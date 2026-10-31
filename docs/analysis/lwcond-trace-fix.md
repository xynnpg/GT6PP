# lwcond trace + generation-based wait fix

**Date:** 2026-10-31
**Base:** main `08f92ec`
**Status:** implementation ported into the working tree; **not built or run**.
**Reference:** `tools/reference/soyjxck-ps3recomp/runtime/ppu/ppu_sysprx.cpp`
(lines 410-519), the ps3recomp fork behind the playable Drakengard 3 port.
MIT; attribution is kept in the source comment.

## 0. Bottom line

| Question | Answer |
|---|---|
| What replaced the semaphore/pending experiment? | A per-queue generation counter: signal = `fetch_add(1)` + `WakeByAddressAll`; wait = snapshot generation before dropping the lwmutex, then `WaitOnAddress` with a 1 ms poll cap. |
| What is the lwcond identity? | The queue id at `lwcond+4` (`0x4C000000` range), exactly as the fork. Guest copies of the 8-byte structure now resolve to the same host channel. |
| Did the old experiment fail because of the qid key? | No. The trace shows **no signal at all** to the waiter's queue; qid keying and pending counts cannot bridge a signal that is never issued. The experiment also replaced GT6's 1 ms poll progress with an **infinite** semaphore wait (`tmo=0` -> `WaitForSingleObject(..., INFINITE)`), so the single-wait A21CBC wrapper parked instead of proceeding. |
| Is the frame fixed? | **Unproven.** This is the requested, sibling-port-proven lwcond implementation. If the run still parks in the FileHost read, section 5 names the next suspect (the `0x00A08B8C` early-return guard that kills the FileHost helper thread). |
| Patch | `patches/ps3recomp-lwcond-generation.patch` (supersedes `patches/ps3recomp-lwcond-qid-pending.patch`). |

## 1. What the run actually did

`work/lwc_run.err` (200 s, `GT6_BRINGUP_DDS=0`, `PS3_LWCOND_TRACE=1`):

| Metric | Value |
|---|---|
| `[LWCOND] wait` | 147 |
| `[LWCOND] signal` | 150 |
| `[LWCOND] woke` | 130 |
| `fast-wake` | 1 |
| `MenuClassDefine` | 0 |
| frame check | **FAIL** 0.00% non-black, 1 colour |

The failing sequence (line numbers from `work/lwc_run.err`):

```
799: [LWCOND] wait tid=1 lwcond=0xCFEFF4A0 ...
801: [fileread] 9F4AA0 stream=0xCFEFF590 req=0xD0044C58 file=0xCFEFF480
802: [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFF590 active=0x00 old=0x00000000
803: [LWCOND] signal tid=14 lwcond=0x016326A0 qid=0x4C000012 waiters=1 pending=0
804: [LWCOND] wait tid=14 lwcond=0x01632790 ...
805: [LWCOND] woke tid=4 lwcond=0x016326A0
806: [LWCOND] wait tid=4 lwcond=0x01632730 ...
```

From that point on there is no `signal` to `0xCFEFF4A0`, `0x01632790`, or
`0x01632730`. The main thread (tid 1) waits on the file object's event; the
file worker (tid 14) waits on the FileHost read-completion event; the FileHost
helper (tid 4) waits on the FileHost "idle/drain" event. Three-way park.

## 2. lwcond object map

### 2.1 The FileHost events (`dev = 0x01630B80`)

`func_00A08D00` (guest `0x00A08D00`) constructs eight lwmutex+lwcond pairs in
order with `func_00A21E60` (`0x00A21E60` -> `func_00A43248` ->
`sys_lwmutex_create` + `sys_lwcond_create`):

| event | object base | cond at `+0x18` | inferred qid |
|---|---|---:|---:|
| E0 | `dev+0x1AA8` | `0x01632640` | `0x4C000010` |
| E1 | `dev+0x1AD8` | `0x01632670` | `0x4C000011` |
| E2 | `dev+0x1B08` | `0x016326A0` | `0x4C000012` **(observed)** |
| E3 | `dev+0x1B38` | `0x016326D0` | `0x4C000013` |
| E4 | `dev+0x1B68` | `0x01632700` | `0x4C000014` |
| E5 | `dev+0x1B98` | `0x01632730` | `0x4C000015` |
| E6 | `dev+0x1BC8` | `0x01632760` | `0x4C000016` |
| E7 | `dev+0x1BF8` | `0x01632790` | `0x4C000017` |

The E2 qid is directly observed in the line-803 signal. The other qids are
fixed by the constructor order (the eight `A21E60` calls in `0x00A08D00` are
consecutive); they are **inferred**, not printed in the old log. The new
`[LWCOND] create` probe prints the exact qid on the next run.

Roles from the guest code:

* E2 `0x016326A0`: "read request available". `func_00A08ED0` (StartRead,
  vtable `FileHost+0x10`) signals it, then waits E7. The FileHost helper
  (`func_00A092B0`, tid 4) waits on it.
