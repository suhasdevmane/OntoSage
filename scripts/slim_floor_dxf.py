#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reduce a floor DXF to exactly what the floor-plan pipeline reads.

Why this exists. A CAD export of a real architectural floor carries the whole
drawing -- walls, furniture, dimensions, hatching -- and lands at 50-135 MB per
floor as DXF text. GitHub refuses files over 100 MB, so a building's room
boundaries could not be committed at all, and even the floors under the limit
would put half a gigabyte of linework into every clone forever. The pipeline
reads none of that: `dwg_pipeline` takes polyline VERTICES (x, y only -- bulges
are ignored by `get_points("xy")`) from room-boundary layers, and TEXT/MTEXT
insert points for room numbers and names. Keeping exactly that reproduces the
manifest bit-for-bit and fits in tens of kilobytes.

Equivalence is not assumed -- verify it: run the same validation on original and
slimmed output (boundary count, room coverage, per-room areas) before replacing
anything. The first slim of a 105 MB floor came out at 55 KB with identical
results: 57 boundaries, 47/47 rooms, same min/median/max areas.

What is deliberately NOT kept:
* other layers' polylines -- the pipeline only falls back to them when NO
  room-boundary layer matched, and a slimmed file always has one;
* INSERT blocks -- the pipeline can read MEP symbols from them, but these
  drawings carry none (every manifest says "0 blocks"); a drawing that does
  should be slimmed with --keep-inserts;
* everything else (hatches, dimensions, viewports): never read.

Usage:
    python scripts/slim_floor_dxf.py "input/Abacws floor 2.dxf" -o out.dxf
    python scripts/slim_floor_dxf.py input/*.dxf --in-place --originals-dir dxf_originals
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import List

#: Layers whose polylines are room boundaries — mirrors the layer-role patterns
#: in shared/floor_plan_config.py (r"(?i)A[_-]?AREA" → room_boundary).
_BOUNDARY_LAYER_RE = re.compile(r"(?i)A[_-]?AREA")


def slim(src: Path, dst: Path, keep_inserts: bool = False) -> dict:
    """Write a minimal DXF to dst; return counts of what was kept."""
    import ezdxf

    doc = ezdxf.readfile(str(src))
    msp = doc.modelspace()

    out = ezdxf.new(dxfversion=doc.dxfversion)
    # Units drive the mm->m scale factor in the pipeline; losing this header
    # would inflate every area by a factor of a million.
    out.header["$INSUNITS"] = doc.header.get("$INSUNITS", 4)
    omsp = out.modelspace()

    kept = {"boundaries": 0, "texts": 0, "inserts": 0}
    for e in msp:
        t = e.dxftype()
        layer = e.dxf.get("layer", "")
        if t in ("LWPOLYLINE", "POLYLINE") and _BOUNDARY_LAYER_RE.search(layer):
            if layer not in out.layers:
                out.layers.add(layer)
            if t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                closed = bool(e.closed)
            else:
                pts = [(v.dxf.location[0], v.dxf.location[1]) for v in e.vertices]
                closed = bool(e.is_closed)
            if len(pts) < 2:
                continue
            omsp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
            kept["boundaries"] += 1
        elif t in ("TEXT", "MTEXT"):
            if layer and layer not in out.layers:
                out.layers.add(layer)
            txt = e.dxf.text if t == "TEXT" else e.text
            h = float(
                e.dxf.get("height", 2.5) if t == "TEXT" else e.dxf.get("char_height", 2.5)
            )
            omsp.add_text(
                txt,
                dxfattribs={"layer": layer, "height": h, "insert": tuple(e.dxf.insert)[:3]},
            )
            kept["texts"] += 1
        elif keep_inserts and t == "INSERT":
            if layer and layer not in out.layers:
                out.layers.add(layer)
            omsp.add_blockref(
                e.dxf.name, tuple(e.dxf.insert)[:2], dxfattribs={"layer": layer}
            )
            kept["inserts"] += 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.saveas(str(dst))
    return kept


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", help="DXF file(s) to slim")
    ap.add_argument("-o", "--out", help="output path (single input only)")
    ap.add_argument(
        "--in-place",
        action="store_true",
        help="replace each input, moving the original to --originals-dir first",
    )
    ap.add_argument(
        "--originals-dir",
        default="dxf_originals",
        help="where --in-place stashes the untouched originals (default: dxf_originals/)",
    )
    ap.add_argument("--keep-inserts", action="store_true", help="also keep INSERT block refs")
    args = ap.parse_args(argv)

    if args.out and len(args.files) > 1:
        ap.error("-o only makes sense with a single input file")

    for f in args.files:
        src = Path(f)
        if not src.is_file():
            print(f"SKIP (not found): {src}")
            continue
        before = src.stat().st_size
        if args.in_place:
            stash = Path(args.originals_dir) / src.name
            stash.parent.mkdir(parents=True, exist_ok=True)
            tmp = src.with_suffix(".slim.tmp.dxf")
            kept = slim(src, tmp, keep_inserts=args.keep_inserts)
            shutil.move(str(src), str(stash))
            shutil.move(str(tmp), str(src))
            dst = src
        else:
            dst = Path(args.out) if args.out else src.with_name(src.stem + ".slim.dxf")
            kept = slim(src, dst, keep_inserts=args.keep_inserts)
        after = dst.stat().st_size
        print(
            f"{src.name}: {before/1048576:.0f} MB -> {after/1024:.0f} KB  "
            f"(boundaries={kept['boundaries']}, texts={kept['texts']}"
            + (f", inserts={kept['inserts']}" if args.keep_inserts else "")
            + ")"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
