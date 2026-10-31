# `Prototypes.adc` / `HOTREAD8` blocker - independent check

**Date:** 2026-10-31
**Checker scope:** read-only. No source edits, no build, no `gt6.exe` run by this
check. Evidence is GT.VOL/TOC data, the extracted tree, `work/` logs, and static
disassembly of `work/bin/EMAIN.elf`.
**Policy:** `third_party/PDTools` was not read or used. The independent volume
listing was produced with the project's own `tools/GTToolsSharp/win-x64/GTToolsSharp.exe`.

## 0. Verdict summary

| Item | Verdict | Finding |
|---|---|---|
| 1. Is `products/gt6/script/Prototypes.adc` absent from GT.VOL / the extracted tree / the cache-key map? | **PASS** | Absent. A fresh, independent GTToolsSharp listing has 32,591 entries and only `products/gt6/script/Prototypes.mwidget`. |
| 2. Is there a legitimate compiled/cached/aliased producer of that path? | **FAIL (no evidence)** | The file loaders append `.adc` and call `HFileReader::open` + the ADCH parser. No ADCH writer/compiler path to `Prototypes.adc` is evidenced. `Prototypes.mwidget` is MPRJ, not ADCH. |
| 3. Is `HOTREAD8 0x19` a null-base read, not a global byte at address 0x19? | **PASS** | `0x009E1A1C: lbz r0,0x19(r29)` with `r29` from a tree traversal; `r29==0` makes the effective address `0x19`. |
| 4. Is the failed `Prototypes.adc` open causally upstream of the observed null call / spin? | **PASS at script level; FAIL as sole cause** | `MenuClassDefine.adc` line 177 calls `loadPrototype("Prototypes")` and line 178 calls `registerPrimitives(prototypes)`. The failed `.adc` is therefore a real functional blocker. But the first tid-5 null calls follow the `K/W2` cache open, not the failed open, so the `HOTREAD8` is not proven to be caused only by `Prototypes.adc`. |
| 5. Does a host-side compile/alias of `Prototypes.mwidget` to `Prototypes.adc` work? | **FAIL** | MPRJ magic is not ADCH; `0x9CD410` rejects a non-`ADCH` header. A fabricated ADCH is data fabrication and does not supply the real prototype registrations. |
| 6. Why is `.fdupi` 0 while `.fdupm` gets the size? | **PASS (diagnosis)** | The cache constructor writes the `stored_size` header through the implemented cellFs write path. `.fdupi` is opened and passed to `cellFsAllocateFileAreaWithoutZeroFill` (NID `0x7A0329A1`, stub `0xF924B0`), whose HLE at `ppu_fs.cpp:866` is a no-op; the real `cellFsTruncate` (NID `0xC9DC3AC5`) is also unregistered. Decisively, no source block is written. `K/IK` is the working control. |
| 7. Is a write-through fix safer than an override for `Prototypes.adc`? | **PASS for TOC-backed assets; FAIL for this file** | A raw-source write-through is data-faithful and is the right class of fix for `K/W2`/`K/6I`/`K/WO`/etc. It cannot create `Prototypes.adc`, because there are no source bytes. |

**Bottom line:** `Prototypes.adc` is genuinely missing and is used directly by
`MenuClassDefine.adc` (`loadPrototype("Prototypes")`, then
`registerPrimitives(prototypes)`), so it is a real functional blocker. The
measured `HOTREAD8`, however, is not proven to come from that missing open
alone: the immediate tid-5 correlate is the empty PDIPFS cache for `K/W2`
(`CursorProject.gpb`), which is opened right before those null calls. The
safest fix order is: do not fabricate `Prototypes.adc`; obtain the real ADCH or
use the engine's own compile/load path; separately fix the PFS cache
write-through for TOC-backed assets and A/B the spin.

---

## 1. `Prototypes.adc` absence (PASS)

### 1.1 Independent volume listing

A fresh listing was produced without using the old `work/gt6_volume_entries.txt`:

```text
GTToolsSharp.exe listfiles -i gt6/GT.VOL -o %TEMP%\gt6_entries_check.txt
```

Result:

