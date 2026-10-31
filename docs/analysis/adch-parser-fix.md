# ADCH boot-script parser: the 0x987910 switch, not a stop at offset 252

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/bin/EMAIN.elf`
**Scope:** static disassembly of the ADCH loader/value reader, the on-disk
`work/gt6_vol/scripts/gt6/main.adc`, and the measured `work/ov2_run.err` /
`work/ov2_run.log` traces; plus the generated-code patch and the reader
hardening in `gt6/src/stubs.cpp`.
**Relation to earlier reports:** corrects the "after offset 252 it switches away
from `HFileReader::read`" conclusion in the "Final measured script result"
section of `docs/analysis/CONTINUE-HERE.md`. The PFS/reader analysis in
`docs/analysis/pfs-decrypt-fix.md` remains valid; this report only fixes the
parser step after the stream is served.

**Read-only work:** this report did not run a relift, build, or `gt6.exe`.
The current `gt6/generated/ppu_recomp_022.cpp` was patched in place so the owner
can build without waiting for a relift; `tools/apply_gt6_post_lift.py` reapplies
the same patch after any relift.

## 0. Verdict

1. **The parser does not stop at ADCH offset 252.** The 32 `[scriptov]` lines
   in `work/ov2_run.err` are the 32-line cap in the old
   `gt6_script_read_override` (`if (_n++ < 32)`), not a parser stop. The 33rd
   `HFileReader::read` is offset **253, length 5** (`"Login"`). A faithful
   model of the v12 reader reaches the code frame at `0x1BD15` after **12,861**
   read calls (12,847 of them the 6,412 symbols), then decodes the first
   instructions.
2. **The real blocker is the lifted `bctr` at guest `0x987910` in
   `func_00987884` (guest `0x987884`).** The state machine dispatches through a
   six-entry table at `0x1419550`:
   `0x987914, 0x98792C, 0x987A08, 0x987A08, 0x9878B8, 0x9878B8`.
   All four targets are **local blocks** of `0x987884`, not function entries.
   The switch-based lift emitted `ps3_indirect_call(ctx); return;`, the runtime
   cannot resolve an intra-function target, and the value reader returns
   without completing a value.
3. **`vector<T> too long` is downstream of that early return.** A misread
   value can select the type-0 reader `0x9EC220` (table `0x1487660`), which
   builds a vector from a count in the stream. `0xDD8CC8` rejects a count above
   `0x3FFFFFFF` and throws the guest libc++ `length_error` whose message is at
   `0x104D298`. The abort stack in `work/ov2_run.log` lines 429-439 is this
   path, not an ADCH format mismatch.
4. **The fix is a generated-code switch plus the existing boot-script stream
   override.** Do **not** add `0x987914/0x98792C/0x987A08/0x9878B8` to the lift
   list: they are intra-function labels. `0x987884` is already a lifted
   function start; no new function boundary is needed.

## 1. What the read trace actually shows

### 1.1 The 32-line cap

`gt6/src/stubs.cpp` (before this fix) logged:

```c
static int _n;
if (_n++ < 32)
    fprintf(stderr, "[scriptov] ...");
