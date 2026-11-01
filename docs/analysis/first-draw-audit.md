# First 2D GPB draw audit — what PresentsRoot will submit and what the backend does with it

**Date:** 2026-10-31
**Baseline:** `08f92ec`
**Scope:** read-only audit of the boot/presents path, the two `RSX_CAP`
manifests, the D3D12 backend, and the lifted GT6 UI draw builders. No build, no
`gt6.exe` run, no game data/keys. The only file written is this one.
`docs/analysis/presents-gpb-notes.md` does not exist; the GPB facts below come
from `docs/analysis/boot-presents-check.md` §4 and
`docs/analysis/first-visible-ui-fix.md` §4.

## 0. Verdict

| Question | Answer |
|---|---|
| Is the current black frame a dropped GPB draw? | **No.** `work/rsxcap_opus/frame_00/manifest.txt` and `work/rsxcap_opus2/frame_00/manifest.txt` both contain exactly one draw: the 10-vertex immediate `DATA2F` black cover, expanded to `n=24`, `t0=0`, `fp=0`, `rt=0`. There is no GPB texture bind in either manifest. |
| Is the backend the current blocker? | **No.** The latest run (`work/real_run.err`, 19:47) opens `GT.VOL` but never reaches `main.adc`, `MenuClassDefine`, `K/LH`, `K/KG`, `K/IE`, or `K/WD`. The earlier cursor/MenuClassDefine runs are not the current state. The missing boot/presents load is upstream of every draw question here. |
| What will the first mapped 2D GPB draw look like? | **Expected (strong static evidence): a 2D textured image plate — `QUADS` (primitive 8), attr0 float32 positions + attr8 float32 UVs, guest VP+FP, DXT1 texture, display backbuffer.** `QUADS` is the strongest static-evidence case; a 4-vertex strip is the other plausible topology. A second GT6 sprite batcher uses attr0 size 4 and per-vertex attr3, so the plate's exact UV source is not settled. The PresentsRoot primitive/VP/FP/blend is **not proven** because no PresentsRoot RSX stream exists. |
| Which path decodes it? | **The VP path**, if the guest VP is present as the UI mode setter indicates: `upload_quads_vp` / `upload_strip_vp` → `is_vp=1` → VP pass → guest-FP PSO sampling the per-draw texture. The legacy textured PSO is only selected when `vp_ucode < 16`; that PSO is the dbgfont atlas PSO, not a generic GPB sampler. The dbgfont atlas path is never correct for a DXT1 GPB image. |
| Smallest missing backend feature | **Generic legacy textured PSO** — but only in the no-VP branch. Of the four candidates, texture upload (VP path), UV handling, and the no-VP viewport transform already exist; the only outright missing piece is a generic legacy textured PSO. The expected VP branch already has the pieces, so the first patch should be diagnostic, not the legacy PSO. |
| Would `draws:` / `RSX_CAP` see it? | **`draws:` counts the record; `RSX_CAP` writes the record and a BMP.** Neither alone proves pixels: the VP pass can skip all `is_vp` draws while `vp_ready=0`, and an untextured legacy quad can make a non-black frame without sampling the GPB image. Success requires a manifest `DRAW` with `t0 != 0`/`fmt=0xA6` **and** a non-black BMP that matches the expected DDS, with `GT6_BRINGUP_DDS=0`. |

## 1. Current evidence: only the cover exists

### 1.1 Draw ops and counts are identical, frame content is not

```text
work/rsxcap_opus/frame_00/manifest.txt
frame_count=1 draws=1 backbuffer=1280x720
op000 DRAW  rt=0x00000000 mrt=0x0/0x0/0x0 vp=0,0,1280x720 fp=0x00000000 vs=0 n=24 cmask=F blend=1 bk=0x0 t0=0x00000000 t1=0x00000000 t2=0x00000000 t3=0x00000000

work/rsxcap_opus2/frame_00/manifest.txt
frame_count=2 draws=1 backbuffer=1280x720
op000 DRAW  rt=0x00000000 mrt=0x0/0x0/0x0 vp=0,0,1280x720 fp=0x00000000 vs=0 n=24 cmask=F blend=1 bk=0x0 t0=0x00000000 t1=0x00000000 t2=0x00000000 t3=0x00000000
```

