# PFS `K/WO` (`MenuClassDefine.adc`): mapping, empty cache, and fix

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Measured run:** `work/lab1_final_run.err`, exe `work/gt6_lab1_final.exe`
**Scope:** identify the first non-script PFS asset (`K/WO`), explain the empty
`.fdupm`/`.fdupi` pair, decide whether the guest decrypt/inflate is supposed to
run on that read, and land the smallest safe unblock.

**Read-only work:** this report did not build or run `gt6.exe`. All guest
addresses are from static disassembly of `work/bin/EMAIN.elf` with
`tools/gt6_disasm_range.py` / `tools/gt6_find_calls.py`. Container work used
`GT.VOL`, `work/gt6_vol`, the GTToolsSharp listing, and
`tools/GTToolsSharp/win-x64/GTToolsSharp.exe`.

**Policy note:** `third_party/PDTools` was not read, copied, or used. The
analysis below is from GT6 data, GT6 logs, and the project's own disassembly
and GTToolsSharp tooling. No PDIPFS path-scrambler code or algorithm from
that repository is reproduced here.

---

## 0. Verdict

1. **`K/WO` is `products/gt6/script/MenuClassDefine.adc`.** TOC:
   `Flags: Compressed`, `FileIndex: 34 (K/WO)`, `SegIndex: 5215`,
   `ZSize: 0x00000E24` (3,620 stored bytes), `Size: 0x000030B0` (12,464
   plaintext bytes). GT.VOL offset
   `0x7E800 + 5215 * 0x800 = 0xAAE000`. The extracted plaintext is
   `work/gt6_vol/products/gt6/script/MenuClassDefine.adc` (12,464 bytes,
   `ADCH012\0`, SHA-256 `c4144c97…f3db9f8d`). It is both compressed (PS2ZIP)
   and ciphered (seed = FileIndex 34).
2. **The `.fdupm` block map is empty and the data file has no bytes.** The
   header is `u64 stored_size`, `u64 id`, `u32 block_count`, followed by an
   8,192-byte bitmap at `+0x14` (one bit per `0x2000`-byte source block).
   In the 14:43–14:49 baseline the K/WO header was all zero. A later live
   run (15:16–15:17, not this analysis) wrote the correct
   `stored_size=0xE24` but still `blocks=0`, bitmap empty, and
   `WO.fdupi=0`. So the source length is known; no source block was
   published. `K/IK` (uncompressed) is the valid control:
   `stored_size=0x8BBC0`, `id=0`, `blocks=70`, full 70-bit bitmap, and its
   bare data file `K/IK` is byte-identical to GT.VOL. `K/PD` has
   `stored_size=0x3EE28`, `blocks=0`, and a `PD.fdupi` whose length
   (857,518 = `Size=0xD15AE`) is inherited from the pre-placed file; its
   first `0x38000` bytes are raw GT.VOL ciphertext. The constructor derives
   `blocks = ceil(size/0x2000)` from the same `size` value it stores in the
   header (`0xA421CC..0xA421DC`), and the header field 0 is `ZSize`, so the
   bitmap counts **source** blocks, not output blocks.
3. **The guest decrypt/inflate is required on the read, not on the copy.**
   The cache holds raw GT.VOL bytes: `K/IK` is byte-identical to GT.VOL even
   though it is uncompressed, and `K/PD.fdupi`'s overwritten prefix is raw
   GT.VOL. The PFS file handle decrypts the raw stream with `0x9FF530`
   (gate `[device+0x144]` at `0x9FF584`); a compressed entry then goes
   through `PDISTD::SpuInflator` (vtable `0x148A2D0`, inflate `0xA43AB4`,
   submit `0xA440E4`). The measured 8,192-byte GT.VOL read at `0xAAE000`
   (magic `397AD60E`, log line 258440) proves the read-through reached the
   right source block. The empty `WO.fdupi`/bitmap is a
   cache-population failure, not a request to skip decrypt/inflate.
4. **Most likely missing piece: the SPU inflate workload, not a missing PPU
   lift of the cipher.** `0x9FF530` is PPU code and the TOC/header decrypt
   already works; GTToolsSharp reproduces the plaintext from the same slice.
   The SPU event handler thread faults at `0x00A564EC`
   (`sys_lwmutex_lock`) after an unresolved indirect call to `0x007F454C`
   (log 259240–259261), so the SPU side that would complete an inflate job is
   broken. The loader threads themselves exit normally (`status=0`, log
   258437 and 258467); they are not blocked in a join.
5. **Fix landed:** a generic, additive `HFileReader` plaintext override in
   `gt6/src/stubs.cpp`. It serves `work/gt6_vol/<virtual-path>` for every
   extracted PFS file (K/WO included), resolves cache-key-only opens
   (`K/WO`, `PDIPFS/K/WO`) through a TOC map, and falls through to the guest
   for files that are not extracted. This is the lowest-risk unblock and
   does not depend on the SPU fix.

---

## 1. What virtual file is `K/WO`?

### 1.1 TOC row and exact offsets

`work/gt6_volume_entries.txt`:

```
products/gt6/script/MenuClassDefine.adc - Flags: Compressed |
FileIndex: 34 (K/WO) | SegIndex: 5215, ZSize: 00000E24 |
Size: 000030B0 | VolIndex: 4294967295
```

Container math:

```
volume header       0x000000 .. 0x0000A0   (160 bytes)
compressed TOC      0x000800 .. 0x07E184   (0x7D984 = 514,436 bytes)
expanded TOC        0xCE43C bytes
data area           0x07E800
K/WO entry          0x7E800 + 5215 * 0x800 = 0xAAE000
stored range        0xAAE000 .. 0xAAE000 + 0xE24 = 0xAAEE24
```

