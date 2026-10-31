# RPCS3 oracle: GT6 v1.00 boot, cursor UI, and `Prototypes.adc`

**Date:** 2026-10-31
**Scope:** offline oracle only. No native-port source, no game data, and no
`PS3-Version/` file was modified. `third_party/PDTools` and
`GTAdhocToolchain` were not read or used.
**Oracle:** `tools/RPCS3/rpcs3.exe`, RPCS3 v0.0.43-20524-df090aa1 Alpha,
firmware 4.50, AMD Ryzen 5 5600 / RX 6650 XT.

## 0. Short answer

- The v1.00 US disc (`BCUS98296`, `APP_VER=01.00`) **does boot in RPCS3 to a
  real GT6 loading/legal screen** (1280x720, "GRAN TURISMO 6 / © 2013 Sony
  Computer Entertainment Inc." plus the Polyphony Digital logo and legal
  text). It does **not** reach the menu in the oracle runs below; it stops in
  RPCS3's PPU/SPU compilation, HDD game-data install, or a Vulkan swapchain
  failure.
- RPCS3 does **not** create or load `products/gt6/script/Prototypes.adc`.
  The file is not in GT.VOL, not in the extracted tree, and not in the
  PDIPFS key map. The game's own boot asks for it only after
  `MenuClassDefine.adc` / `Prototypes.mwidget` / `cursor.mproject` /
  `cursor.adc` (native trace, see `docs/analysis/CONTINUE-HERE.md` and
  `docs/analysis/prototypes-adc-check.md`).
- The v1.00 disc cannot supply `Prototypes.adc`; it supplies only
  `Prototypes.mwidget`, whose magic is `MPRJ`, not `ADCH`. A fabricated ADCH
  cannot substitute for the real prototype registrations.
- **Verdict:** the disc alone reaches a GT6 loading image in RPCS3, and
  `Prototypes.adc` is a real functional dependency of the v1.00 UI script
  path. It is not produced by the disc or by RPCS3. The official GT6 update is
  the legitimate source.

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
`CurrentSettings.ini` was backed up and is restored at the end of the session
(see §8).

## 2. Boot sequence observed

### 2.1 RPCS3's own progress screens (not game content)

The first 3–5 minutes are RPCS3 compiling the game:

```text
Building SPU Cache...   Progress: module 4952 of 10933
Linking PPU Modules...  Progress: module 0 of 1
Applying PPU Code...    Progress: module 160 of 160 (4m remaining)
Precompiling shader interpreter variants... Building base variant 2736 of 6650
```

These overlays are drawn **over the game's first frame**, which is already the
GT6 legal/copyright screen. `work/rpcs3_oracle/frames_async/frame_010s.png`
and `frame_020s.png` show the GT6 logo and "© 2013 Sony Computer Entertainment
Inc." behind the SPU-cache progress bar.

### 2.2 First game loading screen

`work/rpcs3_oracle/frames_hdd_precreated/frame_042s.png` is the first clean
1280x720 game frame captured (no RPCS3 compile overlay except the game's own
message box):

- black background;
- "© 2013 Sony Computer Entertainment Inc." / manufacturers-and-cars legal
  text;
- "POLYPHONY DIGITAL" / "Developed by Polyphony Digital Inc.";
- a game message box: `Insufficient free space on Hard Disk Drive (HDD). At
  least 32MB required. 0x00000001a [183]`.

That message box is the game reacting to a **failed `cellGameContentPermit`**,
not to a real host disk shortage.

### 2.3 What created that HDD error

On a clean emulated HDD, the game runs its game-data creation path:

```text
cellGame: cellGameDataCheck(type=3, dirName="BCUS98296", ...)
cellGame: cellGameDataCheck(): directory '/dev_hdd0/game/BCUS98296' not found
cellGame: cellGameCreateGameData(...)
cellGame: cellGameCreateGameData(): temporary directory
         '/dev_hdd0/game/_GDATA_25252858792800' has been created
cellGame: cellGameContentPermit(...)
```

If `/dev_hdd0/game/BCUS98296` was pre-created by hand (even with the disc's
`game/BCUS98296` tree copied in), RPCS3's permit step fails:

```text
cellGame: cellGameContentPermit(): failed to initialize directory
         '/dev_hdd0/game/BCUS98296' (Already exists)
```

The game then displays the "Insufficient free space" dialog above. This is an
oracle-setup trap: **do not pre-create the game-data directory**. Let the game
create `_GDATA_*` and rename it itself.

