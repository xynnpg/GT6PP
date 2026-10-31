# Jump-table fix — absolute base in `discover_jump_tables()`

**Date:** 2026-10-31
**Status:** implemented; unit tests pass; read-only discovery run on the real
`work/bin/EMAIN.elf` proves the result. **No relift, build, or `gt6.exe` run
was performed by this change** (only a `--dump-jump-tables` pass, which returns
before any source is written).

**Files changed**

| file | change |
|---|---|
| `third_party/ps3recomp/tools/ppu_lifter.py` | `_fold_constant_reg()`; absolute base added to `_bases`; decode loop takes the constant base directly; `--dump-jump-tables` diagnostic |
| `third_party/ps3recomp/tools/test_ppu_jumptables.py` | four new vectors, including the exact GT6 dispatcher and table |
| `docs/analysis/jumptable-fix.md` | this report |

`docs/analysis/spin-triage.md` §1 and §4.1 are the source analysis this
implements. It is the durable fix for the owner's `functions_corrected_lab.json`
workaround: the ten case starts that file adds explicitly are exactly the ten
distinct targets the lifter now decodes.

---

## 1. Root cause

`func_009F92CC` dispatches with a table of **signed offsets relative to a
link-time constant base**:

```text
009F9320: cmplwi cr7, r0, 0xD
009F9328: lis    r9, 0xA0
009F932C: rldic  r11, r0, 2, 0x1E
009F9330: addi   r9, r9, -0x6CB8     ; r9 = 0x009F9348 (table base)
009F9334: lwzx   r0, r11, r9
009F9338: extsw  r0, r0
009F933C: add    r0, r0, r9          ; case = base + offset
009F9340: mtctr  r0
009F9344: bctr
```

`discover_jump_tables()` only resolved the table base through the TOC
(`lwz/ld ...,disp(r2)`). `r9`'s nearest definition is `addi`, so no `_bases`
entry was produced, `tables[0x9F9344]` stayed empty, and the `bctr` was emitted
as:

```c
ctx->ctr = ctx->gpr[0];
ps3_indirect_call(ctx); return;
/* TODO: .word 0x00000038 */;   // the 14 table words decoded as data
```

`ps3_indirect_call()` only knows function **entries**. `0x9F9380` is a
mid-function case start, so the call returned without running the case body.
The FileDevice request/completion state machine therefore never advanced
(`gt6/generated/ppu_recomp_022.cpp:140523` in the current tree).

---

## 2. Implementation

### 2.1 Constant resolver

`_fold_constant_reg(win, reg, before_addr)` walks backward to the **nearest
definition** of `reg` (same rule as the TOC paths, so a later load cannot be
masked by an earlier constant) and folds:

- `lis rX,imm`
- `li rX,imm`
- `addi rX,rX,imm`, `addis rX,rX,imm`
- `ori rX,rX,imm`, `oris rX,rX,imm`

`addi`/`addis` immediates are used with their signed value and the result is
masked to 32 bits; `ori`/`oris` use the unsigned low 16 bits and OR. The chain
is bounded at 8 steps and bottoms out only at `li`/`lis`.

### 2.2 Wiring into `discover_jump_tables()`

- `_bases` entries became
  `(r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base)`; exactly one of
  `disp` / `abs_base` is set.
- When the nearest definition of the candidate operand is a constant former,
  `abs_base` is accepted only if it is word-aligned and inside
  `[text_lo, text_hi)`.
- `if not _bases or not toc: continue` became `if not _bases: continue`; an
  absolute base needs no TOC.
- In the decode loop, an absolute base bypasses `_read_ptr()` and is used as
  `table_base` directly. All existing checks are unchanged: `lwzx` shape,
  optional `add rC,*,base` offset detection, cmp-derived size hint, per-entry
  in-text/4-aligned validation, structural end-of-table, multi-candidate
  scoring.
- TOC-relative behavior is untouched: when `abs_base is None` the original
  `cand + disp` / two-level path runs exactly as before.

### 2.3 Diagnostic