```

`work/ov2_run.err` lines 1067-1098 are exactly those 32 entries. The last one is:

```
1098: [scriptov] this=0x7FFD61E0 want_reader=0x7FFD61E0 n=1 pos=252/857518
```

There is no 33rd line because the cap hides it, not because the parser stopped.
The on-disk byte at 252 is `0x05`, the length of the 15th symbol; the next call
must be `read(253, 5)`.

### 1.2 The exact read model

The ADCH v12 reader (GTAdhocToolchain's `AdhocFile.ReadFromFile` /
`AdhocStream` format, MIT) does:

1. `read(8)` for the magic/version.
2. `VarInt` symbol count, one byte at a time.
3. For each symbol: `VarInt` length, one byte at a time, then one `read(length)`.
4. Code-frame fields (booleans/`u32`/symbols), then the instruction stream.

`tools/adch_read_trace.py` reproduces that sequence. The first 40 calls are:

| call | offset | len | record |
|---:|---:|---:|---|
| 0 | 0 | 8 | `ADCH012\0` |
| 1 | 8 | 1 | symbol-count VarInt byte 0 = `0x99` |
| 2 | 9 | 1 | symbol-count VarInt byte 1 = `0x0c` |
| 3 | 10 | 1 | symbol 0 length = 26 |
| 4 | 11 | 26 | `scripts/gt6/Application.ad` |
| 5 | 37 | 1 | symbol 1 length = 33 |
| 6 | 38 | 33 | `scripts/gt6/.work/release/main.ad` |
| 7 | 71 | 1 | symbol 2 length = 24 |
| 8 | 72 | 24 | `scripts/gt6/bootstrap.ad` |
| 9 | 96 | 1 | symbol 3 length = 4 |
| 10 | 97 | 4 | `main` |
| 11 | 101 | 1 | symbol 4 length = 17 |
| 12 | 102 | 17 | `MINIMUM_HDD_SPACE` |
| 13 | 119 | 1 | symbol 5 length = 7 |
| 14 | 120 | 7 | `__mul__` |
| 15 | 127 | 1 | symbol 6 length = 24 |
| 16 | 128 | 24 | `REPLAY_MINIMUM_HDD_SPACE` |
| 17 | 152 | 1 | symbol 7 length = 25 |
| 18 | 153 | 25 | `INSTALL_MINIMUM_HDD_SPACE` |
| 19 | 178 | 1 | symbol 8 length = 16 |
| 20 | 179 | 16 | `PROJECT_ROOT_DIR` |
| 21 | 195 | 1 | symbol 9 length = 16 |
| 22 | 196 | 16 | `PRODUCT_ROOT_DIR` |
| 23 | 212 | 1 | symbol 10 length = 4 |
| 24 | 213 | 4 | `MGOM` |
| 25 | 217 | 1 | symbol 11 length = 10 |
| 26 | 218 | 10 | `PDINetwork` |
| 27 | 228 | 1 | symbol 12 length = 20 |
| 28 | 229 | 20 | `networkServerEnabled` |
| 29 | 249 | 1 | symbol 13 length = 2 |
| 30 | 250 | 2 | `NP` |
| 31 | 252 | 1 | symbol 14 length = 5 |
| **32** | **253** | **5** | **`Login`** |
| 33 | 258 | 1 | symbol 15 length = 8 |
| 34 | 259 | 8 | `Recorder` |

The first 32 calls are byte-for-byte the measured `[scriptov]` trace. The
parser therefore consumed the stream correctly at least through the point the
log stops.

### 1.3 The whole file parses

`python tools/adch_read_trace.py work/gt6_vol/scripts/gt6/main.adc --reads 40`
prints:

```
size        : 857518 (0xD15AE)
magic       : b'ADCH012\x00' version=12
symbol count: 6412 (VarInt ends at 0xA)
symbols end : 0x1BD15
code frame  : 0x1BD15
  has_debug=1 frame_version=12 source=b'scripts/gt6/Application.ad' has_rest=0
  params=0 captured=0 unknown=0
  stack=12 local=4 static=1590 instruction_count=5564
  first instruction at 0x1BD35
  read calls through code-frame header: 12861
```

The symbol count is the VarInt `0x99 0x0c` = `0x190C` = 6412 (not a 16-bit
integer). The table ends exactly at the last symbol's bytes; the code-frame
header at `0x1BD15` is sane and the instruction count is 5564. This is a valid
ADCH v12 file, so the failure is not a header/format mismatch or a stale reader
length. The inspector decodes only the first few instructions (SOURCE_FILE and
INT_CONST) to show the frame starts on an instruction boundary; decoding the
full 5,564-instruction stream is not needed to locate the failure.

### 1.4 No seek/tell/readAt in the measured trace

`work/ov2_run.err` has no `[scriptseek]` lines. The reader is consumed
sequentially through `HFileReader::read` (`0x9BB020`). The `HStreamReader`
wrapper (`0x9D9604` / `0x9D8DB0` / `0x994078`) does not fill its 0x20 buffer in
this path; the override is the only byte source. There is no second reader
virtual to hook at offset 252.

## 2. The actual blocker: the state-machine `bctr` at 0x987910

### 2.1 Guest code

`0x987884` is the value reader used by the script VM step `0x987A2C`
(call at `0x987D8C`, return at `0x987D90`). Its state is `this+0x24`, its value
stack is at `this+0x6C` (`+0x6C` begin, `+0x70` end, `+0x74` cap), and its
stream object is at `this+0x68`.

The dispatch block is:

```
009878F4: lwz   r0, 0x24(r30)      ; state
009878F8: lis   r9, 0x142
009878FC: slwi  r0, r0, 2
00987900: addi  r9, r9, -0x6AB0    ; table 0x1419550
00987904: extsw r0, r0
00987908: lwzx  r9, r9, r0         ; target
0098790C: mtctr r9
00987910: bctr
```

The table at guest `0x1419550` contains:

```
00 98 79 14   00 98 79 2c   00 98 7a 08
00 98 7a 08   00 98 78 b8   00 98 78 b8
```

i.e. state 0 -> `0x987914`, state 1 -> `0x98792C`, states 2/3 -> `0x987A08`,
states 4/5 -> `0x9878B8`. All four are labels inside `0x987884`
(`0x987884..0x987A28`); none is a function entry.

### 2.2 Generated code

The switch-based lift produced this in `gt6/generated/ppu_recomp_022.cpp`
(before the patch):

```c
        ctx->gpr[9] = vm_read32((ctx->gpr[9] + ctx->gpr[0]));
        ctx->ctr = ctx->gpr[9];
        ps3_indirect_call(ctx); return;
        ctx->gpr[3] = ppc_rldicl(ctx->gpr[28], 0, 32);   /* dead: 0x987914 */
        ...
