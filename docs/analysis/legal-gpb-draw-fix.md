# Legal GPB draw: generic legacy textured path

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`,
`gt6/build/gt6.exe`; D3D12 backend in
`third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`.
**Scope:** read-only analysis of the GPB container, `boot.adc`, and the
current D3D12 backend. The generic legacy textured path described here is
**implemented and applied in the working tree** of
`third_party/ps3recomp` (uncommitted) and recorded in
`patches/gt6-legal-gpb-draw-fix.patch`. No build and no `gt6.exe` run were
performed for this report (READ-ONLY w.r.t. `gt6.exe`); verification is by
log/gate inspection only.

## 0. Verdict

| Question | Answer |
|---|---|
| What is the first real GPB draw? | The `PresentsRoot` page draws its image plates. `PresentsRoot.ad` (embedded in `boot.adc` at `0x1D374`) owns `Plate0`/`Plate1`; `changeImage` sets `/image/boot/<path>.dds` on the front plate and runs the two `ScalarInterpolator`s for a cross-fade. The first sequence is `common/JP/scei` (2 s), `common/notice` (2 s), `scea/JP/epilepsy` (4 s). |
| What does it supply? | A 2D textured image quad/triangle pair: attr0 position, attr3 colour/alpha, attr8 (or attr2) UVs, texture unit 0, backbuffer target. The texture is the GPB's embedded TXS3: `scei` 864x128 DXT1 (`0xA6`), `notice` 1440x720 DXT1, `epilepsy` 1920x1080 DXT1; the page also carries `pdi` 460x80 A8R8G8B8 (`0xA5`) and `loading_circle` 24x24 DXT1. |
| VP or no VP? | **Not measured yet.** The native boot path does not reach `PresentsRoot` in the current logs, so the guest state of the first plate draw is unknown. The backend now handles **both** branches: `vp_ucode_bytes >= 16` uses the existing VP/FP texture path (`vp_upload_tex_slot` → guest-FP PSO sampling t0); `vp_ucode_bytes < 16` uses the new generic legacy textured PSO added by this patch. |
| Why is/was it dropped? | Before the patch, `d3d12_bind_texture` recorded a generic texture in `cur_texs[0]` but set `tex_bound` only for B8 (`0x81`), so the legacy fallback wrote `textured=0` and no texture fields; the only legacy textured PSO sampled the dbgfont atlas (`uv*10/8+0.59` coverage) and never a GPB image. A no-VP GPB image was submitted as an untextured quad. |
| Missing path | **None remaining.** The generic legacy textured PSO + per-draw guest texture upload/SRV for `is_vp == 0` draws is implemented. The VP/FP path already existed. |
| Patch | `patches/gt6-legal-gpb-draw-fix.patch` (applies inside `third_party/ps3recomp`). Verified: its hunks exactly match the working-tree backend; it reverse-applies cleanly to the tree and reproduces it. Base note: the patch context assumes the immediate-path fields (`is_immediate`, `pipeline_state_immediate`) already exist, i.e. it targets the tree state that also carries the DATA2F/self-test work, not raw `ps3recomp` HEAD `4e8f3ca`. |
| First draw to test | `PresentsRoot.changeImage("common/JP/scei")`: 864x128 DXT1, then `notice` (1440x720 DXT1), then `epilepsy` (1920x1080 DXT1). The 30 s oracle frame is an exact `epilepsy.dds` match and is the strongest pixel gate. |

## 1. What the first GPB draw supplies

### 1.1 Script-side evidence

`boot.adc` has one module for `PresentsRoot.ad`:

```text
PresentsRoot
  idx = 0
  plates = [Plate0, Plate1]
  open(context)          -> SequenceUtil.startPageDirect(context, PresentsRoot)
  onInitialize(context)  -> Plate0/Plate1 ScalarInterpolator.reverse = false
                            Plate0/Plate1 image ScalarInterpolator.reset()
  changeImage(path)      -> front.image.image_path = "/image/boot/" + path + ".dds"
                            start/reverse the plate + image interpolators
