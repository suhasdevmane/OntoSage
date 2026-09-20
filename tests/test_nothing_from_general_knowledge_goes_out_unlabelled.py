# -*- coding: utf-8 -*-
"""General knowledge is labelled, and the building's own records come first (2D-16 wave 2).

Wave-1 development read, "What kind of vechicles park?": a paragraph from the model's own knowledge
with no label, about a building whose graph holds a transport-and-parking topic. The amenities used
here are fakes shaped like the resolver's; the real graph is the lead's to check live.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import general_knowledge_gate as gk

pytestmark = pytest.mark.unit


def _am(label, phrases, text="", **kw):
    return SimpleNamespace(label=label, lay_phrases=phrases, _text=text, **kw)


PARKING = _am(
    "Transport Parking",
    ["parking", "car park", "motorcycle", "scooter", "ev charging", "electric vehicle", "badge"],
    "Motorcycle and scooter bays are at the rear; two electric vehicle chargers serve the car park.",
)
BIKES = _am("Bike Storage", ["bike parking", "bicycle parking", "cycle parking", "park my bike"])
TOILETS = _am("Toilets", ["toilet", "wc", "bathroom", "washroom"])
AMENITIES = [PARKING, BIKES, TOILETS]


# ── the label ────────────────────────────────────────────────────────────────


def test_unlabelled_text_gets_the_label_on_top():
    out = gk.labelled("Parking lots hold cars and vans.")
    assert (
        out
        == "General knowledge (not from this building's records): Parking lots hold cars and vans."
    )


@pytest.mark.parametrize(
    "text",
    [
        "General guidance (not from this building's records): Ventilate.",
        "General knowledge (not from this building's records): Cars.",
        "**General guidance** (not from this building's records): Ventilate.",
    ],
)
def test_an_already_labelled_text_is_never_labelled_twice(text):
    assert gk.labelled(text) == text.strip()
    assert gk.is_labelled(text)


def test_empty_text_stays_empty():
    assert gk.labelled("") == "" and gk.labelled("   ") == ""


# ── typo tolerance ───────────────────────────────────────────────────────────


def test_a_slip_of_the_pen_is_put_right_against_the_buildings_own_words():
    vocab = gk.vocabulary_of(AMENITIES)
    assert gk.correct_typos("What kind of vechicles park?", vocab) == "What kind of vehicles park?"


def test_a_word_the_building_knows_or_that_is_nothing_like_one_is_left_alone():
    vocab = gk.vocabulary_of(AMENITIES)
    assert gk.correct_typos("Where is the parking?", vocab) == "Where is the parking?"
    assert gk.correct_typos("Tell me about helicopters", vocab) == "Tell me about helicopters"
    assert gk.correct_typos("anything", set()) == "anything"


# ── the building's own records go first ─────────────────────────────────────


def test_the_question_that_was_answered_from_model_knowledge_matches_the_parking_topic():
    matched = gk.match_amenities("What kind of vechicles park?", AMENITIES)
    assert matched and matched[0] is PARKING


def test_a_question_that_only_mentions_a_parking_word_is_not_claimed_by_the_topic():
    assert gk.match_amenities("Can I park a helicopter on the roof?", AMENITIES) == []


def test_an_unrelated_question_matches_nothing():
    assert gk.match_amenities("Why is the sky blue?", AMENITIES) == []
    assert gk.match_amenities("tell me more", AMENITIES) == []


def test_records_answer_is_the_buildings_own_text_not_the_models(monkeypatch):
    import orchestrator.services.capability_graph_resolver as cgr

    class _Resolver:
        async def _amenities(self):
            return AMENITIES

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())
    monkeypatch.setattr(cgr, "_to_fact", lambda am: SimpleNamespace(render=lambda: am._text))
    text = asyncio.run(gk.records_answer("What kind of vechicles park?", "Abacws Building"))
    assert text.startswith("Here is what I found for **Abacws Building**")
    assert (
        "Motorcycle and scooter bays" in text
        and "Answered live from the building's own records" in text
    )
    assert "General knowledge" not in text


def test_records_answer_is_none_when_nothing_matches_or_the_graph_is_down(monkeypatch):
    import orchestrator.services.capability_graph_resolver as cgr

    class _Resolver:
        async def _amenities(self):
            return AMENITIES

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())
    assert asyncio.run(gk.records_answer("Why is the sky blue?")) is None

    class _Down:
        async def _amenities(self):
            raise ConnectionError("graph down")

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Down())
    assert asyncio.run(gk.records_answer("What kind of vechicles park?")) is None
