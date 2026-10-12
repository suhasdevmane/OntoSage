#!/usr/bin/env python3
"""Make the generated occupancy streams agree with each other (BUG-1506).

Measured 2026-10-10: every room's people count was generated independently with a 0-30 band and
a midday peak near the top of it, so an academic office "held" 29 people and the deliberation lane
summed Floor 4 to 947 people, while the floor's own entry counter -- generated independently too
-- read about 23. "How many people are in the building" and "which floor is busiest" could not
agree because the data they read did not.

This shapes the DEVELOPMENT publisher's map, never a building fact in the TTL:
  * a people-count point with no capacity-based band gets a generation ceiling estimated from its
    space's kind (marked `hi_basis: generator ceiling ...`, so it is never read as a capacity);
  * each floor counter is derived as the SUM of the people counts of the spaces on that floor;
  * each presence flag is derived as "its own space's count >= 1".
Spaces and floors are read from the live graph, so nothing here names a building.

THE BOOT-TIME MAP REBUILD CALLS `apply_occupancy_model` TOO (BUG-1540). The orchestrator rebuilds
the publisher's map from the graph whenever a TTL is ingested (`services/publisher_map.py`), and a
rebuild that did not know this model silently threw it away: two TTL edits on 2026-10-10 reverted
the derived floor counters and the publisher went back to independent counts. One function, two
callers, so the model holds whichever of them wrote the map last.

    python scripts/derive_occupancy_model.py --dry-run
    python scripts/derive_occupancy_model.py            # writes the map (a .bak is kept)
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]

#: Generation ceiling (people) by space kind, matched as a lower-case substring of the space's
#: label or the point's label. First match wins, so specific kinds sit above general ones. These
#: shape GENERATED data only; capacity questions are answered from the graph's own records.
KIND_CEILING = (
    ("computer laboratory", 30),
    ("seminar", 30),
    ("conference", 30),
    ("lecture", 60),
    ("research laboratory", 10),
    ("laboratory", 10),
    ("academic office", 2),
    ("management office", 3),
    ("office", 3),
    ("reception", 6),
    ("kitchen", 8),
    ("common room", 15),
    ("restroom", 3),
    ("toilet", 3),
    ("telecom", 1),
    ("server", 1),
    ("mechanical", 1),
    ("plant", 1),
    ("service", 1),
    ("storage", 1),
    ("loading", 2),
)
DEFAULT_CEILING = 4
BASIS = "generator ceiling by space kind (development data shape only; not a capacity record)"

QUERY = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT DISTINCT ?uuid ?space ?slabel ?floor WHERE {
  ?p ?hx ?r . FILTER(STRENDS(STR(?hx), "hasExternalReference"))
  ?r ?hid ?uuid . FILTER(STRENDS(STR(?hid), "hasTimeseriesId"))
  { ?p brick:hasLocation ?space } UNION { ?p brick:isPointOf ?space } UNION { ?space brick:hasPoint ?p }
  UNION { ?p brick:isPartOf ?space }
  OPTIONAL { ?space rdfs:label ?slabel }
  OPTIONAL {
    { ?space a brick:Floor . BIND(?space AS ?floor) }
    UNION { ?space brick:isPartOf+ ?floor . ?floor a brick:Floor }
    UNION { ?floor brick:hasPart+ ?space . ?floor a brick:Floor }
  }
}"""


def ceiling_for(*labels: str) -> int:
    text = " ".join(x.lower() for x in labels if x)
    for key, cap in KIND_CEILING:
        if key in text:
            return cap
    return DEFAULT_CEILING


