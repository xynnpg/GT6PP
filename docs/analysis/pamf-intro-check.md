# PAMF intro check — encryption, container, keys, and viable paths

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00, `work/gt6_vol/movies/*.pam`,
`work/bin/EMAIN.elf`, RPCS3 oracle logs.
**Checker scope:** read-only. No runtime edits, no build, no `gt6.exe` run.
Temporary decrypted copies were made under `%TEMP%\pamfcheck` only; nothing
game-derived was added to the repository.
**Policy:** `third_party/PDTools` and `GTAdhocToolchain` were not read or used.
No leaked SDK keys were used. Key values are deliberately redacted below.

## 0. Verdict

| Question | Verdict |
|---|---|
| Are the extracted `.pam` files still encrypted? | **PASS — yes.** High-entropy Salsa20 layer, not corrupt. |
| Does the TOC mark movies as compressed/encrypted? | **PASS — no.** All 11 are `Flags: Uncompressed`; there is no movie-encryption flag. |
| Did GTToolsSharp leave movie entries encrypted? | **PASS — expected behaviour.** `unpack` only removes the volume cipher; `cryptmovie` is a separate step. |
| Does PAMFtool expect `PAMF` at offset 0? | **PASS.** It rejects the encrypted file with `Not a PAMF file (bad magic)`. |
| Is a key available without an update/leak? | **PASS.** Per-movie keys are in the user's own `menudb.dat`; the TV base key is also present in the user's executable. |
| Can the opening be decrypted and played as a standalone movie? | **PASS.** Verified: `PAMF0041`, 3 streams, 136.1 s, 1080p AVC + 2ch/5.1 ATRAC3+, demuxed and remuxed to a playable MP4. |
| Is the current in-tree HLE `cellPamf`/`cellDmux` path usable? | **FAIL.** Wrong header layout/structs/error codes, stub demux, and a mismatched NID table. |
| Is “impossible without a game update or a leaked key” true? | **FAIL — false.** No update is needed for the opening. |
| Legality of offline decrypt → demux → FFmpeg? | **PASS with conditions.** User's own data, public algorithms, external tools, no redistribution, no keys committed. |
| Legality of copying PAMFtool/RPCS3 into the MIT runtime? | **FAIL.** PAMFtool is GPL-3.0 and RPCS3 is GPL-2.0; do not link or copy. |

**Bottom line:** the encryption/key question is solved, and a playable
standalone intro can be produced now. The in-engine intro is a separate,
larger problem: the current HLE implementation cannot parse GT6's PAMF, and
the port has not reached the movie-player/render stage (still black,
`draws: 0`, PFS read-through incomplete). The realistic near-term deliverable
is an offline decrypted/demuxed intro, not in-engine playback.

---

## 1. What the files actually are

### 1.1 Raw headers

The head quoted in the task, `47 1f cf 8f ...`, is exactly
`tv_10017_871108574.pam` (the ending movie). Every movie has a different
first block:

| File | First 8 bytes |
|---|---|
| `tv_10005_678632543.pam` | `2c 47 1f da 90 61 4f 2e` |
| `tv_10006_199556544.pam` (OPENING) | `85 31 8c d8 3c 12 7f b6` |
| `tv_10010_224644567.pam` | `96 14 e7 f5 c5 b7 77 84` |
| `tv_10013_787414570.pam` | `19 2c e4 4a 60 bb 10 5e` |
| `tv_10017_871108574.pam` (ENDING) | `47 1f cf 8f fa db 01 17` |
| … | all 11 differ |

- First 4 MiB of the checked file (`tv_10005`): **8.0000 bits/byte**.
- No `PAMF` ASCII in its first 1 MiB.
- No `00 00 01` H.264 start code in its first 1 MiB.
- Sizes match the TOC `Size` fields for the checked entries (Salsa20 is a
  stream cipher; it does not change length or add padding).

This rules out a single corrupt header and a simple fixed-key XOR. It is a
per-file encrypted container.

### 1.2 Decrypted headers

Decrypting `tv_10010` and `tv_10006` with GTToolsSharp `cryptmovie` gives:

```
tv_10010: 50 41 4d 46 30 30 34 31 00 00 00 01 00 00 48 89   "PAMF0041"
tv_10006: 50 41 4d 46 30 30 34 31 00 00 00 02 00 02 9d a8   "PAMF0041"
```

