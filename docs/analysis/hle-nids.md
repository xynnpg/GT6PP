# Missing HLE NIDs at boot — identification and proposals

**Date:** 2026-10-31
**Target:** Gran Turismo 6 US `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Scope:** the three imports still reported unresolved after
`cellSpursGetWorkloadFlag` was added:

| NID | Module | Name | Confidence in name |
|---|---|---|---|
| `0x2DDBCC0A` | `cellSpurs` | `_cellSpursWorkloadFlagReceiver2` | **Certain** |
| `0xFAA275A4` | `cellSysutilAvconfExt` | `cellVideoOutGetScreenSize` | **Certain** |
| `0x5C832BD7` | `cellUsbd` | `cellUsbdSetThreadPriority2` | **Certain** |

All three names are confirmed twice, independently:

1. The real GT6 boot log produced by RPCS3 (`tools/RPCS3/log/RPCS3.log`)
   contains the firmware export tables and the import table for this exact
   executable. It prints the NID together with the firmware's own name.
2. The PS3 NID is `SHA-1(name || suffix)[0..3]` interpreted little-endian
   (`suffix = 67 59 65 99 04 25 04 90 56 64 27 49 94 89 74 1A`). Recomputing
   the hash for the name gives the imported NID exactly. A 32-bit collision is
   not plausible for three independently matched names.

```
_cellSpursWorkloadFlagReceiver2 -> 0x2DDBCC0A
cellVideoOutGetScreenSize      -> 0xFAA275A4
cellUsbdSetThreadPriority2     -> 0x5C832BD7
cellSpursGetWorkloadFlag       -> 0xC765B995  (existing override, unchanged)
```

RPCS3 log evidence (line numbers in `tools/RPCS3/log/RPCS3.log`):

```
12958  cellSpurs export: (0x2ddbcc0a) at 0x013353c [at:0x010f298, rtoc:same-above]:  _cellSpursWorkloadFlagReceiver2
13552  cellUsbd export: (0x5c832bd7) at 0x0110140 [at:0x0100d60, rtoc:same-above]:  cellUsbdSetThreadPriority2
15209  cellUsbd import: [cellUsbdSetThreadPriority2] (0x5c832bd7) -> 0xf92948
15612  cellSpurs import: [_cellSpursWorkloadFlagReceiver2] (0x2ddbcc0a) -> 0xf97b18
15751  cellSysutilAvconfExt import: [cellVideoOutGetScreenSize] (0xfaa275a4) -> 0xf998d8
```

The import stub addresses `0xF97B18`, `0xF92948`, `0xF998D8` match
`work/analysis/emain/hle_stubs_named.json` and the generated chunks, so the
log describes this binary, not just the firmware.

---

## 1. `0x2DDBCC0A` — `_cellSpursWorkloadFlagReceiver2`

### Signature

```c
int _cellSpursWorkloadFlagReceiver2(CellSpurs *spurs,
                                    uint32_t wid,
                                    uint32_t is_set,
                                    uint32_t print_debug_output);