```

`presents_table_scea` selects:

```text
common/JP/scei     2.0 s
common/notice      2.0 s
scea/JP/epilepsy   4.0 s
```

So the first asset-backed legal draw is the `scei` plate, not the immediate
`DATA2F` black cover. `Plate0`/`Plate1` are cross-faded, which is why the draw
carries a vertex/constant alpha and uses alpha blending.

### 1.2 GPB texture layout

`PresentsRootSCEA.gpb` is a `3bpg` container. The TXS3 header carries the RSX
format byte at `+0x4A` (the `+0x5A` word used by `gt6_gpb_extract.py` is the
GCM flags word, `0x2000`), width at `+0x5C`, height at `+0x5E`; the DXT1
payload starts at `+0x80`:

| Pair | Texture | Dimensions | RSX format | Backend format class |
|---:|---|---:|---|---|
| 0 | `/image/boot/common/JP/scei.dds` | 864x128 | `0xA6` | DXT1 -> `0x86` BC1 |
| 1 | `/image/boot/common/notice.dds` | 1440x720 | `0xA6` | DXT1 -> `0x86` BC1 |
| 2 | `/image/boot/common/pdi.dds` | 460x80 | `0xA5` | A8R8G8B8 -> `0x85` RGBA8 |
| 3 | `/image/boot/scea/JP/epilepsy.dds` | 1920x1080 | `0xA6` | DXT1 -> `0x86` BC1 |
| 4 | `/image/cursor/loading_circle.dds` | 24x24 | `0xA6` | DXT1 -> `0x86` BC1 |

`d3d12_bind_texture` masks `LN(0x20)`/`UN(0x40)` with `fmt & 0x9F`, so all
four image classes are already accepted by
`vp_upload_tex_slot`/`rsx_texture_layout`. Decode and format support exist;
what was missing (now implemented by §3) is that the legacy/no-VP draw never
carried the binding into `render_frame` and had no PSO that samples a generic
image.

### 1.3 State the draw is expected to carry

| State | Expected value | Why |
|---|---|---|
| Primitive | `QUADS` or `TRIANGLES` / `TRIANGLE_STRIP` | Image plates are 2D quads. The patch handles the legacy QUADS expansion and the legacy triangle/strip fallback. A no-VP `TRIANGLE_FAN` remains unsupported (pre-existing). |
| attr0 | float32 position, size >= 2 | Standard sprite vertex. |
| attr3 | vertex colour/alpha, or the constant attr3 | The new PS multiplies the sampled RGBA by it, so the plate fade works. |
| UV | attr8..15 first, else attr2 | Existing `read_rsx_vertex` selection; GPB UVs are normalised. |
| Texture | unit 0 (t0), 864x128 / 1440x720 / 1920x1080 DXT1 or 460x80 RGBA8 | GPB image plate. |
| Blend | alpha cross-fade | `ScalarInterpolator` on both the plate and its image. The legacy generic PSO uses straight alpha (`SRC_ALPHA`/`INV_SRC_ALPHA`). |
| Target | display backbuffer | Legacy records force `rt_off = 0`; `PresentsRoot` is a full-screen 2D page. |
| VP/FP | unknown; no-VP is the case this patch adds | If `[DRAWDIAG]` shows `vp_ucode>=16`, the draw takes the existing VP path. |

The concurrent `docs/analysis/first-draw-audit.md` §2.2 adds the strongest
static evidence for the draw class: GT6's UI batcher `func_00B65C04`
(`gt6/generated/ppu_recomp_026.cpp:104054`) writes four-vertex buffers, sets
attr0 = float32 x2 (stride `0x10`) and attr8 = float32 x2 (stride `0x10`), and
calls the draw builder with **primitive 8 (`QUADS`)**, first 0, count a
multiple of 4. The same audit finds the UI mode setter loads a transform
program via `0x1E9C`, so the expected branch is **QUADS + VP+FP**. That is not
proven for PresentsRoot because no PresentsRoot RSX stream has been captured.
The patch is the no-VP fallback for exactly that QUADS/attr0/attr8 shape; it
does not change the expected VP branch.

## 2. What the backend does with the first GPB draw

Two branches now cover the first plate draw; which one fires depends on the
guest state (`vp_ucode_bytes`) which is not yet measured:

### 2.1 VP branch (`vp_ucode_bytes >= 16`, expected)
`d3d12_draw_arrays` routes `QUADS`/`TRIANGLES`/`TRIANGLE_STRIP` to `upload_*_vp`,
which fetches all 16 attributes, expands quads to a triangle list, and records
`is_vp=1` with `fp_addr`, per-unit textures (`cur_texs[0..3]` copied at
record time), blend key, target, and `cb_slot`. `render_frame()`'s VP pass
compiles the guest FP via `vp_get_fp_pso()` and uploads the draw's unit-0
texture through `vp_upload_tex_slot()`, binding the per-draw SRV window at
`DRAW_SRV_BASE + d*4` as t0. A DXT1 GPB plate therefore samples correctly
*provided* the guest FP decompiles/compiles. If `fp_addr == 0` on a VP draw,
the fallback is the atlas/colour PSO pair (P1b territory — not part of this
patch).

### 2.2 Generic legacy branch (`vp_ucode_bytes < 16`, added by this patch)
Without guest VP microcode the draw falls to the legacy expansion
(`upload_quads_from_rsx` / `upload_vertices_from_rsx`), which reads attr0
position, attr3 colour (constant or array), attr8..15/attr2 UV, and applies
the RSX viewport transform. The patch makes this path sample a generic guest
image:

1. **Bind is captured at draw time.** `legacy_record_texture()` is called by
   both legacy record builders (QUADS fallback and triangle/other fallback).
   It snapshots unit 0 (`off`, `raw`, `w`, `h`, `fmt`, `ctrl1`, `cube`,
   `mips`, address/filter/control/border) into `dr->tex[0]` and sets
   `dr->legacy_tex = 1`, but only when
   `legacy_generic_tex_bound()` is true: unit 0 set and non-zero, format in
   `0x85` / `0x86..0x88` (RGBA8 / DXT1-23-45), and the B8 atlas (`0x81`) is
   not the bound texture (the atlas keeps its own coverage PSO).
2. **Texture uploaded per draw.** `render_frame()` runs a pre-pass loop that,
   for each non-VP, non-clear record with `legacy_tex`, calls
   `vp_upload_tex_slot(dr->tex[0].off, w, h, fmt, 0, mips)` (reusing the
   existing DXT1 block-copy / RGBA8 decoder — no new decoder) and writes the
   resulting SRV into the record's own 4-descriptor window at
   `DRAW_SRV_BASE + d*4` via `srv_write_ex()`. Two legacy image draws cannot
   alias a descriptor.
3. **SRV bound as t0 at draw time.** The legacy replay loop binds the SRV heap,
   binds slot 0 (atlas) as the default t0 table, then rebinds the per-draw
   window for generic-textured records (`last_srv_slot` dedupes consecutive
   draws that share a window).
4. **PSO selection.** `pipeline_state_tex_generic` (created next to the atlas
   PSO in `init_d3d12`) is selected when
   `dr->legacy_tex && dr->tex_slot >= 0`. Its PS is
   `tex.Sample(smp, i.uv) * i.col` — straight RGBA sample modulated by vertex
   colour/alpha (the plate fade), straight-alpha blending, depth off, no
   dbgfont `*10`/`*8` UV scaling and no coverage->alpha reinterpretation.
   The VS is the existing `vs_tex` (MVP `c0..c3` via root constants b0 +
   position/colour/UV), so positions go through the guest MVP/identity.
5. **Vertex-position heuristic gated.** `read_rsx_vertex()`'s dbgfont
   fractional-position fold is skipped when `legacy_generic_tex_bound()`, so a
   normal 2D plate position reaches the VS unchanged. Caveat: with no guest VP
   and no ortho `c0..c3`/viewport transform, window-pixel positions clip; the
   verification gates below require `c0..c3` or `viewport_scale` to be non-zero.
6. **Lifetime.** `pipeline_state_tex_generic` is released in
   `rsx_d3d12_backend_shutdown`.

### 2.3 Before the patch (baseline `08f92ec`)
For the record, the pre-patch defect was: `d3d12_bind_texture` populated
`cur_texs[unit]` for `0x85`/`0x8B`/`0x86..0x88`/`0x9A` but set
`s_d3d.tex_bound = 1` only for B8 (`0x81`), so every generic GPB bind left
`tex_bound = 0`; the legacy fallback wrote `textured = 0` and no texture
fields, reaching `render_frame()` with `t0 = 0`; and the only legacy textured
PSO was the dbgfont atlas (`uv*10/8+0.59` coverage), never a GPB sampler.

## 3. Patch file contents

`patches/gt6-legal-gpb-draw-fix.patch` modifies a single file,
`libs/video/rsx_d3d12_backend.c` (inside `third_party/ps3recomp`), and adds
only the legacy/no-VP path; the VP/FP path is untouched. Implementation detail
is in §2.2; this section lists what the patch touches for review.

- `D3D12DrawRecord`: new `legacy_tex` flag (no-VP draw samples tex[0] through
  the generic legacy textured PSO).
- `D3D12State`: new `pipeline_state_tex_generic` PSO pointer.
- `init_d3d12()`: compiles `ps_tex_generic` (`tex.Sample(smp, uv) * i.col`,
  straight-alpha blend, depth off, `vs_tex` MVP VS) and creates
  `pipeline_state_tex_generic`; renames the atlas PSO comment to "dbgfont
  atlas PS".
- New helpers: `legacy_generic_tex_format()` (`0x85` / `0x86..0x88`),
  `legacy_generic_tex_dxgi()`, `legacy_generic_tex_bound()` (excludes B8
  atlas and unset unit 0), `legacy_record_texture()` (snapshots unit 0 into
  `dr->tex[0]`, sets `legacy_tex`).
- `render_frame()`: legacy per-draw upload pre-pass calling
  `vp_upload_tex_slot()` and writing each record's SRV window at
  `DRAW_SRV_BASE + d*4`; SRV heap bound unconditionally; `last_srv_slot`
  dedup; PSO selection branch
  `legacy_tex && tex_slot >= 0 -> pipeline_state_tex_generic`.
- `read_rsx_vertex()`: dbgfont fractional-position fold gated on
  `!legacy_generic_tex_bound()`.
- `d3d12_draw_arrays()`: both legacy record builders (QUADS and
  triangle/other) call `legacy_record_texture(dr)`.
- `[DRAWDIAG]`: generic-texture/no-VP line now reports whether the legacy
  generic PSO will be used or the format is not sampleable.
- `[LEGACYTEX]`: new per-record upload log (`-> generic PSO` or
  `upload FAILED -> untextured`).
- `rsx_d3d12_backend_shutdown()`: releases `pipeline_state_tex_generic`.

**Review note:** the patch's context assumes the immediate-path fields
(`is_immediate`, `pipeline_state_immediate`) already exist, so it targets the
tree state that also carries the DATA2F/self-test work, not raw
`ps3recomp` HEAD `4e8f3ca`. Verified: the patch's hunks exactly match the
working tree (reverse-applies cleanly and reproduces it); see
`docs/analysis/first-draw-audit.md` §8.

## 4. Verification

The patch is already applied in the working tree of
`third_party/ps3recomp`; no source edit is needed. Because `gt6.exe` is
READ-ONLY (no build, no run), verification is by log/gate inspection against
a real run that reaches `PresentsRoot` (boot/presents load must land first —
see `docs/analysis/first-visible-ui-fix.md` §5). The diagnostic DDS overlay
must stay off; do **not** count an overlay frame as a legal-GPB result.

### 4.1 Run the real frame with the overlay off

```powershell
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$env:GT6_BRINGUP_DDS   = "0"          # explicit 0; overlay is opt-in
$env:RSX_CAP           = "1:16:1"     # 1 s windows; 1:4:60 can miss the 2 s scei/not notice windows
$env:RSX_CAP_DIR       = "work/rsxcap_legal_gpb"
$env:RSX_VTXDBG        = "16"
$env:GT6_BOOTUI_TRACE  = "1"
$env:GT6_BOOT_TRACE    = "1"
$env:PS3_VERBOSE       = "1"
# gt6\build\gt6.exe work\bin\EMAIN.elf 2> work\legal_gpb_run.err   (READ-ONLY: not executed here)
```

### 4.2 Gate 1: `RSX_CAP` manifest has a real t0

```powershell
Select-String work\rsxcap_legal_gpb\frame_00\manifest.txt `
  -Pattern 't0=0x0*[1-9A-F]|t0 off='
```