The BMPs are not identical:

| Capture | BMP SHA-256 | `gt6_frame_check` |
|---|---|---|
| `rsxcap_opus` (real, overlay off) | `54BBBB83347167D1056D2D9138B5CC7B57714B7C7EA5CE9844A30539EC5DEC9B` | FAIL: 0.00% non-black, 1 colour |
| `rsxcap_real` (real, overlay off) | `54BBBB…DEC9B` | FAIL: 0.00% non-black, 1 colour |
| `rsxcap_lwc` (real, overlay off) | `54BBBB…DEC9B` | FAIL: 0.00% non-black, 1 colour |
| `rsxcap_opus2` (diagnostic DDS overlay) | `5824C30A668980DFF2EDC55ACA34ACE09AD2AE8C9FF8D7920A87DBF37D210C9F` | PASS: 6.99% non-black, 239 colours |

This is the cleanest proof that the overlay is not a draw: **the DRAW op and
`draws=1` count are identical for a black frame and a non-black overlay frame**,
because
`bringup_present()` is a CPU decode + present-time copy, not an RSX draw
(`third_party/ps3recomp/libs/video/rsx_d3d12_backend.c:4575-4599`). A
`frame_check` PASS on `rsxcap_opus2` therefore says nothing about the game's
draw path.

### 1.2 The manifest fields do not mean what they look like

- `vp=0,0,1280x720` is the **viewport rect**, not vertex-program state.
- `vs=0` is the VP cache slot index. The immediate record is `memset` to zero
  and then sets `is_immediate=1`; `vs_idx` remains 0
  (`rsx_d3d12_backend.c:8403-8423`). A legacy record does not set `vs_idx`
  (`8143-8152`). So **`vs=0` is not evidence of “no VP”**.
- The manifest writer prints `is_clear` as `CLEAR` and everything else as
  `DRAW`, but it does **not** print `is_vp`, `is_immediate`, or `topology`
  (`1851-1871`). The manifest cannot distinguish the cover, a legacy draw, and
  a VP draw by itself. Only `[DRAWDIAG] vp_ucode=`, `[VP]`, and
  `[D3D12] draw_arrays` can.

### 1.3 The overlay is opt-in

`bringup_present()` returns when `GT6_BRINGUP_DDS` is unset, empty, or `0`.
Only a non-empty DDS path enables the diagnostic overlay. Real-frame
verification still sets `GT6_BRINGUP_DDS=0` explicitly as a defensive negative
control.

## 2. What the first mapped 2D GPB draw is

### 2.1 Asset and sequence

`boot.adc` `display_sequence_gt6` calls `presents_sequence_common`, which opens
`PresentsRootSCEA` and runs `common/JP/scei` (2 s) → `common/notice` (2 s) →
`scea/JP/epilepsy` (4 s). The first *mapped* PDIPFS-backed frame is the 30 s
`epilepsy` frame; the 15 s GT6/©/ESRB card is still unmapped and must not be
used as acceptance evidence (`boot-presents-check.md:360-384`).

`PresentsRootSCEA.gpb` embeds (from `boot-presents-check.md:346-352`):

| Pair | Texture | Size | RSX format | Backend base |
|---:|---|---:|---|---|
| 0 | `scei.dds` | 864×128 | `0xA6` DXT1 | `0x86` BC1 |
| 1 | `notice.dds` | 1440×720 | `0xA6` DXT1 | `0x86` BC1 |
| 2 | `pdi.dds` | 460×80 | `0xA5` 32bpp | `0x85` RGBA8 |
| 3 | `epilepsy.dds` | 1920×1080 | `0xA6` DXT1 | `0x86` BC1 |
| 4 | `loading_circle.dds` | 24×24 | `0xA6` DXT1 | `0x86` BC1 |

