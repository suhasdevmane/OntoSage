#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Give the dev data-publisher EVERY narrow point, not the 19 it was hand-listed (BUG-390).

THE PROBLEM
-----------
The publisher tops up only the sensors named in its uuid map, and that map was written by
hand with 19 entries. Measured per-sensor on bldg1:

    noise_data       236 uuids,   1 written in the last 24h
    light_data       242 uuids,   1
    occupancy_data   280 uuids,   6
    temperature_data  67 uuids,   0
    co2_data          66 uuids,   0

— exactly the 19 in the map. A narrow table's sensors are ROWS, so one live writer keeps the
table's ``MAX(datetime)`` at today while 99% of its points are a week dead. That is why
"which space on floor 2 is quietest right now" excludes all 47 floor-2 spaces: every one of
their noise points stopped writing on 2026-08-25.

WHAT THIS DOES
--------------
Reads the LIVE graph for every point whose ``ref:storedAt`` names a narrow table registered
in ``database_registry.yaml``, and writes the complete map. Nothing is invented: a point
appears only if the ontology already says it exists and says where its readings live.

DEV-MODE ONLY, AND LABELLED AS SUCH
-----------------------------------
These are generated readings for a development stack, so that questions about "right now"
are answerable while the real feed is absent. They are not a claim about the building. The
ontology already marks the synthetic points ``ontosage:isSimulated true`` and the evidence
record carries that through to the answer. Before production the publisher is switched off
and ``database_registry.yaml`` is repointed at the real store — the ontology does not change.

BUILDING-AGNOSTIC
-----------------
No building id, namespace, table list or sensor name appears here. Narrow tables come from
the active building's registry, points from its graph, and value ranges are chosen by the
MODALITY the table name declares, with a stated fallback.

    python scripts/generate_publisher_map.py --building-id bldg1
    python scripts/generate_publisher_map.py --building-id bldg1 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Dict, List

import yaml

REPO = Path(__file__).resolve().parent.parent

#: Table-name stem -> the publisher's value_col, which selects a plausible value range.
#:
#: Matched on the stem the registry already uses (``co2_data`` -> ``co2``), so a building
#: that registers a modality this list does not name still gets its points published — it
#: falls back to the generic range and says so, rather than being skipped.
_VALUE_COL_BY_MODALITY = {
    "energy": "kwh",
    "submeter": "kwh",
    "occupancy": "occupancy",
    "parking": "occupancy",
    "water": "flow_lpm",
    "waterflow": "flow_lpm",
    "noise": "noise_db",
    "pm25": "pm25",
    "iaq": "voc",
    "light": "lux",
    "equipment": "vib_mm_s",
    "plant": "runtime_h",
    "temperature": "temp_c",
    "humidity": "rh_pct",
    "co2": "co2_ppm",
    "contact": "contact",
}


def _sparql(endpoint: str, query: str) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        endpoint,
        data=query.encode("utf-8"),
        headers={"Content-Type": "application/sparql-query", "Accept": "text/csv"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:  # nosec B310 - fixed local endpoint
        return list(csv.DictReader(StringIO(resp.read().decode("utf-8"))))


def narrow_tables(registry_path: Path) -> Dict[str, str]:
    """{storage key: table} for every narrow store the active building registers."""
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    databases = raw.get("databases") or raw
    out: Dict[str, str] = {}
    for key, cfg in (databases or {}).items():
        if isinstance(cfg, dict) and str(cfg.get("type", "")).strip() == "mysql_narrow":
            table = str(cfg.get("table") or "").strip()
            if table:
                out[str(key)] = table
    return out


def _value_col(table: str) -> str:
    stem = re.sub(r"_data$", "", table).lower()
    return _VALUE_COL_BY_MODALITY.get(stem, "generic")


def build_map(endpoint: str, tables: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """{uuid: entry} for every point registered to one of these narrow tables."""
    rows = _sparql(
        endpoint,
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT ?sensor ?uuid ?stored ?label WHERE {\n"
        "  ?sensor ref:hasExternalReference ?r .\n"
        "  ?r ref:hasTimeseriesId ?uuid .\n"
        "  ?r ref:storedAt ?stored .\n"
        "  OPTIONAL { ?sensor rdfs:label ?label }\n"
        "}",
    )
    wanted = {t for t in tables.values()}
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        store = str(row.get("stored") or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        uuid = str(row.get("uuid") or "").strip()
        if store not in wanted or not uuid:
            continue
        # One entry per uuid. A point referenced twice in the graph must not be published
        # twice per tick, which would double its apparent sampling rate.
        out.setdefault(
            uuid,
            {
                "uuid": uuid,
                "table": store,
                "value_col": _value_col(store),
                "label": str(row.get("label") or "").strip(),
                "sensor": str(row.get("sensor") or "").rsplit("#", 1)[-1],
            },
        )
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--building-id", required=True)
    ap.add_argument("--endpoint", default="http://localhost:7200/repositories/bldg")
    ap.add_argument("--registry", default=str(REPO / "input" / "database_registry.yaml"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    tables = narrow_tables(Path(args.registry))
    if not tables:
        print("no mysql_narrow stores registered for this building; nothing to publish")
        return 0
    entries = build_map(args.endpoint, tables)
    if not entries:
        print("no points are registered to a narrow store; nothing to publish")
        return 0

    per_table = Counter(e["table"] for e in entries.values())
    print(f"narrow stores registered: {len(tables)}   points found: {len(entries)}")
    for table, count in sorted(per_table.items()):
        col = _value_col(table)
        flag = "" if col != "generic" else "   <-- no modality range; generic values"
        print(f"  {table:20} {count:>5}  value_col={col}{flag}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    out = REPO / "input" / f"{args.building_id}_narrow_publish_map.json"
    out.write_text(json.dumps(entries, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n[written] {out}  ({len(entries)} points)")
    print("Recreate the publisher so it reloads the map: docker compose up -d data-publisher")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
