# GT6 boot-chain analysis — why `main` returns

**Date:** 2026-10-31
**Target:** GT6 US `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Status:** measured on `gt6/build/gt6.exe` plus read-only analysis copies.

This report supersedes the earlier "0x40 init flag" hypothesis. The 0x40 was an
artifact of a hand patch to `func_00A13644`; the real function is a
mutex-protected getter over a global byte, and that byte is **0** during a
normal boot. The real stop is downstream: the boot script is never loaded,
because the game's PFS volume (`GT.VOL`) is never mounted.

---

## 0. TL;DR

1. **`0xA13644` is correct as lifted now.** It locks `0x164AB50`, calls
   `0x3C0E84` (`lbz r3,0x10(r3); blr`) on the global object at `0x164AB80`,
   unlocks and returns the low byte. The only write to `0x164AB90` observed in
   a whole boot is the constructor's zero at `0xE47040`; nothing writes 0x40.
   The fake leaf getter was reading the caller's `r3+0x10` and must stay
   reverted.
2. With the real getter, `main` takes the **flag == 0** path: it calls
   `0x13830("scripts/gt6/main")`, then `0x13BA8` (shutdown), then returns 0.
   `0x13BE8` completes all 15 stages; no init stage is skipped by the runtime.
3. `0x13830` is the **boot-script loader**, not a print. It calls the script
   VM's virtual method `0x009A7654`, which is **synchronous** and returns 0
   without touching `cellFs`/`sys_fs`.
4. The immediate reason it returns 0 is that the built-in loader cannot obtain
   a reader for `scripts/gt6/main.adc`.
5. The upstream reason is a **static-constructor walker bug**: `0x118C8` loses
   its table pointer (`r31`) after the constructor called from `.ctors` slot
   `0x14105D0`. It then walks stack/null memory and never reaches the remaining
   **371 of 722** constructors.
6. One of the skipped constructors is the **PFS path/config initializer** at slot
   `0x141001C` → OPD `0x148E420` → `0x111C8` → `0x110E8`, which builds the
   `"/dev_bdvd/PS3_GAME/USRDIR/GT.VOL"` descriptor at `0x157087C`.
   A control experiment that moves this constructor to the first `.ctors` slot
   makes the descriptor appear (`0x157087C = {6, GT.VOL path, ...}`,
   `0x16A99D4 != 0`) but **GT.VOL still does not open**. So the descriptor is
   necessary but not sufficient: the actual volume mount/open is another
   consumer that is also skipped by the walker abort (or still missing in HLE).
7. `main` returning is therefore a **symptom**, not the intended steady state.
   The CRT then calls `sys_process_exit(0)`; `0x13BA8` has already torn down
   GCM/SPURS/modules and joined the worker threads.

---

## 1. The correction: the init flag is not 0x40

Ground truth from the ELF (`work/bin/EMAIN.elf`):

```
0x00A13644  stdu r1,-0x90(r1)
0x00A13648  mflr r0
0x00A1364C  std  r29,0x78(r1)
0x00A13650  lis  r29,0x165
0x00A13654  std  r28,0x70(r1)
0x00A13658  addi r29,r29,-0x5510   ; r29 = 0x164AAF0
0x00A1365C  std  r0,0xA0(r1)
0x00A13660  addi r28,r29,0x60      ; r28 = 0x164AB50 (mutex)
0x00A13668  mr   r3,r28
0x00A1366C  bl   0xA42DE8          ; lock
0x00A13670  addi r3,r29,0x90       ; r3 = 0x164AB80 (global state object)
0x00A13674  bl   0x3C0E84          ; lbz r3,0x10(r3); blr
0x00A13678  mr   r29,r3
0x00A1367C  mr   r3,r28
0x00A13680  bl   0xA42D3C          ; unlock
0x00A1368C  rldicl r3,r29,0,56     ; low byte
0x00A1369C  blr
```

`0x3C0E84` is the leaf getter. The real flag byte is `0x164AB80 + 0x10 =
0x164AB90`. The page-guard run (`work/boot_analysis/guard_test.log`) logged
exactly one write to that byte in the whole boot:

```
[GUARD] WRITE guest=0x0164AB90 ... guest-fn=0x00E47040  <<< watched addr!
```

`0xE47040` is the state object's constructor, and it writes zero. No code path
writes 0x40. The previously observed "flag=0x40 at step 15" was the fake
getter reading the 17th byte of the caller's leftover `r3` (the HADHOC config
string). It has no meaning.

**Consequence:** the real init flag is 0 throughout boot, so `main` at
`0x109B4` falls through to `0x109B8`:

```
0x109B8  lis  r3,0xFB
0x109BC  addi r3,r3,0xAB8          ; "scripts/gt6/main"
0x109C0  bl   0x13830              ; boot-script loader
0x109C4  bl   0x13BA8              ; shutdown
0x109C8  mr   r3,r31
0x109CC  bl   0xA15B20
0x109DC  ...                        ; static destructor list at 0x16A99D0
```

The `0x109D4` branch (skip loader and shutdown) is the **failure/abort** path,
not the success path. The fake 0x40 patch forced exactly that abort path.

---

## 2. `main`, `0x13BE8`, and the real loop

### 2.1 `main` (`0x1096C`)

```
0x10988  0x13808()                 ; timer/reset
0x10998  0xA15B04()                ; flags at 0x164AC78 (byte 0 = 1, byte 1 = 0)
0x109A4  0x13BE8(&stack_obj, arg)  ; init chain
0x109A8  0xA13644()                ; real global flag
0x109B4  if (flag != 0) goto 0x109D4
0x109B8  0x13830("scripts/gt6/main") ; boot script
0x109C4  0x13BA8()                 ; shutdown
0x109C8  0xA15B20()                ; flags byte 1 = 1
0x109DC  walk list at 0x16A99D0    ; static destructors
0x10A14  return 0
```

`0x13BE8` is an initialization chain, not the game loop. Its stages:

| # | Address | Notes |
|---:|---|---|
| 1 | `0xA503E0` | first arg = `*(obj)` (mode/size) |
| 2 | `0x13E08` | |
| 3 | `0xBE16D0` | |
| 4 | `0xA16734` | |
| 5 | `0xA0B8EC` | |
| 6 | `0x14548` | heap/audio/GCM-related init |
| 7 | `0xA13644` | flag check; 0 → continue |
| 8 | `0x13D44` | language/system check |
| 10 | `0x14450` | static C++ object init (`0x1570E00`) |
| 12 | `0x139AC` | module/VM list load |
| 14 | `0x13FBC` | registers module names `HADHOC/pdistd/pdiext/menu/gtengine/gtmenu/pdiapp` |
| 16 | `0xBE16D0` | |
| 18 | `0x1437C` | system-callback pump (see below) |
| 20 | `0x13DC0` | `0x8C564C` |
| 22 | `0x7DBE10` | static init |
| 24 | `0x13D24` | `0xB3A80C` |

Each odd stage is another `0xA13644` check. With the real getter all checks are
0 and the chain reaches `0x13D24` and returns.

### 2.2 `0x1437C` / `0x14398` is a pump, not the game loop

`0x1437C` is a tail wrapper; `0x14398` contains:

```
loop:
  if (0xA13644() != 0) return;          ; quit flag
  if ([0x1570E18]) call it;
  r = 0xA13424();
  if (r == 0) 0xA3888C();               ; frame/system pump
  if ([0x1570E1C]) call it;
  if (r == 0) goto loop;