Required: a `DRAW` op with `t0 != 0` and a `t0 off=... fmt=...` child line.
The first legal image should be one of:

```text
t0 off=0x........ fmt=0x86 (SZ) 864x128    ; scei
t0 off=0x........ fmt=0x86 (SZ) 1440x720   ; notice
t0 off=0x........ fmt=0x86 (SZ) 1920x1080  ; epilepsy
t0 off=0x........ fmt=0x85 (SZ) 460x80     ; pdi
```

`t0=0` on the plate draw means the bind was not captured; check
`[DRAWDIAG] tex0` and the `SET_TEXTURE_OFFSET`/format pair.

### 4.3 Gate 2: `[DRAWDIAG]` / `[LEGACYVTX]` / `[LEGACYTEX]`

```powershell
Select-String work\legal_gpb_run.err `
  -Pattern '\[LEGACYTEX\]|\[DRAWDIAG\]|\[LEGACYVTX\]'
```

Required:

- `[LEGACYTEX] op=... t0=0x... fmt=0x86 864x128 slot=... -> generic PSO`
  (or notice/epilepsy/pdi size), not `upload FAILED`. Absent on a VP-branch
  draw (use `[VP]` / `[FP]` logs instead).
- `[DRAWDIAG] prim=... vp_ucode=0 ... target=0x... (display)` for the legacy
  path; `vp_ucode>=16` means the VP path — judge via `[VP] pipeline ready` /
  `[FP] guest FP pipeline ready (fp=0x...)` and no `[FP] decompile fail` /
  `PS compile FAIL` / `PSO FAIL`.
- `[DRAWDIAG] a3 en=1` with non-black constant/array colour, or
  `[LEGACYVTX] col=(...)` non-zero, and `uv=(...)` non-zero.
- `tex0=0x... fmt=0x86 ... bound=0 atlas=0` (the generic bind is intentionally
  not the B8 atlas flag).

### 4.4 Gate 3: frame check with the overlay off

```powershell
python tools\gt6_frame_check.py work\rsxcap_legal_gpb `
  --glob "frame_*/backbuffer.bmp" --min-nonblack 1.0 --min-colors 16
```

