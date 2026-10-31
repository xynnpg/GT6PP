# GT6PP — Gran Turismo 6 native Windows port

A research and engineering workspace for running **Gran Turismo 6 (PS3, US disc
`BCUS98296`, v1.00)** on Windows as a **statically recompiled native executable**
— not a full-system emulator.

> **Status: pre-alpha.** The game data is extracted and the executables are
> decrypted. The 33,000-function PPU lift and the first boot are in progress.
> There is no frame yet. See [ROADMAP.md](ROADMAP.md) and
> [docs/STATUS.md](docs/STATUS.md).

## Why this is not "just run RPCS3"

RPCS3 dynamically translates Cell code and emulates a PS3. This project takes the
static-recompilation route used by N64Recomp/ReXGlue: the game's own PowerPC and
SPU programs are translated **ahead of time** to C/C++, compiled into an x86-64
executable, and linked against a native HLE runtime. There is no runtime CPU
interpreter and no emulated console OS. The game's own code runs natively; the
runtime replaces the PS3 system libraries and translates RSX/GCM graphics.

This is still a compatibility layer around the original game, not a clean-room
rewrite. A from-scratch reimplementation of GT6 is not realistic; see
[docs/FEASIBILITY.md](docs/FEASIBILITY.md).

## What already works

| Area | State |
|---|---|
| Disc identification | `BCUS98296`, APP_VER `01.00`, PS3 system `04.5000` |
| `GT.VOL` | Decrypted and unpacked: 4,207 TOC entries, **32,591 files**, ~25.1 GB |
| `EBOOT.BIN` / `EMAIN.SELF` | Decrypted to `EBOOT.elf` (143 KB) / `EMAIN.elf` (22.4 MB) |
| PPU analysis | 44,626 OPD descriptors, **33,091 unique functions**, 747 imports / 46 libraries |
| HLE name coverage | 533/747 import NIDs resolved by the ps3recomp database |
| Runtime build | `ps3recomp` + LLVM/MinGW toolchain builds on this machine |
| Port scaffold | GT6 boot harness, VFS mapping, D3D12 present thread |
| PPU lift | **done**: 68,149 explicit boundaries + 10,621 wrappers = 78,770 functions in 41 chunks |
| Asset tools | MDL3 wheel/interior OBJ export + software previews |
| SPU | 4 embedded images lifted (108 / 159 / 396 / 626 functions), registered by fingerprint |
| GCM | `cellGcmInit`, four 1280x720 display buffers, flip handler; no flip/frame yet |
| First boot | reaches TLS, GCM/SPU init, SPURS workloads, and the engine's worker threads |
| Current stop | boot-script init flag is false; `main` prints `scripts/gt6/main` and returns |
| Frame | none yet — see [docs/STATUS.md](docs/STATUS.md) for the log |

## Layout

```
PS3-Version/                 your own game dump (ignored)
work/                        extracted assets, decrypted ELFs, analysis (ignored)
gt6/                         the GT6 port: boot harness, HLE config, generated C++
  generated/                 PPU/SPU lifter output (ignored, machine-generated)
  src/                       port-specific code
  scripts/                   lift/build helpers
docs/research/               primary-source research reports
docs/                        feasibility, architecture, build/status notes
tools/                       our analysis tools (SELF/ELF/MDL3 probes)
third_party/                 reference checkouts (ignored; fetch commands in docs)
```

## Quick start (developer)

Prerequisites: Windows 10/11 x64, Python 3.10+, CMake 3.20+, Ninja, and the
portable LLVM/MinGW toolchain (or Visual Studio 2022 + clang-cl). The exact
commands used here are in [docs/BUILDING.md](docs/BUILDING.md).

```powershell
# 1. Extract and decrypt (one-time; uses the user's own disc)
#    See docs/BUILDING.md for GTToolsSharp and RPCS3 --decrypt commands.

# 2. Analyse / lift the 22.4 MB EMAIN.elf
python third_party/ps3recomp/tools/ppu_loader.py work/bin/EMAIN.elf -o work/analysis/emain
python third_party/GT5P/scripts/gen_hle_stubs.py work/bin/EMAIN.elf work/analysis/emain/hle_stubs.json
python third_party/ps3recomp/tools/ppu_lifter.py work/bin/EMAIN.elf `
  --functions work/analysis/emain/functions_code.json `
  --hle-stubs work/analysis/emain/hle_stubs.json `
  --output gt6/generated --code-end 0xF908C4 --chunks 32 --jobs 8

# 3. Generate the HLE NID table and build
python third_party/ps3recomp/tools/gen_hle_nids.py --all --out gt6/src/gen/ppu_hle_nids.cpp
powershell -File scripts/build-gt6.ps1

# 4. Boot (D3D12 window; PS3_HEADLESS=1 for a headless run)
gt6\build\gt6.exe work\bin\EMAIN.elf
```

`gt6/GT.VOL` is a hardlink to the dumped volume so the game's own volume reader
can open it through the VFS. It is ignored by git.

## Legal

This repository contains **no game assets, decrypted game code, keys, or
generated recompiled source**. You must own and dump your own copy of the game.
The tooling is provided for interoperability, preservation, and research. Do not
redistribute extracted content. `Gran Turismo` is a trademark of Sony Interactive
Entertainment; this project is not affiliated with Sony or Polyphony Digital.

## Research

- [PS3 native recompilation landscape](docs/research/ps3-native-recompilation.md)
- [GT6 formats, tooling, and prior art](docs/research/gt6-formats-and-tooling.md)

Both reports are pinned to primary sources and distinguish verified facts from
inference. Additional engineering notes:

- [Architecture](docs/ARCHITECTURE.md)
- [Building](docs/BUILDING.md)
- [First boot and debugging](docs/BOOT.md)
- [Status snapshot](docs/STATUS.md)
- [Handoff / next steps](docs/HANDOFF.md)
- [Asset pipeline](docs/ASSETS.md)
- [Local third-party patches](docs/PATCHES.md)