```

`0xA13424` walks the list at `0x16B294C` and returns 0 if any registered
callback returns 0; it returns 1 when the list is empty. In this boot the list
is empty, so the pump does one pass and returns. **It is not the main loop.**
Forcing `0xA13424` to return 0 (analysis copy) makes `0xA3888C` spin forever,
which proved the control flow but is not the real game loop.

The main list at `0x109DC` has head **`0x16A99D0`** (verified from
`lis r9,0x16B; lwz r29,-0x6630(r9)`; the hint addresses `0x16AF9D0` /
`0x16B6630` are not the list head). Its nodes have the shape:

```
+0x00 next
+0x04 self / object
+0x08 callback OPD (code,toc)
```

and callbacks are exit/finalizer entries. In this build the registered
callbacks are effectively no-ops: `0x149E4F0` → `0xBE16C8` (`li r3,0; blr`)
and `0x149E5A0` / `0x149E510` → `0x1AA728` (bare `blr`). The sibling lists
`0x16A99D4` and `0x16A99E0` have the same shape and are walked by
`0xF48764` / `0xF487C4`, called from the CRT finalizer path
(`0xA098E4` / `0xA098A4` → `0x9F79F0`). **All three are exit/finalizer lists,
not task queues.** `0x16A99D0` is empty because its registrar (`0x11934`,
`.ctors` index 706) is also skipped by the walker bug (see §4).

---

## 3. The boot-script path (`0x13830`)

### 3.1 What `0x13830` does

Measured/instrumented call graph:

```
main 0x1096C
  -> 0x13830(path="scripts/gt6/main", 0x00FB0AB8)
       -> 0xA13644()                      ; flag == 0
       -> 0x9D3C84(...)                    ; runtime/context setup
       -> 0xB98168(...)                    ; setjmp; rc = 0
       -> manager = *(0x01570D58)          ; non-null, e.g. 0x4001A538
       -> [manager->vtable + 0x120](manager, &path)
            -> 0x009A7654
