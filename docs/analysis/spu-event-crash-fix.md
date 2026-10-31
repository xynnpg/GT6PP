# SPU event handler crash — root cause and fix

**Date:** 2026-10-31
**Artifact:** `work/gt6_lab1_final.exe` (`work/lab1_final_run.err`, `work/lab1_final_run.log`)
**Guest:** `BCUS98296` v1.00, EBOOT `work/bin/EMAIN.elf`
**Symptom:** after the boot script reaches EOF and the first GT.VOL assets load, PPU
tid 15 (`Spu Event Handler`, host tid 29272) starts dispatching SPURS events, then:

```
[ppu] unresolved indirect call -> 0x007F454C (tid=15 lr=0x00A56A40)
[GT6] ACCESS VIOLATION: read at host 0x19400000000 (thread 29272)
[GT6] crash is PPU tid=14 name="Spu Event Handler" ... hle=sys_lwmutex_lock
```

and the process exits because `report_crash` returns `EXCEPTION_EXECUTE_HANDLER`.

## Bottom line

1. The fatal fault is **not** in `sys_lwmutex_lock` and is **not** a guest memory
   fault. It is a bug in `ps3_indirect_call_impl`'s diagnostic code
   (`third_party/ps3recomp/runtime/ppu/ppu_loader.cpp`): it dereferences the
   unresolved call's `r3` (`0xFFFFFFFF`) as a guest pointer. The 4-byte read at
   guest `0xFFFFFFFF` crosses the end of the 4 GB window and faults at
   `vm_base + 0x100000000`. The `hle=sys_lwmutex_lock` / `prof_pc=0x00A564EC`
   fields are stale per-thread metadata (the crashing host thread is not the
   registered PPU host thread).
2. The bad dispatch is real: the guest object at **0x01675210** owns a
   **16-entry** `{opd,arg}` table. A SPURS job-completion event with
   `data2 = 52` (`0x34`) indexes `obj + 0x1A0`, outside the table. The word
   there (`0x0000FFFF`) is treated as an OPD pointer; guest `0xFFFF` contains
   `0x007F454C / 0x46020201`, and `bctrl` goes to `0x007F454C` (8 bytes into
   `func_007F4544`, not an OPD). Other out-of-range ids read `0xF` and cause
   `bctrl` to NULL.
3. The producer is `cellSpurs.c`'s synthetic job-completion signal:
   `jc_signal_done()` pushes `source=0, data1=jc_ea, data2=job_index, data3=mbox`
   to **every** attached queue. `job_index` is the host walker's monotonically
   increasing `jobs++` counter; it is never reset per chain lap and can exceed
   the receiver's 16 slots. The same routine also pushes to queues belonging to
   *other* SPURS instances because `s_spurs_event_queue` is process-global.
4. `cellSpursInitializeWithAttribute2` (`0x30AA96C4`) being unresolved is **not**
   the cause of this table being uninitialized: the table is zeroed by guest
   constructor `0x00A567B8` and the queue/thread are created before the
   unresolved NID is logged. It is a separate gap (second SPURS instance) and is
   now aliased.

## 1. The event-handler object at 0x01675210

Created by guest `func_00A4259C` (the `"Spu Event Handler"` factory). Layout
observed from the ELF:

| Offset | Contents | Initialised by |
|---:|---|---|
| `+0x00` | vtable `0x0148A7E8` | `0x00A566DC` / `0x00A56760` |
| `+0x04 .. +0x83` | 16 × `{arg @ +8, opd @ +4}` | zeroed by `0x00A567B8`, filled by `0x00A565C8` |
| `+0x88` | PPU thread id | `sys_ppu_thread_create` (`0x00A568C4`) |
| `+0x90` | byte flag | `0x00A56760` |
| `+0x98` | **lwmutex** (24 bytes) | `0x00A43430` → import `0xF99B08` (`sys_lwmutex_create`) |
| `+0xB0` | ctor argument / id | `0x00A567B8` |
| `+0xB4` | **lv2 event queue id** | `sc 0x80` = `sys_event_queue_create` at `0x00A56848` |
| `+0xB8` | **lv2 event port id** | `sc 0x86` = `sys_event_port_create` at `0x00A56864` |

Correction to the earlier working note: `+0xB4` is **not** the lwmutex. The
constructor creates the queue with size 127 and the port with name
`0xD00000A77`, then connects them (`sc 0x88` = `sys_event_port_connect_local`).
The log confirms all three:

