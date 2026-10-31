# RSX first-draw check — GT6 (BCUS98296)

**Date:** 2026-10-31
**Checker scope:** read-only static review plus the existing logs. No `gt6.exe`
run, no build, no source edits.
**Verdict:** **FAIL** for the question "is GT6 submitting a real draw?".
No real guest draw is observed or proved. The fixer's
`RSX_D3D12_SELFTEST` is a valid **synthetic device-path** test, but it
deliberately bypasses the FIFO, the guest command stream and guest memory, so it
cannot stand in for a guest draw. The immediate `SetPrepareFlip` change is a
present workaround, not a draw fix.
**Diagnostic verdict:** PASS as a synthetic D3D12 device test; FAIL as evidence
of a guest draw.

---

## 1. What was checked

- Guest imports and the lifted draw builders in `gt6/generated/`.
- The runtime FIFO walker and `rsx_process_method` method decode in
  `third_party/ps3recomp/libs/video/cellGcmSys.c` and `rsx_commands.c`.
- The D3D12 backend registration, state callbacks and draw callback in
  `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`.
- The fixer's current uncommitted changes:
  `git -C third_party/ps3recomp diff -- libs/video/rsx_d3d12_backend.c …`
  (`RSX_D3D12_SELFTEST`, added at 16:15; `cellGcmSetPrepareFlip` immediate
  fallback was already present earlier).
- Logs:
  - `work/fix_run.err` / `work/fix_run.log` — headless 70 s run.
  - `work/gt6.log` — windowed run with the D3D12 backend.
  - `work/agent_rsx/run3.err` — `RSX_TRACE=1200` headless run.
  - `work/agent_rsx/run2.log` — drain/flip timeline.

---

## 2. GT6's actual draw submission path

GT6 does **not** appear to submit draws through an HLE `cellGcmSetDraw*` import.
The GCM imports observed on this path are flip/label/control helpers; the draw
itself is inline. The frame-tail HLE call is the flip:

- `func_00F984B8` is an import stub:
  `ps3_hle_call(0x0B4B62D5u, ctx)` —
  `gt6/generated/ppu_recomp_039.cpp:145928`. NID `0x0B4B62D5` is
  `cellGcmSetPrepareFlip`.
- `func_00B78788` (`gt6/generated/ppu_recomp_026.cpp:142885`) loads the context
  at `0x016A6200`, reads `current` from `ctx+8`, calls the flip stub, then
  appends the report-DMA command `0x000401A8 / 0xFEED0001` and advances
  `current`. That is the flip/report tail, not a draw.

GT6's draws are **inline NV4097 words** written by GT6's statically linked
libgcm into its own `CellGcmContextData`:

- `func_00B81C10` (`gt6/generated/ppu_recomp_027.cpp:22647`) constructs
  `0x00041808` (`NV4097_SET_BEGIN_END`) at line 22676 and `0x1814`
  (`NV4097_DRAW_ARRAYS`) at line 22682, then writes the primitive and the packed
  draw value.
- `func_00B81D30` (`.../ppu_recomp_027.cpp:22750`) constructs
  `0x00041808`, `0x0004181C` (`NV4097_SET_INDEX_ARRAY_ADDRESS`) and
  `0x00041824` (`NV4097_DRAW_INDEX_ARRAY`) at lines 22777/22783/22784.
- `func_00B74198` (`.../ppu_recomp_026.cpp:136624`) calls `func_00B81C10`;
  `func_00B73F20` (`.../ppu_recomp_026.cpp:136427`) calls `func_00B81D30`.
- The UI list renderers call `func_00B74198` with primitives 2/3/4
  (LINES / LINE_LOOP / LINE_STRIP), first=0 and a count, e.g.
  `func_0004A570` at `gt6/generated/ppu_recomp_000.cpp:69032`,
  `func_0004A834` at `.../ppu_recomp_000.cpp:69216`.
- `func_00B78788` is called from the frame setup `func_007FA9A4`
  (`gt6/generated/ppu_recomp_018.cpp:19856`) after the surface/clear/VP state;
  the UI draw builders are separate functions reached when the UI list is built.

So the submission path is:

```
guest UI list -> func_00B74198 / func_00B73F20
              -> func_00B81C10 / func_00B81D30
              -> inline NV4097 words at ctx->current
              -> guest publishes put (or the runtime does)
              -> cellGcm_rsx_process_fifo -> gcm_3d_method
              -> rsx_process_method -> backend->draw_arrays/draw_indexed
```

