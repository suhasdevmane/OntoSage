# -*- coding: utf-8 -*-
"""A data question that really is too wide is answered in one plain sentence (row 2D-10, wave 2).

The refusal used to read "That question reaches 280 sensors - more than I can read row by row and
summarise in one request without either timing out or quietly answering from a fraction of them",
then two bullets and a paragraph of justification. It described the mechanism, not the reader's
question, and it reached stakeholders on questions that should never have fetched anything.

The refusal itself stays (the aggregate lane cannot answer a dump of every reading). The sentence
names what was asked and offers the two cheapest questions that DO get an answer, built from the
reader's own quantity and period so they can be asked as they stand.
"""

from __future__ import annotations

import pytest

from orchestrator.services.too_broad_reply import JARGON, too_broad_reply

pytestmark = pytest.mark.unit

CO2_LABELS = ["CO2 Level Sensor installed-node 1.40", "Room 5.01 — Research Laboratory co2 [ppm]"]


def test_it_names_the_quantity_and_offers_the_two_cheapest_questions_built_from_it():
    text = too_broad_reply("Show me CO2 for every sensor this week.", 280, CO2_LABELS)
    assert "all 280 CO2 sensors" in text
    assert '"Which floor had the highest CO2 this week?"' in text
    assert '"What is the CO2 level in Room 5.01 right now?"' in text


def test_it_is_one_plain_sentence():
    text = too_broad_reply("Show me CO2 for every sensor this week.", 280, CO2_LABELS)
    assert "\n" not in text and not text.startswith(("-", "*", "#"))
    assert text.endswith(".")
    assert text.count(". ") == 0  # one sentence: the only full stop is the last character


@pytest.mark.parametrize(
    "question",
    [
        "Show me CO2 for every sensor this week.",
        "list every temperature reading yesterday",
        "give me all occupancy readings",
        "Can temperature or humidity affect the CO2 sensor?",
        "show me everything",
    ],
)
def test_it_never_uses_the_vocabulary_of_the_mechanism(question):
    text = too_broad_reply(question, 296, ["Room 4.16 occupancy [persons]", "Air temp 2.10"])
    lowered = text.lower()
    assert not [w for w in JARGON if w in lowered]
    assert "request" not in lowered and "budget" not in lowered


def test_the_period_the_reader_used_is_kept():
    text = too_broad_reply("list every temperature reading yesterday", 296, ["Air temp"])
    assert "Which floor had the highest temperature yesterday?" in text


def test_a_headcount_is_asked_about_as_people_not_as_a_level():
    text = too_broad_reply("give me all occupancy readings", 250, ["Room 4.16 occupancy [persons]"])
    assert "Which floor has the most people right now?" in text
    assert "How many people are in Room 4.16 right now?" in text


def test_the_example_room_comes_from_the_sensors_never_from_the_code():
    other = too_broad_reply("every CO2 reading", 10, ["Room 9.99 co2 [ppm]"])
    assert "Room 9.99" in other and "Room 5.01" not in other
    none = too_broad_reply("every CO2 reading", 10, ["CO2 Level Sensor installed-node"])
    assert "one room" in none and "Room " not in none


def test_with_no_quantity_it_still_says_what_to_do_without_inventing_one():
    text = too_broad_reply("show me every sensor", 300, ["Sensor A"])
    assert "all 300 sensors" in text and "name a floor or a room" in text


def test_the_module_names_no_building():
    import inspect

    from orchestrator.services import too_broad_reply as mod

    src = inspect.getsource(mod)
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "Abacws", "5.01"):
        assert literal not in src, literal
