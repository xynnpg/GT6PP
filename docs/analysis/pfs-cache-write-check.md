# PDIPFS `K/W2` cache write - independent check

**Date:** 2026-10-31
**Checker scope:** read-only. This check did not edit the fixer's source, did not
build, and did not run `gt6.exe`. Evidence is the checked-in fixer diff
(`third_party/ps3recomp/runtime/ppu/ppu_fs.cpp`, timestamp 16:27), the fixer
report (`docs/analysis/pfs-cache-write-fix.md`, 16:27), static disassembly of
`work/bin/EMAIN.elf`, `work/pfstrace.err` / `work/lab1_final_run.err`, the
on-disk cache pairs, and direct reads of `gt6/GT.VOL`.
**Policy:** `third_party/PDTools` was not read or used. The GT6 cipher/inflate
cross-check below used the project's own `tools/GTToolsSharp/win-x64/GTToolsSharp.exe`.

## 0. Verdict

| # | Claim to check | Verdict | Finding |
|---:|---|---|---|
| 1 | `cellFsAllocateFileAreaWithoutZeroFill` (NID `0x7A0329A1`, stub `0xF924B0`) is a no-op in `ppu_fs.cpp` | **PASS** | The pre-fix source was `static void ...(ppu_context*) { ctx->gpr[3] = CELL_OK; }`; the fixer has now replaced it with a real truncate. Import NID was independently confirmed from `EMAIN.imports.json` and the PS3 NID hash. |
| 2 | That no-op is required for `.fdupi` to receive bytes / is upstream of `blocks=0` | **FAIL** | It is a size operation, not the block writer. `0xA40984` writes blocks and increments the count; it has exactly one caller, `0xA40FBC`, which runs only on a PFS cache read miss. For `K/W2` the log shows no source read and the null dispatch occurs before any block write. Before the new allocate `.fdupi` stayed 0; after it `.fdupi` is `ZSize` zeros; in both cases `blocks=0`, proving no successful write. A later `cellFsWrite` would extend the file even with the old no-op. |
| 3 | `cellFsTruncate` (NID `0xC9DC3AC5`, stub `0xF92718`) is unregistered | **FAIL as stated** | It is not in `ppu_fs_register()`, but it *is* registered in the generated legacy NID table (`gt6/src/gen/ppu_hle_nids.cpp:1391`) to the `libs/filesystem/cellFs.c` handler. GT6 never calls it in the measured runs. The fixer's new context handler is still a valid cleanup, not the missing piece. |
| 4 | The cache write is guest-driven | **PASS** | `0xA40984` is called only from `0xA40FBC` (`0xA41228`); `0xA40FBC` is the PFS read/miss path. Nothing in the HLEs writes block data on its own. |
| 5 | `blocks=0` is the header logic at `0xA421CC..0xA421DC` | **PASS with correction** | `0xA421CC` computes the **total** block count at object `+0x68`. The **published** count at `+0x20` is initialized to 0 and is incremented only by a successful `0xA40984` write. The on-disk header's `blocks` field is written on close from `+0x20`, so `blocks=0` means "no successful block write", not a bad total calculation. |
| 6 | The first success criterion is a **239,744-byte** `.fdupi` equal to GT.VOL | **FAIL as worded** | 239,744 (`Size=0x3A880`) is the decompressed read-side view. The raw cache is `ZSize=0xEA57` = **59,991 bytes**, at GT.VOL `0xD48800`, SHA-256 `2b6153ba...9008`. A 239,744-byte `.fdupi` would be wrong. |
| 7 | The fixer's HLE change is a correct fidelity/diagnostic improvement | **PASS (NID/size/flush) / FAIL (rename safety)** | NIDs, size, raw-byte preservation, cache-path flush, and the primary VFS path are right; the 16:41 run proves the sizing path. But `cellFsRename` remove-then-rename can replace a completed bare cache with a zero `.fdupi`, `cellFsTruncate` creates missing files, `cellFsUnlink` can report success without deleting, and the warm tool has false PASS/FAIL modes. |
| 8 | The fixer's change alone makes `K/W2` cache byte-identical to GT.VOL | **FAIL** | The source is 16:27 and the binary was rebuilt at 16:40; a run at 16:41 used it. `K/W2.fdupi` is now 59,991 bytes but **all zero** (SHA `7b5c01...8362`), `.fdupm` still `blocks=0`, and the `0x9F44D8` null call / `HOTREAD8` spin persists. The allocate truncate did exactly what the code says: it sized the file without writing a block. |
| 9 | K/IK and the boot script survive the change | **PASS in the 16:41 run / one risk remains** | The 16:41 run left bare `K/IK` unchanged (572,352 B, SHA `dc4b5f...6ac2`), so the completed-cache reopen did not fire this time. The risk remains if the cache manager ever opens a completed pair: `0xA42020` creates a zero `.fdupi`, the new allocate sizes it, and the new rename removes the bare `K/IK` before replacing it. Real `cellFsUnlink` may delete `K/IK.fdupm`. The boot-script override is unaffected, but a boot A/B is still required. |

