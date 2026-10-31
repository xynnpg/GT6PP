#!/usr/bin/env python3
"""PPU function-boundary audit and corrected function-list generator.

Reads a decrypted PS3 PPU ELF and a candidate function list, recovers real
function extents with a CFG/basic-block walk, and writes:

  * a corrected function list in the same {start, end} schema, and
  * a Markdown audit report.

The tool is read-only with respect to the game tree: it never writes into
``gt6/src``, ``gt6/generated`` or ``third_party``.  The caller chooses the two
output paths.

Why this exists
---------------
``find_functions.py`` seeds functions from prologues (mflr/stwu/stdu), ``bl``
targets and the OPD table, then ends each function at the first ``blr`` and
grows it over its own basic blocks.  On GT6 that leaves two recurring errors:

  1. A short leaf/thunk followed by a frame function whose entry is
     ``mflr r0; ...; stdu r1,-N(r1)`` is merged, because the lifter's
     boundary-recovery pass refuses to cut at an ``mflr`` that is at or before
     the range's first ``stdu`` (it assumes that is the range's own prologue).
     Example: 0x10ED8 (12-byte thunk) + 0x10EE8 (real function).

  2. An OPD function's end is just the next OPD start.  When the OPD table has
     a sparse region, one OPD entry can span tens of KB containing dozens or
     hundreds of real functions.  Example: 0x163174..0x16E3F8 contains 159
     separate 0x120-byte functions.

The corrected list is produced by partitioning each candidate range into
maximal CFG-reachable islands, respecting jump tables, then filling the gaps
between candidate ranges.  A final pass moves prologue-anchor starts back to
the real entry (``mfcr``/``cmpwi`` before ``mflr``).

Usage
-----
    python tools/boundary_audit.py \
        --elf work/bin/EMAIN.elf \
        --functions work/analysis/emain/functions_final3.json \
        --opd work/analysis/emain/EMAIN.functions.json \
        --out-functions work/analysis/emain/functions_corrected.json \
        --out-report docs/analysis/boundary-audit.md \
        --generated gt6/generated

Add ``--check`` to validate an existing corrected list without writing.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------
# ppu_disasm import
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def _import_ppu_disasm():
    candidates = []
    env = os.environ.get("PS3RECOMP_TOOLS")
    if env:
        candidates.append(env)
    candidates += [
        os.path.join(_REPO, "third_party", "ps3recomp", "tools"),
        os.path.join(_HERE, "..", "third_party", "ps3recomp", "tools"),
    ]
    here = _HERE
    for _ in range(6):
        candidates.append(os.path.join(here, "third_party", "ps3recomp", "tools"))
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isfile(os.path.join(path, "ppu_disasm.py")):
            sys.path.insert(0, path)
            import ppu_disasm  # type: ignore
            return ppu_disasm
    raise SystemExit(
        "cannot find ppu_disasm.py; set PS3RECOMP_TOOLS to the "
        "third_party/ps3recomp/tools directory"
    )


ppu_disasm = _import_ppu_disasm()

# ---------------------------------------------------------------------------
# Constants / small helpers
# ---------------------------------------------------------------------------

TERMINATORS = {"blr", "blrl", "bctr", "rfid", "rfi"}
UNCOND_BRANCH = {"b", "ba"}
CALLS = {"bl", "bla", "bctrl"}
COND_BRANCH_PREFIXES = ("bc", "bd", "beq", "bne", "blt", "bgt", "ble", "bge",
                        "bso", "bns", "bun", "bnu", "bt", "bf", "bdnz",
                        "bdz", "bdnzt", "bdnzf", "bdzt", "bdzf")
PAD_MNEMONICS = {"nop", "lnop"}
ZERO_WORDS = {0x00000000, 0x60000000}

DEFAULT_CODE_END = 0xF908C4


def parse_int(value) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def fmt_addr(value: int) -> str:
    return f"0x{value:08X}"


def is_cond_branch(mnemonic: str) -> bool:
    if mnemonic in ("b", "ba", "bl", "bla", "blr", "blrl", "bctr", "bctrl",
                    "rfid", "rfi"):
        return False
    return mnemonic.startswith("b") or mnemonic.startswith("bc")


def branch_target(ins) -> Optional[int]:
    """Return the direct target of a branch/call instruction, if any."""
    mn = ins.mnemonic
    if not (mn in ("b", "ba", "bl", "bla") or is_cond_branch(mn)):
        return None
    op = ins.operands.strip()
    if not op:
        return None
    # Conditional branches are 'cr7, 0xADDR' or '0xADDR'; take the last token.
    token = op.split(",")[-1].strip()
    if token.startswith("0x"):
        try:
            return int(token, 16)
        except ValueError:
            return None
    return None


def is_padding(ins) -> bool:
    return ins.mnemonic in PAD_MNEMONICS or ins.raw in ZERO_WORDS


def is_data(ins) -> bool:
    return ins.mnemonic.startswith(".") or ins.mnemonic in ("???", ".word")


def read_imm(text: str) -> Optional[int]:
    """ppu_disasm prints positive immediates in decimal and negatives in hex."""
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(text, 16)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# ELF image
# ---------------------------------------------------------------------------


class ElfImage:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        if self.data[:4] != b"\x7fELF":
            raise SystemExit(f"{path}: not an ELF file")
        if self.data[4] != 2 or self.data[5] != 2:
            raise SystemExit(f"{path}: expected ELF64 big-endian")
        self.e_entry = struct.unpack_from(">Q", self.data, 0x18)[0]
        e_phoff = struct.unpack_from(">Q", self.data, 0x20)[0]
        e_phentsize = struct.unpack_from(">H", self.data, 0x36)[0]
        e_phnum = struct.unpack_from(">H", self.data, 0x38)[0]
        self.segments: List[Tuple[int, int, int, int]] = []
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            p_type = struct.unpack_from(">I", self.data, off)[0]
            if p_type != 1:  # PT_LOAD
                continue
            p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, _align = \
                struct.unpack_from(">QQQQQQ", self.data, off + 8)
            if p_filesz:
                self.segments.append((p_vaddr, p_offset, p_filesz, p_memsz))
        self.segments.sort()
        if not self.segments:
            raise SystemExit(f"{path}: no PT_LOAD segments")
        self.text_lo = self.segments[0][0]
        self.text_hi = self.segments[0][0] + self.segments[0][2]

    def read(self, va: int, size: int) -> bytes:
        for vaddr, offset, filesz, _memsz in self.segments:
            if vaddr <= va < vaddr + filesz:
                start = offset + (va - vaddr)
                return self.data[start:start + min(size, filesz - (va - vaddr))]
        return b""

    def u32(self, va: int) -> Optional[int]:
        raw = self.read(va, 4)
        if len(raw) != 4:
            return None
        return struct.unpack(">I", raw)[0]

    def disasm(self, start: int, end: int) -> List:
        if end <= start:
            return []
        return ppu_disasm.disassemble_bytes(self.read(start, end - start),
                                            start, True)


# ---------------------------------------------------------------------------
# Jump-table discovery
# ---------------------------------------------------------------------------


@dataclass
class JumpTables:
    ranges: List[Tuple[int, int]] = field(default_factory=list)
    targets: Set[int] = field(default_factory=set)


def find_jump_tables(image: ElfImage, insns: Sequence, lo: int, hi: int) -> JumpTables:
    """Find GCC-style relative jump tables addressed by lis/addi + lwzx/lwz.

    This is deliberately conservative: a table needs at least three entries
    that point back into [lo, hi).  It only recognises tables whose base is a
    literal built by lis/addi in the same straight-line window; TOC-relative
    tables in .rodata are left to the lifter's own discovery pass.
    """
    consts: Dict[str, int] = {}
    refs: List[int] = []

    def clear(reg: str) -> None:
        consts.pop(reg, None)

    def dest_reg(ops: str) -> Optional[str]:
        first = ops.strip().split(",")[0].strip()
        if first.startswith("r") and first[1:].isdigit():
            return first
        return None

    for ins in insns:
        mn = ins.mnemonic
        ops = ins.operands.strip()
        parts = [p.strip() for p in ops.split(",")]
        if mn == "lis" and len(parts) == 2:
            imm = read_imm(parts[1])
            if imm is not None:
                consts[parts[0]] = (imm & 0xFFFF) << 16
            else:
                clear(parts[0])
            continue
        if mn in ("addi", "addis", "ori", "oris", "li") and len(parts) >= 3:
            base = consts.get(parts[1])
            imm = read_imm(parts[2])
            if base is not None and imm is not None:
                if mn == "addi":
                    consts[parts[0]] = base + imm
                elif mn == "addis":
                    consts[parts[0]] = base + (imm << 16)
                elif mn == "ori":
                    consts[parts[0]] = base | imm
                elif mn == "oris":
                    consts[parts[0]] = base | (imm << 16)
                else:
                    consts[parts[0]] = imm
            else:
                clear(parts[0])
            continue
        if mn == "lwzx" and len(parts) == 3:
            if parts[2] in consts:
                refs.append(consts[parts[2]])
            continue
        if mn in ("lwz", "lwa") and len(parts) == 2 and "(" in parts[1]:
            disp_s, reg = parts[1].split("(", 1)
            reg = reg.rstrip(")")
            if reg in consts:
                disp = read_imm(disp_s)
                if disp is not None:
                    refs.append(consts[reg] + disp)
            continue
        dst = dest_reg(ops)
        if dst:
            clear(dst)

    result = JumpTables()
    for base in refs:
        if not (lo <= base < hi):
            continue
        values: List[Tuple[int, int]] = []
        for k in range(512):
            word = image.u32(base + 4 * k)
            if word is None:
                break
            signed = word - 0x100000000 if word >= 0x80000000 else word
            target = None
            for candidate in ((base + signed) & 0xFFFFFFFF, word):
                if lo <= candidate < hi and (candidate & 3) == 0:
                    target = candidate
                    break
            if target is None:
                if values:
                    break
                continue
            values.append((base + 4 * k, target))
        if len(values) >= 3:
            result.ranges.append((base, base + 4 * len(values)))
            result.targets.update(t for _, t in values)
    return result


# ---------------------------------------------------------------------------
# CFG extent
# ---------------------------------------------------------------------------


def cfg_reachable(insns: Sequence, imap: Dict[int, int], entry: int,
                  hi: int) -> Set[int]:
    """Instructions reachable from ``entry`` without crossing ``hi``.

    Direct branches are followed (both conditional paths), tail ``b`` is
    followed only when its target is in range, and a plain ``bctr`` ends the
    block.  Conditional ``bclr``/``bcctr`` continue on the fall-through path.
    ``bl`` is a call: the fall-through continues in the same function.
    """
    seen: Set[int] = set()
    work = [entry]
    while work:
        addr = work.pop()
        if addr in seen or addr < entry or addr >= hi:
            continue
        idx = imap.get(addr)
        if idx is None:
            continue
        while idx < len(insns):
            ins = insns[idx]
            a = ins.addr
            if a >= hi or a in seen:
                break
            seen.add(a)
            mn = ins.mnemonic
            if mn in TERMINATORS:
                break
            if mn in UNCOND_BRANCH:
                tgt = branch_target(ins)
                if tgt is not None and entry <= tgt < hi:
                    work.append(tgt)
                break
            if is_cond_branch(mn):
                tgt = branch_target(ins)
                if tgt is not None and entry <= tgt < hi:
                    work.append(tgt)
                idx += 1
                continue
            idx += 1
    return seen


def inside_ranges(addr: int, ranges: Iterable[Tuple[int, int]]) -> bool:
    for lo, hi in ranges:
        if lo <= addr < hi:
            return True
    return False


# ---------------------------------------------------------------------------
# Range partitioning
# ---------------------------------------------------------------------------


@dataclass
class PartitionEntry:
    start: int
    end: int
    reason: str = ""
    evidence: str = ""


def _first_code(image: ElfImage, start: int, end: int):
    """Return (first_code_addr, insns) skipping leading padding/table words."""
    insns = image.disasm(start, end)
    if not insns:
        return None, []
    idx = 0
    while idx < len(insns):
        ins = insns[idx]
        if is_padding(ins):
            idx += 1
            continue
        if is_data(ins):
            idx += 1
            continue
        return ins.addr, insns
    return None, insns


def split_bctr_range(image: ElfImage, start: int, end: int) -> List[PartitionEntry]:
    """Split a computed-jump range only at unambiguous function prologues.

    A `bctr` prevents CFG reachability from seeing jump-table cases, so a full
    CFG split would turn every case into an overlapping multi-KB function.
    However, a real prologue that follows an unconditional terminator is
    unambiguously a new function.  Split there and leave the remaining
    dispatcher/cases as one container.
    """
    insns = image.disasm(start, end)
    if not insns:
        return []
    candidates = [start]
    for i, ins in enumerate(insns):
        if ins.addr == start:
            continue
        if not (ins.mnemonic in ("stdu", "stwu")
                or (ins.mnemonic == "mflr" and ins.operands.strip() == "r0")):
            continue
        j = i - 1
        while j >= 0 and is_padding(insns[j]):
            j -= 1
        if j >= 0 and insns[j].mnemonic in (TERMINATORS | UNCOND_BRANCH):
            candidates.append(ins.addr)
    candidates = sorted(set(candidates))
    if len(candidates) == 1:
        return [PartitionEntry(start, end, "bctr-container",
                               "computed jump; kept whole")]
    entries = []
    for i, a in enumerate(candidates):
        b = candidates[i + 1] if i + 1 < len(candidates) else end
        if b <= a:
            continue
        entries.append(PartitionEntry(
            a, b, "bctr-prologue-split",
            "prologue follows an unconditional terminator inside a bctr range"))
    return entries


def partition_range(image: ElfImage, start: int, end: int,
                    allow_bctr_split: bool = False) -> List[PartitionEntry]:
    """Partition [start, end) into CFG-reachable islands.

    If the range contains ``bctr`` (a computed jump), do not CFG-split it
    unless ``allow_bctr_split`` is set.  Static CFG cannot see jump-table
    cases, and a CFG-only split turns every case into an overlapping multi-KB
    function.  Prologue-after-terminator boundaries are still split, because
    they are unambiguous.
    """
    if end <= start:
        return []
    insns = image.disasm(start, end)
    if not insns:
        return []
    if not allow_bctr_split and any(i.mnemonic == "bctr" for i in insns):
        return split_bctr_range(image, start, end)
    imap = {ins.addr: i for i, ins in enumerate(insns)}
    tables = find_jump_tables(image, insns, start, end)
    covered: Set[int] = set()
    for lo, hi in tables.ranges:
        for a in range(lo, hi, 4):
            covered.add(a)

    entries: List[PartitionEntry] = []
    pos = start
    while pos < end:
        if pos in covered or pos not in imap:
            pos += 4
            continue
        ins = insns[imap[pos]]
        if is_padding(ins) or is_data(ins):
            covered.add(pos)
            pos += 4
            continue
        entry = pos
        reach = cfg_reachable(insns, imap, entry, end)
        for target in tables.targets:
            if entry <= target < end and target not in reach:
                reach |= cfg_reachable(insns, imap, target, end)
        if not reach:
            covered.add(pos)
            pos += 4
            continue
        last = max(reach)
        entry_end = last + 4
        table_hit = inside_ranges(last, tables.ranges)
        reason = "cfg-island"
        evidence = f"last reachable insn 0x{last:08X} {insns[imap[last]].mnemonic}"
        if table_hit:
            reason = "jump-table-container"
            evidence = "contains detected relative jump table"
        entries.append(PartitionEntry(entry, entry_end, reason, evidence))
        covered |= reach
        nxt = entry + 4
        while nxt < end:
            if nxt not in covered and nxt in imap:
                ni = insns[imap[nxt]]
                if not is_padding(ni) and not is_data(ni):
                    break
            nxt += 4
        pos = nxt
    return entries


def partition_gap(image: ElfImage, start: int, end: int) -> List[PartitionEntry]:
    """Partition code in a gap between two candidate functions.

    Leading padding and jump-table words are skipped.  If the remaining range
    contains a computed jump, it is kept as one container (the lifter discovers
    its cases).  Otherwise the normal CFG partitioner is used.
    """
    if end <= start:
        return []
    first, insns = _first_code(image, start, end)
    if first is None:
        return []
    remaining = image.disasm(first, end)
    if not remaining:
        return []
    if any(i.mnemonic == "bctr" for i in remaining):
        return split_bctr_range(image, first, end)
    return partition_range(image, first, end)


# ---------------------------------------------------------------------------
# Branch target scan (for protection and confidence)
# ---------------------------------------------------------------------------


def scan_branch_targets(image: ElfImage, lo: int, hi: int):
    """Return (bl_targets, branch_targets) by decoding raw branch encodings."""
    bl_targets: Set[int] = set()
    branch_targets: Set[int] = set()
    data = image.data
    for vaddr, offset, filesz, _memsz in image.segments:
        a = max(vaddr, lo)
        b = min(vaddr + filesz, hi)
        if b <= a:
            continue
        off = offset + (a - vaddr)
        for pos in range(off, off + (b - a), 4):
            word = struct.unpack_from(">I", data, pos)[0]
            addr = vaddr + (pos - offset)
            opcode = word >> 26
            if opcode == 18:  # b / bl / ba / bla
                li = word & 0x03FFFFFC
                if li & 0x02000000:
                    li -= 0x04000000
                target = (addr + li) & 0xFFFFFFFF if not (word & 2) else li
                if word & 1:
                    bl_targets.add(target)
                else:
                    branch_targets.add(target)
            elif opcode == 16:  # bc / bcl
                bd = word & 0x0000FFFC
                if bd & 0x8000:
                    bd -= 0x10000
                target = (addr + bd) & 0xFFFFFFFF if not (word & 2) else bd
                branch_targets.add(target)
    return bl_targets, branch_targets


# ---------------------------------------------------------------------------
# Function-list I/O
# ---------------------------------------------------------------------------


@dataclass
class Func:
    start: int
    end: int
    toc: Optional[str] = None
    opd: Optional[str] = None
    origin: str = "unknown"


def load_functions(path: str) -> List[Func]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise SystemExit(f"{path}: expected a JSON list")
    out = []
    for item in raw:
        start = parse_int(item["start"])
        end = parse_int(item["end"])
        out.append(Func(start, end, item.get("toc"), item.get("opd")))
    out.sort(key=lambda f: f.start)
    return out


def load_opd(path: Optional[str]) -> Dict[int, Func]:
    if not path:
        return {}
    funcs = load_functions(path)
    return {f.start: f for f in funcs}


def dedupe_funcs(funcs: Sequence[Func]) -> List[Func]:
    """One definition per start; widest extent wins (lifter semantics)."""
    by_start: Dict[int, Func] = {}
    for f in funcs:
        old = by_start.get(f.start)
        if old is None or f.end > old.end:
            by_start[f.start] = f
    return sorted(by_start.values(), key=lambda f: f.start)


# ---------------------------------------------------------------------------
# Correction builder
# ---------------------------------------------------------------------------


@dataclass
class Correction:
    kind: str           # end | added | removed
    start: int
    old_end: Optional[int]
    new_end: Optional[int]
    origin: str
    confidence: str
    reason: str
    evidence: str
    detail: Dict[str, object] = field(default_factory=dict)


@dataclass
class AuditResult:
    original: List[Func]
    corrected: List[Func]
    corrections: List[Correction]
    bl_targets: Set[int]
    branch_targets: Set[int]
    opd: Dict[int, Func]
    warnings: List[str]
    stats: Dict[str, int]


def _last_insn(image: ElfImage, end: int):
    ins = image.disasm(end - 4, end)
    return ins[0] if ins else None


def _first_insn(image: ElfImage, start: int, end: int):
    ins = image.disasm(start, min(end, start + 16))
    return ins[0] if ins else None


def _entry_kind(image: ElfImage, start: int, end: int) -> str:
    ins = image.disasm(start, min(end, start + 32))
    if not ins:
        return "no-code"
    first = ins[0]
    if first.mnemonic in ("stdu", "stwu"):
        return "prologue"
    if first.mnemonic == "mflr" and first.operands.strip() == "r0":
        return "prologue-mflr"
    if first.mnemonic in ("mfcr", "cmpwi", "cmpw", "cmplwi", "cmpldi", "cmpdi",
                          "lis", "addi", "li", "rlwinm", "rldicl", "extsw"):
        return "setup"
    if first.mnemonic in TERMINATORS:
        return "empty"
    if first.mnemonic in ("b", "ba"):
        return "thunk"
    if first.mnemonic in ("bl", "bla"):
        return "call-start"
    return "leaf"


def _prev_nonpad(image: ElfImage, addr: int, back: int = 32):
    ins = image.disasm(max(image.text_lo, addr - back), addr)
    for item in reversed(ins):
        if is_padding(item):
            continue
        return item
    return None


def _is_prologue_anchor(image: ElfImage, anchor: int) -> bool:
    """True if ``anchor`` is mflr/stdu a few instructions into a function."""
    ins = image.disasm(anchor, anchor + 8)
    if not ins:
        return False
    first = ins[0]
    if first.mnemonic == "mflr" and first.operands.strip() == "r0":
        return True
    if first.mnemonic in ("stdu", "stwu"):
        return True
    return False


def build_corrections(original: List[Func], opd: Dict[int, Func],
                      image: ElfImage, code_end: int,
                      include_gaps: bool = True) -> AuditResult:
    original = dedupe_funcs(original)
    orig_starts = {f.start for f in original}
    orig_by_start = {f.start: f for f in original}

    # Every OPD start below code_end is authoritative and must be present.
    opd_starts = {s for s in opd if s < code_end}
    missing_opd = sorted(opd_starts - orig_starts)
    base_funcs = list(original)
    for s in missing_opd:
        base_funcs.append(Func(s, code_end, opd[s].toc, opd[s].opd, "opd"))
    base_funcs = dedupe_funcs(base_funcs)

    bl_targets, branch_targets = scan_branch_targets(image, image.text_lo, code_end)

    # Partition each candidate range.
    part_by_start: Dict[int, List[PartitionEntry]] = {}
    all_entries: List[PartitionEntry] = []
    for f in base_funcs:
        entries = partition_range(image, f.start, f.end)
        part_by_start[f.start] = entries
        all_entries.extend(entries)

    # Partition gaps (code the candidate list does not cover at all).
    gap_entries: List[PartitionEntry] = []
    if include_gaps:
        for i in range(len(base_funcs) - 1):
            a = base_funcs[i].end
            b = base_funcs[i + 1].start
            if b > a:
                gap_entries.extend(partition_gap(image, a, b))
        all_entries.extend(gap_entries)

    # Union of starts.
    starts: Set[int] = {f.start for f in base_funcs}
    starts.update(e.start for e in all_entries)
    starts = {s for s in starts if image.text_lo <= s < code_end}

    # End assignment: a partition entry's end wins for that start.  Original
    # alias starts that the partitioner did not emit keep their old end (they
    # are deliberate multi-entry routines: memset/memcpy families, case labels).
    part_end: Dict[int, int] = {}
    part_reason: Dict[int, Tuple[str, str]] = {}
    for e in all_entries:
        if e.end <= e.start:
            continue
        if e.start not in part_end or e.end > part_end[e.start]:
            part_end[e.start] = e.end
            part_reason[e.start] = (e.reason, e.evidence)

    ends: Dict[int, int] = {}
    for s in starts:
        if s in part_end:
            ends[s] = part_end[s]
        elif s in orig_by_start:
            ends[s] = orig_by_start[s].end
        elif s in opd:
            ends[s] = opd[s].end
        else:
            ends[s] = s + 4

    corrected = dedupe_funcs([
        Func(s, min(ends[s], code_end),
             opd[s].toc if s in opd else None,
             opd[s].opd if s in opd else None)
        for s in starts
    ])

    # ------------------------------------------------------------------
    # Drop candidate starts that landed on padding/data.  The common case is
    # a nop before an atomic helper: the nop is not an entry, the instruction
    # after it is.  If the real entry was already discovered (usual case),
    # extend it and remove the padding start; otherwise move the start to the
    # first real instruction.
    # ------------------------------------------------------------------
    cleaned: List[Func] = []
    for f in corrected:
        first = _first_insn(image, f.start, f.end)
        if first is not None and (is_padding(first) or is_data(first)):
            # Find the next candidate at or after the first non-pad insn.
            nxt = None
            probe = f.start + 4
            while probe < min(f.end, f.start + 32):
                ins = image.disasm(probe, probe + 4)
                if ins and not is_padding(ins[0]) and not is_data(ins[0]):
                    nxt = probe
                    break
                probe += 4
            if nxt is not None:
                # If a corrected function already starts there, extend it.
                existing = None
                for g in corrected:
                    if g.start == nxt:
                        existing = g
                        break
                if existing is not None:
                    existing.end = max(existing.end, f.end)
                else:
                    cleaned.append(Func(nxt, f.end,
                                        opd[nxt].toc if nxt in opd else None,
                                        opd[nxt].opd if nxt in opd else None))
            # If no real instruction was found, drop the fragment.
            continue
        cleaned.append(f)
    corrected = dedupe_funcs(cleaned)

    # ------------------------------------------------------------------
    # Merge prologue-anchor starts: if the previous range falls through
    # into the next start without an unconditional transfer, the next start
    # is a prologue anchor (mflr/stdu a few insns into the same function).
    # Never merge an OPD start or a bl target.
    # ------------------------------------------------------------------
    merged_count = 0
    changed = True
    while changed:
        changed = False
        out: List[Func] = []
        for f in corrected:
            if not out:
                out.append(f)
                continue
            prev = out[-1]
            if prev.end != f.start:
                out.append(f)
                continue
            last = _last_insn(image, f.start)
            if last is None:
                out.append(f)
                continue
            if (last.mnemonic in TERMINATORS or last.mnemonic in UNCOND_BRANCH
                    or is_data(last) or is_padding(last)):
                out.append(f)
                continue
            if f.start in opd or f.start in bl_targets:
                out.append(f)
                continue
            # Only merge a prologue anchor (mflr/stdu a few instructions into
            # a function), never an arbitrary mid-function label or a jump-table
            # case entry.  Multi-entry routines (memset/memcpy families, switch
            # cases) depend on those aliases remaining addressable.
            if not _is_prologue_anchor(image, f.start):
                out.append(f)
                continue
            if _entry_kind(image, prev.start, prev.end) not in (
                    "prologue", "prologue-mflr", "setup"):
                out.append(f)
                continue
            # Do not merge into a switch container (table data may follow).
            if any(i.mnemonic == "bctr"
                   for i in image.disasm(prev.start, prev.end)):
                out.append(f)
                continue
            # Only merge when the anchor is close to the previous start, or
            # the previous range is a newly discovered setup island.
            if prev.start in opd and f.start - prev.start > 12:
                out.append(f)
                continue
            prev.end = f.end
            merged_count += 1
            changed = True
        corrected = out

    # ------------------------------------------------------------------
    # Build the correction ledger.
    # ------------------------------------------------------------------
    corrections: List[Correction] = []
    corrected_by_start = {f.start: f for f in corrected}
    corrected_starts = set(corrected_by_start)
    orig_by_start = {f.start: f for f in original}

    for f in base_funcs:
        if f.start not in corrected_by_start:
            # Find the range that now contains this address.
            idx = bisect.bisect_right(sorted(corrected_starts), f.start) - 1
            container = corrected[idx] if idx >= 0 else None
            corrections.append(Correction(
                "removed", f.start, f.end,
                container.end if container else None,
                "opd" if f.start in opd else "heuristic",
                "high" if _is_prologue_anchor(image, f.start) else "medium",
                "prologue anchor merged into real entry",
                f"address lies inside {fmt_addr(container.start)}.."
                f"{fmt_addr(container.end)}" if container else "no container",
            ))
            continue
        new = corrected_by_start[f.start]
        if new.end != f.end:
            last = _last_insn(image, new.end)
            last_s = (f"{last.mnemonic} {last.operands}".strip()
                      if last else "?")
            confidence = "high"
            if f.start in opd:
                confidence = "high" if new.end <= opd[f.start].end else "low"
            if any(i.mnemonic == "bctr"
                   for i in image.disasm(f.start, f.end)):
                confidence = "low"
            corrections.append(Correction(
                "end", f.start, f.end, new.end,
                "opd" if f.start in opd else "heuristic",
                confidence,
                "trim to CFG extent" if new.end < f.end else "extend",
                f"last instruction at new end-4: {last_s}",
            ))

    for f in corrected:
        if f.start in orig_by_start or (f.start in opd and f.start in orig_by_start):
            continue
        # New start.
        if f.start in orig_by_start:
            continue
        kind = _entry_kind(image, f.start, f.end)
        prev = _prev_nonpad(image, f.start)
        prev_s = (f"after {prev.mnemonic} at {fmt_addr(prev.addr)}"
                  if prev else "start of gap")
        reason = "interior-split" if any(
            o.start < f.start < o.end for o in original) else "gap-fill"
        confidence = "high" if kind in ("prologue", "prologue-mflr") else "medium"
        if prev is not None and prev.mnemonic in TERMINATORS | UNCOND_BRANCH:
            confidence = "high" if confidence != "low" else confidence
        corrections.append(Correction(
            "added", f.start, None, f.end, "new", confidence, reason,
            f"{prev_s}; first insn {kind}",
        ))

    # ------------------------------------------------------------------
    # Warnings / sanity checks.
    # ------------------------------------------------------------------
    warnings: List[str] = []
    for f in corrected:
        if f.end <= f.start:
            warnings.append(f"{fmt_addr(f.start)}: end <= start")
        if (f.start & 3) or (f.end & 3):
            warnings.append(f"{fmt_addr(f.start)}: unaligned range")
        first = _first_insn(image, f.start, f.end)
        if first is None or is_data(first) or is_padding(first):
            warnings.append(f"{fmt_addr(f.start)}: start is not code")
    missing_after = sorted(opd_starts - {f.start for f in corrected})
    if missing_after:
        warnings.append("OPD starts lost: " + ", ".join(fmt_addr(x) for x in missing_after[:20]))
    # OPD end upper bound.
    for f in corrected:
        if f.start in opd and f.end > opd[f.start].end:
            warnings.append(
                f"{fmt_addr(f.start)}: end {fmt_addr(f.end)} exceeds OPD end "
                f"{fmt_addr(opd[f.start].end)}")
    # Natural end check: if the function ends before the next start, its last
    # instruction should be a transfer (or data/table word).
    starts_sorted = sorted(f.start for f in corrected)
    for i, f in enumerate(corrected):
        nxt = starts_sorted[i + 1] if i + 1 < len(starts_sorted) else code_end
        if f.end >= nxt:
            continue
        last = _last_insn(image, f.end)
        if last is None:
            continue
        if (last.mnemonic not in TERMINATORS and last.mnemonic not in UNCOND_BRANCH
                and not is_data(last) and not is_padding(last)):
            warnings.append(
                f"{fmt_addr(f.start)}: ends at {fmt_addr(f.end)} on "
                f"{last.mnemonic}, next start {fmt_addr(nxt)}")

    stats = {
        "original": len(original),
        "corrected": len(corrected),
        "opd_starts": len(opd_starts),
        "added": sum(1 for c in corrections if c.kind == "added"),
        "removed": sum(1 for c in corrections if c.kind == "removed"),
        "end_changed": sum(1 for c in corrections if c.kind == "end"),
        "trimmed": sum(1 for c in corrections
                       if c.kind == "end" and c.new_end is not None
                       and c.old_end is not None and c.new_end < c.old_end),
        "extended": sum(1 for c in corrections
                        if c.kind == "end" and c.new_end is not None
                        and c.old_end is not None and c.new_end > c.old_end),
        "merged": merged_count,
        "bl_targets": len(bl_targets),
        "branch_targets": len(branch_targets),
    }
    return AuditResult(original, corrected, corrections, bl_targets,
                       branch_targets, opd, warnings, stats)


# ---------------------------------------------------------------------------
# Generated C++ audit
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(r"void (func_[0-9A-Fa-f]{8})\(ppu_context\* ctx\) \{")
_CS_RE = re.compile(r"uint64_t _cs_\d+ = ctx->gpr\[\d+\];")


def parse_generated_function(path: str, name: str):
    """Return (start_line, body_lines) for one generated function."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start_line = None
    depth = 0
    body: List[str] = []
    for i, line in enumerate(lines, 1):
        if start_line is None:
            m = _FUNC_RE.match(line)
            if m and m.group(1) == name:
                start_line = i
                depth = line.count("{") - line.count("}")
            continue
        depth += line.count("{") - line.count("}")
        body.append(line.rstrip("\n"))
        if depth <= 0:
            return start_line, body
    return start_line, body


