# Boot project handoff: the missing consumer is `0x568658` (`processEventLoop`)

**Date:** 2026-10-31
**Target:** GT6 US `BCUS98296` v1.00, `work/bin/EMAIN.elf`, current tree
`3467267` (`runtime: generation lwcond + synchronous host font reads unlock
menu load`), native log `work/hostsync_run.err` (220 s, no bring-up DDS).
**Scope:** read-only guest analysis plus a post-lift pump patch. No generated
tree, no game data, no `third_party`, and no build/run in this pass (the patch
is for the user to apply).

## Verdict

| Question | Finding |
|---|---|
| Is the pending `boot` request (`manager+0x48 = 1`) consumed by the menu worker (tid 35)? | **No.** The worker polls only its own job queue at `arg+0x80..0x88`. In `hostsync_run.err:271885` its queue is empty (`q0 = q1 = 0x7FFECB88`); it never waits on `manager+0x18`. |
| Does the `0x568C94` signal (`0xA21D50(manager+0x18)`) wake anything? | **No live waiter.** `0xA21D50` signals the condvar at `manager+0x18`; the only `0xA21D8C` wait on a `+0x18` object is the destructor `0x6BFD4C`, which belongs to a different class. No `lwcond` wait at `0x7FEF2018` appears in the log. |
| What is the real consumer? | **`0x568658`, the menu manager's `processEventLoop` game-object callback.** It reads `manager+0x48`, and at state 1 calls `0x5FA6C8(system_ctx, &manager+0x50)` -> `0x5FA338`, which opens `<PROJECT_ROOT_DIR>/<name>/<name>.mproject`. |
| How is that callback registered? | During `MGOM.initialize`, `0x56B948` (the cursor loader) calls `0xA14824` with `r4 = "processEventLoop"`, `r5 = OPD 0x14BF800`, `r6 = manager`, `r7 = 0x10000`. OPD `0x14BF800` is `0x568A0C`, which branches to `0x568658`. |
| Why does the native port never call it? | The pdiext **game-object update loop** is not run. The cursor project still loads because `0x56B948` opens it synchronously; the registered `processEventLoop` callback is never pumped afterwards. |
| What is the smallest correct fix? | Capture the manager at `0x568C94` and call the real `0x568658` state machine from the existing menu-worker loop `0xA12170`, once per iteration while the request is pending. This is the real registered consumer and the real loader; it does not write `manager+0x48` or synthesize any state. |

## Measured trace (`work/hostsync_run.err`)

```text
271833  [GT6] menu worker prepare holder=0x0159B990 obj=0x7FFECB00 flag=0
271884  [thread] entry=0x014E0088 arg=0x7FFECB00 tid=35
271885  [GT6] menu worker entry arg=0x7FFECB00 keep=1 q0=0x7FFECB88 q1=0x7FFECB88 q2=0
...
323851  [GT6] menu project request obj=0x7FEF2000 name=0xCFEFED84 ... pending_before=0
323852  [bootui] context_start obj=0x7FEF2000 ... vt=0x0145FC88
323885  [bootui] package_load this=0x7FF9B650 name=0xCFEFEE14
323888  [bootui] file_open arg=0x4036A940 s='/projects/gt6/arcade/arcade.mpackage'
323889  [hostopen] file=0xCFEFE840 path='projects/gt6/arcade/arcade.mpackage'
...
324534  [WAIT] ppu_thread_join(tid=35)
```

Between `323851` and `324534` there is no `project load` for boot and no
`lwcond` wait on `0x7FEF2018`. The worker stays alive and idle; the pending
flag is never read. `MainLoop` then runs `LoadMenuResource`, opens the five
`.mpackage` files, and exits to shutdown.

## The real chain

### 1. Root and manager

`MGOM.setProjectRoot(PROJECT_ROOT_DIR)` (`0x6C4DC0` -> `0x6C4A00`) gets the
menu system context with `0x5EBEBC()` and calls `0x5F0D64(system_ctx, root)`.
`0x5F0D64` stores the root string at **`system_ctx+0x14`**.

`MGOM.initialize()` (`0x6C5424` -> `0x6C5354`) calls `0x5F093C(system_ctx)`,
which allocates the 0x9E0-byte menu manager and stores it at
**`system_ctx+0x48`**. `0x5E6B94(system_ctx)` is the getter for that manager.

