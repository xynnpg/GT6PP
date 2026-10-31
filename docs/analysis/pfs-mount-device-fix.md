# PFS mount/device selection for K/W2: retargeted to the bare-cache path

**Date:** 2026-10-31
**Scope:** the W2 `PDIPFS_bdmark/K/W2` vs bare `PDIPFS/K/W2` choice, the
oracle sequence in `work/rpcs3_oracle/rpcs3_input.log`, the RPCS3 HDD tree,
and the smallest data-level fix. Read-only for `gt6/generated`; no build and
no `gt6.exe` run was performed by this analysis.
**Inputs:** `work/rpcs3_oracle/rpcs3_input.log`, `tools/RPCS3/dev_hdd0`,
`gt6/GT.VOL`, `work/gt6_hdd0`, `work/size_run.err`, `work/probe_run.err`, and
the guest disassembly in `work/bin/EMAIN.elf`.
**Policy:** `third_party/PDTools` was not read or used.

## 0. Verdict

| # | Question | Verdict | Finding |
|---:|---|---|---|
| 1 | Does the oracle open bare `PDIPFS/K/W2`? | **PASS** | `sys_fs_stat` -> `sys_fs_open(flags=0)` -> `lseek(0)` -> `read(0x8000)` + `read(0x6A57)` -> `close` at `0xEA57/0xEA57`. There is no bdmark/W2, `.fdupm`, or `.fdupi` access for W2. |
| 2 | Is `PDIPFS_bdmark` a native-port artifact? | **FAIL (hypothesis)** | RPCS3's own HDD has a `PDIPFS_bdmark` tree, and the oracle creates zero-length markers there for keys missing from the bare cache (e.g. `K/96`). It is a real fallback, not an artifact. |
| 3 | Is the marker directory preferred? | **FAIL (hypothesis)** | The guest tries the bare file first. For W2 the bare stat succeeds and the bare file is opened; for `K/96` the bare stat fails, then the bdmark marker and `.fdupm`/`.fdupi` fallback run. |
| 4 | Why did native W2 get a host FileObject? | **PASS (explained)** | The native tree had no bare `PDIPFS/K/W2`, so the guest took the bdmark fallback and opened the zero-length host marker. `0x9F4130` correctly returned that host FileObject (`vt=0x1488218`, `dev=0x7005C000`). The mount device selection is not the bug. |
| 5 | Smallest correct fix | **PASS** | Seed bare `work/gt6_hdd0/.../PDIPFS/K/W2` with `GT.VOL[0xD48800..+0xEA57]`. Do not remove the bdmark tree; it is the fallback for keys that are not on HDD. No generated-code/vtable patch is needed. |
| 6 | Rejected `FileObject+0x40` bind | **REMOVED** | `tools/gt6_filedevice_flush_patch.py` and `tools/post_lift_fixes.py` no longer require or add it. Both checks now exit 0. |
| 7 | Success criterion | **UPDATED** | The bare path must read `0x8000 + 0x6A57 = 0xEA57` bytes, then the guest decrypt/inflate must produce the 239,744-byte GPB. `0xA40FBC` may still appear; `0xA40984` is not required for a completed bare cache. |

**Bottom line:** the oracle-verified W2 path is a direct bare-cache file, not
a PFS cache build. The native port diverged only because its HDD tree lacked
the bare file. The data fix is already applied and byte-identical to GT.VOL.
The mount/device patch and the `FileObject+0x40` bind are both unnecessary
and should not land.

**Scope caveat:** this data fix resolves W2 because W2 exists in GT.VOL and
the oracle chooses the bare cache file. It does not claim that the
bdmark/cache-build path is correct for keys absent from both the HDD tree and
the volume; those still use the marker + `.fdupm`/`.fdupi` flow and would need
a separate trace. The marker directory must remain for that fallback.

## 1. Oracle sequence (verified)

`work/rpcs3_oracle/rpcs3_input.log`:

```text
64326  sys_fs_stat(path=".../PDIPFS/K/W2")
64329  sys_fs_open(path=".../PDIPFS/K/W2", flags=00) -> fd=3
64330  sys_fs_open(): fd=3, Regular file, Pos/Size: 0/58.585KB (0x0/0xea57)
64331  sys_fs_lseek(fd=3, offset=0x0, whence=0x0)
64332  sys_fs_read(fd=3, buf=*0x1632800, nbytes=0x8000)
64333  sys_fs_read(fd=3, buf=*0x163a800, nbytes=0x6a57)
64337  sys_fs_close(fd=3): Pos/Size: 58.585KB/58.585KB (0xea57/0xea57)
```