`--dump-jump-tables` prints every discovered dispatcher and its case targets,
then returns **before** function lifting/emission. It writes nothing and can be
used to verify the real ELF without touching `generated/`. `JT_DEBUG=<bctr
address>` still prints the per-candidate base/decode trace.

### 2.4 Full diff

```diff
diff --git a/tools/ppu_lifter.py b/tools/ppu_lifter.py
index a657ba6..580adfd 100644
--- a/tools/ppu_lifter.py
+++ b/tools/ppu_lifter.py
@@ -4405,6 +4405,51 @@ def _const_base_targets(win, rC, read_u32, text_lo, text_hi, bctr_addr):
     return None
 
 
+def _fold_constant_reg(win, reg, before_addr, depth=0):
+    """Fold `lis`/`li` + `addi`/`addis`/`ori`/`oris` into the constant in `reg`.
+
+    Scans `win` backward from `before_addr` (exclusive) and stops at the
+    NEAREST instruction that defines `reg`, so a later redefinition cannot
+    mask the value that reaches the use. Returns the 32-bit constant, or None
+    when that nearest definition is not a constant former or the chain does
+    not bottom out in `li`/`lis` (bounded at 8 steps).
+
+    This is how a link-time build materializes an absolute table address:
+    `lis r9,0xA0; addi r9,r9,-0x6CB8` -> 0x009F9348 (GT6 func_009F92CC).
+    The TOC-relative paths do not need it; they start from a load.
+    """
+    if depth > 8:
+        return None
+    for w in reversed([x for x in win if x.addr < before_addr]):
+        a = [x.strip() for x in w.operands.split(',')]
+        # A store READS its first operand; ppu_disasm also names lfs/lfd's FPR
+        # target rN. Neither defines a GPR, so neither ends the search.
+        if not a or a[0] != reg or w.mnemonic.startswith(('st', 'lf')):
+            continue
+        m = w.mnemonic
+        try:
+            if m == 'lis' and len(a) == 2:
+                return (int(a[1], 0) & 0xFFFF) << 16
+            if m == 'li' and len(a) == 2:
+                return int(a[1], 0) & 0xFFFFFFFF
+            if m == 'addi' and len(a) == 3 and a[1] == reg:
+                base = _fold_constant_reg(win, reg, w.addr, depth + 1)
+                return None if base is None else (base + int(a[2], 0)) & 0xFFFFFFFF
+            if m == 'addis' and len(a) == 3 and a[1] == reg:
+                base = _fold_constant_reg(win, reg, w.addr, depth + 1)
+                return None if base is None else (base + (int(a[2], 0) << 16)) & 0xFFFFFFFF
+            if m in ('ori', 'oris') and len(a) == 3 and a[1] == reg:
+                base = _fold_constant_reg(win, reg, w.addr, depth + 1)
+                if base is None:
+                    return None
+                v = int(a[2], 0) & 0xFFFF
+                return (base | (v << 16)) if m == 'oris' else (base | v)
+        except ValueError:
+            return None
+        return None                     # nearest def is not a constant former
+    return None
+
+
 def discover_jump_tables(all_insns, read_u32, toc, text_lo, text_hi, func_starts=None):
     """Find `mtctr rX; bctr` switch dispatchers and read their jump tables.
 
@@ -4601,7 +4646,12 @@ def discover_jump_tables(all_insns, read_u32, toc, text_lo, text_hi, func_starts
         # `add` preference still decides whenever the scores cannot, and a
         # dispatcher only changes when the old pick validated strictly fewer
         # targets.
-        _bases = []         # [(r_base, disp, base_is_ld, disp2, disp2_is_ld)]
+        _bases = []         # [(r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base)]
+                            # abs_base is a link-time constant base (GT6
+                            # func_009F92CC: `lis r9,0xA0; addi r9,r9,-0x6CB8`
+                            # -> 0x009F9348). It needs no TOC indirection; see
+                            # _fold_constant_reg. Exactly one of disp/abs_base
+                            # is set for a resolved entry.
         # Prefer the lwzx operand that the `add ..., base` feeding mtctr combines
         # with the loaded offset. Both operands are often TOC-loaded, so "first
         # candidate with a TOC-load definition" can pick an unrelated index reg
@@ -4632,6 +4682,7 @@ def discover_jump_tables(all_insns, read_u32, toc, text_lo, text_hi, func_starts
         for cand in _cands:
             disp = None; r_base = None; base_is_ld = False
             disp2 = None; disp2_is_ld = False
+            abs_base = None
             # Walk backward to the NEAREST instruction that defines `cand`, and
             # accept it as the table base only if that definition is a TOC load
             # (`lwz`/`ld cand, disp(r2)`). Stopping at the first definition is
@@ -4730,16 +4781,35 @@ def discover_jump_tables(all_insns, read_u32, toc, text_lo, text_hi, func_starts
                         if _resolved or _pass:
                             break
                         _scan = _live(_scan_lo(i), i)
+                elif w.mnemonic in ('lis', 'li', 'addi', 'addis', 'ori', 'oris'):
+                    # ABSOLUTE base: the table address is a link-time constant,
+                    # not a TOC slot. GT6 func_009F92CC (`lis r9,0xA0; addi
+                    # r9,r9,-0x6CB8` -> 0x009F9348) was dropped here: the
+                    # TOC-only resolver left _bases empty, the bctr lifted to
+                    # `ps3_indirect_call(ctx); return;`, and 0x9F9380 (a
+                    # mid-function case start, absent from the function table)
+                    # never ran -- the FileDevice request/completion pump spun.
+                    # Only accept a constant that lands INSIDE the code window
+                    # and is word-aligned: every real switch table this pass
+                    # can lift is in .text (gcc puts it immediately before the
+                    # cases), so a constant pointing at .data/.rodata is far
+                    # more likely to be an unrelated pointer table than a
+                    # jump table. It also keeps a stray `lis/addi` pair from
+                    # being read as a table from unmapped/ELF-header bytes.
+                    v = _fold_constant_reg(win_cand, cand, lwzx.addr)
+                    if v is not None and text_lo <= v < text_hi and (v & 3) == 0:
+                        r_base = cand
+                        abs_base = v
                 break                           # first definition of cand wins/loses
