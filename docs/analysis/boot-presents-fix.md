# Boot/presents gate: `MGOM` construction and the pending `boot` request

**Date:** 2026-10-31
**Target:** GT6 US `BCUS98296` v1.00, `work/bin/EMAIN.elf`, extracted
`work/gt6_vol`, native logs `work/size_run.err` and `work/bootui2_run.err`.
**Scope:** read-only analysis plus additive `gt6/src/stubs.cpp` probes and an
idempotent `tools/apply_gt6_post_lift.py` hook. No generated file, no
`third_party`, no `rsx_d3d12_backend.c`, no game data, and no build/`gt6.exe`
run was performed. `third_party/PDTools` and `GTAdhocToolchain` were not read
or used.

> **Decisive update (2026-10-31, `work/bootui3_run.err`):** the current probe
> build reaches the script VM, then logs 16 identical
> `[bootui] NULL value_dispatch r3=0 ... lr=0x009E2944 tid=1` lines and a
> `HOTREAD8` at `0x009E911C`. `0x009E2944` is **not** `ATTRIBUTE_EVAL start`;
> it is the return site inside `func_009E2914`, a vector/container clear loop
> at `this+0x4c`. The nulls are 16 null `hValue*` elements in that vector. The
> `MGOM` constructor/class-registration path is still the prime suspect, but
> this probe does not prove `MGOM` itself is the null. See §0.3-0.5 for the
> constructor addresses, the checks that are missing, and the next probe.
> `MenuClassDefine` is absent from `bootui3_run.err`, so the `execBoot` branch
> analysis below applies only to the older `size_run.err` build.

## 0. Verdict

| Question | Finding |
|---|---|
| Does `main.adc` call the boot/presents functions directly? | **No.** It calls `bootstrap_phase1_module.execBoot` (code `0xD122F`); `execBoot` calls `initModules`, `initApp`, `initArgs`, `initMenuSystem`, then `main.MGOM.start("boot")` (code `0x1CCA2`). `display_sequence_gt6` / `presents_sequence_common` live only in `boot.adc`; `main.adc`'s 6,412-symbol table does not contain either name. |
| Does the native VM execute `execBoot`? | **Yes.** `MainLoop` is called after `execBoot` in the same TOP frame (`0xD143C`); `MainLoop` is the only caller of `LoadMenuResource`, which is the only script containing `loadPackage`. Native logs show the `loadPackage` builtin (`0x5F7D9C`) being called, so `execBoot` returned and `MainLoop` ran. |
| Does the script VM drop the presents/font calls? | **No dropped CALL is proven.** `main.adc` has no such CALL to drop; the missing event is the `boot.adc` project load. The VM's CALL path (`0x9EEA88` -> `0x9F0748` -> `0x9B0918` -> `0x9C625C` -> `0xDFA51C`) reaches real code, including `loadPackage`. |
| Why are no `K/KG`, `K/LH`, `K/IE`, `K/WD` or font keys opened? | **The pending project request is never consumed.** `MGOM.start("boot")` (`0x6C54DC` -> `0x6C5478` -> `0x568C94`) only stores the project name at `manager+0x50` and sets `manager+0x48 = 1`. It does not open a file. The engine update that should observe that pending flag and call the project loader (`0x5FA338` -> `0x5F0424`) is not proven to run before `MainLoop`. |
| Did the menu worker thread exit prematurely? | **No — hypothesis rejected.** `work/size_run.err:263193-263199` creates thread 35 (`vyENO`, arg `0x7FFECB00`), but the join/exit is at lines `289338-289355`, not immediately after start. The worker is alive for the whole run; its `arg+0x94` keep byte is therefore 1, not 0. Do not add a keep-alive write. |
| Is a presents/font load behind a missing ADCH builtin/HLE? | **No missing builtin is proven.** `0x5F7D9C` (`loadPackage`), `0x6C54DC`/`0x6C5478` (`MGOM.start`), `0x6C4DC0`/`0x6C4A00` (`setProjectRoot`), and `0x6C5424`/`0x6C5354` (`initialize`) are real, registered guest code. The missing event is the engine-side consumer of `manager+0x48`. |
| What is the smallest correct step in this pass? | **First close the current `MGOM` constructor/vector gate, then probe the pending request.** The latest run (`work/bootui3_run.err`, 18:31) stalls at `0x9E911C` with 16 `NULL value_dispatch` lines on `tid=1` before `MenuClassDefine`; §0.3-0.5 identify the `main::MGOM` object/vector as the likely first gate (add the `class_registrar` / `mgom_ctor` / `vector_clear` probes there). The probes in section 3 are read-only and cover the **next** gate: worker entry, `MGOM.start`, `setProjectRoot`, the pending setter, and the project loader. No asset is injected and no presents function is called. |
| Secondary bug | `loadPackage` (`0x14C43D8` -> `0x5F7D9C`) dereferences a null package object after `0x9F79A8` fails (`work/size_run.err:289169-289243`). It is a separate null-object bug on the `MainLoop` -> `LoadMenuResource` path. |

> **Current-build note (concurrent check):** `work/bootui3_run.err` (18:31)
> contains 16 `[bootui] NULL value_dispatch r3=0 b=0 p=0 lr=0x009E2944 tid=1`
> lines before `MenuClassDefine`, then `HOTREAD8 ... 0x9E911C`. Sections 0.3-0.5
> (added by that check) identify the `main::MGOM` constructor/vector at
> `0x006C55DC` -> `0x006C4A5C` and the vector clear at `0x009E2914` as the
> current first gate. The worker/pending-request probes in section 3 are for the
> **next** gate, after `MGOM` is non-null. Do not merge the two gates into one.

