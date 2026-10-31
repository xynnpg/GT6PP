# First visible legal/loading UI — independent check

**Date:** 2026-10-31
**Checker scope:** read-only. No source edit, no relift, no build, and no
`gt6.exe` run by this check. Evidence is the extracted `GT.VOL` tree, the
RPCS3 oracle logs/screenshots, the native logs, the generated ZC, and the
fixer's current patch/tool. `third_party/PDTools` and `GTAdhocToolchain` were
not read or used.
**Inputs:** `docs/analysis/rpcs3-oracle.md`, `work/rpcs3_oracle/frames_*`,
`work/flush_long.err`, `work/size_run.err`, `work/probe_run.err`,
`work/gt6_vol`, `work/gt6_hdd0`, `work/gt6_pfs_keymap.tsv`,
`docs/analysis/filedevice-null-vcall-fix.md` §11,
`patches/gt6-pfs-source-bind.patch`, and
`tools/gt6_filedevice_flush_patch.py`.

## 0. Verdict

| Item | Verdict | Finding |
|---|---|---|
| Oracle first visible pixels (15 s frame: GT6 logo, © 2013 SCEI, ESRB) | **FAIL (unmapped)** | No extracted GT.VOL GPB texture identified in this check matches the full frame composition. The PresentsRoot GPBs contain a different `notice.dds` (full legal text) plus `scei`/`pdi`/`epilepsy`. The 15 s asset is not identified; do not map it to `PresentsRootSCEA.gpb`. |
| Oracle first PDIPFS-backed legal sequence | **PASS** | `boot.adc` `presents_sequence_common` selects `PresentsRootSCEA` and iterates `presents_table_scea`: `common/JP/scei` 2.0 s, `common/notice` 2.0 s, `scea/JP/epilepsy` 4.0 s. The 30 s oracle frame is an exact visual match to the embedded `epilepsy.dds`. |
| First visible screen draw type | **PASS (class), stream not captured** | `PresentsRoot` is a 2D image UI project: textured image draws (full-screen or centered) from the GPB, not a 3D or immediate `DATA2F` block. The oracle log does not contain the guest primitive stream, so exact primitive/count is not proven. |
| Native script execution of the four cursor/UI scripts | **PASS** | `MenuClassDefine.adc` (12,464), `Prototypes.mwidget` (5,827), `cursor.mproject` (46,637), `cursor.adc` (40,290) are served; sizes match the disc. |
| Native `K/W2` open/read | **FAIL** | W2 opens as a **host-backed** FileObject (`vt=0x1488218`, `dev=0x7005C000`) with `size=0`. The `.fdupi` is 59,991 **zero** bytes; no `cache_read`/`cache_write` and no `.fdupi` write occur. |
| Fixer's size-only repair (`gt6-pfs-filesize-fix` lineage) | **FAIL for W2** | It is gated to PFS device vtables and therefore does not fire for W2. No `[filesize]` line exists in `size_run.err`. |
| Fixer's source-bind patch (`gt6-pfs-source-bind.patch`) | **FAIL (unproven; do not merge)** | It is unbuilt and untested. Its preconditions (`FileObject+0x88` cache and `FileStream+0x4C` PFS read state) are not measured; the only measured stream/device pair for W2 is **host** (`A08ED0 dev=0x01630B80`), so the `+0x90 == 0xA0043C` gate may not fire. |
| Native boot/presents path | **FAIL / earlier than W2** | The native logs show **no** `boot.adc` (K/LH), `boot.mproject` (K/KG), `BootProject.gpb` (K/IE), `PresentsRootSCEA.gpb` (K/WD), or font-key loads. W2 is not the first missing step for the oracle's first screen. |
| GPB/texture/font paths, sizes, hashes | **PASS** | Every path/size below was independently read from the extracted tree and the TOC; no fabricated asset is required. |
| Fabrication | **PASS (none)** | No cache byte is synthesized by the reviewed patch; the only proposed write is guest-owned size/device state. `Prototypes.adc` is still correctly treated as absent/not required. |

