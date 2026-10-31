# PFS decrypt / `PD.fdupi` check

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Checked by:** independent checker (read-only; did not edit or build the runtime)
**Supersedes:** the `PD.fdupi` and boot-script-reader sections of
`docs/analysis/pfs-script.md` where they conflict with the later runs below.

## 0. Verdict

| Item | Verdict |
|---|---|
| GT.VOL header/TOC, data-area offset, `main.adc` SegIndex/ZSize/Size | **PASS** |
| Cipher seed 33 and the 857,518-byte `ADCH012\0` script | **PASS** (reproduced with GTToolsSharp) |
| SHA-256 of the extracted script | **PASS** |
| `0x9CD410` reads 8 bytes and compares `ADCH` | **PASS** (disassembly) |
| The reader currently receives raw ciphertext | **NOT CONFIRMED** — it receives **0 bytes / all zeroes** |
| Pre-place a decrypted `PD.fdupi` | **FAIL** — overwritten by the game and not read by the reader |
| Relifting `0x9D7D78` as the read fix | **FAIL (misdiagnosis)** — it is the guest printf `%s` case |
| HLE decrypt at an arbitrary layer | **CONDITIONAL** — only at the PFS virtual-file read layer, for all files |
| Fix the guest PFS decrypt/decompress path | **SAFEST** — if the read path is wired first |

**Overall:** the container/decrypt evidence is solid, but the proposed
"pre-place decrypted `PD.fdupi`" fix is not viable. The first measured blocker is
that `HFileReader::read` returns **0 bytes**; the ADCH comparison never sees
ciphertext. Fix the reader's backing file/mount and the PFS read-through
decrypt/decompress, not the cache file or the ADCH check.

---

## 1. Independent verification of the `pfs-script.md` evidence

All values below were re-derived from the repository files, not copied from the
report.

### 1.1 Volume header and TOC

`VolumeHeader.bin` is 160 bytes, `VolumeTOC.bin` is 844,860 bytes:

| Field | Value |
|---|---|
| Decrypted header magic | `0x5B745162` |
| TOC node index | 11 |
| Compressed TOC | 514,436 (`0x7D984`) |
| Expanded TOC | 844,860 (`0xCE43C`) |
| Serial | 405,868,366 |
| Total volume | 15,407,310,848 (`0x39658E800`) |
| Title | `GT6-PISCINAS-323419048` |
| Decrypted TOC magic | `0x5B74516E` |
| Raw header first 4 | `99 CD DC D6` |
| Raw TOC first 4 at `0x800` | `BA BB E7 68` |

`GTToolsSharp listfiles` independently prints the same TOC index, compressed
size, expanded size and title. The data area is:

```
align_up(0x800 + 0x7D984, 0x800) = 0x7E800
```

**PASS.**

### 1.2 `scripts/gt6/main.adc` entry

`GTToolsSharp listfiles -i ...\GT.VOL` (this checker re-ran it) prints:

```
scripts/gt6/main.adc - Flags: Compressed | FileIndex: 33 (K/PD) |
SegIndex: 5089, ZSize: 0003EE28 | Size: 000D15AE | VolIndex: 4294967295
```

Computed entry offset:

```
0x7E800 + 5089 * 0x800 = 0xA6F000
```

Raw bytes at `0xA6F000`:

```
25 0F FF FE 9B 46 77 B1
```

**PASS.**

### 1.3 Seed 33 and the ADCH output

This checker copied exactly `0x3EE28` bytes from `0xA6F000` to a temp file and
ran the repository's tool:

```
GTToolsSharp.exe crypt -g GT6 -s 33 -i main_0xA6F000.bin
```

Result: **857,518 bytes**, first 8 bytes `41 44 43 48 30 31 32 00`
(`ADCH012\0`), SHA-256:

```
5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746
```

That hash is byte-identical to `work/gt6_vol/scripts/gt6/main.adc` and to
`work/agent_pfs/main_enc.bin`. Note: despite its name, `main_enc.bin` is the
**decrypted 857,518-byte output**, not the raw `0x3EE28`-byte entry.

The logged read length is also consistent:

```
0x3EE28 + 0x8000 read-ahead = 0x46E28 = 290,344
8 * 0x8000 + 0x6E28          = 290,344
```

