# PFS mount/device selection and W2 source-bind check

**Date:** 2026-10-31
**Scope:** independent, read-only check of the W2 (`PDIPFS K/W2` /
`projects/gt6/cursor/gpb/CursorProject.gpb`) host-vs-PFS selection and of the
candidate `FileObject+0x40` source bind. This check did not edit source or
generated code, did not build, and did not run `gt6.exe`. It created only this
document.
**Inputs:** `work/bin/EMAIN.elf` (static disassembly), `work/analysis/mount_decomp.c`,
`work/size_run.err`, `work/probe_run.err`, `gt6/generated/ppu_recomp_022.cpp`,
`patches/gt6-pfs-source-bind.patch`, `tools/gt6_filedevice_flush_patch.py`,
`tools/post_lift_fixes.py`, `tools/gt6_pfs_cache_probe.py`, the on-disk
`PDIPFS/K/W2`, `PDIPFS/K/IK` pair, and direct reads of `gt6/GT.VOL`.
**Policy:** `third_party/PDTools` and `GTAdhocToolchain` were not read or used.

## 0. Verdict

| # | Question | Verdict | Finding |
|---:|---|---|---|
| 1 | Host-vs-PFS selection independently identified | **PASS (branch) / OPEN (mount key)** | The PFS open path `0x9FDAAC` branches on `[FileInfo+0x3C]` at `0x009FDAE8`: nonzero selects the cache/bdmark branch (W2), zero selects the direct PFS open (K/IK). The W2 branch checks `<base>/PDIPFS_bdmark/<key>` via `0x9FD9B8`, attaches the cache with `0xA422A0`, and configures it with `0xA3EB60`. W2's `HFileReader` is opened through `0x9F4130` on a **host** `FileObject` (`vt=0x1488218`, `dev=0x7005C000`); K/IK reaches the PFS read `0xA0043C` -> `0xA40FBC` at `off=0x8BBC0`. The exact `0x9F8E40` mount object/match key is **not logged**, so the mount-layer key remains open. |
| 2 | The fixer's patch gives W2's HFileReader the PFS FileObject/source state | **FAIL** | The only candidate patch present is `patches/gt6-pfs-source-bind.patch`, the previously rejected `FileObject+0x40` bind. It overwrites the device pointer with a read-state pointer. `FileObject+0x88` is **not** the cache (it is the path buffer written by `0x9F58D8`); the cache lives at `[0xA3DF24(handle)+0x88]`. The patch is inert for W2, or corrupts if it ever fires. |
| 3 | Boot script and ordinary host files preserved | **FAIL as a proof** | The guard uses `FileObject+0x88` as "cache presence"; that field is path/uninitialized data on a host object, not a cache marker. The boot script probably does not fire only because `FileStream+0x4C` is not a PFS state, not because the guard is correct. Ordinary host files are not proven safe. |
| 4 | No cache bytes fabricated | **PASS (narrow)** | The patch writes no cache data and does not decrypt or inflate. It does fabricate a device binding and a size field, so this narrow PASS does not make it a fix. |
| 5 | No vtable patched | **PASS (narrow)** | No vtable entry is modified. The patch nevertheless type-puns `FileObject+0x40`, which is a fabricated object binding rather than a mount/open repair. |
| 6 | `+0x4C` / `+0xC0` side effects correct | **FAIL** | `FileStream+0x4C` is the PFS read state written by `0xA010C0`; `FileObject+0x4C` is inside the subobject constructed at `FileObject+0x44` by `0xEB2C00`. The patch's fallback treats `FileObject+0x4C` as a read state, and its `+0xC0` value is read through the wrong `_c` field. |
| 7 | Raw `ZSize=0xEA57` at GT.VOL `0xD48800`, `.fdupi` 59,991 B, `.fdupm` blocks=8, `0xA40FBC`/`0xA40984` reached | **FAIL (current state)** | GT.VOL slice is correct (`0xEA57`, SHA-256 `2b6153…9008`). Current `K/W2.fdupi` is 59,991 **zero** bytes (SHA-256 `7b5c…8362`), `.fdupm` is `(0xEA57,0,0)` with zero bitmap bits, and W2 has no `0xA40FBC`/`0xA40984`. K/IK is the positive control. |
| 8 | Tree / tool / patch are consistent | **FAIL** | The generated tree contains the old size-only block, while `gt6_filedevice_flush_patch.py --check` and `post_lift_fixes.py` require the new bind; both exit 1. The reference patch describes the bind, not the tree. |

