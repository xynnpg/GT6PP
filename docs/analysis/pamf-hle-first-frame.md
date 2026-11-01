# PAMF HLE first frame: real 0041 layout, `cellPamf`/`cellDmux` repair, and the remaining blockers

**Date:** 2026-10-31
**Target:** GT6 US disc `BCUS98296` v1.00; `work/bin/EMAIN.elf`;
`work/gt6_vol/movies/tv_10006_199556544.pam` (opening); RPCS3 oracle
`work/rpcs3_oracle/rpcs3_input.log`.
**Scope:** the smallest clean-room `cellPamf` + `cellDmux` path that produces
the opening movie's AVC access units and feeds the existing `cellVdec` frame
path. This is a first-frame/playback-start task, not full A/V sync.
**Work performed:** read-only analysis plus one patch under `patches/`. No
`gt6.exe` build or run, no game data or generated build output was edited, and
no key values or decrypted assets are published here.

---

## 0. Verdict

1. **The real PAMF 0041 layout is established and is not the layout the old
   in-tree HLE used.** `header_size`/`data_size` are in 2048-byte sectors,
   the stream table is the nested
   `PamfSequenceInfo` → `PamfGroupingPeriod` → `PamfGroup` → 48-byte
   `PamfStreamHeader[]` at `0x50`/`0x70`/`0x82`/`0x88`, and entry points are
   12-byte records at each stream's file-relative `ep_offset`.
2. **The PAMF data area is an MPEG-2 program stream in fixed 2048-byte
   packs.** Each pack starts `00 00 01 BA`; video is PES `0xE0`, audio is
   private PES `0xBD` with a four-byte PAMF prefix and ATRAC3+ `0x0FD0` ATS
   frames. AVC access units are delimited by AUD NALs
   (`00 00 00 01 09` / `00 00 01 09`).
3. **A replay of the exact patch algorithm on the decrypted opening gives
   4,079 AVC access units and 339,175,131 bytes, byte-identical to PAMFtool's
   demuxed `s00_avc.h264`.** Access unit 0 is 841 bytes with PTS 90000,
   DTS 86997 and an IDR slice; that is the first frame the existing
   `cellVdec` FFmpeg path can decode.
4. **The patch repairs the parser, the demuxer, the callbacks and the NIDs**
   (`patches/ps3recomp-cellpamf-celldmux-first-frame.patch`). It also adds the
   missing `cellAdecOpenEx`/`cellAdecOpenExt` aliases, because GT6 imports
   only those forms and the old table registered only `cellAdecOpen`.
5. **The remaining blockers are outside `cellPamf`/`cellDmux`:**
   the port must reach the movie-player script and the guest must decrypt the
   movie; the current GT6 build has `PS3RECOMP_FFMPEG_RUNTIME=OFF`, so
   `cellVdec` would produce its black placeholder rather than a decoded
   picture; and the decoded frame still has to reach the RSX/texture path.
   These are stated precisely in §7 and §8.

**Bottom line:** the format/demux/HLE layer is now specified and patched, and
the first AVC AU is proven on the user's decrypted sample. A real in-engine
first frame additionally needs the FFmpeg-enabled build and the movie-player
path; the patch alone cannot supply either.

---

## 1. Evidence and method

| Evidence | Use |
|---|---|
| `docs/analysis/pamf-intro-fix.md`, `docs/analysis/pamf-intro-check.md` | prior clean-room format/encryption findings |
| `work/rpcs3_oracle/rpcs3_input.log` | exact guest call order and parameter shapes |
| `work/pamf_test/tv_10006.pam` (decrypted local copy) | header, stream table, EP table, pack/PES and AU proof |
| `work/pamf_test/demux10006/tv_10006.s00_avc.h264` (PAMFtool output) | byte-exact demux comparison only; GPL tool used as a separate process |
| `third_party/ps3recomp/libs/codec/*` | current HLE implementation |
| public PS3 SDK ABI descriptions | struct sizes/field order only; no implementation copied |

No PAMFtool, RPCS3 or FFmpeg source was copied into the MIT runtime. The
container offsets and SDK struct layouts are format/ABI facts; the parser and
demuxer in the patch are a direct implementation of those facts.

---

## 2. Real PAMF 0041 layout

All values are big-endian. Offsets are file offsets. `SECTOR = 0x800`.

### 2.1 File header

| Offset | Size | Field | Opening value |
|---:|---:|---|---|
| `0x00` | 4 | magic `PAMF` | `50 41 4D 46` |
| `0x04` | 4 | ASCII version | `30 30 34 31` (`0041`) |
| `0x08` | 4 | `header_size` in sectors | `2` → `0x1000` |
| `0x0C` | 4 | `data_size` in sectors | `0x29DA8` → `0x14ED4000` |
| `0x10` | 4 | `psmf_marks_offset` | `0` |
| `0x14` | 4 | `psmf_marks_size` | `0` |
| `0x18` | 4 | `unk_offset` | `0` |
| `0x1C` | 4 | `unk_size` | `0` |
| `0x20` | `0x30` | reserved | zero |
| `0x50` | | `PamfSequenceInfo` | |

`header_size + data_size == fileSize`:
`0x1000 + 0x14ED4000 = 0x14ED5000 = 351,096,832`. That sum is what
`cellPamfVerify` checks (when `fileSize != 0`).

