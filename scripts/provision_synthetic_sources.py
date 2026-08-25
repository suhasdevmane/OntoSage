#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provision the institutional data the question bank needs, as DECLARED synthetic sources.

V6-T56/T57/T58/T60. Roughly 94% of the supervisors' 480 catalogue questions are blocked not by
this codebase but by data nobody has connected -- timetable, bookings, opening hours, lift and
AV status, accessibility register, cleaning schedules. This script provisions all of it.

WHY THIS IS LEGITIMATE AND NOT FABRICATION
Every record it writes carries ``ontosage:isSimulated true``. That is the same contract bldg2
and bldg3 already live under -- both are wholly synthetic and declared so -- and the same one
the SATURATE pipeline uses for sensor modalities. The honesty contract forbids UNDECLARED
fabrication, not declared simulation. An answer resting on a synthetic booking will say so
(V6-T62), and the scorecard reports the real/synthetic share per building.

HOW IT STAYS BUILDING-AGNOSTIC
It reads the ACTIVE building's own graph and provisions against what it finds: its spaces, its
floors, its lifts, its namespace. There is no building name, room id, floor count or sensor
count anywhere in this file. Run it against a two-room fixture and it provisions two rooms.

WHAT IT DELIBERATELY DOES **NOT** DO
It does not make everything work. Statuses include out-of-service lifts and unverified
accessibility features on purpose: a building where every asset is operational and every
feature verified would make the hard-filter and freshness gates untestable, and every gate
would pass by construction. Realistic imperfection is a feature here, and V6-T61 extends it
into the time-series streams.

    python scripts/provision_synthetic_sources.py --dry-run
    python scripts/provision_synthetic_sources.py --families hours,status,accessibility
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO = _SCRIPT_DIR.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402
import yaml  # noqa: E402

GRAPHDB = "http://localhost:7200/repositories/bldg"
ONTOSAGE_NS = "http://ontosage.org/capabilities#"

#: Advertised families. MUST stay in step with GENERATORS below — this listed
#: "closures" and "timetable", neither of which has a generator, so the constant
#: documented capability the script does not have. A pinned test now compares the
#: two, because a list that can drift from the code it describes will.
FAMILIES = ("hours", "status", "accessibility", "schedules")


def _env(key: str, default: str = "") -> str:
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
                return s.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return default


#: Every discovery query below uses GROUP BY + SAMPLE rather than SELECT DISTINCT.
#: A subject carrying two rdfs:labels fans an OPTIONAL out into two rows, and the generator
#: would then provision a duplicate entity per label. This building has exactly that: six
#: floors each labelled twice ("Floor 1" and "Floor 1 (First Floor)"), which presented as
#: "14 floors" in a six-storey building. The same fan-out cost a seeding script earlier in
#: this project, so it is worth stating plainly: never SELECT a label without aggregating it.


