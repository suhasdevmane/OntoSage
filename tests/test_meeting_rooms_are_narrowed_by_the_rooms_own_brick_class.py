# -*- coding: utf-8 -*-
"""BUG-828 (tail B row B11): "Which meeting rooms are booked this afternoon?" names a KIND of room.

Answered from the live booking store without narrowing, it would list every room with a booking --
offices and labs beside the meeting rooms. Each space carries Brick classes, so the narrowing is a
lookup in the building's own data; these tests pin the words-to-classes step and the rule that a
kind the building does not record is never turned into "nothing is booked".
"""

import pytest

from orchestrator.services.room_kind_words import kinds_asked, rooms_of_kind

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question, phrase, first_class",
    [
        ("Which meeting rooms are booked this afternoon?", "meeting rooms", "Conference_Room"),
        ("Is any conference room free at 3pm?", "meeting rooms", "Conference_Room"),
        ("Which seminar rooms have sessions today?", "meeting rooms", "Conference_Room"),
        ("Is the boardroom booked?", "meeting rooms", "Conference_Room"),
        ("Which labs are booked tomorrow?", "laboratories", "Laboratory"),
        ("Are any offices booked today?", "offices", "Office"),
        ("Which lecture theatres are free this morning?", "teaching rooms", "Classroom"),
    ],
)
def test_the_words_a_person_uses_map_to_brick_room_classes(question, phrase, first_class):
    classes, said = kinds_asked(question)
    assert said == phrase and classes[0] == first_class


@pytest.mark.parametrize(
    "question",
    ["Which rooms are booked this afternoon?", "Is Room 1.06 free?", "How many bookings today?", ""],
)
def test_a_question_that_names_no_kind_is_not_narrowed(question):
    assert kinds_asked(question) == ((), "")


KINDS = {
    "Room1.25": {"Room", "Conference_Room"},
    "Room1.26": {"Room", "Conference_Room"},
    "Room1.06": {"Room", "Laboratory"},
    "Room2.01": {"Room", "Office"},
}
ROOMS = list(KINDS)


def test_rooms_are_narrowed_by_the_class_the_graph_gave_them():
    assert rooms_of_kind(ROOMS, KINDS, ("Conference_Room", "Meeting_Room")) == ["Room1.25", "Room1.26"]
    assert rooms_of_kind(ROOMS, KINDS, ("Laboratory",)) == ["Room1.06"]


def test_a_kind_the_building_does_not_record_is_none_never_an_empty_list():
    # [] would read as "no meeting room is booked"; None says "no room is recorded as one"
    assert rooms_of_kind(ROOMS, KINDS, ("Auditorium",)) is None


def test_no_class_data_at_all_means_no_filter():
    assert rooms_of_kind(ROOMS, {}, ("Conference_Room",)) is None
    assert rooms_of_kind(ROOMS, KINDS, ()) is None


def test_class_matching_ignores_case():
    assert rooms_of_kind(["a"], {"a": {"conference_room"}}, ("Conference_Room",)) == ["a"]