### 2.2 `PamfSequenceInfo` at `0x50`

| Offset | Size | Field | Opening |
|---:|---:|---|---|
| `0x50` | 4 | `size` (excluding this field) | `0xC4` |
| `0x54` | 2 | reserved | 0 |
| `0x56` | 2 | `start_pts_high` | 0 |
| `0x58` | 4 | `start_pts_low` | `0x15CDE` (89,310; 0.9923 s) |
| `0x5C` | 2 | `end_pts_high` | 0 |
| `0x5E` | 4 | `end_pts_low` | `0xBC4825` (12,339,237; 137.10 s) |
| `0x62` | 4 | `mux_rate_bound` (×50 B/s) | `0x1D4C0` (120,000; 48 Mbps) |
| `0x66` | 4 | `std_delay_bound` (90 kHz) | `0x107AC` (67,500) |
| `0x6A` | 4 | `total_stream_num` | 3 |
| `0x6E` | 1 | reserved | 0 |
| `0x6F` | 1 | `grouping_period_num` | 1 |
| `0x70` | | `PamfGroupingPeriod` | |

### 2.3 `PamfGroupingPeriod` at `0x70`, `PamfGroup` at `0x82`

| Offset | Size | Field | Opening |
|---:|---:|---|---|
| `0x70` | 4 | grouping-period `size` | `0xA4` |
| `0x74` | 2 | `start_pts_high` | 0 |
| `0x76` | 4 | `start_pts_low` | `0x15CDE` |
| `0x7A` | 2 | `end_pts_high` | 0 |
| `0x7C` | 4 | `end_pts_low` | `0xBC4825` |
| `0x80` | 1 | reserved | 0 |
| `0x81` | 1 | `group_num` | 1 |
| `0x82` | 4 | group `size` | `0x92` |
| `0x86` | 1 | reserved | 0 |
| `0x87` | 1 | `stream_num` | 3 |
| `0x88` | `48 * n` | `PamfStreamHeader[]` | see below |

All three sizes end at `0x118`, exactly where the first stream's EP table
begins.

### 2.4 `PamfStreamHeader` (48 bytes)

| Field offset | Size | Field | Stream 0 (AVC) | Stream 1 (ATRAC3+) | Stream 2 (ATRAC3+) |
|---:|---:|---|---:|---:|---:|
| `+0x00` | 1 | `stream_coding_type` | `0x1B` | `0xDC` | `0xDC` |
| `+0x01` | 3 | reserved | 0 | 0 | 0 |
| `+0x04` | 1 | `stream_id` | `0xE0` | `0xBD` | `0xBD` |
| `+0x05` | 1 | `private_stream_id` | 0 | 0 | 1 |
| `+0x06` | 2 | `p_std_buffer` | `0x333B` | `0x2014` | `0x2014` |
| `+0x08` | 4 | `ep_offset` (file offset) | `0x118` | 0 | 0 |
| `+0x0C` | 4 | `ep_num` | 191 | 0 | 0 |
| `+0x10` | 32 | codec-specific info | see §2.5 | `00 00 02 01…` | `00 00 06 01…` |

`stream_coding_type` values are `0x02` M2V, `0x1B` AVC, `0x80` LPCM,
`0x81` AC-3, `0xDC` ATRAC3plus, `0xDD` user data, `0xFF` PSMF. The old
in-tree parser used invented raw types 1..6; those are not on the disc.

### 2.5 AVC specific info (`specific[0..31]`)

| `specific` offset | Size | Field | Opening |
|---:|---:|---|---:|
| 0 | 1 | `profileIdc` | 100 (High) |
| 1 | 1 | `levelIdc` | 41 (4.1) |
| 2 | 1 | bit7 `frame_mbs_only`, bit6 `video_signal_info`, low nibble `frame_rate_info_raw` | `0xC4` |
| 3 | 1 | `aspect_ratio_idc` | 1 |
| 4 | 2 | `sar_width` | 0 |
| 6 | 2 | `sar_height` | 0 |
| 8 | 1 | reserved | 0 |
| 9 | 1 | `horizontal_size / 16` | 120 → 1920 |
| 10 | 1 | reserved | 0 |
| 11 | 1 | `vertical_size / 16` | 68 → 1088 |
| 12 | 2 | crop left | 0 |
| 14 | 2 | crop right | 0 |
| 16 | 2 | crop top | 0 |
| 18 | 2 | crop bottom | 4 → displayed 1920×1080 |
| 20 | 1 | bits7-5 video format, bit4 full range | `0xA0` → format 5, full range 0 |
| 21 | 1 | colour primaries | 1 |
| 22 | 1 | transfer characteristics | 1 |
| 23 | 1 | matrix coefficients | 1 |
| 24 | 1 | bit7 entropy, bit6 deblock, bits5-4 min slices, bits1-0 `nfw` | `0xB0` |
| 25 | 1 | `max_mean_bitrate` | 30 |
| 26..31 | 6 | reserved | 0 |

The SDK's `CellPamfAvcInfo.frameRateInfo` is `frame_rate_info_raw - 1`:
raw `4` → SDK `3` = `30000/1001` fps. The old parser read horizontal size at
the wrong offset (14 instead of 9) and read bytes 10/12 for audio channel
count/frequency; both are fixed in the patch.

