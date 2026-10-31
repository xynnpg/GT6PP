# D3D12 draw-readiness check

**Date:** 2026-10-31
**Checker scope:** read-only review of
`third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`, its `rsx_backend`
callbacks, and the boundary with `rsx_commands.c` / `cellGcmSys.c`.
No build, no `gt6.exe` run, no source edits by this checker.
**Reviewed revisions:** `rsx_d3d12_backend.c` 2026-10-31 16:21:45,
`rsx_commands.c` 16:28:27 (a `DATA2F` constant fold landed while this check was
being written; see §3.5/§5.2). The prebuilt host harness used for the runtime
evidence is from 16:18:52 and predates the last robustness edits; see
"Limitations".
**Policy:** `third_party/PDTools/AGENTS.md` was not read or used.

---

## 0. Bottom line

| Question | Verdict |
|---|---|
| Is the D3D12 backend ready for a decoded `NV4097_DRAW_ARRAYS`? | **PASS** |
| Does the fixer's `RSX_D3D12_SELFTEST` prove the D3D12 device/raster path? | **PASS** (independently reproduced) |
| Does it prove GT6's first draw reaches the backend? | **FAIL** |
| Is the `rsx_backend` state-callback ordering valid for a `DRAW_ARRAYS`? | **PASS**, with a fragile global-state contract |
| Does GT6's measured first primitive reach `draw_arrays`? | **FAIL** — it is an immediate-mode `DATA2F` strip, not `DRAW_ARRAYS` |
| Does the backend support constant vertex attributes (`DATA2F` etc.)? | **PARTIAL** — `DATA4F` and, since 16:28, `DATA2F` x/y are folded; `DATA2F` is not treated as an immediate vertex, and `DATA2S`/`4UB`/`4S`/`1F`/`3F` are still missing |
| Is the window showing the D3D12 image? | **NO / MASKED** — `GCM_GUEST_FB` is still forced on by default |

The backend's **`DRAW_ARRAYS` path is not the reason** the titlebar says
`draws: 0`; `d3d12_draw_arrays` records a draw and `render_frame()` replays it,
and the self-test proves this on the actual GPU. The primary failure is at the
**interface boundary**: GT6's first frame is a 10-vertex immediate-mode triangle strip
(`SET_BEGIN_END(6)`, `SET_VERTEX_DATA2F_M` writes, `SET_BEGIN_END(0)`), and the
legacy `rsx_commands.c` path has no immediate-vertex path to call the backend.
Separately, `gt6/src/main.cpp:593` still forces `GCM_GUEST_FB=0,1280,720,6144`,
so the guest-framebuffer copy overwrites whatever the D3D12 backend draws.

---

## 1. Evidence base

- **Backend self-test, independent run** (prebuilt harness
  `%TEMP%\gt6pp_rsx_d3d12_selftest\rsx_d3d12_selftest.exe`, 16:18:52):
  both the fixed-function and VP subtests printed `PASS` with
  `clear=1024/1024 white=1024/1024`, and `selftest returned 0`.
  Running it again with `RSX_D3D12_SELFTEST=1` also exercised the automatic
  startup trigger (two full test runs) and exited 0.
- **GT6 method trace** `work/agent_rsx/run3.err` (`RSX_TRACE=1200`), lines
  22292 and 22399–22420: black clear, then
  `0x1808=6` (TRIANGLE_STRIP), twenty `0x1880/0x1884` DATA2F writes
  (ten vertices), `0x1808=0`, report/fence. No `0x1814`, `0x1818`, `0x181C`
  or `0x1824` appears in the trace.
- **Current windowed log** `work/gt6.log:1312`:
  `[GUESTFB] presenting guest 0x00000000 1280x720 pitch 6144 -> backbuffer`.
  This is the forced guest-framebuffer copy, not a D3D12 draw.
- **Companion check** `docs/analysis/rsx-first-draw-check.md` independently
  found the missing `0x1880`/`0x1884` decode before the 16:28 fix; it counted
  only the explicit draw methods and called the block a state block. The
  project's own immediate compositor test treats the same sequence as a draw:
  `third_party/ps3recomp/libs/video/tests/test_rsx_draw_engine.c:2216-2218`
  asserts that `0x1880/0x1884` DATA2F ATTR0 emits a vertex on its Y word, and
  `test_immediate_compositor()` asserts that a `BEGIN_END` group of such
  vertices becomes a draw (`n_draw`, `draw_vertices`, `draw_indices`).
  `rsx_dispatch.c:281-284,338-347` is the implementation of that rule.