### 0.1 Current probe-build prerequisite: `0x9E911C` with `r11=0`

The latest probe runs, `work/bootui2_run.err` (18:24) and
`work/bootui3_run.err` (18:31), do **not** reach the menu boundary. After the
`[bootui] value_dispatch` stream, `bootui3` logs 16
`[bootui] NULL value_dispatch r3=0 b=0 p=0 lr=0x009E2944 tid=1` lines, then
the wild guest-page commits and:

```text
[GT6] faulted in guest page 0x65760000 (write) -- committed
[GT6] faulted in guest page 0x1C000000 (read) -- committed
...
[HOTREAD8] spinning on 0x00000000 val=0x00 tid=764 guest-fn=0x009E911C
```

`0x9E911C` is the typed-value dispatch thunk:

```text
0x9E911C  lbz  r0,0(r11)          ; opcode from the HValue/bytecode pointer
0x9E9134  slwi r9,r0,5
0x9E9138  slwi r0,r0,3
0x9E913C  subf r9,r0,r9
0x9E9144  add  r9,r9,r10          ; table 0x1487660
0x9E9148  lwz  r11,8(r9)
0x9E914C  lwz  r0,0(r11)
0x9E9150  lwz  r2,4(r11)
0x9E9154  mtctr r0
0x9E9158  bctrl
```

With `r11=0` the `lbz` reads address 0 and the dispatch never advances. This is
a separate VM/HValue bug (the pointer is null on `tid=764`, not the main
script thread). It occurs **before** `MenuClassDefine` in that build, so the
project-handoff probes below cannot be observed there until `r11` is non-null.

It does not invalidate the `size_run.err` trace: in that run the same VM
reached `MenuClassDefine`, `MainLoop`, the worker thread, and the
`loadPackage` chain. The two runs are different builds/paths; both need to be
re-checked after the probes are built.

### 0.2 Hypothesis check for the dropped presents/font calls

| Hypothesis | Verdict |
|---|---|
| Wrong entry frame / `execBoot` never runs | **No.** The TOP frame calls `execBoot` (`0xD122F`); `initMenuSystem` served `MenuClassDefine` (only reachable from `execBoot`); `MainLoop` later called `loadPackage` (only reachable after `execBoot` returns). |
| Missing ADCH builtin / HLE | **No for the boot step.** `MGOM.start`, `MGOM.initialize`, `MGOM.setProjectRoot`, `loadPackage`, and the project/file helpers all have real guest implementations and are reached. `loadPackage` has a separate null-object bug after its open fails. |
| Unresolved/indirect call drops the call | **No.** The VM's CALL path resolves to real code; no unresolved-indirect log is present for `MGOM.start`. |
| The menu worker exits on a zero keep-alive byte | **No (rejected).** Thread 35 is created at `263193`, joined at `289338`, and returns at `289355`. It is alive for the whole run, so the byte is 1. The earlier "immediate exit" reading was wrong: the join/return lines are ~26k log lines later. |
| The project request is queued but its consumer never runs | **Yes, as the measured gap.** `MGOM.start("boot")` sets `manager+0x48=1` and `manager+0x50="boot"`. No project loader (`0x5FA338`) call follows in the logs. The engine update that consumes `manager+0x48` is the missing event. |
| Wrong asset path / missing file | **Not yet.** No `K/KG`/`K/LH` open is attempted, so the path resolver is not the first failure. |

### 0.3 `0x9E2944` is a vector-clear site, not `MGOM.start`

`bootui3_run.err:258265-258280`:

```text
[bootui] NULL value_dispatch r3=0x00000000 b=0x00000000 p=0x00000000 lr=0x009E2944 tid=1
... 16 identical lines ...
```

Disassembly of `func_009E2914` (`0x9E2914`):

```text
0x9E2914  r30 = this + 0x4c
0x9E2924  r31 = [r30 + 4]        ; vector begin
0x9E2928  r0  = [r30 + 8]        ; vector end
0x9E293C  r3  = [r31]            ; element
0x9E2940  bl 0x9E9118            ; -> 0x9E911C
0x9E2944  <-- logged lr
```

So the 16 nulls are elements of a pointer vector at `this+0x50..+0x54`. This is
a **cleanup/clear loop**, not the attribute/method dispatch for
`MGOM.start`. It is consistent with a partially constructed object whose vector
was filled with nulls and then cleared, but it does not by itself prove that
`main::MGOM` is the object.

The next new probe, `[bootui] vector_clear this=... begin=... end=... count=...`,
identifies the object and the exact element count.

### 0.4 `main::MGOM` assignment and constructor

`main.adc` `initMenuSystem`, code `0x1C93A`-`0x1C967`:

```text
1C93A  VARIABLE_EVAL main, menu, MMenuGameObjectManager
1C94D  CALL 0
1C956  VARIABLE_PUSH main, MGOM
1C967  ASSIGN_POP
```

The class is the uppercase `main::menu::MMenuGameObjectManager`.

Class registration and methods:

```text
0x006C4EC0  class registration body (name "MMenuGameObjectManager")
0x006C5064  registration entry; tail-calls 0x006C4EC0
0x006C4F9C  register class with 0xBE2534:
              type/name 0x15DE158
              OPD 0x014CD338 -> 0x006C55DC
0x006C5014  register method "start" -> OPD 0x014CD330 -> 0x006C54DC
0x006C55DC  registered factory/constructor entry
0x006C4A5C  allocation/initializer called by 0x006C55DC:
              allocates 0x108 bytes
              vtable 0x146FCE8
              0x6D52AC, 0xA21E60(0x98), 0xA21E60(0xC8)
              stores the new object through the caller's output slot
```

