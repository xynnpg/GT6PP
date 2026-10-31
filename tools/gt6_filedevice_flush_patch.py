#!/usr/bin/env python3
"""Fix the PDIPSX::FileDeviceHost stale read-stream pointer.

Measured blocker (docs/analysis/filedevice-null-vcall-fix.md):

  * ``func_00A08A00`` (FileDeviceHost init, guest 0x00A08A00) constructs a
    ``PDISTD::FileInternalStreamDefault`` in its **own stack frame** at
    ``r1+0x70`` and publishes the pointer at ``this+0x1C2C`` with
    ``stw r27,0x1c2c(r29)`` (guest 0x00A08A74).  It then destroys that local
    with ``func_009F42D8`` (guest 0x00A08AB4) and returns, leaving
    ``this+0x1C2C`` pointing at a dead stack slot.
  * The phys read pump ``func_00A08ADC`` reloads ``[this+0x1C2C]`` and calls
    ``func_009F44D8`` (PDISTD::FileStream::read).  That helper reads
    ``[stream+0x44]`` -> ``File``, ``[File+0x40]`` -> ``FileDevice`` and then
    dispatches ``FileDevice->vtable[+0x8C]``.  On a reused stack slot the
    "File" is garbage; the measured run had ``File+0x40 == 0x70`` and
    ``[0x70] == 0``, so the indirect call went to 0 (guest 0x009F4550).
  * ``func_00A08B8C`` (the Flush entry, vtable-independent callback) sets the
    "flush requested" byte ``+0x1C28`` and tail-calls the pump **without**
    checking the "read active" byte ``+0x1C29``.  ``0xA08ED0`` sets +0x1C29
    and installs a *live* caller-provided stream; ``0xA09130`` clears it on
    completion.  A flush with no read active has nothing to drain.

Two minimal, non-fabricating edits:

  1. ``func_00A08A00``: clear ``this+0x1C2C`` immediately after destroying the
     stack-local stream.  The object is gone; the field must not keep its
     address.
  2. ``func_00A08B8C``: return unless ``this+0x1C29`` says a read is active.
     This is the same condition ``0xA08ED0``/``0xA09130`` already maintain.

The patch is applied to the generated C after a relift.  It is idempotent and
does not change an active-read path: when +0x1C29 is 1 the behaviour is
byte-for-byte the original.

History: an earlier revision also rewrote ``func_009F4130`` to bind a host
FileObject to a PFS read state.  That was rejected as fabrication (it replaced
a FileDevice* with a read-state pointer).  The W2 path is fixed at the data
layer by seeding the bare PDIPFS cache file; see
docs/analysis/pfs-mount-device-fix.md.  If a generated tree still contains
the old size-only block or the rejected bind, patch_text() removes it and
does not add a replacement.

Usage:
    python tools/gt6_filedevice_flush_patch.py --check gt6/generated
    python tools/gt6_filedevice_flush_patch.py gt6/generated

The second form rewrites generated ``ppu_recomp_*.cpp`` files in place; the
normal entry point is tools/apply_gt6_post_lift.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FLUSH_FUNC = "func_00A08B8C"
INIT_FUNC = "func_00A08A00"
OPEN_FUNC = "func_009F4130"

FLUSH_GUARD = (
    "        /* no read in progress: nothing to flush; +0x1C2C may be stale */\n"
    "        if (vm_read8(ctx->gpr[3] + 0x1C29) == 0) return;\n"
)

INIT_ANCHOR = (
    "        ctx->lr = 0x00A08ABC; func_009F42D8(ctx); DRAIN_TRAMPOLINE(ctx);\n"
)
INIT_CLEAR = (
    "        vm_write32(ctx->gpr[29] + 0x1C2C, 0); "
    "/* local FileInternalStreamDefault is destroyed */\n"
)

# Rejected 0x9F4130 rewrites are removed, not replaced.  The first was a
# size-only block with a bogus FileObject+0x4C write; the second replaced the
# FileDevice* at FileObject+0x40 with a PFS read-state pointer.  Both are
# unsafe and neither fixes the W2 mount choice.  Keep the markers only so an
# already-patched tree can be cleaned.
OLD_OPEN_MARKER = (
    "        /* PFS open left FileObject+0xC0 at zero: use the cache stored_size. */\n"
)
OLD_BIND_MARKER = (
    "        /* Cache-backed host FileObject: bind to the PFS read state. */\n"
)
OLD_OPEN_END = "          } }\n"

FUNC_RE = re.compile(r"^void (func_[0-9A-F]{8})\(ppu_context\* ctx\) \{", re.M)


def _body(text: str, name: str) -> tuple[int, int] | None:
    key = f"void {name}(ppu_context* ctx) {{"
    start = text.find(key)
    if start < 0:
        return None
    end = text.find("\nvoid ", start + len(key))
    return start, (end if end >= 0 else len(text))


def _strip_old_open(body: str) -> str:
    """Remove the rejected size-only or bind block, if a tree still has one."""
    for marker in (OLD_OPEN_MARKER, OLD_BIND_MARKER):
        while True:
            i = body.find(marker)
            if i < 0:
                break
            j = body.find(OLD_OPEN_END, i)
            if j < 0:
                break
            body = body[:i] + body[j + len(OLD_OPEN_END):]
    return body


def patch_text(text: str) -> tuple[str, int]:
    """Return (patched_text, change_count).  Idempotent."""
    changes = 0

    span = _body(text, FLUSH_FUNC)
    if span is not None:
        start, end = span
        body = text[start:end]
        if FLUSH_GUARD.strip() not in body:
            key = f"void {FLUSH_FUNC}(ppu_context* ctx) {{\n    PPU_MM_SNAP\n"
            if body.count(key) == 1:
                text = text[:start] + body.replace(key, key + FLUSH_GUARD, 1) + text[end:]
                changes += 1

    span = _body(text, INIT_FUNC)
    if span is not None:
        start, end = span
        body = text[start:end]
        if INIT_CLEAR.strip() not in body and body.count(INIT_ANCHOR) == 1:
            text = text[:start] + body.replace(
                INIT_ANCHOR, INIT_ANCHOR + INIT_CLEAR, 1) + text[end:]
            changes += 1

    span = _body(text, OPEN_FUNC)
    if span is not None:
        start, end = span
        body = text[start:end]
        new_body = _strip_old_open(body)
        if new_body != body:
            text = text[:start] + new_body + text[end:]
            changes += 1

    return text, changes


def verify_text(text: str) -> list[str]:
    errs: list[str] = []

    span = _body(text, FLUSH_FUNC)
    if span is not None and FLUSH_GUARD.strip() not in text[span[0]:span[1]]:
        errs.append(f"{FLUSH_FUNC} lacks the +0x1C29 active-read guard")

    span = _body(text, INIT_FUNC)
    if span is not None and INIT_CLEAR.strip() not in text[span[0]:span[1]]:
        errs.append(f"{INIT_FUNC} still leaves +0x1C2C pointing at the dead local")

    # 0x9F4130 is intentionally not rewritten.  A bare PDIPFS/K/<key> file is
    # the oracle-verified route (docs/analysis/pfs-mount-device-fix.md); no
    # FileObject size or device bind belongs here.

    return errs


def _targets(root: Path):
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        s = path.read_text(encoding="latin-1")
        if (f"void {FLUSH_FUNC}(" in s or f"void {INIT_FUNC}(" in s
                or f"void {OPEN_FUNC}(" in s):
            yield path, s


def main(argv: list[str]) -> int:
    check = False
    args = list(argv[1:])
    if args and args[0] == "--check":
        check = True
        args.pop(0)
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2

    root = Path(args[0])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    total = 0
    bad = 0
    found = 0
    seen_funcs: set[str] = set()
    for path, s in _targets(root):
        found += 1
        for fname in (FLUSH_FUNC, INIT_FUNC, OPEN_FUNC):
            if f"void {fname}(" in s:
                seen_funcs.add(fname)
        errs = verify_text(s)
        if check:
            if errs:
                bad += 1
                for e in errs:
                    print(f"{path.name}: {e}", file=sys.stderr)
            else:
                print(f"{path.name}: FileDeviceHost guard OK")
            continue
        patched, n = patch_text(s)
        if n:
            path.write_text(patched, encoding="latin-1")
            total += n
            print(f"{path.name}: {n} FileDeviceHost edit(s)")
        errs = verify_text(patched)
        if errs:
            bad += 1
            for e in errs:
                print(f"{path.name}: {e}", file=sys.stderr)

    missing_funcs = [f for f in (FLUSH_FUNC, INIT_FUNC, OPEN_FUNC)
                     if f not in seen_funcs]
    if found == 0 or missing_funcs:
        print(f"generated tree lacks {missing_funcs or 'all target functions'}",
              file=sys.stderr)
        return 2
    if check:
        return 1 if bad else 0
    if bad:
        return 1
    print(f"FileDeviceHost flush patch: {total} edit(s), {found} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