**Bottom line:** the no-op claim is real, but it is not the missing block
publisher. `K/W2` has a guest-side read-path failure: the cache data file is
opened and the thread then hits a null virtual dispatch at `0x9F44D8` /
`0x9F4550` before any logged source read. The 16:41 run with the rebuilt binary
confirms the consequence: `K/W2.fdupi` is 59,991 zero bytes, `.fdupm` is still
`blocks=0`, and the null call/`HOTREAD8` persists. The fixer's HLE/trace work
is useful and mostly faithful, but it cannot make the cache byte-identical by
itself. The correct raw-cache target is 59,991 bytes, not 239,744. Before
landing the new rename, A/B the completed `K/IK` control: the new
remove-then-rename can replace its valid bare file with a zero-filled `.fdupi`
if the completed pair is reopened.

---

## 1. NID and real-ABI verification

### 1.1 Stub -> NID

`work/analysis/emain/EMAIN.imports.json` maps the import stubs independently:

```text
stub 0xF924B0 -> sys_fs NID 0x7A0329A1
stub 0xF92718 -> sys_fs NID 0xC9DC3AC5
stub 0xF92520 -> sys_fs NID 0x7F4677A8 (cellFsUnlink)
stub 0xF927F8 -> sys_fs NID 0xF12EECC8 (cellFsRename)
```

PS3 NID = first four bytes of `SHA-1(name + 67 59 65 99 04 25 04 90 56 64 27 49 94 89 74 1A)`, little-endian:

```text
cellFsAllocateFileAreaWithoutZeroFill -> 0x7A0329A1
cellFsTruncate                        -> 0xC9DC3AC5
cellFsRename                          -> 0xF12EECC8
cellFsUnlink                          -> 0x7F4677A8
```

The cache constructor call is `0xA420A4: mr r3,r30` / `0xA420A8: bl 0xF924B0`
with `0xA42098: ld r29,0x10(r27)` and `0xA420A0: mr r4,r29`; i.e.
`allocate(path, obj+0x10 = ZSize)`. This is independently confirmed.

### 1.2 Real semantics

`cellFsAllocateFileAreaWithoutZeroFill(path, size)` is an **allocation/size**
call. RPCS3 implements it through `sys_fs_fcntl` op `0xE0000017`, which calls
`sys_fs_truncate(path, size)` (current RPCS3 `sys_fs.cpp`, checked 2026-10-31).
It therefore does have the side effect of setting the file size. The old
`ppu_fs.cpp` no-op was a fidelity bug.

It is **not** the cache block writer. On PS3 and in the guest, writes go through
`cellFsWrite`; `0xA40984` is the only code that increments the cache's published
block count. The no-op only left `.fdupi` unsized; a subsequent write at offset
0 would still extend it. So the no-op cannot leave `blocks=0`.

### 1.3 Registration correction

The checker report says `cellFsTruncate` was "unregistered", and the fixer
report says both `cellFsTruncate` and `cellFsRename` were. That is only true of
`ppu_fs_register()`'s context table. The generated table
`gt6/src/gen/ppu_hle_nids.cpp` registers:

```text
line 1391  cellFsTruncate  0xC9DC3AC5 -> libs/filesystem/cellFs.c:cellFsTruncate
line 1392  cellFsFtruncate 0x0E2939E5 -> libs/filesystem/cellFs.c:cellFsFtruncate
line 1400  cellFsRename    0xF12EECC8 -> libs/filesystem/cellFs.c:cellFsRename
line 1401  cellFsUnlink    0x7F4677A8 -> libs/filesystem/cellFs.c:cellFsUnlink
```

`main.cpp` calls `ppu_hle_register_all()` before `ppu_fs_register()`, and
`ps3_hle_call` checks the context table first. Therefore:

* `cellFsTruncate` and `cellFsRename` had legacy handlers. The completed `K/IK`
  control proves rename worked: its bare `K/IK` exists and its `.fdupi` does
  not; `pfs-wo-check.md` §2.2 quotes the `[cellFs] Rename` log from the libs
  handler. GT6 does not call truncate in the measured runs, so its legacy
  handler is not exercised.
* `cellFsFtruncate` also had a legacy handler (GT6 does not import the NID, so
  it is dead for this title).
* `cellFsUnlink` had a legacy handler, but `ppu_fs.cpp`'s context registration
  (`ps3_hle_register_ctx("cellFsUnlink", ...)`) shadowed it with a no-op. That
  is the one completion HLE that was genuinely ineffective.

Consequence: the `K/W2` completion marker (`rename .fdupi -> K/W2`) **could**
have been produced if all blocks had been written; it was not blocked by a
missing rename HLE. The missing piece is the data/bitmap, not registration.
The fixer's new context handlers are still reasonable (they use the primary
`ppu_fs` VFS and handle a stale Windows destination), but the report's
"completion could not be produced" claim is too strong.

---

## 2. Exact guest cache write path

All addresses are guest EAs in `work/bin/EMAIN.elf`.

