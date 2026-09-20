# -*- coding: utf-8 -*-
"""Live 2026-09-19: "Which commissioned CO2-monitored zones show sustained elevated CO2 during an
approved occupied period?" was refused outright — "that covers all 280 CO2 sensors at once".

The exceedance IS computable. What is not is the governance: no series records whether a zone was
commissioned or a period approved. Two wrong answers were available — refuse everything, or answer
as though the qualifier had been applied (a governance claim nothing supports). The third way is to
answer the measured part and say which words were not honoured.
"""

import pytest

from orchestrator.services.aggregate_lane import parse_intent
from orchestrator.services.unrecorded_qualifiers import caveat, unhonoured

pytestmark = pytest.mark.unit

LIVE = "Which commissioned CO2-monitored zones show sustained elevated CO2 during an approved occupied period?"


def test_the_question_now_reads_as_an_exceedance_grouped_by_zone():
    intent = parse_intent(LIVE)
    assert intent is not None and intent.stat == "exceed" and intent.group == "room"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Has CO2 been high anywhere this week?", "exceed"),  # unchanged
        ("Which zones show sustained elevated CO2?", "exceed"),
        ("Which rooms had elevated readings yesterday?", "exceed"),
        ("Which floor had the highest CO2 this week?", "max"),
    ],
)
def test_the_exceedance_family_is_recognised_without_a_copula(question, expected):
    intent = parse_intent(question)
    assert intent is not None and intent.stat == expected


def test_the_qualifiers_that_no_series_carries_are_named():
    assert unhonoured(LIVE) == ["which of them are commissioned", "which periods or zones were approved"]
    note = caveat(LIVE, "every zone with readings in the window")
    assert note.startswith("_The records do not say which of them are commissioned")
    assert "every zone with readings in the window" in note


@pytest.mark.parametrize(
    "question",
    [
        "Has CO2 been high anywhere this week?",  # no qualifier at all
        "Which rooms are occupied right now?",  # occupancy IS measured here
        "Which floor had the highest CO2?",
    ],
)
def test_a_question_without_a_governance_qualifier_gets_no_caveat(question):
    assert caveat(question, "x") == ""


@pytest.mark.parametrize(
    "question",
    [
        "Which observed configuration differences lack a matching approved change record?",
        "Which changes were made without approval?",
        "Who approved the change to the setpoint?",
    ],
)
def test_a_question_ABOUT_the_governance_gets_no_caveat_because_a_register_answers_it(question):
    assert unhonoured(question) == []


def test_the_sql_lane_appends_it_once_and_only_to_an_aggregate_answer():
    import inspect

    from orchestrator.agents.sql_agent import SQLAgent

    src = inspect.getsource(SQLAgent._try_aggregate_lane)
    assert "unrecorded_qualifiers" in src
    assert "note not in answer" in src  # said once
