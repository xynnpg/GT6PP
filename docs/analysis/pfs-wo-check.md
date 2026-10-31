# PFS `K/WO` mapping, cache behavior, and override check

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Scope:** independent check of the first post-boot-script PFS access (`K/WO`), the
`.fdupm`/`.fdupi` cache, and the proposed general HFileReader / PFS read-through
override.
**Read-only:** this check did not build or run `gt6.exe`, and did not edit `gt6/`,
`work/bin`, or the game data. It read the existing artifacts, extracted bytes from
GT.VOL to `%TEMP%`, and disassembled `work/bin/EMAIN.elf`.

**Policy note:** `third_party/PDTools/AGENTS.md` prohibits AI/LLM use of that
subtree. One file there was opened before the notice was received; no code or
algorithm from it is reproduced, quoted, or relied on here. Every mapping claim
below is derived independently from `work/gt6_volume_entries.txt` (the generated
TOC listing), GT.VOL bytes, and `work/gt6_vol`.

---

## 0. Verdict

| # | Item | Verdict |
|---:|---|---|
| 1 | `K/WO` maps to a real GT.VOL entry | **PASS** — FileIndex 34, SegIndex 5215, offset `0xAAE000` |
| 2 | The entry extracts/decrypts correctly | **PASS** — 3,620-byte entry → 12,464-byte `ADCH012` file |
| 3 | The extracted path and size are known | **PASS** — `products/gt6/script/MenuClassDefine.adc`, 12,464 B, SHA-256 `C414…9F8D` |
| 4 | `K/WO` is an actual game file, not a "WO" blob | **PASS** — v12 ADCH **menu class-definition script**; `main.adc` references `/script/MenuClassDefine` |
| 5 | `.fdupm`/`.fdupi` are a raw block cache, not a decrypt cache | **PASS** — proved by `K/IK`: whole cache file is byte-identical to the raw GT.VOL entry |
| 6 | The read path should decrypt/inflate | **PASS** — but only at the PFS file-handle layer, never in the cache |
| 7 | The `log total≈1029232` is the `.fdupm` size/size field | **FAIL (misreading)** — `total` is the runtime's cumulative read counter; `.fdupm` is 8,212 B |
| 8 | The empty `K/WO` map is a PFS decrypt failure | **FAIL / NOT PROVEN** — it is a first-boot incomplete cache; the run then crashes before consumption |
| 9 | A general HFileReader override fixes the observed `K/WO` access | **FAIL as a root fix** — it can bypass the cache *if* `HFileReader::open` is the caller, but it masks the PFS crypto/cache path and is not a PFS fix |
| 10 | The current one-file boot override is safe to keep | **PASS with two caveats** — EOF is not deactivated; the forced open success is not reader-scoped |
| 11 | Key→path mapping is collision-free | **PASS for key→data; caveat for key→path** — 1,776 shared keys, all byte-identical data; 0 duplicate paths |
| 12 | Safest next fix | **Crash first, then probe, then PFS read-through** — not a general HFileReader bypass |

**Overall:** the `K/WO` mapping is solid and is definitely
`products/gt6/script/MenuClassDefine.adc`. The observed `K/WO` access is a
normal-looking raw cache fill from GT.VOL, not a ciphertext/decrypt failure:
the game reads block 0 from `0xAAE000` and the bytes match the entry exactly.
The run then dies in the **Spu Event Handler** before that file is consumed.
A general HFileReader override may bypass that access if `HFileReader::open`
is the caller, but it is still a bypass: it serves plaintext from the host tree
and masks the PFS cipher/inflate path. The boot-script override should stay
one-file.

---

## 1. `K/WO` mapping (PASS)

### 1.1 Exact TOC entry

`work/gt6_volume_entries.txt:30193`:

```
products/gt6/script/MenuClassDefine.adc - Flags: Compressed | FileIndex: 34 (K/WO) |
SegIndex: 5215, ZSize: 00000E24 | Size: 000030B0 | VolIndex: 4294967295
```

The data area and offset are:

```
data_area = align_up(0x800 + TOC_compressed_size, 0x800) = 0x7E800
offset    = 0x7E800 + 5215 * 0x800 = 0xAAE000
ZSize     = 0xE24  = 3,620
Size      = 0x30B0 = 12,464
seed      = FileIndex = 34
```

GT.VOL bytes at `0xAAE000`:

```
39 7A D6 0E E9 94 1F 6D E2 C4 42 3E 57 8B 11 06 ...
```

This matches the log line exactly:

```
work/lab1_final_run.err:258440:
[fs] read fd=3 nbytes=8192 -> 8192 (magic=397AD60E, total=1045636)
```

**PASS.** `fd 3` is GT.VOL (opened at 258386), and the read starts at the
`K/WO` entry offset. The `magic=397AD60E` is the raw entry's first four bytes.

### 1.2 Extract/decrypt and extracted path

This check copied exactly `0xE24` bytes from `0xAAE000` to `%TEMP%\wo_raw.bin`
and ran the repository tool:

```powershell
GTToolsSharp.exe crypt -g GT6 -s 34 -i wo_raw.bin
```

The tool decrypts/decompresses in place. Result:

| Item | Value |
|---|---|
| Output length | **12,464** (`0x30B0`) |
| First 8 bytes | `41 44 43 48 30 31 32 00` (`ADCH012\0`) |
| SHA-256 | `C4144C974A32323ACB65E379DFEC0DAE5383BFA8162A8D3F98538751F3DB9F8D` |
| Extracted file | `work/gt6_vol/products/gt6/script/MenuClassDefine.adc` |
| Extracted size | 12,464 |
| Extracted SHA-256 | same `C414…9F8D` |

**PASS.** The raw entry, seed 34, PS2ZIP stream, and extracted file all agree.

### 1.3 What the file actually is

`MenuClassDefine.adc` is a **v12 ADCH script containing menu class
definitions**, not a world/"WO" asset. Its string table starts:

```
ADCH012\0
&products/gt6/script/MenuClassDefine.ad
main
menu
nil
manager
defined
BasicColormap
...
menu::MBoolAttribute
menu::MIntAttribute
menu::MFloatAttribute
menu::MManager
menu::MActorSet
menu::MSequenceActor
...
```

The boot script explicitly requests it. In `work/gt6_vol/scripts/gt6/main.adc`
at offset 1696:

```
/products/                       (main::PRODUCT_ROOT_DIR reference)
/script/MenuClassDefine
```

So the sequence is: boot `main.adc` finishes, then the script manager loads
`products/gt6/script/MenuClassDefine.adc` (cache key `K/WO`). This is the first
real PFS asset after the boot script, not a random probe.

### 1.4 Three independently verified keys

| Key | FileIndex | Path | SegIndex | Offset | ZSize | Size | Decrypted SHA-256 |
|---|---:|---|---:|---:|---:|---:|---|
| `K/PD` | 33 | `scripts/gt6/main.adc` | 5089 | `0xA6F000` | `0x3EE28` | `0xD15AE` | `5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746` |
| `K/WO` | 34 | `products/gt6/script/MenuClassDefine.adc` | 5215 | `0xAAE000` | `0xE24` | `0x30B0` | `C4144C974A32323ACB65E379DFEC0DAE5383BFA8162A8D3F98538751F3DB9F8D` |
| `K/MO` | 181 | `car/0001/0001/hq/body` | 203130 | `0x18D3B800` | `0x528C` | `0x1B640` | `AC5D4F091CAD2C32FF0CD9E6E149B700F0BB5526ECA9BFD7331E9A929180F38E` |

Each decrypted output is byte-identical to the corresponding file in
`work/gt6_vol`. `K/MO` also confirms the decrypt is not special-cased to ADCH:
it produces the 112,192-byte `MDL3` car body.

---

## 2. `.fdupm` / `.fdupi` behavior (PASS: raw cache; FAIL: "empty map is the decrypt failure")

### 2.1 Correct the log reading

The relevant sequence is:

```
258385: [fs] open '.../PDIPFS_bdmark/K/WO' -> fd 3
258386: [fs] open '/dev_bdvd/PS3_GAME/USRDIR/GT.VOL' -> fd 3
258387: [fs] open '.../PDIPFS/K/WO.fdupm' -> fd 4
258420: [fs] read fd=4 nbytes=20 -> 20 (magic=00000000, total=1029232)
258427: [fs] read fd=4 nbytes=20 -> 20 (magic=00000000, total=1029252)
258428: [fs] open '.../PDIPFS/K/WO.fdupi' -> fd 5
258436: [fs] read fd=4 nbytes=8192 -> 8192 (magic=00000000, total=1037444)
258440: [fs] read fd=3 nbytes=8192 -> 8192 (magic=397AD60E, total=1045636)
```