- **Fixer's audit** `docs/analysis/d3d12-draw-readiness.md` is a useful
  callback checklist, but its conclusion that the 0-draw frame is "upstream"
  stops at `DRAW_ARRAYS`; it does not identify the immediate-mode strip or the
  constant-attribute gap below.

Line numbers in this report are from the reviewed revisions above; the
backend file is being edited concurrently, so function names are the stable
references.

---

## 2. Callback audit

The backend sets up its callback vtable in `rsx_d3d12_backend_init` (current
lines 8050–8059); `set_color_mask` and `set_alpha_test` are left NULL. Several
registered callbacks are intentionally "store state only" and the actual work
is deferred to the draw record / `render_frame()`. The distinction between an
intentional deferred no-op and a dropped feature matters:

| Callback | Current implementation | Verdict / effect |
|---|---|---|
| `init` | `d3d12_init` only logs; real init is in `rsx_d3d12_backend_init` | **not a blocker** for the GT6 host, which calls the public init directly |
| `shutdown` | `d3d12_shutdown` only logs; real shutdown is public | not a blocker |
| `begin_frame` / `end_frame` | no-ops | not a blocker; `render_frame()` owns the frame |
| `present` | `d3d12_present` (line 6262) is **never called by `rsx_commands.c`**; the GT6 present thread calls `rsx_d3d12_backend_present()` (line 8138) directly | interface mismatch; the registered callback is dead code. Its display gate differs from the public function's (the public one also replays offscreen-only batches) |
| `clear` | `d3d12_clear` (line 6296): a display colour clear only sets `s_d3d.clear_color`; offscreen/depth clears are recorded as ordered ops | **works**, but a display clear with no display draws returns and keeps the batch accumulating |
| `set_render_target` | stores `current_rsx_state` and logs; targets are resolved per draw by `current_rt_off()` / `off_rt_get()` | **deferred, not a stub in effect**; no D3D12 call at callback time |
| `set_viewport` | **no-op** (line 6440) | viewport is captured per draw and applied in the VP pass; **scissor is never applied** |
| `set_blend` | logging only | blend is captured into `rsx_blend_key` and used by guest-FP PSOs; the fixed/colour fallback PSO ignores guest blend |
| `set_depth_stencil` | logging only | captured into `rsx_zs_key` and used by guest-FP PSOs; fallback PSOs use fixed depth state |
| `set_color_mask` | **not registered** (`NULL` in the vtable) | `rsx_commands.c:879-882` guards the call, so it is skipped. The draw record captures `state->color_mask` for guest-FP PSOs; fallback PSOs ignore it |
| `set_alpha_test` | **not registered** (`NULL`) | same; captured in `alpha_ctl`, used by the guest-FP HLSL / alpha-test constant path; fallback colour PS does not implement it |
| `set_shader` | logging only with a stale `TODO` (line 7951) | the FP address is captured at draw time; `vp_get_fp_pso()` compiles in `render_frame()`; **not a drop** |
| `set_vertex_attribs` | logging only (line 7919) | vertex data is fetched at draw time from `current_rsx_state`; **not a drop**, but no input layout/prewarm |
| `draw_arrays` | `d3d12_draw_arrays` (line 7384) is implemented and records legacy/VP draws | **works**; gates below |
| `draw_indexed` | `d3d12_draw_indexed` (line 7632) is VP-only; returns early without `vp_vb_mapped`/`vp_root_sig` | partial: indexed fixed-function draws cannot be drawn |
| `bind_texture` | `d3d12_bind_texture` (line 7768): units 0–3 only, whitelist `0x81,0x85,0x8B,0x86..0x88,0x9A`; unsupported formats do not clear the old `cur_texs[unit].set` | partial and stale-state risk |

**Important:** `set_viewport`/`set_shader`/`set_blend`/`set_depth_stencil` being
no-ops is not by itself a draw-readiness failure because the draw record
snapshots the state. The actual defect is the **scissor**: `state->scissor_x/y/w/h`
is decoded by `rsx_commands.c:996-1006` but never read by the D3D12 backend; the
VP replay sets the D3D12 scissor rectangle equal to the viewport rectangle
(`render_frame`, current lines 5360-5385). A title with a guest scissor smaller
than the viewport will overdraw.

---

## 3. Draw path and required state

### 3.1 `draw_arrays`

`d3d12_draw_arrays` is not a stub:

- it requires `s_d3d.pipeline_ready` and `s_d3d.vb_mapped`; both are created in
  `init_d3d12` (the self-test and logs show `pipeline_ready=1`);
- it rejects `count == 0` and `count > MAX_VERTICES` (393,216); the FIFO packet
  count is at most 256, so this is not the GT6 limit;
