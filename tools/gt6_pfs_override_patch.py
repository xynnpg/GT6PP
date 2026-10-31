# Build patches/gt6-pfs-boot-override-hardening.patch as a proposal.
# Does not modify gt6/src/stubs.cpp; diffs a temporary copy.
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "gt6" / "src" / "stubs.cpp"
orig = src.read_text(encoding="utf-8", errors="surrogateescape")
mod = orig

old_match = '    path[sizeof path - 1] = 0;\n    if (!strstr(path, "scripts/gt6/main")) return;\n'
new_match = (
    '    path[sizeof path - 1] = 0;\n'
    '    /* Exact suffix: do not match main_menu.adc or a path that merely\n'
    '     * contains the boot-script prefix. */\n'
    '    {\n'
    '        static const char suffix[] = "scripts/gt6/main.adc";\n'
    '        size_t plen = strlen(path), slen = sizeof suffix - 1;\n'
    '        if (plen < slen || strcmp(path + plen - slen, suffix) != 0) return;\n'
    '    }\n'
)
if old_match not in mod:
    raise SystemExit("match anchor not found")
mod = mod.replace(old_match, new_match, 1)

old_read = (
    'extern "C" int gt6_script_read_override(ppu_context* ctx)\n'
    '{\n'
    '    if (!g_script_active) return 0;\n'
)
new_read = (
    'extern "C" int gt6_script_read_override(ppu_context* ctx)\n'
    '{\n'
    '    /* Only the HFileReader opened for the boot script may consume the\n'
    '     * override; a second reader must go through the guest path. */\n'
    '    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader) return 0;\n'
)
if old_read not in mod:
    raise SystemExit("read anchor not found")
mod = mod.replace(old_read, new_read, 1)

old_eof = (
    '    if (g_script_pos >= g_script_size) {\n'
    '        ctx->gpr[3] = 0;\n'
    '        return 1;\n'
    '    }\n'
)
new_eof = (
    '    if (g_script_pos >= g_script_size) {\n'
    '        /* EOF is final for this reader. Deactivate so later HFileReaders\n'
    '         * (asset loads) go back to the guest/PFS path. */\n'
    '        g_script_active = 0;\n'
    '        ctx->gpr[3] = 0;\n'
    '        return 1;\n'
    '    }\n'
)
if old_eof not in mod:
    raise SystemExit("eof anchor not found")
mod = mod.replace(old_eof, new_eof, 1)

old_pos = (
    '    g_script_pos += k;\n'
    '    ctx->gpr[3] = k;\n'
    '    return 1;\n'
)
new_pos = (
    '    g_script_pos += k;\n'
    '    /* Keep the guest-visible stream offset coherent if the parser asks. */\n'
    '    vm_write32(ctx->gpr[3] + 0x1B4, (uint32_t)g_script_pos);\n'
    '    ctx->gpr[3] = k;\n'
    '    return 1;\n'
)
if old_pos not in mod:
    raise SystemExit("pos anchor not found")
mod = mod.replace(old_pos, new_pos, 1)

diff = difflib.unified_diff(
    orig.splitlines(keepends=True),
    mod.splitlines(keepends=True),
    fromfile="a/gt6/src/stubs.cpp",
    tofile="b/gt6/src/stubs.cpp",
    n=4,
)
out = ROOT / "patches" / "gt6-pfs-boot-override-hardening.patch"
out.write_text("".join(diff), encoding="utf-8", errors="surrogateescape", newline="\n")
print(out, out.stat().st_size, "bytes")