The 8,192-byte read at log line 258440 covers `0xAAE000..0xAAFFFF`, i.e. the
3,620-byte K/WO entry followed by bytes belonging to later 0x800-byte
segments. The next entry, `K/6I` (`products/gt6/script/Prototypes.mwidget`),
starts at `0xAAF000` (SegIndex 5217), so the 8,192-byte block is K/WO's
3,620 bytes, 2,524 bytes of padding/adjacent segment data, and the first
4,096 bytes of K/6I's slot. The cache writer must clamp to `ZSize=0xE24`; it
wrote nothing.

### 1.2 Stored bytes and decrypted output

Raw slice at `0xAAE000` (3,620 bytes):

```
39 7A D6 0E E9 94 1F 6D E2 C4 42 3E 57 8B 11 06
```

That is ciphertext, not the file. GTToolsSharp's GT6 cipher with seed 34
(`FileIndex`) on exactly those 3,620 bytes produces 12,464 bytes:

```
41 44 43 48 30 31 32 00  …   ("ADCH012\0")
```

and the result is byte-identical to
`work/gt6_vol/products/gt6/script/MenuClassDefine.adc`:

| Object | Size | SHA-256 |
|---|---:|---|
| GT.VOL K/WO stored slice (`work/agent_wo/K_WO_stored.bin`) | 3,620 | `b881c1c19fa17984633200d5ab105dc308bc6f83f77daf1eb935d8bee73f23cb` |
| Decrypted+inflated output (`work/agent_wo/K_WO_dec.bin`) | 12,464 | `c4144c974a32323acb65e379dfec0dae5383bfa8162a8d3f98538751f3db9f8d` |
| Extracted host file (`work/gt6_vol/products/gt6/script/MenuClassDefine.adc`) | 12,464 | `c4144c974a32323acb65e379dfec0dae5383bfa8162a8d3f98538751f3db9f8d` |

**Compressed:** yes (`Flags: Compressed`, PS2ZIP).
**Ciphered:** yes (seed 34; stored head differs from plaintext head).
**Cache name:** the PDIPFS layer names the pair `PDIPFS/K/WO.fdupi` and
`PDIPFS/K/WO.fdupm`. The `K/WO` string is the TOC's `FileIndex` rendering,
not a path; the map from `K/WO` to the virtual path is a table lookup.

### 1.3 How `WO` maps to the extracted path

The TOC row ties three things together:

```
FileIndex: 34 (K/WO)   ← PDIPFS cache key / file id
products/gt6/script/MenuClassDefine.adc   ← virtual path
SegIndex 5215, ZSize 0xE24, Size 0x30B0    ← volume location + lengths
```

There is no TOC JSON in the tree; the input is the GTToolsSharp `listfiles`
output `work/gt6_volume_entries.txt`. `work/gt6_pfs_keymap.tsv` (generated by
`tools/patches/gt6_pfs_make_keymap.py`) stores

```
K/WO<TAB>products/gt6/script/MenuClassDefine.adc<TAB>Compressed<TAB>34<TAB>5215<TAB>E24<TAB>30B0<TAB>AAE000
```

The normal `HFileReader::open` already sees the **virtual path**, so the
runtime tries `work/gt6_vol/products/gt6/script/MenuClassDefine.adc`
directly. The key map is only needed if a caller opens the cache key itself
(`K/WO`, `PDIPFS/K/WO`, `PDIPFS_bdmark/K/WO`).

Caveat: the FileIndex string is not globally unique in the listing: the
32,591-row TOC has 29,849 unique keys and 1,776 duplicate keys. For a
key-only lookup the runtime uses the first TOC row and logs the ambiguity
under `GT6_PFS_TRACE=1`. The virtual-path lookup is unambiguous. This is one
more reason to prefer path-based serving over a key-only read-through.

---

## 2. Why is the `.fdupm` empty?

### 2.1 Header and block-map format

`K/IK.fdupm` is 8,212 bytes. Parsing it as the cache code does
(`0xA41EB4` reads 20 bytes, compares two u64s, then stores a u32):

| Offset | Type | K/IK value | K/PD value | K/WO value | Meaning |
|---:|---|---:|---:|---:|---|
| `+0x00` | `u64` | `0x8BBC0` | `0x3EE28` | `0` (baseline) / `0xE24` (15:16 run) | stored stream length (`ZSize`) |
| `+0x08` | `u64` | `0` | `0` | `0` | id / volume generation |
| `+0x10` | `u32` | `70` | `0` | `0` | number of valid source blocks |
| `+0x14` | 8,192 bytes | 70 bits set (`FF×8 3F`) | all zero | all zero | block bitmap |

`K/IK` is `sound_gt/se/gt6sys.sgd`, `Flags: Uncompressed`, FileIndex 31,
SegIndex 4805, `ZSize=Size=0x8BBC0`. Its cache data file
`work/gt6_hdd0/.../PDIPFS/K/IK` is 572,352 bytes and **byte-identical** to
GT.VOL at `0x9E1000`:

```
cache head: b7 93 a0 49 06 7f 24 72 15 af 00 ec a4 ce 71 26
GT.VOL head: b7 93 a0 49 06 7f 24 72 15 af 00 ec a4 ce 71 26
```

GTToolsSharp `crypt -g GT6 -s 31` on that same slice reproduces the
extracted `work/gt6_vol/sound_gt/se/gt6sys.sgd`. So the bare `K/IK` cache
holds the **raw stored stream**; the reader decrypts it.

The `.fdupi` data file for a compressed entry is also a raw source cache,
not plaintext:

