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
