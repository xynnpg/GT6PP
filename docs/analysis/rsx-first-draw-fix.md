# RSX first draw: immediate-mode submission, decoder fixes, and verification

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296`, `work/bin/EMAIN.elf`, `gt6/build/gt6.exe`
**Scope:** static analysis of the lifted guest draw path, the existing headless
and windowed logs, and decoder changes in
`third_party/ps3recomp/libs/video/cellGcmSys.c` and
`third_party/ps3recomp/libs/video/rsx_commands.c`. `rsx_d3d12_backend.c`,
`gt6/generated` and `gt6/src/main.cpp` were not edited.

**Checker input:** `docs/analysis/rsx-first-draw-check.md` is correct that the
first frame is an **immediate-mode 10-vertex DATA2F triangle strip**, not a
`DRAW_ARRAYS` batch. That correction is the basis of the fix below.

---

## TL;DR

1. GT6 does not use HLE `cellGcmSetDrawArrays`/`SetDrawIndexArray`. It uses
   inline NV4097 words from its own statically linked libgcm.
2. The **first real draw is immediate mode**, not `DRAW_ARRAYS`:
   `SET_BEGIN_END(6)` + ten `SET_VERTEX_DATA2F_M` x/y pairs + `SET_BEGIN_END(0)`
   (`run3.err:22399-22420`). The old decoder folded the x/y values into
   `vertex_data4f` but never treated the attr0 **Y** write (`0x1884`) as a
   completed vertex, so no draw callback was emitted.
3. Implemented:
   - immediate-vertex accumulation on `0x1884` (and `0x1C0C`), a temporary
     local-memory vertex buffer, and a real `draw_arrays` callback at
     `SET_BEGIN_END(0)` with the collected primitive/count;
   - `SET_VERTEX_DATA2F_M` (`0x1880/0x1884`) decode for all 16 attributes;
   - `NV4097_INLINE_ARRAY` (`0x1818`) accumulation with the correct VTXFMT
     stride/count;
   - the draw-method gate fix (`0x1808/0x1814/0x1818/0x1824` are never dropped);
   - `GCM_DRAWPROBE=1`, a read-only probe for the guest context and the first
     draw-method words.
4. No synthetic draw is injected into the title frame. The D3D12
   `RSX_D3D12_SELFTEST` remains a separate, standalone device test.
5. Verification: windowed run should log
   `[D3D12] draw_arrays #0 prim=6 first=0 count=10` and a nonzero `draws`
   counter. Headless `GCM_DRAWPROBE=1` should log the `0x1884` sequence and
   `[RSX] IMMEDIATE prim=6 count=10`.
6. The first strip is **black/degenerate by state**, not by a missing draw:
   attr0 is positions only, constant attr3 is `(0,0,0,1)`, no UV/texture is
   supplied, and the VP's transform constants `c0..c3` are zero in the
   captured frame.
   `surface_clip=1440x1080` is not an offscreen target; `surf0=0x660000` is a
   registered display buffer, so this draw already targets the backbuffer.
   The black screen is consistent with this specific draw. A visible loading
   quad needs a later/fuller attribute stream (attr3 color, texcoords, texture,
   and non-zero transform constants).

---

## 1. The first-frame submission path

### 1.1 No HLE draw imports

`gt6/src/gen/ppu_hle_nids.cpp` registers GCM init/control/flip functions. A
search for `Draw`, `DrawArrays`, `DrawIndex`, `SetDraw` finds no HLE draw
entry point. The only GCM import on the frame tail is:

| guest stub | NID | HLE |
|---|---|---|
| `func_00F984B8` (`ppu_recomp_039.cpp:145928`) | `0x0B4B62D5` | `cellGcmSetPrepareFlip` |
| `func_00F984F0` | `0x15BAE46B` | `_cellGcmInitBody` |
| `func_00F98A30` | `0x21397818` | `_cellGcmSetFlipCommand` |

The draws are inline words, so the HLE draw hypothesis is ruled out.

### 1.2 The immediate-mode first frame (the real first draw)

