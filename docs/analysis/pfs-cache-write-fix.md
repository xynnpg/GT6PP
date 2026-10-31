# PDIPFS cache write fix / diagnosis

**Date:** 2026-10-31
**Scope:** `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp`, a read-only probe
patch, and a raw-cache verification tool. No generated file was edited and no
build or `gt6.exe` run was performed by this fix.
**Inputs:** `work/ghidra_pfs.c` (Ghidra 10.4 decompilation), the static
disassembly of `work/bin/EMAIN.elf`, the on-disk `PDIPFS` pairs, and
`work/pfstrace.err` / `work/lab1_final_run.err`.

## 0. Bottom line

| Question | Finding |
|---|---|
| What does `cellFsAllocateFileAreaWithoutZeroFill` (NID `0x7A0329A1`) need to do? | Size the newly opened `<key>.fdupi` to `ZSize`. The old HLE was a no-op. It is now a real `ftruncate`/`_chsize_s` against the guest's open stream. |
| Does that no-op explain `blocks=0`? | **No.** A later `cellFsWrite` would extend the file. The block writer sets the bitmap bit and count only after a successful seek+write; `cellFsAllocateFileAreaWithoutZeroFill` cannot zero that count. |
| Why is the bitmap empty? | Either `cache_write` (`0xA40984`) is never reached, or it is reached and its data-fd write fails. `K/W2` shows the former: `.fdupi` is opened and never read, written or sought, and the thread hits the null virtual call at `0x9F4550`. `K/WO` shows a `.fdupm` bitmap read in tid 33 and a `GT.VOL` 8 KiB read in tid 34. That can be one shared `cache_read` whose page load was done by the other worker, so the decisive check is the new `0xA40984` / `cellFsWrite` probe, not the thread split alone. |
| Is the write missing, buffered, or rejected? | **Missing for K/W2** (the cache read method is never called). For K/WO/6I/JH/7E the source read may have reached the cache, so it is either never entered or the data-fd write failed (closed/reused fd). The HLEs do not reject a valid write; stdio buffering would not leave the in-memory count at 0 (close would flush a nonzero map). The new trace separates these cases. |
| What about `cellFsTruncate` / `cellFsRename` / `cellFsUnlink`? | `cellFsTruncate` (`0xC9DC3AC5`) was unregistered; `cellFsRename` (`0xF12EECC8`) was unregistered and `cellFsUnlink` was a no-op. The completion marker `K/W2` therefore could not be produced by the guest even with a full data file. All three are now real. |
| First success criterion | The cache data must be **`ZSize` = `0xEA57` = 59,991** raw bytes, byte-identical to GT.VOL at `0xD48800`. **239,744 is `Size` (the decompressed read-side view), not a raw cache length.** See section 7. |

## 1. Cache format (verified control)

The 20-byte `.fdupm` header is:

| Offset | Type | K/IK | K/W2 (current) |
|---:|---|---:|---:|
| `+0x00` | u64 BE `stored_size` | `0x8BBC0` | `0xEA57` |
| `+0x08` | u64 BE `id` | `0` | `0` |
| `+0x10` | u32 BE `valid_block_count` | `70` | `0` |
| `+0x14` | 8192-byte bitmap | 70 bits set | all zero |

The data file is `stored_size` bytes of raw GT.VOL source. The completed
`K/IK` pair proves this: 572,352 bytes, SHA-256
`DC4B5FD95FB009E9DD6972253C497B3C551865572FE8D8CC2FC373F9BE1C6AC2`,
byte-identical to the GT.VOL entry. The tool in section 6 reproduces that check
from the volume, not from the old cache.

`K/W2` (`projects/gt6/cursor/gpb/CursorProject.gpb`, FileIndex 58, SegIndex
6548, volume offset `0xD48800`) is compressed: `ZSize=0xEA57` (59,991),
`Size=0x3A880` (239,744). Its raw GT.VOL head is `27 FD F1 57 ...`; the
extracted/decrypted view is 239,744 bytes and starts `33 62 70 67` (`3bpg`).
The cache must store the former; the reader produces the latter.

## 2. Static write path

### 2.1 Attach / object construction

