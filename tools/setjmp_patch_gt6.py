#!/usr/bin/env python3
"""Make GT6 guest setjmp/longjmp transfer control instead of returning.

GT6's libc pair is 0xB98168 (setjmp) and 0xB9828C (longjmp), not the GT5P
addresses. The lifter emits longjmp's final `blr` as `return;`, so the guest
register file is restored and then control resumes in longjmp's caller instead
of at the setjmp site.

Two edits, both in gt6/generated/:

  * every call site of 0xB98168 gets a real host setjmp in the calling frame;
  * 0xB9828C keeps its original body (which restores the guest registers) and
    then fires a host longjmp to the matching setjmp site.

The runtime side is gt6/src/gt6_longjmp.cpp (gt6_jmp_push/host/fire/unwind).

Run after every relift:
    python tools/setjmp_patch_gt6.py gt6/generated
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SETJMP = "00B98168"
LONGJMP = "00B9828C"

DECLS = """
/* ---- setjmp_patch_gt6.py --------------------------------------------- */
#include <setjmp.h>
#include <stdint.h>
struct gt6_jmp;
extern "C" gt6_jmp* gt6_jmp_push(uint32_t buf_ea);
extern "C" jmp_buf* gt6_jmp_host(gt6_jmp* e);
extern "C" int      gt6_jmp_depth(void);
extern "C" void     gt6_jmp_unwind(int depth);
extern "C" void     gt6_jmp_fire(uint32_t buf_ea, int value);
"""

LONGJMP_WRAPPER = """
/* ---- setjmp_patch_gt6.py: guest longjmp ------------------------------ */
void func_%(lj)s(ppu_context* ctx)
{
    uint32_t buf = (uint32_t)ctx->gpr[3];
    int      val = (int)(int32_t)ctx->gpr[4];

    /* The original restores r1, r2, r13-r31, LR, CR and the FPRs. */
    gt6_orig_func_%(lj)s(ctx);
    DRAIN_TRAMPOLINE(ctx);

    /* Then actually go there. Returns only if no buffer is armed. */
    gt6_jmp_fire(buf, val);
}
"""

CALL_RE = re.compile(
    r"( *)ctx->lr = (0x[0-9A-Fa-f]+); func_" + SETJMP + r"\(ctx\); DRAIN_TRAMPOLINE\(ctx\);")

FUNC_RE = re.compile(r"^void (func_[0-9A-F]{8})\(ppu_context\* ctx\) \{")


def patch_call_sites(text: str) -> tuple[str, int]:
    def repl(m: re.Match[str]) -> str:
        ind, lr = m.group(1), m.group(2)
        return (
            f"{ind}{{ gt6_jmp* _j = gt6_jmp_push((uint32_t)ctx->gpr[3]);\n"
            f"{ind}  if (setjmp(*gt6_jmp_host(_j)) == 0) {{\n"
            f"{ind}      ctx->lr = {lr}; func_{SETJMP}(ctx); DRAIN_TRAMPOLINE(ctx);\n"
            f"{ind}  }} }}"
        )
    return CALL_RE.subn(repl, text)


def guard_callers(text: str, names: list[str]) -> tuple[str, int]:
    n = 0
    for name in names:
        define = f"void {name}(ppu_context* ctx) {{"
        if define not in text or f"gt6_orig_{name}" in text:
            continue
        text = text.replace(define, f"void gt6_orig_{name}(ppu_context* ctx) {{", 1)
        text += (
            f"\n/* ---- setjmp_patch_gt6.py: {name} arms a setjmp buffer ---- */\n"
            f"void {name}(ppu_context* ctx)\n{{\n"
            f"    int _d = gt6_jmp_depth();\n"
            f"    gt6_orig_{name}(ctx);\n"
            f"    gt6_jmp_unwind(_d);\n"
            f"}}\n"
        )
        n += 1
    return text, n


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    gen = Path(argv[1])

    total_sites = 0
    total_guards = 0
    did_longjmp = False
    for chunk in sorted(gen.glob("ppu_recomp_*.cpp")):
        text = chunk.read_text(encoding="latin-1")
        original = text
        if "setjmp_patch_gt6.py" in text:
            continue

        owners: list[str] = []
        for m in FUNC_RE.finditer(text):
            end = text.find("\nvoid ", m.end())
            body = text[m.start():end if end > 0 else len(text)]
            if f"func_{SETJMP}(ctx);" in body:
                owners.append(m.group(1))

        text, sites = patch_call_sites(text)
        total_sites += sites
        if sites:
            text = DECLS + text
            # Recompute the owners after wrapping: the setjmp call now sits
            # inside a `{ ... }` block, but the enclosing function is the same.
            wrapped_owners: list[str] = []
            for m in FUNC_RE.finditer(text):
                end = text.find("\nvoid ", m.end())
                body = text[m.start():end if end > 0 else len(text)]
                if "gt6_jmp_push" in body and f"gt6_orig_{m.group(1)}" not in text:
                    wrapped_owners.append(m.group(1))
            text, guards = guard_callers(text, wrapped_owners)
            total_guards += guards

        define = f"void func_{LONGJMP}(ppu_context* ctx) {{"
        if define in text:
            text = text.replace(
                define, f"void gt6_orig_func_{LONGJMP}(ppu_context* ctx) {{", 1)
            if DECLS not in text:
                text = DECLS + text
            text += LONGJMP_WRAPPER % {"lj": LONGJMP}
            did_longjmp = True

        if text != original:
            chunk.write_text(text, encoding="latin-1")
            print(f"  patched {chunk.name}")

    print(f"setjmp call sites wrapped: {total_sites}")
    print(f"arming functions guarded:  {total_guards}")
    print(f"longjmp rewritten:         {did_longjmp}")
    return 0 if total_sites and did_longjmp else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
