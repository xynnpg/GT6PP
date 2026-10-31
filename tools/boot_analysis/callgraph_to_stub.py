#!/usr/bin/env python3
"""BFS over direct `bl` edges from a PPU function to import stubs / targets."""
import argparse
import bisect
import json
import re
import struct
import sys
from collections import deque
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("start", help="hex start address")
    ap.add_argument("--stubs", default="work/analysis/emain/hle_stubs_named.json")
    ap.add_argument("--maxdepth", type=int, default=8)
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()

    d, segs = load_elf(args.elf)
    vaddr, off, filesz, _ = segs[0]
    start = int(args.start, 16)

    stubs = {}
    for e in json.load(open(args.stubs)):
        stubs[int(e["stub"], 16)] = (e.get("module"), e.get("name"), e["nid"])

    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    blob = d[off:off + filesz]

    def insn_at(addr):
        pos = addr - vaddr
        if pos < 0 or pos + 4 > len(blob):
            return None
        got = list(md.disasm(blob[pos:pos + 4], addr))
        return got[0] if got else None

    # decode whole text once, record direct bl targets per instruction address
    calls = {}
    pos = 0
    while pos < len(blob):
        got = list(md.disasm(blob[pos:pos + 4], vaddr + pos))
        if got:
            i = got[0]
            if i.mnemonic in ("bl", "bla"):
                mm = re.search(r"0x([0-9a-fA-F]+)", i.op_str)
                if mm:
                    calls[vaddr + pos] = int(mm.group(1), 16)
        pos += 4

    sys.path.insert(0, "tools/boot_analysis")
    # nearest function start for reporting
    fs = json.load(open("work/analysis/emain/functions_final3.json"))
    starts = sorted({int(x["start"] if isinstance(x, dict) else x, 16) for x in fs})
    def fn(addr):
        i = bisect.bisect_right(starts, addr) - 1
        return starts[i] if i >= 0 else 0

    # BFS over functions: for each function start, scan its body until next start
    # (bounded 0x4000) and collect bl targets.
    def body_calls(f):
        i = bisect.bisect_right(starts, f)
        end = starts[i] if i < len(starts) else f + 0x4000
        end = min(end, f + 0x4000)
        out = []
        for a in range(f, end, 4):
            if a in calls:
                out.append(calls[a])
        return out

    q = deque([(start, [start])])
    seen = {start}
    found = []
    while q:
        f, path = q.popleft()
        if len(path) > args.maxdepth:
            continue
        for t in body_calls(f):
            if t in stubs:
                found.append((path + [t], stubs[t]))
                if len(found) >= args.limit:
                    break
            elif vaddr <= t < vaddr + filesz and t not in seen:
                seen.add(t)
                q.append((t, path + [t]))
        if len(found) >= args.limit:
            break

    for path, s in found:
        print(" -> ".join(f"{a:08X}" for a in path), "=>", s)


if __name__ == "__main__":
    main()
