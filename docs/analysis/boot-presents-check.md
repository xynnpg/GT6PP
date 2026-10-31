# Boot/presents script path — independent check

**Date:** 2026-10-31
**Checker scope:** read-only. No source edit, no relift, no build, and no
`gt6.exe` run by this check. Evidence is the extracted `GT.VOL` tree, the
ADCH disassembly, the native logs, the oracle load-order log, the generated
tree, and the fixer's current trace artifacts. `third_party/PDTools` and
`GTAdhocToolchain` were not read or used.
**Inputs:** `work/gt6_vol/projects/gt6/boot/boot.adc`,
`work/gt6_vol/scripts/gt6/main.adc`,
`work/gt6_vol/projects/gt6/boot/US/PresentsRootSCEA.gpb`,
`work/agent_ui/kloads_input.tsv`, `work/size_run.err`,
`work/flush_long.err`, `work/probe_run.err`, `work/gt6.log`,
`work/boot_presents/*`, `work/agent_ui/*`, `docs/analysis/first-visible-ui-check.md`,
`docs/analysis/w2-size-check.md`, and `docs/analysis/d3d12-draw-readiness.md`.

"PASS" below means supported by the cited evidence. "FAIL" means not reached,
not proven, or not safe to claim; it does not by itself assert that the code is
wrong. A shortcut that reaches the presents calls without the script's own
boot-state initialization is a **mask**, not a fix.

## 0. Verdict

| # | Claim | Verdict | Finding |
|---:|---|---|---|
| 1 | `main.adc` is the VM entry that starts the boot project | **PASS** | Its TOP frame (`scripts/gt6/Application.ad`, 5,564 instructions) ends by calling `bootstrap_phase1_module.execBoot` at code `0xD122F`; `execBoot` calls `initModules`, `initApp`, `initArgs`, `initMenuSystem`, then `main.MGOM.start("boot")` at code `0x1CC86`–`0x1CCA9` (call at `0x1CCA9`). |
| 2 | `boot.adc` contains `display_sequence_gt6` and `presents_sequence_common` | **PASS** | `display_sequence_gt6` is at `0x1875F` and its first call is `presents_sequence_common` (`0x18798`). `presents_sequence_common` is at `0x16012`; it selects `PresentsRootSCEA` for `scea` and iterates `presents_table_scea`. |
| 3 | `main.adc` itself contains those two functions | **FAIL (negative)** | The strings/functions exist only in `boot.adc`. `main.adc` is the entry; `boot.adc` is the sequence container. The context phrasing "`main.adc`/`boot.adc` contains" should not be read as "both contain". |
| 4 | The native port reaches the boot project or presents sequence | **FAIL** | Native logs contain no `K/KG`, `K/LH`, `K/IE`, or `K/WD` open, no `boot.adc`/`boot.mproject`/`BootProject.gpb`/`PresentsRootSCEA.gpb` path, and no `MGOM.start("boot")` instrumentation. The current script path stops around the cursor `K/W2` data read. |
| 5 | The exact missing boot/font opens are known | **PASS** | Native logs open only `K/4D`, `K/E9`, `K/PD`, `K/WO`, `K/6I`, `K/JH`, `K/7E`, `K/W2` (plus `K/IK` in the probe/flush logs). They never open `K/LH`, `K/KG`, `K/IE`, `K/WD`, `K/R2`, `K/4M`, `K/5I`, `K/V4`, `K/HP`, `K/TY`, `K/G4`, `K/CP`, `K/6L`, `K/9N`, `K/D8`, `K/MR`, `K/2F`, or `K/RP`. |
| 6 | The fixer's trace/patch reaches the presents sequence | **FAIL / not yet** | No boot/presents source patch exists as of this check. The recent `work/boot_presents/*` and `work/agent_ui/*` files are disassembly/OPD-reference trace tools; the source/generated tree is still the W2 size-fix tree. There is no `[pfsbind]` and no presents hook. |
| 7 | A direct call to `display_sequence_gt6`/`presents_sequence_common` would be a valid shortcut | **FAIL (design)** | It would skip `boot_sequence_gt6` -> `boot_sequence_common` (which initializes `boot_state`, save/font/UI state) and skip `start_project`. That masks the VM/loader bug and can run presents with uninitialized state. The safe hook is `MGOM.start("boot")` / the boot.adc `boot(context)` entry, not the presents function. |
| 8 | `PresentsRootSCEA.gpb` asset mapping is verified | **PASS** | Five embedded textures, names and dimensions independently parsed; `K/WD` cache is exactly the compressed `GT.VOL` slice at `0xDBD800` (69,530 bytes, SHA-256 `43577C...8E65`). The US and JP extracted GPBs are byte-identical. |
| 9 | The 30 s oracle frame is the `epilepsy.dds` frame | **PASS** | `frame_030s.png` is an exact visual match to the embedded 1920x1080 DXT1 `scea/JP/epilepsy.dds`; same WARNING text, line breaks and PS3 wording. |
| 10 | The 15 s oracle frame is mapped to `PresentsRootSCEA.gpb` | **FAIL (unmapped)** | The 15 s frame occurs **before** `K/WD` is loaded (oracle `K/WD` at `0:00:27.445820`). It cannot be PresentsRoot. No extracted GT.VOL GPB texture matches its full GT6 wordmark / © 2013 / ESRB composition. |
| 11 | First mapped screen draw type is known | **PASS (class only)** | `PresentsRoot.changeImage` builds `/image/boot/<path>.dds` and assigns it to a 2D image plate. It is 2D textured image UI, not a 3D or immediate `DATA2F` block. The oracle log has no guest primitive stream, so the exact primitive count, VP/FP use and blend state are not proven. |
| 12 | GPB/texture/font/no-VP sampling is ready after the script path | **FAIL (downstream, conditional)** | The runtime has no boot/font GPB load yet. GPB formats `0xA6` (DXT1) and `0xA5` (32bpp) are accepted by the backend after the `&0x9F` mask, but a generic non-B8 texture bound on a **no-VP legacy draw** is not sampled; the legacy path only samples the B8 debug-font atlas. The PresentsRoot draw must use VP/FP, or a generic legacy textured PSO must be added, before the first image can appear. |
| 13 | No fabricated asset/byte is used by the current trace | **PASS (current state)** | The script override serves the real 857,518-byte extracted `main.adc`; the generic PFS override serves only extracted files and logs missing paths. The W2 source-bind writes guest state only, not cache bytes; that does not make it safe (see `w2-size-check.md` §4.3). **But** `tools/gt6_gpb_extract.py` hardcodes DXT1 and mis-decodes `pdi.dds` (`0xA5`) and the image-font atlas, so its PNGs must not be used as asset-mapping evidence without fixing the tool. |