```text
entries: 32592 lines including the final "[!] Wrote 32591 ..." line
products/gt6/script/MenuClassDefine.adc
products/gt6/script/Prototypes.mwidget
```

`Select-String -Pattern 'Prototypes' -CaseSensitive:$false` over that listing
returns only the `.mwidget` row. There is no `Prototypes.adc` row, no
case-variant, and no duplicate under another directory.

The project's existing listings agree:

- `work/gt6_volume_entries.txt`: 32,591 extracted entries; only
  `products/gt6/script/Prototypes.mwidget`.
- `work/gt6_pfs_keymap.tsv`: only `K/6I` maps to `Prototypes.mwidget`; no key
  maps to `Prototypes.adc`.
- `work/gt6_vol/products/gt6/script/`: only `MenuClassDefine.adc` and
  `Prototypes.mwidget`.
- No second distinct `GT.VOL`, update volume, or `PDIPFS` source tree exists in
  the workspace. (The `PS3-Version/.../GT.VOL` copy is byte-for-byte the same
  15,407,310,848-byte disc image.) `work/gt6_hdd0/.../PDIPFS` contains cache
  files only.

### 1.2 The TOC string tables are not a path table

`VolumeTOC.bin` contains the separate name-tree token `Prototypes` at
`0x80C6` and the separate extension token `.adc` at `0x1E85C`. That is **not**
a file entry. GT6's TOC keeps names, extensions, and per-folder file entries in
separate B-trees; a name and an extension in different tables do not imply a
path. GTToolsSharp resolves the actual pairings, and its listing has only
`Prototypes.mwidget`. This rules out the common "the string is in the TOC but
the extractor missed it" explanation.

### 1.3 Cache-key check

The PFS cache key is the TOC `FileIndex` string (`K/6I`, `K/WO`, ...), not a
path. `Prototypes.adc` has no `FileIndex` row, so it cannot be a cache-key
alias for an existing volume entry. `K/6I` is the only prototype key.

---

## 2. Caller and compiler path (file load; no compile path proven)

### 2.1 The code that requests `.adc` is a file loader

`func_005F299C` (`0x5F299C`) is the clearest `.adc` loader:

- `0x5F29DC..0x5F29F0` appends the literal `.adc` (vaddr `0x1053910`) to a
  name and looks up a node.
- It constructs an `HFileReader` and calls `0x9CD410` at `0x5F2CB0`.
- `0x9CD410` reads the 8-byte `ADCH` header and invokes the ADCH parser.
- No compiler/writer call is made in that path.

`func_005F3A44` (`0x5F3A44`) has the same shape: it builds the project/name
reader, appends `.adc` at `0x5F4084..0x5F4094`, and performs the script
lookup/load. `func_005F2D74` also calls `func_005F299C`.

The request in `work/pfstrace.err` is exactly that shape:

```text
6507 [pfs-open] reader=0x7FF170E0 arg=0xCFEFD020 data=0x400E6E10 path='/products/gt6/script/Prototypes.adc'
6511 [pfshint] reader=0x7FF170E0 path='products/gt6/script/Prototypes.adc'
6515 [GT6] pfs override: no extracted file for 'products/gt6/script/Prototypes.adc'
```

### 2.2 No ADCH writer / MPRJ-to-ADCH compiler is evidenced

- The ELF contains exactly three `ADCH` strings (`0x1095058`, `0x1095109`,
  `0x10951A4`), all in the reader/error path. There is no `ADCH012` magic string
  in the binary.
- The only code reference to the `ADCH` literal is `func_009CD410` at
  `0x9CD478`, which compares the first four bytes of an input stream.
- `save_script`, `__node_script_path__`, `has_script`, and `%s/%s/%s.mproject`
  are MPRJ serialization/attribute strings, not an ADCH emitter.
- `func_005FA338`/`func_005FADE4`/`func_005FA7D8` are the `.mproject`/`.mwidget`
  MPRJ loaders. They build UI/project objects; they do not emit ADCH.
- The ADHOC library contains `HStreamWriter`/`HFileWriter` and an `Archive`
  serializer, so saving an already-loaded `HAdhocFile` is conceivable. That is
  not the same as compiling `Prototypes.mwidget` into the missing script, and
  no reference from the MPRJ loader to an ADCH writer was found.