* `K/PD.fdupi` is 857,518 bytes because it was pre-placed with the
  extracted `Size` and the game did not truncate it; the game overwrote its
  first `0x38000` bytes with raw GT.VOL ciphertext (old `pfs-decrypt-check.md`
  §1.4). Its header still records `stored_size=0x3EE28=ZSize`, so the
  intended capacity is `ZSize`, not `Size`.
* The constructor stores the same `size` in the header field 0 (`+0x10`)
  and derives `blocks=(size+0x1FFF)>>13` (`+0x68`). The header field 0 is
  `ZSize` for both IK and PD, so the bitmap counts **source** blocks.
* `K/IK`'s data file is byte-identical to GT.VOL, and `K/PD.fdupi`'s
  overwritten prefix is byte-identical to GT.VOL. No cache file has been
  observed to contain plaintext.

For K/WO the expected valid source cache would be:

```
data file   = WO.fdupi, capacity ZSize = 0xE24 = 3,620 bytes
stored_size = 0x0000000000000E24
id          = 0
block_count = 1                 (ceil(0xE24 / 0x2000))
bitmap[0]   = 0x01              (source block 0 present)
```

On disk `WO.fdupi` is 0 bytes and the bitmap is empty. In the 14:43–14:49
baseline the header was all zero; the 15:16 live run wrote
`stored_size=0xE24` but no blocks. The source size is now known; no source
block was published.

### 2.2 Code path that creates/opens the cache

| Address | Role |
|---|---|
| `0x9FDAAC` | `FileDevicePFSBase` open/cache path; resolves the virtual file and reads its entry |
| `0x9FDC5C` | calls `0xA422A0(path, size, id, 0)` from that path |
| `0xA422A0` | cache-manager wrapper; tail-calls `0xA42108` at `0xA42328` |
| `0xA42108` | cache object constructor: allocates 0xF8, stores `size` at `+0x10`, `id` at `+0x18`, computes `blocks = (size+0x1FFF)>>13` at `+0x68` (`0xA421CC..0xA421DC`) |
| `0xA41EB4` | metadata load: builds `.fdupm` (`0xA41EFC..0xA41F0C`), stats it (`0xF924E8`), opens read-only (flags 2 at `0xA41F50`), reads 20 bytes (`li r5,0x14` at `0xA41F6C`), compares the two u64s (`0xA41F9C..0xA41FB8`), stores the header block count at `+0x20` (`0xA41FF0`) |
| `0xA42020` | data-file create: builds `.fdupi` (`0xA42060..0xA42074`), opens with flags `0x42` (`O_RDWR|O_CREAT`) at `0xA42080`, truncates to `[obj+0x10]` through the `(path,size)` wrapper at `0xA420A0` (`0xF924B0`, consistent with `cellFsTruncate`) |
| `0xA3F6B4` | deletes `.fdupm`; path built at `0xA3F6F0..0xA3F704`, unlink wrapper `0xF927F8` at `0xA3F728`; the adjacent `0xA3F7E4` handles `.fdupi` |
| `0xA40E60` | cache destructor/flush; compares `[obj+0x20]` with `[obj+0x68]` at `0xA40EBC..0xA40EC8`, then calls `0xA3F6B4` at `0xA40F50` |

Two consequences:

* The 20-byte header is the object's **own** metadata. If the object is
  constructed with `size=0`, the header written is all zero, `blocks=0`, and
  the data file is truncated to 0. That matches the 14:43 baseline. The
  15:16 state (`stored_size=0xE24`, `blocks=0`) shows the size can be
  written while the block publication still fails, so the baseline zero
  header is not the only failure mode.
* The 0-byte `.fdupi` is the decisive state in both snapshots: no source
  block was published regardless of whether the header carried the size.

### 2.3 What the measured log shows

```
258385 [fs] open '.../PDIPFS_bdmark/K/WO' -> fd 3
258386 [fs] open '/dev_bdvd/PS3_GAME/USRDIR/GT.VOL' -> fd 3
258387 [fs] open '.../PDIPFS/K/WO.fdupm' -> fd 4
258420 [fs] read fd=4 nbytes=20 -> 20 (magic=00000000, total=1029232)
258427 [fs] read fd=4 nbytes=20 -> 20 (magic=00000000, total=1029252)
258428 [fs] open '.../PDIPFS/K/WO.fdupi' -> fd 5
258436 [fs] read fd=4 nbytes=8192 -> 8192 (magic=00000000, total=1037444)
258437 [SYS] sys_ppu_thread_exit(tid=33 status=0)
258440 [fs] read fd=3 nbytes=8192 -> 8192 (magic=397AD60E, total=1045636)
258467 [SYS] sys_ppu_thread_exit(tid=34 status=0)
```

Notes:

* `total` is the process-wide cumulative read counter, not the file size.
* In the baseline the two 20-byte `.fdupm` reads return all zero, so at that
  point the metadata load cannot match a nonzero size/id and cannot learn
  `ZSize=0xE24`. The later 15:16 run did write `stored_size=0xE24`, so the
  size can be published; the missing part is the blocks/data.
* The 8,192-byte `.fdupm` read is the bitmap; all zero means no source block
  is cached.
* The 8,192-byte GT.VOL read has magic `397AD60E`, which is the first four
  bytes of the K/WO entry at `0xAAE000`. The read-through found the right
  volume block.
* Both loader threads exit with status 0. They are not waiting in a join;
  whatever they submitted did not publish data before they returned.

The thread entry is `0xA304D0` (OPD at `0x14E0898`): a generic
`std::function`-style trampoline that calls the function object at
`[arg+0x18]`. It does not identify the worker itself, but it confirms the
threads are ordinary engine workers, not the SPU handler.

### 2.4 Why it stays empty

The safest statement supported by the data is:

1. The cache layer opened the right key (`K/WO`) and the right volume block
   (`0xAAE000`), so the virtual-path → TOC → SegIndex mapping works.
