# FileDevice null virtual call — independent check

**Date:** 2026-10-31
**Scope:** `0x9F3E90` / `0x9F44D8` / `0x9F4550`, the K/W2 cache pair, the
cellFs HLE patch, and the new FileDeviceHost lifetime patch. Read-only: no
build, no `gt6.exe`, no generated-file edit by this check.
**Inputs:** `work/bin/EMAIN.elf`, `gt6/generated/ppu_recomp_022.cpp` /
`_023.cpp`, `work/pfstrace.err`, `work/flush_run.err` / `work/flush_long.err`,
`work/build_flushfix.log`, `gt6/GT.VOL` (fresh GTToolsSharp 5.3.5 listing),
`work/gt6_hdd0/.../PDIPFS/K/W2*`,
`docs/analysis/pfs-cache-write-fix.md`,
`docs/analysis/filedevice-null-vcall-fix.md`,
`patches/gt6-filedevice-flush-guard.patch`,
`patches/ps3recomp-cellfs-pdipfs.patch`.
**Policy:** `third_party/PDTools` was not read or used.

## 0. Bottom line

| Question | Verdict |
|---|---|
| Is `0x9F4550` a null virtual call through a vtable slot whose value is `4`? | **The value-4 reading is FAIL.** At the call `r9` (vtable pointer) and `r11` (OPD pointer) are both **0**; the slot is never read. The `4` in the log is `r12`, which this function uses as the saved condition register. |
| Is the call a missing lift? | **No.** `0x9F44D8` contains the `bctrl` at `0x9F4550`; it is intra-function. The real target of slot `+0x8C` is `0xA0043C` (`PDIPFS::FileDevicePFSBase::read`), which is in the ELF and in the lift table. |
| Why is the vtable null? | **Stale `FileStream` pointer.** `PDIPSX::FileDeviceHost` init (`0xA08A00`) constructs a `PDISTD::FileInternalStreamDefault` on its own stack, publishes its address at `+0x1C2C`, then destroys it and returns. The Flush pump (`0xA08ADC`) reloads that dead pointer. On reused stack, `[File+0x40]` is `0x70`, not a `FileDevice`; `[0x70]` is 0. |
| Is the fixer's new patch a real fix or a mask? | **A real lifetime fix.** It clears `+0x1C2C` after the local is destroyed and makes a Flush with no active read a no-op. It does not fabricate a target and leaves an active-read path unchanged. Residual risks are listed in §3.4. |
| Does the cellFs HLE patch fix or mask this? | **Neither.** It is orthogonal; it does not touch the dispatch. It preserves the guest cache read/write gates. |
| Is K/W2's raw cache length 59,991 (`0xEA57`)? | **PASS.** TOC row, GT.VOL slice, hash and `.fdupm` header agree. 239,744 is the decompressed read-side `Size`, not the cache length. |
| Is K/W2 currently a successful cache? | **FAIL at check time, including after the patch.** `W2.fdupi` is 59,991 bytes but all zeroes (SHA-256 `7b5c0196…8362`), and `W2.fdupm` has `blocks=0`. Post-patch runs (`flush_run.err`, `flush_long.err`, 16:56/16:58) show the `0x9F4550` null call is **gone**, but fd 5 is opened, allocated to 59,991, and closed with **no read or write**. The allocate-only state remains. |
| Safest next step | The null call is fixed; the remaining blocker is the missing read trigger. Trace who opens/reads K/W2 at the HFileReader/`StartRead` layer and why it closes the cache file without a read. Keep the `0xA40FBC`/`0xA40984` probe and require a byte-identical 59,991-byte cache. Do **not** add a lift or patch a vtable slot. |

## 1. The null dispatch

### 1.1 Guest disassembly (verified from `work/bin/EMAIN.elf`)

`0x9F3E90` is `FileStream::get_device()`:

```
0x9F3E90  lwz   r0, 0x44(r3)      ; stream->m_file
0x9F3E94  li    r3, 0
0x9F3E98  cmpwi cr7, r0, 0
0x9F3E9C  clrldi r9, r0, 32
0x9F3EA0  beq   cr7, 0x9F3EA8
0x9F3EA4  lwz   r3, 0x40(r9)      ; file->m_device
0x9F3EA8  clrldi r3, r3, 32
0x9F3EAC  blr
```

`0x9F44D8` takes that result and calls the device's virtual `+0x8C`:

```
0x9F44D8  mfcr   r12              ; <-- r12 = CR, saved at [r1+0x98]
...
0x9F4508  lwz    r30, 4(r3)
...
0x9F451C  mr     r3, r31
0x9F4520  bl     0x9F3E90          ; r3 = stream->m_file->m_device
0x9F4524  mr     r4, r31          ; arg2 = this (FileStream*)
0x9F4528  mr     r9, r3
0x9F452C  clrldi r5, r29, 32      ; arg3 = {offset,length}
0x9F4530  cmpwi  cr7, r9, 0
0x9F4534  clrldi r3, r3, 32
0x9F4538  beq    cr7, 0x9F4558    ; null device -> skip call
0x9F453C  lwz    r9, 0(r9)        ; File->vtable
0x9F4540  lwz    r11, 0x8C(r9)    ; FileDevice->vtable[+0x8C]
0x9F4544  lwz    r0, 0(r11)       ; code
0x9F4548  lwz    r2, 4(r11)       ; TOC
0x9F454C  mtctr  r0
0x9F4550  bctrl                   ; <-- null target
```

The read path is confirmed by the vtable and by the argument shape:
`0x9F44D8` passes `r5 = [FileDeviceHost+0x1C30]`, a `{offset,length}` request
pair; `0xA0043C` reads that pair before calling `0xA40FBC`. An open method would
take a path string, not this pair.

### 1.2 The lift is faithful; `r12` is not the OPD

`gt6/generated/ppu_recomp_022.cpp:137637` (`func_009F44D8`) emits:

```c
ctx->gpr[12] = ctx->cr;                         /* line 137643 */
...
vm_write32(ctx->gpr[1] + 0x98, ctx->gpr[12]);
...
ctx->gpr[9] = vm_read32(ctx->gpr[9] + 0x0);     /* 0x9F453C */
ctx->gpr[11] = vm_read32(ctx->gpr[9] + 0x8C);   /* 0x9F4540 */
ctx->gpr[0] = vm_read32(ctx->gpr[11] + 0x0);
ctx->gpr[2] = vm_read32(ctx->gpr[11] + 0x4);
ctx->ctr = ctx->gpr[0];
ctx->lr = 0x009F4554; ps3_indirect_call(ctx);
```

The runtime log:

```
[null-call] ... near lr=0x009F4554 ... r3=00000070 r9=00000000
            r10=00000000 r11=00000000 r12=00000004
[ppu] bctr to NULL from func_009F44D8+0x65C r12(opd)=0x00000004
      opd[0]=0x00000000 (r3=0x00000070 r4=0xCFEFE338 tid=5)
```

Consequences:

1. `r9 == 0` at `0x9F453C`, so `[File]` is null. There is **no vtable slot
   read**.
2. `r11 == 0`, so `[vtable+0x8C]` is not `4`; `4` is `r12 = CR`
   (`mfcr r12` at entry, saved to `[r1+0x98]`).
3. `opd[0]=0` is read from address `4`, i.e. from `r12`, not from the real OPD.
   The diagnostic's `r12(opd)=…` convention applies to lifted import thunks,
   not to this guest `bctrl`.
4. `func_009F44D8+0x65C` is a **host** code offset from
   `ppu_guest_caller()`'s stack scan, not a guest address. The reliable guest
   call site is `lr = 0x009F4554`.

So the fixer's original "slot `+0x8C` contains `0x00000004`" wording in
`pfs-cache-write-fix.md` was a misreading. The fixer's later
`filedevice-null-vcall-fix.md` §1 corrects exactly this point and reaches the
right root cause.

### 1.3 Object identity and the correct slot alignment

RTTI strings in the ELF confirm the classes:

| Address | String |
|---|---|
| `0x10977F0` | `N6PDISTD10FileStreamE` — `PDISTD::FileStream` |
| `0x1097F40` | `N6PDIPSX14FileDeviceHostE` — `PDIPSX::FileDeviceHost` |
| `0x1097BF0` | `N6PDIPS317FileDevicePFSBaseE` — `PDIPFS::FileDevicePFSBase` |
| `0x1097FA8` | `N6PDISTD17FileObjectDefaultE` — `PDISTD::FileObjectDefault` |

The PFS device vtable is `0x1488AB8`. The anchor is the destructor `0x9FEDC8`,
which stores `lis 0x149; addi -0x7548` = `0x1488AB8` into `[this]`:

```
0x1488AB0: 00000000        ; offset-to-top
0x1488AB4: 01488BA8        ; typeinfo pointer (vtable-4)
0x1488AB8: 014DF908        ; slot 0 -> 0x9FEDC8
...
0x1488B40: 014DFA80        ; +0x88 -> 0xA010C0 (open)
0x1488B44: 014DF9F8        ; +0x8C -> 0xA0043C (read)
0x1488B48: 014DF5F8        ; +0x90 -> 0x9F82C0
```

`0x1488AB4` is the **typeinfo word at vtable-4**, not the vtable base. This
check's earlier draft used `0x1488AB4` as the base and therefore shifted the
table by four bytes; the fixer's `-4` correction is right. With the real base:

| Slot | OPD | Code | Role |
|---|---|---|---|
| `+0x88` | `0x14DFA80` | `0xA010C0` | open |
| `+0x8C` | `0x14DF9F8` | `0xA0043C` | **read -> `0xA40FBC`** |
| `+0x90` | `0x14DF5F8` | `0x9F82C0` | next virtual |

The outer `FileStream` vtable `0x1488168` and the `File` vtable `0x1488218` are
also data-resident and absolute; the latter has `+0x40` as the `m_device` field
(cleared by its constructor / `0x9F5F48`). The failure is not a table base.

### 1.4 Lift-table check

All relevant functions are present in
`work/analysis/emain/functions_corrected_lab2.json` (70,985 entries):

| Function | Lift range |
|---|---|
| `0x9F3E90` getter | `0x009F3E90..0x009F3EB0` |
| `0x9F44D8` read wrapper | `0x009F44D8..0x009F4590` |
| `0xA0043C` PFS read | `0x00A0043C..0x00A00550` |
| `0xA40FBC` cache read | `0x00A40FBC..0x00A41504` |
| `0xA40984` cache write | `0x00A40984..0x00A40A7C` |
| `0xA08A00` device init | `0x00A08A00..0x00A08ADC` |
| `0xA08ADC` pump | `0x00A08ADC..0x00A08B8C` |
| `0xA08B8C` Flush | `0x00A08B8C..0x00A08BA0` |
| `0x9FEDC8` PFS base destructor | `0x009FEDC8..0x009FEDF8` |

`0x9F4550` is `0x9F44D8 + 0x78`; it is an intra-function `bctrl` and must not
be added as a function start. The expected `+0x8C` target `0xA0043C` is
lifted; there is no missing target.

### 1.5 Conclusion for the dispatch

The call is a null **object** dereference: the stream is a dead stack local, so
`m_file` points at reused bytes whose `+0x40` is `0x70`, not a `FileDevice`.
`r9 = [0x70] = 0`, and the intended slot `+0x8C = 0xA0043C` is never read.
This is a guest object-lifetime bug, not a missing lift and not a vtable-data
problem.

## 2. Why the object is stale

`0xA08A00` is `PDIPSX::FileDeviceHost` init. It constructs a
`PDISTD::FileInternalStreamDefault` in its own stack frame and publishes that
stack address:

```
0xA08A0C  addi r27, r1, 0x70        ; &local
0xA08A2C  bl   0x9F4384             ; local constructor
...
0xA08A60  stb  r0, 0x1C28(r29)      ; flush requested = 0
0xA08A74  stw  r27, 0x1C2C(r29)     ; this->m_stream = &local  <-- stack address
...
0xA08AB4  bl   0x9F42D8             ; local destructor
0xA08AD8  blr                       ; local is now dead
```

