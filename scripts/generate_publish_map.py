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

THE THREE DEFECTS FOUND ON 2026-09-30 (BUG-1142), AND WHAT EACH COST
--------------------------------------------------------------------
This script had not been run since the map it owns was last extended by other means, so
nothing exercised it and nothing failed. A dry run measured what a real run would do:
write 32 entries and remove all 1,086 on disk. Attributed by measurement, that number is
not one defect but three, and only one of them was harmful:

**(a) Predicate blindness in both queries -- the whole of the harm.** Both traversals
asked for `?sensor ref:hasExternalReference ?r`. This building spells that relation three
ways: `ref:hasExternalReference` (3,515 triples), `ashrae:hasExternalReference` (3,640)
and `brick:hasExternalReference` (2). Counting distinct uuids that also declare a
`ref:storedAt`, `ref:` alone reaches 3,507 and any predicate reaches 3,544 -- a blind spot
of 37. Those 37 are the sole-reference points on the building's synthetic narrow store,
and **36 of them are the only entries in this map that the publisher actually publishes**
(confirmed from its own log). So a `ref:`-only run silenced 36 live streams and nothing
else. Same cause as BUG-1141, BUG-531 and BUG-481.

The filter now binds `?anyRefPred` rather than naming a predicate. Reaching a timeseries
id is what "has a reference" means, so that is what the query asks. Naming two spellings
only waits for a third. Measured after the change: distinct uuids 2,919 -> 2,956 and
narrow-store candidates 2,543 -> 2,579, both exactly +36/+37 -- no over-capture. `DISTINCT`
is now required because a sensor carrying two spellings of the relation matches twice
(4,895 rows became 9,849 without it).

**(b) The remaining 1,050 removals were inert, and removing them is the fix.** They are
also present in the sibling narrow publish map, and the publisher drops every collision at
load time so that no uuid is written twice per tick: its log reads `1050 sensor(s) appear
in BOTH publish maps`, then `Loaded 36 extended narrow sensors`. The file has therefore
been 97% dead weight, and the disjointness this script exists to maintain was already
violated on disk. These 1,050 were the part of the landmine that looked worst and cost
nothing.

**(c) The guard could not see two of the four publish maps -- a live double-write.**
`_already_published` read only the TOP level of each `*_publish_map.json`. The narrow map
is a flat `{uuid: entry}` dict so it was read correctly; the plant and waste maps nest
their points under `groups[*].roles[*]` and `bins[*].roles[*]`, so the guard collected
**0 of the plant map's 44 uuids and 0 of the waste map's 24**. All 32 entries the old
code would have written were AHU points the plant lane already publishes into the same
`plant_data` table on every tick (`plant: 44 point(s), waste: 24 point(s)` in the
publisher log). The publisher's own runtime collision guard would not have caught them
either -- it compares the extended map against the narrow map only. The walk is now
recursive, which is the safe direction to be wrong in: over-collecting can only make this
script omit an entry, which is visible and recoverable, while under-collecting doubles a
stream's apparent sampling rate and every freshness and stuck-sensor window is expressed
in samples somewhere (CAVEAT-402).

**And the rail, because none of the above is why a script should be safe.** A generator
that rewrites a publish map from scratch can silence a building whatever the reason, so it
now refuses to write when the removal would stop a stream nothing else publishes, and
refuses a bulk removal above `--max-delete-pct` even when every removal looks covered.
`--force` overrides, and prints what it is overriding. Today's correct run removes 96.7%
and silences nothing, so it needs `--force` -- that is the rail working, not misfiring.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

GRAPHDB = "http://localhost:7200/repositories/bldg"

#: Refuse a bulk removal above this share of the existing map without --force.
#: See the module docstring, "And the rail".
DEFAULT_MAX_DELETE_PCT = 25.0

