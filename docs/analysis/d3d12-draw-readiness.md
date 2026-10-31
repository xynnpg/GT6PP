# D3D12 draw readiness — audit and self-test

Scope: `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`, its
`rsx_backend` callbacks, and the public immediate-vertex entry point. The
upstream FIFO / `cellGcmSys` / `rsx_draw_engine` submission path is out of scope
here and is owned by the other fixer.

## Verdict

**The D3D12 half is ready, and the first real draw is now confirmed in the
windowed build.** A validated `rsx_process_method(NV4097_DRAW_ARRAYS)` reaches
`d3d12_draw_arrays`, records a draw, and `render_frame()` replays it through a
real D3D12 device. The in-backend self-test draws a known triangle through the
same callback interface with no FIFO, no guest memory, and no title: on the
reference machine (AMD Radeon RX 6650 XT, 1280×720) the fixed-function and
vertex-program subtests returned **PASS** with `clear=1024/1024`,
`white=1024/1024` in the sampled tiles.

GT6's first draw is an immediate-mode `DATA2F` block. The RSX fixer now
accumulates those vertices, materializes them into the reserved scratch buffer
`0x0FF00000`, and calls `draw_arrays(prim=6, first=0, count=10)`. The backend
recognizes that scratch and routes it through the immediate path. **The black
window for this block is correct guest state**, not a dropped draw:

- `set_render_target(1440x1080)` logs the surface **clip** dimensions. `surf0`
  is `0x660000`, a registered display buffer, and `cellGcmOffsetIsDisplay` is
  true (`display=1`), so the draw targets the **backbuffer**, not an offscreen
  1440x1080 surface.
- The vertex colours come from constant attr3 `(0,0,0,1)` and there is no
  texture/UV; the ten vertices are a full-screen **black cover**.
- The ten vertices repeat each corner: under standard triangle-strip assembly
  every triangle is zero-area, so even a correct backend cannot cover pixels
  from that exact sequence.

Do **not** add an offscreen-to-swapchain composite for this draw. Focus on the
later visible draws: non-black attr3, attr8 texcoords, texture binds, and VP
constants/transform. The fixed-function backend path now reads colour and UV
from the attribute state (falling back to the constant registers), and applies
the RSX viewport transform when no VP is used. New `[DRAWDIAG]` and
`[LEGACYVTX]` lines report exactly what each later draw supplies.

> Verification status: the legacy/VP PASS above is from the previous build.
> The immediate entry point, the scratch routing, the legacy colour/UV/viewport
> changes, and the `[SELFTEST] immediate` shot were added after that run and
> were **not** rebuilt/executed in this revision (the task prohibited
> build/run). The self-test performs the same backbuffer readback and reports
> its own PASS/FAIL; expect a third `[SELFTEST] immediate` line.

## Callback audit

