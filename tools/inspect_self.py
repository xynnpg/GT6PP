#!/usr/bin/env python3
"""Read-only SCE SELF / embedded ELF inspector for PS3 binaries.

Usage: python tools/inspect_self.py <file> [--dump-elf out.elf]
"""
from __future__ import annotations

import argparse
import math
import struct
from collections import Counter
from pathlib import Path

SELF_MAGIC = b"SCE\x00"
ELF_MAGIC = b"\x7fELF"

PT_NAMES = {
    0: "PT_NULL",
    1: "PT_LOAD",
    2: "PT_DYNAMIC",
    3: "PT_INTERP",
    4: "PT_NOTE",
    6: "PT_PHDR",
    7: "PT_TLS",
    0x60000000: "PT_PS3_PRX",
    0x60000001: "PT_PS3_PRX_RELOC",
    0x70000000: "PT_PS3_EXPORT",
    0x70000001: "PT_PS3_IMPORT",
    0x70000002: "PT_PS3_PPU",
    0x70000003: "PT_PS3_SPU",
    0x70000004: "PT_PS3_PROC_PARAM",
}


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def parse_self_header(data: bytes) -> dict:
    if data[:4] != SELF_MAGIC:
        raise SystemExit("not a SCE SELF file")
    magic, version, sdk_type, header_type, metadata_offset, header_len, data_len = struct.unpack_from(
        ">IIHHIIQ", data, 0
    )
    return {
        "magic": magic,
        "version": version,
        "sdk_type": sdk_type,
        "header_type": header_type,
        "metadata_offset": metadata_offset,
        "header_len": header_len,
        "data_len": data_len,
    }


def parse_elf(data: bytes, off: int) -> dict:
    ident = data[off : off + 16]
    if ident[:4] != ELF_MAGIC:
        raise SystemExit(f"no ELF at 0x{off:x}")
    ei_class, ei_data, ei_version, ei_osabi = ident[4], ident[5], ident[6], ident[7]
    if ei_class != 2 or ei_data != 2:
        raise SystemExit(f"expected ELF64 big-endian, got class={ei_class} data={ei_data}")
    (
        e_type,
        e_machine,
        e_version,
        e_entry,
        e_phoff,
        e_shoff,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = struct.unpack_from(">HHIQQQIHHHHHH", data, off + 16)
    return {
        "off": off,
        "e_type": e_type,
        "e_machine": e_machine,
        "e_version": e_version,
        "e_entry": e_entry,
        "e_phoff": e_phoff,
        "e_shoff": e_shoff,
        "e_flags": e_flags,
        "e_ehsize": e_ehsize,
        "e_phentsize": e_phentsize,
        "e_phnum": e_phnum,
        "e_shentsize": e_shentsize,
        "e_shnum": e_shnum,
        "e_shstrndx": e_shstrndx,
    }


def parse_phdrs(data: bytes, elf: dict) -> list[dict]:
    phdrs = []
    base = elf["off"] + elf["e_phoff"]
    for i in range(elf["e_phnum"]):
        p_off = base + i * elf["e_phentsize"]
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            ">IIQQQQQQ", data, p_off
        )
        phdrs.append(
            {
                "i": i,
                "type": p_type,
                "type_name": PT_NAMES.get(p_type, f"0x{p_type:08x}"),
                "flags": p_flags,
                "offset": p_offset,
                "vaddr": p_vaddr,
                "paddr": p_paddr,
                "filesz": p_filesz,
                "memsz": p_memsz,
                "align": p_align,
            }
        )
    return phdrs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--dump-elf", type=Path)
    args = ap.parse_args()
    data = args.file.read_bytes()

    print(f"file: {args.file}")
    print(f"size: {len(data):,} bytes (0x{len(data):x})")
    self_hdr = parse_self_header(data)
    for k, v in self_hdr.items():
        print(f"  SELF {k:18s} = 0x{v:x}" if isinstance(v, int) else f"  SELF {k} = {v}")

    elf_off = data.find(ELF_MAGIC)
    if elf_off < 0:
        raise SystemExit("no embedded ELF magic found")
    print(f"  ELF magic at        = 0x{elf_off:x}")
    elf = parse_elf(data, elf_off)
    for k, v in elf.items():
        print(f"  ELF  {k:18s} = 0x{v:x}" if isinstance(v, int) else f"  ELF  {k} = {v}")

    print("\nProgram headers:")
    phdrs = parse_phdrs(data, elf)
    for p in phdrs:
        # SELF program header offsets are usually relative to the ELF start.
        abs_off = elf_off + p["offset"]
        chunk = data[abs_off : abs_off + min(p["filesz"], 1 << 20)]
        ent = entropy(chunk) if chunk else 0.0
        print(
            f"  [{p['i']}] {p['type_name']:<18} off=0x{p['offset']:08x} abs=0x{abs_off:08x} "
            f"vaddr=0x{p['vaddr']:016x} filesz=0x{p['filesz']:x} memsz=0x{p['memsz']:x} "
            f"flags=0x{p['flags']:x} align=0x{p['align']:x} entropy={ent:.3f}"
        )

    # Show a few words at each PT_LOAD's virtual entry to see if it looks like PPC code.
    print("\nFirst bytes at each load segment:")
    for p in phdrs:
        if p["type"] != 1 or p["filesz"] == 0:
            continue
        abs_off = elf_off + p["offset"]
        chunk = data[abs_off : abs_off + 32]
        print(f"  vaddr 0x{p['vaddr']:x}: {chunk.hex(' ')}")

    if args.dump_elf:
        # The embedded ELF is not a standalone file: segment file offsets are
        # relative to the ELF start, so shift them by elf_off when dumping.
        out = bytearray(data[elf_off:])
        # Rebuild a standalone ELF by copying segments to their file offsets.
        # For analysis only; this does not decrypt anything.
        max_end = elf["e_phoff"] + elf["e_phnum"] * elf["e_phentsize"]
        for p in phdrs:
            max_end = max(max_end, p["offset"] + p["filesz"])
        out = bytearray(max(max_end, len(data) - elf_off))
        out[: len(data) - elf_off] = data[elf_off:]
        args.dump_elf.write_bytes(out)
        print(f"\nWrote raw embedded ELF view to {args.dump_elf} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
