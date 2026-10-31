#!/usr/bin/env python3
"""Find every place a PS3 PPU function materialises a guest address.

Tracks lis/addi/ori/addis through straight-line code and reports when a
register ends up equal to a watched address, plus the memory access (if any)
that consumes it.  Also searches the raw file and .data for the address.

Usage:
  python tools/boot_analysis/find_addr.py work/bin/EMAIN.elf 0x16A99D0 ...
"""
import argparse
import bisect
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

MEM_RE = re.compile(r"(?P<disp>-?0x[0-9a-fA-F]+|-?\d+)?\((?P<base>r\d+)\)")


def load_elf(path):
    d = Path(path).read_bytes()
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


def starts_of(path):
    fs = json.load(open(path))
    return sorted({int(x["start"] if isinstance(x, dict) else x, 16) for x in fs})


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def ops_of(s):
    return [x.strip() for x in s.split(",")] if s else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("watch", nargs="+")
    ap.add_argument("--functions", default="work/analysis/emain/functions_final3.json")
    args = ap.parse_args()

    watch = {}
    for w in args.watch:
        if "-" in w:
            lo, hi = w.split("-")
            watch[(int(lo, 16), int(hi, 16))] = w
        else:
            watch[(int(w, 16), int(w, 16))] = w

    def watched(v):
        for (lo, hi), name in watch.items():
            if lo <= v <= hi:
                return name
        return None

    d, segs = load_elf(args.elf)
    starts = starts_of(args.functions)
    vaddr, off, filesz, _ = segs[0]

    # raw occurrence in the file
    for (lo, hi), name in watch.items():
        for v in (lo,) if lo == hi else ():
            pat = struct.pack(">I", v)
            hits = []
            i = 0
            while True:
                j = d.find(pat, i)
                if j < 0:
                    break
                hits.append(j)
                i = j + 1
            print(f"[raw] {name}: {len(hits)} occurrence(s) {[hex(x) for x in hits[:10]]}")

    def containing(va):
        i = bisect.bisect_right(starts, va) - 1
        return starts[i] if i >= 0 else 0

    regs = {}
    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)

    def insns():
        pos = 0
        while pos < filesz:
            got = list(md.disasm(d[off + pos:off + pos + 4], vaddr + pos))
            if got:
                yield got[0]
            pos += 4

    hits = []
    for insn in insns():
        m, os_ = insn.mnemonic, ops_of(insn.op_str)

        def hit(how, val):
            name = watched(val)
            if name:
                hits.append((insn.address, containing(insn.address), how,
                             f"{m} {insn.op_str}", val, name))

        if m == "lis":
            regs[os_[0]] = (int(os_[1], 0) & 0xFFFF) << 16
            hit("lea", regs[os_[0]])
        elif m == "li":
            regs[os_[0]] = int(os_[1], 0) & 0xFFFFFFFF
            hit("lea", regs[os_[0]])
        elif m == "addis":
            rt, ra = os_[0], os_[1]
            imm = int(os_[2], 0)
            if ra == "r0":
                regs[rt] = (imm & 0xFFFF) << 16
            elif ra in regs:
                regs[rt] = (regs[ra] + ((imm & 0xFFFF) << 16)) & 0xFFFFFFFF
            else:
                regs.pop(rt, None)
            if rt in regs:
                hit("lea", regs[rt])
        elif m == "addi":
            rt, ra = os_[0], os_[1]
            imm = int(os_[2], 0) & 0xFFFF
            if ra in regs:
                regs[rt] = (regs[ra] + s16(imm)) & 0xFFFFFFFF
                hit("lea", regs[rt])
            else:
                regs.pop(rt, None)
        elif m == "ori":
            ra, rs = os_[0], os_[1]
            imm = int(os_[2], 0) & 0xFFFF
            if rs in regs:
                regs[ra] = (regs[rs] | imm) & 0xFFFFFFFF
                hit("lea", regs[ra])
            else:
                regs.pop(ra, None)
        elif m in ("mr", "or") and len(os_) == 2:
            ra, rs = os_
            if rs in regs:
                regs[ra] = regs[rs]
                hit("copy", regs[ra])
            else:
                regs.pop(ra, None)
        elif m in ("lwz", "lbz", "lhz", "ld", "lwa", "lwzu", "lbzu", "ldu"):
            mm = MEM_RE.search(os_[1]) if len(os_) > 1 else None
            if mm:
                base = mm.group("base")
                disp = int(mm.group("disp") or "0", 0)
                if base in regs:
                    ea = (regs[base] + disp) & 0xFFFFFFFF
                    hit("load", ea)
                    if m in ("lwzu", "lbzu", "ldu"):
                        regs[base] = ea
        elif m in ("stw", "stb", "sth", "std", "stwu", "stbu", "sthu", "stdu",
                   "stwcx.", "stdcx."):
            mm = MEM_RE.search(os_[1]) if len(os_) > 1 else None
            if mm:
                base = mm.group("base")
                disp = int(mm.group("disp") or "0", 0)
                if base in regs:
                    ea = (regs[base] + disp) & 0xFFFFFFFF
                    hit("store", ea)
                    if m in ("stwu", "stbu", "sthu", "stdu"):
                        regs[base] = ea

        if m in ("bl", "bla", "bctrl", "bcl", "bcctrl"):
            regs.clear()
        elif m == "blr" or (m.startswith("b") and m not in ("bl", "blr")):
            regs.clear()

    for a, fn, how, text, val, name in hits:
        print(f"{a:08X} fn={fn:08X} {how:5s} {text:32s} -> {val:08X} [{name}]")


if __name__ == "__main__":
    main()
