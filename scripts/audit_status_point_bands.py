#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A point the ontology types as a STATUS must be generated as a boolean (BUG-1150).

WHAT WENT WRONG
---------------
``Booking_Status_Room1_25`` carries the label "Booking Status - Seminar Room 1.25
(available=0 / booked=1)" and is typed ``brick:Occupancy_Status``, which Brick declares a
``brick:Status`` and not a ``brick:Sensor``. Between 2026-08-22 and 2026-09-16 its series
nevertheless held an occupancy COUNT -- 0..189.48 at the widest, 0..30 for most of that
window. A reader asking how many people were in Seminar Room 1.25 got a number, and the
graph said in the same breath that the point only has two states.

WHY THIS IS AN AUDIT AND NOT A NAME LIST
----------------------------------------
The tempting check is "the point is called ``*_Status``". That is the same failure one level
down: it is a building literal wearing a regex, it breaks on the next building's naming, and
it cannot see a point that is a status under another name. The ontology already knows. Brick
declares::

    brick:Occupancy_Status  rdfs:subClassOf* brick:Status
    brick:Open_Close_Status rdfs:subClassOf* brick:Status
    brick:Occupancy_Count_Sensor rdfs:subClassOf* brick:Sensor

so the question "is this point boolean by declaration?" is a subclass closure, not a string.

THE RULE IS ONE-DIRECTIONAL, AND THAT IS MEASURED RATHER THAN ASSUMED
---------------------------------------------------------------------
``Status`` implies boolean. ``Sensor`` does NOT imply continuous: ``brick:Contact_Sensor`` is
a ``brick:Sensor`` and reads 0/1, and on this building 479 points are exactly that. An audit
that asserted the converse would report 479 false positives on its first run and be switched
off by its second. So this only fails a point that is declared a Status and generated wider
than 0..1.

    python scripts/audit_status_point_bands.py            # exits 1 on any violation
    python scripts/audit_status_point_bands.py --verbose  # also print what passed, by bucket

Read-only. It queries GraphDB and reads the publish maps; it writes nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent

#: The Brick TBox roots whose subclasses have a fixed, enumerated set of states. These are
#: ROOTS OF A SUBCLASS CLOSURE, not names matched against a point -- a building may call its
#: points anything at all and still be typed under one of these.
BOOLEAN_ROOTS = ("Status", "Alarm", "Command")

GRAPHDB = os.environ.get(
    "GRAPHDB_QUERY_URL",
    os.environ.get("GDB", "http://localhost:7200/repositories/bldg"),
)


# -- the rule ------------------------------------------------------------------


def band_is_boolean(entry: Dict[str, Any]) -> Optional[bool]:
    """Is this publish-map entry's declared band a boolean one? None = it declares no band.

    The generator's own branch is ``dec == 0 and (hi - lo) <= 1.0``
    (``mysql-dummy-publish-dev/sensor_signal.py``), so that is the condition asked here. Any
    other definition would let the audit pass a point the generator then fills with a count.
    """
    lo, hi = entry.get("lo"), entry.get("hi")
    if lo is None or hi is None:
        return None
    return (float(hi) - float(lo)) <= 1.0 and int(entry.get("dec") or 0) == 0


def violates(is_status: bool, boolean_band: Optional[bool]) -> bool:
    """A declared status generated outside 0..1. One direction only -- see the module docstring."""
    return bool(is_status) and boolean_band is False


# -- inputs --------------------------------------------------------------------


def sparql(query: str, timeout: int = 300) -> List[dict]:
    req = urllib.request.Request(
        GRAPHDB,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed http scheme
        return json.loads(r.read().decode("utf-8"))["results"]["bindings"]


def declared_points() -> List[Tuple[str, str, str, bool]]:
    """(uuid, point name, label, is_status) for every point that resolves to a series.

    The reference predicate is left UNBOUND on purpose: this building spells
    ``hasExternalReference`` three ways and a ``ref:``-only filter missed 71 points (BUG-531,
    lessons #161). Reaching a timeseries id is what matters.
    """
    roots = " ".join(f"brick:{r}" for r in BOOLEAN_ROOTS)
    rows = sparql(
        f"""PREFIX brick: <https://brickschema.org/schema/Brick#>
            PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
            PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?u (SAMPLE(?p) AS ?pt) (SAMPLE(?l) AS ?lab)
                   (MAX(?isBool) AS ?status)
            WHERE {{
              ?p ?anyRefPred ?r . ?r ref:hasTimeseriesId ?u .
              ?p a ?c .
              OPTIONAL {{ ?p rdfs:label ?l }}
              BIND(IF(EXISTS {{ ?c rdfs:subClassOf* ?root .
                                VALUES ?root {{ {roots} }} }}, 1, 0) AS ?isBool)
            }} GROUP BY ?u"""
    )
    out = []
    for r in rows:
        out.append(
            (
                r["u"]["value"],
                r["pt"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1],
                r.get("lab", {}).get("value", ""),
                str(r["status"]["value"]) not in ("0", "false"),
            )
        )
    return out


def _walk(node: Any) -> Iterator[Dict[str, Any]]:
    """Every dict in a publish map that names a uuid, whatever the map's shape.

    The narrow map is uuid -> entry; the plant map nests entries under groups and roles. A
    shape assumption here would quietly skip a whole store, so it makes none.
    """
    if isinstance(node, dict):
        if "uuid" in node and isinstance(node.get("uuid"), str):
            yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def publish_map_bands(input_dir: Path) -> Dict[str, Dict[str, Any]]:
    bands: Dict[str, Dict[str, Any]] = {}
    for path in sorted(input_dir.glob("*publish_map*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  ! could not read {path.name}: {exc}", file=sys.stderr)
            continue
        for entry in _walk(data):
            bands.setdefault(entry["uuid"], entry)
    return bands


# -- run -----------------------------------------------------------------------


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", default=str(REPO / "input"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"no input directory at {input_dir} — is a building active?", file=sys.stderr)
        return 2

    bands = publish_map_bands(input_dir)
    points = declared_points()
    print(f"points resolving to a series : {len(points)}")
    print(f"publish-map entries with a uuid: {len(bands)}")

    buckets = {"status/boolean": 0, "status/undeclared": 0, "other": 0, "unmapped": 0}
    bad: List[Tuple[str, str, Dict[str, Any]]] = []
    for uuid, name, label, is_status in points:
        entry = bands.get(uuid)
        if entry is None:
            buckets["unmapped"] += 1
            continue
        boolean_band = band_is_boolean(entry)
        if violates(is_status, boolean_band):
            bad.append((name, label, entry))
        elif is_status and boolean_band is None:
            buckets["status/undeclared"] += 1
        elif is_status:
            buckets["status/boolean"] += 1
        else:
            buckets["other"] += 1

    if args.verbose:
        for k, v in sorted(buckets.items()):
            print(f"   {v:>5}  {k}")

    if not bad:
        print(
            f"\nOK — {buckets['status/boolean']} declared status points all carry a boolean "
            f"band; {buckets['status/undeclared']} declare no band at all."
        )
        return 0

    print(f"\nFAIL — {len(bad)} point(s) the ontology declares a status, generated as numbers:")
    for name, label, entry in sorted(bad)[:50]:
        print(
            f"   {name[:42]:<42} lo={entry.get('lo')} hi={entry.get('hi')} "
            f"dec={entry.get('dec')} col={entry.get('value_col')}"
        )
        if label:
            print(f"       label: {label[:96]}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
