# -*- coding: utf-8 -*-
"""'Where is reception?' / 'Where is the main entrance?' agree with the graph: floor 0.

The floor-plan lane answered by searching drawing text, and the floor-4 sheet carries "Reception" and
"Main Entrance" labels the PDF text extraction read off the drawing. The graph places the building's
reception in Room 0.01 (brick:Reception, floor 0) and its main entrance in a zone on the ground floor,
and the building's own text says "Ground Floor, main entrance".

These tests pin the "where is X" answer against a fake graph shaped like the real one: a unique kind
is answered with its floor, a question that says anything more is left to the lane that owns it, and
the safety-critical spaces (fire exits, stairwells) are never turned into a location answer here.
"""

import pytest

from orchestrator.services import room_type_lookup as rtl

pytestmark = pytest.mark.unit

_B = "https://brickschema.org/schema/Brick#"
_NS = "http://example.org/b#"


def _row(name, label, floor, classes=()):
    types = " ".join(f"{_B}{c}" for c in (*classes, "Space", "Location", "Class"))
    return {
        "r": {"value": f"{_NS}{name}"},
        "l": {"value": label},
        "f": {"value": f"{_NS}Floor{floor}"},
        "fl": {"value": f"Floor {floor}"},
        "types": {"value": types},
    }


_ROWS = [
    _row("Room0.01", "Room 0.01 — Main Reception", 0, ["Room", "Reception"]),
    _row("Main_Entrance_Zone", "Main Entrance Zone — Ground Floor", 0),
    _row("FireExit_F1_North", "Fire Exit - Floor 1 North", 1),
    _row("FireExit_F2_North", "Fire Exit - Floor 2 North", 2),
    _row("Stairwell_North", "North Stairwell — Fire Escape Route", 0),
    _row("Room2.44", "Room 2.44 — Server Room", 2, ["Room", "Server_Room"]),
    _row("Room4.44", "Room 4.44 — Server Room", 4, ["Room", "Server_Room"]),
    _row("Room1.06", "Room 1.06 — Computer Laboratory", 1, ["Room", "Laboratory"]),
]


async def _exec(_q):
    return {"results": {"bindings": _ROWS}}


def test_the_lookup_asks_for_spaces_not_only_rooms():
    """The main entrance is a brick:Space, not a brick:Room."""
    assert "brick:Space" in rtl._ROOMS_QUERY


def test_where_is_and_where_are_are_a_floors_question():
    assert rtl.wants_rooms_or_floors("Where is reception?") == "floors"
    assert rtl.wants_rooms_or_floors("Where are the server rooms?") == "floors"
    assert rtl.wants_rooms_or_floors("Which floor is the server room on?") == "floors"
    assert rtl.wants_rooms_or_floors("Which rooms are computer laboratories?") == "rooms"
    assert rtl.wants_rooms_or_floors("Is the lift working?") is None


@pytest.mark.asyncio
async def test_where_is_reception_names_floor_0_and_the_room():
    text = await rtl.answer("Where is reception?", _exec)
    assert text.startswith("**The building records a Reception on floor 0:")
    assert "Room 0.01" in text


@pytest.mark.asyncio
async def test_where_is_the_main_entrance_names_floor_0_without_repeating_its_own_label():
    text = await rtl.answer("Where is the main entrance?", _exec)
    assert "Main Entrance Zone on floor 0" in text
    assert text.count("Main Entrance Zone") == 1, "the label is the kind; it is not listed again"


@pytest.mark.asyncio
async def test_where_is_the_entrance_reaches_the_only_entrance_by_its_head_word():
    text = await rtl.answer("Where is the entrance?", _exec)
    assert text is not None and "floor 0" in text


@pytest.mark.asyncio
async def test_where_is_the_west_entrance_is_not_the_main_entrance():
    assert await rtl.answer("Where is the west entrance?", _exec) is None


@pytest.mark.asyncio
async def test_where_is_the_server_room_names_every_floor_that_has_one():
    text = await rtl.answer("Where is the server room?", _exec)
    assert "Server Room on floors 2 and 4" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Where is the entrance open at night?",
        "Where is reception open until?",
        "Where are the toilets?",
        "Where is the nearest lift?",
        "Where is the fire exit?",
        "Where are the fire exits?",
        "Where is the stairwell?",
        "Where can I find the north stairwell?",
    ],
)
async def test_a_question_about_something_else_or_a_safety_space_is_left_alone(question):
    assert await rtl.answer(question, _exec) is None


@pytest.mark.asyncio
async def test_a_fire_exit_and_a_stairwell_are_not_kinds_this_lookup_knows():
    rooms = await rtl.load_rooms(_exec)
    labels = {r.label for r in rooms}
    assert not any("Fire Exit" in label or "Stairwell" in label for label in labels)
    assert "Main Entrance Zone — Ground Floor" in labels


def test_a_named_space_is_called_by_its_label_and_a_numbered_room_by_its_number():
    z = rtl.RoomRecord("x#Z", "Main Entrance Zone — Ground Floor", 0, "Floor 0", ())
    assert z.prefix == "Main Entrance Zone — Ground Floor"
    assert z.descriptor == "Main Entrance Zone"
    r = rtl.RoomRecord("x#R", "Room 0.01 — Main Reception", 0, "Floor 0", ("Reception",))
    assert r.prefix == "Room 0.01" and r.descriptor == "Main Reception"
    assert rtl.RoomRecord("x#Q", "Room 9.99", 9, "Floor 9", ()).descriptor == ""


def test_zone_and_area_carry_no_kind():
    assert rtl.tokens("Common Area") == frozenset({"common"})
    assert rtl.tokens("Main Entrance Zone") == frozenset({"main", "entrance"})
