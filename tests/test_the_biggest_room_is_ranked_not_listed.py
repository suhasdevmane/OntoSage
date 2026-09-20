# -*- coding: utf-8 -*-
"""'What's the biggest room in the building?' returned a 354-row unsorted table (BUG-827).

The spatial lane had a size filter and a per-room lookup and no superlative, so the question fell
through every branch to the default listing of every space. Nothing in it was false; the answer to
the question was somewhere inside 354 rows and the reader was left to find it.

These tests pin the ranking, and the honesty around it: a space the plans give no area for cannot be
ranked and might be the biggest, so the answer says how many were left out; a drawing's own text
labels are not rooms; and a superlative about something that is not a space is not this module's.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services import space_superlatives as sup

pytestmark = pytest.mark.unit


def _space(zone, area, label=None, stype="zone", iri=""):
    return SimpleNamespace(
        zone_id=zone,
        label=label if label is not None else zone,
        area_m2=area,
        type=stype,
        ontology_iri=iri,
    )


def _manifest(floor, *spaces):
    return SimpleNamespace(floor=floor, spaces=list(spaces))


_PLANS = [
    _manifest(0, _space("0.01", 184.5), _space("0.02", 20.0), _space("0.03", None)),
    _manifest(
        1,
        _space("1.01", 201.2, stype="lab"),
        _space("1.02", 5.5),
        _space("1622.88", None, label="\\A1;1622.88 m{\\H0.7x;\\S2^ ;}"),
        _space("1.04", 74.0, stype="office"),
    ),
    _manifest(2, _space("2.01", 99.9, stype="office"), _space("2.02", 10.0)),
]


@pytest.mark.parametrize(
    "question,largest,floor",
    [
        ("What's the biggest room in the building?", True, None),
        ("Which is the largest room?", True, None),
        ("smallest room on floor 3", False, 3),
        ("what is the smallest office on the second floor", False, 2),
    ],
)
def test_a_superlative_about_a_space_is_read(question, largest, floor):
    ask = sup.parse_superlative(question)
    assert ask is not None and ask.largest is largest and ask.floor == floor


@pytest.mark.parametrize(
    "question",
    [
        "What is the biggest energy user?",
        "Which floor has the largest CO2 spread?",
        "How big is room 3.01?",
        "Which rooms are larger than 50 m2?",
        "the biggest and the smallest room",
        "Which is the largest room I can book on Friday?",
        "What is the biggest free room right now?",
    ],
)
def test_a_question_that_is_not_a_single_superlative_about_a_space_is_left_alone(question):
    assert sup.parse_superlative(question) is None


def test_the_top_three_are_returned_biggest_first():
    ask = sup.parse_superlative("biggest room")
    ranking = sup.rank_spaces(_PLANS, ask)
    assert [r.zone_id for r in ranking["top"]] == ["1.01", "0.01", "2.01"]
    assert [r.area_m2 for r in ranking["top"]] == sorted(
        (r.area_m2 for r in ranking["top"]), reverse=True
    )


def test_smallest_is_ascending():
    ranking = sup.rank_spaces(_PLANS, sup.parse_superlative("smallest room"))
    assert [r.zone_id for r in ranking["top"]] == ["1.02", "2.02", "0.02"]


def test_a_floor_named_in_the_question_scopes_the_ranking():
    ranking = sup.rank_spaces(_PLANS, sup.parse_superlative("biggest room on floor 1"))
    assert {r.floor for r in ranking["top"]} == {1}
    assert ranking["top"][0].zone_id == "1.01"


def test_a_kind_of_space_scopes_the_ranking():
    ask = sup.parse_superlative("largest office", space_type="office")
    ranking = sup.rank_spaces(_PLANS, ask)
    assert [r.zone_id for r in ranking["top"]] == ["2.01", "1.04"]


def test_a_space_with_no_area_is_counted_as_unranked_not_ranked_as_zero():
    ranking = sup.rank_spaces(_PLANS, sup.parse_superlative("smallest room"))
    assert ranking["unmeasured"] == 1  # 0.03 only: the drawing's text label is not a room
    assert all(r.area_m2 > 0 for r in ranking["top"])
    assert ranking["ranked"] == 7


def test_a_drawing_text_label_is_never_a_room():
    ranking = sup.rank_spaces(_PLANS, sup.parse_superlative("biggest room"))
    assert all("\\" not in r.label for r in ranking["top"])


def test_the_answer_names_the_winner_the_top_three_and_what_was_left_out():
    ask = sup.parse_superlative("What's the biggest room in the building?")
    text = sup.render(ask, sup.rank_spaces(_PLANS, ask))
    assert text.startswith("**The largest room in the building by floor-plan area is Room 1.01**")
    assert "201.2 m²" in text and "(floor 1)" in text
    assert "1. Room 1.01" in text and "2. Room 0.01" in text and "3. Room 2.01" in text
    assert "Ranked from the 7 spaces" in text
    assert "1 more has no area recorded" in text and "may be larger" in text
    many = sup.render(ask, {**sup.rank_spaces(_PLANS, ask), "unmeasured": 62})
    assert "62 more have no area recorded" in many


def test_the_building_own_name_for_a_room_is_used_when_the_graph_has_one():
    ask = sup.parse_superlative("biggest room")
    ranking = sup.rank_spaces([_manifest(0, _space("0.34", 195.0, iri="urn:room034"))], ask)
    text = sup.render(ask, ranking, {"urn:room034": "Room 0.34 — Telecommunications Room"})
    assert "Room 0.34 — Telecommunications Room" in text


def test_nothing_measurable_is_a_statement_not_an_invented_ranking():
    ask = sup.parse_superlative("biggest room")
    text = sup.render(ask, sup.rank_spaces([_manifest(0, _space("0.01", None))], ask))
    assert "cannot say" in text and "will not estimate" in text


def test_the_asker_own_noun_is_repeated():
    ask = sup.parse_superlative("What is the largest lab?")
    assert ask.noun == "lab"
    assert "largest lab in the building" in sup.render(ask, sup.rank_spaces(_PLANS, ask))
