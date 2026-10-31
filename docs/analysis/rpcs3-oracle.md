# RPCS3 oracle: GT6 v1.00 boot, cursor UI, and `Prototypes.adc`

**Date:** 2026-10-31
**Scope:** offline oracle only. No native-port source, no game data, and no
`PS3-Version/` file was modified. `third_party/PDTools` and
`GTAdhocToolchain` were not read or used.
**Oracle:** `tools/RPCS3/rpcs3.exe`, RPCS3 v0.0.43-20524-df090aa1 Alpha,
firmware 4.50, AMD Ryzen 5 5600 / RX 6650 XT.

## 0. Short answer

- The v1.00 US disc (`BCUS98296`, `APP_VER=01.00`) **does boot in RPCS3 with no
  official update installed**. It reaches the GT6 legal/loading screen, the
  first-run display-area screen, the epilepsy warning, the intro movie, and the
  **Player Name (first-run profile) screen**. It opens the GT6 on-screen
  keyboard for the name fields, writes a real GT6 save
  (`BCJS37016-GAME6`, files `GT6.0`…`GT6.5`), and exits/restarts. The main menu
  was not reached because the automated run did not complete the OSK name
  entry.
- The real game loads the same cursor-UI assets the native port logs:
  `MenuClassDefine.adc` (PDIPFS key `K/WO`), `Prototypes.mwidget` (`K/6I`),
  `cursor.mproject` (`K/JH`), `cursor.adc` (`K/7E`), and
  `CursorProject.gpb` (`K/W2`). **No `Prototypes.adc` cache key or file
  appears.** There is no TOC/keymap entry for it, and no such file exists in
  the emulated HDD before or after the save.
- `Prototypes.adc` is genuinely absent from the v1.00 disc, but the oracle
  shows it is **not required for the v1.00 cursor/first-run UI**. The real
  engine consumes `Prototypes.mwidget` (MPRJ) and continues. The native port's
  request for `products/gt6/script/Prototypes.adc` is therefore a loader/path
  artifact (it appends `.adc` to the prototype name), not a missing disc asset.
- **Verdict:** the v1.00 disc alone reaches the first-run game UI and saves in
  RPCS3. `Prototypes.adc` is **not** a boot/cursor-UI requirement on the real
  v1.00 disc; sourcing it from the update would mask a native loader bug. Fix
  the native `loadPrototype`/MPRJ path instead of requiring the update file.

This contradicts the earlier "update-only, required" conclusion in
`docs/TOOLING.md` and `docs/analysis/prototypes-adc-check.md`. The oracle
evidence is below; those documents should be corrected before the next fix
cycle.

## 1. How the oracle was run (without touching the user's config)

The user's `tools/RPCS3/config/config.yml` was **not** edited. A copy was made
under `work/rpcs3_oracle/` and passed with `--config`:

```powershell
Copy-Item tools\RPCS3\config\config.yml work\rpcs3_oracle\config.yml
# Shader Mode: Async Recompiler (avoids the 6,650-variant interpreter
# precompile; gameplay/asset logic is unchanged)
tools\RPCS3\rpcs3.exe --no-gui `
  --config work\rpcs3_oracle\config.yml `
  "PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)"
```

RPCS3 was booted on the **disc root**, not on `EBOOT.BIN` directly. This makes
RPCS3 mount the disc correctly:

```text
VFS: Mounted path "/dev_bdvd" to "...\Gran Turismo 6 (USA) (En,Ja,Fr)/"
VFS: Mounted path "/dev_bdvd/PS3_GAME" to ".../PS3_GAME/"
VFS: Mounted path "/app_home" to ".../PS3_GAME/USRDIR/"
SYS: Title: Gran Turismor6
SYS: Serial: BCUS98296
SYS: Category: DG
SYS: Version: APP_VER=01.00 VERSION=01.00
```

The `Log:` map in the copy enabled `cellFs`, `sys_fs`, `cellGame`,
`cellSysutil`, and `cellStorage` at `Trace`. RPCS3 writes the log to
`tools/RPCS3/log/RPCS3.log`; each run was copied to
`work/rpcs3_oracle/rpcs3_*.log`.

The GUI log-level setting in `GuiConfigs/CurrentSettings.ini` only filters the
on-screen log. The file log uses the per-channel `Log:` map; trace lines appear
in the file even with the GUI at "Notice". The original
`CurrentSettings.ini`/`persistent_settings.dat` were backed up and are restored
at the end of the session (see §8).

