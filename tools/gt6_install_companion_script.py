#!/usr/bin/env python3
"""Validate and install a real GT6 companion ADCH script.

The v1.00 US disc ships `products/gt6/script/Prototypes.mwidget` (MPRJ) but
not its compiled companion `Prototypes.adc`.  The engine only *reads* ADCH;
there is no MPRJ->ADCH compiler in EMAIN, so this file must come from an
official update/patch volume.  This tool refuses to invent data: it accepts
only a genuine ADCH v12 file whose debug source path names the Prototypes
source, then copies it into the extracted tree used by the PFS override.

Usage:
  # show whether the tree already contains a valid Prototypes.adc
  python tools/gt6_install_companion_script.py --scan work/gt6_vol

  # validate one file from an official update, do not copy
  python tools/gt6_install_companion_script.py --source path/to/Prototypes.adc --dry-run

  # install it where gt6/src/stubs.cpp looks for extracted files
  python tools/gt6_install_companion_script.py --source path/to/Prototypes.adc

The destination defaults to work/gt6_vol/products/gt6/script/Prototypes.adc.
`--source` may be a directory; the tool recurses through *.adc and selects the
single valid file whose source symbol is Prototypes.ad.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import shutil
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"ADCH012\x00"
ACCEPTED_SOURCES = {"prototypes.ad", "_tmp_prototypes.ad"}
DEFAULT_DEST = Path("work/gt6_vol/products/gt6/script/Prototypes.adc")


class InvalidAdch(Exception):
    pass


@dataclass
class AdchInfo:
    path: Path
    size: int
    sha256: str
    version: int
    symbols: int
    source: str
    instructions: int
    stack: int
    locals: int
    statics: int


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def need(self, n: int):
        if n < 0 or self.p + n > len(self.d):
            raise InvalidAdch(f"truncated at 0x{self.p:X} (need {n})")

    def u8(self) -> int:
        self.need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def varint(self) -> int:
        value = self.u8()
        mask = 0x80
        while value & mask:
            value = ((value - mask) << 8) | self.u8()
            mask <<= 7
            if mask > 0x80000000:
                raise InvalidAdch("VarInt overflow")
        return value

    def symbol(self, symbols: list[bytes]) -> bytes:
        idx = self.varint()
        if idx >= len(symbols):
            raise InvalidAdch(f"symbol {idx} out of range at 0x{self.p:X}")
        return symbols[idx]


def _name(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin1")


def inspect_adch(path: Path) -> AdchInfo:
    data = path.read_bytes()
    if len(data) < 32:
        raise InvalidAdch("too small")
    if data[:4] == b"MPRJ":
        raise InvalidAdch("MPRJ project, not ADCH")
    if data[:8] != MAGIC:
        raise InvalidAdch(f"bad magic {data[:8]!r}, expected {MAGIC!r}")
    version = int(data[4:7])
    if version != 12:
        raise InvalidAdch(f"ADCH version {version}, GT6 needs 12")

    r = Reader(data)
    r.p = 8
    nsym = r.varint()
    if nsym > 0x100000:
        raise InvalidAdch(f"implausible symbol count {nsym}")
    symbols: list[bytes] = []
    for _ in range(nsym):
        n = r.varint()
        if n > 0x100000:
            raise InvalidAdch(f"implausible symbol length {n}")
        r.need(n)
        symbols.append(data[r.p:r.p + n])
        r.p += n

    has_debug = r.u8()
    frame_version = r.u8()
    if frame_version != 12:
        raise InvalidAdch(f"code frame version {frame_version}, expected 12")
    source = _name(r.symbol(symbols)) if has_debug else ""
    if frame_version >= 12:
        r.u8()  # has_rest
    nparams = r.u32()
    if nparams > 0x10000:
        raise InvalidAdch(f"implausible parameter count {nparams}")
    for _ in range(nparams):
        r.symbol(symbols)
        r.u32()
    ncapt = r.u32()
    if ncapt > 0x10000:
        raise InvalidAdch(f"implausible captured count {ncapt}")
    for _ in range(ncapt):
        r.symbol(symbols)
        r.i32()
    r.u32()  # unknown stack index
    stack = r.i32()
    local = r.i32()
    static = r.i32()
    icount = r.u32()
    if icount == 0 or icount >= 0x40000000:
        raise InvalidAdch(f"implausible instruction count {icount}")
    if r.p >= len(data):
        raise InvalidAdch("no instruction bytes after frame header")

    return AdchInfo(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        version=version,
        symbols=nsym,
        source=source,
        instructions=icount,
        stack=stack,
        locals=local,
        statics=static,
    )


def source_matches(source: str) -> bool:
    base = posixpath.basename(source.replace("\\", "/")).lower()
    return base in ACCEPTED_SOURCES


def candidate_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*.adc")):
        if p.is_file():
            yield p


def find_valid(root: Path, require_source: bool) -> list[AdchInfo]:
    good: list[AdchInfo] = []
    errors: list[tuple[Path, str]] = []
    for p in candidate_files(root):
        try:
            info = inspect_adch(p)
        except Exception as e:
            errors.append((p, str(e)))
            continue
        if not require_source or source_matches(info.source):
            good.append(info)
    if not good and errors:
        for p, e in errors[:12]:
            print(f"  reject {p}: {e}", file=sys.stderr)
        if len(errors) > 12:
            print(f"  ... {len(errors) - 12} more rejects", file=sys.stderr)
    return good


def print_info(info: AdchInfo):
    print(f"  file        : {info.path}")
    print(f"  size        : {info.size} bytes")
    print(f"  sha256      : {info.sha256}")
    print(f"  adch        : v{info.version}, symbols={info.symbols}, "
          f"instructions={info.instructions}")
    print(f"  frame       : stack={info.stack} local={info.locals} static={info.statics}")
    print(f"  source      : {info.source!r}")


def install(info: AdchInfo, dest: Path, dry_run: bool):
    if dest.exists():
        old = inspect_adch(dest)
        print(f"destination already exists: {dest}")
        print_info(old)
        if old.sha256 == info.sha256:
            print("identical SHA-256; nothing to do.")
            return
        raise SystemExit("refusing to overwrite a different Prototypes.adc "
                         "(remove it or choose --dest)")
    print(f"source validated; installing to {dest}")
    if dry_run:
        print("dry-run: not copied.")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(dest.parent))
    os.close(fd)
    try:
        shutil.copyfile(info.path, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    check = inspect_adch(dest)
    if check.sha256 != info.sha256:
        raise SystemExit("copy verification failed")
    print(f"installed: {dest} (sha256 {check.sha256})")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=None,
                    help="official-update ADCH file or directory to search")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                    help=f"destination (default {DEFAULT_DEST})")
    ap.add_argument("--scan", type=Path, default=None,
                    help="scan an extracted tree for an existing valid file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    if args.scan:
        print(f"scanning {args.scan} for an ADCH v12 Prototypes script...")
        good = find_valid(args.scan, require_source=True)
        if not good:
            print("no valid Prototypes.adc found.")
            print("The v1.00 disc does not contain it; supply the official update.")
            return 2
        for info in good:
            print_info(info)
        return 0

    if not args.source:
        ap.error("pass --source <official update file/dir> or --scan <tree>")

    if not args.source.exists():
        raise SystemExit(f"source does not exist: {args.source}")

    print(f"searching {args.source} for ADCH v12 Prototypes...")
    good = find_valid(args.source, require_source=True)
    if not good:
        raise SystemExit(
            "no ADCH v12 file with source Prototypes.ad found. Refusing to "
            "fabricate one. Extract the official GT6 update and retry."
        )
    if len(good) > 1:
        print(f"multiple candidates ({len(good)}); choose one explicitly:", file=sys.stderr)
        for info in good:
            print_info(info)
        raise SystemExit(2)

    info = good[0]
    print("validated candidate:")
    print_info(info)
    install(info, args.dest, args.dry_run)
    print()
    print("verification:")
    print("  1. run gt6 with GT6_PFS_TRACE=1")
    print("  2. expect '[GT6] pfs override: serving plaintext "
          "products/gt6/script/Prototypes.adc ...'")
    print("  3. expect no '[GT6] pfs override: no extracted file for "
          "'products/gt6/script/Prototypes.adc''")
    print("  4. the 0x9CD410 ADCH reader must accept the file; the "
          "0x9E191C null-node spin must be re-tested independently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