```

`ps3_indirect_call` looks the target up in the function table. `0x987914` is
not a function start, so it logs `unresolved indirect call -> 0x00987914` and
returns. The `return` then exits `func_00987884` without executing the case.

### 2.3 Log evidence

`work/ov2_run.err` has four target-transition lines:

```
1640: [ppu] unresolved indirect call -> 0x00987914 (tid=1 lr=0x009878E8)
2089: [ppu] unresolved indirect call -> 0x009878B8 (tid=1 lr=0x009878E8)
2110: [ppu] unresolved indirect call -> 0x00987914 (tid=1 lr=0x009878E8)
2187: [ppu] unresolved indirect call -> 0x0098792C (tid=1 lr=0x009878E8)
```

`lr=0x009878E8` is exactly the instruction after the virtual call at
`0x9878E4`, i.e. the state machine's own dispatch site. The runtime suppresses
a repeated identical target (`ppu_loader.cpp` lines 2969-2998: `cur == last`
returns without logging), so four lines do **not** mean four failures; the
`bctr` can fail on every value.

The 32-read cap and the four unresolved-call lines together created the
"stops after 252" impression. The read stream is fine; the state machine
returns early after a value read.

## 3. Why `vector<T> too long` follows

The VM value-reader returns early with a half-read value. Later, the typed-value
reader at `0x9EEA88` reads a type tag:

```
009EEC14: lbz   r0, 0(r10)          ; type tag
009EEC18: slwi  r9, r0, 5
009EEC1C: slwi  r0, r0, 3
009EEC20: subf  r9, r0, r9          ; tag * 24
009EEC24: addi  r9, r9, 0x10
009EEC28: extsw r9, r9
009EEC2C: lwzx  r11, r29, r9        ; table 0x1487660
009EEC30: lwz   r0, 0(r11)
009EEC34: lwz   r2, 4(r11)
009EEC38: mtctr r0
009EEC3C: bctrl
```

Table `0x1487660` has 24-byte entries; tag 0 selects `0x9EC220`, a vector
reader. It uses `[r3+4]` as the element count and calls:

```
0x9EC220 -> 0x9C9680(count) -> 0x9C95D4(count)
0x9C95D4 -> 0xDD8CC8(count)
```

`0xDD8CC8` compares the count with `0x3FFFFFFF`; on overflow it builds
`std::length_error` from the string at `0x104D298` (`"vector<T> too long"`) and
calls the throw helper at `0xB84C28`. The measured abort stack is exactly this
chain:

```
work/ov2_run.log:428  exception: vector<T> too long
work/ov2_run.log:429  abort() is called from 0xB89138
work/ov2_run.log:430    from 0xBE2448
work/ov2_run.log:431    from 0xB84C94
work/ov2_run.log:432    from 0xDD9008   (throw helper return)
work/ov2_run.log:433    from 0x9C9620   (0x9C95D4 after 0xDD8CC8)
work/ov2_run.log:434    from 0x9C96B0   (0x9C9680 after 0x9C95D4)
work/ov2_run.log:435    from 0x9EC24C   (0x9EC220 after 0x9C9680)
work/ov2_run.log:436    from 0x9EEC40   (0x9EEA88 after the type dispatch)
work/ov2_run.log:437    from 0x9878E8   (0x987884 after the stream virtual)
work/ov2_run.log:438    from 0x987D90   (0x987A2C after 0x98787C)
work/ov2_run.log:439    from 0x00000000
```

The exact count value was not captured dynamically, but the real code frame has
`instruction_count=5564` and no field near `0x3FFFFFFF`; a genuine ADCH count
cannot trigger this. The count is a consequence of the early-returned value,
not a format error.

## 4. Fix

### 4.1 Generated-code switch (the functional fix)

`tools/gt6_adch_switch_patch.py` rewrites the one dispatch in
`func_00987884`:

```c
        switch ((uint32_t)ctx->gpr[9]) {
        case 0x00987914u: goto loc_00987914;
        case 0x0098792Cu: goto loc_0098792C;
        case 0x00987A08u: goto loc_00987A08;
        case 0x009878B8u: goto loc_009878B8;
        default: break;
        }
        ctx->ctr = ctx->gpr[9];   /* unknown target: keep the old fallback */
        ps3_indirect_call(ctx); return;
