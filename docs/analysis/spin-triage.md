# Spin triage — GT6 native port (2026-10-31)

**Scope:** the `0x009F9380` stuck-loop abort and the current black-window hang
(main parked in `func_00F9AC18 -> func_00A301A8 -> func_009F7C60`).
Read-only analysis: `work/bin/EMAIN.elf`, current `gt6/generated/ppu_recomp_022.cpp`,
and the run logs. No build was performed.

Evidence files:

- `work/agent_spin/disasm_9F92CC.txt` — full `func_009F92CC` / jump table.
- `work/agent_spin/disasm_filedev_pump.txt` — `func_009F83D4`, `func_009F8534`,
  `func_009F7FF0`, `func_009F7F94`.
- `work/agent_spin/disasm_main_chain.txt` — `func_009F74E4`, `func_009F88B4`,
  `func_009F7A84`, `func_009F7C60`, `func_00A301A8`.
- `work/agent_spin/jumptable_9F9348.txt` — 14 decoded cases.
- `work/agent_spin/filedev_vtable.txt` — `PDISTD::FileDevice` vtable map.
- `work/agent_spin/evidence_notes.md` — exact log lines / addresses.

---

## TL;DR

1. **`0x009F9380` is real code**, not garbage. It is case 0/1 of a 14-entry
   **relative jump table at `0x009F9348`** inside `func_009F92CC`. The lifter
   did not discover the table because its base is an **absolute constant**
   (`lis r9,0xA0; addi r9,r9,-0x6CB8`), while
   `discover_jump_tables()` only resolves TOC-relative bases. The `bctr`
   therefore lifted to `ps3_indirect_call(ctx); return;`
   (`gt6/generated/ppu_recomp_022.cpp:143228`). `0x9F9380` is not a function
   entry, so the call does nothing — the state-machine case never runs.

2. **Main is not in the renderer.** It is in `PDISTD::FileDevice` shutdown:
   `func_009F74E4 -> func_009F88B4 -> func_009F7A84 -> func_009F7C60`.
   `func_009F7C60` sets `[dev+0xAC] = 1`, signals the worker lwcond at
   `dev+0x70`, then calls **`sys_ppu_thread_join`** (`sc 44` via
   `func_00A301A8`) on **tid 14**, whose thread object is at `[dev+0xA0]`
   (the tid is `[thread_obj+0]`).

3. The join is a **correct HLE wait**. It never returns because **tid 14 is
   already wedged inside the vtable[0x74] handler `func_009F8534`**, blocked on
   a lightweight mutex built from a **space-filled request buffer**:
   request `0x016810E0`, `[req+8] = 0x20202028`,
   `LWM-BLOCK lwm=0x20202028 owner=0 recur=22661744`.
   The stop flag is set too late; the worker is no longer in the loop that
   checks it.

4. `0xF9AC18` in `[hostchain]` is a **false positive**. It is the cellSailRec
   import thunk for NID `0xF57D74E3`; there is no HLE log for it, and it is not
   part of this call chain. The host-stack walker resolves native wait frames
   to the nearest guest function. The reliable guest frames are `0x00A301A8`
   (`sys_ppu_thread_join`) and `0x009F7C60`.

**Answer to (a)/(b)/(c):** closest to **(c)**, but the broken primitive is not
the HLE event queue/timer. The join is correct. The thread being joined is
deadlocked on a **corrupted guest lwmutex/request descriptor**. No normal
event releases it. It is not a sysutil dialog wait and not an intentional
boot wait.

---

## 1. The `0x9F9380` target: legitimate code, mis-lifted jump table

### 1.1 It is a switch case, not a garbage pointer

`0x009F9380` disassembles as valid PowerPC:

