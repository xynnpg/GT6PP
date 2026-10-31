#!/usr/bin/env python3
"""Minimal ADCH v9-v12 disassembler for GT6 script triage.

Reads the ADCH symbol table and recursively decodes code frames using the
instruction encodings documented by GTAdhocToolchain (MIT):
  GTAdhocToolchain.Core/AdhocCodeFrame.cs
  GTAdhocToolchain.Core/Instructions/**/*.cs

This is intentionally small: it is enough to see which strings a script
pushes and whether it calls REQUIRE / loadPrototype, and to dump the top level
frame without needing the external toolchain. It is not a source decompiler.

Usage:
  python tools/adch_disasm.py FILE [--top] [--max-ins N] [--find SYMBOL]
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# AdhocInstructionType (v12)
OPNAMES = """
ARRAY_CONST_OLD ASSIGN_OLD ATTRIBUTE_DEFINE ATTRIBUTE_PUSH BINARY_ASSIGN_OPERATOR
BINARY_OPERATOR CALL CLASS_DEFINE EVAL FLOAT_CONST FUNCTION_DEFINE IMPORT
INT_CONST JUMP JUMP_IF_TRUE JUMP_IF_FALSE LIST_ASSIGN_OLD LOCAL_DEFINE
LOGICAL_AND_OLD LOGICAL_OR_OLD METHOD_DEFINE MODULE_DEFINE NIL_CONST NOP
POP_OLD PRINT REQUIRE SET_STATE_OLD STATIC_DEFINE STRING_CONST STRING_PUSH
THROW TRY_CATCH UNARY_ASSIGN_OPERATOR UNARY_OPERATOR UNDEF VARIABLE_PUSH
ATTRIBUTE_EVAL VARIABLE_EVAL SOURCE_FILE FUNCTION_CONST METHOD_CONST
MAP_CONST_OLD LONG_CONST ASSIGN LIST_ASSIGN CALL_OLD OBJECT_SELECTOR
SYMBOL_CONST LEAVE ARRAY_CONST ARRAY_PUSH MAP_CONST MAP_INSERT POP
SET_STATE VOID_CONST ASSIGN_POP U_INT_CONST U_LONG_CONST DOUBLE_CONST
ELEMENT_PUSH ELEMENT_EVAL LOGICAL_AND LOGICAL_OR BOOL_CONST MODULE_CONSTRUCTOR
VA_CALL CODE_EVAL DELEGATE_DEFINE JUMP_IF_NIL LOGICAL_OPTIONAL
""".split()
OP = {i: n for i, n in enumerate(OPNAMES)}

# instruction data kinds
SYMBOL = {"ATTRIBUTE_DEFINE", "BINARY_ASSIGN_OPERATOR", "BINARY_OPERATOR",
          "SOURCE_FILE", "STRING_CONST", "SYMBOL_CONST", "STATIC_DEFINE",
          "UNARY_ASSIGN_OPERATOR", "UNARY_OPERATOR"}
SYMBOLS = {"ATTRIBUTE_PUSH", "ATTRIBUTE_EVAL", "UNDEF", "MODULE_DEFINE"}
SYMBOLS_INT = {"VARIABLE_PUSH", "VARIABLE_EVAL"}
INT32 = {"CALL", "INT_CONST", "JUMP", "JUMP_IF_TRUE", "JUMP_IF_FALSE",
         "LOGICAL_AND_OLD", "LOGICAL_OR_OLD", "TRY_CATCH", "STRING_PUSH",
         "LIST_ASSIGN_OLD", "ARRAY_CONST_OLD", "MAP_CONST_OLD", "PRINT",
         "VA_CALL", "LOGICAL_AND", "LOGICAL_OR"}
UINT32 = {"U_INT_CONST", "ARRAY_CONST"}
INT64 = {"LONG_CONST"}
UINT64 = {"U_LONG_CONST"}
F32 = {"FLOAT_CONST"}
F64 = {"DOUBLE_CONST"}
BYTE = {"SET_STATE", "SET_STATE_OLD", "BOOL_CONST"}
LEAVE = {"LEAVE"}
CLASS = {"CLASS_DEFINE"}
IMPORT = {"IMPORT"}
FRAME = {"FUNCTION_DEFINE", "METHOD_DEFINE", "FUNCTION_CONST", "METHOD_CONST"}
LIST_ASSIGN = {"LIST_ASSIGN"}


class Reader:
    def __init__(self, data: bytes, symbols: list[bytes]):
        self.d = data
        self.p = 0
        self.symbols = symbols

    def u8(self):
        b = self.d[self.p]
        self.p += 1
        return b

    def i8(self):
        v = self.u8()
        return v - 256 if v > 127 else v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.p)[0]
        self.p += 8
        return v

    def i64(self):
        v = struct.unpack_from("<q", self.d, self.p)[0]
        self.p += 8
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def f64(self):
        v = struct.unpack_from("<d", self.d, self.p)[0]
        self.p += 8
        return v

    def varint(self):
        value = self.u8()
        mask = 0x80
        while value & mask:
            value = ((value - mask) << 8) | self.u8()
            mask <<= 7
        return value

    def symbol(self):
        idx = self.varint()
        if idx >= len(self.symbols):
            raise ValueError(f"symbol {idx} out of range at 0x{self.p:X}")
        return self.symbols[idx]

    def symbols_list(self):
        n = self.u32()
        if n > 0x10000:
            raise ValueError(f"symbols list too long ({n}) at 0x{self.p:X}")
        return [self.symbol() for _ in range(n)]


def fmt_sym(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin1")


def read_frame(r: Reader, depth: int, max_ins: int, out: list[str], label: str):
    has_debug = r.u8()
    frame_version = r.u8()
    source = r.symbol() if has_debug else b"<none>"
    has_rest = r.u8() if frame_version >= 12 else 0
    nparams = r.u32()
    params = []
    for _ in range(nparams):
        params.append(fmt_sym(r.symbol()))
        if frame_version >= 8:
            r.u32()
    ncapt = r.u32()
    for _ in range(ncapt):
        r.symbol()
        r.i32()
    r.u32()  # unknown stack index
    stack = r.i32()
    local = r.i32()
    static = r.i32() if frame_version >= 12 else 0
    icount = r.u32()
    ind = "  " * depth
    out.append(f"{ind}== {label}: source={fmt_sym(source)!r} stack={stack} "
               f"local={local} static={static} ins={icount} params={params} rest={has_rest}")

    limit = icount if max_ins <= 0 else min(icount, max_ins)
    for i in range(limit):
        ins_start = r.p
        try:
            line = r.u32() if has_debug else 0
            op = r.u8()
            name = OP.get(op, f"OP_{op}")
            at = r.p - 1
            args = ""
            if name in SYMBOL:
                args = fmt_sym(r.symbol())
            elif name in SYMBOLS:
                args = ", ".join(fmt_sym(s) for s in r.symbols_list())
            elif name in SYMBOLS_INT:
                args = ", ".join(fmt_sym(s) for s in r.symbols_list()) + f", idx={r.i32()}"
            elif name in INT32:
                args = str(r.i32())
            elif name in UINT32:
                args = str(r.u32())
            elif name in INT64:
                args = str(r.i64())
            elif name in UINT64:
                args = str(r.u64())
            elif name in F32:
                args = repr(r.f32())
            elif name in F64:
                args = repr(r.f64())
            elif name in BYTE:
                args = str(r.u8())
            elif name in LEAVE:
                args = f"depth={r.i32()}, rewind={r.i32()}"
            elif name in CLASS:
                nm = fmt_sym(r.symbol())
                ext = ", ".join(fmt_sym(s) for s in r.symbols_list())
                args = f"{nm} extends {ext}"
            elif name in IMPORT:
                path = [fmt_sym(s) for s in r.symbols_list()]
                val = fmt_sym(r.symbol())
                alias = fmt_sym(r.symbol())
                args = f"path={path}, value={val}, as={alias}"
            elif name in LIST_ASSIGN:
                n = r.i32()
                rest = r.u8() if frame_version >= 12 else 0
                args = f"count={n}, rest={rest}"
            elif name in FRAME:
                sub_label = "FUNCTION_CONST" if name == "FUNCTION_CONST" else (
                    "METHOD_CONST" if name == "METHOD_CONST" else "FUNCTION/METHOD")
                out.append(f"{ind}  {at:05X}|{line:4d}|{i:4d}| {name} {sub_label}")
                read_frame(r, depth + 1, max_ins, out, sub_label)
                continue
            out.append(f"{ind}  {at:05X}|{line:4d}|{i:4d}| {name} {args}".rstrip())
        except Exception as e:
            out.append(f"{ind}  !! decode error at ins {i} file=0x{ins_start:X}: {e}")
            return
    if limit < icount:
        out.append(f"{ind}  ... {icount - limit} more instructions")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--max-ins", type=int, default=0,
                    help="limit instructions per frame (0 = all)")
    ap.add_argument("--find", default=None,
                    help="only print lines containing this substring")
    args = ap.parse_args(argv[1:])

    data = Path(args.file).read_bytes()
    if data[:4] != b"ADCH":
        print("not an ADCH file", file=sys.stderr)
        return 1
    version = int(data[4:7])
    r = Reader(data, [])
    r.p = 8
    nsym = r.varint()
    for _ in range(nsym):
        n = r.varint()
        r.symbols.append(r.d[r.p:r.p + n])
        r.p += n
    out: list[str] = [f"# {args.file} version={version} symbols={nsym} code=0x{r.p:X}"]
    read_frame(r, 0, args.max_ins, out, "TOP")
    if args.find:
        needle = args.find
        out = [ln for ln in out if needle in ln]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
