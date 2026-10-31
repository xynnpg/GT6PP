# PFS boot-script decrypt path: reader identity, cipher/inflate location, fix

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Scope:** static disassembly of the boot-script reader and the PDIPFS
decrypt/inflate path, plus an audit of the boot-script stream override that is
now in `gt6/src/stubs.cpp`.
**Relation to earlier reports:** this extends `docs/analysis/pfs-decrypt-check.md`
(which measured the 0-byte read) and supersedes only the decrypt-location
section of `docs/analysis/pfs-script.md`. The GT.VOL header, TOC, entry offset,
seed 33 and 857,518-byte ADCH file in those reports are unchanged and correct.

**Read-only work:** this report did not build or run `gt6.exe`; it did not edit
`gt6/src`, `gt6/generated`, or `third_party`.

## 0. Verdict

1. **`0x9CD410` does not read GT.VOL directly and does not read an in-memory
   PFS entry.** It reads through `ADHOC::HFileReader` -> `HStreamReader` ->
   `HFileReader::read` (`0x9BB020`) -> `0x9F4AA0` -> `0x9F3E90`, which returns
   `[device+0x40]` from the filebuf device. The device is resolved by the
   PDIPS3 mount/factory at `0x15DE908`. In the measured 1:18 run the PDIPFS
   source opened immediately before the reader is the **HDD PDIPFS cache**
   `.../PDIPFS/K/PD.fdupi`, and the read returns **0 bytes** because the cache
   block map is empty and the cache copy runs later.
2. **The seed-33 cipher is PPU guest code `0x9FF530`, on the PFS read side, not
   in the copy path.** It is gated by `[device+0x144]` at `0x9FF584` and
   `0x9FF328`. The PS2ZIP inflate is `PDISTD::SpuInflator` (an SPU workload),
   not PPU. Neither is reached while `HFileReader::read` returns 0.
3. **The current boot-script override in `gt6/src/stubs.cpp` is the right
   immediate unblock** (option (a) from the task). It is activated by
   `gt6_script_path_hint` at `HFileReader::open` (`0x9BB11C`) and serves the
   already-decrypted `work/gt6_vol/scripts/gt6/main.adc` from
   `gt6_script_read_override` at `HFileReader::read` (`0x9BB020`). It needs the
   hardening in section 4.2, and it fixes only the boot script.
4. **The general fix remains the PFS read-through path (option (d)), with (c)
   as the HLE fallback.** Pre-placing `PD.fdupi` (option (b)) is rejected: the
   game overwrites it, `.fdupm` describes raw `ZSize` bytes with an empty block
   map, and the reader still returns 0.

## 1. What `0x9CD410` actually reads

### 1.1 Boot chain

```
0x9CD798  ADHOC script load("scripts/gt6/main")
  0x9CC068  registered-loader lookup                -> 0 in the measured run
  0x9D4F50  extension test                          -> 0 (no dot)
  0x9CDBD0..0x9CDBFC  append ".adc" (string 0x1095168)
  0x9CD69C  fallback HFileReader construction
      0x9BB7E0  make HFileReader (vtable 0x1484CC8)
      0x9BB11C  HFileReader::open(path)
      0x9CD410  HStreamReader read 8 + "ADCH" compare
```

`0x9CD69C` arguments are `(out_shared_ptr, manager, path_string)`; the path
string at the call is `scripts/gt6/main.adc`.

### 1.2 The read is a virtual file read, not a cellFs read of GT.VOL

```
0x9CD410
  r5 = &shared_ptr<HFileReader>
  0x9D9604(stack+0x90, r5)        copy shared_ptr into HStreamReader
  0x9D8DB0(stack+0x90, stack+0x88, 8)
      r31 = [stack+0x90]          HFileReader*
      0x994078(r31, stack+0x88, 8)  HStreamReader::read
          0x994078 is the buffered stream reader; when its get area is empty
          it dispatches through HFileReader's vtable slot +0x11C.
```

For HFileReader vtable `0x1484CC8`, slot `+0x11C` is OPD `0x14DCB18` ->
`0x9BB020` (`HFileReader::read`):

