#!/usr/bin/env python3
"""Generate ``patches/gt6-boot-ui-probe.patch`` (read-only diagnostics).

Purpose
-------
The native port loads ``MenuClassDefine``/``Prototypes``/``cursor`` and then
stops loading UI assets.  It never opens ``projects/gt6/boot/boot.mproject``
(K/KG), ``boot.adc`` (K/LH), ``BootProject.gpb`` (K/IE),
``PresentsRootSCEA.gpb`` (K/WD) or the font keys, so
``display_sequence_gt6``/``presents_sequence_common`` never runs.

The script path is not the question any more: ``MenuClassDefine`` is required
only by ``main.adc:initMenuSystem``, which is called only by ``execBoot``, which
is called only by the main.adc top-level frame.  Native does load it, so
``execBoot`` ran.  The open question is what happens at the engine boundary
``MGOM.start("boot")`` (guest 0x006C54DC):

  * 0x006C54DC  MMenuGameObjectManager::start   (start an existing object)
  * 0x006C5478  start implementation (name -> object)
  * 0x005FA338  MProject loader: appends ".mproject" then 0x005F0424
  * 0x005F0424  project existence/load helper
  * 0x005F7D9C  mManager::loadPackage (".mpackage" path; MainLoop menu load)
  * 0x009F79A8  file/package open helper used by 0x005F7D9C

Every line is ``fprintf``-only and is gated by ``GT6_BOOTUI_TRACE=1`` so the
patch can stay applied during other work.  No guest register, memory word or
vtable is written.

Usage:
    python tools/gt6_boot_ui_probe.py            # write patches/gt6-boot-ui-probe.patch
    python tools/gt6_boot_ui_probe.py --check    # fail if an anchor is missing

Apply to a scratch generated tree only (the normal post-lift step owns the
real tree):

    git apply patches/gt6-boot-ui-probe.patch
    powershell -File scripts/build-gt6.ps1
    $env:GT6_BOOTUI_TRACE="1"; gt6\build\gt6.exe work\bin\EMAIN.elf

Expected lines are listed in docs/analysis/first-visible-ui-fix.md.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "gt6" / "generated"
OUT = ROOT / "patches" / "gt6-boot-ui-probe.patch"

# A guest-memory string printer that never writes and never faults: the probe
# runs before the function has validated its arguments, so cap the read and
# stop at the first NUL.  Non-printable bytes become '.'.
STR_HELPER = (
    "        {{ uint32_t _a = (uint32_t)ctx->gpr[{reg}];\n"
    "          char _s[80]; int _i; _s[0] = 0;\n"
    "          for (_i = 0; _i < 79; _i++) {{ unsigned char _c = vm_read8((uint64_t)_a + _i);\n"
    "            if (!_c) break; _s[_i] = (_c >= 32 && _c < 127) ? (char)_c : '.'; }}\n"
    "          _s[_i] = 0;\n"
    "          fprintf(stderr, \"[bootui] {tag} arg=0x%08X s='%s'\\n\", _a, _s); }}\n"
)


def gate(tag: str) -> str:
    return (
        "        { static int _bootui = -1;\n"
        "          if (_bootui < 0) { const char* _e = getenv(\"GT6_BOOTUI_TRACE\");\n"
        "                             _bootui = (_e && *_e && *_e != '0') ? 1 : 0; }\n"
        "          if (_bootui) {\n"
    )


def close_gate() -> str:
    return "          } }\n"


def emit(tag: str, fmt: str, args: str, regs: tuple[int, ...] = ()) -> str:
    text = gate(tag) + f'            fprintf(stderr, "[bootui] {fmt}\\n", {args});\n'
    for reg in regs:
        text += STR_HELPER.format(reg=reg, tag=tag)
    text += close_gate()
    return text


def insert_after(text: str, anchor: str, addition: str) -> str:
    if anchor not in text:
        raise SystemExit("anchor not found:\n" + anchor)
    if addition.strip() in text:
        return text
    return text.replace(anchor, anchor + addition, 1)


def patch_file(name: str, edits: list[tuple[str, str]]) -> str:
    orig = (GEN / name).read_text(encoding="utf-8", errors="surrogateescape")
    mod = orig
    for anchor, addition in edits:
        mod = insert_after(mod, anchor, addition)
    # getenv() needs <stdlib.h>; the generated chunks do not include it.
    if "GT6_BOOTUI_TRACE" in mod and "#include <stdlib.h>" not in mod:
        anchor = '#include "ppu_recomp.h"\n'
        if anchor in mod:
            mod = mod.replace(anchor, anchor + "#include <stdlib.h>\n", 1)
        else:
            mod = "#include <stdlib.h>\n" + mod
    return "".join(difflib.unified_diff(
        orig.splitlines(keepends=True), mod.splitlines(keepends=True),
        fromfile=f"a/gt6/generated/{name}", tofile=f"b/gt6/generated/{name}", n=4))


def main(argv: list[str]) -> int:
    check = "--check" in argv

    p022 = patch_file("ppu_recomp_022.cpp", [
        (
            "void func_009F79A8(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            emit("file_open",
                 "file_open out=0x%08X path=0x%08X r5=0x%08X r6=0x%08X",
                 "(unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4], "
                 "(unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6]",
                 (4,)),
        ),
        (
            "void func_009E911C(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { static int _n; if ((uint32_t)ctx->gpr[11] == 0 && _n++ < 16) {\n'
            '            uint32_t _o = (uint32_t)ctx->gpr[3];\n'
            '            uint32_t _b = (_o >= 0x10000u) ? vm_read32((uint64_t)_o + 4u) : 0u;\n'
            '            uint32_t _p = (_o >= 0x10000u) ? vm_read32((uint64_t)_o + 0x1Cu) : 0u;\n'
            '            fprintf(stderr, "[bootui] NULL value_dispatch r3=0x%08X b=0x%08X p=0x%08X lr=0x%08X tid=%llu\\n",\n'
            '                    _o, _b, _p, (unsigned)ctx->lr, (unsigned long long)ctx->thread_id); } }\n',
        ),
        (
            "void func_009E2914(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { uint32_t _t = (uint32_t)ctx->gpr[3];\n'
            '          uint32_t _b = (_t >= 0x10000u) ? vm_read32((uint64_t)_t + 0x50u) : 0u;\n'
            '          uint32_t _e = (_t >= 0x10000u) ? vm_read32((uint64_t)_t + 0x54u) : 0u;\n'
            '          if (_b) fprintf(stderr, "[bootui] vector_clear this=0x%08X begin=0x%08X end=0x%08X count=%u lr=0x%08X tid=%llu\\n",\n'
            '                  _t, _b, _e, (_e >= _b) ? (_e - _b) / 4u : 0u, (unsigned)ctx->lr, (unsigned long long)ctx->thread_id); }\n',
        ),
        # Per-instruction trace of the script frame loop (0x9EEA88): opcode
        # byte, source line and VM status after each instruction.  Status 5 =
        # keep running, 4 = call pushed, 1 = frame returned.  Printed for tid 1
        # when the status changes or the line is in initApp (142..148).
        (
            "loc_009EEC10:\n        vm_write32(ctx->gpr[31] + 0x1C, ctx->gpr[7]);\n",
            '        gt6_bootui_ins = (uint32_t)ctx->gpr[10]; gt6_bootui_fr = (uint32_t)ctx->gpr[31];\n',
        ),
        (
            "        ctx->lr = 0x009EEC40; ps3_indirect_call(ctx); DRAIN_TRAMPOLINE(ctx);\n",
            '        { static int _n; uint32_t _w = vm_read32(gt6_bootui_ins); uint32_t _ln = _w & 0xFFFFFFu;\n'
            '          uint32_t _st = vm_read32(vm_read32(gt6_bootui_fr + 0x4) + 0x24);\n'
            '          if (getenv("GT6_BOOTUI_TRACE") && ctx->thread_id == 1 && ((_ln >= 0x8E && _ln <= 0x94) || _st != 5) && _n++ < 3000)\n'
            '            fprintf(stderr, "[bootui] ins frame=0x%08X ins=0x%08X op=0x%02X line=%u st=%u\\n",\n'
            '                    gt6_bootui_fr, gt6_bootui_ins, _w >> 24, _ln, _st); }\n',
        ),
        (
            '#include "ppu_recomp.h"\n',
            "static thread_local uint32_t gt6_bootui_ins, gt6_bootui_fr;\n",
        ),
        (
            "void func_009EEA88(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { static int _n; if (_n++ < 128) {\n'
            '            uint32_t _e = (uint32_t)ctx->gpr[3];\n'
            '            uint32_t _p = (_e >= 0x10000u) ? vm_read32((uint64_t)_e + 4u) : 0u;\n'
            '            uint32_t _q = (_e >= 0x10000u) ? vm_read32((uint64_t)_e + 0x1Cu) : 0u;\n'
            '            fprintf(stderr, "[bootui] exec_step this=0x%08X bytecode=0x%08X pc=0x%08X\\n",\n'
            '                    _e, _p, _q); } }\n',
        ),
    ])

    p035 = patch_file("ppu_recomp_035.cpp", [
        (
            "void func_00DFA51C(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { static int _n; if (_n++ < 128)\n'
            '            fprintf(stderr, "[bootui] builtin_dispatch this=0x%08X r4=0x%08X r5=0x%08X r6=0x%08X r7=0x%08X r8=0x%08X\\n",\n'
            '                    (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4], (unsigned)ctx->gpr[5],\n'
            '                    (unsigned)ctx->gpr[6], (unsigned)ctx->gpr[7], (unsigned)ctx->gpr[8]); }\n',
        ),
    ])

    p012 = patch_file("ppu_recomp_012.cpp", [
        (
            "void func_00568C94(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { uint32_t _t = (uint32_t)ctx->gpr[3]; uint32_t _v = (_t >= 0x10000u) ? vm_read32(_t) : 0u;\n'
            '          fprintf(stderr, "[bootui] context_start obj=0x%08X name=0x%08X vt=0x%08X\\n",\n'
            '                  _t, (unsigned)ctx->gpr[4], _v); }\n',
        ),
    ])

    p013 = patch_file("ppu_recomp_013.cpp", [
        (
            "void func_005FA338(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            emit("project_load",
                 "project_load this=0x%08X base=0x%08X name=0x%08X r6=%u r7=%u",
                 "(unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4], "
                 "(unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6], "
                 "(unsigned)ctx->gpr[7]",
                 (4, 5)),
        ),
        (
            "void func_005F7D9C(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            emit("package_load",
                 "package_load this=0x%08X name=0x%08X",
                 "(unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4]",
                 (4,)),
        ),
        (
            "void func_005E6B94(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        { uint32_t _t = (uint32_t)ctx->gpr[3];\n'
            '          uint32_t _o = (_t >= 0x10000u) ? vm_read32((uint64_t)_t + 0x48u) : 0u;\n'
            '          fprintf(stderr, "[bootui] object_slot this=0x%08X slot48=0x%08X\\n", _t, _o); }\n',
        ),
    ])

    p015 = patch_file("ppu_recomp_015.cpp", [
        (
            "void func_006C54DC(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            emit("MGOM.start",
                 "MGOM.start this=0x%08X argstr=0x%08X len=0x%08X r6=0x%08X",
                 "(unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4], "
                 "(unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6]",
                 (4,)),
        ),
        (
            "void func_006C5478(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            emit("MGOM.start_impl",
                 "MGOM.start_impl this=0x%08X name=0x%08X",
                 "(unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4]",
                 (4,)),
        ),
        (
            "void func_006C4C80(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[bootui] singleton this=0x%08X r4=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4]);\n',
        ),
        (
            "void func_006C5064(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[bootui] class_registrar r3=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3]);\n',
        ),
        (
            "void func_006C4EC0(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[bootui] class_register_impl this=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3]);\n',
        ),
        (
            "void func_006C4A5C(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[bootui] mgom_ctor out=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3]);\n',
        ),
        (
            "void func_006C55DC(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[bootui] mgom_factory this=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3]);\n',
        ),
    ])

    diff = p015 + p013 + p022 + p035 + p012
    if not diff:
        print("boot UI probes already present in gt6/generated; nothing to generate")
        return 0
    if check:
        print("boot UI probe anchors found")
        return 0
    OUT.write_text(diff, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(diff)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