## 2. Boot sequence observed

### 2.1 RPCS3 progress screens over the game's first frame

The first cold boot spends several minutes compiling PPU/SPU code. These
overlays are RPCS3's, drawn over the game's legal/copyright screen:

```text
Building SPU Cache...   Progress: module 4952 of 10933
Linking PPU Modules...  Progress: module 0 of 1
Applying PPU Code...    Progress: module 160 of 160 (4m remaining)
```

`work/rpcs3_oracle/frames_async/frame_010s.png` and `frame_020s.png` show the
GT6 logo and "© 2013 Sony Computer Entertainment Inc." behind the SPU-cache
progress bar. The legal text is the game's first real frame, not an RPCS3
screen.

### 2.2 HDD game-data creation (do not pre-create the directory)

On a clean emulated HDD the game runs its game-data creation path:

```text
cellGame: cellGameDataCheck(type=3, dirName="BCUS98296", ...)
cellGame: cellGameDataCheck(): directory '/dev_hdd0/game/BCUS98296' not found
cellGame: cellGameCreateGameData(...)
cellGame: cellGameCreateGameData(): temporary directory
         '/dev_hdd0/game/_GDATA_25252858792800' has been created
cellGame: cellGameContentPermit(...)
```

If `/dev_hdd0/game/BCUS98296` is pre-created by hand (even with the disc's
`game/BCUS98296` tree copied in), RPCS3's permit step fails:

```text
cellGame: cellGameContentPermit(): failed to initialize directory
         '/dev_hdd0/game/BCUS98296' (Already exists)
```

The game then displays `Insufficient free space on Hard Disk Drive (HDD). At
least 32MB required. 0x00000001a [183]` over the legal screen
(`work/rpcs3_oracle/frames_hdd_precreated/frame_042s.png`). This is an
oracle-setup trap, not a real host disk shortage: **let the game create
`_GDATA_*` and rename it to `BCUS98296` itself.**

After a clean run, `dev_hdd0/game/BCUS98296` contains a valid `PARAM.SFO`,
`ICON0.PNG`, the installed PDIPFS cache, `USRDIR/db/userdb0101.dat`, and
`USRDIR/grim2/*`. That is the v1.00 game-data install, not an update.

### 2.3 Emulator failures that stop some runs

Two RPCS3-side failures were reproduced:

1. **Vulkan swapchain resize** when the game window is minimized or occluded:

   ```text
   RSX: Swapchain: Current surface extent is a null region. Is the window minimized?
   SIG: Thread terminated due to fatal error: Invalid swapchain setup.
        Resizing the game window failed. (VKPresent.cpp:489)
   ```

2. **_gcm_intr_thread** access violation during PPU apply:

   ```text
   PPU[0x1000002] Thread (_gcm_intr_thread) [0x00b7ba80]:
     VM: Access violation reading location 0xc (unmapped memory)
   PPU[0x1000002] Thread (_gcm_intr_thread) [0x00000000]:
     SIG: Thread terminated due to fatal error: Unknown/Illegal opcode:
     0x00000000 at 0x0
   ```

Vulkan **fullscreen** avoids the resize failure. The successful first-run run
used `--no-gui --fullscreen` and RPCS3's default keyboard pad handler.

## 3. The real cursor/first-run asset sequence

GT6 does not open each virtual asset by name through `cellFs`; it opens the
single volume once:

```text
sys_fs_open(path="/dev_bdvd/PS3_GAME/USRDIR/GT.VOL", flags=00, ...)
sys_fs_open(): fd=3, Regular file, ... 14.349GB ...
```