**Conclusion:** the request is a plain missing-file load. A runtime-compiled
output is not proven, and there is no proven MPRJ/alias route to
`products/gt6/script/Prototypes.adc`. If a compiler exists in a PRX/update, it
is not in `EMAIN` and not reachable from the evidence here.

---

## 3. `HOTREAD8` location (PASS: null + 0x19, tree traversal)

Exact log lines (`work/long_run.err`, repeated):

```text
2172 [HOTREAD8] spinning on 0x00000019 val=0x00 tid=26944 guest-fn=0x009E191C
```

The disassembly of `func_009E191C` shows the loop:

```text
009E1A18: clrldi  r29, r31, 0x20
009E1A1C: lbz     r0, 0x19(r29)     ; <-- effective address 0x19 when r29 == 0
009E1A20: cmpwi   cr7, r0, 0
009E1A24: beq     cr7, 0x9E1998     ; 0 == "not sentinel": keep traversing
...
009E1998: addi    r0, r31, 0xC
009E199C: clrldi  r11, r0, 0x20
009E19A0: lwz     r9, 4(r11)
...
009E1A04: lwz     r0, 8(r29)        ; next child
...
009E1A14: mr      r31, r0
```

`r29` is the current tree node; a null child/parent makes `r29 == 0`, so the
load is `0x19`, not a global byte at guest address `0x19`. The byte at `+0x19`
is a node flag/sentinel in this custom tree. A value of 0 makes the loop keep
going, so the `[HOTREAD8]` is a null-pointer tree walk, not a file/status byte.

The accessor is reached from `func_00989048` (`0x989048`), which passes the BSS
global `0x15D5F68` and a key to `func_009E191C`. The global is zero-initialized
BSS; no constructor reference to `0x15D5F68` was found in the lifted code. That
makes an unconstructed/empty tree a plausible root cause, independent of any
file. This is a candidate for a defensive fix (initialize/guard the tree), not
proof that the missing script caused it.

Measurement caveat: the `HOTREAD8` detector is only active when the VM's
read diagnostics are armed (the inline loads are bypassed). `work/pfstrace.err`
has no `HOTREAD8` lines but has the same null-call sequence; absence of the log
there is not evidence that the thread did not spin.

---

## 4. Causality: the failed open is a real script-level blocker (PASS at that level), but not the sole measured trigger (FAIL for the HOTREAD8 claim)

### 4.1 The UI script uses the missing file immediately

`work/agent_proto_menuclass.disasm.txt` is an ADCH disassembly of
`products/gt6/script/MenuClassDefine.adc` (820 instructions, source
`products/gt6/script/MenuClassDefine.ad`). Its top-level frame ends with:

```text
0303B| 177| 808| ATTRIBUTE_EVAL loadPrototype
03046| 177| 809| STRING_CONST Prototypes
0304D| 177| 810| CALL 1
03056| 177| 811| VARIABLE_PUSH prototypes, idx=1
03065|   0| 812| ASSIGN_POP
0306A| 178| 813| VARIABLE_EVAL manager, manager, idx=1
03079| 178| 814| ATTRIBUTE_EVAL registerPrimitives
03084| 178| 815| VARIABLE_EVAL prototypes, idx=1
03093| 178| 816| CALL 1
0309C|   0| 817| POP
030A1|   0| 818| LEAVE depth=0, rewind=1
```

So the boot/UI path explicitly calls `loadPrototype("Prototypes")` and then
`registerPrimitives(prototypes)`. `loadPrototype` loads `Prototypes.mwidget`;
the same sequence requests `Prototypes.adc` (the companion script), and the
script then registers the result. This makes the failed `.adc` a genuine
functional blocker: the script proceeds with a failed/incomplete prototype
result and then registers it. That is a much stronger link than "the file name
appears in a log".

### 4.2 The chronology still has a second failure

`work/pfstrace.err` is the run with PFS tracing and explicit opens:

```text
6507  [pfs-open] ... '/products/gt6/script/Prototypes.adc'
6515  [GT6] pfs override: no extracted file for 'products/gt6/script/Prototypes.adc'
6559  [pfs-open] ... '/projects/gt6/cursor/cursor.mproject'
6581  [GT6] pfs override: serving plaintext ... cursor.mproject
20752 [pfs-open] ... '/projects/gt6/cursor/cursor.adc'
20762 [GT6] pfs override: serving plaintext ... cursor.adc
32424 [fs] open .../PDIPFS_bdmark/K/W2
32427 [fs] open .../GT.VOL
32429 [fs] open .../PDIPFS/K/W2.fdupm
32431 [fs] open .../PDIPFS/K/W2.fdupi
32440 [null-call] ... tid=5 r3=00000070 ... r12=00000004
32455 [GSTACK:nc] ... func_009F44D8+0x44 func_00A08ADC+0x5C func_00A304D0+0x48
```

The failed open at 6507 is not immediately followed by a null call; the game
successfully loads both cursor assets and only later fails at `K/W2`. The same
ordering is in `work/long_run.err`:

```text
1780 [fs] open .../PDIPFS_bdmark/K/W2
1782 [fs] open .../PDIPFS/K/W2.fdupm
1784 [fs] open .../PDIPFS/K/W2.fdupi
1820 [null-call] ... tid=5 r3=00000070 ... r12=00000004
2172 [HOTREAD8] spinning on 0x00000019 ... guest-fn=0x009E191C
```

The `work/gt6.log` snapshot (3:49-3:52 run) shows the same `K/W2` sequence at
1885-1889, then a **main-thread** null call at 1910 whose stack includes
`func_0098A198` (the `0x15D5F68` map lookup), `func_009A7270`,
`func_009CD798`, and the boot-script loader. That main-thread stack is a good
candidate for the `registerPrimitives`/prototype path described in Section 4.1, while
the tid=5 null call at 1820 is a separate `func_009F44D8` task-path failure.
Both are real; the logs do not prove they have the same cause.

### 4.3 Verdict

- **Script-level causality: PASS.** `MenuClassDefine.adc` immediately consumes
  the result of `loadPrototype("Prototypes")`, so the missing `.adc` is not
  optional decoration.
- **Sole cause of `HOTREAD8`: FAIL / unproven.** The first tid=5 null calls
  follow the empty `K/W2` cache read, not the failed `.adc` open. The
  `HOTREAD8` could be the combined result of the missing prototype and the
  malformed `W2` object, or one of them. An A/B is required: provide a valid
  `Prototypes.adc` (or disable only that request) and see whether the spin
  persists; separately fix `K/W2` and see whether it disappears.

---

## 5. Fix-proposal review

No separate fixer proposal document was present at check time (15:58). The
options implied by the context were reviewed against the formats and the
runtime; if the fixer later writes a different proposal, this section should be
re-read against it.

### 5.1 Host compile / alias `Prototypes.mwidget` -> `Prototypes.adc` - FAIL

- `Prototypes.mwidget` starts `4D 50 52 4A` (`MPRJ`), not `41 44 43 48`
  (`ADCH`). Serving it as `.adc` makes `func_009CD410` fail its `ADCH` check
  (`0x9CD478`) and the loader returns failure.
- MPRJ is a serialized UI/project tree (`MComponent`, `MWidget`,
  `MActorSet`, ...); it contains no ADCH symbol table or code frame. The
  `.adc` path is a compiled script with an `ADCH012\0` header, a symbol table,
  and a code frame (see `cursor.adc`: header `ADCH012\0`; symbol 0 begins
  `projects/gt6/cursor/_tmp_cursor.ad`).
- There is no host-side ADCH compiler in this repository, and no compiler
  entry point was found in `EMAIN` (no `ADCH012` writer magic; only the reader
  references `ADCH`).
- A hand-built minimal ADCH would be fabricated data. It would at best make
  the open succeed and would not supply the prototype classes the script
  expects; it can mask the error and cause later null calls.

**Verdict: reject.** This is fabrication, not a port fix.

### 5.2 Override `Prototypes.adc` with bytes from another script - FAIL

Using `cursor.adc`, `MenuClassDefine.adc`, or a stub would be equally
fabricated and semantically wrong. The files have different module/symbol
tables and would register the wrong classes.

### 5.3 PFS write-through / cache repair - PASS for TOC-backed assets, not for `Prototypes.adc`

