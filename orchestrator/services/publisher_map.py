# -*- coding: utf-8 -*-
"""Keep the publisher's point map in step with the graph, at boot.

WHY THIS RUNS AUTOMATICALLY. Adding points is three steps — write the TTL, upload it, tell
the publisher — and the third was a script somebody had to remember. On 2026-09-16, 498 new
points were provisioned and uploaded; the graph knew them, the publisher did not, and every
question about them answered "no recent reading". To a stakeholder that is indistinguishable
from a broken sensor, and nothing in the system said otherwise.

So the map is rebuilt whenever the uploader actually ingested something. Nothing here knows a
building: the store list comes from the building's own `database_registry.yaml`, the points
from its graph, and the output path from its id.

The generator in `scripts/generate_publisher_map.py` owns the derivation; this module is the
boot-time caller, so the rule that decides a point's table and value column has ONE
implementation rather than two that can disagree.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[2]


def _endpoint() -> str:
    base = os.environ.get("GRAPHDB_URL", "http://graphdb:7200").rstrip("/")
    repo = os.environ.get("GRAPHDB_REPOSITORY", "bldg")
    return f"{base}/repositories/{repo}"


def _rebuild(building_id: str) -> Dict[str, Any]:
    """Derive the map and write it atomically. Returns what changed."""
    if str(_REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(_REPO / "scripts"))
    from generate_publisher_map import build_map, narrow_tables  # type: ignore

    from shared.building_paths import resolve_building_file

    registry = resolve_building_file(building_id, "database_registry.yaml")
    tables = narrow_tables(Path(registry))
    points = build_map(_endpoint(), tables)
    _attach_bands(points)
    _drop_correlated_series(points)

    out = _REPO / "input" / f"{building_id}_narrow_publish_map.json"
    before: Dict[str, Any] = {}
    if out.exists():
        try:
            before = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            before = {}
    added = len(set(points) - set(before))
    if points == before:
        return {"points": len(points), "tables": len(tables), "added": 0, "written": False}

    # Never write in place: a truncated map feeds nothing (lesson #109).
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".json")
    os.close(fd)
    Path(tmp).write_text(json.dumps(points, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    return {"points": len(points), "tables": len(tables), "added": added, "written": True}


async def refresh_publish_map(building_id: str) -> Dict[str, Any]:
    """Rebuild the map off the event loop — it is a synchronous SPARQL read."""
    return await asyncio.get_event_loop().run_in_executor(None, _rebuild, building_id)


#: The band a quantity is ordinarily found in, per POINT. The publisher otherwise picks a
#: range by COLUMN NAME, and a narrow table holds one column for a whole family: every gas in
#: this building writes to `iaq_data.voc`, so carbon monoxide inherited TVOC's 50-350 and
#: published readings around 204 ppm. Carbon monoxide is dangerous to a person at 200 ppm and
#: the building declares its ordinary range as 0-5, so the number was not merely unrealistic —
#: it was the shape of reading somebody evacuates a building over.
#:
#: The band is the ontology's own `typicalMin/typicalMax/typicalDecimals`, read per sensor
#: class. Nothing is invented here: a class that declares no measurand simply gets no band and
#: keeps the publisher's column default.
#: THE MOST SPECIFIC DECLARING CLASS WINS, by hierarchy depth. A point is typed with several
#: classes, and the shallow ones describe a family: a boiler's flow temperature is a
#: Temperature_Sensor (ordinary range 18-28, because that is a ROOM) and a
#: Leaving_Water_Temperature_Sensor (ordinary range 40-80). Taking either the first or the
#: widest gave a 69 °C heating flow the band for an office, and gave occupancy counts a
#: boolean 0-1. This is BUG-609's mistake in a new place, and the same rule fixes it: rank by
#: how deep the class sits and take the deepest.
_BANDS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:  <https://brickschema.org/schema/Brick/ref#>
PREFIX o:    <http://ontosage.org/capabilities#>
SELECT ?uuid ?lo ?hi ?dec (COUNT(DISTINCT ?anc) AS ?depth) WHERE {
  ?sensor ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid .
  ?sensor a ?cls .
  ?cls o:measuresQuantityKind ?m .
  ?m o:typicalMin ?lo ; o:typicalMax ?hi .
  OPTIONAL { ?m o:typicalDecimals ?dec }
  OPTIONAL { ?cls rdfs:subClassOf* ?anc }
}
GROUP BY ?uuid ?lo ?hi ?dec
ORDER BY ?uuid DESC(?depth)
"""