| Address | Role |
|---|---|
| `0x9FDC5C` | `FileDevicePFS` calls `0xA422A0(path, size, id, 0)` |
| `0xA422A0` | cache-manager wrapper, tail-calls `0xA42108` |
| `0xA42108` | allocates 0xF8, stores size `+0x10`, id `+0x18`, source base `+0x50`, `blocks=(size+0x1FFF)>>13` `+0x68`, block buffer `+0x64`, bitmap buffer `+0x74`, path `+0x78` |
| `0xA41EB4` | builds `<key>.fdupm`, stats it, opens read-only flags 2, reads 20-byte header, compares `header.size == obj+0x10` and `header.id == obj+0x18`, stores `header.blocks` at `obj+0x20` |
| `0xA42020` | builds `<key>.fdupi`, opens flags `0x42` (`O_RDWR|O_CREAT`), then calls `0xF924B0` (`cellFsAllocateFileAreaWithoutZeroFill`) with `(path, obj+0x10)` |

Ghidra agrees: `cache_ctor` lines 67-79 load the map and store
`uStack_f0` (header block count) at `param_1+0x20`; `cache_header` line 382
calls `0xA42020` only after a successful `cache_ctor`.

### 2.2 Map initialization vs header write

`0xA41D80` opens the map with flags `0x241`
(`O_WRONLY|O_CREAT|O_TRUNC`), then writes
`align_up(block_count + 7, 0x2000) + 0x14` bytes from a 0x100-byte zero buffer
in chunks. This is only the zeroed header/bitmap area. It does **not** write
the size/id header. The header is written on close:

```
0xA40E20  flush dirty bitmap page (0xA40A7C)
0xA40E4C  lseek(map_fd, 0, SEEK_SET)
0xA40E64  write(map_fd, cache+0x10, 0x14)   ; size, id, block_count
```

Consequences:

* A `.fdupm` that has `stored_size=0xEA57` and `blocks=0` proves **close ran**
  and the in-memory `cache+0x20` was still 0. It does not prove the constructor
  wrote a header or that the map file was not created.
* The block count is incremented only inside the successful write branch
  (`0xA40A4C..0xA40A58`), so `blocks=0` means no successful `cache_write`.

### 2.3 `cache_read` → `cache_write`

`0xA40FBC` computes `block=(filepos-cache_base)>>13`, page `block>>13`, loads
the bitmap page with `0xA40C08`, tests bit `1<<(block&7)`, and on a miss:

```
0xA411D8  source_fd = [file+0xA0]
0xA411F0  lseek(source_fd, cache_base + block*0x2000, SEEK_SET)
0xA4120C  read(source_fd, [cache+0x64], 0x2000, &nread)
0xA41228  cache_write(cache, block, block&0x1FFF, nread)
```

Ghidra `cache_read` lines 264-274 is the same sequence. The source fd is the
GT.VOL handle; the destination is the cache block buffer.

`0xA40984` (Ghidra `cache_write`, lines 113-139) has exactly four gates:

```c
cache->last_error = 0;
if (block * 0x2000 >= cache->size) return;          // 0xA409A8 / 0xA40A60
if (cache->last_error != 0)        return;          // 0xA409E8
if (lseek(cache->fd, block*0x2000) != 0) return;    // 0xA409F8
if (write(cache->fd, cache->buf, len) != 0) return; // 0xA40A18
bitmap[block>>3] |= 1 << (block&7);                 // 0xA40A40
cache->dirty = 1;                                   // 0xA40A4C
cache->blocks++;                                    // 0xA40A54
```

`cache->size` is the `ZSize` stored at `+0x10` by attach. For K/W2 block 0,
`0 < 0xEA57`, so a reached `cache_write` would write. The map and count are
updated only after all four gates pass.

### 2.4 Helper map

| Address | Signature / role | Downstream |
|---|---|---|
| `0xA40768` | `write_exact(fd, buf, len, &written)`; rejects short writes | `0xF92788` → NID `0xECDCF2AB` `cellFsWrite` |
| `0xA4086C` | `lseek(fd, off, whence, &pos)` | `0xF92638` → NID `0xA397D042` `cellFsLseek` |
| `0xA40B04` | `read_exact(fd, buf, len, &read)` | `0xF92408` → NID `0x4D5FF8E2` `cellFsRead` |
| `0xA40C90` | open wrapper: `fd_out`, path, flags | `0xF92478` → NID `0x718BF5F8` `cellFsOpen` |
| `0xA40D34` | close wrapper | `0xF92398` → NID `0x2CB51F0D` `cellFsClose` |
| `0xA4FDBC` | zero-fill 0x100-byte chunk | local memset |
| `0xA421CC` | not a function: field-init address inside `0xA42108` | block count/dirty/bitmap/path setup |