Audio specific info is `00 00 <channels> <freq> <bits> 00…`:
`channels` at 2, `freq` at 3 (1 = 48 kHz), `bits` at 4 (LPCM only, 1 = 16,
3 = 24).

### 2.6 Entry points

`ep_offset` is a file offset from the PAMF base (not from the header or
group). Each packed record is 12 bytes:

| Offset | Size | Field |
|---:|---:|---|
| `+0x00` | 2 | `value0`: bits 15-14 `index_n - 1`, bit 13 unused, bits 12-0 `nThRefPictureOffset` in 0x800 units |
| `+0x02` | 2 | `pts_high` (always 0 in these assets) |
| `+0x04` | 4 | `pts_low` (90 kHz) |
| `+0x08` | 4 | `rpnOffset` in 0x800 units |

Opening: 191 records. First `pts=0x15F90` (90,000; 1.000 s), `rpn=0`.
Last `pts=12,279,177`, raw `rpn=0x29D91` (171,409 sectors =
`0x14EC8800` bytes, 47,104 bytes before the data end). The EP table ends at
`0xA0C`, inside the two-sector header.

Unpacking for the guest `CellPamfEp`:

```
indexN              = (value0 >> 14) + 1
nThRefPictureOffset = ((value0 & 0x1FFF) * 0x800) + 0x800
pts.upper           = pts_high
pts.lower           = pts_low
rpnOffset           = rpnOffset * 0x800
```

### 2.7 Pack / PES layer

Data starts at `header_size` (`0x1000`) and is `data_size / 0x800` =
171,432 sectors. Every sector begins with a 14-byte MPEG-2 pack header:

```
0x1000: 00 00 01 BA 44 00 0D 50 54 91 07 53 03 F8
```

The first pack also carries:

* system header `00 00 01 BB` (length `0x000C`) at `0x100E`;
* program stream map `00 00 01 BF` (length `0x007A`) at `0x1020`;
* first video PES `00 00 01 E0` at `0x10A0`, length `0x075A`.

PES header rules used by the patch:

* payload begins at `packet_start + 9 + PES_header_data_length` (byte 8);
* `PES_packet_length` includes the 3-byte optional header but not the
  6-byte start/length prefix; `length == 0` means “to the end of the pack”;
* `flags2 & 0x80` ⇒ PTS present (5 bytes at `+9`);
* `(flags2 & 0xC0) == 0xC0` ⇒ DTS present (5 bytes at `+14`);
* PTS/DTS are the standard 33-bit marker-bit encoding.

Opening examples:

| Location | PES | Length | Flags2 | PTS | DTS | Payload |
|---|---:|---:|---:|---:|---:|---|
| `0x10A0` | `E0` | `0x75A` | `0xC1` | 90,000 | 86,997 | `00 00 00 01 09 10 …` (AUD/SPS/PPS/IDR) |
| `0x180E` | `BD` | `0x7EC` | `0x81` | 85,470 | — | `00 00 00 00 0F D0 48 55 …` |
| `0x200E` | `BD` | `0x7EC` | `0x81` | 85,470 | — | `01 00 00 00 0F D0 54 D5 …` |

For private PES `0xBD`, the first payload byte is the `private_stream_id`
(0 or 1), followed by three PAMF framing bytes; the ATRAC3+ ATS data starts
at payload `+4`. The ATS header begins with `0F D0`; the first distance to
the next `0F D0` is the fixed frame size: **696 bytes** for 2 ch, **1720
bytes** for 6 ch in the opening. Pass the ATS header with the AU because the
guest starts `cellAdec` with `au_includes_ats_hdr_flg=1`.

### 2.8 AVC access units

The concatenated video PES payloads are a single H.264 byte stream. Access
units start at each AUD NAL:

* four-byte form `00 00 00 01 09`, or
* three-byte form `00 00 01 09`.

The opening has 4,079 AUDs. The first AU is 841 bytes:

```
00 00 00 01 09 10              AUD
00 00 00 01 27 64 00 29 AC 3E  SPS (High, level 4.1)
00 00 00 01 28 EA 8F 30 0C     PPS
00 00 01 06 …                  SEI
00 00 01 25 …                  IDR slice(s)
```

`isRap` is set by scanning the AU for a NAL type 5 (IDR) start code. For
the opening AU 0 it is true.

---

## 3. Guest ABI used by the HLE

These are the layouts the patch writes; the guest allocates them, the HLE
must not substitute host structs or host pointers.

### 3.1 `cellPamf`