- it fetches vertices from guest memory via `read_vp_vertex()` →
  `rsx_fetch_attrib()` for the VP path, or `read_rsx_vertex()` for the legacy
  fixed-function path;
- it records a `D3D12DrawRecord` with the target (`current_rt_off`), viewport,
  FP address, colour mask, alpha test, blend key, depth/stencil key, texture
  bindings and a per-draw constant-buffer slot;
- `render_frame()` replays legacy records through `pipeline_state` and VP
  records through the decompiled VS/PS PSOs, uploads per-draw constants,
  uploads textures, binds RTVs/DSVs, sets viewports and executes
  `DrawInstanced`.

The self-test independently proves the legacy and VP replay paths on the
actual adapter (AMD RX 6650 XT, 1280×720).

**Gates that matter for GT6:**

1. **`SET_BEGIN_END(prim)` must have run.** It flushes dirty state to the
   callbacks before the draw and sets `current_rsx_state`; `draw_arrays` reads
   that global. Without it a draw can see stale/NULL state.
2. **Attribute 0 must be enabled** (`vertex_attribs[0].enabled`, i.e. size != 0).
   Every VP upload path returns 0 otherwise (`upload_quads_vp` /
   `upload_tris_vp` / `upload_strip_vp`, current lines 6871-6872, 6905-6906,
   6971-6972, 7016-7017, 7143-7144, 7362-7363). This is exactly the
   constant-attribute/immediate-vertex case; see §5.
3. **QUADS prefer the VP path** whenever `vp_vb_mapped && vp_root_sig`, even
   before a VP is compiled, and are then dropped until `vp_ready` is set.
4. **TRIANGLES without VP microcode** fall to the legacy path
   (`upload_vertices_from_rsx`), which only understands attrib0 as float32,
   attrib3 as colour, and uses the identity MVP unless constants 0–3 are set.
5. **FANS without a VP are not expanded**; only the first triangle is
   meaningful. Strips are expanded only on the VP path.
6. **Legacy records force `rt_off = 0`**; they always target the backbuffer,
   not an offscreen surface. VP records capture `current_rt_off()`.
7. **`MAX_DRAWS` (2048) and the per-frame vertex buffer** are silent
   truncation points; the logs only report with `FRAME_BUDGET=1`/`VBFULL`.

### 3.2 Vertex formats

The VP path is complete enough for a first draw:

- `rsx_vertex_fetch.c:29-127` handles all RSX attribute types used by the
  register file: `S1` (type 1), float32 (2), half-float (3), ubyte normalized
  (4), s16 integer (5), compressed CMP (6), ubyte unnormalized (7), with
  big-endian component reads and the per-attribute frequency divider.
- `read_vp_vertex()` fetches all 16 attributes, and `read_rsx_vertex()` is a
  narrower legacy fallback (attrib0 float, attrib3 ubyte/float).
- The backend's own comment in `compile_vp` notes the VP VB carries one
  float4 per input slot and the input layout declares 16 ATTRs; the VP path
  uploads all fetched attributes, so this is consistent.

**Verdict:** PASS for the VP path; PARTIAL for the legacy fallback.

### 3.3 Vertex programs and fragment programs

- VP: `rsx_vp_decompiler.c` + `compile_vp()` / `vp_get_vs()` produce HLSL,
  compile it with D3DCompile, build `pipeline_state_vp` and
  `pipeline_state_vp_color`, and cache per-draw VS blobs. The self-test's
  two-instruction `MOV o0,v0; MOV o1,v1; END` program passes.
- FP: `vp_get_fp_pso()` (line 2327) reads the guest FP ucode at
  `fragment_program_addr`, decompiles, hashes the code, and caches a PSO keyed
  by VS, blend, RT format/count, control bits, colour mask, cull and depth/
  stencil. The self-test sets `fp_addr = 0`, so **the guest-FP path is not
  exercised**.
- Fallback: if FP compilation returns NULL, the draw uses `vpso`; if
  `tex_ready` is set, that is the **atlas** PSO, which samples t0 and discards
  coverage <= 0.5. With no/zero SRV the draw is invisible. The self-test
  deliberately forces `tex_ready=0` for the VP shot to avoid this, so the test
  does not cover the real FP+texture combination.

**Verdict:** VP PASS; FP PARTIAL/untested by the self-test.

### 3.4 Textures

