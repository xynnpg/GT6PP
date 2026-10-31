# Tooling

Short list of what this port uses, what is new, and what is off-limits.

## Build / runtime

| Tool | Use |
|---|---|
| LLVM-MinGW (`tools/llvm-mingw/`) | Windows C/C++ toolchain |
| CMake + Ninja | build |
| `third_party/ps3recomp` | static-recompilation runtime/HLE |
| `tools/GTToolsSharp` | GT.VOL list/extract/decrypt |
| `tools/RPCS3` | offline oracle only; never the shipped runtime |
| Capstone 5 / pyelftools | quick disassembly and ELF checks |

## New: Ghidra 10.4 headless

Installed under `tools/ghidra_dl/` (ignored by git). Java 17 is already on the
machine. Decompile selected guest functions:

```powershell
tools\ghidra_dl\ghidra_10.4_PUBLIC\support\analyzeHeadless.bat `
  tools\ghidra_dl\proj GT6 `
  -import work\bin\EMAIN.elf -noanalysis `
  -scriptPath tools\ghidra_scripts `
  -postScript DecompileAt.java `
  0x9E191C:0x9E1C0C:value_compare `
  0x5F299C:0x5F2D00:adhoc_reader `
  work\ghidra_out.c -deleteProject
```

This is for understanding only. It does not replace `ppu_lifter.py`.

## New agent skills

Installed globally in `~/.agents/skills/`:

- `binary-analysis-patterns` — disassembly/decompilation/CFG checklists.
- `ghidra-reverse` — Ghidra headless workflow and decompilation.

## RenderDoc 1.46 (D3D12 frame capture)

Installed under `tools/renderdoc/` (ignored by git). Use it to inspect why the
first `draw_arrays` is black: the 1440×1080 offscreen target, vertex colors,
shader outputs, resources and the present path.

```powershell
tools\renderdoc\renderdoccmd.exe capture --help
# or launch the GUI:
tools\renderdoc\qrenderdoc.exe
```

The `cli-anything-renderdoc` agent skill is installed; the capture file can be
analyzed with `renderdoccmd`/the RenderDoc Python API.

## PKG update extraction (optional)

`tools/pkg2zip/pkg2zip.exe` (MIT) is installed for the official GT6 update PKG
you supply. It is not used on the v1.00 disc. After extracting
`Prototypes.adc`, install it with `tools/gt6_install_companion_script.py`.

## Debugging tools (installed locally)

- **ProcMon** (`tools/procmon/Procmon64.exe`) - host file I/O. Confirm the
  `/font/...` reads and whether the worker's read completes.
- **x64dbg** (`tools/x64dbg/bin/release/x64dbg.exe`) - user-mode debugger.
  Attach to `gt6.exe`, break in `sys_lwcond_wait`/`sys_lwcond_signal`, inspect
  the stuck worker and the guest stacks.
- **WinDbg** is not installed (no winget on this machine); x64dbg is the
  installed debugger. ProcMon is portable and needs no install.
- **DOD3Recomp reference** (`tools/reference/dod3-recomp`, ignored): a
  playable PS3 recomp using the same ps3recomp toolkit. Its fork
  `tools/reference/soyjxck-ps3recomp` has a generation-based `sys_lwcond`
  implementation; see `docs/analysis/dod3-reuse.md`.

## PFS cache seeding (boot/presents assets)

The native HDD tree originally held only 11 PDIPFS keys, so the guest never
opened `K/LH` (`boot.adc`), `K/KG`, `K/IE`, `K/WD` or the boot fonts. Seed the
raw GT.VOL slices (still volume-encrypted, like the working `K/IK`) with:

```powershell
python tools\gt6_seed_pfs_cache.py --boot-set --dry-run
python tools\gt6_seed_pfs_cache.py --boot-set
python tools\gt6_seed_pfs_cache.py --boot-set --verify
```

The tool reads `work/gt6_pfs_keymap.tsv`, copies each `ZSize` slice from
`gt6/GT.VOL` into `work/gt6_hdd0/.../PDIPFS/K/<key>`, and creates zero-length
`PDIPFS_bdmark/K/<key>` markers. It never decrypts or fabricates data. See
`docs/analysis/pfs-cache-seeding.md`.

## Frame capture and visibility check (no desktop screenshots)

The D3D12 backend dumps its own backbuffer, so a window/desktop capture is not
needed and cannot silently grab the wrong window:

```powershell
$env:RSX_CAP="1:4:60"                 # start frame_count[:count[:stride]]
$env:RSX_CAP_DIR="work/rsxcap_baseline"
gt6\build\gt6.exe work\bin\EMAIN.elf
python tools\gt6_frame_check.py work\rsxcap_baseline `
  --glob "frame_*/backbuffer.bmp" --min-nonblack 5
```