| Struct | Size | Layout |
|---|---:|---|
| `CellCodecTimeStamp` | 8 | `upper` u32 at 0, `lower` u32 at 4 |
| `CellCodecEsFilterId` | 16 | `filterIdMajor` u32 at 0, `filterIdMinor` at 4, `supplementalInfo1` at 8, `supplementalInfo2` at 0xC |
| `CellPamfEp` | 24 | `indexN` 0, `nThRefPictureOffset` 4, `pts.upper` 8, `pts.lower` 0xC, `rpnOffset` u64 at 0x10 |
| `CellPamfEpIterator` | 16 | `isPamf` u8 0, padding 1..3, `index` 4, `num` 8, `pCur` (guest EA) 0xC |
| `CellPamfAvcInfo` | 32 | profile 0, level 1, frameMbsOnly 2, videoSignalInfo 3, frameRateInfo 4, aspect 5, SAR W 6, SAR H 8, width 0xA, height 0xC, crop L 0xE, R 0x10, T 0x12, B 0x14, videoFormat 0x16, fullRange 0x17, colour 0x18, transfer 0x19, matrix 0x1A, entropy 0x1B, deblock 0x1C, minSlice 0x1D, nfw 0x1E, maxBitrate 0x1F |
| `CellPamfAtrac3plusInfo` | 8 | `samplingFrequency` u32 0, `numberOfChannels` u8 4 |
| `CellPamfAc3Info` | 8 | same as ATRAC3+ |
| `CellPamfLpcmInfo` | 8 | `samplingFrequency` u32 0, `numberOfChannels` u8 4, `bitsPerSample` u16 6 |
| `CellPamfReader` | 128 | `headerSize` u64 0, `dataSize` u64 8, `attribute` 0x10, `isPsmf` u16 0x14, `version` u16 0x16, grouping/group/stream indices 0x18/0x1C/0x20, five guest pointers 0x24..0x34, reserved to 0x80 |

The implementation treats `CellPamfReader` as opaque host state keyed by the
guest EA. It zeroes the 128-byte guest object and writes only scalars; it
never writes a host pointer there.

### 3.2 `cellDmux`

| Struct | Size | Layout |
|---|---:|---|
| `CellDmuxType` | 12 | `streamType` s32 0, `reserved1` 4, `reserved2` 8 |
| `CellDmuxType2` | 8 | `streamType` s32 0, `streamSpecificInfo` guest pointer 4 |
| `CellDmuxAttr` | 12 | `memSize` 0, `demuxerVerUpper` 4, `demuxerVerLower` 8 |
| `CellDmuxEsAttr` | 4 | `memSize` 0 |
| `CellDmuxCb` | 8 | `cbFunc` guest OPD 0, `cbArg` 4 |
| `CellDmuxEsResource` | 8 | `memAddr` 0, `memSize` 4 |
| `CellDmuxMsg` / `CellDmuxEsMsg` | 16 | `msgType` s32 0, padding 4, `supplementalInfo` u64 8 |
| `CellDmuxAuInfo` | 40 | `auAddr` 0, `auSize` 4, `auMaxSize` 8, `isRap` u8 0xC, padding 0xD..0xF, `userData` u64 0x10, `pts.upper` 0x18, `pts.lower` 0x1C, `dts.upper` 0x20, `dts.lower` 0x24 |

Callbacks are **guest OPDs** and must go through `g_ps3_guest_caller`:

```c
CellDmuxCbMsg   (handle, CellDmuxMsg  *msg, cbArg)
CellDmuxCbEsMsg (handle, esHandle, CellDmuxEsMsg *msg, cbArg)
```

The old in-tree code called them as host function pointers with
`(handle, msgType, msgData, cbArg)`; that is both the wrong calling
convention and the wrong argument shape.

---

## 4. Exact NIDs

`gen_hle_nids.py` derives each NID from the SDK function name with the
firmware algorithm; the patch adds the missing names to the HLE sources and
the generated table. Every NID below was recomputed from its name and matches
the table.

### 4.1 `cellPamf` (18 GT6 imports)

| NID | Function | Before patch |
|---|---|---|
| `0x1ABEB9D6` | `cellPamfEpIteratorGetEp` | missing |
| `0x28B4E2C1` | `cellPamfReaderSetStreamWithTypeAndIndex` | missing |
| `0x37F723F7` | `cellPamfReaderGetNumberOfStreams` | present |
| `0x439FBA17` | `cellPamfReaderGetEpIteratorWithTimeStamp` | missing |
| `0x44F5C9E3` | `cellPamfGetStreamOffsetAndSize` | missing |
| `0x461534B4` | `cellPamfReaderSetStreamWithIndex` | present |
| `0x4DE501B1` | `cellPamfReaderGetPresentationStartTime` | present |
| `0x50B83205` | `cellPamfEpIteratorMove` | missing |
| `0x67FD273B` | `cellPamfReaderGetStreamInfo` | present (wrong fields) |
| `0x71DF326A` | `cellPamfReaderGetEsFilterId` | missing |
| `0x90FC9A59` | `cellPamfGetHeaderSize2` | missing |
| `0x9AB20793` | `cellPamfReaderGetStreamTypeAndChannel` | missing |
| `0xB8436EE5` | `cellPamfReaderInitialize` | present (wrong layout) |
| `0xD0230671` | `cellPamfReaderGetNumberOfSpecificStreams` | present |
| `0xD1A40EF4` | `cellPamfVerify` | missing |
| `0xD9EA3457` | `cellPamfReaderGetNumberOfEp` | present (wrong signature: returns u32) |
| `0xDB70296C` | `cellPamfReaderGetMuxRateBound` | present |
| `0xF61609D6` | `cellPamfReaderGetPresentationEndTime` | present |

### 4.2 `cellDmux` (12 GT6 imports)

