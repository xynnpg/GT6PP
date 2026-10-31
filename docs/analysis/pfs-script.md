# PFS / GT.VOL and boot-script path - verification report

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Scope:** GT.VOL header/TOC, PFS reads after the TOC, `scripts/gt6/main.adc`,
the `PDIPFS/K/4D` rename failure, and the absolute `cellFs` mappings.

## Verdict

1. **The GT.VOL header and TOC reads are exactly right.** The 160-byte header
   at offset 0 and the 514,436-byte TOC at offset 0x800 match
   `VolumeHeader.bin` / `VolumeTOC.bin` and GTToolsSharp's unpack log.
2. **The guest resolves the volume B-tree correctly.** The first PFS file-data
   read after the TOC is at GT.VOL offset `0xA6F000`, length 290,344 bytes.
   `0xA6F000 = align_up(0x800 + 514436, 0x800) + 5089 * 0x800`, i.e. exactly
   `scripts/gt6/main.adc` (`SegIndex 5089`, `ZSize 0x3EE28`) plus one 32 KiB
   read-ahead.
3. **That read is not proof that the boot script was parsed.** The same bytes
   are written verbatim to `PDIPFS/K/PD.fdupi` by the PDIPFS copy path (it
   coincides with the `ZYWAP` worker and the `PD.fdupm`/`bdmark` probes). The
   copy is byte-identical to the raw encrypted entry, so that path is returning
   stored (encrypted, PS2ZIP) bytes, not a decrypted `ADCH` stream.
4. **The boot-script loader result after the volume read is still unresolved;
   the last measured return was 0.** The current trace is `0x9CC068 -> 0`,
   `0x9D4F50 -> 0`, then `fallback 9CD69C path=...`; no `9CD69C` return /
   `9CC208` / `ADCH` marker is present in the running exe. This is the next
   place to instrument.
5. **The `PDIPFS/K/4D` rename failure is a port mapping bug, not a v1.00
   missing file.** `cellFsOpen/Read/Stat` (runtime `ppu_fs.cpp`) and
   `cellFsRename` (`libs/filesystem/cellFs.c`) resolve `/dev_hdd0` to different
   host roots. It is not fatal to the PFS mount, but it corrupts the extracted
   disc tree and prevents the HDD overlay from ever being created.
6. **`/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` resolves correctly.** The absolute
   `cellFs` mappings now work for the volume. The USRDIR-relative script path
   is not opened through `cellFs` at all; it is resolved (or fails to resolve)
   inside the PFS/script-reader layer.

---

## 1. Volume layout verification

Evidence: `work/agent_pfs/volume_verify.txt`, `work/gt6_unpack.log`.

| Item | Value |
|---|---|
| GT.VOL size | 15,407,310,848 (`0x39658E800`) |
| Header read | 160 bytes (`0xA0`) at fpos 0 |
| Raw header magic | `99 CD DC D6` |
| Decrypted header magic | `0x5B745162` (`[tQb`) |
| TOC node index | 11 |
| Compressed TOC | 514,436 (`0x7D984`) |
| Expanded TOC | 844,860 (`0xCE43C`) |
| Serial | 405,868,366 |
| Title | `GT6-PISCINAS-323419048` |
| TOC read | 514,436 bytes at fpos `0x800` |
| Raw TOC first 4 bytes | `BA BB E7 68` |
| Decrypted TOC | 844,860 bytes, magic `0x5B74516E` |
| Data area | `align_up(0x800 + 0x7D984, 0x800) = 0x7E800` |

The two reads are not sequential (160 then 514,436); the guest seeks to
`0x800` between them:

```
work/agent_pfs/run_fs.err.log
176: [fs] open '/dev_bdvd/PS3_GAME/USRDIR/GT.VOL' -> fd 3
178: [FSDBG] fd=3 ... fpos_before=0     n=160 eof=0
179: [fs] read fd=3 nbytes=160 -> 160 (magic=99CDDCD6, total=160)
181: [fs] open '/dev_bdvd/PS3_GAME/USRDIR/GT.VOL' -> fd 3
183: [FSDBG] fd=3 ... fpos_before=2048 n=514436 eof=0
184: [fs] read fd=3 nbytes=514436 -> 514436 (magic=BABBE768, total=514596)
185: [TOC] data.toc read into buf=0x7006C000 n=514436; lr=0x00A3E65C
```

