# D3D12 draw readiness — audit and self-test

Scope: `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c` and its
`rsx_backend` callbacks. The upstream FIFO / `cellGcmSys` / `rsx_draw_engine`
submission path is out of scope here and is owned by the other fixer.

## Verdict

**The D3D12 half is ready.** A validated `rsx_process_method(NV4097_DRAW_ARRAYS)`
reaches `d3d12_draw_arrays`, records a draw, and `render_frame()` replays it
through a real D3D12 device. The new in-backend self-test draws a known triangle
through the same callback interface with no FIFO, no guest memory, and no title:
on the reference machine (AMD Radeon RX 6650 XT, 1280×720) both the
fixed-function and the vertex-program subtests return **PASS** with
`clear=1024/1024`, `white=1024/1024` in the sampled tiles.

The reason no `DRAW_ARRAYS` has ever reached this backend is therefore upstream
of it: the method has to survive the guest command stream and the FIFO parser
before `rsx_process_method` dispatches it
(`rsx_commands.c`, `NV4097_DRAW_ARRAYS` → `s_backend->draw_arrays`). The backend
does not itself drop draws that arrive through that dispatch, subject to the
state gates below.

## Callback audit

| Callback | Implementation | Effect on a minimal draw |
|---|---|---|
| `init` | logging wrapper; real work in `rsx_d3d12_backend_init` | not a blocker |
| `shutdown` | logging wrapper; real work in `rsx_d3d12_backend_shutdown` | not a blocker |
| `begin_frame` / `end_frame` | no-ops | not a blocker; all work is deferred to `render_frame()` |
| `present` | `d3d12_present` | **gate**: only calls `render_frame()` when the batch is empty or contains a non-clear draw with `rt_off == 0` (display target). An offscreen-only batch is not replayed by this callback. The explicit `rsx_d3d12_backend_present()` does replay offscreen batches but only presents when display content exists. |
| `clear` | `d3d12_clear` | display clears only set `s_d3d.clear_color` (and are not recorded); offscreen/depth clears are recorded as ordered ops. A display clear with no display draws returns and keeps the batch accumulating. |
| `set_render_target` | `d3d12_set_render_target` | stores `current_rsx_state` and logs; does not create or bind anything. Targets are resolved per draw by `current_rt_off()` and created on demand by `off_rt_get()` / `off_ds_get()` in `render_frame()`. Not a stub in effect, but the callback itself does no D3D12 work. |
| `set_viewport` | `d3d12_set_viewport` | **STUB (no-op)**. Draws use `state->viewport_x/y/w/h`, captured per record and applied in the VP pass. `state->scissor_*` is never read at all; the VP pass uses the viewport rect as the scissor. Fine for full-target draws; wrong for guest scissor/sub-rect state. |
| `set_blend` | `d3d12_set_blend` | logging only. Blend enable/factors are captured per draw (`rsx_blend_key`) and become a PSO key only for guest-FP PSOs. The `fp_addr == 0` fallback PSO ignores guest blend. |
| `set_depth_stencil` | `d3d12_set_depth_stencil` | logging only. `rsx_zs_key` is captured per draw and used by `vp_get_fp_pso()`. Fallback PSOs use fixed depth state. |
| `set_color_mask` | **not registered** (`NULL` in `s_d3d12_backend`) | `rsx_commands.c` guards the call, so this is skipped. The draw record captures `state->color_mask` and passes it to the guest-FP PSO key. |
| `set_alpha_test` | **not registered** (`NULL`) | same: draw record captures `alpha_test_enable/func/ref`; the guest-FP HLSL and the fallback colour PS may not honour it if the FP path is absent. |
| `set_shader` | `d3d12_set_shader` | logging only, with a TODO. The actual FP address is captured at draw time (`dr->fp_addr`), and PSO lookup/compile happens in `vp_get_fp_pso()`. Not a drop. |
| `set_vertex_attribs` | `d3d12_set_vertex_attribs` | logging only; vertex data is fetched at draw/upload time from `current_rsx_state`. Not a drop. |
| `draw_arrays` | `d3d12_draw_arrays` | fully implemented; records legacy or VP draws for replay. Gates below. |
| `draw_indexed` | `d3d12_draw_indexed` | VP path only. It returns early if `!pipeline_ready`, bad count, or `!vp_vb_mapped || !vp_root_sig`. Non-indexed fallback state (no VP) cannot be drawn indexed. |
| `bind_texture` | `d3d12_bind_texture` | implemented. Only a whitelist of RSX formats is accepted (`0x81, 0x85, 0x8B, 0x86..0x88, 0x9A`); an unsupported format does not clear `cur_texs[unit].set`, so the draw can inherit a stale texture. `tex_bound` (legacy atlas path) is only set for B8. |

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
   `state->vertex_attribs[0].enabled` and returns 0 otherwise.
