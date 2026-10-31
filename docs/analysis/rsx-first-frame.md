# RSX first frame: why the window is white

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296`, `work/bin/EMAIN.elf`, `gt6/build/gt6.exe`
**Scope:** static analysis of the present/flip path plus two controlled headless runs
(`work/agent_rsx/run2.log`, 18 s; `work/agent_rsx/run3.out`/`run3.err`, 12 s).
No source was edited by this investigation; every patch below is a proposal.
The owner changed the working tree concurrently; see "Current tree status".

## Current tree status (source changed during this investigation)

The controlled logs below were captured while `cellGcmSetPrepareFlip` was still
the stub. While this report was being written the owner changed the working
tree: `cellGcmSys.c:3217-3227` now does

```c
(void)ctx;
return cellGcmSetFlipCommand(bufferId);   /* immediate flip: sets s_flip_pending */
```

and `cellGcm_take_flip_pending()` (`cellGcmSys.c:149-154`) now logs
`[takeflip] 1 (present)`. This is the immediate-present fallback (section A
below), not a FIFO flip. It should remove the white screen because
`cellGcmSetFlipCommand` sets `s_flip_pending`; the owner's 13:11 run already
logs `[takeflip] 1 (present)`, so the present call is reached (see Post-patch
evidence). It does not advance the guest context or put a flip in the guest's
command stream. `gt6/src/main.cpp:580-582`
also removes the forced `GCM_GUEST_FB` default and says the flip now goes
through the guest context FIFO, which is not what the current `cellGcmSys.c`
body does; verify which edit is intended. The second `return
cellGcmSetFlipCommand(bufferId)` at line 3231 is unreachable; the first return
already covers every path.

If the window is still white with this patch, the flip gate is no longer the
cause. Check `[takeflip]`, the present gate (`has_display`/`draw_count`), and
the backend's empty-present path.

### Post-patch evidence

The owner's windowed run at 13:11 (`work/gt6.log`) contains:

```
line 2818: [rsx] backend init OK -- window open
line 2821: [takeflip] 1 (present)
```

and five `[takeflip]` events in the run. `[takeflip]` is printed inside
`cellGcm_take_flip_pending()` (`cellGcmSys.c:153`). Both `SetPrepareFlip`
(current body) and `SetFlipImmediate(0)` call `cellGcmSetFlipCommand`, so this
proves pending flips reach the ticker, not which call produced each one. With
`rsx_ok` true (backend init OK), the ticker's gate then calls
`rsx_d3d12_backend_present()`. The log does not show `[PRESENT]` because
`CELLMARK_BLINKDBG` was not set (the titlebar FPS is not captured in the log);
the actual window colour still needs a screenshot or `CELLMARK_DUMP` BMP. The
flip is still not in the guest's FIFO, so `put` remains frozen and draw/flip
ordering is decoupled.

## TL;DR (state at capture time)

The white window is **not a clear colour and not an uninitialised backbuffer that
was presented**. It is the window/swapchain **before any `Present` at all**.

GT6 does not write a flip word itself; it relies on `cellGcmSetPrepareFlip()`
to do it. That HLE function is a stub: it never writes the flip command into the
guest's command buffer, never advances `ctx->current`, never publishes the FIFO
`put`, and never sets `s_flip_pending`. The guest then writes its next command
(a `SET_CONTEXT_DMA_REPORT` word pair) into the slot where the flip should have
been, and `put` stops advancing. With no flip pending, `gt6_present.cpp` never
calls `rsx_d3d12_backend_present()`, so `render_frame()` never clears or presents
the swapchain.

The immediate cause of the white screen is the missing `s_flip_pending`. At
capture, the stub also failed to write the flip into the guest's command buffer
(`cellGcmSetPrepareFlip`, `cellGcmSys.c:3208` at that revision); that context
write is the correct stream fix. The current tree's immediate fallback
(section A) fixes the present gate. For a hardware-accurate fix,
`cellGcm_rsx_process_fifo()` must also learn `GCM_FLIP_COMMAND` (`0xFEAC`); it
currently only knows its own `0xFEADxxxx` marker (`cellGcmSys.c:2283`).

## Evidence

### 1. Where GT6 requests the flip

GT6 imports `cellGcmSetPrepareFlip` (NID `0x0B4B62D5`). The import stub is
`func_00F984B8` in `gt6/generated/ppu_recomp_039.cpp:145771-145774`. A search of
the lifted sources for `0xFEAD`, `0xFEAC` and `0xE920` finds no flip word
emitted by the guest; the only flip entry on this path is the HLE import.

Its caller is `func_00B78788` (`gt6/generated/ppu_recomp_026.cpp:140435`), which
is called from `func_007FA9A4` (`ppu_recomp_018.cpp:17057`), the function that
also emits the frame's surface/clear/VP state, at two sites (`17228`, `17300`).
This appears to be GT6's per-frame submit/present path.

The important part is what `func_00B78788` does after the HLE call (simplified):

```c
/* ppu_recomp_026.cpp:140455 */
ctx->lr = 0x00B787C8; func_00F984B8(ctx); DRAIN_TRAMPOLINE(ctx);