| Callback | Implementation | Effect on a minimal draw |
|---|---|---|
| `init` | logging wrapper; real work in `rsx_d3d12_backend_init` | not a blocker |
| `shutdown` | logging wrapper; real work in `rsx_d3d12_backend_shutdown` | not a blocker |
| `begin_frame` / `end_frame` | no-ops | not a blocker; all work is deferred to `render_frame()` |
| `present` | `d3d12_present` | **gate**: only calls `render_frame()` when the batch is empty or contains a non-clear draw with `rt_off == 0` (display target). An offscreen-only batch is not replayed by this callback. The explicit `rsx_d3d12_backend_present()` does replay offscreen batches but only presents when display content exists. |
| `clear` | `d3d12_clear` | display clears only set `s_d3d.clear_color` (and are not recorded); offscreen/depth clears are recorded as ordered ops. A display clear with no display draws returns and keeps the batch accumulating. |
| `set_render_target` | `d3d12_set_render_target` | stores `current_rsx_state` and logs; does not create or bind anything. Targets are resolved per draw by `current_rt_off()` and created on demand by `off_rt_get()` / `off_ds_get()` in `render_frame()`. Not a stub in effect, but the callback itself does no D3D12 work. |
| `set_viewport` | `d3d12_set_viewport` | **STUB (no-op)**. VP draws use `state->viewport_x/y/w/h` applied in the VP pass; the fixed-function path applies `viewport_scale/offset` in `read_rsx_vertex()`. `state->scissor_*` is never read at all; the VP pass uses the viewport rect as the scissor. Fine for full-target draws; wrong for guest scissor/sub-rect state. |
| `set_blend` | `d3d12_set_blend` | logging only. Blend enable/factors are captured per draw (`rsx_blend_key`) and become a PSO key only for guest-FP PSOs. The `fp_addr == 0` fallback PSO ignores guest blend. |
| `set_depth_stencil` | `d3d12_set_depth_stencil` | logging only. `rsx_zs_key` is captured per draw and used by `vp_get_fp_pso()`. Fallback PSOs use fixed depth state. |
| `set_color_mask` | **not registered** (`NULL` in `s_d3d12_backend`) | `rsx_commands.c` guards the call, so this is skipped. The draw record captures `state->color_mask` and passes it to the guest-FP PSO key. |
| `set_alpha_test` | **not registered** (`NULL`) | same: draw record captures `alpha_test_enable/func/ref`; the guest-FP HLSL and the fallback colour PS may not honour it if the FP path is absent. |
| `set_shader` | `d3d12_set_shader` | logging only, with a TODO. The actual FP address is captured at draw time (`dr->fp_addr`), and PSO lookup/compile happens in `vp_get_fp_pso()`. Not a drop. |
| `set_vertex_attribs` | `d3d12_set_vertex_attribs` | logging only; vertex data is fetched at draw/upload time from `current_rsx_state`. Not a drop. |
| `draw_arrays` | `d3d12_draw_arrays` | fully implemented; records legacy or VP draws for replay. Recognizes the accumulator's `0x0FF00000` immediate scratch and routes it to the immediate path. Legacy records now read attr3 colour, attr8..15/attr2 UV, and apply the guest viewport transform. Gates below. |
| `rsx_d3d12_backend_draw_immediate` | `rsx_d3d12_backend_draw_immediate` (public backend entry, not a vtable slot) | accepts a temporary window-space vertex array for constant-attribute/immediate blocks; expands to a triangle list and records `is_immediate`. Does not consult attribute arrays or `current_rsx_state`. |
| `draw_indexed` | `d3d12_draw_indexed` | VP path only. It returns early if `!pipeline_ready`, bad count, or `!vp_vb_mapped || !vp_root_sig`. Non-indexed fallback state (no VP) cannot be drawn indexed. |
| `bind_texture` | `d3d12_bind_texture` | implemented. Only a whitelist of RSX formats is accepted (`0x81, 0x85, 0x8B, 0x86..0x88, 0x9A`); an unsupported format does not clear `cur_texs[unit].set`, so the draw can inherit a stale texture. `tex_bound` (legacy atlas path) is only set for B8. |

## Immediate / constant-attribute draws (GT6 DATA2F)

GT6's first block has no vertex-attribute array and no native `DRAW_ARRAYS`;
it is `SET_BEGIN_END(6)`, ten `SET_VERTEX_DATA2F_M` ATTR0 writes,
`SET_BEGIN_END(0)`. The FIFO accumulator synthesizes a `draw_arrays` call from
those vertices; the backend recognizes the accumulator's scratch array and
routes it through the immediate path. There is also an explicit public entry
point for accumulators that can carry more than attr0.

### API

```c
typedef struct rsx_d3d12_immediate_vertex {
    float x, y;   /* RSX window-space pixels, origin top-left */
    float z;      /* D3D clip depth 0..1 (pass 0 for DATA2F/DATA2S) */
    u32   argb;   /* RSX-packed 0xAARRGGBB; 0 = opaque white */
} rsx_d3d12_immediate_vertex;

u32 rsx_d3d12_backend_draw_immediate(u32 primitive,
                                     const rsx_d3d12_immediate_vertex* verts,
                                     u32 count);
```