Immediately before W2, the same main thread opens bare `K/JH` (6,258 B) and
`K/7E` (13,205 B); the `ksF3` thread opens bare `K/RP` (131,553 B). Immediately
after W2, the boot/presents set (`K/KG`, `K/LH`, `K/IE`, `K/WD`) is opened the
same way. None of these use bdmark. A log-wide search finds no
`PDIPFS/K/W2.fdupi`, `PDIPFS/K/W2.fdupm`, or `PDIPFS_bdmark/K/W2` access at
all.

The bdmark fallback is visible for a key that is **not** on HDD:

```text
80721  sys_fs_stat(path=".../PDIPFS/K/96") -> ENOENT
80730  sys_fs_stat(path=".../PDIPFS_bdmark/K")
80733  sys_fs_open(path=".../PDIPFS_bdmark/K/96", flags=02102) -> fd=6
80734  sys_fs_open(): Pos/Size: 0/0 (0x0/0x0)      # zero-length marker
80747  sys_fs_stat(path=".../PDIPFS/K/96.fdupm")
80750  sys_fs_open(path=".../PDIPFS/K/96.fdupm", flags=02)
80755  sys_fs_open(path=".../PDIPFS/K/96.fdupi", flags=0102)
80760  sys_fs_truncate(path=".../PDIPFS/K/96.fdupi", size=0x3a000)
```

The oracle later creates missing bdmark directories and markers (`0:00:51`,
`PDIPFS_bdmark/58`, `PDIPFS_bdmark/5V`, ...). So the marker directory is a
normal part of the PDIPFS design and must be preserved.

### 1.1 RPCS3 HDD contents

`tools/RPCS3/dev_hdd0/game/BCUS98296/USRDIR` contains **both** trees:

| Path | State |
|---|---|
| `PDIPFS_bdmark/K/W2` | 0 bytes (marker) |
| `PDIPFS_bdmark/K/96` | 0 bytes (marker) |
| `PDIPFS/K/W2` | **59,991 bytes**, SHA-256 `2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008` |
| `PDIPFS/K/96` | absent; only `96.fdupm`/`96.fdupi` after the fallback |

The bare W2 file is byte-identical to `GT.VOL[0xD48800..+0xEA57]`
(`ZSize=0xEA57`). Both the bare file and the marker coexist; the oracle still
chooses the bare file. That is the decisive comparison.

### 1.2 Native state before and after

Before this fix the native tree had:

* no bare `work/gt6_hdd0/.../PDIPFS/K/W2`;
* a zero-length `PDIPFS_bdmark/K/W2` marker;
* `W2.fdupi` 59,991 zero bytes and `W2.fdupm` `(0xEA57,0,0)`.

The measured run therefore took the bdmark fallback:

```text
size_run.err:289083  [fileopen] 9F8E40 ... file=0xCFEFE398
size_run.err:289086  [fileopen] 9F4130 ... vt=0x01488218 dev=0x7005C000 size=0x0
size_run.err:289100  [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
size_run.err:289117  [pfscache] 0x9FDC5C attach ...  (PFS handle 0x100, separate object)
size_run.err:289119  [fileread] 9F4AA0 ... file=0xCFEFE398
size_run.err:289120  [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE398
```

This is the expected result of opening a host marker: `0x9F8E40` returns the
host `FileObject`, and `0x9F4AA0` dispatches the host device. The PFS cache
attach at `0x9FDC5C` belongs to the fallback PFS handle, not to the reader's
`FileObject`; the reader therefore never uses it. This is a **path-selection**
outcome, not a mount-table mis-selection, and not a reason to overwrite
`FileObject+0x40`.

After the data fix, the native tree is:

```text
work/gt6_hdd0/.../PDIPFS/K/W2   59,991 bytes
SHA-256 2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

The native path mapping is the same guest path: `gt6/src/main.cpp:663-679`
maps `/dev_hdd0/game/BCUS98296/` to `work/gt6_hdd0/game/BCUS98296` (and sets
`PS3_HDD0_ROOT` to `work/gt6_hdd0`), so the bare file above is the file the
guest's `sys_fs_stat`/`sys_fs_open` will see.

`python tools\gt6_pfs_cache_warm.py --key K/W2 --check` now reports:

```text
completed   .../PDIPFS/K/W2 (bare cache file; guest opens this first)
PASS        data is byte-identical to the GT.VOL slice
WARN        stale/incomplete .fdupm ignored: the guest opens the completed
            bare file and never reads this map
