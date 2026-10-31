# ADCH parser check: offset 252, the computed goto, and `vector<T> too long`

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`,
`work/gt6_vol/scripts/gt6/main.adc`
**Scope:** independent read-only check of the boot-script parser blocker after the
ADCH stream override. This report does not build or run `gt6.exe`; all runtime
evidence is re-read from the existing logs in `work/`.
**Related:** `docs/analysis/pfs-decrypt-fix.md`,
`docs/analysis/pfs-decrypt-check.md`, `work/final_run.err`,
`work/final_run.log`, `work/ov2_run.err`, `work/ov2_run.log`,
`patches/gt6-adch-switch-dispatch.patch`,
`patches/gt6-adch-reader-hardening.patch`.

## 0. Verdict

| Claim | Verdict | Evidence |
|---|---|---|
| ADCH container is correct: 857,518 bytes, `ADCH012\0`, SHA-256 `5B40…A746` | **PASS** | file header + hash, section 1.1 |
| The override serves the ADCH bytes through `HFileReader::read` | **PASS** | `[scriptov]` lines 1067-1098 of `ov2_run.err` |
| The parser **stops** at file offset 252 | **FAIL** | 32-entry log cap; 252 is the 32nd logged read, not the last read. Section 1.2 |
| Offset 252 is a record boundary / the next read should be 5 bytes at 253 | **PASS** | `05 "Login"` at 252..257. Section 1.2 |
| `vector<T> too long` comes from a bad length field at 252 | **FAIL** | 252 is a 1-byte string length; the exception is a 32-bit bytecode count. Section 3 |
| `vector<T> too long` comes from a stale HFileReader offset | **FAIL** | `+0x1B4` is updated on every override read and no seek occurs. Section 2/3 |
| The missing lifted computed goto at guest `0x987910` is the parser blocker | **PASS** | `ps3_indirect_call` at `0x987910`; runtime logs exactly the table targets. Section 3.5 |
| A seek/readAt hook is sufficient to get past this blocker | **FAIL** | the throw stack contains no file-read frame; it is inside `hExecCode::step`. Section 2.4/3.2 |
| The current tree has the `0x987910` switch fix | **PASS** | `gt6-adch-switch-dispatch.patch` applied at `ppu_recomp_022.cpp`; `apply_gt6_post_lift.py` reapplies it. Section 4.1 |
| The current reader hardening patch is applied | **PASS** | `gt6-adch-reader-hardening.patch` matches the current `stubs.cpp`. Section 4.2 |
| The old `gt6-pfs-boot-override-hardening.patch` still applies | **FAIL** | stale/superseded; `git apply --check` fails. Section 4.3 |
| The switch patch generalizes to other jump tables | **FAIL** | it fixes one table at `0x987910`; the lifter still rejects absolute data bases. Section 4.1/5.1 |
| The reader patch is still a one-file bypass | **FAIL** | it only helps `scripts/gt6/main.adc`; PFS read-through remains unimplemented. Section 4.2 |

**Overall:** the ADCH bytes and the reader override are doing their job. The
"read stops at 252" observation is an artifact of the 32-line diagnostic cap in
`gt6_script_read_override`. The actual blocker is the computed `bctr` at guest
`0x987910`: its six-entry jump table at `0x1419550` contains intra-function case
labels, and the pre-fix generated code lifted the dispatch as
`ps3_indirect_call`, which cannot resolve a mid-function label. The runtime logs
the unresolved targets
`0x9878B8`, `0x987914`, and `0x98792C`; the state machine then runs on a stale
program counter and eventually executes a data word as an `ARRAY_CONST_OLD`
bytecode with an impossible element count. That is what throws
`vector<T> too long`.

### 0.1 Current-tree update (2:21 PM)

The `final_run`/`ov2_run` logs are from 1:50-1:52, before the fixer's latest
edits. The current tree now contains two newer patches:

| Patch | Current state | What it does |
|---|---|---|
| `patches/gt6-adch-switch-dispatch.patch` | applied to `ppu_recomp_022.cpp` at 2:21; reapplied by `tools/apply_gt6_post_lift.py` | replaces the `0x987910` `bctr` with the four-case switch, adds `loc_009878B8/loc_00987914/loc_0098792C`, and forces `HFileReader::open` success while the override is active |
| `patches/gt6-adch-reader-hardening.patch` | applied to `stubs.cpp` at 2:19 | exact path suffix, reader identity, unload/re-arm, trace env, zero buffer counters `+0x1AC/+0x1B0`, `n==0` |

`gt6/build/gt6.exe` is still from 1:04, so the patched tree has not yet been
built/run in the logs available here. The verdict below therefore distinguishes
the **pre-fix logged build** from the **current patched tree**. The switch patch
is the correct fix for the logged blocker; the next step is to build and run it.
The old `patches/gt6-pfs-boot-override-hardening.patch` is superseded by the
new reader hardening patch and no longer applies.

## 1. ADCH structure and the real read sequence

### 1.1 Header and string table

The file is the GTToolsSharp seed-33 output, unchanged:

```
work/gt6_vol/scripts/gt6/main.adc
size 857,518
sha256 5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746
0000: 41 44 43 48 30 31 32 00 99 0C 1A 73 63 72 69 70  |ADCH012....scrip|
0010: 74 73 2F 67 74 36 2F 41 70 70 6C 69 63 61 74 69  |ts/gt6/Applicati|
0020: 6F 6E 2E 61 64 21 73 63 72 69 70 74 73 2F 67 74  |on.ad!scripts/gt|
```

The structure visible from offset 10 is a flat table of length-prefixed strings
(`u8 length` followed by that many bytes):

| Offset | Length | Bytes | String |
|---:|---:|---|---|
| 10 | 0x1A (26) | 11..36 | `scripts/gt6/Application.ad` |
| 37 | 0x21 (33) | 38..70 | `scripts/gt6/.work/release/main.ad` |
| 71 | 0x18 (24) | 72..95 | `scripts/gt6/bootstrap.ad` |
| 96 | 0x04 | 97..100 | `main` |
| 101 | 0x11 | 102..118 | `MINIMUM_HDD_SPACE` |
| 249 | 0x02 | 250..251 | `NP` |
| **252** | **0x05** | **253..257** | **`Login`** |
| 258 | 0x08 | 259..266 | `Recorder` |
| 267 | 0x0A | 268..277 | `Transcoder` |

A read-only parse of the same table finds **611** printable length-prefixed
strings, then a 612th record with a `0x80` (128-byte) length at offset 7,733
whose payload starts with `0x89`; parsing with arbitrary byte values reaches at
least 5,001 records / 79,980 bytes. The first two bytes at 8 and 9 (`0x99`,
`0x0C`) are header counts/flags, not the end of the table.

### 1.2 Why the logged reads end at 252

The pre-fix `gt6/src/stubs.cpp` (the one used for the 1:52 run) had:

```c
static int _n;
if (_n++ < 32)
    fprintf(stderr, "[scriptov] this=0x%08X want_reader=0x%08X n=%u pos=%zu/%zu\n", ...);