- `x`/`y` are in target pixels. The backend maps
  `x in [0, width]` and `y in [0, height]` to D3D clip space with the current
  backbuffer dimensions. GT6's `0 / 1280 / 720` values are already in this
  space.
- `z` is passed through as clip depth. The immediate PSO disables depth test
  and write, so `0` is sufficient.
- `argb` is RSX-packed. For the public entry point, `0` means opaque white;
  callers with a constant colour can fill it in. The scratch path from
  `rsx_commands.c` uses constant attr3 by default (so GT6's black cover stays
  black), forces white with `RSX_IMMEDIATE_WHITE=1`, and accepts an override
  with `RSX_IMMEDIATE_COLOR=AARRGGBB`.
- Supported primitives: `TRIANGLES`, `TRIANGLE_STRIP`, `TRIANGLE_FAN`,
  `QUADS`, `QUAD_STRIP`. All are expanded to a D3D triangle list;
  `TRIANGLE_STRIP` alternates the first two indices to keep winding.
- Returns the number of host triangle-list vertices recorded (24 for a
  ten-vertex strip), or 0 if the draw could not be recorded.
- Targets the display backbuffer (`rt_off = 0`). Call it on the FIFO drain
  thread, once per completed `BEGIN/END` block. The scratch path always
  composes on the backbuffer; if the guest surface is offscreen it is logged
  but not used for the 2D immediate block.

The entry point is a public function in `rsx_d3d12_backend.h`, not a new
`rsx_backend` vtable slot: `rsx_commands.h` is outside this change's editable
set. The FIFO fixer should include the backend header and call
`rsx_d3d12_backend_draw_immediate()` directly. If a vtable slot is wanted later,
add it in `rsx_commands.h` and forward to this function; the backend side needs
no change.

### FIFO integration contract (owned by the `rsx_commands.c` fixer)

The current accumulator in `rsx_commands.c` materializes the immediate
vertices into a reserved 64 KiB local-memory scratch at `0x0FF00000`
(big-endian float4, stride 16), temporarily enables attr0 pointing there, and
calls the normal `draw_arrays(prim, first=0, count)`. The backend recognizes
that range (`RSX_D3D12_IMMEDIATE_SCRATCH`) and routes the call through the
immediate path, so the existing accumulator works without a new vtable slot.

The cleaner interface, when the accumulator can carry more than attr0, is the
public function:

```c
/* BEGIN/END accumulation, in the rsx_process_method method switch. */
on SET_BEGIN_END(prim != 0):
    imm_n = 0; imm_prim = prim;

/* On the write that completes one current vertex: */
/* DATA2F Y 0x1884, DATA3F Z 0x1508, DATA1F X 0x1E40,
 * DATA2S 0x1900, DATA4UB 0x1940, DATA4S/SCALED4S second word. */
    imm[imm_n].x = vertex_data4f[0][0];   /* current ATTR0 */
    imm[imm_n].y = vertex_data4f[0][1];
    imm[imm_n].z = 0.0f;                  /* DATA2F folds (x,y,0,1) */
    imm[imm_n].argb = 0;                  /* public API: 0 = opaque white;
                                           * the scratch path uses const attr3 */
    imm_n++;

on SET_BEGIN_END(0):
    if (imm_n >= 3)
        rsx_d3d12_backend_draw_immediate(imm_prim, imm, imm_n);
```

The array is copied synchronously into the per-frame host vertex buffer; the
caller may reuse or destroy it immediately. For the public call the backend does
not touch guest memory, `state->vertex_attribs`, textures, or MVP constants. The
record is replayed by the legacy pass with `pipeline_state_immediate` (a
passthrough VS), so it cannot be transformed by guest `vertex_constants`.

Limits of the current scratch path: it snapshots only attr0, uses the constant
attr3 colour for every vertex, and carries no UV. That is sufficient for the
black cover. If a later immediate strip needs per-vertex colour or texcoords,
extend the accumulator to carry them (or call the public API with a per-vertex
`argb`); the backend’s per-vertex colour conversion is already in
`immediate_vertex_convert()`.

