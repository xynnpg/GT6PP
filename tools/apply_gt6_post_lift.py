#!/usr/bin/env python3
"""Post-lift fixes for GT6 that the lifter cannot express.

Run after tools/setjmp_patch_gt6.py:
  * guard every function that arms a setjmp buffer (the patch script's own
    owner scan is unreliable on these chunks);
  * hook the boot-script reader open/read/seek to gt6/src/stubs.cpp's decrypted
    main.adc override.

Idempotent. Usage:
  python tools/apply_gt6_post_lift.py gt6/generated
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from gt6_adch_switch_patch import PatchError, patch_text, verify_text
except ImportError:  # pragma: no cover - script run outside tools/
    PatchError = RuntimeError  # type: ignore
    patch_text = None         # type: ignore
    verify_text = None        # type: ignore

FUNC_RE = re.compile(r"^void (func_[0-9A-F]{8})\(ppu_context\* ctx\) \{", re.M)


def add_setjmp_guards(root: Path) -> int:
    total = 0
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        s = path.read_text(encoding="latin-1")
        owners: list[str] = []
        for m in FUNC_RE.finditer(s):
            end = s.find("\nvoid ", m.end())
            body = s[m.start():end if end > 0 else len(s)]
            name = m.group(1)
            if "gt6_jmp_push" in body and f"void gt6_orig_{name}" not in s:
                owners.append(name)
        for name in owners:
            define = f"void {name}(ppu_context* ctx) {{"
            if define not in s:
                continue
            s = s.replace(define, f"void gt6_orig_{name}(ppu_context* ctx) {{", 1)
            s += (
                f"\n/* setjmp guard {name} */\n"
                f"void {name}(ppu_context* ctx)\n{{\n"
                f"    int _d = gt6_jmp_depth();\n"
                f"    gt6_orig_{name}(ctx);\n"
                f"    gt6_jmp_unwind(_d);\n}}\n"
            )
            total += 1
        if owners:
            path.write_text(s, encoding="latin-1")
    return total


def add_script_hooks(root: Path) -> int:
    path = root / "ppu_recomp_022.cpp"
    if not path.exists():
        return 0
    s = path.read_text(encoding="latin-1")
    changed = 0

    inc = '#include "ppu_recomp.h"\n'
    decls = (
        'extern "C" void gt6_script_path_hint(uint32_t reader_ea, uint32_t str_ea);\n'
        'extern "C" int gt6_script_read_override(ppu_context* ctx);\n'
        'extern "C" int gt6_script_seek_override(ppu_context* ctx);\n'
        'extern "C" int gt6_script_override_active(void);\n'
    )
    if inc in s:
        missing = "".join(
            line for line in decls.splitlines(keepends=True)
            if line.strip() not in s)
        if missing:
            s = s.replace(inc, inc + missing, 1)
            changed += 1

    for name, hook in (
        ("func_009BB020", "if (gt6_script_read_override(ctx)) return;\n"),
        ("func_009BB11C", "gt6_script_path_hint((uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4]);\n"),
        ("func_009BAFE0", "if (gt6_script_seek_override(ctx)) return;\n"),
    ):
        key = f"void {name}(ppu_context* ctx) {{\n    PPU_MM_SNAP\n"
        if s.count(key) == 1 and hook not in s:
            s = s.replace(key, key + "        " + hook, 1)
            changed += 1
        elif s.count(key) == 1:
            pass
        else:
            print(f"warning: {name} not found exactly once", file=sys.stderr)

    if changed:
        path.write_text(s, encoding="latin-1")
    return changed


def patch_adch_switch(root: Path) -> int:
    """Apply tools/gt6_adch_switch_patch.py to the generated parser file.

    Guest 0x987884 dispatches a six-state jump table with a bctr at 0x987910;
    the lifter emits it as an unresolved indirect call.  The patch replaces it
    with an explicit switch over the local case blocks.  It also forces
    HFileReader::open success while the host boot-script override is active.
    """
    if patch_text is None or verify_text is None:
        print("warning: gt6_adch_switch_patch.py not importable; "
              "ADCH state-machine dispatch was not patched", file=sys.stderr)
        return 0
    total = 0
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        s = path.read_text(encoding="latin-1")
        if "void func_00987884(ppu_context* ctx) {" not in s:
            continue
        try:
            patched, changes = patch_text(s, force_open=True)
        except PatchError as exc:
            print(f"{path.name}: ADCH switch patch failed: {exc}", file=sys.stderr)
            continue
        errs = verify_text(patched)
        if errs:
            print(f"{path.name}: ADCH switch verification failed: {errs}",
                  file=sys.stderr)
            continue
        if changes:
            path.write_text(patched, encoding="latin-1")
        total += changes
    return total


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root = Path(argv[1])
    guards = add_setjmp_guards(root)
    hooks = add_script_hooks(root)
    adch = patch_adch_switch(root)
    print(f"post-lift: setjmp guards added {guards}; script hooks changed {hooks}; "
          f"ADCH switch changes {adch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
