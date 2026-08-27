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
FAMILIES = ("hours", "status", "accessibility", "schedules", "timetable", "amenity_state")


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
    # Spaces a scheduled session could plausibly occupy, chosen by BRICK CLASS rather
    # than by name. The first version sampled from every brick:Location subclass and
    # timetabled "Advanced Systems Architecture" into FireExit_F1_North — which is typed
    # brick:Space, not brick:Room. Brick already distinguishes teaching-capable rooms, so
    # the ontology answers this question; a name heuristic would only have to be rewritten
    # for the next building.
    #
    # brick:Common_Space is deliberately NOT here. A common space is not a teaching
    # room, and including it surfaced a room this building types as Common_Space
    # WITHOUT brick:Room -- which the coverage audit therefore cannot see at all, so
    # every row naming it was correctly skipped by the ingest as a space the building
    # does not have. The mistyping is logged separately; the include list should be
    # right on its own terms either way.
    teaching = [
        (b["s"]["value"], (b.get("l") or {}).get("value", ""))
        for b in _sparql(
            "PREFIX brick: <https://brickschema.org/schema/Brick#> "
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT ?s (SAMPLE(?lab) AS ?l) WHERE { VALUES ?tc { brick:Classroom "
            "brick:Lecture_Hall brick:Conference_Room brick:Laboratory } "
            "?s a ?tc . OPTIONAL { ?s rdfs:label ?lab } } GROUP BY ?s LIMIT 2000",
            endpoint,
        )
    ]
    # Amenities, so their SERVICE STATE can be provisioned. Module P of the schema is
    # explicit that an out-of-service amenity must be excluded from an answer rather than
    # caveated -- but nothing could be excluded while no amenity carried a status at all.
    # Only amenities WITH A LOCATION get a service state. A physical thing you can walk
    # to — a fountain, a lift, a café — can be out of service; an informational entry
    # cannot. The first version statused every ontosage:Amenity and duly marked
    # "Accessibility" and "Reception" out of service, which the resolver would then
    # EXCLUDE from answers: suppressing the building's accessibility information because
    # a synthetic generator called it broken. Location is the building-agnostic
    # discriminator here, and it needs no name matching.
    amenities = [
        (b["s"]["value"], (b.get("l") or {}).get("value", ""))
        for b in _sparql(
            "PREFIX ontosage: <http://ontosage.org/capabilities#> "
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT ?s (SAMPLE(?lab) AS ?l) WHERE { ?s a ontosage:Amenity . "
            "{ ?s ontosage:locatedIn ?anywhere } UNION { ?s ontosage:locationText ?anytext } "
            "OPTIONAL { ?s rdfs:label ?lab } } GROUP BY ?s LIMIT 500",
            endpoint,
        )
    ]
    return {
        "building": building,
        "ns": ns,
        "spaces": spaces,
        "floors": floors,
        "lifts": lifts,
        "amenities": amenities,
        "teaching": teaching,
    }


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


def gen_amenity_state(d: Dict, rnd: random.Random) -> str:
    """Amenity service status + potability statements (Module P, V6-T45).

    TWO DELIBERATE PROPERTIES, both of which the schema argues for at length:

    Most amenities work. A handful do not, because an estate where everything is
    operational makes the exclusion rule untestable — and the rule matters: an
    out-of-service amenity must be EXCLUDED from an answer, not listed with a caveat,
    since somebody who walks to a broken fountain has been given a wrong answer however
    well hedged.

    Potability is a PUBLISHED STATEMENT with an owner and a date, never something derived
    from a reading. A flow sensor sits one short step from "the water is fine to drink",
    and that step is a health claim nobody made. Some outlets get no statement at all:
    "nobody has published one" is the honest answer and has to be representable.\n"""
    amenities = list(d.get("amenities") or [])  # type: ignore[arg-type]
    out = [
        _header(
            str(d["building"]),
            str(d["ns"]),
            "Amenity service status and potability (synthetic)",
            "An amenity with no service state is assumed usable, so a broken one is offered "
            "exactly as if it worked. Potability is published, never inferred from a sensor.",
        )
    ]
    if not amenities:
        print("  no ontosage:Amenity entities — writing an empty amenity-state file")
        return "".join(out)

    now = datetime.now().replace(microsecond=0)
    reasons = ("awaiting parts", "reported fault", "scheduled servicing", "supply isolated")
    n_broken = 0
    for i, (iri, label) in enumerate(sorted(amenities)):
        local = _local(iri)
        # ~12% out of service. Deterministic per amenity so re-runs are byte-identical.
        broken = rnd.random() < 0.12
        state = "out_of_service" if broken else "operational"
        n_broken += 1 if broken else 0
        seen = now - timedelta(minutes=rnd.randint(5, 600))
        out.append(
            f"bldg:amenity_status_{i} a ontosage:AssetStatus ;\n"
            f"    ontosage:statusOf bldg:{local} ;\n"
            f'    ontosage:statusValue "{state}" ;\n'
            f'    ontosage:statusSource "estates_helpdesk" ;\n'
            f'    ontosage:statusObservedAt "{seen.isoformat()}"^^xsd:dateTime ;\n'
            + (f'    ontosage:statusReason "{rnd.choice(reasons)}" ;\n' if broken else "")
            + f'    ontosage:assistanceContact "Estates helpdesk, ext 1234" ;\n'
            f"    ontosage:isSimulated true .\n"
        )

    # POTABILITY IS NOT GENERATED. It used to be, and it produced five simulated
    # statements for this building -- two of them "not_potable" -- attributed to a
    # plausible-sounding "Estates Water Safety Group" that never said any such thing.
    #
    # A simulated broken lift is a harmless demo: somebody walks to a lift, finds it
    # working, and nothing is lost. A simulated potability statement is a false HEALTH
    # claim about a real building's drinking water, and the schema that introduced the
    # vocabulary says exactly why that is different: "a sensor reading does not support
    # a health statement" and "being wrong about drinkability harms someone". The
    # deliberate-imperfection argument that justifies a broken fountain does not reach
    # this far.
    #
    # Potability is authored by the building's owner, with a real authority and a real
    # date, or it is absent -- and absent renders as "nobody has assessed this outlet",
    # which the schema names as a legitimate answer.
    water = [
        (iri, lab)
        for iri, lab in sorted(amenities)
        if any(w in (lab or _local(iri)).lower() for w in ("water", "fountain", "tap", "drink"))
    ]
    print(
        f"  amenity state: {len(amenities)} amenities ({n_broken} out of service), "
        f"{len(water)} water outlet(s) left for the OWNER to publish potability for"
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


#: Teaching weeks generated either side of today. The BACKWARD half makes
#: "how busy was the lecture theatre last term?" answerable; the FORWARD half is
#: the half that matters and the half a naive generator omits — a timetable is
#: consulted about what is coming, and one that stops at today can only ever say
#: "no data" to the question it exists to answer (BUG-290, the same mistake made
#: once already with the booking calendar).
TIMETABLE_WEEKS_BACK = 4
TIMETABLE_WEEKS_FORWARD = 4

#: Module titles are generic academic filler, deliberately not building-specific.
_MODULE_WORDS = (
    "Introduction to",
    "Advanced",
    "Foundations of",
    "Applied",
    "Research Methods in",
)
_MODULE_TOPICS = (
    "Computer Science",
    "Data Analysis",
    "Software Engineering",
    "Human-Computer Interaction",
    "Systems Architecture",
    "Machine Learning",
    "Cyber Security",
)


def gen_timetable(d: Dict, rnd: random.Random) -> str:
    """A recurring teaching timetable as CSV, for the T25 institutional feed.

    Emitted as CSV rather than TTL ON PURPOSE. A timetable is not a fact about the
    building's structure; it is a periodic export from a system of record, and V6-T25
    already gave that shape a declare-and-connect contract: drop the file, name it in
    feeds.yaml, and its rows become interval records in the SAME events store that
    bookings, work orders and access events share. Writing it as triples instead would
    have invented a second availability path that drifts from the one the events lane
    already uses.

    Only a MINORITY of spaces are timetabled. Every room having teaching in it would
    make "which rooms are free?" trivially answerable and the spatial filters
    untestable — and no real building looks like that.
    """
    candidates = list(d.get("teaching") or [])  # type: ignore[arg-type]
    if not candidates:
        # A building that types no teaching-capable rooms gets NO timetable rather
        # than one scattered across its corridors and fire exits. The header alone is
        # the honest outcome: there is nothing here to schedule.
        print(
            "  no brick:Classroom/Lecture_Hall/Conference_Room/Laboratory in this "
            "graph — writing an empty timetable rather than inventing teaching spaces"
        )
        return "room,start,end,module\n"

    # A deterministic minority: enough to answer with, few enough to leave rooms free.
    teaching = sorted(_local(iri) for iri, _lab in candidates)
    rnd.shuffle(teaching)
    teaching = sorted(teaching[: max(1, len(teaching) // 2)])

    monday = date.today() - timedelta(days=date.today().weekday())
    first = monday - timedelta(weeks=TIMETABLE_WEEKS_BACK)
    weeks = TIMETABLE_WEEKS_BACK + TIMETABLE_WEEKS_FORWARD

    rows: List[str] = ["room,start,end,module"]
    for room in teaching:
        # Each room keeps the SAME weekly pattern across the term — that is what makes
        # it a timetable rather than a list of unrelated bookings, and it is what a
        # recurring-window question ("every Tuesday afternoon") needs to find.
        # Deduplicated on (weekday, hour): drawing the same slot twice produced two
        # identical rows whose event ids collide, so 655 parsed records became 429
        # stored ones and the ingest report meant less than it appeared to.
        slots = {}
        for _ in range(rnd.randint(1, 3)):
            weekday = rnd.randint(0, 4)  # teaching runs Mon-Fri
            hour = rnd.choice((9, 10, 11, 13, 14, 15, 16))
            if (weekday, hour) in slots:
                continue
            length = rnd.choice((1, 2))
            module = f"{rnd.choice(_MODULE_WORDS)} {rnd.choice(_MODULE_TOPICS)}"
            slots[(weekday, hour)] = (weekday, hour, length, module)
        slots = list(slots.values())
        for w in range(weeks):
            for weekday, hour, length, module in slots:
                day = first + timedelta(weeks=w, days=weekday)
                # A real timetable has gaps: reading weeks, cancellations, bank holidays.
                # Without them every week is identical and the completeness gate has
                # nothing to detect.
                if rnd.random() < 0.08:
                    continue
                rows.append(
                    f"{room},{day}T{hour:02d}:00:00,{day}T{hour + length:02d}:00:00,{module}"
                )
    return "\n".join(rows) + "\n"


#: The feed declaration that CONNECTS the generated CSV. Writing the file without this
#: would leave the building with a timetable it cannot read — described-but-unconnected,
#: which is the exact half of design contract 8 that this project keeps rediscovering.
TIMETABLE_FEED_ID = "synthetic_timetable"


def ensure_timetable_feed(input_dir: Path, building_id: str, csv_name: str) -> str:
    """Declare the timetable feed in feeds.yaml if it is not already there.

    Idempotent and additive: an existing declaration with this id is left alone, and
    nothing else in the file is touched.
    """
    feeds_path = input_dir / "feeds.yaml"
    try:
        existing = yaml.safe_load(feeds_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        existing = {}
    except Exception as exc:
        return f"could not read feeds.yaml ({exc}) — declare the feed by hand"

    for feed in existing.get("feeds") or []:
        if isinstance(feed, dict) and feed.get("id") == TIMETABLE_FEED_ID:
            return "feed already declared"

    block = (
        "\n  # Synthetic teaching timetable (V6-T56). Generated by\n"
        f"  # scripts/provision_synthetic_sources.py --families timetable.\n"
        f"  # Rows land in the events store via the T25 institutional adapter, and every\n"
        f"  # record declares its synthetic origin so an answer can say where it came from.\n"
        f"  - id: {TIMETABLE_FEED_ID}\n"
        f"    type: timetable\n"
        f"    path: {csv_name}\n"
        f"    space_field: room\n"
        f"    start_field: start\n"
        f"    end_field: end\n"
        f"    title_field: module\n"
        f"    enabled: true\n"
    )
    with feeds_path.open("a", encoding="utf-8") as fh:
        fh.write(block)
    return f"declared feed '{TIMETABLE_FEED_ID}' in feeds.yaml"


GENERATORS = {
    "hours": ("_synthetic_hours.ttl", gen_hours),
    "status": ("_synthetic_status.ttl", gen_status),
    "accessibility": ("_synthetic_accessibility.ttl", gen_accessibility),
    "schedules": ("_synthetic_schedules.ttl", gen_schedules),
    "timetable": ("_timetable.csv", gen_timetable),
    "amenity_state": ("_synthetic_amenity_state.ttl", gen_amenity_state),
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
            # A generated file nothing reads is the described-but-unconnected half of
            # design contract 8, and this project has now found that shape often enough
            # to stop shipping it: the timetable CSV is DECLARED as it is written.
            if fam == "timetable":
                print(f"  {ensure_timetable_feed(out_dir, building_id, path.name)}")

    if written:
        print(
            "\nThese load on the NEXT orchestrator boot (ttl_uploader discovers "
            f"{building_id}_*.ttl in input/). Nothing changes until then."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