```text
009F9380: lwz   r11,0(r31)        ; this->vtable
009F9384: clrldi r30,r31,0x20
009F9388: mr    r4,r29            ; request
009F938C: mr    r3,r30            ; this
009F9390: lwz   r9,0x54(r11)      ; vtable slot 0x54
009F9394: lwz   r0,0(r9)          ; OPD code
009F9398: lwz   r2,4(r9)          ; OPD toc
009F939C: mtctr r0
009F93A0: bctrl
```

The dispatcher in `func_009F92CC`:

```text
009F9328: lis   r9,0x00A0
009F932C: rldic r11,r0,2,0x1e
009F9330: addi  r9,r9,-0x6CB8      ; r9 = 0x009F9348  (table base)
009F9334: lwzx  r0,r11,r9
009F9338: extsw r0,r0
009F933C: add   r0,r0,r9           ; case = table_base + offset
009F9340: mtctr r0
009F9344: bctr
```

The table at `0x009F9348` decodes to 14 cases:

| index | target |
|---|---|
| 0,1 | `0x009F9380` |
| 2,3 | `0x009F93D0` |
| 4 | `0x009F93EC` |
| 5 | `0x009F9428` |
| 6 | `0x009F9444` |
| 7 | `0x009F9460` |
| 8,9 | `0x009F947C` |
| 10,11 | `0x009F9498` |
| 12 | `0x009F94D0` |
| 13 | `0x009F94B4` |

All targets are inside `func_009F92CC` (`0x009F92CC..0x009F95EC`) and share the
epilogue at `0x009F94F0`.

### 1.2 Why the lifter missed it

`third_party/ps3recomp/tools/ppu_lifter.py::discover_jump_tables()` resolves
the table base only from a TOC load (`lwz/ld ...,disp(r2)`), or a two-level
global (`lwz ...,d1(r2); lwz ...,d2(rMid)`). This dispatcher uses a link-time
constant:

```text
lis  r9,0x00A0
addi r9,r9,-0x6CB8
```

so `_bases` stays empty and the dispatcher is silently skipped. The generated
function contains the case bodies but no `switch`:

```c
/* ppu_recomp_022.cpp:143228, func_009F92CC */
ctx->ctr = ctx->gpr[0];
ps3_indirect_call(ctx); return;
/* TODO: .word 0x00000038 */;   // table bytes decoded as data
...
```

`ps3_indirect_call_impl()` only does an exact function-table lookup
(`ppu_loader.cpp:2861`). `0x9F9380` is not in `function_table` (grep of
`ppu_recomp_table.cpp` confirms), so the call logs
`unresolved indirect call -> 0x009F9380` and returns. The case body is never
executed.

**Consequence:** the pending request at `[dev+0x58]` is never completed; the
FileDevice pump `func_009F83D4` keeps re-entering `func_009F7B3C ->
func_009F92CC`. This is a logical infinite loop. It is also a frame leak: the
early `return` skips the `addi r1,r1,0xB0` epilogue at `0x009F94F0`, so the
guest stack pointer is not restored on that path.

### 1.3 What the pump is waiting on

`PDISTD::FileDevice` vtable (vptr `0x014882B0`, RTTI
`N6PDISTD10FileDeviceE`):

| slot | function | role |
|---|---|---|
| `+0x48` | `func_009F83D4` | worker run loop |
| `+0x4C` | `func_009F7B3C` | dispatch request at `[dev+0x58]` |
| `+0x50` | `func_009F92CC` | request state machine |
| `+0x74` | `func_009F8534` | dispatch request at `[dev+0x64]` |

`func_009F83D4`:

```text
009F8400: mr   r3,r29          ; r29 = dev+0x70
009F8404: bl   0xA21D50        ; lwmutex_lock + sys_lwcond_wait + unlock
...
009F8434: lwz  r0,0x58(r31)    ; pending request?
009F8440: bne  0x9F840C
...
009F8478: cmpwi cr7,r11,0      ; r11 = [dev+0xAC] stop flag
009F847C: beq  0x9F8400        ; still running -> wait
```