```
0x9BB020:
  if n == 0 return 0
  ...
  0x9F4AA0(HFileReader+0x30, buf, n, 1)
      0x9F4AA0 -> 0x9F3E90
          0x9F3E90:
            r0 = [HFileReader+0x44]      ; filebuf device
            r3 = r0 ? [r0+0x40] : 0      ; file object
      0x9F4AA0:
        if file == 0 return -1
        call file->vtable[+0x90](file, buf, n, 1)
  if result < 0 return 0
```

So the byte source is the **file object behind the HFileReader filebuf
device**, not a GT.VOL file descriptor owned by the reader. The GT.VOL reads
at `0xA6F000` are made by the PDIPFS copy/install path and are a different
handle.

### 1.3 How the device is selected (`0x9F8E40`)

`HFileReader::open` (`0x9BB11C`) calls:

```
0x9CD69C -> 0x9BB7E0 -> 0x9BB21C (HFileReader ctor; filebuf at +0x30)
0x9CD69C -> 0x9BB11C (HFileReader::open)
0x9BB11C -> 0x9BB168 -> 0x9F4218 (std::basic_filebuf::open thunk)
         -> 0x9F4130 (basic_filebuf::open)
         -> 0x9F6BF4
         -> 0x9F8E40 (std::__basic_file::open)
```

`0x9F8E40` normalizes the path, walks the mount list at `0x15DE908`, and calls
each mount's virtual `match` (vtable `+0x20`) until one returns 1, then calls
its `open` (vtable `+0x38`). The mount objects are **PDIPS3 file devices**:
`PDIPS3::FileDevicePFSBase` vtable `0x14889A8`, file-handle vtable
`0x14DF910`, and the PDIPFS-specific classes named in the binary at
`0x1097A80..0x1097C60` (`FileDevicePFSFSHddGame`, `FileDevicePFSFSHdd`,
`FileDevicePFSFSE`, `FileDevicePFSGameData`, `FileDeviceCachedCellFs`).

This is why there is no `cellFsOpen("scripts/gt6/main.adc")` in the logs: the
path is consumed by the PDIPS3 mount layer, not by a direct newlib/cellFs open
of the script path. The PDIPFS cache files themselves are opened through
cellFs, which is what the `[fs]` log shows.

### 1.4 The measured backing handle and the 0-byte result

From the 1:18 run quoted in `pfs-decrypt-check.md`:

```
1098: [fs] open '.../PDIPFS/K/PD.fdupi' -> fd 6
1099: [scriptload] 9BB11C ret=0x1 reader=0x7FFD61E0
1100: [read994078] this=0x7FFD61E0 err=0x0 buf=0xCFEF7098 n=8
1101: [read994078] ret=0x0
1102: [scriptload] ADCH read ret=0 at 0xCFEF7098: 00 00 00 00 00 00 00 00
```

The current on-disk state (verified by `tools/gt6_pfs_state.ps1`) is
consistent with that:

| Object | Size | Head | Meaning |
|---|---:|---|---|
| `work/gt6_vol/scripts/gt6/main.adc` | 857,518 | `41 44 43 48 30 31 32 00` | correct ADCH output |
| `work/gt6_hdd0/.../PDIPFS/K/PD.fdupi` | 857,518 | `25 0F FF FE 9B 46 77 B1` | raw stored entry, first 0x3E000 byte-identical to GT.VOL at 0xA6F000 |
| `work/gt6_hdd0/.../PDIPFS/K/PD.fdupm` | 8,212 | `00 00 00 00 00 03 EE 28` | `ZSize=0x3EE28`, all remaining bytes zero (empty block map) |
| `work/gt6_hdd0/.../PDIPFS/K/4D` | 160 | `99 CD DC D6 ...` | raw 160-byte volume header copy |

The cache file is opened **before** the copy thread fills it (the copy starts
at log line ~2504 in the same run), and `.fdupm` never gains a block entry, so
the reader gets EOF. The raw copy at `0xA6F000` is not the reader's source at
that moment.

