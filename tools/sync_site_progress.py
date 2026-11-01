#!/usr/bin/env python3
"""Sync the static fallback progress values in the website's index.html.

The website fetches ``progress.json`` live at runtime.  This script only
updates the numbers baked into the HTML so the page is still correct before
the fetch completes (or if it fails).

Usage:
    python tools/sync_site_progress.py path/to/GT6PP-SITE/index.html
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "progress.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/sync_site_progress.py <index.html>", file=sys.stderr)
        return 2

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"not found: {target}", file=sys.stderr)
        return 1

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    system = float(cfg["progress"]["system"])
    render = float(cfg["progress"]["render"])
    gate = str(cfg.get("current_gate", "")).strip()

    text = target.read_text(encoding="utf-8")
    original = text

    text = re.sub(
        r'(data-progress="system">)[\d.]+%',
        rf"\g<1>{system:.1f}%",
        text,
    )
    text = re.sub(
        r'(data-bar="system" style="width:)[\d.]+%',
        rf"\g<1>{system:.1f}%",
        text,
    )
    text = re.sub(
        r'(data-progress="render">)[\d.]+%',
        rf"\g<1>{render:.1f}%",
        text,
    )
    text = re.sub(
        r'(data-bar="render" style="width:)[\d.]+%',
        rf"\g<1>{render:.1f}%",
        text,
    )

    if gate:
        sentence = gate.rstrip()
        if sentence and sentence[-1] not in ".!?":
            sentence += "."
        text = re.sub(
            r'(<p\b[^>]*\bdata-gate\b[^>]*>).*?(</p>)',
            lambda m: f"{m.group(1)}Current gate: {html.escape(sentence, quote=False)}{m.group(2)}",
            text,
            flags=re.DOTALL,
        )

    if text == original:
        print(f"site already current: {target}")
        return 0

    target.write_text(text, encoding="utf-8", newline="")
    print(f"updated site: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