The legal sequence uses pairs 0, 1, and 3 (all DXT1). `pdi` is not part of the
`scea` table.

Some runs load `cursor.mproject`/`cursor.adc` and `CursorProject.gpb` before the
boot project. If a cursor image draws first, it is the same broad 2D textured
UI class and hits the same backend gates, but it is **not** the PresentsRoot
acceptance target and its texture/primitive is not audited here. Do not use a
cursor frame as evidence that the legal screen works.

### 2.2 Draw class: static evidence from GT6's UI batch builder

GT6's UI batch renderer provides a concrete shape for the engine's 2D draws.
The strongest example is `func_00B65C04`
(`gt6/generated/ppu_recomp_026.cpp:104054` onward), a glyph/sprite batcher that:

1. writes four-vertex quads into a guest vertex buffer (positions at
   `0x00/0x04/0x08/0x0C`, then `0x10…0x3C`; `104146-104166`);
2. sets attr0 = 2×float32, stride `0x10`, from that buffer
   (`105199-105204`), and attr8 = 2×float32, stride `0x10`, from the UV buffer
   (`105227-105233`);
3. calls the draw builder with **primitive 8 (`QUADS`), first 0, count
   `0x18` (24 vertices = 6 quads)** (`105188-105191`), and later
   `count=0x360` (216 quads) (`105281-105284`).

The draw builder is `func_00B74198` → `func_00B81C10`, which emits the hardware
methods:

```text
0x00041808  <primitive>              ; NV4097_SET_BEGIN_END
0x00041814  ((count-1)<<24) | first  ; NV4097_DRAW_ARRAYS
```

See `ppu_recomp_026.cpp:136624-136661` (`func_00B74198` calls
`func_00B81C10`), `ppu_recomp_027.cpp:22647-22700` (`0x1808`/`0x1814`
construction), and `rsx-first-draw-check.md:36-80` for the same path.

The UI mode setter `func_00B72D9C` loads a vertex-program descriptor via
`func_00B72A0C` (`ppu_recomp_026.cpp:135060-135090`), and
`func_00B72A0C` → `func_00B7F37C` → `func_00B822E0` writes the RSX
transform-program load method `0x1E9C`
(`ppu_recomp_027.cpp:23327-23345`). The same mode setter calls a paired
shader-program setter (`func_00B72904` → `func_00B72834`,
`ppu_recomp_026.cpp:134617-134687`). This is consistent with a **VP+FP pair**,
but the fragment-program address must be confirmed by `[DRAWDIAG] fp=`.

**Caveat:** `func_00B65C04` is a UI glyph/sprite batcher, not a traced
PresentsRoot plate renderer. The exact PresentsRoot call site is not in the
current logs. It demonstrates the engine's 2D draw format, not the specific
legal-image call.

### 2.3 Predicted first real draw

| Property | Strongest evidence | Confidence |
|---|---|---|
| Topology | `QUADS` (8), first 0, count multiple of 4; a 4-vertex strip (6) is the alternative | **Strong for the UI class; unproven for PresentsRoot** |
| attr0 | float32 ×2 (or ×4) positions, stride `0x10` (or `0x14`) | Strong |
| UV source | attr8 float32 ×2, stride `0x10`, in the text batcher; a second sprite batcher uses attr0 size 4 (possible UV in z/w) plus per-vertex attr3 | Unproven for the plate |
| attr3 | constant colour in the text path; the second sprite batcher uses a per-vertex short4 attr3 | Unproven for the plate |
| VP | guest vertex program loaded by the UI mode setter | Strong |
| FP | paired shader-program setter; exact `fp_addr` unknown | Likely, unproven |
| Texture | t0, DXT1 `0xA6`, 864×128 / 1440×720 / 1920×1080 | **Proven asset data; bind unit/order unproven** |
| Blend | guest blend state; the UI line path enables `0x302/0x303` and blend (`ppu_recomp_000.cpp:68974-68978`); plate factors unknown | Unproven |
| Target | display backbuffer `rt=0`, surface `0x660000`, 1280×720 | **Proven for the cover; expected for the plate** |