#: Sensors are matched to a range through the ontology, in one query.
#:
#: `?cls` is every class the sensor has; the ontology only declares a measurand on the
#: classes where the quantity is unambiguous, so a sensor typed both `CO2_Sensor` and
#: `Air_Quality_Sensor` matches exactly one band -- the supertype deliberately declares
#: none. That is what makes "most specific" fall out of the data rather than out of a
#: hand-maintained precedence list here.
#:
#: `?anyRefPred` is bound, not named -- see the module docstring, defect (a).
_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX o:     <http://ontosage.org/capabilities#>
SELECT DISTINCT ?sensor ?uuid ?store ?cls ?lo ?hi ?dec WHERE {
  ?sensor ?anyRefPred ?r .
  ?r ref:hasTimeseriesId ?uuid ; ref:storedAt ?store .
  ?sensor a ?cls .
  ?cls o:measuresQuantityKind ?m .
  ?m o:typicalMin ?lo ; o:typicalMax ?hi .
  OPTIONAL { ?m o:typicalDecimals ?dec }
}
"""

#: Sensors that HAVE a timeseries reference but whose classes declare no measurand.
#: Reported so the gap is visible; never guessed at.
#:
#: Binds `?anyRefPred` for the same reason as `_QUERY`: a gap report built on a narrower
#: traversal than the thing it reports on understates the gap.
_UNMAPPED = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX o:     <http://ontosage.org/capabilities#>
SELECT ?uuid (SAMPLE(?store) AS ?store)
       (GROUP_CONCAT(DISTINCT ?cls; separator=" ") AS ?classes) WHERE {
  ?sensor ?anyRefPred ?r .
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


def _uuids_anywhere(obj: Any, acc: Set[str]) -> Set[str]:
    """Every `"uuid"` string anywhere in a decoded JSON structure.

    A publish map is not required to be a flat mapping of uuid -> entry, and two of this
    building's four are not: the plant map nests points under `groups[*].roles[*]` and the
    waste map under `bins[*].roles[*]`. A top-level walk sees neither. See the module
    docstring, defect (c).
    """
    if isinstance(obj, dict):
        u = obj.get("uuid")
        if isinstance(u, str) and u:
            acc.add(u)
        for v in obj.values():
            _uuids_anywhere(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _uuids_anywhere(v, acc)
    return acc


def _already_published(out_dir: Path) -> Dict[str, str]:
    """uuid -> the name of the OTHER map that already writes it.

    The maps must be disjoint. A uuid written by two of them on the same tick doubles its
    apparent sampling rate, and every window a freshness check or a stuck-sensor detector
    reasons about is expressed in samples somewhere (CAVEAT-402). The publisher defends
    itself by dropping collisions, but it compares only this map against the narrow one, so
    a collision with the plant or waste map is caught by nothing at all. Relying on a
    downstream drop also means this file's contents are only correct because something
    else corrects them.

    Returns the claiming file's name rather than a bare set, so that a removal this script
    refuses can name who is expected to keep publishing the point.
    """
    claimed: Dict[str, str] = {}
    for p in sorted(out_dir.glob("*_publish_map.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for uuid in _uuids_anywhere(data, set()):
            claimed.setdefault(uuid, p.name)
    return claimed


def build(
    endpoint: str, registry: Path, out_dir: Path
) -> Tuple[Dict[str, dict], Counter, List[str], int, Dict[str, str]]:
    """(map, per-class counts, uuids whose class declares no measurand, n excluded, claims)."""
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
    return out, classes, unmapped, len(excluded), published_elsewhere


def _removal_report(
    current: Dict[str, dict], fresh: Dict[str, dict], claimed: Dict[str, str]
) -> Tuple[Set[str], Set[str], Counter]:
    """(removed, silenced, who-claims-the-rest).

    `silenced` is the only number that describes harm: a uuid this map would stop writing
    and that no other publish map writes either. A removal claimed by a sibling map is a
    duplicate being dropped, which is what disjointness means.
    """
    removed = set(current) - set(fresh)
    silenced = {u for u in removed if u not in claimed}
    by_file = Counter(claimed[u] for u in removed if u in claimed)
    return removed, silenced, by_file


def _read_current(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = data.values() if isinstance(data, dict) else data
    return {str(e["uuid"]): e for e in entries if isinstance(e, dict) and e.get("uuid")}


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
    ap.add_argument(
        "--max-delete-pct",
        type=float,
        default=DEFAULT_MAX_DELETE_PCT,
        help=(
            "refuse to remove more than this share of the existing map without --force "
            f"(default {DEFAULT_MAX_DELETE_PCT:g}%%)"
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="write anyway, and print what is being overridden",
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
        mapping, classes, unmapped, excluded, claimed = build(args.endpoint, registry, out_dir)
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
    current = _read_current(path)
    removed, silenced, by_file = _removal_report(current, mapping, claimed)
    added = set(mapping) - set(current)
    pct = (100.0 * len(removed) / len(current)) if current else 0.0

    print(
        f"  against {path.name} on disk ({len(current)} entries): "
        f"+{len(added)} added, -{len(removed)} removed ({pct:.1f}%)"
    )
    for name, n in by_file.most_common():
        print(f"      {n:>5} of the removals are already published by {name}")
    if silenced:
        print(
            f"      {len(silenced)} of the removals are published by NOTHING ELSE - "
            f"removing them stops those streams:"
        )
        for u in sorted(silenced)[:10]:
            e = current[u]
            print(f"        {u}  {e.get('table')}  {e.get('class')}")
        if len(silenced) > 10:
            print(f"        ... and {len(silenced) - 10} more")

    if args.check:
        try:
            same = (
                json.loads(path.read_text(encoding="utf-8")) == mapping if path.exists() else False
            )
        except Exception:
            same = False
        if same:
            print("  map is up to date with the graph")
            return 0
        print(f"  STALE: {path.name} does not match what the graph declares")
        return 1

    # The rail. A generator that rewrites a publish map from scratch can silence a building
    # whatever the reason, so the refusal is on the OUTCOME, not on the diagnosis.
    refusals: List[str] = []
    if silenced:
        refusals.append(
            f"{len(silenced)} stream(s) would stop and no other publish map writes them"
        )
    if pct > args.max_delete_pct:
        refusals.append(
            f"the removal is {pct:.1f}% of the map, above --max-delete-pct={args.max_delete_pct:g}"
        )

    if args.dry_run:
        print(f"  [dry-run] would write {path.name} ({len(mapping)} entries)")
        if refusals:
            print("  [dry-run] a real run would REFUSE without --force:")
            for r in refusals:
                print(f"              - {r}")
        return 0

    if refusals and not args.force:
        print("  REFUSED - nothing written:")
        for r in refusals:
            print(f"    - {r}")
        print(
            "  Re-run with --force if that is what you intend. A removal every sibling map "
            "already claims is a duplicate being dropped; one nothing claims is a stream "
            "going silent."
        )
        return 2
    if refusals and args.force:
        print("  --force: overriding")
        for r in refusals:
            print(f"    - {r}")

    path.write_text(json.dumps(mapping, indent=1, sort_keys=True), encoding="utf-8")
    print(f"  wrote {path.name} ({len(mapping)} entries)")
    print("\nThe publisher reloads this on its next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