The earlier `work/agent_pfs/run_fs.err.log` shows exactly that sequence:
eight `32768`-byte reads starting at `0xA6F000` (`magic=250FFFFE` on the
first), then one `28200`-byte read (`magic=618F8349`), total 290,344.

**PASS.** The entry offset, compressed size, cipher seed and PS2ZIP stream are
all correct at the container level.

### 1.4 The raw `PD.fdupi` evidence is now stale

`pfs-script.md` says `PD.fdupi` was 253,952 bytes (`0x3E000`) and byte-identical
to the first `0x3E000` bytes of GT.VOL at `0xA6F000`. That was true when it was
written (1:02), but the file has since been replaced by the fixer's decrypted
copy and then overwritten again by the game:

| Snapshot | Length | First 8 | SHA-256 |
|---|---:|---|---|
| fixer pre-place (1:11) | 857,518 | `41 44 43 48 30 31 32 00` | `5B40…A746` (= `main.adc`) |
| after the 1:18 run | 857,518 | `25 0F FF FE 9B 46 77 B1` | `0FAF977F…4544CF` |

After the 1:18 run, the first **229,376 bytes (`0x38000`)** of `PD.fdupi` match
the raw GT.VOL slice at `0xA6F000`; the first mismatch is at `0x38000`. So the
game's copy path overwrote the pre-placed decrypted head with raw PFS bytes, but
did not shrink the file.

The original 253,952-byte raw file can no longer be re-verified byte-for-byte;
its size is a prefix of the raw entry and the 1:18 run reproduces the same raw
prefix. The 1:02 artifact `work/agent_pfs/mapping_rename_evidence.txt` still
records `PD.fdupi ... byte-identical=True length=253952
first8=250FFFFE9B4677B1`, but the file it described has been overwritten. Mark
the *specific file* in `pfs-script.md` as **historical / not reproducible now**,
not as a false claim.

### 1.5 The cache metadata says the cache is raw and compressed

`work/gt6_hdd0/.../PDIPFS/K/PD.fdupm` is 8,212 bytes. Its first 8 bytes are:

```
00 00 00 00 00 03 EE 28
```

i.e. the size field at offset 4 is `0x3EE28` — the **compressed ZSize**, not the
decompressed `0xD15AE`. The rest of the 8,212-byte file is zero; the block map is
empty. This is metadata for a **raw compressed cache**, not for an 857,518-byte
plaintext file.

This is the strongest single argument against pre-placing a decrypted
`PD.fdupi`: the cache's own metadata describes `ZSize` bytes of stored
(compressed/encrypted) data and an empty block map. A pre-placed plaintext file
does not match the cache format or the metadata.

---

## 2. Exact reader chain: what the 8-byte read targets

### 2.1 Boot-script path

`0x9CD798` builds the script path from `scripts/gt6/main`, appends `.adc`
(`0x1095168`), then calls `0x9CD69C` with the path string. `0x9CD69C`:

```
0x9CD6D8  bl 0x9BB7E0     ; construct HFileReader
0x9CD70C  bl 0x9BB11C     ; HFileReader::open(path)
0x9CD728  bl 0x9CD410     ; ADCH check / adhoc code load
```

`0x9BB11C` calls `0x9F4218 -> 0x9F4130 -> 0x9F6BF4 -> 0x9F8E40`. `0x9F8E40` is
the guest's **mount/file factory**: it normalizes the path, walks a mount list at
`0x15DE908`, and calls the matching mount's `open` virtual. If no mount matches,
it returns 0 and the HFileReader device has no file object.

### 2.2 The 8-byte read

`0x9CD410`:

```
0x9CD44C  bl 0x9D9604     ; HStreamReader(this=stack+0x90, HFileReader)
0x9CD464  bl 0x9D8DB0     ; HStreamReader::read(buf=stack+0x88, n=8)
0x9CD478  bl 0xB9AB6C     ; memcmp(first 4, "ADCH", 4)
```

`0x9D8DB0` loads the underlying stream at `0(stream)` and calls `0x994078`.
`0x994078` is the buffered stream reader; when its buffer is empty it dispatches
through the underlying object's vtable slot `+0x11C`. For the HFileReader vtable
`0x1484CC8`, that slot is OPD `0x14DCB18 -> 0x9BB020` (`HFileReader::read`).