```

## 2. Guest selection rule

The oracle shows the order directly:

1. `sys_fs_stat("/dev_hdd0/game/<title>/USRDIR/PDIPFS/K/<key>")`.
2. On success: `sys_fs_open` that bare file with `flags=0`, then read it.
3. On `CELL_ENOENT`: `sys_fs_stat(".../PDIPFS_bdmark/K")`, create/open
   `.../PDIPFS_bdmark/K/<key>` with flags `0x442`, then stat/open
   `.../PDIPFS/K/<key>.fdupm` and `.../PDIPFS/K/<key>.fdupi` for the cache
   build.

The marker directory is therefore a **fallback**, not a preferred mount. It is
not removed by the oracle and must not be removed by the port. A bare file is
authoritative when it exists; a stale `.fdupm`/`.fdupi` next to it is ignored.

Implication for the mount/device layer: `0x9F4130` returning a host
`FileObject` is correct for the host marker path. The PFS device itself is
healthy (the K/IK positive control reaches `0x9F4AA0 -> 0xA0043C ->
0xA40FBC`). The W2 blocker was that the guest was given the bdmark path
because the bare file was absent. Seeding the bare file restores the oracle
path without touching mount order, vtables, `FileObject+0x40`, or the cache
size fields.

## 3. Fix (data only)

```powershell
python tools\gt6_seed_pfs_cache.py --keys K/W2
python tools\gt6_seed_pfs_cache.py --keys K/W2 --verify
```

Expected output of `--verify`:

```text
K/W2   projects/gt6/cursor/gpb/CursorProject.gpb   zsize=0xEA57 off=0xD48800
  OK sha256=2b6153bacd5e833e...
```

Do **not** rename or delete `PDIPFS_bdmark`: the oracle uses it for every key
that is not present as a bare cache file (`K/96`, `K/IP`, and the later
`PDIPFS_bdmark/58`, `5V`, `5B`, `5U` paths). Removing the whole tree would
break those fallbacks. Removing only `PDIPFS_bdmark/K/W2` is harmless but
unnecessary because the bare file already wins.

The stale `W2.fdupi`/`W2.fdupm` pair is also harmless; it is ignored while the
bare file exists. It may be deleted for cleanliness, but the minimal fix is the
single bare file.

## 4. Success criterion (updated)

The bare-file path is now the primary criterion:

| Check | Requirement |
|---|---|
| Bare stat/open | `sys_fs_stat .../PDIPFS/K/W2` succeeds; `sys_fs_open flags=0` returns size `0xEA57` |
| Bare reads | `sys_fs_read` totals `0xEA57` bytes (oracle: `0x8000` + `0x6A57`) |
| Close | Pos/Size `0xEA57/0xEA57` |
| Guest decode | the guest PFS decrypt/inflate produces `CursorProject.gpb` = 239,744 bytes (`Size=0x3A880`) |
| Cache probes | `0xA40FBC` may appear (the K/IK control uses it to read the completed bare file); `0xA40984` is **not** required and its absence is not a failure |

The old criterion "W2 must reach `0xA40FBC`/`0xA40984` and produce `.fdupi`
59,991 bytes + `.fdupm` blocks=8" describes the **fallback cache-build path**
when the bare file is absent. It remains valid only for that case:

| Fallback path (bare file missing) | Requirement |
|---|---|
| bdmark marker | zero-length `PDIPFS_bdmark/K/W2` is opened |
| `.fdupm` | `(0xEA57, 0, 8)`, bitmap `FF` |
| `.fdupi` | 59,991 raw bytes, byte-identical to GT.VOL |
| Probes | `0xA40FBC` then `0xA40984` block writes |

Do not accept a 59,991-byte zero `.fdupi` as success. With the bare file in
place, the guest should not open `.fdupi` at all, matching the oracle.

Optional decoded-output check:

```text
work/gt6_vol/projects/gt6/cursor/gpb/CursorProject.gpb
  239,744 bytes
  SHA-256 FE53F68799A1DF35FB05F24F77B0A5B906EFF9A676714607990F02DFE85ED923