`total` is a **global cumulative byte counter**, not a file size. It increases
by exactly the read sizes: +20, +20, +8192, +8192. The actual `.fdupm` file is
**8,212 bytes** (20-byte header + 8,192-byte bitmap). The `magic=00000000` is
just the first four zero bytes of the header/bitmap; `.fdupm` has no magic field.

### 2.2 Cache format, proved by a completed cache

A completed example is `K/IK` (FileIndex 31, `sound_gt/se/gt6sys.sgd`,
Uncompressed, SegIndex 4805, Size `0x8BBC0`):

| Object | Value |
|---|---|
| `K/IK.fdupm` size | 8,212 |
| header | `00 00 00 00 00 08 BB C0` (cached length `0x8BBC0` at +4) |
| bitmap after +20 | `FF FF FF FF FF FF FF FF 3F` = bits 0..69 set |
| `0x8BBC0 / 0x2000` | 69.9 → 70 blocks, exactly the 70 bits set |
| `K/IK` size | 572,352 |
| `K/IK` SHA-256 | `DC4B5FD95FB009E9DD6972253C497B3C551865572FE8D8CC2FC373F9BE1C6AC2` |
| GT.VOL at `0x9E1000`, 572,352 B | same SHA-256 |

The whole completed cache file is **byte-identical to the raw GT.VOL entry**.
`K/IK` is produced when `.fdupi` is complete: a 14:45 snapshot of `work/gt6.log`
(line 528 at that time; the log has since been truncated by the 14:49 run)
contains:

```
[cellFs] Rename(from='/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/IK.fdupi',
                to  ='/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/IK')
```

That rename is the cache-completion marker. `K/IK.fdupi` no longer exists;
`K/IK` and `K/IK.fdupm` do. The same mechanism would produce `K/WO` if the WO
read completed. It did not: `WO.fdupi` is 0 bytes and `WO.fdupm` is all zero.

`PD.fdupm` has the same shape with `00 00 00 00 00 03 EE 28` (cached length
`0x3EE28` = `main.adc` ZSize); its map is empty. `PD.fdupi` is contaminated by
the earlier 1:11 plaintext pre-place (857,518 bytes with a raw head), so its
length must not be used as cache truth.

### 2.3 The cache code does not decrypt

The cache functions are in the `0xA3F5E0..0xA422A0` range:

| Address | Role |
|---|---|
| `0xA3F5E0` | predicate: `.fdupi`/`.fdupm` exist |
| `0xA41D80` | create/truncate `.fdupm` (open flags `0x241` = O_WRONLY\|O_CREAT\|O_TRUNC), write 20-byte header + zeroed bitmap |
| `0xA41EB4` | load `.fdupm` header/map |
| `0xA40C08` | load one bitmap page: seek `.fdupm` to `page*0x2000 + 0x14`, read `0x2000` |
| `0xA40984` | write one raw block to `.fdupi`, set its bitmap bit, mark dirty |
| `0xA40FBC` | PFS read: test bitmap bit; on miss read raw `0x2000` from source; on hit serve cache |
| `0xA42108` | attach cache (size, source base offset, path) |
| `0xA40DD4` | close: flush bitmap page, write 20-byte header, close/cleanup |

The read path is explicit:

```
0xA41160  r25 = filepos - cache_base
0xA41168  block = r25 >> 13                 ; 8 KiB block index
0xA4116C  page  = block >> 13               ; bitmap page index
0xA411C4  bit   = map[block >> 3] & (1 << (block & 7))
0xA411D8  if bit == 0:
0xA411DC      fd = [file+0xA0]              ; source (GT.VOL / raw cache)
0xA411E8      seek(fd, cache_base + block*0x2000)
0xA4120C      read(fd, [cache+0x64], 0x2000)
0xA41218      call 0xA40984                 ; write raw block + set bit
0xA41230  else:
0xA41288      memcpy from [cache+0x64] if it is the current block
0xA412A8      else seek/read [cache+4]      ; .fdupi
```

`0xA40984`:

```
r11 = block * 0x2000
r9  = [cache+0x10]              ; cached byte length
if (r11 >= r9) return;          ; 0xA409A8/0xA40A60: no write, no bit
seek([cache+4], r11)
write([cache+4], [cache+0x64], min(0x2000, r9 - r11))
map[block>>3] |= 1 << (block&7) ; 0xA40A40
[cache+0x6C] = 1                ; dirty
```