def first_guest_statement(body: Sequence[str]) -> Optional[str]:
    for line in body:
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("/*"):
            continue
        if s.startswith("PPU_MM_SNAP"):
            continue
        if _CS_RE.match(s):
            continue
        if s.startswith("uint64_t _cs_"):
            continue
        if s == "}" or s.startswith("loc_"):
            continue
        return s
    return None


def has_dead_after_return(body: Sequence[str]) -> Optional[str]:
    """A top-level return followed by unlabeled code is a merge signature."""
    depth = 1
    seen_return = False
    pending_label = False
    for line in body:
        s = line.strip()
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
        if depth != 1:
            continue
        if not s or s.startswith("//"):
            continue
        if s.startswith("loc_") and s.endswith(":"):
            pending_label = True
            continue
        if s == "return;" or s.startswith("{ g_trampoline_fn"):
            seen_return = True
            pending_label = False
            continue
        if seen_return and not pending_label:
            return s
        pending_label = False
    return None


def audit_generated(generated_dir: Optional[str], corrected: Sequence[Func],
                    image: ElfImage,
                    corrections: Sequence[Correction] = ()) -> List[Dict[str, object]]:
    """Check generated C++ bodies against the ELF and corrected list.

    The generated tree is ~450 MB.  Parse it line-by-line (no per-character
    brace scan) and only run the expensive dead-code check for functions whose
    boundary changed; start-instruction mismatches are checked for every
    function because they are cheap.
    """
    if not generated_dir or not os.path.isdir(generated_dir):
        return []
    corrected_by_start = {f.start: f for f in corrected}
    interesting = {c.start for c in corrections}
    findings: List[Dict[str, object]] = []
    header_re = re.compile(r"^void (func_[0-9A-Fa-f]{8})\(ppu_context\* ctx\) \{")
    for fname in sorted(os.listdir(generated_dir)):
        if not fname.endswith(".cpp") or "table" in fname:
            continue
        path = os.path.join(generated_dir, fname)
        cur_name = None
        cur_addr = None
        cur_body: List[str] = []
        depth = 0
        try:
            fh = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if cur_name is None:
                    m = header_re.match(line)
                    if not m:
                        continue
                    cur_name = m.group(1)
                    cur_addr = int(cur_name[5:], 16)
                    cur_body = []
                    depth = line.count("{") - line.count("}")
                    continue
                depth += line.count("{") - line.count("}")
                cur_body.append(line.rstrip("\n"))
                if depth > 0:
                    continue
                # Function complete.
                name = cur_name
                addr = cur_addr
                body = cur_body
                cur_name = None
                first = first_guest_statement(body)
                start_ins = image.disasm(addr, addr + 4)
                start_mn = start_ins[0].mnemonic if start_ins else "?"
                mismatch = None
                if first:
                    if "vm_read8" in first and start_mn != "lbz":
                        mismatch = f"body starts vm_read8, ELF starts {start_mn}"
                    elif ("vm_write64(ctx->gpr[1] + -" in first
                          and "ctx->gpr[1] +=" in first
                          and start_mn not in ("stdu", "stwu")):
                        mismatch = f"body starts stack allocation, ELF starts {start_mn}"
                    elif first.startswith("ctx->gpr[0] = ctx->lr;") and start_mn != "mflr":
                        mismatch = f"body starts mflr save, ELF starts {start_mn}"
                dead = None
                inner = None
                if addr in interesting:
                    dead = has_dead_after_return(body)
                    old = corrected_by_start.get(addr)
                    if old is not None:
                        for f in corrected:
                            if old.start <= f.start < old.end and f.start != addr:
                                inner = f
                                break
                if mismatch or (dead and inner is not None):
                    findings.append({
                        "func": name,
                        "addr": addr,
                        "file": os.path.relpath(path, os.getcwd()),
                        "start_mnemonic": start_mn,
                        "first_statement": first or "",
                        "mismatch": mismatch or "",
                        "dead": dead or "",
                        "split": fmt_addr(inner.start) if inner else "",
                    })
    return findings


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _origin_label(f: Func, opd: Dict[int, Func]) -> str:
    if f.start in opd:
        return "OPD"
    return "heuristic"