def fetch_place_rows(endpoint: str, timeout: int = 180) -> List[Dict[str, Any]]:
    """The uuid -> space -> floor bindings of the live graph (SPARQL-JSON bindings)."""
    req = urllib.request.Request(
        endpoint,
        data=QUERY.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as fh:  # nosec B310 - local graph store
        return json.load(fh)["results"]["bindings"]


def apply_occupancy_model(
    doc: Dict[str, Dict[str, Any]], rows: List[Dict[str, Any]], verbose: bool = False
) -> Dict[str, int]:
    """Shape the occupancy entries of a narrow publish map IN PLACE. Returns what it did."""
    occ = {u: e for u, e in doc.items() if e.get("table") == "occupancy_data"}
    place: Dict[str, Dict[str, str]] = {}
    for b in rows:
        u = b["uuid"]["value"]
        if u not in occ:
            continue
        rec = place.setdefault(u, {"space": b["space"]["value"], "slabel": "", "floor": ""})
        rec["slabel"] = rec["slabel"] or b.get("slabel", {}).get("value", "")
        rec["floor"] = rec["floor"] or b.get("floor", {}).get("value", "")

    def is_flag(e):  # a 0/1 point of any kind (presence, booking status, charger state ...)
        return float(e.get("hi", 0) or 0) <= 1.0 and int(e.get("dec", 0) or 0) == 0

    def is_presence(e):  # only an OCCUPANCY flag may be derived from a people count
        text = f"{e.get('label', '')} {e.get('sensor', '')}".lower()
        return is_flag(e) and (
            "occupancy_status" in text or "occupancy status" in text or "presence" in text
        )

    def on_a_floor(u):
        sp = place.get(u, {}).get("space", "")
        return bool(sp) and sp == place.get(u, {}).get("floor")

    def is_floor_counter(u, e):
        # A HEADCOUNT located on a floor -- "Occupancy Count Sensor - Floor 3" -- not a detector
        # on one, and not an ENTRY counter: entries are a flow (people coming in per interval),
        # and deriving them as the same sum would double any per-floor total that adds a
        # floor's counters together.
        text = f"{e.get('label', '')} {e.get('sensor', '')}".lower()
        return on_a_floor(u) and "occupancy count" in text

    counts_by_space = collections.defaultdict(list)
    counts_by_floor = collections.defaultdict(list)
    changed_bands = 0
    for u, e in occ.items():
        if is_flag(e) or on_a_floor(u):
            continue  # floor-level points are counters (derived below) or detectors (left alone)
        if re.search(r"/\s*day|per day|daily", f"{e.get('label', '')}".lower()):
            continue  # a cumulative daily total is not a headcount of a space
        p = place.get(u)
        if not p:
            continue
        counts_by_space[p["space"]].append(u)
        if p["floor"]:
            counts_by_floor[p["floor"]].append(u)
        if (not e.get("hi_basis") or e.get("hi_basis") == BASIS) and float(
            e.get("hi", 0) or 0
        ) >= 30.0:
            e["hi"] = float(ceiling_for(p["slabel"], e.get("label", "")))
            e["hi_basis"] = BASIS
            changed_bands += 1
        elif e.get("hi_basis") == BASIS:
            e["hi"] = float(ceiling_for(p["slabel"], e.get("label", "")))

    floors_derived, flags_derived = 0, 0
    for u, e in occ.items():
        p = place.get(u)
        if not p:
            continue
        if is_floor_counter(u, e) and counts_by_floor.get(p["floor"]):
            e["derive"] = {"op": "sum", "of": sorted(counts_by_floor[p["floor"]])}
            e["hi"] = float(sum(float(occ[m]["hi"]) for m in counts_by_floor[p["floor"]]))
            e["hi_basis"] = "sum of the floor's people counts (generator; BUG-1506)"
            floors_derived += 1
            if verbose:
                print(f"  floor counter: {e.get('label')} = sum of {len(e['derive']['of'])} counts")
        elif is_presence(e) and counts_by_space.get(p["space"]):
            e["derive"] = {"op": "present", "of": counts_by_space[p["space"]][:1]}
            flags_derived += 1
    return {
        "bands": changed_bands,
        "floors": floors_derived,
        "flags": flags_derived,
        "flags_total": sum(1 for e in occ.values() if is_flag(e)),
        "unplaced": sum(1 for u in occ if u not in place),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default=str(REPO / "input" / "bldg1_narrow_publish_map.json"))
    ap.add_argument("--repo", default="bldg")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.map)
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = fetch_place_rows(f"http://127.0.0.1:7200/repositories/{args.repo}")
    stats = apply_occupancy_model(doc, rows, verbose=True)
    print(f"people-count bands set from space kind: {stats['bands']}")
    print(f"floor counters derived as sums:         {stats['floors']}")
    print(f"presence flags derived from counts:     {stats['flags']} of {stats['flags_total']}")
    print(f"occupancy points with no space in the graph (left as they were): {stats['unplaced']}")
    if args.dry_run:
        return 0
    shutil.copyfile(path, path.with_suffix(".json.bak-occupancy"))
    # The map's own format (ASCII-escaped, no trailing newline), so the diff is the change only.
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"wrote {path} (backup {path.with_suffix('.json.bak-occupancy').name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