```

`ov2_run.err` contains **exactly 32** `[scriptov]` lines (1067-1098). The last is:

```
[scriptov] this=0x7FFD61E0 want_reader=0x7FFD61E0 n=1 pos=252/857518
```

The 33rd call is not logged. At offset 252 the file byte is `0x05`; the next
sequential read would be **`read(5)` at file offset 253**, which returns
`Login`, followed by `read(1)` at 258 and `read(8)` at 259. The log cannot by
itself distinguish "stopped at 252" from "continued past 252", but the parser
later executes an `hExecCode` stream built from the rest of the header, and the
only source for that header is this HFileReader. Therefore it read past 252.
The log cap, not a parser stop, is why the trace ends at 252.

This is important: every conclusion that treats 252 as an ADCH section boundary
or a truncation point is based on a diagnostic cap. It is not a boundary.

### 1.3 What the parser actually consumes

The boot path is still the one in `pfs-decrypt-check.md`:

```
0x9CD798  load "scripts/gt6/main" + ".adc"
0x9CD69C  make HFileReader, open, parse
0x9CD410  HStreamReader::read 8 -> 0x994078 -> HFileReader::read 0x9BB020
```

The `[scriptov]` lines show the same `this` pointer for every logged read
(`0x7FFD61E0`), so in this run there is one reader. The override serves the file
sequentially and updates the guest-visible offset `HFileReader+0x1B4` on each
read. There is no evidence of a duplicated reader or a second source.

## 2. HFileReader/HStreamReader methods and hook sufficiency

### 2.1 HFileReader vtable

`HFileReader` vtable `0x1484CC8`:

| Slot | OPD | Code | Method |
|---:|---|---|---|
| `+0x11C` | `0x14DCB18` | `0x9BB020` | `read(buf, n)` |
| `+0x120` | `0x14DCB10` | `0x9BAFE0` | `seek(offset)` |
| `+0x124` | `0x14DCB00` | `0x9BAF60` | `tell()` |
| `+0x128` | `0x14DCB30` | `0x9BB2E4` | `close()` |

The methods are small and measurable:

* **`tell` (0x9BAF60):** `lwz r3,0x1B4(r3); blr`. It returns only the logical
  file offset.
* **`read` (0x9BB020):** has an internal `0x1000`-byte buffer described by
  `+0x1A8` (buffer data), `+0x1AC` (valid bytes), and `+0x1B0` (cursor). It
  refills through `0x9F4AA0` and, at `0x9BB104`, adds the returned count to
  `+0x1B4`.
* **`seek` (0x9BAFE0):** calls the filebuf seek helper `0x9F49D8`, then sets
  `+0x1B4 = offset`, `+0x1AC = 0`, `+0x1B0 = 0`.
* **`close` (0x9BB2E4):** calls `0x9F40DC`, then zeros `+0x1B4`, `+0x1AC`,
  `+0x1B0` and sets state `+0x18 = 2`.

The vtable layout proves there is no separate `readAt`; seek+read is the only
positioned access. `HStreamReader::read` at `0x994078` is the buffered wrapper
above `HFileReader` and calls the `+0x11C` read slot; `0x994170` calls the
`+0x124` tell slot. A read hook that also maintains `+0x1B4` is therefore
coherent for `tell`, and a seek hook that maintains `+0x1B4` is coherent for
`seek`, **while every read of that reader goes through the override**.

### 2.2 Pre-fix override gaps and current hardening

The pre-fix `gt6_script_read_override` (the one that produced the 1:52 logs) had
the band-aid hazards:

* it served **any** reader while `g_script_active` was set;
* `gt6_script_path_hint` matched `strstr(path, "scripts/gt6/main")`;
* it did not deactivate at EOF;
* it did not re-arm/reset on a second open of the same path;
* it updated `+0x1B4` but left the HFileReader buffer counters `+0x1AC`/
  `+0x1B0` and the underlying filebuf position untouched;
* `gt6_script_seek_override` did not zero `+0x1AC`/`+0x1B0`.

The current `gt6-adch-reader-hardening.patch` fixes the exact suffix, the
reader identity, the unload/re-arm path, the trace switch, and the buffer
counters (section 4.2). The remaining hazards are EOF/close, same-reader
re-open, and the un-seeked device position. The override is still a one-file
bypass, not a general PFS fix.

### 2.3 Is a seek/readAt hook sufficient?

For the **read layer**, a full read+seek+tell+close virtualization can serve the
boot script correctly. The current read+seek hooks are close, but they need the
buffer-counter and reader-identity fixes above.

For the **parser blocker**, a seek/readAt hook is **not sufficient**. The
`vector<T> too long` throw stack (section 3.2) contains
`0x9EEA88 -> 0x9EC220 -> 0x9C9680 -> 0x9C95D4 -> 0xDD8CC8` and no
HFileReader/HStreamReader frame. It happens after the file reads, inside
`hExecCode::step`, when a bytecode operand is executed as an array count.
Adding another read hook cannot change that operand.

### 2.4 Second reader / cache block reader

There is no second reader in the measured run: all 32 logged `[scriptov]`
lines have `this == want_reader == 0x7FFD61E0`. The PDIPFS cache/block reader is
below the file device (`0x9F3E90` returns the device's file object, and
`0x9F4AA0` calls its vtable read at `+0x90`); it is not a second object exposed
to the script parser. The parser's immediate object at `[parser+0x68]` is not a
file reader at all: it is an `hExecCode` bytecode container (RTTI name
`9hExecCode`, vtable around `0x14875B0`). Its `+0x14` slot is the guest function
`0x9EEA88`, the bytecode step routine on the throwing stack.

## 3. `vector<T> too long`: exact provenance

### 3.1 The exception machinery

| Address | Meaning |
|---|---|
| `0x104D298` | literal string `vector<T> too long` |
| `0xDD8CC8` | vector size constructor/check; compares requested count `r4` with `0x3FFFFFFF`, throws if larger |
| `0x9C95D4` | `std::vector`/string construct helper; calls `0xDD8CC8` at `0x9C961C` |
| `0x9C9680` | vector constructor wrapper; calls `0x9C95D4` at `0x9C96AC` |
| `0x9EC220` | ADHOC opcode `0x00` (`ARRAY_CONST_OLD`) handler; calls `0x9C9680` at `0x9EC248` |
| `0x9EEA88` | `hExecCode` step/dispatch; calls the opcode handler at `0x9EEC3C` |
| `0x987884` | parser/token step; calls `hExecCode` slot `+0x14` at `0x9878E4` |
| `0x987A2C` | ADCH module parser; calls `0x987884` at `0x987D8C` |

The opcode table is at `0x1487660`, 24-byte records. Record `0x00` is:

```
name  0x10970D8  "ARRAY_CONST_OLD"
+0x10 0x14DEF50 -> 0x9EC220
```

`func_009EC220` reads its element count from `[r3+4]` (`r28` at `0x9EC240`),
where `r3` is the current bytecode pointer. There is no file-length field and
no HFileReader field in this path.

### 3.2 Throw stack

`work/final_run.log` lines 430-440:

```
exception: vector<T> too long
abort() is called from 0x0000000000b89138
                  from 0x0000000000be2448
                  from 0x0000000000b84c94
                  from 0x0000000000dd9008
                  from 0x00000000009c9620
                  from 0x00000000009c96b0
                  from 0x00000000009ec24c
                  from 0x00000000009eec40
                  from 0x00000000009878e8
                  from 0x0000000000987d90
