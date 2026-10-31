# Gran Turismo 6: Formats, Binaries, Tooling, and Prior Art

**Scope:** GT6-specific containers, executables, asset formats, modding tools, RPCS3 status, documented architecture, and the shortest realistic path to a visible result on Windows. General PS3 native-recompilation theory and effort planning are covered by the companion report `docs/research/ps3-native-recompilation.md`; this report stays on GT6.

**Research date:** 2026-10-31. **Target examined:** US retail disc `Gran Turismo 6` (`BCUS98296`, v1.00), plus public sources for the v1.22 update.

**Confidence legend:**

- **Verified** — read directly from the local disc (read-only), from source code, or from an official/primary document on 2026-10-31.
- **Inference** — a conclusion drawn from verified facts, not directly confirmed for GT6.
- **Unverified** — a secondary/community claim that was not independently checked, or a claim that may change.

No game files were modified, decrypted, or redistributed. Local inspection was limited to directory listings, `PARAM.SFO`, ISO volume metadata, SELF/ELF headers, section-info tables, and entropy sampling.

---

## 1. Executive summary

GT6 is a **2013 PS3 game built on Polyphony Digital's in-house engine**, with a small bootstrap `EBOOT.BIN` and a large second-stage executable (`EMAIN.SELF` on this disc). Almost all gameplay logic lives in Polyphony's proprietary **Adhoc** bytecode, while the native executable is the engine/framework: rendering, audio, physics, file system, and the Adhoc VM. The game's assets are packed into **`GT.VOL`**, a 15.4 GB proprietary volume with its own header/TOC encryption and a custom CRC32/xorshift stream cipher — not AES, and not a standard archive.

The community has already reverse-engineered the important parts:

- **`GTToolsSharp`** (MIT) unpacks `GT.VOL` and `PDIPFS`, decrypts the volume header/TOC, and repacks PDIPFS. It is the single most important tool.
- **`GT-File-Specifications-Documentation`** (MIT) has 010 Editor templates for the volume, ModelSet3/MDL3, TXS3 textures, CAR5 car-info, GT6 GARG saves, MPKG packages, and course files.
- **`GTAdhocToolchain`** (MIT) and **`OpenAdhoc`** (GPL-3.0) can disassemble, compile, and partially re-implement Adhoc scripts; OpenAdhoc reports **≥70% of GT6 1.22 scripts** translated.
- **id-daemon's GT6 tool** extracts most car meshes/textures (about 99% of car meshes, with caveats); there is **no general track-mesh exporter**.
- **RPCS3** runs GT6 to “Ingame” status, not “Playable”; 1.05 is the usual sweet spot, and 1.22 needs Read Color Buffers (and sometimes Write Color Buffers) and still has graphical issues.

Prior attempts at a native PC version are thin and mostly unverified:

- **`Denarmo/Gran-Turismo-6-Recomp`** appeared around October 2026 as a “static recompilation port” with 4K/ultrawide claims. It had no `.exe`, required the user to rebuild via Python, and the author deleted the repository; forum users report nobody got it running. Treat it as **vaporware/unverified**, not as a working port.
- **`sp00nznet/GT5P`** is the closest credible sibling: a GT5 Prologue static recompilation on `ps3recomp` with **42,316 lifted PPU functions, 12 SPU images, 439 imports across 26 modules, 116 PDIPFS assets loaded deterministically, D3D12 initialized, one prepare-flip — but no frame yet**. It is pre-alpha. That is the realistic benchmark for a GT-class engine, and GT6 is larger.
- **`RyGT`** is a native port of **Gran Turismo Sport** (PS4), not GT6; it was taken down. It is not evidence of a GT6 port.

**Bottom line for “visible result in days”:** extracting `GT.VOL` and rendering a car model in Blender is a **days-scale** project with existing tools. Booting GT6’s own menu natively is **months-to-years**, not days; the only way to see GT6’s menu quickly is RPCS3.

---

## 2. The local dump: verified facts

### 2.1 Files and sizes

| File | Size (bytes) | Hex | Notes |
|---|---:|---:|---|
| `EBOOT.BIN` | 72,920 | `0x11CD8` | SCE SELF, bootstrap executable |
| `EMAIN.SELF` | 8,843,160 | `0x86EF98` | SCE SELF, main executable on this disc |
| `GT.VOL` | 15,407,310,848 | `0x39658E800` | Encrypted/compressed volume, ~14.35 GiB |
| `PS3UPDAT.PUP` | 268,435,456 | `0x10000000` | Standard PS3 firmware update payload |
| ISO | 25,293,815,808 | `0x5E3A10000` | Dual-layer Blu-ray image |

The ISO9660 primary volume descriptor at sector 16 is valid (`CD001`) and its volume ID is **`GRANTURSIMO`** (sic, one “S” missing). The `PS3_DISC.SFB` in this dump is zero-filled; it is not a useful title-ID source here. `PARAM.SFO` is authoritative.

### 2.2 `PARAM.SFO` fields

Parsed from `PS3_GAME/PARAM.SFO`:

| Key | Value |
|---|---|
| `APP_VER` | `01.00` |
| `TITLE` | `Gran Turismo®6` |
| `TITLE_ID` | **`BCUS98296`** |
| `CATEGORY` | `DG` (disc game) |
| `PS3_SYSTEM_VER` | `04.5000` |
| `PARENTAL_LEVEL` | `3` |
| `RESOLUTION` | `63` |
| `SOUND_FORMAT` | `791` |
| `VERSION` | `01.00` |

