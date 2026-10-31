# Jump-table check - GT6 EMAIN `func_009F92CC`

**Date:** 2026-10-31 13:45
**Checker:** independent checker (read-only: no build, no `gt6.exe`, no source edits)
**Target:** `work/bin/EMAIN.elf`, `func_009F92CC` at `0x009F92CC..0x009F95EC`
**Inputs reviewed:**

- `work/bin/EMAIN.elf`
- `third_party/ps3recomp/tools/ppu_lifter.py` (`discover_jump_tables`, `_fold_constant_reg`, `--dump-jump-tables`)
- `third_party/ps3recomp/tools/test_ppu_jumptables.py`
- `third_party/ps3recomp/tools/test_ppu_jumptable_extent.py`
- `work/analysis/emain/functions_corrected_lab.json`
- `work/analysis/emain/functions_corrected.json`
- `work/relift_corrected.log` (pre-fix), `work/relift_lab2.log` (post-fix relift)
- `gt6/generated/ppu_recomp_022.cpp`, `gt6/generated/ppu_recomp_table.cpp` (1:20/1:21 relift output)

This is the only file written by the checker.

---

## 0. Verdict

| # | Item | Verdict |
|---|---|---|
| 1 | Table at `0x009F9348`: 14 offsets and targets | **PASS** |
| 2 | `discover_jump_tables()` absolute-base fix | **PASS** on the GT6 target and tests; **caveat** on blast radius / end-to-end validation |
| 3a | Workaround starts are real table targets and inside the parent | **PASS** |
| 3b | Workaround overlap is safe (no duplicate starts / redefinition) | **PASS** |
| 3c | Does the workaround "avoid the early return without the epilogue"? | **PARTIAL** - the early return remains; the callee's epilogue makes it safe |
| 4 | Per-case disassembly / shared tail / fallthrough | **PASS** |
| 5 | This report | **PASS** |

**Short version:** the table decodes exactly as the owner's ten starts say; the lifter change finds it on the real ELF and its tests pass; the workaround is functionally safe but is now redundant and should be removed in favour of `functions_corrected.json`. No blocking correction to the lifter fix is required for this function.

---

## 1. Table at `0x009F9348`

### 1.1 Address mapping

ELF `PT_LOAD` 0 is `vaddr=0x10000`, `offset=0`, so for this image:

```text
file offset = vaddr - 0x10000
0x009F9348 - 0x10000 = 0x009E9348
```