`0x800 = 2048`; the read is exactly the compressed TOC size. This is the
expected PFS2 layout, not an accident.

The guest's TOC consumer is at `0xA3E65C` (return address inside a thin
`ReadAt`-style wrapper `0xA3E63C -> 0xF92408`). The TOC buffer is at
`0x7006C000`, size 514,436.

---

## 2. What is read after the TOC

### 2.1 The full sequence

From `work/agent_pfs/run_fs.err.log` and `work/gt6_oobfix.log`:

1. `open FAIL '/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/4D'`
   (v1.00 has no PDIPFS overlay; `stat` of `PDIPFS/K` succeeds).
2. Create `PDIPFS/K/4D.psctmp99999`; reopen GT.VOL and copy the 160-byte
   header into the temp file.
3. `cellFsRename(4D.psctmp99999 -> 4D)` fails `ENOENT` (see section 4).
4. Background `ZYWAP` thread:
   `stat PDIPFS/K/PD -> ENOENT`; open `PDIPFS_bdmark/K/PD`;
   open GT.VOL; `stat/open PDIPFS/K/PD.fdupm`; read 20 bytes.
5. Read 290,344 bytes from GT.VOL starting at `0xA6F000`:
   eight 32,768-byte reads plus one 28,200-byte read.
6. No other script, model, audio, or texture reads appear in the captured
   window.

Exact read timeline (`work/agent_pfs/pfs_timeline.txt`):

```
987: [fsread] fd=3 want=32768 got=32768 pos=10940416   # 0xA6F000
990: [fs] read fd=3 nbytes=32768 -> 32768 (magic=250FFFFE, total=547544)
993: ... pos=10973184  # +0x8000
998: ... magic=5FF058EF
1012: ... magic=B70E4DAB
1039: ... magic=3FC7F3A6
1053: ... magic=31626C83
1056: ... magic=CEB09483
1069: ... magic=0914A0E2
1080: [fs] read fd=3 nbytes=28200 -> 28200 (magic=618F8349, total=772352)
```

`10940416 = 0xA6F000`, and every subsequent position is `+0x8000`.
The total is `8 * 0x8000 + 0x6E28 = 0x46E28 = 290,344`.

### 2.2 Why this is `scripts/gt6/main.adc`

`work/gt6_volume_entries.txt`:

```
scripts/gt6/main.adc - Flags: Compressed | FileIndex: 33 (K/PD) | SegIndex: 5089,
                       ZSize: 0003EE28 | Size: 000D15AE | VolIndex: 4294967295
```

Compute:

```
data_area = align_up(0x800 + 0x7D984, 0x800) = 0x7E800
offset    = 0x7E800 + 5089 * 0x800          = 0xA6F000
length    = 0x3EE28 + 0x8000 read-ahead      = 0x46E28 = 290,344
```

The raw bytes at `0xA6F000` start `25 0F FF FE 9B 46 77 B1`, exactly the
magic sequence in the log. `GTToolsSharp crypt -g GT6 -s 33` on exactly
`0x3EE28` bytes from `0xA6F000` produces 857,518 bytes whose SHA-256 is
`5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746`,
byte-identical to `work/gt6_vol/scripts/gt6/main.adc`. So the entry offset,
compressed size, cipher seed 33, and PS2ZIP stream are all correct at the
container level. The TOC decrypt/B-tree walk is therefore proven end-to-end:
if the decrypted TOC were wrong, the guest could not have produced this exact
entry offset and compressed size. File data uses the same cipher primitive with
the file index as seed; GTToolsSharp verifies seed 33 produces the extracted
script, but the log does not show the guest invoking that decrypt/decompress
for the script path.

