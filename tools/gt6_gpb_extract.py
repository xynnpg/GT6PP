#!/usr/bin/env python3
"""Extract the embedded DXT1 textures from a GT6 ``3bpg`` (GPB) container.

GT6/GT5 GPB containers start with the magic ``3bpg`` (``gpb3`` in the file's
little-endian word order) and carry a table of named textures.  This tool was
written from the v1.00 disc data only; it does not use PDTools or any other
third-party GT asset library.

Container layout (big-endian), verified on the v1.00 US disc:

    0x00  char[4]  "3bpg"
    0x04  u32      0
    0x08  u32      header size (0x20)
    0x0C  u32      texture count
    0x10  u32      0x20
    0x14  u32      string-table offset
    0x18  u32      first texture offset
    0x1C  u32      0
    0x20  entry[texture_count], 16 bytes each:
             u32 name_offset (relative to file start)
             u32 data_offset
             u32 data_size     (not the DXT payload size; see below)
             u32 0

Each texture starts with a ``TXS3`` header.  The useful fields are at

    +0x5A  u16     0x2000 (GCM texture format/flags word)
    +0x5C  u16     width
    +0x5E  u16     height

and the DXT1 payload begins at +0x80.  The payload length is
``max(1,width/4) * max(1,height/4) * 8`` bytes.  All sampled GT6 boot textures
are a single mip level; the next texture starts on the next 0x100 boundary.

Usage:
    python tools/gt6_gpb_extract.py FILE.gpb --out DIR [--list]

Output names are the internal ``/image/...`` paths with '/' replaced by '_'
and the ``.dds`` suffix kept.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _cstr(data: bytes, off: int) -> str:
    end = data.find(b"\x00", off)
    if end < 0:
        end = len(data)
    return data[off:end].decode("ascii", "replace")


def parse_gpb(path: Path) -> list[dict]:
    data = path.read_bytes()
    if len(data) < 0x30 or data[:4] != b"3bpg":
        raise ValueError(f"{path}: not a 3bpg container")

    header_size = _u32(data, 0x08)
    count = _u32(data, 0x0C)
    if header_size < 0x20 or count > 0x10000:
        raise ValueError(f"{path}: implausible header size/count")

    textures: list[dict] = []
    for i in range(count):
        ent = 0x20 + i * 16
        if ent + 16 > len(data):
            raise ValueError(f"{path}: texture entry {i} outside file")
        name_off = _u32(data, ent)
        data_off = _u32(data, ent + 4)
        size_field = _u32(data, ent + 8)

        if data_off + 0x80 > len(data):
            raise ValueError(f"{path}: texture {i} data outside file")
        if data[data_off:data_off + 4] != b"TXS3":
            raise ValueError(f"{path}: texture {i} missing TXS3 magic")

        width = struct.unpack_from(">H", data, data_off + 0x5C)[0]
        height = struct.unpack_from(">H", data, data_off + 0x5E)[0]
        if not width or not height or width > 8192 or height > 8192:
            raise ValueError(f"{path}: texture {i} implausible size {width}x{height}")

        dxt_size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 8
        payload_off = data_off + 0x80
        if payload_off + dxt_size > len(data):
            raise ValueError(f"{path}: texture {i} DXT payload outside file")

        textures.append(
            {
                "index": i,
                "name": _cstr(data, name_off),
                "data_off": data_off,
                "size_field": size_field,
                "width": width,
                "height": height,
                "dxt_format": "DXT1",
                "payload_off": payload_off,
                "payload_size": dxt_size,
            }
        )
    return textures


def dds_header(width: int, height: int, fourcc: bytes = b"DXT1") -> bytes:
    if len(fourcc) != 4:
        raise ValueError("FOURCC must be four bytes")
    # DDSDOC: dwFlags = CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    pitch = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 8
    header = bytearray()
    header += b"DDS "                      # dwMagic
    header += struct.pack("<I", 124)       # dwSize
    header += struct.pack("<I", flags)     # dwFlags
    header += struct.pack("<I", height)    # dwHeight
    header += struct.pack("<I", width)     # dwWidth
    header += struct.pack("<I", pitch)     # dwPitchOrLinearSize
    header += struct.pack("<I", 0)         # dwDepth
    header += struct.pack("<I", 1)         # dwMipMapCount (one level)
    header += bytes(44)                    # dwReserved1[11]
    header += struct.pack("<I", 32)        # ddspf.dwSize
    header += struct.pack("<I", 0x4)       # ddspf.dwFlags = DDPF_FOURCC
    header += fourcc                       # ddspf.dwFourCC
    header += bytes(20)                    # bit count + masks
    header += struct.pack("<I", 0x1000)    # dwCaps = DDSCAPS_TEXTURE
    header += bytes(16)                    # caps2..caps4 + reserved2
    assert len(header) == 128
    return bytes(header)


def extract(path: Path, out_dir: Path, list_only: bool = False) -> int:
    data = path.read_bytes()
    textures = parse_gpb(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for t in textures:
        name = t["name"].lstrip("/").replace("/", "_")
        print(
            f"{path.name}: [{t['index']}] {t['name']} "
            f"{t['width']}x{t['height']} {t['dxt_format']} "
            f"data=0x{t['data_off']:X} payload=0x{t['payload_off']:X}+0x{t['payload_size']:X}"
        )
        if list_only:
            continue
        dds = dds_header(t["width"], t["height"], b"DXT1")
        dds += data[t["payload_off"]:t["payload_off"] + t["payload_size"]]
        (out_dir / name).write_bytes(dds)
    return len(textures)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, default=Path("work/agent_ui/gpb_tex"))
    ap.add_argument("--list", action="store_true", help="list textures without writing DDS")
    args = ap.parse_args(argv)
    n = extract(args.file, args.out, args.list)
    print(f"{n} texture(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
