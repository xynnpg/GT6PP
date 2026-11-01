# Status — 2026-11-01

> **Current state (2026-11-01):** boot script parses fully; UI scripts load; `MGOM.start("boot")`
> fires and the native pump reaches the real manager's pending-project state. Manager remains at
> state 2 after `boot.mproject`/`boot.adc`; no `K/IE` or `K/WD` request and no real textured draw
> verified. Black 1280x720 window. See [analysis/boot-project-handoff-fix.md](analysis/boot-project-handoff-fix.md)
> for the state-2 blocker.

## Media

| Item | Value |
|---|---|
| Title | Gran Turismo 6 (USA) |
| Title ID | `BCUS98296` |
| APP_VER | `01.00` |
| PS3 system version | `04.5000` |
| ISO | 25,293,815,808 bytes |
| `EBOOT.BIN` | 72,920 bytes, SCE SELF → 143,064-byte decrypted ELF |
| `EMAIN.SELF` | 8,843,160 bytes, SCE SELF → 22,371,400-byte decrypted ELF |
| `GT.VOL` | 15,407,310,848 bytes, PFS volume serial `405868366` |
| `GT.VOL` title string | `GT6-PISCINAS-323419048` |
| Extracted volume | 32,591 files, 25,106,251,121 bytes |

`GT.VOL` was unpacked with `GTToolsSharp 5.3.5` (MIT) using its built-in GT6
keyset. The decrypted volume header and TOC are saved as
`VolumeHeader.bin` / `VolumeTOC.bin` in the project root (ignored by git).

## Executable analysis

`work/bin/EMAIN.elf`:

- ELF64, `EM_PPC64`, big-endian, `ET_EXEC`
- entry OPD `0x148e2e0` → code `0x10230`, TOC `0x14ed560`
- 2 PT_LOAD segments:
  - `0x10000..0x1403068` (file-backed, RX)
  - `0x1410000..0x16b2e58` (file + 0x1532ac BSS, RW)
- 44,626 OPD descriptors, 33,091 unique functions
- last executable address: `0xF908C4` (the next OPD entry points into `.rodata`
  and was filtered out)
- 747 imports across 46 libraries:

| Library | Imports | Unresolved names |
|---|---:|---:|
| `sceNp` | 64 | 14 |
| `cellSysutil` | 55 | 13 |
| `cellSpurs` | 49 | 1 |
| `sceNp2` | 48 | 12 |
| `cellGcmSys` | 39 | 0 |
| `sysPrxForUser` | 38 | 5 |
| `sys_net` | 34 | 9 |
| `sceNpCommerce2` | 32 | 4 |
| `cellSail` | 31 | 18 |
| `cellHttp` | 28 | 13 |
| `cellSysutilAvc2` | 27 | 13 |
| `sys_fs` | 26 | 4 |
| `sys_io` | 23 | 5 |
| `cellAudio` | 12 | 0 |
| `cellGame` | 8 | 0 |
| `cellSysmodule` | 6 | 0 |
| `cellSpurs` | 49 | 1 |
| `libvdec` | 8 | 0 |

533 of 747 NIDs are named by the current `ps3recomp` database. The unresolved
names are concentrated in network, media, USB, and UI modules; they are the
expected HLE gap.

`work/bin/EBOOT.elf` is the 188-function bootstrap. Its strings reference
`EBOOT.BIN`, `EMAIN.SELF`, `/dev_bdvd`, and `/dev_hdd0`, confirming it is a
loader; the port targets `EMAIN.elf` directly, as GT5P does.

## Toolchain on this machine

| Tool | Version / path |
|---|---|
| Python | 3.11.15 (hermes venv) |
| CMake | 4.4.4 (pip package) |
| Ninja | 1.13.2 (pip package) |
| Compiler | LLVM-MinGW 20261020 (Clang 23.1.4, UCRT, x86_64) |
| Runtime build | `work/build_ps3recomp` — **succeeds** |
| `_WIN32_WINNT` | `0x0A00` (needed for `GetCurrentThreadStackLimits`) |