**Bottom line:** the script evidence is solid and the PresentsRoot mapping is
real, but the native/fixer path has **not reached** the boot project or the
presents sequence. The current W2 work is a separate, earlier blocker; it is not
a presents fix. The only safe next step is to instrument the real VM path and
prove `MGOM.start("boot")` is invoked and the script enters the boot.adc
`boot(context)` entry; that entry must initialize the boot state and call the
presents sequence. Do not jump to
`display_sequence_gt6`, do not inject boot assets, and do not claim the 15 s
frame is PresentsRoot.

## 1. Expected VM entry and call chain

### 1.1 `main.adc` — the entry

`work/gt6_vol/scripts/gt6/main.adc` is `ADCH012`, 857,518 bytes, 6,412 symbols,
TOP at code `0x1BD15`:

```text
TOP source='scripts/gt6/Application.ad' stack=12 local=4 static=1590 ins=5564
...
0x1C037  FUNCTION_DEFINE initModules
0x1C19F  FUNCTION_DEFINE initApp
0x1CBAC  FUNCTION_DEFINE execBoot
...
0xD1226  TRY_CATCH 5479
0xD122F  VARIABLE_EVAL bootstrap_phase1_module, execBoot, ... idx=1583
0xD1241  CALL 0
```

`execBoot` is only 25 instructions and is the transition to the boot project:

```text
execBoot:
  initModules()
  initApp()
  pdistd.SetFileSystemOptionInt64("/", "PreCopyHddFreeSizeLimit", INSTALL_MINIMUM_HDD_SPACE)
  initArgs()
  initMenuSystem()
  main.MGOM.start("boot")      ; string 0x1CCA2, call 0x1CCA9
```

`initMenuSystem` is where the native log's UI assets come from:

```text
initMenuSystem:
  ...
  REQUIRE /script/MenuClassDefine                 ; code 0x1C80C
  ...
  LangUtil.load()                                 ; code 0x1CA40
  main.MGOM.initialize()                          ; code 0x1CA61
  ...
```