`work/agent_rsx/run3.err:22399-22420` is the first frame's state block:

```
22399  [rsxm] method=0x1808 data=0x00000006   ; SET_BEGIN_END(6) = TRIANGLE_STRIP
22400  [rsxm] method=0x1880 data=0x00000000   ; DATA2F attr0 X
22401  [rsxm] method=0x1884 data=0x00000000   ; DATA2F attr0 Y  -> vertex 0
22402  [rsxm] method=0x1880 data=0x00000000   ; X
22403  [rsxm] method=0x1884 data=0x00000000   ; Y              -> vertex 1
...
22418  [rsxm] method=0x1880 data=0x00000000   ; X
22419  [rsxm] method=0x1884 data=0x00000000   ; Y              -> vertex 9
22420  [rsxm] method=0x1808 data=0x00000000   ; SET_BEGIN_END(0)
```

That is **20 data words = 10 vertices**. The values in the trace include
`0x44A00000` = 1280.0 and `0x44340000` = 720.0, i.e. 2D screen-space positions
for a ten-vertex strip. This is the first real draw, not a clear-only frame.

The other observed builders (`func_00B81C10` -> `0x40041814 DRAW_ARRAYS`,
`func_00B81D30` -> `0x40081824 DRAW_INDEX_ARRAY`) are array-based paths used
by later UI/3D draws. They are correct and supported, but they are not the
first frame.

### 1.3 Register encoding

| method | meaning |
|---|---|
| `0x1808` | `NV4097_SET_BEGIN_END`; data != 0 begins a primitive, data == 0 ends it |
| `0x1880 + attr*8` | `NV4097_SET_VERTEX_DATA2F_M` X for attribute `attr` |
| `0x1884 + attr*8` | the Y word for the same attribute; on **attr 0** this completes one immediate vertex |
| `0x1C00 + attr*16` | `NV4097_SET_VERTEX_DATA4F_M`; W (`lane 3`) completes an immediate vertex |
| `0x1818` | `NV4097_INLINE_ARRAY`; data words are a VTXFMT-packed vertex stream |
| `0x1814` | `NV4097_DRAW_ARRAYS`; data = `(count-1)<<24 | first` |
| `0x181C` / `0x1824` | index-array address / `DRAW_INDEX_ARRAY` |

The completion rule matches `rsx_dispatch.c:338-347`:
`0x1884` (DATA2F Y), `0x1C0C` (DATA4F W), `0x1508` (DATA3F Z), `0x1E40`
(DATA1F X), `0x1900` (DATA2S), `0x1940` (DATA4UB), `0x1984`/`0x0A84`. The legacy
decoder needs the same rule; GT6 only exercises `0x1884`.

---

## 2. What was wrong in the decoder

### 2.1 `0x1880/0x1884` were folded but never completed a vertex

The previous code did:

```c
state->vertex_data4f[idx][lane] = f;
return 0;
```

That is correct constant state, but inside `BEGIN_END` a `DATA2F` attr0 Y write
is also a vertex boundary. The FIFO walker therefore consumed all ten vertices,
reached `SET_BEGIN_END(0)`, and emitted no draw callback. This explains the
zero `[D3D12] draw_arrays` lines and the zero `draws` counter while the clear
and fence calls were present.

### 2.2 `0x1818 INLINE_ARRAY` was unknown

`rsx_dispatch.c` has a complete INLINE_ARRAY model for the draw engine, but the
legacy `rsx_process_method` path had no case. A title using inline geometry lost
the whole stream as "unknown method". GT6's current trace does not contain
`0x1818`, so this is a latent gap, not the first-frame cause.

### 2.3 Draw methods could be gated out

`gcm_3d_method()` only calls `rsx_process_method()` when
`legacy_state_live || gcm_legacy_method_has_effect(m)`, and the effect list did
not include `0x1808/0x1814/0x1818/0x1824`. In the current GT6 runs the legacy
state is live, so this was not the observed cause, but it is a real silent-drop
path for a draw-engine configuration.