```

Runtime check with the existing cellFs/guest probes (no new probe patch needed):

```powershell
$env:GT6_PFS_CACHE_TRACE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\w2_bare_run.log
```

Look for the bare path before any bdmark access:

```text
[pfscache] stat '.../PDIPFS/K/W2' -> size=59991
[pfscache] open '.../PDIPFS/K/W2' flags=0x0 -> fd=...
[fs] read fd=... nbytes=...    # total 0xEA57
```

If the log instead shows `PDIPFS_bdmark/K/W2` first and no bare stat/open,
the guest is not seeing the seeded file; check the `/dev_hdd0` mapping and
file name before touching the mount code.

## 5. Patch / diff and tool state

There is no generated-code patch. The change is one data file:

```diff
+ work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/W2
+   = GT.VOL[0xD48800 .. 0xD48800 + 0xEA57)
+   length 59,991
+   SHA-256 2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

The current `gt6/generated/ppu_recomp_022.cpp` still contains the old
size-only block because this analysis did not edit generated code. It is inert
for W2 (the host device vtable `0x1489480` fails its PFS gate, so it writes
nothing), and `tools/gt6_filedevice_flush_patch.py` strips it on the next apply
or relift. It is not required by either check.

The rejected generated-code patch was removed from the post-lift tooling:

* `tools/gt6_filedevice_flush_patch.py` no longer adds the
  `FileObject+0x40` bind or the old size-only block; it strips either block if
  an already-patched tree still contains it. It retains only the two
  `FileDeviceHost` lifetime guards.
* `tools/post_lift_fixes.py` no longer requires the `func_009F4130` bind.
* `tools/gt6_pfs_cache_warm.py` now prefers a completed bare `<key>` file,
  matching the guest, and treats a stale `.fdupm` as a warning rather than a
  failure when the bare file is present.

Current checks:

```text
python tools\gt6_filedevice_flush_patch.py --check gt6\generated
  ppu_recomp_022.cpp: FileDeviceHost guard OK
  ppu_recomp_023.cpp: FileDeviceHost guard OK
  exit 0

python tools\post_lift_fixes.py gt6\generated
  func_00A13644 body OK
  func_00987884 ADCH switch OK
  func_00A08B8C FileDeviceHost guard OK
  func_00A08A00 FileDeviceHost guard OK
  exit 0

python tools\gt6_pfs_cache_warm.py --key K/W2 --check
  PASS data is byte-identical to the GT.VOL slice
  WARN stale/incomplete .fdupm ignored
  exit 0
```

## 6. Note for the independent checker

The previously rejected "bind `FileObject+0x40` to the PFS read state" patch is
not part of this fix. The oracle proves W2 normally opens the bare
`PDIPFS/K/W2` file directly (`0:00:27.225`), while bdmark is only the fallback
for keys missing from the bare cache (`K/96` at `0:00:28.475`); RPCS3's HDD
contains both trees, and its bare W2 is byte-identical to GT.VOL. Native W2
diverged solely because the bare file was absent, so the correct minimal fix
is the data file, not a mount/vtable/FileObject patch. The bare file is now
present (`59,991` bytes, SHA-256 `2b6153…9008`), the stale `.fdupm` is
correctly ignored, and the post-lift/FileDevice checks pass. The remaining
runtime verification is the oracle's `0x8000 + 0x6A57` read and the 239,744-byte
decoded GPB; `0xA40984` is not required on this path.

## 7. Evidence index

| Evidence | Location / value |
|---|---|
| Oracle bare W2 stat/open/lseek/read/close | `rpcs3_input.log:64326-64337` |
| Oracle bare RP/JH/7E opens | `rpcs3_input.log:64283-64323` |
| Oracle bdmark fallback for `K/96` | `rpcs3_input.log:80721-80760` |
| Oracle creates later bdmark dirs | `rpcs3_input.log:106462-106490` |
| RPCS3 bare W2 | `tools/RPCS3/dev_hdd0/.../PDIPFS/K/W2`, 59,991 B, SHA `2b6153…9008` |
| RPCS3 bdmark W2 | `tools/RPCS3/dev_hdd0/.../PDIPFS_bdmark/K/W2`, 0 B |
| Native W2 before fix | no bare file; bdmark marker 0 B; `.fdupi` zero, `.fdupm` blocks 0 |
| Native host FileObject | `size_run.err:289083-289120` |
| K/IK positive control | `probe_run.err:621-629` |
| Native bare W2 after fix | `work/gt6_hdd0/.../PDIPFS/K/W2`, 59,991 B, SHA `2b6153…9008` |
| Decoded GPB | `work/gt6_vol/.../CursorProject.gpb`, 239,744 B, SHA `FE53F687…D923` |
| Rejected bind removed | `tools/gt6_filedevice_flush_patch.py`, `tools/post_lift_fixes.py` |
