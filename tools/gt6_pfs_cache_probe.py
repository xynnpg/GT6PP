#!/usr/bin/env python3
"""Generate patches/gt6-pfs-cache-probe.patch (read-only diagnostics).

The probe answers the question the cellFs-level trace alone cannot: does the
guest reach the PDIPFS block writer, and with what cached-size field?

    GT6_PFS_CACHE_TRACE=1 gt6.exe work/bin/EMAIN.elf ...

The generated tree is not modified here.  Apply the emitted patch with the
normal patch step if the owner wants guest-address-level probes:

    0x9FDC5C  cache attach arguments (path, size, id, source base)
    0xA42108  cache object construction
    0xA41FEC  .fdupm header loaded (block count, size, id)
    0xA420AC  cellFsAllocateFileAreaWithoutZeroFill return
    0xA40FBC  PFS read entry (file, offset, length)
    0xA40984  cache block write entry (cached size, block, offset, length)

Every line is fprintf-only; no guest register or memory is modified.
"""

from __future__ import annotations

import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "gt6" / "generated"


def insert_after(text: str, anchor: str, addition: str) -> str:
    if anchor not in text:
        raise SystemExit("anchor not found:\n" + anchor)
    if addition.strip() in text:
        return text
    return text.replace(anchor, anchor + addition, 1)


