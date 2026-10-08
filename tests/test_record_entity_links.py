# -*- coding: utf-8 -*-
"""A register's location text is linked to the building's own spaces and floors (v2, P1).

Records said where they were in WORDS -- ``ontosage:locationText "Room 1.06 - ..."`` -- while
every sensor is keyed by the room's IRI, so "a room that seats twelve AND is quiet" had no join
in the graph. The lift now writes an object link beside the text, and only when the text names
exactly one space or floor. These tests pin the rule (dotted id, then exact label, then floor),
the refusals (ambiguous, unknown, a room named as a reference point), that the text predicates
are untouched, that the rule works for a building it has never seen, and that the links stay
out of the places that read a record's FIELDS.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import rdflib
import yaml

from orchestrator.services import record_entity_links as rel
from orchestrator.services.record_documents import lift_document, load_mapping, to_turtle

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
MAPPINGS = REPO / "ontology" / "record_documents"
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
ONTO = "http://ontosage.org/capabilities#"
BRICK = "https://brickschema.org/schema/Brick#"

#: Deliberately not any real building's namespace: the rule must work for one it has never seen.
NS = "http://example.org/towerX#"

LOCATED_IN = rel.LINK_PREDICATES["located_in"]
FLOOR = rel.FLOOR_PREDICATE


def _index(spaces=(), floors=()) -> rel.PlaceIndex:
    """An index from (local, label) spaces and (local, label, level-or-None) floors."""
    rows: List[Dict[str, Any]] = []
    for local, label in spaces:
        rows.append({"place": NS + local, "kind": "space", "label": label, "level": None})
    for local, label, level in floors:
        rows.append({"place": NS + local, "kind": "floor", "label": label, "level": level})
    return rel.PlaceIndex.from_rows(NS, rows)


ROOMS = _index(
    spaces=[
        ("Room1.06", "Room 1.06 — Computer Laboratory"),
        ("Room1.07", "Room 1.07 — Computer Laboratory"),
        ("Room2.01", "Room 2.01 — Research Laboratory"),
        ("Room5.03", "Room 5.03 — Research Laboratory"),
        ("Room4.44", "Room 4.44 — Server Room"),
        # a sub-space whose label MENTIONS its parent's number; it must not claim it
        ("Server_Room_F4", "Server Room — Floor 4 (Room 4.44)"),
        ("Stairwell_North", "North Stairwell — Fire Escape Route"),
        ("Quiet_A", "Quiet Room"),
        ("Quiet_B", "Quiet Room"),
    ],
    floors=[
        ("Floor0", "Floor 0 (Ground Floor)", None),
        ("Floor1", "Floor 1 (First Floor)", None),
        ("Floor2", "Floor 2 (Second Floor)", None),
        ("Mezzanine", "Mezzanine", "3"),  # numbered ONLY by its declared rec:levelNumber
    ],
)


# ── the rule ───────────────────────────────────────────────────────────────────────


def test_a_dotted_room_id_links_to_the_one_space_that_carries_it():
    out = ROOMS.resolve("Room 1.06 — Computer Laboratory", "located_in")
    assert (out.target, out.target_kind, out.rule) == (NS + "Room1.06", "space", "dotted_id")
    # the id may close a longer first clause, as in a work order naming the unit in the room
    assert ROOMS.resolve("Fan Coil Unit Room 5.03", "located_in").target == NS + "Room5.03"


def test_an_exact_label_links_when_the_text_names_no_room_id():
    # the document writes a hyphen where the building's label has an em dash
    out = ROOMS.resolve("North Stairwell - Fire Escape Route", "located_in")
    assert (out.target, out.rule) == (NS + "Stairwell_North", "label")
    assert not ROOMS.resolve("North Stairwell", "located_in").linked, "a prefix is not a match"


def test_a_sub_space_that_mentions_its_parent_does_not_claim_the_parents_number():
    assert ROOMS.space_ids["4.44"] == (NS + "Room4.44",)
    assert ROOMS.resolve("Room 4.44 — Server Room", "located_in").target == NS + "Room4.44"
    sub = ROOMS.resolve("Server Room — Floor 4 (Room 4.44)", "located_in")
    assert (sub.target, sub.rule) == (NS + "Server_Room_F4", "label")


def test_an_ambiguous_label_is_left_unlinked_with_its_reason():
    out = ROOMS.resolve("Quiet Room", "located_in")
    assert not out.linked
    assert out.reason == "matches the label of 2 spaces"


def test_an_unknown_room_is_left_unlinked_never_guessed():
    out = ROOMS.resolve("Room 9.99 — Nowhere", "located_in")
    assert not out.linked and "9.99" in out.reason
    # a nearby id is not a match: 1.6 is not 1.06
    assert not ROOMS.resolve("Room 1.6", "located_in").linked
    assert not ROOMS.resolve("Level 1 riser cupboard", "located_in").linked


def test_a_room_named_as_a_reference_point_is_not_the_location():
    outside = ROOMS.resolve("Corridor outside 2.01", "located_in")
    assert not outside.linked and "reference point" in outside.reason
    after = ROOMS.resolve("2.01 adjacent corridor", "located_in")
    assert not after.linked and "longer description" in after.reason


def test_two_rooms_in_one_value_are_not_linked():
    out = ROOMS.resolve("Rooms 1.06 and 1.07", "located_in")
    assert not out.linked and out.reason == "names 2 rooms (1.06, 1.07)"


def test_a_floor_text_links_to_the_one_floor_numbered_so():
    assert ROOMS.resolve("1", "on_floor").target == NS + "Floor1"
    assert ROOMS.resolve("Level 2", "on_floor").target == NS + "Floor2"
    # a declared rec:levelNumber is the number, whatever the name says
    assert ROOMS.resolve("3", "on_floor").target == NS + "Mezzanine"
    missing = ROOMS.resolve("7", "on_floor")
    assert not missing.linked and missing.reason == "no floor is numbered 7"
    # "Ground" is a word, not a number, and no floor is LABELLED exactly "Ground"
    assert not ROOMS.resolve("Ground", "on_floor").linked


def test_a_location_that_names_a_whole_floor_is_linked_as_a_floor_not_a_space():
    out = ROOMS.resolve("Level 2", "located_in")
    assert (out.target, out.target_kind) == (NS + "Floor2", "floor")
    assert rel.link_predicate("located_in", out.target_kind) == FLOOR
    assert not ROOMS.resolve("Level 2 riser cupboard", "located_in").linked


def test_route_endpoints_link_only_to_spaces():
    assert ROOMS.resolve("Room 2.01 — Research Laboratory", "route_to").target == NS + "Room2.01"
    assert not ROOMS.resolve("Cathays railway station", "route_from").linked
    assert not ROOMS.resolve("Level 2", "route_to").linked, "a route ends at a space"


def test_a_room_described_differently_is_linked_by_id_and_the_difference_is_reported():
    out = ROOMS.resolve("Room 1.06 — Quiet Room", "located_in")
    assert out.target == NS + "Room1.06"
    assert "Quiet Room" in out.note and "Computer Laboratory" in out.note


# ── a building the rule has never seen, through the real query ─────────────────────

_TBOX = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Office rdfs:subClassOf brick:Room .
brick:Laboratory rdfs:subClassOf brick:Room .
brick:Floor rdfs:subClassOf brick:Location .
brick:Zone rdfs:subClassOf brick:Location .
brick:HVAC_Zone rdfs:subClassOf brick:Zone .
"""

