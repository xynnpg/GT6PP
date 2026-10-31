#!/usr/bin/env python3
"""Check whether a GT6 RSX frame dump actually contains visible pixels.

The D3D12 backend writes 24-bit BMPs from its own readback path
(`RSX_CAP=start[:count[:stride]]`, `RSX_CAP_DIR=<dir>`).  That avoids window
capture entirely and is the reliable way to tell a black cover from a real
legal/loading frame.

Adapted from the *idea* of GT4Recomp's `tools/gs_frame_metrics` (MIT): ground
truth comes from frame bytes, not from a screenshot of the desktop.  This file
is original and has no GT4Recomp code in it.

Usage:
    python tools/gt6_frame_check.py work/rsxcap/frame_00/backbuffer.bmp
    python tools/gt6_frame_check.py <dir> --glob "frame_*/backbuffer.bmp" --min-nonblack 5
    python tools/gt6_frame_check.py <bmp> --json work/frame_check.json

Exit code 0 on PASS, 1 on FAIL, 2 on unreadable input.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

BLACK_LEVEL = 8  # any channel above this counts as a lit pixel


def read_bmp(path: Path):
    """Return (width, height, bpp, rows) with rows top-down as (r, g, b) tuples."""
    data = path.read_bytes()
    if len(data) < 54 or data[0:2] != b"BM":
        raise ValueError(f"{path}: not a BMP file")

    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    header_size = struct.unpack_from("<I", data, 14)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    planes, bpp = struct.unpack_from("<HH", data, 26)
    compression = struct.unpack_from("<I", data, 30)[0]

    if planes != 1:
        raise ValueError(f"{path}: planes={planes}")
    if compression != 0:
        raise ValueError(f"{path}: only uncompressed BI_RGB BMPs are supported (compression={compression})")
    if bpp not in (24, 32):
        raise ValueError(f"{path}: only 24/32-bit BMPs are supported (bpp={bpp})")

    top_down = height < 0
    height = abs(height)
    stride = ((width * bpp + 31) // 32) * 4
    if pixel_offset + stride * height > len(data):
        raise ValueError(f"{path}: truncated pixel data")

    rows = []
    for y in range(height):
        src_y = y if top_down else height - 1 - y
        base = pixel_offset + src_y * stride
        row = []
        step = bpp // 8
        for x in range(width):
            at = base + x * step
            b, g, r = data[at], data[at + 1], data[at + 2]
            row.append((r, g, b))
        rows.append(row)
    return width, height, bpp, rows


def luma(r: int, g: int, b: int) -> int:
    return (299 * r + 587 * g + 114 * b) // 1000


def analyze(rows):
    height = len(rows)
    width = len(rows[0]) if height else 0
    lit = 0
    total_luma = 0
    peak_luma = 0
    colors = set()
    min_x, min_y, max_x, max_y = width, height, -1, -1

    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            yv = luma(r, g, b)
            total_luma += yv
            if yv > peak_luma:
                peak_luma = yv
            if r > BLACK_LEVEL or g > BLACK_LEVEL or b > BLACK_LEVEL:
                lit += 1
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
            # Bounded colour census: enough to tell a flat cover from artwork.
            if len(colors) < 4096:
                colors.add((r, g, b))

    pixels = width * height
    return {
        "width": width,
        "height": height,
        "pixels": pixels,
        "nonblack_pixels": lit,
        "nonblack_pct": (100.0 * lit / pixels) if pixels else 0.0,
        "mean_luma": (total_luma / pixels) if pixels else 0.0,
        "peak_luma": peak_luma,
        "unique_colors": len(colors),
        "color_census_capped": len(colors) >= 4096,
        "bbox": None if max_x < 0 else [min_x, min_y, max_x + 1, max_y + 1],
    }


def verdict(stats, min_nonblack, min_colors):
    reasons = []
    if stats["nonblack_pct"] < min_nonblack:
        reasons.append(f"non-black {stats['nonblack_pct']:.2f}% < {min_nonblack}%")
    if stats["unique_colors"] < min_colors:
        reasons.append(f"unique colours {stats['unique_colors']} < {min_colors}")
    return reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="BMP file or directory")
    parser.add_argument("--glob", default="**/backbuffer.bmp", help="pattern when path is a directory")
    parser.add_argument("--min-nonblack", type=float, default=1.0, help="PASS threshold for non-black pixel percent")
    parser.add_argument("--min-colors", type=int, default=16, help="PASS threshold for distinct colours")
    parser.add_argument("--json", type=Path, help="write full results here")
    args = parser.parse_args(argv)

    files = sorted(args.path.glob(args.glob)) if args.path.is_dir() else [args.path]
    if not files:
        print(f"no BMP files under {args.path} matching {args.glob}", file=sys.stderr)
        return 2

    results = []
    failed = False
    for path in files:
        try:
            width, height, bpp, rows = read_bmp(path)
        except (OSError, ValueError) as error:
            print(f"FAIL {path}: {error}", file=sys.stderr)
            failed = True
            continue
        stats = analyze(rows)
        stats["path"] = str(path)
        stats["bpp"] = bpp
        reasons = verdict(stats, args.min_nonblack, args.min_colors)
        stats["pass"] = not reasons
        stats["reasons"] = reasons
        results.append(stats)
        state = "PASS" if stats["pass"] else "FAIL"
        bbox = "none" if stats["bbox"] is None else "{},{}-{},{}".format(*stats["bbox"])
        print(
            f"{state} {path}: {width}x{height} non-black {stats['nonblack_pct']:.2f}% "
            f"mean luma {stats['mean_luma']:.1f} peak {stats['peak_luma']} "
            f"colours {stats['unique_colors']} bbox {bbox}"
            + ("" if stats["pass"] else "  [" + "; ".join(reasons) + "]")
        )
        failed = failed or not stats["pass"]

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"frames": results}, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