## 3. Why the measured runs have `blocks=0`

### 3.1 K/W2

`work/pfstrace.err`:

```
32424 open .../PDIPFS_bdmark/K/W2      -> fd 3
32429 open .../PDIPFS/K/W2.fdupm      -> fd 4
32431 open .../PDIPFS/K/W2.fdupi      -> fd 5
```

There is **no read, write, lseek, stat or close** on fd 5 afterwards. The
thread immediately hits the null indirect call at `0x9F4550`
(`lwz r11,0x8C(vtable); lwz r0,0(r11); mtctr r0`; `r11 == 0x00000004`,
`opd[0] == 0`). The call is in `func_009F44D8`, which resolves the device with
`0x9F3E90` and calls a virtual method at `+0x8C`. The cache read method
(`0xA40FBC`) is never reached.

This is upstream of cellFs. No HLE can make `cache_write` run if the guest
never calls `cache_read`.

### 3.2 K/WO baseline

`work/lab1_final_run.err:258385..258440`:

```
tid 33: read .fdupm 8192       (bitmap)
tid 33: exit
tid 34: read GT.VOL 8192 @ 0xAAE000
tid 34: exit
```

`cache_read` loads the bitmap and reads the source **in the same call**, but
the cache object is shared by the file handle. If tid 33 already loaded page 0
and set `[cache+0x70] = 0`, tid 34's `cache_read` skips `0xA40C08` and goes
straight to the source read. The thread split alone therefore does **not**
disprove that the GT.VOL read is the cache-miss fill.

If it is the cache-miss fill, the next suspect is the data fd: `cache_write`
gates on `[cache+0] == 0`, then `lseek(fd, block*0x2000)` and
`write(fd, buf, len)`. A closed/reused fd returns EBADF/EIO, the bit/count stay
0, and the close-time header still carries the size. The new trace logs
`[pfscache] write ... -> EBADF (closed?)` and every cache `close`, so this is
directly falsifiable. If the GT.VOL read is instead the PFS file/decrypt path,
the probe's `0xA40FBC` line will be absent.

### 3.3 What the HLE no-op did and did not cause

* `cellFsAllocateFileAreaWithoutZeroFill` no-op left `.fdupi` at 0 bytes. A
  later `cellFsWrite` at block 0 would still extend it, so this is not the
  cause of `blocks=0`.
* `cellFsTruncate` unregistered: only relevant if the guest chose that import;
  GT6's cache constructor uses `0x7A0329A1`, not `0xC9DC3AC5`.
* `cellFsRename` unregistered / `cellFsUnlink` no-op: these break the
  **completion** step (`0xA3F6B4`, `0xF927F8`), not the block publication.
* Buffered `fwrite`: a crash can lose bytes, but the guest's in-memory bitmap
  and count are set synchronously after `cellFsWrite` returns. A nonzero count
  would have been flushed by `0xA40DD4`; the observed count is 0. So buffering
  is not the primary cause either.

**Verdict:** for K/W2 the write is missing at the guest read layer: the cache
read method is never called. For the earlier K/WO/JH/7E/6I runs the source read
may have been the cache-miss fill, so the open questions are (a) was
`0xA40984` entered, and (b) did its `cellFsWrite` return EIO/EBADF because the
data fd was already closed or was still 0 bytes? The probe distinguishes them.
In neither case can the missing allocate HLE set the in-memory count to 0; it
only leaves the host file unsized. The fixes below make the HLE faithful and
make a future successful write durable; they do not pretend to repair the null
virtual dispatch.

## 4. HLE changes (applied)

File: `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp`
Patch record: `patches/ps3recomp-cellfs-pdipfs.patch`

