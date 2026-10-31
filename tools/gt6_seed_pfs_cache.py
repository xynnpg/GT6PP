#!/usr/bin/env python3
"""Seed the native PFS cache with the raw GT.VOL slices the boot path needs.

The guest opens many PDIPFS entries as plain files
(`/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/<key>`), the same way the RPCS3
oracle does.  A missing key never reaches the higher-level HFileReader
override, so the boot/presents script can never run.  This tool copies the
*raw* (still volume-encrypted) slice from the user's own GT.VOL into the
native HDD tree.  It does not decrypt, unpack, or fabricate anything.

Usage:
    python tools/gt6_seed_pfs_cache.py --boot-set --dry-run
    python tools/gt6_seed_pfs_cache.py --boot-set
    python tools/gt6_seed_pfs_cache.py --keys K/LH,K/KG,K/IE,K/WD

Exit codes: 0 all requested slices written/verified, 1 an error, 2 bad input.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_VOL = REPO / "gt6" / "GT.VOL"
DEFAULT_MAP = REPO / "work" / "gt6_pfs_keymap.tsv"
DEFAULT_CACHE = REPO / "work" / "gt6_hdd0" / "game" / "BCUS98296" / "USRDIR" / "PDIPFS" / "K"
DEFAULT_MARKERS = REPO / "work" / "gt6_hdd0" / "game" / "BCUS98296" / "USRDIR" / "PDIPFS_bdmark" / "K"

# The keys the oracle opens before the first legal/presents draw
# (docs/analysis/first-visible-ui-check.md) plus the boot/presents fonts.
BOOT_KEYS = [
    "K/LH",  # projects/gt6/boot/boot.adc
    "K/KG",  # projects/gt6/boot/boot.mproject
    "K/IE",  # projects/gt6/boot/gpb/BootProject.gpb
    "K/WD",  # projects/gt6/boot/JP/PresentsRootSCEA.gpb
    "K/4M",  # font/vec/IwataUD_M_latin.vec
    "K/5I",  # font/vec/IwataUD_M_JP.vec
    "K/V4",  # font/vec/IwataUD_B_latin.vec
    "K/HP",  # font/vec/IwataUD_B_JP.vec
    "K/TY",  # font/vec/IwataUD_E_latin.vec
    "K/G4",  # font/vec/IwataUD_L_latin.vec
    "K/CP",  # font/vec/GTfcItalic.vec
    "K/6L",  # font/vec/GTMeterNum.vec
    "K/9N",  # font/vec/GThk.vec
    "K/D8",  # font/vec/FT_B.vec
    "K/MR",  # font/vec/7seg.vec
    "K/2F",  # font/logo/menu_imagefont.bin
]


def load_keymap(path: Path):
    rows = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 8:
                continue
            key, vpath, flags, _idx, _seg, zsize, size, offset = fields[:8]
            try:
                rows[key] = {
                    "path": vpath,
                    "flags": flags,
                    "zsize": int(zsize, 16),
                    "size": int(size, 16),
                    "offset": int(offset, 16),
                }
            except ValueError:
                continue
    return rows


def slice_from_volume(vol_path: Path, offset: int, size: int) -> bytes:
    with vol_path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(size)
    if len(data) != size:
        raise ValueError(f"short read at 0x{offset:X}: {len(data)} != {size}")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keys", help="comma-separated PFS keys (default: --boot-set)")
    parser.add_argument("--boot-set", action="store_true", help="use the boot/presents key list")
    parser.add_argument("--vol", type=Path, default=DEFAULT_VOL)
    parser.add_argument("--keymap", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--markers", type=Path, default=DEFAULT_MARKERS)
    parser.add_argument("--no-markers", action="store_true", help="do not create PDIPFS_bdmark markers")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true", help="only compare existing cache files")
    args = parser.parse_args(argv)

    if args.keys:
        keys = [key.strip() for key in args.keys.split(",") if key.strip()]
    elif args.boot_set:
        keys = BOOT_KEYS
    else:
        parser.error("pass --boot-set or --keys")
    if not args.vol.is_file():
        print(f"GT.VOL not found: {args.vol}", file=sys.stderr)
        return 2
    if not args.keymap.is_file():
        print(f"keymap not found: {args.keymap}", file=sys.stderr)
        return 2
    rows = load_keymap(args.keymap)
    missing = [key for key in keys if key not in rows]
    if missing:
        print(f"keys not in the GT.VOL TOC: {', '.join(missing)}", file=sys.stderr)
        return 2

    failures = 0
    for key in keys:
        row = rows[key]
        dest = args.cache / key.split("/", 1)[1]
        expected = row["zsize"]
        print(
            f"{key:6s} {row['path']:48s} zsize=0x{expected:X} off=0x{row['offset']:X} "
            f"-> {dest.relative_to(REPO) if dest.is_relative_to(REPO) else dest}"
        )
        if args.dry_run:
            continue
        try:
            raw = slice_from_volume(args.vol, row["offset"], expected)
        except (OSError, ValueError) as error:
            print(f"  FAIL: {error}", file=sys.stderr)
            failures += 1
            continue
        digest = sha256(raw)
        if args.verify:
            if not dest.is_file():
                print("  FAIL: cache file missing", file=sys.stderr)
                failures += 1
            elif dest.stat().st_size != expected or sha256(dest.read_bytes()) != digest:
                print("  FAIL: cache differs from GT.VOL slice", file=sys.stderr)
                failures += 1
            else:
                print(f"  OK sha256={digest[:16]}...")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(raw)
        shutil.move(str(tmp), str(dest))
        print(f"  wrote {expected} bytes sha256={digest[:16]}...")
        if not args.no_markers:
            marker = args.markers / key.split("/", 1)[1]
            marker.parent.mkdir(parents=True, exist_ok=True)
            if not marker.exists():
                marker.touch()
                print(f"  marker {marker.relative_to(REPO)}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
