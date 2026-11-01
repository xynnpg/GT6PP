# Legal GPB draw: generic legacy textured path

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`,
`gt6/build/gt6.exe`; D3D12 backend in
`third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`.
**Scope:** read-only analysis of the GPB container, `boot.adc`, and the
current D3D12 backend. No build and no `gt6.exe` run were performed. The
backend is delivered as `patches/gt6-legal-gpb-draw-fix.patch`; the working
tree copy of `third_party/ps3recomp` was restored after generating it.

## 0. Verdict

| Question | Answer |
|---|---|
| What is the first real GPB draw? | The `PresentsRoot` page draws its image plates. `PresentsRoot.ad` (embedded in `boot.adc` at `0x1D374`) owns `Plate0`/`Plate1`; `changeImage` sets `/image/boot/<path>.dds` on the front plate and runs the two `ScalarInterpolator`s for a cross-fade. The first sequence is `common/JP/scei` (2 s), `common/notice` (2 s), `scea/JP/epilepsy` (4 s). |
| What does it supply? | A 2D textured image quad/triangle pair: attr0 position, attr3 colour/alpha, attr8 (or attr2) UVs, texture unit 0, backbuffer target. The texture is the GPB's embedded TXS3: `scei` 864x128 DXT1 (`0xA6`), `notice` 1440x720 DXT1, `epilepsy` 1920x1080 DXT1; the page also carries `pdi` 460x80 A8R8G8B8 (`0xA5`) and `loading_circle` 24x24 DXT1. |
| VP or no VP? | **Not measured yet.** The native boot path does not reach `PresentsRoot` in the current logs, so the guest state of the first plate draw is unknown. The patch covers the **no-VP** case; a draw with `vp_ucode_bytes >= 16` already uses the VP/FP path and is unchanged. |
| Why is it currently dropped? | `d3d12_bind_texture` records a generic texture in `cur_texs[0]` but sets `tex_bound` only for B8 (`0x81`). The legacy fallback record writes `textured=0` and no texture fields, and the only legacy textured PSO samples the dbgfont atlas with `uv*10/8+0.59` as coverage. A no-VP GPB image is therefore submitted as an untextured quad (or samples the wrong atlas). |
| Missing path | **Generic legacy textured PSO + per-draw guest texture upload/SRV for `is_vp == 0` draws.** |
| Patch | `patches/gt6-legal-gpb-draw-fix.patch` (applies inside `third_party/ps3recomp`). |
| First draw to test | `PresentsRoot.changeImage("common/JP/scei")`: 864x128 DXT1, then `notice`, then `epilepsy`. The 30 s oracle frame is an exact `epilepsy.dds` match and is the strongest pixel gate. |

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
`vp_upload_tex_slot`/`rsx_texture_layout`. The missing piece is not decode or
format support; it is that the **legacy/no-VP draw never carries the binding
into `render_frame` and has no PSO that samples a generic image**.

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

## 2. Why the current backend cannot draw it

Baseline line references are from the unpatched
`rsx_d3d12_backend.c` at `08f92ec`.

1. **The bind is recorded but not flagged as textured.**
   `d3d12_bind_texture` (line 8426) populates `cur_texs[unit]` for `0x85`,
   `0x8B`, `0x86..0x88`, and `0x9A`, but only B8 (`0x81`) sets
   `s_d3d.tex_bound = 1` (lines 8570-8573). Every generic GPB bind leaves
   `tex_bound = 0`.
2. **The legacy fallback throws the binding away.**
   The non-VP triangle/other fallback in `d3d12_draw_arrays` (line 7846)
   writes `textured = 0` and never copies `cur_texs[0]` into the draw record
   (around line 8144). The legacy QUADS fallback copies only
   `textured = tex_bound`. A GPB image draw therefore reaches
   `render_frame()` with `t0 = 0`.
3. **The only legacy textured PSO is the dbgfont atlas.**
   `pipeline_state_tex` (line 334, created around line 1216) uses:
   ```hlsl
   float2 uv2 = float2(i.uv.x*10.0, i.uv.y*8.0 + 0.59);
   float cov = tex.Sample(smp, uv2).r;
   return float4(i.col.rgb, i.col.a * cov);
   ```
   That is a single-channel coverage atlas with deliberately distorted
   coordinates. Sampling a GPB image with it is wrong even if the SRV were
   bound.
4. **The legacy PSO selector only checks the atlas.**
   The legacy pass chooses `pipeline_state_tex` only when
   `dr->textured && tex_ready` (line 5312); there is no branch for a generic
   guest texture. The VP pass already uploads/samples generic textures through
   `vp_upload_tex_slot`, but it is gated on `is_vp`.
5. **The atlas upload is the only legacy upload.**
   `render_frame()` uploads the B8 atlas into R8 and writes its SRV at heap
   slot 0. Nothing uploads a generic texture for a no-VP draw, and the SRV
   heap is only made current when `tex_ready` is set. If a GPB image were the
   first textured draw, it would not even have a descriptor heap bound.

## 3. Patch: smallest generic legacy textured path

`patches/gt6-legal-gpb-draw-fix.patch` adds only the legacy/no-VP path; the
VP/FP path is untouched.

### 3.1 Record the binding

- New `D3D12DrawRecord.legacy_tex` flag.
- `legacy_generic_tex_format()` accepts `0x85` and `0x86..0x88` (RGBA8,
  DXT1/23/45). B8 (`0x81`) stays on the atlas PSO; G8B8 (`0x8B`) stays
  untextured because it is LBP's font atlas, not a colour image.
- `legacy_record_texture()` snapshots unit 0 (`off`, `raw`, `w`, `h`, `fmt`,
  `ctrl1`, `cube`, `mips`, address/filter/control/border) into `tex[0]` when a
  generic image is bound.
- Both legacy record builders call it: the QUADS fallback and the
  triangle/other fallback.

### 3.2 New PSO

`pipeline_state_tex_generic` reuses the existing textured VS (MVP from
`c0..c3` + UV) and adds a direct colour PS:

```hlsl
Texture2D tex : register(t0);
SamplerState smp : register(s0);
float4 main(PSIn i) : SV_TARGET { return tex.Sample(smp, i.uv) * i.col; }
```

No dbgfont UV scaling, no coverage reinterpretation. The vertex colour
(including alpha) modulates the sampled RGBA. Blend is straight alpha and
depth is off, matching a 2D UI overlay. The PSO is created next to the atlas
PSO and released in `rsx_d3d12_backend_shutdown`.

### 3.3 Upload and bind at draw time

`render_frame()` gets a second pre-pass loop after the VP texture loop:

```c
if (dr->is_vp || dr->is_clear || !dr->legacy_tex) continue;
ts = vp_upload_tex_slot(dr->tex[0].off, dr->tex[0].w, dr->tex[0].h,
                        dr->tex[0].fmt, 0, dr->tex[0].mips);
