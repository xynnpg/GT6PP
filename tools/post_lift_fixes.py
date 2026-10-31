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

# PDIPSX::FileDeviceHost published a stack-local FileInternalStreamDefault at
# +0x1C2C and its Flush callback dereferenced it after the local died, which is
# the measured null vcall at 0x009F4550 (File+0x40 == 0x70, [0x70] == 0).
# tools/gt6_filedevice_flush_patch.py adds the two lifetime guards.  A relift
# without them reintroduces the null dispatch.
FILEDEV_FLUSH_FUNC = "func_00A08B8C"
FILEDEV_FLUSH_REQUIRED = (
    "if (vm_read8(ctx->gpr[3] + 0x1C29) == 0) return;",
)
FILEDEV_INIT_FUNC = "func_00A08A00"
FILEDEV_INIT_REQUIRED = (
    "vm_write32(ctx->gpr[29] + 0x1C2C, 0);",
)
# func_009F4130 is deliberately not rewritten.  W2 is fixed by seeding the
# bare PDIPFS/K/W2 cache file; see docs/analysis/pfs-mount-device-fix.md.

# Boot/presents probes (docs/analysis/boot-presents-fix.md): the project
# request queued by MGOM.start("boot") is not consumed before MainLoop.
# tools/apply_gt6_post_lift.py installs the read-only worker/project probes.
# Fail the relift if they are lost.
BOOT_WORKER_FUNC = "func_00A122D4"
BOOT_WORKER_REQUIRED = ("gt6_menu_worker_entry(ctx);",)
BOOT_PREPARE_FUNC = "func_00A11F20"
BOOT_PREPARE_REQUIRED = ("gt6_menu_worker_prepare(ctx);",)


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

    # FileDeviceHost stale read-stream guard (docs/analysis/filedevice-null-vcall-fix.md)
    for fname, required in ((FILEDEV_FLUSH_FUNC, FILEDEV_FLUSH_REQUIRED),
                            (FILEDEV_INIT_FUNC, FILEDEV_INIT_REQUIRED)):
        n = 0
        for path in sorted(root.glob("ppu_recomp_*.cpp")):
            body = find_function(path.read_text(encoding="latin-1"), fname)
            if body is None:
                continue
            n += 1
            missing = [m for m in required if m not in body]
            if missing:
                print(f"{path.name}: {fname} FileDeviceHost guard missing {missing}; "
                      "run tools/apply_gt6_post_lift.py", file=sys.stderr)
                return 1
            print(f"{path.name}: {fname} FileDeviceHost guard OK")
        if n != 1:
            print(f"expected exactly one {fname}, found {n}", file=sys.stderr)
            return 1

    # Boot/presents menu-worker hook (docs/analysis/boot-presents-fix.md).
    for fname, required in ((BOOT_WORKER_FUNC, BOOT_WORKER_REQUIRED),
                            (BOOT_PREPARE_FUNC, BOOT_PREPARE_REQUIRED)):
        n = 0
        for path in sorted(root.glob("ppu_recomp_*.cpp")):
            body = find_function(path.read_text(encoding="latin-1"), fname)
            if body is None:
                continue
            n += 1
            missing = [m for m in required if m not in body]
            if missing:
                print(f"{path.name}: {fname} boot/presents hook missing {missing}; "
                      "run tools/apply_gt6_post_lift.py", file=sys.stderr)
                return 1
            print(f"{path.name}: {fname} boot/presents hook OK")
        if n != 1:
            print(f"expected exactly one {fname}, found {n}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