```

RPCS3's implementation declares exactly these four guest arguments
(`ppu_thread&` is an RPCS3 host detail) and its trace string is
`spurs, wid, is_set, print_debug_output`. Confidence: **high** (RPCS3 source +
the call site passes four registers).

### Caller expectation (guest `0xB6E844`)

The prompt's `0xB6E848` is the **return address**, not the call instruction.
The real call is:

```
0xB6E834  li    r5, 1              ; is_set = 1
0xB6E838  li    r6, 0              ; print_debug_output = 0
0xB6E83C  lwz   r4, 0x8(r22)       ; r22 = job-queue manager + 0x80 -> workload ID at manager+0x88
0xB6E840  or    r3, r29, r29       ; CellSpurs*
0xB6E844  bl    0xF97B18           ; _cellSpursWorkloadFlagReceiver2
0xB6E848  ...                      ; return address
```

Generated C++ (`gt6/generated/ppu_recomp_027.cpp`, `func_00B6E6AC`) confirms the
same argument setup (`gpr[5]=1, gpr[6]=0, gpr[4]=vm_read32(gpr[22]+8),
gpr[3]=gpr[29]`).

Immediately afterwards the engine does:

```
0xB6E848  addi  r4, r1, 0x70       ; &local_flag_ptr
0xB6E84C  or    r3, r29, r29       ; CellSpurs*
0xB6E850  bl    0xF981E0           ; cellSpursGetWorkloadFlag(spurs, &local)
0xB6E854  lwz   r3, 0x70(r1)       ; pointer written by GetWorkloadFlag
0xB6E858  bl    0xB76B00           ; translate/encode the guest address
0xB6E85C  rlwinm r0, r3, 0, 1, 31  ; clear bit 0
0xB6E864  stw   r0, 0xE4(r31)      ; cache the encoded flag address on the engine object
```

`func_00B6E6AC` is the engine's SPURS job-queue bootstrap. It is invoked from
`func_008035F4` (the display/video-output setup routine) through the
argument-shuffling thunk at `0xB6E8B4`; the `bl` is at `0x8036B8`. The return
value of `_cellSpursWorkloadFlagReceiver2` is **not checked**; only the
guest-memory side effects matter.

`0xB76B00` is a small guest address-mapping helper (a 16-bit lookup table at
`0x1682148`); it does not dereference the workload-flag pointer. It only
encodes the pointer for later SPU use.

### Real behaviour and the port's layout

`CellSpurs` is a 4 KB (SPURS1) / 8 KB (SPURS2) big-endian guest object.
Relevant fields, confirmed by both RPCS3's `cellSpurs.h` and ps3recomp's
`libs/spurs/cellSpurs.c`:

| Offset | Field |
|---|---|
| `+0x60` | `CellSpursWorkloadFlag wklFlag` (16 bytes: unused0 u64, unused1 u32, flag u32 at `+0x6C`) |
| `+0x77` | `u8 wklFlagReceiver` (`0xFF` = no receiver) |

`_cellSpursWorkloadFlagReceiver2` sets `wklFlagReceiver = wid` (when `is_set`)
and resets the flag word to `0xFFFFFFFF` ("not signalled"). Unsetting clears
the receiver back to `0xFF`. The firmware returns `BUSY` if another workload
owns the receiver and `PERM` if an unset is attempted by a non-owner.

Port-specific accommodation: ps3recomp's `cellSpursInitialize` zeroes the
object and never writes `0xFF` to `+0x77`, whereas the firmware initialises it
to `0xFF`. The proposed handler treats a zero receiver byte as "free" **only
when the flag word at `+0x6C` is also zero** (the fresh ps3recomp state). Once a
receiver has been set, the handler writes `0xFFFFFFFF` to that flag word, so a
zero receiver byte with a non-zero flag word correctly means workload 0 owns
the receiver. This preserves the firmware's "only one receiver" rule for
`wid == 0` as well. Re-setting the same `wid` is also accepted as success
(idempotent), which is slightly more lenient than the firmware.

### Proposed implementation

```c
static void gt6_cellSpursWorkloadFlagReceiver2(ppu_context* ctx)
{
    const uint32_t spurs  = (uint32_t)ctx->gpr[3];
    const uint32_t wid    = (uint32_t)ctx->gpr[4];
    const uint32_t is_set = (uint32_t)ctx->gpr[5];
    const uint32_t debug  = (uint32_t)ctx->gpr[6];   /* ignored */
    ...
    if (!spurs)                      rc = 0x80410811; /* NULL_POINTER */
    else if (wid >= 32)              rc = 0x80410802; /* INVAL */
    else {
        uint8_t receiver = vm_read8(spurs + 0x77);
        if (receiver == 0 && vm_read32(spurs + 0x6C) == 0)
            receiver = 0xFF;                          /* fresh ps3recomp instance */
        if (is_set) {
            if (receiver != 0xFF && receiver != wid) rc = 0x8041080A; /* BUSY */
            else { vm_write8(spurs + 0x77, wid);
                   vm_write32(spurs + 0x6C, 0xFFFFFFFF); }
        } else {
            if (receiver != wid) rc = 0x80410809;     /* PERM */
            else { vm_write8(spurs + 0x77, 0xFF);
                   vm_write32(spurs + 0x6C, 0xFFFFFFFF); }
        }
    }
    ctx->gpr[3] = (uint64_t)(uint32_t)rc;
}
```

Full code: `tools/hle_proposals/gt6_stubs_proposed.cpp`.

### Risks

- ps3recomp's SPURS scheduler does **not** model `wklFlagReceiver`; it schedules
  from ready counts and signals. The write restores guest-visible state but
  will not, by itself, make a PPU wait on the workload flag complete. If the
  engine later blocks on `wklFlag.flag`, that is a scheduler gap to address
  separately.
- The handler writes `+0x77` and `+0x6C` in the guest object. `CellSpurs` is at
  least 4 KB, so both are in range. Only a null pointer is rejected; the
  firmware's 128-byte alignment check was deliberately dropped so a
  misaligned-but-usable instance in this port does not lose the side effect.
  The `vm_read*`/`vm_write*` accessors bounds-check, so a bogus non-null EA is
  ignored by the VM rather than faulting the host.
- The "zero byte means free" rule is a heuristic for ps3recomp's uninitialised
  receiver byte. The flag-word guard makes it correct for the boot sequence
  (set wid, then flag = -1), but if the SPU later overwrites the flag word with
  zero while wid 0 owns the receiver, the zero byte becomes ambiguous again.
  GT6 sets a receiver once per instance during boot, so this is acceptable
  until the SPURS scheduler itself models `wklFlagReceiver`.
- `+0x6C` is the flag word inside `CellSpursWorkloadFlag`, not the byte at
  `+0x60` that ps3recomp initialises. Resetting it to `-1` matches the firmware
  and RPCS3; it does not disturb the existing `cellSpursGetWorkloadFlag`
  override, which still returns `spurs + 0x60`.

### Confidence

- Name, module, import stub: **certain** (log + hash + generated stub).
- Signature: **high** (RPCS3 source, four register arguments in the call).
- Side-effect offsets: **high** (two independent structure definitions).
- Return-code values: **high** for the `CELL_SPURS_POLICY_MODULE_ERROR_*`
  values (`0x804108xx`), medium for the port's lenient zero/same-wid policy.

---

## 2. `0xFAA275A4` — `cellVideoOutGetScreenSize`

### Signature

```c
int cellVideoOutGetScreenSize(uint32_t videoOut, float *screenSize);
```

`videoOut = 0` is `CELL_VIDEO_OUT_PRIMARY`; `1` is
`CELL_VIDEO_OUT_SECONDARY`. RPCS3's declaration is
`error_code cellVideoOutGetScreenSize(u32 videoOut, vm::ptr<f32> screenSize)`.
Confidence: **certain** (RPCS3 source + call site + firmware export log).

`cellSysutilAvconfExt` has exactly one import in `EMAIN.elf`, so resolving this
function closes the module for this title.

Real firmware error values (from RPCS3's `cellVideoOut.h` and RPCS3 logs):

| Constant | Value |
|---|---|
| `CELL_VIDEO_OUT_ERROR_ILLEGAL_PARAMETER` | `0x8002B222` |
| `CELL_VIDEO_OUT_ERROR_UNSUPPORTED_VIDEO_OUT` | `0x8002B225` |
| `CELL_VIDEO_OUT_ERROR_VALUE_IS_NOT_SET` | `0x8002B228` |

Note: ps3recomp's `libs/video/cellVideoOut.h` uses base `0x8002B100` for these,
which yields wrong values (`0x8002B103` etc.). Do not use those macros for this
function.

### Caller expectation (call at `0xB7B140`, return `0xB7B144`)

`func_00B7B034` builds the engine's video-output configuration:

```
0xB7B118  addi r4, r1, 0x70        ; &CellVideoOutResolution on stack
0xB7B11C  rldicl r3, r3, 0, 32     ; resolution id
0xB7B120  bl  0xF996A8             ; cellVideoOutGetResolution
0xB7B124  addi r4, r27, 0x1C       ; &config->screenSize (float, r27 == r31)
0xB7B128  lhz  r9,  0x70(r1)       ; width
0xB7B12C  lhz  r0,  0x72(r1)       ; height
0xB7B130  rldicl r4, r4, 0, 32
0xB7B134  li   r3, 0               ; CELL_VIDEO_OUT_PRIMARY
0xB7B138  stw  r9,  0x14(r31)      ; config->width
0xB7B13C  stw  r0,  0x18(r31)      ; config->height
0xB7B140  bl   0xF998D8            ; cellVideoOutGetScreenSize(0, &config->screenSize)
0xB7B144  lis  r9, 0x10B            ; return address
0xB7B148  lfs  r13, 0x1C(r31)       ; f13 = config->screenSize
0xB7B14C  lfs  r0, -0x6F48(r9)      ; f0 = *(float*)0x10A90B8 = 0x4F0002B2 (2147660288.0f)
0xB7B150  fcmpu cr7, f13, f0
0xB7B154  bne  cr7, 0xB7B160        ; not equal -> keep the value
0xB7B158  li   r0, 0
0xB7B15C  stw  r0, 0x1C(r31)        ; equal to sentinel -> clear to 0.0f
```

The caller ignores the return code. It only cares that the float at
`config+0x1C` is written and is not the constructor's sentinel
`0x4F0002B2`. Writing `24.0f` (`0x41C00000`) satisfies that and gives the
engine a plausible monitor size.

### Proposed implementation

```c
static void gt6_cellVideoOutGetScreenSize(ppu_context* ctx)
{
    const uint32_t videoOut = (uint32_t)ctx->gpr[3];
    const uint32_t out      = (uint32_t)ctx->gpr[4];
    int32_t rc = 0;

    if (!out)                 rc = 0x8002B222; /* ILLEGAL_PARAMETER */
    else if (videoOut != 0)   rc = 0x8002B225; /* UNSUPPORTED_VIDEO_OUT */
    else                      vm_write32(out, 0x41C00000u); /* 24.0f inches */

    ctx->gpr[3] = (uint64_t)(uint32_t)rc;
}
```

Alternative: return `0x8002B228` (`VALUE_IS_NOT_SET`) after writing `0.0f`,
which is what RPCS3 does when 3D/stereo is disabled. The GT6 call site ignores
`r3` and its sentinel check reduces either choice to `0.0` or `24.0`; `24.0` was
chosen because it is a valid screen size and matches RPCS3's default
`screen_size` setting without forcing an error path.

### Risks

- If any future caller uses `screenSize` for a 3D/FOV calculation and expects
  "not set" as `0.0`, `24.0` is a behaviour change. GT6 only calls this once,
  in video configuration, and does not enable stereo in this port.
- The float must be written through `vm_write32` (guest big-endian), not by
  dereferencing the raw guest address. The proposal does that.

### Confidence

- Name, module, stub: **certain**.
- Signature and output type: **certain**.
- Caller expectations: **high** (disassembly + generated code).
- Chosen value/return: design decision, low risk; documented above.

---

## 3. `0x5C832BD7` — `cellUsbdSetThreadPriority2`

### Signature

No public SDK prototype is available in the sources checked, and RPCS3 also
leaves this as `UNIMPLEMENTED_FUNC` with no declared arguments. The GT6 call
site passes **three scalar 32-bit values in r3/r4/r5**, so the ABI-visible
signature is at least:

```c
int cellUsbdSetThreadPriority2(int prio0, int prio1, int prio2);
```

The name and the "2" variant are certain; the exact parameter meanings are
**low confidence** (likely priorities for the USB handler threads). There are
no output pointers.

### Caller expectation (guest `0x8034B4`)

`func_00803464` is the engine's USB init wrapper:

```
0x803478  bl 0xF92B08              ; cellUsbdInit()
0x80347C  r4 = -130
0x803480  r3 = 3
0x803484  bl 0xA30568              ; clamp helper, selector 3
0x803488  r28 = r3                 ; 126
0x80348C  r4 = -129
0x803490  r3 = 3
0x803494  bl 0xA30568
0x803498  r29 = r3                 ; 127
0x80349C  r4 = -128
0x8034A0  r3 = 3
0x8034A4  bl 0xA30568
0x8034A8  r4 = extsw(r29)          ; 127
0x8034AC  r5 = extsw(r3)           ; 128
0x8034B0  r3 = extsw(r28)          ; 126
0x8034B4  bl 0xF92948              ; cellUsbdSetThreadPriority2(126,127,128)
0x8034B8  ...                      ; return address
```

`0xA30568` with selector 3 dispatches to `0xA305BC`, which clamps
`r4 + 0x100` to `[2, 0x1FF]`; `-130,-129,-128` therefore become `126,127,128`,
plausible PPU thread priorities. The wrapper returns immediately after the call
and does not inspect `r3`.

### Proposed implementation

```c
static void gt6_cellUsbdSetThreadPriority2(ppu_context* ctx)
{
    /* The port has no USB host threads; priorities are advisory. */
    ctx->gpr[3] = 0;   /* CELL_OK */
}
```

Log the first call's three values for traceability. A no-op returning
`CELL_OK` matches RPCS3's own stub and cannot corrupt guest state (there are no
output pointers).

### Risks

- If a future real USB-wheel backend needs these priorities, this handler must
  be replaced with one that applies them to the host USB threads. Until then,
  returning an error would only make the engine's init wrapper fail for no
  benefit.
- Exact argument semantics remain unverified. Since the GT6 caller ignores the
  return and passes no pointers, this uncertainty has no consequence at this
  call site.
- Other `cellUsbd` imports in `hle_stubs_named.json` are still unnamed
  (`0x0F411262`, `0x2FB08E1E`, `0x5DE3AF36`, `0x7FE92C54`, `0x90460081`,
  `0xBD554BCB`, `0xDB819E03`). They were not hit during the current boot and
  are out of scope; a future USB-wheel path will need them.

### Confidence

- Name, module, stub: **certain** (log + hash).
- Three-scalar shape: **high** from the call site.
- Meaning of the three values and official prototype: **low**.
- No-op behaviour: **high** (no outputs; RPCS3 does the same).

---

## Cross-check: the existing `cellSpursGetWorkloadFlag` override

The current override is correct and must not change:

```c
vm_write32(out, spurs + 0x60);   /* &spurs->wklFlag */
ctx->gpr[3] = 0;
```

RPCS3's `cellSpursGetWorkloadFlag` writes exactly `spurs.ptr(&CellSpurs::wklFlag)`,
and `CellSpursWorkloadFlag` is at `+0x60`. GT6's new
`_cellSpursWorkloadFlagReceiver2` call immediately precedes it and depends on
this pointer being non-null. The proposed patch keeps the handler and its
registration unchanged. (The existing override does not validate `spurs` or
`out`; the GT6 call site passes both, and hardening it here would change a
verified path for no current benefit.)

`cellSpursGetWorkloadInfo` is already implemented by ps3recomp
(`libs/spurs/cellSpurs.c`) and is not part of this gap.

Runtime dispatch note: `ppu_hle.cpp` checks `prx_resolve_export(nid)` before the
`ps3_hle_register_ctx` table, so a loaded real PRX export wins over these
handlers. GT6PP does not load `libsre.sprx`/`libusbd.sprx` (no PRX loader is
wired in the port), so the handlers are hit. If a real-PRX path is added later,
the firmware implementation taking precedence is the desired behaviour.

---

## Proposed patch and standalone verification

Proposed source (complete, final file):

```
tools/hle_proposals/gt6_stubs_proposed.cpp
```

While this analysis was being finished, the port owner integrated the first
version of the three handlers into `gt6/src/stubs.cpp` (working-tree timestamp
2026-10-31 11:59). That version is correct except for one edge case: it treats
a zero receiver byte as "free" unconditionally, which loses the distinction
between "ps3recomp left it zeroed" and "workload 0 owns the receiver". The
final proposal adds a guard on the flag word (`+0x6C`) and a `vm_read32`
declaration. Two patches are provided:

| Patch | Against | Purpose |
|---|---|---|
| `patches/gt6-hle-nids-2ddbcc0a-faa275a4-5c832bd7.patch` | the currently integrated `gt6/src/stubs.cpp` | incremental final fix (`vm_read32` declaration + wid-0-safe receiver guard); this is the one to apply now |
| `patches/gt6-hle-nids-from-head.patch` | `git HEAD` (pre-integration, 31 lines) | complete patch adding all three handlers, constants, registrations and the final fix; for a pristine tree or review |

Both were checked by applying them to throwaway copies with
`git apply --directory=...`; each produced a file byte-identical to
`tools/hle_proposals/gt6_stubs_proposed.cpp`. The existing
`cellSpursGetWorkloadFlag` handler is untouched by either patch.

This agent did **not** edit `gt6/src/stubs.cpp`; the earlier integration was
performed by the owner. The standalone test distinguishes the two versions: the
currently integrated file fails the `wid == 0` ownership assertion (the second
workload steals the receiver), while the final proposal passes it.

A standalone behavioural test lives under `work/hle_test/` (excluded from the
build). It compiles the proposal with a minimal `ppu_context` and a fake
big-endian guest memory map:

```powershell
tools\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64\bin\clang++.exe `
  -std=c++17 -Wall -Wextra -I work\hle_test `
  work\hle_test\test_stubs.cpp tools\hle_proposals\gt6_stubs_proposed.cpp `
  -o work\hle_test\test_stubs.exe

$env:PATH = (Resolve-Path 'tools\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64\bin').Path + ';' + $env:PATH
work\hle_test\test_stubs.exe
```