### 2.4 The backend drops constant-attribute geometry with attr0 disabled

`d3d12_draw_arrays` / `read_rsx_vertex` only reads a position when
`state->vertex_attribs[0].enabled && type == 2 && size >= 2`. GT6's immediate
strip does not declare an attr0 array; it only writes the constant attr0
registers. The fix therefore redirects attr0 to a temporary float4 buffer for
the duration of the callback (see §3.1), so the backend sees an enabled,
readable position array.

---

## 3. Fixes implemented

### 3.1 Immediate-vertex accumulation and callback (`rsx_commands.c`)

- On `SET_BEGIN_END(prim)` inside `rsx_process_method`:
  `s_immediate_count = 0`.
- On `DATA2F` attr0 Y (`0x1884`) inside `BEGIN_END`:
  `rsx_immediate_push()` copies `state->vertex_data4f[0][0..3]` into
  `s_immediate[count++]`. `DATA4F` attr0 W (`0x1C0C`) does the same, matching
  `rsx_dispatch.c`.
- On `SET_BEGIN_END(0)`:
  `rsx_immediate_finish()`:
  1. logs `[RSX] IMMEDIATE prim=%u count=%u`;
  2. writes the collected float4 positions to the top of RSX local memory at
     offset `0x0FF00000` (64 KiB, big-endian, stride 16);
  3. re-states the render target (`set_render_target`) so the backend's
     `current_rsx_state` is this state even if the surface was already clean;
  4. saves `state->vertex_attribs[0]`, points it at that scratch buffer with
     `type=float32`, `size=4`, `stride=16`, `enabled=1`;
  5. calls `s_backend->draw_arrays(..., state->primitive_type, 0, count)`;
  6. restores the saved attr0;
  7. clears `s_immediate_count`.

Ordering: this happens while decoding the `0x1808 -> 0` word, before the report
DMA and fence methods that follow it in the guest stream. The normal
`SET_BEGIN_END` state flush has already run on the opening `0x1808`, so the
draw callback sees the same surface/viewport/shader state the guest set.

No `rsx_d3d12_backend.c` change is needed: the existing `draw_arrays` callback
already reads vertices through `state->vertex_attribs[0]`, and the temporary
buffer is presented through that same interface. This is the "temporary buffer"
option, not a new backend callback or a synthetic command.

Scratch risk: `0x0FF00000` is the top 64 KiB of the 256 MB local window. GT6's
first frame uses display buffers `0x0..0x01980000`, so there is no collision.
A later allocator-aware version should reserve this through the local-memory
map instead of hardcoding the tail.

### 3.2 `SET_VERTEX_DATA2F_M` (`0x1880/0x1884`)

`rsx_process_method` now decodes the full 16-attribute window:

```c
if (method >= 0x1880u && method < 0x1880u + RSX_MAX_VERTEX_ATTRIBS * 8u) {
    u32 idx  = (method - 0x1880u) >> 3;         /* attribute */
    u32 lane = ((method - 0x1880u) >> 2) & 1;   /* x or y */
    float f; memcpy(&f, &data, 4);
    state->vertex_data4f[idx][lane] = f;
    if (lane == 0) { state->vertex_data4f[idx][2] = 0.0f;
                     state->vertex_data4f[idx][3] = 1.0f; }
    if (idx == 0 && lane == 1) rsx_immediate_push(state);
    return 0;
}
```

The `lane == 0` reset matches `rsx_dispatch.c`'s `vtx_const_fold`. The
`0x1C00` `DATA4F` window now also calls `rsx_immediate_push()` on attr0
lane 3.

### 3.3 `NV4097_INLINE_ARRAY` (`0x1818`)

`rsx_process_method` accumulates the big-endian data words into a 64 KiB
buffer, reset at every `BEGIN_END(prim)`. At `BEGIN_END(0)` it computes:

- `packed` = sum of `rsx_vertex_attrib_size(type, size)` for every enabled
  attribute, in ascending attribute order;
- `declared` = maximum enabled attribute `stride`;
- `stride = declared ? declared : packed`;
- `count = inline_bytes / stride`.