That is the real PAMF layout: `PAMF` magic, ASCII version `0041`,
header size `0x800`/`0x1000`, data size in 2048-byte sectors. The decrypted
opening is 351,096,832 bytes, matching the RPCS3 file size `0x14ED5000`.

### 1.3 TOC flags

A fresh `GTToolsSharp 5.3.5 listfiles` of `gt6/GT.VOL` (not the cached text
file) prints for all 11 movies:

```
movies/tv_10006_199556544.pam - Flags: Uncompressed | FileIndex: 90 (K/IP) ...
movies/tv_10017_871108574.pam - Flags: Uncompressed | FileIndex: 29857 (5R/49) ...
...
```

- There is **no encryption flag** in the TOC.
- `Uncompressed` is correct: the volume layer does not compress these files.
- The extra encryption is content-level, applied after PFS extraction.

### 1.4 Why GTToolsSharp left them encrypted

GTToolsSharp 5.3.5's `UnpackVolumeFile` path calls `CryptoUtils.CryptToFile`,
which applies the **volume** cipher only. Movie decryption is a separate verb:

- `cryptmovie` exists specifically for movies.
- Its help text says: *“Keys for each movie file are within menudb.”*
- `PAMFtool` is not involved in volume extraction.

So this is not a GTToolsSharp bug: the tool did what it was asked. A user who
runs only `unpack` gets volume-decrypted but Salsa-encrypted movies.

---

## 2. Key/format evidence (no secrets published)

### 2.1 Per-movie keys are in the user's own data

`work/gt6_vol/database/gt6/menudb.dat` is itself Salsa20-encrypted. Decrypting
a temporary copy with the public GTToolsSharp MENUDB key yields a normal
SQLite database. It has a `t_movie` table with 10 rows:

| id | Name | FileName | Size/format |
|---:|---|---|---|
| 1 | OPENING | `tv_10006_199556544` | 1920×1080, 136 s |
| 2 | ENDING | `tv_10017_871108574` | 1920×1080, 513 s |
| 3–7 | PHOTO_* | `tv_10010`, `tv_10013`, `tv_10014`, `tv_10015`, `tv_10016` | 960×544 |
| 8–10 | PHOTO_MOON* | `tv_10021`, `tv_10022`, `tv_10023` | 960×544 |

`t_movie.Key` is a 44-character base64 string per row. GTToolsSharp
`cryptmovie` decrypts that key with the public `GT5P_TVBASEKEY`, then uses the
result as a Salsa20 key for the movie. Both tested movies (`tv_10006` opening
and `tv_10010` photo) decrypted to valid `PAMF0041`.

The GT6 entry in `key.json` only carries the volume key and has no
`DecryptManager` movie keys. The movie keys must come from `t_movie` in
`menudb.dat`; `cryptmovie` does not read them from `key.json`.

`tv_10005_678632543.pam` has no `t_movie` row and is not referenced by the
other menudb tables; it is not the opening. It is likely a GT-TV/advert or
unused entry.

### 2.2 Executable evidence

`work/bin/EMAIN.elf` contains:

- imports for `cellPamf` (18 NIDs), `cellDmux` (12 NIDs), `cellAdec` (8 NIDs);
- the literal paths `movies/tv_10006_199556544.pam` and
  `movies/tv_10017_871108574.pam`;
- movie-player strings (`movie_path`, `movie_format`, `movie_audio_output`,
  `movie_shutter_rate`, `createMovieTexture`, etc.);
- SQLite schema strings for the TV database (`t_tv`, `t_tv_chapter`,
  `t_tv_caption`, …).

At file offset `0xFA0A18` there is a base64 string equal to the publicly
documented GT5P TV base key, immediately after a PEM RSA private key block
(redacted; do not quote or commit it). The raw 32-byte key is not present.
This is consistent with guest-side key handling, but is not proof by itself of
the exact call path; the RPCS3 oracle below is the stronger evidence.

No `MENUDB_KEY`, `SPECDB_KEY`, or `CAPTIONDB_KEY` raw/hex strings were found in
`EMAIN.elf`. No Salsa “expand 32-byte k” constant was found either; the cipher
may live in a PRX or be built differently. This does not block the offline
path, which is already proven end-to-end.

