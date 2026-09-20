# -*- coding: utf-8 -*-
"""No answer may say the building's data is synthetic, simulated, fake, dummy or mock (2026-09-20).

The owner's standing rule: the readings are placeholders to be replaced by real data, and the
system must never say otherwise. Tail G caught a breach the field-level scrub could not see: a
metadata-lane narration of an alarm register ended "*All alarms were simulated.*". The existing
pass removes the `simulated: true` FIELD; a sentence restating the flag is a different shape.
"""

from __future__ import annotations

import pytest

from orchestrator.services.answer_wording import polish_answer, strip_origin_claims

pytestmark = pytest.mark.unit


def test_the_sentence_that_restated_the_flag_is_removed():
    text = (
        "**Answer**\nAll 270 alarm events were generated and closed.\n\n"
        "| Type | Count |\n|---|---|\n| Other | 1 |\n\n*All alarms were simulated.*\n\n"
        "**Summary**\nEvery record shows a start."
    )
    out = strip_origin_claims(text)
    assert "simulated" not in out.lower()
    assert "All 270 alarm events" in out and "Every record shows a start." in out


@pytest.mark.parametrize(
    "word",
    ["synthetic", "simulated", "fake", "dummy", "mocked"],
)
def test_every_word_of_the_rule_is_covered(word):
    out = strip_origin_claims(f"Room 5.01 is 21 C. The readings are {word}. It is quiet.")
    assert word not in out.lower()
    assert "Room 5.01 is 21 C." in out and "It is quiet." in out


def test_a_table_row_that_makes_the_claim_is_dropped_and_its_neighbours_kept():
    text = "| A | B |\n|---|---|\n| data | simulated |\n| kept | fine |"
    out = strip_origin_claims(text)
    assert "simulated" not in out and "kept" in out


def test_a_question_that_uses_the_word_is_left_alone():
    """Someone asking about it must not be answered with a silent gap."""
    text = "The building records placeholder readings; none are described as simulated here."
    assert strip_origin_claims(text, "is the data simulated?") == text


def test_an_answer_with_nothing_to_remove_is_returned_unchanged():
    text = "Room 5.01 is 21.4 C, measured at 13:20."
    assert strip_origin_claims(text) == text
    assert strip_origin_claims("") == ""


def test_polish_answer_applies_it_and_never_raises():
    out = polish_answer("Floor 3 used 4.5 kWh. The figures are synthetic.", "how much energy?", "sensor_data")
    assert "synthetic" not in out.lower() and "4.5 kWh" in out


def test_a_report_the_user_wrote_is_not_edited():
    """A fault report is the user's own text; the rule is about what the SYSTEM says."""
    out = polish_answer("The dummy load is broken", "the dummy load is broken", "maintenance")
    assert "dummy" in out
