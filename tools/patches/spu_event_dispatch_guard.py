#!/usr/bin/env python3
"""Guard GT6's 16-entry SPURS event dispatch table against out-of-range ids.

`func_00A569D0` (guest PPU 0x00A569D0) is the dispatcher used by the "Spu Event
Handler" thread (entry OPD 0x014E14C0 -> 0x00A56698 -> 0x00A564EC). It computes

    r28 = this + (id << 3)
    opd = *(u32 *)(r28 + 4)
    arg = *(u32 *)(r28 + 8)
    ctr = *(u32 *)opd ; r2 = *(u32 *)(opd + 4) ; bctrl

The object only owns 16 entries (constructor 0x00A567B8 zeroes 16 pairs at
+4/+8). Nothing in the lifted dispatcher checks `id`, so an id >= 16 reads
unrelated object fields as an OPD. GT6 hit id 52 (0x34): entry obj+0x1A4 held
0x0000FFFF, guest 0xFFFF held 0x007F454C/0x46020201, and bctrl went to
0x007F454C (8 bytes into func_007F4544, no OPD).

The HLE producer is fixed separately (cellSpurs.c wraps its completion index
by the chain's maxGrabbedJob and routes by owning instance). This guard is the
defence-in-depth half: even a future producer mistake cannot make the guest
index past its own table.

The generated file is overwritten by a relift, so run this (or add it to the
relift pipeline) after `scripts/relift-gt6.ps1`.

Usage:
    python tools/patches/spu_event_dispatch_guard.py --check
    python tools/patches/spu_event_dispatch_guard.py --apply
    python tools/patches/spu_event_dispatch_guard.py --file <ppu_recomp_XXX.cpp> --apply

Exit codes: 0 ok / already guarded, 1 not found or wrong shape.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_GLOB = "gt6/generated/ppu_recomp_*.cpp"
MARKER = "SPURS_DISPATCH_GUARD"

GUARD = """        /* SPURS_DISPATCH_GUARD: the object at `this` has exactly 16
         * {opd,arg} entries (0x00A567B8 zeroes 16 pairs at +4/+8). An id >= 16
         * reads unrelated fields as an OPD; GT6 id 52 produced OPD 0xFFFF and
         * bctrl 0x007F454C. Drop it before the table walk. This runs before
         * the frame is built or the object lwmutex is taken, so plain return
         * is safe. The producer fix is in cellSpurs.c. */
        if ((uint32_t)ctx->gpr[4] >= 16u) {
            static unsigned _spurs_guard_n = 0;
            if (_spurs_guard_n++ < 8)
                fprintf(stderr, "[ppu] SPURS dispatch id=%u >= 16 (table=16) "
                        "tid=%llu lr=0x%08X -- ignored\\n",
                        (uint32_t)ctx->gpr[4],
                        (unsigned long long)ctx->thread_id,
                        (uint32_t)ctx->lr);
            return;
        }
"""


def patch_text(text: str) -> tuple[str, str]:
    if MARKER in text:
        return text, "already"
    m = re.search(r"^void func_00A569D0\(ppu_context\* ctx\) \{\r?\n", text, re.M)
    if not m:
        raise SystemExit("func_00A569D0 not found (has the lift layout changed?)")
    start = m.end()
    # Insert after the PPU_MM_SNAP line and the four saved-register locals,
    # before the first guest store. Keeping it before vm_write64 means an
    # early return has not touched the guest stack.
    tail = text[start:]
    anchor = re.search(r"^        uint64_t _cs_31 = ctx->gpr\[31\];\r?\n", tail, re.M)
    if not anchor:
        raise SystemExit("expected _cs_31 prologue line not found")
    at = start + anchor.end()
    guard = GUARD.replace("\n", "\r\n") if "\r\n" in text else GUARD
    return text[:at] + guard + text[at:], "patched"


def find_target(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise SystemExit(f"missing: {explicit}")
        return explicit
    for p in sorted(Path(".").glob(DEFAULT_GLOB)):
        try:
            text = p.read_bytes().decode("utf-8", "surrogateescape")
        except OSError:
            continue
        if "void func_00A569D0(ppu_context* ctx)" in text:
            return p
    raise SystemExit(f"func_00A569D0 not found under {DEFAULT_GLOB}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=None,
                    help=f"explicit generated file (default: search {DEFAULT_GLOB})")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="report status only")
    g.add_argument("--apply", action="store_true", help="write the guard")
    args = ap.parse_args()

    p = find_target(args.file)
    # Generated trees contain a few non-UTF-8 comment bytes from the lifter;
    # surrogateescape round-trips them unchanged.
    raw = p.read_bytes()
    text = raw.decode("utf-8", "surrogateescape")
    new, status = patch_text(text)
    if args.check or not args.apply:
        print(f"{p}: {status}")
        return 0
    if status == "already":
        print(f"{p}: already guarded")
        return 0
    p.write_bytes(new.encode("utf-8", "surrogateescape"))
    print(f"{p}: patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
