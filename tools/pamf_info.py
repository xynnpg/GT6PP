#!/usr/bin/env python3
"""Inspect a *decrypted* PlayStation Advanced Movie Format (.pam) file.

This is a clean-room reference parser for the PAMF 0040/0041 header layout.
It intentionally does not handle any encryption: GT5/GT6 movies on disc are
Salsa20-encrypted at the movie layer, and the game (or GTToolsSharp's
`cryptmovie` verb) decrypts them before PAMF sees them.  If the first four
bytes are not "PAMF", this tool says so instead of guessing.

Usage:
    python tools/pamf_info.py <file.pam> [--json]
    python tools/pamf_info.py <file.pam> --check-packs

The parser is useful for validating HLE cellPamf work: the offsets below are
the ones a correct `cellPamfReaderInitialize` must use.
"""
from __future__ import annotations

import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

SECTOR = 0x800

STREAM_TYPES = {
    0x02: "M2V (MPEG-2)",
    0x1B: "AVC (H.264)",
    0x80: "LPCM",
    0x81: "AC-3",
    0xDC: "ATRAC3plus",
    0xDD: "user data",
    0xFF: "PSMF",
}

AVC_PROFILES = {66: "Baseline", 77: "Main", 88: "Extended", 100: "High", 110: "High 10",
                122: "High 4:2:2", 244: "High 4:4:4"}
AVC_LEVELS = {21: "2.1", 30: "3.0", 31: "3.1", 32: "3.2", 41: "4.1", 42: "4.2", 51: "5.1"}
FRAME_RATES = {0: "24000/1001", 1: "24", 2: "25", 3: "30000/1001", 4: "30", 5: "50", 6: "60000/1001"}
AUDIO_FREQ = {1: 48000, 2: 44100}


def u8(b: bytes, off: int) -> int:
    return b[off]


def u16(b: bytes, off: int) -> int:
    return struct.unpack_from(">H", b, off)[0]


def u32(b: bytes, off: int) -> int:
    return struct.unpack_from(">I", b, off)[0]


def u64(b: bytes, off: int) -> int:
    return struct.unpack_from(">Q", b, off)[0]


@dataclass
class Stream:
    index: int
    coding_type: int
    stream_id: int
    private_stream_id: int
    p_std_buffer: int
    ep_offset: int
    ep_num: int
    specific: bytes
    info: dict = field(default_factory=dict)
    eps: list = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return STREAM_TYPES.get(self.coding_type, f"unknown 0x{self.coding_type:02X}")

    def decode_specific(self) -> None:
        s = self.specific
        if self.coding_type == 0x1B:  # AVC
            profile, level = s[0], s[1]
            x2, aspect = s[2], s[3]
            # The low nibble stores frame_rate_info + 1 (cellPamf subtracts 1
            # before reporting the SDK enum).
            fr_code = max(0, (x2 & 0x0F) - 1)
            self.info = {
                "profile": AVC_PROFILES.get(profile, profile),
                "level": AVC_LEVELS.get(level, level),
                "frame_mbs_only": (x2 >> 7) & 1,
                "video_signal_info": (x2 >> 6) & 1,
                "frame_rate": FRAME_RATES.get(fr_code, fr_code),
                "aspect_ratio_idc": aspect,
                "sar": [u16(s, 4), u16(s, 6)],
                "horizontal_size": s[9] * 16,
                "vertical_size": s[11] * 16,
                "crop": [u16(s, 12), u16(s, 14), u16(s, 16), u16(s, 18)],
                "video_format": (s[20] >> 5) & 0x07,
                "full_range": (s[20] >> 4) & 1,
                "colour_primaries": s[21],
                "transfer_characteristics": s[22],
                "matrix_coefficients": s[23],
                "entropy_coding": (s[24] >> 7) & 1,
                "deblocking": (s[24] >> 6) & 1,
                "min_slice_per_picture": (s[24] >> 4) & 0x03,
                "nfw_idc": s[24] & 0x03,
                "max_mean_bitrate": s[25],
            }
        elif self.coding_type == 0x02:  # M2V
            self.info = {
                "profile_and_level": s[0],
                "progressive": (s[2] >> 7) & 1,
                "frame_rate": s[2] & 0x0F,
                "aspect_ratio_idc": s[3],
                "sar": [u16(s, 4), u16(s, 6)],
                "horizontal_size": s[9] * 16,
                "vertical_size": s[11] * 16,
            }
        elif self.coding_type in (0xDC, 0x81, 0x80):  # audio
            self.info = {
                "channels": s[2],
                "sampling_frequency": AUDIO_FREQ.get(s[3], s[3]),
                "bits_per_sample": s[4] if self.coding_type == 0x80 else None,
            }

    def parse_eps(self, data: bytes) -> None:
        if not self.ep_num:
            return
        for i in range(self.ep_num):
            off = self.ep_offset + i * 12
            if off + 12 > len(data):
                break
            value0 = u16(data, off)
            pts = (u16(data, off + 2) << 32) | u32(data, off + 4)
            rpn = u32(data, off + 8)
            self.eps.append({
                "index": i,
                "index_n": (value0 >> 14) + 1,
                "nth_ref_picture_offset": ((value0 & 0x1FFF) * 0x800) + 0x800,
                "pts": pts,
                "rpn_offset": rpn * 0x800,
            })