`0xA08B8C` is the Flush entry:

```
0xA08B8C  mr   r9, r3
0xA08B90  li   r0, 1
0xA08B98  stb  r0, 0x1C28(r9)       ; flush requested = 1
0xA08B9C  b    0xA08ADC             ; pump (tail call)
```

`0xA08ADC` reloads `+0x1C2C` and calls `0x9F44D8`. The measured `this`
`0xCFEFE338` is a stack address of the main/init thread; by the time tid 5
pumps, that stack has been reused:

* `[stream+4] = 0x20` -> `[LWM] lock: non-guest lwm=0x00000020 ... ESRCH`
  in the lock at `0x9F4518`;
* `[stream+0x44] = <reused pointer>`;
* `[File+0x40] = 0x70` -> `[0x70] = 0`, so the `+0x8C` load is from address 0.

The same stale object appears earlier with a null stream:
`[null-read] ... 0x00000004 by 0x009F44D8` and `... 0x00000044 by
0x009F3E90`. With a null stream the `beq` at `0x9F4538` skips the call; with
the reused stream it does not.

### 2.1 The read-active flag

`PDIPSX::FileDeviceHost` keeps two bytes next to the stream pointer:

| Offset | Written by | Meaning |
|---|---|---|
| `+0x1C28` | `0xA08B8C` = 1; `0xA08A00` / `0xA08DBC` = 0 | flush requested |
| `+0x1C29` | `0xA08ED0` = 1; `0xA09130` / `0xA08DBC` = 0 | read active |
| `+0x1C2C` | `0xA08A74` (stack local); `0xA08ED0` (live caller stream) | `FileStream*` |

`0xA08ED0` (`StartRead`, vtable `+0x10`) installs the caller's live stream and
sets `+0x1C29 = 1`; `0xA09130` clears it on completion. A Flush with
`+0x1C29 == 0` has nothing to drain, but the unpatched code sets `+0x1C28`
anyway and pumps the dead `+0x1C2C` forever (the pump only exits when
`+0x1C28` is cleared, and only init/reset paths clear it).

## 3. Review of the fixer's patch

### 3.1 What the patch changes

`patches/gt6-filedevice-flush-guard.patch` / `tools/gt6_filedevice_flush_patch.py`
make two generated-code edits:

```c
/* func_00A08A00, after the stack local is destroyed at 0xA08AB4 */
vm_write32(ctx->gpr[29] + 0x1C2C, 0); /* local FileInternalStreamDefault is destroyed */

/* func_00A08B8C, at entry */
if (vm_read8(ctx->gpr[3] + 0x1C29) == 0) return; /* no read active: nothing to flush */
```

The tool is idempotent, is wired into `tools/apply_gt6_post_lift.py`, and is
checked by `tools/post_lift_fixes.py`. The checked-in generated tree currently
contains both edits (`ppu_recomp_023.cpp` lines 13682 and 13750-51), and
`python tools/gt6_filedevice_flush_patch.py --check gt6/generated` reports
`FileDeviceHost guard OK`. The patch header still says "NOT applied to the
checked-in generated tree"; that sentence is stale relative to the current
tree, but the tool/verification behavior is correct.

### 3.2 Does it fix a real missing target or mask a null pointer?

**It fixes a real lifetime bug and does not fabricate a target.**
The crash is not "slot `+0x8C` is missing"; it is "the object has no vtable."
The patch removes the use-after-free:

* clearing `+0x1C2C` when the local dies is the C++ lifetime rule;
* the `+0x1C29` guard suppresses a Flush that has no read to drain; the
  unpatched code would otherwise pump the dead pointer and spin on `+0x1C28`.

It does **not**:

* add `0x9F4550` to the lift table;
* synthesize an OPD for `+0x8C`;
* clamp `0x70` or redirect the call to `0xA0043C` while the object is bad.