loc_00987914:
        ctx->gpr[3] = ppc_rldicl(ctx->gpr[28], 0, 32);
        ...
loc_0098792C:
        ctx->gpr[29] = ppc_rldicl(ctx->gpr[28], 0, 32);
loc_00987930:
        ...
loc_009878B8:
        ctx->gpr[11] = vm_read32(ctx->gpr[30] + 0x68);
        ...
```

The case bodies already existed after the old `ps3_indirect_call; return;` as
dead code; the patch only adds the labels and the switch. `loc_00987A08` and
`loc_00987920` already existed. `tools/gt6_adch_switch_patch.py` verifies that
all four labels and gotos are present and is idempotent.

The current `gt6/generated/ppu_recomp_022.cpp` is patched; the diff is
`patches/gt6-adch-switch-dispatch.patch`.

### 4.2 Force the open-success branch

`gt6/src/stubs.cpp` serves the script from the host file, but
`func_009CD69C` still gates the whole load on `HFileReader::open`
(`0x9BB11C`). The measured run opens successfully (the empty `PD.fdupi` exists),
but a clean run with no cache file would take the failure branch at
`0x9CD784` and never reach `0x9CD410`. The patch adds, after the open call:

```c
if ((uint32_t)ctx->gpr[3] == 0 && gt6_script_override_active())
    ctx->gpr[3] = 1;   /* boot-script override needs no PFS file object */
```

`gt6_script_override_active()` is defined in `gt6/src/stubs.cpp` and declared by
`tools/apply_gt6_post_lift.py`.

### 4.3 Reader hardening

`gt6/src/stubs.cpp` (diff: `patches/gt6-adch-reader-hardening.patch`):

* `gt6_script_path_hint` matches the exact suffix `scripts/gt6/main.adc` (the
  measured path is `/scripts/gt6/main.adc`), not a loose `strstr`.
* It unloads the override when a different file is opened on the same
  `HFileReader`, and reloads/reset when the same script path is opened again.
* `gt6_script_read_override` serves only `g_script_reader` (the HFileReader that
  opened the script). It no longer hijacks unrelated readers.
* It handles `n == 0`, returns a short count at EOF, and keeps the guest-visible
  file offset at `+0x1B4` in sync with `g_script_pos`.
* It keeps the real HFileReader read-ahead fields `+0x1AC` (buffer length) and
  `+0x1B0` (buffer position) at zero. The override serves no look-ahead; leaving
  stale values there would confuse `HFileReader::tell`/`read`.
* `gt6_script_seek_override` resets the same fields and writes `+0x1B4`.
* `GT6_SCRIPT_TRACE=1` logs every read/seek (the old 32-line cap is gone from
  the default path; the trace is opt-in so normal logs stay small).

### 4.4 Relift integration

`tools/apply_gt6_post_lift.py` now imports `gt6_adch_switch_patch` and runs it
after the setjmp guards and the script hooks. `scripts/relift-gt6.ps1` already
calls this script at step 5, so a relift reapplies the switch and the
`gt6_script_override_active` declaration. `tools/post_lift_fixes.py` (step 7)
now also fails the relift if `func_00987884` no longer contains the switch, so
a silent regression is caught before the build.

## 5. What not to do

* **Do not add `0x987914`, `0x98792C`, `0x987A08`, or `0x9878B8` as functions.**
  They are labels inside `0x987884`; the cases rely on the prologue's `r28`,
  `r30`, and `r31` and on falling through the loop labels. A separate function
  body would have no prologue, would use caller-saved registers, and would
  duplicate the state machine. The only function start is `0x987884`.
* **Do not patch the ADCH data.** The file has 6412 symbols and a valid 5564-
  instruction code frame; the read model reaches the end without a format error.
* **Do not patch the `ADCH` compare at `0x9CD478` or fake only the 8-byte
  header.** The same reader supplies the symbol table and code frame; a partial
  header would misalign the rest.
* **Do not treat the four unresolved-call lines as the whole count.** The
  runtime suppresses repeated identical targets; the `bctr` fails on every
  value until the switch is fixed.

## 6. Verification

### 6.1 Static (no build)

```powershell
python tools\adch_read_trace.py work\gt6_vol\scripts\gt6\main.adc --reads 40
python tools\gt6_adch_switch_patch.py gt6\generated --check
python tools\apply_gt6_post_lift.py gt6\generated
```

Expected:

```
symbol count: 6412 (VarInt ends at 0xA)
symbols end : 0x1BD15
  stack=12 local=4 static=1590 instruction_count=5564
  read calls through code-frame header: 12861
   32: offset=   253 (0x000FD) len=5