A PASS is only valid with `GT6_BRINGUP_DDS=0` (the overlay is opt-in and
unset/empty is also off). The first `scei` plate is
864x128 centred on a 1280x720 frame, so screen coverage is only about
1.5-3.3 %; `--min-nonblack 1.0 --min-colors 16` is the gate for the first
legal frame. Reserve `--min-nonblack 5` for the full-screen `epilepsy` frame.
`first-draw-audit.md` §5.1-5.2 gives the same threshold caveat.
`[BRINGUP]` must be absent and the manifest texture offset must match the GPB
bind; `draws=1` plus a non-black BMP is **not** sufficient (the overlay adds
no draw — see `first-draw-audit.md` §1.3).

### 4.5 Negative controls

| Observation | Meaning |
|---|---|
| `[LEGACYTEX] ... upload FAILED` | Guest offset resolved to 0 or the texture is empty; check `TEXSRC`/`TEX_PROBE`. |
| `[DRAWDIAG] generic texture bound, no VP: format NOT sampleable...` | Format outside `0x85/0x86..0x88`; GPB expects `0xA6`/`0xA5`. |
| Manifest `t0=0` | Legacy record did not capture unit 0; check `SET_TEXTURE_OFFSET` ordering before `BEGIN_END`. |
| `vp_ucode>=16` | Draw took the VP path; this patch is inert for it (judge via guest FP logs). |
| `GT6_BRINGUP_DDS` set to a DDS path | Overlay frame; not a legal-GPB result. |
| `t0` correct but nothing visible | Check `[LEGACYVTX]` positions / `c0..c3` / `viewport_scale`; the no-VP GPB draw may be clipped by the missing transform. |
| Guest FP fallback wrong on a VP draw | `fp_addr != 0` but `[FP]` logs show a compile fail; next step is P1b (generic VP-FP fallback PSO), not another upload change. |