Result (`exit=0`):

```
[GT6] _cellSpursWorkloadFlagReceiver2(spurs=0x00001000 wid=3 set=1) -> 0x00000000
[GT6] cellVideoOutGetScreenSize(videoOut=0 out=0x00004000) -> 0x00000000 (24.0 inch default)
[GT6] cellUsbdSetThreadPriority2(126, 127, 128) -> CELL_OK
PASS: 4 handlers registered; GetWorkloadFlag, WorkloadFlagReceiver2,
      VideoOutGetScreenSize and UsbdSetThreadPriority2 behave as expected
```

The test covers:

- The exact GT6 sequence: `_cellSpursWorkloadFlagReceiver2(spurs,3,1,0)` then
  `cellSpursGetWorkloadFlag(spurs,&out)`; the receiver survives and `out` is
  `spurs+0x60`.
- Receiver set/unset, same-wid idempotence, `BUSY`, `PERM`, null and invalid
  `wid`, plus the `wid == 0` ownership case that the zero-init workaround must
  not misread as "free".
- Screen size success (24.0f), null out-pointer and non-primary output errors.
- USB priority call returning `CELL_OK`.

This does **not** exercise the real `gt6.exe` build; `gt6/build` was not
touched.

---

## Integration steps

1. Finish the integration. Check whether `gt6/src/stubs.cpp` already contains
   `gt6_cellSpursWorkloadFlagReceiver2`:

   - **Already integrated** (current working tree as of 11:59): apply the
     incremental final fix, or copy the complete proposal over the file:

     ```powershell
     git apply patches/gt6-hle-nids-2ddbcc0a-faa275a4-5c832bd7.patch
     # or: Copy-Item tools\hle_proposals\gt6_stubs_proposed.cpp gt6\src\stubs.cpp
     ```

   - **Still at the pre-integration HEAD version** (31-line file with only
     `cellSpursGetWorkloadFlag`): apply the full patch:

     ```powershell
     git apply patches/gt6-hle-nids-from-head.patch
     ```