Both `0x006C4EC0` and `0x006C4A5C` are lifted. The old probe did **not** cover
them, so the question "does the constructor return `this` or null?" was not
measured. The new probes log:

```text
[bootui] class_registrar r3=...
[bootui] class_register_impl this=...
[bootui] mgom_ctor out=...
[bootui] mgom_factory this=...
[bootui] vector_clear this=... begin=... end=... count=...
```

The §3 patch implements the same read-only points with the `[GT6] MGOM class
register` / `MGOM factory` / `MGOM ctor` / `MGOM vector clear` prefixes.

Interpretation:

- `class_registrar`/`class_register_impl` absent before line 250 -> the
  `MENU::MMenuGameObjectManager` class table was not built; `CALL 0` cannot
  construct `MGOM`.
- `mgom_ctor out=...` fires but the output slot remains 0 -> `0x6C4A5C`'s
  allocation/initialization failed; fix that, not `MGOM.start`.
- `mgom_ctor` fires and `out` becomes nonzero -> `MGOM` is constructed; the
  null vector is another object and the VM hot read remains the next gate.

`initModules()` does have `REQUIRE "menu"` (`main.adc` `0x1C0B1`-`0x1C0C8`)
before `initMenuSystem`, but the script does not check the REQUIRE result. If
the `menu` module's registration did not run, this is the missing module/class,
not a missing boot asset.

### 0.5 Smallest correct fix

Do **not** add a null guard in `0x009E911C` or skip `MGOM.start` on null. A
guard would suppress the crash but leave `MGOM` null, so the boot project,
presents sequence, and legal screen would still never run.

Ordered fix:

1. Rebuild with the new probes and require
   `[bootui] class_registrar` / `class_register_impl` **before**
   `[bootui] mgom_ctor`.
2. If they are absent, invoke the `menu` module class registrar
   (`0x006C5064` -> `0x006C4EC0`) before `main.adc` line 250, or fix the
   `REQUIRE "menu"` failure that should have done it. This is the smallest
   correct patch if the class table is missing.
3. If they run but `mgom_ctor out=` stays 0, fix `0x006C4A5C`'s allocation or
   init return (0x9794E8 / 0x14A94 path) so the output slot receives the
   `0x108`-byte object.
4. Only after `MGOM` is non-null may `MGOM.start("boot")` be considered. The
   next gate is then the pending project consumer described in §2.3.

Consequence of a null guard: the VM stops faulting, but `MGOM` remains null and
`MGOM.start("boot")` cannot queue the boot project. That is a diagnostic
bring-up fallback only, not a fix.



## 1. Script-side trace

### 1.1 `main.adc`

`work/gt6_vol/scripts/gt6/main.adc` is `ADCH012`, 857,518 bytes, 6,412
symbols. TOP is `scripts/gt6/Application.ad`, 5,564 instructions:

```text
0x1BD15  TOP
0xD1226  TRY_CATCH 5479
0xD122F  VARIABLE_EVAL bootstrap_phase1_module, execBoot, ... idx=1583
0xD1241  CALL 0
...
0xD143C  VARIABLE_EVAL MainLoop, MainLoop, ... idx=1587
0xD144D  CALL 0
```

`execBoot` (code `0x1CBD3`, source line 280) is:

```text
0x1CBD3  initModules()
0x1CBF0  initApp()
0x1CC0D  pdistd.SetFileSystemOptionInt64("/", "PreCopyHddFreeSizeLimit", ...)
0x1CC4A  initArgs()
0x1CC67  initMenuSystem()
0x1CC86  main.MGOM.start("boot")
```

`initMenuSystem` (code `0x1C5A0`) sets `PROJECT_ROOT_DIR`/`PRODUCT_ROOT_DIR`,
`REQUIRE /script/MenuClassDefine` (`0x1C80C`), calls `LangUtil.load`
(`0x1CA40`), `MGOM.initialize()` (`0x1CA61`), and builds `ContextMain`/`1P`/`2P`.

`GameSequence` defaults are `current_project = "boot"` and
`current_sequence = MENU` (`0x8E59D`..`0x8E61F`). `MainLoop` (code `0xD0AB9`)
therefore calls `LoadMenuResource()` (`0xD0C3E`) and then
`MGOM.start(GameSequence.getCurrentProject())` (`0xD0E33`).

`main.adc`'s 6,412-symbol table does **not** contain `display_sequence_gt6`
or `presents_sequence_common`; both names exist only in `boot.adc`. A call to
either from `main.adc` is impossible, so the missing screen is a missing
`boot.adc` project load, not a dropped CALL in the main script.

### 1.2 `boot.adc`

`work/gt6_vol/projects/gt6/boot/boot.adc` is `ADCH012`, 141,821 bytes,
1,682 symbols. The sequence is real and is not the first thing `main.adc`
calls:

| Function | Code | Key body |
|---|---:|---|
| `boot_sequence_gt6` | `0x186E5` | `boot_sequence_common(context, "gt6")` |
| `display_sequence_gt6` | `0x1875F` | first call `presents_sequence_common(context)` at `0x18798` |
| `presents_sequence_common` | `0x16012` | `PresentsRoot.open`, loop `changeImage(path)`, `Thread.Sleep(sec)` |
| `presents_table_scea` | `0x15E9F` | `common/JP/scei` 2 s, `common/notice` 2 s, `scea/JP/epilepsy` 4 s |

The actual project open is therefore `MGOM.start("boot")`, not a direct
`display_sequence_gt6` call. Do not shortcut to the presents functions: they
read `boot_state` initialized by `boot_sequence_common`.

