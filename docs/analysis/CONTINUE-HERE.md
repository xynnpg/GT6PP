# CONTINUE HERE — GT6 native port

**Date:** 2026-10-31. **Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`.
**Executable:** `gt6/build/gt6.exe` (static MinGW runtime; double-click safe).
**Current visible state:** a black 1280x720 window titled
`Gran Turismo 6 (ps3recomp) | FPS: 0.x | draws: 0 | 1280x720`, process stays alive.
A real Present now happens (`[takeflip] 1`); the flip is a direct
`cellGcmSetFlipCommand`, because GT6's context is an RSX IO address the runtime
FIFO never sees. The remaining black image is `draws: 0`, not an unpainted
window.

**Latest changes (not yet in the last measured run):**
- `0x9F9380` + its 9 sibling jump-table cases added to the lift list as
  `functions_corrected_lab.json`; `func_009F9380` now exists.
- `/dev_hdd0` roots aligned with `PS3_HDD0_ROOT`/`PS3_HDD1_ROOT` so the PFS
  `K/4D` temp file and rename see the same host tree.
- `0x9CD410` now logs the 8 bytes read before the `ADCH` check.

**Reader trace result:**
- `0x9CD69C` opens `PD.fdupi` with flags `0x42` (read/write+create). The read
  reaches `0x9CD410` but `0x9D8DB0 -> 0x994078` returns **0 bytes** and the
  buffer is all zero; this is not ciphertext, it is a failed/deferred read.
- The reader's virtual method target was `0x9D7D78`, also missing from the lift
  table. `functions_corrected_lab2.json` adds it (and 0xA5712C/0xA57184/
  0xA57358) and a full relift/build is in progress.
- `PD.fdupi` is 857,518 bytes after a run but starts `25 0F FF FE`: the game's
  copy path overwrites the file with the raw PFS entry. A pre-placed decrypted
  file is not enough because O_RDWR|O_CREAT opens it and the copy overwrites.
- If lab2 still yields zeros/raw, the next fix must route the reader through the
  PFS decrypt/decompress method (see the PFS fixer/checker reports) rather than
  accepting ciphertext at `0x9CD410`.

**Boot-script override (current build):**
- `gt6/src/stubs.cpp` now has `gt6_script_path_hint(reader, path)` and
  `gt6_script_read_override(ctx)`. When `HFileReader::open` sees
  `scripts/gt6/main`, it loads the already-decrypted 857,518-byte
  `work/gt6_vol/scripts/gt6/main.adc`; `HFileReader::read` serves that stream
  sequentially, but only for that reader object.
- Hooks are in generated `func_009BB11C` / `func_009BB020`; re-apply after a
  relift (not yet added to the relift script).
- This is a one-file bypass, not a general PFS decrypt. It is the fastest way to
  prove the script VM/loading path while the PFS read-through is implemented.
- The current full build (`work/build_final.log`) includes the lifter's absolute
  jump-table switch generation (2690 case functions), so the FileDevice state
  machine should no longer be skipped.

**Regression warning (measured):**
- The newer 70,975-boundary list (`work/relift_last.log`,
  `work/gt6_corrected70975.exe`) no longer reaches GT.VOL completion/script/flip
  within 60 s: it creates 32 threads and runs engine jobs but stalls before
  `SetPrepareFlip`. Do not replace the stable exe with it without a fix.
- The last stable runnable exe is `gt6/build/gt6.exe` copied from
  `gt6/build/gt6.exe.old6`; it opens GT.VOL, presents, and stays alive (black,
  draws 0). Current process pid is recorded in the session log.
- The script-override builds are `work/gt6_script_override.exe` (75,679 lift,
  reads ADCH to 252) and `work/gt6_script_override_off.exe` (offset-sync test).
  They parse the ADCH header then fail with `vector<T> too long` / exit 1.
- Root next fix: the PFS read-through (guest cipher 0x9FF530 + PDISTD SpuInflator
  0xA43AB4/0xA440E4) or the parser's second reader/seek path; see
  `docs/analysis/adch-parser-*.md` and `pfs-decrypt-*.md`.

**MAJOR MILESTONE (2026-10-31 14:43): the boot script fully parses.**
- `work/gt6_lab1_final.exe` = `functions_corrected_lab.json` (70,989) + fixed
  absolute-table lifter + ADCH switch + reader override + setjmp guards.
- `work/lab1_final_run.err`: 255,264 `[scriptov]` reads, last at
  `pos=857517/857518`; **no** `vector<T> too long`, **no** unresolved
  `0x009879xx` call, `sys_process_exit=0`.
- After EOF the game opens its first real PFS asset:
  `/dev_hdd0/.../PDIPFS_bdmark/K/WO`, `GT.VOL`, `K/WO.fdupm` (head zeros),
  `K/WO.fdupi`, then 8192-byte GT.VOL reads. The PFS read-through is the next
  asset blocker.
- Then PPU tid=15 `Spu Event Handler` (entry OPD 0x014E14C0 -> code 0xA564EC,
  arg 0x1675210) logs repeated `bctr to NULL from func_00A569D0+0x533`, one
  `unresolved indirect call -> 0x007F454C` with a bogus TOC, a
  `faulted in guest page 0xFFFF0000` commit, and finally
  `ACCESS VIOLATION ... hle=sys_lwmutex_lock prof_pc=0x00A564EC`.
  `report_crash` terminates the process; that is the second next blocker.
- `cellKbRead` (NID 0xFF0A21B7) is now implemented as a `cellKbGetData` alias in
  `third_party/ps3recomp/libs/input/cellKb.c/.h` and registered for the next
  build.
- Diagnostic: `GT6_CRASH_THREAD_EXIT=1` makes `report_crash` end only the
  faulting host thread instead of the process, so the next stage is observable.
  This is containment, not a fix.
- With containment (build 14:49, `work/gt6_crashguard.exe`, currently running):
  the process stays alive past the SPU-event fault, keeps the window open,
  reaches `takeflip` 13 times and processes `[RSX] CLEAR_SURFACE` 8 times
  (the guest render loop is draining through the D3D12 backend). `draws` stays
  0 because the game has not submitted any `DRAW_ARRAYS` yet: it is waiting on
  the `K/WO` asset load. The WO `.fdupi` cache on disk is still 0 bytes and
  `.fdupm` is 8,212 zero bytes, so the PFS copy/decrypt path produced nothing.
- `cellKbRead` (0xFF0A21B7) is registered in the current exe and no longer logs
  as unresolved.

**NEW MILESTONE (2026-10-31 15:25): UI scripts now load; next stop is a missing compiled script.**
- `work/gt6_spursfix.exe` / current `gt6/build/gt6.exe` includes:
  - the SPURS completion fix (per-instance routing + `maxGrabbedJob` wrap),
  - the indirect-call reporter bounds check (no more fatal diagnostic),
  - the generated `func_00A569D0` id>=16 guard (env-off switch
    `GT6_SPURS_DISPATCH_GUARD_OFF=1` for A/B),
  - the generic PFS plaintext override from `gt6/src/stubs.cpp`
    (`work/gt6_pfs_keymap.tsv`), plus the boot-script override.
- Clean 70 s headless run (`work/fix_run.err`): boot script served, K/WO opened,
  no `ACCESS VIOLATION`, no `0x007F454C`, no guard drops, 12 flips, alive.
- The game then loads real UI assets through the override:
  `products/gt6/script/MenuClassDefine.adc` (K/WO),
  `products/gt6/script/Prototypes.mwidget` (K/6I),
  `projects/gt6/cursor/cursor.mproject` (K/JH),
  `projects/gt6/cursor/cursor.adc` (K/7E).
- The next request is `products/gt6/script/Prototypes.adc`, which does **not**
  exist in GT.VOL or `work/gt6_vol` (only `Prototypes.mwidget`, an MPRJ project,
  exists). The override logs `no extracted file for ...Prototypes.adc`; after
  that the VM spins in `HOTREAD8` on guest `0x19` at `func_009E191C` (a null
  value/byte at +0x19). No draws yet.
- The PFS cache `.fdupi` files remain 0 bytes while `.fdupm` gets the size
  header; the guest's raw cache write/blocks publish is still not working.
- Known remaining unresolved NIDs: `0x7FE92C54/0xBD554BCB` cellUsbd,
  `0x1F71ECBE` sys_io, `0xA5D06BF0/0xCA9A60BF` sysPrxForUser, `0xF6C6900C`.
  `cellKbRead` and `cellSpursInitializeWithAttribute2` are now registered.

**Policy note:** `third_party/PDTools/AGENTS.md` prohibits any AI/LLM use of
that vendored repository (reading, deriving code, or processing it). Do not use
that subtree for PFS/path work; use the GT6 binary, GT.VOL data, and this
project's own tools instead. This was discovered while looking for a path
resolver; the PFS fix must not copy or derive from PDTools.

**Final corrected lift (2026-10-31 14:2x):**
- `work/analysis/emain/functions_corrected.json` is now 70,975 functions
  (13,204 ledger records; 8,310 starts added, 3,425 ends corrected, 0 OPD loss).
  This split the 213 stale over-merged bodies from the earlier list.
- `tools/apply_gt6_post_lift.py` is wired into `scripts/relift-gt6.ps1`
  (`[5/9]`) and adds the setjmp guards plus the `HFileReader`
  open/read/seek script-override hooks after every lift.
- The current build (`work/build_last.log`) is this list + the fixed lifter's
  switch generation (2,690 case functions) + override. Test it before trusting
  any older result.

**Final measured script result (2026-10-31 14:0x, pre-final-list):**
- With the switch-based relift + override, the guest reads the ADCH stream
  sequentially: 8 bytes at offset 0, then 1/1/1/26/1/33/... through offset 252.
  No exception during those reads.
- **Corrected:** the "no more `[scriptov]` calls after 252" is the 32-line log
  cap in `gt6_script_read_override`, not a parser stop. The 33rd read is
  `offset=253 len=5`; the reader consumes the whole 6,412-symbol table and
  reaches the 5,564-instruction code frame. The real blocker is the unresolved jump-table
  `bctr` at guest `0x987910` (`func_00987884`), and `vector<T> too long` is its
  downstream consequence. See `docs/analysis/adch-parser-fix.md`.
- Artifact: `work/gt6_script_override.exe` contains the switch relift +
  override; `work/final_run.err`, `work/ov2_run.err` have the traces.
- The runnable fallback is `gt6/build/gt6.exe` from `gt6.exe.old6` (stable black
  window, GT.VOL opened, present active); `work/gt6_prelab2.exe` is another
  fallback.

## What already works (measured)

1. Exact exe runs from any CWD; it detects the project root and redirects noisy
   logs to `work/gt6.log` unless `PS3_VERBOSE=1` or `GT6_CONSOLE=1`.
2. Guest entry, TLS, `cellGcmInit`, four 1280x720 display buffers, tiles/Zcull,
   flip handlers, SPURS init, and the corrected `.ctors` walk (722 entries) run.
3. **GT.VOL opens and is read**:
   - open `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL`
   - first 160-byte header, then 514,436-byte TOC
   - `PDIPFS_bdmark/K/PD`, `PDIPFS/K/PD.fdupm`, then ~772 KB of PFS data reads
4. **15 runtime SPURS job binaries** captured from `SPU_DUMP_MISS`, lifted at LS
   base 0, registered as image ids 6..20. Logs now show `dispatch HIT` and
   `job ... RETURNED rc=0`. All 8 WWS PMs resolve (image 5).
5. `SetPrepareFlip(1/2)` and `SetFlipImmediate(0)` occur. `GCM_GUEST_FB` is now
   the default, so the window presents the guest display buffer (black, draws 0)
   instead of crashing on the empty D3D12 present path.
6. Static C++ runtime (`-static`), so no `libc++.dll`/`libunwind.dll` errors.

## The current blocker (measured)

The boot-script call and then teardown:

```
main 0x1096C
 -> 0x13830("scripts/gt6/main")     # synchronous script loader
 -> 0x13BA8                         # teardown sequence
     -> 0x14518 -> 0x9F74E4
         -> 0x9F88B4 -> 0x9F7A84 -> 0x9F7C60
             -> 0xA301A8 -> 0xF9AC18 (system/HLE wait)