An active read is unchanged: when `+0x1C29 == 1`, the guard falls through to the
original body, and `StartRead` has already installed the live stream at
`+0x1C2C`.

### 3.3 Does it preserve the cache read/write gates?

**Yes.** It touches only the FileDeviceHost lifetime/Flush path. The guest
cache gates are untouched:

```text
0xA409A8  block * 0x2000 >= cache->size      -> return
0xA409E8  cache->last_error != 0             -> return
0xA409F8  lseek(fd, block*0x2000) != 0       -> return
0xA40A18  write(fd, buf, len) != 0           -> return
0xA40A40  bitmap bit |= 1 << (block & 7)
0xA40A4C  dirty = 1
0xA40A54  blocks++
```

The patch enables the existing read path to reach `0xA0043C -> 0xA40FBC`; it
does not set the bitmap or the count. The cellFs HLE patch is also orthogonal:
it sizes `.fdupi`, flushes cache writes, and implements rename/unlink, but the
block publication still happens only after the guest's four gates pass.

### 3.4 Residual risks / caveats

1. **`+0x1C28` is not cleared by the pump.** If a Flush runs with
   `+0x1C29 == 1` and the read fails before completion, the pump can still
   loop on `+0x1C28`; the patch only covers the no-read case. This is the
   same limitation the fixer states in `filedevice-null-vcall-fix.md` §9.
2. **Active-read caller lifetime is not proven.** The guard assumes a
   `FileStream` passed to `StartRead` outlives the asynchronous read. If a
   future run shows a stale `+0x1C2C` with `+0x1C29 == 1`, that is a separate
   caller-lifetime bug; log `+0x1C2C`, `+0x1C29`, and the `StartRead` caller.
3. **The patch is generated-code-only.** A relift must run
   `apply_gt6_post_lift.py`; `post_lift_fixes.py` fails the relift if the guards
   are missing. That is wired, but the patch is not visible in the guest ELF
   and cannot be verified without rebuilding.
4. **The post-patch runs remove the null call but do not fill the cache.** The
   patched build (`work/build_flushfix.log`, 16:54) was run twice
   (`work/flush_run.err`, `work/flush_long.err`). Both show **no**
   `bctr to NULL from ... 0x009F4550` and no `[LWM] lock: non-guest
   lwm=0x00000020`. `flush_long.err` shows the K/W2 sequence:
   `.fdupm` read/header, map re-init (0x241), `.fdupi` opened 0x42, allocate
   `size=0xEA57 -> OK`, then `.fdupi` **closed at 59,991 with no read/write**,
   then the map header written and closed. The map ends with `blocks=0`.
   The patch fixes the measured lifetime fault; it does not supply the missing
   read request. That is the next blocker, not the dispatch.

### 3.5 CellFs HLE caveats (not the null-call cause)

* `cellFsUnlink` returns `CELL_OK` for `EACCES`/`EBUSY` and leaves the file.
  For `.fdupm` this can leave a stale map after completion. A post-run check
  must not treat a leftover map as proof of a guest write.
* `cellFsRename` removes an existing destination before `rename`; Windows
  refuses if the destination is still open. On K/W2 the completion destination
  is the bare `K/W2`, not the bdmark file, so this is low risk, but it is not
  an atomic POSIX replace.
* `cellFsAllocateFileAreaWithoutZeroFill` returns `CELL_FS_ENOENT` for every
  failure, not the actual `errno`. It sizes the file with `_chsize_s` /
  `ftruncate`; for a fresh cache that creates zeroes, which is acceptable for
  this format but means size alone is never proof of data.

## 4. K/W2 raw size, offset and format

### 4.1 TOC and GT.VOL slice

Fresh GTToolsSharp 5.3.5 listing of `gt6/GT.VOL` (not the checked-in text
file):

```text
projects/gt6/cursor/gpb/CursorProject.gpb - Flags: Compressed |
FileIndex: 58 (K/W2) | SegIndex: 6548, ZSize: 0000EA57 |
Size: 0003A880 | VolIndex: 4294967295
```