### 2.3 But the game copied the raw entry, it did not parse it

`PDIPFS/K/PD.fdupi` (253,952 bytes = `0x3E000`) is byte-identical to the
first `0x3E000` bytes of GT.VOL at `0xA6F000`:

```
work/agent_pfs/mapping_rename_evidence.txt
PD.fdupi ... byte-identical=True length=253952 first8=250FFFFE9B4677B1
```

That is the encrypted/PS2ZIP stored stream, not `ADCH012\0`. The 290,344-byte
read therefore coincides with the PFS **copy/overlay** path (raw entry ->
`PD.fdupi`) and the `ZYWAP` worker/`PD.fdupm` sequence; it is not evidence
that the boot-script loader consumed a decrypted file. A thread-tagged read log
would make that attribution exact, but the on-disk copy already proves the
raw-entry path exists and is active.

No `cellFs` open for `scripts/gt6/main.adc` exists in any captured log. The
script loader goes through the PFS layer, not `cellFs`.

---

## 3. Boot-script loader state

The boot chain is unchanged through `main -> 0x13830("scripts/gt6/main")`:

```
0x1096C  main
  0x109A8  bl 0xA13644           ; flag == 0
  0x109C0  bl 0x13830            ; r3 = "scripts/gt6/main" (0x00FB0AB8)
0x13830
  0xA13644                       ; flag == 0
  0x9D3C84 / 0xB98168            ; context + setjmp
  [manager+0x120] -> 0x9A7654
  0x9CDF00 -> 0x9CD798
      0x9CC068(this, path, out)  ; registered-loader map lookup
      0x9D4F50(path)             ; path normalization/extension test
      0x9CD69C(reader, path)     ; fallback HFileReader construction
          0x9BB11C               ; open
          0x9CD410               ; read 8 bytes, compare "ADCH"
          0x9CC208               ; execute/parse
```

Current markers (`work/agent_pfs/scriptloader_evidence.txt`,
`work/agent_pfs/scriptload_run_1303.txt`):

```
1100: [scriptload] 9CC068 -> 0x00000000
1101: [scriptload] 9D4F50 -> 0x00000000
1102: [scriptload] fallback 9CD69C path=0xCFEF8268
```

`0x9CC068 == 0` means no registered loader handler took the path, so the
fallback loader runs. `0x9D4F50 == 0` is consistent with a path that has no
extension (`scripts/gt6/main`, not `.adc`); the fallback is expected to append
`.adc`.

There is **no** `9CD69C` return marker, `reader 9CC208`, `9CC208 ->`, or
`FAIL path 9CDEEC` in the logs. The running `gt6/build/gt6.exe` (timestamp
12:58:30) only seems to contain the first three markers; the later markers
were added to `gt6/generated/ppu_recomp_022.cpp` at 13:00 and are not in that
exe. This is why the trace stops at `fallback 9CD69C` - not necessarily
because the guest is stuck there.

`0x9CD410` is the decisive check. It reads 8 bytes into `stack+0x88` and
compares against `"ADCH"` at `0x1095058`:

```
0x9CD464  bl 0x9D8DB0          ; read 8 bytes
0x9CD46C  r3 = stack+0x88
0x9CD470  r4 = 0x1095058       ; "ADCH"
0x9CD474  r5 = 4
0x9CD478  bl 0xB9AB6C          ; memcmp(first 4, "ADCH", 4)
0x9CD480  bne 0x9CD5F4         ; error: "this file is not adhoc script code"
```

The valid first 8 bytes of the extracted script are
`41 44 43 48 30 31 32 00` (`"ADCH012\0"`). The raw PFS entry starts
`25 0F FF FE ...`. Logging those 8 bytes will separate the two hypotheses
immediately.

---

## 4. `PDIPFS/K/4D` rename failure

This is a split-filesystem bug, not a missing v1.00 overlay.

### 4.1 What happens

