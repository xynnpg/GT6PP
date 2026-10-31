# W2 FileObject size repair — independent check

**Date:** 2026-10-31
**Scope:** the `0x9F4130` FileObject size/bind repair for `PDIPFS K/W2`
(`projects/gt6/cursor/gpb/CursorProject.gpb`), the current generated tree, and
the post-fix run `work/size_run.err` (17:32). Read-only: this check did not
edit source or generated code, did not build, and did not run `gt6.exe`.
**Inputs:** `work/size_run.err`, `work/size_run.log`, `work/probe_run.err`,
`work/build_size_fix.log`, `gt6/generated/ppu_recomp_022.cpp`,
`work/bin/EMAIN.elf`, `gt6/GT.VOL`, the on-disk `K/W2` pair, and
`tools/gt6_filedevice_flush_patch.py` / `tools/post_lift_fixes.py`.
**Policy:** `third_party/PDTools` was not read or used.

## 0. Verdict

| # | Claim to check | Verdict | Finding |
|---:|---|---|---|
| 1 | The original `[fileopen] 9F4130 ... size=0` probe is the W2 PFS cache object | **FAIL** | That line (`probe_run.err:699-701`) is the boot-script host reader, immediately after `[GT6] script override`. Its `vt=0x01488218` is the base `PDISTD::FileObject`, and the following `9BB020` reads are the ADCH `main.adc` stream. |
| 2 | The W2-time `9F4130` object is the PFS cache `FileObject` | **FAIL** | `size_run.err:289083-289086` shows the W2-time open as `vt=0x01488218 dev=0x7005C000 size=0` too. The PFS cache is attached separately at `289106`, but `9F4AA0` then goes to the **host** device (`[filehost] A08ED0`, `289120`), not `0xA0043C`/`0xA40FBC`. |
| 3 | `FileObject+0xC0` is the 64-bit size field | **PASS** | `0x9F4B5C`: `lwz r30,0x44(r28)` (FileObject), then `ld r26,0xC0(r30)`; it compares that 64-bit value with the stream offset and uses it as the file size. |
| 4 | `cache+0x10` is the cache `stored_size` | **PASS** | `0xA42108` stores its size argument at `[cache+0x10]`; `0xA40984` reads `[cache+0x10]`; the W2 attach is `size=0xEA57` and the `.fdupm` header is `0xEA57`. |
| 5 | The vtable gate covers the actual W2 device | **FAIL (inert)** | The old block is present in generated code, but no `[filesize]` line appears for W2 and the read is host-backed. The gate excludes the actual W2 object, so the repair does nothing. |
| 6 | The host boot reader is untouched | **PASS (writes) / caveat** | No `[filesize]`/write occurs for the boot line. The old block nevertheless computes `_c = [_dev+0x88]` **before** the `_pfs` test, so it performs one read through the host device field. |
| 7 | The repair preserves raw bytes / avoids double-decrypt | **PASS (no bytes) / not a data fix** | It only writes a size field; it never decrypts, inflates, byte-swaps, or writes cache data. It cannot produce the `.fdupi` bytes. |
| 8 | `[FileObject+0x4C]+0x1C` side effect is correct | **FAIL** | The PFS read state is `[FileStream+0x4C]` (written by `0xA010C0`, read by `0xA0043C`). `FileObject+0x4C` is inside the object constructed at `FileObject+0x44` by `0xEB2C00`, not the read state. The `_st+0x1C` test can read arbitrary memory and the write can corrupt the FileObject. |
| 9 | The latest "bind host FileObject to PFS read state" change is safe and applied | **FAIL** | The new tool wants `vm_write32(_f + 0x40u, _st)` (`FileObject+0x40 = read-state pointer`) before `0x9F3F2C` open. That replaces the `FileDevice` with a non-device object; only its `+0x90` slot is checked. The generated tree does **not** contain this change: `gt6_filedevice_flush_patch.py --check` and `post_lift_fixes.py` both exit 1. |
| 10 | The stated success criterion is correct | **PASS (criterion) / FAIL (state)** | 59,991 raw bytes at `0xD48800`, hash `2b6153…9008`; transient map `(0xEA57,0,8)` bitmap `FF`; completed bare `K/W2`. Current `.fdupi` is 59,991 zero bytes, map `(0xEA57,0,0)`. `9F4AA0` is reached, `0xA40FBC` is not. |

