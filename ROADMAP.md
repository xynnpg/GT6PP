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
- [ ] Make the init flag at `0xA13644` true (current stop).
- [ ] Resolve `0x2DDBCC0A`, `0xFAA275A4`, `0x5C832BD7`.
- [ ] Load the first `GT.VOL` assets (menus, fonts, scripts).
- [ ] Add `longjmp`/`setjmp` support if the LZ decoder stalls (GT5P required
      this).

**Exit criteria:** 8/8 identical boots that open the volume and load a stable
set of assets.

## M3 — RSX/GCM and first frame (next)

- [ ] Bring up the D3D12 backend, RSX local memory, tiles, Zcull, display
      buffers.
- [ ] Drain the GCM FIFO and parse the first command buffer.
- [ ] Translate the first RSX vertex/fragment shaders.
- [ ] Present one frame from the game's own command stream.
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