```

`0x9D3C84` initializes a local context; `0xB98168` is `setjmp` (it saves
r1/r2/r13-r31/LR/CR/FPRs/VRs and returns 0). The virtual call dispatches to
`0x009A7654` (OPD `0x014DBE88`, TOC `0x014ED560`). On a VM exception/error the
setjmp returns non-zero and `0x13830` takes the `0x1396C` error path.

### 3.2 `0x9A7654` is synchronous

```
0x9A7654:
  ctx = 0xBE141C(...)
  r3 = 0x9CC6A4(&stack[0x74])    ; get VM singleton
  r29 = [stack+0x74]
  0x14A94(...)                    ; guard/lock object
  r3 = 0x9CDF00(r29, path, &stack[0x70])
  return r3 & 0xFF
```

`0x9CDF00` is a tiny wrapper around `0x9CD798`:

```
0x9CDF00:
  r3 = 0x9CD798(this, path, &obj)
  return r3 & 0xFF
```

There is no `sys_ppu_thread_create` anywhere in the direct call graph of
`0x9A7654` / `0x9CD798` / `0x9CC208`; the path is synchronous. It is not an
async "queue the boot script" call.

### 3.3 `0x9CC068` is a loader-callback lookup

```
0x9CC068(this, key, obj):
  p = 0x9CBEFC(key)               ; std::map<string, OPD> lookup (strcmp 0xB98A5C)
  ret = 0
  if (p) {
      call [p] with r3 = obj      ; invoke registered loader
      ret = 1
  }
  return ret
```

`0x9CBEFC` is a red-black-tree/string-key lookup. It returns 0 when no handler
is registered for the path.

### 3.4 `0x9CD798`: both branches

```
0x9CD798(this, path, out):
  lock VM
  0x9A73CC(this) / 0x9A74A4(...)   ; VM state checks
  r27 = 1
  if (0x9CC068(this, path, out) != 0) goto 0x9CDEA8   ; handled
  ; ---- fallback built-in loader ----
  0x97BE58 / string ops
  0x9D4F50(path)                     ; path normalization/lookup
  split dir/name/ext; .adc handling
  0x9CD69C(...)                      ; construct HFileReader / stream
  0x9CD410(...)                      ; check 4-byte "ADCH" header
  0x9CC208(...)                      ; execute/parse script
  ; reader at stack+0xB8
  if (reader == 0) goto 0x9CDEEC
  if (reader->vtable[+0x20](reader) == 0) goto 0x9CDEEC
  goto 0x9CDEA8