### 2.3 PAMFtool's expectation

PAMFtool v1.3 (GPL-3.0) expects:

- `PAMF` at offset 0 (`0x50414D46`, big-endian);
- version `0040` or `0041`;
- `header_size`/`data_size` in 2048-byte sectors;
- nested sequence/grouping-period/group/stream headers;
- EP tables at `ep_offset` in 2048-byte units.

Running it on the still-encrypted opening produces:

```
PAMFtool.exe : Unhandled exception. System.IO.InvalidDataException:
Not a PAMF file (bad magic).
```

Running it on the decrypted opening succeeds and reports the real stream
table. That is a clean PASS for the container format and a clean FAIL for
“PAMFtool can open the extracted files as-is”.

---

## 3. Container and stream facts

### 3.1 Opening (`tv_10006_199556544.pam`)

After decryption:

| Field | Value |
|---|---|
| Magic/version | `PAMF0041` |
| Size | 351,096,832 bytes |
| Header | `0x1000` (2 sectors) |
| Stream area | 351,092,736 bytes (171,432 packs) |
| Duration | 136.1103 s |
| Streams | 3 |
| EP table | present, 191 entries across 3 streams |
| Stream 0 | AVC/H.264, 1920×1088 (crop bottom 4 → 1920×1080), High L4.1, 29.97 fps, CABAC |
| Stream 1 | ATRAC3plus, 2 ch, 48 kHz |
| Stream 2 | ATRAC3plus, 6 ch (5.1), 48 kHz |

The 1088→1080 crop is normal; the final display is 1080p.

### 3.2 Photos (`tv_10010` example)

| Field | Value |
|---|---|
| Magic/version | `PAMF0041` |
| Size | 38,031,360 bytes |
| Header | `0x800` (1 sector) |
| Streams | 1 |
| Stream 0 | AVC/H.264, 960×544, High L4.1, 29.97 fps |
| Duration | 16.383 s |
| EP table | absent |

### 3.3 Offline demux/decode result

PAMFtool `-demux` produced:

```
tv_10006...s00_avc.h264          339,175,131 bytes
tv_10006...s01_atrac3plus.at3      2,208,956 bytes (2 ch)
tv_10006...s02_atrac3plus.at3      5,477,564 bytes (6 ch)
```

FFmpeg then:

- decoded the H.264 stream as `h264 (High), yuv420p(tv, bt709),
  progressive, 1920x1080, 29.97 fps`;
- decoded the stereo ATRAC3plus stream as `atrac3p, 48000 Hz, stereo`;
- decoded the 5.1 stream as `atrac3p, 48000 Hz, 5.1`;
- remuxed video + stereo audio to a 136.07 s MP4
  (`h264` + AAC, 1920×1080), which ffprobe accepts as a normal playable file.

A frame extracted from the decrypted stream shows GT6 intro content (blue
Corvette), consistent with RPCS3's intro frame at 45 s
(`work/rpcs3_oracle/frames_after/frame_045s.png`).

**Important:** FFmpeg alone cannot open the PAMF container. Given the raw
`.pam`, it misdetects it as a Netpbm PAM image (`Video: pam, none`) and fails.
The working sequence is: decrypt → **PAMFtool demux** → FFmpeg. Or implement a
PAMF demuxer. FFmpeg's standard demuxers do not include PAMF.

---

## 4. RPCS3 oracle: who decrypts, and what the APIs see

From `work/rpcs3_oracle/rpcs3_after.log`:

```
cellPamfGetHeaderSize2(pAddr=*0xd01a2180, fileSize=0x14ed5000, ...)
cellPamfGetStreamOffsetAndSize(...)
cellPamfVerify(pAddr=*0x427fa000, fileSize=0x14ed5000)
cellPamfReaderInitialize(...)
cellPamfReaderGetNumberOfStreams(...)
cellPamfReaderGetNumberOfSpecificStreams(streamType=20)
cellPamfReaderGetNumberOfSpecificStreams(streamType=21)
cellPamfReaderGetStreamInfo(... size=32) -> CELL_PAMF_STREAM_TYPE_AVC
cellPamfReaderGetStreamInfo(... size=8)  -> CELL_PAMF_STREAM_TYPE_ATRAC3PLUS
cellPamfReaderGetStreamInfo(... size=8)  -> CELL_PAMF_STREAM_TYPE_ATRAC3PLUS
cellDmuxPamf: _CellDmuxCoreOpOpen(...)
cellDmuxPamf: _CellDmuxCoreOpEnableEs(...)
```

