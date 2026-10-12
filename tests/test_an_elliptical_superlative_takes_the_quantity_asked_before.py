""""which floor used the most?" takes its quantity and period from the conversation.

2026-10-11 battery (energy/finance, turn 3): the follow-up has no pronoun, so the follow-up gate
passed it unrewritten; the classifier asked what was meant and the document lane declined.
"""

import pytest

from orchestrator.services.context_switch import (
    resolve_compare_with_before,
    resolve_elliptical_superlative,
)

pytestmark = pytest.mark.unit


def test_the_quantity_and_period_come_from_the_question_that_named_them():
    earlier = [
        "How much electricity did the building use last week?",
        "how does that compare with the week before?",
    ]
    out = resolve_elliptical_superlative("which floor used the most?", earlier)
    assert out == "Which floor used the most electricity last week?"


def test_a_room_superlative_after_a_reading_question():
    out = resolve_elliptical_superlative(
        "and which room had the highest?", ["What was the CO2 in the meeting rooms yesterday?"]
    )
    assert out == "Which room had the highest co2 yesterday?"


def test_nothing_is_invented_when_no_earlier_question_names_a_quantity():
    assert resolve_elliptical_superlative("which floor used the most?", ["hello"]) is None


@pytest.mark.parametrize(
    "latest",
    [
        "which floor used the most energy?",
        "which floor is the cafe on?",
        "which room is the largest meeting room?",
    ],
)
def test_a_complete_question_is_left_alone(latest):
    assert resolve_elliptical_superlative(latest, ["How much electricity last week?"]) is None


# "how does that compare with the week before?" -- the previous question, compared one step back.


def test_the_comparison_is_appended_to_the_users_own_question():
    out = resolve_compare_with_before(
        "how does that compare with the week before?",
        ["How much electricity did the building use last week?"],
    )
    assert (
        out == "How much electricity did the building use last week compared with the week before?"
    )


def test_no_comparison_is_built_without_a_question_naming_quantity_and_period():
    assert (
        resolve_compare_with_before("how does that compare with the week before?", ["hi"]) is None
    )
    assert (
        resolve_compare_with_before(
            "how does that compare with the week before?", ["How much electricity is used?"]
        )
        is None
    )


def test_a_comparison_naming_its_own_subject_is_left_alone():
    assert (
        resolve_compare_with_before(
            "how does the gas use compare with the week before?", ["electricity last week"]
        )
        is None
    )
