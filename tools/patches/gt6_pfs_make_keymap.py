#!/usr/bin/env python3
"""Build the GT6 PFS FileIndex -> virtual-path map used by the host override.

Input is the TOC listing produced by GTToolsSharp (work/gt6_volume_entries.txt):

    products/gt6/script/MenuClassDefine.adc - Flags: Compressed |
      FileIndex: 34 (K/WO) | SegIndex: 5215, ZSize: 00000E24 |
      Size: 000030B0 | VolIndex: 4294967295

The PDIPFS cache names a file by the parenthesised FileIndex string (K/WO);
the virtual path is the text before " - Flags:".  The volume data offset is

    data_offset = 0x7E800 + SegIndex * 0x800

(0x800 volume header + 0x7D984 compressed TOC, aligned up to 0x800).

Output is a tab-separated file consumed by gt6/src/stubs.cpp:

    #key  path  flags  file_index  seg_index  zsize  size  offset

Nothing here derives from third_party/PDTools; the input is GT6 data and the
project's own GTToolsSharp listing.

Usage:
    python tools/patches/gt6_pfs_make_keymap.py
    python tools/patches/gt6_pfs_make_keymap.py --entries work/gt6_volume_entries.txt \
        --out work/gt6_pfs_keymap.tsv --verify
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

DATA_OFFSET = 0x7E800
SEG_STRIDE = 0x800

# One line in the listing is truncated (the last line); skip it.
LINE_RE = re.compile(
    r"^(?P<path>.+?) - Flags: (?P<flags>Compressed|Uncompressed) "
    r"\| FileIndex: (?P<file_index>\d+) \((?P<key>[^)]+)\) "
    r"\| SegIndex: (?P<seg_index>\d+), ZSize: (?P<zsize>[0-9A-Fa-f]+) "
    r"\| Size: (?P<size>[0-9A-Fa-f]+)"
)


def parse_entries(path: Path):
    rows = []
    bad = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if not m:
            bad += 1
            continue
        d = m.groupdict()
        seg = int(d["seg_index"])
        rows.append(
            (
                d["key"],
                d["path"],
                d["flags"],
                int(d["file_index"]),
                seg,
                int(d["zsize"], 16),
                int(d["size"], 16),
                DATA_OFFSET + seg * SEG_STRIDE,
            )
        )
    return rows, bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entries", default="work/gt6_volume_entries.txt")
    ap.add_argument("--out", default="work/gt6_pfs_keymap.tsv")
    ap.add_argument("--vol", default="gt6/GT.VOL",
                    help="optional GT.VOL used by --verify")
    ap.add_argument("--verify", action="store_true",
                    help="check the K/WO slice against GT.VOL")
    args = ap.parse_args()

    entries = Path(args.entries)
    if not entries.exists():
        print(f"missing {entries}; run GTToolsSharp listfiles first", file=sys.stderr)
        return 1

    rows, bad = parse_entries(entries)
    if not rows:
        print(f"no entries parsed from {entries}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#key\tpath\tflags\tfile_index\tseg_index\tzsize\tsize\toffset\n")
        for key, path, flags, fi, seg, zs, sz, off in rows:
            f.write(f"{key}\t{path}\t{flags}\t{fi}\t{seg}\t{zs:X}\t{sz:X}\t{off:X}\n")

    keys = Counter(r[0] for r in rows)
    dup = [k for k, n in keys.items() if n > 1]
    print(f"wrote {out}: {len(rows)} entries, {len(keys)} unique keys, "
          f"{len(dup)} duplicate keys, {bad} unparsed line(s)")
    if dup:
        print(f"  first duplicate keys: {', '.join(dup[:8])}")

    wo = [r for r in rows if r[0] == "K/WO"]
    if not wo:
        print("K/WO not present in the listing", file=sys.stderr)
        return 1
    for key, path, flags, fi, seg, zs, sz, off in wo:
        print(f"  K/WO -> {path} [{flags}] FileIndex={fi} SegIndex={seg} "
              f"ZSize=0x{zs:X} Size=0x{sz:X} offset=0x{off:X}")
        if args.verify:
            vol = Path(args.vol)
            if not vol.exists():
                print(f"  cannot verify: {vol} missing", file=sys.stderr)
                continue
            with vol.open("rb") as vf:
                vf.seek(off)
                head = vf.read(16)
            print(f"  GT.VOL head: {head.hex(' ')}")
            if head[:4] == bytes.fromhex("39 7a d6 0e"):
                print("  verified: K/WO ciphertext magic 0x397AD60E at that offset")
            else:
                print("  WARNING: K/WO magic is not 0x397AD60E", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