The plate is a 2D image, not a 3D mesh and not an immediate `DATA2F` block
(`boot-presents-check.md:390-399`). It should not be assumed to be the black
cover.

## 3. Which backend path will decode it

**Answer:** the **VP path** if `vp_ucode_bytes >= 16`; otherwise the **legacy
path**, where the only textured PSO is the dbgfont atlas PSO and a DXT1 GPB
texture is not sampled at all. The **dbgfont atlas path is never correct** for
`scei`/`notice`/`epilepsy`.

### 3.1 Expected: VP path

`d3d12_draw_arrays` routes `QUADS` to the VP path when all of
`vp_vb_mapped`, `vp_root_sig`, and `current_rsx_state->vp_ucode_bytes >= 16`
are true (`rsx_d3d12_backend.c:7932-7943`). It calls `upload_quads_vp`, which:

- fetches **all 16 attributes** for each of the four vertices
  (`7202-7228`, `read_vp_vertex` at `7007-7035`);
- expands the quad to two triangles (`7218-7220`);
- records `is_vp=1`, `fp_addr`, `vs_idx`, textures, blend key, target, and
  per-draw constants (`7944-8001`).

`render_frame` skips those records in the legacy pass (`5302`) and submits them
in the VP pass (`5339-5362`). For a draw with `fp_addr != 0`, the per-draw PSO
is built by `vp_get_fp_pso` from the guest fragment program
(`5563-5573`); the per-draw texture is uploaded by `vp_upload_tex_slot`
(`2989-3033`, `3229-3349`) and bound in the `DRAW_SRV_BASE + d*4` window
(`5668`).

**Expected result:** the draw is recorded and submitted, and the DXT1 image is
sampled, *provided* the guest FP decompiles and the texture bind is on unit 0–3.

### 3.2 If there is no guest VP: legacy path, but not a textured GPB

Without VP microcode, `QUADS` falls to `upload_quads_from_rsx` and records
`is_vp=0`, `textured = s_d3d.tex_bound` (`8005-8018`). The legacy PSO selection
is:

```c
target_pso = pipeline_state;                       /* untextured */
if (dr->is_immediate) ...
else if (dr->textured && tex_ready && pipeline_state_tex)
    target_pso = pipeline_state_tex;                /* atlas */
```

(`5308-5314`). But `s_d3d.tex_bound` is set **only for B8** (`0x81`) in
`d3d12_bind_texture` (`8565-8577`); every other supported format clears it.
A DXT1 `0xA6` bind therefore records `textured=0` and the draw uses the
**untextured** legacy PSO. It is submitted when `pipeline_ready` is true (the
legacy pass draws every `is_vp=0` record), but it cannot sample the GPB image.

The legacy textured PSO itself is the dbgfont atlas PSO: its PS scales UV by
`*10`/`*8 + 0.59` and uses `tex.Sample(...).r` as coverage
(`1228-1238`). It is not a generic texture sampler. If a stale B8 atlas is
bound, the GPB draw would use this path and produce glyph-like coverage, not
the image.

The legacy vertex reader also contains a dbgfont-specific position heuristic:
when `|x|` or `|y|` is outside NDC, it treats the fractional part as screen
coordinates and attr0.z/w as UV (`6778-6798`). A GPB plate whose positions are
window pixels would be mangled by that heuristic. Any generic legacy path must
gate it on “a generic texture is bound” and keep it for the atlas only.

### 3.3 dbgfont atlas path

This path is only for a single-channel B8 atlas. It is not selected for a
DXT1 GPB texture because `tex_bound` is cleared by the non-B8 bind. It is
never the correct path for `scei`/`notice`/`epilepsy`.