`d3d12_bind_texture` records only units 0–3, and only for the whitelist above.
The actual uploader, `vp_upload_tex_slot`, supports a wider set of formats via
`rsx_texture_layout.c` (B8, RGBA8, G8B8, DXT1/2/3, 16/32-bit float, depth, and
packed colour formats), but the binding gate is narrower. An unsupported
format leaves `cur_texs[unit].set` from the previous bind, so a draw can inherit
a stale texture rather than a disabled one. `RSX_MAX_TEXTURES` is 16 but the
draw record only carries four; GT6 issues texture units 4–6 on subchannel 1
(the `GCM_SUBCH1_3D` comment in `cellGcmSys.c`), which this backend cannot bind.

**Verdict:** PARTIAL. The first draw may be untextured, in which case this is
not the immediate blocker; it is a real gap for later frames.

### 3.5 Constant upload

There are two different constant paths:

- **Transform constants (VP c[]):** `rsx_commands.c` decodes
  `SET_TRANSFORM_CONSTANT_LOAD` (0x1EFC) and the 0x1F00–0x1F7C window into
  `state->vertex_constants[512][4]`; `vp_record_cb()` copies the entire bank
  plus the viewport epilogue into the per-draw CB at record time. This is
  implemented and correct in shape. The self-test does not read any of these
  constants (its VS uses `v0`/`v1` directly), so it does not prove the CB.
- **Constant vertex attributes:** `rsx_commands.c` handles the
  `SET_VERTEX_DATA4F_M` window 0x1C00–0x1C3F (line 832ff) and, since the
  16:28 edit, the `DATA2F` window 0x1880–0x18FC (lines 809–820). The DATA2F
  fold writes x/y into `vertex_data4f[attr][0..1]`; it does **not** reset
  z/w to (0,1) on the x word as `rsx_dispatch.c:281-284` does, so a prior
  `DATA4F` can leave stale z/w. It also does not yet handle `DATA2S`
  (0x1900–0x193C), `DATA4UB` (0x1940–0x197C), `DATA4S` (0x1980–0x19FC),
  `DATA1F` (0x1E40–0x1E7C) or `DATA3F` (0x1500–0x15FC).
  The project's draw-engine decoder folds all of those
  (`rsx_dispatch.c:273-306`) and treats the completing word as an immediate
  vertex (`rsx_dispatch.c:338-347`). The legacy path used by D3D12 has the
  `DATA2F` fold but **not** the immediate-vertex emission.

**Verdict:** transform constants PASS; constant attributes PARTIAL. GT6's
first frame uses `DATA2F`, so the constant values now reach the state, but the
draw is still not emitted (below).

### 3.6 Render target, viewport, scissor, present

- **Render target:** `current_rt_off()` maps registered display offsets to the
  backbuffer (`cellGcmOffsetIsDisplay`) and other offsets to the offscreen RT
  pool; `off_rt_get()` creates/seeds the target. GT6's 0x660000 display buffer
  is recognized. **PASS**, subject to the legacy `rt_off=0` behavior.
- **Viewport:** per-draw `dr->vp_x/y/w/h` from `state->viewport_*` is applied in
  the VP pass; `set_viewport` itself is a no-op. **PASS** for the guest
  viewport rect.
- **Scissor:** `state->scissor_*` is decoded by `rsx_commands.c` but never read
  by the backend; `render_frame()` sets the D3D12 scissor to the viewport
  rectangle. **FAIL** for any guest scissor/sub-rect use.
- **Present:** `rsx_d3d12_backend_present()` (line 8138) renders when a display
  draw (`rt_off == 0`) or an offscreen batch is present. It calls
  `Present` at lines 5981–5986 but **does not check the HRESULT**; a
  `DXGI_ERROR_DEVICE_REMOVED` would be silently ignored. The registered
  `d3d12_present` callback is not invoked by `rsx_commands.c`.

---

## 4. Self-test review

### 4.1 What exists

`RSX_D3D12_SELFTEST=1` is read in `rsx_d3d12_backend_init` (lines 8068–8075)
after the backend is registered. `rsx_d3d12_backend_selftest()` (line 6148):

1. checks `initialized`, device, command list, `pipeline_ready`, `vb_mapped`;
2. builds a synthetic `rsx_state` with attrib0 enabled (float32×4) and, for the
   VP shot, a hand-assembled `rsx_test_programs.h` program
   (`MOV o0,v0; MOV o1,v1; END`);
3. sets a fixed clip-space triangle in `s_selftest_pos` and bypasses guest
   fetch in `read_rsx_vertex` / `read_vp_vertex` only while
   `s_selftest_active && state == &s_selftest_state`;
4. calls the public `rsx_backend` callbacks in order:
   `set_render_target` → `clear(0xF0, red)` → `set_vertex_attribs` →
   `set_shader` → `draw_arrays(TRIANGLES,0,3)` → `render_frame()`;