"FAIL" here means **not supported by the available logs/assets, or not safe to
merge yet**; it does not assert that the code is necessarily wrong. An
unverified mapping is a FAIL for review purposes.

**Bottom line:** the oracle's first *asset-mapped* legal sequence is the
`boot.adc` PresentsRoot sequence, and its epilepsy frame is exactly
`PresentsRootSCEA.gpb`'s embedded `epilepsy.dds`. The fixer's W2 source-bind is
not the first missing native step for that screen: the native port never loads
the boot/presents assets or fonts at all. On the current cursor path, W2's
first missing step is the data read, not GPB decode or D3D12 sampling; the
source-bind patch is a plausible direction but is unmeasured and currently
does not fire in the only W2 run that used the size repair.

## 1. Oracle evidence: the presents sequence

### 1.1 Script path

`boot.adc` (`projects/gt6/boot/boot.adc`, 141,821 bytes) contains
`presents_sequence_common` and the region table. Disassembly with
`tools/adch_disasm.py` gives:

```text
presents_table_scea:
  common/JP/scei      2.0 s
  common/notice       2.0 s
  scea/JP/epilepsy    4.0 s

presents_sequence_common(context):
  PresentsRoot.resource_name = "PresentsRootSCEA"
  PresentsRoot.open(context)
  for p in presents_table:
      PresentsRoot.changeImage(p.path)
      Thread.Sleep(p.sec)
```

`display_sequence_gt6` calls `presents_sequence_common` first, then opens
`AdjustScreenRoot` (the display-area screen) and later `MovieRoot` (the
`OPENING` movie). This matches the oracle order: legal/presents → display
area → epilepsy → intro.

### 1.2 PDIPFS load order in the successful oracle run

Host creation times under
`tools/RPCS3/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/`:

| Key | Size | Creation (2026-10-31) | Asset |
|---|---:|---|---|
| K/4M | 69,040 | 16:54:09.807 | `font/vec/IwataUD_M_latin.vec` |
| K/5I | 1,923,568 | 16:54:09.846 | `font/vec/IwataUD_M_JP.vec` |
| K/V4 | 60,368 | 16:54:09.895 | `font/vec/IwataUD_B_latin.vec` |
| K/HP | 1,883,168 | 16:54:09.935 | `font/vec/IwataUD_B_JP.vec` |
| K/TY | 59,696 | 16:54:09.984 | `font/vec/IwataUD_E_latin.vec` |
| K/G4 | 69,536 | 16:54:10.020 | `font/vec/IwataUD_L_latin.vec` |
| K/CP | 16,224 | 16:54:10.059 | `font/vec/GTfcItalic.vec` |
| K/6L | 10,720 | 16:54:10.095 | `font/vec/GTMeterNum.vec` |
| K/9N | 47,904 | 16:54:10.131 | `font/vec/GThk.vec` |
| K/D8 | 36,864 | 16:54:10.168 | `font/vec/FT_B.vec` |
| K/MR | 10,512 | 16:54:10.205 | `font/vec/7seg.vec` |
| K/2F | 29,847 | 16:54:10.244 | `font/logo/menu_imagefont.bin` |
| K/WO | 3,620 | 16:54:10.611 | `products/gt6/script/MenuClassDefine.adc` |
| K/6I | 1,408 | 16:54:10.669 | `products/gt6/script/Prototypes.mwidget` |
| K/JH | 6,258 | 16:54:10.761 | `projects/gt6/cursor/cursor.mproject` |
| K/7E | 13,205 | 16:54:10.819 | `projects/gt6/cursor/cursor.adc` |
| K/W2 | 59,991 | 16:54:10.866 | `projects/gt6/cursor/gpb/CursorProject.gpb` |
| K/KG | 4,146 | 16:54:10.926 | `projects/gt6/boot/boot.mproject` |
| K/LH | 45,923 | 16:54:10.982 | `projects/gt6/boot/boot.adc` |
| K/IE | 7,434 | 16:54:11.089 | `projects/gt6/boot/gpb/BootProject.gpb` |
| K/WD | 69,530 | 16:54:11.344 | `projects/gt6/boot/US/PresentsRootSCEA.gpb` |