def patch_022(name: str) -> str:
    orig = (GEN / name).read_text(encoding="utf-8", errors="surrogateescape")
    mod = insert_after(
        orig,
        "        ctx->gpr[7] = (int64_t)(int32_t)(0);\n"
        "        ctx->lr = 0x009FDC60; func_00A422A0(ctx); DRAIN_TRAMPOLINE(ctx);\n",
        '        fprintf(stderr, "[pfscache] 0x9FDC5C attach path=0x%08X '
        'size=0x%llX id=0x%llX base=0x%llX\\n",\n'
        '                (unsigned)ctx->gpr[4], (unsigned long long)ctx->gpr[5],\n'
        '                (unsigned long long)ctx->gpr[6], '
        '(unsigned long long)ctx->gpr[7]);\n',
    )

    # FileStream open (guest 0x9F4130): the HFileReader stores the opened
    # FileObject at this+0x44.  Log what the device returned and its device /
    # size fields, so a zero-size file is visible even when the cache was
    # attached and sized from the TOC.
    mod = insert_after(
        mod,
        "        vm_write32(ctx->gpr[31] + 0x44, ctx->gpr[3]);\n",
        '        { uint32_t _f = (uint32_t)ctx->gpr[3];\n'
        '          if (_f >= 0x10000u && _f < 0xE0000000u) {\n'
        '            uint32_t _d = vm_read32(_f + 0x40u);\n'
        '            fprintf(stderr, "[fileopen] 9F4130 this=0x%08X path=0x%08X '
        'file=0x%08X vt=0x%08X dev=0x%08X dev_vt=0x%08X size=0x%llX\\n",\n'
        '                    (unsigned)ctx->gpr[31], (unsigned)ctx->gpr[28], _f,\n'
        '                    (unsigned)vm_read32(_f), _d,\n'
        '                    (unsigned)(_d ? vm_read32(_d) : 0u),\n'
        '                    (unsigned long long)vm_read64(_f + 0xC0u)); }\n',
    )

    # FileStream open helper (0x9F44D8): slot +0x8C -> PFS open (0xA010C0).
    mod = insert_after(
        mod,
        "void func_009F44D8(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[fileopen] 9F44D8 stream=0x%08X '
        'file=0x%08X\\n",\n'
        '                (unsigned)ctx->gpr[3],\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x44u));\n',
    )

    # FileStream read helper (0x9F4AA0): slot +0x90 -> PFS read (0xA0043C ->
    # 0xA40FBC cache_read).  HFileReader::read calls this only when it needs
    # bytes; its absence means the file was treated as EOF/zero-size.
    mod = insert_after(
        mod,
        "void func_009F4AA0(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        { uint32_t _s = (uint32_t)ctx->gpr[3];\n'
        '          uint32_t _f = vm_read32(_s + 0x44u);\n'
        '          uint32_t _c = _f ? vm_read32(_f + 0x88u) : 0u;\n'
        '          uint32_t _st = vm_read32(_s + 0x4Cu);\n'
        '          uint32_t _sv = _st ? vm_read32(_st) : 0u;\n'
        '          fprintf(stderr, "[fileread] 9F4AA0 stream=0x%08X req=0x%08X '
        'file=0x%08X cache=0x%08X z=0x%llX state=0x%08X state_vt=0x%08X '
        'slot90=0x%08X\\n",\n'
        '                  _s, (unsigned)ctx->gpr[4], _f, _c,\n'
        '                  (unsigned long long)(_c ? vm_read64(_c + 0x10u) : 0u),\n'
        '                  _st, _sv,\n'
        '                  (unsigned)(_sv ? vm_read32(_sv + 0x90u) : 0u)); }\n',
    )

    # Device open (0x9F8E40 slot +0x38): log the FileInfo size and the object
    # returned to 0x9F4130.  r29 is the FileInfo from 0xA09FC8, r27 is the
    # output File*, r30 is the returned File*.
    mod = insert_after(
        mod,
        "        ctx->gpr[30] = ppc_rldicl(ctx->gpr[3], 0, 32);\n"
        "        if (((ctx->cr >> 1) & 1)) goto loc_009F8F6C;\n",
        '        fprintf(stderr, "[fileopen] 9F8E40 info=0x%08X '
        'info+3C=0x%08X info+40=0x%08X file=0x%08X\\n",\n'
        '                (unsigned)ctx->gpr[29],\n'
        '                (unsigned)vm_read32(ctx->gpr[29] + 0x3Cu),\n'
        '                (unsigned)vm_read32(ctx->gpr[29] + 0x40u),\n'
        '                (unsigned)ctx->gpr[30]);\n',
    )

    # HFileReader::read (0x9BB020): the buffer/position/size gate.  If r5 is
    # nonzero but this returns without calling 0x9F4AA0, the FileObject size
    # (0x1A8) or the remaining buffer (0x1B0 - 0x1AC) is zero.
    mod = insert_after(
        mod,
        "void func_009BB020(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[fileread] 9BB020 reader=0x%08X '
        'want=0x%08X buf=0x%08X pos=0x%08X end=0x%08X\\n",\n'
        '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[5],\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x1A8u),\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x1ACu),\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x1B0u));\n',
    )

    # Thread body/arg (0x9F8078): the boot-time null calls are on worker
    # threads whose argument is a main-thread stack object.  Log the argument,
    # its vtable and the slot the body calls (+0x48), so the owner can be found.
    mod = insert_after(
        mod,
        "void func_009F8078(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        { uint32_t _a = (uint32_t)ctx->gpr[3];\n'
        '          uint32_t _v = vm_read32(_a);\n'
        '          fprintf(stderr, "[thread] 9F8078 arg=0x%08X vt=0x%08X '
        'slot48=0x%08X\\n", _a, _v, (unsigned)vm_read32(_v + 0x48u)); }\n',
    )

    return "".join(difflib.unified_diff(
        orig.splitlines(keepends=True), mod.splitlines(keepends=True),
        fromfile=f"a/gt6/generated/{name}", tofile=f"b/gt6/generated/{name}", n=4))