srv_write_ex(DRAW_SRV_BASE + d * 4, s_d3d.vp_tex[ts].res, sf,
             rsx_remap_to_d3d(dr->tex[0].ctrl1, bf), 0);
```

- It reuses the existing decoder/upload/cache (`vp_upload_tex_slot`), so DXT1
  block copy, RGBA8 conversion, swizzle and checksum caching are the same code
  the VP path already uses.
- Each draw gets its own 4-descriptor window at
  `DRAW_SRV_BASE + draw_index * 4`, so two legacy image draws cannot share a
  descriptor. The VP pass uses the same windows by draw index; a record is
  either VP or legacy, never both.
- The legacy pass makes the SRV heap current even when the atlas has not been
  uploaded yet, selects `pipeline_state_tex_generic`, and binds the record's
  window as t0. Atlas draws still bind slot 0 and use `pipeline_state_tex`.

### 3.4 Diagnostics

- New `[LEGACYTEX] op=<n> t0=0x<off> fmt=0x<fmt> <w>x<h> slot=<n> -> generic PSO`
  on the first successful uploads, or `upload FAILED -> untextured`.
- The existing `[DRAWDIAG]` "generic texture bound but no VP" line now says
  whether the legacy generic PSO will be used or the format is not sampleable.
- `RSX_CAP` manifests now show the binding because `tex[0].raw`/`off`/`fmt`
  are populated for legacy records.

### 3.5 Vertex-position caveat

`read_rsx_vertex()` has a dbgfont heuristic: positions outside NDC are folded
to their fractional part (`frac(x)*2-1`). That is correct for the biased
dbgfont quads and fatal for a normal 2D image position. The patch skips the
heuristic when a generic legacy texture is bound, so the guest position reaches
the PSO's MVP/vertex-constant transform unchanged. If the first GPB draw has
neither a VP nor an ortho `c0..c3`/viewport transform, its positions will clip;
the verification steps below require `c0..c3` or `viewport_scale` to be
non-zero, or a later draw with those set.

## 4. Verification

### 4.1 Apply and build

```powershell
git -C third_party/ps3recomp apply --check ..\..\patches\gt6-legal-gpb-draw-fix.patch
git -C third_party/ps3recomp apply ..\..\patches\gt6-legal-gpb-draw-fix.patch
powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
```

No build/run was performed for this report.

### 4.2 Run the real frame only

The diagnostic DDS overlay must stay off. Do **not** count an overlay frame.

```powershell
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$env:GT6_BRINGUP_DDS   = "0"          # explicit 0; unset re-enables the overlay
$env:RSX_CAP           = "1:16:1"     # 1 s windows can be missed by 1:4:60
$env:RSX_CAP_DIR       = "work/rsxcap_legal_gpb"
$env:RSX_VTXDBG        = "16"
$env:GT6_BOOTUI_TRACE  = "1"
$env:GT6_BOOT_TRACE    = "1"
$env:PS3_VERBOSE       = "1"
gt6\build\gt6.exe work\bin\EMAIN.elf 2> work\legal_gpb_run.err
```

### 4.3 Gate 1: `RSX_CAP` manifest has a real t0

```powershell
Select-String work\rsxcap_legal_gpb\frame_00\manifest.txt `
  -Pattern 't0=0x0*[1-9A-F]|t0 off='
```