2. In the baseline the cache object published neither `stored_size` nor
   `block_count`; in the later run it published `stored_size=0xE24` but
   still `block_count=0`. It never wrote a source block into `.fdupi`.
3. That is consistent with the worker reading the source block and then
   failing/returning before the decrypt-inflate-store stage. It is also
   consistent with the metadata load treating the cache as valid and
   skipping the create/truncate branch: in the baseline the zero header
   "matched" a zero-sized object; in the 15:16 state the header size matches
   the object's `ZSize`, so `WO.fdupi` is left at 0 while the block map says
   "no blocks". The current probe set does not log the constructor's
   `size`/`id` arguments, so this report does not claim a single cause.
4. It is **not** evidence that the guest wants to skip decryption or
   inflation. The cache is a raw source cache (`K/IK` proof), and the
   read-through fetched the raw K/WO block.

The probe already proposed in `pfs-decrypt-fix.md` §4.1 (mount key,
`[device+0x144]`, `[device+0x148]`) plus a log at `0xA42108` entry
(`size`, `id`) and at `0xA41FEC` (loaded `blocks`) would settle the
constructor argument question without changing behavior. The 15:16 state
(`stored_size=0xE24`, `blocks=0`) already shows the constructor had the right
`ZSize` at least once, so the failure is after that point.

---

## 3. Is the guest decrypt/inflate supposed to run on this read?

**Yes.** The cache is raw; the read side owns both stages.

### 3.1 Cipher: PPU `0x9FF530`

`0x9FF530` is the PFS file-handle method at vtable `0x14DF910` slot `+0x30`.
It is a range cipher over `(device, offset, buffer, length)` with the
distinctive 64-bit multiply constants and the 17/19/23/29 table cycles:

```
0x9FF584  lwz  r0, 0x144(r3)    ; keyset/decrypt-enable
0x9FF5A0  beq  cr7, 0x9FF9CC    ; skip decrypt, return stored bytes
0x9FF5AC  lis  r8, 0x1a7b ...
0x9FF77C  table 0xFA22D0, cycle 17
0x9FF790  table 0xFA22F2, cycle 19
0x9FF79C  table 0xFA2318, cycle 23
0x9FF7AC  table 0xFA2346, cycle 29
```

The TOC/header decrypt already works (the B-tree walk finds the correct
K/WO entry), and GTToolsSharp's independent GT6 cipher with seed 34
reproduces the extracted file. There is no evidence of a missing lift in the
cipher. The only open question is the `[device+0x144]` gate, which was not
logged in this run; if it were zero, the guest would return stored bytes at
`0x9FF9CC`. That would produce ciphertext, not the 0-byte cache state
observed first.

### 3.2 Inflate: SPU `PDISTD::SpuInflator`

| Item | Address |
|---|---|
| typeinfo name | `0x109BF60` (`N6PDISTD11SpuInflatorE`) |
| vtable | `0x148A2D0` |
| ctor | `0xA43A14` (called from `0x10654` with the global at `0x155FC30`) |
| inflate / job start | vtable `+0x08` -> `0xA43AB4` |
| SPU submit | `0xA440E4` (called from `0xA43AE4`) |

`0xA43AB4` checks the one-shot byte at `[this+0x10840]`, reads the two job
parameters from `[this+0x1084C]`/`[this+0x10850]`, calls `0xA440E4`, and sets
the byte. (`addis r31,r3,1` makes the base `this+0x10000`; the offsets are
`0x840`, `0x84C`, `0x850`.) There are no direct `bl` callers because the call
is virtual (vtable slot `+0x08`). This is the only PS2ZIP decompressor in the
binary.

The run's SPU side is broken:

```
259240 [ppu] unresolved indirect call -> 0x007F454C (tid=15 lr=0x00A56A40)
259247       UNRES-guest: ? func_00A569D0+0x533 ? func_00A564EC+0x7D9 ? func_00A56698+0x247
259259 [GT6] ACCESS VIOLATION: read at host 0x19400000000 (thread 29272)
259261 [GT6] crash is PPU tid=14 name="Spu Event Handler" entry=0x014E14C0
              prof_pc=0x00A564EC hle=sys_lwmutex_lock
```

The `[spurs-job] … RETURNED rc=0` lines are the HLE scheduler's return
values; they do not prove the inflate payload wrote its output buffer. A
submitted `SpuInflator` job whose completion depends on this thread will
leave the output empty or untouched.

**Therefore:**

* Missing PPU lift of the cipher: **not supported** by the evidence.
* Missing/broken SPU inflate workload: **primary suspect** for the compressed
  read never producing plaintext.
* Wrong HLE of the cache/fs layer: **possible but unproven**; the `cellFs`
  opens/reads/stats run, and the cache object's zero size is not explained by
  the log. The probe in §2.4 is the next diagnostic.
* The empty `.fdupm` is a **cache-population** failure, separate from the
  inflate. It does not by itself block the read-through (the reader fetched
  GT.VOL directly), but it removes the fast path and makes every read
  dependent on the broken decrypt/inflate path.

### 3.3 Which failure is it?

| Hypothesis | Evidence for | Evidence against | Verdict |
|---|---|---|---|
| Missing PPU lift of the cipher `0x9FF530` | none | the function is present/lifted; TOC/header decrypt works; GTToolsSharp reproduces the file | **No** |
| Wrong HLE of the cache/fs layer (size, truncate, write) | baseline zero header looked like a zero size | the 15:16 run wrote `stored_size=0xE24`; the `cellFs` opens/reads/stats run | **Possible, unproven** |
| Missing/broken SPU inflate job (`SpuInflator`) | compressed entries are the ones with empty caches; `0xA43AB4` -> `0xA440E4` is the only PS2ZIP path; SPU handler faults at `0x00A564EC` | no direct probe log of `0xA43AB4` | **Primary suspect** |
| Copy thread blocked on a join | none | tid 33/34 exit `status=0` at 258437/258467 | **No (not literal)** |