Facts:

- `fileSize=0x14ed5000` is the 351,096,832-byte opening.
- Before those calls, the PDI thread opens
  `PDIPFS/K/IP.fdupi` (fd 14) and reads it; RPCS3 reports the file size as
  exactly `0x14ed5000`. That `.fdupi` is the guest-side decrypted/cached
  movie. `cellPamf` is consuming the plaintext result of the guest PFS/file
  device path, not the encrypted `GT.VOL` bytes.
- The game queries aggregate stream types 20 (video) and 21 (audio), then
  AVC and two ATRAC3plus streams.
- Playback runs from about 41.2 s to 55.0 s in that log; the intro is visible.
- RPCS3's `cellPamf` HLE is a **plaintext** parser. Its source checks
  `pAddr->magic == "PAMF"` and `version == "0040"/"0041"` and does not
  decrypt. The game therefore passes already-decrypted PAMF data to
  `cellPamf`; decryption happens **before** the header parse and demux.
- `cellPamf`/`cellDmuxPamf` do container parsing, EP lookup, and elementary
  stream demux; decode is `libvdec`/`cellAdec`. They do not perform the Salsa
  movie decryption.

This is the key architectural point: **do not put key handling in HLE
`cellPamf`**. Either the guest's own decryption path must run, or the runtime
must pre-decrypt/override the file before the guest sees it.

---

## 5. Review of the current in-tree HLE implementation

There is no separate fixer plan document in the tree at check time. The
review below targets the actual `cellPamf`/`cellDmux` implementation and NID
registration now present in `third_party/ps3recomp` and `gt6/src/gen`.

### 5.1 `cellPamf.c` does not describe GT6 PAMF

The current implementation assumes:

- version `0x00040100` at offset 4 (real: ASCII `0041`);
- “data offset”/“data size” in **bytes** at 0x08/0x0C (real: header/data
  sizes in 2048-byte sectors);
- a “stream descriptor table offset” at 0x10 with fixed **24-byte**
  descriptors (real: nested `PamfSequenceInfo` → grouping period → group →
  48-byte `PamfStreamHeader`);
- a 32-byte host `CellPamfReader` (real: 128-byte guest struct);
- error codes `0x806103xx` (real: `0x806105xx`);
- raw type bytes 1..6 (real coding types: `0x1B` AVC, `0x02` M2V, `0xDC`
  ATRAC3plus, `0x80` LPCM, `0x81` AC-3);
- no `PSMF` magic/version support, no EP iterator, no aggregate stream
  types 20/21, and host-endian `CellPamfAvcInfo` writes.

These are not small offsets; the parser cannot correctly read the opening
header. It would either reject the file or return a bogus stream count and
bogus codec info.

### 5.2 `cellDmux.c` is a stub, not a demuxer

Its own comment says it “synthesize[s] one AU per enabled ES from the entire
stream buffer” and does not parse PES/MPEG-TS. For PAMF, the mux layer is
MPEG-2 program-stream packs (2048-byte sectors) with PES headers, PTS/DTS, and
substream IDs (`0xE0` AVC, `0xBD` + private ID for ATRAC3plus). One giant AU
will not decode as video, and it cannot produce ATRAC3plus frames.

### 5.3 NID registration does not match GT6

GT6 imports 18 `cellPamf` NIDs and 12 `cellDmux` NIDs
(`work/analysis/emain/EMAIN.imports.json`). The generated table in
`gt6/src/gen/ppu_hle_nids.cpp`:

| Library | Real imports | Exact matches registered | Missing | Non-GT6 registered |
|---|---:|---:|---:|---:|
| `cellPamf` | 18 | 9 | 9 | 5 |
| `cellDmux` | 12 | 8 | 4 | 3 |

Missing `cellPamf` NIDs include:

```
0x1ABEB9D6  cellPamfEpIteratorGetEp
0x28B4E2C1  cellPamfReaderSetStreamWithTypeAndIndex
0x439FBA17  cellPamfReaderGetEpIteratorWithTimeStamp
0x44F5C9E3  cellPamfGetStreamOffsetAndSize
0x50B83205  cellPamfEpIteratorMove
0x71DF326A  cellPamfReaderGetEsFilterId
0x90FC9A59  cellPamfGetHeaderSize2
0x9AB20793  cellPamfReaderGetStreamTypeAndChannel
0xD1A40EF4  cellPamfVerify
```

Missing `cellDmux` NIDs include:

```
0x02170D1A  cellDmuxQueryEsAttr
0x21D424F0  cellDmuxResetEs
0xA2D4189B  cellDmuxQueryAttr
0xF6C23560  cellDmuxOpenEx
```

The table instead registers five `cellPamf` NIDs GT6 never imports
(`0xB1DE0854`, `0x03FD2CAA`, `0x041CC708`, `0x01067E22`, `0xD9CDB145`) and
three `cellDmux` ones (`0x68492DE9` Open, `0x2750C5E0` PeekAu,
`0xCCFF1284` ResetStreamAndWaitDone). An unresolved NID currently returns
`CELL_OK` by default, which masks the missing handlers: callers can proceed
with uninitialized output sizes and zeroed results.

This is the most serious HLE finding. Even if the parser were rewritten, a
GT6 import such as `cellPamfGetHeaderSize2` would hit the unresolved path
until the NID table is regenerated from `EMAIN.imports.json`.

### 5.4 Downstream decode is only half-ready

- `cellVdec` has a real FFmpeg H.264/MPEG-2 path when
  `PS3RECOMP_FFMPEG_RUNTIME` is enabled.
- `cellAdec` is explicitly a silence stub; it does not decode ATRAC3plus.
- The port has not reached the movie player or a real RSX draw
  (`draws: 0`, PFS read-through still incomplete; see
  `docs/analysis/CONTINUE-HERE.md`). A correct `cellPamf`/`cellDmux` alone
  will not make the intro appear on screen. The native `work/gt6_hdd0` cache
  has no `K/IP.fdupi` (the opening's decrypted cache in the RPCS3 run), only
  small UI files; the native port has not reached the first movie.

**HLE verdict: FAIL as implemented.** This is a rewrite, not a small patch.

### 5.5 Plan review

Because no written fixer plan was present in the tree, the options that the
evidence supports are judged directly:

| Plan | Technical verdict | Why |
|---|---|---|
| Offline: `cryptmovie` → `PAMFtool -demux` → FFmpeg | **PASS** | Reproduced end-to-end; produces a playable standalone intro. |
| In-engine: keep the current `cellPamf.c`/`cellDmux.c` and add keys | **FAIL** | The parser is the wrong format, the demuxer is a stub, and 9 `cellPamf`/4 `cellDmux` GT6 NIDs are unregistered. |
| In-engine: clean-room real PAMF parser + MPEG-PS demux + FFmpeg VDEC | **PASS in principle / high effort** | Format is public and the oracle logs are sufficient; the port still needs the movie player and render path. |
| Any plan that copies PAMFtool or RPCS3 source into the MIT runtime | **FAIL** | GPL-3.0 / GPL-2.0 contamination. Use them as external tools/oracles only. |
| Any plan that hardcodes keys or commits decrypted movies | **FAIL** | Violates the project's no-key/no-redistribution policy. |

The key/container investigation is therefore not the risk. The risk is
underestimating the in-engine work and treating the existing HLE stubs as a
foundation.

---

## 6. Legality and data-policy review

### PASS conditions

- Decrypting the user's own disc data for interoperability and local testing
  is within this project's stated user-supplied-data policy.
- GTToolsSharp is MIT; using it as a build-time tool is fine. Do not copy its
  embedded key constants into the runtime; use the user's own `key.json`,
  `menudb.dat`, and executable. For a stricter clean-room stance, treat the TV
  base key as user-supplied input rather than a compiled-in constant.
- PAMFtool is **GPL-3.0**. Running `PAMFtool.exe` as a separate external tool
  during asset preparation is acceptable aggregation. Do **not** link its
  code, copy its source, or ship it as if it were MIT. If it is distributed,
  comply with GPL-3.0 (source offer, license, notices).
- RPCS3 is **GPL-2.0**. Use it as a behavioural oracle (logs/screenshots) but
  do not copy `cellPamf.cpp`, `cellDmuxPamf.cpp`, or their headers into
  `third_party/ps3recomp` (MIT). A clean-room implementation from the public
  format facts is required.
- The bundled `tools/ffmpeg` build is **GPL** (`--enable-gpl
  --enable-version3`, static, includes x264/x265). Keep it as an offline tool.
  The runtime's `cellVdec` dynamically loads libavcodec and documents an
  LGPL user-supplied library; do not point the runtime at this GPL build.
- Never commit or publish: per-movie keys, `menudb.dat`, decrypted movies, the
  PEM private key found in `EMAIN.elf`, or any key constant. Do not add
  decrypted assets to `work/` in the repository.

### FAIL conditions

- Copying PAMFtool or RPCS3 code into the MIT runtime.
- Hardcoding the public GTToolsSharp MENUDB/TV base keys into source.
- Publishing the RSA private key or the base64 TV key string from `EMAIN.elf`.
- Distributing decrypted PAMF/MP4 files as part of the project.

No leaked SDK key or `PDTools` content was used in this check.

---

## 7. Ranked realistic paths

### 1. Offline decrypt → PAMFtool demux → FFmpeg (PASS, immediate)

Already reproduced end-to-end:

1. Decrypt the movie with GTToolsSharp `cryptmovie`, using the key from the
   user's own `t_movie` row (the tool decrypts that key with the public TV
   base key).
