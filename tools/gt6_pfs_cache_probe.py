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