There is **no cipher and no inflate** anywhere in this range. The cipher
`0x9FF530` is a separate PFS file-handle method, gated at `0x9FF584`:

```
0x9FF584  lwz   r0, 0x144(r3)   ; keyset / decrypt-enable
0x9FF5A0  beq   cr7, 0x9FF9CC   ; skip decrypt, return stored bytes
```

The inflator is `PDISTD::SpuInflator`: `0xA43AB4` calls `0xA440E4`, which
submits to `0xA450A0`/`0xA43C98`; the diagnostic strings at `0x12BAB80` are
`SpuInflatorBase: bad end of block` / `unknown block type`. It is an SPU
workload, not part of `0xA40FBC`.

**Therefore: the cache must store raw `ZSize` bytes, and decryption/inflation
belongs at the PFS file-handle layer above it.** The completed `K/IK` cache
proves the game stores the source bytes verbatim rather than a decrypted or
normalized copy; for a compressed entry those source bytes are
ciphertext + PS2ZIP, and for an uncompressed entry they are still the stored
PFS stream, not the reader's decrypted view.

### 2.4 Is the game using raw bytes or falling back?

The observed 8,192-byte GT.VOL read at `0xAAE000` is the **cache-miss fill**
inside `0xA40FBC`, not a fallback to `work/gt6_vol` and not a decrypt path:

1. `WO.fdupm` is all zero, so the bitmap bit for block 0 is clear.
2. The cache takes the `0xA411D8` source-read branch.
3. It seeks the source to `base + 0` and reads `0x2000`.
4. The bytes are the raw entry (`39 7A D6 0E ...`), matching GT.VOL at
   `0xAAE000`.

No `cellFs` open of `products/gt6/script/MenuClassDefine.adc` or of
`work/gt6_vol` appears in the log. The game is using the raw PFS entry bytes.

**What is not proven:** whether the subsequent `0xA40984` write was skipped
because the in-memory cached length was 0, or whether the process crashed
before the write/bitmap flush. The on-disk `WO.fdupi` is 0 and the map is zero,
but `.fdupm` is 8,212 bytes (the 20+8192 allocation used for a non-zero block
count), so the cache object did know a size at creation. In addition,
`cellFsWrite` in `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp:548` uses
buffered `fwrite`, so a crash can lose pending cache writes. In-session,
`0xA40984` also stores the block index/length at `[cache+0x58]`/`[cache+0x60]`
and the read path can serve the block from `[cache+0x64]` without waiting for
the disk write. A zero-length `WO.fdupi` after a crash is therefore not
sufficient to call it a metadata failure. This needs a probe, not an override.

The run then dies before any consumer:

```
259240: [ppu] unresolved indirect call -> 0x007F454C (tid=15 lr=0x00A56A40)
259253: [GT6] faulted in guest page 0xFFFF0000 (read) -- committed
259259: [GT6] ACCESS VIOLATION: read at host 0x19400000000 (thread 29272)
259261: [GT6] crash is PPU tid=14 name="Spu Event Handler" entry=0x014E14C0
        prof_pc=0x00A564EC hle=sys_lwmutex_lock
```

`0xA564EC` and `0xA569D0` are in the Spu Event Handler (`0xA569D0+0x533` is the
`bctr` with a null OPD). This is the measured next blocker; there is no ADCH
parse of `MenuClassDefine` and no PFS cipher/inflate log after the WO read.

---

## 3. Review of the proposed override (FAIL as a general fix)

No concrete new patch file was present in `patches/` or `work/` at check time.
This section reviews (a) the current one-file override in `gt6/src/stubs.cpp`
and (b) the described general HFileReader / PFS read-through approach.

### 3.1 The layer question

The observed access is:

```
[fs] open '.../PDIPFS_bdmark/K/WO'
[fs] open '.../PDIPFS/K/WO.fdupm'
[fs] open '.../PDIPFS/K/WO.fdupi'
```

This is the **PDIPFS cache layer** (`0xA3F5E0..0xA422A0`). If the script
manager uses the same `HFileReader` loader as `main.adc`, `HFileReader::open`
(`0x9BB11C`) is the caller and that open walks the mount layer into the
PFS/cache code. The log has no generic `HFileReader::open` marker for
`MenuClassDefine`, so two cases are possible:

1. **`HFileReader::open` is the caller** (likely, because `main.adc` uses the
   same loader). A path-keyed override at `0x9BB11C` can intercept
   `/products/gt6/script/MenuClassDefine.adc` and serve the extracted file
   before the `K/WO` cache is touched. In that case it *can* unblock this access.
2. **A lower-level PFS open is the caller** (no HFileReader constructed yet).
   A general HFileReader override is downstream of the cache and cannot serve
   the `K/WO` header/cache read.

The log alone does not distinguish these. A one-line probe at `0x9BB11C`
logging the path (without changing behavior) settles it. Either way, an
HFileReader override is a bypass, not the PFS fix: it never exercises the
cache, cipher, or inflator for the served file.

A PFS read-through at `0xA40FBC` or the file-handle cipher layer is the root
fix, but it must read the raw GT.VOL entry and run the cipher/inflate there.

### 3.2 Per-boot cache rewrites

| Approach | Survives a fresh boot? | Why |
|---|---|---|
| One-file boot script reading `work/gt6_vol/scripts/gt6/main.adc` | **PASS** | Host file; does not touch the cache |
| General HFileReader reading `work/gt6_vol/<path>` | **PASS** | Host tree; cache irrelevant |
| Pre-placed `K/WO.fdupi` / `.fdupm` | **FAIL** | `.fdupm` is opened `0x241` (create+truncate) at `0xA41D80`; `.fdupi` is opened `0x42` (create, no truncate) at `0xA42020`, and the completed `.fdupi` is renamed to `K/WO` |
| Cache-layer key override | **FAIL unless re-applied after truncate** | The game rewrites the pair every boot; the override must not rely on cache contents |

The current boot-script override survives because it opens a host file at
`HFileReader::open` time. That property does not transfer to a cache-key
override.

### 3.3 Multiple files and seeks

The current override is deliberately single-file:

* one global buffer and one `g_script_reader`;
* matches the exact suffix `scripts/gt6/main.adc`;
* serves only when `ctx->gpr[3] == g_script_reader`;
* `0x9BAFE0` seek is treated as **absolute** (`gpr[4]`); the origin in `gpr[5]`
  is ignored, which is correct for the ADCH loader but not a general file API;
* no per-reader table, no close/reopen, no thread safety.

For the boot script this is adequate (the ADCH loader reads sequentially and
seeks absolutely). For a general override it is **FAIL**: multiple HFileReaders
across threads would share `g_script_pos`, a second file opened on the same
reader would be confused with the first, and a `SEEK_CUR`/`SEEK_END` caller
would get the wrong offset. A safe general version needs a small table keyed by
the HFileReader pointer, per-reader host file/position, origin-aware seek, and
close/reopen cleanup.

### 3.4 One-file vs generalize safely

The current one-file behavior is the right scope: **PASS**. Generalizing it to
every HFileReader is **FAIL for production**:

* The extracted tree is complete for the base volume (32,591 files, 0 missing,
  all sizes match the TOC, 25.1 GB total), so a full host-file bypass would
  technically serve the base game.
* But it would hold/mmap 25 GB, need duplicate-key handling (1,776 shared
  keys), and bypass the guest PFS cipher/inflate for every asset.
* It would also bypass file identity/stat/size semantics and any content not in
  `work/gt6_vol`: patch/DLC overlays, `APP_CACHE`, network/install paths, and
  zero-size entries.

### 3.5 Does it mask a PFS decrypt failure?

**Yes.** A host-file override makes `0x9FF530` and `SpuInflator` dead code for
every served file. The base assets may load, but:

* the guest cipher/inflate path remains unvalidated, so the first non-base
  asset (patch/DLC/network) will fail with the same bug;
* the cache/read-through bug is hidden, so there is no signal when the guest
  path is eventually needed;
* HFileReader object state (`+0x1A8/+0x1AC/+0x1B0/+0x1B4`) must be kept
  coherent; serving plaintext without fixing the size/offset fields can make a
  caller over-read or stop early.

Use a host-file override only as an env-gated diagnostic, one exact path at a
time, and delete it when the PFS path works.

### 3.6 Current hardening gaps

`gt6/src/stubs.cpp` is mostly hardened (exact suffix, reader pointer, seek,
`+0x1B4` sync), but:

* **EOF is not final.** At `stubs.cpp:204-207`, EOF returns 0 without clearing
  `g_script_active`. The proposed hardening patch
  (`patches/gt6-pfs-boot-override-hardening.patch`) adds
  `g_script_active = 0`, but the current file does not have it.