2. `PAMFtool -demux` to raw `.h264` + `.at3`.
3. FFmpeg remux/transcode to MP4 (H.264 video, AAC audio).

Result: a 136.07 s, 1920×1080 intro with stereo audio. This is the right
deliverable if the goal is “watch the intro now” or produce a reference
video. It does **not** make the game play the intro in-engine.

Estimated effort: under an hour for one movie once the key path is known;
batch all 10 with a small script. Keep outputs outside the repo.

### 2. Decrypt-to-PAMF + VFS override + correct HLE (in-engine, medium)

This is the best in-engine route that avoids reimplementing Salsa in the
runtime:

1. Pre-decrypt the movies offline, leaving valid plaintext PAMF (no need to
   demux for this route).
2. Override the guest's movie files through the VFS so the guest receives
   plaintext PAMF. This also bypasses the guest's own decryption/key path for
   movies, which is useful while PFS read-through is incomplete.
3. Rewrite `cellPamf` to the real PAMF 0040/0041 layout and regenerate the
   NID table from `EMAIN.imports.json`.
4. Implement real `cellDmuxPamf` MPEG-PS/PES demux and callbacks.
5. Feed AUs to the existing FFmpeg `cellVdec`; leave audio silent initially
   or add FFmpeg ATRAC3plus decode to `cellAdec`.
6. Wire the movie player's texture/render path.

This still needs the port to reach the movie player and to render a texture;
it is not a one-day change. Estimate: 1–3 weeks for parser/demux/video, plus
audio and movie-player integration.

### 3. Full clean-room HLE from scratch (long)

Same as above, but without pre-decrypting: let the guest's decryption path
run, or implement the movie Salsa layer in the runtime's PFS/asset path. This
adds key handling and PFS work. It is feasible but strictly more work than
path 2 and has no near-term payoff. Estimate: 3–6 weeks including audio and
movie-player polish.

### 4. “Impossible without update/key” — reject

False for the opening. The per-movie keys are in the user's own `menudb.dat`,
the TV base key is in the user's executable, and `cryptmovie` demonstrably
decrypts both tested movies. No PSN update, no leaked SDK key, and no
fabricated key are required. The only “impossible” cases are policy choices
(for example, refusing to use any game-derived key at all) or a user who
lacks `menudb.dat`/the executable.

---

## 8. Recommendations

1. **Do not spend more time on the current `cellPamf.c` parser.** It encodes
   an invented format and cannot be incrementally fixed into GT6 PAMF. Rewrite
   it from the real layout (RPCS3 logs/PAMFtool output as oracle, no code
   copying).
2. **Regenerate the HLE NID table from GT6's 18 `cellPamf` + 12 `cellDmux`
   imports.** Treat missing NIDs as failures, not silent `CELL_OK`.