5. copies the top-left 32×32 and centre 32×32 tiles from the backbuffer to a
   readback buffer, waits for the fence, checks the top-left is red
   (≥90%) and the centre is white (≥50%), and prints
   `[SELFTEST] legacy/vp ... PASS/FAIL`, `[SELFTEST] RESULT`, plus
   `[D3D12] selftest: PASS/FAIL` from init.

The VP subtest releases its test PSOs/VS blobs and resets `vp_ready` so the
title's first real VP compiles fresh.

### 4.2 Independent result

The prebuilt host harness (16:18:52, before the last robustness edits) was run
by this checker:

```
[SELFTEST] start: 1280x720 pipeline_ready=1 vp_resources=1
[SELFTEST] legacy   recorded=1 readback=1 clear=1024/1024 white=1024/1024 nonclear=1024/1024 -> PASS
[SELFTEST] vp       recorded=1 readback=1 clear=1024/1024 white=1024/1024 nonclear=1024/1024 -> PASS
[SELFTEST] vp       cleanup: vp_ready=0
[SELFTEST] RESULT: PASS
selftest returned 0
```

With `RSX_D3D12_SELFTEST=1` the init trigger also ran a full pass before the
harness's explicit call (two `RESULT: PASS` lines, exit 0). This is a real
D3D12 run on the AMD RX 6650 XT, not a log-only claim.

### 4.3 What it proves

- D3D12 device, swapchain backbuffer RTV, clear-colour conversion, depth
  buffer, fixed-function PSO, vertex-buffer upload, `DrawInstanced`, and
  backbuffer readback all work.
- The VP path works end-to-end for a minimal NV40 program: decompiler →
  HLSL → D3DCompile → PSO → `vp_vb` upload → draw → readback.
- It is a good **device-path smoke test** and should stay.

### 4.4 What it does not prove

- It does **not** call `rsx_process_method` or decode any NV4097 packet; it
  calls the vtable functions directly. It cannot prove that the FIFO walker,
  `SET_BEGIN_END` dirty flush, `current_rsx_state` pointer, or
  `NV4097_DRAW_ARRAYS` packet decode work. A `[SELFTEST] PASS` is compatible
  with the guest never issuing a draw.
- It does **not** exercise `draw_indexed`, textures, the guest FP decompiler/
  PSO (`fp_addr` is 0), the per-draw constant bank contents (its VS ignores
  `vp_c[]`), scissor, blend/depth/stencil guest states, offscreen RT/composite,
  or the public `rsx_d3d12_backend_present()` display gate. It calls
  `render_frame()` directly, bypassing the present gate and flip dedupe.
- It does **not** test the immediate-mode `DATA2F` path or attr0-disabled /
  constant-attribute geometry. It explicitly enables attrib0 to make the VP
  upload path pass; GT6's first block has no attribute arrays.
- It does **not** prove the actual `Present` result. `render_frame()` calls
  `IDXGISwapChain::Present` at lines 5981–5986 but ignores the HRESULT, and the
  readback is taken **before** Present. A pass proves backbuffer content, not
  that a frame was composited to the screen.
- It does **not** exercise the guest-framebuffer (`GCM_GUEST_FB`) or composite
  paths: `s_selftest_active` makes `guest_fb_present()` and
  `composite_present()` return early (lines 4350, 4408), which is correct for
  isolation but means those paths are untested.

### 4.5 Environment gate, default behavior, fake output

- **Gate:** default off. `RSX_D3D12_SELFTEST` set to anything except `"0"`
  runs it; `RSX_D3D12_SELFTEST_VP=0` skips the VP half. With the env unset,
  the new `s_selftest_*` branches are inert; normal rendering is unchanged.
- **Fake game output:** the self-test itself does **not** fake game output or
  write guest memory. It uses a synthetic state/vertex source and suppresses
  guest compositing only while active; it restores `current_rsx_state`,
  `tex_bound`, `tex_ready` (VP), and `clear_color`. It does reset
  `draw_count`/VB offsets and advance `frame_count`; it is safe at startup
  (where init calls it) but the public entry point should not be called
  mid-frame.
- **Separate fake output:** `gt6/src/main.cpp:593` still forces
  `GCM_GUEST_FB=0,1280,720,6144` when the env is unset. `guest_fb_present()`
  then copies guest buffer 0 over the backbuffer on every present; the current
  `work/gt6.log:1312` shows `[GUESTFB] presenting guest 0x00000000 ...`.
  This is not the self-test, but it masks the D3D12 image and contradicts
  `docs/analysis/rsx-first-frame.md` (which says the forced default was
  removed). The self-test correctly suppresses it while active, but the game
  run after the test still uses it.
