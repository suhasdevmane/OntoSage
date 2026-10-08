# -*- coding: utf-8 -*-
"""The facet catalogue: what can be known about which kind of entity (v2, P2).

ARBITER's vocabulary was the sensed-modality list, so a question combining a reading with a
register field or a TTL property compiled its non-sensed criteria to unmapped terms. The
catalogue derives every facet from the building's own graph -- sensors from the coverage audit,
record fields from the held registers and their P1 links, TTL properties of spaces, capacity
through its authority order, the executor's availability checks, floors and routes -- and ranks
them for a question by lexical evidence.

Every test here runs OFFLINE through rdflib: synthetic graphs for the rules, and the parked
buildings' own files for the claim that the same code describes two real buildings.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import rdflib
import yaml

from orchestrator.services import record_registry as rr
from orchestrator.services.deliberation import facets
from orchestrator.services.deliberation.coverage_audit import (
    ModalitySpec,
    load_modalities,
    load_modality_raw,
)
from orchestrator.services.record_entity_links import LINK_PREDICATES

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ONTO = "http://ontosage.org/capabilities#"
LOCATED_IN = LINK_PREDICATES["located_in"]
ROUTE_TO = LINK_PREDICATES["route_to"]

#: Deliberately no real building's namespace: the rules must hold for buildings never seen.
NS_A = "http://example.org/towerX#"
NS_B = "http://example.org/campusY#"

NOISE = ModalitySpec(
    "noise", ["Sound_Level_Sensor", "Noise_Level_Sensor"], sat={"unit": "dB", "scope": "room"}
)
CO2 = ModalitySpec("co2", ["CO2_Level_Sensor"], sat={"unit": "ppm", "scope": "room"})
TEMPERATURE = ModalitySpec(
    "temperature", ["Zone_Air_Temperature_Sensor"], sat={"unit": "degC", "scope": "room"}
)


# ── an offline graph, served the way the live stack serves it ──────────────────────


def _sparql_json(g: rdflib.Graph):
    """An async SPARQL-JSON executor over an rdflib graph (the shape live.sparql_exec returns)."""

    async def sparql_exec(query: str) -> Dict[str, Any]:
        res = g.query(query)
        bindings = []
        for row in res:
            binding = {}
            for var in res.vars:
                val = row[var]
                if val is not None:
                    kind = "uri" if isinstance(val, rdflib.URIRef) else "literal"
                    binding[str(var)] = {"type": kind, "value": str(val)}
            bindings.append(binding)
        return {"head": {"vars": [str(v) for v in res.vars]}, "results": {"bindings": bindings}}

    return sparql_exec


def _run_select_over(g: rdflib.Graph):
    """The run_sparql_select shape ({ok, rows}) over an rdflib graph."""

    async def run_select(query: str, limit: int = 1000) -> Dict[str, Any]:
        res = g.query(query)
        rows = [{str(v): (str(b[v]) if b[v] is not None else None) for v in res.vars} for b in res]
        return {"ok": True, "rows": rows}

    return run_select


_TBOX = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix hbco: <http://ontosage.org/hbco#> .
brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
o:Record a owl:Class .
hbco:roomCapacity a owl:DatatypeProperty ; rdfs:label "room capacity"@en .
"""

_PREFIXES = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix hbco: <http://ontosage.org/hbco#> .
@prefix x: <%(ns)s> .
"""

#: Two spaces on one floor, each with a declared capacity; a noise sensor in one; a register of
#: four records -- three placed in a space by the P1 link, one not -- with an integer, a 3-value
#: enum and a boolean field, plus the provenance every lifted record carries.
_BUILDING = (
    _PREFIXES
    + """
x:L1 a brick:Floor ; rdfs:label "%(floor)s" .
x:R1 a brick:Room ; rdfs:label "%(room)s 1" ; brick:isPartOf x:L1 ; hbco:roomCapacity 12 .
x:R2 a brick:Room ; rdfs:label "%(room)s 2" ; brick:isPartOf x:L1 ; hbco:roomCapacity 30 .
x:Noise1 a o:Sound_Level_Sensor ; brick:hasLocation x:R1 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-noise-1" ; ref:storedAt x:noise_data ] .