```
[evt] queue_create -> id=3 key=0x0 size=127
[evt] port_create -> id=2 type=1 name=0xD0A77
[evt] port_connect(port=2 -> queue=3)
[evt] port_connect_local(port=2 -> q=3)
[SYS] sys_ppu_thread_create tid=15 name="Spu Event Handler" entry=0x014E14C0 arg=0x1675210 ...
```

`0x014E14C0` is the first OPD in a table at `0x014E14B8..0x014E1500`; its code
is `0x00A56698` (thread body), which calls vtable+8 = `0x00A564EC`, then
`sys_ppu_thread_exit`. vtable+0xC is `0x014E14D8` = `0x00A569D0` (the
dispatcher).

## 2. Event loop and dispatch

`func_00A564EC` is the receive/dispatch loop:

```asm
00A564EC  stdu  r1,-0xB0(r1)          ; prologue
...
00A56514  lwz   r3,0xB4(r31)          ; r31 = this = 0x01675210 -> queue id 3
00A56518  mr    r4,r28                ; &event on stack
00A5651C  li    r5,0                  ; timeout 0
00A56520  li    r11,0x82
00A56524  sc                          ; sys_event_queue_receive (130)
...
00A56544  mr    r9,r4                 ; r4 = event source
...
00A56554  clrldi r4,r6,0x28           ; r4 = data2 & 0x00FFFFFF  = handler id
00A5655C  clrldi r5,r7,0x20           ; r5 = data3 & 0xFFFFFFFF  = handler arg
...
00A56584  lwz   r9,0(r31)             ; vtable
00A56588  addi  r9,r9,0xC             ; vtable+0xC -> OPD 0x014E14D8
00A56590  lwz   r11,0(r9)
00A56594  lwz   r0,0(r11)             ; code = 0x00A569D0
00A56598  lwz   r2,4(r11)             ; TOC
00A5659C  mtctr r0
00A565A0  bctrl                       ; dispatch(this, id, arg)
00A565A4  b     0x00A56514            ; next event
```

The event register ABI is documented in
`runtime/syscalls/sys_event.c`: `r3=rc, r4=source, r5=data1, r6=data2,
r7=data3`.

`func_00A569D0` does:

```asm
r28 = this + (id << 3)
lock(this + 0x98)
opd = *(u32 *)(r28 + 4)
if (!opd) skip
arg = *(u32 *)(r28 + 8)
ctr = *(u32 *)opd
r2  = *(u32 *)(opd + 4)
bctrl
unlock(this + 0x98)
```

There is **no id bounds check**. The constructor zeroes exactly 16 entries, so
ids `0..15` are valid; `id >= 16` reads adjacent fields of the object as an OPD.

Registration is `func_00A565C8` (first empty slot; stores OPD at `+8*id+4`, arg
at `+8*id+8`); removal is `func_00A56A68`. In this title only a few slots are
registered, which is why ids above that also produce `bctrl` to NULL.

## 3. Why the id is 52 and the OPD is garbage

The crash registers (from `lab1_final_run.err`, unresolved-call dump):

```
r28 = 0x016753B0  r29 = 0x000001A0  r30 = 0x016752A8
r3  = 0xFFFFFFFF  r9  = 0x0000FFFF  r0  = 0x007F454C
r2  = 0x46020201
```

With `this = 0x01675210`:

```
id       = r29 >> 3           = 0x1A0 >> 3 = 52 (0x34)
entry    = this + 0x1A0       = 0x016753B0
opd      = *(u32 *)(entry+4)  = *(u32 *)0x016753B4 = 0x0000FFFF
arg      = *(u32 *)(entry+8)  = *(u32 *)0x016753B8 = 0xFFFFFFFF
*(u32 *)0xFFFF = 0x007F454C   (code)
*(u32 *)0x10003 = 0x46020201  (TOC, garbage)
```

`0x007F454C` is `0x007F4544 + 8`: inside the prologue of a real function, not an
OPD. `bctrl` is reported by `ps3_indirect_call_impl` as unresolved.

The id is produced by `cellSpurs.c`'s `jc_signal_done()`. The probe run with
`EVT_PUSHLOG=3` shows exactly this shape (source 0 = SPURS completion, data1 =
chain EA, data2 = job index):

```
[evt-push] q=3 src=0x0 d=0x701AC000/0x21/0x0 ra=...
[evt-push] q=3 src=0x0 d=0x701AC000/0x22/0x0 ra=...
[evt-push] q=3 src=0x0 d=0x701AC000/0x14/0x0 ra=...
...
[cellSpurs] chain 0x701AC000 job 0 done -> event queue 3 (data2=0 rc=0)
[cellSpurs] chain 0x701AC000 job 0 done -> event queue 4 (data2=0 rc=0)
```