### 1.5 What the new 8-byte log will mean

| First 8 bytes at `0x9CD410` | `gpr[3]` | Interpretation | Next check |
|---|---|---:|---|
| `00 00 00 00 00 00 00 00` | 0 | empty cache / EOF (the measured pre-override state) | `.fdupm` block map; `0x9F3E90` `[device+0x40]`; cache ordering |
| `25 0F FF FE 9B 46 77 B1` | 8 | stored ciphertext reached the reader; PFS cipher was skipped or bypassed | `[device+0x144]` at `0x9FF584`; mount key |
| `C5 EE F7 FF ...` | 8 | cipher ran, PS2ZIP inflate did not | `PDISTD::SpuInflator`, SPU workload dispatch |
| `41 44 43 48 30 31 32 00` | 8 | ADCH; boot script is readable | `0x9CC208` parse return; first asset read |

The current override should produce the fourth row; the pre-override run
produced the first row.

## 2. Where the game decrypts and inflates

### 2.1 Cipher: PPU guest `0x9FF530`

`0x9FF530` is the PFS file-handle method at vtable `0x14DF910` slot `+0x30`.
It decrypts the stored stream in place. Its distinctive implementation uses
four 64-bit tables and the cycle lengths 17, 19, 23, 29:

```
0x9FF5AC  lis  r8,0x1a7b / ori 0x9611   (magic multiply)
0x9FF5B4  lis  r9,-0xf10 / ori 0xf0f0   (magic multiply)
0x9FF5D0  lis  r7,0x642c / ori 0x8590   (magic multiply)
0x9FF5F0  lis  r11,-0x286c / ori 0x35e5 (magic multiply)
...
0x9FF77C  table 0xFA22D0, stride cycle 17
0x9FF790  table 0xFA22F2, stride cycle 19
0x9FF79C  table 0xFA2318, stride cycle 23
0x9FF7AC  table 0xFA2346, stride cycle 29
```

It is a PPU function in EMAIN, not an SPU job.

Gate (file data):

```
0x9FF584  lwz   r0, 0x144(r3)   ; keyset/decrypt-enable pointer
0x9FF588  ...
0x9FF590  cmpwi cr7, r0, 0
0x9FF5A0  beq   cr7, 0x9FF9CC  ; skip decrypt, return stored bytes
```

Gate (header/TOC path `0x9FF280`):

```
0x9FF328  lwz   r3, 0x144(r28)
0x9FF330  beq   cr7, 0x9FF34C  ; skip decrypt
0x9FF348  bl    0xA06780       ; header decrypt helper
0x9FF3B0  compare first 4 bytes to 0x5B74516E (TOC magic)
```

Keyset installation:

```
0x9FF0AC  stw r27, 0x144(r29)   ; constructor arg r4 (keyset pointer)
0x9FF0B8  bl  0xA0672C          ; derive [this+0x148] from [keyset]
```

The only constructor path is `0x12438 -> 0x9FD72C -> 0x9FD60C -> 0x9FF048`;
`0x12438` passes `0x1410F84` as the keyset. The TOC/header decrypt works in
the measured runs (the B-tree walk produces the correct `main.adc` entry), so
the cipher code and key setup are functional. The file-data path is the one
that is skipped or starved.

### 2.2 Inflate: `PDISTD::SpuInflator` (SPU workload)

The PS2ZIP decompressor is the class `PDISTD::SpuInflator`:

| Item | Address/string |
|---|---|
| typeinfo name | `0x109BF60` (`N6PDISTD11SpuInflatorE`) |
| vtable | `0x148A2D0` |
| ctor | `0xA43A14` (constructed at `0x10654`) |
| inflate entry | `0xA43AB4` |
| SPU submit | `0xA440E4` -> `0xA450A0` / `0xA43C98` |

This is an **SPU workload**, not a PPU function. The PS2ZIP stream header
(`C5 EE F7 FF` little-endian magic `0xFFF7EEC5`, then the negated output size)
is consumed on this path. The runtime's SPU workload dispatch must implement
the inflator job; if the job is missing or its lifted code is wrong, the
reader can receive decrypted PS2ZIP bytes (`C5 EE F7 FF...`) but never ADCH.

