# PS3 reference-port reuse matrix

**Date:** 2026-10-31
**Scope:** five external PS3 static-recompilation projects, cloned read-only under
`tools/reference/` (git-ignored). No build and no `gt6.exe` run was performed.
**Purpose:** decide whether any of them has a better fix than GT6PP's current
generation-based `sys_lwcond`, and what is reusable for the boot/presents, first
2D GPB draw, and PAMF/H.264 blockers.

**Status legend:** *verified* = read in the cloned source/patch; *repo claim* =
stated by the project's own README/docs, not independently run here; *unverified*
= plausible but no source or run in these trees.

---

## 0. Bottom line

| Question | Answer |
|---|---|
| Is any repo a drop-in fix for GT6's current file-worker park? | **No.** The current GT6 trace (`docs/analysis/lwcond-trace-fix.md` §2-5) shows **no signal at all** to the FileHost E5/E7 queues; the FileHost helper `func_00A08B8C` exits at boot because of an injected early-return guard. A better lwcond cannot create that producer. |
| Is the Killzone lwcond better than GT6PP's generation counter? | **Yes, semantically.** It distinguishes `signal` / `signal_all` / `signal_to`, keeps one FIFO node per waiter, returns `ETIMEDOUT`, and (in patch 1122) hands the lwmutex to the woken waiter. The generation counter wakes all waiters and treats `signal_to` as `signal`. |
| Does any repo implement async `cellFs` AIO completion? | **No.** Every reviewed `cellFsAioRead` completes inline (GT6PP, inFAMOUS, project-8-plus); the Killzone patches only adjust the read path/locking. No reusable worker exists. |
| Does any repo implement PAMF demux? | **No.** inFAMOUS's `cellPamf.c` is byte-identical to GT6PP 0.18.0 and still uses the disputed `+0x10/+0x14` layout; `cellDmux` is the same stub. Killzone uses AVI/H.264, not PAMF. |
| Does any repo implement GPB / the GT6 boot/presents handoff? | **No.** No `GPB`, `PresentsRoot`, `MGOM`, `execBoot`, or `loadPackage` code exists in the five. |
| Best reusable items | (1) KZ2/KZ3 per-waiter FIFO lwcond + lv2 hand-off; (2) KZ3 generic `cellFs` VFS pre-open/miss hooks; (3) KZ3 D3D12 boot-screen/2D diagnostics and FP/texture fixes. Honourable mention: ATRAC3+ audio for movies. |

> **Current-tree note (not from these repos):** GT6PP already contains the
> generation-based lwcond port (`patches/ps3recomp-lwcond-generation.patch`) and
> the `func_00A08B8C` guard in `gt6/generated/ppu_recomp_023.cpp`. The highest
> impact next experiment is GT6-specific: keep the FileHost helper alive (drop
> only the `+0x1C29` early return, keep the `+0x1C2C` clear) and log E4/E5/E7
> generation changes. Do not expect a reference-port lwcond patch to replace
> that experiment.

---

## 1. Repository matrix