### GT6's actual first block (black cover)

The measured sequence is:

```
BEGIN_END(6)                                  ; TRIANGLE_STRIP
DATA2F (0,0) (0,0) (1280,0) (1280,0)
        (1280,720) (1280,720) (0,720) (0,720)
        (0,0) (0,0)
END
```

`GCM_DRAWPROBE` confirms attr0 positions only; constant attr3 is
`(0,0,0,1)`, there is no texture/UV, and VP constants c0..c3 are zero. The
surface log is `surf0=0x660000`, a registered display buffer, so
`cellGcmOffsetIsDisplay` is true and the draw targets the **backbuffer**;
`set_render_target(1440x1080)` only reports the surface clip dimensions. This
is a full-screen **black cover** by guest state, and the duplicated corners
make every strip triangle zero-area anyway. The window is expected to remain
black after this block; it is not evidence of a backend drop.

The entry point accepts these ten vertices and expands them to eight strip
triangles. The self-test uses a **non-degenerate ten-vertex full-screen zigzag**
(same vertex count) so its readback PASS proves rasterization rather than
degenerate geometry.

## Black-frame evidence and later-draw handoff

Windowed-build evidence (`work/gt6.log`):

```
[D3D12] set_render_target(1440x1080) off0=0x660000 ... display=1 -> rt=0
[D3D12] draw_arrays #0 prim=6 first=0 count=10
[RSX] IMMEDIATE prim=6 count=10 (DATA2F triangle strip)
[takeflip] 1 (present)
```

The 1440x1080 number is the clip rectangle, not an offscreen target. The
registered display buffer is `0x660000`, `display=1`; the draw is display work.
The constant attr3 is black, no texture/UV is bound, and the corners repeat.
The black frame is therefore **expected guest output** for this block. There is
no offscreen-to-swapchain composite to add for it, and none was added.

What was changed for the draws that follow:

- **Scratch routing:** `d3d12_draw_arrays` recognizes the accumulator's scratch
  range `0x0FF00000..+64 KiB` (f32x4 stride 16, first=0). It reads the vertices
  with the same `cellGcmResolveOffset` the writer used, converts window pixels
  to NDC, and submits an `is_immediate` record. The normal VP/array paths are
  unchanged; the check is inert for every other draw.
- **Immediate colour:** the scratch path uses constant attr3 (black for the
  cover). `RSX_IMMEDIATE_WHITE=1` forces white, `RSX_IMMEDIATE_COLOR=AARRGGBB`
  overrides. This makes the first cover black and lets later strips use their
  constant colour.
- **Fixed-function colour:** `read_rsx_vertex()` now uses
  `rsx_fetch_attrib(state, 3, ...)`, so enabled attr3 arrays of any RSX type are
  read, and a disabled array falls back to the current constant register instead
  of hardcoded white.
- **Fixed-function texcoords:** it reads the first enabled 2+ component attribute
  in attr8..15 (then attr2) into the host UV, instead of leaving UV at zero.
- **Fixed-function viewport:** when `viewport_scale[0/1]` is programmed, the
  legacy path applies `window = ndc * scale + offset` and maps the resulting
  window pixels back to D3D clip space for the full backbuffer. A zero scale
  keeps the old clip-space passthrough. This makes later no-VP UI draw at the
  guest viewport instead of always at full-target NDC.
- **Diagnostics:** `[DRAWDIAG]` prints primitive, target, attr0/3/8 enable and
  constant values, texture0, viewport scale/offset and c0..c3.
  `[LEGACYVTX]` prints the first three converted positions/colours/UVs.
  `[IMMEDIATE]` prints the ten scratch vertices, target (display vs offscreen),
  constant colour/UV, FP address and the colour source. `[PRESENT]` prints the
  display/offscreen decision and final present flag.
- **Guest-framebuffer copy:** `guest_fb_present()` is skipped on frames that
  produced D3D12 draws unless `GCM_GUEST_FB_OVERWRITE=1`, so the forced
  `GCM_GUEST_FB` boot fallback cannot overwrite a later visible D3D12 frame.

