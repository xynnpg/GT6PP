# RSX first draw: submission path, why 0 draws, and the FIFO self-test

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296`, `work/bin/EMAIN.elf`, `gt6/build/gt6.exe`
**Scope:** static analysis of the lifted guest draw builders plus the existing
headless/windowed logs. Source changes are limited to
`third_party/ps3recomp/libs/video/cellGcmSys.c` and
`third_party/ps3recomp/libs/video/rsx_commands.c`. `rsx_d3d12_backend.c`,
`gt6/generated` and `gt6/src/main.cpp` were not edited.

**Companion report:** `docs/analysis/d3d12-draw-readiness.md` proves the D3D12
half with an in-backend triangle self-test. This report answers the upstream
question: *does GT6 ever put a `DRAW_ARRAYS` into the FIFO, and if not, why?*

---

## TL;DR

1. **GT6 does not use the HLE draw imports.** The title imports only GCM
   init/control/flip entry points. Draws are inline NV4097 method words emitted
   by GT6's own statically linked libgcm code at `0x00B6Fxxx..0x00B81xxx`.
   The `DRAW_ARRAYS` and `DRAW_INDEX_ARRAY` builders are `func_00B81C10` and
   `func_00B81D30`; their common wrappers are `func_00B74198` / `func_00B74214`.
2. **No draw has been submitted yet.** Every captured frame contains
   `SET_BEGIN_END`, surface/viewport setup, the clear, and fences, but no
   `0x1814`/`0x1824` word. The walker is following the right ring and the
   decoder handles both methods. The missing piece is guest-side: the frame's
   draw list is empty while the script/UI is stalled at `func_009E191C`.
3. **A real latent drop gate was fixed.** `gcm_legacy_method_has_effect()`
   did not list `SET_BEGIN_END`, `DRAW_ARRAYS` or `DRAW_INDEX_ARRAY`, so a
   configuration that turns the legacy state path off could silently drop the
   only methods that produce a draw. They are now always forwarded.
4. **`RSX_FIFO_SELFTEST=1|2`** injects a synthetic, hardware-encoded
   `ATTR0 -> BEGIN_END -> DRAW_ARRAYS -> BEGIN_END` block into the real title
   FIFO through the real `put`, and `RSX_DRAWDBG=1` logs the decoder dispatch.
   This separates "guest never submitted" from "walker/decoder/backend lost it"
   without running a build and without faking game rendering.

---

## 1. GT6's actual draw submission path

### 1.1 No HLE draw imports

`gt6/src/gen/ppu_hle_nids.cpp` registers the GCM entry points the harness
provides. A search for `Draw`, `DrawArrays`, `DrawIndex` and `SetDraw` returns
nothing. The only GCM import on the frame path is:

| guest stub | NID | HLE |
|---|---|---|
| `func_00F984B8` (`ppu_recomp_039.cpp:145928`) | `0x0B4B62D5` | `cellGcmSetPrepareFlip` |
| `func_00F984F0` | `0x15BAE46B` | `_cellGcmInitBody` |
| `func_00F98A30` | `0x21397818` | `_cellGcmSetFlipCommand` |

There is no `cellGcmSetDrawArrays` / `cellGcmSetDrawIndexArray` import stub in
the lifted code and no unresolved NID in the logs that matches a GCM draw
export. Therefore the "HLE draw" hypothesis is ruled out.

### 1.2 The inline builders and their exact encoding

GT6's own libgcm lives at `0x00B70000..0x00B83000`. The draw builders are
plain guest code that reserve space in the `CellGcmContextData` at
`0x016A6200` (`current` at `+8`, `end` at `+4`) and write NV4097 words:

| address | function | role |
|---|---|---|
| `0x00B74198` | `func_00B74198` | wrapper: `func_00B81C10(ctx=0x016A6200, r4, r5, r6)` |
| `0x00B74214` | `func_00B74214` | wrapper: `func_00B81E60` (invalidate + begin/end state) |
| `0x00B81C10` | `func_00B81C10` | emits `DRAW_ARRAYS` (`0x1814`) |
| `0x00B81D30` | `func_00B81D30` | emits `SET_INDEX_ARRAY_ADDRESS` + `DRAW_INDEX_ARRAY` (`0x1824`) |
| `0x00B81E60` | `func_00B81E60` | `SET_INVALIDATE` + `SET_BEGIN_END` |
| `0x00B82070` | `func_00B82070` | `SET_BEGIN_END(0)` |
| `0x00B78788` | `func_00B78788` | frame flip: appends report DMA, calls `cellGcmSetPrepareFlip` |
| `0x007FA9A4` | `func_007FA9A4` | per-frame submit/present entry (calls `0x00B78788`) |

`func_00B81C10` as lifted/disassembled (`0x00B81C10..0x00B81CD0`) writes a
state-invalidate block, then `SET_BEGIN_END`, then one `DRAW_ARRAYS` header
followed by one data word per 256-vertex packet:

```
current+0x00 : 0x400C1714   ; type 2, count 3, method 0x1714 (invalidate)
current+0x04 : 0
current+0x08 : 0
current+0x0C : 0
current+0x10 : 0x00041808   ; type 0, count 1, method 0x1808 (SET_BEGIN_END)
current+0x14 : r4           ; primitive passed by the caller (4 at one site)
current+0x18 : 0x40041814   ; type 2, count 1, method 0x1814 (DRAW_ARRAYS)
current+0x1C : (count-1)<<24 | first
...
```

For a draw of fewer than 256 vertices (`r6 < 256`) the header is exactly
`0x40041814`: a **type 2 (non-increasing)** header with count `1`, one data
word, method `0x1814`. For larger draws the count field becomes
`(r6 >> 8) + 1` and the builder appends that many data words, each with
`first` advanced by 0x100 in the low 24 bits:

```
header = 0x40000000 | (((r6 >> 8) + 1) << 18) | 0x1814
data_i = ((r6 - 1) & 0xFF) << 24 | (i << 8)   ; i = 0..(r6>>8)
```

The walker's count field means "number of data words", so this matches the
runtime convention used by `host_posix.c` and every FIFO test
(`(1u << 18) | method`). The 3-vertex self-test below uses the count-1 form.

`func_00B81D30` emits the indexed equivalent. The exact words from
`0x00B81D30` are:

```
current+0x00 : 0x0008181C   ; type 0, count 2: SET_INDEX_ARRAY_ADDRESS pair
current+0x04 : index DMA / address
current+0x08 : index offset
current+0x0C : 0x00041808   ; SET_BEGIN_END
current+0x10 : r4           ; primitive
current+0x14 : 0x40081824   ; DRAW_INDEX_ARRAY, type 2, count 1
current+0x18 : (count-1)<<24 | first
```

Both builders reserve space through the guest context's `current` and publish
the ring through the control register's `put`; there is no second private
command queue in this path. The `func_00B74198` call sites are in the game's
renderer (`ppu_recomp_000.cpp:69032` and dozens more), so the only question is
whether the renderer reaches them.

### 1.3 The walker and decoder already support these commands

`cellGcm_rsx_process_fifo()` (`cellGcmSys.c:1950`) walks the ring published in
`GCM_CONTROL_GUEST_ADDR+0`. For type 0/2 it extracts
`count=(w>>18)&0x7FF`, `method=w&0x1FFC`, `subch=(w>>13)&7`, and hands each
data word to `gcm_3d_method()` -> `rsx_process_method()`.
`rsx_process_method()` (`rsx_commands.c:434`) has:

- `NV4097_SET_BEGIN_END` (`0x1808`) -> flush dirty state, set
  `state->primitive_type`, `state->in_begin_end`, increment `begin_epoch`;
- `NV4097_DRAW_ARRAYS` (`0x1814`) -> `s_backend->draw_arrays(...)`;
- `NV4097_DRAW_INDEX_ARRAY` (`0x1824`) -> `s_backend->draw_indexed(...)`.

The header encoding in §1.2 decodes to exactly those methods. There is no
encoding mismatch.

---

## 2. Why no draw is observed

### 2.1 The evidence

`work/fix_run.err` (headless, 15:27) contains:

```
[rsx] backend init skipped -- headless
6 x [RSX] CLEAR_SURFACE mask=0xF0 color=0xFF000000
12 x [takeflip] 1 (present)
0 x [RSX] DRAW_ARRAYS
0 x [RSX] DRAW_INDEX_ARRAY
```

`work/long_run.err` (12 s, after the 14:35 relift) is the same: 12 clears,
0 draws, 0 indexed. The earlier windowed capture (before `work/gt6.log` was
overwritten by a later run at 16:09) also logged
`[rsx] backend init OK -- window open` and clears, but no draw line; the
headless and post-relift logs are the reproducible evidence used here.

`work/agent_rsx/run3.err` (`RSX_TRACE=1200`) is the only run with a method
trace. Its first frame block is:

```
:22399 [rsxm] method=0x1808 data=0x00000006   ; SET_BEGIN_END(6)
:22400 [rsxm] method=0x1880 data=0x00000000   ; vertex/attribute state
...
:22420 [rsxm] method=0x1808 data=0x00000000   ; SET_BEGIN_END(0)
:22421 [rsxm] method=0x1A8  data=0xFEED0001   ; report DMA
:22422 [rsxm] method=0x1D6C data=0x00000490   ; fence release
```

There is no `0x1814` or `0x1824` between the begin and the end. The frame is a
complete setup/clear/fence block with an **empty draw list**. The walker reached
the fence (`[SEMA-REL] get=0x002B2478 off=0xFE0`), so `get` is not parked before
the frame.

### 2.2 (a) guest never gets there — yes

The renderer does call its per-frame function `func_007FA9A4`, and that
function does the surface/clear/VP/fence work. It reaches the virtual object
draw calls `func_007F916C` / `func_007F92C8`, but the draw-list objects are
empty while the title is still in its script/UI state. The observable stall is
the UI/script null-value spin at `func_009E191C` (see
`docs/analysis/spin-triage.md` and `CONTINUE-HERE.md`). In that state:

- the frame's `SET_BEGIN_END`/vertex setup is emitted by the renderer's
  clear/present path;
- no object reaches `func_00B74198`, so no `DRAW_ARRAYS` word is ever written;
- the SPU workload images that would feed later draw lists are also missing
  (`spu_workload` errors in the earlier runs), so this is not a one-line RSX
  bug.

This is the primary cause of 0 draws. The decoder is not asked to decode one.

### 2.3 (b) ring/context mismatch — ruled out for the frame stream

The walker sees the same ring the guest publishes:

- `[RSX] CLEAR_SURFACE` is produced by `rsx_process_method` from a FIFO word;
- the fence makes `get` advance to `0x00B02478` and completes
  `[SEMA-REL]`, so `put` and `get` are the same stream;
- the VP microcode, constants, viewport, surface and clear in the same block
  are decoded, so the block is not being resynced over.

The draw builders write to `0x016A6200`; the game's `put` is derived from that
same context. If the title switched to a second ring, `GCM_CTXDBG=1` would
show `gCellGcmCurrentContext` changing; no captured run shows that. The old
comment about `0x70ABE44C` is not reproduced by any log and is not needed to
explain the missing draw: the frame stream that *is* walked contains no draw.

To make this check explicit in the next run, use `GCM_CTXDBG=1` and compare
`[CTX] ... begin/end/current` with the offsets printed by
`[FIFOSELFTEST]`.

### 2.4 (c) decode/state path drops them — ruled out

`rsx_process_method` has both draw cases. The only gate that could drop a draw
without reaching `rsx_process_method` is `gcm_3d_method`:

```c
if (legacy_state_live || gcm_legacy_method_has_effect(m))
    rsx_process_method(st, m, v);