**Important correction:** the working hypothesis in the task description, “BLUS-311??”, is wrong for this dump. The US retail disc is **`BCUS98296`**, a Sony first-party title ID. `BLUS` IDs are typically third-party; GT6 is published by Sony Computer Entertainment. The modding hub also lists US disc `BCUS-98296`, US PSN `NPUA-81049`, EU `BCES-01893`, and JP `BCJS-37016` ([GT6 build page](https://nenkai.github.io/gt-modding-hub/builds/gt6/)).

### 2.3 Trophy data

`PS3_GAME/TROPDIR/NPWR04712_00/TROPHY.TRP` is present, size **2,485,984 bytes**. The trophy set ID is **`NPWR04712_00`**. The file begins `DC A2 4D 00` and contains `TROPCONF.SFM` at offset `0x40`; this is the standard PS3 TRP trophy package, not a GT6-specific format. Trophy unlocking/serialization is handled by the PS3 system libraries, not by GT6's volume format.

### 2.4 `GT.VOL` entropy

Read-only sampling of 1 MiB at offsets `0x0`, `0x800`, `0x100000`, the midpoint, and the last MiB gives **7.9998 bits/byte** at every sample. The first bytes are random (`99 CD DC D6 5F 7D 2E 3D...`), not the expected PFS magic. There are no meaningful ASCII strings in the first 4 MiB; the apparent ASCII runs are random chance. This is consistent with a fully encrypted/compressed container, with only the volume metadata (header/TOC) decryptable via the known keyset.

---

## 3. `GT.VOL` / PDIPFS format

### 3.1 Container model

GT5/GT6 use Polyphony Digital's **PFS/PDIPFS** file system, designed for patching:

- **Disc v1.00:** `GT.VOL` contains the base game. There may be no PDIPFS at all.
- **Updated disc:** `GT.VOL` still contains base data; `USRDIR/PDIPFS/` is an overlay containing update content. The PDIPFS TOC overrides the volume TOC, but individual files may still be read from `GT.VOL`.
- **PSN version:** no `GT.VOL`; `PDIPFS` contains the entire game. The modding hub states this explicitly ([PS3 volume docs](https://nenkai.github.io/gt-modding-hub/formats/volume/ps3_volume/), [volume guide](https://nenkai.github.io/gt-modding-hub/ps3/basics/volume_system/)).

`GT.VOL` is one big PFS container with a header at offset `0x00`, a table of contents at sector 1 (`0x800`), and file data after the TOC. PDIPFS uses the same structures but is a directory of scrambled two-character filenames; the master header is always `PDIPFS/K/4D` (or older `K/4/D`).

### 3.2 Volume header

The volume header is **encrypted**. `GTToolsSharp` reads **`0xA0` bytes** for the GT5/GT6 PFS2 header, decrypts them with seed `1`, and then reads the structure. The modding-hub table says “size `0x20`”, but that table is a partial view: the `TitleID/Description` field at `0x20` is `char[0x80]`, so the actual structure is `0xA0` bytes. Source: [`FileDeviceGTFS2Header.cs`](https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Headers/FileDeviceGTFS2Header.cs), [`PFSVolumeHeaderBase.cs`](https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Headers/PFSVolumeHeaderBase.cs).

Expected **decrypted** layout (big-endian):

| Offset | Size | Field | Notes |
|---:|---:|---|---|
| `0x00` | 4 | Magic | `5B 74 51 62` (`[tQb`) |
| `0x04` | 4 | TOC node index | Seed used to decrypt the TOC |
| `0x08` | 4 | Compressed TOC size | Bytes stored at `0x800` |
| `0x0C` | 4 | Expanded TOC size | After zlib inflate |
| `0x10` | 8 | Serial number | Volume build/patch sequence |
| `0x18` | 8 | Total volume size | Bytes |
| `0x20` | `0x80` | Title ID / description | Null-terminated string |

On this disc the first four bytes are `99 CD DC D6`, not `5B 74 51 62`; that is expected because the header is encrypted. `GTToolsSharp --save-volume-header` can decrypt and save it as `VolumeHeader.bin` for inspection.

### 3.3 Table of contents and B-trees

The TOC is at **`0x800`** (sector 1), encrypted with the header’s `TOC node index` as seed, then zlib-inflated. Expected decrypted magic is **`5B 74 51 6E`** (`[tQn`). The TOC is a set of tightly bit-packed B-trees:

| Offset | Size | Field |
|---:|---:|---|
| `0x00` | 4 | Magic `5B 74 51 6E` |
| `0x04` | 4 | Name B-tree offset |
| `0x08` | 4 | Extension B-tree offset |
| `0x0C` | 4 | File-info B-tree offset |
| `0x10` | 4 | Directory B-tree count |
| `0x14` | 4 × count | Directory B-tree offsets |

B-tree pages are `0x1000` bytes, bit-packed. The page header contains an index-page count, a 24-bit pointer to the index block, a page count, and the first page data. File entries reference a name index, an extension index, and a file-info index. File-info nodes contain:

| Field | Type | Meaning |
|---|---|---|
| Flags | `u8` | `0x00` uncompressed, `0x01` PS2ZIP-compressed, `0x02` custom Salsa (GT5P only), other bits unknown |
| File index | varint | Also the decryption seed |
| Compressed size | varint | Stored size |
| Uncompressed size | varint | Only if compressed |
| Sector offset | varint | Relative to the data area, in `0x800` units |

Sources: [`PFSBTree.cs`](https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/BTree/PFSBTree.cs), [`FileInfoKey.cs`](https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/BTree/FileInfoKey.cs), [modding-hub volume docs](https://nenkai.github.io/gt-modding-hub/formats/volume/ps3_volume/).

The data area starts at:

```
DataOffset = align_up(0x800 + CompressedTOCSize, 0x800)
file_offset = DataOffset + SectorOffset * 0x800
```

Compressed entries use **PS2ZIP**: magic `FF F7 EE C5`, followed by the negated uncompressed size (`size_complement = -size`), then a raw zlib/deflate stream. GT6 uses PS2ZIP, not the newer PDIZIP (`FF F7 F3 2F`) used by GT Sport/GT7 ([compression docs](https://nenkai.github.io/gt-modding-hub/formats/compression/compression_formats/)).

### 3.4 The volume cipher (important: not AES)

GT5/GT6 volume encryption is a **custom byte-stream cipher**, reverse-engineered by flatz and reimplemented by Nenkai. The real algorithm is in [`VolumeCrypto.cs`](https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Encryption/VolumeCrypto.cs); the older `Keyset.CryptBytes` is explicitly documented as a simplified version kept for documentation.

At a high level:

1. Compute `crc = ~CRC32(keyset.Magic, 0)`.
2. Seed with `crc ^ index` (the entry index; `1` for the volume header, the TOC node index for the TOC, the file index for file data).
3. Run four **inverted xorshift** steps with four 32-bit key words.
4. Mask the four results to `0x1FFFF`, `0x7FFFF`, `0x7FFFFF`, `0x1FFFFFFF`.
5. Generate four bit tables with periods `0x11`, `0x13`, `0x17`, `0x1D`.
6. Decrypt each byte by XORing the four rotated table bytes with the ciphertext byte.

The **header** gets an additional block-diffusion pass (`Keyset.DecryptBlocks`: byte-swap each 32-bit block, XOR with `ShuffleBits(previous_block)`), which the TOC and file data do not. The TOC is then zlib-inflated. File data is decrypted with its file index as seed; if compressed, the decrypted stream starts with the PS2ZIP header.

This distinction matters for a native port: **SELF uses AES-CBC**, but **GT.VOL does not**. A port needs both the SELF AES path and the GT.VOL custom cipher.

The GT6 keyset is present in `GTToolsSharp/Encryption/KeysetStore.cs` under the game code `GT6`, with magic `PISCINAS-323419048`. The keys themselves are not reproduced here. `GTToolsSharp` writes a default `key.json` on first run and uses the built-in keysets if no custom key file is supplied.

### 3.5 PDIPFS path scrambling and updates

PDIPFS filenames are not meaningful. Each TOC entry has an **entry number/index**; the index is mapped to a scrambled path of two-character directory/file names. The master header is `PDIPFS/K/4D`; the TOC location is derived from the header’s `TOC node index`. `GTToolsSharp` implements the resolver and the repacker.

GT6 updates use:

- **PKG** files installed by the PS3 (or RPCS3), which populate `PDIPFS`.
- **`UPDATENODEINFO`** metadata describing how a PDIPFS update is applied.
- **`TPPS-<VERSION>`** pending patch folders, removed after application.
- **BSDIFF** binary patches for files that already exist in the previous PDIPFS or in `GT.VOL`.
- **`K/4D`** as the only file that must be replaced to apply/revert a mod. New files are appended with new entry numbers, leaving original files intact.

This is documented in the [GTToolsSharp README](https://github.com/Nenkai/GTToolsSharp) and the [modding-hub volume guide](https://nenkai.github.io/gt-modding-hub/ps3/basics/volume_system/). It is also why modding GT6 is unusually safe: you can back up one file (`K/4D`) and revert.

### 3.6 What is known vs unknown about `GT.VOL`

**Known/verified from source:** header/TOC structures, magic values, B-tree layout, file-info flags, PS2ZIP, custom cipher, data-offset formula, PDIPFS path scrambling, update overlay model.

**Not verified locally:** the decrypted header contents for this exact disc (title string, serial, TOC sizes), the exact file count, and the per-file size distribution. These require running `GTToolsSharp` on the volume; the format is known, the values are not.

---

## 4. Executable layout: `EBOOT.BIN` vs `EMAIN.SELF`

### 4.1 SCE/SELF header

Both files are **SCE SELF v2** containers with an **ELF64 big-endian PowerPC64** payload. The SCE header is `0x20` bytes; the SELF header follows at `0x20`. Verified layout (matches scetool's `sce_header_t` and `self_header_t` in [`sce.h`](https://github.com/naehrwert/scetool/blob/master/sce.h)):

| Offset | Size | Field | EBOOT value | EMAIN value |
|---:|---:|---|---|---|
| `0x00` | 4 | Magic | `53 43 45 00` | `53 43 45 00` |
| `0x04` | 4 | Version | `2` | `2` |
| `0x08` | 2 | Key revision | `0x001C` | `0x001C` |
| `0x0A` | 2 | Header type | `1` (SELF) | `1` (SELF) |
| `0x0C` | 4 | Metadata offset | `0x410` | `0x410` |
| `0x10` | 8 | Header length | `0x980` | `0x980` |
| `0x18` | 8 | Data length (ELF size) | `0x22ED8` | `0x1555C48` |
| `0x20` | 8 | SELF header type | `3` | `3` |
| `0x28` | 8 | App info offset | `0x70` | `0x70` |
| `0x30` | 8 | ELF offset | `0x90` | `0x90` |
| `0x38` | 8 | Program header offset | `0xD0` | `0xD0` |
| `0x40` | 8 | Section header offset | `0x115D8` | `0x86E7D8` |
| `0x48` | 8 | Section info offset | `0x290` | `0x290` |
| `0x50` | 8 | SCE version offset | `0x390` | `0x390` |
| `0x58` | 8 | Control info offset | `0x3C0` | `0x3C0` |
| `0x60` | 8 | Control info size | `0x70` | `0x70` |
| `0x68` | 8 | Padding | `0` | `0` |

At `0x70`, both have an **AppInfo** structure:

- Auth ID: `0x1010000001000003`
- Vendor ID: `0x01000002`
- SELF type: `4` = **APP** (not NPDRM)
- Version: `0x00010000`
- Padding: `0`

This is the standard “retail application” SELF type. The key revision is `0x1C`, consistent with the disc’s `PS3_SYSTEM_VER 04.5000`.

### 4.2 `EBOOT.BIN` (72,920 bytes)

The ELF at `0x90` is a **small bootstrap**:

| ELF field | Value |
|---|---|
| Class/data/OSABI | ELF64, big-endian, OSABI `0x66` (Cell) |
| `e_type` / `e_machine` | `2` (EXEC) / `0x15` (PowerPC64) |
| `e_entry` | `0x30918` |
| `e_phoff` / `e_shoff` | `0x40` / `0x227D8` |
| `e_phnum` / `e_shnum` | `8` / `28` |
| `e_shstrndx` | `27` |

Program headers:

| # | Type | Flags | File offset | Vaddr | File size | Mem size | Align |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | `PT_LOAD` (1) | `0x400005` | `0x0` | `0x10000` | `0x1D958` | `0x1D958` | `0x10000` |
| 1 | `PT_LOAD` (1) | `0x600006` | `0x20000` | `0x30000` | `0x19FC` | `0x255C8` | `0x10000` |
| 2–4 | `PT_LOAD` | `4`, `6`, `0x6600006` | `0x219FC` | `0` | `0` | `0` | `0x10000` |
| 5 | `PT_TLS` (7) | `4` | `0x211CC` | `0x311D0` | `0` | `0x50` | `8` |
| 6 | `0x60000001` | `0` | `0x1D8F0` | `0x2D8F0` | `0x28` | `0x28` | `8` |
| 7 | `0x60000002` | `0` | `0x1D918` | `0x2D918` | `0x40` | `0x40` | `4` |

Section-info entries (`0x20` bytes each) at `0x290`:

| # | Offset | Size | Compressed | Encrypted |
|---:|---:|---:|---:|---:|
| 0 | `0x980` | `0xCD18` | `2` (yes) | `1` (yes) |
| 1 | `0xFD40` | `0xAB1` | `2` | `1` |
| 2 | `0x107FC` | `0` | `1` | `1` |
| 3 | `0x107FC` | `0` | `1` | `1` |
| 4 | `0x107FC` | `0` | `1` | `1` |
| 5 | `0x0` | `0` | `1` | `0` |
| 6 | `0x0` | `0x28` | `1` | `0` |
| 7 | `0x0` | `0x40` | `1` | `0` |

Only the two real loadable segments carry data; the rest are zero-sized or plain metadata. Entropy of the first segment is **7.994 bits/byte**, consistent with compressed + encrypted payload.

### 4.3 `EMAIN.SELF` (8,843,160 bytes)

`EMAIN.SELF` is the **main executable** on this disc. Its ELF is much larger:

| ELF field | Value |
|---|---|
| `e_entry` | `0x148E2E0` |
| `e_phoff` / `e_shoff` | `0x40` / `0x1555488` |
| `e_phnum` / `e_shnum` | `8` / `31` |
| `e_shstrndx` | `30` |

Program headers:

| # | Type | Flags | File offset | Vaddr | File size | Mem size |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | `PT_LOAD` | `0x400005` | `0x0` | `0x10000` | `0x13F3068` | `0x13F3068` |
| 1 | `PT_LOAD` | `0x600006` | `0x1400000` | `0x1410000` | `0x14FBAC` | `0x2A2E58` |
| 2–4 | `PT_LOAD` | `4`, `6`, `0x6600006` | `0x154FBAC` | `0` | `0` | `0` |
| 5 | `PT_TLS` | `4` | `0x14D7158` | `0x14E7158` | `8` | `0x1A4` |
| 6 | `0x60000001` | `0` | `0x13F3000` | `0x1403000` | `0x28` | `0x28` |
| 7 | `0x60000002` | `0` | `0x13F3028` | `0x1403028` | `0x40` | `0x40` |

Section-info entries at `0x290`:

| # | Offset | Size | Compressed | Encrypted |
|---:|---:|---:|---:|---:|
| 0 | `0x980` | `0x7FEADA` | `2` | `1` |
| 1 | `0x80C400` | `0x5CAF8` | `2` | `1` |
| 2 | `0x868EFC` | `0` | `1` | `1` |
| 3 | `0x868EFC` | `0` | `1` | `1` |
| 4 | `0x868EFC` | `0` | `1` | `1` |
| 5 | `0x0` | `0x8` | `1` | `0` |
| 6 | `0x0` | `0x28` | `1` | `0` |
| 7 | `0x0` | `0x40` | `1` | `0` |

The compressed first segment expands to the `0x13F3068` RX segment; the second expands to the `0x14FBAC` RW segment. The SELF file is 8.84 MB, but the ELF is **22,371,400 bytes** (`0x1555C48`).

### 4.4 Why `EBOOT.BIN` is tiny

`EBOOT.BIN` is a **bootstrap**, not the game. Its ELF is only 143 KB; it cannot contain a 22 MB engine. The community has confirmed that GT6's `EBOOT.BIN` executes `EMAIN.SELF` — a PSX-Place thread is literally titled “How to make EBOOT.BIN execute .SELF?” and the GT6 case is “Use GT6 EBOOT.BIN execute same EMAIN.SELF Success” ([thread](https://www.psx-place.com/threads/help-how-to-make-eboot-bin-execute-self.3743/)). The exact syscall/loader path is not publicly documented; the modding hub describes the updated/PSN layout as `EBOOT.BIN` → `EBOOT.SELF` and notes that `EBOOT.SELF` can replace `EBOOT.BIN` ([GT6 file structure](https://nenkai.github.io/gt-modding-hub/ps3/basics/file_structure/)). On this v1.00 disc the second stage is named `EMAIN.SELF`.

**Inference:** the bootstrap's job is to initialize the PS3 environment, mount/read `GT.VOL`, and load the second-stage SELF; the game engine is entirely in `EMAIN`. The small ELF size, separate section data, and community reports support this. The precise call sequence is **unverified**.

### 4.5 Segment encryption/compression

Both executables use **compressed + encrypted** loadable segments (`compressed=2`, `encrypted=1`). The ELF header, program headers, section headers, and section-info table are visible in plaintext; the segment payloads are not. This is why `strings EBOOT.BIN` returns nothing useful and why entropy is ~7.99.

SELF encryption is **AES-CBC** with a metadata key/IV stored in the `0x410` metadata area, itself encrypted with the app key for the key revision. The `scetool` source shows the SCE/SELF structures and the section flags ([`sce.h`](https://github.com/naehrwert/scetool/blob/master/sce.h), [`self.cpp`](https://github.com/naehrwert/scetool/blob/master/self.cpp)). The GT.VOL cipher described in §3.4 is separate and unrelated.

### 4.6 Decryption methods

| Method | What it does | Notes |
|---|---|---|
| **scetool** | `-i` prints SCE/SELF info; `-d` decrypts SELF → ELF; `-e` re-encrypts | Public source, no explicit LICENSE file in the repo. Needs `data/keys` with the APP key for key revision `0x1C`, plus curves. |
| **TrueAncestor SELF Resigner** | Converts a retail SELF to a debug/resigned SELF; used by the GT6 community for debug EBOOTs | Closed-source freeware; commonly bundled with PS3 modding tools. |
| **RPCS3** | Runs encrypted SELF directly using built-in keys; no separate decrypt step | Not a general “export ELF” tool. |
| **`ps3dec` / ISO decrypters** | Decrypt ISO/disk encryption | **Not** for SELF; irrelevant to `EBOOT.BIN`/`EMAIN.SELF`. |
| **klicensee / RAP / RIF** | NPDRM license handling for PSN SELF | Needed for NPDRM builds, not for this disc's APP SELF. |

For this disc, the SELF type is **APP (4)**, not NPDRM (8). **Inference:** decryption should use the APP keyset for key revision `0x1C`; no klicensee/RAP is needed for the disc executables. PSN builds (`NPUA-81049`) may be NPDRM and may require the `.rap`/klicensee path; community tutorials for GT6 debug EBOOTs explicitly mention copying the `.rap` for PSN versions. Do not use a disc key on a PSN SELF.

Expected outputs if decryption succeeds:

- `EBOOT.elf` — **143,064 bytes** (`0x22ED8`), ELF64 PowerPC64, entry `0x30918`.
- `EMAIN.elf` — **22,371,400 bytes** (`0x1555C48`), ELF64 PowerPC64, entry `0x148E2E0`.

Then disassemble with a PS3-aware PowerPC64 toolchain:

```powershell
powerpc64-linux-gnu-objdump -D -b elf64-powerpc -m powerpc:common64 EMAIN.elf > EMAIN.asm
```

or import into Ghidra with the PS3 ELF loader. The GT-File-Specifications repo also has IDA scripts and Ghidra databases for some formats, but not a full GT6 IDB.

**Legal note:** decryption keys are not included here. Use only your own legally obtained disc/console and comply with local law/EULA. The report describes methods, not key material.

### 4.7 Title ID and serial

- **Title ID:** `BCUS98296` (US retail disc).
- **Category:** `DG` (disc game).
- **App version:** `01.00`.
- **System version:** `04.5000`.
- **Trophy set:** `NPWR04712_00`.
- **ISO volume ID:** `GRANTURSIMO`.
- **PSN US title:** `NPUA-81049` (modding hub).
- **EU disc:** `BCES-01893`; **JP disc:** `BCJS-37016`.

There is no `BLUS-311xx` serial on this dump. If a `BLUS` value appears in a filename or database, it is likely a mislabel or a different regional release.

---

## 5. Prior art and status

As of 2026-10-31, I found **no public, verifiable, playable native GT6 port** and no public GT6 **native-engine/binary decompilation**. (There is substantial Adhoc *script* decompilation, covered below.) What exists is a mix of emulation, tooling, partial asset extraction, and unverified claims. The table below separates those.

### 5.1 Status table

| Project / effort | Scope | Status as of 2026-10-31 | Evidence / notes |
|---|---|---|---|
| **RPCS3** | General PS3 emulator | **Ingame**, not Playable. 1.05 recommended; 1.22 needs RCB (WCB on some builds) and has issues. Active development. | [RPCS3 wiki](https://wiki.rpcs3.net/index.php?title=Gran_Turismo_6), [issue #12567](https://github.com/RPCS3/rpcs3/issues/12567), [Notebookcheck 2026-10-09](https://www.notebookcheck.net/RPCS3-announces-big-fix-for-PS3-exclusive-Gran-Turismo-6.1420091.0.html) |
| **`Denarmo/Gran-Turismo-6-Recomp`** | Claimed GT6 static recompilation, 4K/ultrawide, portable package converter | **Deleted/unverified.** No `.exe`; user had to rebuild via Python; no confirmed boot/render. Repo returns 404. | [recomp.fyi row](https://recomp.fyi/), [Adrenaline forum page 4](https://forum.adrenaline.com.br/threads/pc-ports-recomps-e-afins.721752/page-4) |
| **`sp00nznet/GT5P`** | GT5 Prologue static recompilation on `ps3recomp` | **Pre-alpha.** 42,316 PPU functions, 439 imports/26 modules, 12 SPU images, 116 PDIPFS assets loaded deterministically, D3D12 up, one prepare-flip, **no frame**. | [repo](https://github.com/sp00nznet/GT5P), [progress log](https://github.com/sp00nznet/GT5P/blob/main/docs/progress.md) |
| **`RyGT`** | Gran Turismo Sport (PS4) native port | Taken down; not GT6. | [TechPowerUp](https://www.techpowerup.com/353814/gran-turismo-sport-runs-natively-on-pc-through-unofficial-port), [Reddit](https://www.reddit.com/r/decomps/comments/1xfdfzd/the_gran_turismo_sport_pc_port_seems_to_have_been/) |
| **GT4 decomp/native** (`gustavocanepa/gt4-decomp`, `MrGoodGuy2144/OpenGT4`, etc.) | PS2 GT4 engine decompilation/native | Active, but PS2 architecture and not GT6. Methodology reference only. | GitHub search results; not GT6. |
| **`GTToolsSharp`** | GT5/6/S/7 volume unpack/repack | Active, MIT; the de facto standard. | [repo](https://github.com/Nenkai/GTToolsSharp) |
| **`GT-File-Specifications-Documentation`** | 010 templates for GT formats | Active, MIT; covers volume, MDL3, TXS3, CAR5, GARG, MPKG, track files. | [repo](https://github.com/Nenkai/GT-File-Specifications-Documentation) |
| **`GTAdhocToolchain` / `OpenAdhoc`** | Adhoc compiler/disassembler + script reimplementation | Active; GT6 1.22 scripts ≥70% translated. | [toolchain](https://github.com/Nenkai/GTAdhocToolchain), [OpenAdhoc](https://github.com/Nenkai/OpenAdhoc) |
| **id-daemon GT6 car tool** | Car mesh/texture extraction | Works for most car meshes (~99%), some caveats; no track support. | [ResHax thread](https://reshax.com/topic/4960-gt6-gran-turismo-6-ps3/) |
| **GT6 track extraction** | Track meshes | No general tool; shape streams are FVF and need metadata; runway only gives road. | [ResHax track thread](https://reshax.com/topic/18260-gran-turismo-6-track-models/) |
| **Grimoire** | GT5/6 custom server | WIP, heavily unfinished; not production. | [repo](https://github.com/Nenkai/Grimoire) |
| **GT6 save editor** | Garage/save editing | Closed-source community tool; works with encrypted/decrypted saves, with caveats. | [GTPlanet thread](https://www.gtplanet.net/forum/threads/the-gt6-save-editor-thread.410910/) |
| **GT6 Spec II mod** | Adhoc-based content/logic mod | Released; proves script-level modding works. | OpenAdhoc README references it. |

### 5.2 What the Denarmo project actually was

The repository description claimed “Static recompilation port of PS3 Gran Turismo 6 with 4K, Ultrawide (21:9 & 32:9) support and portable package converter.” Forum posts from October 2026 say:

- there was **no `.exe`**; users had to “recompile via python yourself”;
- the author **deleted the project from GitHub**;
- “também não vi ninguém conseguindo rodar” (“I also didn't see anyone managing to run it”).

The repo is now 404, and `recomp.fyi` marks it “repo missing.” There is no evidence of a boot, a frame, or a playable build. It should not be cited as a working GT6 port. A search snippet from the README mentioned “Automates scanning, decryption of EBOOT.BIN / EMAIN.SELF,” which suggests it was a tooling/scaffold repository, not a finished port.

### 5.3 The credible sibling: GT5 Prologue

`sp00nznet/GT5P` is the most useful data point because it is a real, public, source-available attempt on the same engine lineage and the same `ps3recomp` toolchain:

- **42,316 lifted PPU functions**; 439 imported syscalls across 26 modules.
- **12 SPU images** lifted and registered; SPURS job chains dispatch with zero misses.
- **116 PDIPFS assets** loaded deterministically across 8 runs.
- D3D12 backend initialized; tiles, Zcull, display buffers, one prepare-flip.
- **No frame, no audio/input/menus yet.**

This is after multiple phases of work (the progress log is long and detailed). GT6 is a larger game with a 22.4 MB ELF, 1,279 cars, and 107 track layouts; it is not a weekend target. The GT5P port is also the best source of concrete pipeline commands (`pkg_extract.py`, `self_metainfo.py`, `ps3sce`, `ppu_lifter.py`, `spu_lifter.py`) that could be adapted for GT6.

---

## 6. GT6 architecture as publicly documented

### 6.1 Native engine + Adhoc VM

GT6's native executable is the **engine/framework**: rendering, audio, physics, file system, platform libraries, and the Adhoc VM. The game logic is mostly **Adhoc**, Polyphony's in-house scripting language/bytecode introduced in GT4:

- Adhoc is responsible for **roughly 99% of gameplay logic**; the executable “only executes what the adhoc scripts are asking it to do” ([modding-hub Adhoc](https://nenkai.github.io/gt-modding-hub/concepts/adhoc/adhoc/)).
- GT6 uses Adhoc bytecode version **12** (GTPSP/GT5/GT6/GT Sport), per `GTAdhocToolchain`.
- Menus are **projects**: `.adc` compiled scripts, `.mproject`/`.mwidget` UI layouts, `.gpb` UI asset containers, and GT6-only `.mpackage` bundles.
- `OpenAdhoc` reports **GT6 1.22 ≥70%** of scripts re-created from compiled bytecode; GT5 2.11 ≥65%; GT4/GT PSP 100%. This is script-level decompilation, not native engine decompilation.

**Implication:** a native port can reuse the original Adhoc bytecode and VM (recompiled PPU code) or reimplement the VM. It cannot skip the VM and expect menus/game logic to work, because most of the game is scripted.

### 6.2 Rendering and SPU usage

Digital Foundry's technical analysis (John Linneman, Jan 2014) is the best public rendering description:

- GT6 renders at **1440×1080** in “1080p” mode (a 12.5% increase over GT5's 1280×1080), with **MLAA** post-process anti-aliasing instead of GT5's 2× quincunx AA.
- Optional **1280×720** mode is faster and closer to 60 fps; MLAA has fewer pixels to work with.
- Performance depends on **dynamic lighting, number of cars, cockpit view, and weather**. 16 cars are supported; full grids are reserved for later career events.
- **Adaptive tessellation** is used for cars; Digital Foundry notes LOD popping in gameplay and suggests tessellation may be more visible in 30 fps replays.
- Replays originally ran at 30 fps; patch 1.03 restored 60 Hz replay playback. Replays add high-quality motion blur and bokeh depth of field.
- The game targets 60 fps but frequently misses it at 1440×1080; 720p is the smoother mode.

Sources: [Eurogamer/DF article (Wayback)](http://web.archive.org/web/20250704124229/https://www.eurogamer.net/digitalfoundry-2014-vs-gran-turismo-6), [GTPlanet summary](https://www.gtplanet.net/digital-foundry-finds-gran-turismo-6-pushes-ps3-to-the-limit/).

**SPU usage is confirmed in two places:**

- RPCS3 developers state that **MLAA is done on the CPU/SPU** and that GT6's post-processing is still running on an SPU when RSX starts reading the image, causing flicker/tearing if synchronization is wrong ([issue #11290](https://github.com/RPCS3/rpcs3/issues/11290), [issue #12567](https://github.com/RPCS3/rpcs3/issues/12567)).
- GT6's ModelSet3 format has an explicit **SPU SmoothMesh job path**: the 010 template documents `UnkSpuJobBufferSizeQwords` as “m_mmLengthInQwords in a WwsJob command, for the SmoothMesh spu job,” and references GT6 1.22 functions `0x0086acf4` / `0x008eb430` (`ModelSet3::BuildAndSubmitSmoothMeshJobCommands`). This is strong evidence that GT6 offloads mesh smoothing/tessellation work to SPUs.

So a native port must replace at least: **SPU post-processing/MLAA**, **SPU SmoothMesh jobs**, **SPURS scheduling**, and whatever audio/physics jobs use SPUs. The exact SPU job inventory is not public; this is a major reverse-engineering task.

### 6.3 Physics and audio

- **Physics:** GT6 has a native physics engine; public interviews describe a new physics simulator, aerodynamics, suspension, and tyre model at launch, but Polyphony has not published internal update rates or solver details. A public forum claim of “360 Hz physics” exists, but I could not verify it against a Polyphony primary source; treat it as **unverified**. For porting, the practical answer is that the physics code is in the native PPU/SPU binary and must be recompiled or reimplemented; there is no public source.
- **Audio:** car sounds live under `carsound/` (`engine`, `turbo0-3`, `normal0-3`, `start`, `se`, `aes`), with SGX/ESGX engine-sound formats and a BGM library (`sound_gt/library/GT6.lib`). Music tracks can be played with vgmstream; engine-sound synthesis is proprietary and less well documented. The PS3 audio pipeline uses cellAudio and likely SPU mixing; a port needs a replacement mixer/synth.

### 6.4 Online

GT6 uses Polyphony's **Grim** server infrastructure:

- Grim1 debuted in GT5 Prologue: XML content over SSL; supported Sony's `libpace`/DLS P2P/torrent for GTTV; supported PDIPFS online patches, used for **GT6 hotfixes**.
- Grim2 came with GT5; not much public detail.
- GT6 also introduced **TinyWeb** for some live events and asynchronous programming in Adhoc.
- Online services ended **28 March 2018, 12:00 UTC**; DLC distribution ended **31 January 2018** ([official announcement](https://www.gran-turismo.com/us/news/00_5985704.html)).
- **Grimoire** is a WIP open-source GT5/6 custom server (MIT), but its README warns it is heavily unfinished, can break easily, and is not production-ready; using it on real hardware can cause PSN bans.

A native port can ignore online for an offline-first build, but a “complete” port would need a Grim-compatible server or a replacement for community/seasonal features.

### 6.5 Updates, disc vs PSN, DLC

| Aspect | Disc v1.00 | PSN / v1.22 |
|---|---|---|
| Executable | `EBOOT.BIN` + `EMAIN.SELF` | `EBOOT.BIN` + second-stage SELF (community reports `EBOOT.SELF`; PSN may be NPDRM) |
| Assets | `GT.VOL` (15.4 GB) | `PDIPFS` only; no `GT.VOL` |
| Updates | PKG → `PDIPFS` overlay + `UPDATENODEINFO`/`TPPS` | Same, but base content is already in PDIPFS |
| Version | `APP_VER 01.00` | 1.22 final |
| RPCS3 | 1.00 has mixed reports; 1.02+ often needed | 1.05 recommended; 1.22 needs RCB (WCB on some builds) and has issues |

Key dates/content:

- **1.03** (Jan 2014): restored 60 Hz replay playback (DF).
- **1.05** (10 Mar 2014): multi-monitor settings, car search, traction-control/SRF adjustments, and more ([official update details](https://www.gran-turismo.com/sg/news/00_1151278.html)).
- **1.22** (2 Dec 2015, ~35 MB): final update; community version history lists a bug fix. The modding hub recommends 1.22 for modding, 1.05 for RPCS3 playability.
- **Final content:** 1,279 cars (community car list), 40 locations / 107 layouts (official product page). Launch was ~1,200 cars, 37 locations / 100 layouts.
- **DLC:** post-release cars/tracks were delivered through updates/hotfixes and promotional packs (15th Anniversary, Vision GT, etc.); DLC distribution ended 31 Jan 2018. GT Store credits were a separate entitlement.

### 6.6 Save data and trophies

- **Save folder:** PS3 savedata under a folder named `<TITLEID>-GAME6` (e.g. `BCJS37016-GAME6` on JP; US should be `BCUS98296-GAME6`). The save is PS3 SDAT-encrypted; the GT6 save editor offers “Open (Decrypted)” / “Save (Decrypted)” options, implying a game-level layer on top of SDAT.
- **Garage format:** the 010 template `GARG_MGarage.bt` documents a **GARG** header (`0x20` bytes: magic, version, entry size, sheet count, array length, `MCarParameter` size/version) followed by garage entries. `MCarParameter` is the per-car parameter object. This is the closest thing to public save-format documentation.
- **Trophy data:** standard PS3 TRP at `TROPDIR/NPWR04712_00/TROPHY.TRP`; trophy set ID `NPWR04712_00`. No GT6-specific trophy crypto is documented; the PS3 system handles it.

The full save container (SDAT + game encryption + GARG) is **not** publicly documented end-to-end; the save editor is closed-source. A native port would need to implement save import/export or start with a fresh save.

---

## 7. Asset pipeline

### 7.1 Directory map (GT6)

From the modding hub's [GT6 file structure](https://nenkai.github.io/gt-modding-hub/ps3/basics/file_structure/), with additions from the 010 templates:

```
USRDIR/
├─ EBOOT.BIN              # bootstrap
├─ EMAIN.SELF             # main executable (v1.00 disc)
├─ GT.VOL                 # base assets (disc)
├─ PDIPFS/                # update overlay or full PSN content
├─ UPDATENODEINFO/        # update metadata
├─ TPPS-<VERSION>/        # pending binary patches
├─ FIXEDELF114/           # PDI patch fix for 1.13
├─ db/userdb<VERSION>.dat # cached SQLite replay/user metadata
└─ grim2/                 # Grim cached content

Volume/
├─ car/<maker>/<car>/{hq,race}/body, body_s, wheel, interior, meter, info
├─ carparts/{hq,race,image,wheel_thumb,wing_thumb}
├─ carsound/{engine,turbo0-3,normal0-3,start,se,aes}
├─ crs/<course>/{x,.ad,.cam,.cinf,.envptr,.envsky,.esp,.layout,.lv,.lv0,.map,.occluder,.patch,.road,.rwy,.shapestream,.sky,.texstream,.vvls}
├─ database/<branch>/menudb.dat       # SQLite, Salsa-encrypted
├─ database/gt6movie/caption.dat      # SQLite, Salsa-encrypted
├─ description/<branch>/<region>.rt2  # localization
├─ font/{logo,vec}
├─ game_parameter/<branch>/{arcade,autodemo,events,license}
├─ icon/<branch>/{game_bg,game_icon,replay_sr_bg,replay_sr_icon}.png
├─ movies/                            # PAMF, encrypted
├─ piece/                             # most images (TXS3 .img)
├─ products/                          # Adhoc widgets
├─ projects/                          # menus (.adc/.mproject/.mwidget/.gpb/.mpackage)
├─ rtext/                             # localized text
├─ scene/{misc,script}
├─ scripts/<branch>/main.adc          # first script / game loop
├─ sky/
├─ sound_gt/{etc,guide,library,se,track}
├─ specdb/<name>/DBXXXX.dat           # SQLite, Salsa-encrypted
├─ ted/<branch>/*.ted                 # track editor samples
└─ tire/{hq,race}
```

### 7.2 Formats and tooling

| Asset | Format / magic | Tool | Status |
|---|---|---|---|
| Volume | PFS/PDIPFS, `5B 74 51 62` header, `5B 74 51 6E` TOC | GTToolsSharp | Good; unpack/repack |
| Car model | **MDL3 / ModelSet3**, magic `MDL3` or `3LDM` | 010 templates; id-daemon GT6 tool | Car meshes mostly extractable; creation not possible |
| Car info | **CAR5**, magic `CAR5`, header `0x18` | 010 template; CAR5 editor | Camera/driver/rain/exhaust/tire/spoiler data |
| Texture | **TXS3**, magic `TXS3` or `3SXT` | TXS3Converter | Good; DDS-like, DXT1/3/5/DXT10 |
| Audio (music) | `.lib` BGM library; AT3/other streams | vgmstream | Music playable; engine SGX less mature |
| Audio (engine) | `.sgd/.sgb/.sgh`, `.esgx` | 010 templates; community tools | Proprietary synthesis; partial |
| Menus/scripts | `.adc` Adhoc bytecode; `.mproject/.mwidget`; `.mpackage`; `.gpb` | GTAdhocToolchain | Compile/disassemble/package; good |
| Databases | SQLite `.dat` + Salsa20 | GTToolsSharp `cryptsalsa`; SQLite browser | Good once decrypted |
| Car names | **NDB0** | 010 template | Car name/brand mapping |
| Courses | `.crs` variants; `.shapestream`/`.texstream` | 010 templates; manual | Track mesh extraction hard |
| Movies | **PAMF** (`0x464D4150`), encrypted | GTToolsSharp `cryptmovie`; vgmstream/FFmpeg | Playable after decrypt |
| Save | PS3 SDAT + **GARG** garage | GT6 save editor; 010 template | Partial/closed-source |
| Trophy | PS3 **TRP** | Standard tools | Readable |
| Fonts | **NVEC** `.vec` | PDTools/NVecBuilder | Good |

### 7.3 Models: MDL3 / ModelSet3

The 010 template [`MDL3_ModelSet3.bt`](https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/Shared/Models/MDL3_ModelSet3.bt) is the most detailed public description. Key facts:

- **Magic:** `MDL3` (`0x4D444C33`) big-endian, or `3LDM` little-endian.
- **Endianness:** big-endian on GT5/GT6; little-endian on GTPSP.
- **Header:** contains counts and offsets for models, model keys, shapes, shape keys, FVFs, materials, texture set, shaders, bones, constants, VM host methods, VM commands, VM instance, wing data, shape-streaming map, PMSH packed meshes, and (version ≥14) a **car body stream**.
- **Models:** `0x30` bytes each; origin, bounds, setup command pointer/size, VM pointers.
- **Shapes/meshes:** `0x30` bytes each; FVF index, material index, vertex count/pointer, triangle count/pointer, bounds, PMSH reference.
- **FVF (Flexible Vertex Definition):** `0x78` bytes; name, shader-related index, field definitions, field count, vertex stride. This is why generic mesh rippers fail: the vertex layout changes per mesh.
- **Materials:** one material set; links to TXS3 texture set and SHDS/RSX shaders.
- **PMSH (packed mesh):** GT6-specific packed mesh data to save memory; version ≥9.
- **VM commands:** bytecode to set up meshes and RSX parameters; GT6 adds tessellated meshes and SPU SmoothMesh jobs.
- **Wing data:** version <7; custom wing geometry/kinematics.
- **Car body stream:** version ≥14; separate streamed car body data.

The modding hub's [model page](https://nenkai.github.io/gt-modding-hub/formats/models/mdl3_modelset3/) summarizes the same structure and notes that many bits are still undocumented. The [PS3 models guide](https://nenkai.github.io/gt-modding-hub/ps3/models/) is blunt:

- GT5 has no model extractor.
- GT6 car meshes can be “somewhat extracted” with id-daemon's tool, but not all models are supported.
- **Creating models is not possible**; not enough is understood.

### 7.4 Textures: TXS3

TXS3 is “pretty much just DDS” with a GT-specific header ([docs](https://nenkai.github.io/gt-modding-hub/formats/texture/img_txs3_textureset3/)):

- Magic `TXS3` (big-endian) or `3SXT` (little-endian).
- Header `0x40` bytes: file size, relocation pointer, PGLU texture info count, image info count, pointers.
- `PGLUTextureInfo` contains PS3 Cell/RSX texture registers/parameters.
- `ImageInfo` (`0x20` bytes): data pointer/size, image format, mipmap count, width/height, stream info.
- Streamed textures use `.texstream` files, zlib-compressed, with per-mipmap offsets/sizes.

`TXS3Converter` (MIT) converts to/from PNG using TexConv/DirectXTex:

```powershell
TXS3Converter convert-png <file.img> PS3
TXS3Converter convert-img <file.png> PS3 -pf DXT5
```

Most game images are in `piece/` and in `.gpb` UI containers.

### 7.5 Tracks: the hard part

Track data is not a single model file. A course folder contains:

- `x` — main model “pack,” LODs, crucial course definition.
- `.shapestream` — zlib-compressed, streamed mesh data (FVF vertices).
- `.texstream` — zlib-compressed, streamed textures.
- `.rwy` — runway/collision/road boundaries/surface.
- `.ad` / `.esp` — autodrive/AI.
- `.cam` — camera positions/behavior.
- `.cinf` — course info (drift sections, GPS).
- `.envptr` / `.envsky` / `.sky` — environment/weather/sky.
- `.layout` / `.lv` / `.lv0` / `.map` / `.occluder` / `.patch` / `.road` / `.vvls` — gadgets, vision lists, minimap, occlusion, patches, road, unknown.

The 010 repo has templates for `AD`, `ADSP`, `CINF`, `GCam`, `GDGL`, `MMAP`, `PACB`, `PWY`, `RDEF`, `RNW5`, `ROAD`, `Vls1`. There is **no** template that turns a `.shapestream` into a complete track mesh.

Why track ripping is hard:

- Shape streams are **FVF** (flexible vertex format) and change per mesh.
- Without the metadata/VM commands, you get vertices but not correct positions, materials, or object placement.
- `.rwy` gives the road/collision layout but not UVs or objects; ResHax users call it “useless” for full track rips.
- Nenkai: “Trying to extract meshes out of shape streams is futile... not connecting them to the metadata means you won't have any accurate positional data.”

There are Assetto Corsa track mods claiming GT6 origins, but no public general-purpose GT6 track exporter. A track port is a research project, not a button press.

### 7.6 Audio

- Car sounds: `carsound/engine`, `turbo0-3`, `normal0-3`, `start`, `se`, `aes`.
- Sound setup: `sound_gt/etc/se_master.pmf`, `car_sound_gt5.pmf`.
- BGM library: `sound_gt/library/GT6.lib`; music tracks under `sound_gt/track`.
- Engine sounds use SGX/ESGX formats; the modding hub has format pages for `.esgx` and `.sgd/.sgb/.sgh`. These are proprietary synthesis/stream formats, not plain WAV.
- vgmstream can play the music tracks and some streamed audio; engine-sound synthesis is not a simple decode.

### 7.7 Proprietary vs standard: rough estimate

| Layer | Proprietary? | Porting effort |
|---|---|---|
| GT.VOL/PDIPFS container + cipher | 100% proprietary | Medium; already solved by GTToolsSharp |
| MDL3/ModelSet3 + FVF + PMSH + VM commands | 100% proprietary | High; partial docs, no creation |
| TXS3 textures | Container proprietary; DXT payload standard | Low–medium; converter exists |
| SHDS/RSX shaders | Proprietary RSX microcode | High; must translate/decompile |
| Adhoc scripts/VM | 100% proprietary | High; toolchain + 70% scripts, VM still needed |
| SQLite SpecDB/menudb | SQLite standard; Salsa encryption proprietary | Low once decrypted |
| SGX/ESGX audio | Proprietary synthesis | High |
| PAMF movies | Proprietary container; MPEG codecs standard | Low–medium |
| PS3 save/trophy | SDAT/TRP standard; GARG proprietary | Medium |
| Physics/rendering engine | Proprietary native code | Very high; recompile or rewrite |

**Rule of thumb:** the standard pieces (SQLite, zlib, DXT, MPEG, PNG) are the easy 10–20%. The remaining 80–90% of engineering is proprietary formats, VM semantics, shaders, and engine behavior.

---

## 8. What a native port would need to replace

### 8.1 Subsystem table

| Subsystem | What GT6 uses | Native replacement | Difficulty |
|---|---|---|---|
| **PPU** | PowerPC64 + VMX/AltiVec, 2 threads | `ps3recomp` PPU lifter → C/C++; or interpreter | High; 42k functions in GT5P, GT6 larger |
| **SPU** | 6 usable SPUs, SPURS jobs, local stores, DMA | `ps3recomp` SPU lifter/runtime; per-image dispatch; DMA as memcpy | Very high; GT6 uses SPU SmoothMesh and MLAA/postfx |
| **RSX GPU** | GCM command stream, NV47xx, shaders, tiled memory, Zcull, flips | D3D12/Vulkan backend; shader translation; tile/Zcull emulation | Very high; GT6's MLAA/reflections are sensitive |
| **Kernel/OS** | LV2 syscalls: threads, mutex/cond, memory, FS, timers | HLE runtime (`ps3recomp` has most) | Medium–high |
| **Cell libraries** | cellGcm, cellSpurs, cellSync, cellFs, cellPad, cellAudio, cellSysutil, cellNet, cellSsl, cellSaveData, cellGame, cellPngDec/JpgDec, cellFont, cellPamf, etc. | HLE modules | High; GT6 imports many |
| **File system** | GT.VOL/PDIPFS, scrambled paths, updates | Implement PFS reader or pre-extract assets | Medium; format known |
| **Asset loaders** | MDL3, TXS3, SGX/ESGX, PAMF, SQLite/Salsa, Adhoc | Reuse original loaders (recompiled) or rewrite | High; formats partially documented |
| **Game logic** | Adhoc bytecode (~99% gameplay) | Original Adhoc VM (recompiled) or new VM | High; OpenAdhoc 70% scripts, VM still needed |
| **Menus/UI** | `.mproject/.mwidget/.mpackage/.gpb`, Adhoc UI framework | Original VM + UI renderer, or reimplement | High |
| **Physics** | Native engine code (tyre/suspension/aero/collision) | Recompile PPU/SPU or rewrite | Very high; no public source |
| **Audio** | cellAudio, SGX/ESGX synth, BGM library | PC audio mixer + synth/decoder | High |
| **Online** | Grim2 XML/SSL, PSN/RPCN, PDIPFS hotfixes | Offline-first, or Grim-compatible server | Medium–high; optional |
| **Save/trophy** | SDAT + GARG, TRP | Save import/export, trophy stubs | Medium |
| **Timing/sync** | 60 Hz frame, SPU/RSX sync, vblank, flips | Host frame clock; careful synchronization | High; RPCS3 shows GT6 is sync-sensitive |

### 8.2 Static recompilation vs clean-room

- **Static recompilation (recommended if porting):** keep the original PPU/SPU game code, replace the PS3 OS/libs and GPU with HLE. This preserves physics, AI, rendering logic, and Adhoc VM semantics. It is the `ps3recomp` model. GT5P is the proof of concept, but it has not drawn a frame yet.
- **Clean-room reimplementation:** rewrite the engine and asset loaders. This is a multi-year effort and would lose the original physics/rendering behavior unless painstakingly matched. No GT6 project is doing this.
- **Hybrid:** recompile PPU, interpret SPU initially, HLE GPU; then optimize. This is what early `ps3recomp` ports do.

### 8.3 GT6-specific blockers beyond a generic PS3 port

1. **SPU SmoothMesh/tessellation jobs** in ModelSet3; without them, car meshes may render at wrong LOD or not at all.
2. **SPU MLAA/post-processing**; GT6's image pipeline expects SPU-produced buffers, and RSX/SPU synchronization is fragile (RPCS3 issue #11290).
3. **RSX shader translation** for GT6's SHDS/RSX shaders, including reflections, lighting, and MLAA.
4. **Adhoc VM**: menus and game logic are scripts; the native VM must be recompiled or reimplemented.
5. **GT.VOL/PDIPFS**: the game expects its own file system; a port can pre-extract, but updates/PDIPFS overlays and scrambled paths must be handled.
6. **Save data**: GT6 expects PS3 SDAT/GARG; a port needs save import or a new save system.
7. **Online**: Grim2 is dead; offline-first is the sane target.
8. **Content scale**: 1,279 cars, 40 locations/107 layouts, 15.4 GB base volume; asset loading/streaming is a major engineering effort.

---

## 9. Shortest path to a visible result on Windows

### 9.1 What is realistic in days

| Goal | Time | What you get |
|---|---:|---|
| List `GT.VOL` contents / decrypt header+TOC | 0.5 day | `volume_entries.txt`, `VolumeHeader.bin`, `VolumeTOC.bin`; confirms keys/format |
| Full `GT.VOL` extraction | 0.5–1 day (disk-dependent) | ~15.4 GB compressed → likely 20–30 GB extracted asset tree |
| Render one car in Blender | 1–2 days after extraction | OBJ + PNG textures; static car model |
| Convert textures / build a simple viewer | 2–3 days | PNG textures; a minimal OpenGL/Blender viewer |
| Extract music/audio | 1 day | WAV for supported streams; engine sounds partial |
| Disassemble Adhoc scripts | 1 day | `.ad` assembly-like text; understand menu logic |
| Track mesh | 1–4 weeks (research) | Partial track geometry; no turnkey tool |
| Native boot/menu | months–years | GT5P benchmark: boot + 116 assets, no frame after months |

**The shortest “wow” result is a car render, not a native boot.** Extracting the volume and using id-daemon's tool is a known path; booting the game natively is not.

### 9.2 Asset-render path (recommended for days)

1. **Install GTToolsSharp** from [releases](https://github.com/Nenkai/GTToolsSharp/releases). Put it in a work folder with enough free space (≥40 GB).
2. **List the volume first** (cheap, confirms keys):
   ```powershell
   GTToolsSharp listfiles -i "C:\...\GT.VOL" -o volume_entries.txt
   ```
   First run creates `key.json`; run again if prompted. Expected: a text file with game paths and file-info entries.
3. **Unpack** (hours):
   ```powershell
   GTToolsSharp unpack -i "C:\...\GT.VOL" -o "D:\GT6\VOL" --save-volume-header --save-toc-header --no-print
   ```
   Expected: `VolumeHeader.bin` (0xA0 bytes, magic `5B 74 51 62`), `VolumeTOC.bin` (magic `5B 74 51 6E`), and a tree with `car/`, `crs/`, `piece/`, `specdb/`, `scripts/`, etc.
4. **Pick a car** under `car/<maker>/<car>/hq/`. The main model is `body`; `body_s` is streamed data and must be in the same directory.
5. **Extract the car** with id-daemon's GT6 tool (`gt6.rar` from [ResHax](https://reshax.com/files/file/1138-gt6rar/)). Drop `body` onto the tool. Expected: OBJ + textures. Caveats: some facebuffer submeshes export vertices without faces; some UVs are 2×; about 99% of car meshes/textures supported.
6. **Import the OBJ into Blender**, assign the exported textures, and render. This is the fastest visible GT6 asset on Windows.

### 9.3 Menu path via RPCS3 (hours, not native)

If the goal is to see GT6's menu, use RPCS3 with the **1.05** update, not a native port:

- Install the disc game and updates in order; use 1.05 for the best compatibility/performance.
- Settings that the community reports as stable (issue #12567): PPU/SPU LLVM recompiler, Vulkan, SPU loop detection on, SPU block size Safe, accurate XFloat, asynchronous texture streaming, multithreaded RSX **off**, accurate RSX reservation access, PPU non-Java mode fixup, PPU/SPU LLVM precompilation.
- For 1.22, expect to enable **Read Color Buffers** (and sometimes Write Color Buffers); without them races can be black. 1.22 also has severe graphical issues/poor frame rate on many setups.
- Performance is CPU-bound; GT6 uses SPU post-processing, so a fast CPU matters more than a fast GPU. Reports range from ~15–20 fps on older hardware to 30–60 fps on modern CPUs; 4K/120 videos are not representative of typical performance.
- Known issues: flicker, broken reflections (improved/fixed in 2026), MLAA problems, white car icons on first thumbnail generation, tearing. See [issue #12567](https://github.com/RPCS3/rpcs3/issues/12567) and [issue #11290](https://github.com/RPCS3/rpcs3/issues/11290).

This is emulation, not a port, but it is the only way to see the actual GT6 menu in hours.

### 9.4 Native path (not days)

A native GT6 boot would start from `ps3recomp` + the GT5P scaffold. Pin a single version first: v1.00 (this disc) is the least update-dependent target; v1.22 changes code/data and would require re-lifting and retesting.

1. Decrypt `EBOOT.BIN`/`EMAIN.SELF` to ELF (scetool/ps3sce + keys).
2. Parse imports/NIDs, find functions, lift PPU to C++.
3. Lift SPU images and implement SPURS job dispatch.
4. Implement HLE libraries GT6 imports (cellGcm, cellSpurs, cellFs, cellPad, cellAudio, cellSysutil, cellNet, cellSsl, cellSaveData, cellGame, codecs, font, etc.).
5. Implement GT.VOL/PDIPFS or pre-extract assets and map paths.
6. Get RSX command submission and shader translation working; handle tiling/Zcull/flips.
7. Get Adhoc VM and menus running.
8. Get one car/track race running.

The GT5P benchmark shows steps 1–5 can take months and still not produce a frame. GT6's larger ELF and content make it harder. Do not plan a native menu in days.

---

## 10. Concrete next experiments, commands, and expected outputs

> These commands are for the user's own legally obtained files. They decrypt data; run them only in a legal/research context and do not redistribute output. The local `GT.VOL` was locked by another process during part of this research; close any extractor/RPCS3 before running.

### E1 — Verify volume header/TOC without full extraction

```powershell
GTToolsSharp listfiles -i "C:\Users\xynnp\Documents\Projects\GT6PP\PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)\PS3_GAME\USRDIR\GT.VOL" -o volume_entries.txt
```

Expected:

- First run may create `key.json` and print the available game codes (including `GT6`).
- `volume_entries.txt` contains paths like `car/...`, `crs/...`, `piece/...`, with file-info entries (flags, sizes, sector offsets).
- If it fails, the keyset/region is wrong or the file is locked.

Then:

```powershell
GTToolsSharp unpack -i "...\GT.VOL" -o "D:\GT6\VOL" --save-volume-header --save-toc-header --no-print
```

Expected files:

- `VolumeHeader.bin` — 0xA0 bytes; first four bytes `5B 74 51 62`; at `0x20` the title/description string.
- `VolumeTOC.bin` — first four bytes `5B 74 51 6E`; B-tree data.
- `D:\GT6\VOL\car\...`, `crs\...`, `piece\...`, etc.

Inspect:

```powershell
Format-Hex .\VolumeHeader.bin -Count 176
```

Expected: magic at `0x00`, TOC index at `0x04`, sizes at `0x08`/`0x0C`, serial at `0x10`, total size at `0x18`, title at `0x20`.

### E2 — Confirm SELF section layout without decrypting

```powershell
# Read-only; prints SCE/SELF header fields and section-info table.
# Use the values in §4.1–4.3 as the expected output.
```

Expected: `keyrev 0x1C`, `type 1`, `header_len 0x980`, `data_len 0x22ED8` (EBOOT) / `0x1555C48` (EMAIN), `appinfo 0x70`, `elf 0x90`, `phdr 0xD0`, `secinfo 0x290`, and the section table from §4.2/§4.3.

### E3 — Decrypt and disassemble the executables (legal/keys required)

```powershell
scetool -i EBOOT.BIN
scetool -d EBOOT.BIN EBOOT.elf
scetool -i EMAIN.SELF
scetool -d EMAIN.SELF EMAIN.elf
```

Expected:

- `EBOOT.elf` 143,064 bytes; ELF64 PowerPC64; entry `0x30918`.
- `EMAIN.elf` 22,371,400 bytes; ELF64 PowerPC64; entry `0x148E2E0`.
- `scetool -i` prints section info with `compressed=2`, `encrypted=1` for the first two segments.

Then:

```powershell
powerpc64-linux-gnu-objdump -D -b elf64-powerpc -m powerpc:common64 EMAIN.elf > EMAIN.asm
```

Expected: a large disassembly; look for `cellGcm`, `cellSpurs`, `cellFs`, `cellAudio`, `cellPad`, `cellNet`, `cellSsl`, `cellSaveData`, and Adhoc VM functions. Ghidra with the PS3 ELF loader is more usable.

**Note:** If scetool lacks the `0x1C` APP key, use a key dump from your own console or `ps3sce`/RPCS3 tooling; do not use random keys from the internet. PSN NPDRM builds may need `.rap`/klicensee.

### E4 — Extract and render a car

```powershell
# After E1 extraction:
Get-ChildItem "D:\GT6\VOL\car" -Recurse -Filter body | Select-Object -First 10 FullName
```

Pick a car, ensure `body_s` is in the same folder, then drop `body` onto the id-daemon GT6 tool. Expected: `.obj` + texture files. Import into Blender.

Checklist:

- If the tool says “unsupported code,” that submesh may export vertices without faces; try another car or submesh.
- If UVs look 2×, that is a known tool limitation.
- Car `hq/body` is the high-quality menu model; `race/body` is the race LOD.

### E5 — Convert textures

```powershell
TXS3Converter convert-png "D:\GT6\VOL\piece\gt6\course_logo_L\tsukuba.img" PS3
```

Expected: PNG next to the `.img`. Reverse:

```powershell
TXS3Converter convert-img .\tsukuba.png PS3 -pf DXT5
```

Expected: a TXS3 `.img` usable for repacking. Requires TexConv/DirectXTex in the tool folder.

### E6 — Audio probe

```powershell
vgmstream-cli -o out.wav "D:\GT6\VOL\sound_gt\track\<file>"
```

Expected: WAV for supported music/streams. For `carsound/engine`/`.esgx`, expect partial/no support; use the SGX/ESGX format docs and community tools.

### E7 — Adhoc script inspection

```powershell
adhoc "D:\GT6\VOL\scripts\<branch>\main.adc"
```

Expected: a `.ad` disassembly and `.strings` file. Use `GTAdhocToolchain` to compile custom scripts and `OpenAdhoc` to compare/decompile. GT6 supports Adhoc bytecode version 12.

### E8 — RPCS3 baseline

1. Install RPCS3, firmware, and the GT6 disc dump.
2. Install updates in order; use 1.05 for compatibility.
3. Apply the settings from issue #12567; use Vulkan, PPU/SPU LLVM, SPU loop detection, Safe block size, accurate XFloat, async texture streaming, multithreaded RSX off.
4. Boot. Expected: menus and races at playable-but-imperfect frame rates; 1.22 may need RCB (WCB on some builds) and still has issues.

This is the fastest way to see GT6's actual menu, but it is emulation.

### E9 — Track feasibility probe

```powershell
Get-ChildItem "D:\GT6\VOL\crs" -Directory | Select-Object -First 5
Get-ChildItem "D:\GT6\VOL\crs\<course>" | Select-Object Name,Length
```

Expected: `x`, `.shapestream`, `.texstream`, `.rwy`, `.ad`, `.cam`, `.cinf`, etc. Open `x` and `.rwy` with the 010 templates; inspect `.shapestream` for FVF data. Do not expect a quick OBJ; this is a research task.

---

## 11. Known vs unknown

### Known / verified

- US disc title ID **BCUS98296**; `APP_VER 01.00`; PS3 system 4.50; trophy set **NPWR04712_00**.
- `EBOOT.BIN` is a 72,920-byte SELF bootstrap; `EMAIN.SELF` is an 8,843,160-byte SELF containing a 22,371,400-byte ELF; both APP type, key revision `0x1C`, compressed+encrypted segments.
- `GT.VOL` is 15,407,310,848 bytes, high-entropy, with a PFS header at `0x00` and TOC at `0x800`; the format and cipher are documented in GTToolsSharp source.
- GT6 uses MDL3/ModelSet3, TXS3, CAR5, SGX/ESGX, Adhoc v12, SQLite/Salsa, PAMF, GARG, TRP, and PDIPFS.
- GT6's game logic is mostly Adhoc; OpenAdhoc has ≥70% of GT6 1.22 scripts.
- RPCS3 status is “Ingame,” not Playable; 1.05 is the usual best version; 1.22 needs RCB (WCB on some builds) and has issues.
- The only credible GT-class static recomp is GT5P, and it has not drawn a frame yet.
- Denarmo's GT6 recomp repo is deleted and unverified.

### Unknown / uncertain

- The decrypted `GT.VOL` header values for this exact disc (title string, serial, TOC sizes, file count).
- Exact EBOOT→EMAIN loader mechanism (syscall/args); community-confirmed behavior, not documented code.
- Full MDL3 material/shader semantics; PMSH details; how to create models.
- General track mesh extraction from `.shapestream`/`.x`; no public tool.
- Full save container encryption and GARG serialization; save editor is closed-source.
- DLC entitlement/activation details; online server behavior beyond Grim basics.
- Exact SPU job inventory and scheduling; SPU SmoothMesh/MLAA are confirmed, others are not.
- GT6 physics update rate; “360 Hz” is an unverified forum claim.
- Whether a GT6 static recomp can reach a frame in any reasonable timeframe; GT5P suggests it is a multi-month/year effort.

---

## 12. Legal and ethical note

This report describes formats and tools; it contains no game assets, no decryption keys, and no redistributed copyrighted code. Decrypting your own disc may still be restricted by the PS3 EULA and local law; the DMCA/anti-circumvention rules vary by jurisdiction. Use tools only on files you legally own, keep outputs private, and do not redistribute game data or keys. The community tools cited here are intended for preservation/modding of legally obtained copies.

---

## 13. Sources

### Local, read-only

- `PS3_GAME/PARAM.SFO` — title ID, app version, system version, parental level, resolution, sound format.
- `PS3_GAME/USRDIR/EBOOT.BIN` — SCE/SELF header, ELF header, program headers, section-info table.
- `PS3_GAME/USRDIR/EMAIN.SELF` — same.
- `PS3_GAME/USRDIR/GT.VOL` — first 4 KiB, entropy samples at `0x0`, `0x800`, `0x100000`, midpoint, end.
- `PS3_GAME/TROPDIR/NPWR04712_00/TROPHY.TRP` — TRP header.
- ISO PVD at sector 16 — volume ID `GRANTURSIMO`.

### GT6 formats and tools

- Nenkai, **GTToolsSharp** (MIT): <https://github.com/Nenkai/GTToolsSharp>
  - `Encryption/VolumeCrypto.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Encryption/VolumeCrypto.cs>
  - `Volumes/GTVolumePFS.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Volumes/GTVolumePFS.cs>
  - `BTree/PFSBTree.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/BTree/PFSBTree.cs>
  - `BTree/FileInfoKey.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/BTree/FileInfoKey.cs>
  - `Headers/FileDeviceGTFS2Header.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Headers/FileDeviceGTFS2Header.cs>
  - `Encryption/KeysetStore.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/Encryption/KeysetStore.cs>
  - `ProgramArgs.cs`: <https://github.com/Nenkai/GTToolsSharp/blob/master/GTToolsSharp/ProgramArgs.cs>
- Nenkai, **PDTools** (MIT): <https://github.com/Nenkai/PDTools>
- Nenkai, **GT-File-Specifications-Documentation** (MIT): <https://github.com/Nenkai/GT-File-Specifications-Documentation>
  - MDL3/ModelSet3: <https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/Shared/Models/MDL3_ModelSet3.bt>
  - CAR5: <https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/PS3/Cars/CAR5.bt>
  - GARG: <https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/PS3/GT6/GARG_MGarage.bt>
  - MPKG: <https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/PS3/GT6/MPACKAGE_GT6.bt>
  - NDB0: <https://github.com/Nenkai/GT-File-Specifications-Documentation/blob/master/Formats/PS3/GT6/NDB0_GT6.bt>
- Nenkai, **TXS3Converter** (MIT): <https://github.com/Nenkai/TXS3Converter>
- Nenkai, **GTAdhocToolchain** (MIT): <https://github.com/Nenkai/GTAdhocToolchain>
- Nenkai, **OpenAdhoc** (GPL-3.0): <https://github.com/Nenkai/OpenAdhoc>
- Nenkai, **Grimoire** (MIT): <https://github.com/Nenkai/Grimoire>
- emissary935, **Gran Turismo CAR5 Editor Tool**: <https://github.com/emissary935/Gran-Turismo-CAR5-Editor-Tool>

### GT6 modding documentation

- Gran Turismo Modding Hub, **PS3 Volume/PDIPFS**: <https://nenkai.github.io/gt-modding-hub/formats/volume/ps3_volume/>
- **Volume & Making Edits**: <https://nenkai.github.io/gt-modding-hub/ps3/basics/volume_system/>
- **GT6 Folder/File Structure**: <https://nenkai.github.io/gt-modding-hub/ps3/basics/file_structure/>
- **MDL3/ModelSet3**: <https://nenkai.github.io/gt-modding-hub/formats/models/mdl3_modelset3/>
- **TXS3/TextureSet3**: <https://nenkai.github.io/gt-modding-hub/formats/texture/img_txs3_textureset3/>
- **PS3 Models**: <https://nenkai.github.io/gt-modding-hub/ps3/models/>
- **PS3 Textures**: <https://nenkai.github.io/gt-modding-hub/ps3/textures/>
- **Compression formats**: <https://nenkai.github.io/gt-modding-hub/formats/compression/compression_formats/>
- **Decrypting USRDIR files**: <https://nenkai.github.io/gt-modding-hub/ps3/other/decrypting_usrdir_contents/>
- **GT6 build page**: <https://nenkai.github.io/gt-modding-hub/builds/gt6/>
- **Adhoc**: <https://nenkai.github.io/gt-modding-hub/concepts/adhoc/adhoc/>
- **Grim**: <https://nenkai.github.io/gt-modding-hub/concepts/online/grim/>
- **RPCS3 Settings**: <https://nenkai.github.io/gt-modding-hub/ps3/other/rpcs3_setup/>

### Executable / SELF

- naehrwert, **scetool** (public source, no explicit LICENSE file): <https://github.com/naehrwert/scetool>
  - `sce.h`: <https://github.com/naehrwert/scetool/blob/master/sce.h>
  - `self.cpp`: <https://github.com/naehrwert/scetool/blob/master/self.cpp>
  - README: <https://github.com/naehrwert/scetool/blob/master/README>
- PSX-Place, “How to make EBOOT.BIN execute .SELF?”: <https://www.psx-place.com/threads/help-how-to-make-eboot-bin-execute-self.3743/> (Cloudflare-protected; used via search snippet)
- ConsoleMods, PS3 EBOOTs: <https://consolemods.org/wiki/PS3:EBOOTs>
- PSX-Place, “How to create a debug EBOOT from SELF”: <https://www.psx-place.com/threads/tutorial-how-to-create-a-debug-eboot-from-self.38728/>

### RPCS3 and compatibility

- RPCS3 wiki, Gran Turismo 6: <https://wiki.rpcs3.net/index.php?title=Gran_Turismo_6>
- RPCS3 issue #12567, “Gran Turismo 6 Graphical Bugs”: <https://github.com/RPCS3/rpcs3/issues/12567>
- RPCS3 issue #11290, “MLAA postprocessing shader missing in GT6 and TLoU”: <https://github.com/RPCS3/rpcs3/issues/11290>
- RPCS3 issue #18607, “GT6 black reflections (NaN poisoning)”: <https://github.com/RPCS3/rpcs3/issues/18607>
- Notebookcheck, “RPCS3 announces big fix for PS3 exclusive Gran Turismo 6” (2026-10-09): <https://www.notebookcheck.net/RPCS3-announces-big-fix-for-PS3-exclusive-Gran-Turismo-6.1420091.0.html>
- RPCS3 repo (GPL-2.0): <https://github.com/RPCS3/rpcs3>

### GT6 rendering / architecture

- Digital Foundry / Eurogamer, “Digital Foundry vs. Gran Turismo 6” (John Linneman, Jan 2014), Wayback: <http://web.archive.org/web/20250704124229/https://www.eurogamer.net/digitalfoundry-2014-vs-gran-turismo-6>
- GTPlanet summary: <https://www.gtplanet.net/digital-foundry-finds-gran-turismo-6-pushes-ps3-to-the-limit/>
- GTPlanet, “Gran Turismo 6 Pushes PS3 ‘As Far as It Can Go’”: <https://www.gtplanet.net/gran-turismo-6-pushes-ps3-as-far-as-it-can-go/>
- Official GT6 product page (40 locations/107 layouts, 1,200+ cars): <https://www.gran-turismo.com/us/products/gt6/>
- Gran Turismo Wiki car list (1,279 cars final): <https://gran-turismo.fandom.com/wiki/Gran_Turismo_6/Car_List>
- Motor Authority launch summary (1,200 cars, 37 locations/100 layouts): <https://www.motorauthority.com/news/1088218_new-gt6-trailer-released-over-1200-cars-included-video>

### Updates, DLC, online

- Official GT6 online end of service (28 Mar 2018; DLC distribution ended 31 Jan 2018): <https://www.gran-turismo.com/us/news/00_5985704.html>
- Official update 1.05 details: <https://www.gran-turismo.com/sg/news/00_1151278.html>
- GTPlanet, GT6 1.05 multi-monitor: <https://www.gtplanet.net/gran-turismo-6-update-1-05-brings-multi-monitor-support/>
- Gran Turismo Wiki, GT6 DLC list: <https://gran-turismo.fandom.com/wiki/Downloadable_Content/Gran_Turismo_6>
- Gran Turismo Wiki, GT6 version history (1.22, 2 Dec 2015, 35 MB): <https://gran-turismo.fandom.com/wiki/Gran_Turismo_6/Version_History>
- GTPlanet, GT6 update list 1.22 final: <https://www.gtplanet.net/forum/threads/gt6-update-list-1-22-final.321054/>

### Saves, trophies, model/track extraction

- GTPlanet, “The GT6 Save Editor Thread”: <https://www.gtplanet.net/forum/threads/the-gt6-save-editor-thread.410910/>
- ResHax, “GT6 (Gran Turismo 6) [PS3]” (id-daemon car tool): <https://reshax.com/topic/4960-gt6-gran-turismo-6-ps3/>
- ResHax, “Gran Turismo 6 (Track models)”: <https://reshax.com/topic/18260-gran-turismo-6-track-models/>
- ResHax, GT6RAR download: <https://reshax.com/files/file/1138-gt6rar/>

### Prior art

- sp00nznet, **GT5P** (MIT): <https://github.com/sp00nznet/GT5P>
  - Progress log: <https://github.com/sp00nznet/GT5P/blob/main/docs/progress.md>
- sp00nznet, **ps3recomp** (MIT): <https://github.com/sp00nznet/ps3recomp>
- Recomp.fyi (Denarmo GT6 row, repo missing): <https://recomp.fyi/>
- Adrenaline forum, “PC Ports (Recomps e afins)” page 4 (Denarmo deleted, no one ran it): <https://forum.adrenaline.com.br/threads/pc-ports-recomps-e-afins.721752/page-4>
- TechPowerUp, “Gran Turismo Sport Runs Natively on PC Through Unofficial Port” (RyGT, GTS not GT6): <https://www.techpowerup.com/353814/gran-turismo-sport-runs-natively-on-pc-through-unofficial-port>
- Reddit r/decomps, “The Gran Turismo Sport PC Port seems to have been taken down”: <https://www.reddit.com/r/decomps/comments/1xfdfzd/the_gran_turismo_sport_pc_port_seems_to_have_been/>
- GT4 decomp/native projects (PS2, methodology only): [gustavocanepa/gt4-decomp](https://github.com/gustavocanepa/gt4-decomp), [MrGoodGuy2144/OpenGT4](https://github.com/MrGoodGuy2144/OpenGT4), [moesuito/gt4-staticrecomp](https://github.com/moesuito/gt4-staticrecomp).
