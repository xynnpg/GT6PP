#!/usr/bin/env python3
"""Read-only preflight check for the K/WO PFS fix.

Verifies, without running gt6.exe:

  * the K/WO TOC row (path, FileIndex, SegIndex, ZSize, Size);
  * GT.VOL offset 0xAAE000 and the stored ciphertext head 39 7A D6 0E;
  * the extracted plaintext work/gt6_vol/products/gt6/script/MenuClassDefine.adc
    (12,464 bytes, SHA-256 c4144c97...f3db9f8d);
  * the measured cache state: WO.fdupi is 0 bytes and WO.fdupm has no valid
    source block (blocks=0, bitmap empty).  The header may be all zero (the
    14:43 baseline) or carry stored_size=0xE24 (the 15:16 live run);
  * the generated key map contains K/WO -> that virtual path (if present).

Usage:
    python tools/patches/gt6_pfs_check_wo.py
    python tools/patches/gt6_pfs_check_wo.py --vol "PS3-Version/.../GT.VOL"
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

DATA_OFFSET = 0x7E800
SEG_STRIDE = 0x800
WO_KEY = "K/WO"
WO_PATH = "products/gt6/script/MenuClassDefine.adc"
WO_SEG = 5215
WO_ZSIZE = 0xE24
WO_SIZE = 0x30B0
WO_OFFSET = DATA_OFFSET + WO_SEG * SEG_STRIDE
WO_HEAD = bytes.fromhex("39 7a d6 0e")
WO_SHA256 = "c4144c974a32323acb65e379dfec0dae5383bfa8162a8d3f98538751f3db9f8d"

LINE_RE = re.compile(
    r"^(?P<path>.+?) - Flags: (?P<flags>Compressed|Uncompressed) "
    r"\| FileIndex: (?P<file_index>\d+) \((?P<key>[^)]+)\) "
    r"\| SegIndex: (?P<seg_index>\d+), ZSize: (?P<zsize>[0-9A-Fa-f]+) "
    r"\| Size: (?P<size>[0-9A-Fa-f]+)"
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entries", default="work/gt6_volume_entries.txt")
    ap.add_argument("--vol", default="gt6/GT.VOL")
    ap.add_argument("--root", default="work/gt6_vol")
    ap.add_argument("--hdd0", default="work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS/K")
    ap.add_argument("--keymap", default="work/gt6_pfs_keymap.tsv")
    args = ap.parse_args()

    entries = Path(args.entries)
    if not entries.exists():
        fail(f"missing {entries}")

    row = None
    for line in entries.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        if d["key"] == WO_KEY:
            row = d
            break
    if not row:
        fail(f"{WO_KEY} not found in {entries}")
    if row["path"] != WO_PATH:
        fail(f"{WO_KEY} path is {row['path']!r}, expected {WO_PATH!r}")
    if int(row["seg_index"]) != WO_SEG:
        fail(f"{WO_KEY} SegIndex is {row['seg_index']}, expected {WO_SEG}")
    if int(row["zsize"], 16) != WO_ZSIZE or int(row["size"], 16) != WO_SIZE:
        fail(f"{WO_KEY} sizes are ZSize={row['zsize']} Size={row['size']}, "
             f"expected {WO_ZSIZE:X}/{WO_SIZE:X}")
    print(f"PASS: TOC {WO_KEY} -> {WO_PATH} "
          f"(ZSize=0x{WO_ZSIZE:X}, Size=0x{WO_SIZE:X}, SegIndex={WO_SEG})")

    vol = Path(args.vol)
    if not vol.exists():
        fail(f"missing {vol}")
    with vol.open("rb") as f:
        f.seek(WO_OFFSET)
        head = f.read(16)
    if head[:4] != WO_HEAD:
        fail(f"GT.VOL at 0x{WO_OFFSET:X} starts {head[:4].hex(' ')}, "
             f"expected {WO_HEAD.hex(' ')}")
    print(f"PASS: GT.VOL 0x{WO_OFFSET:X} head {head[:16].hex(' ')}")

    extracted = Path(args.root) / WO_PATH
    if not extracted.exists():
        fail(f"missing extracted file {extracted}")
    data = extracted.read_bytes()
    if len(data) != WO_SIZE:
        fail(f"{extracted} is {len(data)} bytes, expected {WO_SIZE}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != WO_SHA256:
        fail(f"{extracted} SHA-256 is {digest}, expected {WO_SHA256}")
    if data[:8] != b"ADCH012\0":
        fail(f"{extracted} does not start with ADCH012\\0")
    print(f"PASS: extracted {extracted} is {len(data)} bytes, ADCH012, sha {digest[:16]}...")

    hdd0 = Path(args.hdd0)
    fdupi = hdd0 / "WO.fdupi"
    fdupm = hdd0 / "WO.fdupm"
    if fdupi.exists():
        n = fdupi.stat().st_size
        if n != 0:
            print(f"NOTE: {fdupi} is {n} bytes (expected 0 in the measured baseline)")
        else:
            print(f"PASS: {fdupi} is 0 bytes (measured baseline)")
    else:
        print(f"NOTE: {fdupi} missing (fresh cache state)")
    if fdupm.exists():
        b = fdupm.read_bytes()
        size, ident, blocks = (
            int.from_bytes(b[0:8], "big"),
            int.from_bytes(b[8:16], "big"),
            int.from_bytes(b[16:20], "big"),
        )
        bits = sum(x.bit_count() for x in b[20:])
        print(f"INFO: WO.fdupm {len(b)} bytes: size=0x{size:X} id={ident} "
              f"blocks={blocks} bitmap_bits={bits}")
        if size not in (0, WO_ZSIZE):
            print(f"WARNING: stored_size=0x{size:X}, expected 0 or 0x{WO_ZSIZE:X}")
        if blocks == 0 and bits == 0:
            print("PASS: WO.fdupm has no valid source block "
                  "(expected while the guest read-through is broken)")
        else:
            print(f"NOTE: WO.fdupm now has {blocks} block(s)/{bits} bit(s); "
                  "the guest cache may have started populating")
    else:
        print(f"NOTE: {fdupm} missing (fresh cache state)")

    keymap = Path(args.keymap)
    if keymap.exists():
        found = False
        for line in keymap.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 2 and fields[0] == WO_KEY and fields[1] == WO_PATH:
                found = True
                break
        if not found:
            fail(f"{keymap} has no {WO_KEY} -> {WO_PATH} row")
        print(f"PASS: {keymap} maps {WO_KEY} -> {WO_PATH}")
    else:
        print(f"NOTE: {keymap} missing; run tools/patches/gt6_pfs_make_keymap.py")

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