The oracle's pre-boot order is therefore not the presents sequence yet: it is
`MenuClassDefine` / `Prototypes` / `rtext` / cursor / `W2`, then the boot
project. That matches the native sequence up to `W2` and explains why no boot
asset appears in the native logs.

### 1.2 `boot.adc` — the sequence

`work/gt6_vol/projects/gt6/boot/boot.adc` is `ADCH012`, 141,821 bytes, 1,682
symbols. The relevant functions are:

| Function | Code offset | Key body |
|---|---:|---|
| `boot(context)` | ~`0x1CEC0` | `boot_sequence(context, pc)`; start `display_sequence` thread; `display_sequence(...)`; thread join; `start_project(context)` |
| `boot_sequence(context, pc)` | `0x1C60D` | dispatch on `GetVersionBranch()`; for `gt6` calls `boot_sequence_gt6(context)`; then `pc.finish()` |
| `boot_sequence_gt6(context)` | `0x186E5` | calls `boot_sequence_common(context, "gt6")` |
| `display_sequence(context, pc, thread)` | `0x1C8AE` | dispatch on `GetVersionBranch()`; for `gt6` calls `display_sequence_gt6(context, pc, thread)` at `0x1C9F8` |
| `display_sequence_gt6(context, pc, initialize_thread)` | `0x1875F` | **first call** `presents_sequence_common(context)` at `0x18798`; then boot-state checks, language select, `AdjustScreenRoot`, save/voucher work, `MovieRoot` |
| `presents_sequence_common(context)` | `0x16012` | `GetGameRegionCode()`; for `scea` selects `PresentsRootSCEA` and `presents_table_scea`; `PresentsRoot.open(context)`; loop `changeImage(p.path)`, `Thread.Sleep(p.sec)` |
| `presents_table_scea` | `0x15E9F` | `common/JP/scei` 2.0 s; `common/notice` 2.0 s; `scea/JP/epilepsy` 4.0 s |

The `scea` selection is explicit:

```text
0x16203  STRING_CONST PresentsRootSCEA
0x1620A  VARIABLE_EVAL PresentsRoot
0x1621B  ATTRIBUTE_PUSH resource_name
0x1622B  VARIABLE_EVAL presents_table_scea
```

`PresentsRoot.changeImage` then builds the image path:

```text
0x1D7D9  STRING_CONST /image/boot/
0x1D7E0  VARIABLE_EVAL path
0x1D7EE  STRING_CONST .dds
0x1D7F5  STRING_PUSH 3
0x1D7FE  VARIABLE_EVAL front
0x1D818  ATTRIBUTE_PUSH image_path
```

So the exact legal sequence is a set of 2D image plates, not a 3D scene and not
the native `DATA2F` black cover.

### 1.3 Correct entry vs. a shortcut

The expected script-side chain is:

```text
main.adc TOP
  -> bootstrap_phase1_module.execBoot
  -> main.MGOM.start("boot")
  -> boot.adc boot(context)                    [project entry; verify the link]
  -> boot_sequence -> boot_sequence_gt6
  -> boot_sequence_common(context, "gt6")      [initializes boot_state]
  -> display_sequence -> display_sequence_gt6
  -> presents_sequence_common
  -> PresentsRoot.open / changeImage
  -> ...
  -> start_project
```

`display_sequence_gt6` is **not** the project entry. It reads `boot_state`
(`init_save_data_done`, `sequence_done`, `is_new_game`, `resume_gp`, etc.) that
`boot_sequence_common` initializes. Calling it directly would skip the boot
project load, the font/UI/save initialization, and `start_project`. That is a
diagnostic-only experiment at best, and it would make a later failure
unattributable.

## 2. Native logs — what is actually opened

### 2.1 The loaded set

`work/flush_long.err`, `work/size_run.err`, and `work/probe_run.err` show the
same pre-boot set (the probe run additionally has the `K/IK` sound control):

```text
K/4D, K/E9, K/PD, K/WO, K/6I, K/JH, K/7E, K/W2
```

`K/PD` is `scripts/gt6/main.adc`; `K/WO` is `MenuClassDefine.adc`; `K/6I` is
`Prototypes.mwidget`; `K/JH` is `cursor.mproject`; `K/7E` is `cursor.adc`;
`K/W2` is `CursorProject.gpb`.

### 2.2 The missing first-screen set

The oracle load order (`work/agent_ui/kloads_input.tsv`) has, before/around the
boot project:

```text
0:00:26.909  K/R2   font/vec/fontset_JP.txt
0:00:26.909  K/4M   font/vec/IwataUD_M_latin.vec
0:00:26.915  K/5I   font/vec/IwataUD_M_JP.vec
0:00:26.920  K/V4   font/vec/IwataUD_B_latin.vec
0:00:26.921  K/HP   font/vec/IwataUD_B_JP.vec
0:00:26.925  K/TY   font/vec/IwataUD_E_latin.vec
0:00:26.926  K/G4   font/vec/IwataUD_L_latin.vec
0:00:26.927  K/CP   font/vec/GTfcItalic.vec
0:00:26.928  K/6L   font/vec/GTMeterNum.vec
0:00:26.928  K/9N   font/vec/GThk.vec
0:00:26.929  K/D8   font/vec/FT_B.vec
0:00:26.929  K/MR   font/vec/7seg.vec
0:00:26.930  K/2F   font/logo/menu_imagefont.bin
0:00:27.187  K/RP   rtext/common/US.rt2
0:00:27.240  K/KG   projects/gt6/boot/boot.mproject
0:00:27.259  K/LH   projects/gt6/boot/boot.adc
0:00:27.328  K/IE   projects/gt6/boot/gpb/BootProject.gpb
0:00:27.445  K/WD   projects/gt6/boot/US/PresentsRootSCEA.gpb
```

None of these keys appears in the native logs. A search for
`K/(LH|KG|IE|WD|4M|5I|V4|HP|TY|G4|CP|6L|9N|D8|MR|2F|R2|RP)`,
`font/vec`, `font/logo`, `boot.adc`, `boot.mproject`, `BootProject`, or
`PresentsRoot` across `flush_long.err`, `size_run.err`, `probe_run.err`,
`flush_run.err`, and `gt6.log` returns no match.

This is the exact gap:

- **Boot project:** `K/KG` (mproject), `K/LH` (boot.adc), `K/IE`
  (BootProject.gpb), `K/WD` (PresentsRootSCEA.gpb) are never requested.
- **Fonts/text:** the fontset/vector/image-font keys and `rtext/common` are
  never requested.
- **Consequence:** no boot project, no PresentsRoot GPB, no font atlas, and no
  PresentsRoot draw can exist in the current native run.

### 2.3 The current blocker is earlier

`size_run.err` shows the native `W2` open at `289083`, the PFS cache attach at
`289106`, and the read dispatching to the host device at `289120`:

```text
289083 [fileopen] 9F8E40 ... file=0xCFEFE398
289086 [fileopen] 9F4130 ... vt=0x01488218 dev=0x7005C000 size=0x0
289100 [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
289106 [pfscache] 0xA42108 attach size=0xEA57 id=0xD48800 ...
289119 [fileread] 9F4AA0 stream=0xCFEFE338 req=0xCFEFE2B8 file=0xCFEFE398
289120 [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE338 active=0x00 old=0
```

The `.fdupi` at `work/gt6_hdd0/.../K/W2.fdupi` is 59,991 zero bytes (SHA-256
`7B5C0196F56232A470EA96EA02111FECE4DDC209761ECFD4BE526DF98A478362`); the
`.fdupm` header is `stored_size=0xEA57`, blocks zero. The raw bytes do exist at
`GT.VOL` `0xD48800` (SHA-256
`2B6153BACD5E833E9E3BB5B5089552AE3BF973A67FEBA599EC6FCD21DB709008`), but the
read never reaches the PFS cache. This is the W2 blocker documented in
`w2-size-check.md`; it is **not** a boot/presents reach.

The native `initMenuSystem` sequence (`MenuClassDefine`, `Prototypes.mwidget`,
`cursor.mproject`, `cursor.adc`, `W2`) is consistent with the oracle's pre-boot
UI setup. The boot project and fonts come after that in the oracle, and the
native path has not reached them.

## 3. Fixer trace/patch review

### 3.1 What exists

As of this check, the fixer has produced analysis artifacts, not a boot/presents
patch:

- `work/boot_presents/boot_adc.txt` and `main_adc.txt` — full ADCH
  disassembly. The only loader workarounds in the source are the `main.adc`
  script override and the generic extracted-file override in
  `gt6/src/stubs.cpp`; both serve real extracted bytes, but they do not make
  the VM request the boot/font keys.