* E5 `0x01632730`: waited by `func_00A08F98` (vtable `FileHost+0x1C`). In the
  original code E5 is signalled only by `func_00A08A00` (FileHost reset /
  abort: wait E0/E1, then signal E2..E7).
* E7 `0x01632790`: "read complete". `func_00A0919C` (vtable `FileHost+0x0C`)
  signals it and then waits E6. `func_00A08ED0` waits on it.
* E4 `0x01632700`: "fill request". `func_00A0901C` (vtable `FileHost+0x18`)
  signals it; the flush/read helper `func_00A08ADC` waits on it.

### 2.2 The main thread's wait (`0xCFEFF4A0`)

The wait is on the event embedded in the caller's local
`PDISTD::FileInternalStreamDefault`:

* file object `0xCFEFF480` (the `[fileopen] 9F8E40 ... file=` value),
* event/mutex at `file+0x08`, lwcond at `file+0x20` = **`0xCFEFF4A0`**.

It is constructed by `func_00A21E60` while the open request is prepared by the
main thread. Its qid is whatever `sys_lwcond_create` hands out at that moment;
the immediately preceding requests used `0x4C0000BC`, `0x4C0000BF`, and
`0x4C0000C2..0x4C0000CD`, so the failing event is expected to be **at least
`0x4C0000CE`**. No `signal` with that (or any nearby) qid appears in the log.

### 2.3 `0x0164AC20` is not the file completion

`0x0164AC20 = 0x0164AAE8 + 0x138`. `0x0164AAE8` is the menu-worker holder
printed by the boot probe:

```
[GT6] menu worker prepare holder=0x0164AAE8 obj=0x7FFEC000 flag=0
```

It has qid `0x4C00000A` - the 10th lwcond created, six allocations **before**
the FileHost E0 (`0x4C000010`). tid 30 (the menu worker, created at line 452)
`signal_all`s it periodically for the whole run (line 15016 onward, every
~13k log lines). It is a menu frame/tick event, not a file-request queue.

