# GT4Recomp reuse review

**Source:** `moesuito/gt4-staticrecomp`, cloned read-only under
`tools/reference/gt4-staticrecomp` (ignored by git).
**License:** MIT for its own code; PCSX2/GSdx is GPL and lives in a separate
process. Its `AGENTS.md` is an agent workflow guide, not an AI-use prohibition.

## What is useful here

| GT4Recomp piece | GT6PP use |
|---|---|
| `tools/vu_recomp` | Microcode AOT pattern: identity digests, differential tests, explicit fallback counts. Adapt the *method* to missing GT6 SPU job images; do not copy PS2 VU code blindly. |
| `native/pacing.cpp`, `frame_clock.cpp` | Single-clock frame pacing and audio-rate control, for the 60 FPS target after the first visible frame. |
| `native/native_vulkan.cpp`, `window.cpp` | Reference for async present and Win32 input/event plumbing; GT6PP currently uses D3D12. |
| `launcher/`, `installer/`, `docs/DISTRIBUTION.md` | Pattern for shipping code only and asking the user for their own disc; useful at release time. |
| `docs/ARCHITECTURE.md`, `TASKS.md` | Evidence/one-writer workflow and task acceptance style. |

## What is not reusable

- EE, IOP, VU0/VU1, GS, GSdx and PCSX2 code: PS2 hardware and GPL; GT6PP targets
  PS3 PPU/SPU/RSX. Reference only, never linked.
- `gt4disc.py`, `gt4_volume.py`, `gt4_vif_framing.py`: GT4 volume/VIF formats, not
  GT6 `GT.VOL`/PFS.
- `LICENSE-DEMO-CIPHER.md`: GT4's FPU-keyed demo cipher, not GT6 PAMF (which is
  Salsa20/keyed from `menudb.dat`; see `pamf-intro-check.md`).

## Adopted now

- `tools/gt6_frame_check.py` - reads the D3D12 backend's own 24-bit
  `backbuffer.bmp` dumps and reports non-black coverage, mean/peak luma,
  distinct colours and the lit bounding box. Adapted from the *method* of
  `tools/gs_frame_metrics` (ground truth from frame bytes, not a desktop
  screenshot); the code is original. This is how the first real legal frame
  will be verified.

- The one-writer integration rule from `AGENTS.md`/`AGENT-WORKFLOW.md`
  (workers propose, an independent reviewer re-derives, one integrator applies
  and builds) is already the GT6PP loop. Keep it: it caught the inert W2 size
  repair and the rejected source-bind patch.

## Immediate conclusion

GT4Recomp does **not** solve the current first-screen blocker (boot/presents
script execution, fonts, `PresentsRootSCEA`, no-VP textured draws). Its best
near-term value is the VU1 AOT test/identity pattern for SPU job lifting; its
pacing and launcher work matter after the first visible frame.