0x9CDEEC:
  r27 = 0
0x9CDEA8:
  cleanup; return r27
```

Key facts:

* If `0x9CC068` returns **1**, `0x9CD798` jumps to `0x9CDEA8` and returns
  **1** (the registered handler took the path).
* If `0x9CC068` returns **0**, the fallback loader runs. A null reader (at
  `stack+0xB8`) or a false return from the reader's virtual `open`/`read`
  method (vtable slot +0x20) jumps to `0x9CDEEC`, sets `r27 = 0`, and returns
  **0**.
* The measured `0x9A7654` return is **0**, and `r27 = 0` is written only at
  `0x9CDEEC`. Therefore the fallback path ran and failed; it was not handled
  by a registered callback.
* `0x9CD798` itself contains **no** `cellFs`/`sys_fs` import calls. Within 8
  direct-call levels the graph reaches only `sysPrxForUser` mutex/time calls.
  Actual file I/O is behind the `HFileReader` virtual interface. The reader is
  either null or its virtual open returns 0, so no `cellFsOpen`/`sys_fs_open`
  appears at all. (The exact reader pointer was not separately logged; the
  return-0 path at `0x9CDEEC` is measured.)

### 3.5 The `.adc` path and header

The VM knows the `.adc` extension (`0x1095168`) and validates the `ADCH`
header (`0x1095058`; error string at `0x1095170`, "this file is not adhoc
script code. HEADER([%s] != [ADCH])"). It never gets that far because the
reader is null. The target file exists in the extracted volume
(`work/gt6_vol/scripts/gt6/main.adc`, 857,518 bytes) but is not reachable
without `GT.VOL`.

---

## 4. Root cause upstream: the `.ctors` walker aborts

### 4.1 The table

`0x118C8` is the static-constructor walker:

```
r9  = *(r2 - 0x7FB0)      ; r2 = 0x14ED560 -> *(0x14E55B0) = 0x1410B4C
r31 = r9 - 4              ; first slot = 0x1410B48
loop:
  v = *r31
  if (v == 0xFFFFFFFF) done
  r31 -= 4
  opd = v
  code = opd[0], toc = opd[1]
  bctrl
  ... read next *r31
```

The table is `0x1410004..0x1410B48`, walked **downward** from
`0x1410B48`: 722 OPD entries, sentinel `0xFFFFFFFF` at `0x1410000`.

### 4.2 Where it breaks

`PS3_CALLTRACE` (`work/gt6_calltrace.log`, `work/boot_analysis/trace_continue.err`)
shows the walker calling constructors normally down to slot `0x14105D0`
(index 350). The last normal call is:

```
[CALL] -> 0x006BCF30 ... r31=0x014105D0  lr=0x0001190C from=func_000118C8+0x3D0
```

After that constructor returns, the walker's next trace is:

```
[null-read] guest read32 from 0x00000000 by guest-fn=0x000118C8
[null-read] guest read32 from 0x00000004 by guest-fn=0x000118C8
[CALL] -> 0x00000000 ... r31=0xFFFFFFFC
```

The guest `r31` has become 0 instead of `0x14105CC`. The walker then reads
`[0]`/`[4]` (null), calls null, decrements `r31` through uncommitted pages,
and never returns to the table. This is the "static-constructor null calls"
noted in `docs/STATUS.md`; it is not a table data problem (all 722 OPDs are
valid). It is a **callee-saved register corruption** in the lifted code.

The generated walker (`gt6/generated/ppu_recomp_000.cpp`, `func_000118C8`)
keeps the table pointer in `ctx->gpr[31]` across `ps3_indirect_call` and
assumes the callee preserves it. The constructor at slot `0x14105D0`
(`0x6BCF30` → `0x6BCE90` → `0x6BCE20`/`0x6BCC34`) returns with
`ctx->gpr[31] == 0`. The leading explanation is the tail-call/register-restore
chain: the lifted epilogue branches to `0xBE1490`/`0xBE148C` via
`g_trampoline_fn`, and the restore helper reloads `r31` from a frame that no
longer holds the caller's value. This is an inference from the generated code
plus the observed register value; it has not yet been proven instruction by
instruction.

### 4.3 What is skipped

The abort at index 350 skips indices **351..721** (371 constructors),
including:

| Index | Slot | OPD | Code | Purpose |
|---:|---|---|---|---|
| 705 | `0x1410044` | `0x148E548` | `0x11C1C` | `0x11B60` finalizer registrar |
| 706 | `0x1410040` | `0x148E4E0` | `0x11988` | `0x11934` finalizer registrar |
| 715 | `0x141001C` | `0x148E420` | `0x111C8` | **PFS/GT.VOL initializer** |

The PFS initializer:

```
0x111C8 (wrapper: r3=1, r4=-1)
  -> 0x110E8
       0xA16684(0x157087C, 0x14E7718)   ; 0x14E7718 = "/dev_bdvd/PS3_GAME/USRDIR/GT.VOL"
       0xA16D40(0x157087C+8, ..., 0x157087C) ; register in list 0x164ACAC
       insert destructor node at 0x16A99D4
            node+8 = OPD 0x148E5A0 -> 0x11EA8