The practical reading is: the worker reads the source block, returns, and the
decode/store completion never lands. Whether the immediate cause is the SPU
job or the cache store HLE, the safe unblock is the same: serve the
already-decoded host file until the guest path is proven.

---

## 4. Fix options, ranked by risk

| Rank | Option | What it fixes | Risk | Verdict |
|---:|---|---|---|---|
| 1 | **(a) HFileReader plaintext override** (implemented) | every file already present in `work/gt6_vol`, including K/WO | **Low**: serves exact extracted bytes, only when the host file exists, falls through otherwise | **Land now** |
| 2 | **(c) Guest cache + SPU inflator root fix** | all PFS files, fresh runs, no extracted tree | **Medium–high**: needs working SpuInflator job completion and cache publication; touches the guest/SPU path | **Root fix, next** |
| 3 | **(b) Host PFS read-through with cipher + inflate** | all PFS files without the guest | **High**: duplicate `0x9FF530` and PS2ZIP, double-decrypt risk, large code surface | **Only if (a) coverage is insufficient** |
| — | Pre-place `.fdupi` | one file | High | **Rejected** (already disproved) |

The task's preferred order is (a), (b), (c); ranked by correctness risk, (a)
is first, the guest root fix (c) is second, and the host duplicate (b) is
last. (b) becomes attractive only when the extracted tree does not cover the
assets the engine needs.

### 4.1 (a) Implemented: generic plaintext override

The existing boot-script override is extended, not replaced:

* `gt6_script_path_hint` still owns `/scripts/gt6/main.adc`.
* A new `gt6_pfs_path_hint` is called for every other `HFileReader::open`.
  It normalizes the guest path, rejects `..`/drive-letter escapes, and tries
  `work/gt6_vol/<path>`.
* If the direct path is absent and the path looks like a cache key
  (`K/WO`, `5T/AM`, optional `PDIPFS/` or `PDIPFS_bdmark/` prefix), it scans
  `work/gt6_pfs_keymap.tsv` for the TOC row and serves the mapped virtual
  path.
* Up to 8 readers are tracked independently; a new open on a reader replaces
  its stream, so stale bytes cannot be returned for a new file.
* Reads copy the plaintext into guest memory (bulk `memcpy` through
  `vm_base` when available) and keep `HFileReader+0x1B4` (tell), `+0x1AC`
  and `+0x1B0` (read-ahead buffer) coherent; at EOF they also set
  `+0x18=1`, matching the real `HFileReader::read` state.
* Seeks update the same fields; EOF returns 0 without discarding the stream.
* Files that are not extracted fall through to the guest path unchanged.

Environment knobs:

```
GT6_PFS_OVERRIDE=0     disable the generic override
GT6_PFS_TRACE=1        log every open path, TOC row, read and seek
GT6_PFS_MAX_MB=<n>     per-file cap (default 64)
GT6_VOL_ROOT=<dir>     extracted tree (default work/gt6_vol)
GT6_PFS_KEYMAP=<file>  map file (default work/gt6_pfs_keymap.tsv)
```

Why this is safe for K/WO:

* The extracted file is the exact output of the guest's intended
  decrypt+inflate; SHA-256 and size match the independent GTToolsSharp result.
* No guest state is synthesized: the same `HFileReader` receives the same
  byte stream, at the same offsets, with the same tell/seek behavior.
* If `work/gt6_vol/products/gt6/script/MenuClassDefine.adc` is missing, the
  guest path runs exactly as before.
* `GT6_PFS_OVERRIDE=0` restores the baseline for A/B verification.

Limitations:

* It does not populate `.fdupi`/`.fdupm` and does not fix the SPU inflate.
* It only helps files already extracted under `work/gt6_vol`.
* If `HFileReader::open` itself returns 0 for a file, the override cannot
  force the success branch (that would need a generated-code edit at the
  `0x9BB11C` call site). The measured K/WO open succeeds, so this is not the
  current blocker.
* It deliberately skips `scripts/gt6/main.adc`, preserving the existing
  boot-script override.

### 4.2 (c) Root fix outline

1. Fix the SPU event handler crash / `SpuInflator` completion
   (`0xA43AB4` -> `0xA440E4`), then verify the PS2ZIP output.
2. Instrument `0xA42108` entry (`size`, `id`) and `0xA41FF0` (loaded
   `blocks`); the 15:16 state already writes `stored_size=0xE24`, so the
   remaining cache fix is to publish `blocks=1` and bitmap bit 0 after the
   source block is decoded.
3. Verify `0x9FF530` is called with `[device+0x144] != 0` for the K/WO read
   (probe in `pfs-decrypt-fix.md` §4.1).
4. Remove or gate the plaintext override once the guest path is proven on a
   clean cache.

### 4.3 (b) Host read-through outline (not implemented)

At the HFileReader/device layer or the PFS read layer:

```
entry = toc_lookup(key)
raw   = gt.vol[0x7E800 + entry.SegIndex * 0x800 .. + entry.ZSize]
plain = pfs_cipher_0x9FF530(raw, seed = entry.FileIndex)
out   = ps2zip_inflate(plain, entry.Size)
serve(out)
```

This duplicates the guest cipher and PS2ZIP. It must not run if the guest
cipher/inflate is later fixed, or the data will be decrypted twice. It also
needs a one-shot guard and exact PS2ZIP semantics. The extracted tree makes
this unnecessary for the current asset set.

---

## 5. Patch / diff

