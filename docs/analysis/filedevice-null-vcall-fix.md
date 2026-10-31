# FileDeviceHost null virtual call at 0x009F4550

**Date:** 2026-10-31
**Scope:** diagnosis + a post-lift lifetime patch. This report did not edit
`gt6/generated/`; the two guards are applied by
`tools/apply_gt6_post_lift.py` / `tools/gt6_filedevice_flush_patch.py` after a
relift. No build or `gt6.exe` run was performed by this fix.
**Inputs:** the static disassembly of `work/bin/EMAIN.elf`,
`work/analysis/emain/functions_corrected_lab.json`,
`gt6/generated/ppu_recomp_022.cpp` / `_023.cpp`, `work/pfstrace.err`,
`work/flush_long.err` (180 s run after the guard), `work/gt6.log`, and the
PDIPFS cache report `docs/analysis/pfs-cache-write-fix.md`.

## 0. Bottom line

| Question | Finding |
|---|---|
| What is the crashing function? | `0x009F44D8` is `PDISTD::FileStream::open`. It reads `stream+0x44` (`PDISTD::FileObject*`), then `FileObject+0x40` (`PDISTD::FileDevice*`), then dispatches `FileDevice->vtable[+0x8C]` (the **open** slot). |
| What is `0x009F3E90`? | `FileStream::get_device()`: `return this->m_file ? this->m_file->m_device : 0` (fields `+0x44`, `+0x40`). |
| What is at `0x009F4550`? | The `bctrl` **inside** `0x009F44D8..0x009F4590`. It is intra-function (`loc_009F4550` in the lift). It is **not** a missing function start. |
| What should slot `+0x8C` be? | For a `PDIPFS::FileDevicePFSBase` file device (object vtable pointer `0x1488AB4`), slot `+0x8C` is `0x00A010C0`, `FileDevicePFS::open`. The **read** slot is `+0x90` and is `0x00A0043C`, whose first act is `bl 0x00A40FBC` (`cache_read`). |
| Why is the slot null? | **(a) the object is not the object it claims to be.** The `FileStream*` handed to `open` is a **stale stack pointer** published by the host-device init (`0x00A08A00`, store at `0x00A08A74`) and destroyed at `0x00A08AB4`. Its bytes were reused, so `FileObject+0x40` is `0x70`, not a `FileDevice`. `[0x70] == 0`, `[0x70+0x8C] == 0`, and `bctrl` goes to 0. |
| Is it a missing lift? | **No.** `0x009F44D8`, `0x009F3E90`, `0x009F4590`, `0x00A08A00`, `0x00A08ADC`, `0x00A08B8C`, `0x00A010C0`, `0x00A0043C` are all in `functions_corrected_lab.json` and in `ppu_recomp_table.cpp`. `0x009F4550` must **not** be added. |
| Is it a wrong data-resident vtable base? | **No.** The outer `FileStream` vtable `0x1488138`, the `FileObject` vtable `0x1488218` and the PFS device vtables `0x1488AB4`/`0x1488AB8` all resolve through their OPDs. The failure is not a table base. |
| Is it a runtime HLE gap? | **No HLE is involved.** The fault is in guest object lifetime. The fix is a two-line post-lift guard, not an HLE change. |
| Correct raw cache length | `ZSize = 0xEA57` (59,991), not 239,744 (`Size = 0x3A880`, the decompressed view). |

## 1. Correction to the measured premise

`work/pfstrace.err:32459` says:

```
[ppu] bctr to NULL from func_009F44D8+0x65C r12(opd)=0x00000004 opd[0]=0x00000000
```

`r12` is **not an OPD pointer** here. `0x009F44D8` begins with `mfcr r12`
and saves that condition-register image at `[r1+0x98]`; the `bctrl` loads
`ctr` from the OPD but never writes `r12`, so the diagnostic prints the saved
CR (`4`). The authoritative line is the preceding `[null-call]` line:

```
32441: [GSTACK:nc] sp=0xD0017E20 ... lr=0x009F4554 r3=0x00000070
       r4=0xCFEFE338 r5=0x016327B0 r31=0xCFEFE338 r30=0x00000020 tid=5
32437: [null-call] ... (near lr=0x009F4554, tid=5)
       r3=00000070 r9=00000000 r10=00000000 r11=00000000 r12=00000004
```

At the call, `r9 == 0` and `r11 == 0`. The sequence at `0x009F453C` is:

```
009F4530: cmpwi  cr7, r9, 0
009F4534: clrldi r3, r3, 0x20
009F4538: beq    cr7, 0x9f4558        ; would skip if r9 == 0
009F453C: lwz    r9, 0(r9)            ; File->vtable
009F4540: lwz    r11, 0x8C(r9)        ; FileDevice->vtable[+0x8C]
009F4544: lwz    r0, 0(r11)
009F4548: lwz    r2, 4(r11)
009F454C: mtctr  r0
009F4550: bctrl
```

The branch was not taken, so `r9` was nonzero at `0x009F4530`. It became zero
at `0x009F453C` because `0x9F3E90` returned `0x70`, and `[0x70]` read as 0 on
the flat VM. So the value `4` in `r12` is not Ã¢â‚¬Å“vtable slot +0x8C = 4Ã¢â‚¬Â. The
slot was never loaded from a real vtable.

## 2. The dispatch, object by object

### 2.1 `0x009F44D8` Ã¢â‚¬â€ `PDISTD::FileStream::open`

