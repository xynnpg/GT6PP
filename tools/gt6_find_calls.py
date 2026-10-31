#!/usr/bin/env python3
"""List direct (bl) call sites of guest PPU functions.

Usage:
  python tools/gt6_find_calls.py 0x9D8DB0 0x994078 0x9BB020
"""
import bisect
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

ELF = Path("work/bin/EMAIN.elf")
FUNCS = Path("work/analysis/emain/functions_final3.json")


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


def main():
    targets = {int(a, 16) for a in sys.argv[1:]}
    if not targets:
        print(__doc__)
        return 1
    d, segs = load_elf(ELF)
    starts = sorted({int(x["start"] if isinstance(x, dict) else x, 16)
                     for x in json.load(open(FUNCS))})
    vaddr, off, filesz = segs[0]
    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    md.skipdata = True
    calls = {t: [] for t in targets}
    for insn in md.disasm(d[off:off + filesz], vaddr):
        if insn.mnemonic not in ("bl", "bla"):
            continue
        try:
            tgt = int(insn.op_str, 16)
        except ValueError:
            continue
        if tgt in targets:
            i = bisect.bisect_right(starts, insn.address) - 1
            fn = starts[i] if i >= 0 else 0
            calls[tgt].append((insn.address, fn))
    for t in sorted(targets):
        print(f"== calls to {t:08X} ({len(calls[t])})")
        for a, fn in calls[t]:
            print(f"  {a:08X} fn={fn:08X} +0x{a - fn:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
