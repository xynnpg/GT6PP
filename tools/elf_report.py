#!/usr/bin/env python3
"""Report on a PS3 PPU ELF: sections, segments, dynamic imports, strings.

Usage: python tools/elf_report.py work/bin/EMAIN.elf [--strings 200] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from collections import Counter
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSection
from elftools.elf.sections import SymbolTableSection

PS3_LIB_RE = re.compile(r"^(cell|sys|gcm|sce|_sys|lib|rt|stdc|pthread|libc|fs|usbd|audio|video|net|http|ssl|crypto|sysutil|sysmodule|sysfs|sysmem|systhread|syssync|sysevent|systimer|sysinterrupt|sysprocess|sysspu|sysrsx|syspad|sysusb|sysnet|syssave|systrophy|sysgame|syspower|syssm|sysboot|sysmgr|sysparam|sysregistry|sysutil|sysio|syslv2|sysprx|sysdbg|sysvm|sysmmapper|sysmpu|sysfs)")


def iter_dynsym(elf: ELFFile):
    for sec in elf.iter_sections():
        if isinstance(sec, SymbolTableSection) and sec["sh_type"] in ("SHT_DYNSYM", "SHT_SYMTAB"):
            for sym in sec.iter_symbols():
                yield sec.name, sym


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--strings", type=int, default=80)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    f = args.file.open("rb")
    elf = ELFFile(f)
    h = elf.header
    print(f"file: {args.file}")
    print(f"  type={h['e_type']} machine={h['e_machine']} entry=0x{h['e_entry']:x} flags=0x{h['e_flags']:x}")
    print(f"  sections={elf.num_sections()} segments={elf.num_segments()}")

    print("\nSections:")
    for i, sec in enumerate(elf.iter_sections()):
        print(
            f"  [{i:2d}] {sec.name or '<anon>':<12} type={sec['sh_type']:<14} "
            f"addr=0x{sec['sh_addr']:08x} off=0x{sec['sh_offset']:08x} "
            f"size=0x{sec['sh_size']:08x} entsize=0x{sec['sh_entsize']:x}"
        )

    print("\nSegments:")
    for i, seg in enumerate(elf.iter_segments()):
        print(
            f"  [{i}] {seg['p_type']:<14} vaddr=0x{seg['p_vaddr']:08x} off=0x{seg['p_offset']:08x} "
            f"filesz=0x{seg['p_filesz']:08x} memsz=0x{seg['p_memsz']:08x} flags=0x{seg['p_flags']:x}"
        )

    print("\nDynamic:")
    needed = []
    dyn_tags = {}
    for sec in elf.iter_sections():
        if isinstance(sec, DynamicSection):
            for tag in sec.iter_tags():
                dyn_tags[tag.entry.d_tag] = tag.entry.d_val
                if tag.entry.d_tag == "DT_NEEDED":
                    needed.append(tag.needed)
                print(f"  {tag.entry.d_tag:<22} {tag.entry.d_val:#x}" + (f"  ({tag.needed})" if tag.entry.d_tag == "DT_NEEDED" else ""))
    if not dyn_tags:
        print("  (no dynamic section)")

    syms = []
    for sec_name, sym in iter_dynsym(elf):
        name = sym.name
        if not name:
            continue
        syms.append(
            {
                "table": sec_name,
                "name": name,
                "value": sym["st_value"],
                "size": sym["st_size"],
                "bind": sym["st_info"]["bind"],
                "type": sym["st_info"]["type"],
                "shndx": sym["st_shndx"],
            }
        )
    print(f"\nSymbols: {len(syms)}")
    for s in syms[:120]:
        print(f"  0x{s['value']:08x} {s['type']:<10} {s['bind']:<8} {s['name']}")

    # Collect printable strings from all PROGBITS sections, with address.
    all_strings = []
    for sec in elf.iter_sections():
        if sec["sh_type"] != "SHT_PROGBITS" or sec["sh_size"] == 0:
            continue
        data = sec.data()
        base = sec["sh_addr"]
        for m in re.finditer(rb"[\x20-\x7e]{5,}", data):
            all_strings.append((base + m.start(), m.group().decode("latin1")))
    print(f"\nPrintable strings (>=5 chars): {len(all_strings)}")
    for addr, s in all_strings[: args.strings]:
        print(f"  0x{addr:08x}  {s[:160]}")

    libs = Counter()
    for _, s in all_strings:
        for m in re.finditer(r"(?:cell|sys|gcm|sce|_sys|lib)[A-Za-z0-9_]{3,}", s):
            libs[m.group(0)] += 1
    print("\nTop PS3-ish identifiers:")
    for name, count in libs.most_common(60):
        print(f"  {count:5d}  {name}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "file": str(args.file),
                    "entry": h["e_entry"],
                    "needed": needed,
                    "symbols": syms,
                    "strings": [{"addr": a, "text": s} for a, s in all_strings],
                },
                indent=2,
            )
        )
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