`0x9BB020` calls `0x9F4AA0(HFileReader+0x30, buf, n, 1)`, which calls
`0x9F3E90(HFileReader+0x30)`:

```
0x9F3E90: lwz r0,0x44(r3)   ; device
          lwz r3,0x40(r0)   ; underlying file object
```

If the device pointer is null or its `+0x40` file object is null, `0x9F4AA0`
returns `-1`; `0x9BB020` then returns 0 bytes. If the device read returns 0
(empty file/EOF), it also returns 0 bytes. Because `0x9BB11C` returned 1 in the
measured run, a mount/file object was found at open time; the 0-byte read is
therefore at least as likely to be an empty cache/EOF as a total mount miss.
The instrumentation in Step 2 distinguishes the two.

**Therefore the 8-byte read targets the virtual file `scripts/gt6/main.adc`
(PFS FileIndex 33, K/PD) through `HStreamReader -> 0x994078 -> HFileReader::read`
and its file/mount device, not a raw `PD.fdupi` cellFs fd.** The `PD.fdupi` open
is done by the PDIPFS cache layer alongside this, but the read itself is the
HFileReader chain above.

After the 8-byte check, `0x9CD5EC` passes the **same HStreamReader** to the
script object's loader virtual (vtable `+0x24`), and `0x9CC208` later executes
it. The reader is consumed sequentially from offset 0.

**Substitution answer:** a decrypted ADCH buffer can be substituted safely only
by replacing the **entire backing stream** at the HFileReader/device layer, with
the full 857,518-byte script and correct length/EOF, so the 8-byte read, the
12-byte version read and the parser all consume the same consistent stream.
That is still a per-file bypass. Replacing only the 8-byte buffer (or patching
the `memcmp` at `0x9CD478`) cannot work: the parser continues from the same
stream and would read ciphertext/zeroes after the fake header.

### 2.3 Measured result in the 1:18 run

```
1098: [fs] open '.../PDIPFS/K/PD.fdupi' -> fd 6
1099: [scriptload] 9BB11C ret=0x1 reader=0x7FFD61E0
1100: [read994078] this=0x7FFD61E0 err=0x0 buf=0xCFEF7098 n=8
1101: [read994078] ret=0x0
1102: [scriptload] ADCH read ret=0 at 0xCFEF7098: 00 00 00 00 00 00 00 00
```

`0x9BB11C` says the open succeeded, but `HFileReader::read` returns **0 bytes**
and the buffer remains zero. The ADCH comparison fails on zeroes, not on
`25 0F FF FE`.

The raw GT.VOL copy starts much later:

```
2504: [fs] read fd=4 nbytes=8192 -> 8192 (magic=250FFFFE, ...)
```

so the cache/copy path has not produced data by the time the boot script is
read. The file is later filled with raw bytes (section 1.4).

**The current first failure is a 0-byte read, not a ciphertext header.** The
original H1 ("the reader gets the raw stream") may still be the next failure
after the read is wired, but it is not what the measured run shows.

### 2.4 `0x9D7D78` is printf `%s`, not the file read

The running log shows:

```
1103: [ppu] unresolved indirect call -> 0x009D7D78 (tid=1 lr=0x009D7BE8)
```

`0x9D7D78` is a case in the **guest printf format switch**, not a file-read
function:

* the function at `0x9D7B00` parses a format character and switches on
  `char - 'E'` via the table at `0x9D7C1C`;
* table index 46 (`'s'`) is `0x9D7D78`;
* the code at `0x9D7D78` builds a `std::string` from the argument and adds its
  length to the output count — the `%s` conversion.

The error string at `0x10950D8` is:

```
stream is not adhoc script code. HEADER([%s] != [ADCH])
```

so the unresolved `0x9D7D78` is the `%s` in the **error message** that is being
formatted after the ADCH failure. Adding `0x9D7D78` to the lift list fixes the
error text; it does **not** fix the 0-byte read. This should not be treated as
the next fix for the script load.

---

## 3. Does the game overwrite a pre-placed `PD.fdupi`?

**Yes.** The relevant behavior is split across two implementations.

### 3.1 `ppu_fs.cpp` (the active handler for `[fs]` opens)

`cellFsOpen` (`third_party/ps3recomp/runtime/ppu/ppu_fs.cpp:265-346`) converts
the PS3 flags directly:

```c
int acc = flags & 0x3;
int oflags = (acc == CELL_FS_O_RDWR) ? O_RDWR : ...;
if (flags & CELL_FS_O_CREAT) oflags |= O_CREAT;
if (flags & CELL_FS_O_TRUNC) oflags |= O_TRUNC;
...
int hfd = open(hpath, oflags | O_BINARY, 0666);
```

For `flags = 0x42` (`O_RDWR | O_CREAT`), this is `open(path, O_RDWR|O_CREAT)`
with **no `O_TRUNC`**. An existing file is opened and writes start at the
current offset (0 unless the guest seeks). On failure the handler maps
everything to `CELL_FS_ENOENT` (line 307), so a read-only file looks like a
missing file to the guest.

`cellFsUnlink` is a stub that returns success without deleting anything
(`ppu_fs.cpp:857`), so a pre-placed file cannot be cleared by the guest's normal
delete-then-create sequence.

### 3.2 `cellFs.c` (used by rename; not the active open handler here)

`flags_to_mode` (`third_party/ps3recomp/libs/filesystem/cellFs.c:379-401`) maps
RDWR+create-without-truncate to `"a+b"` (append/create, no truncate), and
`cellFsWrite` uses `fwrite` at the append position. If this handler were active,
a pre-placed file would have raw data **appended after** the decrypted bytes.
The logs use the `[fs]` prefix from `ppu_fs`, so `ppu_fs` is the active open
handler; the append behavior is not the one observed.

### 3.3 Observed consequence

The 1:18 run opened the pre-placed decrypted `PD.fdupi` successfully (`fd 6`),
then the reader returned 0. After the run:

* length stayed 857,518 (the pre-place size);
* the first 229,376 bytes were raw GT.VOL data (`25 0F FF FE...`);
* the tail remained the pre-placed decrypted data.

So the game neither preserves the plaintext nor truncates to the cache's
`0x3EE28` size. It overwrites from offset 0 with raw PFS bytes, which destroys
the ADCH header, and the stale plaintext tail can confuse a reader that uses the
metadata size.

The cache metadata (`PD.fdupm`) also stayed at `ZSize = 0x3EE28` with an empty
block map. Pre-placing only `PD.fdupi` does not make the cache valid; a usable
cache also needs a block map that says which ranges are present. An empty block
map is consistent with the reader treating the cache as having no data, which
is one explanation for the 0-byte read even before the head was overwritten.

**Verdict: pre-place decrypted `PD.fdupi` FAILS.** It does not survive a fresh
run, does not match the cache format, and is not the reader's data source in the
current wiring.

---

## 4. Review of the candidate fixes

### A. Pre-place a decrypted `PD.fdupi`

**FAIL.**

1. The game opens `PD.fdupi` with `0x42` every boot and writes raw PFS bytes
   from `GT.VOL` over it (observed: first 229,376 bytes replaced).
2. A read-only pre-place makes that open fail; the guest maps the failure to
   `ENOENT` and the reader returns 0 (1:13 run).
3. The cache metadata says `ZSize = 0x3EE28` with an empty block map; a
   plaintext 857,518-byte file is the wrong format/size.
4. Even if it were read, it fixes only K/PD; every other compressed file still
   goes through the missing decrypt/decompress.
5. It masks the real failure and can produce a later, harder-to-diagnose asset
   error.

### B. Read a decrypted host file (override the reader)

**DIAGNOSTIC ONLY, not a fix.**

It can prove the parser works, but it must replace the **entire stream** with a
correct-length plaintext stream, not the 8-byte header. It bypasses the PFS
decrypt for one file and does not help any other asset. If used, put it behind a
debug env var and remove it after the read path is validated.

### C. HLE decrypt

**CONDITIONAL.** Valid only at the **PFS virtual-file read layer** (or the
HFileReader device read), where the raw cache/GT.VOL bytes are turned into the
file stream. It must:

* use the entry's `FileIndex` as the cipher seed (`33` for K/PD);
* decrypt the `ZSize` bytes and PS2ZIP-decompress to `Size`;
* apply to every file, not just `main.adc`;
* not run if the guest decrypt branch is fixed later, or it will double-decrypt.

Do **not** HLE-decrypt at the `PD.fdupi` write/cache layer: the cache is
supposed to hold raw compressed data, and the metadata proves it.