o:%(cls)s rdfs:subClassOf o:Record ; rdfs:label "%(label)s" .
x:d1 a o:%(cls)s ; o:recordId "D-1" ; o:recordOwner "Estates" ;
    o:effectiveFrom "2026-01-01"^^xsd:date ;
    o:%(seats)s 12 ; o:%(kind)s "quiet" ; o:%(flag)s true ; o:locatedInSpace x:R1 .
x:d2 a o:%(cls)s ; o:recordId "D-2" ; o:recordOwner "Estates" ;
    o:effectiveFrom "2026-01-01"^^xsd:date ;
    o:%(seats)s 8 ; o:%(kind)s "group" ; o:%(flag)s false ; o:locatedInSpace x:R2 .
x:d3 a o:%(cls)s ; o:recordId "D-3" ; o:recordOwner "Estates" ;
    o:effectiveFrom "2026-01-01"^^xsd:date ;
    o:%(seats)s 20 ; o:%(kind)s "open" ; o:%(flag)s true ; o:locatedInSpace x:R1 .
x:d4 a o:%(cls)s ; o:recordId "D-4" ; o:recordOwner "Estates" ;
    o:effectiveFrom "2026-01-01"^^xsd:date ;
    o:%(seats)s 6 ; o:%(kind)s "quiet" ; o:%(flag)s false .
