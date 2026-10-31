#!/usr/bin/env python3
"""Patch the lifted ADCH value-reader state machine (guest 0x987884).

Why
---
Guest function 0x987884 is a state machine that reads one ADCH value from the
script stream and pushes/pops it on the parser value stack.  The state is kept
at `this+0x24`; the dispatch is a jump table at guest 0x1419550:

    state 0 -> 0x987914   (pop one value)
    state 1 -> 0x98792C   (pop until the peeked value type is not 2)
    state 2 -> 0x987A08   (return state)
    state 3 -> 0x987A08
    state 4 -> 0x9878B8   (read the next value)
    state 5 -> 0x9878B8

The lifter emitted the `bctr` at 0x987910 as `ps3_indirect_call(ctx); return;`
because none of the targets are function entries.  The runtime therefore fails
to resolve them, returns immediately, and the state machine exits without
completing a value.  After a few such failures the parser consumes a stale
count and the guest libc++ throws `vector<T> too long`.

The fix is local: turn the indirect dispatch into an explicit switch over the
four local blocks, which are already present in the generated function as dead
code.  No game data, function boundary, or lift list changes.

Also optionally forces HFileReader::open to report success when the host
boot-script override is active (the override serves reads without a backing
PFS file object), so the override is independent of the empty .fdupi cache.

Usage
-----
    python tools/gt6_adch_switch_patch.py gt6/generated
    python tools/gt6_adch_switch_patch.py gt6/generated --check
    python tools/gt6_adch_switch_patch.py gt6/generated --diff
    python tools/gt6_adch_switch_patch.py gt6/generated/ppu_recomp_022.cpp

Idempotent: re-running after a successful patch reports "already patched".
Run it after tools/apply_gt6_post_lift.py (it is also called from there).
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

FUNC = "void func_00987884(ppu_context* ctx) {"


class PatchError(RuntimeError):
    pass


def _one(text: str, old: str, new: str, what: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{what}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_text(text: str, force_open: bool = True) -> tuple[str, int]:
    """Return (patched_text, number_of_changes). Raises PatchError on drift."""
    if FUNC not in text:
        raise PatchError(f"{FUNC} not found")

    nl = "\r\n" if "\r\n" in text else "\n"
    changes = 0

    # The force-open hook uses this predicate.  apply_gt6_post_lift.py also
    # declares it; add it here when this script is used standalone.
    if force_open:
        inc = '#include "ppu_recomp.h"' + nl
        decl = 'extern "C" int gt6_script_override_active(void);' + nl
        if decl.strip() not in text and inc in text:
            text = text.replace(inc, inc + decl, 1)
            changes += 1

    # Idempotence: both labels are introduced only by this patch.  Migrate an
    # early patch revision that forgot to restore `ctx->ctr` before the
    # fallback indirect call.
    if "loc_00987914:" in text and "loc_0098792C:" in text:
        early = (
            "        }" + nl +
            "        ps3_indirect_call(ctx); return;" + nl +
            "loc_00987914:"
        )
        fixed = (
            "        }" + nl +
            "        ctx->ctr = ctx->gpr[9];   /* unknown target: keep the old fallback */" + nl +
            "        ps3_indirect_call(ctx); return;" + nl +
            "loc_00987914:"
        )
        if early in text:
            text = text.replace(early, fixed, 1)
            changes += 1
        return text, changes

    # 1) Label the state 4/5 block (0x9878B8), the second half of 0x987878A4.
    old = (
        "        ctx->gpr[11] = vm_read32(ctx->gpr[30] + 0x68);" + nl +
        "        ctx->gpr[0] = (int64_t)(int32_t)(5);"
    )
    new = "loc_009878B8:" + nl + old
    text = _one(text, old, new, "state 5 block")
    changes += 1

    # 2) Replace the unresolved bctr dispatch with an explicit switch.  The
    #    case bodies already exist after the old `ps3_indirect_call; return;`
    #    as dead code; label the first one (0x987914) here.
    old = (
        "        ctx->ctr = ctx->gpr[9];" + nl +
        "        ps3_indirect_call(ctx); return;" + nl +
        "        ctx->gpr[3] = ppc_rldicl(ctx->gpr[28], 0, 32);"
    )
    new = (
        "        switch ((uint32_t)ctx->gpr[9]) {" + nl +
        "        case 0x00987914u: goto loc_00987914;" + nl +
        "        case 0x0098792Cu: goto loc_0098792C;" + nl +
        "        case 0x00987A08u: goto loc_00987A08;" + nl +
        "        case 0x009878B8u: goto loc_009878B8;" + nl +
        "        default: break;" + nl +
        "        }" + nl +
        "        ctx->ctr = ctx->gpr[9];   /* unknown target: keep the old fallback */" + nl +
        "        ps3_indirect_call(ctx); return;" + nl +
        "loc_00987914:" + nl +
        "        ctx->gpr[3] = ppc_rldicl(ctx->gpr[28], 0, 32);"
    )
    text = _one(text, old, new, "bctr dispatch at 0x987910")
    changes += 1

    # 3) Label the state 1 block (0x98792C).
    old = (
        "        goto loc_00987A08;" + nl +
        "        ctx->gpr[29] = ppc_rldicl(ctx->gpr[28], 0, 32);" + nl +
        "loc_00987930:"
    )
    new = (
        "        goto loc_00987A08;" + nl +
        "loc_0098792C:" + nl +
        "        ctx->gpr[29] = ppc_rldicl(ctx->gpr[28], 0, 32);" + nl +
        "loc_00987930:"
    )
    text = _one(text, old, new, "state 1 block")
    changes += 1

    # 4) Optional: force HFileReader::open success while the override serves
    #    the script.  The override answers HFileReader::read before the guest
    #    path touches the file object, so the empty PFS cache must not gate it.
    if force_open:
        old = (
            "        ctx->lr = 0x009CD710; func_009BB11C(ctx); DRAIN_TRAMPOLINE(ctx);" + nl +
            "        ctx->gpr[4] = ppc_rldicl(ctx->gpr[26], 0, 32);"
        )
        new = (
            old + nl +
            "        if ((uint32_t)ctx->gpr[3] == 0 && gt6_script_override_active())" + nl +
            "            ctx->gpr[3] = 1;   /* boot-script override needs no PFS file object */"
        )
        text = _one(text, old, new, "HFileReader::open success override")
        changes += 1

    return text, changes


def verify_text(text: str) -> list[str]:
    """Structural checks on the patched function (no compilation)."""
    errs: list[str] = []
    start = text.find(FUNC)
    if start < 0:
        return [f"{FUNC} not found"]
    end = text.find("\nvoid ", start + len(FUNC))
    body = text[start:end if end >= 0 else len(text)]

    for label in ("loc_009878B8:", "loc_00987914:", "loc_0098792C:",
                  "loc_00987A08:"):
        if label not in body:
            errs.append(f"missing {label}")
    for target in ("loc_009878B8", "loc_00987914", "loc_0098792C",
                   "loc_00987A08"):
        if body.count("goto " + target + ";") == 0:
            errs.append(f"no goto to {target}")
    # The explicit switch must precede the fallback indirect call.
    sw = body.find("switch ((uint32_t)ctx->gpr[9])")
    fb = body.find("ps3_indirect_call(ctx); return;")
    if sw < 0:
        errs.append("state-machine switch missing")
    elif fb >= 0 and fb < sw:
        errs.append("fallback indirect call precedes the switch")
    if ("gt6_script_override_active()" in text and
            'extern "C" int gt6_script_override_active(void);' not in text):
        errs.append("gt6_script_override_active declaration missing")
    return errs


def _iter_targets(path: Path):
    if path.is_dir():
        yield from sorted(path.glob("ppu_recomp_*.cpp"))
    else:
        yield path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="generated directory or ppu_recomp_*.cpp")
    ap.add_argument("--check", action="store_true",
                    help="report whether the patch applies; do not write")
    ap.add_argument("--diff", action="store_true",
                    help="print a unified diff instead of writing")
    ap.add_argument("--no-force-open", action="store_true",
                    help="only patch the 0x987884 switch")
    args = ap.parse_args(argv[1:])

    root = Path(args.path)
    hits = 0
    for path in _iter_targets(root):
        if not path.is_file():
            continue
        text = path.read_text(encoding="latin-1")
        if FUNC not in text:
            continue
        hits += 1
        try:
            patched, changes = patch_text(text, force_open=not args.no_force_open)
        except PatchError as exc:
            print(f"{path}: patch does not apply: {exc}", file=sys.stderr)
            return 1
        if changes == 0:
            print(f"{path}: already patched")
            errs = verify_text(text)
            if errs:
                for e in errs:
                    print(f"  verification: {e}", file=sys.stderr)
                return 1
            continue
        errs = verify_text(patched)
        if errs:
            for e in errs:
                print(f"{path}: verification after patch: {e}", file=sys.stderr)
            return 1
        if args.diff:
            diff = difflib.unified_diff(
                text.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=str(path), tofile=str(path) + " (patched)", n=3)
            sys.stdout.write("".join(diff))
        elif not args.check:
            path.write_text(patched, encoding="latin-1")
            print(f"{path}: patched ({changes} change(s))")
        else:
            print(f"{path}: patch applies ({changes} change(s))")

    if hits == 0:
        print(f"{root}: no {FUNC}", file=sys.stderr)
        return 1
    if hits > 1:
        print(f"{root}: {FUNC} found in {hits} files; expected one",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