This is the requested order proof: the real game loads **fonts, cursor UI,
then the boot project and PresentsRoot**. `K/W2` is loaded before the presents
assets, but it is not the PresentsRoot screen.

The RPCS3 `K/WD` cache is 69,530 bytes, exactly the US GPB's `ZSize`; the
oracle does not log whether the JP or US `K/WD` row was selected, but the
captured frames are English and the US GPB decodes to the English legal text
and epilepsy warning. The W2 cache (59,991 bytes) is separately byte-identical
to the GT.VOL slice at `0xD48800` (SHA-256 `2B6153...9008`). The `K/E2` key is
`projects/gt6/boot/BP/PresentsRootSCEA.gpb` (78,243 compressed, Portuguese
content); it is **not** the US first screen and is absent from the oracle
cache. A fixer mapping K/E2 to the US screen would be wrong.

### 1.3 GPB container and embedded textures

`PresentsRootSCEA.gpb` is a GPB3 container (`3bpg`, big-endian header 0x20,
5 pairs, pair array at 0x20, names at 0x70, data at 0x180). Independent parse:

| Pair | Embedded texture | Dimensions | Format | Data offset | Bytes |
|---:|---|---:|---|---:|---:|
| 0 | `/image/boot/common/JP/scei.dds` | 864x128 | TXS3 0xA6 (DXT1) | 0x180 | 55,555 |
| 1 | `/image/boot/common/notice.dds` | 1440x720 | TXS3 0xA6 (DXT1) | 0xdb00 | 518,659 |
| 2 | `/image/boot/common/pdi.dds` | 460x80 | TXS3 0xA5 (32bpp) | 0x8c580 | 147,459 |
| 3 | `/image/boot/scea/JP/epilepsy.dds` | 1920x1080 | TXS3 0xA6 (DXT1) | 0xb0600 | 1,037,059 |
| 4 | `/image/cursor/loading_circle.dds` | 24x24 | TXS3 0xA6 (DXT1) | 0x1ad980 | 547 |

I decoded the TXS3 blocks (DXT1 565, little-endian block colors) to RGBA:

- `scei.dds` = "Sony Computer Entertainment presents".
- `notice.dds` = the long legal/trademark/PDI notice.
- `pdi.dds` = the Polyphony Digital logo.
- `epilepsy.dds` = the white "WARNING:" epilepsy text.
- `loading_circle.dds` = the loading ring.

`work/rpcs3_oracle/frames_input/frame_030s.png` is an **exact** visual match
to the decoded `epilepsy.dds` (same "WARNING:", line breaks and PS3 wording).
`work/rpcs3_oracle/frames_input/frame_015s.png` is **not** any of these five
textures: it shows the GT6 wordmark, "© 2013 Sony Computer Entertainment Inc.",
and the ESRB "EVERYONE" box. No GT.VOL `.gpb` texture identified in this check
matches the full composition, and `EMAIN.elf` contains no `ESRB`/`GRAN
TURISMO` string or `TXS3` block. The 15 s asset is therefore **not identified**
by this check; it is likely an earlier EBOOT/embedded or movie legal card, or a
composition of a separate `logo_gt6`/image-font asset and an unidentified
rating card, not `PresentsRootSCEA.gpb`. Do not present it as verified. The
15 s capture also sits behind RPCS3's "Precompiling shader interpreter
variants" overlay (`work/rpcs3_oracle/shots/printwindow_1_1643430.png`), so it
is not a clean game-only frame.

### 1.4 Display-area screen

`boot.adc` opens `AdjustScreenRoot` after presents. The disc asset is
`projects/gt6/boot/gpb/AdjustScreenRoot.gpb` (18,944 bytes, ZSize 0x480 =
1,152, key `5W/HH`). It embeds:

- `/image/common/pattern_grid_64.dds` 128x128, TXS3 0x88, 16,643 bytes.
- `/image/component/gt6/arrow.dds` 40x40, TXS3 0xA8, 1,859 bytes.

This is a later 2D grid/arrow adjustment UI, not the first legal screen. The
oracle's screenshot named `fs_printwindow.png` is not present in the workspace;
the display-area visual is therefore **not independently re-verified** here.
The boot script ordering and the `5W/HH` cache are consistent with the oracle,
but that is all.

## 2. Native path after W2

### 2.1 What is proven from the native logs

`work/flush_long.err` (180 s, after the FileDevice guard) and
`work/size_run.err` (300 s, after the size-repair build) both show the same
four UI scripts and then W2. The W2 sequence in `size_run.err` is:

```text
289086 [fileopen] 9F4130 this=0xCFEFE338 file=0xCFEFE398
       vt=0x01488218 dev=0x7005C000 size=0x0
289100 [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
289103 [pfscache] close .../PDIPFS_bdmark/K/W2 size=0
289107 [pfscache] 0xA42108 attach size=0xEA57 id=0xD48800 path=...
289108 [pfscache] open .../PDIPFS/K/W2.fdupm -> fd=4
289111 [pfscache] read .../W2.fdupm nbytes=20 -> 20
289112 [pfscache] 0xA41FEC map loaded blocks=0 size=0xEA57 id=0x0
289115 [pfscache] allocate .../K/W2.fdupi size=0xEA57 -> OK
289118 [fileopen] A3EB60 file=0x00000100 r4=0x014DF818 r5=0x7005C000 r6=0x3A
289119 [fileread] 9F4AA0 stream=0xCFEFE338 req=0xCFEFE2B8 file=0xCFEFE398
289120 [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE338 active=0x00 old=0
289127 [pfscache] close .../K/W2.fdupi size=59991
```

There is **no** `[filesize]`, no `[pfsbind]`, no `0xA40FBC` read, and no
`0xA40984` write. The `.fdupi` is 59,991 bytes but **entirely zero**
(SHA-256 `7B5C0196F56232A470EA96EA02111FECE4DDC209761ECFD4BE526DF98A478362`,
zero nonzero bytes). The `.fdupm` header is `stored_size=0xEA57`, `blocks=0`,
bitmap zero. The source bytes do exist in GT.VOL at `0xD48800`, 59,991 bytes,
SHA-256 `2B6153BACD5E833E9E3BB5B5089552AE3BF973A67FEBA599EC6FCD21DB709008`;
the oracle cache `K/W2` is byte-identical to that slice. The native cache is
preallocated but not populated.

The `[filehost] A08ED0` line is the decisive new evidence: the W2
`FileStream` (`0xCFEFE338`) is attached to a **host** device
(`0x01630B80`), `active=0`, and the host read path is started. `9F4AA0` also
dispatches the host device's `+0x90` slot (not the PFS `0xA0043C`), so the
attached `0xA42108` cache is never consulted. This is consistent with the
FileObject vtable `0x1488218` and host `dev=0x7005C000`.

### 2.2 Stage classification

| Stage | Verdict | Evidence |
|---|---|---|
| Script execution | **PASS** | Four scripts served at `flush_long.err:1241/1313/1427/1547` and `size_run.err:257989/261156/263202/277371`; sizes match the disc. |
| W2 open | **FAIL** | Host FileObject, `size=0`; bdmark marker is 0 bytes; W2 cache attach occurs but is not used. |
| W2 data fetch | **FAIL** | `.fdupi` is zero-filled; no `0xA40FBC` read/write; no GT.VOL bytes copied. |
| Texture/font load | **FAIL / not reached** | No W2 GPB parse, no `CursorProject.gpb` draw data, and no font keys (`K/4M`…`K/2F`) in the native logs. |
| Draw decode | **FAIL / not reached** | No GPB primitive decode; only full-screen `DATA2F` immediate black covers (e.g. `flush_long.err:3670`, `size_run.err:300801`). |
| Backend sampling | **not reached** | No `bind_texture`/`tex0`/textured UI draw. The D3D12 no-VP generic-texture gap is real but downstream. |
| Boot/presents path | **FAIL / earlier** | No K/LH, K/KG, K/IE, K/WD, or font-key opens. RPCS3 opens K/KG at `rpcs3_fullscreen.log` 0:00:28.45; native has no equivalent. |