## 4. Missing backend features and the smallest patch

### 4.1 Candidate audit

| Candidate | Present? | Evidence / gap |
|---|---|---|
| Generic legacy textured PSO | **No** | The only legacy textured PSO is the dbgfont atlas PSO (`1228-1238`), with hardcoded atlas UV scaling and `.r` coverage. A generic PSO must sample `t0.rgba`, multiply by vertex colour, use the real UV, and honour the guest blend key. |
| Texture upload | **Yes, VP path only** | `vp_upload_tex_slot` handles BC1 and RGBA8 (`2989-3033`, `3229-3349`). The legacy pass has no generic upload/SRV bind; it only has the atlas path. Reuse the VP uploader rather than writing a new decoder. |
| UV handling | **Yes, with a caveat** | Legacy: `read_rsx_vertex` reads the first enabled 2+ component attr in 8..15, then attr2 (`6810-6831`); it does **not** treat attr0.z/w as UV. VP: `read_vp_vertex` fetches all 16 (`7027-7034`), so an attr0.zw shader works there. No fix unless `[LEGACYVTX]`/`[VTXPOS]` shows wrong values. |
| No-VP transform | **Yes, with a dbgfont caveat** | `read_rsx_vertex` applies the RSX viewport scale/offset when programmed (`6834-6850`), but its out-of-NDC fractional heuristic (`6778-6798`) must be disabled for a generic GPB plate. |
| Texture unit coverage | **Partial (t0–t3 only)** | `d3d12_bind_texture` records only `unit < 4` (`8499-8504`); GT6 has been observed issuing texture units 4–6 on subchannel 1 (`d3d12-draw-readiness-check.md:201-203`). If the plate binds on t4+, even the VP path records `tex0 bound=0`. Widen the record/slots only if `TEXFMTDBG`/`[DRAWDIAG]` proves it. |

**Smallest missing feature:** the **generic legacy textured PSO**, plus a way to
bind the generic texture to the legacy pass. This is only needed if the first
GPB draw has `vp_ucode < 16`.

**Expected branch:** the UI mode setter loads a VP, so the first GPB draw should
take the VP path. On that branch the backend is already feature-complete for
the draw; the remaining risk is the guest FP/PSO, not the legacy PSO.

### 4.2 Ranked minimal patch plan

1. **P0 — make the path visible (diagnostic, no rendering change).**
   Add `is_vp`, `is_immediate`, and `topology` to the manifest DRAW line
   (`1858-1863`). Optionally add `RSX_CAP_ON_TEX=1` to capture the first frame
   with `cur_texs[0].set` so a 2 s presents window is not missed by the
   `RSX_CAP=1:4:60` stride. This resolves the `vs=0` ambiguity and prevents
   wasted captures.

2. **P1a — generic legacy textured PSO (only if `[DRAWDIAG] vp_ucode=0`).**
   Add one PSO with:
   - the existing legacy VS (pos/colour/UV);
   - a PS `tex.Sample(s0, uv) * col` with the real UV (no `*10`/`*8` atlas
     scaling);
   - guest blend (enable + factors from `rsx_blend_key`, at minimum
     `SRC_ALPHA`/`INV_SRC_ALPHA` for the first plate);
   - depth off for the 2D plate.

   Add a `textured_generic` flag/record field at draw time (not a stale global),
   copy `cur_texs[0]` into the legacy record, and upload the texture to a
   legacy SRV slot. Reuse `vp_upload_tex_slot`; do not add a new DXT1 decoder.
   Gate the dbgfont fractional-position heuristic (`6778-6798`) off when a
   generic texture is bound. Do not modify `pipeline_state_tex` (atlas) — text
   still needs it.

