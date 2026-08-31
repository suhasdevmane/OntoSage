# -*- coding: utf-8 -*-
"""Recurrence questions reach the report history, not a schedule (V7-T73).

Measured on the 111-question stakeholder probe: "which cleaning-related defects or service
problems keep recurring in the same place?" reached the DOCUMENT lane, which searched the
cleaning SCHEDULE and honestly reported that it did not answer. It could not — a schedule
says when cleaning happens, not where the same fault returns.

The building holds 203 reports carrying a location, a category and a date, which is
exactly what recurrence needs, and nothing was asking them.
"""

from __future__ import annotations

import pytest

from orchestrator.services.event_query_service import classify_event_question

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "Which cleaning-related defects keep recurring in the same place?",
        "Which barriers recur after earlier tickets were closed at the same asset?",
        "What problems are repeatedly reported on floor 3?",
        "Which faults keep coming back?",
        "Are there any persistent issues in the atrium?",
        "Which rooms have chronic heating complaints?",
    ],
)
def test_a_recurrence_question_is_classified_as_one(query):
    assert classify_event_question(query) == "recurrence", query


def test_recurrence_beats_the_workorder_kind():
    """These questions usually also name tickets, and a backlog count is the wrong shape.

    The right rows aggregated the wrong way is still a wrong answer — the same failure
    _asks_which_rooms exists to prevent one layer down.
    """
    query = "Which tickets keep recurring at the same asset?"
    assert classify_event_question(query) == "recurrence"


@pytest.mark.parametrize(
    "query",
    [
        "How many open work orders are there?",
        "Is RM101 free at 3pm today?",
        "Which rooms are free this afternoon?",
        "How busy was the main entrance this morning?",
    ],
)
def test_ordinary_event_questions_keep_their_kind(query):
    assert classify_event_question(query) != "recurrence", query


def test_recurrence_is_answerable_without_an_events_adapter():
    """It reads the intake store, so a building with no events source can still answer.

    "What keeps going wrong here" is exactly the question such a building most needs
    answered, and gating it on an unrelated datasource would deny it for no reason.
    """
    import inspect

    from orchestrator.services.event_query_service import EventQueryService

    source = inspect.getsource(EventQueryService.answer)
    assert 'kind != "recurrence"' in source


@pytest.mark.parametrize(
    "query",
    [
        # Straight from the catalogue (FM-021). "Persistent" here qualifies a MEASURED
        # exception, not a reported one — answering it from the report history would
        # return the wrong kind of evidence entirely.
        "Which occupied rooms show persistent temperature, CO2 or particulate exceptions?",
        "Is there a persistent draught measured on floor 2?",
        "Show me chronic CO2 levels in the labs",
    ],
)
def test_persistent_over_a_measurement_is_not_report_recurrence(query):
    assert classify_event_question(query) != "recurrence", query


@pytest.mark.parametrize(
    "query",
    [
        "Are there any persistent issues in the atrium?",
        "Which rooms have chronic heating complaints?",
        "Any persistent maintenance problems on level 3?",
    ],
)
def test_persistent_over_a_reported_thing_is_recurrence(query):
    assert classify_event_question(query) == "recurrence", query