## 2. Native-side trace

### 2.1 What the native log proves

`work/size_run.err`:

```text
774    [GT6] script override: serving decrypted /scripts/gt6/main.adc (857518 bytes)
257989 [GT6] pfs override: serving plaintext products/gt6/script/MenuClassDefine.adc (12464 bytes, ...)
261156 [GT6] pfs override: serving plaintext products/gt6/script/Prototypes.mwidget (5827 bytes, ...)
263202 [GT6] pfs override: serving plaintext projects/gt6/cursor/cursor.mproject (46637 bytes, ...)
277371 [GT6] pfs override: serving plaintext projects/gt6/cursor/cursor.adc (40290 bytes, ...)
289169 [null-write] guest wrote32 0x0 to 0x00000004 (NULL+0x4) by guest-fn=0x006CC5D0
289194 [GSTACK:nw] chain: func_005F7D9C+0x74 func_00DFA51C+0x1CC
         func_009C625C+0x64 func_009B0918+0x1A8 func_009F0748+0xDC
         func_009EEA88+0x1B8 func_00987884+0x64 func_00987A2C+0x364
         func_009881F4+0x8 func_009CC208+0x1A0 func_009CD798+0x5B0
         func_009CDF00+0x10 func_009A7654+0x6C func_00013830+0xF8
         func_0001096C+0x58 func_00010338+0x184
```

The chain is the boot-script VM (`0x9CC208` -> `0x9CD798` -> `0x9A7654` ->
`0x13830`) executing a `CALL` instruction (`0x9EEA88` -> `0x9F0748` ->
`0x9B0918` -> `0x9C625C` -> `0xDFA51C`) that resolves to
`0x5F7D9C` (`loadPackage`). `loadPackage` exists only in `main.adc`, in
`LoadMenuResource` (code `0xD066C`), which is called only by `MainLoop`
(`0xD0C3E`). This is the proof that `execBoot` completed and `MainLoop` ran.

Oracle order for comparison: fonts at `26.909`-`26.934`, `MenuClassDefine`
`27.158`, `Prototypes` `27.177`, `cursor.mproject` `27.195`, `cursor.adc`
`27.213`, `W2` `27.225`, then **`K/KG` `27.240`, `K/LH` `27.259`, `K/IE`
`27.328`, `K/WD` `27.445`**. The native run reaches the same `W2` point and
then stops; the next step in the real engine is the boot project, which never
happens because its pending request is not consumed.

### 2.2 The menu worker thread is alive (corrected reading)

The thread is created during `MGOM.initialize()`:

```text
main.adc 0x1CA61  MGOM.initialize
 -> 0x6C5424  (script method wrapper; name "initialize")
 -> 0x6C5354
 -> 0x5F093C  menu context start
      allocates a 0x9E0-byte menu object
      stores it at thread_context+0x48
      registers the "Work"/"wheel" callbacks
 -> 0x6CD8F8  menu_after_start
 -> 0xA11F20  create_thread
      writes 1 to [*0x159B990 + 0x94]
      sys_ppu_thread_create(name=0x3519D68C, entry=0x14E0088, ...)
```

`0x14E0088` resolves to code `0xA122D4` -> `0xA12170`. The entry is:

```c
do {
    if (0xA186F4(arg + 0x80) != 0) {
        if (*(uint8_t *)(arg + 0x94) == 0) {
            /* drain queues */
            return;                 /* shutdown path */
        }
        /* service/cleanup */
    }
    job = 0xA1862C(arg + 0x80, arg + 0x84, arg + 0x88);
    if (job) { run job; }
} while (1);
```

The native log shows the thread start and, ~26k lines later, the shutdown:

```text
263193 [SYS] sys_ppu_thread_create tid=35 name="vyENO" entry=0x014E0898
       arg=0x7FFE6960 stack=0x4000 prio=2619 flags=0x1
263198 [THREAD 35] host thread started, entry=0x014E0898 hosttid=19168
263199 [thread] A304D0 thread=0x7FFE6960 entry=0x014E0088 arg=0x7FFECB00 tid=35
...
289338 [WAIT] ppu_thread_join(tid=35)
289353 [SYS] sys_ppu_thread_exit(tid=35 status=0)
289355 [THREAD 35] entry RETURNED (r3=0x0) -- thread finished
```

**The worker is alive from 263199 to 289338.** The keep-alive byte at
`arg+0x94` is 1, as `0xA11F20` intended. It is not the gate. The earlier
"worker exits immediately" reading was a misread of the join/return lines.
The join at 289338 comes after the `loadPackage` null writes at 289169: the
script ran for roughly 2.6 s with the boot request pending, then the main
teardown joined the still-idle worker.

What the worker is doing is not visible in the log: it waits on its
`arg+0x80..0x88` queue (a lock-free work queue) and never sees the manager's
`+0x48` pending flag. The worker arg `0x7FFECB00` may be the thread-side
control block or the manager itself; the new `menu worker prepare holder/obj`
line and the pending setter's `obj` line decide that. If `arg` is the manager,
the queue words are its adjacent fields; if not, the worker is waiting on a
different object. The exact handoff between `manager+0x48` and the worker
queue is the missing event.

### 2.3 `MGOM.start("boot")` only queues

`MGOM.start` wrapper `0x6C54DC` -> `0x6C5478`:

```text
0x6C5478:
  context = 0x5EBEBC(...)
  manager = [context+0x48]
  0x568C94(manager, project_name)
```

`0x568C94` (native `menu_start_project`) does **not** open a file:

```text
0x568C94:
  name_copy(manager+0x50, project_name)
  manager+0x48 = 1                 ; pending
  ...
  return
```