| NID | Function | Before patch |
|---|---|---|
| `0x02170D1A` | `cellDmuxQueryEsAttr` | missing |
| `0x04E7499F` | `cellDmuxSetStream` | present (one-AU stub) |
| `0x05371C8D` | `cellDmuxDisableEs` | present |
| `0x21D424F0` | `cellDmuxResetEs` | missing |
| `0x24EA6474` | `cellDmuxReleaseAu` | present |
| `0x42C716B5` | `cellDmuxGetAu` | present (wrong ABI) |
| `0x5D345DE9` | `cellDmuxResetStream` | present |
| `0x7B56DC3F` | `cellDmuxEnableEs` | present (wrong ABI) |
| `0x8C692521` | `cellDmuxClose` | present |
| `0xA2D4189B` | `cellDmuxQueryAttr` | missing |
| `0xEBB3B2BD` | `cellDmuxFlushEs` | present |
| `0xF6C23560` | `cellDmuxOpenEx` | missing |

### 4.3 `cellAdec` open forms

GT6 imports `cellAdecOpenEx` (`0x8B5551A4`) and `cellAdecOpenExt`
(`0xDF982D2C`), but the tree defined/registered only `cellAdecOpen`
(`0xD00A6988`). The patch adds the two aliases so the guest gets a real
handle before `cellAdecStartSeq`. The decoder remains the existing silence
implementation; see §7.

---

## 5. Guest call order → HLE mapping

From `work/rpcs3_oracle/rpcs3_input.log` (PDI thread, 0:00:38.748 onward).
The argument shapes are the ones the patch implements.

| # | Guest call (oracle) | HLE result |
|---:|---|---|
| 1 | `cellPamfGetHeaderSize2(pAddr, fileSize=0x14ED5000, attr=0, &size)` | verifies `PAMF`/`0041`, sizes sum to file size, returns `0x1000` as u64 |
| 2 | `cellPamfGetStreamOffsetAndSize(pAddr, fileSize, &off, NULL)` | returns header size in `off` |
| 3 | `cellPamfGetStreamOffsetAndSize(pAddr, fileSize, &off, &size)` | header/data sizes |
| 4 | `cellPamfVerify(pAddr, fileSize)` | magic/version/size, sequence/group bounds, EP table bounds |
| 5 | `cellPamfReaderInitialize(pSelf, pAddr, fileSize, 0)` | parses 3 streams / 191 EPs, writes the 128-byte reader scalars |
| 6 | `cellPamfReaderSetStreamWithIndex(pSelf, 0)` | selects AVC |
| 7 | `cellPamfReaderGetNumberOfStreams(pSelf)` | 3 |
| 8 | `cellPamfReaderGetNumberOfSpecificStreams(pSelf, 20)` | 1 (video) |
| 9 | `cellPamfReaderGetNumberOfSpecificStreams(pSelf, 21)` | 2 (audio) |
| 10 | `cellPamfReaderInitialize` per stream `0/1/2` | fresh reader for each |
| 11 | `cellPamfReaderSetStreamWithIndex(0/1/2)` | selects each stream |
| 12 | `cellPamfReaderGetStreamTypeAndChannel(pSelf, &type, &ch)` | AVC 0/0, ATRAC3+ 2/0, 2/1 |
| 13 | `cellPamfReaderGetPresentationStartTime/EndTime` | 89,310 / 12,339,237 ticks |
| 14 | `cellPamfReaderGetMuxRateBound` | 120,000 |
| 15 | `cellPamfReaderGetEsFilterId(pSelf, &filter)` | `{0xE0,0,1,0}` video; `{0xBD,0,0,0}` / `{0xBD,1,0,0}` audio |
| 16 | `cellPamfReaderGetStreamInfo(pSelf, &info, 32)` | `CellPamfAvcInfo` 1920×1088, crop bottom 4, High/4.1 |
| 17 | `cellPamfReaderGetStreamInfo(pSelf, &info, 8)` | ATRAC3+ 48 kHz, 2 ch / 6 ch |
| 18 | `cellDmuxQueryAttr(type, &attr)` | memSize/version |
| 19 | `cellDmuxOpenEx(type, resEx, &cb, &handle)` | handle 1..8, stores guest OPD + arg |
| 20 | `cellDmuxQueryEsAttr(type, &filter, specific, &attr)` | video 1.5 MB, audio 256 KB |
| 21 | `cellDmuxEnableEs(handle, &filter, &esRes, &esCb, specific, &esHandle)` | records filter/mem/Cb; returns nonzero ES handle |
| 22 | `cellVdecQueryAttrEx` / `OpenEx` / `StartSeq` | existing cellVdec path |
| 23 | `cellDmuxQueryEsAttr` / `EnableEs` for audio | second/third ES |
| 24 | `cellAdecQueryAttr` / `OpenEx` / `OpenExt` / `StartSeq` | handle now returned by the aliases |
| 25 | repeated `cellDmuxSetStream(handle, data, size, 0, userData)` | 2048-byte pack parser; emits AU_FOUND |
| 26 | `cellDmuxGetAu(es, &auInfo, &specific)` / `ReleaseAu` | one guest `CellDmuxAuInfo` per call |
| 27 | `cellVdecDecodeAu(handle, mode, &au)` | existing FFmpeg path decodes the AVC AU |
| 28 | `cellVdecGetPicture(handle, &fmt, dst)` | first decoded YUV420 picture |
| 29 | `cellDmuxResetStream` / `DisableEs` / `Close` | teardown for stop/skip |

The audio and video decoders run on their own guest threads; the demuxer
callback is synchronous on the PDI thread. The patch never blocks the
callback and never holds a lock while calling guest code.