`func_00A21D50` is a **legitimate blocking wait**: `sys_lwmutex_lock`
(`func_00A42DE8`), `sys_lwcond_wait` (`func_00A21CBC` -> `func_00A4305C` ->
import `0xF99A98`, NID `0x2A6D9D51`), then `sys_lwmutex_unlock`
(`func_00A42D3C`). `func_009F7C60` signals it with `func_00A21E04`.
So the loop is an event pump, not necessarily a tight spin.

The target `0x9F9380` is hit when `[req+0x84]` is 0 or 1. The state machine
then calls vtable `+0x54` (base implementation `func_009F810C` sets
`[req+0xB0]=2`, returns 0) and should complete the request. Because the case
body never runs, the request stays pending forever.

---

## 2. Current main-thread wait: join on tid 14

### 2.1 The chain, with roles

| address | function | what it does |
|---|---|---|
| `0x00014518` | `func_00014518` | boot stage after `0x14450`; calls `0x9F74E4` |
| `0x009F74E4` | `func_009F74E4` | global FileDevice/FileSystem shutdown wrapper |
| `0x009F88B4` | `func_009F88B4` | iterates the registered FileDevice list (`0x15DE908`), calls `0x9F7A84` |
| `0x009F7A84` | `func_009F7A84` | `~FileDevice`: calls vtable `+0x1C` (`0x9F7C60`), then `+0x0C` |
| `0x009F7C60` | `func_009F7C60` | `[dev+0xAC]=1`; signal `dev+0x70`; join thread object `[dev+0xA0]` |
| `0x00A301A8` | `func_00A301A8` | `ld r3,0(r3); li r11,0x2C; sc` = `sys_ppu_thread_join` |
| `0x00F9AC18` | cellSailRec import thunk | **not this chain**; false host-stack resolution |

`func_009F7C60` generated code:

```c
/* ppu_recomp_022.cpp:141425 */
vm_write8(ctx->gpr[28] + 0xAC, 1);          // stop flag
func_00A21E04(ctx);                         // signal lwcond dev+0x70
ctx->gpr[3] = vm_read32(ctx->gpr[28] + 0xA0); // thread id
func_00A301A8(ctx);                         // sys_ppu_thread_join
```

`func_00A301A8`:

```text
00A301D4: ld   r3,0(r3)      ; thread id
00A301D8: li   r11,0x2C
00A301DC: sc                 ; sys_ppu_thread_join
00A301E0: beq  cr4,0xA30200  ; success -> return
00A301E4: bl   0xA2F328      ; log/retry
```

The joined thread was created by `func_009F7CB4`/`func_009F7D34`:
thread entry OPD `0x014DF558` -> `func_009F8078`, argument `this`
(the FileDevice), thread id stored at `[dev+0xA0]`.
`func_009F8078` calls vtable `+0x48` -> `func_009F83D4`, the pump above.

**Normal release condition:** `[dev+0xAC] != 0` must be observed at
`0x9F8478`, which returns from `func_009F83D4`; the worker thread then returns
from `func_009F8078` and `sys_ppu_thread_join` completes. The lwcond signal at
`dev+0x70` only wakes the wait; the flag is the actual exit condition.

### 2.2 Why it does not release

In the current run (`work/gt6.log`, 13:00), tid 14 takes the **second** request
path before main sets the stop flag:

```text
[ppu] unresolved indirect call -> 0x009F9380 (tid=14 lr=0x009F9310)
[null-call] ... near lr=0x009F7FCC, tid=14  r3=016810E0 ...
[GSTACK:nc] ... r28=20202020 r29=20202020 r31=20202020 r30=20202020
[ppu] bctr to NULL from func_009F7F94+0x2AB ... (r3=0x016810E0 r4=0x20202064)
[LWM-BLOCK] tid=14 lwm=0x20202028 owner=0 recur=22661744 tmo=0us
...
[WAIT] ppu_thread_join(tid=14)
```

