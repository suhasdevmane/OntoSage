#!/usr/bin/env python
"""Author the context data a building needs to answer beyond raw readings.

**Why this exists.** Several capabilities were built and verified on bldg1 and have
no data at all on the other buildings, so any portability claim about them is
untested. Measured 2026-08-27:

    knowledge topics   bldg1 45   bldg2 10   bldg3  9
    AssetStatus         bldg1 64   bldg2  0   bldg3  0
    PotabilityStatement bldg1  1   bldg2  0   bldg3  0

The out-of-service exclusion, the drinkability claim and the asset-state lane
therefore cannot be exercised on bldg2 or bldg3 at all. That is not a portability
result; it is an absence of one.

**Discovered, never assumed.** Namespace, floors, rooms and existing amenities all
come from the building's OWN TTLs. bldg1 names floors ``Floor0`` and rooms
``Room5.01``; bldg2 and bldg3 use ``floor0`` and ``RM001A_room``. A generator that
hardcoded either shape would prove nothing about building-agnosticism — it would
only prove it had been told the answer.

**Different, not copied.** Each building gets its own operator, contacts, hours and
topic mix from a profile. Cloning bldg1's content into bldg2 would make the two
answer identically for the wrong reason, and a portability test that passes because
the fixtures are the same file tests nothing.

**It refuses to make a health claim about a real building.** Potability is authored
only where ``building.yaml`` declares ``provenance.nature: synthetic``. bldg1 is a
real building, and five simulated drinkability statements about one had to be
removed from this repository once already.

Run:
  python scripts/generate_building_context.py --building-id bldg2
  python scripts/generate_building_context.py --building-id bldg3 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]

#: Per-building flavour. Fictional throughout, and deliberately DIFFERENT between
#: buildings: same-shaped data with different content is what makes a portability
#: pass meaningful rather than a tautology. A building with no profile here still
#: works — it gets a neutral one derived from its own building.yaml.
PROFILES: Dict[str, Dict[str, Any]] = {
    "bldg2": {
        "operator": "Wellman Estates Office",
        "email": "estates@wellman.example.org",
        "phone": "+1 555 0147",
        "hours": "06:30-20:00 Monday to Friday, 09:00-13:00 Saturday",
        "helpdesk": "Wellman facilities desk",
        "topics": [
            (
                "Wifi",
                "wifi, wi-fi, wireless, internet, network, guest network",
                "The building runs a campus wireless network; visitors use the guest SSID at reception.",
            ),
            (
                "Parking",
                "parking, car park, where do i park, visitor parking, permit",
                "Staff parking is by permit in the north lot; visitor bays are signposted from the main entrance.",
            ),
            (
                "Recycling",
                "recycling, bins, waste, rubbish, where do i put",
                "Mixed recycling and landfill bins sit on every floor by the stair core; glass goes to the loading bay.",
            ),
            (
                "Deliveries",
                "delivery, parcel, courier, goods in, post",
                "Deliveries are received at the loading bay and held at the estates office for collection.",
            ),
            (
                "Bookings",
                "book a room, reserve, meeting room booking, how do i book",
                "Rooms are booked through the campus booking system; the estates office can help with recurring bookings.",
            ),
        ],
    },
    "bldg3": {
        "operator": "BuildSys Site Management",
        "email": "site@buildsys.example.org",
        "phone": "+44 20 7946 0812",
        "hours": "07:00-19:00 weekdays, closed weekends and public holidays",
        "helpdesk": "BuildSys site office",
        "topics": [
            (
                "AccessCards",
                "access card, badge, door won't open, card not working, entry",
                "Access cards are issued by the site office; a card that stops working is usually re-enabled the same day.",
            ),
            (
                "FireProcedure",
                "fire, alarm, evacuate, evacuation, assembly point, drill",
                "On the alarm, leave by the nearest exit and assemble in the courtyard. Drills are quarterly.",
            ),
            (
                "Cycling",
                "bike, bicycle, cycle storage, where do i leave my bike, showers",
                "Covered cycle racks are at the rear entrance, with showers and lockers on the ground floor.",
            ),
            (
                "Cleaning",
                "cleaning, cleaner, spill, my office is dirty, bins not emptied",
                "Offices are cleaned overnight on weekdays. Spills and one-off issues go to the site office.",
            ),
            (
                "Catering",
                "coffee, food, canteen, vending, where can i eat, lunch",
                "There is no canteen on site; vending is on the ground floor and the nearest cafe is a short walk.",
            ),
            (
                "QuietSpace",
                "quiet, quiet room, focus, prayer room, contemplation",
                "A bookable quiet room is available on the top floor for focused work and contemplation.",
            ),
        ],
    },
    "bldg4": {
        "operator": "Northgate Building Services",
        "email": "services@northgate.example.org",
        "phone": "+44 20 7946 0999",
        "hours": "07:00-19:00 weekdays, closed at weekends",
        "helpdesk": "Northgate services desk",
        "topics": [
            (
                "Wifi",
                "wifi, wi-fi, wireless, internet, network access",
                "The building has a single wireless network; the services desk issues guest access.",
            ),
            (
                "LostProperty",
                "lost, found, lost property, i left, missing",
                "Lost property is held at the services desk for thirty days.",
            ),
        ],
    },
}

#: Which amenity kinds may carry a service state, and the plausible reasons. A
#: reason matters: "out of service" with no cause is unactionable, and this data
#: exists to exercise a lane that is supposed to tell someone something useful.
_OUT_OF_SERVICE_REASONS = (
    "awaiting a replacement part",
    "reported faulty and booked for repair",
    "isolated during adjacent works",
)


def _stable(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:4], "big")


def building_dir(building_id: str) -> Optional[Path]:
    active = REPO / "input"
    if (active / "building.yaml").is_file():
        try:
            if building_id in (active / "building.yaml").read_text(encoding="utf-8"):
                return active
        except OSError:  # pragma: no cover
            pass
    parked = REPO / building_id
    return parked if parked.is_dir() else None


def discover(bdir: Path, exclude: Optional[str] = None) -> Dict[str, Any]:
    """Namespace, floors, rooms and amenities, from the building's own files.

    ``exclude`` skips the file this run is about to overwrite. Without it the
    generator reads its OWN previous output as "the building already answers
    that" and a re-run skips everything it wrote last time -- which looked
    exactly like a building that was already complete.
    """
    import rdflib

    brick = rdflib.Namespace("https://brickschema.org/schema/Brick#")
    onto = rdflib.Namespace("http://ontosage.org/capabilities#")

    ns = ""
    g = rdflib.Graph()
    for f in sorted(bdir.glob("*.ttl")):
        if f.name.lower().startswith("brick") or (exclude and f.name == exclude):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if not ns:
            m = re.search(r"@prefix\s+bldg:\s*<([^>]+)>", text)
            if m:
                ns = m.group(1)
        try:
            g.parse(str(f), format="turtle")
        except Exception:
            continue
    if not ns:
        raise SystemExit(f"no bldg: prefix found in {bdir}")

    def locals_of(cls) -> List[str]:
        return sorted(
            {str(s)[len(ns) :] for s in g.subjects(rdflib.RDF.type, cls) if str(s).startswith(ns)}
        )

    amenities = []
    for s in g.subjects(rdflib.RDF.type, onto.Amenity):
        if not str(s).startswith(ns):
            continue
        label = g.value(s, rdflib.RDFS.label)
        floor = g.value(s, onto.onFloor)
        # Locatable means LOCATED, not specifically floor-tagged. Only 9 of bldg2's
        # 22 amenities carry ontosage:onFloor, but many more name a room through
        # ontosage:locatedIn -- and an amenity in a named room can be walked to.
        # Testing for the floor string alone would have called two thirds of a
        # building's amenities unlocatable.
        located_in = g.value(s, onto.locatedIn)
        amenities.append(
            {
                "local": str(s)[len(ns) :],
                "label": str(label or ""),
                "floor": str(floor or ""),
                "space": str(located_in or "").rsplit("#", 1)[-1],
            }
        )
    # What the building ALREADY answers. Authoring a second fault-reporting topic
    # gave bldg2 two answers with different contacts -- "Estates helpdesk" and
    # "Wellman facilities desk" -- in one reply. Two contradictory routes to report
    # a fault is worse than one, and the second was mine.
    #
    # AMENITIES count too, and leaving them out was a second, worse version of the same
    # mistake. bldg3 declares bldg:Cap_cafe with lay terms "cafe, coffee, food, lunch,
    # canteen ...", and this scanned only KnowledgeTopic, so a Catering topic was
    # authored anyway -- asserting "There is no canteen on site" about a building whose
    # own graph declares a ground-floor cafe. Asked live, the cafe answered and the
    # authored text was simply false. A fixture generator that contradicts the
    # building's own data is fabrication, whatever it is labelled.
    existing_terms: List[str] = []
    for cls in (onto.KnowledgeTopic, onto.Amenity):
        for s_ in g.subjects(rdflib.RDF.type, cls):
            for term in g.objects(s_, onto.layTerms):
                existing_terms += [t.strip().lower() for t in str(term).split(",") if t.strip()]

    return {
        "namespace": ns,
        "floors": locals_of(brick.Floor),
        "rooms": locals_of(brick.Room),
        "amenities": sorted(amenities, key=lambda a: a["local"]),
        "existing_lay_terms": sorted(set(existing_terms)),
    }


def provenance_nature(bdir: Path) -> str:
    try:
        import yaml

        cfg = yaml.safe_load((bdir / "building.yaml").read_text(encoding="utf-8")) or {}
        return str((cfg.get("provenance") or {}).get("nature") or "").lower()
    except Exception:  # pragma: no cover
        return ""


def profile_for(building_id: str, bdir: Path) -> Dict[str, Any]:
    if building_id in PROFILES:
        return PROFILES[building_id]
    # A building with no profile still gets context, derived from its own identity.
    try:
        import yaml

        cfg = yaml.safe_load((bdir / "building.yaml").read_text(encoding="utf-8")) or {}
        name = str(cfg.get("building_name") or building_id)
    except Exception:  # pragma: no cover
        name = building_id
    return {
        "operator": f"{name} facilities",
        "email": f"facilities@{building_id}.example.org",
        "phone": "",
        "hours": "",
        "helpdesk": f"{name} facilities desk",
        "topics": [],
    }


def render(building_id: str, info: Dict[str, Any], prof: Dict[str, Any], nature: str) -> str:
    ns = info["namespace"]
    out: List[str] = [
        f"# Building context for {building_id}: knowledge topics, service state, drinkability.",
        "#",
        "# GENERATED by scripts/generate_building_context.py. Every subject declares",
        "# ontosage:isSimulated, because each of these is authored rather than measured.",
        "#",
        "# DISCOVERED, not assumed: the namespace, floors, rooms and amenities below were read",
        f"# from {building_id}'s own TTLs. This building names its floors {info['floors'][:2]}",
        "# and its rooms in its own style; nothing here was written against another building's",
        "# naming, which is the only way this demonstrates building-agnosticism rather than",
        "# demonstrating that someone was told the answer.",
        "#",
        "# The CONTENT differs from every other building's on purpose. Cloning one building's",
        "# topics into another would make them answer identically for the wrong reason, and a",
        "# portability test that passes because the fixtures are the same file tests nothing.",
        "",
        "@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        f"@prefix bldg:     <{ns}> .",
        "",
        "# ── knowledge topics ────────────────────────────────────────────────────────",
        "",
    ]

    covered = set(info.get("existing_lay_terms") or [])

    def _already_answered(lay: str) -> bool:
        """Does the building already answer this? Overlap on a DISTINCTIVE term.

        Compared on lay terms rather than topic names because the same question is
        named differently by different authors -- bldg2 called it "Reporting a
        fault" and so did the profile, but a building that called it "Maintenance
        requests" would still be answering the same question.
        """
        mine = {t.strip().lower() for t in lay.split(",") if len(t.strip()) > 4}
        return len(mine & covered) >= 2

    skipped: List[str] = []
    for name, lay, answer in prof.get("topics", []):
        if _already_answered(lay):
            skipped.append(name)
            continue
        out += [
            f"bldg:Topic_{name} a ontosage:KnowledgeTopic , ontosage:InformationTopic ;",
            f'    rdfs:label "{re.sub(r"(?<!^)(?=[A-Z])", " ", name)}"@en ;',
            '    ontosage:capabilityCategory "INFORMATION" ;',
            f'    ontosage:layTerms "{lay}" ;',
            f'    ontosage:answerText "{answer}" ;',
            f'    ontosage:contactEmail "{prof["email"]}" ;',
        ]
        if prof.get("phone"):
            out.append(f'    ontosage:contactPhone "{prof["phone"]}" ;')
        out += ['    ontosage:isSimulated "true"^^xsd:boolean .', ""]

    # A reporting route and an opening-hours topic every building should be able to
    # answer -- unless it already does.
    _report_lay = (
        "report a fault, something is broken, report a problem, maintenance, who do i tell"
    )
    if _already_answered(_report_lay):
        skipped.append("ReportFault")
    else:
        out += [
            "bldg:Topic_ReportFault a ontosage:KnowledgeTopic , ontosage:Procedure ;",
            '    rdfs:label "Reporting a fault"@en ;',
            '    ontosage:capabilityCategory "PROCEDURE" ;',
            '    ontosage:layTerms "report a fault, something is broken, report a problem, '
            'maintenance, who do i tell" ;',
            f'    ontosage:answerText "Faults go to the {prof["helpdesk"]}." ;',
            f'    ontosage:reportTo "{prof["helpdesk"]}" ;',
            f'    ontosage:contactEmail "{prof["email"]}" ;',
            '    ontosage:steps "Note the room and floor; Say what is wrong; Send it to the '
            'desk" ;',
            '    ontosage:isSimulated "true"^^xsd:boolean .',
            "",
        ]
    if prof.get("hours"):
        out += [
            "bldg:Topic_OpeningHours a ontosage:KnowledgeTopic , ontosage:InformationTopic ;",
            '    rdfs:label "Opening hours"@en ;',
            '    ontosage:capabilityCategory "INFORMATION" ;',
            '    ontosage:layTerms "opening hours, when is the building open, access hours, '
            'closing time, is it open" ;',
            f'    ontosage:answerText "Open {prof["hours"]}." ;',
            '    ontosage:isSimulated "true"^^xsd:boolean .',
            "",
        ]

    # ── service state on a minority of amenities ─────────────────────────────
    # Most work. A building where everything is broken is as untestable as one
    # where nothing is: the exclusion rule only means something when SOME
    # amenities are excluded and the rest are still offered.
    # ── service state, DESIGNED rather than rolled ───────────────────────────
    # A flat probability produced one out-of-service amenity per building and never
    # a drinking-water point, so the "broken fountain is hidden" behaviour -- built
    # and verified on bldg1 -- could not be exercised on any other building. A
    # defect you cannot observe is not in the fixture.
    #
    # So the choice is deliberate: for every amenity KIND with two or more
    # instances, exactly one is out of service. That makes the exclusion visible
    # (one is withheld) while the question stays answerable (the others are not),
    # which is the case the exclusion rule was written for. Separately, ONE
    # single-instance kind is marked so the other branch -- everything that matched
    # is out of service, answer "the ones here are not working" rather than "there
    # are none" -- is exercised too.
    out += ["# ── amenity service state ───────────────────────────────────────────────────", ""]

    def _kind_of(a: Dict[str, Any]) -> str:
        # Amenity_DrinkingWater_floor0 -> DrinkingWater. Reads the building's own
        # naming rather than a fixed list of kinds.
        parts = a["local"].split("_")
        return parts[1] if len(parts) > 2 and parts[0].lower() == "amenity" else a["local"]

    locatable = [a for a in info["amenities"] if a["floor"] or a["space"]]
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for a in locatable:
        by_kind.setdefault(_kind_of(a), []).append(a)

    chosen: List[Dict[str, Any]] = []
    singles: List[Tuple[str, Dict[str, Any]]] = []
    for kind, members in sorted(by_kind.items()):
        members = sorted(members, key=lambda x: x["local"])
        if len(members) >= 2:
            chosen.append(members[_stable(building_id, "pick", kind) % len(members)])
        else:
            singles.append((kind, members[0]))
    if singles:
        kind, only = singles[_stable(building_id, "single") % len(singles)]
        chosen.append(only)

    broken = 0
    for a in sorted(chosen, key=lambda x: x["local"]):
        reason = _OUT_OF_SERVICE_REASONS[
            _stable(building_id, "reason", a["local"]) % len(_OUT_OF_SERVICE_REASONS)
        ]
        broken += 1
        out += [
            f"bldg:Status_{a['local']} a ontosage:AssetStatus ;",
            f"    ontosage:statusOf bldg:{a['local']} ;",
            '    ontosage:statusValue "out_of_service" ;',
            f'    ontosage:statusReason "{reason}" ;',
            f'    rdfs:label "Service state - {a["label"] or a["local"]}"@en ;',
            '    ontosage:isSimulated "true"^^xsd:boolean .',
            "",
        ]

    # ── potability, only where the building is fictional ─────────────────────
    water = [a for a in info["amenities"] if "drinkingwater" in a["local"].lower()]
    if water and nature == "synthetic":
        outlets = " ,\n        ".join(f"bldg:{a['local']}" for a in water)
        out += [
            "# ── drinkability ────────────────────────────────────────────────────────────",
            "#",
            "# Authored only because this building is FICTIONAL (building.yaml declares",
            "# provenance.nature: synthetic). A simulated drinkability claim about a real",
            "# building is a false health claim, and five of them had to be removed from this",
            "# repository once already.",
            "",
            "bldg:Potability_DrinkingWater a ontosage:PotabilityStatement ;",
            '    rdfs:label "Drinking water quality"@en ;',
            '    ontosage:layTerms "is the water safe to drink, can i drink the water, '
            'potable, drinkable, tap water safe, water quality" ;',
            '    ontosage:potabilityValue "potable" ;',
            f'    ontosage:potabilityAuthority "{prof["operator"]}" ;',
            '    ontosage:potabilityIssuedOn "2024-01-01"^^xsd:date ;',
            f"    ontosage:appliesToOutlet {outlets} ;",
            '    ontosage:isSimulated "true"^^xsd:boolean .',
            "",
        ]
    elif water:
        out += [
            "# No potability statement: this building is not declared synthetic, and a",
            f"# simulated drinkability claim about a real building is a false health claim",
            f"# (provenance.nature = {nature!r}).",
            "",
        ]
    return "\n".join(out), broken, skipped


#: Answers that mean "I could not answer", however politely phrased. A context topic
#: that lands on one of these is authored-but-unreachable, which is the failure this
#: probe exists for: the triples are in the graph and the question still gets nothing.
_REFUSALS = (
    "don't have",
    "do not have",
    "no information",
    "not available",
    "couldn't find",
    "could not find",
    "unable to",
    "no data",
    "i'm not able",
    "cannot answer",
    "couldn't generate a response",
)


#: Words too common to distinguish one authored answer from another building's prose.
_COMMON = {
    "about",
    "after",
    "always",
    "available",
    "before",
    "building",
    "during",
    "every",
    "floor",
    "floors",
    "found",
    "here",
    "information",
    "level",
    "other",
    "please",
    "should",
    "there",
    "these",
    "those",
    "through",
    "under",
    "where",
    "which",
    "while",
    "your",
}


def _carries(reply: str, expected: str, asked: str = "") -> bool:
    """Did the AUTHORED answer reach the user, or did another lane answer instead?

    The reply is LLM-framed, so an exact-substring test would fail on correct answers.
    This asks whether enough of the authored answer's DISTINCTIVE words survived --
    content words of five characters or more, minus ones common to any building's
    prose. A different lane's fluent answer shares the topic but not the wording.

    Deliberately lenient (a third of the distinctive words, minimum two): the cost of a
    false alarm here is chasing a non-defect, and the check that matters -- 'cleaning?'
    returning a service-schedule refusal while the authored Cleaning topic went unread --
    shares almost nothing with the authored text and is caught comfortably.
    """
    # Words from the QUESTION are not evidence: any on-topic reply echoes them, so a
    # refusal that names the subject ("no CLEANING schedules recorded") would otherwise
    # score as the authored answer arriving. Only the authored words the asker did not
    # supply can distinguish one lane's answer from another's.
    asked_words = set(re.findall(r"[a-z]{4,}", asked.lower()))
    words = {
        w
        for w in re.findall(r"[a-z]{5,}", expected.lower())
        if w not in _COMMON and not any(w.startswith(a[:5]) for a in asked_words if len(a) >= 5)
    }
    if len(words) < 2:
        return True  # nothing distinctive to look for; do not invent a failure
    low = reply.lower()
    hits = sum(1 for w in words if w in low)
    return hits >= max(2, len(words) // 3)


def probe(building_id: str, bdir: Path, base: str, timeout: float) -> int:
    """Ask the live building one question per authored lay term; report what answers.

    The generator is the only thing that knows which lay terms it authored, so it is
    the right thing to check them. Authoring and verifying split across two owners is
    how this project's recurring defect works -- a capability lands, is correct, is
    tested, and nothing ever calls it (lessons.md #87).
    """
    import importlib.util as _il
    import json as _json
    import re as _re
    import urllib.request as _rq

    # /chat is RBAC-gated; an unauthenticated probe returns 401 for every question,
    # which reads exactly like "the building answers nothing". Reuse the login the
    # other probes use rather than adding a fourth copy of it.
    repo = Path(__file__).resolve().parents[1]
    spec = _il.spec_from_file_location("_cap", str(repo / "scripts" / "capture_golden_baseline.py"))
    cap = _il.module_from_spec(spec)
    spec.loader.exec_module(cap)
    try:
        token = cap._login(base)
    except Exception as exc:  # pragma: no cover - live probe
        print(f"cannot authenticate against {base}: {exc}")
        return 1

    path = bdir / f"{building_id}_context.ttl"
    if not path.is_file():
        print(f"no {path.name} to probe -- generate it first")
        return 1
    text = path.read_text(encoding="utf-8")

    # One question per authored topic: its first lay term, which is the phrasing a
    # person actually types. Later terms are synonyms of the same thing.
    #
    # The topic's OWN answerText is carried alongside, because that -- not the absence
    # of a refusal phrase -- is what the probe should check. Measured on bldg3:
    # "cleaning?" returned "This building has no cleaning or service schedules recorded
    # in its model", a fluent honest no-data answer from a DIFFERENT lane, while the
    # authored Cleaning topic sat in the graph unread. Matching refusal phrases scored
    # that as a success. Asking "did the authored answer arrive?" cannot.
    questions: List[Tuple[str, str, str]] = []
    for block in _re.finditer(r'ontosage:layTerms\s+"([^"]+)"(.*?)(?:\n\n|\Z)', text, _re.DOTALL):
        first = block.group(1).split(",")[0].strip()
        if not first:
            continue
        m = _re.search(r'ontosage:answerText\s+"([^"]+)"', block.group(2))
        questions.append((first, f"{first}?", m.group(1) if m else ""))

    if not questions:
        print(f"{path.name} authors no lay terms")
        return 1

    import uuid as _uuid

    _run_id = _uuid.uuid4().hex[:8]
    print(f"probing {len(questions)} authored topic(s) on {building_id} via {base}\n")
    answered = 0
    misses: List[str] = []
    for i, (term, q, expected) in enumerate(questions):
        # A FRESH session per question, per run. The id used to be stable per lay term,
        # which meant every run replayed into the conversation that previous runs had
        # built -- and Redis keeps conversation state with no time-expiry by default.
        # Measured: "cleaning?" answered from the authored topic 4 times out of 4 in
        # fresh sessions, and returned the PREVIOUS run's superseded answer in the
        # probe's own reused session. The probe was reporting its own history as the
        # building's data, and reported a fix as still broken.
        body = _json.dumps({"message": q, "session_id": f"probe-{building_id}-{_run_id}-{i}"})
        req = _rq.Request(
            f"{base}/chat",
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with _rq.urlopen(req, timeout=timeout) as r:  # noqa: S310 - local only
                payload = _json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # pragma: no cover - live probe
            print(f"  ERROR  {term!r}: {exc}")
            continue
        reply = payload.get("response") or payload.get("data", {}).get("response") or ""
        low = reply.lower()
        if any(marker in low for marker in _REFUSALS):
            verdict = "REFUSED"
        elif expected and not _carries(reply, expected, term):
            # Fluent, on-topic, and not the authored fact. Another lane answered.
            verdict = "WRONG-LANE"
        else:
            verdict = "answered"
            answered += 1
        if verdict != "answered":
            misses.append(f"{term} [{verdict}]")
        print(f"  {verdict:11s} {term!r}")
        print(f"              {' '.join(reply.split())[:150]}")
    print(f"\n{answered}/{len(questions)} authored topics answer on {building_id}")
    if misses:
        print("not reaching the authored topic: " + "; ".join(misses))
    return 0 if answered == len(questions) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Author context data for a building.")
    ap.add_argument("--building-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--probe",
        action="store_true",
        help="ask the LIVE building one question per authored lay term instead of writing",
    )
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    if args.probe:
        d = building_dir(args.building_id)
        if d is None:
            print(f"No directory for {args.building_id}")
            return 1
        return probe(args.building_id, d, args.base.rstrip("/"), args.timeout)

    bdir = building_dir(args.building_id)
    if bdir is None:
        print(f"No directory for {args.building_id} (looked for input/ and {args.building_id}/)")
        return 1

    info = discover(bdir, exclude=f"{args.building_id}_context.ttl")
    prof = profile_for(args.building_id, bdir)
    nature = provenance_nature(bdir)
    ttl, broken, skipped = render(args.building_id, info, prof, nature)

    print(f"{args.building_id}: ns={info['namespace']}")
    print(
        f"  discovered {len(info['floors'])} floors, {len(info['rooms'])} rooms, "
        f"{len(info['amenities'])} amenities"
    )
    print(
        f"  authoring {len(prof.get('topics', []))} profile topic(s) + report route"
        f"{' + hours' if prof.get('hours') else ''}"
    )
    if skipped:
        # Said out loud. A topic silently omitted looks identical to a topic the
        # profile never had, and the reason matters: the building already answers it.
        print(f"  skipped {len(skipped)} topic(s) the building already answers: {skipped}")
    print(f"  {broken} amenity/amenities marked out of service")
    print(
        f"  potability: {'authored' if nature == 'synthetic' else f'REFUSED (nature={nature!r})'}"
    )

    out = bdir / f"{args.building_id}_context.ttl"
    if args.dry_run:
        print(f"\nDRY RUN - would write {out}")
        return 0
    out.write_text(ttl, encoding="utf-8")
    print(f"\nwrote {out}")
    try:
        import rdflib

        g = rdflib.Graph()
        g.parse(str(out), format="turtle")
        print(f"  {len(g)} triples parse OK")
    except ImportError:  # pragma: no cover
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
