# SPU event crash - independent check

**Date:** 2026-10-31
**Scope:** GT6 `BCUS98296` v1.00, `work/bin/EMAIN.elf`, run
`work/lab1_final_run.{log,err}` and the `work/spu_evt_probe.err` probe.
**Subject:** the `Spu Event Handler` crash after the boot script reaches EOF
(`0xA564EC` / `0xA569D0` / `0x0D000A77`, NID `0x30AA96C4`).
**Method:** independent Capstone disassembly, ELF OPD/vtable inspection,
`llvm-symbolizer`/`llvm-nm` on `work/gt6_lab1_final.exe`, and a read-only review
of the fixer's working-tree diff.

---

## 1. Bottom line

The fatal access violation is **not** `sys_lwmutex_lock`. It is the
`ps3_indirect_call_impl` *unresolved-call reporter* dereferencing guest
`0xFFFFFFFF` as if it were an object pointer. The 4-byte read at guest
`0xFFFFFFFF` crosses the end of the 4 GB guest window and faults at
`vm_base + 0x100000000`. `hle=sys_lwmutex_lock` and `prof_pc=0x00A564EC` are
stale/misindexed PPU-thread breadcrumbs.

The first-order bug is a **runtime-generated SPURS job-completion event with an
out-of-range job index**:

- `PDISTD::SpuEventHandler` (queue 3, first CellSpurs instance `0x70100000`) has
  a **16-entry** handler table indexed by `event.data2 & 0xFFFFFF`.
- `jc_signal_done()` broadcasts every job-chain completion to **every attached
  SPURS queue**, and puts the raw `jobs++` ordinal in `data2`.
- The `soc-job` chain has `maxGrabbedJob = 16`. After 16 completions the raw
  ordinal is 17, 18, ...; the q3 table lookup walks past its 16 entries into the
  object's thread-id field and adjacent heap.
- id 17 read the low word of the thread id (`0xF`) as a handler OPD, read guest
  `0xF` (zero-filled null page), and `bctrl`'d to 0.
- id 52 read a heap word as a handler, got code `0x007F454C` (interior of
  `func_007F4544`, not a function entry) and toc `0x46020201`, with handler arg
  `0xFFFFFFFF`; the unresolved-call reporter then dereferenced that arg.

The fixer's two event-side changes are the right shape:

1. route completions only to queues attached to the chain's CellSpurs instance
   (q4/`sgx-audio-thr`, not q3/`SpuEventHandler`);
2. keep `data2` inside `maxGrabbedJob`.

The `maxGrabbedJob` wrap prevents the OOB crash but is only approximately
faithful: the exact contract is the job index **within the current grabbed
batch** (`0..queued-1`, reset each batch). A global `% maxGrab` matches when the
guest queues `maxGrab` jobs per batch (the common case), but not for a smaller
batch; resetting the ordinal at each guard/batch boundary is more faithful. The `g32` bounds check is necessary hardening. The lwmutex
guard is defensive only and would not have prevented this crash. The
`cellSpursInitializeWithAttribute2` alias is required for the second instance's
lifecycle but is only a partial CellSpurs2 implementation. The
`GT6_CRASH_THREAD_EXIT` containment is **not safe for production**: it leaves the
faulting thread inside `0xA569D0`'s lwmutex critical section and leaves the PPU
slot RUNNING.

---

## 2. Claims and verdicts

| # | Claim | Verdict | Basis |
|---|---|---|---|
| 1 | `0xA564EC` is the `SpuEventHandler` run loop; entry OPD `0x014E14C0` calls it through the vtable | **PASS** | OPD/vtable dump; `0xA56698` calls vtable+8, then `sys_ppu_thread_exit` |
| 2 | The handler array is 16 entries at `this+4`, `{u32 opd, u32 arg}` per entry, guarded by the lwmutex at `this+0x98` | **PASS** | `0xA567C8..0xA56818` initializer; `0xA565C8..0xA56660` register; `0xA569D0` dispatch |
| 3 | The event id is `data2 & 0xFFFFFF` and is passed as `r4` to `0xA569D0` | **PASS** | `0xA56554: clrldi r4,r6,0x28`; `0xA565A0: bctrl` |
| 4 | `0x007F454C` comes from an out-of-range event id, not an uninitialized valid slot | **PASS** | id 52: `r29=0x1A0`; valid slots 0..15 only; empty slots are skipped by the `lwz r0,4(r28)` zero check |
| 5 | `0xD0055E20` is a bogus OPD/TOC that explains the failure | **FAIL** | `0xD0055E20` is `r1` (guest SP). The unresolved call's `r2` is `0x46020201`; the real module TOC is `0x14ED560` |
| 6 | The fatal fault is inside `sys_lwmutex_lock` | **FAIL** | crash RVA `0xAFB488` is `ps3_indirect_call_impl+0x1D08`; `sys_lwmutex_lock` is RVA `0xB079D0` |
| 7 | The crash thread is guest tid 15 and is a registered PPU host thread | **PASS** | `[SYS] ... tid=15 ... hosttid=29272`; crash `thread=29272`, scan matches slot 14 (guest tid 15). The printed `tid=14` is the slot index |
| 8 | `hle=` and `prof_pc=` in the crash report are reliable | **FAIL** | `g_hle_inflight[]` is indexed by `thread_id` (slot+1) but read with the slot index; `prof_pc` is the last HLE breadcrumb, not the fault PC |
| 9 | `cellSpursInitializeWithAttribute2` (NID `0x30AA96C4`) is required for the second CellSpurs object | **PASS** | only initializer for `0x159D600`; call site `0x7EE690` |
| 10 | Aliasing WithAttribute2 to WithAttribute is a complete implementation | **PARTIAL / FAIL** | CellSpurs2 is 8 KB and has 32-workload state; runtime clears 4 KB and implements SPURS1 fields only |
| 11 | The runtime's CellSpurs layout is compatible | **PARTIAL** | SPURS1 BE offsets match RPCS3; CellSpurs2 0x1000..0x1FFF and the PS3 attribute layout are not implemented |
| 12 | Per-instance completion routing is correct | **PASS** | q4 attach and chain create both use `*(TOC-0x7C30)`; q3 is attached to the PDI instance |
| 13 | Wrapping the job index by `maxGrabbedJob` is correct | **PASS for safety / PARTIAL for exactness** | prevents OOB; exact value is the index within the current grabbed batch |
| 14 | The `g32` diagnostic bounds check is correct | **PASS** | it prevents the reporter from dereferencing guest-controlled `r3`; it does not fix the bad dispatch |
| 15 | The lwmutex range check prevents this crash | **FAIL** | the lwm was never `0xFFFFFFFF`; the fault is in the reporter. The check is still good defensive hygiene |
| 16 | `GT6_CRASH_THREAD_EXIT` is safe containment | **FAIL as a fix** | `ExitThread` bypasses `sys_ppu_thread_exit`/thread-proc cleanup and leaves the `this+0x98` lwmutex held |