| Function | NID | Old behavior | New behavior |
|---|---:|---|---|
| `cellFsAllocateFileAreaWithoutZeroFill(path,size)` | `0x7A0329A1` (`0xF924B0`) | `return CELL_OK` | `ftruncate`/`_chsize_s` to `size`, using the guest's open `FILE*` when present; creates parents; `CELL_OK`/`CELL_FS_ENOENT` |
| `cellFsTruncate(path,size)` | `0xC9DC3AC5` (`0xF92718`) | unregistered | same path truncate |
| `cellFsFtruncate(fd,size)` | `0x0E2939E5` | unregistered | `fflush` + `_chsize_s`/`ftruncate` on the fd |
| `cellFsRename(from,to)` | `0xF12EECC8` (`0xF927F8`) | unregistered | host `rename`, creates destination parent, replaces a stale destination |
| `cellFsUnlink(path)` | `0x7F4677A8` | no-op | real `remove`; missing file is benign |
| `cellFsFsync(fd)` | `0x967A162B` | `fflush` | `fflush` + `_commit`/`fsync` |
| `cellFsWrite(fd,...)` | `0xECDCF2AB` | buffered `fwrite` | for `<key>.fdupi` / `.fdupm` additionally `fflush` (and optional `GT6_PFS_CACHE_FSYNC` commit); logs short writes |
| `cellFsClose(fd)` | `0x2CB51F0D` | `fclose` | unchanged flush semantics, plus cache size trace |

Only the first four NIDs were unregistered/missing. The rest were already
registered; the flush/trace changes are hardening, not NID fixes.

**Expected intermediate state:** with a real allocate, a fresh `.fdupi` becomes
`ZSize` bytes of zeroes (preallocated, no source data). The map still says
`blocks=0`. That is *not* success. Success requires the data bytes to be raw
GT.VOL bytes and the bitmap to cover them, either through the guest writer or
through the explicit warm tool in section 6.2. Size alone is not a valid check.

Registration is by literal import NID:

```c
ps3_hle_register_ctx(0x7A0329A1u, "cellFsAllocateFileAreaWithoutZeroFill",
                     cellFsAllocateFileAreaWithoutZeroFill);
ps3_hle_register_ctx(0xC9DC3AC5u, "cellFsTruncate",  cellFsTruncate);
ps3_hle_register_ctx(0x0E2939E5u, "cellFsFtruncate", cellFsFtruncate);
ps3_hle_register_ctx(0xF12EECC8u, "cellFsRename",    cellFsRename);
```

`ps3_compute_nid()` of these friendly names produces the same values today;
the literal form guards against a name/hash change.

No `ppu_sysprx.cpp` change was required; `ppu_fs_register()` owns this table.

## 5. Probe

Two levels, both env-gated:

1. **cellFs level (already applied).** `GT6_PFS_CACHE_TRACE=1` logs every
   open/close/read/write/lseek/stat/fstat/truncate/allocate/rename/unlink on a
   path containing `PDIPFS` or ending `.fdupi`/`.fdupm`, with the guest return
   address and the raw size.

2. **Guest address level (patch proposal).**
   `python tools/gt6_pfs_cache_probe.py` emits
   `patches/gt6-pfs-cache-probe.patch` (read-only `fprintf`s, generated tree
   untouched) at:
   `0x9FDC5C`, `0xA42108`, `0xA41FEC`, `0xA420AC`, `0xA40FBC`, `0xA40984`.

   The key line to look for is:

   ```
   [pfscache] 0xA40984 write cache=0x........ size=0xEA57 block=0 off=0 len=8192
   [pfscache] write fd=5 '...K/W2.fdupi' nbytes=8192 -> 8192 lr=0x00A4122C
   ```

   Interpretation:

   | Probe result | Meaning |
   |---|---|
   | no `0xA40FBC` | file read path does not use the cache (K/W2: null virtual at `0x9F4550`) |
   | `0xA40FBC` but no `0xA40984` | miss branch not taken (bit already set) or source lseek/read failed |
   | `0xA40984` with `size=0` | attach passed `ZSize=0`; metadata/attach bug, not the writer |
   | `0xA40984` but no `[pfscache] write` | `cache+0` already held an error, or the data lseek failed |
   | `[pfscache] write ... EBADF` | data fd was closed/reused before the block write |
   | `write ... nbytes=8192 -> 0` / `SHORT` | host write failed; inspect the host path/permissions |
   | `write ... -> 8192` but map stays 0 | bitmap dirty flush / close ordering, not the data write |

## 6. Verification

