# -*- coding: utf-8 -*-
"""'Where are the toilets on floor 2?' listed floors 0, 1 and 3 and never mentioned floor 2 (BUG-827).

The building records a toilet on floor 2. Its live status says out of service, the resolver leaves
an out-of-service amenity out of the list, and the answer therefore said nothing about the floor
asked for -- so the reader concluded the catalogue has no toilet there, which is a different fact
from "the one there is not working" and a different fact again from "none is recorded".

These tests pin the three answers that must stay distinct, and the two ways this could go wrong the
other way: inventing a floor for an amenity that names none, and answering a floor question about a
topic that has no floors at all.
"""

from dataclasses import dataclass

import pytest

from orchestrator.services.amenity_floor_answer import (
    declared_floor,
    floor_in_question,
    floor_scoped_answer,
    kind_stem,
)

pytestmark = pytest.mark.unit

_LAYS = "toilet, toilets, washroom, restroom, bathroom"


@dataclass
class _Fact:
    label: str
    on_floor: str = ""
    lay_terms: str = _LAYS
    placeholder: bool = False


def _toilet(floor, room="Room X", **kw):
    return _Fact(label=f"Toilet facility — {room}", on_floor=f"Floor{floor}", **kw)


# -- reading the floor from the question ---------------------------------------------------------
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Where are the toilets on floor 2?", 2),
        ("nearest toilet on level 3", 3),
        ("Is there a cafe on the second floor?", 2),
        ("toilets on the ground floor", 0),
        ("anything on the 4th floor", 4),
        ("Where are the toilets?", None),
        ("what is the temperature", None),
    ],
)
def test_the_floor_a_question_names(question, expected):
    assert floor_in_question(question) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("Floor3", 3), ("3", 3), ("Level 3", 3), ("unknown", None), ("Rooftop", None), ("", None)],
)
def test_a_floor_declaration_without_digits_is_not_a_floor(value, expected):
    assert declared_floor(value) == expected


def test_the_kind_is_read_from_the_label_the_building_gave():
    assert kind_stem("Toilet facility — Room 2.02 — Research Laboratory") == "toilet facility"
    assert kind_stem("Bottle refill point - Room 0.10") == "bottle refill point"


# -- the three answers ----------------------------------------------------------------------------
def test_a_floor_whose_only_amenity_is_out_of_service_says_so_and_names_the_nearest_that_work():
    live = [_toilet(0, "Room 0.04"), _toilet(1, "Room 1.07"), _toilet(3, "Room 3.02")]
    down = [_toilet(2, "Room 2.02")]
    text = floor_scoped_answer("Where are the toilets on floor 2?", live, down)
    assert "Nothing recorded on floor 2 is currently in service" in text
    assert "Out of service: Toilet facility — Room 2.02" in text
    # nearest working: floor 1 and floor 3 are each one floor away; floor 0 is not the nearest
    assert "Room 1.07" in text and "Room 3.02" in text
    assert "Room 0.04" not in text


def test_a_floor_with_no_amenity_at_all_is_reported_as_none_recorded_not_as_out_of_service():
    live = [_toilet(0, "Room 0.04"), _toilet(1, "Room 1.07")]
    text = floor_scoped_answer("Where are the toilets on floor 4?", live, [])
    assert text.startswith("**The building records no toilets on floor 4.**")
    assert "out of service" not in text
    assert "Nearest recorded" in text and "Room 1.07" in text
    assert "3 floors down" in text


def test_a_floor_with_amenities_lists_only_that_floor_and_points_at_the_others():
    live = [_toilet(0, "Room 0.04"), _toilet(2, "Room 2.35"), _toilet(2, "Room 2.36"), _toilet(3)]
    text = floor_scoped_answer("toilets on floor 2", live, [])
    assert "Room 2.35" in text and "Room 2.36" in text
    assert "Room 0.04" not in text
    assert "Also recorded on floor 0, 3" in text