---

## 3. Exact disassembly and object map

All addresses are guest EAs in `work/bin/EMAIN.elf`. Function boundaries are
from `work/analysis/emain/functions_corrected_lab.json`.

### 3.1 Class and thread entry

The class is `PDISTD::SpuEventHandler` (RTTI string `N6PDISTD15SpuEventHandlerE`
at `0x109C5D8`; thread name `"Spu Event Handler"` at `0x109C5F8`).

```
OPD 0x014E14C0 -> { code 0x00A56698, toc 0x014ED560 }   thread entry
OPD 0x014E14B8 -> { code 0x00A564EC, toc 0x014ED560 }   run()
OPD 0x014E14D8 -> { code 0x00A569D0, toc 0x014ED560 }   notify(id, arg)
OPD 0x014E14D0 -> { code 0x00A56728, toc 0x014ED560 }   deleting dtor
OPD 0x014E14C8 -> { code 0x00A566DC, toc 0x014ED560 }   dtor
```

`0xA56698` is the thread entry wrapper:

```
0xA56698  lwz   r9,0(r3)       ; vptr
0xA566A8  lwz   r10,8(r9)      ; vtable+8 -> OPD 0x014E14B8
0xA566B4  lwz   r0,0(r10)      ; 0xA564EC
0xA566B8  lwz   r2,4(r10)      ; 0x14ED560
0xA566BC  mtctr r0
0xA566C0  bctrl                ; run()
0xA566C4  li    r3,0
0xA566C8  bl    0xF99F30       ; sys_ppu_thread_exit
```

The vtable at `0x148A7E8` has slots:

```
+0x00 OPD 0x014E14D0 (0xA56728)   deleting dtor
+0x04 OPD 0x014E14C8 (0xA566DC)   dtor
+0x08 OPD 0x014E14B8 (0xA564EC)   run()
+0x0C OPD 0x014E14D8 (0xA569D0)   notify
+0x10 0x148CF18                  typeinfo
```

### 3.2 Run loop `0xA564EC` and the event id

`0xA564EC` is a blocking receive/dispatch loop. It reads the queue id from
`this+0xB4` (observed 3), receives into `r1+0x70` with timeout 0, and uses the
lv2 ABI where the event arrives in `r4..r7` (`source,data1,data2,data3`):

```
0xA56514  lwz   r3,0xB4(r31)   ; queue id
0xA56518  mr    r4,r28         ; &event
0xA5651C  li    r5,0           ; infinite
0xA56520  li    r11,0x82       ; sys_event_queue_receive
0xA56524  sc
...
0xA5653C  cmpd  cr6,r4,r0      ; source == 0x0D000A77 (port 2 name)?
0xA56540  cmpd  cr7,r4,r29     ; source == 0xFEE1DEAD (exit)?
...
0xA56554  clrldi r4,r6,0x28    ; r4 = data2 & 0x00FFFFFF  <-- handler id
0xA5655C  clrldi r5,r7,0x20    ; r5 = data3 & 0xFFFFFFFF  <-- notify arg
...
0xA56584  lwz   r9,0(r31)      ; vptr
0xA56588  addi  r9,r9,0xC
0xA56590  lwz   r11,0(r9)      ; OPD 0x014E14D8
0xA56594  lwz   r0,0(r11)      ; 0xA569D0
0xA56598  lwz   r2,4(r11)      ; 0x14ED560
0xA5659C  mtctr r0
0xA565A0  bctrl                ; notify(id, arg)
```

For source `0x0D000A77` the loop instead writes 0 through `data1` and re-loops;
for source `0xFEE1DEAD` it exits. This is the `PDISTD` port protocol, not the
SPURS-internal `data2` protocol (`0/1/2/3`) used by `_spurs::event_helper_entry`.

### 3.3 Handler table layout

The constructor at `0xA567B8` clears 16 entries:

```
0xA567C8  li    r0,0x10
0xA567D4  mtctr r0
0xA56804  add   r9,r11,r31     ; this + 8*i
0xA56808  addi  r11,r11,8
0xA56810  stw   r10,8(r9)      ; entry.arg  = 0
0xA56814  stw   r10,4(r9)      ; entry.opd  = 0
0xA56818  bdnz
```

Therefore:

```
this+0x04 + 8*i : u32 handler OPD pointer   (0 = free)
this+0x08 + 8*i : u32 handler argument
i = 0..15
```