`ps3recomp` v0.18.0 builds as `libps3recomp_runtime.a` with this toolchain.
D3D12 headers and libraries are found; `#pragma comment(lib, ...)` is ignored by
MinGW, so the port's CMake links `d3d12 dxgi dxguid d3dcompiler ws2_32 xinput
ole32 bcrypt` explicitly.

## Current lift

Command used:

```powershell
python third_party/ps3recomp/tools/ppu_lifter.py work/bin/EMAIN.elf `
  --functions work/analysis/emain/functions_corrected.json `
  --hle-stubs work/analysis/emain/hle_stubs.json `
  --output gt6/generated --code-end 0xF908C4 --chunks 40 --jobs 8
python tools/setjmp_patch_gt6.py gt6/generated
powershell -File scripts/lift-spu-gt6.ps1 -Force
```

The current list is the **boundary audit's corrected list**: 70,672 explicit
boundaries (from 64,134), with 3,512 ends corrected and 8,264 starts added. The
lifter emitted **75,418 functions** into 41 chunks plus
`ppu_recomp_table.cpp`. The previous heuristic list produced 78,770 functions;
the difference is mostly removed over-merges and the extra mid-function
wrappers that are no longer needed.

`tools/setjmp_patch_gt6.py` wraps GT6's real setjmp (`0xB98168`) at 21 call
sites and rewrites longjmp (`0xB9828C`) so it transfers control to the matching
host setjmp. Without it the lifted longjmp restores the guest registers and then
returns to the wrong caller.

`gt6/generated/` is ~450 MB of C++ and is gitignored.

## Build

The first `gt6.exe` link attempt failed on two MinGW/Clang incompatibilities in
`ppu_loader.cpp` (MSVC `__try`/`__except`, and a `static inline` vs `extern "C"`
mismatch). Both are fixed locally; see `patches/ps3recomp-mingw-seh.patch` and
`docs/PATCHES.md`. The rebuilt executable is the next milestone.

## First boot (2026-10-31)

`gt6.exe work/bin/EMAIN.elf` now reaches the guest and runs real engine code:

- `ppu_run` dispatches the entry OPD `0x148E2E0` → code `0x10230`, TOC `0x014ED560`.
- `sys_initialize_tls` creates the TLS block; `r13=0x0E007000`.
- The CRT parses argv, initializes C++ constructors, and calls `_cellGcmInitBody`
  (`cmdSize=0x10000`, `ioSize=0x100000`, `ioAddr=0x70000000`).
- `cellSpurs` initializes 5 SPUs and creates workloads (`Wws_Job` /
  `ElemSetRenderHP`, `ElemSetRender`, ...).
- `cellGcmSys` configures four 1280x720 display buffers (pitch 6144) and a flip
  handler. No flip is submitted yet.
- The engine creates worker threads (`MpAnk`, `ZBm9Y`, `kFeqP`, `kFeqg`,
  `ksF3` × several, `Spu Event Handler`) and enters its frame loop.
- **4 embedded SPU images** were extracted and lifted (108 / 159 / 396 / 626
  functions) and are registered by fingerprint; the build has
  `GT6_ENABLE_SPU=ON`.
- All three remaining boot imports are now implemented in `src/stubs.cpp`:
  `0x2DDBCC0A` `_cellSpursWorkloadFlagReceiver2`, `0xFAA275A4`
  `cellVideoOutGetScreenSize`, and `0x5C832BD7` `cellUsbdSetThreadPriority2`.
  `cellSpursGetWorkloadFlag` (`0xC765B995`) remains as before (`spurs+0x60`).
  Boot logs show no `unresolved NID` lines.
- The raw WWS job-manager policy module at guest `0x013FFE00` (12,160 bytes,
  fingerprint `0x5510DCB89C1E98C2`) is lifted as image id 5 and registered by
  `gt6_spu_register_pm_clean()`. All eight `cellSpursAddWorkload` calls now log
  `PM resolved (image=5)`; the policy module runs DMA commands. No workload is
  kicked because the boot still exits first.

## Boot stop (corrected 2026-10-31)

The earlier claim that `0xA13644` was an 8-byte leaf getter
(`lbz r3,0x10(r3); blr`) was **wrong**. The real function is 0x5C bytes: it
locks the mutex at `0x0164AB50`, calls `0x3C0E84` on the global at `0x0164AB80`,
unlocks, and returns the low byte. The fake leaf read byte 0x10 of the `HADHOC`
config string, which produced the bogus `flag=0x40` gate.