Full unified diff:
`tools/patches/gt6-pfs-wo-override.patch` (generated against the
pre-edit `gt6/src/stubs.cpp`, SHA-256
`BCEEEE45B513CE74D3AA50D8F1EB2EE9035C136961EA49333E57FF1FA9022D79`).

Key map generator:
`tools/patches/gt6_pfs_make_keymap.py`.

Generated map:
`work/gt6_pfs_keymap.tsv` (2,551,891 bytes; 32,591 entries; 29,849 unique
keys; 1,776 duplicate keys; one truncated listing line skipped).

### 5.1 Integration hunks (the only changes outside the new block)

```diff
@@ -123,12 +584,20 @@ extern "C" void gt6_script_path_hint(uint32_t reader_ea, uint32_t str_ea)
     path[sizeof path - 1] = 0;
 
+    /* Generic extracted-file override.  It clears any stream previously
+     * installed for this reader and ignores scripts/gt6/main.adc, which the
+     * boot-script override below owns. */
+    if (gt6_script_path_matches(path))
+        gt6_pfs_unload_reader(reader_ea);
+    else
+        gt6_pfs_path_hint(reader_ea, path);
+
     if (!gt6_script_path_matches(path)) {
@@ -167,13 +636,14 @@ extern "C" int gt6_script_seek_override(ppu_context* ctx)
-    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader) return 0;
+    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader)
+        return gt6_pfs_seek_override(ctx);
@@ -184,13 +654,14 @@ extern "C" int gt6_script_read_override(ppu_context* ctx)
-    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader) return 0;
+    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader)
+        return gt6_pfs_read_override(ctx);
```

The new block is inserted after `gt6_script_unload()` and before
`gt6_script_path_hint()`. It adds:

```c
enum { GT6_PFS_SLOTS = 8, GT6_PFS_PATH_MAX = 256,
       GT6_PFS_HOST_MAX = 512, GT6_PFS_DEFAULT_MB = 64 };

struct Gt6PfsSlot {
    uint32_t reader, size, pos;
    uint64_t stamp;
    unsigned char* data;
    char path[GT6_PFS_PATH_MAX];
};
```

and the functions `gt6_pfs_root`, `gt6_pfs_keymap`, `gt6_pfs_relpath`,
`gt6_pfs_strip_cache_prefix`, `gt6_pfs_key_shape`, `gt6_pfs_lookup_key`,
`gt6_pfs_trace_toc`, `gt6_pfs_resolve`, `gt6_pfs_slot_clear`,
`gt6_pfs_find`, `gt6_pfs_slot_for`, `gt6_pfs_unload_reader`,
`gt6_pfs_path_hint`, `gt6_pfs_read_override`, `gt6_pfs_seek_override`.

Selected implementation points:

```c
/* Serve only files that exist under the extracted root. */
snprintf(host, cap, "%s/%s", root, rel);
if (!fopen(host, "rb")) {
    const char* key = gt6_pfs_strip_cache_prefix(rel);
    if (gt6_pfs_key_shape(key) && gt6_pfs_lookup_key(key, vpath, sizeof vpath))
        snprintf(host, cap, "%s/%s", root, vpath);
}
```

```c
/* Read: exact sequential bytes, same fields as HFileReader::read. */
if (vm_base) memcpy(vm_base + out, s->data + s->pos, k);
else for (uint32_t i = 0; i < k; i++)
    vm_write8((uint64_t)out + i, s->data[s->pos + i]);
s->pos += k;
vm_write32((uint64_t)s->reader + 0x1B4, s->pos);
vm_write32((uint64_t)s->reader + 0x1AC, 0);
vm_write32((uint64_t)s->reader + 0x1B0, 0);
ctx->gpr[3] = k;
```

### 5.2 Why the path check is enough for K/WO

The measured `HFileReader` path for the boot script is
`/scripts/gt6/main.adc` (log line 1190). The same open hook is used for
K/WO, so the expected path is
`products/gt6/script/MenuClassDefine.adc` or
`/products/gt6/script/MenuClassDefine.adc`. Both normalize to the extracted
file. If the engine passes a different spelling, `GT6_PFS_TRACE=1` logs
`[pfshint] ... path='…'` before the mount lookup, and the map/tree can be
adjusted without changing the code.

---

## 6. Verification procedure

### 6.1 Regenerate and check the map (no run)

```powershell
python tools\patches\gt6_pfs_make_keymap.py --verify
```

Expected:

```
wrote work\gt6_pfs_keymap.tsv: 32591 entries, 29849 unique keys,
      1776 duplicate keys, 1 unparsed line(s)
  K/WO -> products/gt6/script/MenuClassDefine.adc [Compressed]
         FileIndex=34 SegIndex=5215 ZSize=0xE24 Size=0x30B0 offset=0xAAE000
  GT.VOL head: 39 7a d6 0e e9 94 1f 6d e2 c4 42 3e 57 8b 11 06
  verified: K/WO ciphertext magic 0x397AD60E at that offset
```

### 6.2 Check the cache state (no run)

The preflight script does all of this in one step:

```powershell
python tools\patches\gt6_pfs_check_wo.py
```

Expected baseline/current values:

| Object | Baseline 14:43–14:49 | Current 15:16 state | Valid control |
|---|---|---|---|
| `WO.fdupm` | `size=0, id=0, blocks=0, bits=0` | `size=0xE24, id=0, blocks=0, bits=0` | `size=0xE24, blocks=1, bit0=1` |
| `WO.fdupi` | 0 bytes | 0 bytes | 3,620 bytes (raw source) |
| `PD.fdupm` | `size=0x3EE28, blocks=0` | `size=0x3EE28, blocks=0` | 32 source blocks |
| `PD.fdupi` | 857,518 (pre-place size; raw prefix) | same | 257,576 intended raw source capacity |
| `IK.fdupm` | `size=0x8BBC0, blocks=70, bits=70` | unchanged | full |
| `IK` (bare data file) | 572,352 raw | unchanged | raw == GT.VOL |