The registration helper `0xA565C8` scans the same 16 entries (`li r0,0x10` at
`0xA5660C`), skips a slot unless both `+8` and `+4` are zero, and stores
`arg` at `+8` and `opd` at `+4` (`0xA56644..0xA56658`). GT6 registers exactly one
handler, id 0:

- Call site `0xA42910`, `r3=0x1675210`, `r4=<0x180-byte object>`,
  `r5=OPD 0x014E0EA8` -> code `0xA42400`.
- `0xA42400` dispatches through the object's vtable+0xC; that slot is
  `0x008B2C28`, whose body is a single `blr`. id 0 is deliberately a no-op.

### 3.4 Dispatch `0xA569D0` (the OOB lookup)

```
0xA569D0  stdu  r1,-0x90(r1)
0xA569DC  mr    r29,r4          ; id
0xA569E4  slwi  r29,r29,3       ; id*8
0xA569F8  addi  r0,r3,0x98
0xA569FC  add   r28,r28,r29     ; r28 = this + id*8
0xA56A04  clrldi r30,r0,0x20    ; r30 = this+0x98 (lwmutex)
0xA56A0C  mr    r3,r30
0xA56A14  bl    0xA43378        ; sys_lwmutex_lock(this+0x98)
0xA56A18  lwz   r0,4(r28)       ; handler opd
0xA56A1C  cmpwi cr7,r0,0
0xA56A28  beq   cr7,0xA56A40    ; free slot -> skip
0xA56A2C  lwz   r0,0(r9)        ; handler opd -> code
0xA56A30  lwz   r3,8(r28)       ; handler arg -> r3
0xA56A34  mtctr r0
0xA56A38  lwz   r2,4(r9)        ; handler toc
0xA56A3C  bctrl
0xA56A40  mr    r3,r30
0xA56A44  bl    0xA42D3C        ; sys_lwmutex_unlock
```

There is **no range check** on `r4`. The table's valid range is `id=0..15`; the
word at `this+0x8C` is the low half of the `u64` thread id written by
`sys_ppu_thread_create` (`this+0x88` is the `tid_out` pointer at `0xA5689C`).

---

## 4. The exact bad-pointer path

### 4.1 id 17 (first null call)

From `work/lab1_final_run.err:764-766` and the probe
`work/spu_evt_probe.err:466-471`:

```
[evt-push] q=3 ... d=0x701AC000/0x11/0x0
[evt] q=3 receive RETURNED ... d2=0x11
[null-call] ... r3=10000000 r9=0000000F ... lr=0x00A56A40
[GSTACK:nc] ... r28=0x01675298 r29=0x00000088 r30=0x016752A8 tid=15
```

- `this = r30 - 0x98 = 0x01675210` (matches the thread arg from
  `[SYS] ... tid=15 ... arg=0x1675210`).
- `r28 = this + 0x88`, `r29 = 0x88 = 17*8`.
- handler word at `this+0x8C = 0x0000000F` (the low word of the BE u64 thread id
  `0x000000000000000F`).
- `lwz r0,0(r9)` with `r9=0xF` reads the committed zero null page -> `ctr=0`.
- `ps3_indirect_call_impl` logs `bctr to NULL ... r12(opd)=0`, returns without
  calling; `0xA569D0` unlocks and the loop continues.

The valid ids 0..15 are all empty except 0, so they are skipped. id 16 reads
padding at `this+0x84`; id 17 is the first field overlap.

### 4.2 id 52 (the fatal unresolved call)

From `work/lab1_final_run.err:259240-259253`:

```
[ppu] unresolved indirect call -> 0x007F454C (tid=15 lr=0x00A56A40)
      cia=0x014E14C0 lr=0x00A56A40 r2=0x46020201 r3=0xFFFFFFFF r11=0x014E14D8
      r0 : 007F454C D0055E20 46020201 FFFFFFFF ...
      r24: ... 016753B0 000001A0 016752A8 ...
```

- `r29 = 0x1A0 = 52*8`; `r28 = this + 0x1A0 = 0x016753B0`.
- handler word at `this+0x1A4 = 0x016753B4` is a heap pointer P.
- `[P] = 0x007F454C`, `[P+4] = 0x46020201`.
- arg word at `this+0x1A8 = 0x016753B8` is `0xFFFFFFFF`.
- `0x007F454C` is **not a function entry**: it is `func_007F4544+0x8`
  (`functions_corrected_lab.json` range `0x007F4544..0x007F45AC`). `ppu_lookup`
  correctly refuses it.
- The unresolved-call reporter then does `g32(0xFFFFFFFF)`.

### 4.3 Why the reporter faults

`vm_base = 0x0000019300000000` (`work/lab1_final_run.log`, `VM initialised`).
The reporter's first read of guest `0xFFFFFFFF` touches uncommitted page
`0xFFFF0000`; `fault_commit` commits the 64 KB page and continues. The retry is a
4-byte load at `vm_base+0xFFFFFFFF`, whose last three bytes are at
`vm_base+0x100000000` .. `vm_base+0x100000002`, outside the 4 GB reservation.

The crash PC is RVA `0xAFB488`:

```
140afb481  movq 0x18(%rsi),%rbx    ; rbx = ctx->gpr[3]
140afb485  movl %ebx,%r14d         ; r14 = 0xFFFFFFFF
140afb488  movl (%rax,%r14),%edi   ; <-- fault: rax=vm_base, r14=0xFFFFFFFF
```

`llvm-nm` on `work/gt6_lab1_final.exe`:

```
0x140af9780 t ps3_indirect_call_impl(ppu_context*)
0x140b079d0 t sys_lwmutex_lock(ppu_context*)
```

