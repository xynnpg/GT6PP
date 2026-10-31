#!/usr/bin/env python3
"""Verify hand-verified PPU function bodies after a relift.

The lifter rebuilds gt6/generated/ wholesale, so any hand edit disappears. The
lesson from 0xA13644 is worth encoding: it is a real 0x5C-byte function that
locks a mutex, calls 0x3C0E84, unlocks and returns `rldicl(r29,0,56)`. It is NOT
the 8-byte leaf getter that an earlier boundary reading claimed. Replacing it
with that fake leaf made the boot chain read the 17th byte of a config string
and report a bogus 0x40 gate.

This script changes nothing; it fails the relift if a known-good body regressed.

Usage:
    python tools/post_lift_fixes.py gt6/generated
"""
from __future__ import annotations

import sys
from pathlib import Path

FUNC = "func_00A13644"
REQUIRED = ("func_00A42DE8", "func_003C0E84", "func_00A42D3C",
            "vm_write64(ctx->gpr[1] + -0x90")
FORBIDDEN = ("vm_read8((uint32_t)ctx->gpr[3] + 0x10u)",)

# The ADCH value-reader state machine (guest 0x987884) dispatches a jump table
# at 0x1419550 with a bctr at 0x987910.  tools/apply_gt6_post_lift.py rewrites
# it as an explicit switch; if that hook is lost the parser aborts with
# `vector<T> too long`.  Fail the relift instead of silently regressing.
ADCH_FUNC = "func_00987884"
ADCH_REQUIRED = (
    "switch ((uint32_t)ctx->gpr[9])",
    "loc_00987914:",
    "loc_0098792C:",
    "loc_009878B8:",
)


def find_function(text: str, name: str) -> str | None:
    key = f"void {name}(ppu_context* ctx)"
    start = text.find(key)
    if start < 0:
        return None
    end = text.find("\nvoid func_", start + len(key))
    return text[start:end if end >= 0 else len(text)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root = Path(argv[1])

    found = 0
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        body = find_function(path.read_text(encoding="latin-1"), FUNC)
        if body is None:
            continue
        found += 1
        missing = [m for m in REQUIRED if m not in body]
        bad = [m for m in FORBIDDEN if m in body]
        if missing or bad:
            print(f"{path.name}: {FUNC} regressed; missing={missing} fake={bad}",
                  file=sys.stderr)
            return 1
        print(f"{path.name}: {FUNC} body OK")

    if found != 1:
        print(f"expected exactly one {FUNC}, found {found}", file=sys.stderr)
        return 1

    adch_found = 0
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        body = find_function(path.read_text(encoding="latin-1"), ADCH_FUNC)
        if body is None:
            continue
        adch_found += 1
        missing = [m for m in ADCH_REQUIRED if m not in body]
        if missing:
            print(f"{path.name}: {ADCH_FUNC} ADCH switch missing {missing}; "
                  "run tools/apply_gt6_post_lift.py", file=sys.stderr)
            return 1
        print(f"{path.name}: {ADCH_FUNC} ADCH switch OK")

    if adch_found != 1:
        print(f"expected exactly one {ADCH_FUNC}, found {adch_found}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
