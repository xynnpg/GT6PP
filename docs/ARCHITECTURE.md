# Architecture

GT6PP is a **static-recompilation port**: the original PS3 binaries are
translated ahead of time and linked with a native runtime. There is no runtime
CPU interpreter and no emulated PS3 kernel.

```
                      build time                          run time
┌───────────────────────────────┐          ┌───────────────────────────────┐
│ EMAIN.elf (PPC64, 22.4 MB)    │          │ gt6.exe (x86-64)               │
│  33,090 functions             │          │  lifted PPU functions          │
│  747 import stubs             │  lift    │  lifted SPU images (later)     │
│  44,626 OPD descriptors       │ ───────▶ │  ps3recomp HLE runtime         │
│  embedded SPU images          │          │  RSX/GCM → D3D12               │
└───────────────────────────────┘          │  VFS → PS3_GAME/USRDIR         │
                                           └───────────────┬───────────────┘
                                                           │
                     ┌─────────────────────────────────────┼─────────────────────┐
                     │                                     │                     │
              ┌──────▼──────┐                     ┌────────▼────────┐    ┌───────▼──────┐
              │ GT.VOL      │                     │ PARAM.SFO       │    │ save/trophy  │
              │ (game's own │                     │ BCUS98296       │    │ stubs        │
              │  PFS reader)│                     └─────────────────┘    └──────────────┘
              └─────────────┘
```

## Layers

### 1. Guest memory (`vm`)

The runtime reserves a flat 4 GB guest arena and maps PS3 virtual addresses into
it. All guest pointers are 32-bit big-endian addresses; the host is 64-bit
little-endian. `vm_read*`/`vm_write*` perform the endian conversion. The PPU
loader maps the ELF's `PT_LOAD` segments at their linked addresses. The main
thread gets a 1 MB stack at `0xCFE00000`; worker threads get stacks from the
runtime's `0xD0000000` region.

### 2. PPU AOT recompiler

`ppu_lifter.py` turns each PowerPC64 function into a C function with a
`ppu_context*` argument. The context holds GPRs, FPRs, VMX registers, LR, CTR,
CR, XER, and the TOC (`r2`). Function boundaries come from the ELF's `.opd`
table (ELFv1 function descriptors), which is authoritative for this title.

Imported functions are special: `--hle-stubs` replaces each `.lib.stub`
trampoline with `ps3_hle_call(nid, ctx)`, so the guest's direct call lands in the
HLE dispatcher instead of an unpatched `li r12,0` thunk. This avoids a load-time
import resolver.

Indirect calls (`bctrl`, `blr` with a computed address) dispatch through a
sorted table of lifted function addresses (`ps3_indirect_call`). Jump tables are
lifted as `switch`-like dispatches; unresolved targets are reported.

### 3. HLE runtime

The runtime replaces PS3 system libraries. The port compiles the PPU scaffold
itself (`ppu_loader.cpp`, `ppu_hle.cpp`, `ppu_sysprx.cpp`, `ppu_fs.cpp`) against
the generated `ppu_recomp.h`, then links `libps3recomp_runtime.a`.

Key modules for GT6:

| Module | Role | Status |
|---|---|---|
| `cellGcmSys` | RSX command buffer, tiles, Zcull, flips | 39/39 NIDs named |
| `cellSpurs` | SPU task/event-flag/job-chain management | 48/49 named |
| `cellAudio` | audio output, ports | 12/12 named |
| `cellSysutil` | system callbacks, exit, OSK, video export | 42/55 named |
| `sys_fs` | file I/O | 22/26 named |
| `sys_io` | pads, USB, wheels | 18/23 named |
| `cellGame` | disc/game data queries | 8/8 named |
| `cellSysmodule` | module load/unload | 6/6 named |
| `cellPamf` / `cellDmux` / `libvdec` | video demux/decode | partial |
| `sceNp*` / `cellHttp` / `cellSsl` | PSN/network | offline stubs |

The generated `src/gen/ppu_hle_nids.cpp` maps each imported NID to a handler (or
to a missing-handler diagnostic). `stubs.cpp` is the place for game-specific
overrides.

### 4. SPU and SPURS

The Cell SPU has its own 128-bit ISA and 256 KB local store. GT6 embeds SPU
programs in `EMAIN.elf` and loads others from data. `ps3recomp` supports:

- lifting SPU programs to C (`spu_lifter.py`),
- a SPURS policy/scheduler (`cellSpurs` HLE),
- job-chain dispatch keyed by SPU image fingerprint,
- a resident SPU interpreter for images that are not lifted,
- PPU-side fallbacks for known jobs.

GT6 embeds four SPU images in `EMAIN.elf`; they were extracted and lifted
(108 / 159 / 396 / 626 functions) and registered by content fingerprint. The
runtime's `cellSpurs` HLE creates the `Wws_Job` workloads and dispatches the
lifted images. Further jobs loaded from data may need `SPU_DUMP_MISS` capture
and another lift.

### 5. RSX/GCM → D3D12

The guest writes GCM commands into a command buffer; `cellGcmSys` exposes the
put/get pointers. The runtime's `cellGcm_rsx_process_fifo()` walks the FIFO,
decodes RSX methods, and feeds the D3D12 backend:

- vertex/fragment program translation (RSX microcode → DXBC/SPIR-V),
- textures, render targets, depth/stencil, MRT, cube maps,
- tiles/Zcull, display buffers, flips.

The present thread synthesizes a 60 Hz vblank/flip tick, drains the FIFO, and
presents when the guest flips. This is what turns the guest's render loop into
visible frames.

### 6. Filesystem and `GT.VOL`

The port maps:

| Guest path | Host path |
|---|---|
| `/dev_bdvd/PS3_GAME/` | `PS3-Version/.../PS3_GAME/` |
| `/dev_bdvd/` | `PS3-Version/.../PS3_GAME/` |
| `/dev_hdd0/` | `work/gt6_hdd0/` |
| `/dev_hdd0/game/BCUS98296/` | `work/gt6_hdd0/game/BCUS98296/` |
| `/app_home/` | `work/gt6_app_home/` |
| `PDIPFS/` | `work/gt6_pdipfs/` (future updates) |

The game's own PFS reader opens `GT.VOL` and decrypts/decompresses it. A
hardlink `gt6/GT.VOL` covers relative opens; the file is ignored by git. This is
why the port does not need to extract the volume at runtime.

### 7. Boot sequence

1. `vm_init()` reserves the guest arena.
2. Commit the null page, GCM control page, RSX local memory, argv block, and
   main stack.
3. Install VFS mappings and `PARAM.SFO` identity.
4. Register lv2 syscalls.
5. Load `EMAIN.elf` (`PT_LOAD` → guest memory; BSS zeroed).
6. Register HLE handlers, sysprx, lifted PPU functions, SPU images.
7. Set up argc/argv/envp, TOC (`r2`), and SP.
8. Call the guest entry (`ppu_run` or the direct entry function).
9. A separate present thread ticks vblank/flip and drains GCM.

## Design constraints

- **No runtime translation.** All lifted code is compiled by clang/GCC into the
  executable. The only runtime dispatch is address → function table.
- **No firmware.** HLE replaces system modules; the user must supply the game,
  not a PS3 firmware image.
- **Big-endian guest.** All guest memory accesses go through endian-converting
  accessors or are explicitly swapped in lifted code.
- **32-bit guest pointers.** HLE code must translate guest addresses through
  `vm_base`; the runtime installs a low-4GB trap to catch mistakes.
- **Determinism first.** A boot that loads a stable set of assets is more
  valuable than a fast boot that races.