@dataclass
class Pamf:
    file_size: int
    magic: bytes
    version: bytes
    header_sectors: int
    data_sectors: int
    psmf_marks_offset: int
    psmf_marks_size: int
    unk_offset: int
    unk_size: int
    seq_size: int
    start_pts: int
    end_pts: int
    mux_rate_bound: int
    std_delay_bound: int
    total_streams: int
    grouping_period_num: int
    group_num: int
    streams: list[Stream] = field(default_factory=list)

    @property
    def header_size(self) -> int:
        return self.header_sectors * SECTOR

    @property
    def data_size(self) -> int:
        return self.data_sectors * SECTOR

    @property
    def version_str(self) -> str:
        return self.version.decode("ascii", "replace")


def parse(path: Path) -> Pamf:
    data = path.read_bytes()
    size = len(data)
    if size < 0x100:
        raise ValueError("file is too small to be PAMF")
    if data[:4] != b"PAMF":
        raise ValueError(
            f"bad magic {data[:4].hex(' ')} (expected 'PAMF'); "
            "the file is probably still Salsa20-encrypted (GTToolsSharp cryptmovie) "
            "or is not PAMF at all"
        )

    p = Pamf(
        file_size=size,
        magic=data[:4],
        version=data[4:8],
        header_sectors=u32(data, 0x08),
        data_sectors=u32(data, 0x0C),
        psmf_marks_offset=u32(data, 0x10),
        psmf_marks_size=u32(data, 0x14),
        unk_offset=u32(data, 0x18),
        unk_size=u32(data, 0x1C),
        seq_size=u32(data, 0x50),
        start_pts=u32(data, 0x58),
        end_pts=u32(data, 0x5E),
        mux_rate_bound=u32(data, 0x62),
        std_delay_bound=u32(data, 0x66),
        total_streams=u32(data, 0x6A),
        grouping_period_num=data[0x6F],
        group_num=data[0x81],
    )

    # SequenceInfo @0x50 -> GroupingPeriod @0x70 -> Group @0x82 -> streams @0x88
    group_off = 0x82
    stream_num = data[0x87]
    stream_off = group_off + 6
    for i in range(stream_num):
        off = stream_off + i * 48
        if off + 48 > len(data):
            raise ValueError(f"stream {i} header lies outside the file")
        s = Stream(
            index=i,
            coding_type=data[off],
            stream_id=data[off + 4],
            private_stream_id=data[off + 5],
            p_std_buffer=u16(data, off + 6),
            ep_offset=u32(data, off + 8),
            ep_num=u32(data, off + 12),
            specific=data[off + 16:off + 48],
        )
        s.decode_specific()
        s.parse_eps(data)
        p.streams.append(s)

    if p.header_size + p.data_size != size:
        raise ValueError(
            f"header_size + data_size (0x{p.header_size:X} + 0x{p.data_size:X} = "
            f"0x{p.header_size + p.data_size:X}) != file size 0x{size:X}"
        )
    return p


def check_packs(p: Pamf, path: Path) -> dict:
    data = path.read_bytes()
    start = p.header_size
    pack_count = 0
    off = start
    # PAMF data is a sequence of 2048-byte sectors, each starting with a
    # pack header 00 00 01 BA.  Count them; then locate the first video and
    # private-stream PES headers in the first sector as a sanity check.
    while off + 4 <= len(data):
        if data[off:off + 4] == b"\x00\x00\x01\xBA":
            pack_count += 1
        off += SECTOR
    first = data[start:min(start + SECTOR, len(data))]
    def first_pes(sid: int) -> int | None:
        pat = bytes((0, 0, 1, sid))
        i = first.find(pat)
        return None if i < 0 else start + i
    return {
        "first_pack": data[start:start + 4].hex(" "),
        "pack_sectors": pack_count,
        "declared_data_sectors": p.data_sectors,
        "first_video_pes_offset": first_pes(0xE0),
        "first_private_pes_offset": first_pes(0xBD),
    }