This is the same rule as `rsx_vertex_inline_layout()` in
`rsx_vertex_compact.c` and `rsx_dispatch.c`'s INLINE_ARRAY model. The legacy
D3D12 `rsx_backend` has no inline-array sink, so the decode logs
`[RSX] INLINE_ARRAY prim= bytes= stride= count=` and increments
`g_rsx_inline_decoded`; the draw-engine path
(`RSX_LIVE_DRAW` / `PS3RECOMP_RSX_ENGINE=dispatch`) already has a sink and is
the path to use for a title that actually draws this way.

### 3.4 Gate fix

`gcm_legacy_method_has_effect()` now returns 1 for:

```c
case 0x1808u:   /* NV4097_SET_BEGIN_END */
case 0x1814u:   /* NV4097_DRAW_ARRAYS */
case 0x1818u:   /* NV4097_INLINE_ARRAY */
case 0x1824u:   /* NV4097_DRAW_INDEX_ARRAY */
```

No draw method can be silently skipped before `rsx_process_method`.

### 3.5 What the first immediate strip actually contains

The ten vertices from `run3.err:22400-22419` are a full-viewport 2D strip:

```
(0,0) (0,0) (1280,0) (1280,0) (1280,720) (1280,720)
(0,720) (0,720) (0,0) (0,0)
```

with duplicate vertices at the joins, i.e. a full 1280x720 quad. `GCM_DRAWPROBE`
now prints, per vertex:

```
[DRAWPROBE] vtx 0 pos=(0.000,0.000,0.000,1.000)
            col=(0.000,0.000,0.000,1.000) tc0=(0.000,0.000,0.000,1.000)
...
[DRAWPROBE] imm finish prim=6 count=10 surf0=0x660000 display=1
            clip=1440x1080 vp_bytes=... vp_load=0 fp=0x0FFFFDC0
            c0=... c1=...
            attr0(en=0 sz=0 ...) attr3(en=0 ... const=0.000,0.000,0.000,1.000)
            attr8(en=0 ... const=0.000,0.000,0.000,1.000)
```

This answers the open questions:

- **attr0 is positions only.** No `0x1898/0x189C` (attr3 x/y), no `0x1C30`
  color array, no texcoord array, and no texture bind appear between the
  opening `SET_BEGIN_END(6)` and `SET_BEGIN_END(0)`.
- **Color comes from the constant attribute 3**, which is `(0,0,0,1)` black.
  The five-instruction VP uploaded at `0x0B80` (before the surface setup)
  transforms attr0 by `c0..c3` and copies attr3 to `o[7]`/TEXCOORD0; it leaves
  COL0 at its default black. The trace's transform constants `c0..c3` are all
  zero (`run3.err:22343-22358`), so the VP-transformed position is also
  degenerate. The fragment program address is `0x0FFFFDC0` (`0x08E4`), not the
  VP.
- **No texture or UV.** attr8 constant is `(0,0,0,1)` and no texture unit is
  bound. There is nothing that could sample a loading image.
- **The 1440x1080 is `surface_clip`, not the render target.** GT6's colour
  surface offset is `0x660000`, which is registered as display buffer 1
  (`SetDisplayBuffer(id=1, offset=0x660000, ...)`). `cellGcmOffsetIsDisplay()`
  returns true, so `current_rt_off()` returns 0 (backbuffer). The
  `set_render_target(1440x1080)` line is just the clip size; the draw is not
  going to an offscreen 1440x1080 surface in this run. If a future run logs
  `display=0`, then the offscreen-to-swapchain path is the D3D12 fixer's issue.

**Owner's windowed evidence (16:43):** the title bar reported `draws: 1`; the
log had `[D3D12] draw_arrays #0..#2`, `set_render_target(1440x1080)`,
`set_shader fp_addr=0x0FFFFDC0 vp_load=0 output_mask=0x00004000`, blend and
depth disabled, and the window/screenshot was black. That is exactly the state
described above: the three callbacks are real draws, but each is the same
black full-screen immediate strip. The 1440x1080 value is the clip size, not
an offscreen target, and the strip has no color/UV/texture. It is not a
backend drop.