Log anchors in `work/gt6.log`: null call `:1332`, GSTACK `:1333`, first garbage
vcall `:1345`, join `:1418`, LWM block `:1403`.

The reachable path is `func_009F83D4` at `0x9F8448`:

```text
009F8448: lwz   r0,0x64(r31)   ; second request slot
009F8454: beq   0x9F8478       ; zero -> no work
009F8458: bne   0x9F8478       ; [dev+0xAC] != 0 -> shutdown
009F845C: lwz   r9,0(r31)      ; vtable
009F8460: lwz   r11,0x74(r9)   ; vtable[0x74] = func_009F8534
009F8470: bctrl
```

`func_009F8534` then does:

```text
009F854C: lwz   r9,0x64(r3)    ; r9 = [dev+0x64]
009F8554: lwz   r31,0(r9)      ; r31 = *[dev+0x64]  = 0x016810E0
009F8558: mr    r3,r31
009F855C: bl    0x9F5A14       ; lock [r31+8]
```

`func_009F5A14` locks `req+8`; for `req=0x016810E0` that is `0x20202028`.
Because the LWM contents are garbage, that first lock does not establish a
meaningful owner. `func_009F7FF0` then runs `func_009F7F94` (the null vtable
call) and locks the same field again, where the HLE lightweight-mutex layer
finally blocks:

```text
[LWM-BLOCK] tid=14 lwm=0x20202028 owner=0 recur=22661744 tmo=0us
```

**Exact release condition:** main's join returns only when tid 14 returns from
`func_009F8078` -> `func_009F83D4`. The normal path is the `0x9F8478` check of
`[dev+0xAC] != 0`. In this run tid 14 never reaches that check again; it is
inside `func_009F8534`/`func_009F7FF0`, blocked on
`sys_lwmutex_lock(0x20202028)`. The only ways out are (a) the garbage LWM
being unlocked by an owner that does not exist, or (b) a diagnostic guard /
forced teardown. No timer, event queue, SPU job, or sysutil callback will
release it.

`0x20202028` is not a valid lock word — it is four ASCII spaces plus 8. The
request buffer is filled with `0x20`:

```text
req = 0x016810E0
[req+0x00] = 0x20202020
[req+0x08] = 0x20202028
[req+0x5C] = 0x20202020
[req+0xB0] = 0x20202020
```

`func_009F7F94` reads `[req+0x5C]` = `0x20202020`, treats it as an object,
loads `[0x20202020]` (= 0) as a vtable, then `[0+8]` (= 0) as the method and
does a `bctrl` to 0. That is the null call. The `garbage vcall -> 0x20202020`
lines in the log are the same poison. The null call is a **symptom**; the
block is the lwmutex at `req+8`.

Note: the `GSTACK:nc` chain also prints `func_009F92CC+0x224` (0x009F94F0).
That epilogue is unreachable in the current generated file because the
dispatcher does `ps3_indirect_call(ctx); return;`. Treat that word as a stale
stack/vtable value; the reachable caller of `func_009F7FF0` is
`func_009F8534` at `0x9F85A0`.

Because tid 14 is inside `func_009F8534`, it never returns to the
`func_009F83D4` loop, so it never observes `[dev+0xAC] = 1`. Main's
`sys_ppu_thread_join(tid=14)` waits forever. The stop flag and lwcond signal
are correct but too late.

`0x016810E0` is a `.bss` buffer, not a heap request. It is filled with spaces
(0x20), which strongly suggests a **name/string buffer** was stored where a
`FileDevice` request descriptor was expected, or a request descriptor was
overwritten by a space-padded file name. This is a second, independent bug
from the jump table, though the mis-dispatch may be what leaves the request
slot in this state.

### 2.3 Is this (a), (b), or (c)?