## 5. Risks and limits

- **VP/no-VP remains unmeasured.** The patch is deliberately the no-VP half.
  A VP+FP draw already samples generic textures; a VP draw without an FP still
  falls back to the colour VP PS and is not fixed here.
- **Blend is the legacy straight-alpha policy.** Guest blend factors are not
  keyed into the legacy PSO (pre-existing). The plate cross-fade is expected to
  work because it is vertex-alpha over black.
- **Guest FP is not executed on the legacy path.** The new PS assumes the GPB
  plate's operation is `t0.rgba * vertex_colour`. If `[DRAWDIAG]` shows
  `fp != 0` on a no-VP draw and the image is wrong, the next step is a legacy
  guest-FP path, not another texture upload change.
- **Only unit 0 is captured for legacy draws.** The GPB ImageFace path binds
  t0. A later multi-texture legacy effect needs the same treatment for units
  1-3.
- **No-VP triangle fans are still unsupported**, and indexed no-VP draws still
  require the VP path. The GPB image path is expected to use quads or a
  triangle list/strip.
- **Scissor is still a no-op** and the legacy record forces the display
  backbuffer. That matches the full-screen legal page but would overdraw a
  sub-rect UI.
- **Stale texture binds**: `cur_texs` is not invalidated on an unsupported bind
  (pre-existing). The format check prevents sampling an unsupported binding,
  but a later supported bind can reuse the last one if the guest never rebinds.