**Conclusion:** this particular first draw is a **full-screen black/blank
strip** (a fade/cover or degenerate placeholder), not a visible loading quad.
A black screen at this point is consistent with the guest's own state. Visible
content has to come from a later draw, or from a guest state that supplies a
non-black attr3/texcoord and a non-zero transform matrix.

### 3.6 `GCM_DRAWPROBE=1` (read-only)

`cellGcmSys.c` logs, once per context change:

```
[DRAWPROBE] ctx_out@0x016A8680 -> 0x0F800000 (begin=70000000 end=70010000 current=...)
            gt6@0x016A6200 (begin=... end=... current=...) hle=0x0F800000
```

On each new `put` it scans `[get, put)` and logs the first 16 headers whose
method is one of `0x1814/0x1818/0x181C/0x1824` (array draws/index) or
`0x1880/0x1884/0x1C00/0x1C0C` (immediate DATA2F/DATA4F), with subchannel, count
and up to four data words. `gcm_3d_method()` also logs the first 64 methods
that actually reach the decode gate:

```
[DRAWPROBE] method io=0x001234 m=0x1884 v=0x44340000
[DRAWPROBE] method io=0x001238 m=0x1808 v=0x00000000
```

No guest memory is written and no command is injected.

---

## 4. Exact addresses and encodings

### 4.1 Guest

| address | item |
|---|---|
| `0x007FA9A4` | `func_007FA9A4` — per-frame submit/present |
| `0x00B78788` | `func_00B78788` — frame flip (`SetPrepareFlip`) |
| `0x00B81C10` | `func_00B81C10` — `DRAW_ARRAYS` builder (`0x1814`) |
| `0x00B81D30` | `func_00B81D30` — `DRAW_INDEX_ARRAY` builder (`0x1824`) |
| `0x00B74198` | `func_00B74198` — array-draw wrapper |
| `0x00B73F20` | `func_00B73F20` — indexed-draw wrapper |
| `0x016A6200` | GT6 `CellGcmContextData` used by the builders |
| `0x016A8680` | `gCellGcmCurrentContext` out-pointer |
| `0x0F800000` | HLE `CellGcmContextData` from `cellGcmSetupContext` |
| `0x70000000` | HLE command buffer (IO 0, 64 KiB default ring) |

The immediate-mode sequence is generated by GT6's own inline libgcm code; its
exact writer is in the `0x00B7xxxx` range. The observable encoding is fixed by
`run3.err:22399-22420`.

### 4.2 Runtime

| location | item |
|---|---|
| `cellGcmSys.c:1950` | `cellGcm_rsx_process_fifo()` |
| `cellGcmSys.c:2136` | `gcm_rsx_process_fifo_unlocked()` |
| `cellGcmSys.c:1969` | `gcm_legacy_method_has_effect()` |
| `cellGcmSys.c:2084` | `gcm_drawprobe_pass()` |
| `rsx_commands.c:434` | `rsx_process_method()` |
| `rsx_commands.c:529` | `rsx_immediate_finish()` |
| `rsx_commands.c:943` | `SET_VERTEX_DATA2F_M` |
| `rsx_commands.c:968` | `SET_VERTEX_DATA4F_M` |
| `rsx_commands.c:1001` | `SET_BEGIN_END` / immediate finish |
| `rsx_commands.c:1062` | `NV4097_INLINE_ARRAY` |
| `rsx_commands.c:1079` | `NV4097_DRAW_ARRAYS` |
| `rsx_commands.c:1137` | `NV4097_DRAW_INDEX_ARRAY` |

---

## 5. Verification

### 5.1 Build

Owner's normal rebuild (not run here):

```powershell
powershell -File scripts/build-gt6.ps1
```

Both edited files were syntax-checked with the repo clang
(`-std=gnu17 -fsyntax-only`); no build or `gt6.exe` run was performed.

### 5.2 Headless: prove the immediate strip is decoded

