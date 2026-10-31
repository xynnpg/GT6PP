#!/usr/bin/env python3
"""Generate docs/progress.svg as a dense, plain bring-up grid.

Style: black background, tiny cells, bright green = working, dim green =
partial, dark = pending. Deliberately raw/utilitarian, no gradients, rounded
cards, glow, or marketing hero.

Run from the repo root:
    python tools/make_progress_svg.py
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

W, H = 1200, 440
BG = "#0a0a0a"
PANEL = "#0d0d0d"
GREEN = "#22c55e"
GREEN_DIM = "#14532d"
DARK = "#151515"
EDGE = "#2a2a2a"
WHITE = "#f3f4f6"
MUTED = "#8b8f93"

CELL = 9
GAP = 1
COLS = 40
ROWS = 28
PITCH = CELL + GAP


@dataclass
class Block:
    x: int
    y: int
    w: int
    h: int
    label: str
    done: int
    total: int
    partial: int = 0


LEFT = [
    Block(0, 0, 14, 10, "BOOT", 140, 140),
    Block(14, 0, 14, 10, "PPU LIFT", 140, 140),
    Block(28, 0, 12, 10, "HLE", 87, 120, 14),
    Block(0, 10, 14, 10, "PFS CACHE", 97, 140, 34),
    Block(14, 10, 14, 10, "SCRIPT VM", 73, 140, 38),
    Block(28, 10, 12, 10, "SPU / SPURS", 90, 120, 12),
    Block(0, 20, 20, 8, "THREADS / SYNC", 144, 160, 14),
    Block(20, 20, 20, 8, "AUDIO / INPUT", 40, 160, 10),
]
RIGHT = [
    Block(0, 0, 12, 10, "GCM INIT", 120, 120),
    Block(12, 0, 10, 10, "CLEARS", 100, 100),
    Block(22, 0, 10, 10, "D3D12", 94, 100, 6),
    Block(32, 0, 8, 10, "DRAW 1", 8, 80, 8),
    Block(0, 10, 14, 10, "DATA2F", 30, 140, 24),
    Block(14, 10, 14, 10, "TEXTURES", 10, 140, 17),
    Block(28, 10, 12, 10, "AUDIO OUT", 0, 120),
    Block(0, 20, 14, 8, "INPUT", 0, 112),
    Block(14, 20, 14, 8, "PHYSICS", 0, 112),
    Block(28, 20, 12, 8, "MOTION", 0, 96),
]


def frac_done(blocks: list[Block]) -> tuple[int, int]:
    return sum(b.done for b in blocks), sum(b.total for b in blocks)


def cell_fill(block: Block, index: int, cx: int, cy: int) -> tuple[str, str]:
    if index < block.done:
        return GREEN, "#0b3b1e"
    if index < block.done + block.partial:
        return GREEN_DIM, "#0b2b16"
    return DARK, EDGE


def draw_panel(blocks: list[Block], ox: int, oy: int, title: str, side: str) -> list[str]:
    done, total = frac_done(blocks)
    pct = 100.0 * done / total if total else 0.0
    out = []
    out.append(f'<rect x="{ox-18}" y="{oy-40}" width="{18*2 + COLS*PITCH + 18}" height="{ROWS*PITCH + 58}" fill="{PANEL}" stroke="{EDGE}"/>')
    pct_text = f": {pct:.1f}%"
    count_text = f"({done}/{total})"
    out.append(f'<text x="{ox-6}" y="{oy-17}" class="head">{title}</text>')
    out.append(f'<text x="{ox-6}" y="{oy-17}" class="head" dx="{len(title)*8.6 + 8:.1f}" fill="{GREEN}">{pct_text}</text>')
    out.append(f'<text x="{ox-6}" y="{oy-17}" class="head" dx="{len(title)*8.6 + 8 + len(pct_text)*8.6 + 8:.1f}" fill="{MUTED}">{count_text}</text>')
    out.append(f'<text x="{ox-6}" y="{oy-5}" class="kicker">{side}</text>')

    for bi, b in enumerate(blocks):
        bx = ox + b.x * PITCH
        by = oy + b.y * PITCH
        out.append(f'<rect x="{bx-2}" y="{by-2}" width="{b.w*PITCH+3}" height="{b.h*PITCH+3}" fill="none" stroke="#000" stroke-width="2"/>')
        idx = 0
        for yy in range(b.h):
            for xx in range(b.w):
                fill, stroke = cell_fill(b, idx, xx, yy)
                x = bx + xx * PITCH
                y = by + yy * PITCH
                out.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{fill}" stroke="{stroke}" stroke-width="0.4"/>')
                idx += 1
        # label with a black outline so it reads over both green and dark cells
        out.append(f'<text x="{bx+3}" y="{by+10}" class="blk" stroke="#000" stroke-width="2.2" paint-order="stroke">{b.label}</text>')
        out.append(f'<text x="{bx+3}" y="{by+10}" class="blk">{b.label}</text>')
    return out


def main() -> None:
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    p.append("<defs><style>"
             "text{font-family:Consolas,'Courier New',monospace;}"
             f".head{{fill:{WHITE};font-size:14px;font-weight:700;letter-spacing:0.2px}}"
             f".kicker{{fill:{MUTED};font-size:8px;letter-spacing:1px}}"
             f".blk{{fill:{WHITE};font-size:9px;font-weight:700;letter-spacing:0.3px}}"
             f".foot{{fill:{MUTED};font-size:8px}}"
             "</style></defs>")
    p.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')

    # panel origins: grid starts at x=36/636; headers above
    left_ox, right_ox = 36, 636
    top_oy = 84
    p.extend(draw_panel(LEFT, left_ox, top_oy, "PPU / system bring-up", "GUEST SYSTEM · MEASURED 2026-10-31 LATE"))
    p.extend(draw_panel(RIGHT, right_ox, top_oy, "RSX / draw path", "RENDER · MEASURED 2026-10-31 LATE"))

    # vertical separator
    p.append(f'<line x1="{W//2}" y1="10" x2="{W//2}" y2="{H-30}" stroke="{EDGE}" stroke-width="1"/>')

    # footer legend and legal line
    ly = H - 20
    p.append(f'<rect x="36" y="{ly-7}" width="8" height="8" fill="{GREEN}" stroke="#0b3b1e" stroke-width="0.5"/>')
    p.append(f'<text x="50" y="{ly}" class="foot">working</text>')
    p.append(f'<rect x="110" y="{ly-7}" width="8" height="8" fill="{GREEN_DIM}" stroke="#0b2b16" stroke-width="0.5"/>')
    p.append(f'<text x="124" y="{ly}" class="foot">partial / active</text>')
    p.append(f'<rect x="230" y="{ly-7}" width="8" height="8" fill="{DARK}" stroke="{EDGE}" stroke-width="0.5"/>')
    p.append(f'<text x="244" y="{ly}" class="foot">not started</text>')
    p.append(f'<text x="{W-36}" y="{ly}" text-anchor="end" class="foot">GT6PP · checklist cells, not code coverage · diagnostic overlay only; real game draw still black</text>')
    p.append("</svg>")

    out = Path("docs/progress.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(p), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