The actual `boot.mproject` / `boot.adc` open must be done by the engine update
that consumes `manager+0x48`, then calls the project loader `0x5FA338`
(append `.mproject`, `0x1053A10`) and `0x5F0424`. That is why the native log
can show the `MGOM.start` request and no `K/KG`/`K/LH` open.

`MGOM.setProjectRoot` wrapper `0x6C4DC0` -> `0x6C4A00` -> `0x5F0D64` stores the
root at `manager+0x14`. If the consumer runs, the project path is composed
from that root and the pending name.

## 3. The probe patch

### 3.1 `gt6/src/stubs.cpp` (additive, read-only)

The new code is appended before `gt6_hle_overrides()`:

```c
static int gt6_boot_trace(void);          /* GT6_BOOT_TRACE=1 */
static int gt6_guest_ptr_ok(uint32_t ea);

extern "C" void gt6_menu_worker_entry(ppu_context* ctx)
{
    /* logs arg, arg+0x94 keep byte, arg+0x80..0x88 queue words */
}

extern "C" void gt6_menu_worker_prepare(ppu_context* ctx)
{
    /* logs holder=0x159B990, *holder, and the keep byte before create */
}

extern "C" void gt6_mgom_class_probe(ppu_context* ctx);   /* class register */
extern "C" void gt6_mgom_factory_probe(ppu_context* ctx); /* 0x6C55DC factory */
extern "C" void gt6_mgom_ctor_probe(ppu_context* ctx);    /* 0x6C4A5C ctor */
extern "C" void gt6_mgom_vector_clear_probe(ppu_context* ctx); /* 0x9E2914 */
extern "C" void gt6_mgom_start_probe(ppu_context* ctx);   /* MGOM.start name */
extern "C" void gt6_mgom_setroot_probe(ppu_context* ctx); /* MGOM.setProjectRoot */
extern "C" void gt6_menu_project_request(ppu_context* ctx);/* 0x568C94 pending */
extern "C" void gt6_project_load_probe(ppu_context* ctx); /* 0x5FA338 loader */
```

None of these writes guest memory or calls guest code. The probes are gated by
`GT6_BOOT_TRACE=1`. The `class registrar` / `MGOM factory` / `MGOM ctor` /
`MGOM vector clear` probes are the current-build gate from §0.4; the
`MGOM.start` / pending / project-load probes are the next gate.

### 3.2 `tools/apply_gt6_post_lift.py`

`add_boot_presents_hooks()` adds the calls after `PPU_MM_SNAP`:

| File | Guest function | Hook |
|---|---|---|
| `ppu_recomp_015.cpp` | `func_006C4EC0` / `func_006C5064` (class register) | `gt6_mgom_class_probe(ctx)` |
| `ppu_recomp_015.cpp` | `func_006C55DC` (class factory) | `gt6_mgom_factory_probe(ctx)` |
| `ppu_recomp_015.cpp` | `func_006C4A5C` (0x108-byte ctor) | `gt6_mgom_ctor_probe(ctx)` |
| `ppu_recomp_022.cpp` | `func_009E2914` (vector clear) | `gt6_mgom_vector_clear_probe(ctx)` |
| `ppu_recomp_023.cpp` | `func_00A11F20` (thread create helper) | `gt6_menu_worker_prepare(ctx)` |
| `ppu_recomp_023.cpp` | `func_00A122D4` (worker entry thunk) | `gt6_menu_worker_entry(ctx)` |
| `ppu_recomp_015.cpp` | `func_006C54DC` (`MGOM.start` wrapper) | `gt6_mgom_start_probe(ctx)` |
| `ppu_recomp_015.cpp` | `func_006C4DC0` (`MGOM.setProjectRoot` wrapper) | `gt6_mgom_setroot_probe(ctx)` |
| `ppu_recomp_012.cpp` | `func_00568C94` (pending-project setter) | `gt6_menu_project_request(ctx)` |
| `ppu_recomp_013.cpp` | `func_005FA338` (project loader) | `gt6_project_load_probe(ctx)` |

The function is idempotent (verified on a scratch copy: first pass 5 files,
second pass 0 changes) and is called from `main()` before the FileDevice
patch. It is a tool-side post-lift hook, so no generated file is committed.
`tools/post_lift_fixes.py` now fails the relift if either
`gt6_menu_worker_entry(ctx)` or `gt6_menu_worker_prepare(ctx)` is missing, so
the probes cannot silently disappear on a later lift.

### 3.3 What this does not do

- It does not write any guest byte (no keep-alive write, no forced flag).
- It does not call `display_sequence_gt6` or `presents_sequence_common`.
- It does not create, alias, or inject `boot.mproject`, `boot.adc`,
  `BootProject.gpb`, `PresentsRootSCEA.gpb`, or any font.
- It does not change `gt6/generated`, `third_party`, or the D3D12 backend.
- It does not touch the separate `loadPackage` null-object bug.
- It does not prove which engine update consumes `manager+0x48`; the probes
  identify the handoff in the next run. If the worker stays idle and
  `[bootui] project_load` never appears, the next owner is the native engine
  update/frame loop, not the presents functions.

## 4. Expected native log lines

The current generated tree also contains the `GT6_BOOTUI_TRACE` probes from
`tools/gt6_boot_ui_probe.py` (`[bootui] MGOM.start`, `context_start`,
`project_load`, `package_load`, `file_open`). Those are complementary; run
with both `GT6_BOOT_TRACE=1` and `GT6_BOOTUI_TRACE=1`.

With the probes built:

```text
[GT6] MGOM class register r3=0x........ r4=0x........ r5=0x........ r6=0x........
[GT6] MGOM factory r3=0x........ r4=0x........ r5=0x........ r6=0x........
[GT6] MGOM ctor out=0x........ [out]=0x........ r4=0x........ r5=0x........
[GT6] MGOM vector clear this=0x........ begin=0x........ end=0x........ count=... first=0x........
[GT6] menu worker prepare holder=0x........ obj=0x7FFECB00 flag=0
[GT6] menu worker entry arg=0x7FFECB00 keep=1 q0=0x........ q1=0x........ q2=0x........
[GT6] MGOM.setProjectRoot arg=0x........ '/projects/gt6'
[GT6] MGOM.start name=0x........ 'boot'
[GT6] menu project request obj=0x........ name=0x........ word0=0x........ word1=0x........ pending_before=0 (0x568C94 sets +0x48=1 next)
[GT6] project load this=0x........ base=0x........ '.../boot' name=0x........ 'boot'
```

The `keep=1` is the corrected expectation; if it is `0` on a future run, the
worker's lifetime/exit hypothesis becomes live again. `pending_before` is the
value **before** `0x568C94` writes 1.

The decisive probe is the existing `[bootui] project_load` line from
`0x5FA338`, followed by the real boot asset opens. Before the PFS override
line, the cache layer should log the bdmark key open (the path is
`/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS_bdmark/K/<key>`):

```text
[pfscache] open '.../PDIPFS_bdmark/K/KG' flags=0x442 -> fd=...
[pfscache] open '.../PDIPFS_bdmark/K/LH' flags=0x442 -> fd=...
[pfscache] open '.../PDIPFS_bdmark/K/IE' flags=0x442 -> fd=...
[pfscache] open '.../PDIPFS_bdmark/K/WD' flags=0x442 -> fd=...
[pfscache] open '.../PDIPFS_bdmark/K/4M' flags=0x442 -> fd=...
[pfscache] open '.../PDIPFS_bdmark/K/RP' flags=0x442 -> fd=...
```

Then the existing generic PFS override must serve the real extracted files
(sizes are the uncompressed sizes; the `reader` value is runtime-dependent):

```text
[GT6] pfs override: serving plaintext projects/gt6/boot/boot.mproject (42624 bytes, reader=0x........)
[GT6] pfs override: serving plaintext projects/gt6/boot/boot.adc (141821 bytes, reader=0x........)
[GT6] pfs override: serving plaintext projects/gt6/boot/gpb/BootProject.gpb (14592 bytes, reader=0x........)
[GT6] pfs override: serving plaintext projects/gt6/boot/US/PresentsRootSCEA.gpb (1760256 bytes, reader=0x........)
```

The oracle's key order also includes the font/rtext keys; after the project
consumer runs, the font manager should request these. Accept either the JP or
US PresentsRoot path, but the bytes must be the real extracted file:

```text
K/4M  font/vec/IwataUD_M_latin.vec   69040
K/5I  font/vec/IwataUD_M_JP.vec      1923568
K/V4  font/vec/IwataUD_B_latin.vec   60368
K/HP  font/vec/IwataUD_B_JP.vec      1883168
K/TY  font/vec/IwataUD_E_latin.vec   59696
K/G4  font/vec/IwataUD_L_latin.vec   69536
K/CP  font/vec/GTfcItalic.vec        16224
K/6L  font/vec/GTMeterNum.vec        10720
K/9N  font/vec/GThk.vec              47904
K/D8  font/vec/FT_B.vec              36864
K/MR  font/vec/7seg.vec              10512
K/R2  font/vec/fontset_JP.txt          695
K/2F  font/logo/menu_imagefont.bin   229891
K/RP  rtext/common/US.rt2            352856
```

The latest probe build already requests `/font/vec/fontset_JP.txt` and
`/font/logo/menu_imagefont.bin` early (`work/bootui2_run.err:611-645`), so the
font path is not completely absent in that build. The vector-font set and the
boot assets are still downstream of the project consumer; do not use the two
early requests as evidence that the full font preload ran.

`K/KG` (42,624), `K/LH` (141,821), `K/IE` (14,592), and `K/WD` (1,760,256
uncompressed / 69,530 compressed) must appear exactly as the extracted tree
sizes. Do not accept a 0-byte or synthesized file as evidence.

## 5. Verification plan

0. Current first gate (`work/bootui3_run.err`): the `MGOM class register` /
   `MGOM factory` / `MGOM ctor` / `MGOM vector clear` probes in section 3 are
   included. Require class registration before the factory, and require
   `MGOM ctor [out]` to become nonzero before `main.adc` line 250 (the entry
   probe logs the pre-call slot; add a post-call wrapper if the value is still
   ambiguous). If `MGOM` is null, stop: the worker/pending-request probes below
   are not reachable. Do not add a null guard at `0x9E911C`.
1. Apply the post-lift probes and rebuild through the normal
   `scripts/relift-gt6.ps1` / `scripts/build-gt6.ps1` path.
2. Run headless for 240-300 s with `GT6_BOOT_TRACE=1`,
   `GT6_BOOTUI_TRACE=1`, and `GT6_PFS_TRACE=1`.
3. First gate: `[GT6] menu worker entry ... keep=1` and thread 35 stays alive
   until the shutdown join. If `keep=0`, the worker-exit hypothesis is live;
   otherwise the worker is idle and the handoff is elsewhere.
4. Second gate: `MGOM.start name='boot'`, `MGOM.setProjectRoot
   '/projects/gt6'`, and `menu project request ... 'boot'` must appear
   **before** the `K/KG` open. The `pending_before` value is the state before
   `0x568C94` sets `+0x48=1`.