The cache is raw+compressed by design: `PD.fdupm` records `ZSize=0x3EE28`
and an empty block map, not the 857,518-byte plaintext size. Therefore
decryption and inflation belong on the **read** side, never in the copy/install
side.

### 2.3 The branch/state that skips it now

In the measured run the skip happens **before** the cipher gate:

1. `HFileReader::open` succeeds (the cache file exists), so `0x9BB11C`
   returns 1 and `0x9CD69C` proceeds to `0x9CD410`.
2. The cache has no valid blocks (`.fdupm` all zero after the 8-byte header),
   and the copy thread has not written the data yet. `0x9F3E90` therefore
   yields a null/empty file object, `0x9F4AA0` returns -1, and
   `HFileReader::read` returns 0 bytes.
3. `0x9CD410` compares eight zero bytes to `ADCH`, fails, and `0x9CD798`
   returns 0. The cipher (`0x9FF530`) and inflator (`SpuInflator`) are never
   called.

A second skip exists once data is present: `[device+0x144] == 0` selects the
"stored bytes" branch at `0x9FF9CC`. The probe patch logs both `0x144` and the
mount key so the two cases cannot be confused.

## 3. Fix options, ranked

| Rank | Option | Exactness | Risk | Scope | Verdict |
|---:|---|---|---|---|---|
| 1 | **(a) Boot-script stream override** (already in `gt6/src/stubs.cpp`) | ADCH for the boot script | Low | one file | **Recommended now**, after the hardening in 4.2 |
| 2 | **(d) Cache-miss/read-through in the guest PFS path** | all PFS files | Medium | all files | **Root fix**, after the probe confirms the device/key state |
| 3 | **(c) HLE decrypt+inflate at the PFS read layer** | all PFS files | Medium | all files | Valid fallback; duplicate of guest logic, must not double-decrypt |
| 4 | **(b) Pre-place decrypted `PD.fdupi`** | none | High | one file | **Reject** (proven overwritten, metadata mismatch, reader returns 0) |

### 3.1 (a) Boot-script stream override — current implementation

`gt6/src/stubs.cpp` now has:

- `gt6_script_path_hint` (line 71), called at the top of
  `func_009BB11C` (`gt6/generated/ppu_recomp_022.cpp`):
  reads the C++ string, matches `scripts/gt6/main`, opens
  `work/gt6_vol/scripts/gt6/main.adc`, loads 857,518 bytes, sets
  `g_script_reader` and `g_script_active`.
- `gt6_script_read_override` (line 117), called at the top of
  `func_009BB020`: serves the buffer sequentially and returns the byte count.

This is the correct minimal unblock. It bypasses the empty cache and the
cipher/inflate for this one file; the parser sees the exact bytes the retail
game would see. Use it to get past `0x9CD410` and validate `0x9CC208`, then
implement the general path and remove or gate the override behind a debug
environment variable.

Required hardening (details in 4.2):

* only serve the reader recorded in `g_script_reader`;
* exact path suffix `scripts/gt6/main.adc`;
* deactivate at EOF so later asset readers use the guest path;
* reset `g_script_pos`/`g_script_active` if the same path is opened again
  (the current `if (g_script_active) return;` keeps a stale position);
* keep `HFileReader` position fields coherent;
* force the open-success branch if the guest open ever returns 0.

### 3.2 (d) Root fix: make the cache miss and read through

Treat an empty `.fdupm` block map (or a zero-length/unfilled `.fdupi`) as a
cache miss in the PDIPS3 cache path. On a miss, read `ZSize` bytes from
GT.VOL at `0x7E800 + SegIndex * 0x800`, decrypt with the entry's `FileIndex`
as seed (the existing `0x9FF530` or an HLE equivalent), inflate with
`SpuInflator` (or a host PS2ZIP inflater), and serve the resulting `Size`
bytes through the same file object.

