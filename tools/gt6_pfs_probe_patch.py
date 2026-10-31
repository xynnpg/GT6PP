# Build patches/gt6-pfs-decrypt-probe.patch without touching the generated tree.
# Inserts read-only diagnostics at:
#   0x9BB11C HFileReader::open  -> path string
#   0x9F8E40 mount match        -> mounting device, key, +0x144/+0x148
#   0x9CD410 ADCH read          -> HFileReader pointer/vtable
#   0x9FF530 PFS cipher         -> device keyset, offset, length, first bytes
#   0x9FF280 PFS header cipher  -> device keyset and first bytes
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "gt6" / "generated"


def insert_after(text: str, anchor: str, addition: str) -> str:
    if anchor not in text:
        raise SystemExit(f"anchor not found:\n{anchor}")
    if addition.strip() in text:
        return text
    return text.replace(anchor, anchor + addition, 1)


def patch_pair(name: str) -> str:
    orig = (GEN / name).read_text(encoding="utf-8", errors="surrogateescape")
    mod = orig
    if name == "ppu_recomp_022.cpp":
        mod = insert_after(
            mod,
            "void func_009BB11C(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[pfsprobe] HFileReader::open this=0x%08X pathobj=0x%08X path=\'%s\'\\n",\n'
            '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],\n'
            '                (const char*)(vm_base + vm_read32(ctx->gpr[4])));\n',
        )
        mod = insert_after(
            mod,
            "        if (((ctx->cr >> 1) & 1)) goto loc_009F8F50;\n",
            '        fprintf(stderr, "[pfsprobe] mount factory=0x%08X vtable=0x%08X keyptr=0x%08X key=\'%s\' dev144=0x%08X dev148=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[31],\n'
            '                (unsigned)vm_read32(ctx->gpr[31]),\n'
            '                (unsigned)vm_read32(ctx->gpr[31] + 4),\n'
            '                (const char*)(vm_base + vm_read32(ctx->gpr[31] + 4)),\n'
            '                (unsigned)vm_read32(ctx->gpr[31] + 0x144),\n'
            '                (unsigned)vm_read32(ctx->gpr[31] + 0x148));\n',
        )
        mod = insert_after(
            mod,
            "        ctx->lr = 0x009CD468; func_009D8DB0(ctx); DRAIN_TRAMPOLINE(ctx);\n",
            '        { unsigned r = (unsigned)vm_read32(ctx->gpr[1] + 0x90);\n'
            '          fprintf(stderr, "[scriptload] reader=0x%08X vtable=0x%08X ret=%d\\n", r, r ? (unsigned)vm_read32(r) : 0u, (int)ctx->gpr[3]); }\n',
        )
    elif name == "ppu_recomp_023.cpp":
        mod = insert_after(
            mod,
            "void func_009FF530(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[pfsprobe] cipher this=0x%08X file=0x%08X off=0x%X len=0x%X buf=0x%08X dev144=0x%08X key148=0x%08X pre=%02X%02X%02X%02X%02X%02X%02X%02X\\n",\n'
            '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],\n'
            '                (unsigned)ctx->gpr[5], (unsigned)ctx->gpr[7],\n'
            '                (unsigned)ctx->gpr[6],\n'
            '                (unsigned)vm_read32(ctx->gpr[3] + 0x144),\n'
            '                (unsigned)vm_read32(ctx->gpr[3] + 0x148),\n'
            '                vm_read8(ctx->gpr[6]), vm_read8(ctx->gpr[6]+1), vm_read8(ctx->gpr[6]+2), vm_read8(ctx->gpr[6]+3),\n'
            '                vm_read8(ctx->gpr[6]+4), vm_read8(ctx->gpr[6]+5), vm_read8(ctx->gpr[6]+6), vm_read8(ctx->gpr[6]+7));\n',
        )
        mod = insert_after(
            mod,
            "void func_009FF280(ppu_context* ctx) {\n    PPU_MM_SNAP\n",
            '        fprintf(stderr, "[pfsprobe] pfs-header this=0x%08X arg4=0x%08X dev144=0x%08X key148=0x%08X\\n",\n'
            '                (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],\n'
            '                (unsigned)vm_read32(ctx->gpr[3] + 0x144),\n'
            '                (unsigned)vm_read32(ctx->gpr[3] + 0x148));\n',
        )
    else:
        raise SystemExit(name)
    diff = difflib.unified_diff(
        orig.splitlines(keepends=True),
        mod.splitlines(keepends=True),
        fromfile=f"a/gt6/generated/{name}",
        tofile=f"b/gt6/generated/{name}",
        n=4,
    )
    return "".join(diff)


out = []
out.append(patch_pair("ppu_recomp_022.cpp"))
out.append(patch_pair("ppu_recomp_023.cpp"))
path = ROOT / "patches" / "gt6-pfs-decrypt-probe.patch"
path.write_text("".join(out), encoding="utf-8", errors="surrogateescape", newline="\n")
print(path, path.stat().st_size, "bytes")