4. **TRIANGLES** with `vp_ucode_bytes >= 16`, `vp_vb_mapped`, `vp_root_sig`:
   `upload_tris_vp()` converts all 16 RSX attributes (type-aware, from guest
   memory via `rsx_vertex_fetch.c`) into 16 float4 slots and records
   `is_vp = 1`. Without VP microcode, TRIANGLES fall to the legacy
   `upload_vertices_from_rsx()` path (`is_vp = 0`), which only understands
   attrib0 as float32 and therefore draws in clip space with the identity MVP
   unless the game supplies `vertex_constants[0..3]`.
5. **QUADS** always prefer the VP path whenever `vp_vb_mapped && vp_root_sig`
   exist, even if no VP microcode was captured. Consequence: a quad drawn
   before the first VP is compiled records `is_vp = 1` and is then dropped by
   the render pass until `vp_ready` becomes 1. (Triangles do not have this
   asymmetry.)
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

Reference result (host harness, AMD RX 6650 XT):

```
[SELFTEST] start: 1280x720 pipeline_ready=1 vp_resources=1
[SELFTEST] legacy   recorded=1 readback=1 clear=1024/1024 white=1024/1024 nonclear=1024/1024 -> PASS
[SELFTEST] vp       recorded=1 readback=1 clear=1024/1024 white=1024/1024 nonclear=1024/1024 -> PASS
[SELFTEST] vp       cleanup: vp_ready=0
[SELFTEST] RESULT: PASS
```

Run it outside gt6 with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/patches/run_rsx_d3d12_selftest.ps1
```

## Remaining blockers / correctness gaps (backend side)

These do not stop the self-test, but they are the pieces to check when a real
guest draw still produces nothing:

1. `d3d12_set_viewport` is a no-op and `state->scissor_*` is unused. A title
   that relies on guest scissor or a non-default viewport will overdraw.
2. `set_color_mask` / `set_alpha_test` are not registered. The state is
   captured per draw, but the fallback (non-guest-FP) pipelines ignore it.
3. A guest-FP compile failure is non-fatal but can be visually fatal: the
   atlas PS fallback discards fragments when `tex_ready` is set and the draw's
   texture is absent/zero.
4. `vp_get_vs()` returns before calling `compile_vp()` if the per-draw
   decompile fails, so `vp_ready` can remain 0 and every `is_vp` record is
   dropped. The only diagnostic is the per-draw VS failure log.
5. Legacy (`is_vp == 0`) records ignore `current_rt_off()` and always draw to
   the display target; legacy FANs are not expanded; legacy indexed draws are
   not implemented at all.
6. `bind_texture` leaves stale per-unit state for unsupported formats.
7. `d3d12_present` does not replay offscreen-only batches; the explicit
   `rsx_d3d12_backend_present()` does, but only presents when display content
   is detected.
8. `vp_cb_mapped` allocation failure is silent (only the size line prints).

## Files

- `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`
  - `rsx_d3d12_backend_selftest`, `selftest_shot`, `selftest_setup_state`,
    `selftest_release_vp`, `selftest_analyze_pixels`
  - hooks in `read_rsx_vertex` / `read_vp_vertex`
  - readback branch in `render_frame`
  - startup trigger in `rsx_d3d12_backend_init`
- `third_party/ps3recomp/libs/video/rsx_d3d12_backend.h` — declaration
- `tools/patches/rsx_d3d12_selftest_host.c` — host harness
- `tools/patches/run_rsx_d3d12_selftest.ps1` — build/run script