`job_index` is `jobs++` inside `jc_execute()`. It is not reset at a GUARD/lap and
the host walker can lap a service chain indefinitely while guard notifications
arrive, so it eventually reaches 52. The chain's own attribute says
`maxGrabbedJob=16` — the receiver has one slot per job slot, and the dispatcher
table is 16 entries; the raw counter violates that contract after 16 laps.

There is a second, independent bug in the same push: `s_spurs_event_queue` and
`s_spurs_event_queue_owner` are process-global. q=3 is attached to the PDI
instance `0x70100000` (log line 155), q=4 to the second instance (line 195).
`jc_signal_done()` broadcast every chain's completion to both, so the PDI
`Spu Event Handler` received completions for a chain it did not own. The chain
create call's `spurs` argument was not recorded anywhere (`jc_register` dropped
it), so the routing could not be correct.

## 4. `cellSpursInitializeWithAttribute2` is not the trigger

`[hle] unresolved NID 0x30AA96C4` appears after the q=3 object/thread creation
(`lab1_final_run.err` line 154 vs 134–138). The handler table is guest memory
initialised by `0x00A567B8`; the queue is created and the thread starts before
the unresolved call. The OOB id is entirely explained by the HLE producer above.
The unresolved function may leave the **second** SPURS instance uninitialised
(the one that later attaches q=4), so it is still worth fixing, but it is not the
cause of this crash.

The 16-entry table is filled by guest registration calls, not by
`cellSpursInitialize*`, and the object itself is built by guest code
(`0x00A4259C` → `0x00A567B8`). No HLE writes this layout; the HLE only places
events in the lv2 queue. A missing registration would leave an entry zero (the
dispatcher skips zero safely via `beq 0x00A56A40`); it would not create a valid
but bogus OPD. The observed OPDs (`0xFFFF`, `0xF`) come from indexing past the
table, not from an unregistered entry.

## 5. The fatal ACCESS VIOLATION is the reporter

`ps3_indirect_call_impl` prints the vtable/OPD chain for the unresolved call:

```c
auto g32 = [](uint32_t ea) {
    return __builtin_bswap32(*(volatile uint32_t*)(vm_base + ea));
};
uint32_t obj = (uint32_t)ctx->gpr[3];   /* 0xFFFFFFFF */
uint32_t vt  = g32(obj);                /* reads 4 bytes at 0xFFFFFFFF */
```

The read starts on the last byte of guest page `0xFFFF0000`. `fault_commit` maps
that page, so the first byte succeeds, but the 4-byte access still crosses into
`vm_base + 0x100000000`, which is outside the guest mapping. The symbolised host
stack is:

```
0xAFB488 ps3_indirect_call_impl(ppu_context*)
0x8045FA3 func_00A569D0(ppu_context*)
0x8045259 func_00A564EC(ppu_context*)
0x80455C7 func_00A56698(ppu_context*)
0xAFE81C ppu_thread_entry_trampoline
```

That is why `hle=sys_lwmutex_lock` and `prof_pc=0x00A564EC` are misleading: they
are the thread's last recorded HLE/PC, not the faulting frame. `report_crash`
then returns `EXCEPTION_EXECUTE_HANDLER` and the whole process exits.
`GT6_CRASH_THREAD_EXIT=1` exists in `gt6/src/main.cpp` but is diagnostic only and
does not fix the reporter.

## 6. Fixes implemented (no relift / no gt6.exe build)

### 6.1 Reporter must never fault (`ppu_loader.cpp`)

`g32` now validates the whole 4-byte access, not just the start:

```cpp
auto g32 = [](uint32_t ea)->uint32_t {
    const uint64_t end = (uint64_t)ea + 4u;
    if (ea < 0x10000u || end > 0x100000000ull) return 0;
    if (ppu_vm_size && end > ppu_vm_size) return 0;
    return __builtin_bswap32(*(volatile uint32_t*)(vm_base + ea));
};
```

The `CHAIN` line also marks an out-of-range object. This does not hide the bad
dispatch: the unresolved-call line, the guest stack, and the register dump still
print; the process simply does not die inside its own diagnostics.

### 6.2 Producer contract (`cellSpurs.c`)

* `s_jobchains[]` now records the owning `spurs_ea` (`jc_register` takes it from
  both `cellSpursCreateJobChain*` entry points) and has a `jc_find()` helper.
* `jc_signal_done()` wraps the completion index by the chain's
  `maxGrabbedJob`:

  ```c
  if (!raw && job_index >= 0 && max_grab > 0 && (u32)job_index >= max_grab)
      d2 = (u32)job_index % max_grab;
  ```

  For GT6 `max_grab=16`, so id 52 becomes 4. The first 16 ids are unchanged;
  only contract violations wrap. A one-shot `[cellSpurs] ... wrapping` log makes
  the wrap visible.