```powershell
$env:PS3_HEADLESS='1'
$env:GCM_DRAWPROBE='1'
$env:GCM_METHOD_HIST='5'
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\rsx_drawprobe_headless.log
```

Expected around the first frame:

```
[DRAWPROBE] ctx_out@0x016A8680 -> 0x0F800000 (begin=70000000 ...)
[DRAWPROBE] method io=0x... m=0x1808 v=0x00000006
[DRAWPROBE] method io=0x... m=0x1880 v=0x...
[DRAWPROBE] method io=0x... m=0x1884 v=0x...
... (20 lines = 10 vertices)
[DRAWPROBE] vtx 0 pos=(0,0,0,1) col=(0,0,0,1) tc0=(0,0,0,1)
...
[DRAWPROBE] imm finish prim=6 count=10 surf0=0x660000 display=1
            clip=1440x1080 ... attr3(... const=0.000,0.000,0.000,1.000)
[RSX] IMMEDIATE prim=6 count=10 (DATA2F triangle strip)
```

`display=1` with `surf0=0x660000` means the draw targets the registered display
buffer, not an offscreen surface. `attr3 const=(0,0,0,1)` and
`tc0=(0,0,0,1)` mean the strip is black with no texture; that is a property of
this guest draw, not a decoder drop.

`[RSX] IMMEDIATE ... count=10` is the proof that the decoder collected the
strip. In headless there is no backend, so no `[D3D12]` line is expected.

### 5.3 Windowed: prove the backend callback fires

```powershell
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$env:GCM_DRAWPROBE='1'
$env:RSX_D3D12_SELFTEST='0'
$env:GCM_METHOD_HIST='5'
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\rsx_drawprobe_window.log
```

Expected:

```
[rsx] backend init OK -- window open
[RSX] IMMEDIATE prim=6 count=10
[DRAWPROBE] imm finish prim=6 count=10 surf0=0x660000 display=1
            clip=1440x1080 ... attr3(... const=0.000,0.000,0.000,1.000)
[D3D12] draw_arrays #0 prim=6 first=0 count=10
```

The title bar `draws` counter should become nonzero (it is set in
`render_frame()`), and `CELLMARK_DUMP`/`CELLMARK_BLINKDBG=1` can capture the
frame. The 10-vertex triangle strip should be the first draw, not a synthetic
one. **Do not expect visible content from it:** its attr3 constant is black and
its transform constants are zero in the captured frame. If the window is still
black after later draws, compare their `[DRAWPROBE] vtx`/`imm finish` lines:
they need a non-black `col`, a valid `tc0`/texture, and a non-zero `c0..c3` to
produce a visible quad.

### 5.4 Host-only unit check (performed)

`work/test_immediate.c` links `rsx_commands.c` with a fake `rsx_backend` and
exercises the exact first-frame sequence. It produced:

```
[RSX] IMMEDIATE prim=6 count=10
calls=1 prim=6 count=10 attr0_enabled=1 values=ok
inline_decoded=1
[RSX] INLINE_ARRAY prim=6 bytes=48 stride=16 count=3
```

This proves the decoder emits exactly one callback with `prim=6`, `count=10`,
an enabled temporary attr0, and the ten expected x/y values; the INLINE_ARRAY
path separately computes 3 vertices for 48 bytes at stride 16. The test is a
host harness only and does not run the game.

### 5.5 Negative controls

- `GCM_DRAWPROBE=0` produces no `[DRAWPROBE]` lines.
- `RSX_D3D12_SELFTEST=0` produces no `[SELFTEST]` lines and no synthetic frame.
- If `[RSX] IMMEDIATE` appears but no `[D3D12] draw_arrays`, the backend is
  missing/gated; check `[rsx] backend init` and `pipeline_ready`.
- If `[DRAWPROBE] method ... 0x1884` appears but `[RSX] IMMEDIATE` does not,
  `state->in_begin_end` was not set (no opening `0x1808` in the same drain) or
  the method arrived on a subchannel the walker did not route to 3D.

