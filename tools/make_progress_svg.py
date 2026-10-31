#!/usr/bin/env python3
"""Generate docs/progress.svg - a milestone map for the GT6 native port.

This is a checklist map, not code coverage: each square is one bring-up step or
group of steps. Green = working, yellow = partial/active, dark = not started.

Run from the repo root:
    python tools/make_progress_svg.py
"""
from __future__ import annotations

import html
from pathlib import Path

# (label, total cells, green cells, yellow cells)
LEFT = [
    ("BOOT / VOLUME", 60, 60, 0),
    ("PPU LIFT", 200, 200, 0),
    ("HLE IMPORTS", 120, 86, 0),
    ("PFS / CACHE", 80, 40, 20),
    ("SCRIPT VM / UI", 140, 70, 30),
    ("SPU / SPURS", 104, 80, 12),
]
RIGHT = [
    ("GCM INIT / DISPLAY", 80, 80, 0),
    ("CLEARS / PRESENT", 80, 80, 0),
    ("DRAW SUBMISSION", 40, 0, 4),
    ("SHADERS / VP", 120, 0, 24),
    ("TEXTURES / FONTS", 120, 0, 12),
    ("AUDIO / INPUT / PHYSICS", 72, 0, 0),
]

COLS = 48
CELL = 8
GAP = 2
PITCH = CELL + GAP

GREEN = "#2ea043"
GREEN_HI = "#3fb950"
YELLOW = "#d29922"
DARK = "#21262d"
PANEL = "#0f1317"
BORDER = "#30363d"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
BG = "#0b0d10"


def pct(green: int, total: int) -> str:
    return f"{100.0 * green / total:.1f}%"


def grid_rows(cats):
    return sum((total + COLS - 1) // COLS for _, total, _, _ in cats)


def draw_panel(x, y, w, h, title, cats, readout):
    total = sum(c[1] for c in cats)
    green = sum(c[2] for c in cats)
    out = []
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>')
    out.append(f'<text x="{x+20}" y="{y+30}" class="h">{html.escape(title)}</text>')
    out.append(
        f'<text x="{x+w-20}" y="{y+30}" text-anchor="end" class="pct">'
        f'{pct(green,total)} <tspan class="muted">({green}/{total})</tspan></text>'
    )
    out.append(f'<text x="{x+20}" y="{y+48}" class="sub">milestone map · not code coverage</text>')

    gx = x + (w - (COLS * PITCH - GAP)) // 2
    gy = y + 68
    for label, n, g, yellow in cats:
        rows = (n + COLS - 1) // COLS
        out.append(
            f'<text x="{gx}" y="{gy+11}" class="cat">{html.escape(label)}'
            f'<tspan class="muted">  {g+yellow}/{n}</tspan></text>'
        )
        gy += 16
        for i in range(rows):
            for j in range(COLS):
                idx = i * COLS + j
                if idx >= n:
                    break
                fill = GREEN if idx < g else (YELLOW if idx < g + yellow else DARK)
                stroke = GREEN_HI if fill == GREEN else ("#e3b341" if fill == YELLOW else "#30363d")
                out.append(
                    f'<rect x="{gx+j*PITCH}" y="{gy+i*PITCH}" width="{CELL}" height="{CELL}" '
                    f'rx="1.5" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>'
                )
        gy += rows * PITCH + 15

    # readout lines under the grid
    ry = y + h - 62
    for i, line in enumerate(readout):
        out.append(f'<text x="{x+20}" y="{ry+i*14}" class="readout">{html.escape(line)}</text>')
    return "\n".join(out)


def main() -> None:
    width, height = 1280, 640
    left_h = 500
    right_h = 500
    top = 84
    left_w, right_w = 616, 596
    left_x, right_x = 24, 660

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<defs><style>"
        "text{font-family:Consolas,'Cascadia Mono','Courier New',monospace;}"
        f".title{{fill:#f0f6fc;font-size:20px;font-weight:700;letter-spacing:1px}}"
        f".subtitle{{fill:{MUTED};font-size:11px}}"
        f".h{{fill:#f0f6fc;font-size:14px;font-weight:700;letter-spacing:1px}}"
        f".sub{{fill:{MUTED};font-size:9px}}"
        f".cat{{fill:{TEXT};font-size:9px;font-weight:700;letter-spacing:0.5px}}"
        f".pct{{fill:{GREEN_HI};font-size:13px;font-weight:700}}"
        f".muted{{fill:{MUTED};font-weight:400}}"
        f".readout{{fill:{MUTED};font-size:9px}}"
        f".legend{{fill:{MUTED};font-size:9px}}"
        "</style></defs>",
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        '<text x="24" y="38" class="title">GT6 NATIVE PORT — BRING-UP PROGRESS</text>',
        '<text x="24" y="57" class="subtitle">Gran Turismo 6 · BCUS98296 v1.00 · statically recompiled for Windows · 2026-10-31</text>',
    ]

    parts.append(draw_panel(
        left_x, top, left_w, left_h, "GUEST SYSTEM / BOOT", LEFT,
        [
            "PPU lift: 75,652 functions · corrected list: 70,989",
            "HLE: 1,216 NID handlers · 533/747 imports named",
            "Boot script: 857,518 B parsed to EOF",
            "PFS: boot script + 4 UI assets served",
        ],
    ))
    parts.append(draw_panel(
        right_x, top, right_w, right_h, "RENDER PATH", RIGHT,
        [
            "Last run: 12 flips · 6 clears · 0 draws",
            "Display: 1280×720, four guest buffers, present works",
            "Next: Prototypes.adc → first DRAW_ARRAYS",
        ],
    ))

    # legend
    ly = 616
    lx = 24
    parts.append(f'<rect x="{lx}" y="{ly-9}" width="10" height="10" rx="1.5" fill="{GREEN}" stroke="{GREEN_HI}"/>')
    parts.append(f'<text x="{lx+16}" y="{ly}" class="legend">working</text>')
    parts.append(f'<rect x="{lx+78}" y="{ly-9}" width="10" height="10" rx="1.5" fill="{YELLOW}" stroke="#e3b341"/>')
    parts.append(f'<text x="{lx+94}" y="{ly}" class="legend">partial / active</text>')
    parts.append(f'<rect x="{lx+206}" y="{ly-9}" width="10" height="10" rx="1.5" fill="{DARK}" stroke="{BORDER}"/>')
    parts.append(f'<text x="{lx+222}" y="{ly}" class="legend">not started</text>')
    parts.append(f'<text x="{width-24}" y="{ly}" text-anchor="end" class="legend">No game data, keys, or recompiled code in this repo.</text>')
    parts.append("</svg>")

    out = Path("docs/progress.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