```
009F4508: lwz   r30, 4(r3)          ; stream->m_lock
009F451C: mr    r3, r31
009F4520: bl    0x9F3E90            ; stream->get_device()
009F453C: lwz   r9, 0(r9)           ; FileObject->vtable
009F4540: lwz   r11, 0x8C(r9)       ; FileDevice->vtable[+0x8C] -- open
009F4550: bctrl                     ; (FileDevice*, FileObject*, mode)
```

The **read** wrapper is the sibling `0x009F4AA0`, which uses slot `+0x90`:

```
009F4AE8: bl    0x9F3E90            ; stream->get_device()
009F4B0C: lwz   r11, 0x90(r9)       ; FileDevice->vtable[+0x90] -- read
009F4B1C: bctrl                     ; (FileDevice*, FileObject*, request)
```

`HFileReader::read` (`0x009BB020`) calls `0x009F4AA0` at `0x009BB08C`; it
never calls `0x009F44D8`. The crash at `0x009F4550` was therefore in
**open**, before the read wrapper could run.

The RTTI strings confirm the classes:

| Address | RTTI string | Meaning |
|---|---|---|
| `0x10977F0` | `N6PDISTD10FileStreamE` | `PDISTD::FileStream` (base vtable `0x1488138`) |
| `0x1097830` | `N6PDISTD18FileInternalStreamE` | `PDISTD::FileInternalStream` (vtable `0x1488168`) |
| `0x1097878` | `N6PDISTD10FileObjectE` | `PDISTD::FileObject` (vtable `0x1488218`) |
| `0x1097F40` | `N6PDIPSX14FileDeviceHostE` | `PDIPSX::FileDeviceHost` |
| `0x1097F60` | `N6PDISTD13FileExpandPSXE` | `PDISTD::FileExpandPSX` (the host singleton vtable `0x1489480`) |
| `0x1097BF0` | `N6PDIPS317FileDevicePFSBaseE` | `PDIPFS::FileDevicePFSBase` |

### 2.2 `0x009F3E90` Ã¢â‚¬â€ the getter that produced `0x70`

```
009F3E90: lwz   r0, 0x44(r3)        ; stream->m_file
009F3E94: li    r3, 0
009F3E98: cmpwi cr7, r0, 0
009F3E9C: clrldi r9, r0, 0x20
009F3EA0: beq   cr7, 0x9F3EA8
009F3EA4: lwz   r3, 0x40(r9)        ; m_file->m_device
009F3EA8: clrldi r3, r3, 0x20
009F3EAC: blr
```

`PDISTD::FileObject` layout (`0x009F5C94` ctor):

| Offset | Field |
|---:|---|
| `+0x00` | vtable (`0x1488218`) |
| `+0x38` / `+0x3C` | flags / state |
| `+0x40` | `m_device` (0 after ctor; cleared by `0x009F5F48`) |
| `+0x44` | next member (mutex/ref state), not the device |
| `+0x5C` | owner `FileStream*` |
| `+0xC0` | size, used by `0x009F4B5C` |

`0x009F4130` (`FileStream::open`) stores the opened `FileObject*` at
`stream+0x44`. A valid `FileObject` therefore has a `FileDevice*` at `+0x40`;
the measured value `0x70` is not a device.

### 2.3 Vtable and the two slots

The outer stream vtable (`0x1488168`, `PDISTD::FileInternalStream`) has:

```
+0x8C = OPD 0x14DF380 -> 0x00BE2168   (default)
```

The host-object vtable (`0x1489480`, `PDISTD::FileExpandPSX`) has:

```
+0x8C = OPD 0x14DF5A0 -> 0x009F810C   (default "unsupported" setter)
```

The PFS device vtable used by these calls has **object vtable pointer
`0x1488AB4`** (typeinfo word `0x1488BA8` at `+0x00`; standard slot-0 base
`0x1488AB8`):

```
+0x8C = OPD 0x14DFA80 -> 0x00A010C0   (FileDevicePFS::open)
+0x90 = OPD 0x14DF9F8 -> 0x00A0043C   (FileDevicePFS::read)
+0x94 = OPD 0x14DF5F8 -> 0x009F82C0
+0x98 = OPD 0x14DFA30 -> 0x00A00964
```

`0x00A0043C` calls `0x00A40FBC` at `0x00A004AC`:

```
00A0043C: ... PFS file read
00A004AC: bl 0x00A40FBC        ; cache_read
```

So the **open** slot target is `0x00A010C0`, and the **read** slot target is
`0x00A0043C` -> `0xA40FBC` -> `0xA40984`. The crash was in open; the read was
never reached because open did not complete. `cache_read` is downstream of
that open.

### 2.4 Why the object pointer and the vtable pointer differ by four

The object's first word (`[stream]`, `[FileObject]`, `[FileDevice]`) is the
vtable pointer the guest loads. For the PFS device it is `0x1488AB4`, whose
first word is the typeinfo pointer `0x1488BA8`; the standard slot-0 base is
`0x1488AB8`. The guest's `lwz r11,0x8C(r9)` / `lwz r11,0x90(r9)` use the
**object pointer**, so the open/read slots are `0xA010C0`/`0xA0043C` as listed
above. The independent check's slot table (`filedevice-null-vcall-check.md`)
uses the same object pointer and is correct on this point; an earlier draft of
this report used the standard base and shifted the roles. The verdict is
unchanged: the object at `0x70` has no valid vtable at either slot.


## 3. Why the object is stale

`0x00A08A00` is `PDIPSX::FileDeviceHost` init. It constructs a
`PDISTD::FileInternalStreamDefault` in its **own stack frame** and publishes
that stack address:

```
00A08A0C: addi r27, r1, 0x70        ; &local
00A08A2C: bl   0x009F4384           ; local FileInternalStreamDefault ctor
...
00A08A60: stb  r0, 0x1C28(r29)      ; flush requested = 0
00A08A74: stw  r27, 0x1C2C(r29)     ; this->m_stream = &local  <-- stack address
...
00A08AB4: bl   0x009F42D8           ; local destructor
00A08AD8: blr                       ; local is now dead
```

`0x00A08B8C` is the Flush entry:

```
00A08B8C: mr   r9, r3
00A08B90: li   r0, 1
00A08B98: stb  r0, 0x1C28(r9)       ; flush requested = 1
00A08B9C: b    0x00A08ADC           ; pump (tail call)
```

`0x00A08ADC` reloads `+0x1C2C` and calls `0x009F44D8`. The measured `this`
`0xCFEFE338` is a **stack address of another thread** (the main/init thread;
the same region as the `[pfs-open] arg=0xCFEFD0E8` lines). By the time tid 5
pumps, that stack has been reused:

* `[stream+4] = 0x20` Ã¢â€ â€™ `[LWM] lock: non-guest lwm=0x00000020 ... ESRCH`
  (`work/pfstrace.err:32439`) in the lock at `0x009F4518`;
* `[stream+0x44] = <reused pointer>`;
* `[FileObject+0x40] = 0x70` Ã¢â€ â€™ `[0x70] = 0`, so the `+0x8C` load is from address 0.

The same stale object is also visible earlier, where the pump is called with a
null stream: `[null-read] ... 0x00000004 by 0x009F44D8` and
`... 0x00000044 by 0x009F3E90` (lines 95-136). With a null stream the
`beq` at `0x009F4538` skips the call; with the reused stream it does not.

### 3.1 The read-active flag

`PDIPSX::FileDeviceHost` keeps two bytes next to the stream pointer:

| Offset | Written by | Meaning |
|---:|---|---|
| `+0x1C28` | `0x00A08B8C` = 1, `0x00A08A60`/`0x00A08D00` = 0 | flush requested |
| `+0x1C29` | `0x00A08ED0` = 1, `0x00A09130`/`0x00A08D00` = 0 | read active |
| `+0x1C2C` | `0x00A08A74` (stack local), `0x00A08ED0` (live caller stream) | `FileStream*` |

`0x00A08ED0` (`StartRead`, vtable `+0x10`) installs the caller's **live**
stream and sets `+0x1C29 = 1`; `0x00A09130` clears it on completion. A Flush
that runs while `+0x1C29 == 0` has no read to drain, but the current code sets
`+0x1C28` anyway and pumps the dead `+0x1C2C` forever (the pump only exits when
`+0x1C28` is cleared, and only the init paths clear it).

## 4. Function-table check (do not add 0x9F4550)

`work/analysis/emain/functions_corrected_lab.json` contains:

| Start | End | Note |
|---|---|---|
| `0x009F3E90` | `0x009F3EB0` | getter |
| `0x009F44D8` | `0x009F4590` | `open` (contains `bctrl` at `0x009F4550`) |
| `0x009F4590` | `0x009F45E8` | next function |
| `0x00A010C0` | `0x00A013B4` | PFS open (`+0x8C`) |
| `0x00A0043C` | `0x00A00550` | PFS read (`+0x90`) |
| `0x00A08A00` | `0x00A08ADC` | device init |
| `0x00A08ADC` | `0x00A08B8C` | pump |
| `0x00A08B8C` | `0x00A08BA0` | Flush entry |

`0x009F4550` is `0x009F44D8 + 0x78`; it is an intra-function `bctrl`. Adding
it as a start would split a 0xB8-byte function in half and reintroduce the
boundary class of bug fixed in `jumptable-fix.md`. All of these starts are also
present in `gt6/generated/ppu_recomp_table.cpp` (`0x009F44D8`,
`0x009F3E90`, `0x00A0043C`, `0x00A08A00`, etc.). There is no missing lift.

## 5. Hypothesis check

| Hypothesis | Verdict |
|---|---|
| (a) object/vtable not initialized | **Accepted, in the Ã¢â‚¬Å“stale objectÃ¢â‚¬Â form.** The `FileStream` is a dead stack local; the `FileObject` and device fields are reused garbage. This is not a missing constructor in the lift. |
| (b) target missing from the lift table | **Rejected.** The helper, getter, pump, PFS open and PFS read are all lifted; `0x9F4550` is intra-function. |
| (c) data-resident table with the wrong base | **Rejected.** Outer, `FileObject`, host and PFS-device vtables all resolve with correct OPDs; `+0x8C` is `0xA010C0` (open) and `+0x90` is `0xA0043C` (read -> `cache_read`). |
| (d) runtime/HLE/constructor gap | **Rejected for the dispatch.** No HLE is on this path. The only constructor involved (`0x9F4384`) is lifted and runs. The gap is a guest object-lifetime mistake in the host-device init/Flush. |

## 6. Fix (post-lift, two edits)

The generated C is rebuilt on every relift, so the fix is a post-lift patch:
`tools/gt6_filedevice_flush_patch.py`, wired into
`tools/apply_gt6_post_lift.py` and verified by `tools/post_lift_fixes.py`.
Reference diff: `patches/gt6-filedevice-flush-guard.patch`.

### 6.1 Clear the dead pointer when the local dies

`func_00A08A00`, after the destructor call at guest `0x00A08AB4`:

```c
ctx->lr = 0x00A08ABC; func_009F42D8(ctx); DRAIN_TRAMPOLINE(ctx);
vm_write32(ctx->gpr[29] + 0x1C2C, 0); /* local FileInternalStreamDefault is destroyed */
```

