# PAMF intro movie: why the extracted `.pam` is not plain PAMF, and the playback fix

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00; `work/bin/EMAIN.elf`; `work/gt6_vol/movies/*.pam`; `work/gt6_vol/database/gt6/menudb.dat`
**Scope:** identify the movie-layer format/encryption, locate the key and parser path, compare the runtime's HLE against the RPCS3 oracle, and rank a fix for intro playback.
**Read-only work:** no build and no `gt6.exe` run; no game data, generated code, or `third_party` file was edited. GTToolsSharp and PAMFtool were run only as separate processes on **copies** under `work/pamf_test/`. No key values are published in this document.

**Relation to earlier reports:** complements `docs/analysis/rpcs3-oracle.md` (the oracle plays the intro) and `docs/research/gt6-formats-and-tooling.md` (movies listed as encrypted PAMF). This report supplies the missing format/decryption proof and the runtime gap. An independent check (`docs/analysis/pamf-intro-check.md`) reached the same movie-layer Salsa20 conclusion and verified a standalone remux; this report adds the exact EMAIN offsets, the PAMF 0041 layout, and the HLE gap list.

---

## 0. Verdict

1. **The extracted `.pam` is not PFS-encrypted, mis-extracted, or wrapped.** GTToolsSharp correctly decrypts the PDIPFS/GT.VOL layer. What remains is a **second, movie-layer Salsa20 stream cipher** applied by GT6 before the data is handed to `cellPamf`. The PFS `FileInfoFlags` have no "movie encrypted" bit; the per-movie key is content metadata in `menudb.dat`, table `t_movie`, column `Key`.
2. **The movie keys are in the user's own `menudb.dat`.** `GTToolsSharp cryptmovie` first unwraps each 32-byte `t_movie.Key` with the public `GT5P_TVBASEKEY` (Salsa20, zero IV), then Salsa20-decrypts the file with the unwrapped key and zero IV. This produces a real `PAMF0041` header. Using the `t_movie.Key` directly, without the unwrap, does **not** produce `PAMF`.
3. **RPCS3's HLE `cellPamf` does not decrypt.** Its source requires the literal `PAMF` magic at offset 0 and only parses the header. The oracle log shows `cellPamfGetHeaderSize2(... fileSize=0x14ED5000 ...)` and then valid stream queries for the 351,096,832-byte opening movie. Therefore the **guest side** (game code or a guest-loaded module) must decrypt the movie before `cellPamf` sees it; the emulator only needs a correct PAMF parser/demuxer. The Base64 string matching the public `GT5P_TVBASEKEY` is present in `EMAIN.elf` at file offset `0xFA0A18`, immediately after a PEM RSA private-key block, so the guest side has what it needs for the unwrap.
4. **The actual runtime blocker at the movie stage is the HLE, not the disc file.** `third_party/ps3recomp/libs/codec/cellPamf.c` uses a fabricated header layout: it reads the stream table at `0x10` and the stream count at `0x14`, which are `psmf_marks_offset` (0) and `psmf_marks_size` (0). For the opening movie it would report **0 streams**, `muxRate=0`, and `ep_count=0`. `cellDmux.c` is a stub that presents the whole input buffer as one access unit, and the runtime does not register `cellDmuxQueryAttr`, `cellDmuxOpenEx`, `cellDmuxQueryEsAttr`, or `cellDmuxResetEs`, all of which GT6 imports and calls.
5. **Offline playback already works** with open-source tools: GTToolsSharp (MIT, decryption as a separate process) -> PAMFtool v1.3 (GPLv3, demux; **no** encryption support) -> FFmpeg (H.264 and ATRAC3+ decoders; **no** PAMF demuxer). `PAMFtool` demuxed the opening to a 339,175,131-byte H.264 stream, a 2,208,956-byte 2-channel ATRAC3+ stream, and a 5,477,564-byte 6-channel ATRAC3+ stream; FFmpeg decoded a frame and 2 seconds of audio successfully.
6. **Smallest clean-room runtime path:** fix the `cellPamf` layout and add the missing NIDs, implement a real PAMF pack/PES demuxer behind the generic `cellDmux` API, and feed the existing `cellVdec`/`cellAdec` FFmpeg paths. Do not copy GPL PAMFtool code into the MIT runtime; use it as a separate-process oracle/reference. A movie-layer decryptor is only a fallback if guest decryption fails.

**Feasibility.** Offline decryption -> demux -> decode is proven and can be delivered now. In-engine playback has two independent prerequisites: **(a)** the port must reach the movie-player path (`MovieRoot` / `play_movie`) with the PFS read-through and render loop alive, and **(b)** the HLE gaps in section 5 must be fixed. This report proves (b) is currently broken; it does not prove (a) is reached. The independent native check (`docs/analysis/first-visible-ui-check.md`) reports the port is still at the earlier boot/presents stage (black, `draws: 0`), so the HLE work should be staged after the boot/PFS path reaches the movie script. The offline pipeline is the near-term deliverable; the HLE fix is the next step once the movie path is exercised.

---

## 1. Evidence: files, sizes, heads, and TOC

### 1.1 All 11 movie files are random-headed and 0x800-aligned