This is consistent with the source comments in `rsx_commands.c:434-982`.

---

## 3. Why no draw is observed in the current runs

### 3.1 The drained first frame contains no draw method

`work/agent_rsx/run3.err:22292` shows the first frame's black clear
(`CLEAR_SURFACE mask=0xF0 color=0xFF000000`). At lines 22399-22420 the method
stream then contains:

```
0x1808 = 0x00000006     ; SET_BEGIN_END, primitive TRIANGLE_STRIP
0x1880 / 0x1884 …       ; SET_VERTEX_DATA2F_M pairs (current vertex data)
0x1808 = 0x00000000     ; SET_BEGIN_END, end
0x01A8 = 0xFEED0001     ; report DMA
0x1D6C / 0x1D70         ; fence label
```

There is **no `0x1814`, `0x1818`, `0x181C` or `0x1824`** anywhere in the trace:

```
run3.err 0x1814: 0   0x1818: 0   0x181C: 0   0x1824: 0
fix_run.err same: 0   0          0          0
gt6.log same:     0   0          0          0
```

`work/fix_run.err` has six `CLEAR_SURFACE` events (lines 14917, 35729, 49608,
63412, 77351, 91164) and twelve `[takeflip]` presents (first at line 506), and
zero `DRAW_ARRAYS`/`draw_arrays`. `work/gt6.log` shows the backend's state
callbacks (`set_render_target`, `set_blend`, `set_depth_stencil`, `set_shader`,
`set_vertex_attribs` at lines 472/492/512/522/527) and zero draw callbacks.
`[D3D12] draw_arrays` is printed unconditionally for the first 20 draws in
`d3d12_draw_arrays` (`rsx_d3d12_backend.c:7396-7398`), so its absence is a real
"callback never happened", not a logging threshold.

### 3.2 The guest is still in the loading/UI path

The current run reaches the boot script, opens `GT.VOL`, loads the UI assets
that exist, then requests `products/gt6/script/Prototypes.adc`, which is absent;
the VM spins in `HOTREAD8` at `func_009E191C` (see
`docs/analysis/CONTINUE-HERE.md:104-113`). The frame loop at this point is a
clear-only loading screen: surface setup, black clear, a `SET_BEGIN_END` state
block, report/fence, flip. It has not built the UI draw list, so it never calls
`func_00B74198`/`func_00B81C10`.

That is the primary explanation for "0 draws": **the guest submitted no draw
command**, not that the backend dropped one. The method stream proves the
runtime was reading the stream GT6 wrote for this frame (surface/clear/VP/vertex
data all appear), so the walker and method decode are alive.

### 3.3 The separate-ring claim is not verified

`docs/analysis/rsx-first-frame.md` and the comment in
`cellGcmSys.c:3217-3225` say GT6's context uses an RSX IO address
`0x70ABE44C` that the runtime ring does not see. The only `[CTX]` line in the
on-disk logs is:

```
work/agent_rsx/run2.log:1
[CTX] gCellGcmCurrentContext@0x016A8680 -> 0x0F800000  begin=70000000
      end=70010000 current=70000004 callback=0F800010  (ours=0x0F800000)
```

That probe (`cellGcmSys.c:2110-2121`) reads `s_gcm_ctx_out_ea` (the HLE
context), **not** GT6's context at `0x016A6200`. No log on disk proves
`0x70ABE44C`. Meanwhile the run3 trace shows GT6's inline methods being
drained, which is evidence the frame stream and the runtime ring are at least
partly the same. The claim may still be true for the draw builder's context, but
it needs a direct probe before it is used to justify an immediate flip or a
separate draw path.

### 3.4 Latent method-decode gaps found while checking

These do not explain the present 0-draw frame (no draw was submitted), but they
will break the first real draw if GT6 uses these paths:

- **`0x1880` / `0x1884` (`NV4097_SET_VERTEX_DATA2F_M`) are not handled.**
  `rsx_process_method` handles only the `0x1C00` (`SET_VERTEX_DATA4F_M`) window
  (`rsx_commands.c:799-819`); its own comment says to add the other encodings
  "if a title needs them". GT6's first frame already writes `0x1880/0x1884`
  (run3.err:22400-22419), and GT6's command builder at
  `ppu_recomp_026.cpp:93353`/`93462`/`93513`/`93719` emits `0x1880` headers.
  Those words currently fall through to "unknown method" and are lost. The
  backend would then read default/zero vertex constants.