* The same function snapshots the attached queues under `s_spurs_queue_lock` and
  drops queues whose owner is a different SPURS instance. Owner 0 (pre-tracking
  queues) keeps the old broadcast.

A/B switches, default fixed behaviour:

* `SPURS_JC_INDEX_RAW=1` — restore the raw `jobs++` index (reproduces the crash).
* `SPURS_JC_LEGACY_ROUTE=1` — restore the global broadcast to every queue.

### 6.3 Dispatcher guard (generated-code patch)

New tool: `tools/patches/spu_event_dispatch_guard.py`.

It inserts, at the top of `func_00A569D0` in
`gt6/generated/ppu_recomp_023.cpp` (before the frame is built or the object
lwmutex is taken):

```c
if ((uint32_t)ctx->gpr[4] >= 16u) {
    /* log first 8, then ignore */
    return;
}
```

Applied in this tree; the script is idempotent and `--check` reports `already`.
A relift overwrites `ppu_recomp_023.cpp`, so run `--apply` again (or add it to
the relift pipeline). This is defence-in-depth: the guest dispatcher has no way
to execute an out-of-range id safely, so dropping it with a loud line is the only
non-corrupting behaviour. The producer fix above is what should make the guard
unreachable.

### 6.4 `cellSpursInitializeWithAttribute2` alias

Implemented in `cellSpurs.c` / `cellSpurs.h` as an alias of
`cellSpursInitializeWithAttribute`, and registered for NID `0x30AA96C4` in
`ppu_sysprx.cpp` via `ps3_hle_register_ctx`. It is gated by
`GT6_SPURS_ATTR2_INIT_OFF=1` for A/B runs because the CellSpurs2 layout
difference has not been audited. This removes the unresolved NID but is not the
crash fix.

### 6.5 lwmutex address guard (defence-in-depth)

`sys_lwmutex_lock/trylock/unlock` now reject a mutex address that is not wholly
inside the guest window (24 bytes, no 32-bit wrap) with `CELL_ESRCH`, logging the
first 8. Valid locks are unaffected. This is not the root cause and does not
change normal behaviour; it just prevents a corrupt id from becoming a host read.

## 7. Ranked options

| Rank | Change | Correctness | Risk |
|---:|---|---|---|
| 1 | Record `spurs_ea`, route completions per instance, wrap index by `maxGrabbedJob` (`cellSpurs.c`) | High: restores the SPURS per-batch/per-instance contract | Medium: changes a heuristic that GT5P relied on only for in-range indices; out-of-range behaviour was never valid |
| 2 | 16-entry bounds guard in `func_00A569D0` (generated patch) | High as an invariant; drops impossible ids instead of executing them | Low; must stay loud so it is not a silent event sink |
| 3 | Bounds-check the indirect-call reporter (`ppu_loader.cpp`) | Certain: diagnostics must not fault | Negligible |
| 4 | lwmutex address validation | Defence-in-depth only | Low |
| 5 | `cellSpursInitializeWithAttribute2` alias | Medium: fixes an unresolved import, but CellSpurs2 layout unverified | Low–medium; gated by env |

`GT6_CRASH_THREAD_EXIT=1` (already in `gt6/src/main.cpp`) is a diagnostic
containment only: it keeps the other threads alive after a real fault, but it
does not repair the reporter or the event payload, so it is not ranked as a fix.
The default path is **not** hiding the fault: the unresolved call and the null
dispatch are still logged; only the impossible id is refused before it can
`bctrl` into code.

## 8. Reproducing the evidence

```powershell
# object construction + queue/port/thread
Select-String work\lab1_final_run.err -Pattern 'queue_create -> id=3|port_create -> id=2|Spu Event Handler'
# unresolved call + fatal reporter read
Select-String work\lab1_final_run.err -Pattern 'unresolved indirect call|ACCESS VIOLATION|r28=|0x0000FFFF'
# queue pushes and maxGrabbedJob
Select-String work\spu_evt_probe.err -Pattern '\[evt-push\] q=3'
Select-String work\lab1_final_run.log -Pattern 'AttachLv2EventQueue|maxGrab=16|job .* done -> event queue'
# symbolised host stack (bundled LLVM; add the image base 0x140000000 to RVAs)
tools\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64\bin\llvm-symbolizer.exe `
  --obj=gt6\build\gt6.exe 0x140AFB488 0x148045FA3 0x148045259 0x1480455C7 0x140AFE81C
