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
    _apply_declared_room_ceilings(points)
    _drop_correlated_series(points)

    out = _REPO / "input" / f"{building_id}_narrow_publish_map.json"
    before: Dict[str, Any] = {}
    if out.exists():
        try:
            before = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            before = {}
    _stamp_band_provenance(points, before)
    added = len(set(points) - set(before))
    if points == before:
        return {"points": len(points), "tables": len(tables), "added": 0, "written": False}

    # Never write in place: a truncated map feeds nothing (lesson #109).
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".json")
    os.close(fd)
    Path(tmp).write_text(json.dumps(points, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    return {"points": len(points), "tables": len(tables), "added": added, "written": True}


#: A band that predates this stamp. NOT a date, on purpose: on 2026-09-30 an audit found
#: 1,544,386 stored rows outside the band their point declares and NONE of them written after
#: 2026-09-16, and a third of them are explained entirely by a band that was authored AFTER
#: the readings and applied from that moment with no migration. Writing today's date onto
#: those bands would assert something nobody measured; saying the date is unknown is the
#: finding. Only a band this code writes or changes gets a real date.
_BAND_PREDATES_STAMP = "unknown: this band predates the valid-from stamp"


def _stamp_band_provenance(points: Dict[str, Any], before: Dict[str, Any]) -> int:
    """Date each band from the day it took effect. Returns how many were newly dated.

    WHY A BAND NEEDS A DATE (CAVEAT-1131). Stored readings are judged against the band the
    building declares NOW, and a band is a constraint that can be added or narrowed at any
    time. A band with no valid-from cannot be told apart from one the readings were actually
    taken under, so an audit counts a schema change and a sensor fault as the same number and
    a lane averaging a multi-week window cannot say which it is looking at. The stamp is what
    makes the two separable, and `scripts/audit_declared_band_conformance.py` reads it.

    Carried forward untouched while the band is unchanged, so a rebuild that changes nothing
    still compares equal and the map is not rewritten every boot.
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    dated = 0
    for uuid, entry in points.items():
        if entry.get("lo") is None or entry.get("hi") is None:
            continue
        prior = before.get(uuid) or {}
        same_band = prior.get("lo") == entry["lo"] and prior.get("hi") == entry["hi"]
        if same_band and prior.get("band_from"):
            entry["band_from"] = prior["band_from"]
        elif same_band:
            # Already banded before anything dated bands. We do not know when, and the
            # honest record of that is the words, not a plausible date.
            entry["band_from"] = _BAND_PREDATES_STAMP
        else:
            entry["band_from"] = today
            dated += 1
    if dated:
        logger.info(
            f"[publisher_map] {dated} band(s) newly declared or changed today ({today}); "
            f"readings stored before that date were written under a different band or none"
        )
    return dated


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
    logger.info(f"[publisher_map] {len(banded)} of {len(points)} point(s) carry a declared band")
    return len(banded)


#: A MEASURAND BAND CANNOT EXPRESS A ROOM-LEVEL LIMIT (BUG-1135).
#:
#: `_attach_bands` above gives every point the band its QUANTITY declares, and for a people
#: counter this building declares exactly one: `ontosage:OccupancyCount 0..30`. So all 256
#: room counters are banded identically and the publisher drives each to a diurnal peak at
#: the top of that band. Measured 2026-09-30, latest reading per uuid against the capacities
#: the building itself declares: 29 of the 41 rooms that carry both were over capacity, six
#: eight-person rooms peaking at 30 in seven days — 3.75x. A simulated reading that is
#: physically impossible for the room it names is worse than one that is merely approximate.
#:
#: The ceiling is not invented here and no new predicate is added: `hbco:roomCapacity` is
#: already a triple on 42 spaces, so this reads a fact the graph holds. The relation from a
#: point to its space is bound with a VARIABLE predicate because this building spells it
#: three ways — `brick:hasLocation` (41 counters), `rec:locatedIn` (41) and `brick:isPartOf`
#: (12) — and a query naming one of them loses two thirds of the rooms without saying so
#: (lesson #161). What matters is reaching a space that declares a capacity, not which
#: predicate got there.
#:
#: IT ONLY EVER LOWERS A CEILING, and that is a deliberate choice against the obvious one.
#: Replacing the band with the capacity outright would also RAISE eleven of them — a dry run
#: on 2026-09-30 moved Room2.15 from 30 to 40 — and BUG-1137 measures that same room at
#: 7.83 m², so 40 people is 0.20 m² each and the raise manufactures a reading that is
#: impossible on floor area alone. Lowering and raising do not carry the same risk: if a
#: declared capacity is too small the counter under-reports, which is wrong and harmless,
#: while if it is too large the counter asserts a crowd the room cannot hold. So the ceiling
#: is `min(the quantity's typical maximum, the room's declared capacity)` — neither source
#: can make a reading more crowded than it already allows. The cost is stated rather than
#: discovered: eleven rooms that declare 40 or 50 keep the 30 they have today, so those
#: remain under-reported and this fixes 36 of the 53 counters it can reach.
#:
#: WHAT THIS IS NOT. A capacity carries `ontosage:capacityBasis` saying it is *estimated and
#: not certified*, so the ceiling inherits that basis and must never be read as a fire limit;
#: BUG-1137 holds evidence that 20 of the 42 figures are themselves implausible. It also only
#: reaches the points whose room declares a capacity — the rest keep the measurand band, so
#: this narrows the defect rather than closing it. Both facts are recorded on every entry it
#: touches (`hi_basis`) rather than left to be rediscovered from a band with no provenance.
_ROOM_CEILING_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX hbco:  <http://ontosage.org/hbco#>
SELECT ?uuid (MIN(?cap) AS ?capacity) WHERE {
  ?sensor a brick:Occupancy_Count_Sensor ;
          ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid .
  ?sensor ?anyLocationRelation ?space .
  ?space hbco:roomCapacity ?cap .
}
GROUP BY ?uuid
"""

#: `MIN(?cap)` above, and a point that reaches two disagreeing capacities takes the LOWER —
#: the same rule BUG-896 applied when two occupancy records disagreed, for the same reason:
#: exceeding a recorded limit is the dangerous direction. Measured on this building no
#: counter reaches two different capacities, so the rule is a guard, not a correction.

#: A counter whose room is declared this small cannot be generated AS a counter: the signal
#: generator treats `dec == 0` with a span of 1 or less as a BINARY point that holds and
#: flips, so a one- or two-person room would silently stop being a count and start being a
#: presence flag. No room in this building is that small; the guard is here because the next
#: building's might be, and a modality changing shape without a word is worse than a band
#: that is too wide.
_MIN_COUNTABLE_SPAN = 2.0


def _apply_declared_room_ceilings(points: Dict[str, Dict[str, Any]]) -> int:
    """Cap a people counter at the capacity its own room declares. Returns how many."""
    import urllib.request

    req = urllib.request.Request(
        _endpoint(),
        data=_ROOM_CEILING_QUERY.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as fh:
            rows = json.load(fh)["results"]["bindings"]
    except Exception as exc:  # a building with no capacities is not an error
        logger.info(f"[publisher_map] no declared room capacities applied: {exc}")
        return 0

    applied = skipped = wider = 0
    for row in rows:
        entry = points.get(row["uuid"]["value"])
        if not entry or entry.get("hi") is None:
            continue
        try:
            capacity = float(row["capacity"]["value"])
        except (KeyError, TypeError, ValueError):
            continue
        low = float(entry.get("lo", 0.0))
        if capacity - low < _MIN_COUNTABLE_SPAN:
            skipped += 1
            continue
        if capacity >= float(entry["hi"]):
            # The room declares MORE than the quantity's typical maximum. Not applied: see
            # the note above — raising a ceiling on an estimated capacity manufactures a
            # crowd, and lowering one only under-reports.
            wider += 1
            continue
        entry["hi"] = capacity
        # The band now says something the measurand cannot, so it must say where it came
        # from. A ceiling with no basis cannot be told apart from a certified limit.
        entry["hi_basis"] = (
            "hbco:roomCapacity of the space this point is in; estimated, not certified "
            "(ontosage:capacityBasis)"
        )
        applied += 1
    if applied or skipped or wider:
        logger.info(
            f"[publisher_map] {applied} people counter(s) capped at the capacity their room "
            f"declares; {wider} left on the measurand band (the room declares MORE and an "
            f"estimated capacity may not raise a ceiling); {skipped} left on it (the room "
            f"is declared too small to generate as a count at all)"
        )
    return applied


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
