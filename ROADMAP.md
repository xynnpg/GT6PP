# Roadmap

Status legend: **done** · **active** · **next** · **blocked** · **later**

## M0 — Research and media extraction (done)

- [x] Identify the disc: `BCUS98296`, APP_VER `01.00`, PS3 `04.5000`.
- [x] Parse `PARAM.SFO`, trophy set, ISO/UDF layout.
- [x] Decrypt and unpack `GT.VOL` with GTToolsSharp: 4,207 TOC entries,
      32,591 files, ~25.1 GB expanded.
- [x] Decrypt `EBOOT.BIN` and `EMAIN.SELF` with RPCS3's offline decryptor.
- [x] Parse the PPU ELF: 44,626 OPD descriptors, 33,091 unique functions,
      747 imports across 46 libraries.
- [x] Resolve 533/747 import NIDs against the ps3recomp database.
- [x] Write the feasibility and format reports in `docs/research/`.

## M1 — PPU lift and link (active)

- [x] Filter the OPD function list to executable addresses
      (`start < 0xF908C4`).
- [x] Generate `hle_stubs.json` from the ELF's import table.
- [x] Lift 68,149 explicit boundaries to 78,770 C++ functions (41 chunks,
      including the multi-entry memset/memcpy targets).
- [x] Generate the HLE NID table (`src/gen/ppu_hle_nids.cpp`).
- [x] Configure and build `gt6.exe` with the llvm-mingw toolchain.
- [x] Boot the guest `_start`; reaches `_cellGcmInitBody`, display buffers,
      SPURS workloads, and the engine's worker threads.
- [x] Eliminate the observed unresolved indirect calls with the expanded lift.
- [ ] Set the boot-script/init flag; implement the remaining HLE handlers.

**Exit criteria:** `gt6.exe work/bin/EMAIN.elf` starts, runs the CRT, and reaches
a deterministic stop with a named missing syscall/HLE function.

## M2 — Deterministic engine boot and asset load (active)

- [x] Serve `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` and `PARAM.SFO` through the VFS.
- [x] Fix the guest main stack / argv / TOC / TLS setup (`ppu_run` handles it).
- [x] Implement `cellGcmInit`, display buffers, `cellSpurs` init/workloads.
- [x] Make the init flag at `0xA13644` true (current stop). Boot now runs past it on the EU disc (BCES01893).
- [ ] Resolve `0x2DDBCC0A`, `0xFAA275A4`, `0x5C832BD7`.
- [x] *(2026-11-21)* Boot-2 validator passes on the EU disc: root cause was an empty file cache (`B5B260`), fixed via cache-fill workaround (see `docs/analysis/eu-boot-status.md`).
- [x] *(2026-11-21)* Stub `cellMusicInitialize2` (NID `0xBE50B11E`); game now reaches the language-select dialog at ~36 FPS.
- [ ] cellMusic callback and syscall 327 are still stubbed (2x).
- [x] Load the first `GT.VOL` assets (menus, fonts, scripts). `boot.adc`, `BootProject.gpb` and `PresentsRootSCEE.gpb` load on the EU disc.
- [ ] Add `longjmp`/`setjmp` support if the LZ decoder stalls (GT5P required
      this).

**Exit criteria:** 8/8 identical boots that open the volume and load a stable
set of assets.

## M3 — RSX/GCM and first frame (next)

- [ ] Bring up the D3D12 backend, RSX local memory, tiles, Zcull, display
      buffers.
- [x] Drain the GCM FIFO and parse the first command buffer. Clears, immediate draws and flips run; with `FP_FORCE=1` the backbuffer fills with geometry. Real frames are still black.
- [ ] Translate the first RSX vertex/fragment shaders.
- [x] Present one frame from the game's own command stream. *(EU disc: the "Sony Computer Entertainment presents" legal screen renders, see `docs/analysis/first-frame-sce.png`.)*
- [x] *(2026-11-21)* Display-offset textures get a screen copy; unwritten zeta textures are filled (`patches/ps3recomp-v0.19.0-gt6-eu-all.patch`).
- [x] *(2026-11-21)* Language-select dialog renders: panel, title, 4 menu rows. Text is readable via stencil glyphs plus zeta-as-texture (`patches/ps3recomp-v0.19.0-gt6-eu-all.patch`).
- [x] *(2026-11-21)* Debug tooling: `scripts/cap-gt6.ps1` (one-call render experiments), `TEXDUMP`, zeta fields in the capture manifest.
- [x] *(2026-11-21)* Dialog background fixed: stale attribute-3 (col0) array ignored, matches the RPCS3 reference (dark uniform background, translucent panel) (`patches/ps3recomp-v0.19.0-gt6-eu-all.patch`, `docs/analysis/eu-language-select-bg.png`).
- [x] Title colour (blue) and cursor: a3 is only trusted for the text-quad VS (fp 0x4E739C1, a3.x = palette index); all other draws take col0 from VERTEX_DATA4F. Rule applied at BEGIN_END (before layout build), `patches/ps3recomp-v0.19.0-gt6-eu-all.patch`. Row-1 hover highlight vs RPCS3 not verified.
- [ ] Fix color-buffer / render-target issues as they appear.

**Exit criteria:** a stable menu or attract-mode frame from the game's own
renderer.

## M4 — SPU/SPURS (parallel with M2/M3)

- [x] Extract 4 embedded SPU images from `EMAIN.elf`.
- [x] Lift and register them (108 / 159 / 396 / 626 functions).
- [ ] Verify the job chains dispatch with 0 misses at runtime.
- [ ] Add PPU fallbacks for jobs that cannot be lifted yet.
- [ ] Synchronize SPU/RSX (labels, semaphores, DMA).

**Exit criteria:** SPURS job chains run continuously without wedging the PPU.

## M5 — One drivable race (later)

- [ ] Track streaming (`crs/*.shapestream`, `.texstream`, `x` packages).
- [ ] Physics and vehicle model.
- [ ] XInput controller; optional wheel via `cellUsbd`/`sys_io`.
- [ ] Audio (cellAudio/WASAPI; SGX/ATRAC3+ as needed).
- [ ] Save data and trophy stubs.
- [ ] Performance: frame pacing, shader cache, multithreaded RSX.

**Exit criteria:** a full race weekend (menu → load → race → results) offline.

## M6 — Content complete and polish (later)

- [ ] All tracks, cars, menus, events, licenses, and used-car flows.
- [ ] Local save/trophy emulation.
- [ ] Video/movie playback (`cellPamf`/`cellVdec`).
- [ ] Widescreen/4K, frame-rate options, mod support.
- [ ] Packaging and installer that requires the user's own disc.

## Out of scope (for now)

- PSN online services (shut down), multiplayer, seasonal events.
- Redistribution of any game data, keys, or generated recompiled source.
- A clean-room reimplementation of the GT6 engine (not the same game).