-            if disp is not None:
-                _bases.append((r_base, disp, base_is_ld, disp2, disp2_is_ld))
+            if disp is not None or abs_base is not None:
+                _bases.append((r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base))
         _dbg(all_insns[i].addr, f"bases={_bases} toc={toc}")
-        if not _bases or not toc:
+        if not _bases:
             continue
         toc_candidates = toc if isinstance(toc, (list, tuple)) else [toc]
         best = []
         best_key = (0, 0)
-        for r_base, disp, base_is_ld, disp2, disp2_is_ld in _bases:
+        for r_base, disp, base_is_ld, disp2, disp2_is_ld, abs_base in _bases:
             # offset table iff an `add rC, *, r_base` combines the loaded value + base
             is_offset = any(
                 w.mnemonic == 'add' and
@@ -4821,22 +4891,32 @@ def discover_jump_tables(all_insns, read_u32, toc, text_lo, text_hi, func_starts
             # with. We don't track per-function TOCs here, so try each candidate
             # and keep the one whose table decodes to the most in-text case
             # targets (a wrong TOC reads unrelated data and validates 0 targets).
-            for cand in toc_candidates:
-                if not cand:
-                    continue
-                def _read_ptr(_ea, _is_ld):
-                    # ELFv1 TOC entries are 64-bit; a table address always fits the
-                    # low word, so a non-zero high word means we read the wrong slot.
-                    _ea &= 0xFFFFFFFF
-                    if not _is_ld:
-                        return read_u32(_ea)
-                    if read_u32(_ea):
-                        return None
-                    return read_u32((_ea + 4) & 0xFFFFFFFF)
-                table_base = _read_ptr(cand + disp, base_is_ld)
-                if table_base is not None and disp2 is not None:
-                    table_base = _read_ptr(table_base + disp2, disp2_is_ld)
-                _dbg(all_insns[i].addr, f"r_base={r_base} cand_toc=0x{cand:X} table_base={None if table_base is None else hex(table_base)} count={count} is_offset={is_offset} text=[0x{text_lo:X},0x{text_hi:X})")
+            def _read_ptr(_ea, _is_ld):
+                # ELFv1 TOC entries are 64-bit; a table address always fits the
+                # low word, so a non-zero high word means we read the wrong slot.
+                _ea &= 0xFFFFFFFF
+                if not _is_ld:
+                    return read_u32(_ea)
+                if read_u32(_ea):
+                    return None
+                return read_u32((_ea + 4) & 0xFFFFFFFF)
+            # An ABSOLUTE base is already the table address (the constant
+            # built by lis/addi); there is no TOC slot to read. Otherwise
+            # resolve through each TOC candidate as before.
+            if abs_base is not None:
+                base_candidates = [abs_base]
+            else:
+                base_candidates = [c for c in toc_candidates if c]
+            for cand in base_candidates:
+                if abs_base is not None:
+                    table_base = abs_base
+                else:
+                    table_base = _read_ptr(cand + disp, base_is_ld)
+                    if table_base is not None and disp2 is not None:
+                        table_base = _read_ptr(table_base + disp2, disp2_is_ld)
+                _where = (f"abs=0x{abs_base:X}" if abs_base is not None
+                          else f"cand_toc=0x{cand:X}")
+                _dbg(all_insns[i].addr, f"r_base={r_base} {_where} table_base={None if table_base is None else hex(table_base)} count={count} is_offset={is_offset} text=[0x{text_lo:X},0x{text_hi:X})")
                 if table_base is None:
                     continue
                 targets = []
@@ -5064,6 +5144,13 @@ def main() -> None:
                              "is emitted as `if (guard) {new} else {orig}`, guard "
                              "being an int the port defines. The input must hold "
                              "`orig` at `addr` or the lift stops.")
+    parser.add_argument("--dump-jump-tables", action="store_true",
+                        help="Print every discovered computed-bctr dispatcher and "
+                             "its case targets, then stop before lifting. Useful "
+                             "to verify an absolute-base table (e.g. GT6 "
+                             "func_009F92CC -> 0x009F9348) without rewriting "
+                             "generated sources. Combine with JT_DEBUG=<addr> for "
+                             "the per-candidate base/decode trace.")
     args = parser.parse_args()
 
     # Load firmware-import stubs (addr -> NID) up front; applied to func_bounds
@@ -5423,6 +5510,15 @@ def main() -> None:
         except Exception as exc:
             print(f"  jump-table discovery skipped: {exc}", file=sys.stderr)
 
+    if args.dump_jump_tables:
+        for _disp in sorted(jt_dispatchers):
+            _cases = jt_dispatchers[_disp]
+            print(f"  0x{_disp:08X}: {len(_cases)} case(s): " +
+                  " ".join(f"0x{t:08X}" for t in _cases))
+        print(f"  {len(jt_dispatchers)} dispatcher(s), "
+              f"{len(jt_targets)} case target(s)")
+        return
+
     # ----- fall-through gap repair -----------------------------------------
     # IDA exports sometimes TRUNCATE a function: its declared end lands mid-body
     # on a non-terminator (LBP: malloc wrapper 0x5E7808 exported as ending at
diff --git a/tools/test_ppu_jumptables.py b/tools/test_ppu_jumptables.py
index 64ed245..07f0ec8 100644
--- a/tools/test_ppu_jumptables.py
+++ b/tools/test_ppu_jumptables.py
@@ -61,14 +61,20 @@ def w_mtctr(rs):
     return (31 << 26) | (rs << 21) | (spr << 11) | (467 << 1)
 
 
-def decode_all(words):
-    return [ppu_disasm.decode(w, TEXT_LO + 4 * i) for i, w in enumerate(words)]
+def w_ori(ra, rs, ui):     return (24 << 26) | (rs << 21) | (ra << 16) | (ui & 0xFFFF)
+def w_addi(rt, ra, si):    return (14 << 26) | (rt << 21) | (ra << 16) | (si & 0xFFFF)
+def w_lis(rt, si):         return (15 << 26) | (rt << 21) | (0 << 16) | (si & 0xFFFF)
+def w_extsw(ra, rs):       return (31 << 26) | (rs << 21) | (ra << 16) | (986 << 1)
 
 
-def discover(words, mem):
-    insns = decode_all(words)
+def decode_all(words, base=TEXT_LO):
+    return [ppu_disasm.decode(w, base + 4 * i) for i, w in enumerate(words)]
+
+
+def discover(words, mem, toc=TOC, text_lo=TEXT_LO, text_hi=TEXT_HI, base=TEXT_LO):
+    insns = decode_all(words, base)
     tables = discover_jump_tables(insns, lambda a: mem.get(a & 0xFFFFFFFF),
-                                  [TOC], TEXT_LO, TEXT_HI)
+                                  [toc], text_lo, text_hi)
     return tables.get(insns[-1].addr)                # the bctr is always last
 
 