def _attach_bands(points: Dict[str, Dict[str, Any]]) -> int:
    """Give every point its declared ordinary range. Returns how many were given one."""
    import urllib.request

    req = urllib.request.Request(
        _endpoint(),
        data=_BANDS_QUERY.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as fh:
        rows = json.load(fh)["results"]["bindings"]
    # A sensor typed with several classes yields several rows; count POINTS, or the log
    # reads "4088 of 2844" and the first thing it teaches anyone is not to trust it.
    banded = set()
    for row in rows:
        uuid = row["uuid"]["value"]
        entry = points.get(uuid)
        if not entry:
            continue
        # Rows arrive deepest-class-first per uuid, so the FIRST one for a uuid is the most
        # specific declaration and every later one is a shallower family. Widening to fit
        # them both is how a boiler flow ended up sharing a band with an office.
        if uuid in banded:
            continue
        entry["lo"] = float(row["lo"]["value"])
        entry["hi"] = float(row["hi"]["value"])
        entry["dec"] = int(float(row.get("dec", {}).get("value", 2)))
        banded.add(uuid)
    logger.info(
        f"[publisher_map] {len(banded)} of {len(points)} point(s) carry a declared band"
    )
    return len(banded)


#: Tables whose series are generated as a CORRELATED SET, not point by point.
#:
#: A boiler's flow and return come from one seed, so the difference between them is a real
#: delta-T and a question can ask about it. A per-point publisher cannot reproduce that: it
#: draws each point independently, so flow and return wander apart and the delta becomes
#: noise with a plausible shape — and on 2026-09-16 it also published a 69 degC heating flow
#: at 22.5 degC, because the only ordinary range the ontology declares for water temperature
#: is the AIR one it inherits (`ontosage:WaterTemperature` has a physical band and no typical
#: band).
#:
#: These points keep the history their own generator wrote. Re-provision them with
#: scripts/provision_plant_points.py rather than publishing over them.
#: The waste tables join for the same reason and were added the day they were provisioned,
#: after this map quietly claimed them. A bin's fill level is a SAWTOOTH -- it accumulates
#: and is emptied -- and its weight follows that fill through the bin's own capacity. This
#: map had no band for either (the fallback value column, ``generic``), so the narrow
#: publisher wrote a
#: uniform 0-100 into both tables every 30 s while the waste generator wrote the correct
#: shape every 300 s. The frequent, wrong writer won: a recycling bin with a 28 kg capacity
#: was reporting 60 kg, and fill had stopped being a sawtooth at all.
#:
#: TWO WRITERS ON ONE SERIES IS THE DEFECT, not the values either of them chose. Adding a
#: table here is how a series says "one generator already understands me".
_CORRELATED_TABLES = frozenset({"plant_data", "wastefill_data", "wasteweight_data"})


def _drop_correlated_series(points: Dict[str, Any]) -> int:
    """Leave correlated series to the generator that understands the correlation."""
    dropped = [u for u, e in points.items() if e.get("table") in _CORRELATED_TABLES]
    for uuid in dropped:
        points.pop(uuid, None)
    if dropped:
        logger.info(
            f"[publisher_map] {len(dropped)} point(s) left to their own generator "
            f"({', '.join(sorted(_CORRELATED_TABLES))})"
        )
    return len(dropped)