### 6.1 Static / no run

The tool reads the keymap, the raw GT.VOL slice, and the cache pair; it does
not decrypt or inflate. It accepts either `<key>.fdupi` (building) or `<key>`
(after the completion rename).

```powershell
# K/IK control: must be byte-identical and map-covered
python tools\gt6_pfs_cache_warm.py --key K/IK --check

# K/W2 current state: reports 0-byte data, 0-block map, and the raw/logical sizes
python tools\gt6_pfs_cache_warm.py --key K/W2
```

Expected K/IK:

```
PASS        data is byte-identical to the GT.VOL slice
PASS        map covers 70 blocks (ZSize 0x8BBC0, id 0)
```

Expected K/W2 before the fix:

```
data        ...K/W2.fdupi (0 bytes)
FAIL        length 0, want 59991
FAIL        map blocks 0, want 8
```

### 6.2 Pre-seed the raw cache, then run the owner build

This validates the read side and the completion rename independently of the
broken virtual dispatch. The tool writes exactly the bytes the guest writer
would have copied:

```powershell
python tools\gt6_pfs_cache_warm.py --key K/W2 --write
$env:GT6_PFS_CACHE_TRACE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\w2_cache_run.log
python tools\gt6_pfs_cache_warm.py --key K/W2 --check
```

Expected after a successful run:

* `K/W2.fdupi` is 59,991 bytes and byte-identical to GT.VOL at `0xD48800`;
* `K/W2.fdupm` has `stored_size=0xEA57`, `id=0`, `blocks=8`,
  bitmap byte 0 = `0xFF`;
* the guest close sees `+0x20 == +0x68`, calls `0xA3F6B4` → `0xF927F8`
  (`cellFsRename`) and renames `.fdupi` to `K/W2`;
* `--check` accepts the completed bare `K/W2` file.

### 6.3 Prove the guest writer itself

Remove the pre-seed (or use a fresh key), apply
`patches/gt6-pfs-cache-probe.patch`, and run with
`GT6_PFS_CACHE_TRACE=1`. The writer is proven only when all of these appear:

1. `0xA40FBC read ... off=0x0 ...`,
2. `0xA40984 write ... size=0xEA57 block=0 ...`,
3. `[pfscache] write fd=5 ... nbytes=8192 -> 8192`,
4. the map block count grows to 8 and the bitmap is `FF`.

If step 1 is absent, inspect the null indirect call at `0x9F4550`
(`0x9F44D8` virtual `+0x8C`); that is the current K/W2 blocker. If step 2 is
absent but step 1 is present, the cache miss branch was not taken (bitmap bit
already set) or the source lseek/read failed.

## 7. The 239,744-byte criterion

The task text says the first success criterion is a 239,744-byte `.fdupi`
byte-identical to the GT.VOL entry. That number is `Size=0x3A880`, the
**decompressed logical length**. The cache code writes `ZSize=0xEA57`
(59,991) raw bytes:

* `cache_write` clamps to `cache->size`, which is the `ZSize` stored at
  `+0x10`; the `.fdupm` header on disk is `0xEA57`.
* The source read in `cache_read` is a raw 8 KiB `cellFsRead` from GT.VOL; no
  cipher or inflate call exists in `0xA40984` or `0xA40FBC`.
* The completed K/IK control is byte-identical to GT.VOL (uncompressed, so
  `ZSize == Size`); the compressed PD evidence shows the pre-placed plaintext
  being overwritten with raw GT.VOL prefix bytes.

Therefore the correct raw-cache check is:

```
K/W2.fdupi length == 0xEA57 (59,991)
K/W2.fdupi == GT.VOL[0xD48800 .. +0xEA57]
SHA-256 2B6153BACD5E833E9E3BB5B5089552AE3BF973A67FEBA599EC6FCD21DB709008
```

The 239,744-byte check belongs to the **read-side output**:

```
work/gt6_vol/projects/gt6/cursor/gpb/CursorProject.gpb == 239,744 bytes
```

A 239,744-byte `.fdupi` would make the guest decrypt/inflate raw plaintext a
second time and must not be produced.

## 8. Exact addresses / NIDs index

