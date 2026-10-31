#!/usr/bin/env python3
"""Create/verify a GT6 PDIPFS cache pair from the raw GT.VOL entry.

The PDIPFS cache is a *raw source* cache, not a plaintext cache:

    <key>.fdupi   ZSize bytes copied verbatim from GT.VOL at SegIndex*0x800
    <key>.fdupm   20-byte header + 8192-byte bitmap
                  header = u64 ZSize, u64 id, u32 valid_block_count

The guest's read-side PFS file handle decrypts/inflates the stream after it has
been served; nothing in the cache layer does.  This tool therefore copies exactly
ZSize bytes and never decrypts, decompresses, or pads.  `Size` (the decompressed
logical length) is reported for the read-side check but is deliberately not used
as the cache file length.

Usage:
    # show what would be written (default: verify only)
    python tools/gt6_pfs_cache_warm.py --key K/W2

    # write the raw data + full block map
    python tools/gt6_pfs_cache_warm.py --key K/W2 --write

    # verify the pair after a run
    python tools/gt6_pfs_cache_warm.py --key K/W2 --check

Why write the full map?  The guest's 0xA40984 normally sets one bit per 8 KiB
source block it writes.  When a diagnostic plaintext override serves the reads
above the PDIPFS layer, that writer never runs.  Pre-seeding the raw data and
the map with the *same* raw bytes the writer would have copied is data-faithful
and lets the read path and the completion rename be validated independently.
It does not fabricate a single source byte.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

BLOCK_SIZE = 0x2000
BITMAP_SIZE = 0x2000
HEADER_SIZE = 0x14
MAX_BLOCKS = BITMAP_SIZE * 8


def parse_keymap(path: Path, key: str) -> dict:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            cols = line.rstrip("\r\n").split("\t")
            if len(cols) < 8 or cols[0] != key:
                continue
            return {
                "key": cols[0],
                "path": cols[1],
                "flags": cols[2],
                "file_index": int(cols[3], 0),
                "seg_index": int(cols[4], 0),
                "zsize": int(cols[5], 16),
                "size": int(cols[6], 16),
                "offset": int(cols[7], 16),
            }
    raise SystemExit(f"key {key!r} not found in {path}")


def read_vol_slice(vol: Path, offset: int, length: int) -> bytes:
    with vol.open("rb") as fh:
        fh.seek(offset)
        data = fh.read(length)
    if len(data) != length:
        raise SystemExit(
            f"short read from {vol} at 0x{offset:X}: got {len(data)}, want {length}"
        )
    return data


def build_map(zsize: int) -> tuple[bytes, int]:
    blocks = (zsize + BLOCK_SIZE - 1) // BLOCK_SIZE
    if blocks > MAX_BLOCKS:
        raise SystemExit(
            f"ZSize 0x{zsize:X} needs {blocks} blocks, map holds {MAX_BLOCKS}"
        )
    header = struct.pack(">QQI", zsize, 0, blocks)
    bitmap = bytearray(BITMAP_SIZE)
    for block in range(blocks):
        bitmap[block >> 3] |= 1 << (block & 7)
    return header + bitmap, blocks


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_map(data: bytes) -> tuple[int, int, int, bytes]:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"map is {len(data)} bytes, shorter than the header")
    zsize, ident, blocks = struct.unpack_from(">QQI", data, 0)
    return zsize, ident, blocks, data[HEADER_SIZE:]


def expected_bitmap(blocks: int) -> bytes:
    bitmap = bytearray(BITMAP_SIZE)
    for block in range(blocks):
        bitmap[block >> 3] |= 1 << (block & 7)
    return bytes(bitmap)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default="K/W2", help="PDIPFS cache key (default K/W2)")
    ap.add_argument("--keymap", default="work/gt6_pfs_keymap.tsv")
    ap.add_argument("--vol", default="gt6/GT.VOL")
    ap.add_argument("--cache-dir",
                    default="work/gt6_hdd0/game/BCUS98296/USRDIR/PDIPFS")
    ap.add_argument("--write", action="store_true",
                    help="write <key>.fdupi and <key>.fdupm")
    ap.add_argument("--check", action="store_true",
                    help="verify the existing pair and the raw GT.VOL slice")
    args = ap.parse_args(argv)

    entry = parse_keymap(Path(args.keymap), args.key)
    vol = Path(args.vol)
    cache_dir = Path(args.cache_dir)
    data_path = cache_dir / (args.key + ".fdupi")
    map_path = cache_dir / (args.key + ".fdupm")

    expected_data = read_vol_slice(vol, entry["offset"], entry["zsize"])
    expected_map, blocks = build_map(entry["zsize"])
    want_digest = sha256(expected_data)

    print(f"key         {entry['key']}  ({entry['flags']})")
    print(f"path        {entry['path']}")
    print(f"file_index  {entry['file_index']}   seg_index {entry['seg_index']}")
    print(f"vol offset  0x{entry['offset']:X}")
    print(f"ZSize       0x{entry['zsize']:X} ({entry['zsize']})  -> raw cache length")
    print(f"Size        0x{entry['size']:X} ({entry['size']})  -> read-side logical length")
    print(f"blocks      {blocks} (0x{BLOCK_SIZE:X} each)")
    print(f"raw sha256  {want_digest}")

    if args.write:
        write_atomic(data_path, expected_data)
        write_atomic(map_path, expected_map)
        print(f"wrote       {data_path} ({len(expected_data)} bytes)")
        print(f"wrote       {map_path} ({len(expected_map)} bytes)")

    if args.check or not args.write:
        failed = False
        # The guest renames <key>.fdupi to <key> once every block is present.
        # Accept either state; the bytes and length are the contract.
        completed_path = cache_dir / args.key
        actual_data_path = data_path
        if not data_path.exists() and completed_path.exists():
            actual_data_path = completed_path
            print(f"completed   {actual_data_path} (renamed from .fdupi)")
        if not actual_data_path.exists():
            print(f"MISSING     {data_path} (and no completed {completed_path})")
            failed = True
        else:
            got = actual_data_path.read_bytes()
            print(f"data        {actual_data_path} ({len(got)} bytes)")
            if len(got) != len(expected_data):
                print(f"FAIL        length {len(got)}, want {len(expected_data)}")
                failed = True
            elif got != expected_data:
                print("FAIL        data is not byte-identical to the GT.VOL slice")
                failed = True
            else:
                print("PASS        data is byte-identical to the GT.VOL slice")

        if not map_path.exists():
            print(f"MISSING     {map_path}")
            failed = True
        else:
            raw = map_path.read_bytes()
            print(f"map         {map_path} ({len(raw)} bytes)")
            try:
                zsize, ident, got_blocks, bitmap = parse_map(raw)
            except ValueError as exc:
                print(f"FAIL        {exc}")
                failed = True
            else:
                if zsize != entry["zsize"]:
                    print(f"FAIL        map ZSize 0x{zsize:X}, want 0x{entry['zsize']:X}")
                    failed = True
                if ident != 0:
                    print(f"FAIL        map id {ident}, want 0")
                    failed = True
                if got_blocks != blocks:
                    print(f"FAIL        map blocks {got_blocks}, want {blocks}")
                    failed = True
                if bitmap[:BITMAP_SIZE] != expected_bitmap(blocks):
                    print("FAIL        bitmap does not cover exactly the raw blocks")
                    failed = True
                if len(raw) < HEADER_SIZE + BITMAP_SIZE:
                    print(f"FAIL        map is {len(raw)} bytes, want at least "
                          f"{HEADER_SIZE + BITMAP_SIZE}")
                    failed = True
                if not failed:
                    print(f"PASS        map covers {blocks} blocks "
                          f"(ZSize 0x{zsize:X}, id 0)")

        # The logical file is a read-side result, not a cache file.  Reporting
        # it prevents the common mistake of comparing .fdupi with the extracted
        # (decrypted+inflated) file.
        extracted = Path("work/gt6_vol") / entry["path"]
        if extracted.exists():
            got = extracted.read_bytes()
            if len(got) == entry["size"]:
                print(f"logical     {extracted} ({len(got)} bytes, Size matches)")
            else:
                print(f"logical     {extracted} ({len(got)} bytes, TOC Size "
                      f"0x{entry['size']:X})")
        return 1 if failed else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
