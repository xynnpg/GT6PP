# Asset pipeline notes

The port does **not** need to extract `GT.VOL` at runtime: the game's own PFS
reader opens the volume through the VFS. Extraction is for inspection, tooling,
and fallback rendering. These tools are what produced the wheel/interior
previews in `work/`.

## `GT.VOL`

Unpacked with GTToolsSharp 5.3.5:

| Top-level dir | Files | Size |
|---|---:|---:|
| `crs` (courses) | 2,419 | 11.33 GB |
| `car` | 13,553 | 5.82 GB |
| `movies` | 11 | 1.97 GB |
| `character` | 4,967 | 1.41 GB |
| `sound_gt` | 458 | 0.81 GB |
| `carsound` | 4,894 | 0.71 GB |
| `crowd` | 92 | 0.34 GB |
| `piece` | 2,981 | 0.27 GB |
| `sky` | 3 | 0.24 GB |
| `projects` | 708 | 0.22 GB |
| others | 2,584 | ~0.4 GB |
| **total** | **32,591** | **~25.1 GB** |

The volume contains a mix of:

- plaintext formats: `MDL3` models, `CAR5` car info, `TXS3` textures, XML,
  `.rtext`, `.ad`/`.adc` Adhoc scripts, SQLite databases;
- compressed/encrypted streams: `body_s`, `.shapestream`, `.texstream`,
  `PDIPFS` patches, movies, SGX audio.

The community documentation and 010 templates are in
`third_party/GT-File-Specifications-Documentation` (MIT). The main format pages
are the [GT Modding Hub](https://nenkai.github.io/gt-modding-hub/).

## MDL3 (ModelSet3)

`car/0001/0001/hq/body` and `interior`/`wheel` start with `MDL3`:

| Offset | Field |
|---|---|
| `0x00` | `MDL3` magic |
| `0x04` | file size |
| `0x0C` | version (14 in this dump) |
| `0x10` | model count |
| `0x14` | mesh/shape count |
| `0x18` | FVF count |
| `0x30` | models pointer |
| `0x38` | meshes pointer |
| `0x40` | FVF pointer |
| `0x44` | materials pointer |
| `0x48` | texture set pointer |
| `0xDC` | separate car data pointer |

Each mesh is `0x30` bytes and points at vertices/triangles or at a `PMSH`
(packed mesh) reference. The `hq/body` and `race/body` shells are mostly packed
(`PMSH`) or streamed (`body_s`); their direct vertex counts are zero. The
`wheel` and `interior` models have direct vertex/triangle data, which is why
they are the first assets that can be exported without decoding the stream.

### Tools

```powershell
# Inspect FVF/mesh/stream metadata
python tools/mdl3_export.py "work/gt6_vol/car/0001/0001/hq/wheel" --info

# Export direct meshes to OBJ
python tools/mdl3_export.py "work/gt6_vol/car/0001/0001/hq/wheel" -o work/wheel.obj
python tools/mdl3_export.py "work/gt6_vol/car/0001/0001/interior" -o work/interior.obj

# Render a software preview (PIL only; no GPU)
python tools/obj_preview.py work/wheel.obj -o work/wheel_preview.png
python tools/obj_preview.py work/interior.obj -o work/interior_preview.png
```

Verified output for car `0001/0001`:

- `wheel`: 636 vertices, 650 triangles, FVF `Flex` stride 16 (position float3
  at 0, packed normal at 12).
- `interior`: 8 exported meshes, 2,045 vertices, 3,700 triangles, FVFs
  `Shadow`/`Flex`/`lambert` (position float3 at 0; color/normal/UV variants).

The OBJ export does not apply the model origin or material textures yet; it is a
geometry sanity check.

## What is still locked

- **`body_s`**: `MDL3SeparateCarData` at `0xDC` says the stream has 4 chunks
  (64,671 / 5,414 / 63,826 / 36,907 compressed bytes; 109,568 / 11,136 /
  770,048 / 177,664 decompressed) starting at offset 0 of `body_s`. The bytes
  remain high-entropy after GTToolsSharp's `crypt` toggle, so the stream codec
  and/or per-file key is not yet identified. GT6's own reader will handle it at
  runtime, which is why the port does not depend on this.
- **`.shapestream` / `.texstream`**: documented as zlib-compressed, but the
  first bytes are not zlib and no stream header was found. Likely another
  encryption layer or a custom chunk container.
- **PMSH / SmoothMesh**: the packed mesh bitstream is decoded by an SPU job
  (documented in the `PackedMesh.bt` template). The native port will run that
  SPU job rather than reimplement it.

## Why this matters for the port

The asset work confirms the volume layout and gives a way to sanity-check the
VFS: if the guest opens `GT.VOL` and the PFS reader succeeds, the same bytes are
already known-good. The MDL3 parser is also a reference for the native renderer's
vertex layout, but the actual rendering will come from the game's own RSX command
stream, not from this exporter.
