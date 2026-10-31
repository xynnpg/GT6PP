#!/usr/bin/env python3
"""Disassemble guest PPU address ranges from work/bin/EMAIN.elf.

Usage:
  python tools/gt6_disasm_range.py 0x98759C 0x987EC8
  python tools/gt6_disasm_range.py 0x9CDF00:80 0x9CD410:120

Addresses are guest virtual addresses; an optional :LEN caps the byte
count (otherwise the next range start, or the end of the segment, is used).
Requires capstone (same dependency as tools/boot_analysis/find_addr.py).
"""
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

DEFAULT_ELF = Path("work/bin/EMAIN.elf")


def load_elf(path):
    d = Path(path).read_bytes()
    e_phoff = struct.unpack_from(">Q", d, 0x20)[0]
    e_phentsize = struct.unpack_from(">H", d, 0x36)[0]
    e_phnum = struct.unpack_from(">H", d, 0x38)[0]
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from(">I", d, off)[0]
        p_offset, p_vaddr, _p_paddr, p_filesz, _p_memsz, _p_align = struct.unpack_from(
            ">QQQQQQ", d, off + 8)
        if p_type == 1 and p_filesz:
            segs.append((p_vaddr, p_offset, p_filesz))
    return d, segs


def read_guest(d, segs, va, n):
    for vaddr, off, filesz in segs:
        if vaddr <= va < vaddr + filesz:
            k = min(n, vaddr + filesz - va)
            return d[off + (va - vaddr):off + (va - vaddr) + k]
    raise SystemExit(f"0x{va:X} is not in a file-backed PT_LOAD segment")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    elf = DEFAULT_ELF
    args = sys.argv[1:]
    if args and args[0].endswith(".elf"):
        elf = Path(args.pop(0))
    specs = []
    for a in args:
        if ":" in a:
            lo, ln = a.split(":")
            specs.append((int(lo, 16), int(ln, 16)))
        else:
            specs.append((int(a, 16), None))
    d, segs = load_elf(elf)
    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    md.detail = False
    for i, (lo, n) in enumerate(specs):
        if n is None:
            n = (specs[i + 1][0] - lo) if i + 1 < len(specs) else 0x400
        code = read_guest(d, segs, lo, n)
        print(f"# {lo:08X}..{lo + len(code):08X} ({len(code)} bytes)")
        for insn in md.disasm(code, lo):
            print(f"{insn.address:08X}: {insn.mnemonic:8s} {insn.op_str}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
