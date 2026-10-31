#!/usr/bin/env python3
"""Dump the ADCH v12 read trace and code-frame header of a .adc file.

This mirrors the GTAdhocToolchain v12 reader (MIT, Nenkai):
  magic "ADCH" + 3-digit version
  Symbol Count   VarInt
  Symbols        [VarInt length][bytes] *
  CodeFrame      bool has_debug, u8 frame_version, Symbol source_path,
                 bool has_rest, u32 params..., u32 captured...,
                 u32 unknown, u32 stack, u32 locals, u32 statics,
                 u32 instruction_count, instructions...

The point of the trace is to compare the guest's HFileReader::read sequence
with the on-disk structure.  VarInt bytes are read one at a time and strings
are read in one call, exactly like the guest's HFileReader::read wrapper.

Usage:
  python tools/adch_read_trace.py work/gt6_vol/scripts/gt6/main.adc
  python tools/adch_read_trace.py FILE --reads 40 --symbols 20
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.calls: list[tuple[int, int]] = []   # (offset, length)

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError(f"read {n} at 0x{self.pos:X} past EOF")
        out = self.data[self.pos:self.pos + n]
        self.calls.append((self.pos, n))
        self.pos += n
        return out

    def u8(self) -> int:
        return self.read(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def varint(self) -> int:
        # The trace wants the individual bytes: call read(1) per byte.
        value = self.u8()
        mask = 0x80
        while value & mask:
            value = ((value - mask) << 8) | self.u8()
            mask <<= 7
        return value

    def symbol(self, symbols: list[bytes]) -> bytes:
        idx = self.varint()
        if idx >= len(symbols):
            raise ValueError(f"symbol index {idx} >= {len(symbols)} at 0x{self.pos:X}")
        return symbols[idx]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--reads", type=int, default=40,
                    help="number of HFileReader::read calls to print")
    ap.add_argument("--symbols", type=int, default=20,
                    help="number of symbol-table entries to print")
    args = ap.parse_args(argv[1:])

    data = Path(args.file).read_bytes()
    r = Reader(data)

    magic = r.read(8)
    if magic[:4] != b"ADCH":
        print(f"not ADCH: {magic[:8]!r}", file=sys.stderr)
        return 1
    version = int(magic[4:7])
    print(f"file        : {args.file}")
    print(f"size        : {len(data)} (0x{len(data):X})")
    print(f"magic       : {magic!r} version={version}")

    count = r.varint()
    print(f"symbol count: {count} (VarInt ends at 0x{r.pos:X})")
    symbols: list[bytes] = []
    starts: list[int] = []
    for _ in range(count):
        starts.append(r.pos)
        n = r.varint()
        symbols.append(r.read(n))
    print(f"symbols end : 0x{r.pos:X}")
    for i in range(min(args.symbols, len(symbols))):
        print(f"  [{i:4d}] @0x{starts[i]:05X} len={len(symbols[i]):3d} {symbols[i][:60]!r}")

    print(f"code frame  : 0x{r.pos:X}")
    has_debug = r.u8()
    frame_version = r.u8()
    source = r.symbol(symbols) if has_debug else b"<none>"
    has_rest = r.u8() if version >= 12 else 0
    param_count = r.u32()
    params = []
    for _ in range(param_count):
        sym = r.symbol(symbols)
        params.append((sym, r.u32()) if version >= 8 else (sym, 0))
    captured_count = r.u32()
    captured = []
    for _ in range(captured_count):
        sym = r.symbol(symbols)
        captured.append((sym, r.u32()))
    unknown = r.u32() if version >= 8 else 0
    stack = r.u32()
    local = r.u32()
    static = r.u32() if version >= 12 else 0
    icount = r.u32()

    print(f"  has_debug={has_debug} frame_version={frame_version} "
          f"source={source!r} has_rest={has_rest}")
    print(f"  params={len(params)} captured={len(captured)} unknown={unknown}")
    print(f"  stack={stack} local={local} static={static} "
          f"instruction_count={icount}")
    print(f"  first instruction at 0x{r.pos:X}")
    print(f"  read calls through code-frame header: {len(r.calls)}")
    # Decode only the handful of opcodes needed to show the frame starts on a
    # real instruction boundary.  Full instruction decoding is the toolchain's
    # job; the read trace above is the part this script is about.
    for i in range(8):
        if r.pos + 5 > len(data):
            break
        at = r.pos
        line = r.u32()
        op = r.u8()
        if op == 39:                         # SOURCE_FILE
            sym = r.symbol(symbols)
            print(f"    ins[{i:2d}] @0x{at:05X} line={line:4d} "
                  f"opcode=0x{op:02X} SOURCE_FILE {sym!r}")
        elif op == 23:                       # NOP
            print(f"    ins[{i:2d}] @0x{at:05X} line={line:4d} "
                  f"opcode=0x{op:02X} NOP")
        elif op == 12:                       # INT_CONST
            value = struct.unpack("<i", r.read(4))[0]
            print(f"    ins[{i:2d}] @0x{at:05X} line={line:4d} "
                  f"opcode=0x{op:02X} INT_CONST {value}")
        else:
            print(f"    ins[{i:2d}] @0x{at:05X} line={line:4d} "
                  f"opcode=0x{op:02X} (operand not decoded; stop)")
            break

    print(f"\nHFileReader::read trace (first {args.reads} calls):")
    for i, (off, n) in enumerate(r.calls[:args.reads]):
        print(f"  {i:3d}: offset={off:6d} (0x{off:05X}) len={n}")
    print(f"  total calls={len(r.calls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