- **Failure reporting:** the test prints detailed per-shot counters and a
  `RESULT`, and `rsx_d3d12_backend_selftest()` returns 0/1/-1. However
  `rsx_d3d12_backend_init` prints the result and **ignores the return value**
  (lines 8068–8075); a FAIL does not fail init or the process. A CI gate needs
  to parse the log or the init should propagate a strict failure
  (`RSX_D3D12_SELFTEST_STRICT=1` or return -1 on FAIL).

### 4.6 Minor self-test issues

- The clear comment says "opaque red", but `0x00FF0000` has alpha 0; the
  readback check ignores alpha, so it passes, but the comment is wrong.
- The fixer's audit snippet says `clear -> set_render_target`; the current code
  does `set_render_target -> clear` (correct, because `d3d12_clear` classifies
  the target through `current_rsx_state`). The doc is stale on this point.
- The test uses the same readback resource for both shots. The current code
  resets the counters and requires `readback=1` per shot; a stale legacy tile
  cannot pass the VP shot unless the map succeeds again, so this is less risky
  than it looks, but a sentinel/zeroed readback per shot would be stricter.
- The final source (16:21) is newer than the prebuilt harness (16:18); the
  late edits (counter reset, `mapped_ok`, clear ordering, `tex_bound` restore,
  shutdown readback release) look like robustness fixes. They were not
  rebuilt/run by this checker.

**Self-test verdict:** **PASS** as a synthetic D3D12 device-path test;
**FAIL** as proof of the guest draw path or as a hard gate.

---

## 5. Interface boundary with `rsx_commands.c` / `rsx_backend`

### 5.1 What is valid

- `rsx_d3d12_backend_init()` registers the backend
  (`rsx_set_backend(&s_d3d12_backend)`) before the present thread drains. In
  `cellGcmSys.c`, `legacy_state_live = rsx_get_backend() != NULL || ...`
  becomes true, so every subchannel-0/1 method is handed to
  `rsx_process_method`.
- `rsx_state_init()` marks all state dirty. At the first
  `NV4097_SET_BEGIN_END(prim)`, `rsx_commands.c:863-911` calls
  `set_render_target`, `set_viewport`, `set_blend`, `set_depth_stencil`,
  `set_shader`, `set_vertex_attribs` and `bind_texture` **before** any
  `DRAW_ARRAYS`/`DRAW_INDEX_ARRAY` can run. `d3d12_set_render_target`,
  `set_shader` and `set_vertex_attribs` set `s_d3d.current_rsx_state` to the
  persistent `s_state` from the drain. The `DRAW_ARRAYS` callback receives
  `primitive`, `first` and `count` from the packet
  (`first = data & 0xFFFFFF`, `count = (data>>24)+1`), which matches the RSX
  encoding.
- Vertex data is read at draw time from `vm_base` via
  `cellGcmResolveLocated`, with the local/main location bits honored; index
  arrays use the same resolve and support u32/u16 big-endian indices.
- The `DRAW_ARRAYS` unit test (`libs/video/tests/test_rsx_fifo.c`) and the
  selftest's direct callback path separately show that the dispatch and the
  backend callbacks work.

**Verdict:** valid state/vertex contract for an actual `DRAW_ARRAYS`, subject
to the attr0-enabled gate and the global-state fragility (the callback does
not receive `state` as a parameter; it relies on `s_d3d.current_rsx_state`
being set by a prior dirty-state callback).

### 5.2 The actual GT6 first-frame gap

The measured first frame is **not** a `DRAW_ARRAYS`:

```
work/agent_rsx/run3.err:22399  0x1808 = 0x00000006   ; BEGIN_END TRIANGLE_STRIP
work/agent_rsx/run3.err:22400  0x1880 = 0x00000000   ; DATA2F ATTR0.x
work/agent_rsx/run3.err:22401  0x1884 = 0x00000000   ; DATA2F ATTR0.y -> vertex
...
work/agent_rsx/run3.err:22418  0x1880 = 0x00000000
work/agent_rsx/run3.err:22419  0x1884 = 0x00000000
work/agent_rsx/run3.err:22420  0x1808 = 0x00000000   ; END
```

Ten vertices: (0,0), (0,0), (1280,0), (1280,0), (1280,720), (1280,720),
(0,720), (0,720), (0,0), (0,0). This is an immediate-mode triangle strip
whose corners are duplicated; the project's own draw engine treats each
`0x1884` (DATA2F Y) as a vertex completion and the group as a draw
(`rsx_dispatch.c:281-284,338-347`;
`test_rsx_draw_engine.c:2216-2218`). The hardware draws it; the legacy
`rsx_commands.c` path does not:

- `rsx_process_method` now folds `0x1880`/`0x1884` into
  `vertex_data4f[0]` (lines 809–820), so the constant values are no longer
  lost. But it does **not** treat the `0x1884` write as an immediate-vertex
  completion, and there is still no draw callback for this block.
- `SET_BEGIN_END` only sets `in_begin_end` and flushes state; it never
  accumulates immediate vertices or emits a draw at END.
- The only draw callbacks are on `0x1814`/`0x1824`; there is no `0x1814` in the
  trace. The new `g_rsx_draw_arrays_decoded` counter increments only in the
  `0x1814` case (`rsx_commands.c:918`), so it reads 0 even though the guest
  submitted this strip. `RSX_DRAWDBG` logs only `0x1814`/`0x1824`, so it also
  misses the immediate draw.
- The draw engine's immediate-vertex implementation is not active for D3D12:
  `rsx_draw_engine_enabled()` requires a registered `rsx_draw_backend`
  (`g.be`), and `rsx_d3d12_backend_init` never calls
  `rsx_draw_engine_set_backend`/`rsx_draw_engine_init`. The draw engine is a
  separate vtable (`rsx_draw_engine.h:123-299`), not the `rsx_backend` used by
  `rsx_commands.c`.

Therefore the D3D12 backend receives **zero** `draw_arrays` calls for this
frame, even though the guest is drawing. The fixer's "reason is upstream"
hypothesis is correct in direction but incomplete: the missing piece is the
immediate-mode translation, not just a FIFO/DRAW_ARRAYS loss.

Even if the frontend synthesized a `draw_arrays` for these ten vertices, the
backend's upload paths would return 0 because `vertex_attribs[0].enabled` is
false (there are no vertex arrays; the block uses constant attributes). This is
the second half of the same gap.

### 5.3 Constant attributes

GT6 writes `DATA2F` (0x1880/0x1884); the 16:28 edit now folds its x/y into
`vertex_data4f`, so a constant position is available. The z/w lanes are not
reset to (0,1) on the x word, and the other encodings are still missing. The
draw engine's `vtx_const_fold` (`rsx_dispatch.c:273-306`) is the reference
implementation. More importantly, the fold alone is not enough: the legacy
path still needs an immediate-vertex emitter before GT6's first draw can work.

### 5.4 Default output masking

`gt6/src/main.cpp:593` forces `GCM_GUEST_FB=0,1280,720,6144`. The present path
then calls `guest_fb_present()`, which copies guest display buffer 0 over the
D3D12 backbuffer every present. This is a host-side fallback, not the guest's
draw, and it can make a correct D3D12 frame look black. It must be removed or
made explicitly opt-in before judging any image. The self-test's suppression of
`guest_fb_present`/`composite_present` while active is correct but only covers
the test frames.

---

## 6. Exact missing or wrong functions

| Location | Problem | Impact |
|---|---|---|
| `rsx_commands.c` `rsx_process_method` | `0x1880`/`0x1884` DATA2F x/y are folded (lines 809–820) but not treated as vertex completion; `0x1900` (DATA2S), `0x1940` (DATA4UB), `0x1980` (DATA4S), `0x1E40` (DATA1F), `0x1500` (DATA3F), `0x1818` (INLINE_ARRAY) are still missing; DATA2F does not reset z/w | GT6's first strip is not drawn; constant attributes are partial |
| `rsx_commands.c` `SET_BEGIN_END` | no immediate-vertex accumulation/emission at END | no `draw_arrays` for immediate geometry |
| `rsx_d3d12_backend.c` `upload_quads_vp` / `upload_tris_vp` / `upload_strip_vp` | return 0 if `vertex_attribs[0].enabled == 0` | constant-attribute/immediate geometry cannot draw even if a draw is synthesized |
| `rsx_d3d12_backend.c` `d3d12_set_viewport` | no-op; `state->scissor_*` never read; VP scissor = viewport rect | guest scissor/sub-rect is ignored |
| `rsx_d3d12_backend.c` `d3d12_bind_texture` | units 0–3 only; whitelist; unsupported format leaves stale `cur_texs[unit].set` | texture units 4–6 and other formats are dropped/stale |
| `rsx_d3d12_backend.c` `d3d12_draw_arrays` legacy path | hardcodes `rt_off = 0` | legacy draw to an offscreen surface renders to the backbuffer |
| `rsx_d3d12_backend.c` `d3d12_draw_indexed` | VP-only; early return without VP resources | indexed fixed-function draws are dropped |
| `rsx_d3d12_backend.c` `set_color_mask` / `set_alpha_test` | left NULL in the vtable | fallback PSOs ignore guest colour mask/alpha test (records capture them for guest-FP PSOs only) |
| `rsx_d3d12_backend.c` `Present` calls (lines 5981–5986) | HRESULT ignored | device-removed/present failures are invisible |
| `rsx_d3d12_backend.c` `rsx_d3d12_backend_init` (lines 8068–8075) | selftest return ignored | a FAIL is log-only, not a gate |
| `gt6/src/main.cpp:593` | forces `GCM_GUEST_FB` | guest buffer 0 overwrites the D3D12 frame |
| `rsx_commands.c` `d3d12_present` registration | `rsx_commands.c` never calls `backend->present`; GT6 calls the public API directly | registered callback is dead; other hosts using the vtable would not present |