def to_json(p: Pamf, packs: dict | None) -> str:
    d = {
        "file_size": p.file_size,
        "magic": p.magic.decode("ascii", "replace"),
        "version": p.version_str,
        "header_sectors": p.header_sectors,
        "data_sectors": p.data_sectors,
        "header_size": p.header_size,
        "data_size": p.data_size,
        "psmf_marks_offset": p.psmf_marks_offset,
        "psmf_marks_size": p.psmf_marks_size,
        "unk_offset": p.unk_offset,
        "unk_size": p.unk_size,
        "seq_size": p.seq_size,
        "start_pts": p.start_pts,
        "end_pts": p.end_pts,
        "mux_rate_bound": p.mux_rate_bound,
        "std_delay_bound": p.std_delay_bound,
        "total_streams": p.total_streams,
        "grouping_period_num": p.grouping_period_num,
        "group_num": p.group_num,
        "streams": [],
    }
    for s in p.streams:
        sd = {
            "index": s.index,
            "coding_type": s.coding_type,
            "type_name": s.type_name,
            "stream_id": s.stream_id,
            "private_stream_id": s.private_stream_id,
            "p_std_buffer": s.p_std_buffer,
            "ep_offset": s.ep_offset,
            "ep_num": s.ep_num,
            "specific_hex": s.specific.hex(" "),
            "info": s.info,
            "first_ep": s.eps[0] if s.eps else None,
            "last_ep": s.eps[-1] if s.eps else None,
        }
        d["streams"].append(sd)
    if packs:
        d["pack_check"] = packs
    return json.dumps(d, indent=2)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 1
    path = Path(argv[1])
    as_json = "--json" in argv
    do_packs = "--check-packs" in argv
    try:
        p = parse(path)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    packs = check_packs(p, path) if do_packs else None
    if as_json:
        print(to_json(p, packs))
        return 0

    print(f"File:            {path}")
    print(f"File size:       {p.file_size:,} bytes")
    print(f"Magic/version:   {p.magic.decode()} {p.version_str}")
    print(f"Header:          {p.header_size:,} bytes ({p.header_sectors} sector(s))")
    print(f"Data:            {p.data_size:,} bytes ({p.data_sectors} sectors)")
    print(f"PSMF marks/unk:  {p.psmf_marks_offset:#x}/{p.psmf_marks_size:#x}  "
          f"{p.unk_offset:#x}/{p.unk_size:#x}")
    print(f"Start/end PTS:   {p.start_pts:#x} ({p.start_pts / 90000:.4f}s) .. "
          f"{p.end_pts:#x} ({p.end_pts / 90000:.4f}s) "
          f"= {max(0, p.end_pts - p.start_pts) / 90000:.4f}s")
    print(f"Mux rate bound:  {p.mux_rate_bound:,} (x50 B/s = {p.mux_rate_bound * 50 * 8 / 1e6:.2f} Mbps)")
    print(f"Std delay:       {p.std_delay_bound} ticks")
    print(f"Streams:         {p.total_streams} (group_num={p.group_num})")

    for s in p.streams:
        print()
        print(f"Stream #{s.index}: {s.type_name}  coding=0x{s.coding_type:02X} "
              f"id=0x{s.stream_id:02X} private=0x{s.private_stream_id:02X}")
        print(f"  p_std_buffer: 0x{s.p_std_buffer:04X}  ep_offset=0x{s.ep_offset:X}  ep_num={s.ep_num}")
        if s.info:
            print(f"  info:         {json.dumps(s.info)}")
        if s.eps:
            print(f"  EP[0]:        pts={s.eps[0]['pts'] / 90000:.3f}s rpn=0x{s.eps[0]['rpn_offset']:X}")
            print(f"  EP[-1]:       pts={s.eps[-1]['pts'] / 90000:.3f}s rpn=0x{s.eps[-1]['rpn_offset']:X}")

    if packs:
        print()
        print("Pack check:")
        for k, v in packs.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