After a clean run, `/dev_hdd0/game/BCUS98296` contains a valid `PARAM.SFO`,
`ICON0.PNG`, and the PDIPFS cache the game installed from `GT.VOL`
(`USRDIR/PDIPFS/K/*`, `USRDIR/PDIPFS_bdmark/K/*`, `USRDIR/db/userdb0101.dat`,
`USRDIR/grim2/*`). That is the v1.00 game-data install, not an update.

### 2.4 Emulator failures that stop the oracle

Two RPCS3-side failures were reproduced:

1. **Vulkan swapchain resize** when the game window is minimized or occluded:

   ```text
   RSX: Swapchain: Current surface extent is a null region. Is the window minimized?
   SIG: Thread terminated due to fatal error: Invalid swapchain setup.
        Resizing the game window failed. (VKPresent.cpp:489)
   ```

2. **_gcm_intr_thread** access violation during the PPU-apply phase:

   ```text
   PPU[0x1000002] Thread (_gcm_intr_thread) [0x00b7ba80]:
     VM: Access violation reading location 0xc (unmapped memory)
   PPU[0x1000002] Thread (_gcm_intr_thread) [0x00000000]:
     SIG: Thread terminated due to fatal error: Unknown/Illegal opcode:
     0x00000000 at 0x0
   ```

These are RPCS3 emulator problems. They are not evidence that the disc is
missing a boot asset. The game reached the legal loading screen and the HDD
install path in both cases.

## 3. `Prototypes.adc`: what the disc actually contains

Independent checks (read-only, no PD Tools):

```text
GT.VOL: 14.349 GB, 32,591 entries (work/gt6_volume_entries.txt,
work/gt6_pfs_keymap.tsv)
```

Relevant TOC rows:

```text
K/WO  products/gt6/script/MenuClassDefine.adc   Compressed  FileIndex 34
K/6I  products/gt6/script/Prototypes.mwidget    Compressed  FileIndex 35
K/7E  projects/gt6/cursor/cursor.adc            Compressed  FileIndex 57
K/W2  projects/gt6/cursor/gpb/CursorProject.gpb Compressed  FileIndex 58
K/CF  projects/gt6/cursor/gpb/CursorProjectComponent.gpb
```

There is **no row** for `Prototypes.adc`, no case variant, and no alternate
key. `work/gt6_vol/products/gt6/script/` contains exactly:

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
`Prototypes`, `prototypes`, and `registerPrimitives`. That matches the native
trace's request for `products/gt6/script/Prototypes.adc` and the later null
read. `Prototypes.mwidget` is an MPRJ project; the ADCH parser rejects it
because its first four bytes are not `ADCH`.

## 4. Why the RPCS3 log does not show `Prototypes.adc`

GT6 does not open each virtual asset by name through `cellFs`. It opens the
single volume once:

```text
sys_fs_open(path="/dev_bdvd/PS3_GAME/USRDIR/GT.VOL", flags=00, ...)
sys_fs_open(): fd=3, Regular file, ... 14.349GB ...
```

and then reads via its own PDI/PDIPFS layer. Individual TOC paths
(`MenuClassDefine.adc`, `Prototypes.mwidget`, `cursor.adc`, …) never appear in
RPCS3's `sys_fs` log. Therefore "no `Prototypes.adc` line in RPCS3.log" is
expected and is **not** proof of absence. The proof is the GT.VOL TOC and the
PDIPFS key map: there is no entry to request.

The installed `dev_hdd0/game/BCUS98296` was also searched for `*.adc`,
`Prototypes*`, `CursorProject*`, and `MenuClass*` after the install. Nothing was
created. The game does not compile a missing ADCH on first boot in this oracle.

## 5. Does RPCS3 show the GT6 menu with the v1.00 disc alone?

Not in these runs. What it does show:

| Stage | Result | Evidence |
|---|---|---|
| Disc mount / EBOOT boot | PASS | `SYS: Title: Gran Turismor6`, `Serial: BCUS98296`, `APP_VER=01.00` |
| First game pixels | PASS | GT6 legal/copyright screen, 1280x720 (`frames_async/frame_010s.png`, `frame_020s.png`) |
| HDD game-data creation | PASS (clean HDD) | `cellGameCreateGameData` → `_GDATA_*` → `PARAM.SFO`, `ICON0.PNG`, `PDIPFS` |
| Menu | NOT REACHED | RPCS3 swapchain / `_gcm_intr_thread` failures during PPU apply and install |

A fullscreen Vulkan run was also attempted (`run_fs.ps1`, `config_vk_fs.yml`)
to avoid the resize failure. Its result is recorded in §7. Even if that run
reaches the menu, nothing in the v1.00 disc can supply `Prototypes.adc`; the
file has no TOC entry.

