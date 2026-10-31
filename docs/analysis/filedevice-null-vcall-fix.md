# FileDeviceHost null virtual call at 0x009F4550

**Date:** 2026-10-31
**Scope:** diagnosis + a post-lift lifetime patch. This report did not edit
`gt6/generated/`; the two guards are applied by
`tools/apply_gt6_post_lift.py` / `tools/gt6_filedevice_flush_patch.py` after a
relift. No build or `gt6.exe` run was performed by this fix.
**Inputs:** the static disassembly of `work/bin/EMAIN.elf`,
`work/analysis/emain/functions_corrected_lab.json`,
`gt6/generated/ppu_recomp_022.cpp` / `_023.cpp`, `work/pfstrace.err` and
`work/gt6.log`, and the PDIPFS cache report
`docs/analysis/pfs-cache-write-fix.md`.

## 0. Bottom line

| Question | Finding |
|---|---|
| What is the crashing function? | `0x009F44D8` is `PDISTD::FileStream::read`. It reads `stream+0x44` (`PDISTD::File*`), then `File+0x40` (`PDISTD::FileDevice*`), then dispatches `FileDevice->vtable[+0x8C]`. |
| What is `0x009F3E90`? | `FileStream::get_device()`: `return this->m_file ? this->m_file->m_device : 0` (fields `+0x44`, `+0x40`). |
| What is at `0x009F4550`? | The `bctrl` **inside** `0x009F44D8..0x009F4590`. It is intra-function (`loc_009F4550` in the lift). It is **not** a missing function start. |
| What should slot `+0x8C` be? | For a `PDIPFS::FileDevicePFSBase` file device (`0x1488AAC`/`0x1488AB8`), slot `+0x8C` is `0x00A0043C`, `FileDevicePFS::read`, whose first act is `bl 0x00A40FBC` (`cache_read`). That is the missing link to the cache writer. |
| Why is the slot null? | **(a) the object is not the object it claims to be.** The `FileStream*` handed to `read` is a **stale stack pointer** published by `PDIPSX::FileDeviceHost` init (`0x00A08A00`, store at `0x00A08A74`) and destroyed at `0x00A08AB4`. Its bytes were reused, so `File+0x40` is `0x70`, not a `FileDevice`. `[0x70] == 0`, `[0x70+0x8C] == 0`, and `bctrl` goes to 0. |
| Is it a missing lift? | **No.** `0x009F44D8`, `0x009F3E90`, `0x009F4590`, `0x00A08A00`, `0x00A08ADC`, `0x00A08B8C`, `0x00A0043C` are all in `functions_corrected_lab.json` and in `ppu_recomp_table.cpp`. `0x009F4550` must **not** be added. |
| Is it a wrong data-resident vtable base? | **No.** The outer `FileStream` vtable `0x1488168`, the `File` vtable `0x1488218` and the PFS device vtables `0x1488AAC`/`0x1488AB8` all resolve through their OPDs. The failure is not a table base. |
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
the flat VM. So the value `4` in `r12` is not “vtable slot +0x8C = 4”. The
slot was never loaded from a real vtable.

## 2. The dispatch, object by object

### 2.1 `0x009F44D8` — `PDISTD::FileStream::read`

```
009F4508: lwz   r30, 4(r3)          ; stream->m_lock
009F451C: mr    r3, r31
009F4520: bl    0x9F3E90            ; stream->get_device()
009F453C: lwz   r9, 0(r9)           ; File->vtable
009F4540: lwz   r11, 0x8C(r9)       ; FileDevice->vtable[+0x8C]
009F4550: bctrl                     ; (FileDevice*, File*, buf, len)
```

The RTTI strings confirm the classes:

| Address | RTTI string | Meaning |
|---|---|---|
| `0x10977F0` | `N6PDISTD10FileStreamE` | `PDISTD::FileStream` (base vtable `0x1488138`) |
| `0x1097830` | `N6PDISTD18FileInternalStreamE` | `PDISTD::FileInternalStream` (vtable `0x1488168`) |
| `0x1097878` | `N6PDISTD10FileObjectE` | `PDISTD::FileObject` (vtable `0x1488218`) |
| `0x1097F40` | `N6PDIPSX14FileDeviceHostE` | `PDIPSX::FileDeviceHost` |
| `0x1097F60` | `N6PDISTD13FileExpandPSXE` | `PDISTD::FileExpandPSX` (the host singleton vtable `0x1489480`) |
| `0x1097BF0` | `N6PDIPS317FileDevicePFSBaseE` | `PDIPFS::FileDevicePFSBase` |

### 2.2 `0x009F3E90` — the getter that produced `0x70`

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

`PDISTD::File` layout (`0x009F5C94` ctor):

| Offset | Field |
|---:|---|
| `+0x00` | vtable (`0x1488218`) |
| `+0x38` / `+0x3C` | flags / state |
| `+0x40` | `m_device` (0 after `File` ctor; cleared by `0x009F5F48`) |
| `+0x44` | next member (mutex/ref state), not the device |
| `+0x5C` | owner `FileStream*` |
| `+0xC0` | size, used by `0x009F4B5C` |

`0x009F4130` (`FileStream::open`) stores the opened `File*` at `stream+0x44`.
A valid `File` therefore has a `FileDevice*` at `+0x40`; the measured value
`0x70` is not a device.

### 2.3 Vtable and expected `+0x8C`