```
work/gt6_oobfix.log
259: [fs] open FAIL '/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/4D'
260:   -> 'C:/.../PS3-Version/Gran Turismo 6 (USA) (En,Ja,Fr)/game/BCUS98296/USRDIR/PDIPFS/K/4D'
262: [fs] open '.../PDIPFS/K/4D.psctmp99999' -> fd 3
...
478: [cellFs] Rename(from='.../PDIPFS/K/4D.psctmp99999',
                     to  ='.../PDIPFS/K/4D')
479: [cellFs] Rename: rename('C:\...\work\gt6_hdd0\game\BCUS98296\USRDIR\PDIPFS\K\4D.psctmp99999',
                            'C:\...\work\gt6_hdd0\game\BCUS98296\USRDIR\PDIPFS\K\4D')
              failed: No such file or directory
```

Two different host paths are in play:

| Guest path | `ppu_fs.cpp` (`cellFsOpen/Read/Stat`) | `cellFs.c` (`cellFsRename`) |
|---|---|---|
| `/dev_hdd0/...` | `ppu_vfs_root` = game root (contains `PS3_GAME`) | `cellfs` mapping = `work/gt6_hdd0` |
| resolved | `PS3-Version/.../game/BCUS98296/...` | `work/gt6_hdd0/game/BCUS98296/...` |

`ppu_fs.cpp` does not consult `cellfs_add_path_mapping`; it strips the mount
prefix and appends to `ppu_vfs_root` (`main.cpp` sets that to the game root,
`PS3-Version/Gran Turismo 6 (USA) (En,Ja,Fr)`). `cellFsRename` is implemented in
`third_party/ps3recomp/libs/filesystem/cellFs.c`, which uses the mapping
table. Therefore the temp file is created under the extracted disc tree, while
the rename looks for it under `work/gt6_hdd0`. The source file genuinely does
not exist at the rename source path; the destination directory does exist.

Verified on disk (`work/agent_pfs/mapping_rename_evidence.txt`):

```
work/gt6_hdd0/.../PDIPFS/K/4D.psctmp99999    exists=False
PS3-Version/.../game/.../PDIPFS/K/4D.psctmp99999  exists=True
work/gt6_hdd0/.../PDIPFS/K/4D               exists=False
```

The game also wrote `PD.fdupi` (253,952 bytes, raw `main.adc` entry),
`PD.fdupm` (8,212 bytes), and `PDIPFS_bdmark/K/PD` into the disc tree. That is
the real cost of the bug: the extracted v1.00 tree is being used as writable
HDD storage.

### 4.2 Does it matter?

Not for the volume mount:

* the TOC read and the `main.adc` entry read both happen **after** the rename
  failure;
* the PFS reader is already mounted and usable (read-only from GT.VOL);
* v1.00 has no `USRDIR/PDIPFS` overlay, so the failed `K/4D` open is expected.

It does matter for the intended HDD overlay/cache: the game's temp -> rename
bootstrap never becomes visible, so its PDIPFS/copy state is inconsistent, and
the extracted disc tree is polluted. It is low risk to fix and removes a
confound from later script/asset debugging.

### 4.3 Recommendation

Do **not** pre-create `work/gt6_hdd0/.../K/4D` or `K/` alone; the source of the
rename is in the other root, so the rename will still fail. Do **not** map
`PDIPFS/` to a fake v1.00 overlay; the failing path is
`/dev_hdd0/game/<id>/USRDIR/PDIPFS/...`, not the relative `PDIPFS/` prefix.

Make both `cellFs` halves resolve `/dev_hdd0` identically by setting the
runtime's existing root env vars **before the guest starts**:

```cpp
/* gt6/src/main.cpp, after the gt6_add_mapping calls (~line 650) */
{
    static char hdd0_abs[512], hdd1_abs[512];
    gt6_abs_path(hdd0_abs, sizeof hdd0_abs, "work/gt6_hdd0");
    gt6_abs_path(hdd1_abs, sizeof hdd1_abs, "work/gt6_hdd1");
    _putenv_s("PS3_HDD0_ROOT", hdd0_abs);
    _putenv_s("PS3_HDD1_ROOT", hdd1_abs);
}
```