5. Third gate: `[GT6] project load ...` (or the equivalent
   `[bootui] project_load ...`) from `0x5FA338` must appear, with
   `base`/`name` containing `boot` (the loader appends `.mproject`). If it
   never appears, the project consumer is missing; the next owner is the
   native engine update/frame loop, not the presents functions.
6. Fourth gate: the four boot assets above must be served by the PFS override,
   and `boot.adc` must be parsed as `ADCH012`.
7. Fifth gate: `BootProject.boot` / `boot_sequence_common` /
   `display_sequence_gt6` / `PresentsRoot.open` probe lines must appear, then
   the font/rtext keys.
8. If the worker stays idle and no `project_load` appears, dump the manager
   object fields (`+0x48`, `+0x50`) and the worker queue (`arg+0x80..0x88`)
   with `GT6_BOOT_TRACE=1`. Do not add a direct presents call.
9. Keep the W2 source-bind work separate. W2 is loaded before the boot
   project and its zero cache is a different blocker; it must not be credited
   as a presents fix.

## 6. Secondary: the `loadPackage` null object

`MainLoop` -> `LoadMenuResource` calls `manager.loadPackage(path)` for
`/arcade/arcade`, `/option/option`, `/gtmode/gtmode`, `/garage/garage`, and
`/gtauto/gtauto`. The builtin `0x14C43D8` -> `0x5F7D9C` builds
`path + ".mpackage"` and calls `0x9F79A8` / `0x9F73A0` / `0x9F8E40`. In the
measured run the resulting package object is null; `0x5F7D9C` then calls
`0x6CC5D0(null)`, which writes the null page. The runtime drops those writes,
so the script continues, but this is not correct guest behaviour (on hardware
it would fault).

Evidence: `work/size_run.err:289169-289243`, chain
`0x5F7D9C -> 0xDFA51C -> 0x9C625C -> 0x9B0918 -> 0x9F0748 -> 0x9EEA88`,
and the regenerated `[bootui]` logs in the current generated tree.

This is **not** the boot/presents gate: it happens after `MainLoop` starts,
while the boot project request is already pending. After the project consumer
is fixed, if the package path is still empty/null, add a guarded return in the
`0x5F7D9C` wrapper (log the path and skip the `0x6CC5D0` null dereference)
rather than synthesizing a package. The package files themselves are present
in `work/gt6_vol` (for example `projects/gt6/arcade/arcade.mpackage`, 87,316
bytes), so an absent disc asset is not the explanation.

## 7. Address index

| Address | Meaning |
|---|---|
| `0x1096C` / `0x13830` | `main` / boot-script loader |
| `0x1CBD3` / `0x1C037` | `main.adc` `execBoot` / `initModules` |
| `0x1CA61` | `main.adc` `MGOM.initialize()` |
| `0x1CCA2` | `main.adc` `MGOM.start("boot")` |
| `0xD0C3E` / `0xD066C` | `MainLoop` -> `LoadMenuResource` / `LoadMenuResource` |
| `0x6C4EC0` / `0x6C5064` | `MMenuGameObjectManager` class registration |
| `0x6C55DC` | registered factory/constructor entry |
| `0x6C4A5C` | 0x108-byte `MMenuGameObjectManager` allocation/initializer |
| `0x9E2914` / `0x9E911C` | vector clear / typed-value dispatch (null-vector site) |
| `0x6C5424` | `MGOM.initialize` script wrapper (`0x14CD328`) |
| `0x6C5354` | `MGOM.initialize` implementation |
| `0x5F093C` | menu context start / worker setup |
| `0x6CD8F8` | menu worker thread creation (`0xA11F20`) |
| `0xA11F20` | create thread; writes keep-alive at `[*0x159B990+0x94]` |
| `0x14E0088` | menu worker entry OPD -> code `0xA122D4` -> `0xA12170` |
| `0xA122D4` | worker entry thunk |
| `0xA12170` | worker loop; checks `arg+0x94`, pops `arg+0x80..0x88` |
| `0x6C54DC` / `0x6C5478` | `MGOM.start` wrapper / implementation |
| `0x6C5064` / `0x6C4EC0` | `MENU::MMenuGameObjectManager` class registrar entry / body |
| `0x6C4F9C` / `0x6C5014` | class registration (`0xBE2534`) / method `start` registration |
| `0x6C55DC` / `0x6C4A5C` | registered class entry (OPD `0x14CD338`) / allocator+initializer |
| `0x9E2914` / `0x9E2944` | vector-clear loop / return site for the 16 null elements |
| `0x568C94` | pending-project setter: `manager+0x50 = name`, `manager+0x48 = 1` |
| `0x6C4DC0` / `0x6C4A00` | `MGOM.setProjectRoot` wrapper / implementation |
| `0x5F0D64` | store project root at `manager+0x14` |
| `0x5FA338` / `0x5F0424` | project loader (append `.mproject` / open helper) |
| `0x14C43D8` / `0x5F7D9C` | `loadPackage` builtin / implementation |
| `0x9F79A8` / `0x9F73A0` / `0x9F8E40` | `.mpackage` open wrappers / FileStream open |
| `0x6CC5D0` | null-dereference helper called with a null package object |

## 8. Files changed

```text
gt6/src/stubs.cpp                 additive read-only worker/project probes
tools/apply_gt6_post_lift.py      idempotent boot/presents post-lift hooks
tools/post_lift_fixes.py          relift verification for those probes
docs/analysis/boot-presents-fix.md  this report
```

No generated file, game asset, `third_party` file, or backend file was edited
by this change. The post-lift hook is the only path that touches generated
code, and it runs at relift time.

## 9. Limitations