- `work/boot_presents/menuclassdefine_adc.txt`, `cursor_adc.txt`.
- `work/boot_presents/ghidra_decomp.c` — decompilation of the script-builtin
  registration path (`builtin_14C43D8` / `func_5F7D9C`).
- `work/boot_presents/opdrefs.py`, `findrefs*.py`, `dump_table.py`,
  `names*.py`, `parse_reg.py`, `reg_disasm.txt` — OPD/table tracing.
- `work/agent_ui/*` — GPB strings, image-font extraction attempts, RPCS3 RSX
  trace setup, and ELF string/vtable scans.

No `display_sequence_gt6`/`PresentsRoot` call, no boot asset injection, and no
font override exists in `gt6/src` or `gt6/generated`. `git status` shows only
docs/tools/patches changes; `gt6/src` is unchanged. The generated
`ppu_recomp_022.cpp` still contains the old `[filesize]` block at lines
137371–137391, not a `[pfsbind]` boot hook. The current `gt6/build/gt6.exe`
(17:26) is the size-fix build, not a boot/presents build.

### 3.2 Does the trace reach presents?

**No, not yet.** The trace is correctly identifying the boot script functions
and the script-builtin/OPD registration, but it has not produced:
- a call from `MGOM.start("boot")` to the boot.adc `boot(context)` entry;
- a log of `boot(context)`, `boot_sequence_common`, or
  `display_sequence_gt6`;
- a boot asset open (`K/KG`, `K/LH`, `K/IE`, `K/WD`);
- a font/rtext open;
- a PresentsRoot draw or texture bind.

The trace is therefore **valid analysis, not a fix**. It must not be credited
as "reached presents" until the native log shows the real VM transition.

### 3.3 The shortcut to reject

A patch that calls `display_sequence_gt6` or `presents_sequence_common` directly
would:
- skip `MGOM.start("boot")` and the boot project load;
- skip `boot_sequence_common` and leave `boot_state` uninitialized;
- skip the font/rtext/UI initialization that precedes the boot project;
- skip `start_project` after the sequence;
- make a later crash or black frame look like a GPB/draw bug instead of a VM
  bug.

If the fixer wants a diagnostic, hook/log `MGOM.start("boot")` and the
boot.adc `boot(context)` entry and let the guest call them. Do not add a native call to the
presents functions. The same rule applies to a forced `Prototypes.adc` alias:
the oracle proves `Prototypes.adc` is not required for v1.00, so creating or
renaming one to advance the VM would mask the loadPrototype/MPRJ loader bug.

### 3.4 Current W2 patch is not a presents patch

The `gt6-pfs-source-bind.patch` / `gt6_filedevice_flush_patch.py` change is a
W2 device/size experiment. It:
- does not touch `boot.adc`, `boot.mproject`, `BootProject.gpb`,
  `PresentsRootSCEA.gpb`, or any font key;
- does not add a VM entry call;
- is not built into the current generated tree;
- is independently reviewed as unproven/type-punning in
  `docs/analysis/w2-size-check.md` §4.3.

It can be a separate W2 investigation, but it cannot be used as evidence that
the boot/presents path works, and it must not be merged as the first-screen fix.

### 3.5 Asset-extraction defects (do not overclaim)

`tools/gt6_gpb_extract.py` assumes every embedded TXS3 texture is DXT1
(`parse_gpb` sets `dxt_format = "DXT1"` and computes a DXT1 payload length).
That is false for at least two PresentsRoot-adjacent assets:

- **`pdi.dds`** is `460x80`, format `0xA5` (32bpp), data size field
  `0x24003` = 147,459 bytes. The extractor reports DXT1 and a payload of only
  `0x47E0` (18,400 bytes). Its `image_boot_common_pdi.png` is garbage. The
  first-visible check's `0xA5`/147,459 mapping is the correct one.
- **`font/logo/menu_imagefont.bin`** has a 448x512 embedded texture at
  `0x100`; the payload from `0x180` is 229,376 bytes (8 bits/pixel; 131
  trailing bytes remain in the file), not a 114,688-byte DXT1 payload. The
  extractor's 114,688-byte DXT1 output is the
  striped `menu_imagefont0.png`; it is not a valid decode and cannot support a
  15 s mapping claim.

The PFS/GPB *names and sizes* remain valid; only the pixel decode is wrong.
Re-extract with a format-aware extractor before using these PNGs as visual
evidence. Do not use the garbled `pdi` or image-font PNGs to argue that a frame
is or is not mapped.