So `0xAFB488 - 0xAF9780 = 0x1D08` is inside `ps3_indirect_call_impl`, and
`sys_lwmutex_lock` is 0x...B079D0, nowhere near the fault. The host stack
`AFB488 8045FA3` is `ps3_indirect_call_impl <- func_00A569D0`.

### 4.4 Corrections to the reported metadata

- `0xD0055E20` is `r1` (guest SP), not a TOC. The actual `r2` at the unresolved
  call is `0x46020201` (the fake descriptor's second word). The module's real
  TOC is `0x014ED560`.
- `0x007F454C` is an interior text address, not an OPD and not a function start.
- The crash scan *does* find the PPU thread: slot 14 = guest tid 15,
  `host_tid=29272`, matching `[THREAD 15] host thread started ... hosttid=29272`.
  `guest_fn=0x00000000` only means the fault PC is runtime code, not lifted
  guest code. The claim "not a registered PPU host thread" is not supported by
  `lab1_final_run.err`. If a different run reports no host_tid match, that is a
  separate host-thread bookkeeping issue; the fault PC and the stale metadata
  are the same.
- `crash is PPU tid=14` prints the zero-based **slot index**, not the guest tid.
  The guest tid is 15 (slot+1).
- `hle=sys_lwmutex_lock` is off by one: `ps3_hle_call` writes
  `g_hle_inflight[ctx->thread_id]` (`ppu_hle.cpp:801`), i.e. index 15 for this
  thread, but `report_crash` reads `g_hle_inflight[i]` with `i = 14`
  (`gt6/src/main.cpp:416`). The printed HLE belongs to the previous slot.
- `prof_pc=0x00A564EC` is the last `ppu_prof_stamp` breadcrumb (the run loop /
  event-receive caller), not the fault PC.
- The `r1(SP)=0 ... r3=0` line (`main.cpp:453-456`) prints `g_main_ctx`, not the
  faulting thread's context.

These are diagnostic bugs, not the crash cause, but they are why the failure
looked like a lwmutex fault.

---

## 5. Event producer and why q3 was hit

`jc_signal_done()` (`libs/spurs/cellSpurs.c:2700`) sets:

```
u64 d2 = (u64)(unsigned)(job_index < 0 ? 0 : job_index);
```

and then, in the pre-fix code, pushes to **every** entry of
`s_spurs_event_queue[]` (the process-global attached-queue list). The probe
(`EVT_PUSHLOG=3`) shows the sequence:

```
[evt-push] q=3 src=0x0 d=0x701AC000/0x0/0x0
...
[evt-push] q=3 src=0x0 d=0x701AC000/0x11/0x0   <- id 17
...
```

and the q3 receive immediately followed by the null call
(`work/spu_evt_probe.err:466-471`). The raw `jobs++` ordinal reached 38 in the
probe and 52 in the crashing run.

The relevant queue attachments are:

| Queue | Attached by | Owner (inferred) | Consumer |
|---|---|---|---|
| q3 | `[cellSpurs] AttachLv2EventQueue(queue=3)` (`lab1_final_run.log:155`) | PDI CellSpurs `0x70100000` | `SpuEventHandler` tid 15, table of 16 |
| q4 | `[cellSpurs] AttachLv2EventQueue(queue=4)` (`lab1_final_run.log:195`) | second CellSpurs `0x159D600` | `sgx-audio-thr` tid 18, `lr=0x0082039C` |

The HLE attach log does not print the CellSpurs EA. The q3 owner is inferred
from the PDI singleton path (`0xA30B9C(0)` -> first instance); the q4 owner is
inferred from the second instance init and the q4 manager. Add `spurs=0x%08X` to
the attach log to make both owners explicit in the next run.

The audio chain is created immediately after the q4 attach:

```
[cellSpurs] AttributeInitialize(nSpus=1)                 line 194
[cellSpurs] AttachLv2EventQueue(queue=4) port=17         line 195
[cellSpurs] _JobChainAttributeInitialize(... maxGrab=16) line 196
[cellSpurs] CreateJobChainWithAttribute(jc=0x701AC000 ... maxGrab=16 name="soc-job") line 203
```

The `soc-job` chain object's run method at `0x82025C` (`this=0x701AC000`, the
same EA as the `jc=` argument) calls `cellSpursJobGuardNotify(this+0x180)`, then
`sys_event_queue_receive([this+0x218])`, then indexes a 0x80-stride callback
table at `this+0x2B8`:

```
0x8203C0  slwi  r31,r6,7        ; data2 * 0x80
0x8203C8  addi  r0,r31,0x2B8
0x8203E8  add   r10,r27,r0
0x8203F0  lwz   r10,0x34(r10)   ; callback for slot data2
...
0x82047C  addi  r0,r30,1
0x820480  lwz   r9,0x4284(r28)  ; queued
0x820484  cmpw  cr7,r0,r9
0x820488  blt   0x820394       ; while (data2+1 < queued)
```

This is the same shape as GT5P's documented audio loop
(`third_party/GT5P/docs/progress.md`: `i = data2; callback[i]; while (i+1 < queued)`).
`maxGrabbedJob=16` sizes the table; the raw ordinal 17/52 is out of range for
**both** consumers.

The q4 attach at `0x821E4C` and the chain create at `0x820608` both use the same
CellSpurs EA, `*(TOC-0x7C30)`:

```
; q4 attach
0x821E4C  lwz  r9,-0x7C30(r2)
0x821E54  lwz  r4,0x218(r30)   ; queue 4
0x821E60  lwz  r3,0(r9)        ; same CellSpurs EA
0x821E64  bl   0xF980C8        ; cellSpursAttachLv2EventQueue

; chain create
0x8202C0  lwz  r30,-0x7C30(r2)
...
0x820608  lwz  r3,0(r30)       ; same CellSpurs EA
0x820614  bl   0xF97B50        ; cellSpursCreateJobChainWithAttribute
```

