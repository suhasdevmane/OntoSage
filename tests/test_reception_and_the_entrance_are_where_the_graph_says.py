# -*- coding: utf-8 -*-
"""'How do I get to the lifts from the entrance?' answered 'Reception's floor (floor 4)'.

The building's reception is Room 0.01 (Main Reception, floor 0, brick:Reception) and its own text
says "Ground Floor, main entrance". The floor-4 plan carries two labels the PDF text extraction read
off the drawing -- "Reception" and "Main Entrance", no polygon, no area, no ontology IRI -- and
nothing on floor 0 was typed `reception` in the manifest, so the spatial lane's default starting
point and every lookup of the word "reception" found floor 4.

These tests pin the graph as the authority for WHICH FLOOR a named place is on: a place a question
names resolves to the single graph space of that kind, an ambiguous name resolves to nothing, and a
drawing's stray text never outranks a room the graph places.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services import place_anchor as pa
from orchestrator.services.room_type_lookup import RoomRecord

pytestmark = pytest.mark.unit

_NS = "http://example.org/b#"


def _room(name, label, floor, *classes):
    return RoomRecord(
        iri=f"{_NS}{name}",
        label=label,
        floor=floor,
        floor_label=f"Floor {floor}",
        classes=tuple(classes),
    )


ROOMS = [
    _room("Room0.01", "Room 0.01 — Main Reception", 0, "Reception"),
    _room("Main_Entrance_Zone", "Main Entrance Zone — Ground Floor", 0),
    _room("Room1.06", "Room 1.06 — Computer Laboratory", 1, "Laboratory"),
    _room("Room1.07", "Room 1.07 — Computer Laboratory", 1, "Laboratory"),
    _room("Room2.44", "Room 2.44 — Server Room", 2, "Server_Room"),
    _room("Room4.44", "Room 4.44 — Server Room", 4, "Server_Room"),
    _room("Room1.04", "Room 1.04 — Common Area / Atrium", 1),
]


def _space(zone, iri=None, area=None, label=None, stype="zone"):
    return SimpleNamespace(
        zone_id=zone, ontology_iri=iri, area_m2=area, label=label or zone, type=stype
    )


#: The manifests as they are: a drawn Room 0.01 on floor 0 typed `zone`, and floor-4 text labels
#: typed `reception` that carry no IRI.
MANIFESTS = [
    SimpleNamespace(floor=0, spaces=[_space("0.01", f"{_NS}Room0.01", 184.5)]),
    SimpleNamespace(
        floor=4,
        spaces=[
            _space("fp.4.reception", None, None, "Reception", "reception"),
            _space("fp.4.main_entrance", None, None, "Main Entrance", "reception"),
        ],
    ),
]


# -- the defect ------------------------------------------------------------------------------------
def test_reception_is_the_graphs_reception_on_floor_0_not_the_drawings_text_on_floor_4():
    a = pa.resolve("Where is the nearest lift to reception?", ROOMS, MANIFESTS)
    assert a is not None and a.floor == 0
    assert a.zone_id == "0.01", "mapped to the drawn zone that carries the same ontology IRI"
    assert a.label == "Room 0.01"


def test_the_entrance_resolves_to_the_main_entrance_zone_on_the_ground_floor():
    a = pa.resolve("How do I get to the lifts from the entrance?", ROOMS, MANIFESTS)
    assert a is not None and a.floor == 0
    assert a.label == "Main Entrance Zone", "its KIND; the floor is stated once, by the answer"
    assert a.zone_id is None, "the plans do not draw it, and no zone is invented"


def test_the_default_start_is_the_entry_space_on_the_lowest_floor_that_the_plans_also_draw():
    a = pa.entrance_of(ROOMS, MANIFESTS)
    assert a is not None and a.floor == 0 and a.zone_id == "0.01"


def test_with_nothing_drawn_the_default_start_is_still_the_lowest_entry_space():
    a = pa.entrance_of(ROOMS, [])
    assert a is not None and a.floor == 0


def test_a_building_with_no_entry_space_has_no_default_start():
    assert pa.entrance_of([r for r in ROOMS if r.floor != 0], MANIFESTS) is None


# -- what must not resolve ---------------------------------------------------------------------------
def test_two_spaces_of_one_kind_are_ambiguous_and_resolve_to_nothing():
    assert pa.resolve("nearest toilet to the server room", ROOMS, MANIFESTS) is None
    assert pa.resolve("nearest lift to the computer laboratory", ROOMS, MANIFESTS) is None


def test_a_differently_qualified_place_is_not_the_one_the_building_has():
    """'the west entrance' is not the Main Entrance."""
    assert pa.resolve("nearest lift to the west entrance", ROOMS, MANIFESTS) is None
    assert pa.resolve("nearest lift to the main entrance", ROOMS, MANIFESTS) is not None


def test_what_is_being_sought_is_never_the_reference_point():
    a = pa.resolve("nearest reception to room 3.01", ROOMS, MANIFESTS, exclude=["reception"])
    assert a is None


def test_a_question_naming_no_place_of_the_building_resolves_to_nothing():
    assert pa.resolve("nearest toilet", ROOMS, MANIFESTS) is None
    assert pa.resolve("Which floor is the warmest?", ROOMS, MANIFESTS) is None


def test_two_different_single_places_in_one_question_are_ambiguous():
    assert pa.resolve("from the entrance to reception", ROOMS, MANIFESTS) is None


def test_a_place_the_plans_do_not_draw_keeps_its_graph_floor():
    a = pa.resolve("nearest toilet to the atrium", ROOMS, MANIFESTS)
    assert a is not None and a.floor == 1 and a.zone_id is None


# -- names -------------------------------------------------------------------------------------------
def test_a_numbered_label_names_its_kind_after_the_dash_and_any_other_label_before_it():
    r = _room("R", "Room 0.01 — Main Reception", 0, "Reception")
    assert pa.kind_names(r) == ["Main Reception", "Reception"]
    z = _room("Z", "Main Entrance Zone — Ground Floor", 0)
    assert pa.kind_names(z) == [
        "Main Entrance Zone"
    ], "the part after the dash is a floor, not a kind"
    assert pa.kind_names(_room("Q", "Room 9.99", 9)) == []


def test_a_slash_separated_descriptor_names_each_kind():
    r = _room("R", "Room 1.04 — Common Area / Atrium", 1)
    assert pa.kind_names(r) == ["Common Area", "Atrium"]


def test_a_numbered_room_is_called_by_its_number_and_a_named_space_by_its_label():
    assert pa._display(ROOMS[0]) == "Room 0.01"
    assert pa._display(ROOMS[1]) == "Main Entrance Zone"


def test_a_zone_the_plans_draw_twice_is_mapped_to_the_one_with_an_area():
    twice = [
        SimpleNamespace(
            floor=0,
            spaces=[
                _space("0.01", f"{_NS}Room0.01", None, "drawing text"),
                _space("0.01", f"{_NS}Room0.01", 184.5),
            ],
        )
    ]
    assert pa.zone_for_iri(twice, f"{_NS}Room0.01") == "0.01"
    assert pa.zone_for_iri(twice, f"{_NS}Nowhere") is None


# -- live access never raises -----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_unreadable_graph_yields_no_anchor_and_backs_off():
    calls = []

    async def broken(_q):
        calls.append(1)
        raise RuntimeError("graph down")

    pa._cache.update({"at": 0.0, "rooms": None, "retry_at": 0.0})
    assert await pa.locate("nearest lift to reception", MANIFESTS, sparql_exec=broken) is None
    assert await pa.entrance(MANIFESTS, sparql_exec=broken) is None
    assert len(calls) == 1, "a graph that just failed is not asked again for a minute"
    pa._cache.update({"at": 0.0, "rooms": None, "retry_at": 0.0})


@pytest.mark.asyncio
async def test_the_live_lookup_reads_the_rooms_once_and_answers_from_them():
    calls = []

    async def graph(_q):
        calls.append(1)
        bindings = []
        for r in ROOMS:
            bindings.append(
                {
                    "r": {"value": r.iri},
                    "l": {"value": r.label},
                    "f": {"value": f"{_NS}Floor{r.floor}"},
                    "fl": {"value": r.floor_label},
                    "types": {
                        "value": " ".join(
                            f"https://brickschema.org/schema/Brick#{c}" for c in r.classes
                        )
                    },
                }
            )
        return {"results": {"bindings": bindings}}

    pa._cache.update({"at": 0.0, "rooms": None, "retry_at": 0.0})
    a = await pa.locate("nearest lift to reception", MANIFESTS, sparql_exec=graph)
    b = await pa.entrance(MANIFESTS, sparql_exec=graph)
    assert a.floor == 0 and b.floor == 0 and len(calls) == 1
    pa._cache.update({"at": 0.0, "rooms": None, "retry_at": 0.0})