- **`0x1818` (`NV4097_INLINE_ARRAY`) is not handled.** The hardware encoding is
  listed in `third_party/ps3recomp/docs/rsxfifo.txt`; `rsx_process_method` has
  cases for `0x1814` and `0x1824` (`rsx_commands.c:892-946`) but none for
  `0x1818`. No `0x1818` header was found in the current GT6 trace, so this is a
  latent gap, not the current cause.
- The runtime does handle `0x1814` and `0x1824`, so the two observed GT6 draw
  builders are not inherently undecodable.

---

## 4. Review of the fixer's diagnostic / fix

### 4.1 What was added

Uncommitted changes in `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c`:

- `RSX_D3D12_SELFTEST` support, including `selftest_shot()`
  (`rsx_d3d12_backend.c:6079`), `rsx_d3d12_backend_selftest()` (line 6148),
  readback tiles (lines 5695-5824), synthetic vertex fetch in
  `read_rsx_vertex`/`read_vp_vertex`, and the trigger at backend init
  (lines 8072-8075). Declared in
  `rsx_d3d12_backend.h`.
- No corresponding change to `cellGcmSys.c` or `rsx_commands.c` for the draw
  stream, and no guest-context probe.

### 4.2 Does it prove a real guest draw?

**No — it is explicitly synthetic.** Its own comment says it proves the D3D12
half "WITHOUT the FIFO, the guest command stream, or a title". It:

- builds a synthetic `rsx_state` (`s_selftest_state`) and a fixed clip-space
  triangle;
- bypasses guest vertex fetch (`read_rsx_vertex`/`read_vp_vertex` return
  `s_selftest_pos` when the state is the selftest state);
- calls the `rsx_backend` callbacks directly (`clear -> set_render_target ->
  set_vertex_attribs -> set_shader -> draw_arrays -> render_frame`);
- reads back a 32x32 clear tile and a 32x32 centre tile and prints
  `[SELFTEST] … PASS/FAIL`.

By inspection the test is structurally sound: it exercises clear, state
callbacks, the draw callback, `render_frame` replay, and readback. The checker
did not execute it (no build/run), so the reference PASS in the fixer's doc is a
claim to reproduce. If it does pass, it proves the D3D12 device, clear, PSO, both
vertex paths and readback work. It says nothing about whether GT6 wrote a
`0x1814`/`0x1824` into the drained stream, whether `rsx_process_method` decoded
it, or whether the guest's vertex/constants were valid. The host harness
`tools/patches/rsx_d3d12_selftest_host.c` runs the same synthetic test outside
the emulator; it is useful for device validation and is equally not a guest-draw
proof.

**Verdict for this diagnostic: PASS as a synthetic device test; FAIL as proof of
the guest draw path.** It must not be cited as "draws now work".

### 4.3 Does it alter rendering state or mask missing draws?

It is env-gated (`RSX_D3D12_SELFTEST`), and with the variable unset normal
rendering is unchanged. When enabled it does temporarily alter state:

- `s_selftest_active` suppresses guest compositing (`composite_present` returns
  early, `rsx_d3d12_backend.c:4350`), guest framebuffer presentation
  (`guest_fb_present` returns early, line 4408) and the `CLEAR_RGB` override
  (line 6312). That is correct for an isolated test, but it means the test does
  not exercise the guest framebuffer/compositing path.
- `selftest_shot` saves/restores `current_rsx_state`, `tex_bound`, `tex_ready`
  (VP only) and `clear_color`, and resets `draw_count`/VB offsets. It calls
  `be->present`, which runs `render_frame()` and toggles `s_d3d.vp_parity`; if only the
  legacy shot runs (VP skipped because a guest VP already exists, or
  `RSX_D3D12_SELFTEST_VP=0`), parity is left flipped.
- `selftest_release_vp()` releases the VP PSOs/VS blobs and bumps `vp_gen`
  after the VP shot. At startup, before the title has a VP, this is safe; if the
  test is ever called later it can invalidate a guest VP pipeline.
- The test leaves its synthetic triangle in the backbuffer in `PRESENT` state
  without calling `Present`. The next guest clear/present normally overwrites
  it, but a first present that does not clear could briefly show the test
  triangle.