"""
)

TOWER = {
    "id": "towerX",
    "ns": NS_A,
    "floor": "Level 1",
    "room": "Room",
    "cls": "TestDeskProfile",
    "label": "Desk profile",
    "seats": "seatCount",
    "kind": "deskKind",
    "flag": "isBookable",
}
#: The same shape, in another namespace, with every class and field named differently.
CAMPUS = {
    "id": "campusY",
    "ns": NS_B,
    "floor": "Storey One",
    "room": "Studio",
    "cls": "TestSeatCard",
    "label": "Seat card",
    "seats": "seatTotal",
    "kind": "cardKind",
    "flag": "canReserve",
}


def _graph(building: Dict[str, str], *extra: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=_TBOX, format="turtle")
    g.parse(data=_BUILDING % building, format="turtle")
    for ttl in extra:
        g.parse(data=(_PREFIXES % building) + ttl, format="turtle")
    return g


async def _catalogue(
    g: rdflib.Graph,
    building: Dict[str, str],
    modalities: Tuple[ModalitySpec, ...] = (NOISE,),
    events_store: bool = False,
) -> facets.FacetCatalogue:
    facets.clear_cache()
    return await facets.build_facet_catalogue(
        _sparql_json(g),
        building["id"],
        building["ns"],
        list(modalities),
        modality_config={},
        events_store=events_store,
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    facets.clear_cache()
    yield
    facets.clear_cache()


# ── 1. the catalogue of a small building, facet by facet ─────────────────────────────


async def test_a_two_space_building_yields_exactly_the_expected_facets():
    cat = await _catalogue(_graph(TOWER), TOWER)
    assert cat.errors == ()
    desk = "record:TestDeskProfile."
    assert {f.key for f in cat} == {
        "sensor:noise",
        desk + "seatCount",
        desk + "deskKind",
        desk + "isBookable",
        "ttl:capacity",
        "spatial:floor",
    }, "provenance, identity, the stamp and the link itself are no facets"
    by = {f.key: f for f in cat}
    assert {f.entity_type for f in cat} == {"space"}
    assert {f.key: f.status for f in cat} == {f.key: "suitable" for f in cat}

    assert (by[desk + "seatCount"].value_type, by[desk + "seatCount"].examples) == (
        "integer",
        ("6", "8", "12", "20"),
    )
    assert (by[desk + "deskKind"].value_type, by[desk + "deskKind"].examples) == (
        "enum",
        ("group", "open", "quiet"),
    )
    assert by[desk + "isBookable"].value_type == "boolean"
    for name in ("seatCount", "deskKind", "isBookable"):
        facet = by[desk + name]
        # two spaces, from three linked records: coverage counts ENTITIES, never records
        assert (facet.coverage, facet.join_predicate) == (2, LOCATED_IN), name
        assert (facet.source_kind, facet.record_class) == ("record", "TestDeskProfile")
        assert facet.predicate == ONTO + name

    noise = by["sensor:noise"]
    assert (noise.value_type, noise.unit, noise.coverage, noise.modality) == (
        "number",
        "dB",
        1,
        "noise",
    )
    assert "quiet" in noise.lay_terms, "the compiler's own lay hints are the sensor's vocabulary"

    capacity = by["ttl:capacity"]
    assert (capacity.value_type, capacity.unit, capacity.coverage) == ("integer", "persons", 2)
    assert capacity.examples == ("12", "30")
    assert "authoritative" in (capacity.resolver or ""), "read through its authority order"

    floor = by["spatial:floor"]
    assert (floor.value_type, floor.coverage, floor.examples) == ("enum", 2, ("Level 1",))
    assert cat.entity_counts == {"space": 2, "floor": 1, "room": 2}


_LADDER = """
o:deskNote a owl:DatatypeProperty ; rdfs:domain o:TestDeskProfile .
x:d4 o:deskRemark "spare desk" .
x:d1 o:deskSize 10 .
x:d2 o:deskSize "large" .
x:Co2Unbacked a o:CO2_Level_Sensor ; brick:hasLocation x:R2 .
"""


async def test_every_rung_of_the_ladder_is_computed():
    """declared -> linked -> populated -> suitable, each rung reached for a reason the graph holds."""
    cat = await _catalogue(_graph(TOWER, _LADDER), TOWER, (NOISE, CO2, TEMPERATURE))
    status = {f.key: (f.status, f.coverage) for f in cat}
    # configured, but no sensor of the kind is located anywhere
    assert status["sensor:temperature"] == ("declared", 0)
    # a sensor is located, but nothing says where its readings are stored
    assert status["sensor:co2"] == ("linked", 0)
    # the TBox declares the field for the class, and no record holds a value
    assert status["record:TestDeskProfile.deskNote"] == ("linked", 0)
    # a value exists, on the one record no space is linked to
    assert status["record:TestDeskProfile.deskRemark"] == ("populated", 0)
    # values reach two spaces, but an integer and a string: the value type is NOT known
    mixed = cat.get("record:TestDeskProfile.deskSize")
    assert (mixed.status, mixed.coverage) == ("populated", 2)
    assert any("mixed datatypes" in n for n in mixed.notes)
    assert status["sensor:noise"] == ("suitable", 1)
    assert facets.LADDER == ("declared", "linked", "populated", "suitable")
    assert cat.status_counts() == {"declared": 1, "linked": 2, "populated": 2, "suitable": 6}


# ── 2. what a record is about comes from the link its instances carry ────────────────

_TARIFF = """
o:TestTariff rdfs:subClassOf o:Record ; rdfs:label "Tariff" .
x:t1 a o:TestTariff ; o:recordId "T-1" ; o:unitRate 0.28 ; o:utilityKind "Electricity" .
x:t2 a o:TestTariff ; o:recordId "T-2" ; o:unitRate 0.31 ; o:utilityKind "Gas" .
"""


async def test_a_record_class_with_no_link_is_about_the_building_not_a_space():
    cat = await _catalogue(_graph(TOWER, _TARIFF), TOWER)
    tariff = [f for f in cat if f.record_class == "TestTariff"]
    assert {f.key for f in tariff} == {
        "record:TestTariff.unitRate",
        "record:TestTariff.utilityKind",
    }
    for facet in tariff:
        assert (facet.entity_type, facet.join_predicate, facet.coverage) == ("building", None, 1)
        assert facet.status == "suitable"
    assert cat.get("record:TestTariff.unitRate").value_type == "number"
    assert not [f for f in cat.for_entity("space") if f.record_class == "TestTariff"]


_PARENT = """
o:TestBase rdfs:subClassOf o:Record ; rdfs:label "Base record" .
o:TestDeskProfile rdfs:subClassOf o:TestBase .
x:d1 a o:TestBase . x:d2 a o:TestBase . x:d3 a o:TestBase . x:d4 a o:TestBase .
"""


async def test_a_parent_class_does_not_repeat_its_childrens_facets():
    """Under reasoning every desk is also a TestBase; the child alone describes the field."""
    cat = await _catalogue(_graph(TOWER, _PARENT), TOWER)
    assert not [f for f in cat if f.record_class == "TestBase"]
    assert cat.get("record:TestDeskProfile.seatCount") is not None


_ROUTES = """
o:TestRoute rdfs:subClassOf o:Record ; rdfs:label "Route" .
x:rt1 a o:TestRoute ; o:routeToSpace x:R1 ; o:routeFromSpace x:R2 ;
    o:allowMinutes 5 ; o:isStepFree true ; o:doorOperation "manual" .