def patch_023(name: str) -> str:
    orig = (GEN / name).read_text(encoding="utf-8", errors="surrogateescape")
    mod = orig
    mod = insert_after(
        mod,
        "void func_00A42108(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[pfscache] 0xA42108 attach size=0x%llX '
        'id=0x%llX path=0x%08X\\n",\n'
        '                (unsigned long long)ctx->gpr[5], '
        '(unsigned long long)ctx->gpr[6], (unsigned)ctx->gpr[4]);\n',
    )
    # Thread trampoline (0xA304D0): identify the worker entry and argument.
    # The boot-time 0x9F7FF0/0x9F811C/0x9F8534 null calls happen when this
    # trampoline passes a main-stack argument to the thread body.
    mod = insert_after(
        mod,
        "void func_00A304D0(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[thread] A304D0 thread=0x%08X '
        'entry=0x%08X arg=0x%08X tid=%llu\\n",\n'
        '                (unsigned)ctx->gpr[3],\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x18u),\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x1Cu),\n'
        '                (unsigned long long)ctx->thread_id);\n',
    )
    # FileDeviceHost StartRead (0xA08ED0): r4 is the live FileStream, +0x1C29
    # is the read-active byte.  W2's PFS path should not enter this, but the
    # log distinguishes "host-device flush/StartRead" from "PFS read".
    mod = insert_after(
        mod,
        "void func_00A08ED0(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[filehost] A08ED0 dev=0x%08X stream=0x%08X '
        'active=0x%02X old=0x%08X\\n",\n'
        '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],\n'
        '                (unsigned)vm_read8(ctx->gpr[3] + 0x1C29u),\n'
        '                (unsigned)vm_read32(ctx->gpr[3] + 0x1C2Cu));\n',
    )
    # PFS file cache configuration (0xA3EB60): r4-r8 are the cache fields set
    # by the mount open.  If r6 (stored at cache+0x38) is the size the reader
    # uses, a zero here with a 0xEA57 cache header is the size-source bug.
    mod = insert_after(
        mod,
        "void func_00A3EB60(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[fileopen] A3EB60 file=0x%08X r4=0x%08X '
        'r5=0x%08X r6=0x%08X r7=0x%08X r8=0x%08X\\n",\n'
        '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],\n'
        '                (unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6],\n'
        '                (unsigned)ctx->gpr[7], (unsigned)ctx->gpr[8]);\n',
    )
    mod = insert_after(
        mod,
        "loc_00A41FEC:\n",
        '        fprintf(stderr, "[pfscache] 0xA41FEC map loaded blocks=%u '
        'size=0x%llX id=0x%llX\\n",\n'
        '                (unsigned)vm_read32(ctx->gpr[1] + 0x80),\n'
        '                (unsigned long long)vm_read64(ctx->gpr[1] + 0x70),\n'
        '                (unsigned long long)vm_read64(ctx->gpr[1] + 0x78));\n',
    )
    mod = insert_after(
        mod,
        "        ctx->lr = 0x00A420AC; func_00F924B0(ctx); DRAIN_TRAMPOLINE(ctx);\n",
        '        fprintf(stderr, "[pfscache] 0xA420AC allocate size=0x%llX '
        '-> 0x%08X\\n",\n'
        '                (unsigned long long)ctx->gpr[29], (unsigned)ctx->gpr[3]);\n',
    )
    mod = insert_after(
        mod,
        "void func_00A40FBC(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[pfscache] 0xA40FBC read file=0x%08X '
        'off=0x%llX len=0x%llX\\n",\n'
        '                (unsigned)ctx->gpr[3], (unsigned long long)ctx->gpr[5],\n'
        '                (unsigned long long)ctx->gpr[6]);\n',
    )
    mod = insert_after(
        mod,
        "void func_00A40984(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
        '        fprintf(stderr, "[pfscache] 0xA40984 write cache=0x%08X '
        'size=0x%llX block=%u off=%u len=%u\\n",\n'
        '                (unsigned)ctx->gpr[3], '
        '(unsigned long long)vm_read64(ctx->gpr[3] + 0x10),\n'
        '                (unsigned)ctx->gpr[4], (unsigned)ctx->gpr[5], '
        '(unsigned)ctx->gpr[6]);\n',
    )
    return "".join(difflib.unified_diff(
        orig.splitlines(keepends=True), mod.splitlines(keepends=True),
        fromfile=f"a/gt6/generated/{name}", tofile=f"b/gt6/generated/{name}", n=4))


def main() -> int:
    out = patch_022("ppu_recomp_022.cpp") + patch_023("ppu_recomp_023.cpp")
    path = ROOT / "patches" / "gt6-pfs-cache-probe.patch"
    path.write_text(out, encoding="utf-8", errors="surrogateescape", newline="\n")
    print(f"{path} {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