| Address | Verified role | Evidence |
|---|---|---|
| `0xA42108` | Cache object constructor: size `+0x10`, id `+0x18`, published block count `+0x20 = 0`, total blocks `+0x68 = (size+0x1FFF)>>13` | `0xA42198: stw r29,0x20(r11)` (r29=0); `0xA421C4: std r23,0x10`; `0xA421C8: stw r3,0x64`; `0xA421CC..D0: addi/rldicl`; `0xA421DC: stw r0,0x68` |
| `0xA41D80` | Create `<key>.fdupm` flags `0x241` (`O_WRONLY|O_CREAT|O_TRUNC`), write `align_up(ceil(blocks/8),0x2000)+0x14` **zero** bytes | `0xA41DCC..DF4` computes size, `0xA41DF8` `memset(buf,0,0x100)`, `0xA41E40` write loop |
| `0xA41EB4` | Load `<key>.fdupm`: stat, open flags `2`, read 0x14 header, compare size/id, store header `blocks` at `+0x20` | `0xA41F18` stat, `0xA41F50` open, `0xA41F6C: li r5,0x14`, `0xA41F9C..B8` compare, `0xA41FEC..F0` store |
| `0xA40DD4` | Cache close/destructor: flush dirty bitmap page, seek map fd +8 to 0, write 0x14 header from `+0x10`, compare `+0x20` vs `+0x68`, then unlink/rename on completion | `0xA40E2C..64` header write; `0xA40EBC..C8` count compare; `0xA40EEC..F50` unlink `.fdupm`; `0xA40F18..F50` rename `.fdupi` -> bare |
| `0xA42020` | Create `<key>.fdupi` flags `0x42` (`O_RDWR|O_CREAT`), then `allocate(path, [obj+0x10])` | `0xA42080` open, `0xA42098` size, `0xA420A8` `0xF924B0` |
| `0xA40FBC` | PFS cache read: compute block/page, load bitmap, test bit; on miss seek/read the source and call `0xA40984` | `0xA411C4..D4` bit test, `0xA411E8..120C` source lseek/read, `0xA41228` writer call |
| `0xA40984` | Write one raw block to `.fdupi`, set bitmap bit, set dirty, increment published count | `0xA409A8` size gate, `0xA409F8` lseek, `0xA40A18` write, `0xA40A40` bit, `0xA40A4C` dirty, `0xA40A54` count |
| `0xA3F4B8` | Unlink helper | `0xA3F534: bl 0xF92520` (`cellFsUnlink`) |
| `0xA3F6B4` | Rename helper | `0xA3F728: bl 0xF927F8` (`cellFsRename`) |

Call-graph confirmation (`tools/gt6_find_calls.py`):

```text
calls to 0xA40984: 1   (0xA41228, inside 0xA40FBC)
calls to 0xA40FBC: 6   (PFS read/device paths: 0xA0043C, 0xA0186C,
                        0xA030B8, 0xA0AF18, 0xA3D380, 0xA3DA68)
calls to 0xA41D80: 2   (both inside 0xA41EB4)
calls to 0xA41EB4: 1   (inside 0xA42108)
calls to 0xA42020: 1   (inside 0xA42108)
```

There is no other writer. If `0xA40FBC` is not entered, `0xA40984` cannot run.

### 2.1 `blocks=0` specifically

`0xA421CC..0xA421DC` computes **`+0x68`**, the total/desired block count. The
header's `blocks` field is object `+0x20`:

* initialized to 0 at `0xA42198`;
* loaded from the existing `.fdupm` header at `0xA41FF0`;
* incremented only after a successful write at `0xA40A54`;
* written to the header on close from `+0x10` at `0xA40E50..64`.

So the checker report's wording ("the cache constructor writes the stored_size
header ... computes blocks ... no source block is written") is right in
substance but wrong about the writer: `0xA41D80` writes a **zeroed**
header/bitmap; the size/id/count header is written on close. A `.fdupm` with
`stored_size=0xEA57`, `blocks=0` therefore proves a close wrote the header at
some point (not necessarily this run) and the in-memory count was still 0 at
that close. It does not prove a source block was ever attempted.

---

## 3. Why `K/W2` has no data

### 3.1 Measured sequence

`work/pfstrace.err:32424..32455`:

```text
32424 open .../PDIPFS_bdmark/K/W2      -> fd 3
32427 open .../GT.VOL                 -> fd 3
32429 open .../PDIPFS/K/W2.fdupm      -> fd 4
32431 open .../PDIPFS/K/W2.fdupi      -> fd 5
32440 [null-call] ... near lr=0x009F4554 tid=5 r3=0x70 r9=0 r11=0 r12=4
32455 [GSTACK:nc] ... func_009F44D8+0x44 func_00A08ADC+0x5C ...
```

There is no logged `[fs] read` of GT.VOL for `K/W2` after the open, and no
`[pfsov]`/HFileReader line for `CursorProject.gpb` in that run. The thread
reaches the null virtual dispatch first. `0xA40984` is not shown to be reached;
the new probe is needed to make that definitive.

Caveat: the old log did not log `cellFsWrite`/`cellFsLseek` at all (only reads
and a few opens). "Never sought/written" is not proven by that log; what is
proven is that in the pfstrace run the on-disk `.fdupi` stayed 0 and the
published count stayed 0, so no successful block write occurred. The fixer's
new `[pfscache]` trace and the `0xA40FBC`/`0xA40984` probe are the right way to
settle "never entered" versus "entered and failed".

### 3.2 The override correlation