It does **not** fake the guest draw count: `render_frame()` resets
`draw_count`, and the guest's draw counter stays zero. But a reader who sees
`[SELFTEST] RESULT: PASS` and `[D3D12] selftest: PASS` can mistake it for a
guest-draw success. That is the main "masking" risk: the log needs to say
"synthetic; guest draw not tested", and the report must keep the two results
separate.

Two robustness gaps in the selftest itself:

- The same readback resource is reused for the legacy and VP shots. If the VP
  shot's copy did not execute, the map can return the legacy shot's white centre
  tile and the VP subtest can false-pass. A sentinel clear of the readback (or a
  fresh resource per shot) would make the check strict.
- `selftest_shot` resets `draw_count` and the vertex-buffer offsets without
  saving them. That is safe only at startup before any guest frame, which is
  where `rsx_d3d12_backend_init` runs it (lines 8072-8075); the public API
  should not be called mid-frame without documenting that restriction.

### 4.4 The immediate `SetPrepareFlip` fallback

`cellGcmSetPrepareFlip` (`cellGcmSys.c:3208-3237`) currently does:

```c
(void)ctx;
s32 rc = cellGcmSetFlipCommand(bufferId);
return (rc == CELL_OK) ? (s32)bufferId : rc;
```

This is the only "fix" in the tree related to the frame loop. It:

- sets `s_flip_pending`, `s_flip_direct_pending`, `s_flip_status` and
  `s_flip_request_count` via `gcm_flip_request` (`cellGcmSys.c:3105-3110`);
- does **not** write `0x0004FEAC` + `bufferId` into `ctx->current`;
- does **not** advance `ctx->current` or publish `put`;
- invokes the guest flip handler at request time (the existing compatibility
  wart; `GCM_FLIPCB_ONTICK=1` can defer it);
- presents whatever the drain has already executed, out of order relative to
  the guest's frame tail;
- returns `bufferId` (closer to libgcm than `CELL_OK`), but the second
  `return cellGcmSetFlipCommand(bufferId);` is unreachable, and the comments
  above it describe a queue/publish implementation that is not there.

This is a present-gate workaround, not a flip-in-stream fix. It makes a
clear-only batch look like a working present (`[takeflip]` every frame), which
is exactly the kind of masking the checker must flag. `gcm_flip_into_fifo`
(`cellGcmSys.c:3147-3183`) is the existing correct shape; it is not used here.

### 4.5 The companion readiness doc overclaims

The fixer's `docs/analysis/d3d12-draw-readiness.md` is useful as a callback
audit, but two statements should not be carried into the verdict:

- Lines 9-10: "A validated `rsx_process_method(NV4097_DRAW_ARRAYS)` reaches
  `d3d12_draw_arrays`". The selftest does **not** call `rsx_process_method`; it
  calls the registered `rsx_backend` callbacks directly (`selftest_shot` at
  `rsx_d3d12_backend.c:6079`, which now calls `be->present(be->userdata, 0)` at
  line 6124). The dispatch through `rsx_commands.c` is still unexercised.
- Lines 17-22 conclude the failure is "upstream" of the backend. That is the
  right direction, but the doc does not identify the specific evidence we found
  (no `0x1814`/`0x1824` in the drained first frame; `0x1880` unhandled). Treat
  it as a hypothesis, not a completed diagnosis.
- Lines 146-154 quote a reference `[SELFTEST]` PASS. No `[SELFTEST]` line
  exists in `work/gt6.log`, `work/fix_run.err` or `work/fix_run.log`; the quote
  may come from the separate host harness, but it is not in the checked-in
  logs. It is a claim to reproduce, not evidence already on disk.

The doc's callback audit (the `present` display gate, the VP pass gate, the
fallback-PS issue) is otherwise a good checklist for the first real draw.

### 4.6 `GCM_GUEST_FB` still masks the real framebuffer

Contrary to `docs/analysis/rsx-first-frame.md`, `gt6/src/main.cpp:593` still
forces:

```c
if (!getenv("GCM_GUEST_FB")) _putenv_s("GCM_GUEST_FB", "0,1280,720,6144");
```