Container math:

```text
data area base 0x7E800
offset         0x7E800 + 6548 * 0x800 = 0xD48800
raw length     ZSize = 0xEA57 = 59,991
logical length Size  = 0x3A880 = 239,744
```

Direct read of `gt6/GT.VOL` at `0xD48800`, 59,991 bytes:

```text
first 16   27 FD F1 57 AE 6E B5 CA 26 8B 5A 60 93 29 31 C8
last 16    01 8D 7B 06 A2 E2 07 CB F8 FA 76 D9 C2 26 A4 C4
SHA-256    2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

The extracted read-side file is:

```text
work/gt6_vol/projects/gt6/cursor/gpb/CursorProject.gpb
length     239,744
first 16   33 62 70 67 00 00 00 00 00 00 00 20 00 00 00 14   ("3bpg")
SHA-256    fe53f68799a1df35fb05f24f77b0a5b906eff9a676714607990f02dfe85ed923
```

The fixer's 59,991-byte target is correct. A 239,744-byte `.fdupi` would be
decompressed plaintext served as cache data and must not be produced.

### 4.2 `.fdupm` format

The map is a 20-byte big-endian header followed by an 8,192-byte bitmap:

```text
+0x00 u64 stored_size       (ZSize)
+0x08 u64 id                (0 for GT6)
+0x10 u32 valid_block_count
+0x14 8192-byte bitmap
file length = 8212 = 0x2014
```

Measured pairs:

| Key | `.fdupm` header | bits set | expected blocks | data |
|---|---|---:|---:|---|
| `K/IK` | `0x8BBC0 / 0 / 70` | 70 | 70 | bare `IK`, 572,352 B, GT.VOL-identical |
| `K/W2` (check time) | `0xEA57 / 0 / 0` | 0 | 8 | `.fdupi`, 59,991 B, all zeroes |

`K/IK` is the raw-source control: its 572,352-byte completed file has SHA-256
`dc4b5fd95fb009e9…1c6ac2` and is byte-identical to `GT.VOL[0x9E1000..]`.
That proves the cache stores the raw source bytes, including the ciphertext
prefix, not the decrypted stream.

For `K/W2`, `ceil(0xEA57 / 0x2000) = 8`, so a complete transient map must be
`0xEA57 / 0 / 8` with bitmap byte 0 = `0xFF`, rest zero.

### 4.3 Current state is an allocate-only false positive

At check time (2026-10-31 ~16:50):

```text
W2.fdupi   59,991 bytes, nonzero bytes = 0
           SHA-256 7b5c0196f56232a470ea96ea02111fece4ddc209761ecfd4be526df98a478362