```

Read bottom-up this is exactly the chain above: `0x987D90` is the return from the
parser call, `0x9878E8` is the return from the `hExecCode` step, `0x9EEC40` is
the return from the opcode dispatch, `0x9EC24C` is the return from the vector
constructor, and `0x9C9620`/`0x9C96B0` are inside the length check. The file
reader is not on this stack.

The logs also show repeated `[setjmp] depth overflow, buffer ... not armed`
around the throw. That is why the exception reaches `abort()` instead of a
guest catch. It is a separate defect (the host setjmp depth is exhausted), not
the origin of the bad operand: even with a working catch, the parser would still
be executing the impossible `ARRAY_CONST_OLD` count.

### 3.3 Not the 1-byte length at 252

The value at 252 is a one-byte string length (`0x05`). The failing count is a
32-bit bytecode operand read by `func_009EC220` from `[r3+4]`; the two are
unrelated. A single byte cannot exceed `0x3FFFFFFF` unless it is misinterpreted
as a 32-bit word, and the throw is in the opcode handler, not in the ADCH string
parser.

### 3.4 Not a stale reader offset

`gt6_script_read_override` updates `HFileReader+0x1B4` after every read, and
`HFileReader::tell` returns only that field. No `[scriptseek]` line appears in
the run. The 32 logged reads are exactly sequential and match the ADCH bytes
(`0`, `8`, `9`, `10`, `11`, `37`, …). A stale `+0x1B4` would show up as a
misaligned read offset in the bytes delivered; the logged reads do not.

### 3.5 The computed goto at 0x987910

The parser step function `func_00987884` (`0x987884..0x987A24`) ends with a
state switch:

```
0x9878F4  lwz   r0, 0x24(r30)      ; parser state
0x9878F8  lis   r9, 0x142
0x9878FC  slwi  r0, r0, 2
0x987900  addi  r9, r9, -0x6AB0    ; 0x1419550
0x987904  extsw r0, r0
0x987908  lwzx  r9, r9, r0
0x98790C  mtctr r9
0x987910  bctr
```

The table at `0x1419550` is:

```
0x1419550: 0x00987914
0x1419554: 0x0098792C
0x1419558: 0x00987A08
0x141955C: 0x00987A08
0x1419560: 0x009878B8
0x1419564: 0x009878B8
0x1419568: 0x00000000
```

All six targets are labels inside the same generated function
(`0x987884..0x987A24`), not function entries. In the **pre-fix** generated code
(the build that produced `final_run`/`ov2_run`), the dispatch at
`ppu_recomp_022.cpp` was:

```c
ctx->gpr[9] = vm_read32(ctx->gpr[9] + ctx->gpr[0]);
ctx->ctr = ctx->gpr[9];
ps3_indirect_call(ctx); return;
```

The current tree replaces this with the explicit switch described in 4.1. In
the pre-fix build, the runtime's `ps3_indirect_call` resolved only
function-table entries. It logged and returned when the target was not a known
function, so the case body never ran. The logs prove this happened:

```
work/final_run.err:1921  unresolved indirect call -> 0x00987914 (lr=0x9878E8)
work/final_run.err:2201  unresolved indirect call -> 0x009878B8 (lr=0x9878E8)
work/final_run.err:2218  unresolved indirect call -> 0x00987914 (lr=0x9878E8)
work/final_run.err:2301  unresolved indirect call -> 0x0098792C (lr=0x9878E8)
```

`0x9878E8` is the return address after the `hExecCode` step call; `bctr` does
not change LR, so all four logs are the same `bctr` dispatching to the table's
case labels. The `bctr` target list and the log list are the same addresses.

The parser's state machine is therefore broken: `hExecCode::step` sets a state,
the switch fails to dispatch to the state-0/1 handler, and the step returns to
`0x987A2C` without the required cursor/operand handling. A later iteration reads
a data word as an `ARRAY_CONST_OLD` opcode and passes the following word as the
element count; `func_009EC220` asks the vector constructor for that many
elements, `0xDD8CC8` sees a value above `0x3FFFFFFF`, and throws.

### 3.6 Why the lifter missed it

`discover_jump_tables` in
`third_party/ps3recomp/tools/ppu_lifter.py` handles an absolute table base only
when the base is inside `.text` (line 4800):

```python
if v is not None and text_lo <= v < text_hi and (v & 3) == 0:
    r_base = cand
    abs_base = v