The executable section containing it is `sh_addr=0x10230`, `sh_offset=0x230`, `sh_size=0xF80694` (ends at `0xF908C4`, the relift's `--code-end`). The same file offset results:

```text
0x230 + (0x9F9348 - 0x10230) = 0x9E9348
```

### 1.2 Raw table

56 bytes, 14 big-endian signed 32-bit words read at file offset `0x9E9348`:

```text
00000038 00000038 00000088 00000088 000000A4 000000E0 000000FC 00000118
00000134 00000134 00000150 00000150 00000188 0000016C
```

`target = 0x009F9348 + signed(offset)`:

| idx | raw offset | target |
|---:|---:|---:|
| 0 | `0x00000038` | `0x009F9380` |
| 1 | `0x00000038` | `0x009F9380` |
| 2 | `0x00000088` | `0x009F93D0` |
| 3 | `0x00000088` | `0x009F93D0` |
| 4 | `0x000000A4` | `0x009F93EC` |
| 5 | `0x000000E0` | `0x009F9428` |
| 6 | `0x000000FC` | `0x009F9444` |
| 7 | `0x00000118` | `0x009F9460` |
| 8 | `0x00000134` | `0x009F947C` |
| 9 | `0x00000134` | `0x009F947C` |
| 10 | `0x00000150` | `0x009F9498` |
| 11 | `0x00000150` | `0x009F9498` |
| 12 | `0x00000188` | `0x009F94D0` |
| 13 | `0x0000016C` | `0x009F94B4` |

There are **14 entries, 10 distinct targets**. The duplicate pairs are `9380`, `93D0`, `947C`, `9498`. Note that indices 12 and 13 are deliberately not in address order: index 12 is `94D0` and index 13 is `94B4`. The owner's list is the **set** of ten, so this ordering does not matter.

Exact distinct set:

```text
0x009F9380 0x009F93D0 0x009F93EC 0x009F9428 0x009F9444
0x009F9460 0x009F947C 0x009F9498 0x009F94B4 0x009F94D0
```

### 1.3 Dispatcher

```text
009F931C  lwz    r0, 0x84(r28)       ; switch value
009F9320  cmplwi cr7, r0, 0xD        ; values 0..13 -> 14 entries
009F9324  bgt    cr7, 0x009F94D0     ; default for > 13; index 12 maps here too
009F9328  lis    r9, 0xA0            ; r9 = 0x00A00000
009F932C  rldic  r11, r0, 2, 30      ; index * 4
009F9330  addi   r9, r9, -0x6CB8     ; r9 = 0x009F9348 (table base)
009F9334  lwzx   r0, r11, r9         ; load signed offset
009F9338  extsw  r0, r0              ; sign-extend offset
009F933C  add    r0, r0, r9          ; case = table_base + offset
009F9340  mtctr  r0
009F9344  bctr
```

Arithmetic: `0xA00000 - 0x6CB8 = 0x9F9348`. The first case is `0x9F9348 + 0x38 = 0x9F9380`, which is exactly 56 bytes (14 entries) after the table start. This is a signed-offset table relative to the absolute table base, not a TOC-relative table and not a table of absolute case addresses.

### 1.4 Result

**PASS.** The table contains exactly the 14 offsets listed above and exactly the ten distinct targets the owner added. All targets are 4-aligned and inside the executable section.

---

## 2. `discover_jump_tables()` absolute-base fix

### 2.1 What was reviewed

- `_fold_constant_reg(win, reg, before_addr, depth)` folds `lis`/`li` + `addi`/`addis`/`ori`/`oris`, stopping at the nearest definition of `reg`; depth cap 8.
- The base-candidate loop now accepts a constant-former definition, stores `abs_base`, and rejects the constant unless it is word-aligned and inside `[text_lo, text_hi)`.
- `_bases` entries carry `(r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base)`; exactly one of `disp` / `abs_base` is set.
- The decode loop uses `table_base = abs_base` directly (no TOC slot read) when `abs_base` is set; all existing validation, `is_offset`, structural-end, cmp-hint, and multi-candidate scoring remain.
- The old gate `if not _bases or not toc: continue` is now `if not _bases: continue`, so an absolute base needs no TOC.
- `--dump-jump-tables` returns before lifting/emission.

The current file was last written at `13:14:59`; the tests at `13:15:54`. The checker did not modify either.

### 2.2 Real-ELF proof for GT6

A read-only in-process call disassembled the real `func_009F92CC` window (`0x9F92CC..0x9F95EC`, 200 instructions) and called `discover_jump_tables` with the real `read_u32` mapping, `text_lo=0x10000`, `text_hi=0x1403068`, and the GT6 TOC `0x14ed560`:

```text
tables: {'0x9f9344': ['0x9f9380', '0x9f93d0', '0x9f93ec', '0x9f9428',
                      '0x9f9444', '0x9f9460', '0x9f947c', '0x9f9498',
                      '0x9f94b4', '0x9f94d0']}
```

This result is identical with:

- `func_starts=[0x9F92CC]` (the fixer's normal corrected list), and
- `func_starts=[0x9F92CC] + the ten lab starts` (the owner's workaround list).

So the workaround starts, which all lie **after** the dispatcher at `0x9F9344`, do not truncate the backward base scan.

`JT_DEBUG=0x9F9344` trace:

```text
[JT_DEBUG 0x9F9344] bctr found
[JT_DEBUG 0x9F9344] rC=r0
[JT_DEBUG 0x9F9344] lwzx=r0, r11, r9
[JT_DEBUG 0x9F9344] bases=[('r9', None, False, None, False, 10457928)] toc=[21943648]
[JT_DEBUG 0x9F9344] r_base=r9 abs=0x9F9348 table_base=0x9f9348 count=13 ...
[JT_DEBUG 0x9F9344]   entry[0] raw=0x38 -> target=0x9F9380 valid=True
...
[JT_DEBUG 0x9F9344]   stop at k=14: cursor 0x9F9380 reached first case 0x9F9380
[JT_DEBUG 0x9F9344] decoded 14 targets
```

`10457928` = `0x9F9348`. The decoder read exactly 14 entries and stopped when the cursor reached the first case, then deduplicated to ten targets.

### 2.3 Required behaviours

| Requirement | Result |
|---|---|
| Signed relative offsets (`extsw`, negative entries) | **PASS.** The dispatcher sign-extends at runtime; discovery reads the 32-bit word and sign-extends with `v & 0x80000000` when `is_offset`. Independent synthetic test with absolute base `0x11000` and entries `-0x100`, `+0x100` returned `['0x10f00', '0x11100']`. GT6's entries are all positive (`0x38..0x1CC`), so `extsw` is a no-op here but the signed path is correct. |
| Indexed load (`lwzx`) | **PASS.** Real dispatcher is `lwzx r0, r11, r9`; the code tries both operands and the `add r0,r0,r9` reordering selects `r9` as the base. Debug confirms `r_base=r9 abs=0x9F9348`. `lwax` and the synthesized `sldi/add/lwz` path are covered by the existing test suite. |
| Duplicate targets | **PASS.** 14 raw entries -> 4 duplicate pairs -> `sorted(set(best))` -> 10 targets. The emitted switch is on `ctx->ctr` (the target address), so duplicate indices mapping to one target are safe; the parent switch has ten `case 0x...` arms. |
| Shared epilogue | **PASS.** Discovery returns case *starts*, not ends. The main lift extends the enclosing function to include the cases (`enclosed_cases` / `fb[fs] = new_end`), and the `bctr` emission uses computed gotos to in-function labels. The real parent is `0x9F92CC..0x9F95EC`, so `0x9F94F0` and the register restore/`blr` at `0x9F95C0` are inside it. `test_ppu_jumptable_extent.py` independently asserts: `switch function emitted`, `bctr is a computed goto to every case`, `every case label is inside the function`, `the shared epilogue past the first blr is inside the function`, `no unresolved indirect call outside the switch default`, `the next function stays its own function`. |
| TOC path unchanged | **PASS by inspection.** When `abs_base is None`, the original `cand + disp` / two-level / multi-TOC code runs. Dropping `not toc` only adds the absolute branch; with no TOC and no absolute base, `base_candidates` is empty. |

### 2.4 Tests run by the checker

```text
python -B third_party\ps3recomp\tools\test_ppu_jumptables.py
...
ok   GT6 0x9F9348 raw table decode
ok   absolute base from lis+addi (GT6 func_009F92CC)
ok   absolute base from lis+ori
ok   nearest definition wins over an earlier constant
ok   absolute base outside .text is rejected
...
all jump-table vectors passed
```

All 22 vectors passed. The checker also ran `test_ppu_jumptable_extent.py`; all six extent/shared-epilogue assertions passed.

### 2.5 False-positive / blast-radius audit

This is the main thing to watch. The change is **not narrow**:

- Pre-fix `work/relift_corrected.log:67`: **47 dispatchers, 517 case targets**.
- Post-fix `work/relift_lab2.log:67` (1:21 relift): **358 dispatchers, 4054 case targets, 4053 kept internal, +1 case funcs**.
- Current `--dump-jump-tables` on the real ELF also reports **358 dispatchers, 4054 targets**, including `0x009F9344: 10 case(s): ...`.
- A direct one-TOC scan with the JSON function starts found **311 absolute-base dispatchers / 3549 targets**. The difference `358 - 311 = 47` is consistent with the pre-existing TOC-relative set, so the bulk of the new tables come from the absolute path (plus boundary-recovery differences in the full pipeline).

The checker audited those 311 absolute-base tables (not a hand-picked sample):

- All 3549 decoded targets are valid decoded instructions (none `.word` / undecodable).
- All targets are in the executable window and 4-aligned.
- Target distances from the dispatcher: median **308 bytes**, p90 **2,904 bytes**, maximum **31,552 bytes**; no target farther than `0x40000`.
- Zero dispatchers lie outside a JSON function.
- 41 dispatchers have cases beyond their JSON function end. Several are exactly the truncated-function cases the pre-fix relift already warned about (`func_00206C74`, `func_0020EEA4`, `func_002810D4`, `func_0029EC18`, `func_002F7630`, `func_0033F38C`, `func_003D8C1C`, ...); the rest are the same class of truncated bounds. The post-fix relift log has **0** `WARNING:` lines, versus **27** pre-fix, because the extension now keeps those cases inside the function. This is evidence the new tables are real switches, not random `.text` bytes.

A second real absolute-base table was spot-checked at `0x4BC14`:

```text
004BC14  bctr
004BC18  table: 0xE4, 0x1C, 0x84, ...
```

`JT_DEBUG=0x4BC14` reports `abs=0x4BC18`, `count=6`, `decoded 7 targets`, with distinct cases `0x4BC34, 0x4BC9C, 0x4BCC8, 0x4BCFC` - all local and valid. The shape is the same as GT6: `lis r9,5; addi r9,r9,-17384` -> `0x4BC18`.

**Conclusion:** no false positive was found in this audit. The new absolute tables look like genuine switch tables. The theoretical residual risk remains: the only new gate is "constant inside `.text` and word-aligned"; a constant that points at code but is not a table could decode a few valid-looking entries. The existing structural-end / hole / local-target ranking makes this unlikely, and a single-entry table is the most plausible edge case. This is not a blocker for GT6, but the 311-table blast radius means the owner must still do a full relift + build + boot comparison.

### 2.6 Caveats / corrections for the fix

1. **No blocker found for GT6.** The real ELF decodes the table exactly; the unit tests and extent test pass.
2. **Broad change:** ~311 new absolute-base switches. Runtime validation is required; do not assume the GT6 table is the only behavioural change.
3. **Optional hardening** (not required): warn/reject an absolute table with only one target, or with every target farther than the existing near-window, to make accidental code-pointer constants less likely to become switches. Do not remove the in-text/alignment guard; do not widen to `.rodata` without a separate review.
4. **Coverage gaps by design:** constants built through a different register (`addi r9,r8,off`) or via a stack spill of the constant are not folded; they fall back to the old (dropped) behaviour. This is safe but can miss future tables.
5. The fixer's own `docs/analysis/jumptable-fix.md` documents the same residual risks; the checker's independent result agrees.

---

## 3. Workaround list in `functions_corrected_lab.json`

### 3.1 Entries

At check time the file has 70,985 entries. The parent and the ten added entries are:

```text
parent (0-based index 42680):
  0x009F92CC..0x009F95EC  toc=0x14ed560  opd=0x14df618

added (0-based indices 70975..70984, all end 0x009F95EC):
  0x009F9380
  0x009F93D0
  0x009F93EC
  0x009F9428
  0x009F9444
  0x009F9460
  0x009F947C
  0x009F9498
  0x009F94B4
  0x009F94D0
```

The added entries have no `toc` / `opd` fields. That is not an issue for code-address dispatch: they are switch targets reached by `bctr`, not OPD entry points. The parent retains the real TOC/OPD.

### 3.2 Completeness

- All ten unique table targets are present: yes.
- Any extra start not in the table: no.
- All starts are strictly inside the parent `0x009F92CC..0x009F95EC`: yes.
- The unsorted append order is harmless: the lifter sorts `func_bounds` / `fb` and emits the table in address order.

**PASS.**

### 3.3 Overlap

All ten ranges are `start..0x009F95EC`, so they overlap the parent and each other. The lifter's `_emit_functions()` deduplicates only **same-start** definitions; all starts here are distinct, so all are emitted. The generated source confirms:

```text
gt6/generated/ppu_recomp_022.cpp:142846  void func_009F9380(...)
gt6/generated/ppu_recomp_022.cpp:143023  void func_009F93D0(...)
gt6/generated/ppu_recomp_022.cpp:143179  void func_009F93EC(...)
gt6/generated/ppu_recomp_022.cpp:143471  void func_009F9428(...)
...
gt6/generated/ppu_recomp_022.cpp:144158  void func_009F94D0(...)
gt6/generated/ppu_recomp_table.cpp:43105-43115  parent + 0x009F9380 ... 0x009F94D0
```

No C redefinition, no duplicate table entry. The overlap is safe for the lifter. It does produce ten dead, full-body functions once the fix is in (the parent switch no longer calls them); that is bloat, not a correctness failure.

**PASS.**

### 3.4 Does adding them avoid the early `return` without the epilogue?

**Literal answer: no. Functional answer: yes, but by compensation, not by removing the early return.**

With the workaround and **without** the jump-table discovery (`jump_tables={}`), the real pipeline's `function_entries` is the prologue-scan set (it does not include the added mid-function starts). The parent lifts to:

```c
if (((ctx->cr >> 2) & 1)) goto loc_009F94D0;   /* >13: internal, not a trampoline */
...
ctx->ctr = ctx->gpr[0];
ps3_indirect_call(ctx); return;                 /* bctr: the early return */
```

The `bctr` is still emitted as `ps3_indirect_call(ctx); return;` - an early return that skips the parent's epilogue. What makes it safe is that every possible CTR target (the ten unique table addresses) now has an emitted function whose body ends at `0x009F95EC`, which includes the shared tail and the register-restore/`blr` at `0x009F95C0`. For `0x9380`, `0x93D0`, `0x93EC` and `0x94D0` this is the same function; for `0x9428..0x94B4` the added function trampolines to the auto-generated `0x9F9404`, which owns the epilogue:

```c
loc_009F95C0:
    ctx->gpr[0] = vm_read64(ctx->gpr[1] + 0xC0);
    ...
    ctx->gpr[1] = ctx->gpr[1] + (int64_t)(0xB0);
    return;
```

Trace of the bctr path:

1. Parent executes `ps3_indirect_call(ctx)` with CTR = case address.
2. Runtime `ppu_lookup` resolves the added function.
3. Added function executes the case and reaches `0x9F95C0` directly (or trampolines to `0x9F9404`, which reaches `0x9F95C0`), restoring `r1` and `r25..r31`, then returns.
4. `ps3_indirect_call` returns to the parent's C frame; the parent executes its host `return`.
5. The caller sees the guest stack/LR restored exactly once.

The parent's host `return` is not a second guest epilogue; it does not touch `ctx->gpr[1]`. The guest epilogue runs in the callee.

So the workaround **does not remove** the early return; it ensures the callee owns the epilogue. The fix removes the bctr early return properly by turning it into an internal computed-goto switch.

**PARTIAL** for the literal question; **PASS** for the functional outcome under the dispatch invariant.

### 3.5 Fallthrough across a start boundary

No case falls through into another **start**. The only fallthroughs are into shared blocks that are not starts:

| Start | End of body | Fallthrough / branch | Is the destination a start? |
|---:|---:|---:|---|
| `0x009F9380` | `b 0x009F94F0` | `94F0` | no |
| `0x009F93D0` | `b 0x009F9404` | `9404` | no |
| `0x009F93EC` | falls through | `9404` | no |
| `0x009F9428` | `b 0x009F9404` | `9404` | no |
| `0x009F9444` | `b 0x009F9404` | `9404` | no |
| `0x009F9460` | `b 0x009F9404` | `9404` | no |
| `0x009F947C` | `b 0x009F9404` | `9404` | no |
| `0x009F9498` | `b 0x009F9404` | `9404` | no |
| `0x009F94B4` | `b 0x009F9404` | `9404` | no |
| `0x009F94D0` | falls through | `94DC` | no |

`0x009F9404` and `0x009F94DC` are **shared blocks**, not function starts. The owner correctly did not add them. If someone did add `0x9404` or `0x94DC` as a start, then `0x93EC` and `0x94D0` would fall across a start boundary and the split would duplicate the shared block/epilogue; do not do that.

**PASS**

### 3.6 Dependency on `0x9F9404`

Cases `0x9428, 0x9444, 0x9460, 0x947C, 0x9498, 0x94B4` branch **backward** to `0x9404`, which is before their start and therefore outside their added range. The workaround list does not include `0x9404`. The lifter's mid-entry pass generates it from the out-of-range branch target. The checker verified:

```text
gt6/generated/ppu_recomp_022.cpp:143328  void func_009F9404(ppu_context* ctx)
gt6/generated/ppu_recomp_table.cpp:73500  { 0x009F9404ULL, func_009F9404, ... }
```

`func_009F9404` runs `0x9404` through the epilogue at `0x95C0`, so those six cases still restore the stack. The mid-entry pass generated ten functions in the checker's simulation, including `0x9F9404`, and a second pass generated zero (no loop). If the mid-entry pass were disabled, those six cases would reference an undefined `func_009F9404`; with the current pipeline it is present.

### 3.7 Correction for the workaround

**Remove the ten added entries once the fix is in use.** The fix discovers the table with the parent-only list (`functions_corrected.json`, parent `0x009F92CC..0x009F95EC`); the ten starts are then redundant and produce ten dead duplicate function definitions. The fixer's `docs/analysis/jumptable-fix.md` §3.4/§5.3 says the same; the checker independently confirms it.

If the workaround must be kept for an A/B run **without** the fix:

- Keep all ten unique targets.
- Ensure the mid-entry pass runs so `0x9F9404` exists.
- Do not add `0x9404`/`0x94DC` as starts (shared blocks, not table targets).
- Treat these as mid-function entries, not ABI-callable functions: each assumes the parent's frame and `r28..r31` are live. Exposing them in the global function table is only safe while the parent's switch is the only dispatcher.

---

## 4. Per-case disassembly (independent)

The full function was disassembled with the repo's `ppu_disasm.py` (`--va 0x9F92CC --length 0x320`). Instruction ranges between the owner's starts:

| Start (table idx) | Key body | Body terminator | Destination | Needs shared block? |
|---:|---|---:|---:|---|
| `0x9F9380` (0,1) | `lwz r11,[r31]; ...; lwz r9,[r11+0x54]; mtctr; bctrl; beq 94DC; bl 921C; bl 7B7C` | `b 0x9F94F0` | `94F0` | no (all in range) |
| `0x9F93D0` (2,3) | `lwz r9,[r11+0x58]` | `b 0x9F9404` | `9404` | yes, in range |
| `0x9F93EC` (4) | `lwz r9,[r11+0x5C]` | none | falls to `9404` | yes, in range |
| `0x9F9428` (5) | `lwz r9,[r11+0x70]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F9444` (6) | `lwz r9,[r11+0x60]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F9460` (7) | `lwz r9,[r11+0x64]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F947C` (8,9) | `lwz r9,[r11+0x68]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F9498` (10,11) | `lwz r9,[r11+0x6C]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F94B4` (13) | `lwz r9,[r11+0x7C]` | `b 0x9F9404` | `9404` | yes, backward |
| `0x9F94D0` (12, and >13 default) | `li r0,2; r30=r31; stw r0,0xB0(r28)` | none | falls to `94DC` | yes, in range |

Shared blocks:

```text
0x9F9404: lwz r0,0(r9); li r27,1; lwz r2,4(r9); mtctr r0; bctrl
          bl 0x9F8678; b 0x9F94F0
0x9F94DC: r3=r30; r4=r29; r25=0; r27=1; bl 0x9F8678
0x9F94F0: r3=r29; bl 0x9F5A78; ... state checks ...; 0x9F95C0
0x9F95C0: restore r25..r31, r1 += 0xB0, blr
```

Clarification: the prompt calls `0x9F94F0` the shared epilogue. In the binary, `0x9F94F0` is the shared **post-switch tail** (calls `0x9F5A78`, `0xA42DE8`, state checks). The actual callee-save restore and `blr` are at `0x9F95C0..0x9F95E8`. The parent and all ten added functions end at `0x9F95EC`, so both are included. Cases that `b 0x9F94F0` still reach the restore at `0x9F95C0` by falling through the tail.

Per-case conclusions:

- **No case falls through across a start boundary.**
- `0x9F93EC` and `0x9F94D0` require fallthrough into shared blocks (`0x9404`, `0x94DC`); both are inside the parent and not starts.
- `0x9428..0x94B4` require the backward branch to `0x9404`; without the fix, the workaround depends on the auto-generated `func_009F9404`.
- `0x9380` has an early `beq 0x94DC` path (bctrl result zero), which is inside its own range and reaches `0x94F0`/`0x95C0`.
- All ten starts are genuine table targets; the table's duplicate indices collapse to these ten.

**PASS.**

---

## 5. Evidence commands (all read-only)

```powershell
# table bytes
@'
import struct
b=open('work/bin/EMAIN.elf','rb').read()
base=0x9F9348; off=base-0x10000
for i,v in enumerate(struct.unpack('>14i', b[off:off+56])):
    print(i, hex(v & 0xFFFFFFFF), hex((base+v) & 0xFFFFFFFF))
'@ | python -B -

# full disassembly
python third_party\ps3recomp\tools\ppu_disasm.py work\bin\EMAIN.elf --va 0x9F92CC --length 0x320

# unit tests
python -B third_party\ps3recomp\tools\test_ppu_jumptables.py
python -B third_party\ps3recomp\tools\test_ppu_jumptable_extent.py

# real-ELF discovery, both function lists
# (in-process call to discover_jump_tables with the real read_u32; result shown in 2.2)

# full-pipeline dump (matches the post-fix relift)
python -B third_party\ps3recomp\tools\ppu_lifter.py work\bin\EMAIN.elf `
  --functions work\analysis\emain\functions_corrected_lab.json --dump-jump-tables
```

Generated-source/table references at check time (1:20/1:21 relift):

```text
gt6/generated/ppu_recomp_022.cpp:142653   parent switch (10 cases)
gt6/generated/ppu_recomp_022.cpp:143328   func_009F9404 (auto mid-entry)
gt6/generated/ppu_recomp_table.cpp:73500  { 0x009F9404, func_009F9404, ... }
gt6/generated/ppu_recomp_table.cpp:43105-43115  parent + ten added entries
work/relift_lab2.log:67                   358 dispatchers, 4054 targets
work/relift_corrected.log:67              47 dispatchers, 517 targets (pre-fix)
# checker count: 0 "WARNING:" lines in relift_lab2.log vs 27 in relift_corrected.log
```

No build and no `gt6.exe` run was performed by the checker. The current `gt6/build/gt6.exe` timestamp is `13:18`, before the `13:21` relift; the post-fix generated source therefore may not be in the last executable.

---

## 6. Corrections / recommended actions

1. **Remove the ten `functions_corrected_lab.json` starts** after the lifter fix is validated. Use `work/analysis/emain/functions_corrected.json` (parent `0x009F92CC..0x009F95EC` already spans the cases). This removes ten dead nested functions and the mid-function ABI hazard.
2. **Do not add `0x9F9404` or `0x9F94DC` as starts.** They are shared blocks; `0x93EC` and `0x94D0` fall into them. With the fix they are internal labels; without the fix, `0x9404` is generated by the mid-entry pass.
3. **Validate the broad fix end-to-end.** The change takes the real ELF from 47 to 358 dispatchers (~311 new absolute-base tables). The target and tests pass and the audit found no false positives, but a full relift + build + boot comparison is still required, especially for the 41 functions whose cases extend past their JSON bounds.
4. **Optional hardening:** warn or reject absolute-base tables with a single target or with all targets outside a small window; keep the in-text/word-alignment guard. Not required for this function.

---

## 7. Final verdict

The table at `0x009F9348` is exactly the 14-entry signed-offset table the owner described, and its ten distinct targets match the ten added starts. The lifter's absolute-base fold correctly resolves `lis r9,0xA0; addi r9,r9,-0x6CB8` to `0x009F9348`, handles the `lwzx`/`extsw`/duplicate/shared-epilogue shape, and returns the exact ten targets on the real ELF. The workaround is functionally safe for this switch, but it does not remove the early return; it relies on the dispatched case function owning the shared epilogue. With the fix in place the workaround is redundant and should be removed. No blocking correction to the table or the lifter fix was found.
