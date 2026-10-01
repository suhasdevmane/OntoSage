# -*- coding: utf-8 -*-
"""A safety-critical position may not be asserted and hedged in the same breath (BUG-858, P1).

WHAT HAPPENED
-------------
Asked "Where is the nearest defibrillator?" the system answered

    Defibrillators (AEDs) are located at reception and on floors 3 and 5.

as fact, while the record it came from -- ``bldg:Cap_first_aid`` -- carried

    ontosage:locationText "Defibrillators are modelled at reception, floor 3 and floor 5."

``CapabilityFact.render()`` prints the locationText as the heading and the answerText as the
body, so one answer said both things at once. In an emergency the hedge is the half that gets
ignored, and a reader who does notice it has no way to tell which half to act on.

THE POSITIONS WERE NEVER THE PROBLEM. ``bldg:AED_Reception``, ``bldg:AED_Floor3`` and
``bldg:AED_Floor5`` have carried ``brick:isPartOf`` to ``Room0.01``, ``Room3.17`` and
``Room5.26`` since they were declared, and all three rooms resolve. The defect was entirely in
the prose: one record holding three positions in a sentence, hedged, with nothing tying the
sentence to the graph.

WHAT IS PINNED HERE
-------------------
1. No shipped record hedges a position it also states  (the vocabulary scan).
2. The rooms the first-aid record NAMES are the rooms its ``ontosage:locatedIn`` POINTS AT,
   and the rooms the devices are ``brick:isPartOf``  (the contradiction, directly).
3. Every declared defibrillator is an ``ontosage:Amenity`` with a position that the building
   declares  (so "nearest" is a computation over triples, not a reading of prose).
4. The floor a device claims is the floor its room is on  (a copy-paste that moves a
   defibrillator one storey is a wrong answer of exactly the kind BUG-858 was about).
5. The RENDERED answer -- ``CapabilityFact.render()``, the string the reader sees -- names
   every position and hedges none of them.

Building-agnostic throughout: it reads whatever buildings the repo ships, and a building that
declares no defibrillator is checked for nothing. Nothing here names a room, a floor or a
building; the expected values are derived from the graph and compared against themselves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

BRICK = Namespace("https://brickschema.org/schema/Brick#")
ONTO = Namespace("http://ontosage.org/capabilities#")

#: The class Brick gives a defibrillator. `brick:AED` is declared an alias of it upstream, so a
#: building writing either is found once the vocabulary is loaded; on the raw TTL we look for the
#: canonical name, which is what every building in this repo writes.
AED_CLASS = BRICK.Automated_External_Defibrillator

#: Words that turn a stated position into something the reader cannot act on. A position is a
#: fact or it is absent -- there is no useful middle, and for a defibrillator the middle is the
#: worst of the three.
#:
#: THREE WORDS ARE DELIBERATELY NOT HERE, each because it appears in a record that is telling
#: the truth. "simulated" and "dummy": bldg1 has a real teaching room called the Simulated
#: Trading Room, and D1 (2026-09-22) removed origin flags from the graph entirely, so those
#: words mark a room name, not a hedge. "assumed" was on this list for one run and failed
#: `Amenity_Parking_GroundLevel`, whose answerText says a daily rate "cannot be quoted and must
#: not be assumed" -- a record refusing to invent a figure, which is the behaviour the project
#: wants, flagged by a guard written against the opposite behaviour. A vocabulary check that
#: punishes honest prose gets switched off and takes the real findings with it.
_HEDGES = (
    "modelled",
    "modeled",
    "notional",
    "illustrative",
    "for illustration",
    "placeholder",
    "to be replaced",
    "indicative only",
    "example only",
    "hypothetical",
)

#: A room/space identifier as a person writes it in PROSE: "Room 0.01", "floor 3" -> "0.01".
#: Deliberately NOT a floor number: "floor 3" carries no decimal point, so the two cannot be
#: confused, and a phone number ("999") cannot be read as a room.
_ROOM_NUM = re.compile(r"\b(\d+\.\d{1,3})\b")

#: The same identifier inside an IRI local name, where there is no word boundary to anchor on:
#: `\b` does not match between the "m" and the "3" of `Room3.17`, so the prose pattern silently
#: found nothing and the triples read as absent. Two notations, two patterns.
_ROOM_NUM_IN_NAME = re.compile(r"(\d+\.\d{1,3})")


# ── finding the buildings and their records ──────────────────────────────────


def _building_dirs() -> List[Path]:
    """Every building the repo ships, parked (``bldg<N>/``) or active (``input/``)."""
    dirs = [p for p in REPO.glob("bldg[0-9]*") if p.is_dir()]
    if (REPO / "input").is_dir():
        dirs.append(REPO / "input")
    return sorted(dirs)


def _ttl_text(d: Path) -> List[Tuple[Path, str]]:
    """Every TTL in a building directory, with its text, minus the vendored vocabulary.

    ``Brick_v1.4.ttl`` and ``Brick+extensions.ttl`` define the CLASS and declare no instance;
    parsing them costs megabytes and proves nothing. Skipped by the same name convention the
    rest of the suite uses.
    """
    out = []
    for f in sorted(d.glob("*.ttl")):
        if f.name.lower().startswith("brick"):
            continue
        out.append((f, f.read_text(encoding="utf-8", errors="replace")))
    return out


def _graph_of(files: List[Path]) -> Graph:
    g = Graph()
    for f in files:
        g.parse(f, format="turtle")
    return g


def _records_graph(d: Path) -> Graph:
    """The building's amenity records: every TTL that states a location in words.

    Pre-filtered on the predicate rather than parsed wholesale, because a building's merged
    A-Box + vocabulary file is several megabytes and holds no ``ontosage:locationText`` at all.
    """
    return _graph_of([f for f, t in _ttl_text(d) if "ontosage:locationText" in t])


def _devices_graph(d: Path) -> Graph:
    """The files that DECLARE a defibrillator, plus the files that describe one.

    Selected on the class name appearing next to ``NamedIndividual`` (an instance) or on the
    OCBV first-aid type (an amenity record). Matching the bare class name instead would pull in
    every file that merely mentions the vocabulary.
    """
    wanted = []
    for f, t in _ttl_text(d):
        if "ontosage:FirstAidPoint" in t:
            wanted.append(f)
            continue
        if any(
            "Automated_External_Defibrillator" in line and "NamedIndividual" in line
            for line in t.splitlines()
        ):
            wanted.append(f)
    return _graph_of(wanted)


def _declared_locally(d: Path, local: str) -> bool:
    """Is ``local`` the SUBJECT of a statement anywhere in this building?

    Turtle writes a subject two ways and both are declarations -- ``bldg:Room0.01`` and
    ``<http://.../abacws#Room0.01>`` -- which is the gap that let 19 amenities read as
    undeclared in V10 W1-2. Matched on the text so a five-megabyte file costs a scan, not a
    parse.
    """
    pat = re.compile(
        r"(?m)^\s*(?:[A-Za-z][\w.\-]*:"
        + re.escape(local)
        + r"|<[^>\s]*[#/]"
        + re.escape(local)
        + r">)(?=[\s,;])"
    )
    return any(pat.search(t) for _, t in _ttl_text(d))


def _first_aid_records(g: Graph) -> List[URIRef]:
    return sorted(set(g.subjects(RDF.type, ONTO.FirstAidPoint)), key=str)


def _defibrillators(g: Graph) -> List[URIRef]:
    return sorted(set(g.subjects(RDF.type, AED_CLASS)), key=str)


def _local(iri) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _lit(g: Graph, s, p) -> str:
    v = g.value(s, p)
    return str(v) if v is not None else ""


def _buildings_with_a_defibrillator() -> List[Tuple[Path, Graph]]:
    out = []
    for d in _building_dirs():
        g = _devices_graph(d)
        if _defibrillators(g):
            out.append((d, g))
    return out


# ── 1. nothing hedges a position it also states ──────────────────────────────


def test_no_shipped_record_hedges_a_position_it_also_states():
    """The defect's own wording, as a rule over every building.

    ``ontosage:locationText`` and ``ontosage:answerText`` are what the reader is shown. A
    hedge in either is the BUG-858 shape whatever record it sits on, so this is not scoped to
    first aid.
    """
    offenders: List[str] = []
    for d in _building_dirs():
        g = _records_graph(d)
        for pred in (ONTO.locationText, ONTO.answerText):
            for s, _, o in g.triples((None, pred, None)):
                text = str(o).lower()
                for word in _HEDGES:
                    if word in text:
                        offenders.append(
                            f"{d.name}/{_local(s)} {_local(pred)}: ...{word}... -> {str(o)[:90]}"
                        )
    assert not offenders, (
        "a shipped record hedges a position it also states as fact: "
        + "; ".join(offenders)
        + ". State the position or leave the record out -- BUG-858."
    )


def test_the_guard_would_catch_the_wording_it_was_written_for():
    """The original literal, in miniature. A rule that passes everywhere may simply be broken."""
    assert any(
        w in "Defibrillators are modelled at reception, floor 3 and floor 5.".lower()
        for w in _HEDGES
    )
    assert not any(
        w in "Room 0.01 (Main Reception, floor 0) and Room 3.17 (Staff Common Room).".lower()
        for w in _HEDGES
    )


# ── 2. the record and its answer name the same places as the graph ───────────


def test_some_building_declares_a_first_aid_position():
    """The count behind the two tests below, which skip a building that declares none.

    Without it, every one of those parameters could go quiet together -- a renamed class, a
    changed predicate filter in ``_records_graph``, a building set that stopped resolving --
    and the file would report a clean run having compared no record to any answer. Where a
    defibrillator is is not a claim to get wrong quietly.
    """
    counts = {d.name: len(_first_aid_records(_records_graph(d))) for d in _building_dirs()}
    assert sum(counts.values()) > 0, f"no building declares an ontosage:FirstAidPoint: {counts}"


@pytest.mark.parametrize("d", _building_dirs(), ids=lambda p: p.name)
def test_the_rooms_a_first_aid_record_names_are_the_rooms_it_points_at(d: Path):
    """The contradiction, directly: prose vs triples on the SAME record.

    A record that names rooms in words must point at those rooms with ``ontosage:locatedIn``,
    and its ``locationText`` and ``answerText`` must name the same set. A record that names no
    room (bldg2 and bldg3 say "reception and each floor's lift lobby") is checked for nothing
    -- vague is not the same fault as contradictory, and is not what BUG-858 was about.
    """
    g = _records_graph(d)
    records = _first_aid_records(g)
    # Three of the six building directories declare no first-aid point at all (bldg4 is a
    # synthetic fixture; the two *_source trees hold no amenity records), so those parameters
    # used to report PASSED for a building they never examined -- the same shape as the
    # __init__.py parameter in test_agent_methods_exist (CAVEAT-1115). Skipping says which
    # case it is. `test_some_building_declares_a_first_aid_position` below keeps the whole set
    # from going silent at once.
    if not records:
        pytest.skip(f"{d.name} declares no ontosage:FirstAidPoint")
    for rec in records:
        loc_text = _lit(g, rec, ONTO.locationText)
        ans_text = _lit(g, rec, ONTO.answerText)
        in_loc = set(_ROOM_NUM.findall(loc_text))
        in_ans = set(_ROOM_NUM.findall(ans_text))
        if not (in_loc or in_ans):
            continue
        # An ABSENT answerText is not a disagreement. The three per-device records state their
        # position once, in locationText, and `render()` prints it as a plain amenity line --
        # repeating the same sentence as an answerText would print it twice. Only a record that
        # states positions in BOTH fields can contradict itself, and that is what is compared.
        if ans_text.strip():
            assert in_loc == in_ans, (
                f"{d.name}/{_local(rec)}: locationText names rooms {sorted(in_loc)} and "
                f"answerText names {sorted(in_ans)}. The reader is shown both."
            )
        pointed = {
            m.group(1)
            for t in g.objects(rec, ONTO.locatedIn)
            for m in [_ROOM_NUM_IN_NAME.search(_local(t))]
            if m
        }
        assert in_loc == pointed, (
            f"{d.name}/{_local(rec)}: the record SAYS {sorted(in_loc)} and POINTS AT "
            f"{sorted(pointed)}. Prose and triples must agree, or the triples are decoration."
        )


def test_at_least_one_shipped_building_actually_exercises_that_rule():
    """Otherwise the parametrised test above passes by having nothing to look at."""
    named = []
    for d in _building_dirs():
        g = _records_graph(d)
        for rec in _first_aid_records(g):
            if _ROOM_NUM.findall(_lit(g, rec, ONTO.locationText)):
                named.append(f"{d.name}/{_local(rec)}")
    assert named, (
        "no shipped first-aid record names a room, so the prose-vs-triples check proves "
        "nothing. BUG-858 was closed by making bldg1's record name Room 0.01, 3.17 and 5.26."
    )


# ── 3/4. every declared device is located, and on the floor it claims ────────


@pytest.mark.parametrize(
    "d,g", _buildings_with_a_defibrillator(), ids=lambda x: x.name if isinstance(x, Path) else ""
)
def test_every_declared_defibrillator_is_an_amenity_with_a_declared_position(d: Path, g: Graph):
    """ "Where is the NEAREST one" is answered by amenity_proximity, which reads
    ``ontosage:locatedIn`` / ``ontosage:onFloor`` off an ``ontosage:Amenity``. A device that
    carries neither is invisible to that lane however carefully its position is written down,
    and the only thing left to answer from is prose.
    """
    problems: List[str] = []
    for aed in _defibrillators(g):
        name = f"{d.name}/{_local(aed)}"
        if (aed, RDF.type, ONTO.Amenity) not in g:
            problems.append(f"{name}: not an ontosage:Amenity")
        if (aed, RDF.type, ONTO.FirstAidPoint) not in g:
            problems.append(f"{name}: not an ontosage:FirstAidPoint")
        targets = list(g.objects(aed, ONTO.locatedIn))
        if not targets:
            problems.append(f"{name}: no ontosage:locatedIn")
        for t in targets:
            if not _declared_locally(d, _local(t)):
                problems.append(f"{name}: locatedIn {_local(t)}, which nothing declares")
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(
    "d,g", _buildings_with_a_defibrillator(), ids=lambda x: x.name if isinstance(x, Path) else ""
)
def test_the_floor_a_defibrillator_claims_is_the_floor_its_room_is_on(d: Path, g: Graph):
    """A copy-paste that leaves a device claiming the floor above sends someone up a staircase
    they did not need to climb. Both halves are in the building's own TTL, so they can be
    compared without asking anything.
    """
    rooms = _graph_of([f for f, t in _ttl_text(d) if "brick:isPartOf" in t])
    problems: List[str] = []
    for aed in _defibrillators(g):
        claimed = _lit(g, aed, ONTO.onFloor)
        if not claimed:
            continue
        for room in g.objects(aed, ONTO.locatedIn):
            actual = [_local(f) for f in rooms.objects(room, BRICK.isPartOf)]
            if not actual:
                continue
            if claimed not in actual:
                problems.append(
                    f"{d.name}/{_local(aed)}: onFloor '{claimed}' but {_local(room)} is part "
                    f"of {actual}"
                )
    assert not problems, "; ".join(problems)


# ── 5. the string the reader actually sees ───────────────────────────────────


@pytest.mark.parametrize("d", _building_dirs(), ids=lambda p: p.name)
def test_the_rendered_first_aid_answer_states_every_position_and_hedges_none(d: Path):
    """The pin at the point of failure.

    BUG-858 was not a bad field, it was a bad ANSWER: ``render()`` puts locationText in the
    heading and answerText in the body, so the two were printed together. Asserting on the
    fields separately would have let the same contradiction back in through a third field, so
    the rendered string is what is checked.
    """
    from orchestrator.services.capability_graph_resolver import CapabilityFact

    g = _records_graph(d)
    records = _first_aid_records(g)
    if not records:
        pytest.skip(f"{d.name} declares no ontosage:FirstAidPoint")
    for rec in records:
        rendered = CapabilityFact(
            label=_lit(g, rec, RDFS.label),
            location=_lit(g, rec, ONTO.locationText),
            note=_lit(g, rec, ONTO.note),
            category=_lit(g, rec, ONTO.capabilityCategory),
            answer=_lit(g, rec, ONTO.answerText),
        ).render()
        low = rendered.lower()
        hedged = [w for w in _HEDGES if w in low]
        assert (
            not hedged
        ), f"{d.name}/{_local(rec)} renders a hedged position {hedged}: {rendered[:160]}"
        for room in {m for m in _ROOM_NUM.findall(_lit(g, rec, ONTO.locationText))}:
            assert room in rendered, (
                f"{d.name}/{_local(rec)}: the record states room {room} but the rendered "
                f"answer does not: {rendered[:160]}"
            )


def test_the_render_path_is_the_one_the_reader_gets():
    """`render()` really does print BOTH fields, which is why they had to agree.

    Written as a live check on the class rather than as a comment: if the heading stops
    carrying locationText, the test above quietly stops testing the thing it names.
    """
    from orchestrator.services.capability_graph_resolver import CapabilityFact

    out = CapabilityFact(
        label="Defibrillator (AED) and first aid",
        location="HEADING_TEXT",
        answer="BODY_TEXT",
        category="EMERGENCY",
    ).render()
    assert "HEADING_TEXT" in out and "BODY_TEXT" in out


# ── the closed defect, stated as a fact about the shipped tree ───────────────


def test_bug_858_the_first_aid_record_no_longer_says_modelled():
    """The exact regression, by name. The word must not come back on any first-aid record."""
    offenders: List[str] = []
    for d in _building_dirs():
        g = _records_graph(d)
        for rec in _first_aid_records(g):
            for pred in (ONTO.locationText, ONTO.answerText):
                if "modelled" in _lit(g, rec, pred).lower():
                    offenders.append(f"{d.name}/{_local(rec)}.{_local(pred)}")
    assert not offenders, "BUG-858 is back on: " + ", ".join(offenders)
