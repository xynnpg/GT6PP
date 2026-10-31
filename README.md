# GT6PP

Gran Turismo 6 (PS3 `BCUS98296` v1.00) **statically recompiled for Windows**. The game runs as a native x86-64 executable - no emulator at runtime.

**Status:** boots, parses the full 857,518-byte `ADCH` boot script, loads the UI scripts and presents a 1280x720 window. **The font/file-worker gate is now passed** (generation-based lwcond + synchronous host-font reads): `MenuClassDefine`, `cursor.mproject`/`cursor.adc`, `K/W2`, and the `arcade`/`option`/`gtmode`/`garage`/`gtauto` menu packages load. `MGOM.start` fires and sets the boot-project request. **The real frame is still the black cover**; the next gate is the boot-project handoff (`boot.adc` / `PresentsRootSCEA`).

**Where the first image comes from:** the RPCS3 oracle runs `boot.adc` -> `presents_sequence_common` -> `PresentsRootSCEA` (`K/WD`): `scei` 2 s, `notice` 2 s, `epilepsy` 4 s, then the intro. The native port currently jumps to the later cursor/menu scripts and never opens `K/LH`, `K/KG`, `K/IE`, `K/WD` or the boot fonts. That boot/presents path is the first-screen blocker - not `K/W2`.

**Cache progress:** the boot/presents keys and the raw `K/W2` slice (`59,991 B`, SHA-256 `2b6153...9008`) are now seeded from the user's own `GT.VOL` into the ignored `work/` HDD tree. The oracle opens the bare `/PDIPFS/K/<key>` files; the native port's cached assets take the `PDIPFS_bdmark` branch, and simply deleting the markers does not help. The remaining W2 blocker is the mount/device selection: the `HFileReader` gets a host `FileObject` instead of the PFS cache owner (`docs/analysis/pfs-mount-device-check.md`).

**Diagnostic overlay (not game-rendered):** a CPU-decoded `notice.dds` from the user's own `PresentsRootSCEA.gpb` can be composited over the backbuffer with `GT6_BRINGUP_DDS`. It proves the D3D12 present/capture path and DXT1 decode, **not** the game's legal draw. The real frame is still black; the overlay is not used as a progress proof. See `docs/analysis/lwcond-experiment.md` for the current runtime experiment.

`Prototypes.adc` is **not** required on v1.00 - the RPCS3 oracle proves the disc reaches the first-run UI without it.

![GT6PP bring-up status](docs/progress.png)

*Source: `docs/progress.svg`; rendered PNG is used because GitHub and the app preview do not reliably render the SVG.*

## Run

1. Put your own GT6 disc files under `PS3-Version/Gran Turismo 6 (USA) (En,Ja,Fr)/PS3_GAME/`.
2. Extract `GT.VOL` to `work/gt6_vol/` (not included).
3. From the repo root:

```powershell
$env:GCM_GUEST_FB="0,1280,720,6144"
$env:PPU_STUCKMAX="1000000"
gt6\build\gt6.exe work\bin\EMAIN.elf
```

The console window is the log. The separate 1280x720 window is the game's framebuffer.

## Build

1. Install CMake, Ninja, and [LLVM-MinGW](https://github.com/mstorsjo/llvm-mingw).
2. Clone [ps3recomp](https://github.com/sp00nznet/ps3recomp) into `third_party/ps3recomp`.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
```

The relift pipeline (`scripts/relift-gt6.ps1`) regenerates `gt6/generated/`.

## Tooling

- `tools/GTToolsSharp/` - GT.VOL listing/extraction.
- Ghidra 10.4 headless + `tools/ghidra_scripts/DecompileAt.java` - targeted PPU/SPU decompilation.
- `tools/gt6_seed_pfs_cache.py` - copy the raw boot/presents slices from your own GT.VOL into the local PFS cache.
- `tools/gt6_frame_check.py` - verify a captured backbuffer BMP contains visible pixels.
- `tools/ghidra-reverse` / `binary-analysis-patterns` agent skills.
- Details and restrictions: [docs/TOOLING.md](docs/TOOLING.md).

## What works

| Area | State |
|---|---|
| `GT.VOL` | Opens; 4,207 TOC entries, 32,591 files |
| Boot script | Full `ADCH012` parse; 255,264 reads to EOF |
| PPU lift | 75,652 functions; 70,989-function corrected boundary list |
| SPU / SPURS | 15 runtime job images lifted; dispatch returns `rc=0` |
| HLE / threads | 1,216 NID handlers; SPU event-handler crash fixed |
| Present / clears | Flips and `CLEAR_SURFACE` reach D3D12 |
| UI scripts | `MenuClassDefine`, `Prototypes.mwidget`, `cursor.*` load |
| PFS cache | Boot/presents + font slices seeded from `GT.VOL`; raw `K/W2` matches the TOC |
| Frame capture | Backbuffer BMP capture + `tools/gt6_frame_check.py` (no desktop screenshots) |
| Intro (offline) | `cryptmovie` -> `PAMF0041` -> demux -> 136 s 1080p H.264/AAC MP4 |

## Next up

- Fix the lwcond/file-worker completion wake so `initApp`/`MainLoop` stop dropping script frames.
- Then load `boot.adc` / `PresentsRootSCEA` and render the first **non-black** legal frame with `GT6_BRINGUP_DDS=0`.
- Then menus, audio/input, performance; in-engine PAMF playback is a separate clean-room HLE task.

The RPCS3 oracle (`docs/analysis/rpcs3-oracle.md`) confirms the v1.00 disc alone reaches the legal/loading screen, first-run UI and intro; `Prototypes.adc` is a native loader/path artifact, not a missing game file.

## Contributors

- **XYMPG ([@xynnpg](https://github.com/xynnpg))** - project owner, direction, testing, and the RPCS3 oracle runs.

See [CONTRIBUTORS.md](CONTRIBUTORS.md) to add yourself.

## Legal

This repository contains **code and documentation only**. It does **not** include game data, decryption keys, decrypted executables, or generated recompiled game code. You must own Gran Turismo 6 to use this project. Game names and trademarks belong to their owners.

## License

Original code is MIT-licensed; see [LICENSE](LICENSE). Third-party components keep their own licenses.