A write-through that copies the exact GT.VOL **raw source** bytes into
`.fdupi` and sets the `.fdupm` block map is data-faithful: `K/IK` proves the
cache is a raw-source cache, and `K/IK` is byte-identical to its GT.VOL slice.
Do **not** put the extracted plaintext into `.fdupi`; the guest expects the
ciphertext/PS2ZIP source and decrypts it on read. This is the right class of
fix for `K/W2`, `K/6I`, `K/WO`, `K/JH`, and `K/7E`.

It cannot create `Prototypes.adc`: there is no TOC row and no source slice.
Writing synthetic bytes there is the same fabrication problem as Section 5.1.

### 5.4 Guest map initialization / null guard - diagnostic only

Initializing the `0x15D5F68` tree or adding a null check at `0x9E191C` would
stop the `HOTREAD8`, but it does not restore the missing prototypes and would
mask the missing-asset failure. It is useful as a containment/diagnostic step
only after the cache and prototype fixes and an A/B test.

### 5.5 Does each option fabricate, break the cache, or mask?

| Option | Fabricates data? | Breaks `.fdupi`/`.fdupm`? | Masks a real bug? |
|---|---|---|---|
| Alias `.mwidget` as `.adc` | **Yes** | No (HFileReader-only) | Missing compiler/asset |
| Hand-built/minimal ADCH | **Yes** | No | Missing prototype script |
| Pre-place `.fdupi` with wrong bytes | **Yes** | **Yes** (wrong bitmap/size/cipher) | Guest cache writer |
| Write-through exact raw `ZSize` + bitmap | **No** | No, if header/bitmap are consistent | May hide the guest writer, but supplies correct data |
| Initialize/map-guard `0x15D5F68` | No | No | **Yes**, the missing-prototype path |

The only option that is data-faithful is the exact raw write-through; it is
also the only cache-side option that does not invent `Prototypes.adc`.

---

## 6. Why `.fdupi` is 0 while `.fdupm` has the size (PASS)

Current cache state (parsed big-endian, 20-byte header):

| Key | `stored_size` | `block_count` | bitmap bits | `.fdupi` |
|---|---:|---:|---:|---:|
| `K/6I` | `0x580` | 0 | 0 | 0 |
| `K/7E` | `0x3395` | 0 | 0 | 0 |
| `K/JH` | `0x1872` | 0 | 0 | 0 |
| `K/W2` | `0xEA57` | 0 | 0 | 0 |
| `K/WO` | `0xE24` | 0 | 0 | 0 |
| `K/PD` | `0x3EE28` | 0 | 0 | 857,518 (pre-placed) |
| `K/IK` | `0x8BBC0` | 70 | 70 | 572,352 (valid control) |

The code path:

- `0xA42108` constructs the cache object, stores the size at `+0x10`, and
  computes `blocks = (size+0x1FFF)>>13` at `+0x68`.
- `0xA41EB4` loads `.fdupm`, reads the 20-byte header, and stores the loaded
  block count at `+0x20`.
- `0xA42020` builds the `.fdupi` path, opens it with flags `0x42`
  (`O_RDWR|O_CREAT`), then calls the stub at `0xF924B0` with
  `r4=[obj+0x10]` (the size). That import is NID `0x7A0329A1`,
  `cellFsAllocateFileAreaWithoutZeroFill`, **not** `cellFsTruncate`.
- The HLE at `third_party/ps3recomp/runtime/ppu/ppu_fs.cpp:866` is:
  `static void cellFsAllocateFileAreaWithoutZeroFill(...) { ctx->gpr[3] = CELL_OK; }`.
  It returns success without allocating or extending the file. The real
  `cellFsTruncate` (NID `0xC9DC3AC5`, stub `0xF92718`) is a separate import and
  has no handler in `ppu_fs_register()` either.
- Static diagnosis: `.fdupm` gets its `stored_size` because the constructor
  writes the 20-byte header through the implemented `cellFsWrite` path.
  `.fdupi` stays 0 because the source-block write/decrypt/inflate path never
  publishes data. The no-op allocate is not by itself the reason the file is
  0 -- a later `cellFsWrite` would extend it -- and it is not a truncate; it
  is a fidelity gap only (no preallocation). The decisive failure is the
  missing source-block write. This matches the earlier `pfs-wo-fix.md`
  conclusion that no source block is published, and it is why `K/IK`
  (uncompressed, already complete) works while the compressed entries are
  empty.