gt6\generated\ppu_recomp_022.cpp: already patched
post-lift: setjmp guards added 0; script hooks changed 0; ADCH switch changes 0
```

`python tools\gt6_adch_switch_patch.py gt6\generated --diff` prints the exact
hunks; `patches/gt6-adch-switch-dispatch.patch` applies cleanly to the
pre-patch file (checked with `git apply --check`). The patched
`func_00987884` was also extracted with stubbed helpers and compiled with
`clang++ -std=c++17 -fsyntax-only` (not a full build); it passes, so the
forward/backward gotos do not jump over an initialization. `gt6/src/stubs.cpp`
passes `clang++ -std=c++20 -fsyntax-only` with the include paths from
`gt6/CMakeLists.txt`.

### 6.2 Build/run (owner)

Build normally, then run with the reader trace on:

```powershell
$env:PS3_HEADLESS="1"; $env:PS3_VERBOSE="1"; $env:GT6_CONSOLE="1"
$env:GT6_SCRIPT_TRACE="1"
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\adch_verify.log
```

Expected:

* `[GT6] script override: serving decrypted /scripts/gt6/main.adc (857518 bytes)`
* `[scriptov] ... n=1 pos=252/857518` followed by
  `[scriptov] ... n=5 pos=253/857518` (and the rest of the symbol table).
* No `[ppu] unresolved indirect call -> 0x00987914`, `0x009878B8`, or
  `0x0098792C`.
* No `exception: vector<T> too long` and no `sys_process_exit(code=1)`.
* `0x9CC208` reaches the code-frame parse and the script returns normally; the
  next blocker (if any) is after the script load, not the parser.

If a read still fails, the trace now logs **every** `[scriptov]` call; the
first line where `pos` jumps, a read returns 0, or `this` differs from the
override reader identifies the next stream consumer. `GT6_SCRIPT_TRACE=1` is
the replacement for the old 32-line cap.

### 6.3 If a new failure appears

* If the failure is `unresolved indirect call -> 0x009879xx` again, the switch
  patch did not survive the build (check `loc_00987914` in
  `gt6/generated/ppu_recomp_022.cpp`).
* If the failure is a wrong `vector<T>` count but the switch is present, collect
  the `[scriptov]` trace around the last read and the `0x9EEA88` type tag; the
  next suspect is a different typed-value reader, not the ADCH container.
* If the reads stop before `0x1BD15`, the override path is not being used for
  the reader (`this` mismatch) or the host file was replaced; check
  `GT6_SCRIPT_TRACE` and the file size/head.

## 7. Address index

| Address | Meaning |
|---|---|
| `0x9CD798` | ADHOC script factory (`.adc` append at `0x9CDBD0..0x9CDBFC`) |
| `0x9CD69C` | fallback `HFileReader` construction/open/parse |
| `0x9CD410` | read 8-byte ADCH header, parse version, call parser load |
| `0x9CC208` | ADCH parser construction (calls `0x9881B4`) |
| `0x9881B4` | parser constructor/step loop (calls `0x9880BC`, `0x987A28`) |
| `0x9880BC` | parser init; clones stream object at parser+0x68 |
| `0x987A2C` | script VM step (guest `0x98759C` range; generated `func_00987A2C`) |
| `0x987884` | value-reader state machine (`func_00987884`) |
| `0x987910` | `bctr` dispatch through table `0x1419550` |
| `0x1419550` | six-entry state table: `0x987914, 0x98792C, 0x987A08, 0x987A08, 0x9878B8, 0x9878B8` |
| `0x987914` | state 0 block (pop one value), local label |
| `0x98792C` | state 1 block (pop until peek != 2), local label |
| `0x987A08` | states 2/3 exit block, local label |
| `0x9878B8` | states 4/5 read-next block, local label |
| `0x9D9604` | `HStreamReader` constructor |
| `0x9D8DB0` | `HStreamReader::read` wrapper |
| `0x994078` | buffered stream read; dispatches `HFileReader` vtable `+0x11C` |
| `0x9BB020` | `HFileReader::read` (overridden) |
| `0x9BAFE0` | `HFileReader::seek` (overridden) |
| `0x9BAF60` | `HFileReader::tell` (returns `+0x1B4`) |
| `0x1484CC8` | `HFileReader` vtable |
| `0x14DCB18` | OPD for vtable `+0x11C` -> `0x9BB020` |
| `0x14DCB10` | OPD for vtable `+0x120` -> `0x9BAFE0` |
| `0x14DCB00` | OPD for vtable `+0x124` -> `0x9BAF60` |
| `0x9EEA88` | typed-value reader; type tag at `0x9EEC14` |
| `0x1487660` | 24-byte type table (tag 0 -> `0x9EC220`) |
| `0x9EC220` | vector reader (count at `[obj+4]`) |
| `0x9C9680` / `0x9C95D4` | vector allocation/constructor |
| `0xDD8CC8` | vector max-size check (`0x3FFFFFFF`) |
| `0x104D298` | `"vector<T> too long"` |
| `0xB84C28` | guest throw helper |
| `0x1095058` | `"ADCH"` |
| `0x1095168` | `".adc"` |
| `0x10950D8` | `"stream is not adhoc script code. HEADER([%s] != [ADCH])"` |

## 8. Artifacts

| Path | Purpose |
|---|---|
| `tools/gt6_adch_switch_patch.py` | idempotent generated-code switch + force-open hook |
| `tools/adch_read_trace.py` | ADCH v12 read-trace/code-frame inspector |
| `tools/apply_gt6_post_lift.py` | relift integration (calls the switch patch; declares the predicate) |
| `tools/post_lift_fixes.py` | relift verifier; fails if the ADCH switch is missing |
| `patches/gt6-adch-switch-dispatch.patch` | generated `ppu_recomp_022.cpp` diff |
| `patches/gt6-adch-reader-hardening.patch` | `gt6/src/stubs.cpp` diff |
| `gt6/src/stubs.cpp` | hardened boot-script override |
| `gt6/generated/ppu_recomp_022.cpp` | currently patched in place |

The two patch files are the before/after diffs; the working tree already
contains both changes, so `git apply` would report "already applied" against
the current files. Use them to review or to reapply after reverting.

## 9. Caveats

* This report did not run `gt6.exe`; the parser trace is a model of the
  GTAdhocToolchain v12 format plus the measured 32-read prefix. The 12,861-call
  figure covers the magic, the 6,412-symbol table and the code-frame header;
  it assumes each VarInt byte is read separately and each string in one call,
  which the measured prefix confirms. It does not decode the full
  5,564-instruction stream.
* The exact `vector<T>` count value was not captured. The type-0/0x9EC220 path
  is inferred from the abort stack (`0x9EEC40 -> 0x9EC24C -> 0x9C96B0`) and the
  `0xDD8CC8` check; the count is not a valid ADCH field.
* The force-open hook is defensive: the measured run opens the empty cache
  successfully. It matters only for a clean run with no `PD.fdupi`.
* The current generated file is patched, but a relift will regenerate it;
  `tools/apply_gt6_post_lift.py` must run after the relift (it already does in
  `scripts/relift-gt6.ps1`).
