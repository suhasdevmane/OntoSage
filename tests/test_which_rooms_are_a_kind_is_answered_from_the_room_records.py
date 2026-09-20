# -*- coding: utf-8 -*-
"""'Which rooms are computer laboratories?' answered with a page about the schools (BUG-810, 827).

    "Which rooms are computer laboratories?"   -> prose about departments and key facilities
    "Which floor are the computer labs on?"     -> the same prose, no floor
    "Which floor is the server room on?"        -> a menu of the floors that have plans

The graph types every room and names it: `Room 1.06 — Computer Laboratory`, `brick:Server_Room`.
These tests pin the room lookup against a fake graph: the most specific kind wins, a question that
says anything else at all is left alone, and a kind the building does not have is not invented.
"""

import pytest

from orchestrator.services import room_type_lookup as rtl

pytestmark = pytest.mark.unit

_B = "https://brickschema.org/schema/Brick#"
_NS = "http://example.org/b#"


def _row(room, label, floor, classes):
    types = " ".join(f"{_B}{c}" for c in (*classes, "Room", "Space", "Location", "Class"))
    return {
        "r": {"value": f"{_NS}{room}"},
        "l": {"value": label},
        "f": {"value": f"{_NS}Floor{floor}"},
        "fl": {"value": f"Floor {floor}"},
        "types": {"value": types},
    }


_ROWS = [
    _row("Room1.06", "Room 1.06 — Computer Laboratory", 1, ["Laboratory"]),
    _row("Room1.07", "Room 1.07 — Computer Laboratory", 1, ["Laboratory"]),
    _row("Room2.07", "Room 2.07 — Computer Laboratory", 2, ["Laboratory"]),
    _row("Room2.01", "Room 2.01 — Research Laboratory", 2, ["Laboratory"]),
    _row("Room3.01", "Room 3.01 — Research Laboratory", 3, ["Laboratory"]),
    _row("Room2.44", "Room 2.44 — Server Room", 2, ["Server_Room"]),
    _row("Room4.44", "Room 4.44 — Server Room", 4, ["Server_Room"]),
    _row("Room3.36", "Room 3.36 — Restroom (Male)", 3, ["Restroom"]),
    _row("Room3.10", "Room 3.10 — Academic Office", 3, ["Office"]),
    _row("Room3.11", "Room 3.11 — Office", 3, ["Office"]),
    _row("Room4.13", "Room 4.13 — Seminar Room", 4, ["Conference_Room"]),
    _row("Room5.15", "Room 5.15 — Conference/Seminar Room", 5, ["Conference_Room"]),
]


async def _exec(_q):
    return {"results": {"bindings": _ROWS}}


async def _none(_q):
    return {"results": {"bindings": []}}


async def _broken(_q):
    raise RuntimeError("graph unavailable")


@pytest.mark.asyncio
async def test_the_rooms_of_a_kind_are_listed_by_floor():
    text = await rtl.answer("Which rooms are computer laboratories?", _exec)
    assert "3 rooms are recorded as Computer Laboratory" in text
    assert "Floor 1 (2): Room 1.06, Room 1.07" in text
    assert "Floor 2 (1): Room 2.07" in text
    assert "Research" not in text and "Room 2.01" not in text


@pytest.mark.asyncio
async def test_the_most_specific_kind_wins_over_the_broad_one():
    """'computer laboratory' is a kind of 'laboratory'; asking for it must not return them all."""
    text = await rtl.answer("Which rooms are computer laboratories?", _exec)
    assert "Room 3.01" not in text


@pytest.mark.asyncio
async def test_a_broad_kind_lists_its_descriptors():
    text = await rtl.answer("Which rooms are laboratories?", _exec)
    assert "5 rooms are recorded as Laboratory" in text
    assert "2 Research Laboratory" in text and "3 Computer Laboratory" in text


@pytest.mark.asyncio
async def test_a_floor_question_names_the_floors_that_hold_the_kind():
    text = await rtl.answer("Which floor is the server room on?", _exec)
    assert text.startswith("**The building records a Server Room on floors 2 and 4:**")
    assert "Floor 2: Room 2.44" in text and "Floor 4: Room 4.44" in text


@pytest.mark.asyncio
async def test_a_kind_on_one_floor_is_said_in_one_sentence():
    text = await rtl.answer("Which floor is the restroom on?", _exec)
    assert "records a Restroom on floor 3" in text and "Room 3.36" in text


@pytest.mark.asyncio
async def test_lab_and_labs_mean_laboratory():
    text = await rtl.answer("Which floor are the computer labs on?", _exec)
    assert "Computer Laboratory on floors 1 and 2" in text


@pytest.mark.asyncio
async def test_a_floor_in_the_question_scopes_the_list():
    text = await rtl.answer("Which rooms are computer laboratories on floor 2?", _exec)
    assert "1 room is recorded as Computer Laboratory on floor 2" in text
    assert "Room 1.06" not in text


@pytest.mark.asyncio
async def test_a_kind_absent_from_the_floor_asked_is_stated_with_the_floors_that_have_it():
    text = await rtl.answer("Which rooms are computer laboratories on floor 5?", _exec)
    assert text.startswith("**No room on floor 5 is recorded as Computer Laboratory.**")
    assert "floors 1 and 2" in text


@pytest.mark.asyncio
async def test_the_broad_kind_office_finds_the_specific_descriptor_too():
    text = await rtl.answer("Which rooms are offices?", _exec)
    assert "2 rooms are recorded as Office" in text
    assert "Academic Office" in text


@pytest.mark.asyncio
async def test_slash_separated_descriptors_are_each_a_kind():
    text = await rtl.answer("Which rooms are seminar rooms?", _exec)
    assert "Room 4.13" in text and "Room 5.15" in text


# -- what it must leave alone ---------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What is the temperature in the computer laboratory?",
        "Is the computer laboratory open on Sundays?",
        "Which floor has the most laboratories?",
        "Which rooms are free?",
        "Which rooms are computer laboratories and who books them?",
        "Where are the toilets on floor 2?",
        "How do I book a computer laboratory?",
    ],
)
async def test_a_question_about_something_else_is_left_to_its_own_lane(question):
    assert await rtl.answer(question, _exec) is None


@pytest.mark.asyncio
async def test_a_kind_the_building_does_not_have_is_not_invented():
    assert await rtl.answer("Which rooms are swimming pools?", _exec) is None


@pytest.mark.asyncio
async def test_a_graph_without_rooms_or_that_cannot_be_read_yields_nothing():
    assert await rtl.answer("Which rooms are computer laboratories?", _none) is None
    assert await rtl.answer("Which rooms are computer laboratories?", _broken) is None


def test_a_room_with_no_descriptor_is_matched_on_its_class_alone():
    room = rtl.RoomRecord("x#R1", "Room 9.99", 9, "Floor 9", ("Server_Room",))
    assert room.descriptor == "" and room.prefix == "Room 9.99"
    assert rtl.tokens("Server_Room") == frozenset({"server"})