x:rt2 a o:TestRoute ; o:routeToSpace x:R2 ;
    o:allowMinutes 9 ; o:isStepFree false ; o:doorOperation "automatic" .
"""


async def test_a_route_record_is_about_the_route_and_its_facts_reach_the_space_it_ends_in():
    cat = await _catalogue(_graph(TOWER, _ROUTES), TOWER)
    minutes = cat.get("record:TestRoute.allowMinutes")
    assert (minutes.entity_type, minutes.join_predicate, minutes.coverage) == ("route", ROUTE_TO, 2)
    assert minutes.unit == "minutes", "a numeric field whose name ends in a unit states it"
    reached = cat.get("spatial:TestRoute.allowMinutes")
    assert (reached.entity_type, reached.join_predicate, reached.coverage) == ("space", ROUTE_TO, 2)
    assert cat.get("spatial:TestRoute.isStepFree").value_type == "boolean"
    assert cat.get("spatial:TestRoute.doorOperation") is None, "only numbers and yes/no filter"
    assert any("routeFromSpace" in note for note in reached.notes)


_BOOKINGS = """
o:Booking rdfs:subClassOf o:Record ; rdfs:label "Room booking" ;
    o:layTerms "booking", "booked", "reservation" .
x:b1 a o:Booking ; o:effectiveFrom "2026-09-01T09:00:00"^^xsd:dateTime ;
    o:effectiveTo "2026-09-01T11:00:00"^^xsd:dateTime ; o:locatedInSpace x:R1 .
x:b2 a o:Booking ; o:effectiveFrom "2026-09-02T09:00:00"^^xsd:dateTime ;
    o:effectiveTo "2026-09-02T10:00:00"^^xsd:dateTime ; o:locatedInSpace x:R1 .
"""


async def test_availability_rests_on_booking_records_linked_to_spaces():
    cat = await _catalogue(_graph(TOWER, _BOOKINGS), TOWER)
    free = cat.get("event:free_window")
    assert (free.entity_type, free.value_type, free.status, free.coverage) == (
        "space",
        "boolean",
        "suitable",
        1,
    )
    assert (free.record_class, free.join_predicate) == ("Booking", LOCATED_IN)
    assert "booked" in free.class_terms
    assert any("no events store" in note for note in free.notes)
    assert cat.get("event:booking_pressure").unit == "percent"


async def test_a_registered_events_store_alone_declares_availability_but_cannot_populate_it():
    cat = await _catalogue(_graph(TOWER), TOWER, events_store=True)
    free = cat.get("event:free_window")
    assert (free.status, free.coverage, free.record_class) == ("linked", 0, None)
    assert free.resolver and "events store" in free.notes[0]
    assert (await _catalogue(_graph(TOWER), TOWER)).get("event:free_window") is None


# ── 3. retrieval ───────────────────────────────────────────────────────────────────

_AV = """
o:TestAVKit rdfs:subClassOf o:Record ; rdfs:label "AV kit" ;
    o:layTerms "projector", "display", "av kit" .