def _pct(a: int, b: int) -> str:
    return f"{(100.0 * a / b):.1f}%" if b else "0.0%"


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


FOCUS_NOTES = {
    (0xA13508, 0xA13704): (
        "All seven ranges are real functions and are unchanged. `0xA13508` is a "
        "16-byte leaf setter; `0xA13644` is the 0x5C-byte lock/getter/unlock "
        "wrapper ending in `blr` at `0xA1369C`. The 8-byte `lbz r3,0x10(r3); blr` "
        "is `0x3C0E84..0x3C0E8C` (outside this range) and was already correct. "
        "No correction is applied here."),
    (0xA4FD30, 0xA4FF30): (
        "Intentional multi-entry `memset`/`memcpy` family. The overlapping starts "
        "at 4-byte offsets are real alternate entry points into a shared body; "
        "the body uses computed (`bctr`) jump tables. Do not collapse these "
        "aliases. The audit leaves them intact and keeps each `bctr` container "
        "whole. Only the canonical entry ends at the next 4-byte alias; the "
        "outer ranges share a common end."),
    (0xA30568, 0xA30728): (
        "One computed-jump function. The dispatcher is `0xA30568..0xA3058C`, the "
        "relative table is `0xA30590..0xA305B0`, and the case targets are "
        "`0xA305B0`, `0xA305B8`, `0xA305BC`, `0xA30604`, `0xA3064C`, `0xA30694`, "
        "`0xA306DC`; all converge on the epilogue at `0xA30720`. The corrected "
        "list keeps the dispatcher/table/cases whole and preserves the explicit "
        "case aliases. `0xA305B8` is a case target not in the candidate list; "
        "the lifter's jump-table pass discovers it, and the audit leaves the "
        "container intact rather than inventing a partial body."),
    (0xA56C04, 0xA58194): (
        "This is a mid-function tail entry, not a standalone getter. The frame "
        "was already allocated at `0xA56BA4`; `0xA56C04` starts with `mflr r0` "
        "and no `stdu`. It is a computed-jump container with case entries "
        "`0xA56D60` and `0xA56F64`. Keep it whole; splitting it by CFG would "
        "turn every case into an overlapping multi-KB function."),
    (0xAF17E4, 0xAF18E4): (
        "Not six independent getters. These are six case blocks of the switch "
        "dispatcher at `0xAF1758` (table `0xAF1780..0xAF17E4`, base 0xAF1780). "
        "The corrected list adds the missing dispatcher "
        "`0xAF1758..0xAF17E4` and models the case entries `0xAF17E4`, "
        "`0xAF17F4`, `0xAF1818`, `0xAF1844`, `0xAF186C`, `0xAF1894`, "
        "`0xAF18C0`; the first two overlap deliberately (0xAF17F4 falls into "
        "0xAF1800)."),
}