`ppu_fs.cpp` and `sys_fs.c` already honor `PS3_HDD0_ROOT` / `PS3_HDD1_ROOT`.
After this, `cellFsOpen` creates `K/4D.psctmp99999` under
`work/gt6_hdd0/...`, and `cellFsRename` finds it there. The `PDIPFS/` mapping
becomes unused for this title and can be removed or left as documentation.

Clean up the stale artifacts under `PS3-Version/.../game/BCUS98296/USRDIR`
before re-testing (`PDIPFS/K/4D.psctmp99999`, `PDIPFS/K/PD.fdupi`,
`PDIPFS/K/PD.fdupm`, `PDIPFS_bdmark/K/PD`) so they cannot mask behavior. They
are generated, not part of the dump.

---

## 5. Absolute `cellFs` mapping audit

`gt6/src/main.cpp` now resolves each mapping to an absolute host path
(`gt6_abs_path`) before calling `cellfs_add_path_mapping`, and also sets
`ppu_vfs_root` / `g_sys_fs_root` to the absolute game root.

| Mapping | Resolves to | Status |
|---|---|---|
| `/dev_bdvd/PS3_GAME/` | `.../PS3-Version/.../PS3_GAME/` | **works** (GT.VOL open + correct bytes) |
| `/dev_bdvd/` | `.../PS3-Version/.../` | works |
| `/dev_hdd0/game/BCUS98296/` | `work/gt6_hdd0/game/BCUS98296/` | works only in `cellFs.c` (rename); ignored by `ppu_fs` |
| `/app_home/` | `work/gt6_app_home/` | absolute; not exercised here |
| `/dev_hdd0/` | `work/gt6_hdd0/` | mapping table only; `ppu_fs` still uses `ppu_vfs_root` |
| `/dev_hdd1/` | `work/gt6_hdd1/` | mapping table only; set `PS3_HDD1_ROOT` to align |
| `/dev_usb000/` | `work/gt6_usb/` | absolute; not exercised here |
| `PDIPFS/` | `work/gt6_pdipfs/` | absolute, but unused for `/dev_hdd0/.../PDIPFS/...` paths |

For the volume: `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` resolves to the real
15.4 GB file, and the bytes match. The old double-root bug (USRDIR + relative
mapping) is gone.

For the script path: `cellfs_set_root_path(vfs_abs)` is `.../PS3_GAME/USRDIR`.
A relative `scripts/gt6/main.adc` opened through `cellFs` would become
`.../PS3_GAME/USRDIR/scripts/gt6/main.adc`, which **does not exist** (the
extracted volume is under `work/gt6_vol/`). The boot script is expected to be
resolved by the PFS reader from GT.VOL, not by a host file. No `cellFs` open
for `scripts/gt6/main.adc` is observed. If the fallback `HFileReader` uses
plain `cellFs`, it will miss; the `[scriptload]` markers should show whether
it ever reaches an open.

---

## 6. Ranked hypotheses

### H1 - high: the script reader receives the raw encrypted/PS2ZIP stream

`0x9CD410` reads 8 bytes and compares `"ADCH"`. If the reader supplies the
stored PFS entry (`25 0F FF FE ...`) instead of a decrypted stream
(`41 44 43 48 30 31 32 00`), the check fails, `0x9CD798` returns 0, `0x13830`
returns 0, and `main` proceeds to `0x13BA8` teardown.

Evidence:

* the only file-data read is the raw entry at `0xA6F000`, and its first bytes
  are `25 0F FF FE`;
* the same bytes are written verbatim to `PD.fdupi`;
* `0x9A7654` returns 0 (measured by the owner);
* no `ADCH` success or parser activity appears;
* the volume read itself is correct, so the failure is downstream of the
  B-tree lookup.

This is the most likely single failure and the cheapest to confirm.