x:av1 a o:TestAVKit ; o:avKind "projector" ; o:locatedInSpace x:R1 .
x:av2 a o:TestAVKit ; o:avKind "display" ; o:locatedInSpace x:R2 .
x:av3 a o:TestAVKit ; o:avKind "projector" ; o:locatedInSpace x:R2 .
"""


async def test_a_compound_question_retrieves_a_facet_for_each_of_its_criteria():
    cat = await _catalogue(_graph(TOWER, _AV), TOWER, (NOISE, CO2, TEMPERATURE))
    top = [f.key for _, f in cat.retrieve("a quiet room for twelve people with a projector", k=5)]
    assert "sensor:noise" in top, top
    assert {"ttl:capacity", "record:TestDeskProfile.seatCount"} & set(top), top
    assert "record:TestAVKit.avKind" in top, top
    assert "sensor:co2" not in top and "sensor:temperature" not in top

    assert cat.retrieve("the coffee machine") == []
    assert cat.unmatched_terms("the coffee machine") == ["coffee", "machine"]
    assert cat.unmatched_terms("a quiet room for twelve people with a projector") == []


def _facet(key: str, *words: str, status: str = "suitable") -> facets.Facet:
    return facets.Facet(
        key=key,
        entity_type="space",
        source_kind="ttl",
        label=words[0],
        value_type="number",
        lay_terms=tuple(words[1:]),
        status=status,
        coverage=1 if status == "suitable" else 0,
    )


def test_a_whole_multi_word_term_outranks_the_same_words_found_apart():
    cat = facets.FacetCatalogue([_facet("t:phrase", "sound level"), _facet("t:word", "sound")])
    together = [f.key for _, f in cat.retrieve("what is the sound level here?")]
    assert together == ["t:phrase", "t:word"]
    # the same two words, apart and reversed, are not the phrase: only the single word matches
    apart = [f.key for _, f in cat.retrieve("what level of sound is there?")]
    assert apart == ["t:word"]


def test_retrieval_is_deterministic_and_breaks_ties_on_the_key():
    fs = [_facet("t:b", "glare"), _facet("t:a", "glare"), _facet("t:c", "draught")]
    forward = facets.FacetCatalogue(fs).retrieve("any glare by the window?")
    backward = facets.FacetCatalogue(list(reversed(fs))).retrieve("any glare by the window?")
    assert [(s, f.key) for s, f in forward] == [(s, f.key) for s, f in backward]
    assert [f.key for _, f in forward] == ["t:a", "t:b"]
    assert forward[0][0] == forward[1][0], "identical evidence, identical score"


def test_inflections_reach_the_word_a_facet_is_named_by():
    cat = facets.FacetCatalogue([_facet("t:quiet", "quiet"), _facet("t:seat", "seat")])
    assert [f.key for _, f in cat.retrieve("the quietest one")] == ["t:quiet"]
    assert [f.key for _, f in cat.retrieve("how many seats?")] == ["t:seat"]


def test_a_minimum_rung_keeps_merely_declared_facets_out():
    cat = facets.FacetCatalogue(
        [_facet("t:held", "glare"), _facet("t:declared", "glare", status="declared")]
    )
    assert [f.key for _, f in cat.retrieve("glare")] == ["t:declared", "t:held"]
    assert [f.key for _, f in cat.retrieve("glare", min_status="suitable")] == ["t:held"]


# ── 4. building-agnostic ─────────────────────────────────────────────────────────────


async def test_the_same_code_describes_a_building_it_has_never_seen():
    tower = await _catalogue(_graph(TOWER), TOWER)
    campus = await _catalogue(_graph(CAMPUS), CAMPUS)

    from orchestrator.services.deliberation.space_kinds import SPACE_KIND_FACET

    def shape(cat: facets.FacetCatalogue) -> List[Tuple[Any, ...]]:
        return sorted(
            (f.source_kind, f.entity_type, f.value_type, f.status, f.coverage)
            for f in cat
            if f.key != SPACE_KIND_FACET
        )

    # The two graphs differ in ONE recorded fact, and the catalogue must say so: the campus's
    # rooms are labelled "Studio 1", "Studio 2" -- a kind of space -- and the tower's "Room 1",
    # "Room 2", which name none. Everything else is the same graph under other names.
    assert shape(campus) == shape(tower)
    assert campus.get(SPACE_KIND_FACET).examples == ("Studio",)
    assert campus.get(SPACE_KIND_FACET).coverage == 2
    assert tower.get(SPACE_KIND_FACET) is None
    assert {k: v for k, v in campus.counts().items() if k != "spatial"} == {
        k: v for k, v in tower.counts().items() if k != "spatial"
    }
    assert campus.get("record:TestSeatCard.seatTotal").value_type == "integer"
    assert campus.get("record:TestSeatCard.cardKind").examples == ("group", "open", "quiet")
    assert campus.get("spatial:floor").examples == ("Storey One",)
    for cat, ns in ((tower, NS_A), (campus, NS_B)):
        assert not [f.key for f in cat if ns in f.key or ns in f.label]


def test_the_facet_module_names_no_building():
    text = Path(facets.__file__).read_text(encoding="utf-8")
    banned = re.compile(r"abacws|cardiff|bldg[123]\b|buildsys\.org", re.IGNORECASE)
    assert not banned.findall(text)


# ── the pieces it reuses, and the cache ──────────────────────────────────────────────

#: The query `schema_hint` sent before it read the shared profile query.
_OLD_SCHEMA_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?p (SAMPLE(?v) AS ?example) WHERE {
  ?i a o:%s ; ?p ?v .
} GROUP BY ?p
"""