**Therefore:** on the current cursor path, the first missing step after W2 is
the **data/source fetch and device binding**, not draw decode and not the
D3D12 sampler. For the oracle's first legal/presents screen, the first missing
native step is **earlier**: the native port never runs the boot/presents
sequence or loads its fonts/GPBs. Fixing W2 alone cannot produce the 15 s
legal card or the PresentsRoot frames.

## 3. Review of the fixer's current patch/checklist

The relevant fixer document is `docs/analysis/filedevice-null-vcall-fix.md`
§11; the current reference patch is `patches/gt6-pfs-source-bind.patch`
(created during this check at 17:37), implemented by
`tools/gt6_filedevice_flush_patch.py` `OPEN_SIZE_FIX`.

### 3.1 What is correct

- **PASS:** the size-only repair is insufficient for W2. `size_run.err` shows
  the host device and `size=0`; no `[filesize]` line. The doc says this
  correctly in §11.2.
- **PASS:** the cache is attached for W2: `0xA42108 attach size=0xEA57
  id=0xD48800` and `.fdupm` `stored_size=0xEA57` are real. The cache size is
  the raw `ZSize`, not 239,744.
- **PASS (no fabrication):** the proposed patch copies only guest-owned
  `stored_size` and a guest device pointer; it does not synthesize cache bytes,
  does not modify a vtable, and does not write `.fdupi`.
- **PASS (guarded):** it requires a nonzero `FileObject+0x88` cache and a
  nonzero `_z`, and only rebinds when the current device is not already PFS.
  A blind rewrite of every host open is not proposed.

### 3.2 Claim-by-claim check

| Fixer claim | Verdict | Evidence |
|---|---|---|
| W2's FileObject is host-backed (`vt=0x1488218`, `dev=0x7005C000`) | **PASS** | `size_run.err:289086`; `A08ED0` host stream at 289120. |
| The PFS cache is attached for W2 (`size=0xEA57`) | **PASS** | `0xA42108 attach size=0xEA57 id=0xD48800`; `.fdupm` header. |
| The cache manager is at `FileObject+0x88` | **UNVERIFIED** | `0xA3EB60` writes `[r4+0x88]`, but `r4` identity is not W2's FileObject; no `_f+0x88` log. |
| The PFS read state is at `FileStream+0x4C` with `+0x90 == 0xA0043C` | **UNVERIFIED** | No log of `_s+0x4C`/`[_st vtable+0x90]`; only host `A08ED0` device is measured. |
| The source-bind gate fires for W2 | **NOT OBSERVED** | No `[pfsbind]` in `size_run.err`; generated source still has old `[filesize]` block. |
| The size-only repair cannot fire for W2 | **PASS** | No `[filesize]`; host vtable not in PFS set. |
| The source-bind is the first missing W2 step | **PLAUSIBLE, not proven** | It addresses the right dispatch, but data fetch/object identity is unmeasured. |
| W2 is the first missing step for the oracle's first screen | **FAIL** | Native never loads boot/presents/fonts; those are earlier. |

### 3.3 What is not supported

1. **The patch is unbuilt/untested.** `size_run.err` was produced from
   `gt6/generated/ppu_recomp_022.cpp` that still contains the old
   `[filesize]` block (lines 137371–137391), not the new `[pfsbind]` block.
   The generated source has no `[pfsbind]` string. The `[pfsbind]` positive
   evidence in §11.5 is therefore expected, not observed.