`guest_fb_present` (`rsx_d3d12_backend.c:4414-4448`) then copies RSX local
memory offset 0 over the rendered backbuffer at `render_frame`
(`rsx_d3d12_backend.c:5693`). GT6 flips buffers 1/2/3 (offsets `0x660000`,
`0xCC0000`, `0x1320000`), so this default copies the wrong buffer over any real
draw. The selftest suppresses this copy (`s_selftest_active`), but a real guest
draw would be overwritten. Any first-draw diagnostic must run with
`GCM_GUEST_FB` **unset**; otherwise a black/blank result is expected and is not
evidence about the draw.

---

## 5. D3D12 backend boundary

The boundary is wired correctly in the normal sense:

- `rsx_d3d12_backend_init` fills `s_d3d12_backend`, registers
  `draw_arrays`/`draw_indexed` and all state callbacks, and calls
  `rsx_set_backend(&s_d3d12_backend)` at
  `rsx_d3d12_backend.c:8059-8063`.
- `rsx_process_method` receives an `rsx_state*`, and for `NV4097_DRAW_ARRAYS`
  calls `s_backend->draw_arrays(s_backend->userdata, state->primitive_type,
  first, count)` at `rsx_commands.c:915-917`. `NV4097_DRAW_INDEX_ARRAY` calls
  `draw_indexed` at lines 941-944.
- `d3d12_draw_arrays` uses `s_d3d.current_rsx_state`; the state callbacks
  (`d3d12_set_render_target`, `d3d12_set_shader`,
  `d3d12_set_vertex_attribs`) set that pointer (`rsx_d3d12_backend.c:6426,
  7919, 7951`). `SET_BEGIN_END` flushes the dirty state before the draw
  (`rsx_commands.c:840-889`), so a normal guest sequence supplies a valid
  state pointer.
- `d3d12_draw_arrays` logs every early call and records a draw record; its
  absence from the logs means the callback was not invoked.

**Caveat:** the selftest calls the backend callbacks directly with a synthetic
state and synthetic vertices, so it only proves the signature and the D3D12
side are usable. It does not prove that a real `rsx_state` from the FIFO and
guest vertex fetch produce correct vertex data. The real path is unexercised
because no draw reached it. There is no observed state-pointer mismatch; the
only mismatch is that the claimed separate guest context is not probed.

One boundary coupling is worth flagging: `draw_arrays` does not carry the
`rsx_state*`, so `d3d12_draw_arrays` uses `s_d3d.current_rsx_state` set by the
last state callback. A guest `DRAW_ARRAYS` that arrives without a preceding
`SET_BEGIN_END`/state flush would use a stale pointer. GT6's observed first
frame does issue `0x1808`, so this is not the current blocker, but it is a
reason to keep the state-flush ordering in the probe.

---

## 6. Exact expected first draw command

The deterministic part is the method encoding:

```
0x00041808  <primitive>              ; NV4097_SET_BEGIN_END
0x00041814  ((count - 1) << 24) | first   ; NV4097_DRAW_ARRAYS
```

or, for the indexed builder:

```
0x00041808  <primitive>              ; NV4097_SET_BEGIN_END
0x0004181C  <index array address>    ; NV4097_SET_INDEX_ARRAY_ADDRESS
0x00041824  ((count - 1) << 24) | first   ; NV4097_DRAW_INDEX_ARRAY
```

`func_00B81C10` constructs the first form at `ppu_recomp_027.cpp:22676` and
`:22682`; `func_00B81D30` constructs the second at `:22777`, `:22783`, `:22784`.
The GT6 UI list callers pass primitives 2/3/4 (LINES/LINE_LOOP/LINE_STRIP),
first=0, with the count coming from `func_002A4F1C` (e.g.
`ppu_recomp_000.cpp:69028-69032`). The first frame's state block uses primitive
6 (TRIANGLE_STRIP), so a full-screen quad draw would be
`0x00041808 0x00000006` followed by `0x00041814 <value>`.

The **exact data value** (`first`/`count`) is not determinable from the current
logs: no `0x1814`/`0x1824` word was captured, and the UI list count comes from
the missing `Prototypes.adc` data. Do not invent a value; log it when the guest
first emits the header.

The only concrete candidate visible in the first frame is the full-screen quad
state: `SET_BEGIN_END(6)` plus four 2F vertex updates. If that quad is later
submitted as `DRAW_ARRAYS` with primitive 6, first 0 and four vertices, the
pair would be:

```
0x00041808  0x00000006     ; triangle strip
0x00041814  0x03000000     ; count-1=3 in [31:24], first=0 in [23:0]
```

That is a **candidate**, not observed. The trace ends at `0x1808=0` and the
fence; no `0x1814` follows.