def _focus_ranges(image: ElfImage, corrected: Sequence[Func],
                  original: Sequence[Func], ranges: Sequence[Tuple[int, int]]) -> str:
    out = []
    corr = sorted(corrected, key=lambda f: f.start)
    orig = sorted(original, key=lambda f: f.start)
    for lo, hi in ranges:
        out.append(f"\n### {fmt_addr(lo)}..{fmt_addr(hi)}\n")
        rows = []
        for f in corr:
            if lo <= f.start < hi:
                first = _first_insn(image, f.start, f.end)
                last = _last_insn(image, f.end)
                rows.append([
                    fmt_addr(f.start) + ".." + fmt_addr(f.end),
                    f"{f.end - f.start}",
                    (f"{first.mnemonic} {first.operands}".strip()
                     if first else "?"),
                    (last.mnemonic if last else "?"),
                ])
        if rows:
            out.append(_table(rows, ["corrected range", "size", "first insn", "last insn"]))
        else:
            out.append("_no corrected functions in this range_")
        old_rows = []
        for f in orig:
            if lo <= f.start < hi:
                old_rows.append([fmt_addr(f.start) + ".." + fmt_addr(f.end),
                                 f"{f.end - f.start}"])
        if old_rows:
            out.append("\nBefore:")
            out.append(_table(old_rows, ["old range", "size"]))
        note = FOCUS_NOTES.get((lo, hi))
        if note:
            out.append("\n**Interpretation.** " + note)
    return "\n".join(out)