### D. Fix the skipped guest decrypt branch

**SAFEST / most general**, if the branch exists and the reader is wired. The PFS
layer already reads the volume and TOC; the missing step is the file-data
decrypt/decompress when the virtual file is read. Fixing that benefits all 4,207
entries and survives fresh runs.

However, do it **after** fixing the 0-byte read. The current run has no data at
all; a decrypt fix cannot decrypt zero bytes. First make `HFileReader::read`
return the raw `ZSize` stream (or a valid file object), then decrypt/decompress
it.

### E. Relift `0x9D7D78`

**NOT A FIX for the load.** It is the printf `%s` case used by the ADCH error
message (section 2.4). It may be needed for readable errors, but it will not
change the 0-byte read or the ADCH result.

---

## 5. Safest recommended fix

### Step 1 — clean the test state and restore the raw cache

Remove the pre-placed/stale cache artifacts so they cannot mask behavior:

```
work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/PD.fdupi
work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/PD.fdupm
work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS_bdmark/K/PD
PS3-Version/.../game/BCUS98296/USRDIR/PDIPFS/K/PD.fdupi   (stale copy)
PS3-Version/.../game/BCUS98296/USRDIR/PDIPFS/K/PD.fdupm   (stale copy)
```

Do not pre-place a decrypted file. If a pre-place test is repeated, make the
file writable and replace **both** `.fdupi` and `.fdupm` with a consistent
raw-cache pair; otherwise the result is meaningless.

### Step 2 — instrument the reader, not the ADCH compare

Log, in `gt6/generated/ppu_recomp_022.cpp`:

* the path string passed to `0x9CD69C` / `0x9BB11C` (guest pointer at
  `0xCFEF8268` in the current run);
* the return of `0x9F8E40` (mount match) and the value of `device+0x40`
  (`HFileReader+0x74 -> +0x40`);
* the return of `0x9F4AA0` and the virtual target at `0x994120` (`+0x11C`);
* the first 8 bytes returned by `0x9BB020`.

This distinguishes "no file object/mount" from "empty cache/EOF" from
"ciphertext". The current log only proves the read returned 0.

### Step 3 — wire the file/mount and implement read-through decrypt

1. Ensure the relative `scripts/gt6/main.adc` path matches a mount in
   `0x9F8E40`'s list and opens the PFS `K/PD` entry (FileIndex 33).
2. On a cache miss, read `ZSize` bytes from GT.VOL at
   `0x7E800 + SegIndex*0x800`, decrypt with seed `FileIndex`, PS2ZIP-decompress
   to `Size`, and serve that stream to `HFileReader`.
3. Cache the raw compressed bytes in `PD.fdupi` only if the metadata block map
   is updated consistently; decryption stays on the read side.
4. Do not patch `0x9CD410` to accept ciphertext and do not fake only the 8-byte
   header; the same `HStreamReader` is passed to the parser.

### Step 4 — verify

Expected after the fix:

```
[scriptload] ADCH read ret=8 at ...: 41 44 43 48 30 31 32 00
[scriptload] 9CC208 -> nonzero
```

and no `9CDEEC` failure. Then let the script request its first asset, map the
new GT.VOL `fpos` to its entry, and confirm the same decrypt/decompress path is
used. A fresh run with no pre-placed cache files must still work.

---

## 6. Evidence-quality notes

* `pfs-script.md`'s `PD.fdupi` byte-identity claim is **stale**: the file was
  replaced at 1:11 and overwritten by the game at 1:18. Preserve a raw copy
  before any pre-place experiment.
* `work/gt6.log` is a live, growing file and the fixer has run concurrently;
  line numbers can move. The quotes above are from the 1:18:41 snapshot. Use a
  dedicated log per run for future checks.
* `work/agent_pfs/main_enc.bin` is the **decrypted** 857,518-byte output, not the
  raw `0x3EE28`-byte entry; the name is misleading.
* The `/dev_hdd0` root alignment is working for the cache paths in the 1:18 run
  (`PD.fdupi`/`PD.fdupm` resolve under `work/gt6_hdd0`), and
  `work/gt6_hdd0/.../PDIPFS/K/4D` and `E9` exist from the earlier successful
  rename. The current log does not contain a rename line, so do not use it as a
  fresh rename test.
