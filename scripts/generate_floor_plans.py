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

ROOM_W, ROOM_H, GAP = 5.0, 4.0, 0.3  # metres (0.3m gap < 0.6m adjacency threshold, no overlap)
# a few typed rooms per floor so the classifier has variety (keywords the PDF pipeline knows)
TYPED = ["Toilet", "Meeting Room", "Server Room", "Kitchen", "Store Room", "Office"]


def sparql(q):
    req = urllib.request.Request(
        GRAPHDB,
        data=q.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["results"]["bindings"]


def building_shape():
    """(floors, room_names_per_floor[[]]) from the active graph.

    Uses the graph's ACTUAL room local names as plan labels (subclass-closure so
    buildings that type rooms as Office/Laboratory still enumerate) — the labels
    are the join key the manifest linker matches back to ontology IRIs, so
    invented names would orphan every space (the V4-T13 lesson). Falls back to
    generated names only when the graph declares no rooms at all.
    """
    ns = os.environ.get("BUILDING_NAMESPACE", "")
    ns_filter = f'FILTER(STRSTARTS(STR(?r), "{ns}"))' if ns else ""
    rows = sparql(
        "PREFIX brick:<https://brickschema.org/schema/Brick#> "
        "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT DISTINCT ?r ?f WHERE { ?r a ?c . ?c rdfs:subClassOf* brick:Room . "
        "OPTIONAL { ?r brick:isPartOf ?f . ?f a brick:Floor } " + ns_filter + " }"
    )
    by_floor = {}
    for b in rows:
        room = b["r"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        floor = b.get("f", {}).get("value", "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        by_floor.setdefault(floor, []).append(room)
    if not by_floor:

        def count(cls):
            b = sparql(
                f"PREFIX brick:<https://brickschema.org/schema/Brick#> "
                f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s a brick:{cls} }}"
            )
            return int(b[0]["n"]["value"]) if b else 0

        floors = max(1, count("Floor") or count("Storey"))
        rooms = count("Space") or (floors * 12)
        base, extra = divmod(rooms, floors)
        return floors, [
            [f"R{f}{i:02d}" for i in range(1, base + (1 if f < extra else 0) + 1)]
            for f in range(floors)
        ]
    floors = sorted(by_floor)
    return len(floors), [sorted(by_floor[f]) for f in floors]


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


def label_for(names, floor, idx):
    """Real graph room name when available (exact label = the linker's join key)."""
    if idx <= len(names):
        return names[idx - 1]
    zid = f"R{floor}{idx:02d}"  # invented fallback
    if idx % 3 == 0:
        return f"{zid} {TYPED[(floor + idx) % len(TYPED)]}"
    return zid


def make_dxf(rects, names, floor, path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres → scale_to_m = 1.0
    doc.layers.add("A-AREA-ROOM")
    doc.layers.add("A-AREA-IDEN")
    msp = doc.modelspace()
    for i, (x0, y0, x1, y1) in enumerate(rects, 1):
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            close=True,
            dxfattribs={"layer": "A-AREA-ROOM"},
        )
        t = msp.add_text(
            label_for(names, floor, i), dxfattribs={"layer": "A-AREA-IDEN", "height": 0.6}
        )
        t.set_placement(((x0 + x1) / 2, (y0 + y1) / 2))
    doc.saveas(str(path))


def dxf_to_dwg(dxf_path, dwg_path):
    for args in (
        [("dxf2dwg", "-o", str(dwg_path), str(dxf_path))],
        [("dxf2dwg", str(dxf_path))],
    ):  # fallback: writes alongside input
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


def make_pdf(rects, names, floor, path):
    max_x = max(r[2] for r in rects) + 2
    max_y = max(r[3] for r in rects) + 2
    s = 18.0  # metres → points
    pg_w, pg_h = max_x * s, max_y * s
    doc = fitz.open()
    page = doc.new_page(width=pg_w, height=pg_h)
    page.insert_text((10, 16), f"{BUILDING} — Floor {floor}", fontsize=11)
    for i, (x0, y0, x1, y1) in enumerate(rects, 1):
        rect = fitz.Rect(x0 * s, pg_h - y1 * s, x1 * s, pg_h - y0 * s)  # flip Y
        page.draw_rect(rect, color=(0.2, 0.3, 0.5), width=1)
        page.insert_text((rect.x0 + 4, rect.y0 + 14), label_for(names, floor, i), fontsize=8)
    doc.save(str(path))
    doc.close()


def main():
    floors, per_floor = building_shape()
    print(
        f"[fp] {BUILDING}: {floors} floors, rooms/floor={[len(n) for n in per_floor]} → {OUT_DIR}"
    )
    for f in range(floors):
        names = per_floor[f]
        rects = room_grid(len(names))
        dxf = OUT_DIR / f"{BUILDING} floor {f}.dxf"
        pdf = OUT_DIR / f"{BUILDING} floor {f}.pdf"
        # Emit a VALID .dxf directly (the pipeline reads .dxf natively). We avoid the
        # libredwg dxf2dwg→dwg2dxf round-trip, which corrupts handles so ezdxf can't
        # re-read it. Real AutoCAD .dwg files still work via the pipeline's dwg2dxf path.
        make_dxf(rects, names, f, dxf)
        make_pdf(rects, names, f, pdf)
        print(f"  floor {f}: {len(rects)} rooms  →  {dxf.name} + {pdf.name}")
    print("[fp] done")


if __name__ == "__main__":
    main()