---

## 7. Safest next step

1. **Do not** add a synthetic draw to the title's frame and do not use
   `RSX_D3D12_SELFTEST` PASS as evidence that GT6 draws. Keep it as a separate
   device-path check.
2. Add an env-gated **guest draw probe** (no rendering change):
   - in `cellGcm_rsx_process_fifo`, when `GCM_FIRSTDRAW=1`, log the first
     `0x1814`/`0x1818`/`0x1824` with `get`, `put`, primitive, first, count and a
     64-byte dump around it;
   - log GT6's context at `0x016A6200` (`begin/end/current`) when `current`
     changes, in addition to the existing HLE `[CTX]` probe;
   - log whether the word came from the PPU ring or an SPU pushbuffer
     (`gcm_spu_block_for_put`).
3. Fix the decode gaps before judging pixels:
   - add `NV4097_SET_VERTEX_DATA2F_M` (`0x1880..0x18FF`) handling to
     `rsx_commands.c`, mapping `(method - 0x1880) >> 3` to the attribute and
     `((method - 0x1880) >> 2) & 1` to x/y, defaulting z/w to 0/1;
   - add `NV4097_INLINE_ARRAY` (`0x1818`) handling, or at minimum log it as an
     unhandled draw method.
4. Fix the real blocker for the draw: the missing UI asset
   (`products/gt6/script/Prototypes.adc`) / the PFS read path, so the guest
   builds the UI draw list and calls `func_00B74198`. The selftest cannot
   substitute for this.
5. Rerun with:
   `PS3_HEADLESS=1 PS3_VERBOSE=1 GCM_DRAINDBG=1 GCM_CTXDBG=1 RSX_TRACE=4000
   RSX_VTXDBG=64 RSX_LIVE_FEED_DBG=1`
   and **without** `GCM_GUEST_FB`. Expect a `[RSX] DRAW_ARRAYS` or
   `[D3D12] draw_arrays`, a `put` advance, and then judge the image.
6. If the draw is written to a stream the drain does not see, implement the
   proper stream publication/flip handling (the `0xFEAC` path or the guest
   context's ring). Do not present a synthetic frame as a fix.

---

## 8. PASS/FAIL summary

| Check | Result | Evidence |
|---|---|---|
| GT6 draw path identified as inline NV4097 (not HLE) | **PASS** | `func_00B81C10`/`func_00B81D30` build `0x1808`+`0x1814`/`0x181C`+`0x1824`; only the flip uses HLE NID `0x0B4B62D5` |
| Real guest draw observed in current logs | **FAIL** | 0 `0x1814/0x1818/0x181C/0x1824` in `run3.err`, `fix_run.err`, `gt6.log`; backend logged no `draw_arrays` |
| D3D12 backend registered and draw callback wired | **PASS** | `rsx_set_backend` at `rsx_d3d12_backend.c:8063`; `rsx_process_method` calls `draw_arrays` at `rsx_commands.c:916` |
| Backend receives a valid **real** `rsx_state` and vertex data | **UNPROVEN** | no real draw reached the callback; selftest is synthetic and bypasses guest fetch |
| Selftest is a valid synthetic device test | **PASS (by inspection; not executed here)** | fixed triangle, readback clear/centre checks, `[SELFTEST] PASS/FAIL` |
| Selftest proves a guest draw | **FAIL** | it explicitly bypasses FIFO, guest stream and guest memory |
| Immediate `SetPrepareFlip` is a correct flip fix | **FAIL** | presents already-drained batch out of order; no `0xFEAC` in guest stream; unreachable second return |
| Method decode covers GT6's methods | **FAIL** | `0x1880/0x1884` and `0x1818` unhandled; `0x1814/0x1824` handled |
| Exact first draw method determinable | **PASS (method only)** | `0x00041808` + primitive, then `0x00041814` or `0x00041824`; exact value not in logs |
| `GCM_GUEST_FB` can mask real draws | **FAIL (risk)** | default at `main.cpp:593`; copy at `rsx_d3d12_backend.c:5693` |

**Bottom line:** the backend is ready enough to draw, the walker is alive, but
GT6 has not submitted a draw yet and the fixer's selftest only proves the
synthetic D3D12 path. The next run must prove a guest `0x1814`/`0x1824` in the
drained stream (or find the stream that carries it), with `GCM_GUEST_FB` off.
