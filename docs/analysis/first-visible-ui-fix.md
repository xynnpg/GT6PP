# First visible legal UI: boot/presents path, not W2

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`,
`gt6/build/gt6.exe`.
**Scope:** read-only analysis of the oracle load order, `main.adc`/`boot.adc`
code frames, the native logs, and the lifted engine project/package loaders.
No build and no `gt6.exe` run was performed for this report. Files added:
`tools/gt6_boot_ui_probe.py`, `patches/gt6-boot-ui-probe.patch`,
`tools/gt6_gpb_extract.py`. `third_party/PDTools` and `GTAdhocToolchain` were
not read or used.

> **Later trace update (2026-10-31):** the probe build (`work/bootui_run.err`)
> stalls at `HOTREAD8 ... guest-fn=0x009E911C` with `r11=0` before
> `MenuClassDefine` appears. The `execBoot` analysis below applies to runs
> where `MenuClassDefine` is actually served. See
> `docs/analysis/boot-presents-fix.md` for the exact `execBoot` branch and the
> new VM/null-bytecode blocker.

## 0. Verdict

| Question | Answer |
|---|---|
| First asset-mapped legal sequence | `boot.adc` `display_sequence_gt6` calls `presents_sequence_common`, which opens `PresentsRootSCEA` and iterates `common/JP/scei` (2 s) -> `common/notice` (2 s) -> `scea/JP/epilepsy` (4 s). |
| The 15 s GT6/©/ESRB frame | **Still unmapped.** No extracted GT.VOL GPB matches the full composition. Do not use it as the PresentsRoot acceptance target; use the 30 s epilepsy frame (exact `epilepsy.dds` match) or the `notice` frame. |
| Does native execute `main.adc`? | **Yes.** `MenuClassDefine` is required only by `main.adc:initMenuSystem`, which is called only by `execBoot`, which is called only by the `main.adc` top-level frame. Native loads it, so `execBoot` ran. |
| Does the ADCH VM drop the present/font calls? | **No.** The VM is executing `hExecCode` and builtin-method dispatch in the same window: `func_009EEA88` (`hExecCode::step`), `func_00987A2C`, `func_00DFA51C` (`h_builtin_method` argument check) are in the native GSTACK. |
| First missing step | **The boot project is never loaded/registered.** `MGOM.start("boot")` (`main.adc` line 280) enters the engine `MMenuGameObjectManager::start` entry (`0x006C54DC`), which starts an already-registered object; it does not open a `.mproject`. Native never calls the project loader `0x005FA338` with `boot`, so `boot.mproject` (K/KG), `boot.adc` (K/LH), `BootProject.gpb` (K/IE), `PresentsRootSCEA.gpb` (K/WD) never open. |
| Consequence in native logs | After the cursor assets, the engine has already fallen through to `MainLoop`'s `LoadMenuResource` (`main.adc` 5456-5480): `manager.loadPackage(PROJECT_ROOT_DIR + "/arcade/arcade")` etc. The `.mpackage` loader `0x005F7D9C` gets a null object and `0x006CC5D0` performs the measured null writes at `0x4/0x8/0xC`. |
| Fonts | Font keys (`K/4M`...`K/2F`) are a **separate early engine preload** on the `ksF3` worker pool. Native creates the workers but issues no font opens. Fonts are not required for PresentsRoot (it uses GPB textures), so this is not the first fix for the legal screen. |
| W2 | W2 is loaded **before** boot in the oracle too. Its zero-data read is real, but it is not the reason the PresentsRoot assets are absent: the boot project load never starts. W2 is downstream of the missing boot registration. |
| Draw/backend | Not reached. There is no textured UI draw to decode or sample yet; the D3D12 no-VP texture gap is downstream. |

## 1. Oracle order and the exact presents sequence

### 1.1 PDIPFS order that matters

The successful oracle run creates these cache objects in this order (host
creation times 16:54:09-11, `tools/RPCS3/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/`):

```text
K/4M  font/vec/IwataUD_M_latin.vec          69,040
K/5I  font/vec/IwataUD_M_JP.vec          1,923,568
K/V4  font/vec/IwataUD_B_latin.vec          60,368
K/HP  font/vec/IwataUD_B_JP.vec          1,883,168
K/TY  font/vec/IwataUD_E_latin.vec          59,696
K/G4  font/vec/IwataUD_L_latin.vec          69,536
K/CP  font/vec/GTfcItalic.vec              16,224
K/6L  font/vec/GTMeterNum.vec              10,720
K/9N  font/vec/GThk.vec                    47,904
K/D8  font/vec/FT_B.vec                    36,864
K/MR  font/vec/7seg.vec                    10,512
K/2F  font/logo/menu_imagefont.bin         29,847
K/WO  products/gt6/script/MenuClassDefine.adc   3,620
K/6I  products/gt6/script/Prototypes.mwidget    1,408
K/JH  projects/gt6/cursor/cursor.mproject       6,258
K/7E  projects/gt6/cursor/cursor.adc           13,205
K/W2  projects/gt6/cursor/gpb/CursorProject.gpb 59,991
K/KG  projects/gt6/boot/boot.mproject           4,146
K/LH  projects/gt6/boot/boot.adc               45,923
K/IE  projects/gt6/boot/gpb/BootProject.gpb     7,434
K/WD  projects/gt6/boot/US/PresentsRootSCEA.gpb 69,530
```

The oracle log (`work/rpcs3_oracle/rpcs3_input.log`) shows the main thread opening
K/WO at `0:00:27.158`, K/6I at `27.177`, K/JH at `27.195`, K/7E at `27.213`,
K/W2 at `27.225`, K/KG at `27.240`, K/LH at `27.259`, K/IE at `27.328`, and
K/WD at `27.445`. The font keys are opened on `ksF3` thread `0x1000010` at
`26.909`-`26.934`, i.e. **before** the main script even opens `K/PD`
(`scripts/gt6/main.adc`). This is why fonts are an independent preload, not a
`main.adc` call.

### 1.2 Script path

`main.adc` (source `scripts/gt6/Application.ad` + `bootstrap.ad`) has a single
top-level module constructor at code offset `0x1D11EB` (instruction line 5467).
It calls `bootstrap_phase1_module.execBoot` at `0x1D122F` (line 5474), then
`MainLoop` at `0x1D143C` (line 5526).

`execBoot` (`main.adc` line 280) is:

```text
initModules()            ; REQUIRE pdistd, pdiext, menu, gtmenu, gtengine, pdiapp
initApp()
initArgs()
initMenuSystem()         ; REQUIRE PRODUCT_ROOT_DIR + "/script/MenuClassDefine"
MGOM.start("boot")       ; <-- the boot project entry point
```

`boot.adc` is the project script that owns `display_sequence_gt6` (code offset
`0x1875F`). Its first instruction at line 23 unconditionally calls
`presents_sequence_common(context)`; the rest of the function only decides
whether to continue to save data/language select/AdjustScreenRoot/MovieRoot.
`presents_sequence_common` selects `PresentsRootSCEA` for `scea` and iterates
`presents_table_scea` (`common/JP/scei` 2 s, `common/notice` 2 s,
`scea/JP/epilepsy` 4 s). **If `boot.adc` never loads, this function does not
exist and no presents/AdjustScreenRoot/movie asset can be requested.**

## 2. What the native port actually executes

### 2.1 Proven: `execBoot` ran

`initMenuSystem` is the only caller of the `MenuClassDefine` `REQUIRE`, and
`execBoot` is its only caller. Native serves `MenuClassDefine.adc` at:

```text
work/flush_long.err:1241
work/size_run.err:257989
[GT6] pfs override: serving plaintext products/gt6/script/MenuClassDefine.adc (12464 bytes, ...)
```

Therefore the top-level frame, `execBoot`, and `initMenuSystem` all ran. This
rules out "main is executing a different startup path" and "the ADCH parser
never reaches the bootstrap module".

### 2.2 Proven: the VM is alive at the failure point

After W2, `work/size_run.err:289194` contains:

```text
[GSTACK:nw] chain: func_005F7D9C+0x74 func_00DFA51C+0x1CC
    func_009C625C+0x64 func_009B0918+0x1A8 func_009F0748+0xDC
    func_009EEA88+0x1B8 func_00987884+0x64 func_00987A2C+0x364 ...