The four cache pairs `K/6I`, `K/7E`, `K/JH`, `K/W2` were created at 15:16, the
same run that built the generic HFileReader plaintext override. `K/6I`, `K/7E`
and `K/JH` have `[pfs-open]`/`[pfsov]` lines in `work/pfstrace.err`, so their
reads were served by the override; the guest PFS cache read was bypassed by
design. Their empty `.fdupi` files are expected under the override. `K/W2` has
no such HFileReader line; its cache open is followed by the null dispatch.
Either way, no `0xA40FBC` entry is logged/proven for these runs; the new probe
settles it.

`K/IK` is the working control: bare `K/IK` is 572,352 bytes and byte-identical
to GT.VOL at `0x9E1000`; its `.fdupm` has 70 blocks and 70 bitmap bits. It was
completed at 14:45, before the override was built, and it proves the cache
format/raw-source rule. It does **not** prove that the allocate no-op caused the
compressed caches to be empty.

### 3.3 Is the HLE no-op upstream?

**No.** The no-op only leaves `.fdupi` at 0 until a write extends it. The writer
is `0xA40984`; its only caller is `0xA40FBC`; that caller requires a guest PFS
read. The missing link is the read path (null dispatch and/or the override),
not the size call. Implementing allocate/truncate faithfully is correct, but it
does not set `+0x20` and cannot produce a block bitmap.

The fixer's own report agrees (`pfs-cache-write-fix.md` §0 and §10). The
checker report's §6 implication that the no-op explains why `.fdupi` is 0 is
too strong; the decisive failure is the missing source block write.

---

## 4. Success criterion vs GT.VOL

### 4.1 TOC row and bytes

`work/gt6_volume_entries.txt` / `work/gt6_pfs_keymap.tsv`:

```text
projects/gt6/cursor/gpb/CursorProject.gpb
  Flags: Compressed | FileIndex: 58 (K/W2)
  SegIndex 6548, ZSize 0xEA57 (59,991), Size 0x3A880 (239,744)
  GT.VOL offset 0x7E800 + 6548*0x800 = 0xD48800
```

Direct read of `gt6/GT.VOL`:

```text
offset 0xD48800, length 0xEA57
first bytes 27 FD F1 57 AE 6E B5 CA ...
SHA-256 2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

The independent GTToolsSharp check on a fresh copy of that 59,991-byte slice
(`crypt -g GT6 -s 58`) produces **239,744** bytes whose SHA-256 is
`fe53f687...5ed923` and which is byte-identical to
`work/gt6_vol/projects/gt6/cursor/gpb/CursorProject.gpb`. So:

* **raw cache contract:** 59,991 bytes, SHA-256 `2b6153...9008`, byte-identical
  to GT.VOL at `0xD48800`;
* **read-side contract:** 239,744 bytes, SHA-256 `fe53f6...d923`, matching the
  extracted tree after the guest decrypt/inflate.

A 239,744-byte `.fdupi` would be raw plaintext, not a cache; the checker must not
accept it.

### 4.2 Expected map

For `ZSize=0xEA57`, blocks = `ceil(0xEA57/0x2000)` = **8**. A complete pair
(before the guest's completion cleanup) must be:

```text
.fdupm header:  u64 0xEA57 | u64 0 | u32 8
bitmap:         byte 0 = 0xFF, rest 0x00
.fdupi / bare:  59,991 bytes, SHA-256 2b6153...9008
```

On-disk state **before** the 16:41 new-binary run:

| Key | `.fdupm` size/id/blocks | bitmap bits | `.fdupi` | bare key |
|---|---|---:|---:|---:|
| `K/IK` | `0x8BBC0 / 0 / 70` | 70 | absent | 572,352 B, GT.VOL-identical |
| `K/W2` | `0xEA57 / 0 / 0` | 0 | 0 B | absent |
| `K/6I` | `0x580 / 0 / 0` | 0 | 0 B | absent |
| `K/7E` | `0x3395 / 0 / 0` | 0 | 0 B | absent |
| `K/JH` | `0x1872 / 0 / 0` | 0 | 0 B | absent |
| `K/WO` | `0xE24 / 0 / 0` | 0 | 0 B | absent |

After the 16:41 run with the rebuilt binary, the `.fdupi` sizes are now the
`ZSize` values but the contents are zeros:

| Key | `.fdupi` now | contents | `.fdupm` blocks | bitmap bits |
|---|---:|---|---:|---:|
| `K/W2` | 59,991 B | all `00`, SHA `7b5c0196...8362` | 0 | 0 |
| `K/6I` | 1,408 B | all `00` | 0 | 0 |
| `K/7E` | 13,205 B | all `00` | 0 | 0 |
| `K/JH` | 6,258 B | all `00` | 0 | 0 |
| `K/WO` | 3,620 B | all `00` | 0 | 0 |
| `K/PD` | 257,576 B | old pre-placed content preserved (not a valid raw cache) | 0 | 0 |
| `K/IK` | absent | bare 572,352 B unchanged | 70 | 70 |

**Current `K/W2`: FAIL.** The length now matches `ZSize`, but the content is
not the GT.VOL slice and the bitmap is empty.

### 4.3 Post-completion nuance

The completion path (`0xA40EBC..0xA40F50`) does two things when
`+0x20 == +0x68`:

1. unlink `<key>.fdupm` (`0xA40EF0..F00` -> `0xA3F4B8` -> `cellFsUnlink`);
2. rename `<key>.fdupi` to the bare `<key>` (`0xA40F18..F50` -> `0xA3F6B4` ->
   `cellFsRename`).

Therefore a **successful** final state is normally the bare `K/W2` file with the
59,991 raw bytes and **no `.fdupm`**. The `.fdupm` with blocks=8/bitmap FF is a
transient pre-close state. A checker that requires `.fdupm` after the process
exits will false-FAIL a correct run. The reverse is also true: a pre-seeded
`.fdupi`/`.fdupm` pair that the guest never touched will pass a pair-only check
without proving the guest writer.

The bare rename is itself strong evidence: the guest only renames when the
in-memory count equals the total (`+0x20 == +0x68`), so a bare `K/W2` with the
correct hash proves 8/8 blocks were published, even if the map has been
deleted.

---

## 5. Review of the fixer's change

Source reviewed: `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp` at 16:27
(62,636 bytes; the fixer report at 16:27). The binary `gt6/build/gt6.exe` was
rebuilt at 16:40, so the change **compiled**. A run at 16:41 used it and
produced the intermediate state predicted by the fixer: `.fdupi` files sized to
`ZSize` but all zero, `.fdupm` still `blocks=0`, and the `0x9F44D8` null
dispatch / `HOTREAD8` spin unchanged. The captured log has no `[pfscache]`
lines, so the new trace still needs a controlled run with
`GT6_PFS_CACHE_TRACE=1`.

### 5.1 What is correct

* **NIDs:** `0x7A0329A1`, `0xC9DC3AC5`, `0x0E2939E5`, `0xF12EECC8` are the
  right literal values. `cellFsFtruncate` is not imported by EMAIN, but the
  registration is harmless.
* **Size:** `fs_truncate_guest_path` uses the guest's already-open `FILE*` when
  found by exact guest path, so the `.fdupi` opened at `0xA42080` is sized with
  `_chsize_s`/`ftruncate` without a second Windows open. Existing bytes are
  preserved; extending creates zeroes, which is a stronger guarantee than
  "without zero fill" and is acceptable for this cache. The 16:41 run proves
  this path works: every compressed `.fdupi` is exactly its TOC `ZSize`
  (`K/W2` 59,991, `K/6I` 1,408, `K/7E` 13,205, `K/JH` 6,258, `K/WO` 3,620).
* **Raw bytes:** the change does not decrypt, inflate, byte-swap, or pad block
  data. `cellFsWrite` still writes the guest buffer verbatim. A guest-driven
  fill would therefore preserve GT.VOL source bytes.
* **Flush/close:** cache-path `cellFsWrite` now `fflush`es (and optionally
  `_commit`s) after each write; `cellFsFsync` commits; `cellFsClose` flushes.
  This addresses the "bitmap says written, data still in stdio buffer" failure
  mode. The guest `0xA40768` write wrapper already rejects short writes
  (`0xA40828` compares the out-count), so a short `cellFsWrite` cannot silently
  set a bitmap bit.
* **Primary VFS:** the new truncate/rename/unlink use `ppu_fs.cpp`'s
  `host_path`, which is configured for GT6's `PS3_HDD0_ROOT`, rather than the
  separate `libs/filesystem/cellFs.c` mapping table. That is the right layer.
* **Diagnostics:** `GT6_PFS_CACHE_TRACE=1` logs open/close/read/write/lseek/
  stat/fstat/allocate/truncate/rename/unlink with the guest LR. This is exactly
  the evidence needed to distinguish "never entered" from "entered and failed".

### 5.2 What is wrong or risky

1. **It is not a cache-bytes fix, and the 16:41 run proves it.**
   `cellFsAllocateFileAreaWithoutZeroFill` now truncates `.fdupi` to 59,991
   **zero** bytes at open. In the 16:41 run, `K/W2.fdupi` is 59,991 bytes with
   SHA-256 `7b5c0196...8362` and every byte zero; `K/6I`, `K/7E`, `K/JH` and
   `K/WO` are likewise exact `ZSize` zero-filled files; all their `.fdupm`
   headers remain `blocks=0`. The guest read still does not run, and the null
   call/spin is unchanged. A length-only check would false-PASS this state.
   The fixer's own report says the intermediate state is not success; the
   16:41 run confirms it.

2. **`cellFsTruncate` creates missing files.** Both allocate and truncate call
   the same helper, which uses `open(..., O_RDWR|O_CREAT, ...)`. Real
   `cellFsTruncate` requires an existing file and should return `ENOENT` for a
   missing path. This is a semantic deviation; it does not affect the observed
   cache path (truncate is not called), but it is a correctness bug in the new
   HLE. Use a `create` flag: allocate creates, truncate does not.

3. **`cellFsRename` deletes the destination before proving the source, and can
   destroy `K/IK`.** `if (stat(hto)==0) remove(hto); rename(hfrom,hto);`. If
   `hfrom` is missing, a valid old bare cache is deleted and the rename fails.
   The completed-cache scenario is worse: `K/IK` has bare data + a 70-block
   `.fdupm` and no `.fdupi`. If the guest's cache manager opens that pair again
   (as it does for the incomplete keys), `0xA42020` creates `.fdupi`, the new
   allocate zero-fills it to `ZSize`, the loaded header still says 70 blocks,
   and the completion branch can rename the zero-filled `.fdupi` over the valid
   bare `K/IK` after deleting it. That would replace the 572,352-byte control
   with zeros. The old legacy rename at least did not pre-delete the
   destination on Windows. **Do not land the new rename without an A/B on a
   completed `K/IK`.** The robust guard is: **never replace an existing
   non-empty bare `<key>` with a `.fdupi` source** (return success/EEXIST and
   leave both, or refuse); for a first completion the destination is absent, so
   the rename still works. If a size check is used, capture the sibling
   `.fdupm` `stored_size` before the completion unlinks it, not at rename time.
   Also require `hfrom` to exist and return a more specific error than always
   `CELL_FS_ENOENT`.

4. **`cellFsUnlink` can report success without deleting.** It returns
   `CELL_OK` for `EACCES`/`EBUSY`, leaving the file. That makes the final state
   nondeterministic: `.fdupm` may be deleted (normal) or left with blocks=8
   (if Windows still has a handle). The guest then renames `.fdupi` to bare;
   the left-map state also primes the completed-cache reopen risk in item 3.
   For deterministic cleanup, close any known open handle for the cache path
   and retry `remove`, or, in `cellFsRename`, delete the sibling `.fdupm`
   after a successful `.fdupi` rename.

5. **`fs_find_open` is exact-string and unlocked.** It compares
   `g_fd_path[i]` with the guest path. For `.fdupi` the open and allocate use
   the same guest buffer, so it matches; the trace will confirm. For other
   callers (the second allocate call site at `0xA3F104` / `0xA3DAF4`) the path
   may not be open, in which case the helper opens a second handle. On Windows
   this can fail if the first handle denies sharing. Low risk, but the second
   site is not K/W2-specific and should be A/B tested.

6. **Broad unlink/rename behavior change, including read-only mounts.**
   `cellFsUnlink` was a context-level no-op; it is now real for every guest
   path, not just cache paths. `cellFsRename` is now a context handler too.
   `host_path` maps `/dev_bdvd/...` into the host game tree (`GT6_GAME_ROOT`,
   `PS3-Version/...`); a guest unlink/rename/truncate of a disc path can now
   delete or replace a host asset instead of returning a read-only error. The
   cache cleanup only needs `/dev_hdd0/.../PDIPFS`. Gate the real
   implementations to writable cache paths (or at least reject `/dev_bdvd` and
   `/dev_flash`) until a boot A/B proves nothing deletes disc assets.

7. **`cellFsRename` is not needed for the first `K/IK` completion.** The legacy
   `libs/filesystem/cellFs.c` handler was registered and worked (the bare
   `K/IK` and `[cellFs] Rename` log prove it). The fixer's report's claim that
   rename was unregistered is factually wrong; a context rename handler can be
   useful for replacing a stale Windows destination **when the source is known
   good** (full `ZSize`, guest-written), but it must not remove a valid
   non-empty bare cache blindly, and it is not the missing piece.

8. **The build is proven; the target run is not controlled.** The binary was
   rebuilt at 16:40 and a run at 16:41 exercised the new allocate (`.fdupi`
   sizes changed), so the compile and `_chsize_s` path work. That run did not
   set `GT6_PFS_CACHE_TRACE=1` and did not populate a block. The null-dispatch
   interaction, the rename/unlink path, and the K/IK reopen risk are still
   unverified by a controlled run.

9. **Two small factual corrections to the fixer report.** It calls `.fdupm`
   open flags `2` "read-only"; PS3 flags `2` is `O_RDWR` (`ppu_fs` maps
   `acc == 2` to `O_RDWR`). It also says `r11 == 0x00000004` at the null call;
   the log line is `r12(opd)=0x00000004 opd[0]=0x00000000` (`r9=0`, `r11=0`).
   Neither changes the conclusion. Its §5 example labels a `cellFsWrite` HLE
   line with `lr=0x00A4122C`; that is the guest call to `0xA40984` (return
   `0xA4122C`). The HLE `lr` is `0x00A407E4` (return from the `0xA40768`
   wrapper's import call).
   Its §3.2 correctly says the K/WO GT.VOL read "may" be the cache fill, while
   §10 says K/WO's cache "is also not reached"; the old log cannot prove the
   negative for K/WO. Only K/W2 is clearly before any source read.

### 5.3 K/IK and boot

* `K/IK` has no `.fdupi` today, so the allocate/truncate change is not exercised
  **if the cache manager uses the bare `K/IK` and never opens the pair again**.
  The 16:41 run left bare `K/IK` unchanged: 572,352 bytes, SHA
  `dc4b5f...6ac2`, and `.fdupm` still 70 blocks. The completed-cache reopen did
  not fire in that run.
* The risk is the completed pair reopen path described in item 3: if the cache
  manager does open `.fdupm`/`.fdupi` for a completed `K/IK`, the new allocate
  creates a zero-filled `.fdupi`, the header still reports 70 blocks, and the
  new rename can remove the valid bare `K/IK` and replace it with zeros. The
  16:41 run is not a proof that this never happens; test a copy of the control
  on a fresh run before landing.
* On a future `K/IK` completion, the real `cellFsUnlink` may delete
  `K/IK.fdupm`. That is the guest's intended cleanup; the bare `K/IK` remains.
  The old `K/IK.fdupm` (70 blocks) is an artifact of the previous no-op unlink.
  Tests that use `.fdupm` as the permanent control must snapshot it before the
  run or accept its deletion.
* The boot-script override in `gt6/src/stubs.cpp` is independent of these HLEs.
  No change was made there. A boot A/B is still required because unlink/rename
  are now real for all paths; in particular, a guest unlink of `/dev_bdvd/...`
  can now delete a host disc-tree asset instead of failing read-only.
* `K/W2` itself: the change makes `.fdupi` 59,991 zero bytes on a fresh run,
  but does not populate `0xA40FBC`/`0xA40984`. The null dispatch at
  `0x9F44D8`/`0x9F4550` remains the measured blocker.

### 5.4 Verification tooling issues

`tools/gt6_pfs_cache_warm.py` is the right raw-byte/bitmap checker, but its
current pass/fail logic needs three fixes:

* **False PASS on a pre-seed.** `--write` followed by `--check` passes if the
  files still contain the pre-seeded bytes. That does not prove the guest ever
  read or wrote them. The fixer's §6.2 "read-side validation" is only valid if
  the run also shows the guest rename (bare `K/W2`, `.fdupi` gone) or the
  `0xA40FBC`/`0xA40984` trace. A pre-seed that the guest never touches must be
  labelled "fixture", not "guest cache".
* **False FAIL after completion.** A successful guest completion unlinks
  `.fdupm` and renames `.fdupi` to bare. `--check` then reports
  `MISSING ...K/W2.fdupm` and exits 1 even though the bare data is correct.
  Accept a missing map when the bare file exists and matches, and state that
  the rename gate (`+0x20 == +0x68`) proves the 8/8 bitmap. Alternatively,
  snapshot `.fdupm` before close.
* `--write` does not remove a stale bare `K/W2`; the guest may prefer the bare
  file and ignore the freshly pre-seeded `.fdupi`. Remove the bare file before
  writing a fresh pair.

The fixer's report §6.2 also expects `.fdupm` with `blocks=8` **after** the run,
which contradicts their own real `cellFsUnlink`: the completion path deletes
that map. The map with blocks=8 exists only before close/unlink. The acceptance
criterion must account for both states.

---

## 6. Safest next fix

### 6.1 First, prove where the read stops (no behavior change)

The 16:41 run did not set the trace. Re-run the already-built binary with:

```powershell
$env:GT6_PFS_CACHE_TRACE="1"
$env:GT6_PFS_CACHE_FSYNC="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\w2_trace.log
```

Expected on a correct guest path:

```text
[pfscache] allocate '.../K/W2.fdupi' size=0xEA57 -> OK lr=0x00A420AC
[pfscache] write fd=... '.../K/W2.fdupi' nbytes=8192 -> 8192 lr=0x00A407E4   (x7)
[pfscache] write fd=... '.../K/W2.fdupi' nbytes=2647 -> 2647 lr=0x00A407E4
[pfscache] close fd=... '.../K/W2.fdupm' size=8212 ...
[pfscache] rename '.../K/W2.fdupi' -> '.../K/W2' OK
[pfscache] unlink '.../K/W2.fdupm' -> OK/ENOENT ...
```

The HLE trace's `lr` is the return address inside the guest wrapper, not the
`0xA41228` call site: `cellFsWrite` is reached through the wrapper at
`0xA40768`, whose import call returns to `0xA407E4`. The `0xA40984` call site
is `0xA41228` (return `0xA4122C`); the generated code sets `ctx->lr` to that
before the call, but the current probe prints the cache arguments, not LR.
Do not treat the trace's `0xA407E4` as a different caller.

If there is **no `.fdupi` write**, the HLE is not the problem. Use the
`0xA40FBC`/`0xA40984` probe to separate the cases: no `0xA40FBC` means the
read path was never entered (the measured `K/W2` null dispatch at
`0x9F44D8` / `0x9F4550`, vtable `+0x8C`, OPD `0x4`, code 0); `0xA40FBC` but no
`0xA40984` means the miss branch was not taken or the source lseek/read failed;
`0xA40984` but no HLE write means a `0xA40984` gate or the data fd failed. Do
not implement a host fake of `0xA40FBC` before that dispatch is understood.

### 6.2 If the read path cannot be fixed immediately: data-faithful fixture

For an acceptance test only, pre-seed the pair with the exact raw bytes the
guest writer would have copied:

```text
.fdupi = GT.VOL[0xD48800 .. +0xEA57]          (59,991 bytes, SHA 2b6153...9008)
.fdupm = u64 0xEA57 | u64 0 | u32 8 | bitmap FF 00 ... (8,212 bytes)
```

`tools/gt6_pfs_cache_warm.py --key K/W2 --write` does this correctly, provided
any stale bare `K/W2` is removed first. This is data-faithful (no plaintext, no
padding) and does not touch `K/IK` or the boot script. It is **not** a
guest-driven fix and must be labelled as a fixture; it bypasses the missing
read/write path.

### 6.3 Correct acceptance criteria

**Guest-produced (preferred):**

1. trace shows the allocate and at least the eight block writes (or the
   `0xA40984` probe shows `block=0..7`, `len=0x2000`/`0xA57`);
2. the guest closes `K/W2.fdupm` with the header write and either renames
   `.fdupi` to bare `K/W2` or leaves the pair in a consistent state;
3. final bare `K/W2` (or `.fdupi` before rename) is **59,991 bytes**, byte
   identical to GT.VOL `0xD48800`, SHA-256 `2b6153...9008`;
4. `.fdupm`, if still present, has `size=0xEA57`, `id=0`, `blocks=8`, bitmap
   byte 0 `0xFF`; if absent, the bare rename proves the 8/8 gate;
5. `K/IK` bare is still 572,352 bytes / SHA `dc4b5f...6ac2` (or its map snapshot
   still 70 blocks), and the boot script still loads.

**Fixture (not proof of the writer):** the pair matches the same bytes, and the
run must additionally show the guest consumed it (bare rename/`.fdupi` gone) or
the fixture is explicitly marked as static.

### 6.4 Small HLE corrections before landing

* `cellFsTruncate`: do not create a missing file; return `ENOENT`.
* `cellFsRename`: **do not replace an existing non-empty bare cache with a
  `.fdupi` source**. If the destination exists, leave both and return
  success/EEXIST (or refuse); a first completion has no destination, so the
  normal rename still works. If you need a size check, capture the sibling
  `.fdupm` `stored_size` before the completion unlinks it. If no safe guard can
  be proven, keep the legacy rename (it works for the first completion) rather
  than landing remove-then-rename. Before landing, copy the completed `K/IK`
  control, run, and verify its bare hash is unchanged — the new remove-then-
  rename can otherwise replace it with a zero `.fdupi`.
* `cellFsUnlink`: make cache cleanup deterministic (close/retry) or, after a
  successful `.fdupi` -> bare rename, remove the sibling `.fdupm` explicitly.
  Reject unlink/rename/truncate on read-only mounts (`/dev_bdvd`,
  `/dev_flash`) instead of deleting host disc-tree files.
* `tools/gt6_pfs_cache_warm.py`: accept the post-completion "bare data, map
  deleted" state; reject a pre-seed that the guest did not touch; clear stale
  bare files on `--write`.
* Keep the cache-path flush and the trace; they are the right diagnostics and
  do not alter raw bytes.

---

## 7. Evidence index

| Evidence | Location / value |
|---|---|
| Import stub -> NID | `work/analysis/emain/EMAIN.imports.json` (0xF924B0/0x7A0329A1, 0xF92718/0xC9DC3AC5, 0xF92520/0x7F4677A8, 0xF927F8/0xF12EECC8) |
| Legacy NID registrations | `gt6/src/gen/ppu_hle_nids.cpp:1391,1392,1400,1401` |
| Constructor / header logic | `0xA42108`, `0xA42198`, `0xA421CC..DC`; `0xA41D80`; `0xA40DD4`/`0xA40E2C..64` |
| Load / allocate / read / write | `0xA41EB4`; `0xA42020`, `0xA420A8`; `0xA40FBC`, `0xA41228`; `0xA40984`, `0xA409A8..A40A54` |
| Completion | `0xA40EBC..C8` count compare; `0xA40EF0..F50` unlink/rename |
| K/W2 log | `work/pfstrace.err:32424..32455` |
| K/WO read | `work/lab1_final_run.err:258385..258467` |
| K/IK rename evidence | `docs/analysis/pfs-wo-check.md:200..207` |
| K/IK control | `work/gt6_hdd0/.../PDIPFS/K/IK` 572,352 B, SHA `dc4b5fd9...6ac2`; `.fdupm` 70 blocks, 70 bits |
| K/W2 TOC | `work/gt6_volume_entries.txt:30342`; `work/gt6_pfs_keymap.tsv:30343` |
| GT.VOL K/W2 slice | offset `0xD48800`, 59,991 B, SHA `2b6153ba...9008` |
| Plaintext K/W2 | GTToolsSharp `crypt -g GT6 -s 58` -> 239,744 B, SHA `fe53f687...d923`, equals `work/gt6_vol/projects/gt6/cursor/gpb/CursorProject.gpb` |
| Current cache state after the 16:41 new-binary run | `K/W2.fdupi` 59,991 B all zero (SHA `7b5c0196...8362`); `.fdupm` `size=0xEA57,id=0,blocks=0,bits=0`; `K/6I/7E/JH/WO` also exact-`ZSize` zero files; `K/IK` unchanged 572,352 B SHA `dc4b5f...6ac2` |
| 16:41/16:43 run logs | `work/gt6.log` (16:41 run, K/W2 open then null call `lr=0x009F4554`, `HOTREAD8`); `work/immediate_run.err` (16:43 run, same sequence) |
| Fixer source / report | `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp` 16:27; `docs/analysis/pfs-cache-write-fix.md` 16:27; binary rebuilt 16:40 |
| Fixer probes | `patches/gt6-pfs-cache-probe.patch`; `tools/gt6_pfs_cache_warm.py`; `tools/gt6_pfs_cache_probe.py` |