## 6. What the native port should copy

1. **Do not fabricate `Prototypes.adc`.** The MPRJ header is not ADCH, and a
   synthesized ADCH would not contain the real prototype registrations.
   `MenuClassDefine.adc` calls `loadPrototype("Prototypes")` and then
   `registerPrimitives(prototypes)`; a fake file only moves the failure.
2. **Keep the v1.00 PDIPFS/GT.VOL path as the source of truth for TOC-backed
   assets.** The disc's `MenuClassDefine.adc`, `Prototypes.mwidget`,
   `cursor.mproject`, `cursor.adc`, and `CursorProject.gpb` are all present and
   must be served exactly. The native port's extracted-tree override is
   equivalent for those files.
3. **Treat `Prototypes.adc` as an update-only asset.** The official GT6 update
   is the legitimate source; install the real ADCH with
   `tools/gt6_install_companion_script.py` after extracting it from the update
   PKG.
4. **Do not pre-create the RPCS3 game-data directory** when reproducing this
   oracle; let `cellGameCreateGameData` / `cellGameContentPermit` do it. This
   avoids the "Already exists" → "Insufficient free space" false error.
5. **For oracle screenshots, prefer RPCS3's F12 capture** (saved under
   `tools/RPCS3/screenshots/BCUS98296/`) once the game is past PPU apply. Native
   window captures (`PrintWindow`) are affected by occlusion, minimization, and
   Vulkan swapchain resizes.

## 7. Fullscreen run result

`work/rpcs3_oracle/run_fs.ps1` boots with:

```powershell
tools\RPCS3\rpcs3.exe --no-gui --fullscreen `
  --config work\rpcs3_oracle\config_vk_fs.yml `
  "PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)"
```

Vulkan fullscreen avoided the window-resize crash. The run reached 60 FPS after
the PPU/SPU caches were warm and displayed the **"Adjust Display Area"**
first-run screen at 1920x1080. That screen is game/system content, not an RPCS3
overlay:

- `work/rpcs3_oracle/fs_printwindow.png` — four corner marks, "Press the up
  and down buttons to move the four marks so that they sit exactly in the four
  corners of the screen", "When you've finished your adjustment, press the X
  button".

RPCS3's default input path is active even when `Keyboard: "Null"` is set in
`config.yml`:

```text
Input: Input configuration empty. Adding default keyboard pad handler
Input: Pad 0: device='Keyboard', handler=Keyboard, VID=0x0, PID=0x0
```

The fullscreen run was stopped without sending the X/confirm input, so it did
not advance past this screen. `work/rpcs3_oracle/run_input.ps1` repeats the
boot with a keyboard input schedule (X at t=24/33/45/63/90 s, Enter at
t=54/75 s) and captures before/after frames under
`work/rpcs3_oracle/frames_input/`.

Timeline and log: `work/rpcs3_oracle/run_fs.timeline.txt`,
`work/rpcs3_oracle/rpcs3_fullscreen.log`.

> The input run did not reach the menu before its 240 s budget; the SPU cache
> for the next boot phase was still being built (`Building SPU Cache... module
> 1352 of 12066`). A longer follow-up is recorded below if it completed.

## 8. Config hygiene

- `tools/RPCS3/config/config.yml` was never written; SHA-256 before/after:
  `4EAA5686A715A1A6756CEA738F1A942A8C632AFE273B6E6AEB55A9B19A1AADCB`.
- `tools/RPCS3/config/games.yml` was unchanged
  (`9D3ED4FB140B26FCA18AB626E15828F315D9C4EA8C2A7C4999CEF6B58F7E303D`).
- `GuiConfigs/CurrentSettings.ini` was backed up to
  `work/rpcs3_oracle/CurrentSettings.ini.bak` and restored after the runs.
  RPCS3 rewrites window geometry/visibility on exit, so the restored file is
  the original backup, not a hand-merged one.
- All oracle configs and logs are under `work/rpcs3_oracle/`. The only files
  written under `tools/RPCS3/` are the emulator's own log, its caches, the
  installed `dev_hdd0/game/BCUS98296` game data, and an empty
  `screenshots/BCUS98296/` directory.

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
Select-String work\rpcs3_oracle\rpcs3_async.log `
  -Pattern 'GT.VOL|cellGameDataCheck|cellGameCreateGameData|cellGameContentPermit|fatal error'

# 4. Verify the missing file independently
Select-String work\gt6_volume_entries.txt -Pattern 'Prototypes'
Select-String work\gt6_pfs_keymap.tsv -Pattern 'Prototypes|MenuClassDefine|cursor.adc|CursorProject'
```
