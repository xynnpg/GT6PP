# Native PS3 Recompilation for Gran Turismo 6

**Scope:** the general PlayStation 3 native/static-recompilation landscape, architecture options, reusable open-source components, GT6-specific blockers, a staged plan, and legal constraints. GT6 file formats and asset extraction are deliberately out of scope; a companion report covers those.

**Research date:** 2026-10-31. **Target examined:** US retail disc `Gran Turismo 6` (`BCUS98296`, v1.00), plus public sources for the v1.22 update.

**Confidence legend used throughout:**

- **Verified** — read directly in source code, a project document, a license file, or the local disc's metadata on 2026-10-31.
- **Inference** — a conclusion drawn from verified facts, not directly confirmed for GT6.
- **Unverified** — a secondary/community claim that was not independently checked, or a claim that may change.

No game files were modified. The only local game inspection was read-only: directory listing, `PARAM.SFO` parsing, and the first 64 bytes of `EBOOT.BIN`/`EMAIN.SELF`. Method: source/docs were read at pinned commits, project status claims were checked against the repositories where possible, and web/GitHub searches were used to find adjacent projects; secondary claims are marked **Unverified**.

## Contents

- [1. Executive summary and bottom line](#1-executive-summary-and-bottom-line)
- [2. What "native" means here](#2-what-native-means-here)
- [3. The landscape: what actually exists](#3-the-landscape-what-actually-exists)
- [4. Technical architecture options](#4-technical-architecture-options)
- [5. Concrete open-source components to reuse](#5-concrete-open-source-components-to-reuse)
- [6. The hardest blockers specific to GT6](#6-the-hardest-blockers-specific-to-gt6)
- [7. Staged roadmap with measurable milestones](#7-staged-roadmap-with-measurable-milestones)
- [8. Legal and ethical constraints](#8-legal-and-ethical-constraints)
- [9. Recommendations and next actions](#9-recommendations-and-next-actions)
- [10. Sources](#10-sources)

---

## 1. Executive summary and bottom line

**Bottom line: a native GT6 port is technically feasible with today's static-recompilation tooling, but it is a multi-person-year, single-title engineering project — not a configuration change, and not something RPCS3 can be "converted" into by flipping a switch.** As of 2026-10-31 there is **no verified public native GT6 port or GT6-specific recompilation project** that I could find; a claimed repo was deleted and is treated as vaporware (§3.4). The closest precedents are two Polyphony Digital titles from the same developer/era, almost certainly sharing the in-house engine lineage (inference; confirm from code):

- **Gran Turismo 5 Prologue Recompiled** (`sp00nznet/GT5P`): 42,316 lifted PPU functions, 439 imports across 26 modules, 12 SPU images, deterministic load of 116 PDIPFS assets, RSX tiles/Zcull/display buffers configured, one prepare-flip — **but no frame**. Status: pre-alpha. ([README](https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/README.md))
- **GT5 Native Recomp** (`MauricioRSJ98/gt5-native-recomp`): 43,525 generated PPU entry addresses, 6 embedded SPU ELFs plus 16 captured raw SPU images, Vulkan initialized, display buffers configured, audio and XInput initialized — **but no observed guest draw, flip, menu, or race**. Status: pre-alpha. ([README](https://github.com/MauricioRSJ98/gt5-native-recomp/blob/0559a614d4df8d586237eb343f8c8ba167a4ea79/README.md), [STATUS](https://github.com/MauricioRSJ98/gt5-native-recomp/blob/0559a614d4df8d586237eb343f8c8ba167a4ea79/docs/STATUS.md))

Those two projects are the single most important data points in this report. They show that a GT-class Polyphony engine can be parsed, lifted, linked, and booted to the point of loading its own assets and configuring the RSX, using current open-source tooling. They also show where the wall is: **SPU/SPURS scheduling, RSX command submission and shader translation, and the last mile from "boots" to "draws a frame."**

The recommended path is:

1. **Build on [`sp00nznet/ps3recomp`](https://github.com/sp00nznet/ps3recomp)** (MIT, v0.18.0, October 2026), not on RPCS3. ps3recomp is a real ahead-of-time static recompiler: PPU and SPU code become C/C++ compiled into the host executable, with a clean-room HLE runtime for LV2/cell libraries and a D3D12/Metal/Vulkan RSX backend. ([README](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md))
2. **Target the US v1.00 disc first** (`BCUS98296`), because that is the disc in hand and the least update-dependent target. Add v1.22 later, after the pipeline is stable; updates replace code and require a re-lift.
3. **Use RPCS3 as a behavioral oracle, not a code source.** RPCS3 is GPL-2.0; ps3recomp is MIT. Copying RPCS3 code into an MIT port is a license violation. Reading its behavior, logs, RSX captures, and source to understand semantics is the clean path; if you want to link RPCS3's renderer, the whole port must be GPL-2.0-compatible.
4. **Treat "first boot", "first pixel", "first frame", and "first race" as separate gates.** They are months apart, not days.

**What is solved vs. what is not (for GT6 specifically):**

| Layer | Status | Why |
|---|---|---|
| PPU lifting | **Generically solved; GT6 scale unmeasured** | ps3recomp lifts 40k–90k-function games; GT6's `EMAIN` size suggests tens of thousands of functions. |
| SPU lifting | **Generically solved; GT6 job mix partly known** | Static lifter + interpreter fallback exist; MLAA/post-processing and SmoothMesh SPU jobs are confirmed, but the full inventory is unmeasured. |
| Adhoc VM/scripts | **Not solved; separate workstream** | Most gameplay logic is Adhoc bytecode; the original VM must run (recompiled) or be reimplemented; OpenAdhoc reports ~70% of GT6 1.22 scripts translated. |
| OS/HLE | **Broad but uneven** | Threads/FS/audio/pad/saves are strong; `cellSpurs` and media codecs are Partial; `cellUsbd` is an empty stub. |
| RSX | **Functional, not complete** | FIFO + D3D12/Metal/Vulkan + NV40 decompilers exist; HDR/MRT/textures/shader edge cases remain. |
| Assets | **Out of scope here** | Companion report covers `GT.VOL` and formats; the runtime needs a VFS/streaming layer. |
| Input/audio | **Basics covered; wheels/codecs partial** | DualShock + cellAudio work; USB wheels and ATRAC3plus streaming need work. |
| Online | **Not solved** | Official servers dead; GT6 protocol unknown; legal/ToS risk. |
| Legal | **User-supplied data only** | See §8; no keys/assets/firmware/generated code distribution. |

**Rough effort, assuming a small experienced team reusing ps3recomp:**

| Milestone | Effort | Calendar with 1 senior dev + AI | Calendar with 3–5 devs |
|---|---:|---:|---:|
| Minimum viable native runtime (PPU only, no graphics) | 0.5–1.5 person-months | 2–6 weeks | 1–3 weeks |
| Full PPU boot to game `main`, HLE imports resolved | 2–4 person-months | 1–3 months | 3–6 weeks |
| SPU/SPURS job dispatch working | 3–8 person-months | 2–5 months | 1–3 months |
| First RSX clear/flip (a window with GT6's clear color) | 1–3 person-months | 3–8 weeks | 2–5 weeks |
| First real 3D frame / menu | 4–8 person-months | 3–6 months | 1.5–3 months |
| One drivable race (one car, one track, input, audio, HUD) | 8–15 person-months | 6–12 months | 3–6 months |
| Offline content-complete (cars/tracks/events/weather/replay/tuning/saves) | 21–47 person-months direct (24–52 with contingency) | 2–4 person-years | 8–18 months |
| Online/private-server support (optional) | +6–12 person-months | +6–12 months | +3–6 months |

These are **low-to-medium confidence** estimates. They are anchored on GT5P/GT5 bring-up speed, the first-level-playable Demon's Souls port (started June 2026, first level playable by October 2026), and the Armored Core 4 port's reported ~54,000 functions / 99.3% code coverage. GT6 is larger and more content-heavy than all of those, and its online layer is dead but not documented.

**Go/no-go gates are in §7.5.** The short version: if a team cannot get a full PPU lift to boot to game code within ~6 weeks, or cannot get a guest draw submitted within ~4 months, the architecture or the team's capacity is wrong and the project should be re-scoped before more content work.

---

## 2. What "native" means here

The word "native" is overloaded. This report uses a precise, practical definition:

> **Native static-recompilation port:** the game's PPU and (where possible) SPU machine code is translated **ahead of time** into host C/C++ and compiled into a normal host executable. At runtime there is **no CPU instruction interpreter or JIT** for translated code. Console OS services are replaced by a compatibility runtime (HLE), and RSX GPU commands are translated to a host graphics API at runtime.

This is the N64Recomp / XenonRecomp / ps3recomp model. It is "native" in the same sense that a source port is native: the CPU executes host code, not emulated guest instructions. It is **not** "native" in the sense that every hardware behavior is reimplemented from scratch; the GPU command stream and OS libraries are still compatibility layers.

A useful spectrum:

| Model | CPU execution | GPU | OS libraries | Is it native? | Example |
|---|---|---|---|---|---|
| **Static recompilation + HLE** | Guest PPU/SPU translated AOT to C/C++ | RSX FIFO translated at runtime to D3D12/Vulkan | Clean-room HLE | **Yes**, in the static-recomp sense | ps3recomp, GT5P |
| **Static PPU + SPU interpreter + HLE** | PPU AOT; SPU interpreted | Same | HLE | **Hybrid**; CPU PPU native, SPU not | Early ps3recomp ports, GT5 attempt |
| **Dynamic JIT + HLE/LLE** | Guest code JIT-compiled at runtime | RSX translated at runtime | HLE/LLE | **No**, it is an emulator | RPCS3 |
| **Full source decompilation / reimplementation** | Original C/C++ rebuilt | Rewritten or reimplemented | Rewritten | **Yes**, source-native | inFAMOUS clean-room decomp (early) |
| **Official remaster/source port** | Original source ported | Rewritten | Rewritten | **Yes** | Journey/Flower PC ports (not GT6) |

**Important nuance:** RPCS3's PPU "AOT" recompiler is not offline static recompilation. RPCS3 compiles whole PPU modules to LLVM IR at load time and caches the result; the translation still happens inside the emulator, and the emulator still owns the guest CPU state, memory map, syscalls, and scheduler. The RPCS3 FOSDEM talk describes this as an "AOT recompiler" in the emulator's terminology, but it is runtime code generation, not a standalone native executable. ([RPCS3 PPU translator](https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/PPUTranslator.cpp), [FOSDEM 2022 slides](https://archive.fosdem.org/2022/schedule/event/ps3/attachments/slides/5257/export/events/attachments/ps3/slides/5257/slides.pdf))

**Important nuance 2:** "native" does not mean "no compatibility layer." ps3recomp still implements LV2 syscalls, cell libraries, RSX command parsing, and shader translation. The CPU is native; the platform is emulated at the library/GPU boundary. That is the correct mental model for planning.

---

## 3. The landscape: what actually exists

### 3.1 RPCS3 — the general emulator, not a native runtime

RPCS3 is the de facto general PS3 emulator/debugger: C++, GPL-2.0, ~20k GitHub stars, actively developed. It is the compatibility baseline and the best oracle for GT6 behavior. It is **not** a static recompiler and does not produce a native executable. Its GT6 compatibility status is **In-game, not Playable**: 1.05 is the usual target, while 1.22 needs Read Color Buffers and still has graphical issues (companion format report; [RPCS3 issue #12567](https://github.com/RPCS3/rpcs3/issues/12567)).

Verified architecture from the repository:

- **PPU:** LLVM-based translator (`rpcs3/Emu/Cell/PPUTranslator.cpp`, `PPUAnalyser.cpp`, `PPUThread.cpp`) with interpreter fallback. Whole modules are compiled at load and cached.
- **SPU:** LLVM recompiler (`SPULLVMRecompiler.cpp`), ASMJIT recompiler (`SPUASMJITRecompiler.cpp`), common recompiler/cache (`SPUCommonRecompiler.cpp`), interpreter (`SPUInterpreter.cpp`). SPU code is compiled into a cache keyed by code hash.
- **HLE:** one C++ file per library under `rpcs3/Emu/Cell/Modules/` — `cellGcmSys.cpp`, `cellSpurs.cpp`, `cellAudio.cpp`, `cellPad.cpp`, `cellSaveData.cpp`, `sceNpTrophy.cpp`, etc.
- **RSX:** `rpcs3/Emu/RSX/` with NV47 hardware state, FIFO, Vulkan (`VK/`) and OpenGL (`GL/`) backends, shader decompilers under `Program/`.
- **Loading/decryption:** `Loader/ELF.cpp`, `Loader/mself.cpp`, `Crypto/unself.cpp`, `Crypto/unedat.cpp`; firmware is user-supplied.

**Why it matters for GT6:** RPCS3 renders GT6 to In-game status with title-specific fixes and is the fastest way to answer "what should this draw call look like?" or "what does this syscall return?" ([RPCS3 GT6 wiki](https://wiki.rpcs3.net/index.php?title=Gran_Turismo_6)). But it cannot be shipped as a native GT6 port, and its GPL-2.0 license constrains code reuse.

### 3.2 ps3recomp — the real static-recompilation toolkit

[`sp00nznet/ps3recomp`](https://github.com/sp00nznet/ps3recomp) is the only general-purpose, actively maintained PS3 static-recompilation toolkit I found. Verified facts:

- **License:** MIT. ([LICENSE](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/LICENSE))
- **Scale:** 1,052 files in the Git tree, ~14 MB repository, 611 stars / 88 forks as of 2026-10-31. ([GitHub API metadata](https://api.github.com/repos/sp00nznet/ps3recomp))
- **Version:** v0.18.0, October 2026, with 155 PRs in that release alone. ([README changelog](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md))
- **Pipeline:** `tools/ppu_loader.py` → `tools/ppu_lifter.py` → C/C++; `tools/extract_spu_images.py` → `tools/find_spu_functions.py` → `tools/spu_lifter.py` → C; link against `runtime/` + `libs/`.
- **Runtime:** flat 4 GB guest address space, big-endian memory accessors, PPU context, SPU context/local store/MFC DMA, LV2 syscall table, HLE modules.
- **Graphics:** `cellGcmSys` HLE → NV4097 FIFO parser → `rsx_dispatch`/`rsx_draw_engine` → D3D12 (Windows), Metal (macOS), Vulkan (Linux, opt-in), null backend. Guest NV40 vertex/fragment programs are decompiled to HLSL/SPIR-V.
- **SPU:** static lifter plus interpreter fallback for dynamically loaded/self-modified code (`runtime/spu/spu_interp.h`), SPURS HLE (`libs/spurs/cellSpurs.h`), and an LLE path for real firmware modules such as `libsre.prx` (`docs/FIRMWARE_LLE.md`).
- **Legal stance:** no Sony code, firmware, keys, or game data; user supplies the disc; HLE is clean-room. ([README Legal](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md#legal))

**What is actually proven:** the repository lists The Simpsons Arcade Game as playable and Tornado Outbreak as in-game, plus earlier bring-ups of Virtua Fighter 5, Tokyo Jungle, You Don't Know Jack, Twisted Metal, flOw, and Rubber Ducky. Community ports include inFAMOUS, Killzone 3, Demon's Souls, Drakengard 3, God of War HD/Ascension, Yakuza: Dead Souls, Soulcalibur II HD, and others. ([README](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md#game-ports-using-ps3recomp), [Recompendium PS3](https://recompendium.com/en/consola/ps3))

**What is not proven:** a GT-class racing game with a full content loop. GT5P and GT5 both stop before a frame. The runtime's `cellSpurs` module is marked **Partial** in the module status doc, and media decoders (`cellVdec`, `cellAdec`, `cellAtrac`) are partial. ([docs/MODULE_STATUS.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))

### 3.3 The closest precedents: GT5 Prologue and GT5

These deserve detailed treatment because they are the same developer, same era, almost certainly the same in-house engine family (inference), and the same toolchain.

#### GT5 Prologue Recompiled (`sp00nznet/GT5P`, MIT)

Verified from its README and progress log:

- 42,316 lifted PPU functions; 439 imported system calls across 26 modules; 12 SPU images lifted and registered.
- Boot is deterministic: 116 PDIPFS assets loaded, 8 of 8 runs.
- RSX: D3D12 up, tiles, Zcull, display buffers, one prepare-flip — but **no command buffer submitted and no frame**.
- Audio, input, and menus not reached.
- A `longjmp` bug was the single biggest early blocker: the lifter emitted `longjmp`'s final `blr` as a plain C `return`, so the guest restored its register file and then returned to the wrong caller, corrupting the heap. A targeted `setjmp`/`longjmp` patch (`scripts/setjmp_patch.py`) fixed it; PDIPFS opens went from 4 to 108 at best (7 median), SPU job dispatches from 159 to 113,765, and RSX SetTile/SetZcull/SetDisplayBuffer/SetPrepareFlip calls appeared. ([docs/progress.md](https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/docs/progress.md))
- After that, main parked in `sys_cond_wait` (syscall 107, no timeout), waiting for a signal nobody sent. That is where the public progress log ends. ([ROADMAP](https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/ROADMAP.md))

This is a textbook example of why static recompilation of a real game is not just instruction lifting: non-local control flow, per-thread TLS, callee-save correctness, and heap behavior all matter before a single frame.

#### GT5 Native Recomp (`MauricioRSJ98/gt5-native-recomp`, MIT)

Verified from README/STATUS:

- 43,525 generated PPU entry addresses (including internal CFG entries; not all independently verified functions).
- 6 embedded ELF SPU images plus 16 raw SPU images captured at runtime, 6,723 generated entries.
- Vulkan initialized on a GTX 1050 Ti; guest shader translation through glslang/SPIR-V enabled.
- Display buffers configured at 2048×1080/pitch 8192; host offscreen target 1280×720.
- Audio init/port/thread and XInput init/force-feedback worker reached.
- **No observed guest draw, game flip, menu, or playable race.**
- Current stop: 87 missing PPU code; unresolved USB imports (`cellUsbdSetThreadPriority2`, `cellUsbdRegisterExtraLdd2`, etc.).
- The integrated executable excludes the SPU interpreter; missing CPU code stops execution rather than falling back. ([docs/STATUS.md](https://github.com/MauricioRSJ98/gt5-native-recomp/blob/0559a614d4df8d586237eb343f8c8ba167a4ea79/docs/STATUS.md))

This project is only two days old at the research date, so its counts are not evidence of difficulty by themselves. But its stop reasons are exactly the ones a GT6 port should expect: missing PPU targets, raw SPU images, USB HLE, and the absence of an interpreter safety net.

### 3.4 Other PS3 static-recompilation ports

The ecosystem is real but young and per-title. A non-exhaustive list of public projects (status as of late October 2026; treat all status claims as community claims unless verified in the repo):

| Project | Game / title ID | Status | Stack | Notes |
|---|---|---|---|---|
| [`JonathanDC64/DemonsSoulsRecomp`](https://github.com/JonathanDC64/DemonsSoulsRecomp) | Demon's Souls, BLUS30443 | First level playable | ps3recomp fork, D3D12 | Requires decrypted `EBOOT.BIN` and `libsre.prx`; online via community server. |
| [`soyjxck/dod3-recomp`](https://github.com/soyjxck/dod3-recomp) | Drakengard 3, BLUS31197 | Playable, alpha | ps3recomp, D3D12/Metal/Vulkan | Windows/macOS; requires 1.01 update; DLC supported. |
| [`whompay/inFAMOUSreborn`](https://github.com/whompay/inFAMOUSreborn) | inFAMOUS, BCES00220 | Playable (v1.0, Oct 2026) | ps3recomp, D3D12 | Installer builds from user's disc; community reports ~13 fps on macOS in an earlier build. |
| [`undecuple/project-helghast`](https://github.com/undecuple/project-helghast) | Killzone 3 | Nine chapters load; one played to end | ps3recomp | Windows/Proton; not full-game complete. |
| [`SulphurS16/AC4-Port`](https://github.com/SulphurS16/AC4-Port) | Armored Core 4, BLUS30027 | Playable | Own recompiler + D3D11 | ~54,000 functions, 99.3% code coverage; SPU AOT + interpreter; some LLE firmware. |
| [`SulphurS16/ACFA-Port`](https://github.com/SulphurS16/ACFA-Port) | Armored Core: For Answer, BLUS30187 | Playable | Same runtime | Shares runtime with AC4. |
| [`n0madic/Soulcalibur2HD-recomp`](https://github.com/n0madic/Soulcalibur2HD-recomp) | Soulcalibur II HD, NPUB31366 | Playable | ps3recomp | Windows/Metal/Linux; 720p only. |
| [`MaxLeiter/project-8-plus`](https://github.com/MaxLeiter/project-8-plus) | Tony Hawk's Project 8, BLUS30011 | Early release | ps3recomp | Launcher builds from disc; mods/HD textures. |
| [`canersaka/Yakuza-Dead-Souls-Recompiled`](https://github.com/canersaka/Yakuza-Dead-Souls-Recompiled) | Yakuza: Dead Souls, BLUS30826 | Opening playable | ps3recomp fork, D3D12 | ~20 fps in crowded outdoor opening. |
| [`sp00nznet/simpsonsarcade-ps3`](https://github.com/sp00nznet/simpsonsarcade-ps3) | The Simpsons Arcade, NPUB30563 | Playable, online | ps3recomp + psnr | 35–57 fps gameplay; online match via psnr. |
| [`sp00nznet/tornado`](https://github.com/sp00nznet/tornado) | Tornado Outbreak, BLUS30371 | In game | ps3recomp, D3D12 | ~10–16 fps first level; shared runtime fixes. |
| [`sp00nznet/GT5P`](https://github.com/sp00nznet/GT5P) | GT5 Prologue | Boot only, no frame | ps3recomp | 42,316 PPU functions, 12 SPU images. |
| [`MauricioRSJ98/gt5-native-recomp`](https://github.com/MauricioRSJ98/gt5-native-recomp) | GT5, BCUS98114 v2.17 | Boot only, no frame | ps3recomp fork, Vulkan | 43,525 PPU entries, 22 SPU images. |

The catalogues ([Recompendium PS3](https://recompendium.com/en/consola/ps3), [decomps.net PS3](https://decomps.net?platform=ps3)) list 20+ projects. The important pattern is: **one title, one port, one runtime fork.** There is no general "PS3 compatibility layer" that runs the library natively. Every project re-does title-specific HLE, shader, and scheduling work.

**GT6-specific false positive:** a repository named `Denarmo/Gran-Turismo-6-Recomp` appeared around October 2026 claiming a "static recompilation port" with 4K/ultrawide support. It had no executable, required the user to rebuild via Python, the author deleted it, and forum users report nobody got it running. Treat it as **vaporware/unverified**, not as a working port. The companion format report documents the episode. ([companion format report](gt6-formats-and-tooling.md))

### 3.5 Xbox 360 and N64 analogues (why they are not drop-in)

The Xbox 360 is the closest architectural analogue: PowerPC CPU, big-endian, unified shader GPU, XMA audio. The static-recomp ecosystem there is more mature:

- **[XenonRecomp](https://github.com/hedge-dev/XenonRecomp)** (MIT): converts Xbox 360 executables to C++. It explicitly does **not** provide a runtime; it handles PPC instruction translation, function boundaries from `.pdata`, jump tables, big-endian memory, VMX intrinsics, and some FP/denormal behavior. It does not support exceptions or MMIO. ([README](https://github.com/hedge-dev/XenonRecomp/blob/ddd128bcca99fe8bfbb99bea583c972351fa6ace/README.md))
- **[ReXGlue](https://github.com/rexglue/rexglue-sdk)** (BSD-3-Clause-style, Xenia-derived): an SDK/runtime that started as a Xenia-based hybrid and is moving toward fuller static recompilation. It is the closest "toolkit + runtime" analogue to ps3recomp. ([README](https://github.com/rexglue/rexglue-sdk/blob/c94f5ebdcb3c9d1a460ca48e04f9758448f8d518/README.md))
- **[UnleashedRecomp](https://github.com/hedge-dev/UnleashedRecomp)** (GPL-3.0 per repository metadata): a full static recompilation of Sonic Unleashed (Xbox 360) into a native PC port; proof that a complete commercial game can be done this way.
- **[N64Recomp](https://github.com/N64Recomp/N64Recomp)** (MIT): the pioneering modern static recompiler; MIPS, not PowerPC, but the architecture (recompile to C, link a runtime, replace the renderer/OS) is the same.
- **[PS2Recomp](https://github.com/ran-j/PS2Recomp)** (GPL-3.0): the PS2 sibling; MIPS R5900, different GPU, but the same per-title toolchain model.

**Why they are not drop-in for PS3:** the Cell's SPUs are not just more PowerPC cores. They are separate 128-bit SIMD processors with 256 KB local stores, explicit DMA, channels, mailboxes, and a cooperative SPURS scheduler. Xbox 360 has no equivalent. PS3's RSX is also an NV47/G70-class fixed-function + NV40 shader pipeline, not the Xbox 360's unified Xenos. The CPU lifter ideas transfer; the runtime, SPU model, and GPU translation do not.

### 3.6 Decompilation projects

Full source decompilation is a different sport. Public PS3 decompilation is early and sparse:

- **[`bucketcomps/infamous`](https://github.com/bucketcomps/infamous)** (clean-room inFAMOUS decompilation): rebuilds the game as C/C++ that compiles back to the retail bytes, with its own PPU/SPU runtime and a Vulkan renderer. It boots the intro movie and has drawn splash screens; it has no public code yet, and it is explicitly slow/for behavior discovery, not play. ([README](https://github.com/bucketcomps/infamous/blob/f824d279808b0364bbcd8feaf5e33a3e6e536b75/README.md))
- **White Knight Chronicles II** has a decompilation/recompilation research project ([decomps.net entry](https://decomps.net?platform=ps3)); it is early.
- I found **no public GT6 decompilation**. A matching decomp of GT6 would require reconstructing tens of thousands of functions, the custom Polyphony engine, the car physics, the track/AI/UI logic, and the exact compiler/toolchain behavior — a multi-decade community effort, not a first path.

### 3.7 Commercial/official native ports

There is no official PC port of GT6, and no Sony-sanctioned native PS3 runtime. PS3 games on modern PlayStation hardware are either emulated/streamed or remastered from source. Some PS3-era titles received official PC ports (e.g. Journey, Flower, Beyond: Two Souls, Heavy Rain), but those are source-level remasters/ports, not PS3 binary compatibility, and they do not help with GT6.

**Conclusion of the landscape survey:** the only realistic route to a native GT6 executable is the ps3recomp-style static-recompilation stack. RPCS3 is the oracle and the fallback for "what should this look like," not the product.

---

## 4. Technical architecture options

### 4.1 Option A — static PPU + static SPU + HLE runtime (recommended)

This is the ps3recomp model, and the only model that combines native CPU execution with a tractable per-title effort.

**PPU path:**

1. `tools/elf_parser.py` and `tools/ppu_loader.py` parse the decrypted ELF, extract `PT_LOAD` segments, the OPD function descriptor table, the TOC (`r2`), and the `proc_prx_param` import table (`libstub` → library/NID/stub address). PS3 retail EBOOTs are `ET_EXEC` with fixed load addresses, so the image loads verbatim; PRX/`.sprx` modules need relocation handling. ([ppu_loader.py](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/tools/ppu_loader.py), [docs/PPU_RECOMP.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/PPU_RECOMP.md))
2. `tools/ppu_lifter.py` emits one C function per guest function, taking `ppu_context*` (GPRs, FPRs, VMX registers, CR/LR/CTR/XER/FPSCR/VSCR, reservation state). Direct `bl` becomes a direct C call; indirect `bctrl`/`bctr` goes through `ps3_indirect_call`; `sc` goes through `lv2_syscall`; import stubs become `ps3_hle_call(NID, ctx)`. Output is split into translation units by default (`--chunk-lines`, `--chunks`, `--jobs`), which is essential at GT6 scale. ([ppu_lifter.py](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/tools/ppu_lifter.py), [docs/PPU_RECOMP.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/PPU_RECOMP.md))
3. `runtime/ppu/ppu_loader.cpp` loads the image into the flat guest VM, registers lifted functions, and runs the entry OPD with `r1`/`r2` set. `runtime/ppu/ppu_hle.cpp` marshals the PPC integer/pointer ABI (`r3..r10` → C args, return `r3`) and dispatches NIDs. Pointer-taking functions need per-function host↔guest wrappers; the generic path passes raw guest addresses, which is fine only when the HLE handler understands guest memory. ([ppu_hle.cpp](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/ppu/ppu_hle.cpp))
4. Big-endian memory is handled at every guest load/store (`vm_read*`/`vm_write*`, `be_t<T>`), while register-local computation stays host-native. The guest address space is mapped at `vm_base + guest_addr`, with a 4 GB reservation and demand-committed pages. ([docs/ARCHITECTURE.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/ARCHITECTURE.md))

**SPU path:**

1. `tools/extract_spu_images.py` scans the PPU ELF for embedded SPU ELFs (`EM_SPU=23`) and extracts each image. `tools/find_spu_functions.py` seeds function boundaries from the SPU entry point, symbol table, `brsl`/`brasl` targets, and link-register idioms, then emits `--functions` JSON. ([extract_spu_images.py](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/tools/extract_spu_images.py), [find_spu_functions.py](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/tools/find_spu_functions.py))
2. `tools/spu_lifter.py` emits one C function per SPU function, with 128 registers of 128 bits, 256 KB local store, channel I/O, MFC DMA, and indirect dispatch. The runtime is `runtime/spu/spu_context.h`, `spu_dma.h`, `spu_channels.c`, `spu_interp.h`. ([spu_context.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/spu/spu_context.h), [spu_dma.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/spu/spu_dma.h), [spu_interp.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/spu/spu_interp.h))
3. Unlifted code — DMA'd overlays, self-modified code, computed branches into unknown regions — falls back to the SPU interpreter, which shares the exact `spu_context` and helpers with lifted code. This is not optional for a real game: SPU code is loaded into local store at runtime, so a static lift can never see all of it in advance. ([docs/SPU_LIFTER.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/SPU_LIFTER.md))
4. SPURS is handled either by HLE (`libs/spurs/cellSpurs.h`, partial) or by lifting the real `libsre.prx` firmware module from the user's console (`docs/FIRMWARE_LLE.md`). The LLE path is more faithful because SPURS is a scheduler, not a thin syscall wrapper; the HLE path is easier but has known edge cases. ([cellSpurs.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/spurs/cellSpurs.h), [FIRMWARE_LLE.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/FIRMWARE_LLE.md))

**RSX path:**

1. `libs/video/cellGcmSys.h` implements the GCM API: `cellGcmInit`, control registers (`put`/`get`/`ref`), display buffers, flip/VBlank handlers, tile/Zcull config, IO mapping, address→offset translation, reports/labels, timestamps. ([cellGcmSys.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/cellGcmSys.h))
2. `libs/video/rsx_commands.h` parses the NV47xx FIFO: method headers, increasing/non-increasing/jump/call-return packets, surface/viewport/scissor/blend/depth/stencil/cull/texture/vertex/shader/draw state, and draw dispatch. `libs/video/rsx_dispatch.h` is the register-file dispatcher; `libs/video/rsx_draw_engine.h` is the platform-neutral draw engine that hands the backend resource/pipeline/draw records. ([rsx_commands.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_commands.h), [rsx_draw_engine.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_draw_engine.h))
3. NV40 vertex and fragment programs are decompiled to HLSL (`rsx_vp_decompiler.h`, `rsx_fp_decompiler.h`), then compiled by D3DCompile for D3D12, or translated to SPIR-V for Vulkan, or to MSL for Metal. The decompilers are substantial but not complete: the fragment decompiler header still calls out partial texture sampling and input plumbing; vertex flow control/branch bits are handled with caveats. ([rsx_vp_decompiler.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_vp_decompiler.h), [rsx_fp_decompiler.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_fp_decompiler.h))
4. Textures are swizzled/compressed RSX formats; the runtime decodes them into host rows (`rsx_texture_layout.c`, `rsx_texture_formats.h`). Render targets need format mapping, resolve/copy, depth readback, MRT, FP16 HDR, gamma/sRGB, and zcull/tile handling. These are where "it boots" turns into "it looks right."

**HLE path:** `runtime/syscalls/` implements LV2 syscalls (threads, mutex/cond/sem/rwlock, event queues/ports/flags, timers, memory, FS, SPU groups, RSX); `libs/` implements cell libraries (audio, video, input, network, filesystem, system, SPURS, sync, codecs, font, misc). ([lv2_syscall_table.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/syscalls/lv2_syscall_table.h), [docs/MODULE_STATUS.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))

**GT6-specific:** the native executable includes Polyphony's **Adhoc VM**; the recompiled PPU code must run that VM correctly, and the Adhoc bytecode/assets must be loaded from `GT.VOL`. This is why the asset VFS and script layer are on the critical path even though the VM itself is native code. The companion format report covers the Adhoc/asset side.

### 4.2 Option B — static PPU + SPU interpreter + HLE

Same as A, but skip the SPU lifter and run all SPU code through `spu_interp_run`. This is the fastest way to get a boot and to validate PPU/HLE/RSX, and it is a legitimate bring-up strategy. It is also almost certainly too slow for GT6's SPU-heavy workloads: GT5P dispatches 113,765 SPU jobs in a boot, and GT6 has more content and more per-frame jobs. Use the interpreter as a correctness floor and as the fallback for overlays, not as the shipping path.

**When to use it:** first boot, first RSX frame, and debugging a specific job where the lifted code is suspect. **When not to use it:** performance milestones, physics/audio timing, or any claim of "playable."

### 4.3 Option C — dynamic recompilation + HLE/LLE (RPCS3-style)

This is what RPCS3 does: PPU/SPU JIT or interpreter at runtime, HLE modules, RSX Vulkan/OpenGL. It is the most compatible and the least per-title work, because the emulator already handles the hardware and the library surface. It is also **not a native port**: it requires firmware, emulates the console, and carries JIT/scheduling overhead.

**Use it for:** oracle runs, shader/RSX captures, syscall behavior, save/trophy formats, regression comparisons, and a fallback if the native port stalls. **Do not use it for:** the product, unless the goal is "run GT6 on PC" rather than "native GT6."

### 4.4 Option D — full source decompilation / reimplementation

Write C/C++ that compiles back to the retail machine code (matching decomp), or reimplement the engine from behavior. This is the only path that yields a truly source-native, maintainable game, and it is the path the inFAMOUS decomp team is taking. It is also the most expensive by an order of magnitude:

- Tens of thousands of functions, each needing exact compiler/toolchain matching or behavioral proof.
- The custom Polyphony engine, car physics, AI, track streaming, UI, audio mixing, and online protocols.
- The **Adhoc VM and bytecode**: most gameplay/menu logic is scripted, so a source decomp needs either the original VM semantics or a reimplementation plus script decompilation (OpenAdhoc reports ~70% of GT6 1.22 scripts translated).
- Asset formats still need reverse engineering; assets remain copyrighted.
- Clean-room process, dual implementation, and years of testing.

For GT6, this is **not a realistic first path**. It becomes interesting only after a static-recomp port has mapped the engine and identified the high-value modules worth rewriting.

### 4.5 Option E — hybrid: static game code + LLE firmware modules

This is a variant of A: keep the game's PPU/SPU code static, but replace selected HLE modules with **real, user-supplied firmware PRXs** lifted by the same toolchain. ps3recomp documents this for `libsre.prx` (the SPURS kernel): the scheduler loop is authentic Sony code running on the recompiled PPU/SPU runtime, so games launch tasks the same way they do on hardware. ([docs/FIRMWARE_LLE.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/FIRMWARE_LLE.md))

**Why it matters for GT6:** SPURS is the most likely source of scheduling hangs, and GT5P/GT5 both show SPU/SPURS as the wall. LLE `libsre` is a strong fallback if HLE `cellSpurs` cannot be made faithful. **Cost:** user must supply decrypted firmware; the lifted firmware is Sony code and must never be distributed; the port becomes more complex to build and debug.

### 4.6 Comparison table

| Dimension | A. Static PPU+SPU+HLE | B. Static PPU+SPU interp+HLE | C. Dynamic JIT (RPCS3) | D. Full decomp | E. Static + LLE firmware |
|---|---|---|---|---|---|
| **CPU translation** | AOT C/C++ for PPU and SPU | AOT PPU; SPU interpreted | Runtime JIT/interpreter | Source rebuild | AOT game + AOT firmware |
| **Native executable?** | Yes | Hybrid | No | Yes | Yes |
| **Effort for GT6** | 21–47 PM direct offline (24–52 with contingency) | 18–40 PM, but slow | ~0 to run, not a port | 240–600 PM | 30–60 PM offline |
| **Graphics** | RSX FIFO → D3D12/Vulkan; shader decompiler gaps | Same | Mature Vulkan/OpenGL | Rewrite renderer | Same as A |
| **Audio** | HLE cellAudio + SPU jobs + FFmpeg | Same, but SPU slow | Mature | Rewrite | Same as A |
| **Threading/SPURS** | Host threads + SPURS HLE/LLE | Same, SPU interpreter bottleneck | Mature | Rewrite | Best fidelity, more complex |
| **Filesystem** | HLE cellFs/cellGame; mount ISO/GT.VOL | Same | Mature VFS | Rewrite | Same as A |
| **PSN/network** | Offline stubs; psnr optional | Same | RPCN/offline | Rewrite | Same as A |
| **Legal risk** | Medium: user disc, no keys/assets; MIT tooling | Same | Lower for emulator, GPL | High: derivative work, clean-room needed | Medium-high: firmware copyright |
| **Best use** | Shipping path | Bring-up/debug | Oracle/fallback | Long-term preservation | SPURS fidelity fallback |

### 4.7 Subsystem deep dive

#### PPU (PowerPC64/PPE + VMX)

- **ISA:** PowerPC64 with VMX/AltiVec, running a 32-bit ABI in games. The PPU has 32 GPRs, 32 FPRs, 32 128-bit VMX registers, CR/LR/CTR/XER/FPSCR/VSCR, and a TOC register (`r2`). PS3 function pointers are OPD descriptors (`{u32 func, u32 toc}`), so indirect calls must resolve OPD→code entry. ([docs/PPU_RECOMP.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/PPU_RECOMP.md))
- **Big-endian:** every guest memory access needs byte-swapping; VMX element order is a common source of silent wrong results. XenonRecomp's README is a useful warning: it reverses the whole 16-byte vector and adjusts instructions accordingly, rather than swapping individual 32-bit elements. ([XenonRecomp README](https://github.com/hedge-dev/XenonRecomp/blob/ddd128bcca99fe8bfbb99bea583c972351fa6ace/README.md))
- **Control flow:** direct branches are easy; indirect branches, jump tables, virtual calls, and `setjmp`/`longjmp` are hard. GT5P's `longjmp` bug is the canonical example: a `blr` after restoring LR is not a normal return. Any GT6 port must audit non-local control flow early.
- **Threads/TLS:** PS3 games create many PPU threads. Each needs its own TLS block; GT5P's shared-TLS bug corrupted an allocator context. Host threads must model guest priorities, join/detach, and synchronization.
- **PRX/relocations:** retail EBOOTs are fixed-address; PRX modules are `ET_DYN` and need relocation. GT6's `EMAIN.SELF` may be a fixed executable or a PRX-like container; determine after decryption.

#### SPU (Cell SPE)

- **Architecture:** 128 × 128-bit GPRs, 256 KB local store, MFC DMA engine, channels (mailboxes, signal notification, event status, decrementer), and a dual-issue SIMD ISA. Six SPEs are available to games (one SPE disabled for yield, one reserved for the OS). ([Copetti PS3](https://www.copetti.org/writings/consoles/playstation-3/), [spu_context.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/spu/spu_context.h))
- **Floating point:** SPU single-precision rounds **toward zero** and flushes denormals; this is not x86 default behavior. A naive `float` lift will diverge on physics/geometry. ps3recomp exposes `SPU_FLOAT_RZ` to run single precision under a round-toward-zero FPCR, and has exact float tests. ([SPU_LIFTER.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/SPU_LIFTER.md), [IBM SIMD spec](https://informatica.uv.es/guia/asignatu/AAC/ps3/documentacion/SIMD_Library_Specification_for_CBEA_v10.pdf))
- **DMA/coherency:** MFC get/put, list commands, tag groups, barriers, and atomic reservations (`GETLLAR`/`PUTLLAR`). Guest code uses lock-free queues and spinlocks; a host `memcpy` without reservation/coherency semantics will deadlock or corrupt. ps3recomp implements a lock-line reservation bitmap and DMA engine (`spu_dma.h`, `spu_coherency.h`).
- **Code loading:** SPU programs are often loaded into local store at runtime (job modules, overlays). Static extraction finds embedded ELFs, but not raw images or self-modified code. The interpreter fallback is mandatory for full coverage. GT5's attempt captured 16 raw images in addition to 6 embedded ELFs; GT6 should expect a similar mix.
- **SPURS:** a cooperative scheduler with workloads, tasksets, job chains, event flags, and signal ports. HLE is subtle because the scheduler's state machine is guest-visible. LLE `libsre.prx` is the fidelity escape hatch. **GT6-specific:** MLAA/post-processing and ModelSet3 SmoothMesh are confirmed SPU jobs; plan for them explicitly rather than treating "SPU" as one generic workload.

#### RSX (NV47/G70-class GPU)

- **Command stream:** games write NV4097 methods into a ring buffer via `cellGcm`; the FIFO contains method headers, increasing/non-increasing packets, jumps, calls/returns, and draw commands. The parser must track surfaces, viewport, scissor, blend, depth/stencil, cull, alpha test, 16 texture units, 16 vertex attributes, shader programs, and constants. ([rsx_commands.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_commands.h))
- **Shaders:** RSX uses NV40/NV47 vertex and fragment program ISAs, not DX9 HLSL. Vertex programs are VLIW (one vector + one scalar op per instruction), 4 words/16 bytes, up to 512 instructions; fragment programs are variable-length and terminate with an end instruction. Both need decompilation to HLSL/GLSL/SPIR-V, including relative addressing, branches, loops, constants, texture samplers, and half-precision output. ([docs/RSX_GRAPHICS.md](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/RSX_GRAPHICS.md), [rsx_fp_decompiler.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/video/rsx_fp_decompiler.h))
- **Textures/render targets:** swizzled layouts, DXT/BC compression, X16/B8 formats, FP16 HDR targets, MRT, depth textures, resolves, gamma/sRGB. These are not optional for a 2013 racing game with HDR and post-processing.
- **Tessellation:** GT6's marketed "adaptive tessellation" cannot be RSX hardware tessellation (the RSX has no tessellation unit). It is almost certainly generated on the PPU/SPU and submitted as ordinary geometry. **Inference:** this makes SPU/PPU geometry generation a first-class blocker, not a cosmetic one. Confirm by tracing GT6 draw calls once the ELF is decrypted.

#### Audio

- **cellAudio:** multiple ports, a 5.33 ms mixing thread, 7.1 downmix, WASAPI/SDL2 backends. The HLE implementation is marked Complete. ([MODULE_STATUS](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))
- **Codecs:** `cellAtrac` decodes ATRAC3plus RIFF in memory through FFmpeg (partial: no streaming, no plain ATRAC3); `cellAdec`/`cellAdecAtrac3p` are partial; `cellVdec` handles H.264/MPEG-2 through FFmpeg. GT6's BGM/movies may need these paths; verify the actual codecs after asset extraction.
- **SPU audio:** mixing, reverb, and engine synthesis may run as SPU jobs. If so, the SPU lifter/interpreter is on the audio critical path, and audio timing must be tied to the video/flip clock to avoid drift.

#### Threading, timing, and SPURS

- **PPU threads:** two hardware threads per PPU, but games create many software threads. Host threads + fibers (`cellFiber`) + guest priorities are needed. `sys_ppu_thread`, `sys_mutex`, `sys_cond`, `sys_semaphore`, `sys_event`, `sys_event_flag`, `sys_event_queue`, `sys_event_port` are the core syscall surface. ([lv2_syscall_table.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/runtime/syscalls/lv2_syscall_table.h))
- **SPU threads/groups:** `sys_spu_thread_group_create/start/join`, `sys_spu_thread_initialize`, `sys_spu_thread_write_ls/read_ls`, `sys_spu_thread_set_argument`, event ports. SPURS builds on these.
- **Frame clock:** GT6's presentation targets 60 Hz; vblank/flip handlers drive the frame loop, and the engine may run physics at a different fixed rate. A host timer must emulate the vblank cadence, and `cellGcmSetWaitFlip`/flip status must behave like the RSX. If the host runs faster or slower, game logic that assumes a fixed cadence will desync.
- **Determinism:** physics/AI may depend on thread scheduling and SPU job completion order. A static-recomp port should preserve guest-visible ordering where it matters, not just "run fast."

#### Filesystem and game data

- **Paths:** `/dev_bdvd/PS3_GAME/...`, `/dev_hdd0/game/<TITLE_ID>/...`, `/dev_hdd1`, `/app_home`, `/dev_flash`, `/dev_usb`. `cellFs` maps these to host paths; `cellGame` reports boot type, title ID, and data directory; `cellSaveData` handles saves. ([cellFs.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/libs/filesystem/cellFs.h), [MODULE_STATUS](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))
- **GT6:** `EBOOT.BIN` appears to be a 72,920-byte SELF loader; `EMAIN.SELF` is an 8,843,160-byte SELF and the main-executable candidate; `GT.VOL` is a 15,407,310,848-byte encrypted/compressed PFS/PDIPFS-style volume with a custom cipher. The game will stream from `GT.VOL`; the port needs a read-only virtual filesystem with async I/O and the PDIPFS-style archive reader. GT5P's PDIPFS work is the closest reference, but GT6's `GT.VOL` must be verified independently. ([companion format report](gt6-formats-and-tooling.md), [GT5P README](https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/README.md))
- **Updates:** v1.22 is the final update (2 Dec 2015, ~35 MB); updates are PKG installs that populate `PDIPFS` overlays/`UPDATENODEINFO` and can replace game code/data. Target v1.00 first, then re-lift v1.22. ([companion format report](gt6-formats-and-tooling.md))

#### PSN, trophies, and online

- **Offline boot:** GT6 should boot offline with `sceNp*` stubs returning offline/not-connected errors, plus local trophy storage. ps3recomp has `sceNp`, `sceNpBasic`, `sceNpCommerce`, `sceNpMatching2`, `sceNpTrophy`, `sceNpUtil`, `cellHttp`, `cellSsl`, and `psnr` integration. ([MODULE_STATUS](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md), [psnr](https://github.com/sp00nznet/psnr/blob/78f4a72e67b73174dac7bc602451895598e1fa9f/README.md))
- **Online:** GT6's official online services ended 2018-03-28; the game is playable offline. Reviving online requires reverse-engineering GT6's lobby/matchmaking/telemetry protocols, not just implementing generic PSN Matching2. psnr provides rooms/leaderboards and P2P signaling, but it is game-agnostic and only proven with The Simpsons Arcade. **Inference:** GT6 online is a separate multi-month project with legal/ToS risk, not part of an offline MVP.

#### Input and peripherals

- **DualShock 3:** `cellPad` supports XInput/SDL2, analog sticks, triggers, pressure buttons, rumble. This is enough for a basic driving port.
- **Racing wheels:** GT6 is known to support racing wheels; the exact models/protocols should be verified. ps3recomp's `cellUsbd` is an empty stub: LDD registration works, device list returns empty, pipe/transfer returns `NO_DEVICE`. **Inference:** wheels will not work without implementing USB HID/FFB for the specific wheel families, or patching the game to use `cellPad` and mapping a host wheel to pad axes. ([MODULE_STATUS](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))
- **Six-axis:** `cellPad` has sensor-mode APIs, but motion data fidelity is unclear. GT6 likely does not require motion control for racing; treat as optional/unverified.

### 4.8 Architecture diagram (text)

```
┌──────────────────────────────────────────────────────────────────────┐
│ USER-SUPPLIED, NEVER DISTRIBUTED                                     │
│  GT6 disc / ISO: EBOOT.BIN (72 KB SELF), EMAIN.SELF (8.8 MB SELF),   │
│  GT.VOL (15.4 GB archive), PARAM.SFO, TROPDIR, LICDIR                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ user-side decrypt/mount
                                │ (own keys / RPCS3; no keys in repo)
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ OFFLINE ANALYSIS                                                      │
│  elf_parser.py / ppu_loader.py  → segments, OPD, TOC, imports, NIDs   │
│  extract_spu_images.py          → embedded SPU ELFs                   │
│  find_spu_functions.py          → SPU function boundaries             │
│  Ghidra / xrefs / vtables       → names, jump tables, data refs       │
└───────────────┬──────────────────────────────────┬───────────────────┘
                │                                  │
                ▼                                  ▼
┌───────────────────────────────┐   ┌──────────────────────────────────┐
│ PPU LIFTER                    │   │ SPU LIFTER + INTERPRETER         │
│ ppu_lifter.py → C/C++         │   │ spu_lifter.py → C                │
│ one func per guest function   │   │ 128×128-bit regs, 256 KB LS      │
│ ppu_context, OPD/TOC, VMX     │   │ MFC DMA, channels, SPURS         │
└───────────────┬───────────────┘   └───────────────┬──────────────────┘
                └───────────────────┬───────────────┘
                                    ▼
                     ┌────────────────────────────────┐
                     │ NATIVE GAME.EXE                │
                     │ clang-cl / MSVC / GCC          │
                     │ no guest CPU interpreter       │
                     └───────────────┬────────────────┘
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        ▼                            ▼                             ▼
┌──────────────────┐      ┌────────────────────────┐    ┌──────────────────┐
│ HLE RUNTIME      │      │ RSX COMMAND PIPELINE   │    │ HOST PLATFORM    │
│ LV2 syscalls     │      │ cellGcmSys → NV4097    │    │ Win32 threads    │
│ cellFs/cellGame  │      │ FIFO → state → draws   │    │ WASAPI / SDL2    │
│ cellAudio/Pad    │      │ VP/FP decompiler       │    │ XInput / HID     │
│ cellSpurs/Sync   │      │ → HLSL/SPIR-V → GPU    │    │ saves/trophies   │
│ sceNp*/trophies  │      │ D3D12 / Vulkan / Metal │    │ PSN stubs/psnr   │
└────────┬─────────┘      └───────────┬────────────┘    └────────┬─────────┘
         │                            │                          │
         ▼                            ▼                          ▼
┌──────────────────┐      ┌────────────────────────┐    ┌──────────────────┐
│ Guest VM         │      │ Host GPU               │    │ User files       │
│ vm_base + EA     │      │ RTs, textures, shaders │    │ ISO / GT.VOL     │
│ 4 GB flat space  │      │ pipeline cache         │    │ save data        │
│ SPU LS per SPE   │      │                        │    │ config           │
└──────────────────┘      └────────────────────────┘    └──────────────────┘
```

The key boundary: **guest CPU code is host code; guest OS/GPU behavior is a runtime compatibility layer.** That is why the project can be "native" and still need a large HLE/RSX effort.

---

## 5. Concrete open-source components to reuse

### 5.1 Master table

| Component | URL | License | Language | Maturity (2026-10-31) | What to reuse / study |
|---|---|---|---|---|---|
| **ps3recomp** | https://github.com/sp00nznet/ps3recomp | MIT | C, C++, Python | Active toolkit; v0.18.0; multiple playable downstream ports | The whole PPU/SPU lift pipeline, HLE runtime, RSX FIFO/draw engine, D3D12/Metal/Vulkan backends. **Primary base.** |
| **GT5P Recompiled** | https://github.com/sp00nznet/GT5P | MIT | Python, C++ | Pre-alpha; boots, loads 116 assets, no frame | Closest Polyphony-engine bring-up; `setjmp` patch, PDIPFS handling, SPU job lifting, present path. |
| **GT5 Native Recomp** | https://github.com/MauricioRSJ98/gt5-native-recomp | MIT | Python, C | Pre-alpha; no frame | GT5-specific patches, raw SPU capture, Vulkan bring-up, status/blocker taxonomy. |
| **RPCS3** | https://github.com/RPCS3/rpcs3 | GPL-2.0 | C++ | Mature emulator | Behavioral oracle: PPU/SPU translators, HLE modules, RSX renderer, loaders, syscalls. **Do not copy into MIT code.** |
| **XenonRecomp** | https://github.com/hedge-dev/XenonRecomp | MIT | C++ | Mature-ish tool; used by full Xbox 360 ports | PowerPC→C++ lifting ideas, `.pdata` function boundaries, jump tables, big-endian/VMX/FP handling. No runtime. |
| **ReXGlue** | https://github.com/rexglue/rexglue-sdk | BSD-3-Clause-style (Xenia-derived) | C/C++ | Early SDK | Toolkit + runtime architecture; hybrid-to-static trajectory; release engineering. Not PS3-specific. |
| **N64Recomp** | https://github.com/N64Recomp/N64Recomp | MIT | C++ | Mature | Canonical "recompile to C, link runtime" architecture; not ISA-compatible. |
| **PS2Recomp** | https://github.com/ran-j/PS2Recomp | GPL-3.0 | C++ | Active | Per-title static-recomp workflow; MIPS, not PowerPC. License prevents direct reuse in MIT code. |
| **UnleashedRecomp** | https://github.com/hedge-dev/UnleashedRecomp | GPL-3.0 (repo metadata) | C++ | Complete game port | Proof that a full commercial game can be statically recompiled; study scope/QA, not code. |
| **psnr** | https://github.com/sp00nznet/psnr | MIT | Go, C client | Alpha; one game online | Generic PSN Matching2/Score stand-in; rooms, leaderboards, P2P signaling. GT6 protocol still unknown. |
| **FFmpeg** | https://ffmpeg.org/ | LGPL-2.1+ (some optional GPL parts) | C | Mature | H.264/MPEG-2 video, ATRAC3plus audio; ps3recomp loads it at runtime for cellVdec/cellAtrac. |
| **SDL2** | https://libsdl.org/ | zlib | C | Mature | Cross-platform input/audio; ps3recomp uses it on non-Windows. |
| **glslang** | https://github.com/KhronosGroup/glslang | Apache-2.0 / BSD-3-Clause (Khronos) | C++ | Mature | HLSL/GLSL → SPIR-V for Vulkan. |
| **SPIRV-Cross** | https://github.com/KhronosGroup/SPIRV-Cross | Apache-2.0 | C++ | Mature | SPIR-V → MSL/HLSL reflection/translation. |
| **envytools / rnndb** | https://envytools.readthedocs.io/ | MIT | Python/XML | Mature reverse-engineering docs | NV40/NV47 method and shader ISA documentation; the source of truth behind many RSX constants. |
| **Mesa nouveau nv30/nvfx** | https://gitlab.freedesktop.org/mesa/mesa/-/tree/main/src/gallium/drivers/nouveau/nv30 | MIT | C | Mature | NV40 vertex/fragment program compiler and shader ISA reference. |
| **Ghidra** | https://github.com/NationalSecurityAgency/ghidra | Apache-2.0 | Java | Mature | Static analysis, function boundaries, xrefs, vtables, decompiler; use PyGhidra/scripts for ELF analysis. |
| **LIEF** | https://github.com/lief-project/LIEF | Apache-2.0 | C++/Python | Mature | ELF/PE parsing, section/segment manipulation; useful for custom loaders. |
| **Capstone** | https://github.com/capstone-engine/capstone | BSD-3-Clause | C | Mature | Generic disassembly; PowerPC support exists, but SPU needs a custom decoder. |
| **ps3-disc-dumper** | https://github.com/13xforever/ps3-disc-dumper | MIT | C# | Mature | User-side disc dumping/verification; not a runtime component. |
| **inFAMOUS clean-room decomp** | https://github.com/bucketcomps/infamous | No public code yet (site/wiki) | C/C++ (planned) | Early research | Long-term decompilation methodology, hardware measurement, clean-room process. |

### 5.2 ps3recomp file map (the most important list)

If you read only one repository, read this one. These are the files that matter for a GT6 port, in roughly the order you will touch them:

**Analysis and lifting**

- `tools/elf_parser.py` — ELF/SELF/PRX parsing primitives; `ET_SCE_PPURELEXEC`, program/section headers, segment data.
- `tools/ppu_loader.py` — image manifest, OPD function table, TOC, `proc_prx_param` imports. Outputs `.functions.json`, `.image.json`, `.loader.json`, `.imports.json`.
- `tools/ppu_disasm.py` — PowerPC64 + VMX disassembler.
- `tools/ppu_lifter.py` — PPC→C lifter; one function per guest function; `--functions`, `--imports`, `--hle-stubs`, `--names`, `--chunk-lines`, `--chunks`, `--jobs`, `--single-file`, `--raw`.
- `tools/spu_disasm.py` — SPU disassembler; the doc warns the original tables had systemic errors and were rewritten against RPCS3's `SPUOpcodes.h`. Verify any from-scratch decoder against real images.
- `tools/spu_lifter.py` — SPU→C lifter; 128×128-bit regs, local store, channels, DMA, indirect branches; `--auto-functions`.
- `tools/extract_spu_images.py` — extracts embedded SPU ELFs (`EM_SPU=23`) from a PPU ELF.
- `tools/find_spu_functions.py` — SPU function boundary detection from entry, symbols, `brsl`/`brasl`, link-register idioms.
- `tools/prx_analyzer.py` — PRX/SPRX dependency graph and NID resolution.
- `tools/nid_database.py` — NID computation and lookup. **Verified algorithm:** `NID = little-endian first 4 bytes of SHA-1(name + 16-byte suffix 67 59 65 99 04 25 04 90 56 64 27 49 94 89 74 1A)`. The architecture doc's older "big-endian, no suffix" statement is stale; `include/ps3emu/nid.h` and `tools/nid_database.py` agree on the little-endian/suffix form. ([nid.h](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/include/ps3emu/nid.h), [nid_database.py](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/tools/nid_database.py))
- `tools/gen_hle_nids.py` — scans HLE library sources, computes NIDs, emits `ps3_hle_register` calls.

**PPU runtime**

- `runtime/ppu/ppu_context.h` — register file and context layout shared with lifted code.
- `runtime/ppu/ppu_loader.cpp` — `ppu_load_elf`, guest memory accessors, address→function registry, `ps3_indirect_call`, `ppu_run`.
- `runtime/ppu/ppu_hle.cpp` — NID→handler table, PPC ABI adapter, context-aware handlers, fast-path handlers, real-PRX bridge.
- `runtime/ppu/ppu_memory.h`, `ppu_ops.h`, `ppu_vmx.h`, `ppu_tls.h` — memory/ops/VMX/TLS helpers.
- `runtime/ppu/sdata_decrypt.h` — save-data decryption helper (user data, not game executable decryption).

**SPU runtime**

- `runtime/spu/spu_context.h` — 128×128-bit GPRs, 256 KB local store, channels, MFC state, per-image dispatch.
- `runtime/spu/spu_dma.h` — MFC get/put/list, tag groups, barriers, DMA queue, committed-page checks.
- `runtime/spu/spu_channels.c` — channel I/O, mailboxes, signal notification, event status, decrementer, SRR0.
- `runtime/spu/spu_coherency.h`, `spu_coh_bitmap.h` — lock-line reservations, atomic coherency.
- `runtime/spu/spu_interp.h` — interpreter fallback and `spu_dispatch` for computed/indirect branches.
- `runtime/spu/spu_lifted_thread.h`, `spu_lifted_job.h`, `spu_workload.h` — lifted thread/job/workload dispatch.
- `runtime/spu/spu_raw.h`, `spu_overlay_residency.h` — raw SPU images and overlay residency.
- `runtime/spu/tests/` — self-contained SPU tests (sum, shufb, DMA, brsl-return, event, lfqueue, taskset, torture) and an RPCS3 oracle harness.

**Syscalls and HLE**

- `runtime/syscalls/lv2_syscall_table.h` — syscall numbers and dispatch; includes the real `_sys_process_exit` (22), `sys_ppu_thread_*`, mutex/cond/sem/rwlock, event queue/port/flag, timer, memory, SPU, RSX.
- `runtime/syscalls/sys_ppu_thread.h`, `sys_mutex.h`, `sys_cond.h`, `sys_event.h`, `sys_fs.h`, `sys_memory.h`, `sys_timer.h`, `sys_vm.h` — kernel object implementations.
- `libs/system/cellSysutil.h`, `cellGame.h`, `cellSaveData.h`, `cellSysmodule.h`, `cellRtc.h` — system utilities, boot check, saves, modules.
- `libs/filesystem/cellFs.h`, `cellFsUtility.h`, `edat.h` — file I/O, path mapping, EDAT.
- `libs/audio/cellAudio.h`, `cellMic.h`, `cellVoice.h` — audio output/input/voice.
- `libs/codec/cellVdec.h`, `cellAdec.h`, `cellAtrac.h`, `cellPamf.h`, `cellDmux.h` — video/audio demux/decode.
- `libs/input/cellPad.h`, `cellKb.h`, `cellMouse.h` — controller/keyboard/mouse.
- `libs/hardware/cellUsbd.h`, `cellCamera.h`, `cellGem.h` — USB/camera/Move.
- `libs/spurs/cellSpurs.h`, `cellSpursJq.h`, `cellDaisy.h`, `cellFiber.h` — SPURS/job queues/Daisy/fibers.
- `libs/sync/cellSync.h`, `cellSync2.h` — PPU/SPU synchronization.
- `libs/network/sceNp.h`, `sceNpMatching2.h`, `sceNpTrophy.h`, `cellHttp.h`, `cellSsl.h`, `np_psnr.h` — PSN/trophies/HTTP/TLS/psnr.

**Graphics**

- `libs/video/cellGcmSys.h` — GCM API and `CellGcmContextData`/`CellGcmControl`.
- `libs/video/rsx_commands.h` — NV4097 method constants, FIFO packet parsing, `rsx_state`, backend callbacks.
- `libs/video/rsx_dispatch.h` — register-file dispatcher and sink interface.
- `libs/video/rsx_draw_engine.h` — platform-neutral draw engine: surfaces, samplers, render state, pipelines, draws.
- `libs/video/rsx_vp_decompiler.h` — NV40 vertex program → HLSL.
- `libs/video/rsx_fp_decompiler.h` — NV40 fragment program → HLSL.
- `libs/video/rsx_texture_layout.c`, `rsx_texture_formats.h`, `rsx_vertex_formats.h`, `rsx_primitives.h` — texture/vertex/primitive translation.
- `libs/video/rsx_d3d12_backend.h`, `rsx_metal_backend.h`, `rsx_vulkan_backend.h`, `rsx_null_backend.h` — host backends.
- `libs/video/cellVideoOut.h`, `cellResc.h` — video output/resolution scaling.

**Docs worth reading before writing code**

- `docs/ARCHITECTURE.md` — Cell overview, pipeline, memory model; note some sections are stale (e.g. it mentions a `tools/decrypt_self.py` that is not in the tree).
- `docs/PPU_RECOMP.md` — PPU loader/lifter/HLE/boot; an earlier Uncharted bring-up (14,104 functions, 99.8% ISA coverage, 69% import coverage). Treat its status numbers as historical, not current.
- `docs/SPU_LIFTER.md` — SPU ISA coverage, interpreter handoff, tests, known stubs.
- `docs/RSX_GRAPHICS.md` — RSX layers, FIFO, backend interface; the D3D12 capability table is older than the current code.
- `docs/MODULE_STATUS.md` — per-module completeness. **Use this over the README's summary table** when judging risk: `cellSpurs` is Partial, media codecs are Partial, `cellUsbd` is an empty-device stub.
- `docs/FIRMWARE_LLE.md` — how to lift a user-supplied decrypted firmware PRX (`libsre.prx`) for SPURS.
- `docs/SPU_FALLBACK.md` — per-job PPU-side fallback registry; useful for bring-up, not a general SPU replacement.
- `docs/SPURS_SCHEDULING.md` — bounded policy scheduling and its limitations.
- `docs/GAME_PORTING_GUIDE.md` — 12-phase porting walkthrough with a flOw case study.

### 5.3 RPCS3 file map (oracle only)

Use these to answer behavioral questions, not to copy code:

- `rpcs3/Emu/Cell/PPUTranslator.cpp` — PPU→LLVM IR translation; instruction semantics, memory access, VMX.
- `rpcs3/Emu/Cell/PPUAnalyser.cpp` — function analysis, patterns, validation.
- `rpcs3/Emu/Cell/PPUThread.cpp` — PPU thread state, syscall entry, module loading.
- `rpcs3/Emu/Cell/SPULLVMRecompiler.cpp` — SPU→LLVM IR; the most complete public SPU semantic reference.
- `rpcs3/Emu/Cell/SPUCommonRecompiler.cpp` — SPU cache, dispatch, block analysis, register state.
- `rpcs3/Emu/Cell/SPUThread.cpp` — SPU channels, DMA, mailboxes, reservations, interrupts.
- `rpcs3/Emu/Cell/SPUInterpreter.cpp` — SPU interpreter semantics.
- `rpcs3/Emu/Cell/Modules/cellGcmSys.cpp` — GCM API behavior and command buffer construction.
- `rpcs3/Emu/Cell/Modules/cellSpurs.cpp` — SPURS HLE state machine; large and instructive.
- `rpcs3/Emu/Cell/Modules/cellAudio.cpp`, `cellPad.cpp`, `cellSaveData.cpp`, `sceNpTrophy.cpp` — library behavior.
- `rpcs3/Emu/RSX/RSXThread.cpp`, `Emu/RSX/NV47/`, `Emu/RSX/VK/`, `Emu/RSX/GL/`, `Emu/RSX/Program/` — RSX command processing, NV47 state, Vulkan/OpenGL backends, shader decompilers.
- `rpcs3/Loader/ELF.cpp`, `Loader/mself.cpp`, `Crypto/unself.cpp`, `Crypto/unedat.cpp` — SELF/MSELF/EDAT handling; user-side decryption reference.
- `rpcs3/Emu/Cell/lv2/` — syscall implementations; the ground truth for return codes and edge cases.

### 5.4 Xbox 360 analogues: what specifically transfers

- **XenonRecomp** is the best code-level reference for PowerPC lifting mechanics that are ISA-adjacent to the PPU: function boundaries from `.pdata`, jump-table detection around `mtctr`/`bctr`, big-endian memory access, VMX intrinsics, FP denormal handling, and indirect-function dispatch. Its README explicitly warns that exceptions and MMIO are unsupported, and that jump-table detection is game-specific. Those warnings apply to PS3 too. ([README](https://github.com/hedge-dev/XenonRecomp/blob/ddd128bcca99fe8bfbb99bea583c972351fa6ace/README.md))
- **ReXGlue** is the best reference for SDK/product shape: a recompiler, a runtime, per-game configuration, release engineering, and a community feedback loop. It is not a PS3 runtime and its Xenia-derived code is BSD-3-Clause-style with attribution; do not assume PS3 hardware semantics.
- **UnleashedRecomp** is the best reference for scope/QA: a complete game port needs a renderer, audio, input, saves, UI, and a test matrix, not just a CPU lifter.
- **N64Recomp/PS2Recomp** are architectural references; their ISAs and GPUs are different. PS2Recomp is GPL-3.0, so code reuse in an MIT project is not possible.

### 5.5 License compatibility: the practical rules

1. **ps3recomp (MIT) + XenonRecomp (MIT) + N64Recomp (MIT) + psnr (MIT) + SDL2 (zlib) + envytools (MIT) + Mesa (MIT)** can be combined with attribution. Apache-2.0 components (Ghidra, LIEF, SPIRV-Cross, glslang) require preserving notices and patent clauses; they are compatible with MIT and GPL-3.0, but not with GPL-2.0-only.
2. **RPCS3 (GPL-2.0)** cannot be linked into an MIT port. If you copy or link RPCS3 code, the derivative must be GPL-2.0 and you must provide source. The clean approach is behavioral reference plus independent implementation.
3. **PS2Recomp (GPL-3.0)** and **UnleashedRecomp (GPL-3.0)** are not compatible with GPL-2.0-only code; they can be combined with MIT code only by accepting GPL-3.0 for the combined work. Keep them as separate processes/references if you want an MIT port.
4. **ReXGlue (BSD-3-Clause-style)** is permissive with attribution; still check the Xenia-derived portions and any additional notices.
5. **Firmware and game code are not open source.** Lifting `libsre.prx` or GT6 code does not grant redistribution rights. Keep those artifacts local and out of the repository.

---

## 6. The hardest blockers specific to GT6

### 6.1 GT6 profile (verified local metadata + public facts)

| Property | Value | Source / confidence |
|---|---|---|
| Title | Gran Turismo 6 | `PARAM.SFO` (verified) |
| Developer / publisher | Polyphony Digital / Sony Computer Entertainment | Wikipedia (secondary) |
| Release | 2013-12-06 | Wikipedia (secondary) |
| US disc title ID | `BCUS98296` | `PARAM.SFO` (verified) |
| Local disc version | `01.00` | `PARAM.SFO` (verified) |
| Required system version | `04.5000` | `PARAM.SFO` (verified) |
| Boot executable (candidate) | `EBOOT.BIN`, 72,920 bytes, SELF magic `SCE\0` | Local read-only inspection (verified) |
| Main executable candidate | `EMAIN.SELF`, 8,843,160 bytes, SELF magic `SCE\0` | Local read-only inspection (verified) |
| Main asset archive | `GT.VOL`, 15,407,310,848 bytes | Local read-only inspection (verified) |
| Other content | `TROPDIR`, `LICDIR`, `ICON0.PNG`, `PIC0.PNG`, `PIC2.PNG`, `PS3LOGO.DAT` | Local listing (verified) |
| Final update | v1.22 (2 Dec 2015, ~35 MB) | Companion format report (secondary) |
| Online services | Ended 2018-03-28 12:00 UTC | [Official GT6 notice](https://www.gran-turismo.com/us/news/00_5985704.html) (verified) |
| Content scale | 1,200+ cars; 100+ track layouts (count depends on how layouts are counted) | [Wikipedia](https://en.wikipedia.org/wiki/Gran_Turismo_6), [official E3 page](https://www.gran-turismo.com/sg/news/00_4937863.html), companion format report (secondary) |
| Rendering features | Adaptive tessellation; HDR dynamic range 50× GT5 | [Official E3 page](https://www.gran-turismo.com/sg/news/00_4937863.html) (verified) |
| Game logic | Mostly **Adhoc bytecode** (~99% of gameplay logic); native executable is engine/framework + Adhoc VM | Companion format report, [GT Modding Hub: Adhoc](https://nenkai.github.io/gt-modding-hub/concepts/adhoc/adhoc/) (secondary; exact share is inference) |
| Engine lineage | In-house Polyphony engine, shared with GT5/GT5P | **Inference** from developer/era/tech; confirm from code |
| Public native port | None verified as of 2026-10-31; a claimed `Denarmo/Gran-Turismo-6-Recomp` was deleted/unverified | Search result + companion report; not proof of absence |

**GT6 is an engine plus a bytecode VM, not just a monolithic native game.** The companion format report found that the native executable is the engine/framework — rendering, audio, physics, filesystem, platform libraries, and Polyphony's **Adhoc** VM — while most gameplay/menu/event logic is Adhoc bytecode stored in the assets. The modding community puts Adhoc at roughly 99% of gameplay logic ([GT Modding Hub: Adhoc](https://nenkai.github.io/gt-modding-hub/concepts/adhoc/adhoc/)). **Implication:** a static recompilation port recompiles the engine and runs the original Adhoc VM and bytecode; it does not automatically recompile the game's scripting logic. Script compatibility is a separate workstream ([GTAdhocToolchain](https://github.com/Nenkai/GTAdhocToolchain), MIT; [OpenAdhoc](https://github.com/Nenkai/OpenAdhoc), GPL-3.0), and a "full source decomp" would need Adhoc decompilation too. Exact shares are inference; the architectural split is well supported.

**Two-stage boot is the first practical surprise.** `EBOOT.BIN` is only ~72 KB, while `EMAIN.SELF` is ~8.8 MB. The companion format report's SELF analysis and community sources identify `EBOOT.BIN` as a bootstrap that executes `EMAIN.SELF`; the exact loader/syscall path is not publicly documented. A static port must decide whether to:

- lift `EBOOT.BIN` and let it load/decrypt `EMAIN.SELF` (requires reproducing the loader and its decryption), or
- decrypt `EMAIN.SELF` directly and start at its entry point with the memory layout/arguments the loader would have established (requires understanding the loader's contract).

**Inference:** the second path is usually cleaner for a static recompiler, but it must be validated against the loader's behavior. GT5P's pipeline lifts the decrypted executable; GT6 should follow that pattern after confirming which SELF contains the game code.

### 6.2 Blocker table

| # | Blocker | Evidence | Impact | Mitigation | Confidence |
|---|---|---|---|---|---|
| 1 | Two-stage SELF boot + encryption | Local `EBOOT.BIN` 72 KB, `EMAIN.SELF` 8.8 MB, both `SCE\0`; PS3 SELF/EDAT | Cannot even lift the game until both are decrypted and the loader contract is understood | User-side decryption; analyze both; start from `EMAIN` entry; reproduce loader memory/args | High |
| 2 | Scale: tens of thousands of PPU functions, 15–40 SPU images, 1,200+ cars, 15.4 GB assets | GT5P 42,316 functions/12 images; GT5 43,525 entries/22 images; GT6 `EMAIN` SELF 8.8 MB / ELF ~22.4 MB; `GT.VOL` 15.4 GB | Long compile times, huge generated code, slow iteration, asset streaming bugs | ps3recomp output splitting/parallel lift; incremental subsets; asset VFS; caching | High (scale), Medium (exact counts) |
| 3 | SPU/SPURS scheduling and performance | GT6 uses SPU MLAA/post-processing and ModelSet3 SmoothMesh jobs (RPCS3 #11290/#12567; companion report); `cellSpurs` Partial; GT5 22 SPU images | Hangs, wrong physics, low fps, audio glitches, missing post-processing | SPU lifter + interpreter fallback; LLE `libsre.prx`; profile per job; per-job fallbacks | High |
| 4 | RSX shader/HDR/tessellation translation | GT6 HDR 50×, adaptive tessellation, custom NV40 shaders; SPU-produced MLAA/post buffers; ps3recomp FP/VP decompilers partial | Missing effects, wrong colors, broken geometry, flicker/tearing, low fps | Shader corpus + decompiler improvements; per-shader overrides; RPCS3 capture comparison; D3D12/Vulkan pipeline cache; SPU/RSX sync tests | High |
| 5 | Frame timing / physics determinism | GT6 presentation targets 60 Hz; internal physics rate unknown; vblank/flip-driven loop; SPU job completion order | Game logic desync, physics slow/fast, AI weirdness | Host vblank clock; preserve internal fixed step; guest-visible ordering; deterministic scheduling; frame-time scaling only where safe | Medium |
| 6 | Racing wheels / USB / force feedback | `cellUsbd` returns empty device list/`NO_DEVICE`; GT6 is known to support racing wheels (exact models to verify) | Wheels unusable; pad-only port | Implement USB HID/FFB for specific wheel families, or patch to `cellPad` + host wheel mapping | High (stub), Medium (GT6 behavior) |
| 7 | Audio codecs/mixing | `cellAtrac` partial (no streaming/plain ATRAC3); `cellAdec` partial; GT6 BGM/engine audio unknown | Silent/missing music, wrong engine sound, timing drift | FFmpeg runtime; verify codecs from assets; SPU audio jobs; audio clock sync | Medium |
| 8 | Saves/trophies/PSN | `cellSaveData`/`sceNpTrophy` HLE exist; GT6 uses SDAT + GARG saves (full container encryption undocumented); online dead | Save corruption, trophy errors, boot hangs on PSN checks | Offline stubs; test save round-trip; local trophy storage; no PSN sign-in; fresh-save fallback | Medium |
| 9 | Updates/DLC/anti-piracy | v1.22 update; EDAT/RAP; SELF; user licenses | Cannot use update content; re-lift needed; legal risk | Target 1.00 first; add 1.22 later; user-supplied PKG/keys; no distribution | High |
| 10 | Content/test matrix | 1,200+ cars, 100+ layouts, events, licenses, tuning, replays, weather/time, UI | "One race works" ≠ "game works"; enormous QA surface | Vertical slice first; automated golden captures; prioritize arcade/time trial; defer full career | High |
| 11 | Legal/clean-room | DMCA §1201, derivative generated code, GPL/MIT | Project can be blocked or forced to relicense | See §8; user-supplied data; clean-room; no assets/keys | High |
| 12 | Adhoc VM + script compatibility | ~99% of gameplay logic is Adhoc bytecode; GTAdhocToolchain/OpenAdhoc reports ~70% of GT6 1.22 scripts translated | Menus/game logic fail or diverge if the VM/scripts are wrong; recompiling the engine alone is not enough | Run the original Adhoc VM (recompiled PPU code) and load original bytecode; use GTAdhocToolchain for analysis; script reimplementation is optional later | High (split), Medium (exact share) |

### 6.3 The SPU/SPURS wall in detail

This is the blocker I would bet on causing the first major schedule slip.

**What the evidence says:**

- GT5P lifts 12 SPU images and dispatches SPURS job chains with zero misses, but still stalls in a PPU `sys_cond_wait` after loading 116 assets. That is not necessarily an SPU bug, but it shows how much machinery must be correct before a frame.
- GT5's attempt captures 16 **raw** SPU images in addition to 6 embedded ELFs. Raw images are loaded at runtime, so static extraction alone is insufficient; the port needs an interpreter or a capture-and-lift loop.
- ps3recomp's `cellSpurs` is **Partial**, not Complete: management APIs, workloads, tasks, tasksets, event flags, and lifted SPU task execution exist, but taskset edge cases and scheduling fidelity are still open. ([MODULE_STATUS](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md))
- The `docs/FIRMWARE_LLE.md` document exists precisely because HLE SPURS diverges in corner cases; lifting the real `libsre.prx` is the fidelity escape hatch.

**Why GT6 is SPU-heavy (partly confirmed):**

- **MLAA/post-processing runs on the SPU.** RPCS3 developers state that GT6's MLAA is done on the CPU/SPU and that post-processing is still running on an SPU when the RSX starts reading the image, which is why synchronization errors show up as flicker/tearing ([RPCS3 #11290](https://github.com/RPCS3/rpcs3/issues/11290), [RPCS3 #12567](https://github.com/RPCS3/rpcs3/issues/12567)).
- **ModelSet3 has an explicit SPU SmoothMesh job path.** The companion format report documents `UnkSpuJobBufferSizeQwords` as "m_mmLengthInQwords in a WwsJob command, for the SmoothMesh spu job" and references GT6 1.22 `ModelSet3::BuildAndSubmitSmoothMeshJobCommands` at `0x0086acf4`/`0x008eb430` (1.22-specific addresses; 1.00 may differ). This is direct evidence that GT6 offloads mesh smoothing/LOD work to SPUs. ([companion format report](gt6-formats-and-tooling.md))
- GT6's adaptive tessellation has no hardware tessellation unit on RSX; geometry must be generated on the PPU/SPU (inference).
- A 60 Hz racing sim with multi-car grids, tire/suspension/aero physics, AI, and weather/time transitions is a natural fit for Cell's SPEs (inference).
- GT5/GT5P already use SPURS job dispatch; GT6 is likely the same engine lineage (inference).
- Audio mixing/engine synthesis on PS3 frequently uses SPU jobs (inference; GT6 engine-sound synthesis is proprietary).
- **Physics is native engine code.** Public interviews describe a new physics simulator (aerodynamics, suspension, tyre model), but Polyphony has not published internal update rates or solver details; a forum claim of "360 Hz physics" is unverified. The practical implication is that the recompiled PPU/SPU physics should be preserved, not rewritten, if behavior fidelity matters. ([companion format report](gt6-formats-and-tooling.md))

**What to do:**

1. Extract and lift all embedded SPU ELFs first; measure coverage and dispatch misses.
2. Keep the SPU interpreter enabled for raw/overlay/self-modified code; never ship a build that silently returns 0 for an unlifted SPU job.
3. Instrument SPU job entry points, dispatch counts, and per-job wall time. Build a "job map" for GT6 (which entry point does what).
4. If HLE SPURS hangs, switch the SPURS path to LLE `libsre.prx` from the user's firmware before rewriting the scheduler.
5. Optimize only after correctness: SPU float rounding, DMA/coherency, and reservation semantics first; SIMD width second.

### 6.4 The RSX wall in detail

GT6 is a late-generation PS3 game with a custom renderer. The RSX is an NV47/G70-class GPU with NV40 shader ISAs, not a modern unified-shader GPU. The port must translate:

- **Command FIFO:** NV4097 methods, jumps/calls, state packets, draw commands.
- **Shaders:** vertex programs (VLIW, 512 instructions max) and fragment programs (variable length), including relative addressing, branches/loops, constants, texture samplers, and fp16/fp32 outputs.
- **Textures:** swizzled layouts, BC/DXT compression, X16/B8 formats, cube maps, volume textures, border colors, sRGB/gamma.
- **Render targets:** FP16 HDR, MRT, depth textures, resolves, zcull/tile interactions, MSAA (if used), alpha test, logic ops.
- **Tessellation:** GT6's adaptive tessellation is almost certainly CPU/SPU-generated geometry (the RSX has no tessellation unit), so the RSX side sees ordinary draws; the hard part is the generator, not a tessellation shader.

GT6's SPU MLAA/post-processing means the RSX and SPU share buffers; the port must reproduce synchronization/ordering, not just draw calls. RPCS3's GT6 flicker/tearing reports are the warning: a correct-looking frame can still be one buffer late. ([RPCS3 #11290](https://github.com/RPCS3/rpcs3/issues/11290))

ps3recomp's D3D12 backend executes the title's real NV4097 vertex/fragment programs and supports indexed draws, per-draw constants/textures, render-to-texture, MRT, and FP predication (README). But the fragment decompiler header still notes partial texture sampling/input plumbing, and the vertex decompiler has caveats around flow control and branch bits. **Inference:** GT6 will hit shader cases that need decompiler work or per-shader overrides. Budget for a shader corpus and a regression harness.

**Practical approach:** capture GT6's RSX command stream and shader programs under RPCS3, cluster unique shaders by hash, and build a decompile-success dashboard. Start with the title/menu shaders (simpler), then car paint/lighting, then track/weather/post-processing. Do not attempt a full generic NV40 compiler before you know which opcodes GT6 actually uses.

### 6.5 Timing, physics, and the "60 Hz trap"

A racing game is a real-time system. GT6's presentation/frame loop is 60 Hz; physics may run at a higher internal rate (a "360 Hz" forum claim is unverified), and AI, tire wear, and audio scheduling may be tied to frame/vblank counts. The port must reproduce whatever fixed step the engine actually uses, not assume that 60 Hz is the only clock. A static port that runs "as fast as possible" can break:

- Physics integration (if dt is frame-count based).
- AI reaction times.
- Audio sequencing/mixing.
- Replay recording.
- License test timing.

**Mitigation:** implement a host vblank/flip clock at the guest's configured rate, run the presentation loop at 60 Hz, and preserve the engine's internal fixed physics step (whatever its rate). Decouple rendering only if the game already supports it. Use frame-time scaling cautiously; a fixed-step physics loop is easier to validate than a variable-step one. Instrument guest timer/decrementer reads and compare against RPCS3.

### 6.6 Wheels, USB, and force feedback

`cellPad` covers DualShock 3-style input, including analog sticks, triggers, pressure buttons, and rumble. That is enough for a pad-only MVP. Racing wheels are a different path:

- GT6 is known to support racing wheels; the exact Logitech/Thrustmaster/Fanatec models and their USB protocols should be verified from the game/manual before implementing a device class.
- ps3recomp's `cellUsbd` is an empty-device stub: LDD registration works, but device enumeration returns empty and pipe/transfer returns `NO_DEVICE`.
- **Inference:** a wheel will not be detected unless the port implements the USB device class/HID reports for that wheel family, or patches the game to accept `cellPad` input and maps a host wheel's axes/FFB to pad/rumble.

**Recommendation:** ship pad-only first; add wheel support as a separate milestone with a specific wheel model and a HID capture. Do not block the first race on USB.

### 6.7 Audio

GT6's audio stack likely includes:

- `cellAudio` output ports and mixing.
- ATRAC3plus or another codec for streamed BGM.
- SPU jobs for mixing/reverb/engine synthesis (likely; verify).
- 5.1/7.1 output and downmix.

The companion format report adds concrete GT6 detail: car sounds live under `carsound/` (`engine`, `turbo0-3`, `normal0-3`, `start`, `se`, `aes`) in SGX/ESGX formats; there is a BGM library (`sound_gt/library/GT6.lib`); music tracks can be played with vgmstream, but engine-sound synthesis is proprietary and not a simple decode; movies are encrypted PAMF. ([companion format report](gt6-formats-and-tooling.md))

ps3recomp's `cellAudio` is Complete for output/mixing, but `cellAtrac` is Partial (in-memory ATRAC3plus only, no streaming, no plain ATRAC3), and `cellAdec` is Partial. FFmpeg can decode ATRAC3+/H.264/MPEG-2, but the container/demux path (`cellPamf`, `cellDmux`) must match GT6's assets. **Inference:** audio will work in stages: first silence/init, then PCM/SFX, then BGM, then 5.1/engine detail. Engine-sound synthesis may need a dedicated reimplementation or SPU job path, not just a decoder.

### 6.8 Saves, trophies, and PSN

- `cellSaveData` is Complete for callback-driven save/load, directory enumeration, file ops, and simplified `PARAM.SFO`. GT6's save is PS3 SDAT-encrypted with a GARG garage layer; the full container/game encryption is not publicly documented end-to-end, so save import/export is a separate task. ([companion format report](gt6-formats-and-tooling.md))
- `sceNpTrophy` is Complete with persistent JSON storage, unlock timestamps, and progress tracking. GT6's `TROPDIR` can be read; trophy set IDs/definitions need mapping.
- GT6's online services are dead, so offline boot should not require PSN. But the game may still call `sceNp*` at startup; offline stubs must return the right error codes to avoid hangs.
- `sceNpMatching2` over psnr is generic and proven only with The Simpsons Arcade. GT6's lobby protocol is likely custom; **do not assume psnr will work unchanged**.

### 6.9 Updates, DLC, and anti-piracy

- The local disc is v1.00. v1.22 is the final update (2 Dec 2015, ~35 MB); updates are PKG installs that populate `PDIPFS` overlays/`UPDATENODEINFO` and can replace code/data. A port targeting v1.22 needs a re-lift and re-test, not just a data patch.
- PS3 updates/DLC use PKG/EDAT/RAP licensing. The port must consume user-supplied packages and licenses; it must not ship keys or decrypted content.
- **Recommendation:** v1.00 MVP; v1.22 as a second target after the pipeline is stable. Do not promise update compatibility before the base game runs.

### 6.10 Content scale and QA

GT6 is not a 4-hour action game. A content-complete port needs:

- 1,200+ cars with different models, materials, interiors, and physics.
- 100+ track layouts, with weather/time variants (counting conventions vary).
- Career events, license tests, seasonal-style events, arcade, time trial, drift, tuning, paints, replays, photo mode, course maker (if in scope).
- UI across multiple languages, save data, trophies, and settings.
- Stable 60 fps with multi-car grids, weather, and post-processing.

**Implication:** "first race" is a vertical slice, not a product. Plan a long tail of content validation, and automate golden-frame/telemetry comparisons wherever possible.

---

## 7. Staged roadmap with measurable milestones

### 7.1 Principles

1. **User-supplied data only.** The repository contains tools, patches, and documentation; never the disc, `EBOOT.BIN`, `EMAIN.SELF`, `GT.VOL`, keys, firmware, decrypted assets, or generated game code.
2. **Target v1.00 first.** It is the disc in hand and has the fewest moving parts. v1.22 is a second target after the pipeline is stable.
3. **Vertical slices, not breadth.** One car, one track, one camera, one weather setting before 1,200+ cars and 100+ layouts.
4. **Correctness before performance.** SPU float rounding, DMA/coherency, and guest-visible ordering before SIMD optimization.
5. **Every milestone has a measurable acceptance test.** "It boots" is not a milestone; "it executes N guest instructions and resolves M imports" is.
6. **RPCS3 is the oracle.** Compare screenshots, syscall traces, shader hashes, and save behavior; do not copy GPL code.

### 7.2 Stage table

| Stage | Effort | Deliverable | Acceptance criteria | Depends on |
|---|---:|---|---|---|
| **M0 — Recon** | 0.2–0.5 PM (days) | Toolchain builds; decrypted `EMAIN.ELF`; function/import/SPU inventory; risk memo | `ppu_loader.py` parses the ELF; reports function count, import count, library list; `extract_spu_images.py` reports SPU image count; no crashes | User-supplied decryption |
| **M1 — MVNR** (minimum viable native runtime) | 0.5–1.5 PM (1–3 weeks) | Host executable runs lifted PPU code through the OPD/TOC ABI and HLE dispatcher; no graphics/SPU/audio | Executes ≥10M guest instructions; ≥95% of statically imported NIDs resolved; zero unresolved NIDs in the first 1,000 import calls; deterministic 10/10 runs; clean exit | M0 |
| **M2 — Full PPU boot** | 1–2 PM (2–6 weeks) | Full-image PPU lift; HLE coverage for GT6's imports; boot to game `main`/Adhoc VM/first frame loop | Reaches `main` or the first `cellGcm`/`cellSysutil` callback and initializes the Adhoc VM; import coverage ≥95%; no unlifted function hit in the first 10M instructions; 10/10 deterministic | M1 |
| **M3 — SPU/SPURS** | 2–5 PM (4–12 weeks) | All embedded SPU images lifted; raw/overlay images interpreted; SPURS job chains dispatch | ≥95% of SPU jobs complete, including MLAA/post-processing and SmoothMesh; dispatch-miss rate <1%; interpreter share <20% of SPU wall time; one full frame's jobs complete without hangs | M2 |
| **M4 — First pixel** | 1–2 PM (2–6 weeks) | `cellGcmSys` + FIFO walker + null/D3D12 clear; display buffer + flip | Window presents GT6's clear color; `SET_DISPLAY_BUFFER`, `SET_FLIP`, `SET_BEGIN_END` observed; 60 Hz flip loop for 60 s | M2 |
| **M5 — First frame / menu** | 2–4 PM (4–10 weeks) | First guest draw with decompiled VP/FP; menu/title frame; input; audio init; save | One guest draw with correct topology/vertex fetch/shader; screenshot diff vs RPCS3 within tolerance; menu responds to input; save round-trip | M3, M4 |
| **M6 — First race** | 4–8 PM (3–6 months) | One car, one track, one camera, one weather setting; physics; HUD; audio; input | Race loads; car drives; physics tick stable; HUD draws; audio plays; 30 fps; 5 min crash-free | M5 |
| **M7 — Content/performance** | 12–24 PM (9–18 months) | Multiple cars/tracks/events; weather/time; replay; tuning; saves; 60 fps | 10+ cars, 5+ tracks; 60 fps target; 1 h crash-free; save/trophy integrity; golden-frame suite green | M6 |
| **M8 — Online/DLC/1.22** (optional) | 6–12 PM (6–12 months) | v1.22 re-lift; update/DLC handling; private-server online (if pursued) | v1.22 boots; owned DLC loads; online match only if protocol is understood and legal | M7 |

**Cumulative core effort (M0–M7):** ~21–47 person-months of direct work; add 30–50% contingency for a realistic 27–70 person-months (2.3–5.8 person-years). M8 adds 6–12 person-months. These ranges are **low-to-medium confidence** and assume reuse of ps3recomp plus an experienced team.

### 7.3 What can be proven in days/weeks

**Days (M0):**

1. Build ps3recomp and run its test suites. Confirm the runtime, lifters, and at least one backend compile on the target machine.
2. Decrypt the user's own `EBOOT.BIN`/`EMAIN.SELF` to ELF outside the repo. Verify the ELF magic, `e_machine`, entry point, and `PT_LOAD` segments.
3. Run `ppu_loader.py` on `EMAIN.ELF`. Count functions, imports, and libraries. This alone tells you whether the target is 30k or 70k functions and which HLE modules matter.
4. Extract embedded SPU images. Count them. If the count is zero, the game uses raw/dynamic SPU images and the interpreter/capture path is mandatory.
5. Lift a 100-function subset and run it in the boot harness. The first HLE call is a real milestone: it proves the OPD/TOC ABI, big-endian memory, and NID dispatch are wired correctly.

**Weeks (M1–M2):**

6. Full PPU lift with output splitting and parallel jobs. Compile it. Fix the inevitable ABI/relocation/switch-table issues.
7. Boot to `main`. Map unresolved imports to HLE; implement the top 20 missing functions by call frequency, not alphabetically.
8. Get a deterministic boot (10/10 runs) and a clean syscall trace. Nondeterminism at this stage is usually TLS, uninitialized memory, or host-thread ordering.
9. Bring up the RSX null backend: parse the FIFO, log `SET_DISPLAY_BUFFER`, `SET_FLIP`, `SET_BEGIN_END`, and present a clear color. This is the first visual proof that the guest is driving the GPU path.
10. Lift one SPU image and run its tests; then dispatch a real SPU job from the guest. This proves the SPU context, DMA, channels, and job registration.

**Illustrative commands (pin the toolkit commit and check `--help`; flags change):**

```bash
# Build the toolkit (from its README)
git clone https://github.com/sp00nznet/ps3recomp.git
cd ps3recomp
pip install -r requirements.txt
cmake -B build -G Ninja
cmake --build build

# Stage 1: parse the user-supplied decrypted ELF
python tools/ppu_loader.py /path/to/EMAIN.ELF -o out/

# Stage 2: lift PPU to C/C++ (split output; parallel)
python tools/ppu_lifter.py /path/to/EMAIN.ELF \
  --functions out/EMAIN.functions.json \
  --hle-stubs out/EMAIN.imports.json \
  --output recompiled/ \
  -j 8

# Stage 3: generate the NID -> HLE table
python tools/gen_hle_nids.py --all --out recompiled/ppu_hle_nids.cpp

# SPU inventory and lift
python tools/extract_spu_images.py /path/to/EMAIN.ELF -o spu_images/
python tools/find_spu_functions.py spu_images/spu_0000.elf --out spu_0000.functions.json
python tools/spu_lifter.py spu_images/spu_0000.elf \
  --functions spu_0000.functions.json --output spu_recompiled/

# Build the template port
cd templates/project
cmake -B build -G Ninja
cmake --build build
```

Do **not** run these commands against the encrypted `EBOOT.BIN`/`EMAIN.SELF`; `ppu_loader.py` expects an ELF. Decryption is a user-side step with the user's own keys/tools, outside the port repository.

### 7.4 Metrics dashboard

Track these from day one; they are the project's instrumentation, not vanity metrics:

| Area | Metric | Target |
|---|---|---|
| PPU | Functions lifted / total | 100% of executable text |
| PPU | Unlifted functions hit at runtime | 0 in steady state |
| HLE | Imports resolved / total | ≥95% at M2, 100% for hit imports |
| HLE | Unresolved NID calls in first 1k | 0 |
| SPU | Images extracted / lifted | 100% of embedded; raw captured |
| SPU | Dispatch misses | <1% |
| SPU | Interpreter share of SPU time | <20% at M3 |
| RSX | FIFO methods parsed | 100% of encountered methods |
| RSX | Unique shaders decompiled / failed | ≥95% at M5 |
| RSX | Draws per frame / flips | Match guest intent |
| Runtime | Crash-free minutes | 5 at M6, 60 at M7 |
| Runtime | FPS / frame time | 30 at M6, 60 at M7 |
| Content | Cars/tracks/events validated | 10/5 at M7, full at M8 |
| Quality | Golden-frame diff vs RPCS3 | Within tolerance; no regressions |

### 7.5 Go/no-go gates

| Gate | When | Question | If no |
|---|---|---|---|
| **G0** | End of M0 (days) | Can we parse and lift the ELF at all? | Fix tooling/decryption; do not start a port repo |
| **G1** | End of M1 (1–3 weeks) | Does MVNR execute 10M instructions with 0 unresolved imports in the first 1k calls? | ABI/HLE/TLS bug; stop and fix before scaling |
| **G2** | End of M2 (≤6 weeks) | Does full PPU boot reach `main` deterministically? | Re-scope; consider LLE firmware or a different target |
| **G3** | End of M3 (≤3 months) | Do SPU/SPURS jobs complete a frame without hangs, with interpreter <20%? | Switch to LLE `libsre`; per-job fallbacks; performance work |
| **G4** | End of M4 (≤4 months) | Do we see a guest clear/flip? | RSX/HLE architecture wrong; revisit FIFO/GCM |
| **G5** | End of M5 (≤6 months) | Do we see a real guest draw/menu with ≥95% shader success? | Shader workstream or per-shader overrides; reassess |
| **G6** | End of M6 (≤12 months) | One race at ≥30 fps, 5 min stable? | SPU/performance or content pipeline problem; re-scope |
| **G7** | End of M7 (≤24 months) | 60 fps, 10 cars/5 tracks, 1 h stable? | Content/performance tail; decide whether to ship a vertical slice |

### 7.6 Effort scenarios

| Scenario | Team | MVNR | First frame | One race | Offline complete | Notes |
|---|---|---:|---:|---:|---:|---|
| **A. Reuse ps3recomp, focused** | 1 senior dev + AI | 2–6 weeks | 3–6 months | 6–12 months | 2–4 years | GT5P/GT5 pace; high risk of single-person bottleneck |
| **B. Reuse ps3recomp, small team** | 3–5 devs | 1–3 weeks | 1.5–3 months | 3–6 months | 8–18 months | Parallelize HLE, RSX, SPU, tools; best realistic path |
| **C. From scratch runtime** | 3–5 devs | 3–6 months | 12–24 months | 2–4 years | 5–10+ years | Not recommended; ps3recomp already solves too much |
| **D. Full decompilation** | Community/team | n/a | n/a | n/a | 20–50+ person-years | Not a first path; only after static port maps the engine |

**Why these numbers:** GT5P reached "boot + 116 assets + one prepare-flip" in about one month with a mature toolkit and prior port experience, but no frame. Demon's Souls reached first-level playable in about four months with a fork and heavy AI assistance. GT6 is larger, has a two-stage SELF boot, a 15.4 GB archive, more cars/tracks, and likely heavier SPU use. The ranges reflect that step-up.

### 7.7 Critical path and parallel work

**Critical path:** PPU boot → Adhoc VM/script load → SPU/SPURS → first RSX clear/flip → first guest draw → shader corpus → one race → content/performance.

**Parallelizable once MVNR is green:**

- HLE module coverage (imports by frequency).
- RSX backend (null → D3D12 → Vulkan), FIFO parser, texture formats.
- Asset VFS (`GT.VOL` reader, async I/O) — companion agent's format work feeds this.
- Input/audio/save/trophy stubs.
- Test harness: golden frames, syscall traces, shader hashes, save round-trips.
- Build/CI: split lifts, caching, reproducible generation.

**Do not parallelize before MVNR.** A second workstream on shaders or content before the PPU/HLE ABI is stable creates unmergeable branches and false progress.

### 7.8 What to defer

- Online/private servers (until offline is complete and the protocol is understood).
- Racing wheels/FFB (pad-only MVP; add one wheel model later).
- v1.22/DLC (after v1.00 is stable).
- Photo mode, course maker, multi-screen, 4K/120 fps, mods.
- Full career/content breadth (vertical slice first).
- Any "generic PS3 runtime" ambition; this is a GT6 port, not a product for all PS3 games.

---

## 8. Legal and ethical constraints

> **This is engineering research, not legal advice.** Copyright/anti-circumvention law is fact-specific and varies by jurisdiction. If this project is more than a private research effort, get counsel.

### 8.1 The non-negotiable practical rules

1. **Require the user's own disc.** The port must not include the ISO, `EBOOT.BIN`, `EMAIN.SELF`, `GT.VOL`, decrypted assets, firmware, keys, RAP licenses, or any game-derived code.
2. **Do not ship decryption keys or decrypted executables.** Decryption is a user-side step with the user's own legally obtained keys/tools. The repository can document the *interface* (e.g. "point the build at a decrypted ELF") but not provide the means to bypass protection.
3. **Do not distribute generated game code.** The C/C++ emitted by the PPU/SPU lifters is a translation/derivative of the game's machine code. Even if the tooling is MIT, the generated code is not yours to publish. Keep `recompiled/`, `generated/`, and any lifted source out of Git.
4. **Do not distribute firmware-derived code.** Lifting `libsre.prx` or any `dev_flash` module produces Sony-derived code. Keep it local; document how the user generates it from their own firmware.
5. **Do not enable piracy.** No patched EBOOTs, no "no-disc" cracks, no PSN license bypasses, no key databases. The project's value is preservation of a game the user already owns, not circumvention for non-owners.
6. **Keep online out of scope until offline is complete.** GT6's official servers are dead; reviving them raises separate legal/ToS/CFAA questions.

### 8.2 DMCA §1201 and the narrow exemptions

17 U.S.C. §1201(a)(1)(A) prohibits circumventing a technological measure that effectively controls access to a copyrighted work. PS3 SELF/EDAT/AACS encryption is such a measure. The statute has limited exceptions:

- **§1201(f) reverse engineering for interoperability.** A person who lawfully obtained the right to use a copy of a computer program may circumvent access controls for the sole purpose of identifying/analyzing elements necessary to achieve interoperability with an independently created program, if those elements were not readily available, and the acts do not infringe. The information/means may be shared only for interoperability, not general circumvention. ([17 U.S.C. §1201(f)](https://www.law.cornell.edu/uscode/text/17/1201))
- **§1201(a)(1)(B) triennial exemptions.** The Librarian of Congress may exempt classes of works. The 2024 rule includes a narrow video-game preservation/personal-local-gameplay exemption at 37 C.F.R. §201.40(b)(19): lawfully acquired complete games, where the copyright owner ceased providing an external server necessary for authentication, for personal local gameplay or eligible library/archive/museum preservation. It is not a blanket "abandonware" license, and it does not authorize distribution of the game or decrypted assets. ([37 C.F.R. §201.40](https://www.law.cornell.edu/cfr/text/37/201.40), [Copyright Office 2024 page](https://www.copyright.gov/1201/2024/))
- **The 2024 rulemaking did not adopt a broad video-game preservation exemption.** The Video Game History Foundation's statement is a useful summary of the outcome. ([VGHF statement](https://gamehistory.org/dmca-2024-statement))

**Application to GT6:** GT6 is a complete offline-capable game; its online services ended in 2018, but the game does not require server authentication to play offline. That means the §201.40(b)(19)(i)(A) "authentication server ceased" hook may not apply, and the library/archive exemption is limited to eligible institutions. Do not build a business or public distribution model on an assumption that GT6 is "abandonware." The safest posture is private, user-owned research with no distribution of protected material.

### 8.3 Fair use and reverse-engineering cases

- **Sega Enterprises Ltd. v. Accolade, Inc., 977 F.2d 1510 (9th Cir. 1992):** intermediate copying/disassembly to discover functional interoperability requirements was fair use where the information was not otherwise available. ([Copyright Office summary](https://www.copyright.gov/fair-use/summaries/segaenters-accolade-9thcir1992.pdf))
- **Sony Computer Entertainment, Inc. v. Connectix Corp., 203 F.3d 596 (9th Cir. 2000):** intermediate copying of the PlayStation BIOS during reverse engineering to build a non-infringing emulator was fair use; the court dissolved the injunction. ([Copyright Office summary](https://www.copyright.gov/fair-use/summaries/sony-connectix-9thcir2000.pdf))

These cases support reverse engineering as a method, but they do not bless distribution of copied code/assets, and they do not override §1201. They are also U.S.-specific; other jurisdictions differ.

### 8.4 EU/UK decompilation

EU Directive 2009/24/EC Article 6 permits reproduction/translation of code without the rightholder's authorization where indispensable to achieve interoperability of an independently created program, subject to conditions: the acts are performed by a licensee/person with a right to use a copy, the interoperability information was not readily available, and the acts are confined to the necessary parts. The information cannot be used for other goals or to develop a substantially similar program. ([Directive 2009/24/EC](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0024))

National implementations and EULAs vary. The UK, for example, has a similar decompilation exception but with its own conditions. Do not assume the U.S. analysis applies globally.

### 8.5 Clean-room process

A defensible clean-room process separates **specification** from **implementation**:

1. **Specification team** studies public hardware/OS documentation, behavior, and black-box traces, and writes a behavioral spec: syscall semantics, GCM command behavior, shader ISA, file formats, timing.
2. **Implementation team** writes the runtime/lifter from the spec, without copying source from GPL/proprietary implementations.
3. **Provenance log** records every source used: IBM/Cell manuals, ps3devwiki, envytools, RPCS3 behavior (not code), ps3recomp (MIT), etc.
4. **Review** checks for copied code, leaked SDK headers, and game-derived constants that are not functional facts.
5. **No leaked Sony SDK.** Public documentation and black-box behavior only. Leaked headers/source are radioactive.

ps3recomp's own legal stance is a good model: clean-room HLE, no Sony code/firmware/keys, user supplies the game. ([README Legal](https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md#legal))

### 8.6 Open-source license compatibility

- **MIT/BSD/zlib:** permissive; keep notices. ps3recomp, GT5P, XenonRecomp, N64Recomp, psnr, SDL2, envytools, Mesa.
- **Apache-2.0:** permissive with patent/notice terms; Ghidra, LIEF, SPIRV-Cross, glslang.
- **GPL-2.0:** RPCS3. Linking/copying RPCS3 code makes the derivative GPL-2.0; you must provide source. Do not mix GPL-2.0-only with GPL-3.0 code.
- **GPL-3.0:** PS2Recomp, UnleashedRecomp (per repo metadata). GPL-3.0 is incompatible with GPL-2.0-only; a combined work needs a compatible license choice.
- **Firmware/game code:** not open source; user-supplied, never redistributed.

**Recommendation:** keep the port MIT (ps3recomp-compatible), use RPCS3 only as a behavioral oracle, and isolate any GPL tooling in separate processes. If you decide to link RPCS3's RSX renderer, accept GPL-2.0 for the whole port and publish source.

### 8.7 PSN, online, and CFAA/ToS

GT6's official online services ended 2018-03-28. Offline play is the safe target. Reviving online requires:

- Reverse-engineering GT6's lobby/matchmaking/telemetry protocols.
- Running a server that impersonates PSN services.
- Handling PSN authentication/tickets (or bypassing them).

That can raise Computer Fraud and Abuse Act issues, violate Sony's terms of service, and create copyright/anti-circumvention exposure. Private servers for dead games have been tolerated in some communities, but tolerance is not a legal defense. Keep online optional, separate, and counsel-reviewed. Do not include PSN certificates/keys or Sony code.

### 8.8 Trademarks and presentation

"Gran Turismo," "GT6," "PlayStation," and "Polyphony Digital" are trademarks of their owners. A fan port should:

- Use an "unofficial" label and a clear disclaimer of affiliation.
- Avoid official logos/cover art in the repository or installer.
- Avoid implying endorsement by Sony/Polyphony.
- Respect the game's EULA and local law.

### 8.9 Practical repository policy

A conservative, enforceable policy:

```
ALLOWED in repo:
  - recompiler/lifter source (MIT/BSD/Apache)
  - clean-room HLE/runtime source
  - build scripts, patches, docs
  - test fixtures that contain no game code/assets
  - hashes/addresses/metadata that are functional facts

FORBIDDEN in repo:
  - ISO, EBOOT.BIN, EMAIN.SELF, GT.VOL, any game asset
  - decryption keys, RAP files, firmware, dev_flash PRXs
  - generated/recompiled game code (C/C++ or binaries)
  - lifted firmware code
  - patched executables or "no-disc" builds
  - PSN certificates/keys or server impersonation code
```

Add a CI check that rejects large binaries and known game-file hashes, and a `README` section that explains the user must supply their own disc and decryption.

### 8.10 If you want to be maximally conservative

- Keep the project private until counsel reviews it.
- Do not publish decryption tooling or instructions; only document the expected input format.
- Do not publish generated code or performance numbers derived from a specific retail build in a way that facilitates piracy.
- Do not support online.
- Keep a provenance/clean-room log.
- Require users to verify their own disc hash.

---

## 9. Recommendations and next actions

### 9.1 Decision

- **If the goal is "play GT6 on PC soon":** use RPCS3. Its GT6 status is In-game (not Playable), but it is mature and a native port will not be playable for months. Do not frame a native port as a faster route to playing.
- **If the goal is "native GT6 port / preservation / moddability":** proceed with the ps3recomp-based staged plan. It is feasible, but budget years, not weeks.
- **If the goal is "a generic native PS3 runtime":** do not. The evidence is that every port is a per-title fork with title-specific HLE, shader, and scheduling work. Build a toolkit and a flagship port, not a universal runtime.

### 9.2 First ten tasks

| # | Task | Output | Time |
|---|---|---|---|
| 1 | Freeze the toolkit at a known commit (`4e8f3ca…` or later) and vendor it as a submodule | Reproducible build; MIT notices | 1 day |
| 2 | Build ps3recomp on Windows with clang-cl; run its tests | Green build/test log | 1–2 days |
| 3 | Decrypt your own `EBOOT.BIN`/`EMAIN.SELF` to ELF outside the repo; hash and record provenance | Local `EMAIN.ELF`; hash; no repo artifact | 1 day |
| 4 | Run `ppu_loader.py`; inventory functions, imports, libraries | `docs/gt6-inventory.md` with counts and top libraries | 1–2 days |
| 5 | Extract embedded SPU images; count them; identify entry points | `docs/gt6-spu-inventory.md` (addresses only, no code) | 1–2 days |
| 6 | Lift a 100-function subset; run MVNR harness; reach first HLE call | MVNR v0 binary/log | 1–2 weeks |
| 7 | Full PPU lift; boot to `main`; HLE coverage report | Boot log + unresolved-NID list | 2–6 weeks |
| 8 | Bring up RSX null backend; parse FIFO; first clear/flip | Window with GT6 clear color; FIFO log | 2–6 weeks |
| 9 | D3D12 first guest draw; shader corpus/dashboard | Screenshot + shader success metrics | 4–10 weeks |
| 10 | Lift all SPU images; profile jobs; add LLE `libsre` fallback if needed | SPU job map + performance profile | 2–5 months |

### 9.3 What would make me stop or re-scope

- **No full PPU boot within ~6 weeks** despite a clean lift: the ABI/HLE/loader model is wrong, or the target is not what we think it is.
- **SPU/SPURS cannot complete a frame without hangs after LLE `libsre`:** the scheduling fidelity problem is deeper than the team can afford; consider a different game or a narrower demo.
- **RSX shader decompile success <80% after the first 20 unique shaders:** the renderer path needs a different strategy (per-shader overrides or a different backend), not more generic compiler work.
- **Legal counsel says decryption/distribution is not defensible:** stop public work; keep it private or drop it.
- **The team is one person with a full-time job:** expect years; scope to a tech demo, not a full port.

### 9.4 What "done" looks like

A credible v1.0 offline release:

- Boots from the user's own v1.00 (or v1.22) disc dump.
- Plays one full car/track combination at 60 fps with physics, HUD, audio, and saves.
- Supports a standard controller; wheels optional.
- Has a stable 1-hour session and a regression suite of golden frames/telemetry.
- Contains no game data, keys, firmware, or generated game code.
- Clearly labels itself unofficial and documents the user-supplied-data requirement.

That is a realistic "done" for a small team. "All 1,200+ cars, all layouts, all events, online" is a multi-year live-service-scale effort and should be treated as a separate program.

---

## 10. Sources

### Primary PS3 static-recompilation sources

- **ps3recomp** — repository, README, changelog, module status, architecture, PPU/SPU/RSX docs, and source at commit `4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514`:
  - https://github.com/sp00nznet/ps3recomp
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/README.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/ARCHITECTURE.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/PPU_RECOMP.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/SPU_LIFTER.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/RSX_GRAPHICS.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/MODULE_STATUS.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/FIRMWARE_LLE.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/SPU_FALLBACK.md
  - https://github.com/sp00nznet/ps3recomp/blob/4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514/docs/GAME_PORTING_GUIDE.md
- **GT5 Prologue Recompiled** — repository, README, progress log, roadmap, and scripts at commit `65c75d61ade58efb4f6af5f099c3b78b64c0a8e6`:
  - https://github.com/sp00nznet/GT5P
  - https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/README.md
  - https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/docs/progress.md
  - https://github.com/sp00nznet/GT5P/blob/65c75d61ade58efb4f6af5f099c3b78b64c0a8e6/ROADMAP.md
- **GT5 Native Recomp** — repository, README, and status at commit `0559a614d4df8d586237eb343f8c8ba167a4ea79`:
  - https://github.com/MauricioRSJ98/gt5-native-recomp
  - https://github.com/MauricioRSJ98/gt5-native-recomp/blob/0559a614d4df8d586237eb343f8c8ba167a4ea79/README.md
  - https://github.com/MauricioRSJ98/gt5-native-recomp/blob/0559a614d4df8d586237eb343f8c8ba167a4ea79/docs/STATUS.md

### Emulator/oracle

- **RPCS3** — repository, license, and source at commit `df090aa12797b5c5f4a6f2567f1578ec3e85409d`:
  - https://github.com/RPCS3/rpcs3
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/LICENSE
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/PPUTranslator.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/SPULLVMRecompiler.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/SPUCommonRecompiler.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/RSX/RSXThread.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/Modules/cellGcmSys.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Emu/Cell/Modules/cellSpurs.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Crypto/unself.cpp
  - https://github.com/RPCS3/rpcs3/blob/df090aa12797b5c5f4a6f2567f1578ec3e85409d/rpcs3/Crypto/unedat.cpp
- **RPCS3 GT6 wiki** — https://wiki.rpcs3.net/index.php?title=Gran_Turismo_6
- **RPCS3 quickstart (firmware requirement)** — https://rpcs3.net/quickstart
- **RPCS3 PPU/SPU translator history (FOSDEM 2022)** — https://archive.fosdem.org/2022/schedule/event/ps3/attachments/slides/5257/export/events/attachments/ps3/slides/5257/slides.pdf

### Xbox 360 / N64 / PS2 analogues

- **XenonRecomp** — https://github.com/hedge-dev/XenonRecomp (README at commit `ddd128bcca99fe8bfbb99bea583c972351fa6ace`)
- **ReXGlue** — https://github.com/rexglue/rexglue-sdk (README at commit `c94f5ebdcb3c9d1a460ca48e04f9758448f8d518`)
- **N64Recomp** — https://github.com/N64Recomp/N64Recomp
- **PS2Recomp** — https://github.com/ran-j/PS2Recomp
- **UnleashedRecomp** — https://github.com/hedge-dev/UnleashedRecomp

### Reusable components and tools

- **psnr** — https://github.com/sp00nznet/psnr (README at commit `78f4a72e67b73174dac7bc602451895598e1fa9f`)
- **FFmpeg** — https://ffmpeg.org/
- **SDL2** — https://libsdl.org/
- **glslang** — https://github.com/KhronosGroup/glslang
- **SPIRV-Cross** — https://github.com/KhronosGroup/SPIRV-Cross
- **envytools / rnndb** — https://envytools.readthedocs.io/
- **Mesa nouveau nv30/nvfx** — https://gitlab.freedesktop.org/mesa/mesa/-/tree/main/src/gallium/drivers/nouveau/nv30
- **Ghidra** — https://github.com/NationalSecurityAgency/ghidra
- **LIEF** — https://github.com/lief-project/LIEF
- **Capstone** — https://github.com/capstone-engine/capstone
- **ps3-disc-dumper** — https://github.com/13xforever/ps3-disc-dumper
- **inFAMOUS clean-room decompilation** — https://github.com/bucketcomps/infamous (README at commit `f824d279808b0364bbcd8feaf5e33a3e6e536b75`)

### GT6 game facts

- **Local `PARAM.SFO`** — read-only inspection: `TITLE_ID=BCUS98296`, `APP_VER=01.00`, `PS3_SYSTEM_VER=04.5000`, `TITLE=Gran Turismo®6`.
- **Local file inventory** — read-only: `EBOOT.BIN` 72,920 bytes; `EMAIN.SELF` 8,843,160 bytes; `GT.VOL` 15,407,310,848 bytes; both executables start with `SCE\0`.
- **Companion format report** — `docs/research/gt6-formats-and-tooling.md` (same project, read-only): SELF/ELF layout, `GT.VOL`/PDIPFS, Adhoc VM, SPU SmoothMesh/MLAA, audio formats, RPCS3 status.
- **Official GT6 E3 2013 information (adaptive tessellation, HDR 50×)** — https://www.gran-turismo.com/sg/news/00_4937863.html
- **Official GT6 online end-of-service notice (2018-03-28)** — https://www.gran-turismo.com/us/news/00_5985704.html
- **Wikipedia: Gran Turismo 6 (release, 1,200 cars, 30+ tracks, weather/time)** — https://en.wikipedia.org/wiki/Gran_Turismo_6
- **RPCS3 GT6 issues referenced for SPU/RSX synchronization** — https://github.com/RPCS3/rpcs3/issues/11290, https://github.com/RPCS3/rpcs3/issues/12567
- **GT Modding Hub: Adhoc explained** — https://nenkai.github.io/gt-modding-hub/concepts/adhoc/adhoc/
- **GTAdhocToolchain** — https://github.com/Nenkai/GTAdhocToolchain
- **OpenAdhoc** — https://github.com/Nenkai/OpenAdhoc

### Hardware / ISA documentation

- **Copetti, "PlayStation 3 Architecture"** — https://www.copetti.org/writings/consoles/playstation-3/
- **IBM, SPU Assembly Language Specification v1.4** — https://ia600603.us.archive.org/27/items/ps3-public-docs/SPU_Assembly_Language_v14_e.pdf
- **IBM, SIMD Math Library Specification for Cell Broadband Engine Architecture (SPU round-toward-zero)** — https://informatica.uv.es/guia/asignatu/AAC/ps3/documentacion/SIMD_Library_Specification_for_CBEA_v10.pdf
- **IBM Cell Broadband Engine documentation index** — https://public.dhe.ibm.com/linux/cellsdk/docs

### Legal

- **17 U.S.C. §1201 (anti-circumvention; §1201(f) reverse engineering)** — https://www.law.cornell.edu/uscode/text/17/1201
- **37 C.F.R. §201.40 (2024 exemptions, including video games)** — https://www.law.cornell.edu/cfr/text/37/201.40
- **U.S. Copyright Office, 2024 Section 1201 rulemaking** — https://www.copyright.gov/1201/2024/
- **Video Game History Foundation statement on the 2024 ruling** — https://gamehistory.org/dmca-2024-statement
- **Sega v. Accolade, 977 F.2d 1510 (9th Cir. 1992) — Copyright Office summary** — https://www.copyright.gov/fair-use/summaries/segaenters-accolade-9thcir1992.pdf
- **Sony v. Connectix, 203 F.3d 596 (9th Cir. 2000) — Copyright Office summary** — https://www.copyright.gov/fair-use/summaries/sony-connectix-9thcir2000.pdf
- **Directive 2009/24/EC (EU software directive; Article 6 decompilation)** — https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0024

### Catalogues (secondary, for landscape only)

- **Recompendium PS3** — https://recompendium.com/en/consola/ps3
- **decomps.net PS3** — https://decomps.net?platform=ps3

---

## Appendix A — Glossary

| Term | Meaning |
|---|---|
| **PPU / PPE** | PowerPC Processing Unit / Power Processing Element: the Cell's main 64-bit PowerPC core, 2-way SMT. |
| **SPU / SPE** | Synergistic Processing Unit / Element: 128-bit SIMD coprocessor with 256 KB local store and MFC DMA. |
| **LS** | Local Store: 256 KB private memory per SPU. |
| **MFC** | Memory Flow Controller: the SPU's DMA engine. |
| **RSX** | Reality Synthesizer: PS3's NVIDIA NV47/G70-class GPU. |
| **GCM** | Graphics Command Management: the PS3 SDK's RSX API (`cellGcmSys`). |
| **NV4097** | The RSX's 3D method register range; games write these methods into the command FIFO. |
| **SPURS** | SPU Runtime System: Sony's cooperative task/job scheduler for the SPUs. |
| **Adhoc** | Polyphony Digital's in-house scripting language/bytecode used for most GT6 gameplay/menu logic. |
| **PAMF** | Sony's PS3 media container used by GT6 movies; encrypted on disc. |
| **SGX/ESGX** | Polyphony's proprietary engine-sound formats; synthesis, not simple PCM decode. |
| **HLE** | High-Level Emulation: reimplement console OS/library behavior natively. |
| **LLE** | Low-Level Emulation: run the real firmware/library code. |
| **OPD** | Official Procedure Descriptor: PS3 function pointer `{u32 code, u32 toc}`. |
| **TOC** | Table of Contents pointer (`r2`) used by the 32-bit PPC ABI. |
| **NID** | Name Identifier: 32-bit hash used to link PRX imports/exports. |
| **SELF** | Sony encrypted executable container (`SCE\0` magic). |
| **EDAT** | Sony encrypted data container used for DLC/updates. |
| **PRX / SPRX** | PS3 relocatable module / system module. |
| **AOT** | Ahead-of-time translation (offline, static). |
| **JIT** | Just-in-time translation (runtime, dynamic). |
| **MVNR** | Minimum Viable Native Runtime: PPU-only boot harness defined in §7. |

## Appendix B — GT6 local inventory (read-only)

| File | Size (bytes) | Magic | Role (inference) |
|---|---:|---|---|
| `PS3_GAME/PARAM.SFO` | 1,192 | `\0PSF` | Title metadata: `BCUS98296`, v1.00, system 04.5000. |
| `PS3_GAME/USRDIR/EBOOT.BIN` | 72,920 | `SCE\0` | SELF loader/launcher. |
| `PS3_GAME/USRDIR/EMAIN.SELF` | 8,843,160 | `SCE\0` | Main game executable candidate. |
| `PS3_GAME/USRDIR/GT.VOL` | 15,407,310,848 | (archive) | Main asset archive. |
| `PS3_GAME/TROPDIR` | — | — | Trophy data. |
| `PS3_GAME/LICDIR` | — | — | License/DRM data. |

**Note:** file roles are inferred from names/sizes and PS3 conventions; confirm by decryption and ELF entry-point analysis. The companion report covers GT6 file formats.

## Appendix C — Open questions that change the plan

1. **Which SELF contains the game code?** If `EMAIN.SELF` is the game and `EBOOT.BIN` is only a loader, lift `EMAIN` directly. If `EBOOT.BIN` contains meaningful setup/decryption, reproduce it.
2. **How many PPU functions and SPU images?** GT5P/GT5 suggest ~40k functions and 12–22 SPU images; GT6 could be higher. Measure before estimating.
3. **Does GT6 use SPURS for physics/geometry/audio?** Trace SPU job entry points and dispatch counts; this determines whether the SPU lifter is on the critical path.
4. **What is GT6's `GT.VOL` format?** PDIPFS-like or a new variant; the companion report should answer this.
5. **Which shaders does GT6 actually use?** Capture the unique VP/FP hashes; do not build a generic NV40 compiler before measuring.
6. **Does GT6 require PSN at boot?** If offline stubs hang, map the exact `sceNp*` call sequence.
7. **Do wheels enumerate via `cellUsbd` or `cellPad`?** Capture USB traffic or test with a real wheel; this determines the input workstream.
8. **Is v1.22 materially different?** Diff the decrypted v1.00 vs v1.22 executables; if large, treat as a second target.

---

*End of report.*