- **(a) intentional boot/loading wait?** No. The join is in the FileDevice
  destructor path (`func_009F7A84`), not a "wait for a loader job" call. The
  worker should exit when the stop flag is set. It cannot because it is blocked
  in the request handler.
- **(b) cellSysutil dialog callback never posted?** No. There is no
  `cellSysutil`/dialog call in the chain. `0xF9AC18` is a false host-stack
  frame.
- **(c) broken HLE wait?** Only in the sense that the wait never wakes. The HLE
  `sys_ppu_thread_join` is implemented correctly (`WaitForSingleObject` on the
  thread's `finish_event`, `sys_ppu_thread.c:658`). The broken part is the
  **guest-side lwmutex** built from `0x20202028`; the HLE accepts it and
  blocks.

---

## 3. The `bctr to NULL` families

### 3.1 `func_009F7F94` / `func_009F7FF0` — fatal in effect, but a symptom

`func_009F7FF0(req)`:

```text
009F8008: lwz   r0,0xB0(r3)
009F8014: cmpwi cr7,r0,0
009F8020: beq   cr7,0x9F8028
009F8024: bl    0x9F7F94        ; if [req+0xB0] != 0
...
009F8028: addi  r29,r3,8
009F8034: bl    0xA42DE8        ; lock req+8
...
009F8038: lwz   r11,0(r31)      ; vtable
009F8040: lwz   r9,0x20(r11)
009F8050: bctrl                 ; vtable[0x20]
009F8058: bl    0xA42D3C        ; unlock
```

With `req=0x016810E0`, `[req+0xB0]` is `0x20202020` (nonzero), so it calls
`func_009F7F94`. That reads `[req+0x5C]=0x20202020`, then a null vtable slot,
and does `bctrl` to 0. Then `func_009F7FF0` locks `req+8=0x20202028` and
blocks. These calls are **required** in the normal request-completion path;
they must not be blanket-no-op'd. The correct fix is to prevent the
space-filled request from entering this path.

### 3.2 `func_00A19218` — repeated, non-blocking

`PDISTD::KeyboardManager` singleton at `0x0164B020`; vtable `0x0148A3F8`
(RTTI `N6PDISTD15KeyboardManagerE`). `func_00A19178` initializes it and
writes the vptr `0x0148A3F8`, but the runtime dump shows `r9=0x0000A3F8`
(low 16 bits only) and `[r9+0x10]=0`. The slot is not actually null in the
static vtable (`0x14E1100 -> 0x00A4D9B4`), so the live vptr is truncated or
partially overwritten. The calls repeat on tid 27 but **do not block boot**;
the run continues to open/read files. This is a separate partial-initialization
bug, not the spin blocker. Investigate the writer of `0x0164B020` / the
truncated vptr later.

### 3.3 `func_00B3A868` / `func_00AF9484` / `func_00AF92EC` / `func_00AF97F8`

These are calls through **zeroed .data function-pointer slots**:

- `0x0155A760 + 0x34`, `+0x6C` (inside `func_00B3A868`)
- `0x0155A790` (inside `func_00AF9484`)
- `0x0155A780` (inside `func_00AF9484`)

The slots are zero in the ELF and no direct writer is visible in the lifted
code. They look like optional PDI callbacks/hooks (function-pointer table, not
C++ vtables; the code loads `ctr`/`r2` directly from them). The calls happen
once during PDI file-system startup; the run then opens `PDIPFS/K/PD.fdupm`,
`GT.VOL`, and reads 32 KB chunks, so they are **not the immediate blocker**.
Because the runtime returns with `r3` untouched, a caller that expects an
allocation/result could be misled; do not blanket no-op. Find the intended
initializer if the feature matters.

---

## 4. Smallest concrete fix

### 4.1 Preferred: absolute jump tables in the lifter

File: `third_party/ps3recomp/tools/ppu_lifter.py`
Function: `discover_jump_tables()`
Lines: `_bases = []` at 4604, `_bases.append(...)` at 4735,
`if not _bases or not toc` at 4737, table read at 4824-4836.

Add a constant-base resolver and a sixth `_bases` element:

```python
def _const_reg(insns, reg, before):
    """Fold lis/li + addi/addis/ori/oris definitions of reg before `before`."""
    for w in reversed([x for x in insns if x.addr < before]):
        a = [s.strip() for s in w.operands.split(',')]
        if not a or a[0] != reg or w.mnemonic.startswith(('st', 'lf')):
            continue
        try:
            if w.mnemonic == 'lis' and len(a) == 2:
                return (int(a[1], 0) & 0xFFFF) << 16
            if w.mnemonic == 'li' and len(a) == 2:
                return int(a[1], 0) & 0xFFFFFFFF
            if w.mnemonic == 'addi' and len(a) == 3 and a[1] == reg:
                b = _const_reg(insns, reg, w.addr)
                return None if b is None else (b + int(a[2], 0)) & 0xFFFFFFFF
            if w.mnemonic == 'addis' and len(a) == 3 and a[1] == reg:
                b = _const_reg(insns, reg, w.addr)
                return None if b is None else (b + (int(a[2], 0) << 16)) & 0xFFFFFFFF
            if w.mnemonic in ('ori', 'oris') and len(a) == 3 and a[1] == reg:
                b = _const_reg(insns, reg, w.addr)
                if b is None:
                    return None
                v = int(a[2], 0) & 0xFFFF
                return (b | (v << 16)) if w.mnemonic == 'oris' else (b | v)
        except ValueError:
            return None
        return None
    return None
```

Then, in the per-candidate definition scan (before the final `break`):

```python
elif w.mnemonic in ('lis', 'li', 'addi', 'addis', 'ori', 'oris'):
    v = _const_reg(win_cand, cand, w.addr)
    if v is not None and text_lo <= v < text_hi and (v & 3) == 0:
        r_base, abs_base = cand, v
```

Extend `_bases` to `(r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base)`,
and resolve:

```python
if abs_base is not None:
    table_base = abs_base
else:
    table_base = _read_ptr(cand + disp, base_is_ld)
    ...
```

Keep the existing `lwzx + add` shape check, the in-text target validation, the
compare-derived count, and the structural end-of-table check. For
`func_009F92CC` this yields 14 cases and the switch emission at
`ppu_lifter.py:2237`:

```c
switch ((uint32_t)ctx->ctr) {
case 0x009F9380u: goto loc_009F9380;
case 0x009F93D0u: goto loc_009F93D0;
...
default: ps3_indirect_call(ctx); return;
}
```

All 14 targets are inside `func_009F92CC`, so the switch is self-contained and
the shared epilogue at `0x009F94F0` is restored normally.

**Why not a runtime mid-function dispatch?** `ps3_indirect_call` only knows
function entries. Mapping `0x9F9380` to the enclosing `func_009F92CC` would
re-run the prologue and corrupt the register/stack state. A mid-function
tail-entry wrapper is also wrong here: the case body ends at the shared
epilogue and would return twice (once from the wrapper, once from the original
`func_009F92CC`). The switch is the correct lift.

### 4.2 If the join still hangs: poison-request guard (diagnostic, not final)

After the jump-table fix, if `sys_ppu_thread_join(tid=14)` still appears,
the space-filled request at `[dev+0x64]` is independent. Add a **validity
check before locking**, in `func_009F8534` (lifted
`ppu_recomp_022.cpp:142129`, or a post-lift patch):

```c
uint32_t node = vm_read32(ctx->gpr[3] + 0x64);
uint32_t req  = node ? vm_read32(node) : 0;
if (!req || req < 0x10000u || req >= 0x40000000u ||
    vm_read32(req) == 0x20202020u) {
    vm_write32(ctx->gpr[3] + 0x64, 0);   /* drop the already-garbage request */
    goto loc_009F85C4;                    /* epilogue */
}
```

This lets the pump observe `[dev+0xAC]` and the join complete, but it **skips
a request**. Use it only to confirm the next stage; it hides the producer bug.

An alternative, lower-touch guard is in the HLE lightweight-mutex path:
reject a guest LWM whose fields are poison (`0x20202020` fill, or
`recur > 0x100000`) with `CELL_ESRCH` and a `[lwm-poison]` log. That avoids
the infinite block but lets `func_009F7FF0` continue with a bad request; the
runtime's garbage-vcall guard then no-ops the subsequent calls.

**Root fix for the request:** write-watch the producer.
`dev` was `0x7005C000` in the earlier stuck dump, so watch `0x7005C064` and
`0x016810E0`:

```powershell
$env:GT6_GUARD="7005C064:0"   # or 16810E0:0
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_spin\guard_req.log
```

The guard logs the faulting guest function and call stack. The target is a
4 KB page, so filter for the watched word. This identifies whether a
name/string buffer is being stored into the request slot.

### 4.3 Do not use as a fix

- `PPU_STUCKMAX=0` only silences the guard; the loop and the join remain.
- Blanket no-op of null calls (`PS3_NULL_CALL=0` or a global "return 0") hides
  required calls and leaves state incomplete.
- Mapping mid-function targets to the enclosing function in
  `ps3_indirect_call` is unsafe (prologue re-entry / double return).

---

## 5. Ranked hypotheses

| rank | hypothesis | evidence | status |
|---|---|---|---|
| 1 | Absolute jump table in `func_009F92CC` not discovered; case bodies unreachable | table at `0x9F9348`, `lis/addi` base, generated `ps3_indirect_call; return`, no `0x9F9380` in function table | **proven** |
| 2 | Early `return` at the dispatcher leaks `0xB0` of guest stack / skips epilogue | `0x9F92CC` prologue `stdu -0xB0`; no `addi r1,+0xB0` on the unresolved path; repeated 2000× | **high** (consequence of 1) |
| 3 | Space-filled request `0x016810E0` enters `func_009F8534`; `req+8=0x20202028` deadlocks tid 14 | `[LWM-BLOCK] lwm=0x20202028 owner=0 recur=22661744`; `r28..r31=0x20202020`; null vtable at `[req+0x5C]` | **proven** (current black-window blocker) |
| 4 | `func_00A19218` KeyboardManager vptr is truncated to `0xA3F8` | `r9=0000A3F8`, slot 0; static vtable slot is valid | **high** (separate, non-blocking) |
| 5 | Zeroed PDI function-pointer slots at `0x155A760+0x34/+0x6C`, `0x155A780/90` are optional hooks | calls happen once; boot continues to open/read files | **medium/low** (not the blocker) |

---

## 6. Next steps

1. Apply the `discover_jump_tables` patch, relift EMAIN, rebuild (owner does
   this; no build was run here). Confirm `func_009F92CC` contains
   `case 0x009F9380u: goto loc_009F9380;` and `0x9F9380` is no longer logged
   as an unresolved indirect call.
2. Run with `GT6_MAINSTACK=5`, `SPU_MISS_FATAL=1`, default `PPU_STUCKMAX`.
   Check whether `ppu_thread_join(tid=14)` still blocks.
3. If it still blocks, run the `GT6_GUARD` write-watch on `0x7005C064` /
   `0x016810E0`, capture the writer, and fix the request-slot producer.
4. Separately trace the `0x0164B020` vptr truncation (`func_00A19218`) and the
   PDI callback slots; they are not the current boot blocker but will bite
   later.

**Risks:** the absolute-base resolver could misclassify unrelated
constant-base `bctr` sites; keep the existing `lwzx + add`, in-text target, and
table-termination checks. The space-filled request may be independent of the
jump table; do not assume the join disappears without verifying. The
poison-guard is a diagnostic band-aid and must not be shipped as the final fix.