So the per-instance owner routing is well-defined for this chain: it must go to
q4, not q3. The fixer should still log the EA in both calls to make the owner
explicit.

---

## 6. `cellSpursInitializeWithAttribute2` (NID `0x30AA96C4`)

### 6.1 Is it required?

Yes, for the second instance. The game calls it once at guest `0x7EE690`:

```
0x7EE650  addi r23,r23,-0x2A80   ; 0x0159D580 (manager)
0x7EE66C  addi r28,r23,0x80      ; 0x0159D600 (CellSpurs2 object)
0x7EE660  ... r3=r1+0x360 (attr), r4=2 (revision), r5=0x00330000 (sdk),
              r6=1 (nSpus), r7=0x10 (spuPriority), r9=1 (exitIfNoWork)
0x7EE680  bl   0xF97F08          ; _cellSpursAttributeInitialize
0x7EE684  mr   r4,r29            ; attr
0x7EE688  mr   r3,r28            ; spurs = 0x0159D600
0x7EE690  bl   0xF97B88          ; cellSpursInitializeWithAttribute2
```

Evidence:

- `work/analysis/emain/EMAIN.imports.json`: `0x30aa96c4` stub `0xf97b88`,
  library `cellSpurs`.
- `work/lab1_final_run.err:154`: `[hle] unresolved NID 0x30AA96C4`.
- `work/lab1_final_run.log:194`: `[cellSpurs] AttributeInitialize(nSpus=1)`.
- `work/lab1_final_run.log:195`: q4 attach.
- No other initializer for `0x159D600` appears.

Without it, the unresolved-NID default returns CELL_OK and no
`SpursInst` entry is created for `0x159D600`. `cellSpursAttachLv2EventQueue` and
`cellSpursCreateJobChain` still succeed because they do not call
`spurs_inst_find`, but `cellSpursGetInfo`, `cellSpursFinalize`,
`cellSpursCreateTaskset`, and `cellSpursAddWorkload` would return
`CELL_SPURS_CORE_ERROR_STAT`. The BE fields `nSpus` (0x76) and `wklFlag` (0x60)
would also never be initialized.

### 6.2 Correct semantics / ABI

RPCS3 `cellSpursInitializeWithAttribute2` (`work/analysis/rpcs3_ref/cellSpurs.cpp:1405`)
is identical to WithAttribute except it adds `SAF_SECOND_VERSION`:

```
s32 cellSpursInitializeWithAttribute2(CellSpurs* spurs,
                                      const CellSpursAttribute* attr)
```

Checks: `attr != NULL`, `attr` 8-byte aligned, `attr->revision <= 2`. Then
`_spurs::initialize(..., flags | SAF_SECOND_VERSION, ...)`.

`SAF_SECOND_VERSION` means CellSpurs2:

| Property | CellSpurs1 | CellSpurs2 |
|---|---|---|
| object size | 4096 (`0x1000`) | 8192 (`0x2000`) |
| workloads | 16 | 32 (`SF1_32_WORKLOADS = 0x40` in `flags1` at 0x74) |
| extra state | - | `wklInfo2` at 0x1000, `wklF2` at 0x1200, `wklH2` at 0x1A00 |
| kernel entry | `CELL_SPURS_KERNEL1_ENTRY_ADDR` | `CELL_SPURS_KERNEL2_ENTRY_ADDR` |

### 6.3 Runtime compatibility

The runtime's guest BE layout (`libs/spurs/cellSpurs.c:407`) matches CellSpurs1
for the fields it uses:

```
0x60 wklFlag, 0x70 wklSignal1, 0x76 nSpus, 0x80 wklState1,
0xB0 wklEnabled, 0xB00 wklInfo1 (16 x 0x20)
SPURS_INST_SIZE = 0x1000
```

The runtime comment itself says: "The 8192-byte variant is CellSpurs2
(cellSpursInitialize*2* NIDs) ... clearing 0x2000 here overran the game's 4KB
heap block." That warning is about using the CellSpurs1 initializer on a 4KB
object; it is not a reason to skip the 0x2000 clear for a genuine CellSpurs2.
The fixer's alias currently:

```
memset(vm_base + spurs_ea, 0, 0x1000);   // not 0x2000
... writes CellSpurs1 fields only
```

For GT6's observed use (1 SPU, no workloads, job chain only), the SPURS1 subset
is sufficient for the chain/attach calls. It is **not** a complete CellSpurs2.
If the game later calls 32-workload/taskset APIs on `0x159D600`, the upper
0x1000 and `flags1` will be wrong.

The attribute layout is also not PS3-compatible:

| Field | Runtime `CellSpursAttribute` | PS3 (RPCS3) |
|---|---|---|
| nSpus | 0x00 | 0x08 |
| spuPriority | 0x04..0x23 | 0x0C |
| prefix | 0x24 | 0x15 |
| prefixSize | 0x34 | 0x24 |
| flags | 0x38 | 0x28 |
| size | 192 | 512 |

This works for GT6 because the attr is produced by the runtime's
`_cellSpursAttributeInitialize` and consumed by the runtime's
`cellSpursInitializeWithAttribute2` (same host layout). A title that fills the
attribute with guest code would be misread. Do **not** add RPCS3's
`attr->revision > 2` check without fixing the layout: `revision` would read the
runtime's `nSpus` field.

### 6.4 ABI/registration review

