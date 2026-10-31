# Seed the native PFS cache with the boot/presents slices

**Date:** 2026-10-31
**Status:** data-only fix, verified against the GT.VOL TOC. No runtime or
generated code changed.

## Why

The RPCS3 oracle opens the first boot assets directly from the PDIPFS cache at
`0:00:27` (`work/rpcs3_oracle/rpcs3_input.log`):

| Key | Oracle path | Size | GT.VOL TOC |
|---|---|---|---|
| `K/KG` | `.../PDIPFS/K/KG` | 4,146 | `projects/gt6/boot/boot.mproject` |
| `K/LH` | `.../PDIPFS/K/LH` | 45,923 | `projects/gt6/boot/boot.adc` |
| `K/IE` | `.../PDIPFS/K/IE` | 7,434 | `projects/gt6/boot/gpb/BootProject.gpb` |
| `K/WD` | `.../PDIPFS/K/WD` | 69,530 | `projects/gt6/boot/US/PresentsRootSCEA.gpb` |

The native HDD tree contained only 11 PDIPFS keys (`4D`, `6I`, `7E`, `DK`,
`E9`, `IK`, `JH`, `PD`, `R2`, `W2`, `WO`). `LH`, `KG`, `IE`, `WD` and every
boot font key were missing, so the guest's `sys_fs_stat`/open never reached the
higher-level `HFileReader` override. The boot script can only run
`presents_sequence_common` if those opens succeed.

## Fix

`tools/gt6_seed_pfs_cache.py` reads the existing keymap
(`work/gt6_pfs_keymap.tsv`) and copies the **raw** GT.VOL slice for each key
into `work/gt6_hdd0/.../PDIPFS/K/<key>`. The bytes are still volume-encrypted,
exactly like the working `K/IK` cache file (572,352 B, TOC `0x8BBC0`); the
guest's own PFS cipher/inflate path is unchanged. It also creates zero-length
`PDIPFS_bdmark/K/<key>` markers so existence checks succeed.

```powershell
python tools\gt6_seed_pfs_cache.py --boot-set --dry-run
python tools\gt6_seed_pfs_cache.py --boot-set
python tools\gt6_seed_pfs_cache.py --boot-set --verify
```

`--boot-set` covers `K/LH`, `K/KG`, `K/IE`, `K/WD` and the 12 boot font keys
(`K/4M`, `K/5I`, `K/V4`, `K/HP`, `K/TY`, `K/G4`, `K/CP`, `K/6L`, `K/9N`,
`K/D8`, `K/MR`, `K/2F`). `--verify` re-reads GT.VOL and compares SHA-256.

## Evidence the slice is right

| Key | Cache file bytes | SHA-256 (first 16) |
|---|---|---|
| `K/LH` | 45,923 | `d1cec8fef4d6e1f2` |
| `K/KG` | 4,146 | `875d4031b9f3830b` |
| `K/IE` | 7,434 | `9a91a2972088f0b3` |
| `K/WD` | 69,530 | `43577c4ee5ba2df9` |

All four match `GT.VOL[offset : offset + ZSize]` for their TOC rows.

## Verification

Run 300 s with `GT6_PFS_TRACE=1` and check for:

- `[pfscache] open '.../PDIPFS/K/LH'` and a non-zero read;
- `[GT6] pfs override: serving plaintext projects/gt6/boot/boot.adc` (or the
  guest's own decrypt succeeding);
- the same for `K/KG`, `K/IE`, `K/WD` and the font keys;
- `[RSX] IMMEDIATE` / draw diagnostics with a non-black attr3 or a texture;
- `work/rsxcap_seeded/frame_*/backbuffer.bmp` checked by
  `python tools/gt6_frame_check.py`.

If the guest instead takes the bdmark cache route (`stat K/<key>.fdupm`,
`open K/<key>.fdupi`), the bare file is not enough: the mount/device fix in
`docs/analysis/pfs-mount-device-fix.md` must land first. The two changes are
complementary, not alternatives.