**The earlier note in `lwcond-experiment.md` ("the completion path signals
0x0164AC20") is therefore a misread of a periodic menu signal.** The file
completion signal is not misrouted; it is never emitted.

## 3. Why qid keying alone did not help

The experiment keyed slots by `lwcond+4` (correct) and remembered a pending
signal when `waiters == 0` (not lv2 semantics). The failing trace has:

* no signal to the main event `0xCFEFF4A0` (qid expected >= `0x4C0000CE`);
* no signal to E7 `0x01632790` (`0x4C000017` expected), so tid 14 never wakes;
* no signal to E5 `0x01632730` (`0x4C000015` expected), so tid 4 never wakes.

`pending` cannot create a producer. Worse, the experiment's wait used
`WaitForSingleObject(c->sem, INFINITE)` whenever the guest passed `tmo=0`.
GT6's `func_00A21CBC` waits **once** and does not re-check a predicate, so a
missing signal parks the thread forever. The pre-experiment code returned
after `Sleep(1)`; that poll-progress behaviour is what the generation port
restores (see section 4).

## 4. Ported implementation

Changes in `third_party/ps3recomp/runtime/ppu/ppu_sysprx.cpp`:

1. `#include <atomic>` (top of file).
2. `sys_lwcond_create` keeps the qid assignment and adds a
   `[LWCOND] create tid=... lwcond=... qid=... lwmutex=... lr=...` probe
   (gated by `PS3_LWCOND_TRACE`).
3. `lwc_gen(lwcond)` reads `+0x04` and returns
   `&s_lwc_gen[qid & 4095]` only for `(qid & 0xFF000000) == 0x4C000000`.
   Any other id is unkeyed and falls back to the old 1 ms sleep.
4. `lwc_wake` does `fetch_add(1, release)` then `WakeByAddressAll`.
   `signal` and `signal_all` both bump once and wake all; the fork does the
   same because it does not track a waiter count. A spurious wake only makes
   a predicate-loop guest re-check; for GT6's one-shot A21CBC wrappers the
   1 ms poll already produced the same effect.
5. `sys_lwcond_wait`:
   * reads `seen = gen.load(acquire)` **before** clearing the lwmutex
     owner/recursive fields and calling `lwm_release(sl)`;
   * after the release, if `gen == seen`, calls
     `WaitOnAddress(&gen, &seen, 4, (max_us + 999) / 1000)`;
   * `max_us` is `PS3_LWCOND_POLL_MS` (default 1 ms), capped by the guest
     timeout when it is shorter;
   * the 1 ms cap is load-bearing, not just a safety net: when no signal ever
     arrives, `WaitOnAddress` returns after the cap and `sys_lwcond_wait`
     returns `CELL_OK`, which is the old `Sleep(1)` poll-progress behaviour.
     GT6's A21CBC waits once, so this is what lets the file request finish
     instead of parking on an infinite semaphore;
   * then `lwm_acquire(sl, 0)` and restores the owner/recursive count.
6. Removed the `LwcSlot` semaphore, `waiters`, `pending`, `fast-wake`, and the
   `PS3_LWCOND_POLL` mode. `PS3_LWCOND_SLEEP=1` restores the old `Sleep(1)`
   path for A/B. `PS3_LWCOND_POLL_MS=<n>` changes the cap.
7. Trace lines now carry `qid` and `gen`:
   `wait`, `woke`, `signal`/`signal_all`, and `create`.

`win32_compat.h` already provides `WaitOnAddress`/`WakeByAddressAll` on POSIX
(a hashed parking lot that broadcasts), so the fork's
`std::condition_variable` fallback is not needed. The value is changed before
the wake, which is the ordering that rules out a lost wake.

**Timeout return:** the fork returns `CELL_OK` when the poll cap expires.
GT6's A21CBC/A21D50 wrappers ignore the return value, and the cap is the
progress path for their one-shot wait. We keep that behaviour. The old code
returned `CELL_ETIMEDOUT` after a guest timeout; if a title is found to depend
on it, restore it in one line.

**Attribution:** the algorithm is from
`soyjxck/ps3recomp` (MIT), `runtime/ppu/ppu_sysprx.cpp`, lines 410-519.
Our adaptation is only the `lwm_slot`/`lwm_release`/`lwm_acquire` mapping and
the trace.

## 5. Residual risk / next check (unproven)

The generation wait is correct even when the producer never runs: it makes
progress on the 1 ms poll cap instead of parking on an infinite semaphore. It
cannot invent the missing E5/E7 producer, but it does let GT6's single-wait
wrappers fall through. If the next run still ends at the same three waits,
check the FileHost helper thread before adding any new HLE workaround.

Evidence that the helper is killed by a post-lift guard:

* Thread tid 5 is created with OPD `0x014DFE80` = guest **`0x00A08B8C`**
  (verified by parsing `work/bin/EMAIN.elf`).
* Original `0x00A08B8C` is:
  ```
  00A08B8C: mr    r9,r3
  00A08B90: li    r0,1
  00A08B94: clrldi r3,r3,0x20
  00A08B98: stb   r0,0x1C28(r9)   ; flush requested = 1
  00A08B9C: b     0x00A08ADC       ; flush/read pump, waits on E4
  ```
  It is a persistent helper: `0xA08ADC` signals E1, then loops on E4
  (`dev+0x1B68`, cond `0x01632700`) and calls `0x009F44D8` (the internal PFS
  stream read) on each fill request.
* The generated tree has an injected guard
  (`gt6/generated/ppu_recomp_023.cpp`, `func_00A08B8C`):
  ```c
  if (vm_read8(ctx->gpr[3] + 0x1C29) == 0) return;
  ```
  applied by `tools/gt6_filedevice_flush_patch.py`. At boot `+0x1C29`
  (read-active) is 0, so tid 5 returns immediately and exits:
  `work/lwc_run.err:40-42` (`sys_ppu_thread_exit(tid=5)`), long before the
  first read at line 799.
* With no E4 waiter, the FileHost fill/read path has no helper to produce the
  E5/E7 hand-offs. The `+0x1C2C` dead-pointer clear added by the same patch is
  still needed; the *early return* is the suspect.

Unproven: whether keeping tid 5 alive is sufficient to complete the read. The
minimal experiment is to keep the `func_00A08A00` `+0x1C2C = 0` clear, drop
only the `func_00A08B8C` early return, and log `E4`/`E5`/`E7` generation
changes. Do not add a blank guard or a fake SET_STATE.

## 6. Apply / verify

The working tree already contains the port. The reference patch is against a
clean `third_party/ps3recomp` HEAD and **supersedes**
`patches/ps3recomp-lwcond-qid-pending.patch`:

```powershell
# clean ps3recomp tree only:
git -C third_party/ps3recomp apply --check ..\..\patches\ps3recomp-lwcond-generation.patch
git -C third_party/ps3recomp apply         ..\..\patches\ps3recomp-lwcond-generation.patch
```

Build and run on the owner's side. Useful environment:

```powershell
$env:PS3_LWCOND_TRACE="1"      # create/wait/woke/signal with qid+gen
$env:PS3_LWCOND_POLL_MS="1"   # default cap
$env:PS3_LWCOND_SLEEP="1"     # A/B: old 1 ms sleep path
```

Expected new trace shape:

```
[LWCOND] create tid=1 lwcond=0x016326A0 qid=0x4C000012 lwmutex=0x01632688 lr=...
[LWCOND] wait   tid=1 lwcond=0xCFEFF4A0 qid=0x4C0000CE gen=N ...
[LWCOND] signal tid=14 lwcond=0xCFEFF4A0 qid=0x4C0000CE gen=N+1 ...
[LWCOND] woke   tid=1 lwcond=0xCFEFF4A0 qid=0x4C0000CE gen=N+1 ...
```

Success criteria for this change alone:

* every wait that is signalled wakes within one poll interval;
* no `fast-wake`/pending bookkeeping in the trace;
* the qid printed at `create` matches the qid at both `wait` and `signal`
  for the same object, including stack copies.

Frame success still requires the FileHost producer described in section 5.
Do not count the diagnostic DDS overlay as a frame.
