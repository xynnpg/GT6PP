# GT6PP

**Gran Turismo 6 — statically recompiled for native Windows.**  
No emulator. No RPCS3. Just the game as a real x86-64 executable.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-early%20bring--up-orange)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20x64-blue)]()
[![Built with](https://img.shields.io/badge/built%20with-ps3recomp-purple)](https://github.com/sp00nznet/ps3recomp)

> **Goal:** Turn the legendary PS3 racing sim into a true native PC port — higher performance potential, full moddability, and long-term preservation.

![GT6PP bring-up status](docs/progress.png)

*Source: `docs/progress.svg`*

---

## Why this exists

Gran Turismo 6 is one of the best racing games ever made. RPCS3 already runs it well, but **static recompilation** is a different approach:

| | RPCS3 (emulator) | GT6PP (static recomp) |
|---|---|---|
| **How it runs** | Interprets/JITs PowerPC + SPU at runtime | Translates the game to C++ **ahead of time** |
| **Performance** | Good, but always pays emulation tax | Native code — no translation overhead |
| **Modding** | Limited | Full source-level access once lifted |
| **Requirements** | High-end PC recommended | Potentially much lighter once polished |
| **Approach** | One binary, many games | Deep per-game port |

This project uses [ps3recomp](https://github.com/sp00nznet/ps3recomp) to lift GT6's PPU/SPU code into native C++ and link it against a clean-room HLE runtime + D3D12 backend.

**You must own the game.** This repo contains **zero** game data, keys, or generated binaries.

---

## Current status (early bring-up)

The port **boots**, opens a 1280×720 window, parses the full boot script, and loads major UI packages. The real legal/intro frame is still black — that's the next big gate.

**What already works:**

| Area | State |
|------|-------|
| `GT.VOL` | Opens · 4,207 TOC entries · 32,591 files |
| Boot script | Full `ADCH012` parse |
| PPU lift | 75,652 functions |
| SPU / SPURS | 15 job images lifted · dispatch OK |
| HLE / threads | 1,216 NID handlers |
| Present path | Flips + `CLEAR_SURFACE` reach D3D12 |
| UI scripts | `MenuClassDefine`, cursor, arcade/option/gtmode/garage packages load |
| PFS cache | Boot/presents + font slices seeded from your own `GT.VOL` |
| Offline intro | Full 136 s 1080p H.264/AAC extract works |

**Next milestone:** get the first non-black legal frame (`boot.adc` → `PresentsRootSCEA`).

See [ROADMAP.md](ROADMAP.md) for the full plan.

---

## Quick start

### Requirements
- Your own **Gran Turismo 6** disc (USA `BCUS98296` v1.00 recommended)
- Windows 10/11 x64
- CMake, Ninja, [LLVM-MinGW](https://github.com/mstorsjo/llvm-mingw)
- [ps3recomp](https://github.com/sp00nznet/ps3recomp) cloned into `third_party/ps3recomp`

### Build
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
```

### Run
1. Place your disc files under `PS3-Version/Gran Turismo 6 (USA) (En,Ja,Fr)/PS3_GAME/`
2. Extract `GT.VOL` to `work/gt6_vol/` (use the included tools)
3. Launch:

```powershell
$env:GCM_GUEST_FB="0,1280,720,6144"
$env:PPU_STUCKMAX="1000000"
gt6\build\gt6.exe work\bin\EMAIN.elf
```

Console = log. Separate window = game framebuffer.

---

## Tooling included

- `tools/GTToolsSharp/` — GT.VOL listing & extraction
- Ghidra headless scripts for targeted PPU/SPU decomp
- `tools/gt6_seed_pfs_cache.py` — seed boot/presents cache from your disc
- `tools/gt6_frame_check.py` — verify captured frames actually contain pixels
- Full details in [docs/TOOLING.md](docs/TOOLING.md)

---

## Contributors

**Project owner**

- **XYMPG ([@xynnpg](https://github.com/xynnpg))** — project owner, direction, requirements, hardware & disc access, RPCS3 oracle runs, visual acceptance, and release decisions.

**How to join**

Anyone who contributes code, analysis, testing, hardware, or documentation is welcome.  
Open a pull request that adds yourself to [CONTRIBUTORS.md](CONTRIBUTORS.md) with a short description of what you did.

See the full list and contribution guidelines in [CONTRIBUTORS.md](CONTRIBUTORS.md).

---

## How you can help

This is still early. The most valuable contributions right now:

1. **Reverse-engineering the remaining boot path** (`boot.adc` / presents sequence)
2. **HLE gaps** and file-worker / lwcond issues
3. **RSX/GCM command stream** analysis once the first real frame appears
4. Testing on different hardware and reporting deterministic logs

Open an issue, submit a PR, or just star the repo so more people see the work.

---

## Legal

- This repository contains **code and documentation only**.
- No game data, decryption keys, decrypted executables, or generated recompiled game binaries are included or distributed.
- You must legally own Gran Turismo 6 to use this project.
- Gran Turismo and all related trademarks belong to their respective owners.
- Original project code is released under the **MIT License** — see [LICENSE](LICENSE).
- The LICENSE also contains an explicit disclaimer that no game data is licensed or distributed by this repository.

---

## Related projects

- [ps3recomp](https://github.com/sp00nznet/ps3recomp) — the static recompilation toolkit this port is built on
- [GTToolsSharp](https://github.com/Nenkai/GTToolsSharp) — excellent GT.VOL / PDIPFS tools
- Other static recomp ports (N64Recomp, UnleashedRecomp, etc.) — same philosophy, different consoles

---

**Star the repo if you want to see GT6 run natively.**  
Every star helps more reverse engineers and performance nerds discover the project.
