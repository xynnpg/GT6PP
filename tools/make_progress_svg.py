#!/usr/bin/env python3
"""Generate docs/progress.svg as a plain engineering status sheet.

Deliberately utilitarian: paper, ruled lines, monospace type, hand-marked
blockers. No gradients, rounded cards, glow, or marketing hero. Each square is
a checklist step, not code coverage.

Run from the repo root:
    python tools/make_progress_svg.py
"""
from __future__ import annotations

import html
from pathlib import Path

W, H = 1240, 780
PAPER = "#f3efe5"
INK = "#1b1b1a"
MUTED = "#706a5e"
FAINT = "#e5ddcd"
RULE = "#cfc4ae"
GREEN = "#2f6b3f"
GREEN_L = "#dbe7d8"
AMBER = "#a8761f"
AMBER_L = "#f0e2c6"
RED = "#9e3b2f"
RED_L = "#efd9d3"
GRAY = "#c9c1b1"

# label, detail, done boxes, status, status colour
LEFT = [
    ("VOLUME / TOC", "4,207 entries · 32,591 files", 12, "done", GREEN),
    ("BOOT SCRIPT", "857,518 B · ADCH012 parsed to EOF", 12, "done", GREEN),
    ("PPU LIFT", "75,652 functions · 70,989 boundaries", 12, "done", GREEN),
    ("HLE IMPORTS", "1,216 handlers · 533/747 imports named", 10, "partial", AMBER),
    ("SPU / SPURS", "15 job images · dispatch rc=0", 11, "working", GREEN),
    ("PFS CACHE", "4 UI assets served · raw cache blocked", 6, "blocked", RED),
    ("SCRIPT VM / UI", "Prototypes.adc absent from v1.00 disc", 4, "blocked", RED),
]
RIGHT = [
    ("GCM INIT / BUFFERS", "4 × 1280×720 · pitch 6144", 12, "done", GREEN),
    ("CLEARS / PRESENT", "12 flips · 6 CLEARSURFACE", 12, "done", GREEN),
    ("D3D12 BACKEND", "selftest PASS · triangle readback", 11, "ready", GREEN),
    ("GUEST DRAW", "0 DRAW_ARRAYS · 0 draws", 0, "not yet", RED),
    ("DATA2F IMMEDIATE", "10-vertex strip · decoder in progress", 3, "active", AMBER),
    ("TEXTURES / FONTS", "not reached", 0, "pending", MUTED),
    ("AUDIO / INPUT / PHYSICS", "not reached", 0, "pending", MUTED),
]


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def row(x: int, y: int, width: int, label: str, detail: str, done: int,
        status: str, color: str, note: str = "") -> str:
    out = []
    out.append(f'<text x="{x}" y="{y}" class="label">{esc(label)}</text>')
    out.append(f'<text x="{x}" y="{y+15}" class="detail">{esc(detail)}</text>')
    bx = x + width - 158
    for i in range(12):
        fill = GREEN_L if i < done else "#fbf8f0"
        stroke = GREEN if i < done else GRAY
        out.append(f'<rect x="{bx+i*11}" y="{y-10}" width="9" height="9" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
        if i < done:
            out.append(f'<rect x="{bx+i*11+1.5}" y="{y-8.5}" width="6" height="6" fill="{color}"/>')
    out.append(f'<text x="{bx}" y="{y+16}" class="status" fill="{color}">{esc(status)}</text>')
    if note:
        out.append(f'<text x="{x}" y="{y+30}" class="note">{esc(note)}</text>')
    return "\n".join(out)


def main() -> None:
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    p.append("<defs><style>"
             "text{font-family:'Courier New',Consolas,monospace;}"
             f".kicker{{fill:{MUTED};font-size:9px;letter-spacing:2px}}"
             f".title{{fill:{INK};font-size:30px;font-weight:700;letter-spacing:1px}}"
             f".sub{{fill:{MUTED};font-size:10px}}"
             f".h{{fill:{INK};font-size:11px;font-weight:700;letter-spacing:1.5px}}"
             f".label{{fill:{INK};font-size:11px;font-weight:700;letter-spacing:0.5px}}"
             f".detail{{fill:{MUTED};font-size:9px}}"
             f".status{{font-size:9px;font-weight:700;letter-spacing:0.5px}}"
             f".note{{fill:{RED};font-size:9px;font-style:italic}}"
             f".small{{fill:{MUTED};font-size:9px}}"
             f".next{{fill:{INK};font-size:11px}}"
             f".nextn{{fill:{RED};font-size:10px;font-weight:700}}"
             "</style></defs>")
    p.append(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')
    # notebook ruling
    for y in range(24, H, 26):
        p.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{FAINT}" stroke-width="0.7"/>')
    p.append(f'<line x1="28" y1="0" x2="28" y2="{H}" stroke="#d9b9b2" stroke-width="1"/>')
    p.append(f'<line x1="32" y1="0" x2="32" y2="{H}" stroke="#e4cfc9" stroke-width="0.7"/>')

    # header
    p.append('<text x="48" y="52" class="kicker">NATIVE PORT / STATUS SHEET</text>')
    p.append('<text x="48" y="84" class="title">GT6PP</text>')
    p.append(f'<text x="48" y="102" class="sub">Gran Turismo 6 · BCUS98296 v1.00 · statically recompiled for Windows</text>')
    p.append(f'<text x="{W-48}" y="52" text-anchor="end" class="kicker">2026-10-31 / LOCAL BUILD</text>')
    p.append(f'<text x="{W-48}" y="70" text-anchor="end" class="small">measured, not aspirational</text>')
    # stamp
    p.append(f'<rect x="{W-236}" y="82" width="188" height="34" fill="none" stroke="{RED}" stroke-width="1.2"/>')
    p.append(f'<text x="{W-142}" y="104" text-anchor="middle" fill="{RED}" font-size="11" font-weight="700" letter-spacing="1">PRE-ALPHA · 0 DRAWS</text>')
    # double rule
    p.append(f'<line x1="48" y1="122" x2="{W-48}" y2="122" stroke="{INK}" stroke-width="1.2"/>')
    p.append(f'<line x1="48" y1="126" x2="{W-48}" y2="126" stroke="{RULE}" stroke-width="0.7"/>')

    # columns
    lx, rx = 48, 648
    colw = 540
    p.append(f'<text x="{lx}" y="150" class="h">SYSTEM / BOOT</text>')
    p.append(f'<text x="{rx}" y="150" class="h">RENDER / RSX</text>')
    y = 178
    for r in LEFT:
        p.append(row(lx, y, colw, *r))
        y += 52
    y = 178
    for r in RIGHT:
        p.append(row(rx, y, colw, *r))
        y += 52

    p.append(f'<text x="48" y="536" class="note">PFS read thread dies at 0x9F44D8 (null vcall) before cache_read</text>')

    # next box
    by = 556
    p.append(f'<rect x="48" y="{by}" width="{W-96}" height="128" fill="#fbf8ef" stroke="{INK}" stroke-width="1"/>')
    p.append(f'<text x="64" y="{by+22}" class="h">NEXT, IN ORDER</text>')
    p.append(f'<text x="64" y="{by+47}" class="next"><tspan class="nextn">1.</tspan> resolve 0x9F44D8 null vcall → K/W2 raw cache read (59,991 B)</text>')
    p.append(f'<text x="64" y="{by+68}" class="next"><tspan class="nextn">2.</tspan> first DATA2F immediate strip → D3D12 draw_arrays</text>')
    p.append(f'<text x="64" y="{by+89}" class="next"><tspan class="nextn">3.</tspan> textures + fonts → first loading image</text>')
    p.append(f'<text x="64" y="{by+112}" class="small">Missing Prototypes.adc is a v1.00 disc gap; the official update supplies it. No fabrication.</text>')

    # footer
    p.append(f'<line x1="48" y1="694" x2="{W-48}" y2="694" stroke="{RULE}" stroke-width="0.8"/>')
    p.append(f'<text x="48" y="714" class="small">Measured from work/fix_run.err, work/pfstrace.err, rsx-first-draw-check.md and d3d12-draw-readiness.md.</text>')
    p.append(f'<text x="48" y="730" class="small">No game data, decryption keys, decrypted executables, or generated recompiled code in this repository.</text>')
    p.append(f'<text x="{W-48}" y="730" text-anchor="end" class="small">checklist = milestone map · not code coverage</text>')
    p.append("</svg>")

    out = Path("docs/progress.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(p), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
