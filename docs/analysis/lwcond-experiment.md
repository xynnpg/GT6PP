# lwcond qid/pending experiment — no frame yet

**Date:** 2026-10-31
**Branch:** `opus/boot-frame-3` (from main `447fa03`)
**Status:** experimental; **do not merge as a fix.** No visible game frame was
produced.

## Change

`third_party/ps3recomp/runtime/ppu/ppu_sysprx.cpp`:

1. Key `LwcSlot` by the lwcond **queue id at +4**, not by the guest address.
   The guest copies the 8-byte lwcond in the `0xA21D50` wrappers, so the waiter
   and signaler can pass different addresses for the same kernel object.
2. Keep a **pending signal** when `waiters == 0`, and consume it at the next
   `sys_lwcond_wait` (`fast-wake`). This prevents a completion signal that
   arrives just before the waiter registers from being lost.

The snapshot is in `patches/ps3recomp-lwcond-qid-pending.patch` (against the
current dirty ps3recomp tree; it also includes earlier sysPrx changes).

## Evidence (`work/lwc_run.err`, 200 s, `GT6_BRINGUP_DDS=0`)

| Metric | Value |
|---|---|
| `[LWCOND] wait` | 147 |
| `[LWCOND] signal` | 150 |
| `[LWCOND] woke` | 130 |
| `fast-wake` | 1 |
| `MenuClassDefine` | 0 |
| boot keys `K/LH`/`K/KG`/`K/IE`/`K/WD` | 0 |
| frame check | **FAIL** 0.00% non-black, 1 colour |

The font preload reaches `/font/logo/menu_imagefont.bin`, then tid 1 waits on
`0xCFEFF4A0`; the file worker (tid 14) waits on `0x01632790`; the completion
path signals `0x0164AC20` (qid `0x4C00000A`) with `waiters=0`, which is a
different queue from the waiter. The pending count does not bridge them.

## Conclusion

The qid/pending change is a real improvement to lwcond identity, but it does
**not** fix the frame drop. The file-worker completion is still routed to a
different lwcond than the request wait. Next step:

- log `sys_lwcond_create` address/qid and the wait/signal qid at
  `0xCFEFF4A0` / `0x01632790` / `0x0164AC20`;
- or serve `/font/...` and the other host files synchronously from the
  extracted tree, bypassing the async worker.

Do not count the diagnostic DDS overlay as a frame. The game's own legal draw
is still black.