def test_schema_hint_reads_the_same_predicates_through_the_shared_profile_query():
    g = _graph(TOWER)
    before = {str(row.p) for row in g.query(_OLD_SCHEMA_QUERY % "TestDeskProfile")}
    after = {str(row.p) for row in g.query(rr.predicate_profile_query(["TestDeskProfile"]))}
    assert before and before == after
    detailed = rr.predicate_profile_query(["TestDeskProfile"], NS_A, detailed=True)
    rows = {str(row.p): row for row in g.query(detailed)}
    seats = rows[ONTO + "seatCount"]
    assert (int(seats.carriers), int(seats.distinct), int(seats.literals)) == (4, 4, 4)


async def test_record_classes_read_from_another_graph_leave_the_router_untouched():
    rr._ID_PREFIXES.clear()
    rr._CACHE.clear()
    found = await rr.read_record_classes(_run_select_over(_graph(TOWER)))
    assert [(r.local_name, r.instances) for r in found] == [("TestDeskProfile", 4)]
    assert rr._ID_PREFIXES == {} and rr._CACHE == {}


async def test_a_catalogue_is_cached_per_building_and_a_partial_one_is_not():
    g = _graph(TOWER)
    exec_ = _sparql_json(g)

    async def build(executor) -> facets.FacetCatalogue:
        return await facets.build_facet_catalogue(
            executor, "towerX", NS_A, [NOISE], modality_config={}, events_store=False
        )

    first = await build(exec_)
    assert await build(exec_) is first
    facets.clear_cache()
    rebuilt = await build(exec_)
    assert rebuilt is not first and [f.key for f in rebuilt] == [f.key for f in first]

    async def space_profile_down(query: str) -> Dict[str, Any]:
        if "?carriers" in query and "brick:Space" in query:
            raise RuntimeError("graph unavailable")
        return await exec_(query)

    facets.clear_cache()
    partial = await build(space_profile_down)
    assert partial.errors and partial.errors[0].startswith("ttl")
    assert partial.get("sensor:noise") is not None, "one source failing costs only its facets"
    assert await build(exec_) is not partial, "a partial catalogue is never served twice"


def test_the_value_type_comes_from_the_data_and_is_checked_against_the_declaration():
    xsd = "http://www.w3.org/2001/XMLSchema#"
    assert facets._value_type([xsd + "integer", xsd + "decimal"], None, False, 3, 3)[0] == "number"
    vt, typed, notes = facets._value_type(
        [xsd + "integer", xsd + "string"], "xsd:integer", False, 2, 2
    )
    assert (vt, typed) == ("integer", False) and notes
    vt, typed, notes = facets._value_type([xsd + "date"], "xsd:string", False, 4, 4)
    assert (vt, typed) == ("datetime", True) and "declared xsd:string" in notes[0]
    repeated_labels = ["red", "blue"]
    assert facets._value_type([xsd + "string"], None, False, 2, 6, repeated_labels)[0] == "enum"
    prose = ["a long note that is plainly a sentence and not a category label at all, " * 2]
    assert facets._value_type([xsd + "string"], None, False, 1, 6, prose)[0] == "text"
    assert facets._value_type([xsd + "string"], None, True, 9, 9)[0] == "enum"
    assert facets._unit_from_name("allowMinutes", "integer") == "minutes"
    assert facets._unit_from_name("openingHours", "enum") is None


# ── 5. the parked buildings' own files ───────────────────────────────────────────────