2. Rebuild `gt6.exe` with the normal build (owner of `gt6/build`; not this
   agent):

   ```powershell
   powershell -File scripts/build-gt6.ps1
   ```

3. Boot with the unresolved-NID diagnostic enabled to prove all three now
   resolve:

   ```powershell
   $env:PS3_HLE_UNRESOLVED = 'fail'
   powershell -File scripts/run-gt6.ps1 -Seconds 30
   ```

   Expected: no `[hle] unresolved NID 0x2DDBCC0A`, `0xFAA275A4` or `0x5C832BD7`
   lines, and one each of the new `[GT6]` trace lines. The pre-existing
   `cellSpursGetWorkloadFlag` path must still log/behave as before.

4. Sanity-check that the init flag path (`0x13BE8` / `0xA13644`) now gets past
   the point that previously returned 0; if it does not, the receiver/flag
   writes are not the gate and the next suspect remains the scheduler/flag
   semantics described under risks.

5. If anything regresses, remove only the three new `ps3_hle_register_ctx`
   calls; the existing `cellSpursGetWorkloadFlag` override is independent.

---

## Source and licensing notes

- The names and signatures were read from RPCS3's source and from the RPCS3
  log of this title, used only as an oracle. No RPCS3 code was copied; the
  implementations above are original MIT-compatible C++ written against the
  ps3recomp HLE ABI and the documented guest layout.
- The PS3 firmware `libsre.sprx` / `libusbd.sprx` in `tools/RPCS3/dev_flash`
  are encrypted SELF files and were not decrypted. The RPCS3 boot log's export
  table was sufficient to confirm both names.
- `work/analysis/rpcs3_ref/` contains downloaded reference sources used for
  this analysis; `work/` is gitignored and not part of the port.
