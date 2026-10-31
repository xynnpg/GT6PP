#!/usr/bin/env python3
"""Parse a Gran Turismo 5/6 MDL3 ModelSet3 file and export direct meshes to OBJ.

This handles the plaintext MDL3 meshes whose vertices/triangles are stored in
the file. Body shells whose geometry lives in a packed/streamed `PMSH` or
`body_s` are reported, not exported. Based on the public MDL3 documentation and
010 templates (Nenkai/GT-File-Specifications-Documentation).

Usage:
  python tools/mdl3_export.py work/gt6_vol/car/0001/0001/hq/wheel -o work/wheel.obj
  python tools/mdl3_export.py file --info
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

# CELL_GCM_VERTEX_TYPE names used by GT5/6.
VTYPE = {
    0: "S1",
    1: "S1N",       # 2 x 16-bit?
    2: "F32",       # float32
    3: "F16",
    4: "UB8",       # 4 x u8
    5: "S16",
    6: "PACKED",    # 11_11_10 normal
    7: "CMP",
}


def u8(d: bytes, o: int) -> int:
    return d[o]


def u16(d: bytes, o: int) -> int:
    return struct.unpack_from(">H", d, o)[0]


def s16(d: bytes, o: int) -> int:
    return struct.unpack_from(">h", d, o)[0]


def u32(d: bytes, o: int) -> int:
    return struct.unpack_from(">I", d, o)[0]


def f32(d: bytes, o: int) -> float:
    return struct.unpack_from(">f", d, o)[0]


def cstr(d: bytes, o: int) -> str:
    if o <= 0 or o >= len(d):
        return ""
    e = d.find(b"\x00", o)
    return d[o:e].decode("latin1", "replace") if e >= 0 else ""


class MDL3:
    def __init__(self, path: Path):
        self.path = path
        self.d = path.read_bytes()
        d = self.d
        if d[:4] != b"MDL3":
            raise SystemExit(f"{path}: not an MDL3 file (magic {d[:4]!r})")
        self.size = u32(d, 0x04)
        self.version = u16(d, 0x0C)
        self.model_count = u16(d, 0x10)
        self.shape_count = u16(d, 0x14)
        self.fvf_count = u16(d, 0x18)
        self.models = u32(d, 0x30)
        self.meshes = u32(d, 0x38)
        self.fvfs = u32(d, 0x40)
        self.sepdata = u32(d, 0xDC)

    def models_list(self):
        out = []
        for i in range(self.model_count):
            a = self.models + i * 0x30
            out.append(
                {
                    "index": i,
                    "origin": (f32(self.d, a + 4), f32(self.d, a + 8), f32(self.d, a + 0x0C)),
                    "bounds_count": u16(self.d, a + 0x12),
                    "bounds": u32(self.d, a + 0x14),
                    "commands": u32(self.d, a + 0x18),
                    "commands_size": u32(self.d, a + 0x1C),
                }
            )
        return out

    def fvfs_list(self):
        out = []
        for i in range(self.fvf_count):
            a = self.fvfs + i * 0x78
            name = cstr(self.d, u32(self.d, a))
            field_count = u8(self.d, a + 0x18)
            stride = u8(self.d, a + 0x19)
            defs = u32(self.d, a + 0x08)
            fields = []
            for j in range(field_count):
                b = defs + j * 8
                fields.append(
                    {
                        "name": cstr(self.d, u32(self.d, b)),
                        "start": u8(self.d, b + 4),
                        "count": u8(self.d, b + 5),
                        "type": u8(self.d, b + 6),
                        "type_name": VTYPE.get(u8(self.d, b + 6), "?"),
                    }
                )
            out.append({"index": i, "name": name, "stride": stride, "fields": fields})
        return out

    def meshes_list(self):
        out = []
        for i in range(self.shape_count):
            a = self.meshes + i * 0x30
            out.append(
                {
                    "index": i,
                    "flags": u16(self.d, a),
                    "fvf": s16(self.d, a + 2),
                    "material": s16(self.d, a + 4),
                    "vert_count": u32(self.d, a + 8),
                    "vert_offset": u32(self.d, a + 0x0C),
                    "tri_length": u32(self.d, a + 0x14),
                    "tri_offset": u32(self.d, a + 0x18),
                    "tri_count": u16(self.d, a + 0x26),
                    "bbox": u32(self.d, a + 0x28),
                    "pmsh_ref": u32(self.d, a + 0x2C),
                }
            )
        return out

    def separate_data(self):
        if not self.sepdata:
            return []
        d = self.d
        count, a, b, off = struct.unpack_from(">IhhI", d, self.sepdata)
        infos = []
        for i in range(count):
            e = off + i * 0x0C
            name_off, chunk_count, chunk_off = struct.unpack_from(">III", d, e)
            info = {
                "name": cstr(d, name_off),
                "chunk_count": chunk_count,
                "chunk_offset": chunk_off,
                "chunks": [],
            }
            if chunk_off and chunk_off + 0x10 <= len(d):
                offset, c1, c2, cioff, u1, u2 = struct.unpack_from(">QhhIhh", d, chunk_off)
                info["stream_offset"] = offset
                info["chunk_info_count"] = c1 + c2
                for j in range(c1 + c2):
                    if cioff + j * 8 + 8 > len(d):
                        break
                    w0, w1 = struct.unpack_from(">II", d, cioff + j * 8)
                    info["chunks"].append(
                        {
                            "compressed": bool(w0 >> 31),
                            "compressed_size": w0 & 0x7FFFFFFF,
                            "decompressed_size": w1,
                        }
                    )
            infos.append(info)
        return infos

    def position_field(self, fvf_index: int):
        if fvf_index < 0 or fvf_index >= self.fvf_count:
            return None
        for f in self.fvfs_list()[fvf_index]["fields"]:
            if f["name"].lower() in ("position", "pos", "p"):
                return f
        return None

    def export_obj(self, out: Path, mesh_index: int | None = None):
        fvfs = self.fvfs_list()
        meshes = self.meshes_list()
        seen = set()
        verts = []
        faces = []
        exported = 0
        for m in meshes:
            if mesh_index is not None and m["index"] != mesh_index:
                continue
            if not m["vert_count"] or not m["vert_offset"] or not m["tri_count"] or not m["tri_offset"]:
                continue
            key = (m["vert_offset"], m["vert_count"], m["tri_offset"], m["tri_count"], m["fvf"])
            if key in seen:
                continue
            seen.add(key)
            fvf = m["fvf"]
            if fvf < 0 or fvf >= len(fvfs):
                continue
            pos = next((f for f in fvfs[fvf]["fields"] if f["name"].lower() in ("position", "pos", "p")), None)
            if not pos or pos["count"] < 3:
                continue
            stride = fvfs[fvf]["stride"]
            base = m["vert_offset"]
            start = pos["start"]
            vbase = len(verts)
            for i in range(m["vert_count"]):
                o = base + i * stride + start
                if o + 12 > len(self.d):
                    break
                verts.append((f32(self.d, o), f32(self.d, o + 4), f32(self.d, o + 8)))
            for i in range(m["tri_count"]):
                o = m["tri_offset"] + i * 6
                if o + 6 > len(self.d):
                    break
                a, b, c = struct.unpack_from(">3H", self.d, o)
                if a < len(verts) - vbase and b < len(verts) - vbase and c < len(verts) - vbase:
                    faces.append((vbase + a, vbase + b, vbase + c))
            exported += 1

        if not verts or not faces:
            print("no direct meshes with vertices/triangles found")
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="ascii") as f:
            f.write(f"# {self.path.name}: {exported} mesh(es), {len(verts)} verts, {len(faces)} tris\n")
            for x, y, z in verts:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            for a, b, c in faces:
                f.write(f"f {a+1} {b+1} {c+1}\n")
        print(f"wrote {out}: {exported} mesh(es), {len(verts)} verts, {len(faces)} tris")
        return len(faces)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--mesh", type=int)
    ap.add_argument("--info", action="store_true")
    args = ap.parse_args()

    mdl = MDL3(args.file)
    print(f"{args.file}: size={len(mdl.d)} version={mdl.version} models={mdl.model_count} "
          f"meshes={mdl.shape_count} fvfs={mdl.fvf_count} sepdata=0x{mdl.sepdata:x}")
    for f in mdl.fvfs_list():
        print(f"  FVF {f['index']} {f['name']!r} stride={f['stride']}")
        for fld in f["fields"]:
            print(f"    {fld['name']:<12} start={fld['start']:>2} count={fld['count']} "
                  f"type={fld['type']} ({fld['type_name']})")
    if args.info:
        for m in mdl.meshes_list():
            print(f"  mesh {m['index']:3d} fvf={m['fvf']:2d} mat={m['material']:3d} "
                  f"verts={m['vert_count']:5d}@{m['vert_offset']:#x} "
                  f"tris={m['tri_count']:5d}@{m['tri_offset']:#x} pmsh={m['pmsh_ref']:#x}")
        for info in mdl.separate_data():
            print(f"  sepdata {info['name']!r} chunks={info['chunk_count']} "
                  f"stream_off={info.get('stream_offset', 0):#x} "
                  f"entries={len(info['chunks'])}")
    if args.output:
        mdl.export_obj(args.output, args.mesh)


if __name__ == "__main__":
    main()
