#!/usr/bin/env python3
"""Temporary debug instrumentation for GT6's init chain (generated code)."""
import re
from pathlib import Path

p = Path("gt6/generated/ppu_recomp_000.cpp")
s = p.read_text(encoding="latin-1")
start = s.index("void func_00013BE8(")
end = s.index("void func_00013D24(", start)
body = s[start:end]
out = []
n = 0
for line in body.splitlines():
    out.append(line)
    m = re.search(r"func_([0-9A-F]+)\(ctx\)", line)
    if "DRAIN_TRAMPOLINE(ctx);" in line and m:
        n += 1
        out.append(
            '        fprintf(stderr, "[init] step%d %s r3=0x%%08X\\n", %d, "%s", (unsigned int)ctx->gpr[3]);'
            % (n, m.group(1), n, m.group(1))
        )
        if m.group(1) == "00A13644":
            out.append(
                '        fprintf(stderr, "[init] flag=0x%02X\\n", (unsigned int)(ctx->gpr[3] & 0xFF));'
            )
s = s[:start] + "\n".join(out) + s[end:]
p.write_text(s, encoding="latin-1")
print("instrumented", n, "calls in", p)
