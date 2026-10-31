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

try:
    import gt6_filedevice_flush_patch as filedev
except ImportError:  # pragma: no cover - script run outside tools/
    filedev = None  # type: ignore

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
        'extern "C" void gt6_pfs_host_open_prepare(uint32_t path_ea, uint32_t file_ea);\n'
        'extern "C" void gt6_pfs_host_open_commit(uint32_t file_ea, uint32_t ret_ea);\n'
        'extern "C" int gt6_pfs_stream_read_override(ppu_context* ctx);\n'
        'extern "C" int gt6_pfs_stream_seek_override(ppu_context* ctx);\n'
        'extern "C" int gt6_pfs_stream_tell_override(ppu_context* ctx);\n'
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
        # FileStream helpers used by the host-font loader and other
        # non-HFileReader readers (see docs/analysis/host-font-sync-fix.md).
        ("func_009F4AA0", "if (gt6_pfs_stream_read_override(ctx)) return;\n"),
        ("func_009F49D8", "if (gt6_pfs_stream_seek_override(ctx)) return;\n"),
        ("func_009F4930", "if (gt6_pfs_stream_tell_override(ctx)) return;\n"),
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


# Boot/presents probes.  The menu worker (0x6CD8F8 -> 0xA11F20 -> entry
# 0x14E0088 -> 0xA122D4) is alive for the whole measured run, so the missing
# event is the engine update that consumes the project request queued by
# MGOM.start("boot") at manager+0x48/+0x50.  These hooks are read-only trace
# points for that handoff; none writes guest state.
BOOT_PRESENTS_HOOKS = (
    ("ppu_recomp_015.cpp", "func_006C4EC0", "gt6_mgom_class_probe"),
    ("ppu_recomp_015.cpp", "func_006C5064", "gt6_mgom_class_probe"),
    ("ppu_recomp_015.cpp", "func_006C55DC", "gt6_mgom_factory_probe"),
    ("ppu_recomp_015.cpp", "func_006C4A5C", "gt6_mgom_ctor_probe"),
    ("ppu_recomp_022.cpp", "func_009E2914", "gt6_mgom_vector_clear_probe"),
    ("ppu_recomp_023.cpp", "func_00A11F20", "gt6_menu_worker_prepare"),
    ("ppu_recomp_023.cpp", "func_00A122D4", "gt6_menu_worker_entry"),
    ("ppu_recomp_015.cpp", "func_006C54DC", "gt6_mgom_start_probe"),
    ("ppu_recomp_015.cpp", "func_006C4DC0", "gt6_mgom_setroot_probe"),
    ("ppu_recomp_012.cpp", "func_00568C94", "gt6_menu_project_request"),
    ("ppu_recomp_013.cpp", "func_005FA338", "gt6_project_load_probe"),
)


def add_boot_presents_hooks(root: Path) -> int:
    by_file: dict[str, list[tuple[str, str]]] = {}
    for filename, func, hook in BOOT_PRESENTS_HOOKS:
        by_file.setdefault(filename, []).append((func, hook))

    changed = 0
    for filename, hooks in by_file.items():
        path = root / filename
        if not path.exists():
            print(f"warning: {filename} not found; boot/presents hooks skipped",
                  file=sys.stderr)
            continue
        s = path.read_text(encoding="latin-1")
        file_changed = False

        inc = '#include "ppu_recomp.h"\n'
        if inc in s:
            missing = "".join(
                f'extern "C" void {hook}(ppu_context* ctx);\n'
                for _, hook in hooks
                if f'extern "C" void {hook}(ppu_context* ctx);' not in s)
            if missing:
                s = s.replace(inc, inc + missing, 1)
                file_changed = True

        for func, hook in hooks:
            key = f"void {func}(ppu_context* ctx) {{\n    PPU_MM_SNAP\n"
            call = f"        {hook}(ctx);\n"
            if call in s:
                continue
            if s.count(key) != 1:
                print(f"warning: {func} not found exactly once in {filename}",
                      file=sys.stderr)
                continue
            s = s.replace(key, key + call, 1)
            file_changed = True

        if file_changed:
            path.write_text(s, encoding="latin-1")
            changed += 1
    return changed


def add_host_open_wrapper(root: Path) -> int:
    """Wrap 0x9F8E40 so the host open is keyed by its returned FileObject.

    See docs/analysis/host-font-sync-fix.md.  r3 is the guest path string and
    r4 is the FileObject (also the success return).  0x9F4AA0 reads through
    that FileObject, so a slot keyed by r4 is what the read override matches.
    """
    path = root / "ppu_recomp_022.cpp"
    if not path.exists():
        return 0
    s = path.read_text(encoding="latin-1")
    define = "void func_009F8E40(ppu_context* ctx) {"
    orig = "void gt6_orig_func_009F8E40(ppu_context* ctx) {"
    if orig in s:
        return 0
    if s.count(define) != 1:
        print("warning: func_009F8E40 not found exactly once", file=sys.stderr)
        return 0
    s = s.replace(define, orig, 1)
    s += (
        "\n/* Host-open wrapper (0x9F8E40), see docs/analysis/host-font-sync-fix.md.\n"
        " * r3 = guest path, r4 = FileObject (also the success return).  The\n"
        " * extracted-file slot is keyed by that FileObject and served by\n"
        " * gt6_pfs_stream_read_override() at 0x9F4AA0. */\n"
        "void func_009F8E40(ppu_context* ctx)\n"
        "{\n"
        "    const uint32_t _path = (uint32_t)ctx->gpr[3];\n"
        "    const uint32_t _file = (uint32_t)ctx->gpr[4];\n"
        "    gt6_pfs_host_open_prepare(_path, _file);\n"
        "    gt6_orig_func_009F8E40(ctx);\n"
        "    gt6_pfs_host_open_commit(_file, (uint32_t)ctx->gpr[3]);\n"
        "}\n"
    )
    path.write_text(s, encoding="latin-1")
    return 1


def patch_filedevice_flush(root: Path) -> int:
    """Stop PDIPSX::FileDeviceHost from publishing/dereferencing a dead stack
    FileInternalStreamDefault (guest 0x00A08A74 / 0x00A08B8C).

    See docs/analysis/filedevice-null-vcall-fix.md.  The edits are idempotent
    and leave an active-read path untouched.
    """
    if filedev is None:
        print("warning: gt6_filedevice_flush_patch.py not importable; "
              "FileDeviceHost stale-stream guard was not applied", file=sys.stderr)
        return 0
    total = 0
    for path in sorted(root.glob("ppu_recomp_*.cpp")):
        s = path.read_text(encoding="latin-1")
        if "func_00A08B8C" not in s and "func_00A08A00" not in s:
            continue
        patched, n = filedev.patch_text(s)
        errs = filedev.verify_text(patched)
        if errs:
            print(f"{path.name}: FileDeviceHost patch verification failed: {errs}",
                  file=sys.stderr)
            continue
        if n:
            path.write_text(patched, encoding="latin-1")
        total += n
    return total


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
    boot_hooks = add_boot_presents_hooks(root)
    host_open = add_host_open_wrapper(root)
    adch = patch_adch_switch(root)
    filedev_changes = patch_filedevice_flush(root)
    print(f"post-lift: setjmp guards added {guards}; script hooks changed {hooks}; "
          f"boot/presents hooks changed {boot_hooks}; "
          f"host-open wrappers {host_open}; "
          f"ADCH switch changes {adch}; FileDeviceHost changes {filedev_changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
