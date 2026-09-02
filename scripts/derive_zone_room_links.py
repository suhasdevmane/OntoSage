#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assert the zone <-> room correspondence a building's TTL leaves unstated (BUG-388).

THE PROBLEM
-----------
bldg1's spatial graph is two disconnected overlays. The real abacws sensors hang off HVAC
zones (``Air_Temperature_Sensor_5.04 brick:hasLocation Zone_5.04``) while the synthetic
saturation overlay hangs off rooms (``Room5.04_sat_temperature brick:hasLocation Room5.04``).
Measured live: 39 HVAC zones, 234 rooms, and ZERO predicates joining a room to a zone in
either direction.

The consequence is BUG-378. A question about "room 5.04" resolves ONLY the saturation point,
because that is the one whose location is Room5.04 — so the live sensor holding 1,045
readings for the date asked about is never even a candidate, and the store-coverage selection
that would prefer it has nothing to choose between. The lane then answers "No data found"
about a room whose temperature is sitting in the wide store.

WHY THIS IS A SCRIPT AND NOT A HAND-EDITED FILE
-----------------------------------------------
The links are DERIVED, and derived facts should be reproducible. Re-running this after the
ontology changes regenerates the file; a hand-edited one silently rots.

WHAT IT WILL AND WILL NOT ASSERT
--------------------------------
Only an EXACT, UNAMBIGUOUS identifier match: an id must resolve to exactly one zone and
exactly one room. Measured on bldg1 that is 24 of 34 zones — 10 zones (5.19, 5.24, 5.25,
5.27-5.33) have no matching room and are left alone, as are the 201 room ids with no zone.

That conservatism is the point. This writes into the source of truth, and a wrong containment
claim is worse than the gap it fills: it would let an answer about one room be served from
another room's sensor, which is precisely the substitution the honesty contract forbids.
Every triple is therefore stamped as derived-by-identifier rather than surveyed, and written
to its own named graph so it can be dropped wholesale if the mapping turns out to be wrong.

BUILDING-AGNOSTIC
-----------------
No building name, no namespace and no room list appears here. Zones and rooms are read from
whatever building is live, the identifier is whatever trailing ``N.NN`` their names carry, and
a building that already links its spaces produces an empty file and a message saying so.

    python scripts/derive_zone_room_links.py --building-id bldg1
    python scripts/derive_zone_room_links.py --building-id bldg1 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent

#: The trailing identifier shared by a zone and the room it serves — "5.04" in both
#: ``Zone_5.04`` and ``Room5.04``. Anchored at the end so a digit elsewhere in the name
#: cannot masquerade as one.
_IDENT_RE = re.compile(r"(\d+\.\d+)$")