This is a concrete HLE gap, separate from `Prototypes.adc`. It explains why
`K/IK` (uncompressed, already has a complete cache) works while the compressed
entries have empty data caches.

**Fix implication:** a faithful raw-source write-through is safe and
data-faithful. Implementing `cellFsAllocateFileAreaWithoutZeroFill` as a real
preallocation, or `cellFsTruncate` as a real truncate, would not by itself
supply the source bytes; a zero-filled `.fdupi` is worse than the 0-byte file
for a parser. The write-through of exact `ZSize` raw bytes (plus the bitmap)
is the fix.

---

## 7. Safest next fix

1. **Do not add a `Prototypes.adc` override or alias.** There are no legitimate
   bytes for it in this dump; aliasing `Prototypes.mwidget` is rejected by the
   `ADCH` check, and a fabricated ADCH masks the real missing asset.
2. **Get the real `Prototypes.adc`.** The clean fix is to extract it from a
   complete/updated GT6 package (or the original build output) and verify
   `ADCH012\0`, the symbol table, and the code frame. If no such data exists,
   make `loadPrototype`/`registerPrimitives` fail gracefully and log the
   missing prototype; do not inject synthetic code.
3. **Fix the PFS cache for TOC-backed compressed entries.** Implement a
   write-through that copies exactly `ZSize` raw bytes from GT.VOL into
   `.fdupi` and sets `.fdupm` `block_count` + bitmap.
   `cellFsAllocateFileAreaWithoutZeroFill` (no-op) and `cellFsTruncate`
   (NID `0xC9DC3AC5`, unregistered) should be implemented faithfully if the
   write path needs them, but neither can create the source data. Then A/B
   `GT6_PFS_OVERRIDE=0` / `=1` on `K/W2` and confirm whether the tid-5 null
   call and `HOTREAD8` disappear.
4. **Separately address the `0x15D5F68` tree** only if the spin survives the
   cache/prototype fixes. The accessor has no visible constructor in the lifted
   code; an initialization/guard fix is defensible, but it must not be
   presented as a `Prototypes.adc` fix.
5. **If no real `Prototypes.adc` can be obtained:** make the loader tolerate its
   absence and log it, but expect missing prototype registrations. Do not
   substitute synthetic code.

## 8. Evidence index

| Evidence | Location |
|---|---|
| Independent 32,591-entry listing | `%TEMP%\gt6_entries_check.txt` (GTToolsSharp; recreated during this check) |
| Existing TOC listing / keymap | `work/gt6_volume_entries.txt`, `work/gt6_pfs_keymap.tsv` |
| TOC name/extension tokens | `VolumeTOC.bin` at `0x80C6`, `0x1E85C` |
| Failed open / assets | `work/pfstrace.err:6507,6515,6559,6581,20752,20762` |
| First null call after `K/W2` | `work/pfstrace.err:32424-32455`; `work/long_run.err:1780-1820` |
| `HOTREAD8` | `work/long_run.err:2172` (and repeated) |
| Main-thread null-call stack | captured `work/gt6.log` snapshot at 3:52, lines 1885-1922 (the log file was later truncated by a new run) |
| `.adc` path builder | `func_005F299C` at `0x5F29DC`, `func_005F3A44` at `0x5F4084` |
| ADCH reader | `func_009CD410` at `0x9CD478`; `ADCH` strings at `0x1095058` |
| Tree-walk spin | `func_009E191C` at `0x009E1A1C`; caller `0x989048` |
| Cache object/header | `0xA42108`, `0xA41EB4`, `0xA42020`; `0xF924B0` |
| Allocation/truncate HLE gaps | `cellFsAllocateFileAreaWithoutZeroFill` no-op at `ppu_fs.cpp:866` (NID `0x7A0329A1`); `cellFsTruncate` (NID `0xC9DC3AC5`) unregistered |
| Cache control `K/IK` | `work/gt6_hdd0/.../PDIPFS/K/IK` (572,352 bytes, 70 blocks) |