@@ -324,9 +330,6 @@ def test_multi_toc_prefers_targets_near_the_dispatcher():
           tables.get(insns[-1].addr), [0x11100, 0x11200])
 
 
-def w_ori(ra, rs, ui):     return (24 << 26) | (rs << 21) | (ra << 16) | (ui & 0xFFFF)
-
-
 def test_bound_compare_beyond_window():
     """The bounds compare sits more than 30 instructions before the bctr.
 
@@ -356,6 +359,97 @@ def test_bound_compare_beyond_window():
           [first + 4 * k for k in range(n)])
 
 
+def test_absolute_base_from_lis_addi():
+    """GT6 func_009F92CC: a link-time constant table base, no TOC slot.
+
+        009F9320: cmplwi cr7, r0, 0xD
+        009F9328: lis    r9, 0xA0
+        009F932C: rldic  r11, r0, 2, 0x1E
+        009F9330: addi   r9, r9, -0x6CB8    <- r9 = 0x009F9348
+        009F9334: lwzx   r0, r11, r9
+        009F9338: extsw  r0, r0
+        009F933C: add    r0, r0, r9
+        009F9340: mtctr  r0 ; bctr
+
+    The base never passes through r2, so the TOC-relative resolver left
+    `_bases` empty and the bctr lifted to `ps3_indirect_call(ctx); return;`.
+    0x9F9380 is a mid-function case start, not in the function table, so the
+    call did nothing and the FileDevice state machine never advanced.
+
+    Table at 0x009F9348 (offsets from the base), as decoded from the ELF:
+    14 slots, 10 distinct case addresses. The owner's temporary workaround
+    adds exactly those 10 as explicit function starts; the run must produce
+    the same set.
+    """
+    gt6_base = 0x9F9348
+    gt6_offsets = [0x38, 0x38, 0x88, 0x88, 0xA4, 0xE0, 0xFC, 0x118,
+                   0x134, 0x134, 0x150, 0x150, 0x188, 0x16C]
+    raw_targets = [(gt6_base + o) & 0xFFFFFFFF for o in gt6_offsets]
+    # The fixture is the real table: 14 slots, duplicates included.
+    check("GT6 0x9F9348 raw table decode", raw_targets,
+          [0x9F9380, 0x9F9380, 0x9F93D0, 0x9F93D0, 0x9F93EC, 0x9F9428,
+           0x9F9444, 0x9F9460, 0x9F947C, 0x9F947C, 0x9F9498, 0x9F9498,
+           0x9F94D0, 0x9F94B4])
+    mem = {gt6_base + 4 * k: v for k, v in enumerate(gt6_offsets)}
+    got = discover([w_cmplwi(7, 0, 0xD), w_lis(9, 0xA0), w_slwi(11, 0, 2),
+                    w_addi(9, 9, -0x6CB8), w_lwzx(0, 11, 9), w_extsw(0, 0),
+                    w_add(0, 0, 9), w_mtctr(0), w_bctr()],
+                   mem, text_lo=0x9F0000, text_hi=0x9FA000, base=0x9F92CC)
+    check("absolute base from lis+addi (GT6 func_009F92CC)", got,
+          [0x9F9380, 0x9F93D0, 0x9F93EC, 0x9F9428, 0x9F9444,
+           0x9F9460, 0x9F947C, 0x9F9498, 0x9F94B4, 0x9F94D0])
+
+
+def test_absolute_base_from_lis_ori():
+    """Same shape with `lis`+`ori` (the other constant former gcc emits).
+
+        cmplwi cr0, r3, 2 ; lis r11,1 ; ori r11,r11,0x1000  -> 0x11000
+        slwi r9,r3,2 ; lwzx r0,r9,r11 ; add r0,r0,r11 ; mtctr r0 ; bctr
+    """
+    table = 0x11000
+    mem = {table + 0: 0x100, table + 4: 0x200, table + 8: 0xFFFFFFFF}
+    got = discover([w_cmplwi(0, 3, 2), w_lis(11, 1), w_ori(11, 11, 0x1000),
+                    w_slwi(9, 3, 2), w_lwzx(0, 9, 11), w_add(0, 0, 11),
+                    w_mtctr(0), w_bctr()], mem)
+    check("absolute base from lis+ori", got, [0x11100, 0x11200])
+
+
+def test_absolute_base_nearest_def_wins():
+    """A later load of the same register must hide the earlier constant.
+
+        lis r9,0xA0 ; addi r9,r9,-0x6CB8 ; lwz r9,16(r2)   <- real base
+        slwi r10,r3,2 ; lwzx r0,r10,r9 ; add r0,r0,r9 ; mtctr r0 ; bctr
+
+    Taking the constant would read 0x9F9348, which is not a table in this
+    fixture, and drop a dispatcher the TOC path already handled.
+    """
+    table = 0x11000
+    mem = {TOC + 16: table, 0x9F9348: 0x38, 0x9F934C: 0x38,
+           table + 0: 0x100, table + 4: 0x200, table + 8: 0xFFFFFFFF}
+    got = discover([w_cmplwi(0, 3, 2), w_lis(9, 0xA0), w_addi(9, 9, -0x6CB8),
+                    w_lwz(9, 2, 16), w_slwi(10, 3, 2), w_lwzx(0, 10, 9),
+                    w_add(0, 0, 9), w_mtctr(0), w_bctr()], mem)
+    check("nearest definition wins over an earlier constant", got,
+          [0x11100, 0x11200])
+
+
+def test_absolute_base_outside_text_rejected():
+    """A constant base below .text is data, not a switch table.
+
+        lis r9,8 ; addi r9,r9,0  -> 0x8000 (below TEXT_LO)
+        entries would decode to 0x13000/0x14000, inside .text.
+
+    Accepting it would manufacture a switch out of unrelated data; the
+    in-text guard on the base prevents that.
+    """
+    base = 0x8000
+    mem = {base + 0: 0xB000, base + 4: 0xC000, base + 8: 0xFFFFFFFF}
+    got = discover([w_cmplwi(0, 3, 2), w_lis(9, 8), w_addi(9, 9, 0),
+                    w_slwi(10, 3, 2), w_lwzx(0, 10, 9), w_add(0, 0, 9),
+                    w_mtctr(0), w_bctr()], mem)
+    check("absolute base outside .text is rejected", got, None)
+
+
 def main() -> int:
     test_encodings()
     test_absolute_base_is_second_operand()
@@ -368,6 +462,10 @@ def main() -> int:
     test_base_before_fallthrough_split()
     test_const_base_no_table()
     test_const_base_needs_constant()
+    test_absolute_base_from_lis_addi()
+    test_absolute_base_from_lis_ori()
+    test_absolute_base_nearest_def_wins()
+    test_absolute_base_outside_text_rejected()
     test_multi_toc_prefers_targets_near_the_dispatcher()
     test_bound_compare_beyond_window()
     test_spilled_base_reused_as_target()
```

---

## 3. Evidence

### 3.1 Real ELF, read-only discovery

`--dump-jump-tables` on `work/bin/EMAIN.elf` (same function list, code end, and
HLE stub map as `scripts/relift-gt6.ps1`) exited 0 and printed:

```text
  jump tables: 358 dispatchers, 4054 case targets, 4053 kept internal, +1 case funcs
  0x009F9344: 10 case(s): 0x009F9380 0x009F93D0 0x009F93EC 0x009F9428
                          0x009F9444 0x009F9460 0x009F947C 0x009F9498
                          0x009F94B4 0x009F94D0
```

The dispatcher key is the `bctr` address (`0x009F9344`); its host function is
`func_009F92CC` (`0x009F92CC..0x009F95EC`). The 10 distinct targets are exactly
the cases listed in `docs/analysis/spin-triage.md` §1.1.

### 3.2 Raw table bytes

Read from the ELF at `0x009F9348` (file offset `0x9E9348`), 14 32-bit words:

```text
0x38 0x38 0x88 0x88 0xA4 0xE0 0xFC 0x118 0x134 0x134 0x150 0x150 0x188 0x16C
```

`base + signed(offset)`:

```text
0x9F9380 0x9F9380   0x9F93D0 0x9F93D0   0x9F93EC   0x9F9428
0x9F9444 0x9F9460   0x9F947C 0x9F947C   0x9F9498   0x9F9498
0x9F94D0 0x9F94B4
```

The unit test pins this exact sequence (`GT6 0x9F9348 raw table decode`) and the
deduplicated set the lifter returns (`absolute base from lis+addi`).

### 3.3 Unit tests

```text
python third_party\ps3recomp\tools\test_ppu_jumptables.py
...
ok   GT6 0x9F9348 raw table decode
ok   absolute base from lis+addi (GT6 func_009F92CC)
ok   absolute base from lis+ori
ok   nearest definition wins over an earlier constant
ok   absolute base outside .text is rejected
all jump-table vectors passed
```

`test_ppu_jumptable_extent.py` also still passes (switch emission, internal
case labels, shared epilogue). `py_compile` passes on both changed files.

### 3.4 Agreement with the owner's workaround

`work/analysis/emain/functions_corrected_lab.json` contains, in this region:

```text
0x009F92CC-0x009F95EC   (parent)
0x009F9380-0x009F95EC   0x009F93D0-0x009F95EC   0x009F93EC-0x009F95EC
0x009F9428-0x009F95EC   0x009F9444-0x009F95EC   0x009F9460-0x009F95EC
0x009F947C-0x009F95EC   0x009F9498-0x009F95EC   0x009F94B4-0x009F95EC
0x009F94D0-0x009F95EC
```

Those ten starts are exactly the ten targets the lifter now finds. After the
relift, use `work/analysis/emain/functions_corrected.json` (parent
`0x009F92CC-0x009F95EC` already spans the cases); the lab entries are then
redundant and add ten dead nested definitions to the output. The fix does not
depend on the lab file.

---

## 4. False-positive and regression risks

**Guards added for the absolute path**

1. **Base must be word-aligned and inside `[text_lo, text_hi)`.** A `lis/addi`
   pair is used constantly for `.data`/`.rodata` pointers; treating one as a
   jump table would read unrelated bytes. Requiring the constant to land in the
   code window rejects those. The real table (`0x9F9348`), like every gcc switch
   table this pass already handles, sits in `.text` immediately before its
   cases.
2. **Nearest definition wins.** The constant is only accepted when the nearest
   definition of the `lwzx` operand is a constant former. A later
   `lwz rX,d(r2)` (or any other definition) ends the scan without an absolute
   base, so the existing TOC path decides. Pinned by
   `test_absolute_base_nearest_def_wins`.
3. **All existing decode checks still apply.** Each entry must resolve to a
   4-aligned in-text target; the scan stops at the first hole after real
   entries (leading holes allowed up to 4); the structural stop ends the table
   when the cursor reaches the first forward case; the cmp-derived size is only
   a hint and the per-entry validation determines the real end. This is what
   keeps a garbled constant from producing thousands of bogus cases.
4. **TOC path unchanged.** `abs_base is None` runs the original `cand + disp` /
   two-level / multi-TOC code. The only gate change is dropping the `not toc`
   requirement, which can only add the absolute branch; when `toc` is empty and
   no absolute base exists, `base_candidates` is empty and nothing is emitted.
5. **Performance:** `_fold_constant_reg` runs only when the nearest definition
   is one of six mnemonics, walks backward at most to that definition, and is
   depth-capped at 8. No extra pass over instructions.

**Residual risks**

- A **table of 32-bit function pointers** in `.text` addressed by a constant and
  loaded with `lwzx; mtctr; bctr` will also match. That is semantically a
  switch and emitting it is safe (targets are validated). If the pointers are
  relocated at runtime, the static values may be wrong; `JT_DEBUG=<bctr>` shows
  every decoded entry.
- **Offset tables in `.rodata`** addressed absolutely are intentionally missed.
  If a future title has one, widen the base guard to "inside any loaded
  readable segment", not just `.text`; do not remove the alignment check.
- **Constants built through a different register** (`addi r9,r8,off`) or through
  a stack spill of the constant are not folded. They fall back to the old
  behavior (dispatcher dropped) rather than mis-lifting.
- **Raw mode without `--toc`** still skips jump-table discovery entirely
  (pre-existing gate `if args.raw and args.toc`). For a raw PRX with absolute
  tables, pass a real or dummy `--toc` until that gate is relaxed.
- This fixes **case dispatch only**. The space-filled request at
  `0x016810E0` / `[req+8]=0x20202028` (spin-triage §2) is independent; if the
  join still blocks after the relift, follow §4.2/§6.3 of the triage.

---

## 5. Exact next commands

All commands from the repo root
`C:\Users\xynnp\Documents\Projects\GT6PP`.

### 5.1 Self-check (safe, no lift)

```powershell
python third_party\ps3recomp\tools\test_ppu_jumptables.py
python third_party\ps3recomp\tools\test_ppu_jumptable_extent.py
```

### 5.2 Dump-only check on the real ELF (no generated writes)

```powershell
python third_party\ps3recomp\tools\ppu_lifter.py work\bin\EMAIN.elf `
  --functions work\analysis\emain\functions_corrected.json `
  --hle-stubs work\analysis\emain\hle_stubs.json `
  --code-end 0xF908C4 --dump-jump-tables
```

Expect a line containing:

```text
0x009F9344: 10 case(s): 0x009F9380 0x009F93D0 0x009F93EC 0x009F9428 0x009F9444 0x009F9460 0x009F947C 0x009F9498 0x009F94B4 0x009F94D0
```

This returns before lifting; `generated/` is not touched. Add
`$env:JT_DEBUG="0x9F9344"` for the per-candidate trace.

### 5.3 Relift and build (owner)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\relift-gt6.ps1 -Jobs 8 -Chunks 40
powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
```

Use the default `functions_corrected.json`. Do not pass
`functions_corrected_lab.json`: its ten extra case starts are now redundant
(and produce dead nested functions). If the lab list is already the default
somewhere, switch back after this relift.

### 5.4 Verify the emitted function

```powershell
Select-String -Path gt6\generated\ppu_recomp_022.cpp `
  -Pattern 'void func_009F92CC' -Context 0,120 |
  Select-String -Pattern 'case 0x009F9380u|case 0x009F94D0u|\.word 0x00000038'
```

Expected: ten `case 0x009F93xxu: goto loc_009F93xx;` arms inside
`switch ((uint32_t)ctx->ctr)`, and no `.word 0x00000038` remainder in that
function. A broader check:

```powershell
Select-String -Path gt6\generated\ppu_recomp_0*.cpp -Pattern 'case 0x009F9380u: goto loc_009F9380'
```

### 5.5 Runtime check

```powershell
gt6\build\gt6.exe work\bin\EMAIN.elf *> work\relift_jt.log
Select-String -Path work\relift_jt.log -Pattern 'unresolved indirect call -> 0x009F9380|ppu_thread_join\(tid=14\)|LWM-BLOCK'
```

Pass criteria for this fix: no `unresolved indirect call -> 0x009F9380`.
If `ppu_thread_join(tid=14)` or the `lwm=0x20202028` block remains, that is the
independent poisoned-request bug — proceed to `docs/analysis/spin-triage.md`
§4.2/§6.3 (write-watch `0x7005C064` / `0x016810E0`).

---

## 6. Rollback

Revert only the two tool files:

```powershell
git -C third_party\ps3recomp checkout -- tools/ppu_lifter.py tools/test_ppu_jumptables.py
```

No generated source, runtime, or library file was modified by this change.