3. **P1b — generic textured VP fallback (only if `[DRAWDIAG] vp_ucode>0` but
   `fp=0`, `[FP] decompile fail`, `[FP] PS compile FAIL`, or `[FP] PSO FAIL`).**
   The current VP fallback is the atlas PS when `tex_ready` is set
   (`5345-5348`), which samples `.r` and discards. Add a small
   `pipeline_state_vp_tex_generic` that uses the decompiled VS and a PS
   `tex.Sample(t0, uv) * col0` with guest blend. Select it when `dpso == NULL`
   and a generic texture is bound, instead of the atlas/colour fallback. This
   is smaller than a legacy PSO and directly serves the expected VP branch.

4. **P2 — only if the logs show a real defect.**
   Do not preemptively change `read_rsx_vertex` UV/viewport, `read_vp_vertex`,
   or `vp_upload_tex_slot`; they already implement the needed pieces. Verify
   with `[LEGACYVTX]` (pos/col/uv), `[DRAWDIAG]` (a0/a3/a8 enables, tex0),
   `RSX_VTXDBG=64`, `TEXFMTDBG=1`, and `VTX_DUMP=1` before touching them.
   If `[DRAWDIAG] tex0 bound=0` appears despite a `TEXFMT` line, widen the
   texture-unit recording from t0–t3 to the unit the plate actually uses; do
   not add a new sampler PSO for that symptom.

5. **Do not** add an offscreen-to-swapchain composite for the cover, a boot/
   presents shortcut, a forced `Prototypes.adc`, or a synthetic texture. The
   current blocker is the load path, not the renderer.

## 5. Counting and success criteria

### 5.1 `draws:` and `RSX_CAP`

- `s_dbg_last_draws = s_d3d.draw_count` is set at the end of `render_frame`
  (`5806`); the title bar prints it once per second (`6224-6227`). A GPB draw
  is counted if it was recorded, **even if the VP pass later skips it**. A
  one-frame draw can also be missed by the 1 s title update.
- `RSX_CAP` captures when `s_d3d.frame_count >= target && s_dbg_last_draws > 0`
  (`6191`) and writes `draws=<s_dbg_last_draws>` plus every record
  (`1839-1871`). It reads the backbuffer **after** `render_frame` (`1910-1912`).
  Therefore:
  - manifest lists the draw **whether or not** it was submitted;
  - BMP is black if `vp_ready=0` skipped the VP pass, even though the manifest
    has the record;
  - the current `RSX_CAP=1:4:60` samples frames 1/61/121/181 and can miss the
    2 s `scei`/`notice` windows. Use a texture-draw trigger or consecutive
    frames around the load.

### 5.2 Exact success criteria

Run with:

```powershell
$env:GT6_BRINGUP_DDS = "0"        # explicit negative control; overlay is opt-in
$env:GT6_BOOTUI_TRACE = "1"
$env:GT6_BOOT_TRACE = "1"
$env:PS3_VERBOSE = "1"
$env:PPU_STUCKMAX = "1000000"
$env:RSX_CAP = "1:16:1"           # or the new texture-draw trigger
$env:RSX_CAP_DIR = "work/rsxcap_firstdraw"
Remove-Item Env:PS3_HEADLESS,Env:GCM_GUEST_FB,Env:GT6_GUEST_FB_FORCE,Env:GCM_GUEST_FB_OVERWRITE -ErrorAction SilentlyContinue
```

Accept only when **all** of the following hold:

1. **Load:** the log shows `K/WD` / `projects/gt6/boot/US/PresentsRootSCEA.gpb`
   served, `MGOM.start s='boot'`, and `PresentsRoot.open`/`changeImage` (or the
   boot project entry). Without K/WD there is no GPB draw to audit.
   For the current build, `work/real_run.err` does **not** satisfy this.
2. **Texture bind:** `TEXFMTDBG=1` (or `[DRAWDIAG]`) shows a PresentsRoot
   texture bind: `fmt=0xA6` (DXT1) or `0xA5` (pdi), with dimensions
   `864×128`, `1440×720`, or `1920×1080`.