`work/gt6_vol/movies/` contains 11 `.pam` files. Every size is an exact multiple of `0x800` (PAMF's 2048-byte sector), and every first 16 bytes look random and differ from every other file. There is no `PAMF` magic anywhere in the heads.

| File | Size | Size % 0x800 | First 16 bytes (hex) |
|---|---:|---:|---|
| `tv_10005_678632543.pam` | 53,909,504 | 0 | `2c 47 1f da 90 61 4f 2e 86 da 82 7e d5 fc 97 59` |
| `tv_10006_199556544.pam` | 351,096,832 | 0 | `85 31 8c d8 3c 12 7f b6 87 ec c9 31 f2 84 9d 74` |
| `tv_10010_224644567.pam` | 38,031,360 | 0 | `96 14 e7 f5 c5 b7 77 84 0c 17 7a 31 87 40 21 7c` |
| `tv_10013_787414570.pam` | 42,977,280 | 0 | `19 2c e4 4a 60 bb 10 5e c3 bf 5a 0c cd 24 4e 49` |
| `tv_10014_308338571.pam` | 25,454,592 | 0 | `f5 0b 45 0a 59 a0 f2 24 92 74 ff 62 b8 3b e3 4e` |
| `tv_10015_829261572.pam` | 96,727,040 | 0 | `e5 25 2b cc 76 b0 3f ba 3c 22 40 82 e7 eb 54 ee` |
| `tv_10016_350185573.pam` | 78,903,296 | 0 | `b4 9e 4c e0 b8 4e d6 c9 b0 ff 20 95 78 67 58 ff` |
| `tv_10017_871108574.pam` | 1,317,222,400 | 0 | `47 1f cf 8f fa db 01 17 25 40 66 90 5d 60 b1 f0` |
| `tv_10021_896196597.pam` | 33,550,336 | 0 | `66 90 00 4d 41 7c 30 40 5c ea 9d c8 bb d2 59 76` |
| `tv_10022_417120598.pam` | 43,091,968 | 0 | `51 c1 9a ca 49 86 94 d7 42 2d bb 85 2e 77 83 26` |
| `tv_10023_938043599.pam` | 32,960,512 | 0 | `91 cf 4f f7 d7 fe 75 4d 1b 5c 32 49 45 06 73 84` |

The earlier "mod 16 == 0" observation is only a consequence of the 0x800 sector alignment; it is not evidence of a 16-byte block cipher. Salsa20 is a byte-oriented stream cipher, so there is no repeated-block or block-padding signature to look for. A 1 MiB sample of `tv_10017` had 65,536 unique 16-byte blocks and zero duplicates, which rules out ECB but is equally consistent with Salsa20/CTR/CBC.

### 1.2 The PFS TOC has no movie-encryption flag

`VolumeTOC.bin` (844,860 bytes) holds the volume's string table. At file offset `0x1d5a4` it lists the movie base names, each prefixed by a length byte:

```
... 12 'tv_10005_678632543' 12 'tv_10006_199556544' 12 'tv_10010_224644567'
    12 'tv_10013_787414570' 12 'tv_10014_308338571' 12 'tv_10015_829261572'
    12 'tv_10016_350185573' 12 'tv_10017_871108574' 12 'tv_10021_896196597'
    12 'tv_10022_417120598' 12 'tv_10023_938043599' ...
```

The TOC stores the names **without** the `movies/` prefix. The PFS `FileInfoFlags` enum in GTToolsSharp has only `Uncompressed=0x00`, `Compressed=0x01`, `PDIZIPCompressed/CustomSalsaCrypt=0x02`, and four unknown bits; there is no per-file "movie key" or "encrypted movie" flag. An independent `GTToolsSharp listfiles` run on the same volume reported all 11 movie entries as `Flags: Uncompressed` (opening `tv_10006` at FileIndex 90 / `K/IP`, ending `tv_10017` at FileIndex 29857 / `5R/49`). GTToolsSharp's `PFSVolumeUnpacker.cs` applies a custom Salsa layer only on the `IsGT5PDemoStyle` path; GT6 takes the normal path, which decrypts the PFS volume data and inflates if needed, then writes the file. That is exactly why the extracted movie still has the movie-layer stream cipher.

`tv_10005` is present in the TOC but absent from `t_movie`; see section 8.

### 1.3 `menudb.dat` -> `t_movie` -> per-movie key

`work/gt6_vol/database/gt6/menudb.dat` is Salsa20-wrapped. Using the public `MENUDB_KEY` constant from GTToolsSharp's `KeysetStore.cs` on a **copy** produced a normal SQLite 3 database (`53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33`). The `t_movie` table contains 10 rows and the key column is a 44-character Base64 string (redacted here):

| id | Name | FileName | Width | Height | StreamID | Duration |
|---:|---|---|---:|---:|---:|---:|
| 1 | OPENING | `tv_10006_199556544` | 1920 | 1080 | 10006 | 136 |
| 2 | ENDING | `tv_10017_871108574` | 1920 | 1080 | 10017 | 513 |
| 3 | PHOTO_GEMA_SOLAR | `tv_10010_224644567` | 960 | 544 | 10010 | 0 |
| 4 | PHOTO_SIRACUSA_DAY | `tv_10013_787414570` | 960 | 544 | 10013 | 0 |
| 5 | PHOTO_SIRACUSA_NIGHT | `tv_10014_308338571` | 960 | 544 | 10014 | 0 |
| 6 | PHOTO_RONDA | `tv_10015_829261572` | 960 | 544 | 10015 | 0 |
| 7 | PHOTO_CAC_NIGHT | `tv_10016_350185573` | 960 | 544 | 10016 | 0 |
| 8 | PHOTO_MOON | `tv_10021_896196597` | 960 | 544 | 10021 | 0 |
| 9 | PHOTO_MOON_02 | `tv_10022_417120598` | 960 | 544 | 10022 | 0 |
| 10 | PHOTO_MOON_03 | `tv_10023_938043599` | 960 | 544 | 10023 | 0 |

The `Key` column is the only per-movie secret in the game data. It is **not** the final Salsa20 key: it is itself wrapped with the public `GT5P_TVBASEKEY`.

### 1.4 Decryption proof

On a copy of `tv_10014` (smallest movie, 25,454,592 bytes):

* `GTToolsSharp cryptsalsa -k <t_movie.Key>` (direct key, no unwrap) produced a still-random head:
  `b1 46 5a 0d a4 21 1c ec ee 1c 87 03 7b 91 9a b4 ...`
* `GTToolsSharp cryptmovie -k <same t_movie.Key>` (unwraps the key with `GT5P_TVBASEKEY`, then decrypts the file) produced:

```
50 41 4d 46 30 30 34 31 00 00 00 01 00 00 30 8c   PAMF0041......0.
```

For the opening movie `tv_10006`:

```
50 41 4d 46 30 30 34 31 00 00 00 02 00 02 9d a8   PAMF0041........
```

This is a real `PAMF` version `0041` header. The raw-key test proves the unwrap is required; the successful unwrap proves the file is a single Salsa20 stream, not a wrapper or a PFS-encrypted file.

`PAMFtool v1.3 -info` accepts the decrypted file and reports the expected structure (section 4). The tool is GPLv3 and has **no** encryption path (the only `key` identifiers in its VB.NET source are dictionary keys, not cryptographic keys), so it must be fed the decrypted file.

---

## 2. Evidence: RPCS3's HLE has no decryption

The oracle log `work/rpcs3_oracle/rpcs3_input.log` shows the movie path at `0:00:38.748`:

```
line 87513: cellPamf: cellPamfGetHeaderSize2(pAddr=*0xd0176180, fileSize=0x14ed5000,
                                               attribute=0x0, pSize=*0x428126b8)
...
line 87552: cellDmux: cellDmuxQueryAttr(...)
line 87554: cellDmux: cellDmuxOpenEx(...)
line 87558: cellDmuxPamf: _CellDmuxCoreOpOpen(...)
line 8756x: cellVdec: cellVdecQueryAttrEx(...) / cellAdec: cellAdecOpenEx(...)
```

`0x14ED5000` is exactly 351,096,832, the size of `tv_10006_199556544.pam`. The calls proceed to stream queries and decoder setup, and the oracle's `frames_input/frame_045s.png` shows the intro playing.

RPCS3's `cellPamf.cpp` (`pamfVerifyMagicAndVersion`) requires:

```cpp
if (pAddr->magic != std::bit_cast<be_t<u32>>("PAMF"_u32))
    return CELL_PAMF_ERROR_UNKNOWN_TYPE;
```

and `pamfGetHeaderAndDataSize` computes `header_size = pAddr->header_size * 0x800`, `data_size = pAddr->data_size * 0x800`. There is no decryption in `cellPamf.cpp` or `cellDmuxPamf.cpp`. Therefore the guest must have decrypted the movie before `cellPamf` sees it. This also means the runtime's job is **format parsing and demuxing**, not movie decryption, as long as the guest decryption path works under the recompiled code.

The log also proves GT6 uses the **generic `cellDmux` API with a PAMF backend** (`cellDmuxOpenEx`), not the standalone `cellDmuxPamf` entry points only. The `_CellDmuxCoreOp*` calls are RPCS3's internal PAMF implementation, not guest imports.

---

## 3. Evidence: `EMAIN.elf` search (no keys published)

`work/bin/EMAIN.elf` is a fully linked PPU ELF; its main segments map `vaddr = file_offset + 0x10000` (segment 0: file `0x0`, vaddr `0x10000`; segment 1: file `0x1400000`, vaddr `0x1410000`). Offsets below are **file offsets**, with the corresponding vaddr where useful.

### 3.1 What is present

| Item | File offset | Evidence |
|---|---:|---|
| `cellPamf` module name | `0xf8ac64` | import-name table (`cellDmux` at `0xf8ac54`) |
| `cellPamf` import stubs | `0xf90b88`..`0xf90f40` | RPCS3 log: `cellPamfEpIteratorGetEp -> 0xf90b88`, ..., `cellPamfReaderGetPresentationEndTime -> 0xf90f40` |
| `N6PDIEXT13PAMFAudioPortE` (RTTI) | `0x10683fa` | native PAMF audio port class |
| `N6PDIEXT10PAMFStreamE` (RTTI) | `0x106841a` | native PAMF stream class |
| `movies/tv_10006_199556544.pam` | `0xfa1230` | hardcoded opening path |
| `movies/tv_10017_871108574.pam` | `0xfa1250` | hardcoded ending path |
| `decodeContentsKey` | `0x10577f0` | script-visible method name |
| `setKey` | `0x1042578`, `0x1077f18` | movie-player property names |
| `mBlob` / `encrypt` / `decrypt` | `0x1079360`..`0x1079438` | script crypto builtin names (`encrypt.decrypt` and `PDISTD5mBlob`) |
| PEM RSA private-key block | `0xFA0698`..`0xFA09FA` | `-----BEGIN RSA PRIVATE KEY-----` .. `-----END RSA PRIVATE KEY-----`; value redacted |
| Base64 string matching public `GT5P_TVBASEKEY` | `0xFA0A18` (44 chars) | the unwrap key used by `cryptmovie`; value redacted |

The hardcoded opening/ending paths are important: GT6 knows the exact movie names in the executable, independently of the `MovieRoot.ad` script's SQL query. The Base64 base-key string sits next to `NP_PASSPHRASE_SIZE`, `NP_SIGNATURE_SIZE`, `NPWR04712_00_NP_PASSPHRASE`, and `NPWR04712_00_NP_SIGNATURE`, i.e. a PSN/content-key blob. The exact function that consumes it was not disassembled, but the storage question is resolved.

### 3.2 What is absent (or present only as text)

* **No `PAMF` magic literal in code.** The only `PAMF` ASCII hits are the two mangled RTTI names; the magic comparison lives in the HLE/system parser, not in a guest string.
* **No complete Salsa20 sigma constant.** Searching for `expand 32-byte k` and for the four sigma words `0x61707865, 0x3320646e, 0x79622d32, 0x6b206574` in both endiannesses found no complete set. Only the four bytes `65 78 70 61` (`"expa"`) appear at several unrelated offsets. This does not prove Salsa20 is absent (the core may be in a PRX or build the state from immediates), but no self-contained Salsa20 core was located in `EMAIN.elf`.
* **No AES movie cipher.** The 230 `AES` string hits are `GTSound::AESFileLoader`, `AESParameter`, and `AESSlot`—the engine-audio “AES” subsystem, not Advanced Encryption Standard. There is no AES key schedule or Rijndael naming.
* **The base key is present, but as text, not raw bytes.** The 44-character Base64 string at `EMAIN.elf` file offset `0xFA0A18` is exactly the public `GT5P_TVBASEKEY`; the raw 32-byte key is not present. The per-movie `t_movie.Key` values are only in the user's decrypted `menudb.dat`.

### 3.3 Where the game's key handling is visible

The boot script `work/gt6_vol/projects/gt6/boot/boot.adc` contains:

* the 32-byte value matching GTToolsSharp's public `MENUDB_KEY` at file offset **`0x7e8`** (the surrounding strings are `initMenuDB`, `MENUDB`, `/database/gt6/menudb.dat`);
* the `MovieRoot.ad` strings at `0x5d94`..`0x5ec3`: `MovieFace`, `play_movie`, `stop_movie`, `end_movie`, `SELECT * FROM t_movie WHERE Name = 'OPENING'`, `/movies/`, `FileName`, `.pam`, `decodeContentsKey`, `setKey`.

`play_movie.adc` contains the same method names (`decodeContentsKey` at `0x791`, `setKey` at `0x7ab`, `setVideoSize`, `/movies/`, `FileName`, `load`, `unload`). The script therefore:

1. reads `t_movie.Key` for the requested movie,
2. calls `decodeContentsKey` (the unwrap step),
3. calls `setKey` (hands the final key to the native PAMF movie player),
4. loads and plays the decrypted stream.

### 3.4 Direct guest `cellPamf` call sites

A branch scan of the executable segments for `b`/`bl` targets equal to the import stubs found one tightly clustered native movie player plus a second consumer:

| Guest call site (vaddr) | Import stub called |
|---|---|
| `0x7FCD60` | `cellPamfReaderInitialize` |
| `0x7FDDCC` | `cellPamfGetHeaderSize2` |
| `0x7FDE00` | `cellPamfGetStreamOffsetAndSize` |
| `0x7FDF50` | `cellPamfVerify` |
| `0x7FDF78` | `cellPamfReaderGetNumberOfStreams` |
| `0x7FDF8C`, `0x7FDF9C` | `cellPamfReaderGetNumberOfSpecificStreams` |
| `0x7FDFF0` | `cellPamfReaderSetStreamWithIndex` |
| `0x7FE000` | `cellPamfReaderGetStreamTypeAndChannel` |
| `0x7FE00C` | `cellPamfReaderGetPresentationStartTime` |
| `0x7FE018` | `cellPamfReaderGetPresentationEndTime` |
| `0x7FE020` | `cellPamfReaderGetMuxRateBound` |
| `0x7FE0C8`, `0x7FE164` | `cellPamfReaderGetEsFilterId` |
| `0x7FE0E0`, `0x7FE17C` | `cellPamfReaderGetStreamInfo` |
| `0x7FEA50` | `cellPamfReaderSetStreamWithTypeAndIndex` |
| `0x7FEA58` | `cellPamfReaderGetNumberOfEp` |
| `0x7FEA70` | `cellPamfReaderGetEpIteratorWithTimeStamp` |
| `0x7FEA84` | `cellPamfEpIteratorGetEp` |
| `0x7FEAB4` | `cellPamfEpIteratorMove` |
| `0xBD4E4C`, `0xBD4E68` | `cellPamfReaderGetPresentationStartTime` / `EndTime` (second consumer) |

The `0x7FCD60..0x7FEAB4` cluster is the native PAMF movie player; the `0xBD4E4C`/`0xBD4E68` pair is a second consumer, probably UI/metadata. This is direct evidence that the PAMF parsing and key handling live in `EMAIN.elf`, not only in a system module. The base-key string at `0xFA0A18` is in the same image; the exact instruction that reads it was not traced.

---

## 4. PAMF 0041 layout (exact, from the opening movie)

All values are big-endian. This is the layout a correct `cellPamf` must use; it is **not** the layout currently in `third_party/ps3recomp/libs/codec/cellPamf.c`.

### 4.1 Header

| Offset | Size | Field | Opening value |
|---:|---:|---|---|
| `0x00` | 4 | magic `PAMF` | `50 41 4d 46` |
| `0x04` | 4 | version | `30 30 34 31` (`0041`) |
| `0x08` | 4 | `header_size` in 0x800 sectors | `2` -> 0x1000 |
| `0x0C` | 4 | `data_size` in 0x800 sectors | `0x29DA8` -> 351,092,736 |
| `0x10` | 4 | `psmf_marks_offset` | 0 |
| `0x14` | 4 | `psmf_marks_size` | 0 |
| `0x18` | 4 | `unk_offset` | 0 |
| `0x1C` | 4 | `unk_size` | 0 |
| `0x20` | `0x30` | reserved (zero) | 0 |
| `0x50` | | `PamfSequenceInfo` | |

`header_size * 0x800 + data_size * 0x800 = 0x1000 + 0x14ED4000 = 0x14ED5000` = 351,096,832 = file size. This exact sum is what `cellPamfVerify` checks.

### 4.2 Sequence info at `0x50`

| Offset | Size | Field | Opening value |
|---:|---:|---|---|
| `0x50` | 4 | `size` (excluding this field) | `0xC4` = 196 |
| `0x54` | 2 | reserved | 0 |
| `0x56` | 2 | `start_pts_high` | 0 |
| `0x58` | 4 | `start_pts_low` | `0x15CDE` = 89,310 (0.9923 s) |
| `0x5C` | 2 | `end_pts_high` | 0 |
| `0x5E` | 4 | `end_pts_low` | `0xBC4825` = 12,339,237 (137.1026 s) |
| `0x62` | 4 | `mux_rate_bound` (x50 B/s) | `0x1D4C0` = 120,000 (48.00 Mbps) |
| `0x66` | 4 | `std_delay_bound` (90 kHz) | `0x107AC` = 67,500 (0.75 s) |
| `0x6A` | 4 | `total_stream_num` | 3 |
| `0x6E` | 1 | reserved | 0 |
| `0x6F` | 1 | `grouping_period_num` | 1 |
| `0x70` | | `PamfGroupingPeriod` | |

### 4.3 Grouping period at `0x70` and group at `0x82`

| Offset | Size | Field | Opening value |
|---:|---:|---|---|
| `0x70` | 4 | `size` | `0xA4` = 164 |
| `0x74` | 2 | `start_pts_high` | 0 |
| `0x76` | 4 | `start_pts_low` | `0x15CDE` |
| `0x7A` | 2 | `end_pts_high` | 0 |
| `0x7C` | 4 | `end_pts_low` | `0xBC4825` |
| `0x80` | 1 | reserved | 0 |
| `0x81` | 1 | `group_num` | 1 |
| `0x82` | 4 | `group.size` | `0x92` = 146 |
| `0x86` | 1 | reserved | 0 |
| `0x87` | 1 | `group.stream_num` | 3 |
| `0x88` | 3*48 | three `PamfStreamHeader`s | see below |

### 4.4 Stream headers (48 bytes each, from `0x88`)

| Field offset | Size | Field | Stream 0 (AVC) | Stream 1 (ATRAC3+) | Stream 2 (ATRAC3+) |
|---:|---:|---|---|---|---|
| `+0x00` | 1 | `stream_coding_type` | `0x1B` | `0xDC` | `0xDC` |
| `+0x01` | 3 | reserved | 0 | 0 | 0 |
| `+0x04` | 1 | `stream_id` | `0xE0` | `0xBD` | `0xBD` |
| `+0x05` | 1 | `private_stream_id` | `0x00` | `0x00` | `0x01` |
| `+0x06` | 2 | `p_std_buffer` | `0x333B` | `0x2014` | `0x2014` |
| `+0x08` | 4 | `ep_offset` | `0x118` | 0 | 0 |
| `+0x0C` | 4 | `ep_num` | 191 | 0 | 0 |
| `+0x10` | 32 | codec-specific info | see below | `00 00 02 01...` | `00 00 06 01...` |

AVC codec info (stream 0): profile `0x64` = High, level `0x29` = 4.1, `x2=0xC4` (frame_mbs_only=1, video_signal_info=1, frame_rate_info_raw=4 -> SDK code 3 = 30000/1001), aspect `1` (1:1), SAR 0/0, horizontal `60*16=1920`, vertical `68*16=1088`, crop L/R/T/B = `0/0/0/4` -> displayed 1920x1080, CABAC=1, deblock=0, max_mean_bitrate=30.

Audio codec info: `00 00 <channels> 01` — 2 channels and 6 channels, both 48 kHz. There is no per-stream EP table for audio (`ep_num=0`).

### 4.5 Entry-point table

The AVC stream's `ep_offset=0x118` is a **file offset**, not relative to the header or group. Each `PamfEpHeader` is 12 bytes:

| Offset | Size | Field |
|---:|---:|---|
| `+0x00` | 2 | `value0`: 2 bits `index_n`, 1 bit unused, 13 bits `nThRefPictureOffset` (units of 0x800) |
| `+0x02` | 2 | `pts_high` (always 0) |
| `+0x04` | 4 | `pts_low` (90 kHz) |
| `+0x08` | 4 | `rpnOffset` (units of 0x800) |

For the opening: 191 entries, first `pts=0x15F90` (1.000 s, `rpn=0`), last `pts=0xBB5D89` (136.435 s, `rpn=0x14EC8800`). The EP table ends before the first pack at `0x1000`; it fits inside the 2-sector header.

### 4.6 Pack layer

The data area starts at `header_size` (`0x1000`) and is a sequence of 2048-byte sectors. Each sector starts with an MPEG-2 PS pack header:

```
0x1000: 00 00 01 BA 44 00 0D 50 54 91 07 53 ...
0x1800: 00 00 01 BA 44 00 0D 51 46 41 07 53 ...
```

The first video PES (`00 00 01 E0`) is at `0x10A0`; the first private-stream PES (`00 00 01 BD`) is at `0x180E`. `tools/pamf_info.py --check-packs` verifies that the number of `00 00 01 BA` sector starts equals `data_size / 0x800` (171,432 for the opening).

`PAMFtool -info` output for the opening agrees:

```
PAMF version    : 0041
Header size     : 0x1000 (2 sectors)
Stream size     : 351,092,736 bytes (171432 packs)
Stream #0 AVC (H.264) 1920x1088, crop bottom 4, 29.97 fps, High/4.1, 191 EPs
Stream #1 ATRAC3plus 2ch 48000 Hz
Stream #2 ATRAC3plus 6ch 48000 Hz
```

The decrypted photo movie `tv_10014` is a smaller example: 1 header sector, 12,428 data sectors, one AVC stream 960x544, 12 EPs, duration 10.377 s.

---

## 5. The runtime gap (this is the actual intro fix)

### 5.1 `cellPamf.c` reads the wrong header offsets

`third_party/ps3recomp/libs/codec/cellPamf.c` defines:

```c
#define PAMF_OFF_DATA_OFFSET   0x08
#define PAMF_OFF_DATA_SIZE     0x0C
#define PAMF_OFF_STREAM_TABLE  0x10
#define PAMF_OFF_NUM_STREAMS   0x14
#define PAMF_OFF_PRESENT_START 0x18
#define PAMF_OFF_PRESENT_END   0x1C
#define PAMF_OFF_MUX_RATE      0x20
#define PAMF_OFF_EP_OFFSET     0x24
#define PAMF_OFF_EP_COUNT      0x28
#define PAMF_STREAM_DESC_SIZE  24
```

These do not match the real layout. For the opening file the code would compute:

| Code reads | Real field | Value read | Consequence |
|---|---:|---:|---|
| `dataOffset = be32(0x08)` | `header_size` sectors | 2 | treated as 2 bytes instead of 0x1000 |
| `dataSize = be32(0x0C)` | `data_size` sectors | 0x29DA8 | treated as bytes |
| `streamTableOffset = be32(0x10)` | `psmf_marks_offset` | 0 | all stream descriptors read from offset 0 |
| `numStreams = be16(0x14)` | `psmf_marks_size` (low half) | 0 | **0 streams** |
| `muxRate = be32(0x20)` | reserved | 0 | wrong mux rate |
| `ep_count = be32(0x28)` | reserved | 0 | **0 entry points** |

So `cellPamfReaderGetNumberOfSpecificStreams(20)` returns 0, the game enables no video/audio ES, and the movie cannot start. The parser also assumes 24-byte stream descriptors, while the real `PamfStreamHeader` is 48 bytes (it includes 32 bytes of codec-specific info), and it writes host-endian `u16`/`u32` fields into the guest info struct (the source itself notes the missing swap).

### 5.2 Missing NIDs that GT6 imports

The runtime registers 14 `cellPamf` functions (`gt6/src/gen/ppu_hle_nids.cpp:1734` onward) and 11 generic `cellDmux` functions (`:1322` onward). GT6 imports/calls more. From the oracle log:

**`cellPamf` — 9 imported functions are not registered:**

| NID | Function | Status / evidence |
|---|---|---|
| `0x90FC9A59` | `cellPamfGetHeaderSize2` | yes, first call |
| `0x44F5C9E3` | `cellPamfGetStreamOffsetAndSize` | yes |
| `0xD1A40EF4` | `cellPamfVerify` | yes |
| `0x9AB20793` | `cellPamfReaderGetStreamTypeAndChannel` | yes |
| `0x71DF326A` | `cellPamfReaderGetEsFilterId` | yes |
| `0x28B4E2C1` | `cellPamfReaderSetStreamWithTypeAndIndex` | call site `0x7FEA50` |
| `0x439FBA17` | `cellPamfReaderGetEpIteratorWithTimeStamp` | call site `0x7FEA70` |
| `0x1ABEB9D6` | `cellPamfEpIteratorGetEp` | call site `0x7FEA84` |
| `0x50B83205` | `cellPamfEpIteratorMove` | call site `0x7FEAB4` |

**`cellDmux` — 4 imported functions are not registered:**

| NID | Function | Status / evidence |
|---|---|---|
| `0xA2D4189B` | `cellDmuxQueryAttr` | yes |
| `0xF6C23560` | `cellDmuxOpenEx` | yes |
| `0x02170D1A` | `cellDmuxQueryEsAttr` | yes |
| `0x21D424F0` | `cellDmuxResetEs` | imported |

The runtime has `cellDmuxOpen` (the old API, NID `0x68492DE9`), but GT6 does not import it; it imports `cellDmuxOpenEx`. It also has `cellDmuxEnableEs`, `SetStream`, `GetAu`, `PeekAu`, `ReleaseAu`, `FlushEs`, `ResetStream`, `ResetStreamAndWaitDone`, and `DisableEs`, but those alone cannot replace the missing setup/query calls.

### 5.3 `cellDmux.c` is a one-AU stub

`cellDmuxSetStream` does not parse MPEG-PS. It presents the **entire input buffer** as one access unit per enabled ES:

```c
es->currentAu.auAddr = streamAddr;
es->currentAu.auSize = streamSize;
es->currentAu.pts = (u64)dmux->auSeqNo * 3003;
```

For a 351 MB AVC movie, `cellVdec` would receive one 351 MB "AU" and no frame boundaries or PTS. It cannot decode the intro. A real PAMF demuxer must:

1. walk each 2048-byte pack (`00 00 01 BA`),
2. parse the pack header and the PES packets (`00 00 01 E0` video, `00 00 01 BD` private audio),
3. accumulate AVC access units (AUD/NAL boundaries) and ATRAC3+ frames,
4. deliver one AU per callback with PTS/DTS and `isRap` from the PAMF EP table.

`cellVdec.c` already has a libavcodec path (`PS3RECOMP_FFMPEG_RUNTIME`, `vdec_ffmpeg.c`) that decodes complete AUs and queues pictures in display order; `cellAdec` has an ATRAC3+ path (`cellAdecAtrac3p.c`, `atrac3plus*.cpp`). Those paths are not the blocker once the demuxer produces real AUs.

### 5.4 What already works

* `cellVdecQueryAttrEx` / `cellVdecOpenEx` / `StartSeq` / `EndSeq` / `Close` are exercised by the oracle and the runtime has a `cellVdec` implementation with an FFmpeg path.
* `cellAdecQueryAttr` / `OpenEx` / `OpenExt` / `StartSeq` / `EndSeq` / `Close` are exercised and the runtime has ATRAC3+ support.
* The game's own decryption path is exercised by the oracle; the runtime does not need to decrypt if that guest code is recompiled and reaches the same data.

---

## 6. Tooling and open-source landscape

| Tool | License | What it does | Can it handle GT6 movies? |
|---|---|---|---|
| **GTToolsSharp 5.3.5** | MIT | GT.VOL/PDIPFS unpack/repack, `cryptmovie` (Salsa20 key unwrap + file decrypt), `cryptsalsa` | **Yes**, on the user's own data; separate process. Its Salsa20 implementation is in the `PDTools` submodule, which is off-limits for code reuse. |
| **PAMFtool v1.3** | **GPLv3** | PAMF header parse, demux AVC/M2V/ATRAC3+/LPCM/AC3, mux | **Yes after decryption**; **no** encryption support. We verified a full demux of `tv_10006`. |
| **FFmpeg 9.0.2** | LGPL/GPL depending on build; the bundled `essentials_build` is **GPL** | H.264 and ATRAC3+ decoders; mux to MP4/MKV | **No PAMF demuxer**; `-demuxers` has no `pamf`, and the file is misdetected as Netpbm PAM. Use it on PAMFtool's demuxed streams. |
| **vgmstream** | ISC-like | Game audio formats | **No PAMF container parser** in `src/meta`; the FFmpeg backend also has no PAMF. It can play the demuxed `.at3` streams. |
| **RPCS3** | GPLv2 | Oracle, HLE `cellPamf`/`cellDmuxPamf` reference | **Yes** (the oracle plays the intro). Reference only; do not link into the MIT runtime without GPL compliance. |

**Legal/licensing constraints**

* GTToolsSharp is MIT, but its `PDTools` submodule is explicitly off-limits for this project. Do not copy `PDTools.Crypto.Salsa20` into the runtime. Salsa20 itself is a public cipher specification; a clean-room implementation from Bernstein's spec is unencumbered.
* PAMFtool is GPLv3. Keep it as a **separate executable** for offline demux/verification. Do not link or copy its VB.NET code into the MIT runtime. The PAMF container facts (offsets, start codes, EP layout) are format facts, not code.
* RPCS3 is GPLv2. Use its source to understand the API behavior, not as linked code.
* Do not redistribute game data or key values. `t_movie.Key` and `menudb.dat` stay on the user's machine. The public `MENUDB_KEY`/`GT5P_TVBASEKEY` constants are already in open-source tooling; this report does not reproduce their values.

---

## 7. Ranked plan

### P-1 — Reach the movie-player path (prerequisite, separate workstream)

Before the HLE fixes can be exercised, the native port must load the boot/presents scripts and reach `MovieRoot` / `play_movie` with the PFS read-through and render loop alive. The independent native check reports the port is still black at the earlier boot/presents stage (`draws: 0`), so do not expect the HLE changes alone to produce the intro. Track this as the boot/PFS workstream; the PAMF work below is staged for when the movie script runs.

### P0 — Fix `cellPamf` parsing and register the missing NIDs (hours; unblocks stream discovery)

1. Replace the `PAMF_OFF_*` constants with the layout in section 4:
   * `header_size = be32(0x08) * 0x800`, `data_size = be32(0x0C) * 0x800`;
   * `seq_info` at `0x50`, `grouping_period` at `0x70`, `group` at `0x82`, streams at `0x88`;
   * 48-byte stream headers, not 24;
   * `ep_offset`/`ep_num` from the stream header (`+0x08`/`+0x0C`), 12-byte EP entries;
   * `mux_rate_bound = be32(0x62) & 0x3FFFFF`;
   * `start_pts = (be16(0x56) << 32) | be32(0x58)`, `end_pts = (be16(0x5C) << 32) | be32(0x5E)`.
2. Convert `CellPamfAvcInfo`/audio info fields to guest big-endian before writing them; do not write host-endian `u16`/`u32`.
3. Register and implement the `cellPamf` NIDs in section 5.2. The first six are enough for the observed movie path; the three EP-iterator functions are needed for seeking/metadata.
4. Validate with `tools/pamf_info.py` on a decrypted copy: the runtime log should print 3 streams, `1920x1088`/crop 4, `High/4.1`, 48 kHz 2ch+6ch, 191 EPs, and `mux=120000`.
5. Do not change the PFS/volume layer; the extracted file is already PFS-decrypted.

### P1 — Implement the generic `cellDmux` PAMF backend (1–2 days; unblocks AUs)

1. Add `cellDmuxQueryAttr`, `cellDmuxOpenEx`, `cellDmuxQueryAttr2` (if called internally), and `cellDmuxQueryEsAttr` with the signatures GT6 uses; keep the existing `cellDmuxEnableEs`/`SetStream`/`GetAu`/`ReleaseAu`/`FlushEs`/`Close` behavior.
2. In `cellDmuxSetStream`, parse the PAMF pack layer:
   * each 2048-byte sector begins with `00 00 01 BA`; the pack header is 14 bytes (MPEG-2);
   * PES packets begin with `00 00 01 <stream_id>`; video is `0xE0`, private audio is `0xBD` with sub-stream id in the PES header;
   * AVC: group NAL units into one access unit per picture; use the PAMF EP table for `isRap`/PTS where available;
   * ATRAC3+: one frame per PES payload after the 8-byte ATS frame header (`0x0FD0` sync, size, reserved); preserve PTS. PAMFtool's `Atrac3PlusAuStripper` is the reference for the frame boundary.
3. Deliver one `CELL_DMUX_ES_MSG_TYPE_AU_FOUND` per AU with the correct address/size/PTS/DTS/`isRap`. Do **not** present the whole buffer as one AU.
4. Keep the demuxer state per ES; handle `ResetStream`, `ResetEs`, `FlushEs`, and `ReleaseAu` without leaking or reusing stale AUs.

### P2 — Validate the decode path (hours)

1. Run the runtime against the decrypted opening copy or the original disc (the guest should decrypt at runtime). Check `cellVdec` receives ~4,080 video AUs and `cellAdec` receives ATRAC3+ frames.
2. Verify 1920x1080 output (crop bottom 4 from 1088), 29.97 fps, and 2ch/6ch selection.
3. If video is black but AUs are present, inspect `cellVdec`'s FFmpeg path and the `CellVdecPicItem` format/stride; the source already has a decoder path, so this is likely a format/PTS issue, not a missing decoder.
4. Use the RPCS3 oracle frames (`work/rpcs3_oracle/frames_input/frame_045s.png`) as the visual reference.

### P3 — Fallback movie-layer decryptor (conditional; 1 day)

Only if the recompiled guest code cannot perform the `decodeContentsKey` unwrap in practice (for example, the native consumer of the `0xFA0A18` Base64 string is not reached):

* implement Salsa20 from the public spec (not PDTools) in a clearly isolated module;
* read the per-movie key from the user's decrypted `menudb.dat` `t_movie.Key`;
* unwrap with the public `GT5P_TVBASEKEY` only if the user's game data requires it, behind a configuration flag;
* never bundle keys or decrypted game data; keep this path off by default and document the legal constraints.

Do **not** pre-decrypt the game's `.pam` files in place. If a private working copy is needed for testing, keep it under `work/` and do not redistribute it.

### P4 — Seek/iterator APIs (hours, only if needed)

Implement `cellPamfReaderGetEpIteratorWithTimeStamp`, `cellPamfEpIteratorGetEp`, `cellPamfEpIteratorMove`, `cellPamfReaderGetEpWithIndex`, and `cellPamfReaderGetEpWithTimeStamp` using the 12-byte EP entries and `pamfEpUnpack` semantics (RPCS3's `cellPamf.cpp` is the behavioral reference). The captured 136-second run did not call them, so they are lower priority than P0/P1.

---

## 8. Open questions and evidence gaps

1. **Base-key consumer path.** The Base64 `GT5P_TVBASEKEY` string is present at `EMAIN.elf` `0xFA0A18` (after a PEM RSA block and NPWR04712 passphrase/signature strings), but the exact native function that reads it and feeds `mBlob`/`decodeContentsKey` was not disassembled. The offline path does not need this; the runtime path only needs it if guest decryption fails.
2. **`tv_10005`.** The TOC lists 11 movies but `t_movie` has 10 rows; `tv_10005_678632543.pam` (53,909,504 bytes) has no `t_movie` entry. It may be an unused/demo/alternate opening. Do not assume it is the intro; `OPENING` is explicitly `tv_10006`.
3. **EP iterators.** The captured run's 39 `cellPamf` calls do not include the iterator functions, but the native player has direct call sites at `0x7FEA50`..`0x7FEAB4`; seek/pause UI likely uses them.
4. **6ch vs 2ch.** The opening has two ATRAC3+ streams (2ch and 6ch). The game's audio settings choose one; the runtime must expose both and let `cellAdec`/the title select.
5. **Guest decryption under recompilation.** The oracle proves GT6 decrypts the movie under RPCS3. The recompiled runtime must execute the same guest `decodeContentsKey`/`setKey` path; the Base64 base key is present in the image, so the remaining risk is whether the native consumer is reached, not whether the key exists. P3 is the fallback.

---

## Appendix A — Reproduction commands (no key values shown)

All commands operate on copies under `work/pamf_test/`; no game data is modified.

```powershell
# 1. Decrypt a copy of menudb.dat (public MENUDB_KEY from GTToolsSharp KeysetStore.cs)
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptsalsa -i work/pamf_test/menudb.dat -k <MENUDB_KEY>

# 2. Read the per-movie key from the decrypted SQLite table (local helper; do not print it)
$key = python work/pamf_test/get_movie_key.py work/pamf_test/menudb.dat tv_10006_199556544

# 3. Decrypt a copy of the movie (unwraps Key with GT5P_TVBASEKEY, then Salsa20)
Copy-Item work/gt6_vol/movies/tv_10006_199556544.pam work/pamf_test/tv_10006.pam
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptmovie -i work/pamf_test/tv_10006.pam -k $key

# 4. Inspect the real PAMF header/streams/EPs
python tools/pamf_info.py work/pamf_test/tv_10006.pam --check-packs

# 5. Demux with PAMFtool (GPLv3, separate process)
tools\pamftool\PAMFtool.exe -demux work/pamf_test/tv_10006.pam work/pamf_test/demux10006

# 6. Decode with FFmpeg (no PAMF demux support; feed the demuxed streams)
tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe -i work/pamf_test/demux10006/tv_10006.s00_avc.h264 -frames:v 1 out.png
tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe -i work/pamf_test/demux10006/tv_10006.s01_atrac3plus.at3 -t 2 out.wav
```

Observed results:

* `tv_10006`: H.264 `339,175,131` bytes; ATRAC3+ 2ch `2,208,956` bytes; ATRAC3+ 6ch `5,477,564` bytes; FFmpeg exit 0 for a PNG frame and a 2-second WAV.
* `tv_10014`: H.264 `25,156,630` bytes; one AVC stream, 12 EPs, 10.377 s.

## Appendix B — New tool

`tools/pamf_info.py` is a clean-room reference parser for **decrypted** PAMF 0040/0041 files. It prints the header, sequence/group fields, stream codec info, EP tables, and (with `--check-packs`) verifies the 2048-byte pack count. It deliberately refuses files without the `PAMF` magic and points at `GTToolsSharp cryptmovie`. With `--json` it emits a machine-readable dump for comparing the runtime's HLE output.

## Appendix C — Key files touched/read

| Path | Role |
|---|---|
| `work/gt6_vol/movies/*.pam` | encrypted movie-layer files (read-only) |
| `work/gt6_vol/database/gt6/menudb.dat` | SQLite `t_movie` key source (copied to `work/pamf_test/` for decryption) |
| `work/gt6_vol/projects/gt6/boot/boot.adc` | `MovieRoot.ad` strings, SQL query, `decodeContentsKey`/`setKey`, public `MENUDB_KEY` at `0x7e8` |
| `work/gt6_vol/projects/gt6/play_movie/play_movie.adc` | movie playback script strings |
| `work/bin/EMAIN.elf` | native PAMF classes, hardcoded movie paths, import stubs |
| `work/rpcs3_oracle/rpcs3_input.log` | oracle proof of plaintext `cellPamf` input and demux/decode calls |
| `third_party/ps3recomp/libs/codec/cellPamf.c` | wrong header layout (read-only) |
| `third_party/ps3recomp/libs/codec/cellDmux.c` | one-AU stub (read-only) |
| `gt6/src/gen/ppu_hle_nids.cpp` | missing `cellPamf`/`cellDmux` NIDs |
| `tools/pamf_info.py` | new reference parser (this report) |