```

`0x1419550` is in the writable data segment (`PT_LOAD` 1,
`0x1410000..0x155FBAC`), so the base is rejected. Running the stock lifter with
`JT_DEBUG=0x987910` prints:

```
[JT_DEBUG 0x987910] bctr found
[JT_DEBUG 0x987910] rC=r9
[JT_DEBUG 0x987910] lwzx=r9, r9, r0
[JT_DEBUG 0x987910] bases=[]
```

The table entries are never read. This is a lifter heuristic failure, not a
missing guest function. A temporary copy of the lifter with only the
`text_lo <= v < text_hi` condition relaxed for the base produces:

```
[JT_DEBUG 0x987910] bases=[('r9', None, False, None, False, 21075280)]
[JT_DEBUG 0x987910] r_base=r9 abs=0x1419550 table_base=0x1419550 ...
[JT_DEBUG 0x987910]   entry[0] raw=0x987914 -> target=0x987914 valid=True
[JT_DEBUG 0x987910]   entry[1] raw=0x98792C -> target=0x98792C valid=True
[JT_DEBUG 0x987910]   entry[2] raw=0x987A08 -> target=0x987A08 valid=True
[JT_DEBUG 0x987910] decoded 6 targets
```

and the dump gains exactly one dispatcher with four unique cases:

```
0x00987910: 4 case(s): 0x009878B8 0x00987914 0x0098792C 0x00987A08
```

No other GT6 dispatcher changes. That is strong evidence that the general fix is
both correct and low-risk on this binary.

## 4. Review of the current patches

### 4.1 `gt6-adch-switch-dispatch.patch` — PASS, one small defect

This is the patch that addresses the logged blocker. It is applied to
`gt6/generated/ppu_recomp_022.cpp` and re-applied by
`tools/apply_gt6_post_lift.py`, so it survives a relift. It does three things:

1. Adds `loc_009878B8:` at the state 4/5 block.
2. Replaces `ctx->ctr = ctx->gpr[9]; ps3_indirect_call(ctx); return;` with:

```c
switch ((uint32_t)ctx->gpr[9]) {
case 0x00987914u: goto loc_00987914;   /* state 0 */
case 0x0098792Cu: goto loc_0098792C;   /* state 1 */
case 0x00987A08u: goto loc_00987A08;   /* state 2/3: exit */
case 0x009878B8u: goto loc_009878B8;   /* state 4/5: step again */
default: break;
}
ps3_indirect_call(ctx); return;
loc_00987914:
...
```

3. Adds `loc_0098792C:` at the state 1 block, and forces
   `HFileReader::open` success while `gt6_script_override_active()` is true.

The case values, labels, and destinations match the guest table and the
generated case bodies. This is the correct fix for the logged
`vector<T> too long` blocker, and it benefits every ADCH script that uses the
`func_00987884` state machine, not only `main.adc`.

Application check (read-only): `python work/agent_adch_check_patches.py` applies
both new patches to the pre-patch snapshots with `git apply --check` rc=0;
`python tools/gt6_adch_switch_patch.py gt6/generated --check` reports
`already patched` and its `verify_text` passes; `python
tools/post_lift_fixes.py gt6/generated` passes.

**Small defect:** the `default:` path falls through to `ps3_indirect_call(ctx)`
with `ctx->ctr` stale (the patch removed the `ctx->ctr = ctx->gpr[9]` line).
After the preceding `hExecCode` call at `0x9878E4`, `ctx->ctr` still holds that
callee's entry (`0x9EEA88`), so a state outside 0..5 (including table entry 6 =
0) would re-enter the bytecode step instead of logging the bad target. The
expected states are 0..5, so this is unlikely, but a corrupt state should not
recurse. Set `ctx->ctr = (uint32_t)ctx->gpr[9]` before the fallback, or simply
`return;` from the default. This is a one-line robustness fix, not a reason to
reject the patch.

**Scope:** this is a generated-file patch, not a lifter fix. It fixes one
table. Other absolute jump tables in writable data will still be rejected by
`discover_jump_tables` and lifted as unresolved indirect calls. The general
lifter fix in section 5.1 is still needed for those.

**Open-success fallback:** the inserted check is:

```c
if ((uint32_t)ctx->gpr[3] == 0 && gt6_script_override_active())
    ctx->gpr[3] = 1;
