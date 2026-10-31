# Handoff — where the GT6 port stands

**Date:** 2026-10-31. **Target:** GT6 US disc `BCUS98296` v1.00. **Build:**
`gt6/build/gt6.exe` (LLVM-MinGW, 75,652 lifted PPU functions, 15 runtime SPU
job images). **Frame:** black 1280×720; boot script and UI scripts load, but
`draws: 0`.

**Current handoff:** [docs/analysis/CONTINUE-HERE.md](analysis/CONTINUE-HERE.md).
This file is the historical shortest path; `STATUS.md` is the measured snapshot
and `BOOT.md` has the early diagnostics.

## Reproduce

```powershell
# Toolchain + checkout (if starting fresh)
# - LLVM-MinGW in tools/llvm-mingw
# - ps3recomp in third_party/ps3recomp (apply patches/ps3recomp-mingw-seh.patch)
# - GT5P scripts in third_party/GT5P
# - decrypted work/bin/EMAIN.elf

powershell -File scripts/relift-gt6.ps1    # PPU lift + HLE NID table
# After a PPU relift, re-lift SPU images (they live under gt6/generated):
python third_party/ps3recomp/tools/build_spu_workloads.py `
  --images work/analysis/spu --lifted gt6/generated/spu_lifted `
  --out gt6/src/gen/spu_workloads.c --register-fn gt6_spu_register_all --title GT6

powershell -File scripts/build-gt6.ps1
powershell -File scripts/run-gt6.ps1 -Seconds 30
```

The build cache is `gt6/build/`; incremental rebuilds only compile changed
chunks plus the link. A full relift rebuild is ~10 minutes at `-j 8`.

## Current stop (measured)

```
[GT6] Executing entry OPD 0x0148E2E0 ...
[cellGame] BootCheck: type=1, titleId='BCUS98296'
[cellGame] ContentPermit() -> /dev_bdvd/PS3_GAME
[cellGcmSys] Init(cmdSize=0x10000, ioSize=0x100000, ioAddr=0x70000000)
[cellGcmSys] SetDisplayBuffer(id=0..3, 1280x720, pitch=6144)
[cellSpurs] Initialize "PDI" ... nSpus=5
[cellSpurs] AddWorkload ... "Wws_Job"/"ElemSetRenderHP" ...
...
[sysPrxForUser] sys_process_exit(code=0)
```

The guest reaches `main` at `0x1096C`, runs the init chain at `0x13BE8`, and
completes **all 15 stages** with the real flag at `0x00` every time. The earlier
claim that `0xA13644` was a leaf getter (`lbz r3,0x10(r3); blr`) was wrong; the
real function is 0x5C bytes and locks `0x0164AB50`, calls `0x3C0E84` on
`0x0164AB80`, unlocks, and returns the low byte. The fake leaf read byte 0x10 of
the `HADHOC` config string and produced the bogus `0x40` value. It has been
reverted; `tools/post_lift_fixes.py` now only verifies the real body.

`main` then calls `0x13830` with `"scripts/gt6/main"`. `0x13830` constructs the
path, calls `0xB98168` (`setjmp`, returns 0), loads the manager from
`0x01570D58`, and calls virtual slot `[manager->vtable + 0x120]`. That dispatches
to guest `0x009A7654` and **returns 0 immediately**; no `cellFs`/`sys_fs` open
for `scripts/gt6/main` and no `GT.VOL` open occurs. `main` walks the finalizer
list at `0x109DC` and returns 0; the CRT calls `sys_process_exit(0)`.
`YDKJ_NOEXIT=1` parks main but the engine threads still join/exit.

Key addresses:

| Address | Meaning |
|---|---|
| `0x1096C` | guest `main` (called by CRT `0x10338`) |
| `0x13BE8` | init chain (15 stages, each followed by a flag check) |
| `0xA13644` | real flag getter: mutex `0x0164AB50`, `0x3C0E84(0x0164AB80)`, returns low byte |
| `0x13830` | boot-script loader: `setjmp`, then virtual `[manager+0x120]` |
| `0x9A7654` | script-manager virtual target; returns 0 without opening the script |
| `0x9CDF00` / `0x9CD798` / `0x9CC068` | script load path to inspect next |
| `0x118C8` | static-constructor/finalizer table walker; null calls at `lr=0x1190C` |
| `0x1024C` | `_start` body; calls CRT then `sys_prx_exitspawn_with_level` |
| `0x10300` | CRT `exit()`; calls `sys_process_exit` |