| Repo | Game / engine | Recomp stack | License | Status | Source in repo | GT6PP relevance |
|---|---|---|---|---|---|---|
| [whompay/inFAMOUSreborn](https://github.com/whompay/inFAMOUSreborn) | inFamous (PS3 2009, BCES00220), Sucker Punch in-house engine | **ps3recomp 0.11.0 vendored in-repo** + custom `infamous-recomp`, D3D12 | MIT (ps3recomp MIT); SDL3 zlib; RPCS3 used only to decrypt | playable per `.recomp.json`; native Windows + installer | **full runtime + port source** (+ prebuilt installer/launcher binaries) | Best source for a **mature per-lwcond implementation with per-site stats**; older 0.11.0 base, cherry-pick the lwcond block only. Bink movie code is not PAMF. |
| [undecuple/project-pyrrhus](https://github.com/undecuple/project-pyrrhus) | Killzone 2 (BCUS98116, 1.29 update), Guerrilla in-house engine | ps3recomp **v0.18.0 submodule** + numbered `port/patches/`, D3D12 | MIT; FFmpeg LGPL-2.1+ separate DLL; at3_standalone LGPL separate DLL | early, partly playable; intro/menus/first level (~23 fps); v0.1.6 | port code + patch series; runtime is a submodule (not vendored in this clone) | **KZ2 6005 FIFO lwcond**, 6041 `ps3_evcv`, 6035 cellFs pre-open hook, 6022/6023 movie audio. No PAMF/GPB. |
| [undecuple/project-helghast](https://github.com/undecuple/project-helghast) | Killzone 3 (BCUS98234, 1.14 update), Guerrilla in-house engine | ps3recomp **v0.18.0 submodule** + numbered `port/patches/`, D3D12 | MIT; RPCS3 GPL-2.0 reference only | partly playable; intro/menus/levels, 16-22 fps; v0.1.7 | port code + patch series; runtime is a submodule | **KZ3 1059 per-waiter FIFO**, **1122 lv2 sync hand-off**, 1032 wait accounting, 2002 boot-screen D3D12, 4024/0004 cellFs hooks, 2072 pacing. No PAMF/GPB. |
| [MaxLeiter/project-8-plus](https://github.com/MaxLeiter/project-8-plus) | Tony Hawk's Project 8 (BLUS30011 1.02), Neversoft engine | ps3recomp upstream `a679051` (2026-09-29) + branch `1cf8753`; **one huge `ps3recomp-thp8.patch`**, D3D12 | MIT; RPCS3 used only to decrypt; third-party notices in `NOTICE` | playable; v0.9.2; installer + Lua mod API | title source + **runtime only as a patch** | `PS3_SPIKE_MS` per-frame/per-thread profiler, lwmutex fast path, cellFs AIO (still synchronous), Bink movie mode. Its lwcond is older/semaphore-based, **not** better. |
| [TheWishin/T5DROnline](https://github.com/TheWishin/T5DROnline) | Tekken 5: Dark Resurrection Online (PS3), Namco | ps3recomp (NoahBPeterson `infamous/upstream-sync`, pin `f17bcd3`) + custom launcher/lobby | MIT docs; ps3recomp MIT; FFmpeg/at3 LGPL | released 1.1.x; online revival + offline mode | **docs only** (`README.md`, `README.de.md`, `TROUBLESHOOTING.md`, `LICENSE`); no source/binaries in repo | Documentation-level only: WMF H.264 decode, `PS3_VDEC_STALL_MS` watchdog, launcher/pacing. No code to copy. |

**Commits reviewed:** inFAMOUS `2e9405c` (2026-10-23), Pyrrhus `218f660`
(2026-10-30), Helghast `4f97260` (2026-10-29), Project 8 Plus `1130644`
(2026-10-26), T5DR `917294a` (2026-10-30).

---

## 2. Keyword coverage

`H` = substantial implementation, `M` = helper/hook or partial, `L` = docs or
diagnostic only, `—` = absent.

| Search term | inFAMOUS | Pyrrhus (KZ2) | Helghast (KZ3) | Project 8 Plus | T5DR |
|---|---|---|---|---|---|
| `lwcond` / `lwmutex` | **H** custom per-object + stats + strict waits | **H** 0003, 6005 FIFO, 6004 ring | **H** 0003, 1059 FIFO, 1122 lv2 hand-off | M old semaphore/futex lwmutex; lwcond is `Sleep(1)` | — |
| `cellFs` / async file worker | M sync `cellFsAioRead` | M 6035/6036/2078; sync AIO | **H** 0004 VFS miss hook, 4024 pre-open, 4018 unlink/rmdir, 2078 write hook | M strict VFS + sync AIO | — |
| `cellPamf` / PAMF / Bink / movie | M `cellPamf` parser (same wrong layout as GT6PP), `cellDmux` stub, Bink player | **H** AVI + H.264 via FFmpeg cellVdec, ATRAC3+/AC3 | H Bink movies (guest Bink player); no PAMF | H Bink movie mode/compositor | L docs: WMF H.264, `PS3_VDEC_STALL_MS` |
| `RSX` / D3D12 / Vulkan | H full D3D12 backend; Vulkan planned only | **H** 2000-series D3D12 patches; Vulkan separate project | **H** 2000-series D3D12 patches; Vulkan planned only | **H** D3D12 backend in patch; Linux via vkd3d | L docs; no Vulkan backend |
| `cellGcm` | H | H | H | H | L docs |
| 2D UI / GPB | UI tools/font, no GPB | KZ2 browser/menu UI, no GPB | **M** 2002 boot-screen 2D quad, 2009 UI gamma; no GPB | Bink/UI, no GPB | — |
| skip intro | — (movie pool wait env) | `KZ2_SKIP_INTRO=1` start-page patch | — (movies play) | `straight_to_menu`/`skip_intro` plugin hook | online intro skip (both players Start) |
| boot project handoff | `ppu_boot_frames_presented` boot present scaffold; no MGOM | own boot; no MGOM | own boot; no MGOM | own boot; no MGOM | — |
| `PPU_WAITPROF` / stall profiling | **H** `[LWCOND-STAT]`, per-LR waits | H 6004 lwcond ring, host sampler | **H** 1032 `KZ3_WAIT_ACCT`, 1033 sampler, 1081 stall diag | **H** `PS3_SPIKE_MS` | L `PS3_VDEC_STALL_MS` |
| launcher / pacing | H installer + launcher | H `tools/release/launch.py`, first-run | **H** `launch.py`, `firstrun.py`, `RSX_PACE` | H builder/launcher | L docs |

---

## 3. Findings

### F1 — Per-waiter FIFO lwcond and lv2 hand-off (best blocker-1 code)

**Where**

- KZ3 `port/patches/1059-lwcond-per-waiter-fifo.patch` — new
  `runtime/ppu/kz3_lwcond_fifo.h` (166 lines) + `ppu_sysprx.cpp` integration.
- KZ3 `port/patches/1122-lv2-sync-handoff-lwmutex-lwcond-semantics.patch` —
  new `runtime/syscalls/lv2_sync_core.h`; rewrites `sys_lwmutex`,
  `sys_lwcond`, `sys_mutex`, `sys_cond` on one lv2-style core.
- KZ2 `port/patches/6005-lwcond-fifo-wakeups.patch` — the same design inline in
  `ppu_sysprx.cpp` (KZ3 1059 credits KZ2 6005 as its design source).
- inFAMOUS `ps3recomp/runtime/ppu/ppu_sysprx.cpp` lines 445-780 — a different,
  diagnostic-heavy implementation with `[LWCOND-STAT]`.

**Exact functions**

- 1059: `kz3_lwc_init`, `kz3_lwc_reset`, `kz3_lwc_enqueue`,
  `kz3_lwc_wait`, `kz3_lwc_wake`; patched `sys_lwcond_wait`,
  `sys_lwcond_signal`, `sys_lwcond_signal_all`, `sys_lwcond_signal_to`.
- 1122: `lv2s_init`, `lv2s_lock`, `lv2s_unlock`, `lv2s_wait_cond`,
  `lv2s_signal_cond`, `lv2s_release_locked`; `sys_lwmutex_*`/`sys_lwcond_*`
  built on them.
- 6005: `struct LwcWaiter`, `lwc_unlink`, `lwcond_wake(lwcond, all, to_tid)`,
  `sys_lwcond_wait`.
- inFAMOUS: `lwc_wake`, `lwc_strict`, `lws_report`, `lwc_site_poll_cfg`,
  `lwc_bucket`.

**Why it is better than GT6PP's generation counter**

| Semantics | GT6PP generation port | KZ FIFO / 1122 |
|---|---|---|
| `signal` | bumps one generation, `WakeByAddressAll` (all waiters) | marks the oldest queued waiter only |
| `signal_all` | same as `signal` (all) | marks every waiter queued at signal time |
| `signal_to(tid)` | same as `signal` (all) | marks that thread's node, else oldest |
| Lost wakeup | generation snapshot before mutex drop helps, but a waiter woken spuriously can re-wait | node lives on the waiter's stack and is claimed by name; no count stealing |
| Timeout | returns `CELL_OK` on the poll cap (current patch) | unlinks the node and returns `ETIMEDOUT` (`0x8001000B`) |
| Mutex hand-off | releases then reacquires; a third thread can steal it | 1122 hands the lwmutex directly to the woken waiter |

The KZ3 1059 header states the failure it fixes: with a counting semaphore, a
thread woken by `signal_all` could go back to waiting and take the count meant
for another waiter, which then slept on — it names **Killzone 2's FIOS
media-thread startup hang** as the case that exposed it (repo claim). Its host
test reproduces the lost-wakeup mechanism with the old algorithm and passes on
the FIFO. GT6's FileHost has the same shape (client / helper / completion
queues), so this is the right base.

**Tests**

- `tools/spu/test_lwcond_fifo.sh` + `.c` (Helghast): builds the FIFO header with
  pthreads and reproduces the old lost wakeup as a negative control; checks
  `signal`, `signal_to`, and timeout.
- `tools/spu/test_r104_lv2_sync.sh` + `test_r104_lwsync.cpp` (Helghast): lv2
  mutex/cond hand-off and timeout tests.

**Caveats**

- **This cannot fix GT6's current trace by itself.** `lwcond-trace-fix.md` shows
  no E5/E7 signal because the FileHost helper `func_00A08B8C` returns at boot
  (`+0x1C29 == 0`). The producer must exist first.
- 1122 is a large patch (new sync core, `sys_mutex`/`sys_cond` rewrites). Start
  with 1059 if the only goal is `sys_lwcond`; take 1122 only if hand-off or
  timeout semantics are needed.
- GT6PP's wrappers currently ignore the `sys_lwcond_wait` return value, so the
  generation port's `CELL_OK`-on-timeout is tolerated. A FIFO port should restore
  `ETIMEDOUT` for correctness; verify the `0xA21CBC`/`0xA21D50` wrappers first.
- inFAMOUS's implementation is a **different** design (per-object buckets,
  pending counts, `PS3_LWCOND_STRICT_LR`), not a drop-in for 1059. Its value is
  the diagnostic surface:
  - `PS3_TELEM=1` (default on) prints `[LWCOND-STAT]` every 10 s: waits,
    signalled wakes, guest-timeout wakes, poll wakes, **signals with no waiter**,
    per-LR top sites, main-thread wait µs.
  - `PS3_LWCOND_STRICT_LR=<hex lr>[,...]` makes only those wait sites block for
    a real signal (inFAMOUS sets `18631C,18638C` for its movie player).
  - `PS3_LWCOND_MAX_MS=3000` safety net for untimed waits.
  - `LWCOND_PER_OBJ`, `LWCOND_POLL_MS`, `LWCOND_SITE_POLL`, `PS3_LWCOND_POLL`.
  This is the quickest way to prove that a GT6 wait site never receives a
  signal, and to A/B a strict wait at one LR without changing the global model.

**Links**

- <https://github.com/undecuple/project-helghast/blob/main/port/patches/1059-lwcond-per-waiter-fifo.patch>
- <https://github.com/undecuple/project-helghast/blob/main/port/patches/1122-lv2-sync-handoff-lwmutex-lwcond-semantics.patch>
- <https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/6005-lwcond-fifo-wakeups.patch>
- <https://github.com/whompay/inFAMOUSreborn/blob/main/ps3recomp/runtime/ppu/ppu_sysprx.cpp#L445-L780>

---

### F2 — Generic cellFs VFS miss / pre-open hooks (best blocker-2 asset code)

**Where**

- KZ3 `port/patches/0004-vfs-miss-hook.patch`: adds
  `void (*g_ps3_vfs_miss_hook)(char* path, size_t cap)` to
  `runtime/syscalls/sys_fs.c`, called from `ps3_vfs_ps3game_fallback()` when the
  host path still misses. KZ3 uses it to serve files from `data_ps3.psarc`.
- KZ3 `port/patches/4024-cellfs-preopen-hook.patch`: adds
  `void (*g_ps3_fs_preopen_hook)(const char* guest_path, const char* host_path)`
  to `runtime/ppu/ppu_fs.cpp`, called before `cellFsOpen` stats/opens anything.
- KZ3 `port/patches/4018-cellfs-unlink-rmdir-remove-on-host.patch`: real
  `cellFsUnlink`/`cellFsRmdir` with writable-mount checks. Needed when a stale
  FIOS cache is rejected and reopened with `O_CREAT`.
- KZ2 `port/patches/6035-cellfs-preopen-hook.patch` + `port/kz2/kz2_fios_stamp.h`:
  same hook, policy = remove `/dev_hdd1/cache/<title>/fios/cache.idx|dat` on the
  first open after a build/switch. `KZ2_FIOS_STAMP=0` disables it.

**Why it matters for GT6PP**

GT6PP currently has ad-hoc overrides in `gt6/src/stubs.cpp`
(`gt6_script_path_hint`, `gt6_script_read_override`, `work/gt6_pfs_keymap.tsv`)
that only cover `HFileReader`/the boot script. The generic hooks cover every
`cellFsOpen`/`cellFsRead`/AIO path, so the same mapping can serve
`projects/gt6/...`, `image/boot/...`, `font/...`, and the PFS cache from
`work/gt6_vol` without per-file patches. The pre-open hook is also the correct
place to delete a stale FIOS cache that GT6PP cannot write (current `.fdupi` is
0 bytes, `.fdupm` gets only the header).

This does **not** fix the MGOM/presents handoff or the FileHost helper. It only
removes asset-side failures and stale-cache loops.

**Exact integration**

- Set `PS3_HDD0_ROOT` / `PS3_BDVD_ROOT` to the extracted tree.
- Install `g_ps3_vfs_miss_hook` to rewrite a missing host path to
  `work/gt6_vol/<guest-relative-path>`.
- Install `g_ps3_fs_preopen_hook` to remove `fios/cache.idx` and `cache.dat` on
  the first open of that directory (only for the GT6 title id).
- Use `KZ2_FIOS_STAMP=0` A/B to prove the hook is what changed behaviour.

**Caveats**

- The hook must be quick and must not block (both patch headers say so).
- Do not map read-only disc paths into a writable cache root; KZ3 4018 restricts
  deletion to `/dev_hdd0`, `/dev_hdd1`, `/dev_usb*`.
- GT6PP's existing plaintext override is already working for the boot script;
  migrate it behind the hook rather than adding a second path resolver.

**Links**

- <https://github.com/undecuple/project-helghast/blob/main/port/patches/0004-vfs-miss-hook.patch>
- <https://github.com/undecuple/project-helghast/blob/main/port/patches/4024-cellfs-preopen-hook.patch>
- <https://github.com/undecuple/project-helghast/blob/main/port/patches/4018-cellfs-unlink-rmdir-remove-on-host.patch>
- <https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/6035-cellfs-preopen-hook.patch>

---

### F3 — D3D12 boot-screen / 2D toolkit (closest blocker-3 code)

**Where:** Helghast
`port/patches/2002-d3d12-kz3-boot-screen-programs-and-texture-formats.patch`
(plus `2009-live-draw-texture-gamma.patch` for UI gamma).

**What it changes**

1. `libs/video/rsx_fp_decompiler.c`: `float4 r[48]; float4 h[48];` becomes
   `r[64]/h[64]` because FP source/destination fields are 6 bits. KZ3's
   99-instruction boot-screen program used `h50` and failed to compile (E5019),
   then fell back to the built-in colour PS (solid blue/gradient).
2. `vp_get_fp_pso` passes the guest `SET_SHADER_CONTROL` 32-bit-export bit
   (`fp_exp32`) instead of `RSX_FP_CTRL_AUTO` guessing the export file.
3. `tex_fmt_uploadable()` + `tex_decoded_dxgi()`: upload every format
   `rsx_texture_layout()` classifies (packed 16-bit, HILO, depth, X16, Y16X16,
   F16/F32), not only B8/A8R8G8B8/G8B8/DXT1/3/5. KZ3's boot screen sampled six
   64x1 `W16Z16Y16X16_FLOAT` tables and drew black.
4. `SCREEN_AS_TEX` defaults to **0** (was 1): it swapped any display-sized
   texture for the last presented frame, turning KZ3's own 1280x720 scene target
   into a feedback loop.
5. Diagnostics: `DRAWLOG=<N>` (per replayed draw: pipeline or FALLBACK, target,
   viewport, blend, textures), `FP_DUMP_MATCH=<text>`, `FP_FAIL_DUMP=1`
   (keep failed HLSL), `D3D12_DBG=1` (debug layer + InfoQueue messages).

**GT6PP applicability**

GT6PP's backend already has `vp_upload_tex_slot`, `d3d12_bind_texture`, and
`SCREEN_AS_TEX` default **1**; it still has `r[48]/h[48]` and no `DRAWLOG`.
The generic texture formats used by the GPB plates (DXT1 `0xA6`, A8R8G8B8
`0xA5`) are already supported, so this is **not** the missing no-VP GPB path.
The value is:
- `DRAWLOG` / `FP_FAIL_DUMP` to prove whether the first GPB draw reaches the
  guest-FP path or the legacy fallback, and which texture/format it binds.
- the 64-register and `fp_exp32` fixes if the GPB shader is longer than 48
  registers or exports half floats.
- `SCREEN_AS_TEX=0` to rule out a feedback loop on later UI frames.
- 2009 gamma: RSX `TEXTURE_ADDRESS` gamma bits on UI textures; switches
  `LD_NO_GAMMA=1`, `LD_GAMMA_NO_SURF=1`, `LD_GAMMA_LOG=1`.

**Caveats**

- This patch is about KZ3's **guest-FP** boot screen, not GT6's **no-VP** GPB
  plate. GT6PP still needs its own generic legacy textured PSO
  (`patches/gt6-legal-gpb-draw-fix.patch`); 2002 is a supporting toolkit, not a
  replacement.
- No repo contains `GPB`, `PresentsRoot`, `MGOM`, or `execBoot` code.

**Links**

- <https://github.com/undecuple/project-helghast/blob/main/port/patches/2002-d3d12-kz3-boot-screen-programs-and-texture-formats.patch>
- <https://github.com/undecuple/project-helghast/blob/main/port/patches/2009-live-draw-texture-gamma.patch>
- <https://github.com/undecuple/project-helghast/blob/main/port/patches/2005-live-draw-text-diagnostics.patch>

---

### F4 — PAMF / H.264 / movie: mostly negative; one ready audio piece

**PAMF:** none of the five has a usable PAMF parser.

- inFAMOUS's `ps3recomp/libs/codec/cellPamf.c` is **byte-identical** to GT6PP's
  0.18.0 file (`git diff --no-index` is empty). It still reads the stream table
  at `+0x10` and the count at `+0x14`, which `docs/analysis/pamf-intro-fix.md`
  identifies as `psmf_marks_offset/size`; it would report 0 streams for GT6's
  opening movie. Its `cellDmux.c` is the same whole-buffer stub.
- Killzone does not use PAMF: KZ2 uses **AVI + H.264**; KZ3 uses **Bink**.
  KZ2's `cellVdec` H.264 path is already upstream in GT6PP 0.18.0
  (`libs/codec/vdec_ffmpeg.c`, `AV_CODEC_ID_H264`;
  `PS3RECOMP_FFMPEG_RUNTIME`).
- T5DR is docs-only: it documents Windows Media Foundation H.264 decode and
  `PS3_VDEC_STALL_MS` (default 5 s; 0 = wait forever) for a decoder that never
  answers. No code.

**Ready audio piece:** KZ2's `6022-at3-standalone-shared-library.patch` builds
`third_party/at3_standalone` (FFmpeg's ATRAC3/ATRAC3+ decoder as extracted by
PPSSPP, LGPL-2.1+) as `at3_standalone.dll` via `PS3RECOMP_AT3_SHARED`. GT6PP
already has that source tree and `at3_bridge.cpp` (`at3p_open`, `at3p_close`,
`at3p_flush`, `at3p_decode`), and `cellAtrac.c` uses it for music. But
`cellAdec.c` is still a silence stub, and `cellAdecAtrac3p.c` is a separate
silence stub. PAMF's audio is ATRAC3+ 2ch/6ch, so wiring `cellAdec`'s ATRACX
path to `at3p_*` is the concrete movie-audio task. `6023-celladec-ac3-ffmpeg.patch`
shows the shape: decode the AU through the runtime decoder, put the real sample
count/size in `CellAdecPcmItem` and `bsiInfo+0x14`, copy before `AUDONE`, and
keep the decoder in a separate LGPL DLL.

**Verdict:** PAMF demux remains a GT6PP clean-room task; no reference repo
shortens it. ATRAC3+ audio and the H.264 decode plumbing are the reusable parts.

**Links**

- <https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/6022-at3-standalone-shared-library.patch>
- <https://github.com/undecuple/project-pyrrhus/blob/main/port/patches/6023-celladec-ac3-ffmpeg.patch>
- <https://github.com/TheWishin/T5DROnline/blob/main/TROUBLESHOOTING.md#L525-L544>

---

### F5 — Boot/presents project handoff: no reusable fix

No repo contains GT6's `boot.adc` → `presents_sequence_common` →
`PresentsRootSCEA` → `MGOM.start("boot")` path, `execBoot`, `loadPackage`, or
`PresentsRoot`. Their boots are their own engines:

- inFAMOUS: `infamous-recomp/main.cpp` `ppu_boot_frames_presented()` keeps the
  window presenting during a long boot; not a project-request handoff.
- KZ2/KZ3: own front-end/menu flow; KZ2's `KZ2_SKIP_INTRO=1` patches the start
  page word in `port/kz2/main.cpp` (a game-specific script patch, not reusable).
- Project 8 Plus: `mod/native/p8plus_plugin/src/p8plus_intro.c` hooks
  `PlayMovie` and skips logos/intro after the cache is done; same *pattern* as a
  GT6 script patch, but Bink/Neversoft-specific.
- T5DR: online intro skip is a netcode rule.

**Conclusion:** the boot/presents handoff stays GT6-specific. The only reusable
pieces are F2's asset hooks and generic diagnostics; they do not consume
`manager+0x48` or construct `MGOM`.

---

### F6 — Profiling, pacing, launcher (later, not blockers)

- Project 8 Plus: `libs/video/frame_trace.{c,h}` in
  `patches/ps3recomp-thp8.patch` (starts ~line 13394). `PS3_SPIKE_MS=<ms>` turns
  on `[spike]` per-frame itemisation, `[spike-thr]` per-guest-thread CPU/wall
  time and top HLE/syscall keys, `[spike-sum]` every 10 s, plus `[spike-io]` /
  `[spike-tex]` slow-read/decode lines. `PS3_GAME_STATS` covers lwmutex/SPU
  contention. Only fires on presented frames; GT6 does present black frames, so
  it is usable, but GT6PP already has `PS3_LWCOND_TRACE` / `GT6_MAINSTACK`.
- KZ3: `1032-wait-accounting.patch` (`KZ3_WAIT_ACCT=<ms>`) per-host-thread wait
  accounting and `1033-host-sampling-profiler.patch`; `1081` `KZ3_STALL_DIAG=1`.
- Pacing: KZ3 `2072-frame-pacing-metric.patch` (`RSX_PACE=0`, `[pace]` p50/p99),
  `2127-present-never-blocks-frame-thread.patch`, `6040` fullscreen/present
  recovery; Project 8 Plus `PS3_PRESENT_PACE`, `PS3_PACE_STATS`.
- Launcher: KZ2/KZ3 `tools/release/launch.py`, `firstrun.py`, `installer/`;
  Project 8 Plus `builder/` + launcher; inFAMOUS `installer/`.
- None of this is on the critical path until a visible frame exists.

---

## 4. Ranked top 3 (impact on current blockers)

| Rank | Finding | Blocker | Impact | Effort | Confidence | Apply |
|---:|---|---|---|---|---|---|
| **1** | **Per-waiter FIFO lwcond + lv2 hand-off** (KZ3 1059/1122, KZ2 6005) + inFAMOUS `[LWCOND-STAT]` diagnostics | `sys_lwcond` / file-worker completion | **High** semantic fix; **conditional** on GT6's missing producer | M | High (code + host tests) | Start with 1059; use 1122 if hand-off/timeout is needed. Add per-LR stats before/after. |
| **2** | **Generic cellFs VFS miss/pre-open hooks** (KZ3 0004/4024/4018, KZ2 6035) | boot/presents asset path, PFS cache | **Medium** | S-M | High (generic hooks, MIT) | Install `g_ps3_vfs_miss_hook` + `g_ps3_fs_preopen_hook`; map `work/gt6_vol`; test `KZ2_FIOS_STAMP=0` A/B. |
| **3** | **D3D12 boot-screen/2D toolkit** (KZ3 2002 + 2009) | first 2D GPB draw | **Medium** (diagnostics + FP/texture limits; not GPB itself) | M | Medium (KZ3-specific evidence) | Port `DRAWLOG`, `FP_FAIL_DUMP`, `r[64]/h[64]`, `fp_exp32`, all-format upload, `SCREEN_AS_TEX=0`; use with `D3D12_DBG=1`. |
| 4 | **ATRAC3+ movie audio** (KZ2 6022 + existing `at3_standalone`) | PAMF/H.264 playback | Medium (audio only) | S-M | High (decoder already vendored) | Wire `cellAdec` ATRACX to `at3p_open/decode/close`; use 6023's PcmItem shape. |
| 5 | `PS3_SPIKE_MS` / `KZ3_WAIT_ACCT` / pacing | all, later | Low now | S | High | Port after the first visible frame. |

### Why this order

1. **lwcond is the only direct code for blocker 1.** The generation counter is a
   progress workaround: it wakes all waiters and cannot target a thread. FIFO is
   what lv2/FIOS actually expects, and both KZ ports found it necessary for FIOS.
   But GT6's trace has no producer; FIFO alone will still park. The honest
   sequence is: restore the FileHost helper (GT6-local), then port FIFO so the
   restored hand-offs are correct.
2. **cellFs hooks are the only reusable code that touches the boot/PFS asset
   path.** They will not construct `MGOM`, but they remove a whole class of
   path/cache failures and replace GT6PP's ad-hoc per-file overrides.
3. **The 2D toolkit is the closest thing to GPB help, but it is not GPB.** Its
   diagnostics are valuable exactly because GT6PP cannot yet see whether the
   first plate draw is a guest-FP draw or the legacy fallback. The actual no-VP
   textured PSO remains GT6PP's own patch.

---

## 5. Negative findings / traps

- **inFAMOUS's `cellPamf` is not an upgrade.** It is byte-identical to GT6PP
  0.18.0 and uses the same disputed `+0x10/+0x14` layout. Its docs calling it
  "real PAMF header + stream descriptor parsing" are **repo claims**, not true
  for GT6's PAMF0041 movie.
- **No repo has an async `cellFs` worker.** GT6PP, inFAMOUS, and Project 8 Plus
  all `fread()` inline in `cellFsAioRead` and invoke the guest callback before
  returning. The Killzone patches only add pre-open hooks/guest-write tracking.
  Do not expect a ready-made fix for completion ordering.
- **No repo has GPB.** The `GPB` hits in `tools/reference/gt4-staticrecomp` are
  GT4 menu images (`docs/INGAME-SETTINGS-STUDY.md`), not GT6's `3bpg` container.
- **No repo has MGOM/presents.** The boot/presents handoff is PD-engine-specific.
- **RPCS3 is GPL-2.0 reference only.** None of the five links RPCS3 code; KZ
  project rules explicitly forbid copying/paraphrasing it. Keep any RPCS3-derived
  behaviour as independently written code.
- **FFmpeg / at3_standalone are LGPL, not MIT.** KZ2 ships them as separate
  DLLs (`avcodec-63.dll`, `avutil-61.dll`, `at3_standalone.dll`) so they remain
  replaceable. Follow that if GT6PP ships a binary.
- **T5DR is docs-only.** Its `PS3_VDEC_STALL_MS` / WMF notes are useful leads but
  cannot be copied as code; its `patches/ps3recomp/` directory is not in the
  public repo clone.

---

## 6. Recommended next actions

1. **GT6-local (highest):** run the FileHost experiment in
   `docs/analysis/lwcond-trace-fix.md` §5 — keep the `func_00A08A00` `+0x1C2C`
   clear, remove only the `func_00A08B8C` `+0x1C29` early return, and log E4/E5/E7
   generation changes. This is the only step that can create the missing
   producer; no reference repo replaces it.
2. **Port lwcond 1059** (or 1122 if hand-off is needed) and add inFAMOUS-style
   per-LR `[LWCOND-STAT]` (waits / signalled / timeout / poll / signals with no
   waiter). Use `PS3_LWCOND_STRICT_LR` only as a diagnostic A/B.
3. **Install KZ3 0004 + 4024 cellFs hooks** behind `PS3_HDD0_ROOT` /
   `PS3_BDVD_ROOT`; serve `work/gt6_vol`; delete stale FIOS cache on first open.
4. **Port KZ3 2002's `DRAWLOG` / `FP_FAIL_DUMP` / 64-register / `fp_exp32`
   pieces** before testing the legal GPB draw; keep the no-VP textured PSO from
   `patches/gt6-legal-gpb-draw-fix.patch`.
5. **When the movie stage starts:** wire `cellAdec` ATRAC3+ to the existing
   `at3_standalone` bridge (KZ2 6022 pattern), then implement PAMF demux
   clean-room. Do not port inFAMOUS's `cellPamf.c`; it is the same wrong parser.

---

## 7. Attribution / licensing

All five repositories' own code is **MIT** (LICENSE files read). ps3recomp is
MIT. Killzone 2 ships FFmpeg (`avcodec-63.dll`, `avutil-61.dll`) and
`at3_standalone` as separate **LGPL-2.1+** DLLs; Killzone 3 lists FFmpeg as
optional and builds `at3_standalone` inside ps3recomp. RPCS3 is **GPL-2.0** and
is reference-only. inFAMOUS bundles SDL3 (zlib). Project 8 Plus and T5DR use
RPCS3 only for decryption/keys and do not link it. No game data, lifted game
code, assets, or keys were copied into this report or the GT6PP tree.

When porting any code: keep the MIT copyright notice, name the source patch and
commit, and do not copy game-specific tables (KZ FIOS cache names, GT6 GPB
formats, THP8 Bink addresses) into GT6PP.