| Item | Value |
|---|---|
| `cellFsOpen` | `0x718BF5F8` (stub `0xF92478`) |
| `cellFsClose` | `0x2CB51F0D` (stub `0xF92398`) |
| `cellFsRead` | `0x4D5FF8E2` (stub `0xF92408`) |
| `cellFsWrite` | `0xECDCF2AB` (stub `0xF92788`) |
| `cellFsLseek` | `0xA397D042` (stub `0xF92638`) |
| `cellFsStat` | `0x7DE6DCED` (stub `0xF924E8`) |
| `cellFsFstat` | `0xEF3EFA34` (stub `0xF927C0`) |
| `cellFsAllocateFileAreaWithoutZeroFill` | `0x7A0329A1` (stub `0xF924B0`) |
| `cellFsTruncate` | `0xC9DC3AC5` (stub `0xF92718`) |
| `cellFsFtruncate` | `0x0E2939E5` |
| `cellFsRename` | `0xF12EECC8` (stub `0xF927F8`) |
| `cellFsUnlink` | `0x7F4677A8` (stub `0xF92520`) |
| Cache attach caller | `0x9FDC5C` → `0xA422A0` → `0xA42108` |
| Map load | `0xA41EB4` |
| Map init (zero fill) | `0xA41D80` |
| Data create + allocate | `0xA42020`, call at `0xA420A8` |
| Bitmap page load | `0xA40C08` |
| PFS cache read | `0xA40FBC` |
| Bit test / miss | `0xA411C4` / `0xA411D8` |
| Writer call | `0xA41228` → `0xA40984` |
| Writer gates | `0xA409A8`, `0xA409E8`, `0xA409F8`, `0xA40A18` |
| Bit / dirty / count | `0xA40A40`, `0xA40A4C`, `0xA40A54` |
| Cache close | `0xA40DD4` |
| Header write | `0xA40E4C..0xA40E64` |
| Completion rename helper | `0xA3F6B4`, `0xA3F728` |
| Null virtual read | `0x9F4550` (`0x9F44D8+0x78`, slot `+0x8C`) |
| PFS cipher / gate | `0x9FF530`, `0x9FF584`/`0x9FF5A0` |

## 9. Patch / diff

Applied change record: `patches/ps3recomp-cellfs-pdipfs.patch` (generated from
the `third_party/ps3recomp` git checkout; the checkout is a separate repo and
is gitignored by the GT6PP tree). Core registration hunk:

```diff
-    ps3_hle_register_ctx(ps3_compute_nid("cellFsAllocateFileAreaWithoutZeroFill"),
-                         "cellFsAllocateFileAreaWithoutZeroFill", cellFsAllocateFileAreaWithoutZeroFill);
+    ps3_hle_register_ctx(0x7A0329A1u, "cellFsAllocateFileAreaWithoutZeroFill",
+                         cellFsAllocateFileAreaWithoutZeroFill);
+    ps3_hle_register_ctx(0xC9DC3AC5u, "cellFsTruncate",  cellFsTruncate);
+    ps3_hle_register_ctx(0x0E2939E5u, "cellFsFtruncate", cellFsFtruncate);
+    ps3_hle_register_ctx(0xF12EECC8u, "cellFsRename",    cellFsRename);
```

The full 257-line diff includes the path truncate helper, the rename/unlink
implementations, the cache-path flush, and the `GT6_PFS_CACHE_TRACE` logs.

Probe proposal: `patches/gt6-pfs-cache-probe.patch`, generated by
`tools/gt6_pfs_cache_probe.py`.

Verification tool: `tools/gt6_pfs_cache_warm.py`.

## 10. Remaining blocker

Fixing the cellFs HLEs does not make `blocks=0` disappear by itself. The
measured K/W2 sequence ends in the null virtual read at `0x9F4550`; K/WO's
cache is also not reached by the observed GT.VOL read. The next code-level
target is the `0x9F44D8` / `0x9F3E90` virtual dispatch and the object whose
vtable slot `+0x8C` contains `0x00000004`. Until that read path calls
`0xA40FBC`, the cache writer is dead code for these keys.

The HLE fixes are still required for the path to work once the dispatch is
fixed: a real `cellFsAllocateFileAreaWithoutZeroFill` sizes `.fdupi`, the cache
path flush makes block writes visible before the completion marker, and real
`cellFsRename`/`cellFsUnlink` are needed for `K/W2` to replace `.fdupi`.
