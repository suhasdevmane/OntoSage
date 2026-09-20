# -*- coding: utf-8 -*-
"""The muster point, the car park and the store (wave 4).

    "is there a muster point outside the building?" -> the whole fire-safety paragraph
    "Are there free parking spaces available now?"  -> declined
    "Where is the nearest authorised store ...?"    -> the floor-plan menu

Three different faults with one shape: the building holds the fact and no INSTANCE carried it.

The assembly point is SAFETY-CRITICAL, and is recorded anyway because it was not invented: the
building publishes it twice, in the same words ("the open area on Senghennydd Road directly outside
the main entrance"). These tests pin that the record says exactly that and no more — no floor, no
room, no distance — and that it carries no simulated flag, because flagging it would claim the
building had not stated it.

Parking is the opposite discipline: the place is recorded, the free-bay COUNT is not copied into
it. A count written into a record is stale the moment it is written; the building measures it at a
point of its own.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_NS = "http://ontosage.org/capabilities#"
_REPO = Path(__file__).resolve().parents[1]
# The active building's file, else the PARKED copy: the committed tree has no `input/` (Workflow
# rule 8), so a fresh clone and CI read this from `bldg1/`.
_INPUT = next(
    (p for p in (_REPO / "input" / "bldg1_amenity_stated.ttl", _REPO / "bldg1" / "bldg1_amenity_stated.ttl") if p.is_file()),
    _REPO / "input" / "bldg1_amenity_stated.ttl",
)
_SCHEMA = Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl"


def _graph(path: Path):
    from rdflib import Graph

    g = Graph()
    g.parse(str(path), format="turtle")
    return g


def _one(g, local: str):
    from rdflib import URIRef

    ns = "http://abacwsbuilding.cardiff.ac.uk/abacws#"
    subject = URIRef(ns + local)
    return {str(p).rsplit("#", 1)[-1]: str(o) for p, o in g.predicate_objects(subject)}


# -- the safety place ------------------------------------------------------------------------------
def test_the_assembly_point_says_what_the_building_says_and_nothing_more():
    facts = _one(_graph(_INPUT), "AssemblyPoint_SenghennyddRoad")
    assert facts, "no assembly-point instance"
    where = facts["locationText"]
    assert where == "The open area on Senghennydd Road, directly outside the main entrance"
    # NOTHING the building did not state: no floor, no room, no metres, no compass direction.
    for invented in ("floor", "room", " m ", "metre", "north", "south", "east", "west"):
        assert invented not in where.lower(), f"{invented!r} is not in the building's own words"
    assert "onFloor" not in facts, "it is outside; a floor would be invented"
    assert "locatedIn" not in facts


def test_the_assembly_point_is_not_flagged_simulated_because_the_building_states_it():
    facts = _one(_graph(_INPUT), "AssemblyPoint_SenghennyddRoad")
    assert "isSimulated" not in facts
    assert "transcribed" in facts["comment"].lower()


def test_the_assembly_point_answer_still_carries_the_actions_a_reader_needs():
    answer = _one(_graph(_INPUT), "AssemblyPoint_SenghennyddRoad")["answerText"]
    assert "do not use the lifts" in answer.lower()
    assert "fire warden" in answer.lower()


def test_its_vocabulary_asks_where_and_leaves_the_procedure_to_the_procedure():
    terms = {
        t.strip()
        for t in _one(_graph(_INPUT), "AssemblyPoint_SenghennyddRoad")["layTerms"].split(",")
    }
    assert "assembly point" in terms and "muster point" in terms
    for procedural in ("evacuation", "fire", "emergency", "refuge", "peep"):
        assert not any(procedural == t for t in terms), f"{procedural!r} belongs to the procedure"


# -- the count that is not copied -------------------------------------------------------------------
def test_the_car_park_records_the_place_and_never_a_free_bay_count():
    import re

    facts = _one(_graph(_INPUT), "Amenity_Parking_GroundLevel")
    assert facts, "no parking instance"
    answer = facts["answerText"]
    assert "measured separately" in answer
    # the only number allowed is the EV charger count the graph itself holds
    numbers = set(re.findall(r"\b\d+\b", answer))
    assert numbers <= {"6"}, f"a count was copied into the record: {numbers}"
    assert "six electric-vehicle charging stations" in answer
    assert facts["locatedIn"].endswith("#Parking_Level_Ground")


def test_the_parking_vocabulary_has_no_bare_parking_word():
    """'parking' alone appears in questions about cameras, permits and bicycles."""
    schema = _graph(_SCHEMA)
    from rdflib import Namespace, URIRef

    o = Namespace(_NS)
    terms = {
        t.strip().lower()
        for v in schema.objects(URIRef(_NS + "ParkingArea"), o.layTerms)
        for t in str(v).split(",")
    }
    assert terms, "the class declares no lay terms"
    assert "parking" not in terms
    assert "car park" in terms and "where can i park" in terms


def test_both_new_kinds_are_amenity_subclasses():
    from rdflib import RDFS, URIRef

    schema = _graph(_SCHEMA)
    for local in ("AssemblyPoint", "ParkingArea"):
        parents = {str(p) for p in schema.objects(URIRef(_NS + local), RDFS.subClassOf)}
        assert _NS + "Amenity" in parents, f"{local} is not an Amenity"


# -- the store ---------------------------------------------------------------------------------------
def test_a_reader_who_says_store_reaches_the_rooms_the_building_calls_storage():
    from orchestrator.services.room_type_lookup import tokens

    assert tokens("store") == tokens("Storage Room") == frozenset({"storage"})
    assert tokens("stores") == tokens("storeroom") == frozenset({"storage"})


def test_the_nearest_store_is_a_kind_the_spatial_lane_knows():
    from orchestrator.agents.spatial_agent import kind_words_for_target

    assert "storage" in kind_words_for_target("Where is the nearest store?")
    assert "storage" in kind_words_for_target("nearest storeroom to room 3.01")
    assert kind_words_for_target("Where is the nearest toilet?") == {"toilet"}


@pytest.mark.asyncio
async def test_storing_something_is_not_a_question_about_a_storeroom():
    """'store' is also a verb, and a verb reading leaves content words over."""
    from orchestrator.services import room_type_lookup as rtl

    rows = [
        {
            "r": {"value": "x#Room0.29"},
            "l": {"value": "Room 0.29 — Storage Room"},
            "f": {"value": "x#Floor0"},
            "fl": {"value": "Floor 0"},
            "types": {"value": "https://brickschema.org/schema/Brick#Storage_Room"},
        }
    ]

    async def _exec(_q):
        return {"results": {"bindings": rows}}

    assert await rtl.answer("Do you store conversations between sessions?", _exec) is None
    assert "Room 0.29" in (await rtl.answer("Where is the store?", _exec) or "")