and then reads through its own PDI/PDIPFS layer. Individual TOC paths never
appear in `RPCS3.log`, so the proof of what was loaded is the **PDIPFS cache
that the game writes to the emulated HDD**. After the successful fullscreen run,
these files exist under
`tools/RPCS3/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/` (host creation time
`2026-10-31 16:54:10`, i.e. during that run; they were not copied from the
disc's `game/BCUS98296` folder):

| Key | Compressed cache size | TOC path (from `work/gt6_pfs_keymap.tsv`) |
|---|---:|---|
| `K/WO` | 3,620 | `products/gt6/script/MenuClassDefine.adc` (12,464 uncompressed) |
| `K/6I` | 1,408 | `products/gt6/script/Prototypes.mwidget` (5,827 uncompressed) |
| `K/JH` | 6,258 | `projects/gt6/cursor/cursor.mproject` (46,637 uncompressed) |
| `K/7E` | 13,205 | `projects/gt6/cursor/cursor.adc` (40,290 uncompressed) |
| `K/W2` | 59,991 | `projects/gt6/cursor/gpb/CursorProject.gpb` (239,744 uncompressed) |

This is exactly the native port's logged sequence up to `CursorProject.gpb`.
There is **no `Prototypes.adc` key, file, or TOC row**. The real game then
rendered the Player Name screen and saved; it did not ask for a compiled
`Prototypes` script.

The keymap has 32,591 entries and only `K/6I` for `Prototypes`:

```text
K/6I  products/gt6/script/Prototypes.mwidget  Compressed  35  5217  580  16C3  AAF000
```

`work/gt6_vol/products/gt6/script/` contains exactly:

```text
12,464  MenuClassDefine.adc
 5,827  Prototypes.mwidget
```

Magic bytes:

```text
MenuClassDefine.adc   41 44 43 48 30 31 32 00   "ADCH012\0"
cursor.adc            41 44 43 48 30 31 32 00   "ADCH012\0"
Prototypes.mwidget    4D 50 52 4A 01 0E 0A 4D   "MPRJ..."
CursorProject.gpb     33 62 70 67 00 00 00 00   GPB container
```

`MenuClassDefine.adc` contains the literal strings `loadPrototype`,
`Prototypes`, `prototypes`, and `registerPrimitives`. `Prototypes.mwidget` is
an MPRJ project; the ADCH parser rejects it because its first four bytes are
not `ADCH`. The real v1.00 engine clearly handles that MPRJ and does not need a
separate `Prototypes.adc` for the cursor/first-run UI.

## 4. What this means for `Prototypes.adc`

The earlier analysis established two facts correctly:

1. `Prototypes.adc` is absent from GT.VOL.
2. `MenuClassDefine.adc` references `loadPrototype("Prototypes")` and then
   `registerPrimitives(prototypes)`.

The missing step was the oracle check: **does the real v1.00 engine actually
request a `.adc` for that call?** The RPCS3 run says no:

- It loaded `Prototypes.mwidget` (`K/6I`), `cursor.mproject` (`K/JH`),
  `cursor.adc` (`K/7E`), and `CursorProject.gpb` (`K/W2`).
- It rendered the GT6 Player Name screen (a real cursor/UI screen) and wrote
  `cellSaveDataAutoSave2(dirName="BCJS37016-GAME6", ...)` with `GT6.0`…`GT6.5`,
  `ICON0.PNG`, and `PIC1.PNG`.
- It never wrote or read a `Prototypes.adc` cache key/file.

Therefore the native port's `/products/gt6/script/Prototypes.adc` open is not
faithful to v1.00. The likely bug is in the native `loadPrototype` path
extension: the real engine resolves the prototype project to
`Prototypes.mwidget` (MPRJ) and/or the shared `Prototype.gpb`, while the native
loader appends `.adc` and expects an ADCH. A real ADCH from the update would
make the native port advance, but it would **mask** the loader bug and would
not reproduce the v1.00 data flow.

Caveat: this oracle proves the cursor/first-run path, not every later menu.
A later code path could still use an update-provided ADCH. But the v1.00 boot
and cursor UI demonstrably do not require it.

## 5. Does RPCS3 show the GT6 menu with the v1.00 disc alone?

It reaches the **first-run player/profile UI** and saves. The main menu was not
observed in the 240 s input run: the game saved and exited/restarted at
`0:01:35` (`_sys_process_exit(status=0)`), which is consistent with a normal
first-run restart. A follow-up boot with the save present is recorded in §7.

| Stage | Result | Evidence |
|---|---|---|
| Disc mount / EBOOT boot | PASS | `SYS: Title: Gran Turismor6`, `Serial: BCUS98296`, `APP_VER=01.00` |
| First game pixels | PASS | GT6 legal/copyright screen, 1280x720 (`frames_async/frame_010s.png`) |
| Display area | PASS | `fs_printwindow.png` ("Adjust Display Area") |
| Epilepsy warning | PASS | `frames_input/frame_030s.png` |
| Intro movie | PASS | `frames_input/frame_045s.png` |
| Player Name UI | PASS | `frames_input/frame_075s.png` |
| Save data | PASS | `cellSaveDataAutoSave2`, `dev_hdd0/home/00000001/savedata/BCJS37016-GAME6/GT6.0…5` |
| Cursor assets | PASS | PDIPFS cache `K/WO`, `K/6I`, `K/JH`, `K/7E`, `K/W2` |
| `Prototypes.adc` | NOT PRESENT / NOT LOADED | no TOC row, no cache key, no file |
| Main menu | NOT REACHED IN AUTOMATION | OSK name entry needs manual pad-grid input; no asset error |

Observed visual/draw sequence (all 2D / FMV; no 3D car or race draw before the
Player Name screen):

1. GT6 legal/copyright screen (`frames_async/frame_010s.png`).
2. "Adjust Display Area" system screen (`fs_printwindow.png`).
3. Epilepsy warning (`frames_input/frame_030s.png`).
4. Intro movie (`frames_input/frame_045s.png`).
5. Player Name + welcome boxes (`frames_input/frame_075s.png`,
   `frames_after/frame_060s.png`).
6. GT6 OSK (`interact/05_after_down_x.png`, `interact/08_after_ok.png`).

## 6. What the native port should copy

1. **Do not require or fabricate `Prototypes.adc` for the v1.00 boot/cursor
   path.** The real game reaches the Player Name screen without it.
2. **Fix the prototype loader.** Match the real sequence: serve
   `MenuClassDefine.adc` (`K/WO`), `Prototypes.mwidget` (`K/6I`),
   `cursor.mproject` (`K/JH`), `cursor.adc` (`K/7E`), and
   `CursorProject.gpb` (`K/W2`), and make `loadPrototype("Prototypes")` use the
   MPRJ/prototype project instead of appending `.adc`.
3. **Keep the v1.00 PDIPFS/GT.VOL path as the source of truth for TOC-backed
   assets.** The disc supplies every asset the real first-run flow used.
4. **Do not pre-create the RPCS3 game-data directory** when reproducing this
   oracle; let `cellGameCreateGameData`/`cellGameContentPermit` do it.
5. **Use fullscreen Vulkan for oracle screenshots.** Windowed mode hits the
   swapchain resize failure when the window is minimized/occluded. F12 saves to
   `tools/RPCS3/screenshots/BCUS98296/`; `PrintWindow` also works for the
   fullscreen window.
6. If the official update is installed later, treat its `Prototypes.adc` as an
   **optional later-path asset**, not as the fix for the v1.00 cursor spin.

## 7. Fullscreen and input runs

### 7.1 Display-area run (no confirm input)

`work/rpcs3_oracle/run_fs.ps1`:

```powershell
tools\RPCS3\rpcs3.exe --no-gui --fullscreen `
  --config work\rpcs3_oracle\config_vk_fs.yml `
  "PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)"
```

Warm caches reached 60 FPS in ~20 s and displayed "Adjust Display Area"
(1920x1080). RPCS3's default input path is active even with
`Keyboard: "Null"` in `config.yml`:

```text
Input: Input configuration empty. Adding default keyboard pad handler
Input: Pad 0: device='Keyboard', handler=Keyboard, VID=0x0, PID=0x0
```

The run was stopped without X/confirm, so it stayed on that screen.

### 7.2 Input run: X/Enter through first-run UI

`work/rpcs3_oracle/run_input.ps1` sent X (Cross) at t=24/33/45/63/90 s and
Enter (Start) at t=54/75 s. Captures under
`work/rpcs3_oracle/frames_input/`:

- `frame_030s.png` — epilepsy warning.
- `frame_045s.png` — intro movie (black-and-white cars on a road).
- `frame_075s.png` — **Player Name (English Characters)** with First Name /
  Last Name fields and OK, over the GT6 blue UI. This is the first real cursor
  UI screen captured.
- The game then wrote the save at `0:00:53` (`cellSaveDataAutoSave2`) and
  exited at `0:01:35` (`_sys_process_exit(status=0)`), after `cellKbEnd()` and
  unloading `libsysutil_oskdialog_ext.sprx`. This looks like the normal
  first-run save/restart, not a crash.

### 7.3 Follow-up boot with the save present

`work/rpcs3_oracle/run_after.ps1` boots again with the save and sends X at
t=30/60 s, Enter at t=45 s, capturing under
`work/rpcs3_oracle/frames_after/`. The game replays the intro movie, then
returns to the **Player Name** screen with the first-run welcome boxes:

- `frames_after/frame_045s.png` — intro movie again.
- `frames_after/frame_060s.png` — Player Name screen with "Welcome to Gran
  Turismo 6!".
- `frames_after/frame_075s.png` — second message, "Greetings from the Gran
  Turismo Association…".

Interactive captures under `work/rpcs3_oracle/interact/` show the on-screen
keyboard opening for the name fields:

- `05_after_down_x.png` / `08_after_ok.png` — the **GT6 OSK** ("[Enter Text]",
  A/a, @#:, Space, Backspace, Return) over the Player Name screen.
- `06_after_typing.png` — first-name field focused after the OSK closes.

The OSK is navigated with the pad grid, not host text injection; the automated
run did not finish the name entry, so the **main menu was not reached**. This
is an automation limit, not an asset failure: the cursor UI, the Player Name
screen, the welcome flow, and the OSK all render with the v1.00 disc alone.
No `Prototypes.adc` cache key or missing-asset error appeared in this flow.


### 7.4 Key log excerpts from the successful first-run run

```text
cellSaveData: cellSaveDataAutoSave2(version=1, dirName="BCJS37016-GAME6",
             errDialog=0, setBuf=..., funcStat=..., funcFile=..., ...)
cellSaveData: savedata_op(): Recreating savedata. (mode=2)
cellSaveData: SECUREFILE: GT6.1 -> 0x771d1c71e75b4e70803873f7402511a7
cellSaveData: SECUREFILE: GT6.2 -> 0x771d1c71e75b4e70803873f7402511a7
...
cellKb: cellKbEnd()
cellSysmodule: unload_module(): path="external/libsysutil_oskdialog_ext.sprx"
sys_process: _sys_process_exit(status=0, arg2=0x0, arg3=0x0)
```

The save files are real, not RPCS3 metadata:

```text
dev_hdd0/home/00000001/savedata/BCJS37016-GAME6/
  GT6.0  310 B
  GT6.1  23,093 B
  GT6.2  8,968 B
  GT6.3  1,183 B
  GT6.4  36 B
  GT6.5  36 B
  ICON0.PNG  14,214 B
  PIC1.PNG   4,481 B
  PARAM.SFO  3,012 B
```

The game did not create a save on the pre-created-HDD run (it stopped at the
false "Insufficient free space" dialog); the save above is from the clean run
with the v1.00 disc alone.

## 8. Config hygiene

- `tools/RPCS3/config/config.yml` was never written; SHA-256 before/after:
  `4EAA5686A715A1A6756CEA738F1A942A8C632AFE273B6E6AEB55A9B19A1AADCB`.
- `tools/RPCS3/config/games.yml` was unchanged
  (`9D3ED4FB140B26FCA18AB626E15828F315D9C4EA8C2A7C4999CEF6B58F7E303D`).
- `GuiConfigs/CurrentSettings.ini` and `persistent_settings.dat` were backed up
  to `work/rpcs3_oracle/*.bak` and restored after the runs. RPCS3 rewrites
  window geometry/visibility on exit, so the restored file is the original
  backup, not a hand-merged one.
- All oracle configs/logs are under `work/rpcs3_oracle/`. The only files
  written under `tools/RPCS3/` are the emulator's own log, caches, the
  installed `dev_hdd0/game/BCUS98296` game data, the `BCJS37016-GAME6` save,
  trophies, and the screenshot directory.

## 9. Commands used

```powershell
# 1. Copy the config and enable file logging
Copy-Item tools\RPCS3\config\config.yml work\rpcs3_oracle\config.yml
# edit work\rpcs3_oracle\config.yml: Shader Mode: Async Recompiler;
# Log: cellFs/sys_fs/cellGame/cellSysutil/cellStorage: Trace

# 2. Boot the disc root (not EBOOT.BIN directly)
tools\RPCS3\rpcs3.exe --no-gui `
  --config work\rpcs3_oracle\config.yml `
  "PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)"

# 3. Inspect the log
Select-String work\rpcs3_oracle\rpcs3_input.log `
  -Pattern 'GT.VOL|cellGameDataCheck|cellSaveData|cellKb|fatal error'

# 4. Verify the missing file independently
Select-String work\gt6_volume_entries.txt -Pattern 'Prototypes'
Select-String work\gt6_pfs_keymap.tsv -Pattern 'Prototypes|MenuClassDefine|cursor.adc|CursorProject'

# 5. Verify what the real game actually loaded (after a run)
Get-ChildItem tools\RPCS3\dev_hdd0\game\BCUS98296\USRDIR\PDIPFS -Recurse -File |
  Where-Object { $_.FullName -match 'K\\(WO|6I|JH|7E|W2)$' }
```