## 4. PresentsRoot asset mapping and the 15 s frame

### 4.1 `PresentsRootSCEA.gpb`

Independent parse of
`work/gt6_vol/projects/gt6/boot/US/PresentsRootSCEA.gpb`
(1,760,256 bytes, `3bpg`, 5 pairs, names at `0x70`, data at `0x180`):

| Pair | Embedded path | Dimensions | Format | Data offset | Size field |
|---:|---|---:|---|---:|---:|
| 0 | `/image/boot/common/JP/scei.dds` | 864x128 | `0xA6` DXT1 | `0x180` | `0xD903` |
| 1 | `/image/boot/common/notice.dds` | 1440x720 | `0xA6` DXT1 | `0xDB00` | `0x7EA03` |
| 2 | `/image/boot/common/pdi.dds` | 460x80 | **`0xA5` 32bpp** | `0x8C580` | `0x24003` |
| 3 | `/image/boot/scea/JP/epilepsy.dds` | 1920x1080 | `0xA6` DXT1 | `0xB0600` | `0xFD303` |
| 4 | `/image/cursor/loading_circle.dds` | 24x24 | `0xA6` DXT1 | `0x1AD980` | `0x223` |

The US and JP extracted GPBs are byte-identical
(SHA-256 `301B687A0CEA78FB8E4A8BC0399BC67D8382DE4BBF3465D6751EBE11132418E5`),
so the JP/US row ambiguity in the oracle keymap is moot. The oracle `K/WD`
cache is exactly the compressed `GT.VOL` slice at `0xDBD800` (69,530 bytes,
SHA-256 `43577C4EE5BA2DF99B2E1B6839E1D73197DE0372AC8B63B27D38CB693D6A8E65`).

The 30 s frame (`work/rpcs3_oracle/frames_input/frame_030s.png`) is an exact
visual match to the embedded 1920x1080 `epilepsy.dds`: same WARNING text,
line breaks, and "YOUR PS3™ SYSTEM FOR MORE DETAILS" wording. The 30 s
PDIPFS-backed legal screen is therefore **PASS**.

### 4.2 The 15 s frame is not PresentsRoot

The 15 s frame
(`work/rpcs3_oracle/frames_input/frame_015s.png`) shows the GT6 wordmark,
"© 2013 Sony Computer Entertainment Inc.", and the ESRB "EVERYONE" card. It is
still behind RPCS3's "Building SPU Cache..." overlay; the other capture
`work/rpcs3_oracle/shots/printwindow_1_1643430.png` has the shader-precompile
overlay. Two independent facts make it impossible to map to
`PresentsRootSCEA.gpb`:

1. The oracle opens `K/WD` at `0:00:27.445820`; the 15 s frame is 12 s earlier.
2. The PresentsRoot `scea` table contains only `scei`, `notice`, and
   `epilepsy`; none of their decoded textures is the GT6-wordmark/ESRB
   composition. `notice.dds` is the long legal text, not this card.

No extracted GT.VOL `.gpb` texture identified by the earlier all-GPB scan or by
this check matches the full 15 s composition. It is likely an earlier EBOOT/embedded/movie legal card, or a
composition of a separate logo/rating asset, not `PresentsRootSCEA.gpb`. The
15 s frame remains **unmapped**; do not present it as verified PresentsRoot
output. The first *mapped* PDIPFS-backed screen is the 30 s epilepsy frame.

## 5. First visible screen draw type and downstream requirements

### 5.1 Draw class

`PresentsRoot.changeImage` constructs `/image/boot/<path>.dds` and assigns it
to the `Plate0`/`Plate1` image plates. The GPB contains only images (plus the
loading ring); there is no text or 3D mesh in the PresentsRoot GPB. The first
mapped legal screen is therefore a **2D textured image UI** draw class.

The oracle log does not contain the guest RSX primitive stream, so the exact
primitive (quad/strip), vertex program, fragment program, blend state, and
texture unit are **not proven**. Do not claim a specific `DRAW_ARRAYS` count or
"no VP" from the current evidence. The 15 s card's draw type is also unknown
because the asset itself is unmapped.

### 5.2 Texture path

The runtime texture uploader reads guest RSX memory, not
`work/gt6_vol/*.dds`; extracted DDS files are oracle mapping evidence only. The
GPB must be loaded into guest memory by the boot project, and the GPB parser /
menu renderer must upload the embedded TXS3 texture.