* **Forced open success is global.** `gt6/generated/ppu_recomp_022.cpp:91071`
  does:

  ```cpp
  if ((uint32_t)ctx->gpr[3] == 0 && gt6_script_override_active())
      ctx->gpr[3] = 1;
  ```

  `gt6_script_override_active()` is not tied to the current reader/path, so a
  later failed ADCH open (for example `MenuClassDefine.adc`) is converted into
  a forced success and then fails at the read/ADCH check. It does not serve the
  wrong bytes, but it masks the real open failure. Make it
  `gt6_script_override_active_for(reader)` or clear the flag at EOF.
* **Same-path reopen on a reused reader address** returns early at
  `stubs.cpp:138-139` with the old position. A reload of `main.adc` on the same
  reader pointer would start at EOF. Reset the position (or unload/reload) on
  every matching open.

None of these block the current milestone, but they must be fixed before the
override is kept for more than one boot-script load.

---

## 4. Key→path mapping false positives (PASS with caveats)

### 4.1 TOC-wide checks

Over all 32,591 entries in `work/gt6_volume_entries.txt`:

| Check | Result |
|---|---|
| FileIndex → one key label | 0 FileIndexes with more than one label |
| Key → data blob | 1,776 keys shared by 2–155 paths; **all** duplicates have identical `SegIndex`/`ZSize`/`Size` (0 conflicting) |
| Duplicate extracted paths | 0 (case-insensitive too) |
| Extracted files present | 32,591 / 32,591 |
| Extracted sizes vs TOC `Size` | 0 mismatches |
| Keys ending in `/WO` | 23; exact `K/WO` is unique (FileIndex 34) |

So **key→data is unambiguous**: a shared key never means two different blobs.
**Key→single path is ambiguous** for 1,776 keys (e.g. `K/WX` is both
`car/0001/0028/info` and `car/0001/0029/info`, same `0x774EC`/`0x2761`/`0x3EAC`;
one key is shared by 155 paths).
Any alias is byte-identical, but an override that whitelists only one path can
miss a valid alias, and an override that assumes one path per key is wrong.

### 4.2 Substring hazard

`K/WO` is a **suffix** of `58/WO`, `5R/WO`, `5J/WO`, etc. A `strstr(key, "K/WO")`
or a path search for `WO` would hit many unrelated entries. Use an exact
`(K/WO)` label / exact key comparison, never a substring.

### 4.3 Three verified entries

The table in section 1.4 is the independent proof: `K/PD`, `K/WO`, and `K/MO`
all decrypt to byte-identical extracted files. No false positive was found for
an exact key match among those three.

### 4.4 Caveat for the fixer's method

The cache key is not a path. The guest opens `K/WO`; the eventual script path
is `products/gt6/script/MenuClassDefine.adc`. A key→path table built from the
TOC is valid for a cache-layer override, but an HFileReader path override never
sees `K/WO` at all. If the fixer maps `K/WO` to an extracted path and then
expects HFileReader to use it, the mapping is being applied at the wrong layer.

---

## 5. Safest next fix

### Step 1 — fix/contain the actual next blocker first

The process dies in the **Spu Event Handler**:

```
0xA569D0+0x533  bctr with a null OPD
0x007F454C      unresolved indirect call / bogus TOC
0xA564EC        ACCESS VIOLATION, hle=sys_lwmutex_lock
```

No PFS or `K/WO` fix can be validated while the process crashes ~800 log lines
after the first WO block read. Diagnose the `0xA569D0` jump-table/OPD target
and `0x7F454C`; `GT6_CRASH_THREAD_EXIT=1` is containment, not a fix.

### Step 2 — add read-only probes (no behavior change)

Instrument the cache/read path for the `K/WO` request:

| Address | Log |
|---|---|
| `0xA42108` | attach: file id, path, `size` (r5), source base (r6), first 8 bytes of path |
| `0xA40FBC` | read: fd, file position, block, bit value, source fd, bytes read |
| `0xA40984` | write: `[cache+0x10]` size, block, write return, bit set, dirty |
| `0x9FF530` | cipher gate `[+0x144]`, offset, length, first 8 bytes |
| `0xA43AB4`/`0xA440E4` | inflator entry/submit, input/output sizes |

This distinguishes the two remaining hypotheses:

* in-memory `size == 0` → cache write/bit skipped (metadata/attach bug);
* `size != 0` and write succeeded → the crash/flush ordering is the problem.

### Step 3 — keep the boot override one-file; harden it

* Keep the exact `scripts/gt6/main.adc` suffix and reader-pointer checks.
* Add EOF deactivation (`g_script_active = 0`) and make the forced open success
  reader-scoped (`gt6_script_override_active_for(reader)`).
* Do **not** generalize it to every HFileReader.
* If `MenuClassDefine` needs a temporary unblock for triage, add a second
  exact-path entry to the same table, per-reader, env-gated, with origin-aware
  seek and EOF/reopen reset; remove it once the PFS path works.

### Step 4 — if the probe shows the cipher/inflate is skipped, fix the PFS path

The correct general fix is read-through at the PFS file-handle layer:

1. On a cache miss, read `ZSize` raw bytes from GT.VOL at
   `0x7E800 + SegIndex*0x800` (the cache already does the raw part).
2. Decrypt with `FileIndex` as seed (`0x9FF530` or a proven HLE equivalent).
3. Inflate PS2ZIP to `Size` (`SpuInflator` or a host zlib implementation).
4. Serve the `Size`-byte stream to the reader.
5. Keep `.fdupi` raw; never decrypt at the cache/write layer.
6. Add a one-shot guard so a later guest fix cannot double-decrypt.

Validate on `MenuClassDefine` first (`3,620` → `12,464`, ADCH), then on
`main.adc` (`257,576` → `857,518`). Only remove the boot-script override after
`main.adc` succeeds through the guest path.

### Step 5 — do not ship a general HFileReader override

It is a useful diagnostic, but it is not the PFS fix: it bypasses the observed
`K/WO` cache access (if `HFileReader::open` is the caller) rather than repairing
it, and it hides the cipher/inflate path that will be needed for
patch/DLC/network content. Leave it behind an env var and delete it before
shipping.

---

## 6. Evidence index

| Item | Evidence |
|---|---|
| `K/WO` TOC entry | `work/gt6_volume_entries.txt:30193` |
| `K/WO` raw bytes | GT.VOL `0xAAE000`, first 4 `39 7A D6 0E` |
| `K/WO` log read | `work/lab1_final_run.err:258440` |
| Cache opens | `work/lab1_final_run.err:258385..258428` |
| Cache reads | `work/lab1_final_run.err:258420,258427,258436` |
| Spu Event Handler crash | `work/lab1_final_run.err:259240..259261` |
| `K/IK` completed cache | `work/gt6_hdd0/.../PDIPFS/K/IK` (572,352 B), `IK.fdupm` (8,212 B, bitmap `FF…3F`) |
| `IK` rename | 14:45 `work/gt6.log:528` snapshot (log since truncated) |
| Cache init | `0xA41D80` (flags `0x241`), `0xA41EB4`, `0xA40C08`, `0xA40984`, `0xA40FBC` |
| Cache attach | `0xA42108` (size at `+0x10`, source base at `+0x50`) |
| Cipher | `0x9FF530`, gate `0x9FF584`/`0x9FF5A0`, skip `0x9FF9CC` |
| Inflator | `0xA43AB4` → `0xA440E4`; strings `0x12BAB80` |
| Boot override | `gt6/src/stubs.cpp:49-221`; hooks at `gt6/generated/ppu_recomp_022.cpp:68867,68888,68965,91071` |
| Hardening proposal | `patches/gt6-pfs-boot-override-hardening.patch` (EOF deactivation not applied) |

## 7. Caveats

* `work/gt6.log` was truncated by the 14:49 run; the 14:45 `IK` rename line
  number is from the earlier snapshot. The durable evidence is the on-disk
  `K/IK` + `IK.fdupm` pair and its byte-identity with GT.VOL.
* `PD.fdupi` is contaminated by the 1:11 plaintext pre-place and the later
  overwrite. Do not use its 857,518-byte length as the cache's real length; the
  real cache length is `ZSize` (`0x3EE28`).
* The exact reason `WO.fdupi` stayed 0 is not proven by this run. It is
  consistent with either an in-memory size 0 during the first header read or a
  crash before the block write/flush. The probe in Step 2 is required.
* This check did not run `gt6.exe` or build anything. All dynamic claims are
  from `work/lab1_final_run.err` and the existing on-disk cache artifacts.