- The NID `0x30AA96C4`, the 2-argument signature, and the s32 return are correct.
- `ppu_sysprx.cpp:955-966` registers a ctx-aware wrapper:
  `ctx->gpr[3] = cellSpursInitializeWithAttribute2(r3, r4)`. The C function
  translates both guest EAs with `GUEST_PTR`, so the wrapper must pass raw EAs
  (it does).
- The generated `gt6/src/gen/ppu_hle_nids.cpp` does not contain the NID, so the
  runtime registration is currently the only one. The ctx table is checked
  before the generic NID table, so a future generated registration cannot
  override it.
- `ppu_sysprx_register()` is called from `gt6/src/main.cpp:707`, before guest
  execution, so the handler is live.
- The `GT6_SPURS_ATTR2_INIT_OFF` env gate is a useful A/B switch; default ON is
  the correct behavior for a title that calls the real API.
- Add the cheap 8-byte alignment check on `attr` (and return
  `CELL_SPURS_CORE_ERROR_ALIGN`). Do not add the `revision > 2` check until the
  host attribute layout is replaced with the PS3 one; as written it would read
  `nSpus` as `revision`.

**Verdict:** the alias is a reasonable first implementation for GT6 and fixes
the unresolved-NID gap, but it should be documented as a partial CellSpurs2 and
extended to `0x2000`/`SF1_32_WORKLOADS` if CellSpurs2 workloads are exercised.

---

## 7. Review of the fixer's working-tree change

### 7.1 Per-instance completion routing (`jc_signal_done`)

The diff records `spurs_ea` per `JcSlot` in `jc_register`, then copies only the
queues whose `s_spurs_event_queue_owner` matches the chain owner:

```
if (!s_legacy_route && jc && jc->spurs_ea && owner && owner != jc->spurs_ea)
    continue;
```

For GT6, q3 owner is the PDI instance (`0x70100000`) and q4 owner is the second
instance; the chain object `0x701AC000` creates/runs itself and attaches q4 with
the same `*(TOC-0x7C30)` CellSpurs EA. The filter removes q3 and leaves q4. This
is the root fix for the q3 crash.

Notes:

- If `jc` is NULL, `spurs_ea` is 0, or the queue owner is 0, the code falls back
  to broadcast. That keeps older titles working, but it means a queue attached
  before owner tracking can still receive a misrouted event. GT6's q3/q4 owners
  are set, so this does not affect the crash.
- `SPURS_JC_LEGACY_ROUTE` provides the A/B old behavior. Good.
- `jc_find(0)` currently returns the first free slot (`jc_ea == 0`). No caller
  passes 0 today, but add `if (!jc_ea) return NULL;` for safety.
- `jc_register` writes `jc_ea` before `spurs_ea`/`max_grab`. A concurrent reader
  could see a half-published record. In GT6 the create happens before Run and
  the walker, so this is latent, but publishing `jc_ea` last (or taking a small
  lock) is safer.
- `cellSpursDetachLv2EventQueue` clears the port mapping but does not remove the
  queue from `s_spurs_event_queue[]`. A detached queue can still receive
  completions until Finalize compacts the list. GT6 does not detach q3/q4 before
  the crash, but teardown ordering should be checked.

### 7.2 `maxGrabbedJob` bound (`jc_signal_done`)

The wrap:

```
if (job_index >= 0 && max_grab > 0 && (u32)job_index >= max_grab)
    d2 = (u32)job_index % max_grab;
```

prevents the q3/q4 OOB and is a strict improvement over the raw counter.

Caveat: on hardware `data2` is the job index **within the current grabbed
batch** (`0..queued-1`), not a global ordinal modulo the ring. The log's
`soc-job` chain is one job per guard lap (`GUARD, JOB, SYNC, NEXT`), so `queued`
may be 1 for each notify and the expected index may be 0 each lap, while `%16`
gives 0,1,2,...15,0,... . If the manager queues 16 jobs per batch, `%16` matches
exactly. The log does not print the manager's `queued` field, so this must be
confirmed with a one-line log (`[manager+0x4284]`) or by observing the q4
callback indices. A more faithful fix is:

- reset the completion ordinal to 0 when `jg_wait()` returns at a guard (new
  batch), and at the start of `jc_execute`;
- keep the `% max_grab` bound as a final safety net.

If `max_grab == 0` (a malformed/unregistered chain), the current code falls back
to the raw ordinal. Add a fallback (`d2 = 0`) so an unknown chain cannot OOB the
receiver.

### 7.3 `g32` diagnostic bounds (`ps3_indirect_call_impl`)

The reporter now checks:

```
end = (uint64_t)ea + 4;
if (ea < 0x10000u || end > 0x100000000ull) return 0;
if (ppu_vm_size && end > ppu_vm_size) return 0;
```

and prints `CHAIN ... (obj not a guest object -- chain skipped)`. This is exactly
the check that would have prevented the fatal fault. It is **hardening**, not the
root fix: with it, the unresolved call at `0x007F454C` is logged and skipped, the
thread unlocks and continues, and the process stays alive, but the q3 handler is
still receiving semantically wrong events. Keep it.

### 7.4 `vm_oob` wrap check

The inline bounds check now rejects an access whose end wraps past 4 GB:

```
if (a > 0xFFFFFFFFu - (n - 1)) return vm_oob_report(a, n);
```

This protects lifted loads/stores at the last bytes of the guest space and logs
`[vm] OOB access`. It is consistent with the runtime's existing zero-fill OOB
policy. It does not protect unchecked HLE `vm_read32`/`vm_write32` calls (the
`g32` fix is separate). It can turn a genuine guest top-of-space read into a
zero, but the report makes it visible. Acceptable hardening; not the root fix.

### 7.5 lwmutex range check

`lwm_addr_ok` is added to lock/fast/trylock/unlock:

```
end = (uint64_t)a + 0x18;
if (a < 0x10000u || end > 0x100000000ull) return 0;
if (ppu_vm_size && end > ppu_vm_size) return 0;
```

This is good defensive hygiene and would prevent a host fault if a bad lwm ever
reached the HLE. It is **not** the observed crash: the fault was the reporter
reading `r3=0xFFFFFFFF`, and the lwm on the path (`0x16752A8`) is valid. If the
fixer presents this as the fix, that is a misdiagnosis.

Gaps:

- `sys_lwmutex_create` (`ppu_sysprx.cpp:121`) still does six `vm_write32` calls
  with no validation. Add `lwm_addr_ok` there too.
- `sys_lwcond_wait` reads `lwmutex = vm_read32(lwcond+0)` and then dereferences
  it without a check. Validate that EA.
- The check allows `0xFFFF0000` (end `0xFFFF0018` <= 4 GB); the fault-commit VEH
  will commit that page and the runtime will treat zeroes as a free lock. If a
  stricter error is wanted, query the committed state (`VirtualQuery`) or
  `vm_is_valid_addr`, but that risks rejecting valid lazily-mapped mmapper
  locks. The wrap check is the safe minimum.

### 7.6 Does the change mask a guest bug?

No. The OOB index is generated by the **runtime** (`jc_signal_done`), not by the
guest. The q3 handler table is 16 entries; the q4 callback table is indexed by
the same job index and is bounded by the chain's `maxGrabbedJob` (16 here). The
owner routing and bound restore that contract. The `g32`/`vm_oob` changes are
visibility/hardening. The only masking risk is the general `vm_oob` zero-fill,
which is logged.

---

## 8. Thread-exit containment

`gt6/src/main.cpp:463-468` has:

```
if (getenv("GT6_CRASH_THREAD_EXIT")) {
    fprintf(stderr, "[GT6] GT6_CRASH_THREAD_EXIT: ending only this host thread\n");
    fflush(stderr); fflush(stdout);
    ExitThread(0xDEADBEEFu);
}
```

This is executed on the faulting PPU host thread (the unhandled exception filter
runs on that thread). It is **not** equivalent to `sys_ppu_thread_exit`.

### 8.1 What the normal path does

`sys_ppu_thread_exit` (`sys_ppu_thread.c:614`) marks the thread FINISHED,
signals `finish_event`, then `longjmp`s to `ppu_host_thread_proc`. The thread
proc (`sys_ppu_thread.c:241-280`) calls `ps3_tprof_thread_exit`, stores the exit
status, and either frees the slot/closes handles (non-joinable) or sets FINISHED
and signals the join event. `sys_ppu_thread_join` (`:658`) waits on
`finish_event` forever if it is never signaled.

### 8.2 What `ExitThread` bypasses

- no `longjmp`/thread-proc cleanup;
- slot stays `PPU_THREAD_STATE_RUNNING`; `host_thread` handle stays open;
  `host_tid` becomes stale; the slot cannot be reused;
- `finish_event` is never signaled, so `sys_ppu_thread_join(tid=15)` blocks
  forever (the thread was created with flags=1, i.e. joinable);
- `g_hle_inflight[15]` and `prof_pc` remain stale;
- the fault is inside `0xA569D0`'s critical section: the lwmutex at
  `this+0x98 = 0x016752A8` is locked at `0xA56A14` and would be unlocked at
  `0xA56A40`. Killing the thread leaves the `g_lwm` slot `state=1` and the guest
  owner field 15 (plus `holder=15` when `PS3_LWMUTEX_TRACE` is on). A later
  lock, unregister (`0xA56A68`), or destructor on the same object blocks
  forever;
- any GCM/SPU/SRWLOCK/CRITICAL_SECTION held at the fault is not released by
  `ExitThread`. The observed fault holds the event-handler lwmutex, not a GCM
  lock, but the option is generic; a render-thread fault under the FIFO lock
  would wedge the presentation path;
- the q3 queue loses its only consumer; producers can fill it and get EBUSY.

It does not corrupt VM memory directly: the fatal access is a read, and
`fault_commit` committing a page is harmless. The damage is to guest/host
synchronization state and the PPU thread table.

### 8.3 Verdict

The crashguard run (`CONTINUE-HERE.md`, 14:49) proves the containment lets the
process reach `takeflip` and `CLEAR_SURFACE`, which is useful observation. It is
not a fix and must not be the shipped path. If containment is needed for
diagnosis:

- unwind through the existing `s_exit_jmp`/thread-proc path so the slot,
  `finish_event`, and handles are cleaned;
- explicitly release the lwm slot only if the dead thread is the recorded
  holder, with a loud warning;
- accept that arbitrary guest/GCM/SPU locks cannot be safely force-released;
  the root fault must be prevented.

---

## 9. `sys_lwmutex_lock` validation

Although it is not this crash, the fixer's check is worth keeping. The safe
guest-address range for `sys_lwmutex_t` (24 bytes, 4-byte fields) is:

```
0x00010000 <= lwm  and  lwm + 0x18 <= 0x100000000
```

(and `lwm + 0x18 <= ppu_vm_size` when `ppu_vm_size != 0`). Optionally require
4-byte alignment (`lwm & 3 == 0`); do not require 8 unless the title's ABI does.

- All valid lwmutexes in this run pass: `0x016752A8` (event handler),
  `0x7FFD4AE0`/`0xCFEFF288` (stack), `0x701AC200` (SPURS memory).
- `0xFFFFFFFF` fails (`end = 0x100000017 > 4 GB`). This is the value the
  reporter tried to dereference; it was never an lwmutex argument on the crash
  path.
