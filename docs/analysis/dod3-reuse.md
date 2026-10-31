# DOD3Recomp reuse review

**Source:** `soyjxck/dod3-recomp`, cloned read-only under
`tools/reference/dod3-recomp` (ignored by git). It is a **playable PS3 static
recomp of Drakengard 3** built on the same `ps3recomp` toolkit, MIT-licensed.
Its runtime fork is cloned at `tools/reference/soyjxck-ps3recomp`.

## Highest-value finding: generation-based lwcond

`soyjxck-ps3recomp/runtime/ppu/ppu_sysprx.cpp` (lines ~410-519) replaces the
poll/no-op lwcond with a **generation counter keyed by the queue id at
lwcond+4**:

- `lwc_gen(lwcond)` keys a `std::atomic<uint32_t> s_lwc_gen[4096]` by
  `id & 0xFF000000 == 0x4C000000`.
- `lwc_wake` does `gen.fetch_add(1, release)` + `WakeByAddressAll`.
- `sys_lwcond_wait` reads `seen = gen.load(acquire)` **before releasing the
  lwmutex**, then `WaitOnAddress(&gen, &seen, 4, 1 ms)`, then reacquires.
- `PS3_LWCOND_SLEEP=1` restores the old sleep; `PS3_LWCOND_POLL_MS` tunes the
  poll cap.

The fork's `docs/TECHNICAL.md` says this made loads ~10 s faster and calls out
FIOS read chains (client/scheduler/media/completion) — exactly GT6's file
worker/font-read failure. This is the first thing to port.

## Other reusable pieces

| Piece | Use in GT6PP |
|---|---|
| `lwm` user-mode lock word (`WaitOnAddress`) | Replace the semaphore per lwmutex; reduces syscall overhead. Later. |
| `PPU_WAITPROF=1/2`, `DOD3_STALL_MS`, stack sampling | Port the *idea*: per-thread syscall waits and stack dumps when no frame presents. |
| `PS3RECOMP_FRAME_GRAB`, `RSX_CAPTURE`, `ppm2png.py` | A frame-capture path independent of the game's own draw; GT6 already has `RSX_CAP`. |
| `tools/capture_run.bat` / `capture_now.bat` | Capture scheduling pattern. |
| `tools/compare_frames.py`, `replay_regress.sh` | Renderer regression idea; GT6 needs its own reference frames. |
| `tools/menu_patch.py` + `DOD3_SKIP_INTRO` | The pattern for skipping logos/movies by patching game script functions. GT6's equivalent would be a boot-script patch, not a PAMF HLE. |
| `src/main.cpp` movie pacing/idle tick | Relevant later for the intro; not a PAMF decoder. |
| `installer/`, `launcher/`, `dod3.ini` | Distribution, settings and double-click UX. Later. |

## Not reusable

- Drakengard 3's game code, UnrealScript, Bink movies, assets, saves, DLC.
- Its Bink movie player: GT6 uses **PAMF/H.264**, so the PAMF HLE work is still
  required.
- Its Unreal-specific fast paths and menu patch data.

## Immediate action

1. Port the generation-based lwcond into our `ppu_sysprx.cpp` (agent is doing
   this).
2. Build/run with `GT6_BRINGUP_DDS=0` and `PS3_LWCOND_TRACE=1`.
3. If the font preload completes, check `MenuClassDefine`/boot assets; then the
   legal GPB draw patch.
4. Use ProcMon (`tools/procmon/Procmon64.exe`) to confirm the host
   `work/gt6_vol/font/...` reads complete.

Attribution: `soyjxck/ps3recomp` is MIT; keep the copyright notice when porting
code. No game data from DOD3 is used or needed.