3. **Draw record:** the manifest contains a `DRAW` with `t0 != 0` and a
   following line `t0 off=0x... fmt=0xA6 (LN) ... 1920x1080 ...`; `fp != 0`;
   `rt=0`; `n` at least 4 (6/24 after quad expansion). `vs` may be 0; it is a
   cache slot, not a path flag.
4. **Path:** `[DRAWDIAG]` shows `vp_ucode>0`, `a8 en=1` (or the plate's actual
   UV attribute enabled), `tex0 ... bound=1 atlas=0`, and
   `target=... (display)`; `[VP] pipeline ready` / per-draw VS cached appears;
   and the guest FP either logs `[FP] guest FP pipeline ready (fp=0x...)` on
   first use or was already cached from an earlier draw. No
   `[FP] decompile fail`/`PS compile FAIL`/`PSO FAIL` for that draw. If
   `vp_ucode=0`, the new generic legacy PSO must be present and `[LEGACYVTX]`
   must show the correct pos/uv; otherwise a non-black quad is not the GPB
   image.
5. **Pixels:** `gt6_frame_check.py` PASS with `--min-nonblack 1.0
   --min-colors 16` (not 5 %), and the BMP visually/pixel-wise matches the
   expected `image_boot_common_*.dds`. `[BRINGUP]` must be absent and the
   manifest texture offset must match the GPB bind.
6. **Not the overlay / guest fb:** no `GT6_BRINGUP_DDS` file loaded, no
   `GCM_GUEST_FB` copy. The overlay frame has the **same single DRAW op and
   `draws=1`** as a black frame (`rsxcap_opus2` vs `rsxcap_opus`), so a manifest
   `draws=1` plus non-black BMP is explicitly not sufficient.

**Threshold caveat:** the verify script uses `--min-nonblack 5`
(`scripts/verify-real-frame.ps1:80`). A CPU DXT1 decode of the extracted
PresentsRoot textures gives approximately 12.5 % non-black for `scei`, 7.0 %
for `notice`, and 5.5 % for `epilepsy`. If `scei` is drawn at its native
864×128 size on a 1280×720 screen, the screen coverage is only ~1.5 %; scaled
to screen width it is ~3.3 %. A 5 % threshold can therefore reject a correct
first `scei` frame. Use 1 % for the first legal frame and reserve 5 % for the
full-screen `epilepsy` frame.

## 6. Claims not supported by the logs

| Claim | Verdict |
|---|---|
| “The black frame is a dropped GPB draw.” | **Unsupported.** The manifest is the immediate cover (`n=24`, `t0=0`, `fp=0`); the cover is guest-state black with duplicated corners (zero-area triangles), not a drop. |
| “`draws=1` / `frame_check PASS` proves a real draw.” | **False.** `rsxcap_opus2` has the same single DRAW op and `draws=1` as the black `rsxcap_opus`, but a different BMP from the overlay. The overlay adds no draw. |
| “`vs=0` in the manifest means no VP.” | **Unsupported.** `vs` is the VP cache slot; immediate/legacy records zero-init it. The manifest has no `is_vp`/`is_immediate` field. |
| “`vp=0,0,1280x720` means no vertex program.” | **False.** It is the viewport rect. |
| “The first GPB draw is definitely `QUADS`, no VP, one texture.” | **Overclaimed.** `QUADS`/attr0/attr8 is strong static evidence from the UI batcher; the exact PresentsRoot primitive/VP/FP/blend/unit is not traced. |
| “The GPB draw will use the dbgfont atlas path.” | **False for DXT1.** `tex_bound` is B8-only; the atlas PS is not a generic sampler. |
| “The current backend is the first blocker.” | **Unsupported.** The latest run never reaches `main.adc`/`K/WD`; the missing boot/presents load is upstream. |
| “The overlay is off by default.” | **Source agrees.** `GT6_BRINGUP_DDS` must name a DDS file to enable it; unset, empty, and `0` disable it. |
| “The 15 s GT6/©/ESRB frame is PresentsRoot.” | **Unsupported.** It predates `K/WD` and matches none of the five GPB textures; it remains unmapped (`boot-presents-check.md:365-384`). |
| “The self-test proves the first GPB draw.” | **False.** The D3D12 self-test bypasses the FIFO/guest state and sets `fp_addr=0`; it does not exercise the guest FP+texture path (`d3d12-draw-readiness-check.md:308-330`). |