**Bottom line:** the built repair is a **safe-ish no-op for W2**, not a cache
fix. The W2 `HFileReader` is bound to a host/bdmark `FileObject`; the PFS cache
is attached to a different object/state, and the read goes through the host
device. Setting `FileObject+0xC0` cannot change that. The newer bind is
unbuilt, untested, and substitutes a read-state pointer for a `FileDevice`,
which is fabrication rather than a mount/open fix. Do not land either change
as the W2 solution.

---

## 1. What the probes actually show

### 1.1 The original `9F4130` line is the boot script

`work/probe_run.err:696-701`:

```text
696: [GT6] script override: serving decrypted /scripts/gt6/main.adc (857518 bytes)
699: [fileopen] 9F8E40 info=0x400C749C info+3C=0x400C74FC info+40=0x00000000 file=0x7FFD6270
701: [fileopen] 9F4130 this=0x7FFD6210 file=0x7FFD6270 vt=0x01488218 dev=0x7005C000 size=0x0
```

The object is the host boot-script reader:

* `0x7FFD6210` is the reader `0x7FFD61E0 + 0x30` (`FileStream`); `0x7FFD6270`
  is reader `+0x90` (the `FileObject`), as documented in
  `filedevice-null-vcall-check.md` §11.1.
* `vt=0x01488218` is the base `PDISTD::FileObject` vtable, not a PFS subclass.
* The following `[fileread] 9BB020` sequence is the ADCH parser consuming
  `main.adc`, and the script override serves it.
* `A3EB60` at `747` is a **different call**: `r3=0x100` is a PFS
  handle/index, not the `FileObject`; `r6=0x21` is not a size. `A3EB60`
  resolves the handle through `0xA3DF24` and writes fields `+0x28..+0x48`;
  it does not read `FileObject+0xC0`.

### 1.2 The W2-time line is also host-backed

The post-fix run `work/size_run.err` reaches W2 at `289083`:

```text
289083: [fileopen] 9F8E40 info=0x402987C4 info+3C=0x40379D90 info+40=0x015DE7C8 file=0xCFEFE398
289086: [fileopen] 9F4130 this=0xCFEFE338 file=0xCFEFE398 vt=0x01488218 dev=0x7005C000 size=0x0
289100: [pfscache] open .../PDIPFS_bdmark/K/W2 flags=0x442 -> fd=3
289103: [pfscache] close fd=3 ... size=0
289106: [pfscache] 0xA42108 attach size=0xEA57 id=0xD48800 path=0xCFEFDD7C
289113: [pfscache] open .../K/W2.fdupi flags=0x42 -> fd=5
289115: [pfscache] allocate ... size=0xEA57 -> OK
289119: [fileread] 9F4AA0 stream=0xCFEFE338 req=0xCFEFE2B8 file=0xCFEFE398
289120: [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFE338 active=0x00 old=0x00000000
289127: [pfscache] close fd=5 ... size=59991
289129: [pfscache] write fd=4 .../K/W2.fdupm nbytes=20
```

This is decisive:

* `0x9F4AA0` **is** reached. The old premise "HFileReader::read sees EOF and
  never calls `0x9F4AA0` because the size is zero" is wrong for this run.
* The very next line is `0xA08ED0` (`FileDeviceHost::StartRead`), the host
  async-read path. There is no `0xA0043C`, no `0xA40FBC`, and no `.fdupi`
  read/write. The read request went to the host/bdmark object, not the PFS
  cache.