```

`0xA16684` writes `{6, path}` into the volume object; `0xA16D40` links it into
the global list at `0x164ACAC`.

### 4.4 Measured proof

A throwaway copy of the 11:40 build was frozen at the entry of `0x13830`
(the boot-script loader) by patching its first bytes to `EB FE` (the original
`gt6/build/gt6.exe` was not touched). At that point `GT6_PEEK` reported:

```
[peek] 01570D58: 4001A538 ...        ; script VM object (non-null)
[peek] 016A99D4: 00000000 ...        ; PFS finalizer list empty
[peek] 016A99E0: 00000000 ...        ; other finalizer list empty
[peek] 0157087C: 00000000 ...        ; PFS descriptor absent
[peek] 016A99D0: 00000000 ...        ; main's destructor list empty
```

So the PFS initializer has not run by the time the boot script is requested.
That is why no `GT.VOL` / `PDIPFS` open appears anywhere in the run.

### 4.5 Control experiment: move the PFS initializer early

To separate "walker skipped it" from "this is the only missing piece", the
PFS OPD was swapped with the **first** `.ctors` entry in a throwaway ELF copy
(`work/boot_analysis/EMAIN_pfs_early.elf`; slot `0x1410B48` ↔
`0x141001C`). The walker called the PFS initializer first, before the abort.
At the frozen `0x13830` point:

```
[peek] 0157087C: 00000006 014E7718 0157087C 00FB0CF8 0164AC7C ...
[peek] 016A99D4: 0157089C ...
[peek] 0157089C: 00000000 0157089C 0148E5A0 ...
```

The descriptor now exists (`{6, GT.VOL path, self, "pfsVolumePath"}`) and the
finalizer node is registered. **But `GT.VOL` still does not open, and the
script loader still returns 0.**

Conclusion: the walker abort is a real root cause (it suppresses both the
descriptor and whatever consumes it), but the descriptor alone is not enough.
The actual volume mount/open is a separate consumer that is also absent in the
skipped tail, or it depends on an HLE module that is itself missing. The
next diagnostic is to run all 371 skipped constructors (walker fix) and see
which one reaches `cellFsOpen(GT.VOL)`.

### 4.6 PFS-early log note

`work/boot_analysis/pfs_early.log` / `pfs_early.err` show the PFS-early run
reaching `[init] step25/26` and creating engine threads, but no `GT.VOL` or
`cellFs` open. `work/boot_analysis/pfs_early_peek.err` is the frozen state
above.

---

## 5. CRT exit and worker threads

The CRT path is:

```
0x10230 (_start)
  -> 0x10338 (__libc_start_main-ish; TLS, .ctors via 0x118C8, argv)
       -> main 0x1096C
  -> 0x1027C (libc exit)
       -> 0xB8F3E4 / 0xF74844 / 0xB975A8 / 0xB989A4 / 0xF9A080
            -> sys_process_exit(0)