```

`GT6_MAINSTACK=5` shows main parked in `func_00F9AC18` with this host chain.
`0x13BA8` calls `0x13D04, 0x14594, 0x13DA0, 0x7DD6E8, 0x88980C, 0x7DBDDC,
0x14428, 0x14518, 0x13DE0`; it is the shutdown/cleanup path, not the game loop.
So `0x13830` returned (script load failed or the script finished immediately),
and main is waiting in teardown while worker threads/SPU jobs still run.

The volume read proves the PFS is mounted. The script manager path is:

```
0x13830 -> virtual [manager+0x120] -> 0x9A7654
 -> 0x9CDF00 -> 0x9CD798
     -> 0x9CC068  # std::map lookup for a registered loader callback
         1 = handler found -> 0x9CDEA8 -> return 1
         0 = not found -> fallback loader 0x9CD69C -> 0x9CD410 -> 0x9CC208
                          failure returns r27=0 at 0x9CDEEC
```

Measured: `0x9A7654` returns **0**, so the fallback loader failed. It has read
~772 KB of PFS data by then. The next question is **why the reader/handler
returns failure**, not whether GT.VOL opened.

## Highest-value next tasks

1. **Trace `0x9CD798` branch outcomes** after the 772 KB read: instrument
   `0x9CC068` return, `0x9D4F50` return, and `0x9CDEEC`/`0x9CDEA8` hits in
   generated `ppu_recomp_022.cpp`. Identify the first failing condition.
2. **Confirm whether `scripts/gt6/main.adc` is the 772 KB PFS read** and whether
   its header/decryption is valid. Compare with `work/gt6_vol/scripts/gt6/main.adc`
   (857,518 bytes). The PFS report is `docs/analysis/pfs-script.md`.
3. **Why main enters 0x13BA8 immediately after `0x13830`.** If the script VM is
   supposed to block, find the return/error path that ends it. Do not patch main
   to park; fix the script return.
4. **RSX draws:0.** Once the script keeps running, verify the FIFO put pointer
   and first draw method; see `docs/analysis/rsx-first-frame.md`.
5. **Unresolved late NIDs** seen during the run:
   `0xCA9A60BF`, `0xBD554BCB`, `0x7FE92C54`, `0xA5D06BF0`, `0x1F71ECBE`
   (sysPrxForUser/cellUsbd/sys_io). They may be optional input/USB, but check
   whether any return value gates the script.

## Commands

```powershell
# build (LLVM-MinGW on PATH is handled by the script)
powershell -File scripts/build-gt6.ps1