When the next visible draw appears, the first checks are:

1. `[DRAWDIAG]` shows `a3 en=1` (or a non-black constant attr3) and a non-zero
   texture0 / attr8 enable. `tex0 ... bound=1 atlas=0` with `vp_ucode=0` means
   a generic texture is bound but the no-VP legacy path can only sample the
   dbgfont atlas; that draw needs the VP/FP path (or a future generic legacy
   textured PSO). The backend prints
   `[DRAWDIAG] generic texture bound but no VP` for that case.
2. `[LEGACYVTX]` shows the expected colour/UV, or `vp_ucode>0` routes the draw
   through the VP path.
3. `[DRAWDIAG]` c0..c3 match the guest MVP (zero c0..c3 means the guest itself
   has not set a transform).
4. `[PRESENT]` says `display=1`; no offscreen resolve is needed.

## Minimal-draw walkthrough and gates

For `NV4097_DRAW_ARRAYS` to produce pixels:

1. **`SET_BEGIN_END(prim)` must have run.** It sets `state->primitive_type`,
   increments `begin_epoch`, and flushes dirty state to the `rsx_backend`
   callbacks. Without it, `current_rsx_state` can be stale/NULL and the draw
   silently degenerates (all fetched vertices are zero) or is skipped.
2. `d3d12_draw_arrays` requires `s_d3d.pipeline_ready` and `s_d3d.vb_mapped`.
   Both are created in `init_d3d12`; failures are logged there. With either
   false the callback returns before recording anything.
3. Vertex attribute 0 must be enabled (`size != 0`). Every upload path checks
   `state->vertex_attribs[0].enabled` and returns 0 otherwise. The exception is
   the accumulator's temporary scratch array, which the backend detects by
   range and routes through the immediate path.
4. **TRIANGLES** with `vp_ucode_bytes >= 16`, `vp_vb_mapped`, `vp_root_sig`:
   `upload_tris_vp()` converts all 16 RSX attributes (type-aware, from guest
   memory via `rsx_vertex_fetch.c`) into 16 float4 slots and records
   `is_vp = 1`. Without VP microcode, TRIANGLES fall to the legacy
   `upload_vertices_from_rsx()` path (`is_vp = 0`): attrib0 must be float32,
   colour comes from attr3 or the constant register, UV from the first enabled
   attr8..15 (then attr2), and the guest viewport transform is applied when
   `viewport_scale` is programmed. Without `vertex_constants[0..3]` the MVP is
   the identity.
5. **QUADS** use the VP path only when the guest actually has a vertex
   program (`vp_ucode_bytes >= 16`) and VP resources. Without one they fall to
   the legacy expansion, which carries colour/UV and the viewport transform.
   (Previously they always preferred the VP path and were dropped while
   `vp_ready` was 0.)
6. **STRIP/FAN** with a VP are expanded to triangle lists by
   `upload_strip_vp()`. Without a VP, a FAN falls through to the legacy path
   with topology `TRIANGLES` and is **not** expanded: only the first triangle
   of the fan is meaningful.
7. **Legacy records always set `rt_off = 0`.** They render to the backbuffer
   even if the current surface is an offscreen target. VP records capture
   `current_rt_off()` and can render to the offscreen pool.
8. `render_frame()` is called by `present` / the display-clear boundary. It:
   waits for the GPU, transitions the backbuffer to RENDER_TARGET, clears,
   runs the legacy pass (`is_vp == 0`), then the VP pass (`is_vp == 1`).
9. **VP pass gate:** `s_d3d.vp_ready` must be 1 and at least one record must be
   `is_vp`. `vp_ready` is set only when `compile_vp()` succeeds. `compile_vp()`
   is called from `vp_get_vs()` at record time (only after the decompiler
   returns instructions) or from `render_frame()` if the live state still has
   microcode. If the guest VP fails to decompile/compile, `vp_ready` stays 0
   and **every** VP record is skipped. Logs: `[VP] decompile failed`,
   `[VP] VS compile FAIL`, `[VP] PSO creation FAIL`.