**Bottom line:** the host-vs-PFS split is now clear: W2 takes the
`[FileInfo+0x3C] != 0` cache/bdmark branch and its `HFileReader` receives a
host `FileObject`; K/IK takes the direct PFS branch and reads through
`0xA0043C` -> `0xA40FBC`. The present `FileObject+0x40` bind does not change
that selection. It is not a mount/open fix and must not be landed. The next
work is a read-only mount trace followed by a patch at the branch that returns
the PFS cache owner, not a state pointer.

## 1. How the host-vs-PFS choice is made

### 1.1 The mount walk: `0x9F8E40`

`0x9F8E40` is the VFS open/mount factory. Ghidra (`work/analysis/mount_decomp.c`)
and the disassembly agree:

```text
009F8EEC: lwz   r11, 0x20(r9)      ; mount->match(path)
009F8EF8: mtctr r0
009F8EFC: bctrl
009F8F00: ... if match == 0 -> next node at [node+8]
009F8F1C: lwz   r9, 0x38(r11)      ; mount->open(path, FileInfo)
009F8F2C: bctrl
```

The mount registry/list is at `0x15DE908`; its first node pointer is
`[0x15DE918]`. The walk passes the normalized path in `r4` and the
`FileInfo*` in `r5` (the `r27` register) to the mount's `open`.

The current log does **not** record which mount object matched. It does prove
that the PFS cache setup (`0x9FDAAC` -> `0xA422A0` -> `0xA3EB60`) runs in the
same window as the host open and that the `HFileReader` object is host-backed:

```text
289083: [fileopen] 9F8E40 info=0x402987C4 ... file=0xCFEFE398
289086: [fileopen] 9F4130 this=0xCFEFE338 file=0xCFEFE398 vt=0x01488218 dev=0x7005C000 size=0x0
289100: [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
289106: [pfscache] 0xA42108 attach size=0xEA57 id=0xD48800
289113: [pfscache] open .../PDIPFS/K/W2.fdupi flags=0x42 -> fd=5
289119: [fileread] 9F4AA0 stream=0xCFEFE338 ... file=0xCFEFE398
289120: [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE338 ...
```