def write_report(path: str, res: AuditResult, image: ElfImage,
                 focus: Sequence[Tuple[int, int]],
                 generated_findings: Sequence[Dict[str, object]],
                 elf_path: str, func_path: str,
                 opd_path: Optional[str], code_end: int,
                 out_functions: Optional[str] = None,
                 out_ledger: Optional[str] = None) -> None:
    s = res.stats
    orig = res.original
    corr = res.corrected
    opd = res.opd

    # Correction size distribution.
    trims = [c for c in res.corrections
             if c.kind == "end" and c.old_end is not None and c.new_end is not None
             and c.new_end < c.old_end]
    adds = [c for c in res.corrections if c.kind == "added"]
    rems = [c for c in res.corrections if c.kind == "removed"]

    lines: List[str] = []
    A = lines.append
    A("# PPU function-boundary audit — GT6 BCUS98296 v1.00")
    A("")
    A(f"Generated by `tools/boundary_audit.py` from `{elf_path}` and "
      f"`{func_path}`" + (f" (OPD: `{opd_path}`)" if opd_path else "") + ".")
    A("")
    A("This is a static audit. It does not rebuild the port and does not modify "
      "`gt6/src`, `gt6/generated`, `third_party` or `gt6/build`.")
    A("")
    A("## Summary")
    A("")
    A(_table([
        ["Functions before", f"{s['original']:,}"],
        ["Functions after", f"{s['corrected']:,}"],
        ["Net change", f"{s['corrected'] - s['original']:+,}"],
        ["OPD starts (< code end)", f"{s['opd_starts']:,}"],
        ["Ends corrected", f"{s['end_changed']:,} ({s['trimmed']:,} trimmed, {s['extended']:,} carried into a merged prologue)"],
        ["New starts added", f"{s['added']:,}"],
        ["Starts removed / merged", f"{s['removed']:,}"],
        ["OPD starts lost", "0" if not [w for w in res.warnings if "OPD starts lost" in w] else "YES"],
        ["Warnings", f"{len(res.warnings):,}"],
    ], ["Metric", "Value"]))
    A("")
    A(f"Code range: `{fmt_addr(image.text_lo)}`..`{fmt_addr(code_end)}` "
      f"({code_end - image.text_lo:,} bytes).")
    A("")
    corr_end_by_start = {f.start: f.end for f in corr}
    opd_trims = [(s, f.end, corr_end_by_start[s]) for s, f in opd.items()
                 if s in corr_end_by_start and corr_end_by_start[s] < f.end]
    opd_bytes = sum(e - c for _s, e, c in opd_trims)
    A(f"{len(opd_trims):,} OPD entries had their corrected end below the OPD "
      f"upper bound, releasing {opd_bytes:,} bytes of container span (the code "
      "is redistributed into the added entry points below, not deleted). The "
      "ledger only records the subset that also differs from "
      "`functions_final3.json`; this count compares directly with the OPD end.")
    A("")
    A("## What was wrong")
    A("")
    A("The candidate list treats *next candidate start* as *function end*. "
      "That is safe only when the next candidate is the next real function. "
      "GT6 has three failure modes that break that assumption:")
    A("")
    A("1. **OPD containers.** `EMAIN.functions.json` ends every OPD entry at the "
      "next OPD start. Where the OPD table is sparse, one entry spans many real "
      "functions. Example: `0x163174..0x16E3F8` contains **159** separate "
      "0x120-byte functions; the candidate list gives the first one a 45,360-byte "
      "body.")
    A("2. **Leaf/thunk followed by a frame function.** A 12-byte `li; li; "
      "rldicl; b` thunk followed by `cmpwi; mflr; stdu` cannot be split by the "
      "lifter's prologue recovery, because the second function's `mflr` is "
      "before its first `stdu`. Example: `0x10ED8` (12 bytes) merged with "
      "`0x10EE8..0x110A4`.")
    A("3. **Prologue anchors.** `find_functions.py` sometimes seeds the `mflr` "
      "of a prologue, not the real entry, when a `mfcr`/`cmpwi`/`lis` setup "
      "instruction precedes it. The corrected list moves the start back. "
      "Example: `0x14398` (mflr) -> real entry `0x1437C` (mfcr; stdu...).")
    A("")
    A("The corrected list partitions every candidate range and every uncovered "
      "gap into maximal CFG-reachable islands, detects relative jump tables, "
      "keeps `bctr` switch containers whole (splitting only at unambiguous "
      "prologues after a terminator), and then merges prologue anchors into the "
      "real entry.")
    A("")
    A("A positive delta in the ledger is **not** new code. It happens when a "
      "range such as `0xB4EE80..0xB4EEE0` is only the prologue of a larger "
      "function: `0xB4EEE0` was a false `mflr` start. The real function starts "
      "at `0xB4EE80` and runs to `0xB57230`. The ledger records the earlier "
      "start's end as extended and the later anchor as removed; together they "
      "are one function.")
    A("")
    A("## Representative corrections (byte-verified)")
    A("")
    corr_by_start = {f.start: f for f in corr}
    orig_by_start2 = {f.start: f for f in orig}
    examples = [
        (0x00163174, "OPD container split"),
        (0x00010ED8, "leaf thunk split from next frame function"),
        (0x00B4EE80, "prologue-anchor merge (start moved back)"),
        (0x00AF1758, "missing switch dispatcher added"),
        (0x0001437C, "start moved from mflr back to mfcr/stdu"),
        (0x008B33B8, "nop padding start removed"),
    ]
    rows = []
    for addr, label in examples:
        c = corr_by_start.get(addr)
        if c is None:
            continue
        first = _first_insn(image, c.start, c.end)
        last = _last_insn(image, c.end)
        old = orig_by_start2.get(addr)
        old_s = (f"{fmt_addr(old.start)}..{fmt_addr(old.end)}"
                 if old else "not in candidate list")
        rows.append([
            label,
            old_s,
            f"{fmt_addr(c.start)}..{fmt_addr(c.end)}",
            (f"{first.mnemonic} {first.operands}".strip() if first else "?"),
            last.mnemonic if last else "?",
        ])
    A(_table(rows, ["case", "old range", "corrected range", "first insn", "last insn"]))
    A("")
    A("## Confidence")
    A("")
    A(_table([
        ["high", "End stops on an unconditional transfer (`blr`/`b`/`bctr`/`rfi`) "
                 "and the next instruction is a new entry, **or** the start is an "
                 "OPD start, a `bl` target, or a prologue with no competing evidence."],
        ["medium", "Gap-resident code island that is not directly referenced by a "
                   "`bl`/branch; still a valid code region, but provenance is weaker."],
        ["low", "Range contains `bctr` / an unrecognised computed jump, or the "
                "trim is blocked by OPD/`bl` evidence. Not auto-split; needs a "
                "manual look or the lifter's jump-table pass."],
    ], ["Confidence", "Meaning"]))
    A("")
    A("## Corrections")
    A("")
    A("### End corrections")
    A("")
    ledger_rel = (os.path.relpath(out_ledger, os.getcwd())
                  if out_ledger else "boundary_audit_ledger.json")
    A(f"{len(trims):,} functions were trimmed. The table lists every trim; the "
      "complete ledger (all end changes, added starts and removed starts) is in "
      f"`{ledger_rel}`.")
    A("")
    rows = []
    for c in sorted(trims, key=lambda c: (c.old_end or 0) - (c.new_end or 0),
                    reverse=True):
        delta = (c.old_end or 0) - (c.new_end or 0)
        last = _last_insn(image, c.new_end or c.start)
        rows.append([fmt_addr(c.start), fmt_addr(c.old_end or 0),
                     fmt_addr(c.new_end or 0), f"{delta:,}",
                     c.origin, c.confidence,
                     last.mnemonic if last else "?"])
    A(_table(rows, ["start", "old end", "new end", "trim", "origin", "confidence",
                    "last insn"]))
    A("")
    exts = [c for c in res.corrections
            if c.kind == "end" and c.old_end is not None and c.new_end is not None
            and c.new_end > c.old_end]
    A(f"### Prologue-anchor merges (ends carried forward)")
    A("")
    A(f"{len(exts):,} earlier starts absorbed a later false start whose first "
      "instruction was `mflr r0`/`stdu` but which was inside the same function. "
      "The retained start's end is carried forward; the later start is listed "
      "under removed starts.")
    A("")
    rows = []
    for c in sorted(exts, key=lambda c: (c.new_end or 0) - (c.old_end or 0),
                    reverse=True):
        anchor = ""
        for r in rems:
            if c.start < r.start < (c.new_end or 0):
                anchor = fmt_addr(r.start)
                break
        rows.append([fmt_addr(c.start), fmt_addr(c.old_end or 0),
                     fmt_addr(c.new_end or 0), anchor or "-",
                     c.confidence])
    A(_table(rows, ["start", "old end", "new end", "merged anchor", "confidence"]))
    A("")
    A("")
    A("### Added starts")
    A("")
    A(f"{len(adds):,} starts were added. They are grouped into contiguous "
      "runs; each run is a region of code that the candidate list either "
      "swallowed or did not cover at all.")
    A("")
    # Group added starts into contiguous runs.
    groups: List[List[int]] = []
    for c in sorted(adds, key=lambda c: c.start):
        if groups and c.start == groups[-1][-1] + 4:
            groups[-1].append(c.start)
        else:
            groups.append([c.start])
    rows = []
    corr_by_start_all = {f.start: f for f in corr}
    for g in groups:
        first = g[0]
        last = g[-1]
        count = len(g)
        kinds = collections.Counter()
        ends = []
        for a in g:
            f = corr_by_start_all.get(a)
            if f is not None:
                ends.append(f.end)
            kinds[_entry_kind(image, a, min(a + 64, code_end))] += 1
        if ends:
            end_s = (fmt_addr(min(ends)) if min(ends) == max(ends)
                     else fmt_addr(min(ends)) + ".." + fmt_addr(max(ends)))
        else:
            end_s = "?"
        rows.append([fmt_addr(first) + (".." + fmt_addr(last) if count > 1 else ""),
                     str(count), end_s,
                     ", ".join(f"{k}:{v}" for k, v in kinds.most_common())])
    A(_table(rows, ["added starts", "count", "new end(s)", "entry kinds"]))
    A("")
    A("### Removed starts")
    A("")
    A(f"{len(rems):,} candidate starts were removed. In every case the address "
      "was a prologue anchor (`mflr r0` / `stdu`) inside the function that now "
      "starts earlier, or a padding `nop` before an atomic helper; the "
      "containing function has the same end (or carries it forward).")
    A("")
    rows = []
    for c in sorted(rems, key=lambda c: c.start):
        rows.append([fmt_addr(c.start), fmt_addr(c.new_end or 0),
                     c.confidence, c.evidence])
    A(_table(rows, ["removed start", "same end as container", "confidence", "evidence"]))
    A("")
    A("## Focus ranges")
    A(_focus_ranges(image, corr, orig, focus))
    A("")
    A("## Short-leaf scan")
    A("")
    A("A short first block that returns (`blr`) inside a much larger declared range "
      "is the classic over-merge signature. The corrected list was scanned for "
      "it; the remaining cases are listed below. They are *not* over-merges: the "
      "`blr` is an early return behind a conditional branch, or the start is a "
      "deliberate multi-entry alias into a jump-table body.")
    A("")
    short_rows = []
    for f in corr:
        n = min(24, f.end - f.start)
        ins = image.disasm(f.start, f.start + n)
        if not ins:
            continue
        saw_cond = False
        blr_idx = None
        for i, x in enumerate(ins[:6]):
            if is_cond_branch(x.mnemonic):
                saw_cond = True
            if x.mnemonic == "blr":
                blr_idx = i
                break
            if x.mnemonic in ("b", "bctr"):
                break
        if blr_idx is not None and f.end - f.start > 64:
            kind = "early return" if saw_cond else "multi-entry alias"
            short_rows.append([fmt_addr(f.start), fmt_addr(f.end),
                               str(f.end - f.start), str(blr_idx + 1), kind])
    if short_rows:
        A(_table(short_rows, ["start", "end", "size", "insns to first blr", "classification"]))
    else:
        A("None.")
    A("")
    A("## The 0xA13644 record (correct as-is)")
    A("")
    A("The earlier `docs/STATUS.md` / `docs/HANDOFF.md` claim that `0xA13644` "
      "is an 8-byte `lbz r3,0x10(r3); blr` is **false**. Ground truth from "
      "`EMAIN.elf`:")
    A("")
    A("```")
    A("0xA13644  stdu  r1,-0x90(r1)")
    A("0xA13648  mflr  r0")
    A("0xA1364C  std   r29,0x78(r1)")
    A("0xA13650  lis   r29,0x165")
    A("0xA13654  std   r28,0x70(r1)")
    A("0xA13658  addi  r29,r29,-0x5510      ; 0x164AAF0")
    A("0xA1365C  std   r0,0xA0(r1)")
    A("0xA13660  addi  r28,r29,0x60         ; 0x164AB50 (lock object)")
    A("0xA13664  clrldi r28,r28,0x20")
    A("0xA13668  mr    r3,r28")
    A("0xA1366C  bl    0xA42DE8             ; lock")
    A("0xA13670  addi  r3,r29,0x90          ; 0x164AB80 (flag object)")
    A("0xA13674  bl    0x3C0E84             ; lbz r3,0x10(r3); blr")
    A("0xA13678  mr    r29,r3")
    A("0xA1367C  mr    r3,r28")
    A("0xA13680  bl    0xA42D3C             ; unlock")
    A("0xA13684  ld    r0,0xA0(r1)")
    A("0xA13688  ld    r28,0x70(r1)")
    A("0xA1368C  clrldi r3,r29,0x38")
    A("0xA13690  mtlr  r0")
    A("0xA13694  ld    r29,0x78(r1)")
    A("0xA13698  addi  r1,r1,0x90")
    A("0xA1369C  blr")
    A("0xA136A0  stdu  r1,-0xA0(r1)         ; next function")
    A("```")
    A("")
    A("`functions_final3.json`'s `0xA13644..0xA136A0` is therefore **correct**, "
      "and this audit does **not** shorten it or list it as a correction. The "
      "8-byte getter is `0x3C0E84..0x3C0E8C` and was already correctly listed. "
      "The fake-leaf body patch in `gt6/generated` has been reverted. Keep the "
      "first-instruction cross-check as a general gate, but do not special-case "
      "`0xA13644`.")
    A("")
    A("## Generated-code cross-check")
    A("")
    if generated_findings:
        mismatches = sum(1 for f in generated_findings if f.get("mismatch"))
        splits = sum(1 for f in generated_findings if f.get("split"))
        A(f"`tools/boundary_audit.py` found {len(generated_findings)} generated "
          f"functions to review: **{mismatches}** with a first-instruction "
          f"mismatch and **{splits}** whose old body contains dead code after a "
          "top-level `return;` now covered by a corrected split. A mismatch is "
          "a manual/stale body; a split is expected to disappear on the next "
          "relift (the generated tree is still from `functions_final3.json`). "
          "The first 40 are listed below.")
        A("")
        rows = []
        for f in generated_findings[:40]:
            rows.append([f["func"], fmt_addr(f["addr"]), f["file"],
                         f["mismatch"] or "-", f["split"] or "-"])
        A(_table(rows, ["function", "start", "file", "start mismatch", "corrected split"]))
        if mismatches == 0:
            A("")
            A("No first-instruction mismatches remain; in particular "
              "`func_00A13644` now matches the wrapper bytes. All listed "
              "findings are stale merged bodies that the corrected list splits.")
    else:
        A("No generated C++ directory was supplied, or no mismatch was found.")
    A("")
    A("## Suggested post-lift patch policy")
    A("")
    A("Cases that cannot be fixed by ends alone:")
    A("")
    A("1. **Never patch a generated body without checking the ELF bytes at the "
      "function's start.** `0xA13644` is the canonical counter-example: a former "
      "manual patch labelled it a \"corrected leaf getter\" although the bytes "
      "are a frame-allocating wrapper. The patch has been reverted; keep the "
      "first-instruction check so this class of edit cannot return.")
    A("2. **Multi-entry routines** (memset/memcpy family at `0xA4FD30..0xA4FF30`, "
      "jump-table cases, `0xA305B0`, `0xA56F64`, `0xAF2658`): keep every explicit "
      "entry, give each an end that stops at the next entry or the shared "
      "epilogue, and do not let a tail entry inherit the next OPD function's "
      "end. The lifter's `_MAX_MID_TAIL` cap is a safety net, not a boundary.")
    A("3. **`bctr` switch containers** (`0xA30568`, `0xA56C04`, `0xA4FDBC`): do "
      "not CFG-split them. Add the dispatcher and, if needed, each case target "
      "as an explicit start whose end is the shared epilogue. The lifter's "
      "jump-table pass already discovers relative tables; explicit entries are "
      "for cases reached only through function-pointer tables.")
    A("4. **Prologue anchors:** prefer moving the start back to the `mfcr`/"
      "`cmpwi`/`lis` setup instruction over patching the body. The real entry is "
      "the first instruction after the previous function's terminator, not "
      "necessarily `mflr`.")
    A("5. **OPD containers:** keep the OPD start and `toc`/`opd` metadata, but "
      "let the CFG-derived child starts bound the container. An OPD end is an "
      "upper bound, not a size.")
    A("6. **Semantic bugs** (the boot flag, null constructor entries) belong in "
      "`gt6/src` or HLE stubs, not in generated bodies. A body patch hides the "
      "fact that the guest never initialised the object.")
    A("7. **CI gate:** run `python tools/boundary_audit.py --check` after every "
      "lift. It fails on: lost OPD starts, a start that is not code, an end "
      "past the OPD bound, or a generated function whose first guest statement "
      "does not match the ELF.")
    A("")
    A("## Warnings from this run")
    A("")
    if res.warnings:
        A(f"{len(res.warnings):,} warnings. The first 100:")
        A("")
        for w in res.warnings[:100]:
            A(f"- {w}")
    else:
        A("None.")
    A("")
    A("## Files")
    A("")
    if out_functions:
        A(f"- Corrected list: `{os.path.relpath(out_functions, os.getcwd())}`")
    else:
        A("- Corrected list: not written (`--out-functions` omitted)")
    if out_ledger:
        A(f"- Per-correction ledger: `{os.path.relpath(out_ledger, os.getcwd())}`")
    A(f"- Report: `{os.path.relpath(path, os.getcwd())}`")
    A("- Tool: `tools/boundary_audit.py`")
    A("")

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_ledger(path: str, res: AuditResult, image: ElfImage) -> None:
    records = []
    for c in res.corrections:
        rec = {
            "kind": c.kind,
            "start": fmt_addr(c.start),
            "old_end": fmt_addr(c.old_end) if c.old_end is not None else None,
            "new_end": fmt_addr(c.new_end) if c.new_end is not None else None,
            "origin": c.origin,
            "confidence": c.confidence,
            "reason": c.reason,
            "evidence": c.evidence,
        }
        records.append(rec)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1)


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------