def test_a_broken_one_beside_a_working_one_is_reported_beside_it():
    live = [_toilet(2, "Room 2.35")]
    down = [_toilet(2, "Room 2.02")]
    text = floor_scoped_answer("toilets on floor 2", live, down)
    assert "Room 2.35" in text
    assert "Currently out of service on floor 2: Toilet facility — Room 2.02" in text


def test_the_nearest_names_every_amenity_at_the_smallest_distance():
    live = [_toilet(1, "Room 1.07"), _toilet(3, "Room 3.02"), _toilet(5, "Room 5.02")]
    text = floor_scoped_answer("toilets on floor 2", live, [])
    assert "Room 1.07" in text and "Room 3.02" in text and "Room 5.02" not in text


# -- what it must NOT do --------------------------------------------------------------------------
def test_a_question_that_names_no_floor_is_left_to_the_ordinary_answer():
    assert floor_scoped_answer("Where are the toilets?", [_toilet(1)], []) is None


def test_a_topic_with_no_floors_is_not_answered_as_though_it_had_one():
    topic = _Fact(label="Toilet Facilities By Floor", on_floor="")
    assert floor_scoped_answer("Where are the toilets on floor 2?", [topic], []) is None


def test_an_amenity_whose_floor_is_not_recorded_is_never_placed_on_a_floor():
    unknown = _Fact(label="Toilet facility — Server Room", on_floor="unknown")
    live = [unknown, _toilet(1, "Room 1.07")]
    text = floor_scoped_answer("toilets on floor 4", live, [])
    assert "Server Room" not in text


def test_with_no_located_amenity_anywhere_it_says_it_cannot_place_the_nearest():
    live_only_unknown = [_Fact(label="Toilet facility — x", on_floor="Floor1")]
    text = floor_scoped_answer("toilets on floor 2", live_only_unknown, [])
    assert "Nearest recorded" in text


# -- a record from the building's own rooms outranks a placeholder on the same floor -----------
def test_a_placeholder_is_dropped_on_a_floor_that_has_a_record_from_a_real_room():
    live = [
        _toilet(2, "Room 2.35 — Restroom (Male)"),
        _toilet(2, "Room 2.02 — Research Laboratory", placeholder=True),
        _toilet(3, "Room 3.02 — Research Laboratory", placeholder=True),
    ]
    text = floor_scoped_answer("toilets on floor 2", live, [])
    assert "Room 2.35" in text
    assert "Room 2.02" not in text


def test_a_broken_placeholder_is_not_reported_on_a_floor_whose_real_restrooms_work():
    live = [_toilet(2, "Room 2.35 — Restroom (Male)")]
    down = [_toilet(2, "Room 2.02 — Research Laboratory", placeholder=True)]
    text = floor_scoped_answer("toilets on floor 2", live, down)
    assert "out of service" not in text


def test_placeholders_alone_are_still_answered():
    live = [_toilet(1, "Room 1.07", placeholder=True)]
    text = floor_scoped_answer("toilets on floor 1", live, [])
    assert "Room 1.07" in text


def test_the_kind_is_named_in_the_askers_own_word_when_the_building_declared_it():
    text = floor_scoped_answer("Where are the toilets on floor 4?", [_toilet(1)], [])
    assert "records no toilets on floor 4" in text
    text = floor_scoped_answer("Is there a toilet on floor 4?", [_toilet(1)], [])
    assert "records no toilet on floor 4" in text


def test_an_accessibility_question_is_never_answered_from_lay_terms():
    """Every ordinary toilet carries 'accessible toilet' among its lay terms so that people who
    type those words find a toilet. A floor answer built from that list would tell a wheelchair
    user that an ordinary toilet is accessible; those questions keep the verified-record lanes."""
    live = [_toilet(1, "Room 1.07")]
    assert floor_scoped_answer("Where is the accessible toilet on floor 1?", live, []) is None
    assert floor_scoped_answer("Is there a step-free toilet on floor 1?", live, []) is None
    assert floor_scoped_answer("Where is the toilet on floor 1?", live, []) is not None