`0x568200` (manager base constructor) sets:

```text
manager+0x14  project root string
manager+0x18  lwcond (0xA21E60)
manager+0x48  pending state       = 0
manager+0x4C  cross-thread flag    = 0
manager+0x4D  load-result byte     = 0
manager+0x50  project name string
```

### 2. Cursor load and callback registration

`0x6C5354` reads `manager = 0x5E6B94(system_ctx)` and calls the virtual slot
`[manager vtable + 0x138]`. The derived implementation is `0x5E7DD4`, which
calls `0x56B948(manager)`.

`0x56B948` is the **cursor-specific** loader:

```text
0x56B96C  r4 = 0x104A5E8 "processEventLoop"
0x56B970  r5 = 0x14BF800  (OPD -> 0x568A0C -> 0x568658)
0x56B978  r6 = manager
0x56B980  r7 = 0x10000
0x56B988  r8 = 0
0x56B98C  bl 0xA14824
```

`0xA14824` loads the object's vtable, calls `[vt+8]()` and then calls
`[vt+0xC]()` with `r3 = object`, `r4 = result`, and **`r5..r8` untouched**.
That is the registration call that stores the callback OPD, the manager
argument, and the flags. The link from `0xA14824` to the pdiext
game-object-loop registration is inferred from the forwarded ABI arguments,
not from a symbol.

`0x56B948` also formats `"%s/cursor/cursor"` (0x104A600) and calls
`0x5FA338(loader, base, path, 1, 1)`, which is why cursor assets still load.

### 3. `MGOM.start("boot")` only queues

`0x6C54DC` -> `0x6C5478`:

```text
system_ctx = 0x5EBEBC()
manager    = 0x5E6B94(system_ctx)
0x568C94(manager, name)
```

`0x568C94` (inside the 0x568AFC/0x568200 class block) does only:

```text
copy name -> manager+0x50
manager+0x48 = 1
0xA21D50(manager+0x18)     ; signal lwcond
return
```

It does not open a file.

### 4. The consumer: `0x568658` (`processEventLoop`)

`0x568658` is a six-state machine. `this` is the manager:

| State | Action |
|---:|---|
| 1 | `0x9D3C84`/`0xB98168` cross-thread guard; if foreign, set `manager+0x4C=1`, call `[vtable+0x140]`, then `0x5FA6C8(system_ctx, &manager+0x50)`. |
| 3 | If the load-result byte `manager+0x4D` is set, run the sequence-slot setup `0x5680FC`/`0x5680C0`; set state 5. |
| 5 | `0x5FB9E8(system_ctx)` cleanup/unload, `[vtable+0x144]`, `manager+0x48 = 0`, signal `manager+0x18` again. |

The state-1 loader `0x5FA6C8` formats `"%s/%s/%s.mproject"` (0x1053A20) with
`root = [system_ctx+0x14]`, `name = [manager+0x50]`, and calls
`0x5FA338(system_ctx, base, "<root>/<name>/<name>", 1, 0)`. For boot this is
`/projects/gt6/boot/boot`.

`0x568A0C` is the 4-byte thunk (`b 0x568658`) and OPD `0x14BF800` is its
function descriptor. The state machine is only reachable through that
callback registration; there is no direct `bl` to `0x568658` anywhere in the
image.

## Why the worker is not the consumer

The menu worker is a generic job queue:

```text
0xA122D4 -> 0xA12170
arg+0x80  queue head
arg+0x84  queue tail/word
arg+0x88  queue word
arg+0x8C  job
arg+0x94  keep-alive byte
0xA186F4(arg+0x80)   non-blocking "queue non-empty"
0xA1862C(...)        pop job
```

The worker never reads `manager+0x48`, never calls `0xA21D8C`, and its queue
is empty in the measured run (`q0 == q1`). Fixing the lwcond generation alone
cannot wake it for this request because it is not waiting on the manager
condvar.

The `manager+0x18` signal is for the **game-object loop waiter** that the
native port does not run. This is why the new lwcond is correct but the boot
project still does not load.

## Smallest correct fix (patch)

`patches/gt6-menu-project-pump.patch`:

1. `gt6/src/stubs.cpp`
   - captures `manager` in `gt6_menu_project_request` (the `0x568C94` hook);
   - adds `gt6_menu_project_tick(ctx, worker_arg)`, which checks
     `worker_arg+0x94 != 0`, reads `manager+0x48`, and calls the real
     `func_00568658(ctx)` with `r3 = manager`, saving/restoring `*ctx`;
   - clears the captured manager when the state reaches 0.
2. `tools/apply_gt6_post_lift.py`
   - injects `gt6_menu_project_tick(ctx, (uint32_t)ctx->gpr[25]);` at
     `loc_00A121AC` in `func_00A12170` (top of the worker loop), idempotently.
3. `tools/post_lift_fixes.py`
   - fails the relift if the pump call disappears.

Apply and run the post-lift injector; generated files are not committed:

```powershell
git apply patches\gt6-menu-project-pump.patch
python tools\apply_gt6_post_lift.py gt6\generated
python tools\post_lift_fixes.py gt6\generated
powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
```

The pump calls the **real** state machine and the **real** loader. It does not
write `manager+0x48`, does not call `0x5FA338` with a hard-coded path, and does
not fake `SET_STATE`.

### Why not call `0x5FA338` directly

`0x5FA338` needs the base/root object and the composed path built by
`0x5FA6C8`. Calling it with a literal `/projects/gt6/boot/boot` would skip the
`manager+0x50`/root composition and the state machine's cross-thread guard and
cleanup. The cursor path is a special-case loader (`0x56B948`); the generic
boot path is the `0x568658` state machine.

## Verification

Run with `GT6_BOOT_TRACE=1 GT6_BOOTUI_TRACE=1 GT6_PFS_TRACE=1`.

1. `[GT6] menu project request obj=0x........ ... pending_before=0` still
   appears.
2. `[GT6] menu pump manager=0x........ state=1` appears within the next worker
   iteration; then `state_after=3`, then states 3 and 5, then state 0.
3. `[GT6] project load this=... base=... name=... '/projects/gt6/boot/boot'`
   appears from `0x5FA338`.
4. The PFS override serves the real extracted files:

   ```text
   projects/gt6/boot/boot.mproject            42624
   projects/gt6/boot/boot.adc                141821
   projects/gt6/boot/gpb/BootProject.gpb      14592
   projects/gt6/boot/US/PresentsRootSCEA.gpb 1760256
   ```

   Accept `JP/PresentsRootSCEA.gpb` only if the extracted tree has it; the US
   title uses the US path.
5. `boot.adc` parses as `ADCH012`; the script reaches `boot_sequence_gt6`,
   `display_sequence_gt6`, and `presents_sequence_common`.
6. `presents_table_scea` changes images `common/JP/scei` (2 s),
   `common/notice` (2 s), `scea/JP/epilepsy` (4 s), then hands off to the
   movie sequence (`play_movie`/PAMF).
7. Real frame percentage becomes non-zero and the legal notice is visible.

If step 2 runs but step 3 never appears, the state machine returned early
(check `manager+0x48` and the name string at `manager+0x50`). If step 3
appears but step 4 does not, the MPRJ open or the PFS path is the next bug,
not this handoff.

## Unproven / risks

- The `0xA14824` -> pdiext game-object registration is inferred from the
  ABI-forwarded arguments (`r5=0x14BF800`, `r6=manager`, `r7=0x10000`); no
  runtime probe has observed the stored callback.
- `0x568658` has no static xref; it is only reachable through the registered
  OPD. This is consistent with a callback, but it means the exact engine loop
  that invokes it is not identified by a symbol.
- The pump runs the state machine on the menu worker thread. The state
  machine has an explicit cross-thread guard (`0xB98168`/`manager+0x4C`), so
  this is supported by design, but the original game-object loop thread is
  not proven to be tid 35.
- State 5 (`0x5FB9E8`) is inferred to be old-project cleanup. If it is
  actually activation, pumping to state 0 may unload the project; the
  verification log will show it immediately.
- The keep-byte check (`worker_arg+0x94`) prevents pumping after the worker is
  told to shut down, but the captured manager is not invalidated by
  `MGOM.finalize`; a stale pointer is still possible if finalize runs while
  the keep byte is 1.
- No build and no `gt6.exe` run were performed in this pass.