## 6. Evidence index

| Evidence | Location |
|---|---|
| `PresentsRoot.ad` class, `Plate0/Plate1`, `changeImage`, interpolators | `work/gt6_vol/projects/gt6/boot/boot.adc`; `tools/adch_disasm.py` output at code `0x1D374`, `0x1D39F`, `0x1D4D1`, `0x1D716` |
| `presents_table_scea` order | `docs/analysis/first-visible-ui-fix.md` §1.2; `boot.adc` `0x15E9F` |
| GPB pairs, formats, dimensions | `work/gt6_vol/projects/gt6/boot/US/PresentsRootSCEA.gpb`; TXS3 `+0x4A` format, `+0x5C/+0x5E` dimensions |
| GPB extractor layout | `tools/gt6_gpb_extract.py` |
| UI batcher shape (QUADS, attr0/attr8) and expected VP branch | `docs/analysis/first-draw-audit.md` §2.2-2.3; `gt6/generated/ppu_recomp_026.cpp:104054-105284` |
| B8-only `tex_bound` | `rsx_d3d12_backend.c` `d3d12_bind_texture` (baseline 8426, flags 8570-8573) |
| Legacy record drops texture | `rsx_d3d12_backend.c` `d3d12_draw_arrays` (baseline 7846, 8144-8147) |
| Atlas-only legacy PSO | `rsx_d3d12_backend.c` `pipeline_state_tex` (baseline 334, block 1216) and legacy selector (baseline 5312) |
| Texture upload/decode to reuse | `rsx_d3d12_backend.c` `vp_upload_tex_slot` (baseline 2987) |
| Manifest fields | `rsx_d3d12_backend.c` `rsx_capture_frame` (baseline 1838-1861) |
| Frame checker | `tools/gt6_frame_check.py`; `scripts/verify-real-frame.ps1` |
| Patch | `patches/gt6-legal-gpb-draw-fix.patch` |