The 15:16 live run was not started by this analysis. It is included because
it changes the K/WO header from all-zero to `stored_size=0xE24`, which
narrows the failure to the block/data publication.

### 6.3 Build and run (owner)

1. Apply/keep `gt6/src/stubs.cpp` as in `tools/patches/gt6-pfs-wo-override.patch`
   (the patch was generated from the pre-edit file; the owner may already
   have the file open).
2. Build with the normal `scripts/build-gt6.ps1`.
3. Run headless with tracing:

```powershell
$env:PS3_HEADLESS="1"; $env:PS3_VERBOSE="1"; $env:GT6_CONSOLE="1"
$env:GT6_PFS_TRACE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_wo\run_wo_trace.log
```

Expected lines (reader address will differ):

```
[GT6] script override: serving decrypted /scripts/gt6/main.adc (857518 bytes)
[pfshint] reader=0x........ path='products/gt6/script/MenuClassDefine.adc'
[pfstoc] key=K/WO path=products/gt6/script/MenuClassDefine.adc flags=Compressed
         file=34 seg=5215 zsize=E24 size=30B0 offset=AAE000
[GT6] pfs override: serving plaintext products/gt6/script/MenuClassDefine.adc
      (12464 bytes, reader=0x........)
[pfsov] this=0x........ n=... pos=0/12464 products/gt6/script/MenuClassDefine.adc
```

The first returned bytes must be:

```
41 44 43 48 30 31 32 00    ("ADCH012\0")
```

4. Confirm no `[pfsov]` is served by the wrong reader: `this` must be the
   same reader as the `[GT6] pfs override` line.
5. Confirm the boot-script reader still returns `41 44 43 48 30 31 32 00`
   and is not handled by the generic slot.
6. A/B baseline:

```powershell
$env:GT6_PFS_OVERRIDE="0"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_wo\run_wo_baseline.log
```

Expected baseline: no `pfs override` lines for K/WO; the `.fdupi` stays 0
and the `.fdupm` stays block-empty (the header may be all zero as in the
14:43 baseline, or carry `stored_size=0xE24` as in the 15:16 run).

### 6.3.1 Corroborating 15:16 run (not a controlled verification)

The owner's `work/build_spursfix.log` at 15:15:53 compiled `src/stubs.cpp`
with the generic override block and linked `gt6/build/gt6.exe`; the binary
contains the new strings `[pfshint]`, `[pfstoc]`,
`pfs override: serving plaintext`, and `gt6_pfs_keymap.tsv`. (The final
`+0x18` EOF-state tweak was added after that build; it does not change the
serving logic.) A run at 15:16:55 then created cache pairs for
`K/6I`, `K/7E`, `K/JH`, and `K/W2`. Those keys map to:

| Key | Virtual path | Extracted? |
|---|---|---|
| `K/6I` | `products/gt6/script/Prototypes.mwidget` | yes |
| `K/7E` | `projects/gt6/cursor/cursor.adc` | yes |
| `K/JH` | `projects/gt6/cursor/cursor.mproject` | yes |
| `K/W2` | `projects/gt6/cursor/gpb/CursorProject.gpb` | yes |

That is the expected next-asset sequence after `MenuClassDefine.adc`, and all
four files are present in `work/gt6_vol`. Their `.fdupm` headers carry the
exact TOC `ZSize` (`0x580`, `0x3395`, `0x1872`, `0xEA57`) with `blocks=0`
and empty bitmaps; the `.fdupi` files are 0 bytes. That is the same
signature as K/WO: the guest cache open runs and writes the size, but no
data block is published. The empty `.fdupi` files are **expected** when the
override serves the reads: `HFileReader::open` still runs the guest cache
open (which creates the pair), but `read` is served from the extracted file.
Do not read these empty caches as a failure; they are the signature of the
override doing its job. This is corroborating evidence that the override
advanced past K/WO, not a controlled verification: no `GT6_PFS_TRACE` log
from that run was captured. The next run should save the trace log as in
§6.3.

### 6.4 What to check if K/WO still fails

| Symptom | Meaning | Next check |
|---|---|---|
| no `[pfshint] path=...MenuClassDefine...` | the engine opened a different path | search the trace for `MenuClass`/`.adc`; adjust the map or extracted tree |
| `[pfshint]` shows the path, no `pfs override` line | host file missing/cap | check `work/gt6_vol/<path>` and `GT6_PFS_MAX_MB` |
| `pfs override` line, but parser still fails | ADCH/asset parser, not PFS | run the ADCH parser checks in `adch-parser-check.md` |
| `pfsov` returns 0 at `pos=0/12464` | reader address mismatch or slot eviction | raise `GT6_PFS_SLOTS`, check the `this` value |
| `.fdupi` still 0 after K/WO served | expected: the override bypasses the cache; this does not indicate failure | verify the override log and the returned bytes |

### 6.5 Independent byte check

`crypt` is in-place, so work on a fresh copy of the stored slice (do not run
it twice on the same file):

```powershell
Copy-Item work\agent_wo\K_WO_stored.bin work\agent_wo\K_WO_check.bin -Force
tools\GTToolsSharp\win-x64\GTToolsSharp.exe crypt -g GT6 -s 34 `
    -i work\agent_wo\K_WO_check.bin
Get-FileHash work\agent_wo\K_WO_check.bin, `
    work\gt6_vol\products\gt6\script\MenuClassDefine.adc -Algorithm SHA256
```

