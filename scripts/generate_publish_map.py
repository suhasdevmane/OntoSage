#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive the synthetic publisher's per-sensor value ranges from the building's own graph.

WHY THIS EXISTS
---------------
`input/<building>_extended_narrow_uuids.json` tells the publisher what value range to
generate for each sensor. It had **no generator**. It was written once, by hand, against
whatever the graph held that day, and then the building changed around it.

Measured on the active building 2026-09-06:

    174 sensors typed `brick:CO2_Sensor` in the graph, named `CO2_Level_Sensor_N.NN`,
    appear in that map as `"class": "Air_Quality_Sensor", "lo": 0, "hi": 150`.

0-150 is an **air quality index** scale. So every floor 0-4 CO2 stream has been carrying
an index while the answer layer labelled it ppm, and the building answered:

    "Floor 1's average CO2 (157 ppm) is higher than Floor 3's (111 ppm) ... Actionable
     recommendation: install or verify adequate ventilation."

Outdoor air is about 420 ppm. Neither number is a low reading; neither is a reading.

TWO ROOT CAUSES, AND BOTH MATTER
--------------------------------
1. **The map typed sensors by a Brick SUPERCLASS.** `Air_Quality_Sensor` is Brick's
   supertype for CO2, TVOC and particulate sensors alike, so one band was applied to
   quantities that share no unit. `ontology/measurand_kinds.ttl` exists precisely because
   rolling up Brick's hierarchy loses the quantity; this cost values rather than counts.

2. **The ranges were a second hand-written table.** The publisher already had one
   (`_WIDE_RANGES`, keyed by name substring). Two tables, one of them with no owner,
   disagreeing about the same sensors, and nothing comparing them.

WHAT THIS DOES INSTEAD
----------------------
Reads the ACTIVE building's graph. For each sensor with a timeseries reference into a
narrow table, it takes the **most specific** Brick class that declares a measurand, and
reads that measurand's `ontosage:typicalMin/typicalMax/typicalDecimals` from the ontology.
No range, no class name and no building literal appears in this file.

A sensor whose class declares no measurand is **reported and skipped**, not given a
default. A default is how 174 CO2 sensors came to be generating an index.

    python scripts/generate_publish_map.py --dry-run
    python scripts/generate_publish_map.py --check     # exit 1 if the map is out of date
    python scripts/generate_publish_map.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

GRAPHDB = "http://localhost:7200/repositories/bldg"

#: Sensors are matched to a range through the ontology, in one query.
#:
#: `?cls` is every class the sensor has; the ontology only declares a measurand on the
#: classes where the quantity is unambiguous, so a sensor typed both `CO2_Sensor` and
#: `Air_Quality_Sensor` matches exactly one band -- the supertype deliberately declares
#: none. That is what makes "most specific" fall out of the data rather than out of a
#: hand-maintained precedence list here.
_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX o:     <http://ontosage.org/capabilities#>
SELECT ?sensor ?uuid ?store ?cls ?lo ?hi ?dec WHERE {
  ?sensor ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid ; ref:storedAt ?store .
  ?sensor a ?cls .
  ?cls o:measuresQuantityKind ?m .
  ?m o:typicalMin ?lo ; o:typicalMax ?hi .
  OPTIONAL { ?m o:typicalDecimals ?dec }
}
"""

#: Sensors that HAVE a timeseries reference but whose classes declare no measurand.
#: Reported so the gap is visible; never guessed at.
_UNMAPPED = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX o:     <http://ontosage.org/capabilities#>
SELECT ?uuid (SAMPLE(?store) AS ?store)
       (GROUP_CONCAT(DISTINCT ?cls; separator=" ") AS ?classes) WHERE {
  ?sensor ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid ; ref:storedAt ?store .
  ?sensor a ?cls .
  FILTER(STRSTARTS(STR(?cls), "https://brickschema.org/"))
  FILTER NOT EXISTS { ?sensor a ?any . ?any o:measuresQuantityKind ?m }
} GROUP BY ?uuid
"""