# exact exe, normal run (logs -> work/gt6.log, guest FB present)
gt6\build\gt6.exe work\bin\EMAIN.elf

# diagnostic run: console + verbose, keep SPU miss capture
$env:PS3_VERBOSE="1"; $env:GT6_CONSOLE="1"; $env:SPU_DUMP_MISS="work/spu_jobs/dump"
gt6\build\gt6.exe work\bin\EMAIN.elf

# main-thread location / all PPU threads
$env:GT6_MAINSTACK="5"; $env:GT6_THREADS="1"

# relift (corrected boundaries + control-flow patches + WWS PM + jobs)
powershell -File scripts/relift-gt6.ps1
```

Useful env: `PPU_STUCKMAX=1000000` (default set by main), `GCM_GUEST_FB`
(default `0,1280,720,6144`), `SPU_MISS_FAKE_OK=1` (diagnostic only),
`PS3_HEADLESS=1`, `PS3_CALLTRACE`, `PS3_HLE_TRACE`, `GCM_DRAINDBG`,
`GT6_SCRIPT_TRACE=1` (log every boot-script read/seek; replaces the old
32-line `[scriptov]` cap).

## Patches that must survive a relift

- `tools/setjmp_patch_gt6.py` (GT6 pair `0xB98168`/`0xB9828C`).
- `tools/ctor_walk_patch.py` (restores `.ctors` walker `r31` after slot 351).
- `tools/apply_gt6_post_lift.py` (boot-script hooks + the ADCH `0x987910`
  jump-table switch; fails the relift via `tools/post_lift_fixes.py` if lost).
- `scripts/lift-spu-gt6.ps1` (WWS PM, image 5).
- `scripts/lift-spu-jobs.ps1` (15 runtime jobs, ids 6..20).
- Runtime: `vm_oob` wrap check in `third_party/ps3recomp/runtime/ppu/ppu_loader.cpp`.

## Reports

- `docs/analysis/boot-chain.md` — main/script/CRT analysis.
- `docs/analysis/boundary-audit.md` — corrected 70,672-function list.
- `docs/analysis/hle-nids.md` — three boot NIDs.
- `docs/analysis/spu-spurs.md` — WWS PM and dispatch.
- `docs/analysis/spin-triage.md` — current main wait (agent, in progress).
- `docs/analysis/rsx-first-frame.md` — white/black screen and FIFO (agent, in progress).
- `docs/analysis/pfs-script.md` — GT.VOL/script reads (agent, in progress).
- `docs/analysis/pfs-decrypt-fix.md` — PFS reader/cipher/inflate analysis.
- `docs/analysis/adch-parser-fix.md` — ADCH read trace, the `0x987910` switch,
  and the `vector<T> too long` chain.

Do not commit `gt6/generated/`, `gt6/build/`, `work/`, game data, decrypted ELFs,
`GT.VOL`, or keys.