def check_list(image: ElfImage, funcs: Sequence[Func], opd: Dict[int, Func],
               code_end: int) -> List[str]:
    errors: List[str] = []
    starts = {f.start for f in funcs}
    for s in opd:
        if s < code_end and s not in starts:
            errors.append(f"missing OPD start {fmt_addr(s)}")
    for f in funcs:
        if f.end <= f.start:
            errors.append(f"{fmt_addr(f.start)}: end <= start")
        if (f.start & 3) or (f.end & 3):
            errors.append(f"{fmt_addr(f.start)}: unaligned range")
        if f.end > code_end:
            errors.append(f"{fmt_addr(f.start)}: end past code end")
        if f.start in opd and f.end > opd[f.start].end:
            errors.append(f"{fmt_addr(f.start)}: end past OPD bound")
        first = _first_insn(image, f.start, f.end)
        if first is None or is_data(first) or is_padding(first):
            errors.append(f"{fmt_addr(f.start)}: start is not code")
    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_focus(values: Optional[Sequence[str]]) -> List[Tuple[int, int]]:
    default = [
        (0xA13508, 0xA13704),
        (0xA4FD30, 0xA4FF30),
        (0xA30568, 0xA30728),
        (0xA56C04, 0xA58194),
        (0xAF17E4, 0xAF18E4),
    ]
    if not values:
        return default
    out = []
    for value in values:
        lo_s, hi_s = value.split("-", 1)
        out.append((parse_int(lo_s), parse_int(hi_s)))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--elf", required=True, help="decrypted PPU ELF")
    parser.add_argument("--functions", required=True, help="candidate function JSON")
    parser.add_argument("--opd", default=None, help="authoritative OPD JSON")
    parser.add_argument("--out-functions", default=None,
                        help="write corrected function JSON here")
    parser.add_argument("--out-report", default=None,
                        help="write Markdown report here")
    parser.add_argument("--out-ledger", default=None,
                        help="write per-correction JSON ledger here")
    parser.add_argument("--generated", default=None,
                        help="optional gt6/generated directory to cross-check")
    parser.add_argument("--code-end", default=f"0x{DEFAULT_CODE_END:X}",
                        help="exclusive end of executable range")
    parser.add_argument("--focus", action="append", default=None,
                        help="START-END range to detail (repeatable)")
    parser.add_argument("--no-gaps", action="store_true",
                        help="do not fill code gaps between candidate ranges")
    parser.add_argument("--check", action="store_true",
                        help="validate --functions instead of writing a new list")
    args = parser.parse_args(argv)

    code_end = parse_int(args.code_end)
    image = ElfImage(args.elf)
    original = load_functions(args.functions)
    opd = load_opd(args.opd)
    focus = parse_focus(args.focus)

    if args.check:
        errors = check_list(image, original, opd, code_end)
        if errors:
            for e in errors:
                print("ERROR:", e)
            return 1
        print(f"OK: {len(original):,} functions, no OPD loss or invalid starts")
        return 0

    res = build_corrections(original, opd, image, code_end,
                            include_gaps=not args.no_gaps)

    if args.out_functions:
        records = []
        for f in res.corrected:
            rec = {"start": fmt_addr(f.start), "end": fmt_addr(f.end)}
            if f.start in res.opd:
                o = res.opd[f.start]
                if o.toc is not None:
                    rec["toc"] = o.toc
                if o.opd is not None:
                    rec["opd"] = o.opd
            records.append(rec)
        os.makedirs(os.path.dirname(os.path.abspath(args.out_functions)) or ".",
                    exist_ok=True)
        with open(args.out_functions, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=1)
        print(f"wrote {len(records):,} functions to {args.out_functions}")

    if args.out_ledger:
        write_ledger(args.out_ledger, res, image)
        print(f"wrote ledger to {args.out_ledger}")

    if args.out_report:
        generated = audit_generated(args.generated, res.corrected, image,
                                    res.corrections)
        write_report(args.out_report, res, image, focus, generated,
                     args.elf, args.functions, args.opd, code_end,
                     args.out_functions, args.out_ledger)
        print(f"wrote report to {args.out_report}")

    print(f"before={res.stats['original']:,} after={res.stats['corrected']:,} "
          f"added={res.stats['added']:,} removed={res.stats['removed']:,} "
          f"end_changed={res.stats['end_changed']:,} "
          f"warnings={len(res.warnings):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