### H2 - medium: the fallback `HFileReader` is not wired to the mounted PFS

`0x9CD69C` constructs an object via `0x9BB7E0`, opens it via `0x9BB11C`, then
calls `0x9CD410`. If the reader factory/file-device pointer is null (e.g. a
constructor/order issue), `0x9BB11C` returns 0 and the ADCH check is skipped.
The current logs reach `fallback 9CD69C` but do not yet show its return; the
running exe lacks the later markers. Rebuild and read `9CD69C ->` before
changing anything.

### H3 - medium-low: `.adc` extension/path normalization after `0x9D4F50`

`0x9D4F50` returns 0 for `scripts/gt6/main` (no dot). The fallback then runs a
large std::string sequence to append `.adc` (`0x1095168` is the extension
string). A lifter/refcount bug in that block could produce a bad path or hang.
This is plausible but not yet evidenced; the return marker will tell.

### H4 - low: the `K/4D` rename failure aborts PFS

Rejected. The TOC and `main.adc` entry reads occur after the rename failure,
so the PFS mount survives it. Fix the mapping for hygiene, not because it
blocks the volume.

### H5 - low: the script loads and exits immediately

Inconsistent with `0x9A7654 == 0` and the absence of a `9CC208` marker. The
fallback failure path (`0x9CDEEC`, `r27=0`) is the better fit.

---

## 7. Exact next patch / check

### 7.1 First check (no new code): rebuild with the current instrumentation

The running exe is older than the generated source. Rebuild, run 20-30 s
headless, and grep:

```powershell
powershell -File scripts/build-gt6.ps1
$env:PS3_HEADLESS="1"; $env:PS3_VERBOSE="1"; $env:GT6_CONSOLE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\agent_pfs\run_script.log
Select-String work\agent_pfs\run_script.log -Pattern '\[scriptload\]'
```

Expected markers:

```
[scriptload] 9CC068 -> 0x00000000
[scriptload] 9D4F50 -> 0x00000000
[scriptload] fallback 9CD69C path=...
[scriptload] 9CD69C -> 0x...          <- new
[scriptload] reader 9CC208 this=...   <- new
[scriptload] 9CC208 -> 0x...          <- new
[scriptload] FAIL path 9CDEEC ...     <- if it fails
```

* `9CD69C -> 0`: `0x9BB11C` failed to open/construct the reader. Go to H2.
* `9CD69C -> 1`, then `FAIL path 9CDEEC`: the reader opened but a later check
  failed (most likely ADCH). Go to 7.2.
* `9CC208 -> 1`: the script parsed; move on to asset streaming.

### 7.2 If ADCH fails: log the 8 bytes and the compare

In `gt6/generated/ppu_recomp_022.cpp`, immediately after the read at
`0x9CD464` (generated line ~90392) and before the `0xB9AB6C` compare at
`0x9CD478` (line ~90397), add:

```cpp
fprintf(stderr,
    "[scriptload] ADCH first8=%02X%02X%02X%02X%02X%02X%02X%02X\n",
    vm_base[ctx->gpr[31] + 0], vm_base[ctx->gpr[31] + 1],
    vm_base[ctx->gpr[31] + 2], vm_base[ctx->gpr[31] + 3],
    vm_base[ctx->gpr[31] + 4], vm_base[ctx->gpr[31] + 5],
    vm_base[ctx->gpr[31] + 6], vm_base[ctx->gpr[31] + 7]);
```

The buffer is `stack+0x88` (`r31` at `0x9CD46C`). Expected:

```
valid script : 41 44 43 48 30 31 32 00   ("ADCH012\0")
raw PFS entry: 25 0F FF FE 9B 46 77 B1   (ciphertext/PS2ZIP)
```

Also log the reader-open return at `0x9CD70C`:

```cpp
fprintf(stderr, "[scriptload] 9BB11C -> 0x%X reader=0x%08X\n",
        (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[31]);
```