This is the only option that fixes every compressed file and survives a
fresh run. The exact insertion point is the cache lookup that returns the
file object used by `0x9F3E90`; the probe in section 4.1 identifies the
matching mount and `[device+0x144]`.

### 3.3 (c) HLE decrypt+inflate at the PFS read layer

If the guest cache path cannot be repaired quickly, hook the PFS virtual-file
read (or the HFileReader device read) and perform:

1. `ZSize = entry.ZSize`, `seed = entry.FileIndex` (`33` for K/PD);
2. read/decrypt `ZSize` bytes from GT.VOL/cache with the `0x9FF530` cipher or
   an MIT-licensed reimplementation;
3. PS2ZIP-inflate to `Size` (zlib is MIT-compatible; the header is
   `C5 EE F7 FF` + negated size);
4. serve the `Size`-byte stream to the reader.

Do this at the **read** layer only. The cache must keep raw bytes; `.fdupm`
proves that. Add a one-shot guard so it cannot double-decrypt if the guest
path is later fixed.

### 3.4 (b) Pre-place `PD.fdupi` — reject

The game opens the cache with `flags=0x42` (`O_RDWR|O_CREAT`, no truncate) and
overwrites the head with raw GT.VOL bytes; the current `PD.fdupi` is 857,518
bytes with a raw head `25 0F FF FE...`, while the disc-tree copy is ADCH. The
cache metadata still says `ZSize=0x3EE28` with an empty block map. A pre-placed
plaintext file neither survives nor matches the cache format, and the measured
reader still returned 0.

## 4. Patch/diff sketch

### 4.1 Probe patch (new file, not applied)

`patches/gt6-pfs-decrypt-probe.patch` is generated by
`tools/gt6_pfs_probe_patch.py`. It adds read-only logs:

| Guest address | Generated function | Log |
|---|---|---|
| `0x9BB11C` | `func_009BB11C` | HFileReader this, path object, path string |
| `0x9F8E40` | `func_009F8E40` | matching mount factory, vtable, key, `[+0x144]`, `[+0x148]` |
| `0x9CD410` | `func_009CD410` | reader pointer and vtable after the 8-byte read |
| `0x9FF280` | `func_009FF280` | header-cipher device, keyset, key |
| `0x9FF530` | `func_009FF530` | cipher device, offset, length, buffer, keyset, key, first 8 bytes |

Apply with `git apply patches/gt6-pfs-decrypt-probe.patch` (or paste the five
hunks). The patch is diagnostic only; remove it before shipping. It was
generated against the 2026-10-31 13:45 generated tree; after another relift,
re-run `python tools/gt6_pfs_probe_patch.py` to regenerate it.

### 4.2 Hardening the existing override

`patches/gt6-pfs-boot-override-hardening.patch` is a proposed diff for
`gt6/src/stubs.cpp` (generated by `tools/gt6_pfs_override_patch.py`, not
applied here):

```diff
-    if (!strstr(path, "scripts/gt6/main")) return;
+    {
+        static const char suffix[] = "scripts/gt6/main.adc";
+        size_t plen = strlen(path), slen = sizeof suffix - 1;
+        if (plen < slen || strcmp(path + plen - slen, suffix) != 0) return;
+    }

-    if (!g_script_active) return 0;
+    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader) return 0;

     if (g_script_pos >= g_script_size) {
+        g_script_active = 0;          /* EOF is final for this reader */
         ctx->gpr[3] = 0;
         return 1;
     }
     ...
     g_script_pos += k;
+    vm_write32(ctx->gpr[3] + 0x1B4, (uint32_t)g_script_pos);
     ctx->gpr[3] = k;
     return 1;
```

Open-success fallback (generated code, not in the patch above): after
`0x9BB11C` returns in `func_009CD69C`, if the result is 0 but
`gt6_script_override_active()` is true, force the success branch to
`0x9CD728` instead of `0x9CD784`. Expose a small predicate from `stubs.cpp`:

```cpp
extern "C" int gt6_script_override_active(void) { return g_script_active; }
```

and insert in `func_009CD69C` after the open call:

```cpp
if ((int)ctx->gpr[3] == 0 && gt6_script_override_active())
    ctx->gpr[3] = 1;
```

This makes the override independent of whether the empty cache open succeeds.
The current measured run opens successfully, so this is defensive.

### 4.3 Root fix sketch (option d)

Pseudo-code at the cache lookup (the code that returns the file object consumed
by `0x9F3E90`):

```c
/* .fdupm header: [u32 ?][u32 ZSize][block map...] */
if (fdupm.blocks_present == 0 || fdupi_size == 0) {
    /* cache miss: do not return an empty file object */
    return pfs_read_through(entry);   /* GT.VOL -> cipher -> inflate */
}
```

`pfs_read_through` must use the same entry metadata the TOC already resolves:

```
offset = 0x7E800 + entry.SegIndex * 0x800;
zsize  = entry.ZSize;      /* 0x3EE28 for K/PD */
size   = entry.Size;       /* 0xD15AE */
seed   = entry.FileIndex;  /* 33 for K/PD */
```

Then decrypt `zsize` bytes with `0x9FF530` (or the HLE cipher) and inflate with
`SpuInflator`/zlib to `size`. The probe in 4.1 prints the mount key and
`[device+0x144]`, which says whether the guest chooses the keyed volume device
or the unkeyed cache device.

## 5. Verification procedure

### 5.1 Snapshot the state (no run)

```powershell
powershell -ExecutionPolicy Bypass -File tools\gt6_pfs_state.ps1
```

Expected (current tree):

```
decrypted main.adc   857518  head 41 44 43 48 30 31 32 00  sha 5B40...A746
hdd PD.fdupi         857518  head 25 0F FF FE 9B 46 77 B1  (raw head)
hdd PD.fdupm           8212  head 00 00 00 00 00 03 EE 28  nonzero_after_8=0
PD.fdupi vs GT.VOL@0xA6F000 first 0x3E000: identical=True
```

If the head is already ADCH, the override/cache state differs; record it
before interpreting the run.

### 5.2 Build and run with the probe patch

1. Apply `patches/gt6-pfs-decrypt-probe.patch`.
2. Build with the owner's normal `scripts/build-gt6.ps1` (owner runs this).
3. Run headless 20-30 s and grep:

```powershell
$env:PS3_HEADLESS="1"; $env:PS3_VERBOSE="1"; $env:GT6_CONSOLE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\run_pfs_probe.log
Select-String work\agent_pfs\run_pfs_probe.log -Pattern '\[pfsprobe\]|\[scriptload\]|\[scriptov\]|script override'
```

Expected with the override active:

```
[pfsprobe] HFileReader::open ... path='scripts/gt6/main.adc'
[GT6] script override: serving decrypted scripts/gt6/main.adc (857518 bytes)
[scriptov] this=... want_reader=... n=8 pos=0/857518
[scriptload] ADCH read ret=8 ...: 41 44 43 48 30 31 32 00
```

Expected without the override (diagnostic baseline):

```
[pfsprobe] HFileReader::open ... path='scripts/gt6/main.adc'
[pfsprobe] mount factory=... vtable=... key='...' dev144=0x... dev148=0x...
[scriptload] ADCH read ret=0 ...: 00 00 00 00 00 00 00 00
```

If the mount log shows `dev144=0`, the unkeyed cache device is selected; that
is the `0x9FF584` skip. If `dev144!=0` and the bytes are `25 0F FF FE`, the
cipher gate is not the problem; check the file-handle/read path. If the bytes
are `C5 EE F7 FF`, the cipher ran and the SPU inflator is the next failure.

### 5.3 After ADCH succeeds

1. Confirm `0x9CC208` returns nonzero and no `9CDEEC` failure.
2. Confirm the override deactivates after the script stream is consumed
   (`g_script_active=0`), so the next `HFileReader::read` is not served by it.
3. Capture the first asset request and map its GT.VOL `fpos` to an entry:
   `offset = 0x7E800 + SegIndex * 0x800`.
4. Verify that the first asset read uses the same PFS read-through path and
   that `0x9FF530`/`SpuInflator` are called (probe logs).