---

## 7. Safest next step

Ordered by risk and by what actually explains the observed frame:

1. **Keep the self-test, but do not treat its PASS as a fix.** It already
   proves the D3D12 device/raster/readback half. Run it again after the next
   full build, and make a failed auto-run fail init (or parse
   `[SELFTEST] RESULT: FAIL`) if it is meant to gate CI.
2. **Fix the immediate-mode boundary** (owned by the FIFO/`rsx_commands`
   fixer): accumulate `DATA2F`/`DATA2S`/`DATA4UB`/`DATA4S`/`DATA1F`/`DATA3F`
   vertex completions inside `SET_BEGIN_END`, and emit a draw to the backend at
   END. Do not fake a `DRAW_ARRAYS` with attr0 disabled; the backend's
   `upload_*` paths reject it. The clean options are:
   - add an explicit `immediate_vertices`/`draw_immediate` callback to
     `rsx_backend` and materialize the vertices in the backend; or
   - reuse the existing `rsx_draw_engine` immediate path by implementing its
     `rsx_draw_backend` for D3D12 (larger, but the engine's
     `immediate_vertex` logic is already tested); or
   - at minimum, materialize the vertices into a temporary backend-side vertex
     buffer and extend the D3D12 draw entry point; do not write guest memory
     from the walker.
3. **Complete the constant-attribute fold** in `rsx_commands.c`, mirroring
   `rsx_dispatch.c:273-306`: reset z/w to (0,1) on the DATA2F x word, and add
   `DATA2S`/`DATA4UB`/`DATA4S`/`DATA1F`/`DATA3F`. This is needed even outside
   immediate mode (constant colour/normal/UV attributes).
4. **Remove or opt-in the forced `GCM_GUEST_FB` default** at
   `gt6/src/main.cpp:593`. Use it only as a diagnostic with the current display
   buffer offset; otherwise it will keep overwriting the D3D12 image. Judge the
   backend only with it unset.
5. **Then add a real-draw diagnostic:** keep `RSX_DRAWDBG=1`, add a counter for
   immediate vertices, and expect `[D3D12] draw_arrays #...` (the first 20 are
   logged unconditionally) plus a nonzero titlebar `draws`. If the counter
   moves but the image is black, re-check the FP/texture path
   (`tex_ready`/atlas PS discard) and the forced guest-FB copy.
6. **Backend hygiene after the first draw:** implement guest scissor, clear
   `cur_texs[unit].set` on unsupported binds, support/warn on units 4–15,
   propagate the Present HRESULT, and register or explicitly document the
   `set_color_mask`/`set_alpha_test` callbacks.

The key point for the parent session: **do not spend more time re-auditing
backend callbacks to explain `draws: 0`.** The backend records and replays a
`DRAW_ARRAYS`; the measured GT6 frame never calls it because the frontend has
no immediate-vertex path, and the backend's attr0 gate would reject the
constant-attribute draw even if the frontend synthesized one.

---

## 8. Limitations

- This check is static review plus the independent run of the **prebuilt**
  host harness. It did not build the current source or run `gt6.exe`
  (read-only policy). The final source is newer than the harness; the late
  self-test edits look like robustness fixes, but a fresh harness/build should
  confirm them.
- Line numbers refer to the 16:21/16:28 revisions and may shift with the
  concurrent fixer.
- The immediate-mode interpretation is based on the project's own
  `rsx_dispatch.c` rules and `test_rsx_draw_engine.c` assertions, not on a
  hardware trace. The companion `rsx-first-draw-check.md` reads the same block
  as state rather than a draw; either reading supports the same conclusion for
  the backend: it is never called for this block.
- `third_party/PDTools` was not read or used.