* There is no `[filesize]` line. The old vtable-gated size block did not
  fire for this W2 object. The build that produced `size_run.err` used the
  old probe format (no `path`/`dev_vt`), so the exact device vtable was not
  logged, but the host read and the absent `[filesize]` are sufficient to
  show the gate did not match.
* The PFS cache attach (`0xA42108`, size `0xEA57`) and the `.fdupi` allocation
  are real, but they are attached to a different object/state than the
  `FileObject` stored at `HFileReader+0x44`.

The probe field mapping is:

| Probe | Actual meaning |
|---|---|
| `9F4130 this=` | `ctx->gpr[31]`, the `FileStream`/HFileReader side |
| `9F4130 file=` | `ctx->gpr[3]`, the `FileObject*` stored at `FileStream+0x44` |
| `9F4130 vt=` | `[FileObject]`, the FileObject vtable |
| `9F4130 dev=` | `[FileObject+0x40]`, the `FileDevice*` |
| `9F4130 size=` | `[FileObject+0xC0]`, the 64-bit stream size |
| `9F8E40 info=` | mount/lookup object, not necessarily the final FileObject |
| `A3EB60 file=` | `ctx->gpr[3]`, a PFS handle/index, **not** the FileObject |
| `A3EB60 r6=` | sixth argument (flags/cache field), not a size |

---

## 2. FileObject layout, size field, and the actual read path

### 2.1 `FileObject+0xC0` is a real 64-bit size

`0x9F5C94` (base `PDISTD::FileObject` ctor) initializes `+0x38`, `+0x3C`,
`+0x40`, `+0x44`, `+0x50..+0x60`, `+0x74`, `+0x7C`, `+0x84`, `+0x94..+0xAC`,
`+0xF0..+0x10C`. It does **not** initialize `+0xC0`. The field is read by
`0x9F4B5C`:

```text
009F4B9C: lwz   r30, 0x44(r28)      ; r28 = FileStream, r30 = FileObject
009F4BAC: ld    r26, 0xC0(r30)      ; 64-bit stream size
009F4BB4: cmpld cr7, r26, r29       ; compare with offset at stream+0x60
```

So `+0xC0` is the size the guest expects on the stream, and a 64-bit write is
the right width. That part of the fixer's layout claim is correct.

### 2.2 The HFileReader/PFS read path does not consult `FileObject+0xC0`

`0x9BB020` (`HFileReader::read`) gates on its own buffer state
(`reader+0x1A8/+0x1AC/+0x1B0`) and calls `0x9F4AA0` when it needs bytes; it
does not load `FileObject+0xC0`. `0x9F4AA0` dispatches the device read slot
`+0x90`. For PFS, that slot is `0xA0043C`:

```text
00A00464: lwz   r31, 0x4C(r4)       ; r4 = FileStream; r31 = PFS read state
00A00484: lwz   r9, 0x1C(r31)       ; chunk cap / request clamp
00A004AC: bl    0xA40FBC            ; cache_read
00A004D8: ld    r5, 0x10(r31)       ; current offset
00A004F8: ld    r11, 0x18(r31)      ; remaining bytes
```

The PFS read state is **`FileStream+0x4C`**, and `0xA010C0` writes that field
when it builds the state. `0xA0043C` uses state `+0x10` (offset), `+0x18`
(remaining), and `+0x1C` (chunk cap). Nothing here reads
`FileObject+0xC0`. Setting that field may help a different `FileStream::read`
entry (`0x9F4B5C`), but it is not the gate for the measured
`9BB020 -> 9F4AA0` path.

### 2.3 `cache+0x10` is the stored size

`0xA42108` (`cache_ctor`) allocates `0xF8` bytes and does:

```text
00A4218C: stw   r11, 0x88(r30)      ; [PFS object + 0x88] = cache
00A421C4: std   r23, 0x10(r11)      ; [cache + 0x10] = size argument
```