With the real function restored, the chain at `0x13BE8` runs **all 15 stages**
with `flag=0x00` at every check and returns normally. `main` (`0x1096C`) then:

1. calls `0x13830` with `r3 = "scripts/gt6/main"` (`0x00FB0AB8`);
2. `0x13830` constructs the path string, calls `0xB98168` (`setjmp`, returns 0),
   loads the manager from `0x01570D58`, and calls its virtual slot
   `[manager->vtable + 0x120]`;
3. that dispatches to guest `0x009A7654` (`ctr`), which calls
   `0x9CDF00 -> 0x9CD798 -> 0x9CC068(this, path, ...)` and **returns 0
   immediately** — no `cellFs`/`sys_fs` open for `scripts/gt6/main` and no
   `GT.VOL` open appears in the run;
4. `main` walks the finalizer list at `0x16A99D0` (head
   `0x016B0000-0x6630`), returns 0, and the CRT calls `sys_process_exit(0)`.

`YDKJ_NOEXIT=1` only parks the main thread; the other engine threads still
join/exit. No frame has been presented yet.

## Asset tools

`tools/mdl3_export.py` parses ModelSet3 headers, FVFs, meshes, and separate-car
data. It exported car `0001/0001` `wheel` (636 verts / 650 tris) and `interior`
(2,045 verts / 3,700 tris) to OBJ; `tools/obj_preview.py` rendered both to PNG.
`hq/body` is packed/streamed (`PMSH`/`body_s`) and is not directly exportable
yet. See `docs/ASSETS.md`.

## Known issues / risks

1. **Boot-script dispatch returns immediately.** The real init chain completes
   with flag 0; `main` calls the script manager at `0x13830` with
   `"scripts/gt6/main"`, which dispatches to `0x009A7654` and returns 0 without
   any file open. This is the current stop. `0x9CC068` / `0x9CD798` are the
   functions to inspect next.
2. **No remaining unresolved boot NIDs.** The three were implemented and are
   logged as resolved in `gt6/src/stubs.cpp`.
3. **Static-constructor walk corrupts `r31`.** `0x118C8` walks the table at
   `0x1410B48` down to the `-1` terminator at `0x1410000`. The first ~120
   constructors preserve `r31`; after that it becomes 0 and the walker calls
   NULL repeatedly. This is being traced with `[ctor] BAD` instrumentation.
4. **`setjmp`/`longjmp`.** Now patched for GT6's real pair
   (`0xB98168`/`0xB9828C`) by `tools/setjmp_patch_gt6.py`: 21 setjmp call sites
   and 14 arming functions. The patch must be re-run after every relift.
5. **`GT.VOL` path.** The game's own reader must open the volume through the
   VFS. `gt6/src/main.cpp` now resolves every `cellFs` mapping to an absolute
   host path and sets `ppu_vfs_root` to the game root; before this, cellFs
   prepended its USRDIR root to the relative mappings and the absolute
   `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` open could never land. No GT.VOL open has
   been observed yet because the constructor/script path still fails first.
6. **GCM base address.** `GT6_GCM_CTRL_BASE=0x03000000` is inherited from GT5P;
   GT6's heap may use it. If the guest corrupts its allocator, move it.
7. **No verified GT6 port exists.** Treat any claim of a working GT6 PC port
   without a reproducible build with suspicion.

## Next actions

1. Trace `0x9CC068` / `0x9CD798` / `0x9A7654`: determine why the script-manager
   call returns 0 without opening `scripts/gt6/main` or `GT.VOL`.
2. Confirm whether the script load is asynchronous and which worker is supposed
   to run it; if so, make `main` wait for that worker instead of returning to
   the CRT.
3. Apply the boundary audit's corrected function list (but do **not** shorten
   `0xA13644`; that range is correct) and relift.
4. Once the boot script opens, capture the next `cellFs`/`sys_fs` stop and the
   first `GT.VOL` read.
5. Then move to the RSX first-frame work; the D3D12 backend already initializes
   at 1280x720 on this machine, and tiles/Zcull/display buffers are configured.