Required: a `DRAW` op with `t0 != 0` and a `t0 off=... fmt=...` child line.
The first legal image should be one of:

```text
t0 off=0x........ fmt=0x86 (SZ) 864x128
t0 off=0x........ fmt=0x86 (SZ) 1440x720
t0 off=0x........ fmt=0x86 (SZ) 1920x1080
t0 off=0x........ fmt=0x85 (SZ) 460x80
```

`t0=0` on the plate draw means the bind was not captured; check
`[DRAWDIAG] tex0` and the `SET_TEXTURE_OFFSET`/format pair.

### 4.4 Gate 2: `[DRAWDIAG]` / `[LEGACYVTX]` / `[LEGACYTEX]`

```powershell
Select-String work\legal_gpb_run.err `
  -Pattern '\[LEGACYTEX\]|\[DRAWDIAG\]|\[LEGACYVTX\]'
```

Required:

- `[LEGACYTEX] op=... t0=0x... fmt=0x86 864x128 slot=... -> generic PSO`
  (or the notice/epilepsy/pdi size), not `upload FAILED`.
- `[DRAWDIAG] prim=... vp_ucode=0 ... target=0x... (display)` for the legacy
  path; a draw with `vp_ucode>=16` is the VP path and must be judged through
  its FP logs instead.
- `[DRAWDIAG] a3 en=1` with non-black constant/array colour, or
  `[LEGACYVTX] col=(...)` non-zero, and `uv=(...)` non-zero.
- `tex0=0x... fmt=0x86 ... bound=0 atlas=0` (the generic bind is intentionally
  not the B8 atlas flag).

### 4.5 Gate 3: frame check with the overlay off

```powershell
python tools\gt6_frame_check.py work\rsxcap_legal_gpb `
  --glob "frame_*/backbuffer.bmp" --min-nonblack 1.0 --min-colors 16
```

A PASS is only valid with `GT6_BRINGUP_DDS=0`. The first `scei` plate is
864x128 centred on a 1280x720 frame, so its screen coverage is only about
1.5-3.3 %; `--min-nonblack 1.0 --min-colors 16` is the gate for the first
legal frame. Reserve `--min-nonblack 5` for the full-screen `epilepsy` frame.
`first-draw-audit.md` §5.1-5.2 gives the same threshold caveat.

### 4.6 Negative controls

| Observation | Meaning |
|---|---|
| `[LEGACYTEX] ... upload FAILED` | Guest offset resolved to 0 or the texture is empty; check `TEXSRC`/`TEX_PROBE`. |
| `[DRAWDIAG] generic texture bound, no VP: format NOT sampleable...` | Format outside `0x85/0x86..0x88`; GPB expects `0xA6`/`0xA5`. |
| Manifest `t0=0` | Legacy record did not capture unit 0; check `SET_TEXTURE_OFFSET` ordering before `BEGIN_END`. |
| `vp_ucode>=16` | Draw took the VP path; this patch is inert for it. |
| `GT6_BRINGUP_DDS` non-zero | Overlay frame; not a legal-GPB result. |
| `t0` correct but nothing visible | Check `[LEGACYVTX]` positions/`c0..c3`/`viewport_scale`; the GPB draw may be clipped by the no-VP transform. |

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