10. **Per-draw PSO:** `vp_get_fp_pso()` compiles the guest FP and creates a
    PSO keyed by FP code hash, VS, blend, RT count/format, control bits,
    colour mask, cull and depth/stencil. Failure returns NULL; the draw then
    uses the fallback `vpso`. If `tex_ready` is set at that point, `vpso` is
    the **atlas** PS, which samples t0 and discards where coverage <= 0.5.
    With a null/zero SRV every fragment is discarded: the draw is submitted
    but invisible. For untextured minimal draws the fallback must be the
    colour PS (`pipeline_state_vp_color`).
11. **Constant upload:** `vp_record_cb()` snapshots `vertex_constants`, the
    viewport z epilogue and FP constants per draw. It returns early if
    `vp_cb_mapped` is NULL; all constants then read zero and geometry
    degenerates. `init_d3d12` allocates this buffer but does not print a
    failure if `CreateCommittedResource` fails.
12. **Textures:** `bind_texture()` records only supported formats. Per-draw
    uploads happen in `render_frame()` via `vp_upload_tex_slot()`; unsupported
    formats get a null SRV. A guest FP that samples one outputs zero/black,
    not a dropped draw.
13. **Present:** the callback `d3d12_present` only replays when a display draw
    (`rt_off == 0`) is present. A title that renders entirely offscreen and
    composites through `rsx_d3d12_composite_from_offscreen()` or
    `RT_DISPLAY_BY_SIZE` needs those paths; otherwise the backend executes
    nothing and the window shows the backbuffer clear.

## What the self-test proves

New public entry point:

```c
int rsx_d3d12_backend_selftest(void);   /* 0 = pass, 1 = fail, -1 = skipped */
```

Automatic run at startup:

```powershell
$env:RSX_D3D12_SELFTEST = "1"
$env:RSX_D3D12_SELFTEST_VP = "0"   # optional: skip the VP half
gt6.exe
```

It builds a synthetic `rsx_state` with attrib 0 enabled float32×4 and calls the
registered `rsx_backend` callbacks in order:

```
clear(0xF0, red) -> set_render_target -> set_vertex_attribs -> set_shader
                 -> draw_arrays(TRIANGLES, 0, 3) -> present(0)
```

`present` is the real callback; it replays the recorded batch through
`render_frame()`, exactly as it does for a guest frame.

`read_rsx_vertex()` / `read_vp_vertex()` return a fixed clip-space triangle only
while `s_selftest_active` is set, so no `vm_base` and no FIFO are involved. The
frame is copied into a readback buffer (top-left 32×32 and centre 32×32) and
checked numerically: top-left must remain the red clear, the centre must be
white. The VP subtest additionally loads a hand-assembled two-instruction NV40
program (`rsx_test_programs.h`: `MOV o0, v0; MOV o1, v1; END`), runs it through
`rsx_vp_decompiler` → `D3DCompile` → `CreateGraphicsPipelineState`, draws, and
then releases the test pipelines so the title's first real VP compiles fresh.

The **immediate subtest** calls `rsx_d3d12_backend_draw_immediate()` with a
ten-vertex full-screen `TRIANGLE_STRIP` in window pixels, no attribute array.
It deliberately sets a hostile MVP in the synthetic state (x/y scale 2,
translate +4); the passthrough immediate PSO must ignore it. If the immediate
PSO is missing and the basic MVP PSO is used instead, the strip is pushed
off-screen and the shot fails. It requires 24 emitted vertices and white
coverage in both the top-left and centre tiles.

Previously observed result (host harness, AMD RX 6650 XT; the immediate shot
did not exist in that build):

```
[SELFTEST] start: 1280x720 pipeline_ready=1 vp_resources=1 imm_pso=1
[SELFTEST] legacy   recorded=1 verts=0  ... clear=... -> PASS
[SELFTEST] vp       recorded=1 verts=0  ... clear=... -> PASS
[SELFTEST] vp       cleanup: vp_ready=0
[SELFTEST] RESULT: PASS
```

