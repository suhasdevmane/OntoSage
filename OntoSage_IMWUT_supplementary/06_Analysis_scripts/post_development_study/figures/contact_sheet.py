#!/usr/bin/env python3
"""Tile rendered figures into one review image, each with its file name (for checking layout at a glance).

    python figures/contact_sheet.py [glob ...]      default: every PNG in figures/out/

Writes figures/out/_contact_sheet.png (not a paper figure).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "out"


def main() -> int:
    pats = sys.argv[1:] or ["*.png"]
    files = sorted({p for pat in pats for p in OUT.glob(pat) if not p.name.startswith("_")})
    if not files:
        print("no figures")
        return 1
    W = 1100
    tiles = []
    for f in files:
        im = Image.open(f).convert("RGB")
        im.thumbnail((W, 900))
        canvas = Image.new("RGB", (W, im.height + 26), "white")
        canvas.paste(im, (0, 26))
        ImageDraw.Draw(canvas).text((4, 6), f.name, fill=(200, 0, 0))
        tiles.append(canvas)
    cols = 2
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    H = sum(max(t.height for t in r) for r in rows)
    sheet = Image.new("RGB", (W * cols, H), (235, 235, 235))
    y = 0
    for r in rows:
        for j, t in enumerate(r):
            sheet.paste(t, (j * W, y))
        y += max(t.height for t in r)
    sheet.save(OUT / "_contact_sheet.png")
    print(f"{len(files)} figures -> {OUT / '_contact_sheet.png'} ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