This is the C++ lifetime rule: the object is destroyed, so its address must not
remain in `m_stream`. On a fresh device the field is already 0; this also
prevents a previous value from surviving a re-init.

### 6.2 Flush only when a read is active

`func_00A08B8C`, at entry:

```c
void func_00A08B8C(ppu_context* ctx) {
    PPU_MM_SNAP
        /* no read in progress: nothing to flush; +0x1C2C may be stale */
        if (vm_read8(ctx->gpr[3] + 0x1C29) == 0) return;
        ... original body ...
}
```

`+0x1C29` is the existing read-active byte maintained by `0x00A08ED0` and
`0x00A09130`. An active-read path is unchanged; a spurious Flush becomes a
no-op instead of pumping a dead pointer and spinning on `+0x1C28`.

### 6.3 Apply / verify statically

```powershell
# fresh relift: reports both missing edits (exit 1)
python tools\gt6_filedevice_flush_patch.py --check gt6\generated

# apply the post-lift guards (idempotent)
python tools\apply_gt6_post_lift.py gt6\generated
python tools\gt6_filedevice_flush_patch.py --check gt6\generated

# relift regression gate (also checks the ADCH switch and func_00A13644)
python tools\post_lift_fixes.py gt6\generated
```

On a fresh relift, `post_lift_fixes.py` fails with:

```
ppu_recomp_023.cpp: func_00A08B8C FileDeviceHost guard missing [...]
```

After the post-lift step it prints `FileDeviceHost guard OK` for both
`func_00A08B8C` and `func_00A08A00`. The patch tool is idempotent (a second
run reports `0 edit(s)`).

## 7. Runtime verification (next build)

The patch only removes a dead dispatch; it does not fabricate cache data. The
cache write still has to be proven by the guest writer.

### 7.1 Expected trace

Enable both the cellFs cache trace and the guest probes:

```powershell
$env:GT6_PFS_CACHE_TRACE="1"
# apply patches/gt6-pfs-cache-probe.patch (0xA40FBC / 0xA40984) before building
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\filedevice_fix.log
```

Required lines for `K/W2`:

```
[pfscache] allocate '...K/W2.fdupi' size=0xEA57 -> OK
[pfscache] 0xA40FBC read ... off=0x0 ...
[pfscache] 0xA40984 write ... size=0xEA57 block=0 ...
[pfscache] write fd=5 '...K/W2.fdupi' nbytes=8192 -> 8192
```

The first two prove that `0xA0043C` reached `cache_read` after the
`FileDevicePFS` slot `+0x8C` resolved. The last two prove that `cache_write`
ran. There must be **no** `[LWM] lock: non-guest lwm=0x00000020` and no
`bctr to NULL from ... 0x009F4550` for tid 5.

### 7.2 Raw cache bytes

The first success criterion is the **raw** stream, `ZSize = 0xEA57`
(59,991), not 239,744.

```powershell
python tools\gt6_pfs_cache_warm.py --key K/W2 --check
```

Expected after a successful guest write (or the section 6.2 preseed in the
cache report):

```
data        ...K/W2.fdupi (59991 bytes)
PASS        data is byte-identical to the GT.VOL slice
PASS        map covers 8 blocks (ZSize 0xEA57, id 0)
```

Byte check:

```
K/W2.fdupi length == 0xEA57
K/W2.fdupi == GT.VOL[0xD48800 .. 0xD48800+0xEA57]
SHA-256 2B6153BACD5E833E9E3BB5B5089552AE3BF973A67FEBA599EC6FCD21DB709008
```

`.fdupm` after completion:

| Offset | Expected |
|---:|---|
| `+0x00` u64 BE `stored_size` | `0xEA57` |
| `+0x08` u64 BE `id` | `0` |
| `+0x10` u32 BE `valid_block_count` | `8` |
| `+0x14` bitmap | byte 0 = `0xFF` |

`239,744` is `Size = 0x3A880`, the decompressed read-side output. A
239,744-byte `.fdupi` would double-decrypt raw plaintext and must not be
produced.

### 7.3 Negative control

Before the fix, the same trace shows:

```
[fs] open .../K/W2.fdupi -> fd 5
[LWM] lock: non-guest lwm=0x00000020 tid=5 -- ESRCH
[null-call] ... near lr=0x009F4554 ... r3=00000070 r9=00000000 r11=00000000
[ppu] bctr to NULL from func_009F44D8+0x65C ...
```

and no read/write/lseek on fd 5. After the guard, that `[LWM]`/`[null-call]`
pair is absent. The cache write is **not** automatic: the 180 s run still
opens, sizes and closes `.fdupi` with no read; see Ã‚Â§10 for the open/size
blocker that remains.

## 8. Why this is upstream of the cache writer

`0x00A40984` (`cache_write`) is reached only from `0x00A40FBC` (`cache_read`),
and `cache_read` is reached from `0x00A0043C`, the PFS device's **`+0x90`**
(read) method. The measured run never reaches that read because the preceding
**open** (`+0x8C` = `0xA010C0`) did not complete. The host-device guard removes
the spurious open that walks the dead stream; it does not touch the PFS cache
path. Once the guest opens a valid PFS `FileObject` and issues
`HFileReader::read` -> `0x9F4AA0`, the cache read/write path is the existing
lifted code.

The `cellFsAllocateFileAreaWithoutZeroFill` / truncate / rename / fsync HLEs
from `pfs-cache-write-fix.md` remain required **after** this point: they size
`.fdupi`, make the block writes durable, and perform the completion rename.