def _building_folder(building_id: str) -> Optional[Path]:
    """The building's files, parked under its id or active under input/; None when absent."""
    parked = REPO / building_id
    if (parked / "env.building").is_file():
        return parked
    active = REPO / "input" / "env.building"
    if active.is_file() and f"BUILDING_ID={building_id}" in active.read_text(encoding="utf-8"):
        return active.parent
    return None


def _namespace(folder: Path) -> str:
    for line in (folder / "env.building").read_text(encoding="utf-8").splitlines():
        if line.startswith("BUILDING_NAMESPACE="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"no namespace in {folder / 'env.building'}")


def _modalities(folder: Path, scratch: Path):
    """The shared modality config merged with the building's overlay, as load_modalities reads it."""
    merged: Dict[str, Any] = {}
    for path in (
        REPO / "config" / "saturation_modalities.yaml",
        folder / "saturation_modalities.yaml",
    ):
        if path.is_file():
            merged.update(
                (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("modalities") or {}
            )
    config = scratch / "saturation_modalities.yaml"
    config.write_text(yaml.safe_dump({"modalities": merged}), encoding="utf-8")
    return load_modalities(config_path=config), load_modality_raw(config_path=config)


def _real_catalogue(building_id: str, scratch: Path) -> facets.FacetCatalogue:
    from orchestrator.services.event_query_service import EVENTS_STORE_KEY
    from orchestrator.services.record_documents import lift_document, to_turtle
    from orchestrator.services.record_entity_links import load_place_index
    from scripts.register_reach import events_store_registered

    folder = _building_folder(building_id)
    if folder is None:
        pytest.skip(f"{building_id}'s files are neither parked nor active in this checkout")
    namespace = _namespace(folder)
    g = rdflib.Graph()
    for path in sorted(folder.glob("*.ttl")):
        g.parse(str(path), format="turtle")
    # The shared ontology every building's repository is loaded with.
    for name in ("ontosage_schema.ttl", "hbco_core.ttl", "hbco_mappings.ttl"):
        g.parse(str(REPO / "ontology" / name), format="turtle")
    # The registers, lifted and LINKED in-process exactly as the indexer lifts them.
    places = asyncio.run(load_place_index(namespace, _run_select_over(g)))
    for doc in sorted((folder / "documents").glob("*.md")):
        result = lift_document(
            doc, namespace, REPO / "ontology" / "record_documents", places=places
        )
        if result.ok:
            g.parse(data=to_turtle(result), format="turtle")
    modalities, raw = _modalities(folder, scratch)
    facets.clear_cache()
    return asyncio.run(
        facets.build_facet_catalogue(
            _sparql_json(g),
            building_id,
            namespace,
            modalities,
            modality_config=raw,
            events_store=events_store_registered(folder, EVENTS_STORE_KEY),
        )
    )


@pytest.fixture(scope="module")
def first_building(tmp_path_factory):
    return _real_catalogue("bldg1", tmp_path_factory.mktemp("facets_first"))


@pytest.fixture(scope="module")
def second_building(tmp_path_factory):
    return _real_catalogue("bldg2", tmp_path_factory.mktemp("facets_second"))


def test_a_real_building_has_a_facet_for_each_kind_of_criterion_on_its_spaces(first_building):
    cat = first_building
    assert cat.errors == ()
    space = {f.key: f for f in cat.for_entity("space")}
    assert space["sensor:co2"].status == "suitable"
    seats = space["record:WorkspaceProfile.seatCount"]
    assert (seats.value_type, seats.status, seats.join_predicate) == (
        "integer",
        "suitable",
        LOCATED_IN,
    )
    av = [f for f in space.values() if f.record_class == "AVReadiness"]
    assert av and all(f.join_predicate == LOCATED_IN for f in av)
    assert any(f.status == "suitable" for f in av)
    capacity = space["ttl:capacity"]
    assert (capacity.status, capacity.unit) == ("suitable", "persons") and capacity.coverage > 0
    assert space["spatial:floor"].status == "suitable"
    # every facet's coverage is an entity count the building can actually have
    assert all(f.coverage <= cat.entity_counts["space"] for f in space.values())


def test_a_second_real_building_needs_no_code_change(second_building):
    cat = second_building
    assert cat.errors == ()
    space = cat.for_entity("space")
    assert space and any(f.status == "suitable" for f in space)
    assert any(f.source_kind == "sensor" for f in space)