`d3d12_bind_texture` strips the `LN(0x20)`/`UN(0x40)` flags with
`format & 0x9F` (`rsx_d3d12_backend.c:8389`). That maps:

- `0xA6` -> `0x86` DXT1 -> `DXGI_FORMAT_BC1_UNORM`;
- `0xA5` -> `0x85` A8R8G8B8 -> `DXGI_FORMAT_R8G8B8A8_UNORM`.

So the PresentsRoot formats are in the backend whitelist. The missing piece is
the actual guest texture bind/upload, not a format rejection.

### 5.3 The no-VP caveat is real

The backend's generic texture sampling is VP/FP-only. The legacy (`is_vp == 0`)
path still samples only the B8 debug-font atlas; a generic non-B8 texture bound
on a no-VP draw is recorded but not sampled
(`rsx_d3d12_backend.c:7798-7804`, `8458-8470`;
`docs/analysis/d3d12-draw-readiness.md` §“Remaining blockers” item 5). If the
PresentsRoot menu draw is a legacy draw, it will be submitted but invisible
until either:
- the guest VP/FP path is used and compiles, or
- a generic legacy textured PSO is added.

Do not assume the existing `DATA2F` black cover path covers PresentsRoot. The
black cover is a 10-vertex immediate strip with constant black attr3 and no
texture/UV (`d3d12-draw-readiness.md` §“GT6's actual first block”); it is not a
GPB image draw.

### 5.4 Fonts

The oracle loads the fontset, 11 vector fonts, the image font, and
`rtext/common` before the boot project. The native path opens none of them.
`initMenuSystem` calls `LangUtil.load` (main.adc `0x1CA40`) and
`MGOM.initialize` (`0x1CA61`); those calls, and the font manager's PFS opens,
are the right places to instrument.

The PresentsRoot legal images themselves are image plates and may not sample a
vector font, but:
- `BootProjectComponent` uses `TextFace` and the `IwataSet_3` font;
- the display-area/player-name UI needs the font system;
- the 15 s card may use the `K/2F` image font (not proven);
- the oracle loads the fonts before the boot project regardless.

Therefore font loading is a required part of the boot project/UI path even if
the three PresentsRoot images do not need it. Do not fabricate a font or skip
`K/R2`/`rtext` merely because the legal images look text-free.

## 6. Safest next step

1. **Do not merge a presents shortcut.** No direct `display_sequence_gt6` /
   `presents_sequence_common` call, no forced `Prototypes.adc`, no injected
   PresentsRoot texture. Those mask the script/VM/loader bug.
2. **Instrument the real VM transition.** Add read-only logs at:
   - `main.adc` `execBoot` `0x1CC86`–`0x1CCA9` (`MGOM.start("boot")`, call `0x1CCA9`);
   - `boot.adc` `boot` / `boot_sequence_gt6` / `boot_sequence_common`;
   - `LangUtil.load` (`0x1CA40`) and the font/rtext PFS opens;
   - the boot project open (`K/KG`, `K/LH`, `K/IE`, `K/WD`).
   Run 240–300 s and require the native log to show `MGOM.start("boot")`,
   the boot.adc `boot(context)` entry, and the boot asset/font keys. The existing generic PFS
   override may serve extracted files **only as a diagnostic**; it must not be
   counted as a fix.
3. **Keep the W2 work separate.** The native path is currently blocked on the
   W2 host/PFS read (zero `.fdupi`). Fix the mount/device selection, not the
   PresentsRoot path, and do not claim W2 progress is presents progress. The
   current source-bind is unbuilt/type-punning; see `w2-size-check.md` §4.3.
4. **Fix the GPB extractor before using visual evidence.** Add `0xA5` 32bpp
   and the image-font format handling, re-extract `pdi.dds` and
   `menu_imagefont.bin`, and re-check the 15 s frame. Until then, keep the 15 s
   frame unmapped.
5. **Verification gate for the first mapped screen:**
   - native log opens `K/KG`, `K/LH`, `K/IE`, `K/WD`, `K/R2`, the vector font
     keys, and `K/RP`;
   - native log shows the boot project entry and `PresentsRoot.open`;
   - a `[DRAWDIAG]`/`[TEXFMT]` line shows a PresentsRoot texture bind with
     `0xA6`/`0xA5`;
   - the draw is either VP/FP or uses a new generic legacy textured PSO;
   - the frame matches `epilepsy.dds` at the expected sequence point.
   Do not accept a black `DATA2F` cover, a debug-font atlas, or a
   `0xA40FBC`/`.fdupi` state as evidence of presents.
6. **Backend work waits for a textured draw.** The no-VP generic-texture gap is
   real but downstream. Do not add a fake texture or a preset image to make the
   window non-black; that would hide the missing GPB/font path.

## 7. Evidence index

| Evidence | Location / value |
|---|---|
| `main.adc` TOP and `execBoot` | `work/gt6_vol/scripts/gt6/main.adc`; `main.adc` code `0x1BD15`, `execBoot` `0x1CBD3`, `MGOM.start("boot")` call `0x1CCA9`, top-level call `0xD122F` |
| `boot.adc` sequence functions | `work/gt6_vol/projects/gt6/boot/boot.adc`; `display_sequence_gt6` `0x1875F`, `presents_sequence_common` `0x16012`, `presents_table_scea` `0x15E9F`, `display_sequence` `0x1C8AE`, `boot` ~`0x1CEC0` |
| `main.adc` SHA-256 | `5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746` |
| `boot.adc` SHA-256 | `7149EFCAD057B80486EA1650CF04F98EB6FE4C6F44AF2D74F15B5848A88F10AE` |
| `boot.mproject` / `BootProject.gpb` hashes | `15D0DCFCE78E44E4DF3ACB85FC2687D2AC99E6B206E7358A007B9D0C1DABE599` / `D4487DD29B12CC1F53754FF7B2E51905D71C1A4F516F7C403AAB5E5A69DCFAF8` |
| `PresentsRootSCEA.gpb` hash | `301B687A0CEA78FB8E4A8BC0399BC67D8382DE4BBF3465D6751EBE11132418E5` (US and JP identical) |
| `K/WD` cache / GT.VOL slice | 69,530 bytes at `GT.VOL` `0xDBD800`, SHA-256 `43577C4EE5BA2DF99B2E1B6839E1D73197DE0372AC8B63B27D38CB693D6A8E65` |
| Native pre-boot opens | `work/size_run.err:774`, `257989`, `261156`, `263202`, `277371`; `work/flush_long.err:736`, `1241`, `1313`, `1427`, `1547` |
| Native W2 host read / zero cache | `work/size_run.err:289083-289130`; `.fdupi` 59,991 zero bytes SHA-256 `7B5C0196F56232A470EA96EA02111FECE4DDC209761ECFD4BE526DF98A478362`; `.fdupm` `stored_size=0xEA57`, blocks 0 |
| Oracle load order incl. fonts and `K/WD` | `work/agent_ui/kloads_input.tsv`; `K/WD` at `0:00:27.445820` |
| 30 s epilepsy match | `work/rpcs3_oracle/frames_input/frame_030s.png` vs `PresentsRootSCEA.gpb` pair 3 |
| 15 s frame / overlay | `work/rpcs3_oracle/frames_input/frame_015s.png`; `work/rpcs3_oracle/shots/printwindow_1_1643430.png` |
| `pdi` format/size | `PresentsRootSCEA.gpb` pair 2: `0xA5` 32bpp, 460x80, size field `0x24003`; extractor bug at `tools/gt6_gpb_extract.py:90,103` |
| `menu_imagefont.bin` | `work/gt6_vol/font/logo/menu_imagefont.bin`; TXS3 at `0x100`, 448x512, 229,376 data bytes from `0x180`; extractor writes only 114,688 DXT1 bytes |
| Backend format mask | `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c:8389-8397` |
| No-VP generic texture gap | `third_party/ps3recomp/libs/video/rsx_d3d12_backend.c:7798-7804`, `8458-8470`; `docs/analysis/d3d12-draw-readiness.md` §“Remaining blockers” item 5 |
| W2 source-bind review | `docs/analysis/w2-size-check.md` §4.3; `patches/gt6-pfs-source-bind.patch`; `tools/gt6_filedevice_flush_patch.py` |
| Current generated tree | `gt6/generated/ppu_recomp_022.cpp:137371-137391` still the old `[filesize]` block; no `[pfsbind]` |
| Fixer trace artifacts | `work/boot_presents/*` (17:48–17:54); `work/agent_ui/*` (GPB strings, imagefont, RSX trace attempts); no boot/presents source patch |
