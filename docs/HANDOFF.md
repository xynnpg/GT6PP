# Handoff — where the GT6 port stands

**Date:** 2026-10-31. **Target:** GT6 US disc `BCUS98296` v1.00. **Build:**
`gt6/build/gt6.exe` (LLVM-MinGW, 78,770 lifted PPU functions, 4 lifted SPU
images). **Frame:** none yet.

This file is the shortest path for the next agent/session. Read
[docs/STATUS.md](STATUS.md) for the measured log and
[docs/BOOT.md](BOOT.md) for diagnostics.

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

The guest reaches `main` at `0x1096C`, runs the init chain at `0x13BE8`, then
checks a byte flag through `0xA13644` (`lbz r3,0x10(r3)`). The flag is 0, so
`main` prints `scripts/gt6/main` and returns 0. The CRT then calls
`sys_process_exit(0)`.

Key addresses:

| Address | Meaning |
|---|---|
| `0x1096C` | guest `main` (called by CRT `0x10338`) |
| `0x13BE8` | init chain (many steps, each followed by a flag check) |
| `0xA13644` | `return obj->byte[0x10]`; the boot-script/init flag |
| `0x118C8` | static-constructor/finalizer table walker; null calls at `lr=0x1190C` |
| `0x1024C` | `_start` body; calls CRT then `sys_prx_exitspawn_with_level` |
| `0x10300` | CRT `exit()`; calls `sys_process_exit` |

## Priority order

1. **Make the init flag true.** Instrument `0x13BE8` (each `bl` step) and
   `0xA13644`; find which step is supposed to set `obj+0x10`. Compare against an
   RPCS3 log of the same boot (`Log Level: All`). This is the current gate.
2. **Identify the three unresolved NIDs.**
   - `0x2DDBCC0A` (`cellSpurs`): caller at `0xB6E848` sets `r3=spurs`,
     `r4=[r22+8]`, `r5=0`, `r6=0`. Likely a workload-info/contention call.
   - `0xFAA275A4` (`cellSysutilAvconfExt`): only one import in this module.
   - `0x5C832BD7` (`cellUsbd`): one of the USB/wheel calls.
   Implement overrides in `gt6/src/stubs.cpp`; register with
   `ps3_hle_register_ctx(nid, name, fn)` after `ppu_hle_register_all()`.
3. **Fix the null constructor calls.** `0x118C8` reads a table at
   `r2-0x7fb0` (`0x14E55B0`). A zero entry may be a relocation that the runtime
   does not apply. If the flag fix requires a constructor, this is the next
   suspect.
4. **Then the script VM.** Once the flag is true, the game should open
   `scripts/gt6/main.adc` (857 KB, present in `work/gt6_vol/scripts/gt6/`).
   Confirm the open in the log (`[cellFs] Open` or `[sys_fs] open OK`). If the
   path is wrong, adjust `GT6_USRDIR`/`g_sys_fs_root` mappings.
5. **Then RSX.** `cellGcmInit` and four display buffers already work. The first
   goal is a flip/first frame, then menu/attract mode.

## Adding a missing PPU function

If a dispatch miss names a guest address:

```powershell
# Add the start to work/analysis/emain/functions_final3.json (or a new copy),
# then relift. Keep start < 0xF908C4.
python third_party/ps3recomp/tools/ppu_lifter.py work/bin/EMAIN.elf `
  --functions work/analysis/emain/functions_final3.json `
  --hle-stubs work/analysis/emain/hle_stubs.json `
  --output gt6/generated --code-end 0xF908C4 --chunks 40 --jobs 8
# Re-lift SPU afterwards if the PPU relift wiped generated/spu_lifted.
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
- 4 SPU images lifted and registered (108 / 159 / 396 / 626 functions).
- `cellSpursGetWorkloadFlag` override is active (NID no longer unresolved).
- MDL3 wheel/interior export + software preview.

## Do not

- Do not commit `gt6/generated/`, `gt6/build/`, `work/`, `PS3-Version/`,
  `third_party/`, decrypted ELFs, `GT.VOL`, or `key.json`.
- Do not replace a real HLE implementation with a silent `CELL_OK` when the
  function has output pointers; the guest may read uninitialized memory.
- Do not assume a clean exit is success. A `sys_process_exit(0)` after `main`
  returns is the current failure mode, not a finished boot.
