#!/usr/bin/env python3
"""Building-agnostic synthetic floor-plan generator (portability tooling).

Reads the ACTIVE building's floors + room count from GraphDB and emits, per floor,
a synthetic **PDF** (labelled rooms — text layer) and **DWG** (room polygons + areas +
adjacency) named ``<building> floor <N>.pdf`` / ``.dwg`` in ``input/`` — the names the
floor-plan pipeline expects. Zero building literals: the layout is derived from whatever
the active graph declares. Lets spatial queries (room count, area, adjacency, "show floor
N", room types) work without a real CAD file.

Run inside the orchestrator container (has ezdxf + fitz + dxf2dwg + graph access):
    docker cp scripts/generate_floor_plans.py ontosage-orchestrator:/tmp/fp.py
    docker compose exec -T orchestrator python /tmp/fp.py
"""
import json
import math
import os
import subprocess
import urllib.request
from pathlib import Path

import ezdxf
import fitz  # PyMuPDF

GRAPHDB = os.environ.get("GRAPHDB_QUERY_URL", "http://graphdb:7200/repositories/bldg")
BUILDING = os.environ.get("BUILDING_ID", "bldg2")
OUT_DIR = Path(os.environ.get("FP_OUT_DIR", "/app/input"))

ROOM_W, ROOM_H, GAP = 5.0, 4.0, 0.3   # metres (0.3m gap < 0.6m adjacency threshold, no overlap)
# a few typed rooms per floor so the classifier has variety (keywords the PDF pipeline knows)
TYPED = ["Toilet", "Meeting Room", "Server Room", "Kitchen", "Store Room", "Office"]


def sparql(q):
    req = urllib.request.Request(
        GRAPHDB, data=q.encode(),
        headers={"Content-Type": "application/sparql-query",
                 "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["results"]["bindings"]


def building_shape():
    """(floors, rooms_per_floor[]) from the active graph; even split if no floor links."""
    def count(cls):
        b = sparql(f'PREFIX brick:<https://brickschema.org/schema/Brick#> '
                   f'SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s a brick:{cls} }}')
        return int(b[0]["n"]["value"]) if b else 0
    floors = max(1, count("Floor") or count("Storey"))
    rooms = count("Room") or count("Space") or (floors * 12)
    base, extra = divmod(rooms, floors)
    return floors, [base + (1 if i < extra else 0) for i in range(floors)]


def room_grid(n):
    """Grid of (x0, y0, x1, y1) room rectangles (metres)."""
    cols = max(1, int(math.ceil(math.sqrt(n))))
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        x0 = c * (ROOM_W + GAP)
        y0 = r * (ROOM_H + GAP)
        out.append((x0, y0, x0 + ROOM_W, y0 + ROOM_H))
    return out


def label_for(floor, idx):
    zid = f"R{floor}{idx:02d}"                      # matches default zone_id_pattern R{floor}{nn}
    if idx % 3 == 0:                                # sprinkle typed rooms
        return f"{zid} {TYPED[(floor + idx) % len(TYPED)]}"
    return zid


def make_dxf(rects, floor, path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6                      # metres → scale_to_m = 1.0
    doc.layers.add("A-AREA-ROOM")
    doc.layers.add("A-AREA-IDEN")
    msp = doc.modelspace()
    for i, (x0, y0, x1, y1) in enumerate(rects, 1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                           close=True, dxfattribs={"layer": "A-AREA-ROOM"})
        t = msp.add_text(label_for(floor, i), dxfattribs={"layer": "A-AREA-IDEN", "height": 0.6})
        t.set_placement(((x0 + x1) / 2, (y0 + y1) / 2))
    doc.saveas(str(path))


def dxf_to_dwg(dxf_path, dwg_path):
    for args in ([("dxf2dwg", "-o", str(dwg_path), str(dxf_path))],
                 [("dxf2dwg", str(dxf_path))]):  # fallback: writes alongside input
        try:
            subprocess.run(args[0], check=True, capture_output=True, timeout=60)
            cand = dwg_path if dwg_path.exists() else dxf_path.with_suffix(".dwg")
            if cand.exists():
                if cand != dwg_path:
                    cand.replace(dwg_path)
                return True
        except Exception as e:
            last = e
    print(f"  dxf2dwg failed: {last}")
    return False


def make_pdf(rects, floor, path):
    max_x = max(r[2] for r in rects) + 2
    max_y = max(r[3] for r in rects) + 2
    s = 18.0                                          # metres → points
    pg_w, pg_h = max_x * s, max_y * s
    doc = fitz.open()
    page = doc.new_page(width=pg_w, height=pg_h)
    page.insert_text((10, 16), f"{BUILDING} — Floor {floor}", fontsize=11)
    for i, (x0, y0, x1, y1) in enumerate(rects, 1):
        rect = fitz.Rect(x0 * s, pg_h - y1 * s, x1 * s, pg_h - y0 * s)  # flip Y
        page.draw_rect(rect, color=(0.2, 0.3, 0.5), width=1)
        page.insert_text((rect.x0 + 4, rect.y0 + 14), label_for(floor, i), fontsize=8)
    doc.save(str(path))
    doc.close()


def main():
    floors, per_floor = building_shape()
    print(f"[fp] {BUILDING}: {floors} floors, rooms/floor={per_floor} → {OUT_DIR}")
    for f in range(floors):
        rects = room_grid(per_floor[f])
        dxf = OUT_DIR / f"{BUILDING} floor {f}.dxf"
        pdf = OUT_DIR / f"{BUILDING} floor {f}.pdf"
        # Emit a VALID .dxf directly (the pipeline reads .dxf natively). We avoid the
        # libredwg dxf2dwg→dwg2dxf round-trip, which corrupts handles so ezdxf can't
        # re-read it. Real AutoCAD .dwg files still work via the pipeline's dwg2dxf path.
        make_dxf(rects, f, dxf)
        make_pdf(rects, f, pdf)
        print(f"  floor {f}: {len(rects)} rooms  →  {dxf.name} + {pdf.name}")
    print("[fp] done")


if __name__ == "__main__":
    main()
