# Feasibility: native Gran Turismo 6 on Windows

**Target:** Gran Turismo 6, PS3 US retail disc `BCUS98296`, v1.00 (the dump in
this workspace). **Date:** 2026-10-31. **Companion research:**
[PS3 native recompilation](research/ps3-native-recompilation.md) ·
[GT6 formats and tooling](research/gt6-formats-and-tooling.md).

## Bottom line

A **fully native, clean-room GT6 port does not exist and is not a realistic
first project**. A **static-recompilation port is technically feasible** with
today's open-source tooling, but it is a multi-person-year, single-title
engineering effort. This workspace is pursuing that path, using
[`ps3recomp`](https://github.com/sp00nznet/ps3recomp) and the GT5 Prologue
sibling port [`sp00nznet/GT5P`](https://github.com/sp00nznet/GT5P) as the
foundation.

What "native" means here:

- the game's PowerPC (PPU) and synergistic-processor (SPU) programs are
  translated **ahead of time** to C/C++ and compiled for x86-64;
- there is no runtime CPU interpreter or dynamic recompiler;
- the PS3 operating-system services are replaced by a native HLE runtime;
- RSX/GCM graphics commands are translated to D3D12/Vulkan/Metal.

It is not a from-scratch reimplementation of Polyphony's engine, and the
original game code is still present in recompiled form. A clean-room rewrite of
GT6's engine, physics, rendering, and 15 GB of assets would be a much larger
project and would not be the same game.

## Why GT6 is unusually hard

| Blocker | What it means |
|---|---|
| **Two-stage executable** | `EBOOT.BIN` is a 72 KB loader; the real 22.4 MB game is `EMAIN.SELF`. The port targets `EMAIN.elf` directly and serves the disc tree through the VFS. |
| **SPU-heavy engine** | GT6 uses Cell SPUs for physics, post-processing (MLAA), audio, and ModelSet3 `PMSH`/SmoothMesh decode. SPURS job chains must be scheduled and synchronized. |
| **RSX/GCM** | The game builds its own command buffers and uses custom RSX shaders. A native backend must parse GCM and translate shaders, not just present a framebuffer. |
| **Adhoc bytecode** | Much of the menu/gameplay logic is Polyphony's Adhoc script VM, not native code. The engine's VM must run the original scripts. |
| **15.4 GB `GT.VOL`** | Proprietary PFS container with encrypted header/TOC, zlib/PS2ZIP chunks, and a CRC32/xorshift stream cipher. The game's own reader can open it if the VFS is correct. |
| **Online / PSN / media** | PSN services are dead; `sceNp*`, `cellHttp`, `cellSail`, `cellPamf`, trophies, and save data need stubs or local implementations. Offline is the only sane first target. |
| **Peripherals** | Racing wheels via `cellUsbd`/`sys_io`; a first port can use XInput and defer wheel support. |

## What exists (prior art)

- **`ps3recomp`** (MIT): AOT PPU/SPU lifters, HLE runtime, RSX→D3D12/Metal/Vulkan,
  SPURS/cellSpurs, cellSysutil/cellGcmSys/cellAudio/cellPad/cellFs modules.
  Working ports include flOw, Shadow of the Colossus, Drakengard 3, and The
  Simpsons Arcade Game. This is the base for GT6PP.
- **`sp00nznet/GT5P`** (MIT): the closest sibling. 42,316 lifted PPU functions,
  12 SPU images, 439 imports across 26 modules, 116 PDIPFS assets loaded
  deterministically, D3D12 initialized, one prepare-flip — **but no frame yet**
  (pre-alpha). It proves a GT-class Polyphony engine can be lifted and booted.
- **`MauricioRSJ98/gt5-native-recomp`**: a second GT5 attempt; 43,525 PPU entry
  addresses, 22 SPU images, Vulkan/audio/XInput initialized — **no frame or
  race**. Also pre-alpha.
- **RPCS3**: runs GT6 to "Ingame" (not Playable) and is useful as a behavioral
  oracle and for decrypting binaries, but its GPL-2.0 code cannot be copied into
  an MIT port.
- **No verified GT6 native port.** A claimed `Denarmo/Gran-Turismo-6-Recomp`
  repository was deleted and is treated as vaporware.

## Effort estimate

From the research report, assuming a small experienced team and the GT5P
precedent:

| Milestone | Rough effort |
|---|---|
| Minimum viable native runtime (boots, loads assets, no frame) | 1–3 weeks |
| First frame (menu or attract mode) | 1.5–3 months |
| One drivable race | 3–6 months |
| Offline content-complete | 8–18 months with 3–5 developers |
| Solo, content-complete | 2–4 years |

These are engineering estimates, not promises. GT6 is larger than GT5P (33k
unique functions vs 42k OPD entries, 747 imports vs 439) and has more SPU/RSX
work.

## Recommended path (and what this repo does)

1. **Extract and decrypt** the user's own disc (`GT.VOL`, `EBOOT.BIN`,
   `EMAIN.SELF`). Done locally; nothing is committed.
2. **Lift the PPU executable** (`EMAIN.elf`) with `ps3recomp`'s
   `ppu_loader.py` + `ppu_lifter.py`, converting each imported stub to
   `ps3_hle_call(nid)`.
3. **Boot the CRT and engine** with the GT6 harness: guest VM, main stack,
   argv, VFS, `cellGame` IDs, D3D12 present thread, vblank/flip ticker.
4. **Close HLE gaps** module by module: `cellGcmSys`, `cellSpurs`, `cellAudio`,
   `cellSysutil`, `sys_fs`, `cellPad`, then media/network stubs.
5. **Lift SPU images** and dispatch SPURS jobs; add PPU fallbacks for jobs that
   are not yet lifted.
6. **Get a frame**: parse GCM, translate RSX shaders, present with D3D12.
7. **Get a race**: asset streaming, physics, input, audio, save data.
8. **Polish**: performance, widescreen, controller/wheel support, packaging.

## Risks and unknowns

- The GT6 `EMAIN` may require boot parameters or module loading that the GT5P
  harness does not provide. The first boot will tell us.
- GT6's SPU job set and shader corpus are larger than GT5P's; SPU/RSX coverage
  is the critical path.
- The game's own `GT.VOL` reader may use paths or memory layouts that need
  targeted HLE fixes.
- Anti-tamper/obfuscation and online checks may surface during boot.
- The legal status of reverse engineering and anti-circumvention varies by
  jurisdiction. This project requires a user-supplied disc and does not
  distribute keys or assets.

## Conclusion

Proceed with static recompilation. It is the only path that runs the actual game
natively within a realistic timeframe. Expect a long project; the first
measurable milestone is a deterministic boot that reads `GT.VOL` and reaches the
engine's main loop, not a playable race.