## 9. Remaining risk

The guard fixes the measured **spurious open with no active read**. It does
not prove that every caller-provided `FileStream` passed to `0x00A08ED0`
outlives the asynchronous read. If a future run still shows a stale `+0x1C2C`
with `+0x1C29 == 1`, that is a separate stream-lifetime bug in the caller, and
the next diagnostic is to log `[+0x1C2C]`, `[+0x1C29]` and the caller of
`0x00A08ED0` at read-start time. The current patch is deliberately limited to
the state where no read is active, so it cannot mask that case.

## 10. After the guard: W2 open completes, but read is never issued

| Question | Finding |
|---|---|
| Did `0x9F44D8` (open) still crash? | **No.** The 180 s run has zero `0x9F4550` null calls. |
| Did `0xA08ED0` (StartRead) run for W2? | **No, and it should not.** It is the `PDISTD::FileExpandPSX` host-device async read; the PFS path is `0x9F4AA0` -> `0xA0043C`. |
| Did the `+0x1C2C`/`+0x1C29` state cause the missing read? | **No.** Those fields belong to the host device. The PFS `FileObject` and its `+0x8C`/`+0x90` device slots are a different object. |
| Did the `0x9F7FF0`/`0x9F811C`/`0x9F8534` callbacks abort the pump? | **No.** They are worker-thread bodies on a dead main-stack argument (thread trampoline `0xA304D0`), occur before the W2 open, and the boot continues to the UI assets. |
| Why is `cache_read` not reached? | The PFS **open** (`+0x8C` = `0xA010C0`) did not produce a readable `FileObject` (failed or **size 0**), so `HFileReader::read` sees EOF and never calls `0x9F4AA0` (`+0x90` = `0xA0043C` -> `cache_read`). |

The 180 s run with the guard has **zero** `0x9F4550` null calls. It now reaches
the UI assets (four `pfs override` lines) and W2:

```
2064: [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3 lr=0x00A41B9C
2081: [pfscache] close fd=3 ... size=0
2092: [pfscache] open .../PDIPFS/K/W2.fdupm flags=0x241 -> fd=4
...
2237: [pfscache] open .../PDIPFS/K/W2.fdupi flags=0x42 -> fd=5
2239: [pfscache] allocate ... size=0xEA57 -> OK
2252: [pfscache] close fd=5 ... size=59991
```

There is **no read, write, lseek or cache call on fd 5** between 2239 and 2252.
The map is then zero-initialized (`256`-byte writes at fd 4), its 20-byte header
is written (`stored_size=0xEA57, blocks=0`), and fd 4 is closed. This is the
**cache-create** path, not a cache read.

### 10.1 The slot roles, corrected

| Guest | Slot | Target | Role |
|---|---|---|---|
| `0x009F44D8` | `+0x8C` | `0x00A010C0` | **open** `FileObject` through the PFS device |
| `0x009F4AA0` | `+0x90` | `0x00A0043C` | **read** -> `0xA40FBC` `cache_read` |
| `0x009BB020` | direct | `0x009F4AA0` at `0x009BB08C` | `HFileReader::read` |

The crash at `0x9F4550` was in the **open** helper, not the read helper. The
guard stopped the spurious open of the dead `FileStream`; it could not make a
zero-size `FileObject` readable. The read wrapper `0x9F4AA0` has no observable
effect on W2: there is no `[pfscache] read/write fd=5` line. The new probe
will log `[fileread] 9F4AA0` if it is ever entered.

### 10.2 Why the read is skipped

`HFileReader::read` (`0x9BB020`) only calls `0x9F4AA0` when it needs bytes from
the file. It gates on:

```
reader+0x1A8 : current data buffer (0 if none)
reader+0x1AC : bytes already in the buffer
reader+0x1B0 : buffer end / requested size
```

If the PFS `FileObject` reports **size 0** (or the open returned no object),
the first read sees `pos == end` and returns EOF without calling `0x9F4AA0`.
The zero-length `PDIPFS_bdmark/K/W2` marker is the prime suspect for that
zero size: it is opened with `flags=0x442` (`O_RDWR|O_CREAT|O_TRUNC`) and is
0 bytes. The cache itself is sized from a different field (`0xEA57` in the
`.fdupm` header), so the two size sources disagree.

The likely split is:

* `0x00A422A0`/`0x00A42108` get the **cache size** from the TOC entry
  (`device+0x18`/the `ZSize`), hence `0xEA57`;
* `0x00A3EB60` gets the **FileObject size** from the mount-open `FileInfo`
  (`0x009F8E40` -> `[FileInfo+0x40]`), which is the zero-length bdmark marker,
  hence 0.

`0x00A3EB60` stores its `r6` at `cache+0x38`; `0xA0043C` reads `[cache+0x1C]`
and the request length, so the exact field used by the reader must be
confirmed by the probe. The probe added to `tools/gt6_pfs_cache_probe.py` logs
`0x9F8E40` (`info`, `info+0x3C`, `info+0x40`, returned FileObject),
`0x9F4130` (FileObject, vtable, device, `+0xC0` size), `0x9F44D8`,
`0x9F4AA0`, `0x9BB020` and `0xA3EB60` (all `r4..r8`). The next run will show
exactly which field is 0 and whether `0x9F4AA0` is entered.

### 10.3 The follow-on `0x9F7FF0`/`0x9F811C`/`0x9F8534` calls

These are **not** the `+0x1C2C`/`+0x1C29` state and they do not abort the PFS
open. They occur on worker threads at boot:

* `0xA304D0` is the **PPU thread trampoline** (OPD `0x14E0898`, the same
  `entry=` printed by every `sys_ppu_thread_create`). It calls the thread body
  stored at `[thread+0x18]` with the argument at `[thread+0x1C]`.
* The arguments observed at the null calls are `0xCFEFF600`, `0xCFEFF590`
  and `0x40059D64` Ã¢â‚¬â€ **main-thread stack addresses** or a string pointer, not
  the PFS `FileDevice`.
* `0x9F8078` (thread body) calls `arg->vtable[+0x48]`; the chain
  `0x9F83D4 -> 0x9F7B3C -> 0x9F7FF0`/`0x9F811C`/`0x9F8534` is a destructor /
  close chain on that argument. The vtable pointer happens to still point
  into the old `FileStream` data, but the fields are reused garbage.
* `r12(opd)=0x28000024` / `0x28000042` are **condition-register images**, not
  OPDs. `0x28000024`/`0x28000042` are read as Ã¢â‚¬Å“OPDÃ¢â‚¬Â addresses, which is why
  the VM faults in `0x24000000`, `0x28000000` and `0x2F730000`. The actual
  `ctr` is 0 from a garbage vtable slot (`[0x016778F0+8]=0x7FFF` or
  `[0x0130052F]=0`).