- The probes are **unbuilt and unrun** in this pass (the task forbids a build
  and a `gt6.exe` run). The evidence is the decompiled guest control flow, the
  generated lift, and the measured thread lifetime.
- The latest probe build (`work/bootui2_run.err`) stalls earlier at
  `0x9E911C` with `r11=0`; the project handoff is visible in the
  `work/size_run.err` build. Both paths must be re-checked after the VM
  `r11=0` fault is fixed; the two blockers are independent.
- The exact engine update that consumes `manager+0x48` is not identified. The
  probes decide whether it is the menu worker, another update thread, or a
  missing native frame-loop call.
- The `loadPackage` null object remains a separate bug. Do not use its
  null-page writes as evidence that the boot path ran.

## Opus handoff (2026-10-31, branch `opus/boot-frame`)

**Answer: MGOM is not the null object.** The 16 `NULL value_dispatch` lines
are teardown. They come after the script has already given up.

Evidence (`work/opus_run.err`, 4 runs, `GT6_BOOTUI_TRACE=1 GT6_BOOT_TRACE=1`):
- `[GT6] MGOM class register r3=0x4001CC90 r4=0x4009F080` fires at startup
  (line ~600). Hypothesis A (registration missing) is false.
- The boot result is **nondeterministic between runs**:
  - Runs 1-3: `initApp` (`bootstrap.ad` lines 142-148, 39 instructions) is
    entered (`step_ret st=4 pc=0x40110010`). Its frame never reaches
    `SET_STATE 1`. TOP resumes at the `try { execBoot() }` exit (`JUMP 5490`),
    so `success` is false, `MainLoop` is skipped and `execShutdown` runs. Then
    `0x9E2968` destroys every code object (`vector_clear lr=0x009E297C`), and
    the first one is the 5,564-instruction TOP. Code object `0x401EAE70`
    (10 slots) holds null instruction pointers, which gives the 16 null
    dispatches. Guest pages `0xF8210000`/`0x38210000` are paged in during that
    teardown, and those look like PPC opcodes read as pointers. **Do not guard
    `0x9E911C`**: the run is already dead by then.
  - Run 4: `initApp` finishes. `MenuClassDefine` and `Prototypes.mwidget` are
    served, then `MGOM factory/ctor` fire (hypothesis B: `[out]` is read at
    entry, so 0 is expected there; the object is valid because
    `setProjectRoot` and `start` run on it). `cursor.mproject`/`cursor.adc`
    load. `MGOM.start` (execBoot) -> `menu project request obj=0x7FEFE000`
    sets `+0x48=1`. **No `project load` for boot follows.** `MainLoop` ->
    `LoadMenuResource` -> `loadPackage("/projects/gt6/arcade/arcade.mpackage")`
    opens `PDIPFS_bdmark/K/L4` and `K/L4.fdupm`, but nothing reads the data.
    The package object stays null, and `0x6CC5D0` writes to NULL+4/8/C
    (dropped). The `MainLoop` frame then ends without `SET_STATE`, and `step_ret`
    is never logged for it. TOP falls through to shutdown.
- Common pattern: in both failures a script frame is dropped in the middle of a
  step and no Adhoc exception is raised. That looks like a native fault
  being recovered (null-call "returning with r3 untouched", setjmp guard)
  that unwinds the whole `0x9EEA88` step. The cause is not a script `throw`.

Changes: `tools/gt6_boot_ui_probe.py` adds a per-instruction trace of the frame
loop (`[bootui] ins frame= op= line= st=`; opcode byte = `word0>>24`, line =
`word0&0xFFFFFF`; status 5 run / 4 call / 1 return). `vector_clear` now logs
`lr` and skips empty vectors. Deleted the rejected
`patches/gt6-pfs-source-bind.patch`. `patches/gt6-boot-ui-probe.patch` is
**not** regenerated: regenerate it from a clean relift.

Still broken (first failing addresses):
1. Intermittent: the native call inside `initApp` that drops the frame.
   Candidates are `pdistd::MRandom`, `pdiext::getBetterTime().getBySecond`,
   `getMTInt().toULong`, `GetSystemTimeMicroSecond`, and the `pdiapp::play_id`
   setter. The time-dependent ones are the likely suspects. Next: in a failing
   run, read the last `[bootui] ins ... line=14x` before the TOP `JUMP`.
2. The boot pending flag (`ctx 0x7FEFE000 +0x48`) is never consumed. The menu
   worker (tid 35, arg `0x7FFECB00`, `q0==q1` = empty queue) never wakes. The
   signal in `0x568C94` goes to `ctx+0x18` via `0xA21D50`. Check whether that
   object is the one the worker waits on. Cursor reference loader: `0x56B948`
   (called from `0x5E7DF0`).
3. `loadPackage` (`0x5F7D9C`): `K/L4` (arcade), `K/KZ` (option) and `K/WY`
   (gtmode) are not seeded. Try `python tools\gt6_seed_pfs_cache.py --keys
   K/L4,K/KZ,K/WY,K/7P,K/J4` before the next run.

No frame was produced. Success criterion 1 (boot assets) was **not** reached.

Next command:
    python tools\apply_gt6_post_lift.py gt6\generated
    python tools\gt6_boot_ui_probe.py; git apply patches\gt6-boot-ui-probe.patch
    powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
    $env:GT6_BOOTUI_TRACE="1"; $env:GT6_BOOT_TRACE="1"; .\gt6\build\gt6.exe work\bin\EMAIN.elf 2> work\opus_run.err
    Select-String work\opus_run.err -Pattern "\] ins .*line=14[2-8]|step_ret|MGOM|project load|package_load"