The outer stream vtable (`0x1488168`, `PDISTD::FileStream`) has:

```
+0x8C = OPD 0x14DF380 -> 0x00BE2168   (default)
```

The host device vtable (`0x1489480`, `PDIPSX::FileDeviceHost`) has:

```
+0x8C = OPD 0x14DF5A0 -> 0x009F810C   (default "unsupported" setter)
```

The PFS device vtables (`0x1488AAC` and `0x1488AB8`, both typeinfo
`PDIPFS::FileDevicePFSBase`) have:

```
+0x8C = OPD 0x14DF9F8 -> 0x00A0043C   (FileDevicePFS::read)
+0x90 = OPD 0x14DF5F8 -> 0x009F82C0
+0x94 = OPD 0x14DFA30 -> 0x00A00964
+0x98 = OPD 0x14DF9F0 -> 0x00A00414
```

`0x00A0043C` calls `0x00A40FBC` at `0x00A004AC`:

```
00A0043C: ... PFS file read
00A004AC: bl 0x00A40FBC        ; cache_read
```

So the **expected** slot target for a PFS file is `0x00A0043C`, and that is
exactly the function that was never reached. The null dispatch is upstream of
`cache_read`, and `cache_read` is upstream of `cache_write` (`0x00A40984`).

### 2.4 Vtable base alignment (the `-4` trap)

`docs/analysis/filedevice-null-vcall-check.md` independently reaches the same
conclusion (the slot is never read; the target exists) but its slot table is
shifted by four bytes. Its “base” `0x1488AB4` is the **typeinfo word** at
`vtable-4`; the actual slot-0 address stored in the object is `0x1488AB8`.
With the real base:

| Real slot | OPD | Code | Role |
|---|---|---|---|
| `+0x88` | `0x14DFA80` | `0x00A010C0` | open |
| `+0x8C` | `0x14DF9F8` | `0x00A0043C` | read -> `0xA40FBC` |
| `+0x90` | `0x14DF5F8` | `0x009F82C0` | (next virtual) |

The call itself confirms `+0x8C` is read: `0x009F44D8` passes
`r5 = [FileDeviceHost+0x1C30]`, a `{offset,length}` request pair, and
`0xA0043C` reads that pair (`lwz r11,4(r5)`, `lwz r0,0(r5)`) before calling
`cache_read`. Open would take a path string, not that pair.

The same `-4` shift is why the check doc calls `+0x8C` the open slot. It does
not change its verdict: the object at `0x70` has no vtable at either slot.


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

* `[stream+4] = 0x20` → `[LWM] lock: non-guest lwm=0x00000020 ... ESRCH`
  (`work/pfstrace.err:32439`) in the lock at `0x009F4518`;
* `[stream+0x44] = <reused pointer>`;
* `[File+0x40] = 0x70` → `[0x70] = 0`, so the `+0x8C` load is from address 0.

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
| `0x009F44D8` | `0x009F4590` | `read` (contains `bctrl` at `0x009F4550`) |
| `0x009F4590` | `0x009F45E8` | next function |
| `0x00A0043C` | `0x00A00550` | PFS read (expected `+0x8C`) |
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
| (a) object/vtable not initialized | **Accepted, in the “stale object” form.** The `FileStream` is a dead stack local; the `File` and device fields are reused garbage. This is not a missing constructor in the lift. |
| (b) target missing from the lift table | **Rejected.** The helper, getter, pump and PFS read are all lifted; `0x9F4550` is intra-function. |
| (c) data-resident table with the wrong base | **Rejected.** Outer, `File`, host-device and PFS-device vtables all resolve with correct OPDs; slot `+0x8C` of the PFS vtable is `0xA0043C` (cache read). |
| (d) runtime/HLE/constructor gap | **Rejected for the dispatch.** No HLE is on this path. The only constructor involved (`0x9F4384`, `FileInternalStreamDefault`) is lifted and runs. The gap is a guest object-lifetime mistake in `FileDeviceHost` init/Flush. |

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

and no read/write/lseek on fd 5. After the fix, that `[LWM]`/`[null-call]`
pair must be absent and fd 5 must show the cache write.

## 8. Why this is upstream of the cache writer

`0x00A40984` (`cache_write`) is reached only from `0x00A40FBC` (`cache_read`),
and `cache_read` is reached from `0x00A0043C`, the PFS device's `+0x8C`
method. The measured run never resolves `+0x8C` because `File+0x40` is not a
`FileDevice`. The FileDeviceHost guard removes the spurious flush that walks
the dead stream; it does not touch the PFS cache path. Once the guest reaches
a valid PFS file read, the cache read/write path is the existing lifted code.

The `cellFsAllocateFileAreaWithoutZeroFill` / truncate / rename / fsync HLEs
from `pfs-cache-write-fix.md` remain required **after** this point: they size
`.fdupi`, make the block writes durable, and perform the completion rename.

## 9. Remaining risk

The guard fixes the measured **spurious flush with no active read**. It does
not prove that every caller-provided `FileStream` passed to `0x00A08ED0`
outlives the asynchronous read. If a future run still shows a stale `+0x1C2C`
with `+0x1C29 == 1`, that is a separate stream-lifetime bug in the caller, and
the next diagnostic is to log `[+0x1C2C]`, `[+0x1C29]` and the caller of
`0x00A08ED0` at read-start time. The current patch is deliberately limited to
the state where no read is active, so it cannot mask that case.