---

## 6. Implementation in the patch

`patches/ps3recomp-cellpamf-celldmux-first-frame.patch` changes:

| File | Change |
|---|---|
| `third_party/ps3recomp/libs/codec/cellPamf.h` | real error codes (`0x806105xx`), SDK stream types, guest ABI structs, real function names |
| `third_party/ps3recomp/libs/codec/cellPamf.c` | header/sequence/group/stream/EP parser; all 18 imported entry points; EP iterators; exact `CellPamfAvcInfo`/audio fields; guest big-endian writes |
| `third_party/ps3recomp/libs/codec/cellDmux.h` | real `CellDmuxType`/`Attr`/`Cb`/`Msg`/`AuInfo`/`CellCodecEsFilterId` layouts; real entry-point signatures |
| `third_party/ps3recomp/libs/codec/cellDmux.c` | PAMF pack/PES parser, AVC AUD AU assembly, ATRAC3+ ATS frame split, per-ES AU queue, guest OPD callbacks, `QueryAttr`/`OpenEx`/`QueryEsAttr`/`ResetEs`/`EnableEs`/`GetAu`/`ReleaseAu`/`FlushEs` |
| `third_party/ps3recomp/libs/codec/cellAdec.h/.c` | `cellAdecOpenEx`/`cellAdecOpenExt` aliases to the existing open |
| `gt6/src/gen/ppu_hle_nids.cpp` | registers the 9 missing `cellPamf`, 4 missing `cellDmux`, 2 `cellAdec` open NIDs (plus optional `GetHeaderSize`/iterator/`GetAuEx` aliases) |

### 6.1 `cellPamf` behaviour

* `cellPamfGetHeaderSize2` validates magic/version, computes
  `header_size = be32(0x08) * 0x800`, checks
  `header_size + data_size == fileSize`, and returns the u64 header size.
  `CELL_PAMF_ATTRIBUTE_MINIMUM_HEADER` returns
  `0x54 + seq_info.size` without touching group/stream/EP tables.
* `cellPamfVerify` additionally bounds the sequence/group/stream/EP tables
  and checks that EP `rpnOffset * 0x800` is non-decreasing and within the
  data area.
* `cellPamfReaderInitialize` stores host state keyed by the guest reader EA,
  zeroes the guest 128-byte object, and writes header/data size, attribute,
  version and indices. It does not write host pointers.
* `GetStreamInfo` writes the real AVC field order and the audio
  frequency/channel fields, with big-endian `vm_write16`/`vm_write32`.
* `GetEsFilterId` writes four u32 fields, not two bytes.
* `GetNumberOfEp` returns the current stream's `ep_num` directly.
* The EP iterator functions unpack the 12-byte records and maintain
  `pCur = base + ep_offset + index * 12`.

### 6.2 `cellDmux` behaviour

* `cellDmuxSetStream` accepts any chunking, keeps a small pending buffer,
  detects an optional `PAMF` header and skips `header_size` sectors, then
  finds `00 00 01 BA` pack starts and processes complete 2048-byte sectors.
* Packs are walked from offset 14; `0xBB`/`0xBF`/`0xBE` are skipped by
  length; `0xE0` and `0xBD` PES packets are parsed with PTS/DTS.
* Video ES bytes are assembled and split at AUD NALs. Completed AUs are
  copied into a bounded host queue (8 AUs / 8 MB per ES), then into the
  guest's `CellDmuxEsResource.memAddr` (or a committed HLE fallback) when
  `cellDmuxGetAu` is called. The first AU is queued first; see §8 for the
  full-playback backpressure limit.
* Audio ES bytes are assembled after the four-byte private prefix and split
  at `0F D0` ATS frames; the first inter-sync distance is used as the frame
  size. `au_includes_ats_hdr_flg=1` is preserved: the ATS header is part of
  the AU.
* PTS/DTS are taken from the PES mark at or before each AU start; if a PES
  does not carry a timestamp, the next frame is synthesized from the
  previous PTS plus 3003 ticks (video) or 3840 ticks (audio, 2048 samples
  at 48 kHz).
* `isRap` is true when the AVC AU contains an IDR NAL; audio frames are
  marked random-access.
* `AU_FOUND`, `FLUSH_DONE` and `DEMUX_DONE` are delivered through
  `g_ps3_guest_caller` with the public `CellDmuxMsg`/`CellDmuxEsMsg`
  layouts.
* `QueryAttr`, `QueryAttr2`, `OpenEx`, `QueryEsAttr`, `QueryEsAttr2`,
  `ResetEs`, `GetAuEx`, `FlushEs`, `ResetStream` and `Close` are all
  implemented; `PeekAu` aliases `GetAu` for compatibility.

The demuxer deliberately does **not** decrypt. The movie-layer Salsa20
stream is the guest's job; `cellPamf`/`cellDmux` only see plaintext PAMF,
exactly as RPCS3's HLE does.

---

## 7. Proof on the decrypted sample

The patch algorithm was replayed on a local decrypted copy
(`work/pamf_test/tv_10006.pam`) and compared with PAMFtool's demuxed output
(separate GPL process, reference only):