```

## 9. Run procedure and exact verification

After the owner rebuilds (`powershell -File scripts/build-gt6.ps1`), from the
project root:

```powershell
# Headless, verbose, prove which queue receives what.
$env:PS3_HEADLESS = "1"
$env:PS3_VERBOSE  = "1"
$env:GT6_CONSOLE  = "1"
$env:PS3_EVT_RECV = "3"          # log receives on the SPU handler queue
$env:EVT_PUSHLOG  = "3"          # log every push to queue 3 (first 200)
gt6\build\gt6.exe work\bin\EMAIN.elf
```

Expected, in order:

1. `[cellSpurs] AttachLv2EventQueue(spurs=0x70100000 queue=3) port=16` and
   `[cellSpurs] AttachLv2EventQueue(spurs=<second> queue=4) port=17`.
   `CreateJobChainWithAttribute(spurs=... jc=0x701AC000 ...)` now names the
   owner directly; the completions must follow that owner.
2. Job completions for the second-instance chain show only queue 4 (or, if the
   chain is the PDI instance's, only queue 3). `[evt-push]` for the other queue
   disappears.
3. If the walker laps past 16, exactly:
   `[cellSpurs] chain ... completion index N >= maxGrabbedJob=16 -- wrapping to M`
   with `M < 16`.
4. No `[ppu] unresolved indirect call -> 0x007F454C`.
5. No `[GT6] ACCESS VIOLATION: read at host ...100000000`.
6. If an impossible id still reaches the dispatcher, at most 8 lines of
   `[ppu] SPURS dispatch id=... >= 16 (table=16) ... ignored`, and no `bctrl`.

A/B controls:

```powershell
$env:SPURS_JC_INDEX_RAW   = "1"   # expect 0x007F454C again
$env:SPURS_JC_LEGACY_ROUTE= "1"   # expect q=3 to see q=4's chain again
$env:GT6_SPURS_ATTR2_INIT_OFF = "1" # unresolved NID 0x30AA96C4 returns
```

Windowed run: same without `PS3_HEADLESS`.

To prove the reporter fix independently, force a bad indirect call with
`SPURS_JC_INDEX_RAW=1` and confirm the run logs the unresolved call, the full
register dump, and then **continues** instead of printing `ACCESS VIOLATION`.

## 10. Files changed

| File | Change |
|---|---|
| `third_party/ps3recomp/runtime/ppu/ppu_loader.cpp` | Bounds-checked `g32` in the indirect-call vtable/OPD diagnostic; out-of-range object note |
| `third_party/ps3recomp/libs/spurs/cellSpurs.c` | `JcSlot.spurs_ea` + `jc_find`; per-instance queue routing; completion index wrapped by `maxGrabbedJob`; `cellSpursInitializeWithAttribute2` alias |
| `third_party/ps3recomp/libs/spurs/cellSpurs.h` | `cellSpursInitializeWithAttribute2` declaration |
| `third_party/ps3recomp/runtime/ppu/ppu_sysprx.cpp` | Register NID `0x30AA96C4`; lwmutex guest-address guard |
| `tools/patches/spu_event_dispatch_guard.py` | New idempotent generated-code guard for `func_00A569D0` |
| `gt6/generated/ppu_recomp_023.cpp` | Guard applied by the tool (regenerated on relift; re-apply) |
| `docs/analysis/spu-event-crash-fix.md` | This document |

Not touched: `gt6/src/main.cpp`, `gt6/src/stubs.cpp`.

## 11. Remaining risks / next work

* The completion selector is still a **count**, not a recovered handler id. The
  wrap keeps it inside `maxGrabbedJob`, but if the title queues slots out of
  order the callback may be the wrong one. The next run should log the first
  `EVT_PUSHLOG` values and the handler table's registered slots
  (`0x01675210 + 8*id + 4/+8`) to confirm whether ids 0..15 map to job slots or
  to workloads. The per-instance routing is the higher-confidence half.
* The second SPURS instance still needs its `CellSpurs2` object layout audited
  (8 KB vs 4 KB clear, attribute2 fields). The alias is gated for this reason.
* Remaining unresolved NIDs from the run are unrelated to this crash:
  `0xFF0A21B7` cellKbRead (stub exists in `libs/input/cellKb.c`, not in this
  exe), `0x7FE92C54/0xBD554BCB` cellUsbd, `0x1F71ECBE` sys_io,
  `0xA5D06BF0/0xCA9A60BF` sysPrxForUser.
* If a future relift changes `func_00A569D0`'s prologue shape, the guard tool
  fails closed (`func_00A569D0 not found` / `expected _cs_31 ...`); do not
  hand-edit around it.