`frame_NN/backbuffer.bmp` is the composed frame; `frame_NN/manifest.txt` lists
every clear/draw with surface, shader, texture and VP state. The checker reports
non-black coverage, mean/peak luma, distinct colours and the lit bounding box;
exit 0 means a visible frame. The method is adapted from GT4Recomp's
`gs_frame_metrics` (MIT), not its code.

## PAMF movies (`work/gt6_vol/movies/*.pam`)

The extracted `.pam` files are still **Salsa20-encrypted at the movie layer**;
GTToolsSharp's unpack decrypts only the PDIPFS/GT.VOL layer. The per-movie key is
in `database/gt6/menudb.dat`, table `t_movie`, column `Key`.

```powershell
# On copies only; do not edit the extracted game data.
# <MENUDB_KEY> is the public constant in GTToolsSharp/Encryption/KeysetStore.cs.
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptsalsa -i work\pamf_test\menudb.dat -k <MENUDB_KEY>
# Read t_movie.Key for the desired FileName with any SQLite client, then:
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptmovie -i work\pamf_test\tv_10006.pam -k $key
python tools\pamf_info.py work\pamf_test\tv_10006.pam --check-packs
tools\pamftool\PAMFtool.exe -demux work\pamf_test\tv_10006.pam work\pamf_test\demux10006
tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe -i work\pamf_test\demux10006\tv_10006.s00_avc.h264 -frames:v 1 out.png
```

* `tools/pamf_info.py` is a clean-room reference parser for decrypted PAMF
  0040/0041 files; it does not handle encryption.
* PAMFtool v1.3 is **GPLv3** and has no encryption support. Keep it a separate
  process; do not link/copy its code into the MIT runtime.
* FFmpeg has no PAMF demuxer; it does have H.264 and ATRAC3+ decoders. Feed it
  PAMFtool's demuxed `.h264`/`.at3` outputs.
* The runtime fix is in the HLE, not the disc file: `cellPamf.c` uses the wrong
  header offsets and `cellDmux` lacks the `OpenEx`/`QueryAttr` PAMF backend. See
  `docs/analysis/pamf-intro-fix.md` for the exact layout and ranked plan.

## Restricted sources (do not use)

- `third_party/PDTools/AGENTS.md` prohibits AI/LLM use of that repository.
- `Nenkai/GTAdhocToolchain` has its own `AGENTS.md` and vendors `PDTools`; it is
  not used here. The official GT6 update/patch volume is the legitimate source
  of the missing `Prototypes.adc`.

## `Prototypes.adc` correction

The RPCS3 oracle (`docs/analysis/rpcs3-oracle.md`) shows the **v1.00 disc alone**
reaches the legal/loading screen, first-run display setup, epilepsy warning,
intro movie and Player Name screen. It loads the same cursor assets as the
native port and **never loads `Prototypes.adc`**. The v1.00 engine consumes
`Prototypes.mwidget` (MPRJ); the native port's request for `Prototypes.adc` is a
loader/path artifact. Do not source or fabricate it. Fix the native
`loadPrototype`/MPRJ path instead.

The companion installer remains only for a genuine official-update file you
already own; it is not required for v1.00.