2. **`FileObject+0x88` is not proven to be the cache manager.** The
   `0xA3EB60` probe logs `file=0x00000100 r4=0x014DF818 r5=0x7005C000
   r6=0x3A`; the lifted `0xA3EB60` writes fields at `[r4+0x88]`, but `r4` is
   not shown to be the same object as the W2 FileObject (`0xCFEFE398`).
   The earlier §11.1 analysis identifies `A3EB60`'s `file=0x100` as a PFS
   handle/index, not the FileObject. The superseded size block read the cache
   at `_dev+0x88`; the new block reads `_f+0x88`. Those are different owner
   offsets, and the `0xA3EB60` writer uses `r4`, whose identity is not proven.
   The cache attach at `0xA42108` is proven; its exact owner offset is not.
3. **`FileStream+0x4C` is not proven to be a PFS read state.** Neither
   `0x9F4130` nor `0x9F4AA0` in the lifted source reads `FileStream+0x4C`
   for the read dispatch; `9F4AA0` uses `FileStream+0x44` →
   `FileObject+0x40` → device vtable `+0x90`. The only measured W2
   stream/device pair is host (`A08ED0 dev=0x01630B80 stream=0xCFEFE338`).
   If `_st` is that host device, its `+0x90` is not `0xA0043C` and the gate
   will not fire. This must be measured before calling the layer "correct".
4. **The doc's evidence citation is wrong.** §11.4 cites the K/IK positive
   control at `size_run.err:625-626`. The K/IK `9F4AA0` → `0xA40FBC` control
   is in `probe_run.err:625-626`; `size_run.err:625` is a thread creation /
   null-read region, not K/IK. The claim is true in substance but the cited
   file/line is not.
5. **The doc's probe-status wording is misleading.** §11.5 says the 300 s
   log has only the old probe format and "the latest probe extension was not
   in that build." `size_run.err` does contain the new `[filehost] A08ED0` and
   `0xA42108 attach size=... id=... path=...` probes. Only the
   `9F4130 path/dev_vt` extension is missing. This matters because the
   `A08ED0` line already shows the host path.
6. **Overlap/ownership:** the patch modifies the generic `FileObject` open
   helper (`0x9F4130`) and the W2/PFS read path. It overlaps the PFS/W2 owner
   and the FileDevice owner, not the D3D12 backend owner. The D3D12 no-VP
   generic-texture gap is downstream and must not be "fixed" in parallel as
   if it were the first missing step. No backend change can make an unread
   W2 GPB or unloaded fonts visible.

### 3.4 Risk if merged as-is