After rebuilding with the immediate entry point, expect:

```
[SELFTEST] legacy    recorded=1 verts=0  ... -> PASS
[SELFTEST] immediate recorded=1 verts=24 readback=1 ... tlwhite=1024/1024 ... -> PASS
[SELFTEST] vp        recorded=1 verts=0  ... -> PASS
[SELFTEST] vp        cleanup: vp_ready=0
[SELFTEST] RESULT: PASS
```

This revision was not built/run (per task instruction), so the immediate line is
expected, not yet observed.

Run it outside gt6 with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/patches/run_rsx_d3d12_selftest.ps1
```

## Remaining blockers / correctness gaps (backend side)

These do not stop the self-test, but they are the pieces to check when a real
guest draw still produces nothing:

1. `d3d12_set_viewport` is a no-op; the VP pass applies the guest viewport
   rect per draw and the fixed-function path now applies the RSX viewport
   transform, but `state->scissor_*` is still unused. Guest scissor/sub-rect
   scissoring will overdraw.
2. `set_color_mask` / `set_alpha_test` are not registered. The state is
   captured per draw, but the fallback (non-guest-FP) pipelines ignore it.
3. A guest-FP compile failure is non-fatal but can be visually fatal: the
   atlas PS fallback discards fragments when `tex_ready` is set and the draw's
   texture is absent/zero.
4. `vp_get_vs()` returns before calling `compile_vp()` if the per-draw
   decompile fails, so `vp_ready` can remain 0 and every `is_vp` record is
   dropped. The only diagnostic is the per-draw VS failure log.
5. Legacy (`is_vp == 0`) records still force `rt_off = 0` (display), do not
   expand triangle fans, and have no indexed path. Colour (attr3/constant), UV
   (attr8..15/attr2) and the guest viewport transform are now implemented.
   A non-B8 texture bound on a no-VP draw is still not sampled: the legacy
   textured PSO is the dbgfont atlas path; generic textures require the VP/FP
   path.
6. `bind_texture` leaves stale per-unit state for unsupported formats.
7. `d3d12_present` does not replay offscreen-only batches; the explicit
   `rsx_d3d12_backend_present()` does, but only presents when display content
   is detected. This does not affect GT6's first cover (`display=1`).
8. `vp_cb_mapped` allocation failure is silent (only the size line prints).
9. `d3d12_draw_arrays` still requires attribute 0 for normal draws. The
   accumulator's reserved scratch range `0x0FF00000..+64 KiB` is detected and
   routed through the immediate path; the scratch carries only attr0, so the
   constant attr3 colour is used. The public
   `rsx_d3d12_backend_draw_immediate()` API carries per-vertex colour but no
   UV; a textured immediate strip would require an extended vertex struct and
   sampling PSO.

## Files

- `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`
  - `rsx_d3d12_backend_draw_immediate`, `immediate_vertex_convert`,
    `immediate_pack_argb`
  - `draw_uses_immediate_scratch` / `draw_immediate_scratch` (routes the
    accumulator's `0x0FF00000` scratch through the immediate path)
  - `pipeline_state_immediate` creation and selection for `is_immediate`
  - `read_rsx_vertex` colour/UV fetch + RSX viewport transform
  - `d3d12_set_render_target` / `d3d12_draw_arrays` diagnostics
  - `rsx_d3d12_backend_selftest`, `selftest_shot`, `selftest_setup_state`,
    `selftest_release_vp`, `selftest_analyze_pixels`
  - hooks in `read_rsx_vertex` / `read_vp_vertex`
  - readback branch in `render_frame`; guest-FB overwrite guard
  - startup trigger in `rsx_d3d12_backend_init`
- `third_party/ps3recomp/libs/video/rsx_d3d12_backend.h` — immediate-vertex
  struct/entry point, scratch range, selftest declaration
- `tools/patches/rsx_d3d12_selftest_host.c` — host harness
- `tools/patches/run_rsx_d3d12_selftest.ps1` — build/run script