W2.fdupm   8,212 bytes, header (0xEA57, 0, 0), bitmap all zero
```

`tools/gt6_pfs_cache_warm.py --key K/W2 --check` reports:

```text
FAIL  data is not byte-identical to the GT.VOL slice
FAIL  map blocks 0, want 8
FAIL  bitmap does not cover exactly the raw blocks
```

A 59,991-byte zero-filled `.fdupi` is what the new
`cellFsAllocateFileAreaWithoutZeroFill` produces via `_chsize_s`/`ftruncate`
when the guest writer never runs. It is **not** success. The fixer's report
already says this in §4; this check confirms it on disk. The K/W2 size criterion
must always be paired with the byte-identity check.

The post-patch run reproduces the same state after the null call is gone:

```text
flush_long.err:2237  [pfscache] open '.../K/W2.fdupi' flags=0x42 -> fd=5
flush_long.err:2239  [pfscache] allocate '.../K/W2.fdupi' size=0xEA57 -> OK
flush_long.err:2252  [pfscache] close fd=5 '.../K/W2.fdupi' size=59991
```

No `read fd=5`, no `write fd=5`, and no `0xA40FBC`/`0xA40984` (the guest probe
patch was not applied to that build). The many 256-byte `.fdupm` writes at
`lr=0x00A407E4` are the zero-fill map initialization, and the final 20-byte
write is the header at close; neither is block publication. The map was
re-initialized and its 20-byte header written with `blocks=0`. So the lifetime
patch removed the null call, but the guest still does not issue the cache read
for K/W2.

## 5. Verification criterion review

The stated criterion is:

1. `.fdupi` becomes 59,991 bytes and byte-identical to GT.VOL at the K/W2
   offset;
2. `.fdupm` bitmap covers 8 blocks;
3. `0xA40FBC` and `0xA40984` are reached.

| Criterion | Check |
|---|---|
| 59,991 raw bytes, not 239,744 | **PASS.** The fixer targets `ZSize=0xEA57`; the checker independently confirmed the TOC, slice and hash. It explicitly rejects the decompressed `Size=0x3A880`. |
| byte-identical to GT.VOL at `0xD48800` | **Correct requirement.** Current file fails (all zeroes, SHA-256 `7b5c…8362`). Size alone is not enough. |
| bitmap covers 8 blocks | **Correct for the transient pre-completion state.** `ceil(0xEA57/0x2000)=8`; header must be `(0xEA57,0,8)`, bitmap byte 0 `0xFF`. |
| `.fdupm` after process exit | **Too strong.** On completion (`+0x20 == +0x68` at `0xA40EBC`) the guest unlinks `<key>.fdupm` (`0xA40F04 -> 0xA3F4B8`) and renames `<key>.fdupi` to the bare `<key>` (`0xA40F50 -> 0xA3F6B4`). A successful final state is normally the bare `K/W2` with 59,991 bytes and **no** map. A checker that requires `.fdupm` after exit will false-FAIL a correct run. Accept either the transient pair or the completed bare file, but always verify the data bytes/hash. |
| `0xA40FBC` / `0xA40984` reached | **Correct and necessary.** Without the probe patch these addresses are silent. The writer is proven only if `0xA40FBC` is entered, `0xA40984` is entered with `size=0xEA57`, and the map reaches 8 blocks (or the bare rename occurs). |

The fixer does **not** target 239,744; this part is correct. The flag is the
opposite: a size-only 59,991-byte check passes the current zero-filled file but
is not a cache. Byte identity is mandatory.

## 6. Safest next step

The lifetime patch is the right shape and the post-patch runs prove it removes
the measured null call. The remaining blocker is the missing read request.

1. **Keep the current patch and probe.** Build with
   `patches/gt6-pfs-cache-probe.patch` (`0xA40FBC` / `0xA40984`) and run with
   `GT6_PFS_CACHE_TRACE=1`. The post-patch run already shows the K/W2 sequence
   up to `.fdupi` close; the probe will prove whether a later read ever enters
   `0xA40FBC`.
2. **Find why K/W2 is opened and closed without a read.** The current sequence
   is: bdmark marker open/close (size 0), `.fdupm` header read, map re-init,
   `.fdupi` open + allocate + close, map header write. No `read fd=5` occurs.
   Trace:
   * the caller of `0x9F4130` / `0x9BB11C` for the K/W2 HFileReader;
   * the caller of `0xA08ED0` (`StartRead`) for that reader;
   * the bdmark marker result (`PDIPFS_bdmark/K/W2`, fd 3) and whether its
     zero length gates the real read.
   A read that is never requested is not a cache-writer bug.
3. If a read is requested but the null persists, log the active-read state at
   `0xA08B8C` / `0xA08ED0`:
   * `[+0x1C28]`, `[+0x1C29]`, `[+0x1C2C]`;
   * the caller of `StartRead` and the stream pointer it installs;
   * the pump's `this`.
   A stale pointer with `+0x1C29 == 1` is a caller-lifetime bug, not the
   spurious-flush case this patch targets.
4. **Do not** add `0x9F4550` to the lift table, synthesize an OPD for `+0x8C`,
   or redirect the call to `0xA0043C` while the object is bad. The target is
   already lifted; the object was the problem, and the patch fixed it.
5. Verify the cache by hash, not size:

   ```powershell
   python tools\gt6_pfs_cache_warm.py --key K/W2 --check
   ```

   Accept either `W2.fdupi` + `W2.fdupm` (transient) or bare `W2` (completed),
   but require the 59,991-byte GT.VOL slice and SHA-256 `2b6153…9008`. Reject a
   zero-filled 59,991-byte file and reject 239,744.

## 7. Address index used by this check

| Item | Value |
|---|---|
| Getter `stream->m_file->m_device` | `0x9F3E90` |
| Stream read wrapper / slot `+0x8C` | `0x9F44D8`, `bctrl` at `0x9F4550` |
| PFS device vtable (real base) | `0x1488AB8` (typeinfo at `0x1488AB4`) |
| PFS read `+0x8C` | OPD `0x14DF9F8` -> `0xA0043C` -> `0xA40FBC` |
| PFS open `+0x88` | OPD `0x14DFA80` -> `0xA010C0` |
| File vtable / `m_device` field | `0x1488218`, `File+0x40` |
| Outer `FileStream` vtable | `0x1488168` |
| FileDeviceHost vtable | `0x1489480` (`StartRead +0x10`, completion `+0x14`) |
| FileDeviceHost init | `0xA08A00`; store `+0x1C2C` at `0xA08A74`; destroy at `0xA08AB4` |
| Flush entry / pump | `0xA08B8C` / `0xA08ADC` |
| Read-active flag | `+0x1C29`; set `0xA08ED0`, clear `0xA09130` |
| Cache read / write | `0xA40FBC` / `0xA40984` |
| Cache close / header | `0xA40DD4` / `0xA40E20` |
| Completion unlink / rename | `0xA40F04 -> 0xA3F4B8` / `0xA40F50 -> 0xA3F6B4` |
| K/W2 TOC | FileIndex 58, SegIndex 6548, `ZSize 0xEA57`, `Size 0x3A880` |
| K/W2 GT.VOL offset | `0xD48800` |
| K/W2 raw SHA-256 | `2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008` |
| K/W2 read-side SHA-256 | `fe53f68799a1df35fb05f24f77b0a5b906eff9a676714607990f02dfe85ed923` |
| K/IK control | 572,352 B, SHA-256 `dc4b5fd95fb009e9…1c6ac2`, map 70/70 |
| Current K/W2 `.fdupi` | 59,991 B, all zeroes, SHA-256 `7b5c0196…8362`, map 0/8 |

## 8. Verdict

* **Null-slot wording (`+0x8C = 4`): FAIL.** `r9` and `r11` are zero; the slot
  is never read; `r12` is CR. The call is a null object, not a null slot.
* **Stale-`FileStream` diagnosis: PASS.** The fixer's later report identifies
  the `FileDeviceHost` init/flush lifetime bug, and the static evidence
  (`0xA08A74` store, `0xA08AB4` destroy, `0xA08ADC` reload) supports it.
* **Expected target: PASS.** `0x1488AB8 + 0x8C = 0xA0043C` (`PDIPFS::FileDevicePFSBase::read`
  -> `0xA40FBC`), and it is in the ELF and lift table. The `-4` base correction
  (`0x1488AB8`, not `0x1488AB4`) is right.
* **Fixer's lifetime patch: PASS with caveats.** It clears the dangling
  pointer and suppresses the no-read Flush; it does not fabricate a target and
  leaves the active-read path unchanged. The post-patch runs confirm the
  `0x9F4550` null call is gone. Residual risks: un-cleared `+0x1C28` on a failed
  active read, and unproven caller-provided stream lifetime.
* **K/W2 raw size/offset: PASS.** 59,991 bytes at `0xD48800`, SHA-256
  `2b6153…9008`; 239,744 is read-side `Size`.
* **Current cache: FAIL.** 59,991 zero bytes and map 0/8, including after the
  patch. The null call is fixed, but no read is issued: `.fdupi` is opened,
  allocated, and closed without a read/write, and `0xA40FBC`/`0xA40984` do not
  run. A size-only check is a false positive. The next blocker is the missing
  read trigger, not the dispatch.