- `0xFFFF0000` passes the range check; the VEH commits it and the runtime sees a
  zeroed lock. To reject it, query committed state, but that can reject valid
  lazy mappings.
- `0x00000000..0x0000FFFF` is rejected (null page); PS3 user space starts at
  `0x10000`.

Error code: `CELL_ESRCH` (`0x80010005`) is acceptable and matches the runtime's
existing invalid-object convention and GT5P's `FAIL -> ESRCH` log. `CELL_EFAULT`
(`0x8001000D`) is the more literal lv2 "bad address" error. Either is safe for
valid locks because the check only fires out of range. Return before any
`vm_read32`.

Caveat: the guest wrapper `0xA43378` retries `sys_lwmutex_lock` on any nonzero
return, so an invalid lwm becomes a guest spin rather than a host crash. The
first 8 failures are logged by the guard; after that it is silent. That is still
preferable to an AV, but the caller must not pass bad pointers.

Apply the same check to `sys_lwmutex_create` and to the lwmutex read in
`sys_lwcond_wait`. `sys_lwmutex_destroy` is a no-op and safe.

---

## 10. Safest recommended fix (ordered)

1. **Route job-chain completions per CellSpurs instance** (fixer's owner
   tracking). This is the root fix for q3: the `soc-job` chain belongs to the
   q4 audio manager, not the PDI `SpuEventHandler`.
   - Add `spurs=0x%08X` to `cellSpursAttachLv2EventQueue` and
     `cellSpursCreateJobChain*` logs to prove the owner in the next run.
   - Ensure `jc->spurs_ea` is set for both Create forms and that a queue
     attached before owner tracking does not silently broadcast once a chain
     owner is known.
2. **Keep the completion ordinal inside the receiver's table.** Prefer resetting
   the ordinal at each guard/batch boundary; keep `% maxGrabbedJob` as a hard
   bound and use `d2=0` when `max_grab==0`. This protects both the q3 16-entry
   handler table and the q4 16-slot callback table.
3. **Keep the `g32` reporter bounds.** It turns the fatal reporter fault into a
   visible unresolved call. It is not a substitute for 1/2.
4. **Implement `cellSpursInitializeWithAttribute2` properly enough for the
   object.** The current alias is acceptable for GT6's observed 1-SPU instance;
   extend it to clear `0x2000` and set the CellSpurs2 flags if 32-workload APIs
   are reached. Do not add PS3-layout revision checks to the runtime's host
   struct without fixing the attribute layout.
5. **Keep the lwmutex range checks as defence, not as the fix.** Add create and
   lwcond coverage. Return `CELL_ESRCH` (or `CELL_EFAULT`) before any read.
6. **Do not ship `GT6_CRASH_THREAD_EXIT`.** Use it only to observe the next
   stage, and document that it leaves the `this+0x98` lwmutex held and the PPU
   slot RUNNING.

A correct run after 1+2+3+4 should show:

- `[cellSpurs] Initialize ... ea=0x159D600 nSpus=1` instead of
  `[hle] unresolved NID 0x30AA96C4`;
- `[cellSpurs] chain 0x701AC000 job N done -> event queue 4`, with no
  `-> event queue 3` lines;
- q3 `SpuEventHandler` stays blocked in `event_queue_receive(q=3)`; q4
  `sgx-audio-thr` receives `data2` in `0..15` and runs the matching callback.
  Log the manager's `queued` field (`+0x4284`) to confirm whether the exact
  batch ordinal (0..queued-1) is needed rather than the global `%16`;
- no `bctr to NULL from func_00A569D0`, no `unresolved indirect call ->
  0x007F454C`, no `faulted in guest page 0xFFFF0000`, no access violation;
- the process should not need `GT6_CRASH_THREAD_EXIT` to stay alive.

Optional A/B: `SPURS_JC_LEGACY_ROUTE=1` restores the old broadcast and should
reproduce the q3 crash; `SPURS_JC_INDEX_RAW=1` restores the raw index and should
reproduce the OOB if the route still reaches q3/q4.

---

## 11. Evidence index

| Item | Path / address |
|---|---|
| Crash run stdout | `work/lab1_final_run.log` (VM base, q3/q4 attach, chain maxGrab=16) |
| Crash run stderr | `work/lab1_final_run.err:138,154,764-766,259240-259261` |
| Event probe | `work/spu_evt_probe.err:466-471,3235-3250` |
| Thread create | `[SYS] ... tid=15 ... entry=0x014E14C0 arg=0x1675210` |
| Run loop / id extract | `0xA564EC`, `0xA56554`, `0xA565A0` |
| Table init / register / dispatch | `0xA567C8`, `0xA565C8`, `0xA569D0` |
| Vtable / OPDs | vtable `0x148A7E8`; OPDs `0x14E14B8`, `0x14E14C0`, `0x14E14D8` |
| q4 consumer | `0x82025C`, callback index `0x8203C0`, loop `0x82047C` |
| `cellSpursInitializeWithAttribute2` call | `0x7EE690`; object `0x159D600`; NID `0x30AA96C4` |
| Reporter fault PC | `ps3_indirect_call_impl+0x1D08` (`RVA 0xAFB488`) |
| `sys_lwmutex_lock` PC | `RVA 0xB079D0` (not the fault) |
| Crash metadata bug | `gt6/src/main.cpp:413-416,449,453-456,463-468` |
| Thread cleanup | `sys_ppu_thread.c:241-280,614-656,658-...` |
| Fixer diff | `libs/spurs/cellSpurs.c:601-612,2384-2400,2723-2780`; `ppu_sysprx.cpp:129-137,955-966`; `ppu_loader.cpp:1383-1395,3077-3090` |