| Check | Result |
|---|---|
| Header/streams | `PAMF0041`, header `0x1000`, data `0x14ED4000`, 3 streams |
| AVC params | 1920×1088, crop bottom 4, High/4.1, `frameRateInfo=3` |
| EP table | 191 entries; first PTS 90,000, last PTS 12,279,177 |
| Video AUs | **4,079** |
| Video ES bytes | **339,175,131**, exactly PAMFtool's `s00_avc.h264` |
| Video ES SHA-256 | **equal** to PAMFtool's `s00_avc.h264` (full-file comparison) |
| AU 0 | **841 bytes**, PTS **90,000**, DTS **86,997**, IDR present |
| AU 1..3 | 137 bytes each, synthesized PTS 93,003 / 96,006 / 99,009 |
| Audio 2 ch | first `0F D0` at 0, frame size **696**; first PTS 85,470 |
| Audio 6 ch | first `0F D0` at 0, frame size **1,720**; first PTS 85,470 |
| Audio PTS cadence | 11,520 ticks per 3 frames (3 × 2,048 / 48 kHz) |

The first AU's PES carries PTS 90,000 and DTS 86,997; the next PES with a
timestamp is at ES offset `0xC61` (PTS 144,054) and belongs to the AU that
starts at `0xC62`. The mark rule in §6.2 consumes it for that AU and
synthesizes the intervening frames, which is why AU 1..17 get
93,003/96,006/… and AU 18 gets the exact 144,054.

The C sources were syntax-checked with LLVM/Clang 23 (`-std=c99 -Wall
-Wextra`) against the real ps3recomp headers; the generated NID table was
checked to compute every registration from its function name. The patch was
checked with `git apply --check` against the current tree; the touched
source/NID files are unchanged from `08f92ec`.

---

## 8. Proven vs. still missing

### Proven

* The real PAMF 0041 header/sequence/group/stream/EP layout and the
  2048-byte pack/PES layout.
* The exact guest ABI for the `cellPamf` and `cellDmux` structures used by
  GT6, and the real callback shapes.
* The NID set: all 18 `cellPamf` and 12 `cellDmux` imports resolve to the
  function names in the patch; `cellAdecOpenEx`/`Ext` are covered.
* The demux algorithm produces the correct AVC ES and the correct first AU
  on the decrypted opening (byte-exact against PAMFtool).
* The patch applies cleanly and the C translation is syntactically valid.
* `cellPamf`/`cellDmux` do not decrypt, do not use keys, and do not contain
  GPL code.

### Not proven / missing

| Gap | Consequence | Smallest next step |
|---|---|---|
| The port has not reached `MovieRoot` / `play_movie` | `cellPamf` is never called | continue the boot/PFS workstream; watch for the `cellPamf` log line |
| Guest-side movie decryption (`decodeContentsKey`/`setKey`) has not been observed in the native port | `cellPamf` would see random bytes and reject them | run with the guest decrypt path, or add a documented user-supplied pre-decrypt/VFS override; do not put keys in the HLE |
| `PS3RECOMP_FFMPEG_RUNTIME=OFF` in `gt6/build/CMakeCache.txt` | `cellVdec` uses the callback-only black placeholder; no real picture | reconfigure with `-DPS3RECOMP_FFMPEG_RUNTIME=ON` and an LGPL libavcodec header/runtime; do not point the runtime at the bundled GPL build |
| `cellAdec` is a silence stub | audio callbacks advance but there is no ATRAC3+ audio | accept silence for the first-frame milestone, or wire an LGPL ATRAC3+ decoder later |
| Movie texture/RSX presentation path | the decoded YUV frame may not be displayed | feed `cellVdecGetPicture` into the existing movie texture/present path |
| `M2V`, LPCM, AC-3 | the demuxer treats non-ATRAC3+ audio as ATRAC3+ and video as AVC | not needed for the opening; add per-coding splitters only when a title requires them |
| Bounded AU queue | the host queue holds 8 AUs / 8 MB per ES. A guest that submits a very large `cellDmuxSetStream` chunk without draining can see later AUs dropped. AU #1 is always queued first, so the first frame is unaffected | add backpressure (stop at a full queue and resume on `ReleaseAu`) or a larger queue for full playback |
| Full EOS / `PROG_END_CODE` | a player that waits for an end code at the end of the movie may not get one | see §9; the stop/skip path already works through `ResetStream`/`Close` |
| A/V sync and 6ch selection | audio timing is approximate and always silence | out of scope for the first frame |

**The patch alone therefore proves the HLE layer, not in-engine playback.**
The first decoded frame additionally requires the guest to reach the movie
player, the movie to be decrypted by the guest, and the FFmpeg-enabled
`cellVdec` build. The first *presented* frame also requires the texture/render
path.

---

## 9. Smallest path to the first decoded frame

1. **Apply the patch** (§10) and regenerate/keep the NID table.
2. **Configure a decoder-capable build.** `PS3RECOMP_FFMPEG_RUNTIME` is `OFF`
   in `gt6/build/CMakeCache.txt`. Turn it on and point
   `PS3RECOMP_FFMPEG_INCLUDE_DIR` at an LGPL FFmpeg build's headers; make
   sure the runtime can load that `libavcodec` (the bundled
   `tools/ffmpeg` is GPL and is an offline tool only). Without this,
   `cellVdec` logs “no libavcodec” and returns black pictures.