`0xA40984` (`cache_write`) reads `[cache+0x10]` for its size gate, and the
`.fdupm` header uses the same value. For W2 the attach is `size=0xEA57`, and
the map header is `size=0xEA57`. The `cache+0x10` mapping is correct.

**Caveat:** the old repair computes `_c = [_dev+0x88]` where `_dev` is
`[FileObject+0x40]`. `0xA42108` stores the cache at `[first_arg+0x88]`, where
`first_arg` is the PFS object returned by `0xA3DF24(handle)`. That object is
not proven to be the same as `[FileObject+0x40]`. The W2 attach probe's
argument registers are printed after the call (`path=0xEA57`,
`size=0x4037F014`), so it cannot prove the object identity. This mapping is
therefore **unverified**, not established.

---

## 3. Vtable gate review

Resolved from `work/bin/EMAIN.elf`:

| Vtable | Slot `+0x8C` | Slot `+0x90` | Meaning |
|---|---|---|---|
| `0x1488AB8` | `0xA010C0` open | `0xA0043C` read | `FileDevicePFSBase` (destructor `0x9FEDC8`) |
| `0x1488AB4` | `0xA010C0` | `0xA0043C` | same table, object-pointer/typeinfo form |
| `0x1488AC0` | `0xA00964` | `0xA00414` | PFS base vtable (destructor `0xA0026C`) |
| `0x1488A2C` | `0x9FEDC8` | `0x9FED88` | PFS mount/vfs table (`+0x38 = 0x9FDAAC`) |
| `0x1488AAC` | `0x9FFFCC` | `0xA00C08` | another PFS-related table |
| `0x1489480` | `0x9F810C` | `0x9F8100` | `PDIPSX::FileExpandPSX` host device |

The old gate includes the two `FileDevicePFSBase` forms (`0x1488AB4/AB8`), so
it would match a real PFS device, and it excludes the host `0x1489480`. That
is why the boot reader and W2 host object are not modified. But:

* It also includes `0x1488A2C`, a mount table whose `+0x8C` is a destructor,
  not a read slot.
* It omits `0x1488AC0`, another PFS table. If W2's device were that form, the
  gate would miss it.
* More importantly, the measured W2 object does **not** match the gate at
  all: no `[filesize]`, host `A08ED0` read. The gate's correctness for
  hypothetical PFS objects is not the same as fixing W2.

The old block also reads `_dev+0x88` before evaluating `_pfs`
(`uint32_t _c = _dev ? vm_read32(_dev + 0x88u) : 0;`). So it does touch the
host device field even though it does not write it. For a host object at
`0x7005C000` this happened without a crash, but it is not strictly
"untouched".

---

## 4. Safety review

### 4.1 Raw bytes / double-decrypt

The old block only writes a size. It does not decrypt, inflate, byte-swap, or
write cache bytes. It therefore cannot double-decrypt or corrupt cache data
by itself. It also cannot produce the missing `.fdupi` bytes.

### 4.2 The `+0x4C` side effect is wrong

The old block does:

```c
uint32_t _st = vm_read32(_f + 0x4Cu);       /* FileObject+0x4C */
if (_st && vm_read64(_st + 0x1Cu) == 0)
    vm_write64(_st + 0x1Cu, _z);
```

The PFS read state is **`[FileStream+0x4C]`**, not `[FileObject+0x4C]`.
`FileObject+0x4C` lies inside the object built at `FileObject+0x44` by
`0xEB2C00`; it is not the read state. The condition dereferences an arbitrary
pointer and the write can corrupt the FileObject. Even if it were changed to
`FileStream+0x4C`, `+0x1C` is a chunk cap, not the file size; the remaining
count is `+0x18`, and the offset is `+0x10`.

### 4.3 The latest bind is fabrication

The current `gt6_filedevice_flush_patch.py` (17:36) replaces the old block
with:

```c
if (_dvt is not a PFS vtable)
    vm_write32(_f + 0x40u, _st);   /* FileObject device = PFS read state */
```

It then expects `9F4AA0` to dispatch the read-state's `+0x90` slot
(`0xA0043C`). Problems:

* It overwrites the `FileDevice*` at `FileObject+0x40` with a **read-state**
  pointer before `0x9F3F2C` performs the open. The open slot `+0x88` is not
  checked; the state is not a `FileDevice`, and later open/seek/close/stat
  operations will dispatch slots on it.
* It checks only `_slot == 0xA0043C`; it does not prove the state's other
  device slots or lifetime.
* It bypasses the real bug (the wrong/host FileObject was selected at mount
  open) by type-punning the object. This is masking, not fixing the mount.
* It is **not applied** to the current generated tree. The check tool and
  `post_lift_fixes.py` now require the bind, but `ppu_recomp_022.cpp` still
  contains the old size-only block. Both checks exit 1:

```text
ppu_recomp_022.cpp: func_009F4130 lacks the cache-backed PFS read-state bind
ppu_recomp_022.cpp: func_009F4130 FileDeviceHost guard missing
  ['Cache-backed host FileObject: bind to the PFS read state.',
   'vm_write32(_f + 0x40u, _st);']
```

The `patches/gt6-pfs-filesize-fix.patch` still documents the old size-only
block, not the bind. The tree, the patch, and the verifier are inconsistent.
Do not build or land this state without a decision on which approach is
intended.

---

## 5. Current state and success criterion

### 5.1 TOC, GT.VOL slice, and hash

Fresh direct read of `gt6/GT.VOL`:

```text
offset 0xD48800, length 0xEA57 (59,991)
first 16 27 FD F1 57 AE 6E B5 CA 26 8B 5A 60 93 29 31 C8
last 16  01 8D 7B 06 A2 E2 07 CB F8 FA 76 D9 C2 26 A4 C4
SHA-256  2b6153bacd5e833e9e3bb5b5089552ae3bf973a67feba599ec6fcd21db709008
```

`Size=0x3A880` (239,744) is the decompressed read-side length, not the raw
cache length. A 239,744-byte `.fdupi` would be wrong.

### 5.2 On-disk state at check time

| File | Length | Contents |
|---|---:|---|
| `K/W2.fdupi` | 59,991 | all zero; SHA-256 `7b5c0196f56232a470ea96ea02111fece4ddc209761ecfd4be526df98a478362` |
| `K/W2.fdupm` | 8,212 | header `(0xEA57, 0, 0)`; bitmap zero bits |
| bare `K/W2` | absent | — |

The 17:32 run logged a `.fdupm` close header write at `289129`, but the
checked file still has header `(0xEA57,0,0)` and mtime 17:27:49. That may be
a durability issue (the process was not cleanly closed) or a different map
instance; either way the cache is not populated.

### 5.3 Acceptance criterion

| Criterion | Verdict |
|---|---|
| `.fdupi` 59,991 bytes, byte-identical to `GT.VOL[0xD48800..+0xEA57]`, SHA-256 `2b6153…9008` | **Correct; current FAIL** (59,991 zero bytes) |
| Transient `.fdupm` `(0xEA57,0,8)`, bitmap byte 0 `0xFF` | **Correct for the pre-completion state; current FAIL** (0/8, zero bits) |
| Completed state: bare `K/W2` with the same bytes and no map | **Correct alternative**; the guest renames `.fdupi` to bare only when `+0x20 == +0x68`; do not require a map after exit |
| `HFileReader::read` reaches `0x9F4AA0` | **PASS** at `size_run.err:289119` |
| `0x9F4AA0` reaches `0xA40FBC` / `0xA40984` | **FAIL**; the read goes to `[filehost] A08ED0`, and no `0xA40FBC`/`0xA40984` line exists for W2 |