This is a **separate use-after-scope of a thread argument** (the worker thread
starts after the main thread's stack frame is gone). It is not fixed by, and
does not need, the `+0x1C29` guard. A guard on these destructor paths would
mask a real lifetime bug, so none is added. The diagnostic is the thread
trampoline probe in Ã‚Â§10.4: log `[thread+0x18]` (entry OPD), `[thread+0x1C]`
(arg) and the guest tid at `0xA30500`, and log `arg`, `[arg]` at `0x9F8078`.

### 10.4 Probe patch

`tools/gt6_pfs_cache_probe.py` now also emits (read-only `fprintf`s):

| Guest | What is logged |
|---|---|
| `0x9F8E40` | `FileInfo`, `[+0x3C]`, `[+0x40]`, returned FileObject |
| `0x9F4130` | FileObject, vtable, `+0x40` device, `+0xC0` size |
| `0x9F44D8` | `FileStream`, `[+0x44]` FileObject |
| `0x9F4AA0` | `FileStream`, request pointer, FileObject, `[FileObject+0x88]` cache, `stored_size`, `[stream+0x4C]` state/vtable/slot `+0x90` |
| `0x9BB020` | HFileReader, requested bytes, `+0x1A8/+0x1AC/+0x1B0` |
| `0xA08ED0` | host device, stream argument, `+0x1C28/+0x1C29/+0x1C2C` |
| `0xA304D0` | thread object, entry OPD, argument, tid |
| `0x9F8078` | worker argument, its vtable, `[vtable+0x48]` |
| `0xA3EB60` | FileObject and `r4..r8` (cache fields) |
| `0xA40FBC` / `0xA40984` | existing read/write entries |

Expected next-run lines:

```
[fileopen] 9F8E40 info=0x........ info+3C=0x00000000 info+40=0x00000000 file=0x........
[fileopen] 9F4130 this=0x........ path=0x........ file=0x........ vt=0x........ dev=0x........ size=0x0000000000000000
[fileopen] A3EB60 file=0x........ r4=... r5=... r6=0x00000000 r7=... r8=...
[fileread] 9BB020 reader=0x........ want=0x00002000 buf=0x........ pos=0x00000000 end=0x00000000
```

If `9F4130` shows `file=0` or `dev=0`, the PFS open failed and the cache was
torn down; if it shows a valid file with `size=0`, the size source is the
bdmark marker. In either case `9F4AA0`/`A40FBC` must not be expected until the
FileObject has a nonzero size.

### 10.5 What not to do

* Do **not** add a guard to `0x9F7FF0`, `0x9F811C` or `0x9F8534`: they are
  destructor/close methods on a valid object family; the bug is the dead
  thread argument, not the slot.
* Do **not** hardcode `0xEA57` or synthesize cache bytes. The conditional
  repair in Ã‚Â§11 copies the guest cache's own `stored_size`; the bytes still
  come from `0xA40FBC`/`0xA40984`.
* Do **not** treat the 59,991-byte zero-filled `.fdupi` as success. It is the
  HLE's `_chsize_s` preallocation, not a cache.

## 11. Probe run interpretation and the PFS source bind

`work/probe_run.err` (180 s) reached only the first draw, but it did fire the
open probe once:

```
696: [GT6] script override: serving decrypted /scripts/gt6/main.adc (857518 bytes)
699: [fileopen] 9F8E40 info=0x400C749C info+3C=0x400C74FC info+40=0x00000000 file=0x7FFD6270
701: [fileopen] 9F4130 this=0x7FFD6210 file=0x7FFD6270 vt=0x01488218 dev=0x7005C000 size=0x0
747: [fileopen] A3EB60 file=0x00000100 r4=0x014DF818 r5=0x7005C000 r6=0x00000021 r7=0 r8=0
```

### 11.1 That object is the boot script, not W2 or the marker

**Verdict: the `size=0` line does not confirm the W2 hypothesis.** It is the
boot-script reader, served by the existing script override, not the W2 PFS
cache file.

* `0x7FFD6210` is the `HFileReader` at `0x7FFD61E0` + `0x30` (its embedded
  `FileStream`); `0x7FFD6270` is that reader + `0x90`, the `FileObject`.
* `vt=0x01488218` is the **base `PDISTD::FileObject`** vtable, not the
  `FileObjectDefault` (`0x1489588`) or a PFS subclass.
* `dev=0x7005C000` is a **host device** (`FileExpandPSX`/`FileDeviceHost`
  family), not the PFS device.
* The probe line is immediately after `[GT6] script override`, and the
  `[fileread] 9BB020` sequence that follows is the ADCH parser reading
  `8, 1, 1, 1, 0x1A, ...` Ã¢â‚¬â€ the decrypted `main.adc`, not W2's 8 KiB cache
  blocks.
* The script is served by `gt6_script_read_override`; a zero host size does
  not stop it. Therefore **this line does not confirm the W2 hypothesis**.

`[fileopen] A3EB60 file=0x00000100 ... r6=0x21` is a **different call**:
`0xA3EB60` has one caller (`0x9FDC84` in `0x9FDAAC`), and the log's `r3=0x100`
is a PFS handle/index, not the FileObject `0x7FFD6270`. `r6=0x21` (33) is a
cache-info field, not a size; for the K/PD cache `0x3EE28` (32 blocks of
0x2000), 33 is consistent with a block/entry count, not the byte size. The
probe labels are raw register names; the mapping is:

| Probe | Correct field meaning |
|---|---|
| `9F4130 file=` | `ctx->gpr[3]`, the returned `FileObject*` |
| `9F4130 vt=` | `[FileObject]`, the object's vtable pointer |
| `9F4130 dev=` | `[FileObject+0x40]`, the `FileDevice*` |
| `9F4130 size=` | `[FileObject+0xC0]`, the logical size |
| `9F8E40 info=` | `ctx->gpr[29]`, the `FileInfo`/lookup object, not necessarily a path; `+0x3C/+0x40` are its fields, not a guaranteed size |
| `A3EB60 file=` | `ctx->gpr[3]`, a PFS handle/state, **not** the `FileObject`; `r6` is the 6th argument, not the size |
| `9BB020 buf/pos/end` | `[reader+0x1A8]`, `[+0x1AC]`, `[+0x1B0]`; these are the reader's buffer state, not the file size |

The positive control is also in the same run:

```
625: [fileread] 9F4AA0 stream=... file=0xCFEFEA70
626: [pfscache] 0xA40FBC read file=0x00000100 off=0x8BBC0 len=...
```

K/IK reaches `0x9F4AA0` -> `0xA40FBC` with a nonzero FileObject size. The PFS
read path itself works; W2's problem is earlier or specific to its open.

### 11.2 Why the size-only repair cannot fire

The 300 s run with the size repair (`work/size_run.err`) shows the decisive
sequence at W2:

```
289086: [fileopen] 9F4130 this=0xCFEFE338 file=0xCFEFE398 vt=0x01488218 dev=0x7005C000 size=0x0
289100: [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
289107: [pfscache] stat .../PDIPFS/K/W2.fdupm -> size=8212
289113: [pfscache] open .../PDIPFS/K/W2.fdupi flags=0x42 -> fd=5
289115: [pfscache] allocate ... size=0xEA57 -> OK
289118: [fileopen] A3EB60 file=0x00000100 ... r6=0x3A ...
289119: [fileread] 9F4AA0 stream=0xCFEFE338 req=0xCFEFE2B8 file=0xCFEFE398
289127: [pfscache] close fd=5 ... size=59991
```

`0x9F4AA0` **is called** for W2 (contrary to the earlier reading), but
`0xA40FBC` is absent. The FileObject is **host-backed** (`vt=0x1488218`,
`dev=0x7005C000`), so `0x9F4AA0` dispatches the host device's `+0x90`
default (`0x9F8100`), not the PFS read `0xA0043C`. The cache exists, but the
FileObject never points at the PFS read state. The size-only repair checked
the device vtable for PFS and therefore intentionally skipped; even if it had
set `+0xC0`, the wrong `+0x90` dispatch would still skip `cache_read`.

### 11.3 The correct layer: bind the cache-backed host FileObject

`0x9F4130` now applies this **cache-presence** repair after storing the opened
FileObject:

```c
/* Cache-backed host FileObject: bind to the PFS read state. */
{ uint32_t _s = (uint32_t)ctx->gpr[31];     /* FileStream */
  uint32_t _f = (uint32_t)ctx->gpr[3];      /* FileObject */
  if (_s >= 0x10000u && _f >= 0x10000u && _f < 0xE0000000u) {
    uint32_t _dev = vm_read32(_f + 0x40u);
    uint32_t _dvt = _dev ? vm_read32(_dev) : 0;
    uint32_t _c  = vm_read32(_f + 0x88u);   /* PDIPFS cache manager */
    if (!_c && _dev) _c = vm_read32(_dev + 0x88u);
    uint32_t _st = vm_read32(_s + 0x4Cu);   /* state 0xA0043C reads */
    uint32_t _sv = _st ? vm_read32(_st) : 0;
    uint32_t _slot = _sv ? vm_read32(_sv + 0x90u) : 0;
    if (_slot != 0x00A0043Cu) {             /* fallback: FileObject+0x4C */
      uint32_t _alt = vm_read32(_f + 0x4Cu);
      uint32_t _av = _alt ? vm_read32(_alt) : 0;
      if (_av && vm_read32(_av + 0x90u) == 0x00A0043Cu) {
        _st = _alt; _sv = _av; _slot = 0x00A0043Cu;
      }
    }
    if (_c && _st && _slot == 0x00A0043Cu) {
      uint64_t _z  = vm_read64(_c + 0x10u); /* stored_size / ZSize */
      uint32_t _slotc8 = _sv ? vm_read32(_sv + 0xC8u) : 0;
      if (_z && _slotc8) {
        if (vm_read64(_f + 0xC0u) == 0) vm_write64(_f + 0xC0u, _z);
        if (vm_read32(_s + 0x4Cu) != _st) vm_write32(_s + 0x4Cu, _st);
        if (_dvt != 0x1488A2Cu && _dvt != 0x1488AACu &&
            _dvt != 0x1488AB4u && _dvt != 0x1488AB8u) {
          vm_write32(_f + 0x40u, _st);      /* bind to the PFS read state */
          fprintf(stderr, "[pfsbind] file=0x%08X state=0x%08X "
                  "dev=0x%08X size=0x%llX slotC8=0x%08X\n",
                  _f, _st, _dev, (unsigned long long)_z, _slotc8);
        }
      }
    }
  } }
```


Why this is safe and not fabrication:

* It requires a **cache manager at `FileObject+0x88`** with a nonzero
  `stored_size`. The boot script and ordinary host files have no such cache,
  so they are untouched.
* It requires `FileStream+0x4C` (or the `FileObject+0x4C` fallback) to point
  at a state whose own vtable `+0x90` is exactly `0xA0043C` and whose `+0xC8`
  (the buffer-copy slot `0xA0043C` uses) is nonzero. If the state is not the
  PFS read object, nothing is written and nothing is logged.
* It only rebinds when the current device is not already one of the PFS
  vtables. K/IK, whose FileObject already dispatches to `0xA0043C`, is
  untouched.
* It writes `FileObject+0x40` (the device pointer) and `FileObject+0xC0`
  (size) from guest-owned objects. It does not patch a vtable entry and does
  not write cache data. `0xA40FBC`/`0xA40984` still read GT.VOL and write the
  cache.
* The `[pfsbind]` line is the positive evidence that the bind fired; if it is
  absent for W2, the state at `FileStream+0x4C` is not the PFS read object and
  the fix must move to the PFS source-open, not be widened here.

Apply with:

```powershell
python tools\gt6_filedevice_flush_patch.py gt6\generated
# or the normal post-lift step
python tools\apply_gt6_post_lift.py gt6\generated
python tools\post_lift_fixes.py gt6\generated
```

The reference diff is `patches/gt6-pfs-source-bind.patch`.

### 11.4 Why W2 is host-backed while K/IK works

`PDIPFS_bdmark` is a **marker directory**. `PDIPFS_bdmark/K/W2` is a
zero-length existence/bdmark file; it is not the data. The actual data is the
GT.VOL entry, and `PDIPFS/K/W2.fdupi` is the read-through cache.

For K/IK the FileObject is opened through the **PFS device**, whose `+0x90`
is `0xA0043C`; `9F4AA0` therefore reaches `0xA40FBC` (the positive control at
`size_run.err:625-626`). For W2 the same generic `FileStream::open`
(`0x9F4130`) was handed a **host FileObject** for the bdmark marker
(`vt=0x1488218`, `dev=0x7005C000`). The cache attach at `0xA422A0` still ran
and put the cache manager at `FileObject+0x88`, but it did not replace the
host device at `+0x40` or install the PFS read slot. That is the wrong-layer
object bug: the cache is attached to a host-backed file, so the read dispatch
never consults it.

The bind in Ã‚Â§11.3 repairs exactly that: for a cache-backed host FileObject,
it points `+0x40` at the PFS read state that `0xA0043C` already uses, and
sets the size from the cache. It does not make the bdmark marker itself
readable, and it does not touch files without a cache.

### 11.5 What the next run must show

The current 300 s log still shows the old `9F4130` format (`vt=` but no
`path=`/`dev_vt=`), so the latest probe extension was not in that build.
Rebuild with `patches/gt6-pfs-cache-probe.patch` (or rerun
`tools/gt6_pfs_cache_probe.py` on the relifted tree) and use a **240-300 s**
run. The W2 sequence should become:

```
[fileopen] 9F4130 this=... path=... file=... vt=... dev=0x........ dev_vt=0x........ size=0x0
[pfsbind] file=... state=... dev=0x........ size=0xEA57 slotC8=0x........
[fileread] 9F4AA0 stream=... req=... file=... cache=0x........ z=0xEA57 state=0x........ state_vt=0x........ slot90=0x00A0043C
[pfscache] 0xA40FBC read file=0x00000100 off=0x0 len=0x2000
[pfscache] 0xA40984 write cache=... size=0xEA57 block=0 ...
[pfscache] write fd=5 '...K/W2.fdupi' nbytes=8192 -> 8192
```

Then the raw file must be 59,991 bytes and equal GT.VOL at `0xD48800`
(SHA-256 `2B6153...9008`), with `.fdupm` `blocks=8`, bitmap byte 0 `0xFF`.

If `[pfsbind]` does **not** fire for W2, the state at `FileStream+0x4C` is
not a PFS read object (or has no cache/state). Do not widen the condition
blindly; the `9F4130`/`9F4AA0` probes and `[file+0x88]`/`[stream+0x4C]` values
will show which pointer is missing. The next fix then belongs in the PFS
source-open (`0x9FDAAC`/`0x9F8E40`) that should create the PFS-backed
FileObject, not in the generic host open.

### 11.6 The previous slow run is not a regression

The non-probe 180 s run reaches W2 and four `pfs override` lines; the probe run
reaches only the first draw because each probe adds `fprintf` to hot open/read
paths. This is a measurement cost, not a semantic change from the flush guard.
Use a longer run or disable the per-read probes (`9BB020`/`9F4AA0`) once the
open/size question is answered.