---

### 5.6 Handoff to the D3D12 backend owner

These are the backend-side points this decoder evidence raises; they do not
require an `rsx_d3d12_backend.c` edit from this investigation.

1. **`set_render_target(1440x1080)` is not an offscreen target by itself.**
   It prints `surface_clip_w/h`. The actual target is
   `current_rt_off()`, which returns 0 when
   `cellGcmOffsetIsDisplay(surface_color_offset[0])` is true. GT6's
   `0x660000` is display buffer 1, so this draw already targets the
   backbuffer. The backend owner should log/compare `rt_off` (or use
   `RT_OFFDBG=1`/`RT_SEQDBG=1`) before adding an offscreen composite path.
2. **If a run shows `display=0`**, then `rt_off=0x660000` and
   `d3d12_present` will not replay an offscreen-only batch. `RT_DISPLAY_BY_SIZE`
   cannot help because it compares `surface_clip_w/h` to the 1280x720 window,
   while GT6's clip is 1440x1080. The owner needs either a display-buffer match
   by registered offset (preferred) or an offscreen surface composite to the
   swapchain.
3. **Screen-space immediate positions need an NDC transform.** The strip is
   `0..1280` x `0..720`. The legacy `read_rsx_vertex` fallback treats values
   outside NDC as "fractional screen coords" (`frac(x)*2-1`), which maps
   0/1280/720 all to the same corner. If `vp_ucode_bytes < 16`, the backend
   must map with `state->viewport_w/h` or accept a decoder-provided NDC
   buffer. If the VP runs, `c0..c3` must be the ortho matrix; the captured
   frame has them zero, so the VP output is degenerate. The decoder probe now
   prints `vp_bytes`, `vp_load`, `fp`, `c0`, and `c1` at the draw.
4. **Color/UV is absent in this draw.** attr3 constant is black and attr8
   constant is zero; no texture unit is bound. A later draw with attr3/texcoord
   data is the one that can show content. Do not make the backend invent a
   visible color for this first strip: that would turn a black fade into a
   synthetic white flash.

---

## 6. Risks / limits

- **Scratch collision.** The temporary vertex buffer is the top 64 KiB of local
  memory (`0x0FF00000`). This is safe for GT6's first frame (display buffers end
  at `0x01980000`) but should become an allocator reservation before later
  frames use large VRAM.
- **Attr0 redirect only.** The immediate strip only supplies attr0. Other
  attributes keep their constant values; the legacy backend defaults colour to
  white when attr3 is disabled. A title that supplies colour through immediate
  `DATA2F` attr3 will need the same temporary-buffer treatment for attr3.
- **INLINE_ARRAY is decode-only on the legacy backend.** The draw-engine path
  has the sink; the D3D12 legacy backend does not. No GT6 trace uses it.
- **The self-test is separate.** `RSX_D3D12_SELFTEST` remains the standalone
  device test described in `docs/analysis/d3d12-draw-readiness.md`; it is not
  used as evidence of the guest draw.

---

## 7. Files changed

- `third_party/ps3recomp/libs/video/cellGcmSys.c`
  - `gcm_drawprobe_pass()` and its call in the drain
  - `gcm_legacy_method_has_effect()` keeps `0x1808/0x1814/0x1818/0x1824`
  - `gcm_3d_method()` per-method draw probe
- `third_party/ps3recomp/libs/video/rsx_commands.c`
  - `SET_VERTEX_DATA2F_M` (`0x1880/0x1884`) decode
  - immediate-vertex accumulation and `rsx_immediate_finish()`
  - `NV4097_INLINE_ARRAY` (`0x1818`) decode with VTXFMT stride/count
  - `g_rsx_immediate_draws`, `g_rsx_inline_decoded` counters
  - `RSX_DRAWDBG` logs for `DRAW_ARRAYS`/`DRAW_INDEX_ARRAY`
- `docs/analysis/rsx-first-draw-fix.md` (this report)
- `work/test_immediate.c` — host-only decode harness used for §5.4 (not part
  of the shipped build)