If the bytes are `25 0F FF FE...`, the fix is to route this reader through
the PFS decrypt/decompress path before `0x9CD410`. The volume reader already
has the custom cipher and PS2ZIP code (the same entry decrypts correctly with
seed 33 in GTToolsSharp); the missing link is the file-device method that
returns a decrypted stream to the script VM. Do not patch `0x9CD410` to accept
ciphertext.

### 7.3 Independent mapping fix (recommended, small)

Apply the `PS3_HDD0_ROOT` / `PS3_HDD1_ROOT` block from section 4.3 in
`gt6/src/main.cpp`. This:

* makes `cellFsOpen` create `K/4D.psctmp99999` under `work/gt6_hdd0`;
* makes `cellFsRename` succeed (`[cellFs] Rename` no longer prints ENOENT);
* stops writing `PD.fdupi` / `PD.fdupm` / `PDIPFS_bdmark` into the extracted
  disc tree;
* does not change the GT.VOL read path.

Verify with:

```
[fs] open '/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/4D.psctmp99999' -> fd ...
[cellFs] Rename(from='...', to='...')          # no "failed:" line
work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/4D  # exists
```

### 7.4 After the script loads

Use the FS logging knobs to see the first asset requests:

```powershell
$env:FS_READ_ALL="1"; $env:PS3_FS_READ_PATH="1"; $env:PS3_FSLOG_READS="3"; $env:PS3_FSLOG="1"
```

`PS3_FSLOG_READS=3` logs `fpos` for every GT.VOL read. Map any new
`fpos`/size to a volume entry with:

```
entry_offset = 0x7E800 + SegIndex * 0x800
```

The first streaming request after `main.adc` will identify the next
subsystem (menu/model/audio) without guessing.

---

## 8. Artifacts

All under `work/agent_pfs/`:

| File | Contents |
|---|---|
| `volume_verify.txt` | Header/TOC fields, data offset, main.adc offset/hash comparison |
| `pfs_timeline.txt` | Exact PFS/cellFs events from the 20 s headless capture |
| `mapping_rename_evidence.txt` | Rename host paths, on-disk existence, PD.fdupi comparison |
| `scriptloader_evidence.txt` | `[scriptload]` markers and instrumentation addresses |
| `scriptload_run_1303.txt` | Slice of the 13:03 run at the fallback loader |
| `run_fs.out.log`, `run_fs.err.log` | 20 s headless diagnostic run with `PS3_FSLOG`, `FS_READ_ALL`, `PS3_FSLOG_TOC`, `PS3_FSLOG_READS=3` |
| `disasm_*.txt` | Guest disassembly of `0x9CD69C`, `0x9CD410`, `0x9CD798`, `0x9BB11C`, `0xA3E63C` |
| `main_enc.bin` | Raw 0x3EE28-byte main.adc entry extracted from GT.VOL at 0xA6F000 |
| `make_*.py`, `find_*.py` | Reproducible extraction/verification scripts |

The 20 s capture was taken while the owner was restarting their run; treat it
as a duplicate of `work/gt6.log` for FS offsets, not as a controlled timing
experiment. It was headless and killed after 20 s; it did not modify game
data.

## 9. Bottom line

* GT.VOL is not the problem: header, TOC, entry offset, cipher seed, and PS2ZIP
  stream all verify byte-for-byte.
* `scripts/gt6/main.adc` **is** read from GT.VOL at `0xA6F000`, but by the
  PDIPFS copy path, which stores the raw encrypted entry in `PD.fdupi`. That is
  not the boot-script parser.
* The next missing lookup is inside the script loader fallback:
  `0x9CD69C -> 0x9CD410 ("ADCH") -> 0x9CC208`. Rebuild with the current
  markers and log the first 8 bytes at `0x9CD410`; that single line will say
  whether the VM is being handed ciphertext or `ADCH012\0`.
* Fix the `/dev_hdd0` split between `ppu_fs.cpp` and `cellFs.c` with
  `PS3_HDD0_ROOT`; it is not the script blocker, but it is a real bug and it
  currently writes overlay files into the extracted disc tree.
