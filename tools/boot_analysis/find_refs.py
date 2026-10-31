#!/usr/bin/env python3
"""Find code references to guest addresses in a PS3 PPU ELF.

Small forward constant propagation over straight-line code.  Recognises the
lis/addi/ori/addis idioms PS3 compilers use to materialise globals and reports
every load/store whose effective address hits one of the watched addresses.

Usage:
  python tools/boot_analysis/find_refs.py work/bin/EMAIN.elf 0x16A99D0 ...
"""
import argparse
import bisect
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

TOK_RE = re.compile(r"-?0x[0-9a-fA-F]+|-?\d+")
MEM_RE = re.compile(r"(?P<disp>-?0x[0-9a-fA-F]+|-?\d+)?\((?P<base>r\d+)\)")


def load_elf(path):
    d = Path(path).read_bytes()
    assert d[:4] == b"\x7fELF"
    e_phoff = struct.unpack_from(">Q", d, 0x20)[0]
    e_phentsize = struct.unpack_from(">H", d, 0x36)[0]
    e_phnum = struct.unpack_from(">H", d, 0x38)[0]
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from(">I", d, off)[0]
        p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            ">QQQQQQ", d, off + 8)
        if p_type == 1 and p_filesz:
            segs.append((p_vaddr, p_offset, p_filesz, p_memsz))
    return d, segs


def func_starts(path):
    fs = json.load(open(path))
    out = []
    for x in fs:
        s = x["start"] if isinstance(x, dict) else x
        out.append(int(s, 16))
    return sorted(set(out))


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def split_ops(op_str):
    return [x.strip() for x in op_str.split(",")] if op_str else []


def is_reg(tok):
    return bool(re.fullmatch(r"r\d+", tok))


def parse_imm(tok):
    tok = tok.strip().lstrip("#")
    return int(tok, 0)


BRANCHES = {
    "b", "ba", "bc", "bca", "bcl", "bcla", "blr", "blrl", "bctr", "bctrl",
    "bcctr", "bcctrl", "beq", "bne", "blt", "bgt", "ble", "bge", "bso", "bns",
    "bdnz", "bdz", "bdnzt", "bdnzf", "bt", "bf", "beq-", "bne-", "beq+", "bne+",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("watch", nargs="+", help="hex guest addresses")
    ap.add_argument("--functions", default="work/analysis/emain/functions_final3.json")
    ap.add_argument("--json-out")
    args = ap.parse_args()

    watch = set()
    ranges = []
    for w in args.watch:
        if "-" in w:
            lo, hi = w.split("-")
            ranges.append((int(lo, 16), int(hi, 16)))
        else:
            watch.add(int(w, 16))
    d, segs = load_elf(args.elf)
    starts = func_starts(args.functions)

    vaddr, off, filesz, memsz = segs[0]

    def containing(va):
        i = bisect.bisect_right(starts, va) - 1
        return starts[i] if i >= 0 else 0

    refs = []
    regs = {}
    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    md.detail = False

    blob = d[off:off + filesz]
    # Capstone's streaming disassembler stops at the first word it cannot
    # decode; .text contains data and VMX encodings it rejects.  Decode one
    # word at a time and just skip unknown words.
    def instructions():
        pos = 0
        while pos < len(blob):
            got = list(md.disasm(blob[pos:pos + 4], vaddr + pos))
            if got:
                yield got[0]
            pos += 4

    for insn in instructions():
        m = insn.mnemonic
        ops = split_ops(insn.op_str)

        def rec(kind):
            refs.append(dict(addr=insn.address, fn=containing(insn.address),
                             kind=kind, insn=f"{m} {insn.op_str}"))

        if m == "lis":
            regs[ops[0]] = (parse_imm(ops[1]) & 0xFFFF) << 16
        elif m == "li":
            regs[ops[0]] = parse_imm(ops[1]) & 0xFFFFFFFF
        elif m == "addis":
            rt, ra, imm = ops[0], ops[1], parse_imm(ops[2])
            if ra == "r0" or ra == "0":
                regs[rt] = (imm & 0xFFFF) << 16
            elif ra in regs:
                regs[rt] = (regs[ra] + ((imm & 0xFFFF) << 16)) & 0xFFFFFFFF
            else:
                regs.pop(rt, None)
        elif m == "addi":
            rt, ra, imm = ops[0], ops[1], parse_imm(ops[2])
            if ra in regs:
                regs[rt] = (regs[ra] + s16(imm & 0xFFFF)) & 0xFFFFFFFF
            else:
                regs.pop(rt, None)
        elif m == "ori":
            ra, rs, imm = ops[0], ops[1], parse_imm(ops[2])
            if rs in regs:
                regs[ra] = (regs[rs] | (imm & 0xFFFF)) & 0xFFFFFFFF
            else:
                regs.pop(ra, None)
        elif m in ("mr", "or") and len(ops) == 2:
            ra, rs = ops
            if rs in regs:
                regs[ra] = regs[rs]
            else:
                regs.pop(ra, None)
        elif m in ("lwz", "lbz", "lhz", "ld", "lwa", "lwzu", "lbzu", "ldu"):
            rt = ops[0]
            mm = MEM_RE.search(ops[1])
            if mm:
                base = mm.group("base")
                disp = parse_imm(mm.group("disp") or "0")
                if base in regs:
                    ea = (regs[base] + disp) & 0xFFFFFFFF
                    if ea in watch or any(lo <= ea <= hi for lo, hi in ranges):
                        rec("load")
                    if m in ("lwzu", "lbzu", "ldu"):
                        regs[base] = ea
        elif m in ("stw", "stb", "sth", "std", "stwu", "stbu", "sthu", "stdu",
                   "stwcx.", "stdcx."):
            mm = MEM_RE.search(ops[1])
            if mm:
                base = mm.group("base")
                disp = parse_imm(mm.group("disp") or "0")
                if base in regs:
                    ea = (regs[base] + disp) & 0xFFFFFFFF
                    if ea in watch or any(lo <= ea <= hi for lo, hi in ranges):
                        rec("store")
                    if m in ("stwu", "stbu", "sthu", "stdu"):
                        regs[base] = ea

        if m in ("bl", "bla", "bctrl", "bcl", "bcctrl"):
            regs.clear()
        elif m in BRANCHES or (m.startswith("b") and m not in ("bl", "blr")):
            # local branch/call: control flow merge, drop constants
            regs.clear()

    seen = set()
    out = []
    for r in refs:
        key = r["addr"]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    for r in out:
        print(f"{r['addr']:08X} fn={r['fn']:08X} {r['kind']:5s} {r['insn']}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