_TOWER = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix x: <http://example.org/towerX#> .
@prefix y: <http://example.org/otherSite#> .
x:L7 a brick:Floor ; rdfs:label "Level 7 (Upper Floor)" .
x:R701 a brick:Office ; rdfs:label "Room 7.01 — Team Office" ; brick:isPartOf x:L7 .
x:R702 a brick:Laboratory ; rdfs:label "Room 7.02 — Wet Lab" ; brick:isPartOf x:L7 .
x:Z702 a brick:HVAC_Zone ; rdfs:label "HVAC Zone 7.02" .
y:R702 a brick:Laboratory ; rdfs:label "Room 7.02 — Elsewhere" .
"""


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=_TBOX, format="turtle")
    g.parse(data=_TOWER, format="turtle")
    return g


def _run_select_over(g: rdflib.Graph):
    async def run_select(query: str, limit: int = 1000) -> Dict[str, Any]:
        res = g.query(query)
        rows = [{str(v): (str(b[v]) if b[v] is not None else None) for v in res.vars} for b in res]
        return {"ok": True, "rows": rows}

    return run_select


def _tower_index() -> rel.PlaceIndex:
    index = asyncio.run(rel.load_place_index(NS, _run_select_over(_graph())))
    assert index is not None
    return index


def test_the_real_query_reads_spaces_and_floors_of_this_building_only():
    index = _tower_index()
    assert (index.spaces, index.floors) == (2, 1)
    # the zone sharing a room's number is not a space, and another site's 7.02 is not ours
    assert index.space_ids["7.02"] == (NS + "R702",)
    assert index.floor_numbers == {7: (NS + "L7",)}


_SITE_MAPPING = {
    "record_type": "site_note",
    "class": "ontosage:SiteNote",
    "iri_template": "note/{code}",
    "columns": {
        "code": {"predicate": "ontosage:recordId", "required": True},
        "room": {"predicate": "ontosage:locationText", "link": "located_in"},
        "floor": {"predicate": "ontosage:onFloor", "link": "on_floor"},
        "from_point": {"predicate": "ontosage:routeFrom", "link": "route_from"},
        "to_point": {"predicate": "ontosage:routeTo", "link": "route_to"},
        "status": {"predicate": "ontosage:recordStatus"},
    },
}

_FRONT = """---
record_type: site_note
owner: Estates
authority: Estates
source_system: test
effective_from: 2026-01-01
version: 1
tables:
  - name: Notes
    maps_to: ontosage:SiteNote
