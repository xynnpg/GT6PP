#!/usr/bin/env python3
"""Tiny software renderer for OBJ files exported by tools/mdl3_export.py.

No GPU, no third-party 3D library: orthographic projection, painter's
algorithm, flat Lambert shading, PIL output. Enough to sanity-check that the
MDL3 vertex/triangle parse is right.

Usage: python tools/obj_preview.py work/wheel.obj -o work/wheel_preview.png
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw


def load_obj(path: Path):
    verts = []
    faces = []
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("v "):
            _, x, y, z = line.split()[:4]
            verts.append((float(x), float(y), float(z)))
        elif line.startswith("f "):
            parts = line.split()[1:]
            idx = []
            for p in parts:
                i = int(p.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                faces.append((idx[0], idx[k], idx[k + 1]))
    return verts, faces


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("obj", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--yaw", type=float, default=35.0)
    ap.add_argument("--pitch", type=float, default=-22.0)
    args = ap.parse_args()

    verts, faces = load_obj(args.obj)
    if not verts or not faces:
        raise SystemExit("empty OBJ")

    # Center and scale to the image.
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    cz = sum(v[2] for v in verts) / len(verts)
    centered = [(v[0] - cx, v[1] - cy, v[2] - cz) for v in verts]

    yaw = math.radians(args.yaw)
    pitch = math.radians(args.pitch)
    cyw, syw = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    def project(v):
        # Rotate around Y, then X; orthographic.
        x = v[0] * cyw + v[2] * syw
        z = -v[0] * syw + v[2] * cyw
        y = v[1] * cp - z * sp
        z2 = v[1] * sp + z * cp
        return x, y, z2

    proj = [project(v) for v in centered]
    minx = min(p[0] for p in proj)
    maxx = max(p[0] for p in proj)
    miny = min(p[1] for p in proj)
    maxy = max(p[1] for p in proj)
    span = max(maxx - minx, maxy - miny) or 1.0
    margin = 60
    scale = (args.size - 2 * margin) / span

    def screen(p):
        x = (p[0] - (minx + maxx) / 2) * scale + args.size / 2
        y = -(p[1] - (miny + maxy) / 2) * scale + args.size / 2
        return x, y

    img = Image.new("RGB", (args.size, args.size), (18, 19, 22))
    draw = ImageDraw.Draw(img)

    light = norm((-0.4, 0.8, 0.5))
    order = []
    for f in faces:
        a, b, c = proj[f[0]], proj[f[1]], proj[f[2]]
        depth = (a[2] + b[2] + c[2]) / 3.0
        n = norm(cross(sub(b, a), sub(c, a)))
        shade = max(0.12, min(1.0, 0.25 + 0.75 * abs(dot(n, light))))
        color = (int(210 * shade), int(90 * shade), int(55 * shade))
        order.append((depth, f, color))
    order.sort(key=lambda t: t[0])

    for _, f, color in order:
        pts = [screen(proj[f[0]]), screen(proj[f[1]]), screen(proj[f[2]])]
        draw.polygon(pts, fill=color, outline=(20, 20, 22))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"wrote {args.output} ({len(verts)} verts, {len(faces)} tris)")


if __name__ == "__main__":
    main()