def _sparql(query: str, endpoint: str) -> List[Dict[str, Dict[str, str]]]:
    r = requests.post(
        endpoint,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _env(key: str, default: str = "") -> str:
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
                return s.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return default


def _narrow_tables(registry: Path) -> Dict[str, str]:
    """storedAt key -> table name, for the NARROW backends only.

    Read from the building's own datasource registry. Which backends are narrow is a
    deployment fact, not a property of the ontology, so it is not inferable from the graph.
    """
    import yaml

    if not registry.exists():
        return {}
    cfg = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    dbs = cfg.get("databases") or cfg
    out: Dict[str, str] = {}
    for key, spec in (dbs or {}).items():
        if isinstance(spec, dict) and str(spec.get("type", "")).endswith("narrow"):
            out[key] = str(spec.get("table") or key)
    return out


def _already_published(out_dir: Path) -> set:
    """UUIDs the publisher's OTHER map already writes.

    The two maps must be disjoint. A uuid written by both on the same tick doubles its
    apparent sampling rate, and every window a freshness check or a stuck-sensor detector
    reasons about is expressed in samples somewhere (CAVEAT-402). The publisher defends
    itself by dropping collisions, but relying on that means this file's contents are only
    correct because something downstream corrects them.
    """
    seen: set = set()
    for p in out_dir.glob("*_narrow_publish_map.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries = data.values() if isinstance(data, dict) else data
        for e in entries:
            if isinstance(e, dict) and e.get("uuid"):
                seen.add(str(e["uuid"]))
    return seen


def build(
    endpoint: str, registry: Path, out_dir: Path
) -> Tuple[Dict[str, dict], Counter, List[str], int]:
    """(map, per-class counts, uuids whose class declares no measurand, n excluded)."""
    narrow = _narrow_tables(registry)
    published_elsewhere = _already_published(out_dir)
    rows = _sparql(_QUERY, endpoint)

    out: Dict[str, dict] = {}
    classes: Counter = Counter()
    excluded: set = set()
    for b in rows:
        store_key = _local(b["store"]["value"])
        table = narrow.get(store_key)
        if table is None:
            continue  # a wide backend; the publisher writes those by column
        uuid = b["uuid"]["value"]
        if uuid in published_elsewhere:
            excluded.add(uuid)
            continue
        cls = _local(b["cls"]["value"])
        # A sensor can carry two mapped classes only if the ontology declares a measurand
        # on both -- which it does for equivalent names such as CO2_Sensor and
        # CO2_Level_Sensor. Same measurand, same band, so either is correct; take the
        # longer name so the record reads specifically.
        prev = out.get(uuid)
        if prev is not None and len(prev["class"]) >= len(cls):
            continue
        out[uuid] = {
            "uuid": uuid,
            "table": table,
            "lo": float(b["lo"]["value"]),
            "hi": float(b["hi"]["value"]),
            "dec": int(float((b.get("dec") or {}).get("value", 2))),
            "class": cls,
        }

    # Counted from the FINAL map, not as rows arrive. A class can be seen and then lost
    # when a longer name for the same measurand replaces it, and the first version
    # counted the sighting -- so the summary named classes the map does not contain.
    classes = Counter(v["class"] for v in out.values())

    # Restricted to sensors that were CANDIDATES for this map. Unfiltered it counted every
    # sensor in the building with no declared measurand -- 308 of them, nearly all bound for
    # a wide table this map never covers -- and reported them as skipped. A gap report that
    # inflates the gap is one nobody acts on.
    narrow_stores = set(narrow)
    unmapped = [
        b["uuid"]["value"]
        for b in _sparql(_UNMAPPED, endpoint)
        if _local((b.get("store") or {}).get("value", "")) in narrow_stores
    ]
    unmapped = [u for u in unmapped if u not in out and u not in published_elsewhere]
    return out, classes, unmapped, len(excluded)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=GRAPHDB)
    ap.add_argument("--out", default="input")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the map on disk differs from what the graph implies",
    )
    args = ap.parse_args(argv)

    building_id = _env("BUILDING_ID", "")
    if not building_id:
        print("BUILDING_ID not resolvable from .env - is a building active?")
        return 1

    out_dir = REPO / args.out
    registry = out_dir / "database_registry.yaml"
    print(f"reading the ACTIVE building ({building_id}) and the measurand bands it declares...")
    try:
        mapping, classes, unmapped, excluded = build(args.endpoint, registry, out_dir)
    except Exception as exc:
        print(f"failed: {exc}")
        return 1

    if not mapping:
        print(
            "  no sensor resolves to a narrow table AND a declared measurand.\n"
            "  Either no narrow backend is registered, or ontology/measurand_kinds.ttl is "
            "not loaded."
        )
        return 1

    print(
        f"  {len(mapping)} sensor(s) mapped, by class "
        f"({excluded} excluded because the other publish map already writes them):"
    )
    for cls, n in classes.most_common():
        sample = next(v for v in mapping.values() if v["class"] == cls)
        print(f"    {n:>5}  {cls:<34} {sample['lo']:g} .. {sample['hi']:g}")
    if unmapped:
        # NOT given a default. A default range is exactly how 174 CO2 sensors came to be
        # generating an air-quality index.
        print(
            f"  {len(unmapped)} sensor(s) have a timeseries reference and no declared "
            f"measurand; they are SKIPPED, not guessed at. Declare their class in "
            f"ontology/measurand_kinds.ttl to include them."
        )

    path = out_dir / f"{building_id}_extended_narrow_uuids.json"
    fresh = json.dumps(mapping, indent=1, sort_keys=True)

    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            same = json.loads(current) == mapping
        except Exception:
            same = False
        if same:
            print("  map is up to date with the graph")
            return 0
        print(f"  STALE: {path.name} does not match what the graph declares")
        return 1

    if args.dry_run:
        print(f"  [dry-run] would write {path.name} ({len(mapping)} entries)")
        return 0

    path.write_text(fresh, encoding="utf-8")
    print(f"  wrote {path.name} ({len(mapping)} entries)")
    print("\nThe publisher reloads this on its next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