---

# Notes

"""


def _lift(tmp_path: Path, rows: str, places, mapping: Dict[str, Any] = None):
    mappings = tmp_path / "mappings"
    mappings.mkdir(exist_ok=True)
    spec = mapping or _SITE_MAPPING
    (mappings / f"{spec['record_type']}.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    doc = tmp_path / "site_notes.md"
    header = "| code | room | floor | from_point | to_point | status |\n|---|---|---|---|---|---|\n"
    doc.write_text(_FRONT + header + rows, encoding="utf-8")
    return lift_document(doc, NS, mappings, places=places)


_ROWS = (
    "| N-1 | Room 7.02 — Wet Lab | 7 | Railway station | Room 7.01 — Team Office | open |\n"
    "| N-2 | Corridor outside 7.01 | 7 |  |  | open |\n"
    "| N-3 | Room 9.99 — Nowhere | 9 |  |  | open |\n"
)


def test_a_record_of_an_unseen_building_is_linked_through_its_own_graph(tmp_path):
    result = _lift(tmp_path, _ROWS, _tower_index())
    assert result.ok, result.errors
    n1 = NS + "note/N-1"
    assert (n1, LOCATED_IN, NS + "R702") in result.triples
    assert (n1, FLOOR, NS + "L7") in result.triples
    assert (n1, rel.LINK_PREDICATES["route_to"], NS + "R701") in result.triples
    assert not any(s == n1 and p == rel.LINK_PREDICATES["route_from"] for s, p, _ in result.triples)
    n2, n3 = NS + "note/N-2", NS + "note/N-3"
    assert not any(s == n2 and p == LOCATED_IN for s, p, _ in result.triples)
    assert (n2, FLOOR, NS + "L7") in result.triples
    assert not any(s == n3 and p in rel.LINK_PREDICATE_IRIS for s, p, _ in result.triples)
    # every value that named nothing exactly is listed, with its reason
    unresolved = {(u.column, u.value) for u in result.unresolved}
    assert unresolved == {
        ("from_point", "Railway station"),
        ("room", "Corridor outside 7.01"),
        ("room", "Room 9.99 — Nowhere"),
        ("floor", "9"),
    }
    assert result.links == 4 and result.links_attempted


def test_the_text_predicates_are_still_written_beside_the_links(tmp_path):
    linked = _lift(tmp_path, _ROWS, _tower_index())
    plain = _lift(tmp_path, _ROWS, None)
    assert plain.ok and not plain.links_attempted and plain.links == 0
    n1 = NS + "note/N-1"
    assert (n1, ONTO + "locationText", "Room 7.02 — Wet Lab") in linked.triples
    assert (n1, ONTO + "onFloor", "7") in linked.triples

    def stable(result):
        return {t for t in result.triples if not t[1].endswith("retrievedAt")}

    # linking ADDS the link triples and changes nothing else
    assert stable(linked) - stable(plain) == linked.link_triples
    assert stable(plain) <= stable(linked)


def test_the_links_serialise_as_nodes_not_strings(tmp_path):
    result = _lift(tmp_path, _ROWS, _tower_index())
    g = rdflib.Graph()
    g.parse(data=to_turtle(result), format="turtle")
    obj = g.value(rdflib.URIRef(NS + "note/N-1"), rdflib.URIRef(LOCATED_IN))
    assert isinstance(obj, rdflib.URIRef) and str(obj) == NS + "R702"


def test_columns_naming_different_floors_link_neither(tmp_path):
    index = _index(
        floors=[("F7", "Floor 7", None), ("F8", "Floor 8", None)],
    )
    rows = "| N-9 | Level 7 | 8 |  |  | open |\n"
    result = _lift(tmp_path, rows, index)
    assert result.ok
    assert not any(p == FLOOR for _, p, _ in result.triples)
    assert any(u.reason == "its columns name different floors" for u in result.unresolved)


def test_an_unknown_link_kind_fails_the_lift_loudly(tmp_path):
    bad = dict(_SITE_MAPPING)
    bad["columns"] = dict(_SITE_MAPPING["columns"])
    bad["columns"]["room"] = {"predicate": "ontosage:locationText", "link": "near_to"}
    result = _lift(tmp_path, _ROWS, _tower_index(), mapping=bad)
    assert not result.ok and "near_to" in result.errors[0]
    assert not result.unresolved, "a lift that wrote nothing reports nothing as unlinked"


# ── loading never yields a half-read index ─────────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        RuntimeError("graph down"),
        {"ok": False, "error": "HTTP 500", "rows": []},
        {"ok": True, "rows": []},
        {"ok": True, "rows": [{"place": NS + "R", "kind": "space", "label": "x"}] * 5},
    ],
    ids=["raises", "not-ok", "empty", "hit-the-limit"],
)
def test_an_unusable_read_means_no_links_are_attempted(answer):
    async def run_select(query: str, limit: int = 1000):
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert asyncio.run(rel.load_place_index(NS, run_select, limit=5)) is None


# ── the mappings and the schema ────────────────────────────────────────────────────

_TEXT_TO_LINK = {
    "ontosage:locationText": "located_in",
    "ontosage:onFloor": "on_floor",
    "ontosage:routeFrom": "route_from",
    "ontosage:routeTo": "route_to",
    "ontosage:servesArea": "serves",
}


def test_every_shipped_location_column_declares_its_link():
    declared = 0
    for path in sorted(MAPPINGS.glob("*.yaml")):
        mapping = load_mapping(path.stem, MAPPINGS)
        for column, spec in mapping.columns.items():
            assert not spec.link or spec.link in rel.LINK_KINDS, (path.name, column, spec.link)
            want = _TEXT_TO_LINK.get(spec.predicate, "")
            assert spec.link == want, f"{path.name}:{column} ({spec.predicate}) link={spec.link!r}"
            declared += bool(want)
    assert declared == 30, declared


def test_the_schema_declares_every_link_with_no_domain():
    g = rdflib.Graph()
    g.parse(str(SCHEMA), format="turtle")
    rdfs, owl = rdflib.RDFS, rdflib.OWL
    for iri in rel.LINK_PREDICATE_IRIS:
        p = rdflib.URIRef(iri)
        assert (p, rdflib.RDF.type, owl.ObjectProperty) in g, iri
        assert g.value(p, rdfs.label) and g.value(p, rdfs.comment), iri
        # a domain would TYPE every linked record under the repository's rdfs reasoning
        assert g.value(p, rdfs.domain) is None, iri
        assert g.value(p, rdfs.range) == rdflib.URIRef(BRICK + "Location"), iri


def test_the_links_are_not_the_capability_or_served_zone_properties():
    """Both exist with an rdfs:domain; on a record they would make it a capability or a space."""
    assert ONTO + "locatedIn" not in rel.LINK_PREDICATE_IRIS
    assert ONTO + "servesSpace" not in rel.LINK_PREDICATE_IRIS


# ── the links stay out of a record's FIELDS ────────────────────────────────────────


def test_the_exclusion_filter_is_valid_sparql_and_drops_only_the_links():
    g = rdflib.Graph()
    rec = rdflib.URIRef(NS + "note/N-1")
    g.add((rec, rdflib.URIRef(ONTO + "onFloor"), rdflib.Literal("7")))
    g.add((rec, rdflib.URIRef(FLOOR), rdflib.URIRef(NS + "L7")))
    g.add((rec, rdflib.URIRef(LOCATED_IN), rdflib.URIRef(NS + "R702")))
    rows = g.query(f"SELECT ?p WHERE {{ ?r ?p ?v . {rel.exclude_link_predicates('?p')} }}")
    assert {str(r[0]) for r in rows} == {ONTO + "onFloor"}


def test_which_floors_still_groups_by_one_field_when_records_carry_floor_links(monkeypatch):
    """The grouping declines unless EXACTLY one field matches; onFloorEntity must not be one."""
    from orchestrator.agents.sparql_agent import SPARQLAgent
    from orchestrator.services import record_registry

    g = rdflib.Graph()
    cls = rdflib.URIRef(ONTO + "TimetabledSession")
    for i, floor in enumerate(["1", "1", "2"]):
        rec = rdflib.URIRef(f"{NS}session/S{i}")
        g.add((rec, rdflib.RDF.type, cls))
        g.add((rec, rdflib.URIRef(ONTO + "onFloor"), rdflib.Literal(floor)))
        g.add((rec, rdflib.URIRef(FLOOR), rdflib.URIRef(f"{NS}Floor{floor}")))

    asked: List[str] = []
    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _execute(query: str, *a, **k):
        asked.append(query)
        res = g.query(query)
        bindings = []
        for row in res:
            b = {}
            for var in res.vars:
                val = row[var]
                if val is not None:
                    kind = "uri" if isinstance(val, rdflib.URIRef) else "literal"
                    b[str(var)] = {"type": kind, "value": str(val)}
            bindings.append(b)
        return {"head": {"vars": [str(v) for v in res.vars]}, "results": {"bindings": bindings}}

    async def _format(*a, **k):
        raise AssertionError("the graph counted the groups; the model must not be asked")

    agent._execute_query = _execute
    agent._format_results = _format
    record = record_registry.RecordClass(
        "TimetabledSession",
        "Timetabled session",
        675,
        record_registry._terms_for(
            "TimetabledSession", "Timetabled session", "teaching session|teaching sessions"
        ),
    )

    async def _classes(namespace: str = ""):
        return [record]

    monkeypatch.setattr(record_registry, "record_classes", _classes)
    state = SimpleNamespace(building_id=None, intermediate_results={})
    result = asyncio.run(
        agent._whole_register(state, "Which floors have teaching sessions this week?")
    )
    # Grouped by the graph in ONE query. Without the exclusion the grouping matches two fields,
    # declines, and the lane falls through to reading the whole register.
    assert result is not None and result["formatted_response"].startswith("**2 floors"), result
    assert len(asked) == 1 and "NOT IN" in asked[0] and FLOOR in asked[0], asked


def test_every_place_that_reads_a_records_fields_excludes_the_links():
    from orchestrator.agents.sparql_agent import SPARQLAgent
    from orchestrator.services import absence_second_chance

    whole = inspect.getsource(SPARQLAgent._whole_register)
    assert whole.count("exclude_link_predicates(") >= 2, "the scope clause and the fetch"
    for fn in (SPARQLAgent._register_projected_whole, SPARQLAgent._register_grouping):
        assert "exclude_link_predicates(" in inspect.getsource(fn), fn.__name__
    assert "exclude_link_predicates(" in inspect.getsource(absence_second_chance)


# ── the indexer re-lifts a register whose links are stale ───────────────────────────


def _indexer():
    from orchestrator.services.document_indexer import DocumentIndexer

    return DocumentIndexer(qdrant_client=None, embedding_service=None)


@pytest.mark.parametrize(
    "has_triples, attempted, held, current",
    [
        (False, True, set(), False),  # empty graph: lift it
        (True, False, set(), True),  # no place index this run: leave the graph alone
        (True, True, None, True),  # links unreadable: leave it alone
        (True, True, {("s", "p", "o")}, True),  # holds exactly what this lift writes
        (True, True, set(), False),  # lifted before linking existed: re-lift
    ],
    ids=["empty", "not-attempted", "unreadable", "current", "stale"],
)
def test_a_sha_skipped_register_is_relifted_only_when_its_links_differ(
    monkeypatch, has_triples, attempted, held, current
):
    indexer = _indexer()

    async def _has(graph_iri):
        return has_triples

    async def _held(graph_iri, limit):
        return held

    monkeypatch.setattr(indexer, "_graph_has_triples", _has)
    monkeypatch.setattr(indexer, "_graph_link_triples", _held)
    result = SimpleNamespace(
        graph_iri="g",
        document="d.md",
        links_attempted=attempted,
        link_triples={("s", "p", "o")},
    )
    assert asyncio.run(indexer._graph_is_current(result)) is current


def test_the_place_index_is_read_once_per_indexing_run(monkeypatch, tmp_path):
    calls: List[str] = []

    async def _load(namespace, run_select):
        calls.append(namespace)
        return None

    monkeypatch.setattr(rel, "load_place_index", _load)
    indexer = _indexer()
    asyncio.run(indexer._places_for_run(NS))
    asyncio.run(indexer._places_for_run(NS))
    assert calls == [NS]
    indexer._input_root = tmp_path  # no documents: the run returns early, after resetting
    asyncio.run(indexer.index_building("towerX"))
    asyncio.run(indexer._places_for_run(NS))
    assert calls == [NS, NS]
