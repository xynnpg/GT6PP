#!/usr/bin/env python3
"""Check whether a decrypted GT6 EMAIN.elf matches the layout GT6PP was built on.

GT6PP hard-codes guest addresses (0x9CD410, 0x987910, 0xB98168, ...) taken from
the US disc (BCUS98296 v1.00). Run this on the ELF of any other disc (EU, JP,
patched builds) BEFORE a relift. Passing only means the sampled layout checks
(sizes, entry/TOC values and the first instruction at a handful of anchors)
agree with the US build. It does not prove that every address used by the
function lists and patches matches; only a relift and a build confirm that.

Usage:
  python tools/gt6_region_check.py [work/bin/EMAIN.elf]

Exit code 0 = all anchors pass, 1 = at least one mismatch (do not reuse the
US address lists), 2 = file/ELF problem. Prints the SHA-256 so results can be
compared between machines. Needs capstone (already a project dependency).
"""
import hashlib
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

# Values documented for the US build (README / docs/BUILDING.md section 4).
EXPECT = {
    "size": 22_371_400,
    "entry_opd": 0x148E2E0,
    "entry_code": 0x10230,
    "toc": 0x14ED560,
}

# (guest address, expected first mnemonic(s), why it matters)
ANCHORS = [
    (0x00013830, ("stdu",), "boot script loader (scripts/gt6/main)"),
    (0x00987910, ("bctr",), "ADCH parser jump-table dispatch (gt6_adch_switch_patch)"),
    (0x009CD410, ("lis",), "ADCH header reader"),
    (0x009FF530, ("stdu",), "PFS guest cipher"),
    (0x00A43AB4, ("stdu",), "PDISTD SpuInflator"),
    (0x00A564EC, ("stdu",), "Spu Event Handler thread entry"),
    (0x00A569D0, ("stdu",), "SPURS dispatch (id>=16 guard)"),
    (0x00B98168, ("addi",), "libc setjmp (setjmp_patch_gt6)"),
    (0x00B9828C, ("addi",), "libc longjmp (setjmp_patch_gt6)"),
    (0x00F9AC18, ("li",), "HLE import stub (li r12,0 ; oris r12,..)"),
]


def load_segments(d):
    phoff = struct.unpack_from(">Q", d, 0x20)[0]
    phentsize, phnum = struct.unpack_from(">HH", d, 0x36)
    segs = []
    for i in range(phnum):
        o = phoff + i * phentsize
        if struct.unpack_from(">I", d, o)[0] != 1:  # PT_LOAD
            continue
        off, va, _pa, fsz, msz, _al = struct.unpack_from(">QQQQQQ", d, o + 8)
        segs.append((va, fsz, off))
    return segs


def read_va(d, segs, va, n):
    for sva, fsz, off in segs:
        if sva <= va < sva + fsz:
            s = off + (va - sva)
            return d[s:s + n]
    return None


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "work/bin/EMAIN.elf")
    try:
        d = path.read_bytes()
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 2
    if d[:4] != b"\x7fELF":
        print(f"{path} is not an ELF (still an encrypted SELF?)")
        return 2

    try:
        segs = load_segments(d)
        entry = struct.unpack_from(">Q", d, 0x18)[0]
        opd = read_va(d, segs, entry, 8)
        if opd is None or len(opd) < 8:
            raise ValueError(f"entry descriptor {entry:#x} is not mapped by any segment")
        code, toc = struct.unpack(">II", opd)  # PS3 OPD: 32-bit pair
    except (struct.error, ValueError) as e:
        print(f"{path} is not a usable PS3 ELF: {e}")
        return 2
    ok = True

    def row(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name:<10} got={got:#x} want={want:#x}")

    print(f"file   : {path}")
    print(f"sha256 : {hashlib.sha256(d).hexdigest()}")
    row("size", len(d), EXPECT["size"])
    row("entryOPD", entry, EXPECT["entry_opd"])
    row("entryCode", code, EXPECT["entry_code"])
    row("toc", toc, EXPECT["toc"])

    md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
    for va, want, why in ANCHORS:
        raw = read_va(d, segs, va, 4)
        got = next(md.disasm(raw, va), None) if raw else None
        mn = got.mnemonic if got else "?"
        good = mn in want
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {va:#010x} {mn:<6} (want {'/'.join(want)})  {why}")

    print("RESULT:", "sampled layout checks match the US build (relift + build still needed to confirm)" if ok else "MISMATCH - do not reuse US address lists")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
