#!/usr/bin/env python3
"""Which generated points follow the SUN rather than their table's day (BUG-1580).

The publish map takes each point's generation shape from its TABLE (`generate_publisher_map`), and
the PV arrays' power points are stored in the energy submeter table, so they were generated like
meters: never zero, 1.4 kW at 02:00. Which points are photovoltaic generation is the graph's own
statement (`ontosage:PV_Generation_Power_Sensor`), so it is read from there on every rebuild and
applied to the map here, beside the generator, the same way `derive_occupancy_model` applies the
occupancy rules. The publisher's `sensor_signal.solar_fraction` draws the shape.

    python scripts/derive_generation_shapes.py --map input/bldg1_narrow_publish_map.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

#: The publisher's shape key for photovoltaic generation.
PV_SHAPE = "pv_kw"

PV_POINTS_QUERY = """
PREFIX ontosage: <http://ontosage.org/capabilities#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?uuid WHERE {
  ?p a ontosage:PV_Generation_Power_Sensor ;
     ref:hasExternalReference/ref:hasTimeseriesId ?uuid .
}
"""


def pv_uuids_from(bindings: List[Dict[str, Any]]) -> List[str]:
    """The timeseries ids in a SPARQL result's bindings."""
    return [str((b.get("uuid") or {}).get("value") or "") for b in bindings if b.get("uuid")]


def mark_generation_shapes(points: Dict[str, Any], pv_uuids: List[str]) -> int:
    """Give each PV generation point the solar shape; returns how many were marked."""
    n = 0
    for u in pv_uuids:
        entry = points.get(u)
        if isinstance(entry, dict) and entry.get("value_col") != PV_SHAPE:
            entry["value_col"] = PV_SHAPE
            n += 1
    return n


def fetch_pv_uuids(endpoint: str, timeout: float = 30.0) -> List[str]:
    """The PV generation points' timeseries ids, from the live graph."""
    r = requests.post(
        endpoint,
        data={"query": PV_POINTS_QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    r.raise_for_status()
    return pv_uuids_from(r.json()["results"]["bindings"])


#: The publisher's shape key for a building water meter's interval volume (litres per reading),
#: and its range: the working week drawn by `sensor_signal.water_fraction`, 0-600 L a quarter-hour.
WATER_SHAPE = "water_l"
WATER_BAND = (0.0, 600.0, 1)

WATER_POINTS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?uuid WHERE {
  ?p a brick:Building_Water_Meter ;
     ref:hasExternalReference/ref:hasTimeseriesId ?uuid .
}
"""


def mark_water_shapes(points: Dict[str, Any], water_uuids: List[str]) -> int:
    """Give each building water meter the interval-volume shape and range; returns how many."""
    n = 0
    lo, hi, dec = WATER_BAND
    for u in water_uuids:
        entry = points.get(u)
        if not isinstance(entry, dict):
            continue
        want = {"value_col": WATER_SHAPE, "lo": lo, "hi": hi, "dec": dec}
        if any(entry.get(k) != v for k, v in want.items()):
            entry.update(want)
            n += 1
    return n


def _fetch_uuids(endpoint: str, query: str, timeout: float = 30.0) -> List[str]:
    r = requests.post(
        endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    r.raise_for_status()
    return pv_uuids_from(r.json()["results"]["bindings"])


def apply_generation_shapes(points: Dict[str, Any], endpoint: str) -> Dict[str, int]:
    """Mark the map's PV and building-water points from the graph; returns counts marked."""
    return {
        "pv": mark_generation_shapes(points, fetch_pv_uuids(endpoint)),
        "water": mark_water_shapes(points, _fetch_uuids(endpoint, WATER_POINTS_QUERY)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:7200/repositories/bldg")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path = Path(args.map)
    points = json.loads(path.read_text(encoding="utf-8"))
    stats = apply_generation_shapes(points, args.endpoint)
    print(f"PV points given the solar shape: {stats['pv']}; water meters: {stats['water']}")
    if not args.dry_run and (stats["pv"] or stats["water"]):
        path.write_text(json.dumps(points, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