```

and `289205`:

```text
[GSTACK:nw] sp=0xCFEFEB50: func_009D5064+0x70 func_00014AB4+0x10
    func_005F7D9C+0x74 func_00A4BAF0+0xBC func_0097D1C0+0x1C
    func_009794A8+0x20 func_009A6144+0x4C func_00DFA51C+0x1CC
    func_009C625C+0x64 func_009E57A8+0x44 func_009B0918+0x1A8 ...
    func_009EB96C+0x50 func_009EF3BC+0xDC func_009EEA88+0x1B8 ...
```

`0x009EEA88` is `hExecCode::step`; `0x00DFA51C` is the builtin-method
invoker that checks the argument count and throws
`RuntimeError("argument count is wrong ...")` (`0x1053890`,
`h_builtin_method.h` at `0x10538B8`); `0x005F7D9C` is the
`MENU::mManager::loadPackage(string)` builtin (`0x005F7D9C` + `.mpackage` at
`0x1053A00`). This is **script bytecode calling an engine builtin**, not a
parser dead end.

This also rules out a dropped ADCH CALL for the presents functions:
`presents_sequence_common` and `display_sequence_gt6` are defined in
`boot.adc`, not `main.adc`. Their names are not in the `main.adc` symbol table
(6,412 symbols), so no `main.adc` CALL can target them. The VM cannot execute a
function from a module it has not loaded; the missing event is the `boot.adc`
module load itself, which happens before any presents bytecode exists.

### 2.3 Proven: native falls through to `MainLoop` menu resources

`MainLoop`'s `LoadMenuResource` (`main.adc` 5456-5480) calls
`manager.loadPackage(PROJECT_ROOT_DIR + "/arcade/arcade")`, then
`/option/option`, `/gtmode/gtmode`, `/garage/garage`, `/gtauto/gtauto`.
The chain above is the first of those calls. It is reached only when
`GameSequence.getCurrentSequence() == MENU`; during the boot sequence it should
be BOOT. The fact that native is here proves the boot project did not take over
the sequence.

The package file is not loaded: `0x005F7D9C` builds `<name>.mpackage`, calls
`0x009F79A8`, and if the result is null calls `0x006CC5D0` with `r3=0`.
`0x006CC5D0` then performs the measured null writes/read:

```text
[null-write] guest wrote32 0x0 to 0x00000004 (NULL+0x4) by guest-fn=0x006CC5D0 -- DROPPED
[null-write] guest wrote32 0x0 to 0x00000008 (NULL+0x8) by guest-fn=0x006CC5D0 -- DROPPED
[null-read]  guest read32 from 0x00000008 (NULL+0x8) by guest-fn=0x006CC5D0
[null-write] guest wrote32 0x0 to 0x0000000C (NULL+0xC) by guest-fn=0x006CC5D0 -- DROPPED
[null-read]  guest read32 from 0x00000008 (NULL+0x8) by guest-fn=0x005F7D9C
```

This is the first post-boot symptom, not the root cause: the engine is already
in the menu-resource loader because the boot project never started.

### 2.4 The engine boundary: `MGOM.start("boot")`

`main.adc` line 280 resolves `MGOM.start` to the guest method
`0x006C54DC` (OPD `0x014CD330`, registered with name `start` at
`0x006C5014`). Its body is:

```text
0x006C54DC  MMenuGameObjectManager::start(this, name, len, ...)
  0x006C4C80  get singleton / manager object
  0x006C5478  start implementation
      0x005EBEBC  get the static menu context object
      0x005E6B94  return the object at this+0x48
      0x00568C94  start the update context for the named object