```

`gcm_legacy_method_has_effect()` listed only fence/notify/report methods, not
`0x1808/0x1814/0x1824`. In the current GT6 runs `legacy_state_live` is true
(no vtable backend in headless, backend present in windowed), so this was not
the observed cause. It is still a real latent drop: a run with
`PS3RECOMP_RSX_ENGINE=dispatch` plus a backend, or any future path where the
legacy state is considered dead, would silently discard the only draw
submission methods. Fixed in §4.

The old `run3.err` also shows indirect calls to mid-function targets
`0x00B7183C`, `0x00B74D88`, `0x00B74DFC`, etc. from tid 30. Those were lift
gaps in the 12:56 build (the absolute jump-table fix landed at 14:35). The
current `fix_run.err` has only one unresolved indirect call
(`0x4000B010`, tid 5) and none in the `0x00B7xxxx` renderer range. They are not
the current reason for 0 draws, but they are why the older run's renderer
stopped earlier than the current one.

---

## 3. Diagnostics added

### 3.1 `RSX_DRAWDBG=1` (`rsx_commands.c`)

Three counters and one log line at the decoder dispatch site:

```c
u64 g_rsx_draw_arrays_decoded;   /* every 0x1814 decoded */
u64 g_rsx_draw_index_decoded;    /* every 0x1824 decoded */
u64 g_rsx_draw_backend_calls;    /* every callback actually invoked */
```

At `NV4097_DRAW_ARRAYS` before the callback:

```
[DRAWDBG] DRAW_ARRAYS prim=6 first=0 count=3 backend=yes cb=yes surf0=0x660000
```

At `NV4097_DRAW_INDEX_ARRAY`:

```
[DRAWDBG] DRAW_INDEX_ARRAY prim=... first=... count=... backend=... cb=... surf0=...
```

`backend=no` means headless / no registered backend. `cb=no` means the backend
exists but does not implement that callback. The counters are global so a
debugger can read them without parsing logs.

### 3.2 `RSX_FIFO_SELFTEST=1|2` (`cellGcmSys.c`)

`gcm_fifo_selftest_queue()` runs at the top of the drain pass, before `put` is
read. It appends one block at the current `put` (falling back to the ring base
only when `put` is outside the ring), so it does not overwrite already-published
commands, writes the vertices just past the block, and publishes the new `put`:

```
0x00041740 0x00001042   ; VERTEX_DATA_ARRAY_FORMAT[0] = f32x4, stride 16
0x00041680 <vtx_io>     ; VERTEX_DATA_ARRAY_OFFSET[0]
0x00041808 0x00000006   ; SET_BEGIN_END(6)
0x00041814 0x02000000   ; DRAW_ARRAYS first=0 count=3
0x00041808 0x00000000   ; SET_BEGIN_END(0)
```

The three clip-space vertices are at `<vtx_io>` (immediately after the block,
or `io_b+0x40` if the block does not fit):

```
(-1,-1,0,1) (3,-1,0,1) (-1,3,0,1)
```

Modes:

| value | when it queues | what it proves |
|---|---|---|
| `1` | first drain with a GCM context | `put` -> `cellGcm_rsx_process_fifo` -> `rsx_process_method` |
| `2` | first drain after `rsx_get_backend()!=NULL` | the same plus `rsx_backend->draw_arrays` |

The block is diagnostic only. It is not game rendering and must not be left
enabled. It writes one `[FIFOSELFTEST]` line with the exact IO range and
`put`.

Why this is valid: it uses the same guest-memory `put` field, the same IO
translation, the same walker, the same `rsx_process_method` and the same
`rsx_backend` that a real draw uses. The only synthetic part is the command
block itself. This is deliberately different from
`RSX_D3D12_SELFTEST`, which calls the backend callbacks directly and never
touches the FIFO; the FIFO self-test is the missing link between the two.
It still does **not** prove that GT6's UI list is populated: only a real
`[DRAWDBG]` on a game draw does that.

---

## 4. Smallest fix for the first real draw

### 4.1 Applied: never gate the draw methods out

`cellGcmSys.c`, `gcm_legacy_method_has_effect()`:

```diff
     case 0x0050u: case 0x0104u: case 0x0180u: case 0x01A4u:
     case 0x1D6Cu: case 0x1D70u: case 0x1D74u:
         return 1;