```

It is correct for the boot path, but `gt6_script_override_active()` is global,
not per-reader. If a different reader fails to open while a previous boot-script
override is still active, this could force a false success. Prefer a predicate
that checks `g_script_active && g_script_reader == ctx->gpr[3]` (the reader being
opened), or clear the override on close/EOF.

### 4.2 `gt6-adch-reader-hardening.patch` — PASS for hardening, PARTIAL fix

This patch is applied to `gt6/src/stubs.cpp`. It fixes the concrete hazards in
the earlier override:

* exact suffix `scripts/gt6/main.adc` (`gt6_script_path_matches`);
* reader-identity check `gpr[3] == g_script_reader` in read/seek;
* `gt6_script_unload()` on a different path opened on the same reader;
* re-arm of `g_script_data`/position on a fresh script load;
* `GT6_SCRIPT_TRACE` instead of a hard 32-line cap;
* `n == 0` handled;
* zeros the HFileReader buffer counters `+0x1AC`/`+0x1B0` on read and seek, so
  the guest path cannot see stale look-ahead state.

The remaining gaps are:

1. **No EOF deactivation.** At `g_script_pos >= g_script_size` the hook returns
   0 but leaves `g_script_active = 1`. The earlier proposed patch cleared it.
   With the current code, a later `gt6_script_override_active()` remains true,
   and the open-success fallback can force a success for a reader that is not
   actually being served.
2. **Same reader + same path re-open.** `gt6_script_path_hint` returns early if
   `g_script_active && reader_ea == g_script_reader`, so a second open of the
   same script on the same reader reuses the old position. If the engine ever
   re-opens the boot script on the same HFileReader, it will not see a fresh
   stream. Reset `g_script_pos` (and possibly the buffer counters) on re-open,
   or document that the reader is one-shot.
3. **No close hook.** `HFileReader::close` (0x9BB2E4) is not intercepted. The
   override can remain active after the reader is closed/freed. A close hook
   should unload and clear `g_script_reader`.
4. **Device position not advanced.** The override never seeks the underlying
   filebuf/device. If the override is unloaded and the guest `HFileReader::read`
   resumes on the same reader, it will refill from the device's old position
   (usually 0), duplicating data. The zeroed `+0x1AC/+0x1B0` fields make this a
   *clean* refill from the wrong position, not a stale-buffer read. Either keep
   the override active for the reader's lifetime or call the real seek to
   `g_script_pos` on unload.
5. **Path object extraction.** `gt6_script_path_hint` still treats `[str_ea]` as
   the character pointer. A short `std::string` with SSO stores bytes inline;
   this would read a bogus pointer. The boot path is long enough to be
   heap-backed, so it is not the current blocker, but the helper is not general.

The patch is still a **one-file bypass**. It does not implement PFS
read-through, decryption, or inflate for any other entry. It is the right
hardening for the boot-script unblock, not the general PFS fix.

### 4.3 `gt6-pfs-boot-override-hardening.patch` — stale, superseded

The older patch no longer applies:

```
git apply --check patches/gt6-pfs-boot-override-hardening.patch
error: patch failed: gt6/src/stubs.cpp:128
error: gt6/src/stubs.cpp: patch does not apply
```

The current `stubs.cpp` has already moved past it (seek hook, reader hardening,
unload/re-arm). Keep it only as history; use
`gt6-adch-reader-hardening.patch` as the current reader diff.

## 5. Safest next fix

### 5.1 Immediate: build and validate the applied switch patch

The switch patch is already in `ppu_recomp_022.cpp`. The immediate next step is
to build that tree and run it, because the existing logs predate the patch. The
expected result is that the four `unresolved indirect call` addresses disappear
and the `vector<T> too long` abort does not occur.

Before the run:

1. Fix the small `default:` defect in the switch: set
   `ctx->ctr = (uint32_t)ctx->gpr[9]` before `ps3_indirect_call`, or simply
   `return;` from the default. Do not leave a stale CTR.
2. Raise the read trace: use `GT6_SCRIPT_TRACE=1` (the new reader patch) instead
   of the old 32-line cap, and log the final `g_script_pos`.
3. Keep the reader-identity check and exact suffix check.

After the run, confirm:

1. No `unresolved indirect call -> 0x009878B8 / 0x00987914 / 0x0098792C`.
2. `0x9CC208` returns nonzero and there is no `vector<T> too long`.
3. The parser reaches the next boot stage (the first asset load) instead of
   exiting with code 1.

### 5.2 Durable: generalize the lifter

The applied switch patch is a post-lift patch for one table. The durable fix is
in `discover_jump_tables`:

1. Allow an absolute base to live in a mapped data segment, not only `.text`.
2. Keep the existing per-entry validation strictly in `.text`
   (`text_lo <= target < text_hi`, word-aligned).
3. For data-resident absolute bases, add a strict guard: require at least three
   distinct in-text targets within, say, 1 MB of the `bctr` (the GT6 table has
   four unique targets within `0x150` bytes).
4. Add a regression test with this exact table:
   `bctr 0x987910 -> [0x9878B8, 0x987914, 0x98792C, 0x987A08]`.
5. Re-lift. `func_00987884` should then contain the switch natively and no
   `ps3_indirect_call` for `0x987910`.

The temp-copy experiment above already shows the one-dispatcher / four-target
delta on GT6, so this is a low-risk generalization. Until it is done, the
post-lift patch must be kept in `apply_gt6_post_lift.py` and re-verified after
every relift.

### 5.3 Reader hardening: close the remaining gaps

The applied reader patch is a good hardening of the one-file unblock, but the
following should be addressed before it is treated as stable:

1. Deactivate or unload on EOF (or hook `HFileReader::close`), so
   `gt6_script_override_active()` cannot remain true after the reader is gone.
2. Reset the position when the same reader re-opens the same path, or document
   that the reader is one-shot.
3. On unload/close, seek the underlying device to `g_script_pos` (or close it),
   so the guest path cannot refill from the device's old position.
4. Make the open-success fallback reader-specific:
   `g_script_active && g_script_reader == opened_reader`, not a global predicate.
5. Handle `std::string` SSO in `gt6_script_path_hint` if the helper is ever used
   for short paths.

### 5.4 Do not use a seek/readAt hook as the parser fix

Keep the reader work separate. A seek/readAt hook is useful for a correct
one-file stream and should be part of the eventual PFS read-through, but it
cannot change the `hExecCode` operand that throws. If it is presented as the
fix, the next run will still abort at `0x9EEC40`.

### 5.5 Clean-cache verification

Once the parser runs, re-run from a clean cache state (no pre-placed
`PD.fdupi`/`PD.fdupm`) and confirm the boot script is served by the override
without depending on the empty PFS cache. Then confirm the first asset read
uses the guest PFS path, not the boot-script override.

## 6. Evidence index

| Address / file | Meaning |
|---|---|
| `work/gt6_vol/scripts/gt6/main.adc` | 857,518-byte ADCH, SHA-256 `5B40…A746` |
| offsets 249/252/253/258 | `02 "NP"`, `05 "Login"`, `08 "Recorder"` |
| `gt6/src/stubs.cpp` `gt6_script_path_hint` (line 113) | exact suffix + unload/re-arm |
| `gt6/src/stubs.cpp` `gt6_script_seek_override` (line 171) | seek + zero buffer counters |
| `gt6/src/stubs.cpp` `gt6_script_read_override` (line 187) | reader check, trace, `+0x1AC/+0x1B0` |
| `ov2_run.err:1067-1098` | 32 `[scriptov]` lines, last `pos=252` |
| `0x1484CC8` + `0x11C/0x120/0x124/0x128` | HFileReader read/seek/tell/close |
| `0x9BB020` | HFileReader::read; buffer `+0x1A8/+0x1AC/+0x1B0/+0x1B4` |
| `0x9BAFE0` | HFileReader::seek; zeros `+0x1AC/+0x1B0` |
| `0x9BAF60` | HFileReader::tell; returns `+0x1B4` |
| `0x9BB2E4` | HFileReader::close; zeros offsets |
| `0x994078` | HStreamReader buffered read; calls vtable `+0x11C` |
| `0x994170` | HStreamReader tell/seek wrapper; calls `+0x124` |
| `0x9F3E90` | device -> `[device+0x40]` file object |
| `0x9F4AA0` | filebuf read helper; calls file object vtable `+0x90` |
| `0x987884..0x987A24` | parser step `func_00987884` |
| `0x9878F4..0x987910` | state jump table load + `bctr` |
| `0x1419550` | 6-entry table: `0x987914, 0x98792C, 0x987A08, 0x987A08, 0x9878B8, 0x9878B8` |
| `0x987A2C` | ADCH module parser (calls step at `0x987D8C`) |
| `0x98759C..0x987EC8` | parser region containing both functions |
| `0x1487660` | ADHOC opcode descriptor table, 24-byte records |
| record `0x00` | `ARRAY_CONST_OLD` -> `0x9EC220` |
| `0x9EEA88` | `hExecCode` step/dispatch; `+0x14` vtable slot |
| `0x9EC220` | `ARRAY_CONST_OLD` handler; reads count `[bytecode+4]` |
| `0x9C9680` | vector constructor wrapper |
| `0x9C95D4` | calls `0xDD8CC8` length check |
| `0xDD8CC8` | throws `vector<T> too long` for count > `0x3FFFFFFF` |
| `0x104D298` | literal `vector<T> too long` |
| `final_run.err:1921/2201/2218/2301` | unresolved `0x987914`, `0x9878B8`, `0x987914`, `0x98792C` |
| `final_run.log:430-440` | exception + abort stack |
| `ppu_lifter.py:4800` | absolute-base `.text` restriction |
| `patches/gt6-adch-switch-dispatch.patch` | applied switch for `0x987910`; reapplied by `tools/apply_gt6_post_lift.py` |
| `patches/gt6-adch-reader-hardening.patch` | applied reader hardening for `stubs.cpp` |
| `patches/gt6-pfs-boot-override-hardening.patch` | stale/superseded; `git apply --check` fails |