```

`main` itself calls `0x13BA8` on the flag==0 path. `0x13BA8` runs the shutdown
chain (`0x13D04`, `0x14594`, `0x13DA0`, `0x7DD6E8`, `0x88980C`, `0x7DBDDC`,
`0x14428`, `0x14518`, `0x13DE0`) which tears down GCM/SPURS/modules. That is
where the worker threads are joined. The final `sys_process_exit(0)` is the
guest's explicit exit, not a runtime-set global flag.

`0x13BA8` is reached **only** when the flag is 0. The fake 0x40 patch skipped
it entirely, which is another reason that patch was wrong.

---

## 6. Hypotheses ranked

### H1 — measured, high confidence: `.ctors` walker abort is the upstream gate

The walker aborts at slot `0x14105D0` (index 350) and skips 371 constructors,
including the PFS descriptor at index 715. `0x157087C` and `0x16A99D4` are
zero at `0x13830`. The PFS-early control experiment creates the descriptor but
does not open `GT.VOL`, so the walker skip also suppresses at least one later
PFS consumer/mount step (or that step needs an HLE module that is still
missing).

### H2 — next gate: the actual GT.VOL mount/open

Even with the PFS descriptor present (`EMAIN_pfs_early.elf`), no `cellFsOpen`
for `GT.VOL` occurs. The volume mount/open is a separate consumer of the
descriptor (likely one of the skipped constructors, or a module loaded by the
boot script). Fixing the walker should run all 371 skipped constructors and
reveal it; if not, search the skipped OPDs for `cellFsOpen` callers
(`0xA3E900`, `0xA40C90`, `0xA46D88`, `0xA363DC`, ...).

### H3 — possible: no loader callback registered

`0x9CC068` returned 0 (no registered handler). In a correct boot the engine
may register a script-loader callback in the map; the fallback should still
work once PFS is mounted, but the callback may be the intended fast path. The
map's key/value registration site has not been identified yet.

### H4 — rejected: async boot-script queue

There is no thread creation in the direct call graph, and `0x9A7654` returns
the loader result synchronously. The failure is before the file system, not a
queued job whose worker exits.

### H5 — rejected: init flag 0x40 / wrong getter

The real getter reads 0; the 0x40 was the fake leaf patch. See §1.

---

## 7. Exact next patch/hook

### 7.1 Fix the walker (smallest, safest)

In the generated `func_000118C8`, keep the table index in a **host-side local**
across the indirect call, and write it back to `ctx->gpr[31]` afterwards:

```c
/* before ps3_indirect_call */
uint32_t slot = (uint32_t)ctx->gpr[31];
/* ... code/toc load ... */
ps3_indirect_call(ctx);
ctx->gpr[2] = 0x014ED560;          /* existing TOCFIX */
ctx->gpr[31] = slot;               /* NEW: the walker owns r31 */
```

Equivalent: in the lifter's call emission, reload any nonvolatile guest GPR
that the caller is using live across a call. A runtime-level save/restore of
r14-r31 in `ps3_indirect_call` is a broader workaround, but it can mask other
ABI bugs and should be validated against functions that legitimately return
data in nonvolatile registers.

This is a **generated-code/lifter** change, not a game patch. It must be made
by the lift owner; do not hand-edit `gt6/generated/` as a permanent fix.

### 7.2 Verification sequence

1. Apply the walker fix; rebuild.
2. Run headless with `PS3_FSLOG=1` and `PS3_HLE_TRACE=1`.
3. Confirm the walker reaches slot `0x141001C`; check `0x157087C != 0`,
   `0x16A99D4 != 0`.
4. Confirm `[cellFs] Open` / `sys_fs` for
   `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL`.
5. Confirm `scripts/gt6/main.adc` is opened and the `ADCH` header check passes.
6. Only then expect `0x13830` to block in the script VM and the frame loop to
   start.

### 7.3 Do not

* Do not re-apply the `0xA13644` leaf getter patch.
* Do not add a `0x40` flag hack; 0 is the correct boot value.
* Do not park `sys_process_exit`; the exit is downstream of the real failure.
* Do not skip `0x14105D0` alone; the walker will simply lose `r31` at the next
  constructor. The fix must preserve the walker's pointer across every call.

---

## 8. Risks

1. **The null-call storm has already executed arbitrary guest addresses.** The
   walker calls null repeatedly and walks down through `0xFFFFxxxx`/`0xFFFExxxx`
   pages. Some of those reads/calls may have side effects. Fixing the walker
   may expose a different, cleaner failure or a new crash.
2. **371 constructors are currently skipped.** Besides PFS, this includes the
   finalizer registrars and potentially other engine subsystems. Expect more
   missing state after the walker is fixed; the boot may get further but hit
   new uninitialized-object faults.
3. **The callee-saved corruption may affect more than r31.** The same
   tail-call/restore-helper path can clobber r14-r30. Validate all nonvolatile
   GPRs, not just r31.
4. **The PFS/HFileReader layer is untested.** Even with `GT.VOL` opened, the
   engine's PFS reader, decompression, and `HFileReader` virtual interface may
   have HLE/ABI gaps.
5. **The script VM may still fail on the ADCH header or module load.** The
   `.adc` path and header checks are visible in the ELF, but the VM's module
   registration (`0x13FBC` / `0x139AC`) may depend on the same skipped
   constructors.

---

## 9. Limitations

* **RPCS3 was not run in this pass.** The host runtime traces and ELF
  disassembly were sufficient to localize the failure. A useful confirmation
  would be an RPCS3 boot with `Log Level: All`, grepping for
  `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` before `scripts/gt6/main`; the game dump
  was not modified.
* The analysis copies are from the 11:40 build because another workstream was
  rebuilding `gt6/build/gt6.exe` concurrently. The `.ctors` walker and the
  script-loader code are generated from the same lift and are unaffected by
  the getter patch; the copies force the real boot value (0) at machine-code
  level.
* The exact instruction that loses `r31` is inferred from the generated
  epilogue and the observed register value, not from a single-step debugger.
  The walker-level save/restore fix does not depend on identifying it.

## 10. Evidence index

| File | Contents |
|---|---|
| `work/boot_analysis/guard_test.log` | page guard; only write to 0x164AB90 is `0xE47040` zero |
| `work/gt6_calltrace.log` | constructor walk; r31 descends to 0x14105D0 then null |
| `work/boot_analysis/trace_continue.err` | calltrace with r31=0x14105D0 and null calls |
| `work/boot_analysis/at13830_pfs.err` | frozen at 0x13830; 0x157087C/0x16A99D4/0x16A99E0/0x16A99D0 = 0 |
| `work/boot_analysis/flag0_trace.log` | flag-0 run; no cellFs/sys_fs open |
| `work/boot_analysis/disasm_9CD798.txt` | loader disassembly |
| `work/boot_analysis/disasm_6BC7B4.txt`, `disasm_6BCC34.txt` | constructor/tail-call path |
| `tools/boot_analysis/find_addr.py` | address/xref scanner |
| `tools/boot_analysis/callgraph_to_stub.py` | direct-call BFS to imports |

### Reproduce the key measurements

```powershell
# page guard: only the constructor writes 0x164AB90
$env:GT6_GUARD="164AB90:0xE00000"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\boot_analysis\guard.log

# constructor walk trace
$env:PS3_CALLTRACE="200000"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\boot_analysis\trace.log

# freeze at 0x13830 in a throwaway copy, then peek PFS globals
# (see work/boot_analysis/gt6_at13830.exe; patched EB FE at func_00013830)
$env:GT6_MAINSTACK="2"
$env:GT6_PEEK="0x1570D58,0x157087C,0x16A99D4,0x16A99E0,0x16A99D0"
work\boot_analysis\gt6_at13830.exe work\bin\EMAIN.elf *> work\boot_analysis\at13830.log
```