The `FileObject` handed to `HFileReader` is `0xCFEFE398`. The cache is
attached to a different PFS object resolved from the handle used by
`0xA422A0` (the log's `A3EB60 file=0x00000100`). These are distinct objects.

### 1.2 The exact branch: `[FileInfo+0x3C]` in `0x9FDAAC`

`0x9FDAAC` is the PFS open path (vtable `0x1488A2C` slot `+0x38`). Whether the
W2 `0x9F8E40` call selected this mount or a host mount is not recorded by the
current probe; the branch below is the PFS-side selector, and the W2/K/IK
object split is observed. The disassembly starts:

```text
009FDAE8: lwz   r26, 0x3C(r5)      ; cache/key descriptor
009FDAF4: lwz   r27, 0x40(r5)      ; path/key argument
009FDAF8: cmpwi cr7, r26, 0
009FDB08: bne   cr7, 0x9FDC8C     ; nonzero -> cache/bdmark branch
```

* **W2:** `[FileInfo+0x3C]` is nonzero (the cache/source descriptor that
  `vtable+0xC0` turns into the volume id/offset). The branch at `0x9FDC8C`
  builds the bdmark path, calls `0x9FD9B8`, attaches the cache, and configures
  it:

```text
009FDB64: lwz   r11, 0(r29)       ; this->vtable
009FDB74: lwz   r9, 0xF4(r11)     ; bdmark/path predicate
009FDB84: bctrl
009FDBA0: bl    0x9FD9B8          ; <base>/PDIPFS_bdmark/<key> exists?
009FDC5C: bl    0xA422A0          ; cache attach
009FDC84: bl    0xA3EB60          ; cache config
```

* **K/IK:** the direct path is selected when `[FileInfo+0x3C] == 0`; it falls
  through to `0x9FDB5C`/`0x9FDD00` -> `0xA00DA8(this, [this+0x1F0], info)`.
  No cache attach is needed because K/IK is already a completed bare PFS file.
  The current probe does not log the real K/IK `FileInfo`, so the zero value
  itself is still to be confirmed by the next trace.

The observable key is the path component:

| Key | Guest path | Observed object |
|---|---|---|
| `K/W2` | `/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS_bdmark/K/W2` (zero-length marker) | host `FileObject`, `vt=0x1488218`, `dev=0x7005C000` |
| `K/IK` | `/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/IK` (572,352-byte bare cache) | PFS `FileObject` -> `0x9F4AA0` -> `0xA0043C` -> `0xA40FBC off=0x8BBC0` |

`0x9FD9B8` is the bdmark path builder/checker: it appends
`PDIPFS_bdmark` (string `0x1097B78`) and the key, then tests existence. It is
the branch that selects the marker object for W2. It is **not** the source
read; the source read is the `0xA00DA8` path with `[this+0x1F0]`.

`0xA41B9C` is a red herring for the FileObject selection. It is the return
address of the `cellFsOpen` call inside `0xA41A90`:

```text
00A41B98: bl    0xF92478          ; cellFsOpen
00A41B9C: mr    r30, r3
```

That is the cache file open (`<key>.fdupm`/`.fdupi`), not the mount open that
returns the `HFileReader`'s `FileObject`.

### 1.3 The read dispatch

`0x9F4AA0` obtains the device with `0x9F3E90`:

```text
009F3EA4: lwz   r3, 0x40(r9)      ; FileObject->device
```

and dispatches slot `+0x90` of that device:

```text
009F4B0C: lwz   r11, 0x90(r9)
009F4B1C: bctrl
```

For the W2 host object, the device is `0x7005C000` and the slot is the host
read default (`0x9F8100`), which is why the log shows `[filehost] A08ED0`.
For a PFS device (`0x1488AB4`), `+0x90` is `0xA0043C` -> `0xA40FBC`.
Setting `FileObject+0xC0` does not change this dispatch.

### 1.4 Proven vs open

| Item | Status | Evidence |
|---|---|---|
| W2 `HFileReader` object is host-backed | **PROVEN** | `size_run.err:289086`, `vt=0x1488218`, `dev=0x7005C000` |
| W2 read dispatches host `0xA08ED0` | **PROVEN** | `size_run.err:289119-289120` |
| K/IK is PFS-backed and reaches `0xA40FBC` | **PROVEN** | `probe_run.err:625-626`, `off=0x8BBC0` |
| Cache is attached to a different object than the `HFileReader` `FileObject` | **PROVEN** | `0xA42108` attach on handle `0x100`; `9F4130 file=0xCFEFE398` |
| PFS-side branch is `[FileInfo+0x3C] != 0` | **PROVEN** | `0x009FDAE8`/`0x009FDB08` |
| W2 `[FileInfo+0x3C] != 0` and K/IK `== 0` | **OPEN** | the branch is proven; the actual `FileInfo` values are not logged |
| W2's `0x9F8E40` matched mount object/vtable/key | **OPEN** | current probe logs `r29` (path), not the mount or `r27` (`FileInfo`) |
| Which object `0x9FDAAC` returns to `0x9F8E40` | **OPEN** | `0xA3EB60 file=0x100` vs `9F4130 file=0xCFEFE398`; they are distinct, but the return linkage needs the trace |

### 1.5 Probe-label correction

The existing `0x9F8E40` probe logs `ctx->gpr[29]` as `info`:

```text
[fileopen] 9F8E40 info=0x402987C4 info+3C=0x40379D90 info+40=0x015DE7C8 file=0xCFEFE398
```

`r29` is the **normalized path pointer**, not the `FileInfo*`. The actual
`FileInfo*` is the `r27` register. Consequently the logged `info+3C` /
`info+40` values are bytes inside/after the path buffer, not `FileInfo+0x3C`
/`+0x40`. The earlier reading of `info+0x40=0x15DE7C8` as a mount/FileInfo
pointer is therefore unproven. This must be corrected before the next trace;
otherwise the W2/K/IK comparison is reading the wrong object.

Recommended log (read-only) at the `0x9F8E40` open return:

```c
fprintf(stderr,
  "[fileopen] 9F8E40 path=0x%08X fileinfo=0x%08X info+18=0x%llX "
  "info+3C=0x%08X info+40=0x%08X file=0x%08X vt=0x%08X dev=0x%08X\n",
  (unsigned)ctx->gpr[29], (unsigned)ctx->gpr[27],
  (unsigned long long)vm_read64(ctx->gpr[27] + 0x18u),
  (unsigned)vm_read32(ctx->gpr[27] + 0x3Cu),
  (unsigned)vm_read32(ctx->gpr[27] + 0x40u),
  (unsigned)ctx->gpr[30],
  (unsigned)vm_read32(ctx->gpr[30]),
  (unsigned)vm_read32(ctx->gpr[30] + 0x40u));
```

Also log the matched mount object and its vtable at the `0x9F8EEC` call, and
the `0x9FDAAC` entry/return (`[info+0x3C]`, `[info+0x40]`, `[this+0x16C]`,
`[this+0x1F0]`) plus the `0x9FD9B8` constructed path. Those values identify
the exact match key; the current logs do not.

## 2. Review of the candidate patch

### 2.1 What is present

No mount/device-selection patch or `docs/analysis/pfs-mount-device-fix.md`
exists at check time (18:05). The only candidate patch is
`patches/gt6-pfs-source-bind.patch`, and
`tools/gt6_filedevice_flush_patch.py` implements the same previously rejected
bind.
The core is:

```c
uint32_t _c  = vm_read32(_f + 0x88u);       /* claimed cache */
if (!_c && _dev) _c = vm_read32(_dev + 0x88u);
uint32_t _st = vm_read32(_s + 0x4Cu);       /* claimed read state */
...
if (_c && _st && _slot == 0x00A0043Cu) {
  uint64_t _z = vm_read64(_c + 0x10u);
  if (_z && _slotc8) {
    if (vm_read64(_f + 0xC0u) == 0) vm_write64(_f + 0xC0u, _z);
    if (vm_read32(_s + 0x4Cu) != _st) vm_write32(_s + 0x4Cu, _st);
    if (_dvt != 0x1488A2Cu && ... ) {
      vm_write32(_f + 0x40u, _st);          /* bind */
    }
  }
}
```

The generated tree does not contain it (the old size-only block is still at
`gt6/generated/ppu_recomp_022.cpp:137371-137391`). Both checks fail:

```text
ppu_recomp_022.cpp: func_009F4130 lacks the cache-backed PFS read-state bind
ppu_recomp_022.cpp: func_009F4130 FileDeviceHost guard missing
  ['Cache-backed host FileObject: bind to the PFS read state.',
   'vm_write32(_f + 0x40u, _st);']
```

### 2.2 Does it deliver the PFS FileObject/source state?

**No.** It does not select or open a PFS object. It writes a pointer into
`FileObject+0x40` and calls that pointer a device. The object it writes is a
read state (`_st`), not the PFS cache owner and not a `FileDevice`.

Three concrete reasons:

1. **`FileObject+0x88` is not the cache.** `0x9F4130` calls `0x9F58D8` with
   `r3=FileObject` and `r4=path`; `0x9F58D8` writes the path's three words to
   `FileObject+0x88`, `+0x8C`, `+0x90` and stores `FileObject+0x88` at `+0x94`:

```text
009F58E0: lwz r0, 0(r4)
009F58E4: stw r0, 0x88(r3)
009F58E8: lwz r9, 4(r4)
009F58EC: stw r9, 0x8C(r3)
009F58F0: lwz r0, 8(r4)
009F58F4: stw r0, 0x90(r3)
009F58FC: stw r4, 0x94(r3)
```

   The actual cache is attached by `0xA422A0`/`0xA42108` to the object
   returned by `0xA3DF24(handle)`: `0xA422A0` stores the new cache at
   `[uVar3+0x88]` and `0xA42108` stores the stored size at `[cache+0x10]`.
   That object is the PFS source (handle `0x100` in the log), not the host
   `FileObject` `0xCFEFE398`. The patch's `_f+0x88` read is at best
   uninitialized at bind time and is overwritten with path bytes immediately
   afterwards; it is not a cache-presence test.

2. **The bind runs before the device is used.** The insertion point is right
   after `vm_write32(FileStream+0x44, FileObject)`. Before `0x9F3F2C` opens
   the device, `0x9F59EC` calls `0x9F86A8(device=[FileObject+0x40],
   FileObject)`; `0x9F86A8` locks `device+0x18` and inserts
   `FileObject+0x44` into `device+0x48`. If `+0x40` is a read state, those
   are arbitrary offsets, not a device mutex/list. Then `0x9F3F2C` loads
   `[device]` and dispatches device vtable `+0x88` (the **open** slot). The
   patch checks only the state's `+0x90` (read) slot, never `+0x88`, so it
   can call an unrelated function or crash.

3. **The patch's own guard cannot distinguish a cache-backed host file.** It
   checks `_slot == 0xA0043C` on `[state]`, but a read state is not a
   `FileDevice`; the check proves only that some object's `+0x90` slot equals
   the PFS read function. It does not prove the object's lifetime, open/close
   slots, or that the host `FileObject` should own it. That is the definition
   of a type-punning bind, not a mount/open fix.

### 2.3 No vtable patch / no cache bytes

The patch does not write a vtable entry and does not write cache bytes. Those
narrow claims are **PASS**. It does write `FileObject+0xC0`, `FileStream+0x4C`
and `FileObject+0x40`; the first is only valid if `_c` is the cache (it is
not), the second can corrupt a host stream, and the third is the fabricated
device bind.

### 2.4 `+0x4C` and `+0xC0` details

* **`FileStream+0x4C` is the read state.** `0xA010C0` writes it at
  `0xA012B0` and `0xA0136C`:

```text
00A012B0: stw r29, 0x4C(r25)
00A0136C: stw r3,  0x4C(r25)
```

  `0xA0043C` reads it at `0xA00464` (`lwz r31,0x4C(r4)`) and uses `+0x10`
  (offset), `+0x18` (remaining) and `+0x1C` (chunk cap). Writing the state
  pointer is meaningful only if it is the state created by the PFS open.

* **`FileObject+0x4C` is not that state.** `0x9F5C94` constructs a subobject
  at `FileObject+0x44` with `0xEB2C00`; `FileObject+0x4C` is inside that
  subobject. The old size-only block's `_st = [FileObject+0x4C]` and the
  new bind's fallback `_alt = [FileObject+0x4C]` both read it as a read-state
  pointer. That is a wild dereference. The old block then writes `_st+0x1C`,
  which is a chunk cap, not the file size.

* **`FileObject+0xC0` is the size read by `0x9F4B5C`** (`ld r26,0xC0(r30)`),
  but it is not the gate for the measured `0x9BB020` -> `0x9F4AA0` path. The
  gate is the device dispatch at `+0x90`. Setting `+0xC0` from the cache
  `stored_size` can be a useful follow-up **after** the correct PFS object is
  selected, but it cannot fix the dispatch by itself.

### 2.5 Boot script and ordinary host files

The boot script `9F4130` object is also a host `FileObject`
(`this=0x7FFD6210 file=0x7FFD6270 vt=0x1488218 dev=0x7005C000 size=0`). Its
`FileStream+0x4C` is not the PFS state, so the bind will probably not fire.
That is incidental safety, not a correct guard. Because `FileObject+0x88` is
path/uninitialized data and `FileStream+0x4C` is a general stream field, the
patch cannot prove that an ordinary host file will not match the
cache/state/slot conditions. The K/IK `+0x40` write is skipped by the PFS
vtable exclusion, but the patch still writes `+0xC0`/`FileStream+0x4C` from
the same unverified `_c`/`_st` values. **Preservation is not established.**

## 3. Success criterion and current state

### 3.1 Correct raw criterion

The TOC row and direct volume read agree:

```text
K/W2  projects/gt6/cursor/gpb/CursorProject.gpb  Compressed
      FileIndex 58, SegIndex 6548, ZSize 0xEA57, Size 0x3A880
      GT.VOL offset 0xD48800
```

```text
offset 0xD48800, length 0xEA57 (59,991)
first 16 27 FD F1 57 AE 6E B5 CA 26 8B 5A 60 93 29 31 C8
last 16  01 8D 7B 06 A2 E2 07 CB F8 FA 76 D9 C2 26 A4 C4
SHA-256  2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

The raw cache is `ZSize`, not the decompressed `Size` (239,744). A 239,744-
byte `.fdupi` would double-decrypt raw plaintext and is wrong.

### 3.2 Current on-disk state

| File | Length | Contents / header |
|---|---:|---|
| `K/W2.fdupi` | 59,991 | all `00`; SHA-256 `7b5c0196f56232a470ea96ea02111fece4ddc209761ecfd4be526df98a478362` |
| `K/W2.fdupm` | 8,212 | `stored_size=0xEA57`, `id=0`, `blocks=0`; bitmap byte 0 `0x00`, 0 bits |
| `K/IK` | 572,352 | SHA-256 `dc4b5fd95fb009e9dd6972253c497b3c551865572fe8d8cc2fc373f9be1c6ac2`; byte-identical to GT.VOL `0x9E1000` |
| `K/IK.fdupm` | 8,212 | `stored_size=0x8BBC0`, `id=0`, `blocks=70`; 70 bitmap bits |

`K/W2` currently fails both content and map criteria. The 59,991-byte length
is only the HLE `cellFsAllocateFileAreaWithoutZeroFill` preallocation; it is
not the cache.

### 3.3 Reached addresses

| Evidence | W2 | K/IK control |
|---|---|---|
| `0x9F4130` open | host `vt=0x1488218 dev=0x7005C000 size=0` at `size_run.err:289086` | PFS-backed; no host line |
| `0x9F4AA0` | reached, `size_run.err:289119`, file `0xCFEFE398` | reached, `probe_run.err:625`, file `0xCFEFEA70` |
| `0xA40FBC` | **absent** | `off=0x8BBC0` at `probe_run.err:626` |
| `0xA40984` | **absent** | not needed on the completed control (bits already set) |
| Host read `0xA08ED0` | present at `size_run.err:289120` | absent |
| `.fdupi` read/write | none; fd 5 is only allocated and closed | source read 572,352 bytes |

The W2 sequence is `9F4AA0` -> host `A08ED0`, not `9F4AA0` -> `0xA0043C` ->
`0xA40FBC`. The K/IK control proves the PFS path itself works.

### 3.4 Criterion table

| Criterion | Verdict | Note |
|---|---|---|
| Raw `ZSize=0xEA57` at GT.VOL `0xD48800` | **PASS** | 59,991 B, SHA `2b6153…9008` |
| `.fdupi` is 59,991 bytes byte-identical to GT.VOL | **FAIL** | length matches, content is all zero |
| `.fdupm` `(0xEA57,0,8)`, bitmap byte 0 `0xFF` | **FAIL** | current `(0xEA57,0,0)`, 0 bits; this is a transient pre-completion state |
| Completed bare `K/W2` with the same bytes and no map | **acceptable final state** | the guest renames `.fdupi` to bare only when `+0x20 == +0x68`; do not require the map after exit |
| `0xA40FBC` reached for W2 | **FAIL** | absent |
| `0xA40984` reached for W2 | **FAIL** | absent |
| No `[filehost] A08ED0` for the W2 read | **FAIL** | present |
| K/IK and boot script preserved | **PASS current / needs A/B after any patch** | IK hash and 70-block map unchanged; boot override line `774` still serves `main.adc` |

### 3.5 Probe gaps

The existing probes are not yet sufficient to identify the mount match:

* `0x9F8E40` logs `r29` (path) as `info`; it must log `r27` (`FileInfo`) and
  the matched mount object/vtable.
* `0x9F4130` logs `vt/dev/size`, but not the path string or `dev_vt`; the
  newer probe in `tools/gt6_pfs_cache_probe.py` has these fields but was not
  in the build that produced `size_run.err`.
* `0x9F4AA0` logs `cache = [FileObject+0x88]`, which is path data on the
  host object, not the cache. It should log `[0xA3DF24(handle)+0x88]` or the
  PFS object, and `[FileStream+0x4C]` state/vtable/slot.
* `0x9FDAAC` is not probed. Add entry/return logging for `[FileInfo+0x3C]`,
  `[FileInfo+0x40]`, `[this+0x16C]`, `[this+0x1F0]`, `0x9FD9B8` path and
  existence, `0xA00DA8` return, and the `0xA422A0` first argument.
* The `0x9F8E40` mount map is a path-keyed map; log the key/object for the
  matching node, not just the final file.

## 4. Safest next step

1. **Do not apply `patches/gt6-pfs-source-bind.patch`** and do not use the
   `FileObject+0x40` write in `tools/gt6_filedevice_flush_patch.py` as the W2
   fix. The tree is currently consistent with the old size-only block, which
   is inert for W2; keep it that way until the mount trace is done. The two
   check tools exit 1 because they require the rejected bind, not because the
   tree regressed.

2. **Run a read-only mount trace first (no behavior change).** With the
   corrected `0x9F8E40`/`0x9FDAAC` probes above, use a 240-300 s run and
   compare W2 with K/IK. Required fields:
   * `0x9F8E40`: path, real `FileInfo` `+0x18/+0x3C/+0x40`, matched mount
     object/vtable, returned object;
   * `0x9FDAAC`: `[FileInfo+0x3C]`, `[FileInfo+0x40]`, `[this+0x16C]`,
     `[this+0x1F0]`, `0x9FD9B8` path/existence, `0xA00DA8` return,
     `0xA422A0` first argument;
   * `0x9F4AA0`: `[FileStream+0x4C]` state/vtable/`+0x90`, and the actual
     cache owner (not `FileObject+0x88`).

3. **Patch the selection, not the object.** The smallest correct change is
   expected to make the W2 cache/bdmark branch return the PFS-backed object
   that owns `[PFS object+0x88]` (the same object `0xA422A0` attaches to), or
   make the `PDIPFS_bdmark` path select that object instead of the host
   marker. Do not overwrite `FileObject+0x40` with a read state; do not use
   `FileObject+0x88` as a cache; do not hardcode `0xEA57` or write cache
   bytes. If the trace shows the host object is produced by a different mount
   match, fix that match/key at `0x9F8E40` instead.

4. **Accept only a guest-produced result.** Verify:
   * `0xA40FBC` with `size=0xEA57`, then `0xA40984` blocks 0..7;
   * `.fdupi` 59,991 bytes byte-identical to GT.VOL `0xD48800` (SHA
     `2b6153…9008`), or bare `K/W2` after the completion rename;
   * `.fdupm` `(0xEA57,0,8)` bitmap `FF` transient, or no map after the bare
     rename;
   * no `[filehost] A08ED0` on the W2 read;
   * boot script still serves `main.adc`; K/IK still 572,352 B / SHA
     `dc4b5f…6ac2`; ordinary host files unchanged.

5. **Treat `tools/gt6_seed_pfs_cache.py` as a fixture, not the fix.** Seeding
   raw GT.VOL slices and zero-length bdmark markers can make a bare cache
   path readable, but it does not prove the guest writer or the mount
   selection. The seeding note itself says the mount/device fix must land
   first for the bdmark cache route.

## 5. Evidence index

| Evidence | Location / value |
|---|---|
| W2 TOC row | `work/gt6_volume_entries.txt:30342`; `work/gt6_pfs_keymap.tsv:30343`; `ZSize=0xEA57`, `Size=0x3A880`, offset `0xD48800` |
| GT.VOL W2 slice | `0xD48800`, 59,991 B, SHA-256 `2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008` |
| W2 open/cache sequence | `work/size_run.err:289083-289130` |
| W2 host read | `work/size_run.err:289119-289120` |
| K/IK positive control | `work/probe_run.err:621-629` (`0xA40FBC off=0x8BBC0`, 572,352-byte read) |
| K/IK cache bytes | 572,352 B, SHA-256 `dc4b5fd95fb009e9dd6972253c497b3c551865572fe8d8cc2fc373f9be1c6ac2`, equal to GT.VOL `0x9E1000` |
| W2 current cache | `.fdupi` 59,991 zero bytes, SHA `7b5c0196…8362`; `.fdupm` `(0xEA57,0,0)`, 0 bits |
| Mount walk | `0x9F8E40`, `0x009F8EEC` match `+0x20`, `0x009F8F1C` open `+0x38`; list `0x15DE908` |
| PFS open branch | `0x9FDAAC`, `0x009FDAE8` `lwz r26,0x3C(r5)`, `0x009FDB08` `bne 0x9FDC8C` |
| Bdmark path check | `0x9FD9B8`, strings `0x1097B70` (`PDIPFS`), `0x1097B78` (`PDIPFS_bdmark`) |
| Cache attach | `0xA422A0` -> `0xA3DF24` -> `[object+0x88]`; `0xA42108` stores `+0x10` size |
| Cache file open | `0xA41A90`, `0x00A41B98` `bl 0xF92478`; return `0xA41B9C` |
| Read dispatch | `0x9F4AA0`, `0x009F4B0C` slot `+0x90`; `0x9F3E90` `[FileObject+0x40]` |
| Size field | `0x9F4B5C`, `0x009F4BAC` `ld r26,0xC0(r30)` |
| Path buffer at `+0x88` | `0x9F58D8` stores path words at `FileObject+0x88/+0x8C/+0x90` |
| Device use before open | `0x9F59EC` -> `0x9F86A8(device, FileObject)`; `0x9F3F2C` device `+0x88` open |
| PFS read state | `0xA010C0` stores `FileStream+0x4C` at `0xA012B0`/`0xA0136C`; `0xA0043C` reads it at `0xA00464` |
| Subobject at `+0x44` | `0x9F5C94` calls `0xEB2C00` with `r3=FileObject+0x44` |
| Candidate bind | `patches/gt6-pfs-source-bind.patch`; `tools/gt6_filedevice_flush_patch.py:81-116` |
| Tree/tool mismatch | `gt6/generated/ppu_recomp_022.cpp:137371-137391` (old block); both checks exit 1 |
| Boot script | `work/size_run.err:774`; host `9F4130` at `776` |