+    /* Draw submission must never be gated out. */
+    case 0x1808u:   /* NV4097_SET_BEGIN_END */
+    case 0x1814u:   /* NV4097_DRAW_ARRAYS */
+    case 0x1824u:   /* NV4097_DRAW_INDEX_ARRAY */
+        return 1;
```

This does not create a draw. It removes the only configuration in which a
draw that *is* present could be silently skipped before the decoder. It also
keeps `SET_BEGIN_END` alive so the backend state flush that precedes the draw
is not lost.

### 4.2 Applied: decode the first frame's `SET_VERTEX_DATA2F_M`

`run3.err:22400-22419` shows the first frame streams the 2-float constant
encoding, not the 4-float one:

```
method=0x1880 data=0x00000000
method=0x1884 data=0x00000000
...
```

`rsx_process_method` only handled `0x1C00` (`SET_VERTEX_DATA4F_M`). The
`0x1880+attr*8` x/y pair therefore fell through as an unknown method and the
constant attributes stayed at the reset value. Added:

```diff
+    if (method >= 0x1880u && method < 0x1880u + RSX_MAX_VERTEX_ATTRIBS * 8u) {
+        u32 idx  = (method - 0x1880u) >> 3;         /* attribute */
+        u32 lane = ((method - 0x1880u) >> 2) & 1;   /* x or y */
+        float f; memcpy(&f, &data, 4);
+        state->vertex_data4f[idx][lane] = f;
+        return 0;
+    }
```

The z/w lanes keep `rsx_state_init()`'s `(0,0,0,1)`. `0x1818`
(`NV4097_INLINE_ARRAY`) is still unhandled, but no GT6 trace contains it; add
it when a draw actually uses it.

### 4.3 Applied: decoder counters/logging

`rsx_commands.c`, at the top-level backend state:

```diff
 u32 g_rsx_last_reference = 0;