## 7. Evidence index

| Evidence | Location |
|---|---|
| Current capture manifests (cover only) | `work/rsxcap_opus/frame_00/manifest.txt`, `work/rsxcap_opus2/frame_00/manifest.txt` |
| Black vs overlay BMP hashes | `54BBBB…DEC9B` (opus/real/lwc) vs `5824C3…10C9F` (opus2) |
| `frame_check` output | 0.00 % / 1 colour for black; 6.99 % / 239 colours for overlay |
| GPB texture table | `docs/analysis/boot-presents-check.md:346-352`; `first-visible-ui-fix.md:268-272` |
| PresentsRoot sequence | `boot-presents-check.md:110-122`; `first-visible-ui-fix.md:90-97` |
| 2D UI draw builder (`QUADS`, attr0/attr8) | `gt6/generated/ppu_recomp_026.cpp:104054,104146-104166,105188-105237,105281-105284` |
| `DRAW_ARRAYS` emission (`0x1808`/`0x1814`) | `gt6/generated/ppu_recomp_027.cpp:22647-22700` |
| UI mode setter loads transform program | `gt6/generated/ppu_recomp_026.cpp:135060-135090`; `ppu_recomp_027.cpp:23327-23345` |
| QUADS VP preference | `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c:7932-8004` |
| VP pass / guest FP PSO | `rsx_d3d12_backend.c:5339-5362,5563-5573` |
| Legacy PSO selection / atlas PS | `rsx_d3d12_backend.c:5308-5314,1228-1238` |
| Legacy quad record (`textured=tex_bound`) | `rsx_d3d12_backend.c:8005-8018` |
| Texture bind whitelist / B8 `tex_bound` | `rsx_d3d12_backend.c:8496-8564,8565-8577` |
| VP texture upload (BC1/RGBA8) | `rsx_d3d12_backend.c:2989-3033,3229-3349` |
| Attribute fetch / legacy UV / viewport | `rsx_d3d12_backend.c:6749-6851,7007-7035,7202-7231` |
| Manifest writer / immediate record | `rsx_d3d12_backend.c:1839-1871,8403-8423` |
| `draws:` / `RSX_CAP` gate | `rsx_d3d12_backend.c:5806,6177-6195,6224-6227` |
| Overlay default / off switch | `rsx_d3d12_backend.c:4575-4599`; `scripts/verify-real-frame.ps1:44-52,80` |
| Cover is the immediate DATA2F strip | `work/real_run.err:29291,50817` (`[RSX] IMMEDIATE prim=6 count=10`); `d3d12-draw-readiness.md` §“GT6's actual first block” |
| Current run reaches only GT.VOL | `work/real_run.err:93,131`; no `main.adc`/`K/WD` matches |
| Latest handoff / overlay result | `docs/analysis/boot-presents-fix.md:740-776` |

## 8. Note on concurrent, uncommitted work

During this audit an untracked `patches/gt6-legal-gpb-draw-fix.patch`
(20,685 B, 20:17) appeared. It implements the P1a generic legacy textured PSO,
reuses `vp_upload_tex_slot` into per-draw SRV windows, and gates the dbgfont
fractional-position heuristic. It is **not** part of `08f92ec`, was not built
or run here, and is not evidence for any claim above. If it compiles and the
first GPB draw is no-VP, it addresses exactly the missing feature identified in
§4; if the draw is VP, it does not address the guest-FP branch and the VP
texture/FP path still needs the `[DRAWDIAG]`/`[FP]` gate.