3. **Reach the movie script.** The PDI thread must call
   `cellPamfGetHeaderSize2(pAddr, fileSize=0x14ED5000, …)`. The patch then
   logs `PAMF41 header=0x1000 data=0x14ED4000 streams=3 …` and the three
   stream lines (0x1B/0xE0, 0xDC/0xBD/0, 0xDC/0xBD/1).
4. **Confirm the demuxer.** On the first `cellDmuxSetStream` the patch logs
   an ATRAC3+ frame size (696/1720) and
   `ES n: AU #1 size=841 pts=90000 dts=86997 rap=1`. That is the first video
   AU.
5. **Confirm the decoder.** `cellVdec` must log
   `decoding with libavcodec`; otherwise the build is still the stub path.
   `cellVdecGetPicture` then returns the 1920×1088 YUV420 picture (crop
   bottom 4 → 1920×1080).
6. **Present it.** Hand that picture to the movie texture/present path. The
   HLE side is complete for frame 1 at this point.

If step 3 never happens, the blocker is the boot/PFS/movie-player
workstream, not PAMF. If step 4 happens but step 5 logs no libavcodec, the
blocker is the build configuration. If step 5 happens but nothing is on
screen, the blocker is the texture/render path.

### EOS / reaching the menu

The stop/skip path is already covered:

* `cellDmuxResetStream` clears the pending pack and each ES assembly/queue.
* `cellDmuxResetEs` clears one ES.
* `cellDmuxDisableEs` frees the ES buffers.
* `cellDmuxClose` frees the demuxer and its ES.
* `cellDmuxFlushEs` finalizes the last partial AU and emits `FLUSH_DONE`.
* `cellVdecEndSeq` drains held pictures and emits `SEQDONE`;
  `cellAdecEndSeq` emits `SEQDONE`.

For a player that waits for an end-of-program notification, the smallest
additional stub is: in `dmux_pack`, when the `00 00 01 B9` program-end code
is seen, set a flag and emit `CELL_DMUX_MSG_TYPE_PROG_END_CODE` through the
normal demux callback (or emit it from `cellDmuxFlushEs`). The captured
136-second RPCS3 run does not prove GT6 needs that message, so it is not in
the patch; the teardown calls above are sufficient for the stop/skip path.

---

## 10. Apply and validate

```powershell
git apply patches/ps3recomp-cellpamf-celldmux-first-frame.patch
git apply --check patches/ps3recomp-cellpamf-celldmux-first-frame.patch   # after revert, checks cleanly
```

The patch touches `gt6/src/gen/ppu_hle_nids.cpp`, which is auto-generated.
Either keep the added lines or regenerate from the new source names:

```powershell
python third_party/ps3recomp/tools/gen_hle_nids.py --all `
  --out gt6/src/gen/ppu_hle_nids.cpp
```

`gen_hle_nids.py` computes NIDs from the function names, so the new
`cellPamfGetHeaderSize2`, `cellDmuxOpenEx`, `cellAdecOpenEx`, etc. register
the same values shown in §4.

Header-only validation on a **decrypted local copy** (no keys, no game data
committed):

```powershell
python tools/pamf_info.py work/pamf_test/tv_10006.pam --check-packs
```

Expected: `PAMF 0041`, header `0x1000`, 171,432 packs, stream 0 AVC
1920×1088 crop 4, 191 EPs, streams 1/2 ATRAC3+ 2 ch/6 ch. For AU counts,
the replay described in §7 is the reference; the HLE log should show 4,079
video AUs over the whole movie and AU #1 with size 841/pts 90000/rap 1.

**Do not** commit `work/pamf_test`, decrypted movies, `menudb.dat`, or any
key value.

---

## 11. Clean-room / licensing notes

* No PAMFtool (GPLv3), RPCS3 (GPLv2), or FFmpeg source was copied into the
  MIT runtime. PAMFtool and FFmpeg were used only as separate-process
  oracles on local copies; RPCS3 was used for the call-order log and public
  API/ABI facts.
* The container offsets, NID values and struct layouts are format/ABI facts,
  independently implemented in the patch.
* The patch contains no decryption, no keys, no key derivation, and no game
  data. `cellPamf` rejects a non-`PAMF` buffer; the guest is responsible for
  the movie-layer Salsa20 decryption.
* The bundled `tools/ffmpeg` build is GPL; keep it as an offline tool. The
  runtime's `cellVdec` loads a user-supplied LGPL libavcodec at run time.

---

## 12. Open questions

1. **Does the native port reach `MovieRoot` before the first movie?** The
   earlier checks report the port is still at the boot/presents stage
   (`draws: 0`); the HLE patch cannot answer this.
2. **Does the guest `decodeContentsKey`/`setKey` path run under the
   recompiled code?** The oracle proves it under RPCS3; the native port must
   execute the same path. If not, use a user-supplied pre-decrypt/VFS
   override, not a key in the HLE.
3. **Does the guest require audio PCM before displaying the first video
   frame?** The demuxer delivers both ESs and `cellAdec` returns silence
   PCMOUT, which is enough for callback-driven players. A player that waits
   for non-silent audio would need a real decoder.
4. **Does GT6 use the EP iterator for seeking?** The captured run does not
   call it; the functions are implemented for the pause/seek UI.
5. **Does GT6 need `PROG_END_CODE`?** Not observed in the captured run; the
   minimal hook is described in §9.