The patch rewrites `FileObject+0x40` from a host device to a state object
whose vtable `+0x90` happens to be the PFS read entry. That is a **type
change**, not a data repair. If the state object is not a full
`FileDevicePFS` (or if the FileObject's other fields are host-layout), the PFS
read can dereference the wrong object, read the zero-filled `.fdupi`, or
crash. The gate reduces the blast radius but does not prove the object
identity. It must be A/B tested on W2 with a probe that prints
`_f+0x88`, `_s+0x4C`, `[_st]`, `[_st vtable+0x90]`, and `_c+0x10` before the
write.

## 4. Exact asset/font paths and sizes

All values below are from `work/gt6_volume_entries.txt`,
`work/gt6_pfs_keymap.tsv`, and the extracted files; no value is inferred from
the fixer's prose.

| Key | Compressed | Uncompressed | Path | SHA-256 (extracted) |
|---|---:|---:|---|---|
| K/WD | 69,530 | 1,760,256 | `projects/gt6/boot/US/PresentsRootSCEA.gpb` | `301B687A0CEA78FB8E4A8BC0399BC67D8382DE4BBF3465D6751EBE11132418E5` |
| K/E2 | 78,243 | 1,760,256 | `projects/gt6/boot/BP/PresentsRootSCEA.gpb` (Portuguese) | `0B8B53BF8FA95739309CB6EE50CAD670D3755F35F5756F26E1B3A35B1CC14333` |
| K/LH | 45,923 | 141,821 | `projects/gt6/boot/boot.adc` | `7149EFCAD057B80486EA1650CF04F98EB6FE4C6F44AF2DF15B5848A88F10AE` |
| K/KG | 4,146 | 42,624 | `projects/gt6/boot/boot.mproject` | `15D0DCFCE78E44E4DF3ACB85FC2687D2AC99E6B206E7358A007B9D0C1DABE599` |
| K/IE | 7,434 | 14,592 | `projects/gt6/boot/gpb/BootProject.gpb` | `D4487DD29B12CC1F53754FF7B2E51905D71C1A4F516F7C403AAB5E5A69DCFAF8` |
| 5W/HH | 1,152 | 18,944 | `projects/gt6/boot/gpb/AdjustScreenRoot.gpb` | not needed for first screen |
| K/W2 | 59,991 | 239,744 | `projects/gt6/cursor/gpb/CursorProject.gpb` | `FE53F68799A1DF35FB05F24F77B0A5B906EFF9A676714607990F02DFE85ED923` |
| K/WO | 3,620 | 12,464 | `products/gt6/script/MenuClassDefine.adc` | — |
| K/6I | 1,408 | 5,827 | `products/gt6/script/Prototypes.mwidget` | — |
| K/JH | 6,258 | 46,637 | `projects/gt6/cursor/cursor.mproject` | — |
| K/7E | 13,205 | 40,290 | `projects/gt6/cursor/cursor.adc` | — |
| K/2F | 29,847 | 229,891 | `font/logo/menu_imagefont.bin` | `D8E0F5E7D17AC08146AF464994E8AB8873DDBD7BF1748DD4BEA89C7333E9F9B4` |

Fonts (all uncompressed, loaded by the oracle before the boot project):

| Key | Bytes | Path |
|---|---:|---|
| K/4M | 69,040 | `font/vec/IwataUD_M_latin.vec` |
| K/5I | 1,923,568 | `font/vec/IwataUD_M_JP.vec` |
| K/V4 | 60,368 | `font/vec/IwataUD_B_latin.vec` |
| K/TY | 59,696 | `font/vec/IwataUD_E_latin.vec` |
| K/HP | 1,883,168 | `font/vec/IwataUD_B_JP.vec` |
| K/G4 | 69,536 | `font/vec/IwataUD_L_latin.vec` |
| K/CP | 16,224 | `font/vec/GTfcItalic.vec` |
| K/6L | 10,720 | `font/vec/GTMeterNum.vec` |
| K/9N | 47,904 | `font/vec/GThk.vec` |
| K/D8 | 36,864 | `font/vec/FT_B.vec` |
| K/MR | 10,512 | `font/vec/7seg.vec` |

`Prototypes.adc` remains absent and is not required by the oracle. The native
port requests it as a path artifact; do not fabricate or alias it.

## 5. Safest next step

1. **Do not merge the source-bind patch as "fixed."** It is unbuilt and its
   two object-identity assumptions are unmeasured. Add the missing read-only
   probes first (below), then apply it in an isolated A/B.
2. **Probe W2 before changing it.** At `0x9F4130` and `0x9F4AA0`, log for the
   W2 stream (`0xCFEFE338`): `FileObject+0x88`, `FileStream+0x4C`, `[_st]`,
   `[_st vtable+0x90]`, `_c+0x10`, and the current `FileObject+0x40` device
   vtable. The existing `A08ED0` line already shows a host device; confirm
   whether `FileStream+0x4C` is that host device or a PFS state. If it is the
   host device, the source-bind gate cannot fire; move the fix to the PFS
   source-open (`0x9FDAAC`/`0x9F8E40`), not the generic helper.
3. **If the gate is proven**, apply it only to cache-backed host FileObjects,
   run 240–300 s, and require all of:
   - `[pfsbind] file=... state=... dev=0x........ size=0xEA57`
   - `[pfscache] 0xA40FBC read file=0x00000100 off=0x0 ...`
   - `[pfscache] 0xA40984 write ... size=0xEA57 block=0 ...`
   - `K/W2.fdupi` = 59,991 bytes = GT.VOL[0xD48800..+0xEA57], SHA-256
     `2B6153BACD5E833E9E3BB5B5089552AE3BF973A67FEBA599EC6FCD21DB709008`.
   If any line is absent, do not widen the condition; the object model is
   wrong and the PFS source-open is the next owner.
4. **Separately instrument the earlier boot/presents gap.** The native port
   must open K/KG, K/LH, K/IE, K/WD and the font keys before any PresentsRoot
   frame can appear. Compare against the oracle times in §1.2. If the native
   boot trigger never issues those opens, fixing W2 will still leave the
   first legal screen black; that is the higher-priority gap for the first
   visible screen.
5. **Do not couple this to D3D12 sampling.** The backend's no-VP generic
   texture gap is real (`d3d12-draw-readiness.md`), but the native log has no
   textured UI draw to sample yet. Backend work should wait until W2/fonts
   produce GPB draws; otherwise the W2 owner and the D3D12 owner will both
   claim the same missing frame.
6. **Do not require or fabricate `Prototypes.adc`.** The v1.00 oracle reaches
   the Player Name screen without it; the native `.adc` request is a loader
   path artifact.

## 6. Evidence index

| Evidence | Location |
|---|---|
| PresentsRoot script/table/order | `work/gt6_vol/projects/gt6/boot/boot.adc`; disassembly `presents_sequence_common`, `presents_table_scea`, `display_sequence_gt6` |
| PresentsRoot GPB pairs/textures | `work/gt6_vol/projects/gt6/boot/US/PresentsRootSCEA.gpb` (1,760,256 bytes; pairs at 0x20, data at 0x180) |
| Decoded `epilepsy.dds` matches 30 s oracle frame | `work/rpcs3_oracle/frames_input/frame_030s.png` vs embedded 1920x1080 TXS3 at 0xb0600 |
| 15 s frame has no GT.VOL GPB match | `work/rpcs3_oracle/frames_input/frame_015s.png`; all extracted `.gpb` texture scan; `EMAIN.elf` string scan |
| Oracle load order | PDIPFS `K/` cache creation times 16:54:09–11; `work/rpcs3_oracle/rpcs3_fullscreen.log` K/KG stat at 0:00:28.45 |
| W2 host FileObject, size 0 | `work/size_run.err:289086` |
| W2 cache attach, bdmark, zero `.fdupi` | `work/size_run.err:289100–289127`; `work/gt6_hdd0/.../K/W2.fdupi` (all zero), `.fdupm` (stored_size 0xEA57, blocks 0) |
| W2 raw GT.VOL slice | GT.VOL offset `0xD48800`, 59,991 bytes, SHA-256 `2B6153...9008`; RPCS3 `K/W2` equals it |
| Host read state for W2 | `work/size_run.err:289120` `[filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE338 active=0x00 old=0` |
| K/IK positive control | `work/probe_run.err:625–626` (`9F4AA0` → `0xA40FBC` read 572,352 bytes) |
| Native four scripts | `work/flush_long.err:1241/1313/1427/1547`; `work/size_run.err:257989/261156/263202/277371` |
| Native black-only draws | `work/flush_long.err:3670`; `work/size_run.err:300801`; no `[DRAWDIAG]`/`[LEGACYVTX]` textured UI |
| Fixer patch | `patches/gt6-pfs-source-bind.patch`; `tools/gt6_filedevice_flush_patch.py` `OPEN_SIZE_FIX` |
| Fixer doc | `docs/analysis/filedevice-null-vcall-fix.md` §11.2–§11.6 |
| Stale generated block | `gt6/generated/ppu_recomp_022.cpp:137371–137391` (old `[filesize]`, no `[pfsbind]`) |