+u64 g_rsx_draw_arrays_decoded = 0;
+u64 g_rsx_draw_index_decoded = 0;
+u64 g_rsx_draw_backend_calls = 0;
```

and inside the two draw cases:

```diff
     if (method == NV4097_DRAW_ARRAYS) {
+        ++g_rsx_draw_arrays_decoded;
+        { static int _dbg = -1; if (_dbg < 0) _dbg = getenv("RSX_DRAWDBG") ? 1 : 0;
+          if (_dbg) fprintf(stderr, "[DRAWDBG] DRAW_ARRAYS ..."); }
         ...
-        if (s_backend && s_backend->draw_arrays)
+        if (s_backend && s_backend->draw_arrays) {
+            ++g_rsx_draw_backend_calls;
             s_backend->draw_arrays(...);
+        }
```

The indexed case is symmetric.

### 4.4 Applied: FIFO self-test

The `gcm_fifo_selftest_queue()` function is inserted immediately before
`gcm_rsx_process_fifo_unlocked()`, and called after `legacy_state_live` is
computed:

```diff
     const int legacy_state_live = ...;
+    gcm_fifo_selftest_queue();
     u32 put = vm_read32(GCM_CONTROL_GUEST_ADDR + 0);
```

### 4.5 The actual first-draw blocker is guest-side

No RSX-side change can manufacture GT6's first real draw without faking it.
The evidence points to the script/UI stall at `0x009E191C` and the missing
SPU workloads. The RSX work is now in a state where the first real draw, once
the guest writes it, will be decoded and dispatched; §5 verifies that. The
next work items are therefore:

1. Fix the UI/script spin at `0x009E191C` (lifter/guest state, outside this
   report).
2. Lift/register the missing SPU images so the WWS/PM jobs produce the draw
   lists (`spu_workload` errors in the earlier runs).
3. Re-run with `RSX_DRAWDBG=1` and watch for the first `[DRAWDBG]`.

If the game is known to be drawing but `[DRAWDBG]` stays absent, the next
check is the context: `GCM_CTXDBG=1` should show whether
`gCellGcmCurrentContext` points at a ring other than the one `put` describes.
That would be the only remaining "draws go to a different ring" case, and the
self-test can be pointed at it by appending at the context's `current` rather
than the control `put`.

---

## 5. Verification procedure

### 5.1 Build

The owner's normal rebuild (not run by this investigation):

```powershell
powershell -File scripts/build-gt6.ps1
```

`cellGcmSys.c` and `rsx_commands.c` were syntax-checked with the repo's
clang (`-std=gnu17 -fsyntax-only`); no build or `gt6.exe` run was performed
here.

### 5.2 Headless: prove walker + decoder

```powershell
$env:PS3_HEADLESS='1'
$env:RSX_FIFO_SELFTEST='1'
$env:RSX_DRAWDBG='1'
$env:GCM_DRAINDBG='1'
$env:GCM_DRAINDBG_EVERY='10'
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\rsx_selftest_headless.log
```

Expected, once, near the first drain:

```
[FIFOSELFTEST] queued io=0x... put=0x... vtx=0x...
[RSX] DRAW_ARRAYS prim=6 first=0 count=3
[DRAWDBG] DRAW_ARRAYS prim=6 first=0 count=3 backend=no cb=no surf0=0x...
```

`backend=no` is correct in headless (the D3D12 backend is not created). If
`[FIFOSELFTEST]` appears but no `[DRAWDBG]`, the walker did not reach the
block: check `put`/`get` in the same log (`[DRAIN]`/`[DRAINEND]`) and whether
the guest wrote over the block first. If `[DRAWDBG]` appears, the walker and
decoder are proven.

### 5.3 Windowed: prove the backend callback

```powershell
Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
$env:RSX_FIFO_SELFTEST='2'
$env:RSX_DRAWDBG='1'
$env:RSX_D3D12_SELFTEST='0'
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\rsx_selftest_window.log
```

Expected:

```
[rsx] backend init OK -- window open
[FIFOSELFTEST] queued ...
[DRAWDBG] DRAW_ARRAYS prim=6 first=0 count=3 backend=yes cb=yes surf0=...
```

`backend=yes cb=yes` is the proof that the decoded method reached the D3D12
`draw_arrays` callback. The synthetic triangle may or may not be visible; it
is not a game frame and must not be used to judge game rendering.

### 5.4 Real game draw

```powershell
$env:RSX_DRAWDBG='1'
$env:RSX_FIFO_SELFTEST='0'
$env:GCM_CTXDBG='1'
$env:GCM_DRAINDBG='1'
$env:GCM_METHOD_HIST='5'      # top methods every 5 s; 0x1814/0x1824 must appear
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\rsx_drawdbg.log
```

- First `[DRAWDBG]` with `backend=yes cb=yes` = the first real guest draw
  reached the backend.
- No `[DRAWDBG]` while `[RSX] CLEAR_SURFACE` keeps appearing = the guest
  still has not submitted a draw; this is the current expected state until
  the UI/SPU blockers are fixed.
- `[CTX]` lines plus `[FIFOSELFTEST]` offsets = whether the guest's draw
  context is the ring the walker follows.

### 5.5 Negative controls

- `RSX_FIFO_SELFTEST=0` must produce no `[FIFOSELFTEST]` line.
- `RSX_DRAWDBG=0` must produce no `[DRAWDBG]` line.
- With `RSX_FIFO_SELFTEST=2` in a headless run, the self-test must not queue
  (no backend), proving the mode gate.

---

## 6. Exact addresses and commands

### 6.1 Guest

| address | item |
|---|---|
| `0x00B74198` | `func_00B74198` — `DRAW_ARRAYS` wrapper |
| `0x00B74214` | `func_00B74214` — invalidate/begin-end wrapper |
| `0x00B81C10` | `func_00B81C10` — writes `0x40041814` `DRAW_ARRAYS` |
| `0x00B81D30` | `func_00B81D30` — writes `0x0008181C` + `0x40081824` indexed |
| `0x00B81E60` | `func_00B81E60` — writes `0x400C1714` + `0x00041808` |
| `0x00B82070` | `func_00B82070` — writes `0x00041808` end |
| `0x00B78788` | `func_00B78788` — frame flip (`SetPrepareFlip`) |
| `0x007FA9A4` | `func_007FA9A4` — per-frame submit/present |
| `0x016A6200` | GT6 `CellGcmContextData` used by the builders |
| `0x016A8680` | `gCellGcmCurrentContext` out-pointer from `_cellGcmInitBody` |
| `0x0F800000` | HLE `CellGcmContextData` created by `cellGcmSetupContext` |
| `0x70000000` | HLE command buffer (IO 0, 64 KiB default ring) |

### 6.2 Runtime

| location | item |
|---|---|
| `cellGcmSys.c:1950` | `cellGcm_rsx_process_fifo()` |
| `cellGcmSys.c:2136` | `gcm_rsx_process_fifo_unlocked()` |
| `cellGcmSys.c:1969` | `gcm_legacy_method_has_effect()` |
| `cellGcmSys.c:2071` | `gcm_fifo_selftest_queue()` |
| `rsx_commands.c:434` | `rsx_process_method()` |
| `rsx_commands.c:902` | `NV4097_DRAW_ARRAYS` case |
| `rsx_commands.c:960` | `NV4097_DRAW_INDEX_ARRAY` case |

### 6.3 Log anchors

| file | line | event |
|---|---|---|
| `work/fix_run.err` | 4 | `[rsx] backend init skipped -- headless` |
| `work/fix_run.err` | 14917, 35729, 49608, 63412, 77351, 91164 | six `CLEAR_SURFACE` |
| `work/agent_rsx/run3.err` | 22399 | `SET_BEGIN_END(6)` |
| `work/agent_rsx/run3.err` | 22420 | `SET_BEGIN_END(0)` (no draw between) |
| `work/agent_rsx/run3.err` | 684, 22475 | old-build unresolved `0x00B7183C` |
| `work/long_run.err` | 12 x | `CLEAR_SURFACE`, 0 draws |

---

## 7. Risks / limits

- **The self-test is not a game frame.** It writes a synthetic command block
  and vertices, and may clear/draw over whatever the guest was doing. Use it
  in a dedicated run with `RSX_FIFO_SELFTEST=1|2` only.
- **The self-test races the guest at cold boot.** It appends at `put`, so it
  cannot overwrite published commands, but a title that publishes its first
  frame between the helper's read and write can overwrite the block. The
  `[FIFOSELFTEST]`/`[DRAWDBG]` lines make that obvious; retry if needed.
- **Mode 2 waits forever in headless.** That is intentional: no backend means
  no callback to prove. Use mode 1 for headless.
- **The gate fix does not create a draw.** If the guest never writes `0x1814`,
  nothing renders. The UI/SPU blockers still have to be fixed.
- **The context question is not fully closed.** The current logs show the
  frame setup/clear stream is walked. If a future run ever shows
  `[DRAWDBG]` absent while `GCM_CTXDBG` shows a context change, extend the
  self-test to append at `gCellGcmCurrentContext->current` instead of the
  control `put`.

---

## 8. Files changed / produced

- `third_party/ps3recomp/libs/video/cellGcmSys.c`
  - `gcm_fifo_selftest_queue()` and its call in the drain
  - `gcm_legacy_method_has_effect()` now keeps `0x1808/0x1814/0x1824`
- `third_party/ps3recomp/libs/video/rsx_commands.c`
  - `SET_VERTEX_DATA2F_M` (`0x1880`) decode for GT6's first-frame attributes
  - `g_rsx_draw_*` counters
  - `RSX_DRAWDBG` logs and backend-call counter at both draw methods
- `docs/analysis/rsx-first-draw-fix.md` (this report)
