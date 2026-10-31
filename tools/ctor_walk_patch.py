#!/usr/bin/env python3
"""Keep the .ctors walker's table pointer across the constructor call.

`func_000118C8` walks the 722-entry .ctors table at 0x1410B48 downward and
keeps the next slot in r31. The constructor at slot 351 (OPD 0x14CCDB0 ->
0x6BCF30 -> 0x6BCE90) is a compiler-generated `__cxa_atexit` thunk that uses
the `_savegpr`/`_restgpr` helpers. The lifted body does not preserve r31 back
to the walker, so r31 becomes 0, the walker reads slot 0/0xFFFFFFFC and skips
the remaining 371 constructors -- including the PFS/GT.VOL descriptor
initializer at index 715.

On hardware r31 is callee-saved, so the walker is entitled to rely on it. This
patch restores the walker's own slot value after the indirect call. It is a
targeted workaround for the one ABI-lost register, not a general callee-save
emulation. Re-run after every relift.

Usage:
    python tools/ctor_walk_patch.py gt6/generated
"""
from __future__ import annotations

import sys
from pathlib import Path

FUNC = "func_000118C8"
CALL = "ctx->lr = 0x0001190C; ps3_indirect_call(ctx); DRAIN_TRAMPOLINE(ctx);"
PATCHED = "_gt6_ctor_slot31"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    gen = Path(argv[1])

    hits = 0
    for path in sorted(gen.glob("ppu_recomp_*.cpp")):
        text = path.read_text(encoding="latin-1")
        start = text.find(f"void {FUNC}(ppu_context* ctx)")
        if start < 0:
            continue
        end = text.find("\nvoid func_", start + 20)
        body = text[start:end if end >= 0 else len(text)]
        if PATCHED in body:
            print(f"{path.name}: {FUNC} already patched")
            hits += 1
            continue
        if body.count(CALL) != 1:
            print(f"{path.name}: expected one walker call in {FUNC}, "
                  f"found {body.count(CALL)}", file=sys.stderr)
            return 1
        patched = body.replace(
            CALL,
            "{ uint32_t _gt6_ctor_slot31 = (uint32_t)ctx->gpr[31];\n"
            "          " + CALL + "\n"
            "          ctx->gpr[31] = _gt6_ctor_slot31; }",
            1,
        )
        text = text[:start] + patched + text[end if end >= 0 else len(text):]
        path.write_text(text, encoding="latin-1")
        print(f"{path.name}: patched {FUNC} r31 preservation")
        hits += 1

    if hits != 1:
        print(f"expected exactly one {FUNC}, found {hits}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