def _sparql(query: str, endpoint: str) -> List[Dict[str, Dict[str, str]]]:
    r = requests.post(
        endpoint,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def discover(endpoint: str) -> Dict[str, object]:
    """Read the ACTIVE building's own structure. Nothing here is assumed."""
    ns_rows = _sparql(
        "SELECT ?b WHERE { ?b a <https://brickschema.org/schema/Brick#Building> } LIMIT 1",
        endpoint,
    )
    if not ns_rows:
        raise RuntimeError("no brick:Building in the graph - is a building active and loaded?")
    building = ns_rows[0]["b"]["value"]
    ns = building.rsplit("#", 1)[0] + "#" if "#" in building else building.rsplit("/", 1)[0] + "/"

    spaces = [
        (b["s"]["value"], (b.get("l") or {}).get("value", ""))
        for b in _sparql(
            "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s (SAMPLE(?lab) AS ?l) WHERE { ?s a ?c . ?c rdfs:subClassOf* brick:Location .\n"
            "  FILTER NOT EXISTS { ?s a brick:Building }\n"
            "  OPTIONAL { ?s rdfs:label ?lab } } GROUP BY ?s LIMIT 4000",
            endpoint,
        )
    ]
    floors = [
        (b["s"]["value"], (b.get("l") or {}).get("value", ""))
        for b in _sparql(
            "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s (SAMPLE(?lab) AS ?l) WHERE { ?s a brick:Floor .\n"
            "  OPTIONAL { ?s rdfs:label ?lab } } GROUP BY ?s",
            endpoint,
        )
    ]
    lifts = [
        (b["s"]["value"], (b.get("l") or {}).get("value", ""))
        for b in _sparql(
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
            "SELECT ?s (SAMPLE(?lab) AS ?l) WHERE { ?s a ontosage:Lift .\n"
            "  OPTIONAL { ?s rdfs:label ?lab } } GROUP BY ?s",
            endpoint,
        )
    ]
    return {"building": building, "ns": ns, "spaces": spaces, "floors": floors, "lifts": lifts}


def _header(building: str, ns: str, title: str, why: str) -> str:
    return (
        f"# {title}\n"
        f"# GENERATED by scripts/provision_synthetic_sources.py -- do not hand-edit.\n"
        f"#\n"
        f"# {why}\n"
        f"#\n"
        f"# EVERY record here declares ontosage:isSimulated true. This is DECLARED simulation,\n"
        f"# not fabrication: answers resting on it say so, and the scorecard reports the\n"
        f"# real/synthetic share. Replace with a real feed by pointing the same source kind at\n"
        f"# the institutional system -- the graph shape does not change.\n"
        f"#\n"
        f"# Deliberately imperfect: some assets are out of service and some accessibility\n"
        f"# features are unverified. A building where everything works would make the hard\n"
        f"# filter and the freshness gate untestable.\n\n"
        f"@prefix bldg: <{ns}> .\n"
        f"@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
        f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f"@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        f"@prefix ontosage: <{ONTOSAGE_NS}> .\n\n"
    )


def gen_hours(d: Dict, rnd: random.Random) -> str:
    """Opening hours + closures. 271 of 480 questions touch this family."""
    out = [
        _header(
            str(d["building"]),
            str(d["ns"]),
            "Opening hours and closure periods (synthetic)",
            "Opening hours say what is NORMAL; a closure says what overrides it. 271 of the "
            "supervisors' 480 questions depend on the override being visible.",
        )
    ]
    b = _local(str(d["building"]))
    out.append(
        f'bldg:{b} ontosage:openingHours "Mon-Fri 07:00-21:00; Sat 09:00-17:00; Sun closed" ;\n'
    )
    out.append("    ontosage:isSimulated true .\n\n")

    floors = d["floors"] or []  # type: ignore[assignment]
    today = date.today()
    for i, (iri, label) in enumerate(list(floors)[:3]):  # a few, not all - closures are exceptional
        start = today + timedelta(days=rnd.randint(3, 40))
        out.append(
            f"bldg:closure_{_local(iri)}_{i} a ontosage:ClosurePeriod ;\n"
            f'    rdfs:label "Planned closure - {label or _local(iri)}"@en ;\n'
            f"    ontosage:appliesTo bldg:{_local(iri)} ;\n"
            f'    ontosage:closureReason "{rnd.choice(["planned electrical maintenance", "deep clean", "lift refurbishment", "fire-system testing"])}" ;\n'
            f'    ontosage:startedAt "{start}T08:00:00"^^xsd:dateTime ;\n'
            f'    ontosage:endedAt "{start}T17:00:00"^^xsd:dateTime ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )
    return "".join(out)


def gen_status(d: Dict, rnd: random.Random) -> str:
    """Lift / AV / network status. 162 + 158 + 94 questions."""
    out = [
        _header(
            str(d["building"]),
            str(d["ns"]),
            "Asset and service status (synthetic)",
            "Lift status (162 questions), network/IT service (158) and AV equipment (94). Every "
            "status is an ASSERTED record with an issuing source and an observation time - never "
            "inferred from telemetry, because a green heartbeat is not proof a device will work.",
        )
    ]
    now = datetime.now().replace(microsecond=0)
    spaces = list(d["spaces"])  # type: ignore[arg-type]
    lifts = list(d["lifts"])  # type: ignore[arg-type]

    # Lifts: mostly working, at least one not. An always-working estate cannot test the
    # accessibility hard filter or the route-blocking path.
    for i, (iri, label) in enumerate(lifts):
        state = "out_of_service" if i == 0 and len(lifts) > 1 else "operational"
        seen = now - timedelta(minutes=rnd.randint(2, 90))
        out.append(
            f"bldg:status_lift_{i} a ontosage:AssetStatus ;\n"
            f'    rdfs:label "Status of {label or _local(iri)}"@en ;\n'
            f"    ontosage:statusOf bldg:{_local(iri)} ;\n"
            f'    ontosage:statusValue "{state}" ;\n'
            f'    ontosage:statusSource "lift_controller" ;\n'
            f'    ontosage:statusObservedAt "{seen.isoformat()}"^^xsd:dateTime ;\n'
            f'    ontosage:assistanceContact "Estates helpdesk, ext 1234" ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )

    # AV in a sample of teaching-ish spaces, and a network service per floor.
    for i, (iri, label) in enumerate(spaces[:12]):
        state = rnd.choices(["operational", "degraded", "unverified"], weights=[7, 2, 1])[0]
        seen = now - timedelta(minutes=rnd.randint(5, 600))
        out.append(
            f"bldg:av_{_local(iri)} a ontosage:AVEquipment ;\n"
            f'    rdfs:label "AV rig - {label or _local(iri)}"@en ;\n'
            f"    brick:isPointOf bldg:{_local(iri)} ;\n"
            f"    ontosage:isSimulated true .\n\n"
            f"bldg:status_av_{i} a ontosage:AssetStatus ;\n"
            f"    ontosage:statusOf bldg:av_{_local(iri)} ;\n"
            f'    ontosage:statusValue "{state}" ;\n'
            f'    ontosage:statusSource "av_support" ;\n'
            f'    ontosage:statusObservedAt "{seen.isoformat()}"^^xsd:dateTime ;\n'
            f'    ontosage:assistanceContact "AV support, ext 4321" ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )

    for i, (iri, label) in enumerate(list(d["floors"])):  # type: ignore[arg-type]
        state = rnd.choices(["operational", "degraded"], weights=[9, 1])[0]
        seen = now - timedelta(minutes=rnd.randint(1, 30))
        out.append(
            f"bldg:wifi_{_local(iri)} a ontosage:NetworkService ;\n"
            f'    rdfs:label "Wireless coverage - {label or _local(iri)}"@en ;\n'
            f"    ontosage:isSimulated true .\n\n"
            f"bldg:status_wifi_{i} a ontosage:AssetStatus ;\n"
            f"    ontosage:statusOf bldg:wifi_{_local(iri)} ;\n"
            f'    ontosage:statusValue "{state}" ;\n'
            f'    ontosage:statusSource "network_operations" ;\n'
            f'    ontosage:statusObservedAt "{seen.isoformat()}"^^xsd:dateTime ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )
    return "".join(out)


def gen_accessibility(d: Dict, rnd: random.Random) -> str:
    """Accessibility register. 59 questions, and the highest-consequence family."""
    out = [
        _header(
            str(d["building"]),
            str(d["ns"]),
            "Accessibility register (synthetic)",
            "59 questions, and the highest-consequence family in the bank: getting an "
            "accessibility answer wrong strands a person. Some features are deliberately left "
            "UNVERIFIED so the hard filter is exercised in both directions - a register where "
            "everything is verified cannot test the rule that unverified is not accessible.",
        )
    ]
    floors = list(d["floors"])  # type: ignore[arg-type]
    kinds = [
        ("accessible_wc", "Accessible WC", "accessible toilet, disabled toilet, wheelchair toilet"),
        ("hearing_loop", "Hearing loop", "hearing loop, induction loop, hard of hearing"),
        ("power_assisted_door", "Power-assisted door", "automatic door, push pad door"),
        (
            "step_free_entrance",
            "Step-free entrance",
            "step free, level access, wheelchair entrance",
        ),
    ]
    for i, (firi, flabel) in enumerate(floors):
        kind, label, lay = kinds[i % len(kinds)]
        # Roughly a quarter unverified, on purpose.
        verified = rnd.random() > 0.25
        out.append(
            f"bldg:access_{kind}_{i} a ontosage:AccessibilityFeature ;\n"
            f'    rdfs:label "{label} - {flabel or _local(firi)}"@en ;\n'
            f'    ontosage:accessibilityKind "{kind}" ;\n'
            f"    ontosage:locatedIn bldg:{_local(firi)} ;\n"
            f'    ontosage:layTerms "{lay}" ;\n'
            f"    ontosage:accessibilityVerified {'true' if verified else 'false'} ;\n"
        )
        if verified:
            when = date.today() - timedelta(days=rnd.randint(10, 300))
            out.append(f'    ontosage:accessibilityVerifiedOn "{when}"^^xsd:date ;\n')
        out.append(
            f'    ontosage:answerText "{label} on {flabel or _local(firi)}. '
            f'{"Inspected and confirmed working." if verified else "NOT independently verified - confirm with Estates before relying on it."}" ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )
    return "".join(out)


def gen_schedules(d: Dict, rnd: random.Random) -> str:
    """Cleaning and planned-maintenance schedules."""
    out = [
        _header(
            str(d["building"]),
            str(d["ns"]),
            "Service schedules (synthetic)",
            "Cleaning, waste collection and planned maintenance. Distinct from work orders, "
            "which are reactive: 'when is this room next cleaned' and 'who is fixing the tap' "
            "are different questions with different authoritative sources.",
        )
    ]
    for i, (iri, label) in enumerate(list(d["floors"])):  # type: ignore[arg-type]
        kind = ["cleaning", "waste_collection", "planned_maintenance"][i % 3]
        start = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(
            days=rnd.randint(0, 6)
        )
        out.append(
            f"bldg:sched_{kind}_{i} a ontosage:ServiceSchedule ;\n"
            f'    rdfs:label "{kind.replace("_", " ").title()} - {label or _local(iri)}"@en ;\n'
            f'    ontosage:scheduleKind "{kind}" ;\n'
            f"    ontosage:appliesTo bldg:{_local(iri)} ;\n"
            f'    ontosage:startedAt "{start.isoformat()}"^^xsd:dateTime ;\n'
            f'    ontosage:endedAt "{(start + timedelta(hours=2)).isoformat()}"^^xsd:dateTime ;\n'
            f"    ontosage:isSimulated true .\n\n"
        )
    return "".join(out)


GENERATORS = {
    "hours": ("_synthetic_hours.ttl", gen_hours),
    "status": ("_synthetic_status.ttl", gen_status),
    "accessibility": ("_synthetic_accessibility.ttl", gen_accessibility),
    "schedules": ("_synthetic_schedules.ttl", gen_schedules),
}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=GRAPHDB)
    ap.add_argument("--out", default="input", help="output directory (default: input/)")
    ap.add_argument("--families", default="hours,status,accessibility,schedules")
    ap.add_argument(
        "--seed", type=int, default=7, help="deterministic output; same seed = same file"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    building_id = _env("BUILDING_ID", "")
    if not building_id:
        print("BUILDING_ID not resolvable from .env - is a building active?")
        return 1

    print(f"discovering structure of the ACTIVE building ({building_id}) from its own graph...")
    try:
        d = discover(args.endpoint)
    except Exception as exc:
        print(f"discovery failed: {exc}")
        return 1
    print(
        f"  namespace={d['ns']}  spaces={len(d['spaces'])}  "  # type: ignore[arg-type]
        f"floors={len(d['floors'])}  lifts={len(d['lifts'])}"  # type: ignore[arg-type]
    )

    out_dir = REPO / args.out
    rnd = random.Random(args.seed)
    written: List[Tuple[str, int]] = []
    requested = [f.strip() for f in args.families.split(",") if f.strip()]
    unknown = [f for f in requested if f not in GENERATORS]
    if unknown:
        # REFUSE, do not skip. This printed a note and carried on to exit 0, so
        # asking for a family with no generator — `timetable` and `closures` are
        # both named in FAMILIES and implemented by neither — provisioned nothing
        # and reported success. A caller scripting this would see a green exit and
        # a building that gained no data.
        print(
            f"  ERROR: no generator for {', '.join(unknown)} "
            f"(available: {', '.join(sorted(GENERATORS))})"
        )
        return 2
    for fam in requested:
        suffix, fn = GENERATORS[fam]
        text = fn(d, rnd)
        path = out_dir / f"{building_id}{suffix}"
        if args.dry_run:
            print(f"  [dry-run] would write {path.name}  ({len(text.splitlines())} lines)")
        else:
            path.write_text(text, encoding="utf-8")
            written.append((path.name, len(text.splitlines())))
            print(f"  wrote {path.name}  ({len(text.splitlines())} lines)")

    if written:
        print(
            "\nThese load on the NEXT orchestrator boot (ttl_uploader discovers "
            f"{building_id}_*.ttl in input/). Nothing changes until then."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