/* ... check current + 8 <= end, then: */
/* ppu_recomp_026.cpp:140682-140718 */
vm_write32(current + 0, 0x000401A8);   /* NV4097_SET_CONTEXT_DMA_REPORT, 1 word */
vm_write32(current + 4, 0xFEED0001);   /* main memory */
vm_write32(ctx + 8, current + 8);      /* advance current */
```

So the guest expects `cellGcmSetPrepareFlip(ctx = 0x016A6200, bufferId)` to
write the flip into `ctx->current` **first**, and only then appends the report
DMA command:

```
expected:  [0x0004FEAC][bufferId] [0x000401A8][0xFEED0001] ...
actual:                              [0x000401A8][0xFEED0001] ...
                                    ^ report DMA lands in the flip's slot
```

On hardware/libgcm the flip is two words:

```
0x0004FEAC   ; count = 1, method = 0xFEAC (GCM_FLIP_COMMAND)
bufferId     ; data
```

RPCS3 implements exactly that (`gcmSetPrepareFlip`, `cellGcmSys.cpp`):
`rsx::make_command(ctxt->current, GCM_FLIP_COMMAND, { id })` then optionally
`control.put += cmd_size`. `GCM_FLIP_COMMAND` is `0x0000FEAC >> 2` in
`Emu/RSX/gcm_enums.h`.

### 2. What the HLE actually does

**At capture time**, `cellGcmSetPrepareFlip` in `cellGcmSys.c:3207-3232`
ignored `ctx` entirely:

```c
(void)ctx;                       /* command buffer context -- not used in HLE */
...
gcm_set_current_display_buffer(bufferId);
s_flip_status = CELL_GCM_FLIP_STATUS_DONE;
s_flip_request_count++;
s_last_flip_time = get_timestamp_ns();
if (s_flip_handler_opd && ...) g_ps3_guest_caller(...);
return CELL_OK;
```

It did **not**:

- write `0x0004FEAC` + `bufferId` into `ctx->current`;
- advance `ctx->current`;
- publish `GCM_CONTROL_GUEST_ADDR + 0` (`put`);
- set `s_flip_pending`;
- return the prepared flip id. It returned `CELL_OK` (0) for every buffer,
  while libgcm returns `id`; `func_00B78788` stores the return value in `r30`
  and writes it into its own state at `ctx+0x3F0`
  (`ppu_recomp_026.cpp:140459`, `140488`).

`s_flip_pending` is the only gate the present ticker checks
(`gt6/src/gt6_present.cpp:91-92`, `107-108`), and it is set only by
`gcm_flip_request()` (`cellGcmSys.c:3105-3109`) or by a `0xFEAD` word in the
FIFO (`cellGcmSys.c:2306-2314`). At capture time `SetPrepareFlip` used
neither.

**Current tree:** the body (`cellGcmSys.c:3217-3227`) is now:

```c
(void)ctx;
return cellGcmSetFlipCommand(bufferId);   /* immediate flip */
```

`cellGcmSetFlipCommand` calls `gcm_flip_request(bufferId, 0)`, which *does* set
`s_flip_pending` and `s_flip_direct_pending`, so the ticker now has something to
present. This is the smallest present-gate fix; it does not queue a flip into
the guest's command stream and does not advance the guest context.

### 3. Measured FIFO timeline (controlled headless run)

`work/agent_rsx/run2.log`, env:
`PS3_HEADLESS=1 PS3_VERBOSE=1 GCM_DRAINDBG=1 GCM_DRAINDBG_EVERY=10
GCM_FLIPCOUNT=1 GCM_CTXDBG=1 GT6_THREADS=1`.

| line | event |
|---|---|
| 147 | `[DRAINEND] caught-up: 00000000 -> 00010058 (65624 bytes), put=00010058` |
| 168-171 | four display buffers registered: `0x0 / 0x660000 / 0xCC0000 / 0x1320000`, pitch 6144, 1280x720 |
| 1844 | `[cellGcmSys] SetPrepareFlip(bufferId=1)` |
| 1895-... | every later `[DRAIN]` shows `put=00010058`; `ctx.current=70000004` (the HLE context, not GT6's) |
| 9225 | `[RSX] CLEAR_SURFACE mask=0xF0 color=0xFF000000` (the guest's black clear, from the next 0x1028-byte block) |
| 9240 | `[cellGcmSys] SetPrepareFlip(bufferId=2)` |
| 9247-... | every later `[DRAIN]` shows `put=00011080`, unchanged for the rest of the run |

There is **no** `[flip]`, `[FLIP]`, or `[flipword]` line in the whole run,
despite `GCM_FLIPCOUNT=1`; `cellGcm_take_flip_pending()` therefore never has a
pending flip to return. Run2 predates the owner's `[takeflip]` instrumentation,
so its absence is expected. (`[PRESENT]` logging is off unless
`CELLMARK_BLINKDBG` is set, so its absence is not evidence by itself.)

The 0x1028-byte block at `0x10058..0x11080` is a complete frame setup:
`NV4097_SET_SURFACE_FORMAT=0x148`, pitch `0x1800`, colour A offset `0x660000`,
zeta `0x1980000`, viewport 1280x720, scissor, `SET_COLOR_CLEAR_VALUE=0xFF000000`,
`CLEAR_SURFACE=0xF0`, then vertex-program microcode and a fence. The guest is
submitting real frames; only the flip is missing.

### 4. Why the window is white, exactly

`rsx_d3d12_backend_init()` (`rsx_d3d12_backend.c:7637`) creates the window,
swapchain, RTVs, depth buffer and PSOs. It **never clears or presents**. The
window class has `wc.hbrBackground = NULL` and is created `WS_VISIBLE`
(`create_window`, `rsx_d3d12_backend.c:676-699`), so the un-presented client
area is the desktop/DWM default (white in these runs). The controlled runs below
were headless, so no window was created; the white observation is from the
owner's windowed run (`work/gt6_windowed.log`). The present gate and the missing
flip are identical in both modes; headless only skips
`rsx_d3d12_backend_init()`.

The only present path is:

```
gt6_present.cpp:91   if (rsx_ok && cellGcm_take_flip_pending())
gt6_present.cpp:92       rsx_d3d12_backend_present()
rsx_d3d12_backend.c:7754 rsx_d3d12_backend_present()
rsx_d3d12_backend.c:7836     render_frame()
rsx_d3d12_backend.c:4948         ClearRenderTargetView(..., s_d3d.clear_color, ...)
rsx_d3d12_backend.c:5844         IDXGISwapChain::Present(1, 0)
```

`render_frame()` also handles guest clear records at
`rsx_d3d12_backend.c:5985-6077`; a display clear is not itself a present unless
a flip has landed since the last present (`cellGcm_flip_request_count` check at
`6031-6059`).

The guest's own clear value is black (`0xFF000000`, run3.err method
`0x1D90`/`0x1D94`), so even the first real frame would be black, not white.
**White = no `Present` has ever happened.**

At capture time, `SetPrepareFlip` *did* bump `s_flip_request_count`, which arms
the clear-boundary present path in `d3d12_clear`
(`rsx_d3d12_backend.c:6031-6059`).
That path still requires a non-clear display draw already accumulated
(`have_display_draws` at `6011-6018`). In the traced block the display clear
precedes any non-clear display draw, so `have_display_draws` is false and
`d3d12_clear` returns; the count alone does not produce a present.

One extra trap: at capture time `gt6/src/main.cpp:583` forced
`GCM_GUEST_FB=0,1280,720,6144` by default. `guest_fb_present()`
(`rsx_d3d12_backend.c:4350-4418`) copies RSX local memory offset **0** over the
rendered backbuffer inside `render_frame()`. GT6 renders into the buffer it
flips (`0x660000` for buffer 1, `0xCC0000` for buffer 2), so this copy would
overwrite the correct image with display buffer 0. It was not the white-screen
cause when no flip happened, but it would mask the first correct frame once the
flip was fixed. The current tree removes that default (`main.cpp:580-582`) and
keeps `GCM_GUEST_FB` as an explicit diagnostic.

One caveat about the owner's older logs and `docs/analysis/CONTINUE-HERE.md`:
they mention `SetFlipImmediate(0)`. That entry point *does* set
`s_flip_pending` (it calls `cellGcmSetFlipCommand(0)`), so it can present
display buffer 0 even without `SetPrepareFlip`. The two controlled runs above
did not call it. If the current windowed run does, the white could be the
forced `GCM_GUEST_FB` copy of buffer 0 (or the empty-present path exiting),
rather than "no flip at all". Check `FLIP_DBG=1` and `CELLMARK_BLINKDBG=1` in
the windowed run: a `SetFlipImmediate(0)` present is still not a flip of buffer
1/2 and does not advance the frame chain.

### 5. Display buffers and tiles

All four buffers are interpreted consistently:

- pitch 6144 = 1280 * 4 + 1024 bytes of row padding, 256-byte aligned;
- offsets `0x0, 0x660000, 0xCC0000, 0x1320000`;
- `0x660000 / 6144 = 1088` rows, so each buffer covers 6144 * 1088 = 0x660000
  bytes (1280x1088 pixels with row padding); the 720 visible rows are the
  first 720 rows of that allocation;
- tile 4 / Zcull at `0x1980000` (immediately after the four buffers), tile pitch
  8192, size 0x880000; 1920x1088*4 = 0x7F8000, so the size/pitch are right;
- the first-frame surface setup uses colour A `0x660000` and zeta `0x1980000`,
  exactly the registered display buffer and depth tile.

No offset or tile misinterpretation was found for the first frame. The D3D12
backend recognises display offsets through `cellGcmOffsetIsDisplay()`
(`cellGcmSys.c:3028`) and keys surfaces by raw RSX offset, so buffer 1 is
correctly treated as scanout.

### 6. GCM methods GT6 uses before the prepare flip

From `run3.err` (`RSX_TRACE=1200`), the first frame block contains:

- surface: `0x208` format `0x148` (A8R8G8B8 / Z24S8 / pitch), `0x20C` pitch
  `0x1800`, `0x210` colour A `0x660000`, `0x214` zeta `0x1980000`, `0x218`/
  `0x21C` colour B, `0x22C` zeta pitch `0x2000`, `0x280`/`0x284` C/D pitch,
  `0x288`/`0x28C` C/D offsets, `0x2B8` window offset, `0x1D88` shader window;
- viewport/scissor: `0x0A00`/`0x0A04` (1280x720), `0x0A20..0x0A3C`,
  `0x08C0`/`0x08C4`, `0x394`/`0x398`;
- clear: `0x1D90=0xFF000000`, `0x1D94=0xF0`;
- state: `0x220` target, `0x324` colour mask, `0x370` MRT mask, `0x1D7C` AA,
  `0x1834` front face, `0x183C` cull, `0x1FCC` attrib tex coord,
  `0x1A8` report DMA, `0x1450` performance params, `0x1710`/`0x1714`
  invalidates, `0x1FD8` invalidate L2;
- draw setup: `0x1E9C` transform program load, `0x0B80..` VP microcode,
  `0x1EFC`/`0x1F00..` constants;
- fences: `0x1D6C`/`0x1D70` semaphore release, `0x50` reference, `0x1800` get
  report.

The D3D12 backend handles the surface, clear, viewport, shader, constant and
draw paths. `0x1450`, `0x1710`, `0x1714`, `0x1FD8` are harmless no-ops;
`0x1FCC` is state-only. There is no `0xFEAC` case in `rsx_commands.c` or
`rsx_dispatch.c`; a `0x0004FEAC` word would decode as method `0x0EAC` on
subchannel 7 and be sent to the 2D path. **The first missing method in the frame
is the flip command itself**, and it is missing because `SetPrepareFlip` does
not write it.

### 7. Secondary blockers (not the white screen)

- `func_009F92CC` (`ppu_recomp_022.cpp:143181`) performs a computed jump through
  a local jump table (`0x009F9348 + {0x38, 0x88, ...}`), calling code labels
  such as `0x009F9380` that are inside the function but have no `.opd` entry.
  The lifter turns this into `ps3_indirect_call`; the target is unresolved, and
  thread 14 (`Spu Event Handler`) spins there. With `PPU_STUCKMAX=1e6` the
  process survives, but the render thread is starved.
- Nine SPU images are still reported as "no lifted image" and dropped
  (`spu_workload` errors in run2). The WWS/PM jobs cannot complete, which also
  holds up the render loop.
- The guest's context is **not** the HLE context. `_cellGcmInitBody` creates
  `0x0F800000` (seen as `ctx.current=70000004` in `[DRAIN]`), while GT6's
  renderer uses its own `CellGcmContextData` at `0x016A6200`. The HLE must use
  the `ctx` argument; it cannot rely on `s_gcm_context_ea`.

## Ranked hypotheses

1. **At capture, `cellGcmSetPrepareFlip` did not enqueue the flip (primary,
   proven).** The guest wrote the report-DMA command into the flip's slot;
   `put` never advanced; `s_flip_pending` stayed 0; no present. This is
   sufficient to explain the white window. The current tree replaces the body
   with an immediate `cellGcmSetFlipCommand`, which sets `s_flip_pending`; this
   hypothesis is addressed, and the owner's 13:11 run logs
   `[takeflip] 1 (present)`.
2. **The FIFO walker has no `0xFEAC` decoder (co-primary for a correct fix).**
   Even if `SetPrepareFlip` writes the hardware command, the walker would
   decode `0x0004FEAC` as method `0x0EAC` on subchannel 7 and drop it. The
   runtime's `0xFEAD` marker is a private encoding, not what libgcm emits. The
   owner's current comment says GT6's context uses an RSX IO address
   (`0x70ABE44C`) the runtime ring does not see, which is a related but
   larger issue: the drain is not watching the same command stream. If true,
   even a correct `SetPrepareFlip` write would not make the drain render GT6's
   first frame; the immediate path presents only what the drain has already
   seen.
3. **`GCM_GUEST_FB` was forced to buffer 0 (`main.cpp:583` at capture).** Once
   a present happened, `guest_fb_present` would overwrite the correct
   backbuffer with the wrong display buffer. This would make a correct first
   frame look like an old/blank frame, not white; the current tree removes the
   forced default.
4. **The render thread is stuck at `0x009F9380` and SPU jobs are dropped.**
   This prevents sustained frames and explains why `put` only moved twice in
   18 s, but the first clear/present can still be made to happen.
5. **Display/tile offsets are wrong.** Ruled out: the four buffers, tile 4 and
   Zcull all agree with GT6's 1280x720 pitch-6144 layout.

## Exact next patch

### A. Smallest change: already applied in the current tree

The body at `cellGcmSys.c:3217-3227` is now:

```c
(void)ctx;
return cellGcmSetFlipCommand(bufferId);   /* immediate flip */
```

This is the smallest possible present-gate fix. `cellGcmSetFlipCommand` calls
`gcm_flip_request(bufferId, 0)`, which sets `s_flip_pending` and
`s_flip_direct_pending` (`cellGcmSys.c:3105-3110`). The ticker then logs
`[takeflip] 1 (present)` and calls `rsx_d3d12_backend_present()`.

What it does:

- removes the all-zero `s_flip_pending` condition that left the window
  unpainted;
- presents the batch the drain has **already executed**;
- completes the flip on the next `cellGcmTickFlip` via `s_flip_direct_pending`.

What it does **not** do:

- queue the flip into the guest's command stream;
- advance `ctx->current` or publish `put`;
- preserve frame ordering/fences between the flip and the draws.

The owner's comment says GT6's context uses an RSX address in the
`0x70xxxxxx` IO window (`0x70ABE44C`), which the runtime ring (control `put`,
`GCM_CONTROL_GUEST_ADDR + 0`) does not see.
If that measurement is correct, the immediate path is the only practical
present fix without teaching the drain about that stream. It will show a
black/clear frame or the accumulated first batch; it will not by itself make
the guest's frame chain correct.

If the window is still white with this body, the flip gate is no longer the
cause. Check:

- `[takeflip] 1 (present)` in the log after each `SetPrepareFlip`; if absent,
  `cellGcmSetFlipCommand` is not reached or the ticker is not running;
- `has_display` / `s_d3d.draw_count` at
  `rsx_d3d12_backend.c:7779-7790`: an offscreen-only batch sets
  `has_display=0` and `render_frame()` is skipped;
- the empty-present path (`draw_count == 0`): the owner's note says it exits on
  this title. Guard it or force `has_display` for the first frame;
- `GCM_GUEST_FB=0x660000,1280,720,6144` (buffer 1) as a one-run diagnostic to
  force a present from the flipped buffer. Do not keep it as a permanent
  default: the offset must follow the current display buffer.

### B. Correct follow-up: put the flip in the stream the drain reads

The hardware command is two words:

```c
/* count = 1, method 0xFEAC */
vm_write32(cur + 0, 0x0004FEACu);
vm_write32(cur + 4, bufferId);
vm_write32(ctx + 8, cur + 8);
s_fifo_flips_queued++;   /* paired with s_fifo_flips_reached in the walker */
```

This is only useful if the drain can see that stream. For a context that maps
to the runtime ring, `gcm_ea2io(cur)` succeeds and publishing
`put = gcm_ea2io(cur + 8)` would expose it. The owner measured `0x70ABE44C`
for GT6's context, so first determine whether that EA maps to an IO offset the
drain walks; if it does not, the flip must stay outside the stream (option A)
until the drain is taught to follow that context.

If the stream is visible, add a walker case before the generic
`type == 0 || type == 2` decode at `cellGcmSys.c:2412`:

```c
if (w == 0x0004FEACu) {
    const u32 dea = gcm_io2ea(s_fifo_getoff + 4);
    const u32 id  = dea ? vm_read32(dea) : 0xFFFFFFFFu;
    s_fifo_getoff += 8;
    gcm_fifo_flip_resets_state(&s_state);
    if (id < CELL_GCM_MAX_DISPLAY_BUFFER_NUM) {
        gcm_set_current_display_buffer(id);
        s_flip_pending = 1;
        s_flip_request_count++;
        if (s_fifo_flips_reached != s_fifo_flips_queued) s_fifo_flips_reached++;
    }
    why = "flip";
    break;
}
```

The `s_fifo_flips_reached` increment is required for
`gcm_flip_executed_take()` to complete the flip on the next vblank. If
`SetPrepareFlip` also calls `gcm_flip_request(..., 1)`, increment
`s_fifo_flips_queued` when writing the command so the counts stay paired.

### C. Return value still worth fixing

The current body returns `cellGcmSetFlipCommand`'s `CELL_OK` (0). libgcm returns
the prepared flip id; `func_00B78788` stores `r30` at `ctx+0x3F0`
(`ppu_recomp_026.cpp:140459`, `140488`). For buffer 1/2 this is 0 instead of
1/2. If the engine uses that byte as the current flip index, return
`(s32)bufferId` on success in both the immediate and FIFO paths.

### D. Also fix before judging the first frame

- The forced `GCM_GUEST_FB` default is already removed in the current
  `main.cpp:580-582`; keep it as an explicit diagnostic only. If you use it,
  make its offset follow the current display buffer (buffer 1 first, then 2/3),
  not a fixed 0.
- Fix the PPU computed jump at `0x009F9380` (local jump table in
  `func_009F92CC`) so thread 14 stops spinning. This is a lifter/boundary issue,
  not an RSX one.
- Lift/register the nine missing SPU images; otherwise SPURS jobs continue to
  be dropped and the render loop will not run at frame rate.

## Test procedure

1. Rebuild with `powershell -File scripts/build-gt6.ps1`.
2. Headless flip check:

   ```powershell
   $env:PS3_HEADLESS='1'; $env:PS3_VERBOSE='1'
   $env:GCM_DRAINDBG='1'; $env:GCM_DRAINDBG_EVERY='10'
   $env:GCM_FLIPCOUNT='1'; $env:FLIP_DBG='1'
   gt6\build\gt6.exe work\bin\EMAIN.elf
   ```

   Expected after the first `SetPrepareFlip` with the **current immediate
   body**:
   - `[takeflip] 1 (present)` (the owner's instrumentation);
   - `[FLIP]`/`[flip]` lines from `gcm_flip_request`;
   - the tick's `cellGcmTickFlip` marks the status DONE via
     `s_flip_direct_pending`;
   - **`put` may remain `0x10058`/`0x11080`**: the immediate path does not
     advance the guest context, so a frozen `put` is expected here, not a
     failure. It only needs to move after the FIFO/`0xFEAC` follow-up.

   If you implement option B (flip in the drained stream), expect instead
   `[DRAIN] ... put=0001005C` (or higher) and the marker/`0xFEAC` handling.

3. Windowed check:

   ```powershell
   Remove-Item Env:GCM_GUEST_FB -ErrorAction SilentlyContinue
   $env:CELLMARK_BLINKDBG='1'; $env:CELLMARK_DUMP='4'
   gt6\build\gt6.exe work\bin\EMAIN.elf
   ```

   Expected: the title bar shows `FPS`/`draws` (it is only set in
   `render_frame`, `rsx_d3d12_backend.c:5857-5875`), `[PRESENT]` lines appear,
   and `CELLMARK_DUMP` writes BMPs that are black/first-frame, not white.

4. If it is still white, check whether `[takeflip] 1 (present)` appears. If it
   does not, the flip is not reaching the ticker. If it does but there is no
   `[PRESENT]`, the batch is offscreen-only or the empty-present path exited;
   try `GCM_GUEST_FB=0x660000,1280,720,6144` (buffer 1) as a one-run diagnostic.
   A `[GUESTFB]` image that is buffer 0 confirms the overwrite, not the flip.
5. `GCM_FLIP_NEEDS_FIFO=1` only changes completion timing; it does not create
   a flip. Use `FLIP_DBG=1 GCM_FLIPCOUNT=1` and watch the counter; the first
   flip must be > 0.

## Risks

- **Immediate flip is out of order.** The current body presents whatever the
  drain has already executed, not the draws that logically precede this flip.
  With a single slowly-submitted first frame that is fine; with a steady frame
  chain it can present frame N while frame N-1's tail is still in the guest
  stream. The visible symptom would be flicker/lag, not white.
- **Publishing `put` early (option B only).** `SetPrepareFlip` is the frame
  boundary in GT6's path, so exposing commands through the flip is sensible; a
  title that calls it mid-frame would expose a partial frame. GT6 calls it at
  the end of `func_00B78788`, after the surface/clear/VP setup.
- **Marker/encoding (option B).** Option B's `0xFEAC` command is the hardware
  encoding; the runtime's `0xFEAD0100|id` marker is private. The marker consumes
  only 4 bytes, while libgcm's command is 8; the guest's `current` check uses
  `current + 8` for its *own* next command, so either size is safe here, but the
  ring layout differs from hardware.
- **Ring wrap (option B).** `gcm_flip_into_fifo` can write a JUMP at `cur+4` and
  rewind `ctx->current` to `begin` when the ring is nearly full. Publishing
  `put = begin` then does not include the marker written at the old tail. GT6's
  first flips are far from the end (current around `0x10058`, ring ~1 MB), so
  this does not affect the first frame, but a robust patch should publish the
  pre-wrap offset or write the flip after the wrap check.
- **Flip handler timing.** `gcm_flip_request` calls the handler at request time
  (the existing compatibility wart). If it re-enters half-built state, set
  `GCM_FLIPCB_ONTICK=1`.
- **First frame may still be black or skipped.** The current immediate flip
  makes a present reachable, not a correct image. The first batch contains a black clear and
  early 3D setup; the VP path and texture state may not yet produce the game's
  real first frame. Without `GCM_GUEST_FB`, a batch with no display-targeted
  draw is deferred rather than presented. Fix the `0x009F9380` lifter gap and
  the missing SPU jobs before judging visual correctness.
- **`GCM_GUEST_FB` overwrite.** As above, the default copy from buffer 0 can
  hide the correct flipped buffer. Disable it for this title or make it follow
  the current flip.
- **Guest context address may vary (option B).** Option B uses the `ctx` passed
  by the guest; if a later code path passes a non-context pointer,
  `gcm_flip_into_fifo` fails its `current/end` checks and the immediate fallback
  still presents. Add a `GCM_CTXDBG`-style log of `ctx`, `begin`, `end`,
  `current` if the first run does not show `put` moving.

## Logs

- `work/agent_rsx/run2.log` - 18 s headless run with `GCM_DRAINDBG`,
  `GCM_FLIPCOUNT`, `GT6_THREADS`; the FIFO timeline above.
- `work/agent_rsx/flip-timeline.txt` - the seven key lines from run2 quoted in
  the table above.
- `work/agent_rsx/run3.out`, `work/agent_rsx/run3.err` - 12 s headless run with
  `RSX_TRACE=1200`; the first-frame method stream.
- `work/gt6_oobfix.log` - owner's earlier run; same first
  `SetPrepareFlip(1)` and no subsequent flip. (Its first 64 KB drain is not
  instrumented, so run2 is the cleaner timeline.)
- `work/gt6.log` - **not used for the pre-patch timeline**: it was
  overwritten/contaminated by overlapping runs early in this investigation. Its
  13:11 windowed run is used only for the post-patch `[takeflip]` evidence
  above. The controlled pre-patch logs are run2 and run3.