## Priority order

1. **Why the boot-script dispatch returns 0.** Trace `0x9A7654 -> 0x9CDF00 ->
   0x9CD798 -> 0x9CC068`. Determine whether this is an async queue (and main is
   supposed to wait) or a failed lookup. No file open is attempted today.
2. **Keep the process alive only when the guest expects it.** If the script VM
   is asynchronous, identify the worker/condition main should wait on. Do not
   globally park threads as a substitute.
3. **Apply the boundary audit's corrected list** after checking that it does
   not include the false `0xA13644` leaf correction. Then relift and rebuild.
4. **Then the script/PDIPFS reads.** The game should open
   `scripts/gt6/main.adc` (857 KB, present in `work/gt6_vol/scripts/gt6/`).
   Confirm `[cellFs] Open`/`[sys_fs] open OK`; if absent, check VFS mappings.
5. **Then RSX.** `cellGcmInit`, tiles/Zcull and four display buffers work; the
   D3D12 backend initializes at 1280x720. The first goal is a flip/first frame,
   then menu/attract mode.

The three boot NIDs and the WWS policy module are done; see the "verified good"
list below.

## Adding a missing PPU function

If a dispatch miss names a guest address:

```powershell
# Prefer the boundary audit's corrected list; do not use the raw OPD list.
# Add the missing start to functions_corrected.json (keep start < 0xF908C4).
python third_party/ps3recomp/tools/ppu_lifter.py work/bin/EMAIN.elf `
  --functions work/analysis/emain/functions_corrected.json `
  --hle-stubs work/analysis/emain/hle_stubs.json `
  --output gt6/generated --code-end 0xF908C4 --chunks 40 --jobs 8
# Always re-apply the control-flow patches after a lift:
python tools/setjmp_patch_gt6.py gt6/generated
powershell -File scripts/lift-spu-gt6.ps1 -Force
```

The lifter's mid-function pass handles branch targets inside a lifted function,
but **not** multi-entry routines referenced only by data tables. That is why the
`0xA4FD30..0xA4FF30` range is listed explicitly.

## Adding an HLE override

`gt6/src/stubs.cpp` is the place. The handler signature is
`void (*)(ppu_context*)`; write outputs through `vm_write*` (guest addresses, not
host pointers), set `ctx->gpr[3]` to the return code, and register with
`ps3_hle_register_ctx`. Example: the `cellSpursGetWorkloadFlag` override returns
`spurs+0x60`, the real `wklFlag` offset.

## What is already verified good

- `GT.VOL` decryption/unpack: 4,207 TOC entries, 32,591 files, ~25.1 GB.
- `EBOOT.BIN`/`EMAIN.SELF` decryption; `EMAIN.elf` loads at its linked addresses.
- `ppu_run` PS3 process-entry ABI (TLS, argv, stack) works.
- `cellGcmInit`, four 1280x720 display buffers, flip handler.
- `cellSpurs` initializes 5 SPUs and creates `Wws_Job` workloads.
- 4 embedded SPU ELFs lifted/registered (108 / 159 / 396 / 626 functions), plus
  the raw WWS job-manager PM as image 5 (190 functions); 8/8 PMs resolve.
- All three boot HLE NIDs implemented; `cellSpursGetWorkloadFlag` still returns
  `spurs+0x60`.
- D3D12 backend initializes at 1280x720 on the test machine (windowed run).
- MDL3 wheel/interior export + software preview.

## Do not

- Do not commit `gt6/generated/`, `gt6/build/`, `work/`, `PS3-Version/`,
  `third_party/`, decrypted ELFs, `GT.VOL`, or `key.json`.
- Do not replace a real HLE implementation with a silent `CELL_OK` when the
  function has output pointers; the guest may read uninitialized memory.
- Do not assume a clean exit is success. A `sys_process_exit(0)` after `main`
  returns is the current failure mode, not a finished boot.
