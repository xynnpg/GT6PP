# Status — 2026-10-31

This is a measured snapshot, not a plan. Re-run the commands before trusting a
number after a new lift.

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
  --functions work/analysis/emain/functions_final3.json `
  --hle-stubs work/analysis/emain/hle_stubs.json `
  --output gt6/generated --code-end 0xF908C4 --chunks 40 --jobs 8
```

Result: **78,770 functions** lifted (68,149 explicit boundaries plus 10,621
mid-function tail-entry wrappers) into 41 chunks plus `ppu_recomp_table.cpp`.
The first pass used only the `.opd` table (33,091 entries → 71,875 lifted
functions) and missed indirect-call targets. `find_functions.py` then found
67,322 boundaries; explicit entries were added for the multi-entry memset/memcpy
family (`0xA4FD30..0xA4FF30`) and `0xA305B0`, `0xA56F64`, `0xAF2658`.
`gt6/generated/` is ~450 MB of C++ and is gitignored.

`tools/ppu_loader.py` reported 33,091 unique functions; the extra lifted entries
are internal labels/tail entries, not new source-level functions.

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
- One unresolved HLE NID: `0xFAA275A4` (`cellSysutilAvconfExt`).
- A second: `0x2DDBCC0A` (`cellSpurs`, name unknown) and `0x5C832BD7`
  (`cellUsbd`, name unknown).
- `cellSpursGetWorkloadFlag` (`0xC765B995`) was missing; `src/stubs.cpp` now
  returns `spurs+0x60` (the real `wklFlag` offset), and the NID is no longer
  unresolved.

The remaining blocker at this snapshot is a set of **indirect calls into
mid-function entries** that the OPD list did not cover (memset/memcpy-like
routines at `0xA4FD30..0xA4FF30`, plus `0xA305B0`, `0xA56F64`, `0xAF2658`). The
heuristic `find_functions.py` found **67,322** boundaries; the final lift adds
the whole multi-entry range explicitly. The game currently reaches `main`
(`0x1096C`), calls the Adhoc/VM init at `0x13BE8`, then checks a byte flag via
`0x3C0E84`. The flag is 0, so `main` prints `scripts/gt6/main` and returns 0.
The final relift is meant to remove the unresolved memset/memcpy calls that
corrupt this init. No frame has been presented yet.

## Asset tools

`tools/mdl3_export.py` parses ModelSet3 headers, FVFs, meshes, and separate-car
data. It exported car `0001/0001` `wheel` (636 verts / 650 tris) and `interior`
(2,045 verts / 3,700 tris) to OBJ; `tools/obj_preview.py` rendered both to PNG.
`hq/body` is packed/streamed (`PMSH`/`body_s`) and is not directly exportable
yet. See `docs/ASSETS.md`.

## Known issues / risks

1. **Boot-script init flag.** `main` at `0x1096C` runs the init chain at
   `0x13BE8`; the byte flag returned by `0xA13644` (`obj+0x10`) is 0, so `main`
   prints `scripts/gt6/main` and returns 0. This is the current stop.
2. **Remaining HLE NIDs.** `0xFAA275A4` (`cellSysutilAvconfExt`),
   `0x2DDBCC0A` (`cellSpurs`, name unknown), `0x5C832BD7` (`cellUsbd`, name
   unknown). `cellSpursGetWorkloadFlag` is now implemented in
   `gt6/src/stubs.cpp`.
3. **Static-constructor null calls.** `0x118C8` calls null entries in the
   constructor/finalizer table (`lr=0x1190C`). Some may be optional; they have
   not been individually identified.
4. **`setjmp`/`longjmp` not patched.** GT5P's LZ decoder required a host-side
   `setjmp` patch. GT6's equivalents have not been located. If the volume reader
   spins or corrupts memory, this is the first suspect.
5. **`GT.VOL` path.** The game's own reader must open the volume through the
   VFS. A hardlink `gt6/GT.VOL` is created for relative opens, and
   `/dev_bdvd/` is mapped to the extracted `PS3_GAME` tree.
6. **GCM base address.** `GT6_GCM_CTRL_BASE=0x03000000` is inherited from GT5P;
   GT6's heap may use it. If the guest corrupts its allocator, move it.
7. **No verified GT6 port exists.** Treat any claim of a working GT6 PC port
   without a reproducible build with suspicion.

## Next actions

1. Instrument `0x13BE8` / `0xA13644` to find which init step is supposed to set
   the byte flag, and compare the sequence with an RPCS3 log of the same boot.
2. Identify `0x2DDBCC0A` (`cellSpurs`) from RPCS3's NID table or the call site at
   `0xB6E848`; implement it in `gt6/src/stubs.cpp` with the real output layout.
3. Stub or implement `0xFAA275A4` (`cellSysutilAvconfExt`) and `0x5C832BD7`
   (`cellUsbd`) with valid outputs.
4. Once the flag is true, confirm `scripts/gt6/main.adc` opens through
   `cellFs`/`sys_fs` and that the Adhoc VM starts.
5. Then move to the RSX first-frame work in M3.