5. Re-run from a clean cache state (remove `PD.fdupi`, `PD.fdupm`,
   `PDIPFS_bdmark/K/PD`, and the stale disc-tree copies) to prove the fix does
   not depend on a pre-placed file.

## 6. Address index

| Address | Meaning |
|---|---|
| `0x9CD798` | ADHOC script load; path `.adc` append at `0x9CDBD0..0x9CDBFC` |
| `0x9CD69C` | fallback HFileReader construction/open/parse |
| `0x9CD410` | HStreamReader read 8 + `"ADCH"` compare |
| `0x9D9604` | HStreamReader wrapper construction |
| `0x9D8DB0` | HStreamReader read wrapper |
| `0x994078` | buffered stream read; HFileReader vtable slot `+0x11C` dispatch |
| `0x1484CC8` | HFileReader vtable |
| `0x14DCB18` | OPD for HFileReader vtable `+0x11C` -> `0x9BB020` |
| `0x9BB020` | `HFileReader::read` |
| `0x9F4AA0` | filebuf read helper; calls `0x9F3E90` |
| `0x9F3E90` | `device = [HFileReader+0x44]; file = device ? [device+0x40] : 0` |
| `0x9BB11C` | `HFileReader::open` |
| `0x9BB21C` | HFileReader ctor; filebuf at `+0x30` |
| `0x9F4218` | `std::basic_filebuf::open` thunk |
| `0x9F4130` | `std::basic_filebuf::open` |
| `0x9F6BF4` | basic_filebuf open helper |
| `0x9F8E40` | `std::__basic_file::open`; mount/factory walk at `0x15DE908` |
| `0x15DE908` | mount/factory registry (map/list) |
| `0x14889A8` | `PDIPS3::FileDevicePFSBase` vtable |
| `0x14DF910` | PFS file-handle vtable |
| `0x9FF100` | PFS file open/decrypt-state setup (flags at entry `+8`) |
| `0x9FF280` | PFS header/TOC read, decrypt, magic `0x5B74516E` check |
| `0x9FF530` | PFS file-data cipher (seed = FileIndex; tables 17/19/23/29) |
| `0x9FF584` | cipher gate `[device+0x144] != 0` |
| `0x9FF9CC` | skip-decrypt return path |
| `0x9FF328` | header-cipher gate |
| `0x9FF0AC` | install keyset pointer at `[this+0x144]` |
| `0x9FF0B8` | derive `[this+0x148]` from keyset |
| `0x12438` | constructs the PDIPFS device with keyset `0x1410F84` |
| `0x9FD60C` / `0x9FD72C` | `FileDevicePFSBase` ctor / factory |
| `0x9FDF8C` | PFS raw volume read (cellFs read) |
| `0x109BF60` | `PDISTD::SpuInflator` typeinfo name |
| `0x148A2D0` | `SpuInflator` vtable |
| `0xA43AB4` | `SpuInflator` inflate entry |
| `0xA440E4` | `SpuInflator` SPU submit |
| `0x1095168` | `".adc"` string |
| `0x1095058` | `"ADCH"` string |
| `0xFB0AB8` | `"scripts/gt6/main"` string |
| `0x109BF38` / `0x109BF40` | `".fdupi"` / `".fdupm"` strings |

## 7. Caveats

* The exact block-map consumer inside the PDIPS3 cache layer was not isolated
  to a single function; the decisive dynamic evidence is the mount key and
  `[device+0x144]`/`[device+0x40]` at the probe points. The on-disk `.fdupm`
  state (empty map, `ZSize=0x3EE28`) is verified.
* The 1:18 run and the on-disk state in section 1.4 are from
  `pfs-decrypt-check.md` and `tools/gt6_pfs_state.ps1`; this report did not
  re-run the game.
* `gt6/src/stubs.cpp` is the owner's current work. The hardening patch is a
  proposal; it was not applied.
* The boot-script override is a one-file unblock. It must not be treated as
  the PFS decrypt fix: every other compressed file still needs the read-through
  path in 3.2/3.3.