Both must be `c4144c974a32323acb65e379dfec0dae5383bfa8162a8d3f98538751f3db9f8d`
and 12,464 bytes. `python tools\patches\gt6_pfs_check_wo.py` performs the
same size/hash checks without touching the file.

---

## 7. Address index

| Address | Meaning |
|---|---|
| `0x9FDAAC` | `FileDevicePFSBase` open/cache path; reads the entry and sets up the cache |
| `0x9FDC5C` | call to `0xA422A0(path, size, id, 0)` |
| `0xA422A0` | cache-manager wrapper; tail-call to `0xA42108` at `0xA42328` |
| `0xA42108` | cache object constructor; `+0x10` size, `+0x18` id, `+0x68` block count |
| `0xA421CC` | `blocks = (size + 0x1FFF) >> 13` |
| `0xA41EB4` | `.fdupm` metadata load; reads 20 bytes, compares size/id, stores block count |
| `0xA41F6C` | `li r5,0x14` — 20-byte header read |
| `0xA41F9C` | header `size`/`id` compare |
| `0xA41FF0` | store header block count to object `+0x20` |
| `0xA42020` | `.fdupi` create/open/truncate path |
| `0xA42080` | open flags `0x42` (`O_RDWR|O_CREAT`) |
| `0xA420A0` | truncate to `[obj+0x10]` through `0xF924B0` |
| `0xA3F6B4` | delete `.fdupm` (adjacent `0xA3F7E4` handles `.fdupi`) |
| `0xA40E60` | cache destructor/flush; compares `+0x20` and `+0x68`, calls `0xA3F6B4` |
| `0xA43AB4` | `SpuInflator` inflate/job start |
| `0xA440E4` | `SpuInflator` SPU submit |
| `0x148A2D0` | `SpuInflator` vtable; slot `+0x08` = `0xA43AB4` |
| `0x109BF60` | typeinfo `N6PDISTD11SpuInflatorE` |
| `0x109BF78` | string `inflatorSPU` |
| `0x9FF530` | PFS file-data cipher (PPU), seed = FileIndex |
| `0x9FF584` | cipher gate `[device+0x144]` |
| `0x9FF9CC` | skip-decrypt return |
| `0x14DF910` | PFS file-handle vtable; slot `+0x30` = `0x9FF530` |
| `0x9FFD88` | PFS file-handle method at vtable `+0x40` (calls the path/open helper) |
| `0x9FFA58` | PFS path/open helper used by `0x9FFD88` |
| `0xA304D0` | generic thread trampoline used by tid 33/34 (OPD `0x14E0898`) |
| `0x14E14C0` | SPU event handler entry (OPD) |
| `0x00A564EC` | SPU event handler fault PC (`sys_lwmutex_lock`) |
| `0x9BB020` | `HFileReader::read` (override hook) |
| `0x9BAFE0` | `HFileReader::seek` (override hook) |
| `0x9BB11C` | `HFileReader::open` (override hook) |
| `0x1484CC8` | `HFileReader` vtable |
| `0x14DCB18` | OPD for `HFileReader` vtable `+0x11C` -> `0x9BB020` |
| `0x9BAF60` | `HFileReader::tell` (`+0x1B4`) |
| `0x9BB2E4` | `HFileReader::close` (clears `+0x1B4`, sets `+0x18=2`) |
| `0x109BF38` | `.fdupi` string |
| `0x109BF40` | `.fdupm` string |
| `0x1097B70` | `PDIPFS` string |
| `0x1097B78` | `PDIPFS_bdmark` string |
| `0x14E7718` | `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` string |
| `0xFB0FBC` | `PDIPFS` module string |

## 8. Caveats

* The exact reason the 14:43 baseline header was all zero is not proven.
  The 15:16 state (`stored_size=0xE24`, `blocks=0`) shows the constructor
  had the right `ZSize` at least once, so the remaining failure is after the
  size is known: the block/data publication. The next probe should log
  `0xA42108`'s `size`/`id` arguments and `0xA41FEC`'s loaded block count.
* The `.fdupm` mtime (14:49:54) is later than its creation (14:43:49), so the
  baseline all-zero header may include a late flush/overwrite. The 0-byte
  `.fdupi` is the decisive state in both snapshots.
* The 8,192-byte GT.VOL read at `0xAAE000` is inferred from the magic
  `397AD60E`; the read offset itself is not logged. The match is exact for
  the K/WO entry.
* The generic override keeps one stream per `HFileReader`, matching the
  existing boot-script override. A nested open on the same reader replaces
  the previous stream; the measured boot script uses separate readers, but
  an engine path that reuses one reader for nested opens would drop the
  outer stream.
* The SPU event handler fault is being handled by a separate agent; this
  report treats it as the likely inflate-completion blocker and does not
  propose an SPU patch.
* The `cellFs` wrapper names `0xF92478`/`0xF92398`/`0xF924B0`/`0xF924E8`/
  `0xF927F8` are inferred from call signatures and error handling
  (`cellFsOpen`, `cellFsClose`, `cellFsTruncate`, `cellFsStat`,
  `cellFsUnlink`). The NID registration is in
  `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp`; the wrappers are the
  guest-side PLT stubs, not the HLE names.
* `third_party/PDTools` was not consulted; no code or algorithm from it is
  included in `gt6/src/stubs.cpp`, the key-map generator, or this report.
* This report did not invoke a build or a `gt6.exe` run. The override was
  syntax-checked with `clang++ -std=c++20 -fsyntax-only` against the project
  include paths. A concurrent owner build at 15:15:53 compiled a `stubs.cpp`
  containing the generic override and linked a binary with the new log
  strings; a concurrent owner run at 15:16 produced the cache pairs noted in
  §6.3.1. The final EOF-state tweak was added after that build. Neither is a
  controlled verification by this analysis.