```

It has **no file open and no `.mproject` path construction**. The project
loader is a different function:

```text
0x005FA338  MProject load entry: append ".mproject" (0x1053A10) and call
0x005F0424  file/load helper -> 0x009D4F50 / 0x009D6BA4
```

`0x005FA338` is called by the cursor loader at `0x0056BADC` after building
`"%s/cursor/cursor"` (`0x104A600`, `CursorProject` at `0x104A5D8`);
native loads `cursor.mproject`/`cursor.adc` accordingly. The same loader is
**never called with `boot`**. Consequently K/KG, K/LH, K/IE, K/WD are never
opened.

In other words: `MGOM.start("boot")` starts a game object that must already be
registered/loaded. The missing step is that registration/load, not the ADCH
CALL and not a draw method. Native provably never calls the project loader with
`boot`; whether `start` found a pre-registered object or an empty slot is what
the probe in section 5 decides. In either case `execBoot` returns and
`MainLoop` starts the MENU sequence.

## 3. Why the fonts are missing but are not the first fix

The font keys are opened by `ksF3` workers before `menu/main` is parsed. Native
creates nine `ksF3` threads with the same entry (`0x014DF558`) and the same
worker names, but the logs show no font key opens and one worker blocks early:

```text
[LWM-BLOCK] tid=14 lwm=0xCFEFF1B8 owner=0 recur=3488609407 tmo=0us
```

That is a separate early async-file/preload issue. It matters for text UI
later, but `PresentsRoot` is an image UI project: its frames come from
`PresentsRootSCEA.gpb`'s embedded `scei`/`notice`/`pdi`/`epilepsy` textures.
No `.vec` font is needed to draw `presents_table_scea`. Fixing fonts first would
still leave the legal screen black because `boot.adc`/`PresentsRoot` are not
loaded.

Do not require `Prototypes.adc`; the v1.00 oracle reaches the Player Name UI
without it.

## 4. Assets, keys, and exact sizes

| Key | Compressed | Uncompressed (native override serves this) | Path |
|---|---:|---:|---|
| K/KG | 4,146 | 42,624 | `projects/gt6/boot/boot.mproject` |
| K/LH | 45,923 | 141,821 | `projects/gt6/boot/boot.adc` |
| K/IE | 7,434 | 14,592 | `projects/gt6/boot/gpb/BootProject.gpb` |
| K/WD | 69,530 | 1,760,256 | `projects/gt6/boot/US/PresentsRootSCEA.gpb` |
| K/WO | 3,620 | 12,464 | `products/gt6/script/MenuClassDefine.adc` |
| K/6I | 1,408 | 5,827 | `products/gt6/script/Prototypes.mwidget` |
| K/JH | 6,258 | 46,637 | `projects/gt6/cursor/cursor.mproject` |
| K/7E | 13,205 | 40,290 | `projects/gt6/cursor/cursor.adc` |
| K/W2 | 59,991 | 239,744 | `projects/gt6/cursor/gpb/CursorProject.gpb` |

Font keys (all uncompressed, loaded by the oracle before MenuClassDefine):

```text
K/4M  font/vec/IwataUD_M_latin.vec      69,040
K/5I  font/vec/IwataUD_M_JP.vec      1,923,568
K/V4  font/vec/IwataUD_B_latin.vec      60,368
K/HP  font/vec/IwataUD_B_JP.vec      1,883,168
K/TY  font/vec/IwataUD_E_latin.vec      59,696
K/G4  font/vec/IwataUD_L_latin.vec      69,536
K/CP  font/vec/GTfcItalic.vec            16,224
K/6L  font/vec/GTMeterNum.vec            10,720
K/9N  font/vec/GThk.vec                  47,904
K/D8  font/vec/FT_B.vec                  36,864
K/MR  font/vec/7seg.vec                  10,512
K/2F  font/logo/menu_imagefont.bin       29,847
```

`PresentsRootSCEA.gpb` is a `3bpg` container (header 0x20, 5 pairs at 0x20,
names at 0x70, first TXS3 at 0x180):

| Pair | Embedded texture | Dimensions | Format | TXS3 offset |
|---:|---|---:|---|---:|
| 0 | `/image/boot/common/JP/scei.dds` | 864x128 | DXT1 | 0x180 |
| 1 | `/image/boot/common/notice.dds` | 1440x720 | DXT1 | 0xDB00 |
| 2 | `/image/boot/common/pdi.dds` | 460x80 | DXT1 | 0x8C580 |
| 3 | `/image/boot/scea/JP/epilepsy.dds` | 1920x1080 | DXT1 | 0xB0600 |
| 4 | `/image/cursor/loading_circle.dds` | 24x24 | DXT1 | 0x1AD980 |

`tools/gt6_gpb_extract.py` parses the container and writes each payload as a
DDS. The 30 s oracle frame is an exact visual match to the epilepsy texture;
the 15 s GT6/©/ESRB frame is **not** any of these five and remains unmapped.

## 5. Smallest fix / ordered checklist

The smallest fix is **engine-side boot project registration/load**, before or
inside `MGOM.start("boot")`. Do not patch the ADCH VM, the font loader, or the
D3D12 backend for this first screen.

1. **Probe the boundary (no behavior change).** Apply
   `patches/gt6-boot-ui-probe.patch` (generated by
   `tools/gt6_boot_ui_probe.py`) to a scratch generated tree and run with
   `GT6_BOOTUI_TRACE=1`. The generator is idempotent: if the tree already
   contains the `[bootui]` probes it reports "already present" instead of
   inserting duplicates. It logs:
   - `[bootui] MGOM.start this=... argstr=... len=...`
   - `[bootui] MGOM.start_impl ... s='...'`
   - `[bootui] project_load this=... base=... name=... sbase='...' sname='...'`
   - `[bootui] package_load ... s='...'`
   - `[bootui] file_open out=... path=... s='...'`
2. **Confirm the lookup.** Expected native line is
   `[bootui] MGOM.start ... s='boot'`. If `start_impl` runs but
   `project_load` is absent, the object manager has no registered `boot`
   object. If `project_load` runs, read `sname`/`sbase`: it must be
   `projects/gt6/boot/boot` (the loader appends `.mproject`).
3. **Fix the registration, not the CALL.** Make the boot project load happen
   before `MGOM.start("boot")`, mirroring the cursor loader at `0x0056BADC`:
   construct `PROJECT_ROOT_DIR + "/boot/boot"` and call the project loader
   `0x005FA338` (or the engine method that does this in the real path). Then
   `boot.adc` must be parsed and its `display_sequence_gt6` frame must run.
4. **Do not synthesize files.** The disc supplies K/KG, K/LH, K/IE, K/WD. The
   generic PFS plaintext override can serve them from `work/gt6_vol` once the
   loader asks for them; verify the exact override log lines below. If a GPB
   goes through the non-`HFileReader` `FileStream` path (as W2 does), document
   that as a separate PFS source-fetch issue; do not alias `Prototypes.adc`.
5. **Only after the boot assets open**, revisit W2/fonts if they still block
   later UI. The W2 zero-data read and the `ksF3` font preload are real but
   later than the presents load.
6. **Only after a textured PresentsRoot draw exists**, fix the D3D12 no-VP
   generic texture sampling if that draw is legacy. There is no textured UI
   draw to sample yet.

## 6. Expected native log lines and verification plan

**No build or run was performed for this report.** The lines below are the
required observations for the next run, not measured output. The current
generated tree may already contain the probe insertions (the generator detects
them); they are gated by `GT6_BOOTUI_TRACE=1`.

### 6.1 Success lines for the boot/presents load

With the boot project loader fixed and the plaintext PFS override active, the
first lines should be (sizes are the extracted `work/gt6_vol` sizes because the
override serves plaintext, not the compressed cache length):

```text
[GT6] pfs override: serving plaintext projects/gt6/boot/boot.mproject (42624 bytes, reader=...)
[GT6] pfs override: serving plaintext projects/gt6/boot/boot.adc (141821 bytes, reader=...)
[GT6] pfs override: serving plaintext projects/gt6/boot/gpb/BootProject.gpb (14592 bytes, reader=...)
[GT6] pfs override: serving plaintext projects/gt6/boot/US/PresentsRootSCEA.gpb (1760256 bytes, reader=...)
```

The equivalent `[pfscache] open .../PDIPFS_bdmark/K/KG`, `K/LH`, `K/IE`, `K/WD`
lines prove the engine issued the opens even if the override takes over. The
font preload should show the `K/4M`...`K/2F` opens separately:

```text
[pfscache] open .../PDIPFS_bdmark/K/4M ...
[pfscache] open .../PDIPFS_bdmark/K/5I ...
...
[pfscache] open .../PDIPFS_bdmark/K/2F ...
```

### 6.2 Probe lines

```text
[bootui] MGOM.start this=... argstr=... len=... arg=... s='boot'
[bootui] MGOM.start_impl ... s='boot'
[bootui] project_load this=... base=... name=... sbase='.../boot' sname='boot'
[bootui] file_open out=... path=... s='.../boot/boot.mproject'
```

If `MGOM.start s='boot'` appears but no `project_load`, the object manager is
missing the boot object. If `package_load s='.../arcade/arcade'` appears before
any `project_load`, the engine is still in `MainLoop`/MENU and the boot sequence
has been skipped.

### 6.3 Frame verification

1. Run 240-300 s with the probe and `GT6_BOOTUI_TRACE=1`.
2. Require all four boot assets and the font preload (or an explicit documented
   reason fonts use a separate path) before judging pixels.
3. A successful first legal frame is the PresentsRoot sequence:
   - `scei` (Sony Computer Entertainment presents) for 2 s,
   - `notice` (legal/trademark/PDI notice) for 2 s,
   - `epilepsy` (WARNING) for 4 s.
   The 30 s oracle frame must match `epilepsy.dds` (already verified).
4. Only then check for textured UI draws (`[DRAWDIAG]`/`[IMMEDIATE]`/`[LEGACYVTX]`).
   A legal frame must not be accepted from the 15 s GT6/©/ESRB capture; that
   frame is still unmapped.

## 7. Evidence index

| Evidence | Location |
|---|---|
| Oracle PDIPFS order / creation times | `tools/RPCS3/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/`; `work/rpcs3_oracle/rpcs3_input.log` 0:00:26.9-27.4 |
| `presents_sequence_common`, `presents_table_scea`, `display_sequence_gt6` | `work/gt6_vol/projects/gt6/boot/boot.adc`; `tools/adch_disasm.py` |
| `main.adc` `execBoot`/`initMenuSystem`/`MainLoop` | `work/gt6_vol/scripts/gt6/main.adc`; disassembly in `work/agent_ui/main_disasm.txt` |
| Native MenuClassDefine load (proves `execBoot`) | `work/flush_long.err:1241`; `work/size_run.err:257989` |
| Native cursor assets, no boot/font assets | `work/size_run.err:263202/277371`; grep for K/KG, K/LH, K/IE, K/WD returns nothing |
| VM alive / builtin dispatch | `work/size_run.err:289194`, `289205` |
| Package null-parse chain | `work/size_run.err:289154` onward; `[null-write] ... 0x006CC5D0`; `0x005F7D9C` |
| `MMenuGameObjectManager::start` does not open a project | guest `0x006C54DC` / `0x006C5478` disassembly; OPD `0x014CD330`; registration `0x006C5014` |
| Project loader `0x005FA338` + `.mproject` | guest `0x005FA338` / `0x005F0424`; string `0x1053A10` |
| Cursor project loader | guest `0x0056BADC`; `%s/cursor/cursor` `0x104A600` |
| GPB textures | `work/gt6_vol/projects/gt6/boot/US/PresentsRootSCEA.gpb`; `tools/gt6_gpb_extract.py` |
| Probe generator/patch | `tools/gt6_boot_ui_probe.py`; `patches/gt6-boot-ui-probe.patch` |