The K/IK control in `probe_run.err:625-626` proves the PFS path itself can work:
`[fileread] 9F4AA0 ... file=0xCFEFEA70` followed by
`[pfscache] 0xA40FBC read file=0x00000100 off=0x8BBC0`. W2's failure is not a
missing `0x9F4AA0` call; it is the wrong device/read state on the
`FileObject`.

---

## 6. Safest next step

1. **Do not land the old size-only block or the new bind as the W2 fix.**
   The old block is inert for W2 and has a wrong `+0x4C` side effect; the new
   bind is an unbuilt type-punning hack that replaces a `FileDevice` with a
   read-state pointer.
2. **Restore a consistent tree/tool state before any build.** Decide whether
   the `0x9F4130` change is wanted at all. If it is kept, the generated tree,
   `patches/gt6-pfs-filesize-fix.patch`, `gt6_filedevice_flush_patch.py`, and
   `post_lift_fixes.py` must describe the same code and the gate must pass.
3. **Fix the mount/device selection, not the size field.** The W2
   `HFileReader` is bound to a host/bdmark `FileObject`; the PFS cache attach
   is separate. Trace, with the updated probe:
   * `0x9F8E40` mount match and the returned `FileObject`;
   * `0x9F4130` `path`, `dev`, `dev_vt`;
   * `0x9F44D8`/`0xA010C0` PFS open, and `0x9F4AA0`/`0xA0043C`;
   * `0x9FDC5C`/`0xA422A0`/`0xA42108` cache attach object identity.

   Compare W2 with the working K/IK open. Bind the PFS `FileObject`/read state
   through the guest's normal open path; do not overwrite `FileObject+0x40`
   with a non-device pointer.
4. **If a size repair is still needed after the correct PFS object is
   selected,** set the PFS read state's remaining/offset fields
   (`[FileStream+0x4C]` `+0x18`/`+0x10`) from the guest cache's own
   `stored_size`, not `FileObject+0x4C`. Set `FileObject+0xC0` only if the
   normal PFS open is expected to have done so and a probe proves it is the
   gate.
5. **Verify with a long run (240–300 s) and the updated probe.** Require:
   * `0xA40FBC` with `size=0xEA57`, then `0xA40984` block writes;
   * `.fdupi` 59,991 bytes and SHA-256 `2b6153…9008`;
   * `.fdupm` `(0xEA57,0,8)`/bitmap `FF` **or** bare `K/W2` after the
     completion rename;
   * no `[filehost] A08ED0` for the W2 read, and no zero-filled `.fdupi`
     accepted as success.

### Evidence index

| Evidence | Location / value |
|---|---|
| Boot-script `9F4130` probe | `work/probe_run.err:696-701` |
| W2-time `9F4130` and host read | `work/size_run.err:289083-289130` |
| K/IK positive control | `work/probe_run.err:625-626` |
| Current W2 data/map | 59,991 zero bytes, SHA `7b5c…8362`; map `(0xEA57,0,0)` |
| GT.VOL W2 slice | `0xD48800`, 59,991 B, SHA `2b6153…9008` |
| FileObject size read | `0x9F4B5C` `ld r26,0xC0(r30)` |
| PFS read state | `0xA010C0` writes `FileStream+0x4C`; `0xA0043C` reads it |
| Cache size | `0xA42108` `std r23,0x10(r11)`; `0xA40984` reads `[cache+0x10]` |
| PFS device vtables | `0x1488AB8`/`0x1488AB4` (`+0x8C=0xA010C0`, `+0x90=0xA0043C`) |
| Host device vtable | `0x1489480` (`+0x8C=0x9F810C`, `+0x90=0x9F8100`) |
| Old repair block | `gt6/generated/ppu_recomp_022.cpp:137371-137391` |
| Latest bind / gate mismatch | `tools/gt6_filedevice_flush_patch.py:81-106`; `gt6_filedevice_flush_patch.py --check` and `post_lift_fixes.py` exit 1 |