3. **Separate the two goals.** Ship/keep the offline intro artifact first;
   then implement in-engine PAMF behind the movie-player milestone. Do not
   claim the intro is fixed because the offline MP4 plays.
4. **Use the pre-decrypt + VFS override route** for the first in-engine
   attempt; it removes the Salsa/key layer from the critical path.
5. **Keep GPL and keys out of the MIT runtime.** PAMFtool/RPCS3 are oracles
   and external tools, not source donors. The GPL FFmpeg build is an offline
   tool only.
6. **Do not commit** decrypted movies, `menudb.dat`, per-movie keys, the TV
   base key, or the RSA private key from `EMAIN.elf`.

---

## 9. Reproduction commands (no key values)

These are the safe, value-free forms; keys are read from the user's own data
and are never echoed into logs or this document.

```powershell
# 1. Confirm the TOC flags
tools\GTToolsSharp\win-x64\GTToolsSharp.exe listfiles `
  -i gt6/GT.VOL -o "$env:TEMP\gt6_entries.txt"
Select-String "$env:TEMP\gt6_entries.txt" -Pattern '^movies/'

# 2. Decrypt the user's menudb copy with the public GTToolsSharp MENUDB key
#    (the key is documented in the GTToolsSharp source; do not commit it)
copy work\gt6_vol\database\gt6\menudb.dat "$env:TEMP\menudb.dat"
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptsalsa `
  -i "$env:TEMP\menudb.dat" -k <MENUDB_KEY>

# 3. Read the per-movie key for the opening from t_movie (do not print it)
#    and pass it to cryptmovie; the tool decrypts the key with GT5P_TVBASEKEY.
copy work\gt6_vol\movies\tv_10006_199556544.pam "$env:TEMP\opening.pam"
tools\GTToolsSharp\win-x64\GTToolsSharp.exe cryptmovie `
  -i "$env:TEMP\opening.pam" -k <BASE64_KEY_FROM_t_movie>

# 4. Parse and demux
tools\pamftool\PAMFtool.exe -info "$env:TEMP\opening.pam"
tools\pamftool\PAMFtool.exe -demux "$env:TEMP\opening.pam" "$env:TEMP\opening_demux"

# 5. Decode/remux with FFmpeg
tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe `
  -fflags +genpts -r 30000/1001 `
  -i "$env:TEMP\opening_demux\tv_10006_199556544.s00_avc.h264" `
  -i "$env:TEMP\opening_demux\tv_10006_199556544.s01_atrac3plus.at3" `
  -map 0 -map 1 -c:v copy -c:a aac -b:a 192k `
  "$env:TEMP\gt6_opening.mp4"
```

The last step uses the raw `.at3` as an input; if FFmpeg's timestamp handling
drops the audio, decode it to WAV first and mux the WAV. That does not change
the conclusion.

---

## 10. Evidence index

| Evidence | Path |
|---|---|
| Raw encrypted headers/entropy | `work/gt6_vol/movies/*.pam` |
| TOC flags (fresh) | `GTToolsSharp listfiles` output; `work/gt6_volume_entries.txt` |
| GTToolsSharp unpack vs cryptmovie | GTToolsSharp 5.3.5 source: `PFSVolumeUnpacker.cs`, `Program.cs`, `ProgramArgs.cs` |
| menudb schema/keys | decrypted temp copy of `work/gt6_vol/database/gt6/menudb.dat` (`t_movie`) |
| PAMFtool format/magic | `tools/pamftool/PAMFtool.exe` v1.3; GPL-3.0 repo `ravenDS/PAMFtool` |
| RPCS3 cellPamf/cellDmux log | `work/rpcs3_oracle/rpcs3_after.log` |
| RPCS3 intro frame | `work/rpcs3_oracle/frames_after/frame_045s.png` |
| GT6 imports | `work/analysis/emain/EMAIN.imports.json` |
| Current HLE implementation | `third_party/ps3recomp/libs/codec/cellPamf.c`, `cellPamf.h`, `cellDmux.c` |
| Current NID table | `gt6/src/gen/ppu_hle_nids.cpp` |
| Boot/movie-player state | `docs/analysis/CONTINUE-HERE.md`, `docs/STATUS.md` |
| Project policy | `docs/research/gt6-formats-and-tooling.md` §“Legal/ethical” |