_PREFIXES = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
"""


def _sparql(endpoint: str, query: str) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        endpoint,
        data=query.encode("utf-8"),
        headers={"Content-Type": "application/sparql-query", "Accept": "text/csv"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310 - fixed local endpoint
        return list(csv.DictReader(StringIO(resp.read().decode("utf-8"))))


def _by_identifier(iris: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    for iri in iris:
        match = _IDENT_RE.search(iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
        if match:
            out[match.group(1)].append(iri)
    return out


def derive_links(endpoint: str) -> Tuple[List[Tuple[str, str, str]], Dict[str, int]]:
    """(zone, room, identifier) triples to assert, plus counts for the report."""
    prefix = "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    zones = [r["z"] for r in _sparql(endpoint, prefix + "SELECT ?z WHERE { ?z a brick:HVAC_Zone }")]
    rooms = [r["r"] for r in _sparql(endpoint, prefix + "SELECT ?r WHERE { ?r a brick:Room }")]
    existing = _sparql(
        endpoint,
        prefix + "SELECT (COUNT(*) AS ?n) WHERE { ?r a brick:Room . ?z a brick:HVAC_Zone . "
        "{ ?r ?p ?z } UNION { ?z ?p ?r } }",
    )

    zi, ri = _by_identifier(zones), _by_identifier(rooms)
    links: List[Tuple[str, str, str]] = []
    ambiguous = 0
    for ident in sorted(set(zi) & set(ri), key=lambda s: [int(x) for x in s.split(".")]):
        # More than one candidate on either side means the identifier does not pick out a
        # single pair, and a guess here would assert a containment nobody verified.
        if len(zi[ident]) != 1 or len(ri[ident]) != 1:
            ambiguous += 1
            continue
        links.append((zi[ident][0], ri[ident][0], ident))

    stats = {
        "zones": len(zones),
        "rooms": len(rooms),
        "existing_links": int((existing[0]["n"] if existing else 0) or 0),
        "matched": len(links),
        "ambiguous_skipped": ambiguous,
        "zones_without_room": len(set(zi) - set(ri)),
        "rooms_without_zone": len(set(ri) - set(zi)),
    }
    return links, stats


def _namespace_of(iri: str) -> str:
    """The building namespace an IRI belongs to, up to and including its separator.

    Derived from the data rather than configured. Every per-building TTL must declare
    ``@prefix bldg:`` and the validator HARD-FAILS a file that omits it or disagrees with
    ``ontology_namespace`` — which is exactly what happened to the first version of this
    generator, which emitted full IRIs and was rejected at boot. Reading the namespace off
    the entities means the declaration cannot disagree with them.
    """
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[0] + sep
    return iri


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def render_ttl(links: List[Tuple[str, str, str]], building_id: str) -> str:
    lines = [
        f"# Zone <-> room correspondence for {building_id}, DERIVED not surveyed (BUG-388).",
        "#",
        "# Generated by scripts/derive_zone_room_links.py on "
        f"{date.today().isoformat()}. Do not hand-edit; re-run the script.",
        "#",
        "# WHY: the building's real sensors are located on HVAC zones and its synthetic",
        "# saturation overlay on rooms, with nothing in the graph joining the two. A question",
        "# about a room therefore never sees the room's real sensor (BUG-378).",
        "#",
        "# BASIS: an exact, unambiguous match on the trailing identifier the two names share",
        "# (Zone_5.04 <-> Room5.04). Asserted ONLY where one zone and one room carry the same",
        "# identifier. This is a derived claim about containment, not a survey result, and",
        "# every subject below carries an rdfs:comment saying so.",
        "#",
        "# If the mapping is ever shown to be wrong, drop this named graph: nothing else",
        "# depends on these triples and no other file duplicates them.",
        "",
        f"@prefix bldg:  <{_namespace_of(links[0][0])}> .",
        _PREFIXES,
    ]
    for zone, room, ident in links:
        note = f'"derived-zone-room-link-v1: matched on identifier {ident}, not surveyed"'
        lines += [
            f"bldg:{_local(zone)} brick:hasPart bldg:{_local(room)} ;",
            f"    rdfs:comment {note} .",
            f"bldg:{_local(room)} brick:isPartOf bldg:{_local(zone)} ;",
            f"    rdfs:comment {note} .",
            "",
        ]
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--building-id", required=True)
    ap.add_argument("--endpoint", default="http://localhost:7200/repositories/bldg")
    ap.add_argument("--dry-run", action="store_true", help="report the mapping, write nothing")
    args = ap.parse_args(argv)

    links, stats = derive_links(args.endpoint)
    print(
        f"zones={stats['zones']}  rooms={stats['rooms']}  existing links={stats['existing_links']}"
    )
    print(
        f"matched={stats['matched']}  ambiguous skipped={stats['ambiguous_skipped']}  "
        f"zones without a room={stats['zones_without_room']}  "
        f"rooms without a zone={stats['rooms_without_zone']}"
    )
    if stats["existing_links"]:
        print("This building already links rooms to zones; nothing to derive.")
        return 0
    if not links:
        print("No unambiguous identifier matches; nothing asserted.")
        return 0

    for zone, room, _ in links[:3]:
        print(f"  {zone.rsplit('#', 1)[-1]}  hasPart  {room.rsplit('#', 1)[-1]}")
    print(f"  ... {len(links)} pair(s)")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    out = REPO / "input" / f"{args.building_id}_zone_room_links.ttl"
    out.write_text(render_ttl(links, args.building_id), encoding="utf-8")
    print(f"\n[written] {out}  ({len(links) * 2} triples)")
    print("Restart the orchestrator so ttl_uploader ingests it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
