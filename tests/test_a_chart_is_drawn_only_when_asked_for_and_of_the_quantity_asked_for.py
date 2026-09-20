# -*- coding: utf-8 -*-
"""An unrelated chart is never drawn (2D-16 wave 2, defect class C19).

Wave-1 held-out read: "I may not see visual alerts. Which verified audible or staff-assisted
notification provision is available?" returned "The line chart tracks 1,000 noise sensor readings
on Floor 5 ..." with an image. The adjective "visual" was read as a picture request and "audible"
resolved to noise sensors. A chart now needs (1) a question that asks for one, (2) a series of the
quantity asked for and (3) a caption that says which quantity, where and when.
"""

from __future__ import annotations

import pytest

from orchestrator.services import chart_policy as cp

pytestmark = pytest.mark.unit

NOTIFICATION_Q = (
    "I may not see visual alerts. Which verified audible or staff-assisted notification "
    "provision is available?"
)

NOISE_ROWS = [
    {"uuid": "n1", "timestamp": "2026-09-18 05:58:00", "value": 38.5},
    {"uuid": "n1", "timestamp": "2026-09-19 04:37:00", "value": 62.0},
]
NOISE_META = {"n1": {"label": "Floor 5 noise sensor", "unit": "dB", "floor": "5", "kind": "sound"}}
CO2_ROWS = [
    {"uuid": "c1", "timestamp": "2026-09-18 22:50:00", "value": 723},
    {"uuid": "c1", "timestamp": "2026-09-19 03:50:00", "value": 800},
]
CO2_META = {"c1": {"label": "Room 5.01 CO2 sensor", "unit": "ppm", "kind": "co2"}}


# ── 1. does the question ask for a chart ─────────────────────────────────────


def test_the_adjective_visual_is_not_a_request_for_a_picture():
    assert not cp.asks_for_chart(NOTIFICATION_Q)


@pytest.mark.parametrize(
    "question",
    [
        "I have a visual impairment. Which rooms have hearing loops?",
        "Are there visual display screens in the atrium?",
        "Where is the display board for the timetable?",
        "Which meeting rooms have a projector panel?",
        "Is there a map of the building at reception?",
        "What was the CO2 in room 5.01 yesterday?",
        "How stuffy is Room 1.06 at the moment?",
        "Give me the figures for Floor 3",
        "Which rooms are noisy in the afternoon?",
    ],
)
def test_ordinary_questions_containing_picture_words_ask_for_no_chart(question):
    assert not cp.asks_for_chart(question)


@pytest.mark.parametrize(
    "question",
    [
        "plot the CO2 in room 5.01 today",
        "show me a bar chart of temperature by floor",
        "Graph humidity for the last week",
        "can you visualise occupancy on floor 2",
        "draw the trend",
        "show the trend of energy use",
        "give me a heat map of CO2",
        "plots of every floor please",
        "Chart CO2 for the last 24 hours in the atrium.",
        "show me a picture of the temperature on floor 2",
        "give me a visual of noise levels this week",
        "how has the temperature in the lab changed since Monday",
    ],
)
def test_real_chart_requests_are_recognised(question):
    assert cp.asks_for_chart(question)


def test_a_picture_word_without_a_quantity_is_not_a_chart_request():
    assert not cp.asks_for_chart("show me a picture of the entrance")


# ── 2. the series is the quantity asked for ─────────────────────────────────


def test_the_quantities_a_question_names():
    assert cp.quantities_named("plot noise and humidity by floor") == ["sound", "humidity"]
    assert cp.quantities_named("chart carbon dioxide") == ["co2"]
    assert cp.quantities_named("chart everything") == []


def test_a_chart_of_noise_for_a_question_about_co2_is_not_drawn():
    d = cp.decide("plot the CO2 in room 5.01 today", NOISE_ROWS, NOISE_META)
    assert not d.draw and d.reason == "series_is_not_the_quantity_asked_for"


def test_a_chart_of_the_quantity_asked_for_is_drawn():
    d = cp.decide("plot the CO2 in room 5.01 today", CO2_ROWS, CO2_META)
    assert d.draw and d.quantities == ("co2",)


def test_a_named_quantity_that_cannot_be_checked_is_not_drawn():
    """Unverifiable is the failure this rule exists to stop."""
    assert not cp.decide("plot the CO2 in room 5.01", CO2_ROWS, {}).draw


def test_a_question_that_names_no_quantity_is_not_held_to_one():
    assert cp.decide("chart it", CO2_ROWS, CO2_META, follow_up=True).draw
    assert cp.decide("draw the trend", CO2_ROWS, CO2_META).draw


def test_the_wave_one_failure_is_refused_at_the_first_step():
    d = cp.decide(NOTIFICATION_Q, NOISE_ROWS, NOISE_META)
    assert not d.draw and d.reason == "not_a_chart_request"


def test_synonyms_in_the_sensor_label_count():
    meta = {"x": {"label": "Zone 2 Sound Level Sensor", "unit": "dB"}}
    rows = [{"uuid": "x", "timestamp": "2026-09-19 01:00:00", "value": 40}]
    assert cp.decide("graph the noise on floor 2", rows, meta).draw


# ── 3. the caption says which quantity, where and when ──────────────────────


def test_the_caption_names_the_sensor_the_unit_the_period_and_the_count():
    header = cp.caption_header(CO2_ROWS, CO2_META)
    assert (
        header == "Chart of Room 5.01 CO2 sensor (ppm) — 18 Sep 22:50 to 19 Sep 03:50, 2 readings."
    )


def test_many_sensors_are_summarised_with_their_floor():
    meta = {f"u{i}": {"label": f"Room {i} noise", "unit": "dB", "floor": "5"} for i in range(4)}
    rows = [
        {"uuid": f"u{i}", "timestamp": "2026-09-19 01:00:00", "value": 40 + i} for i in range(4)
    ]
    header = cp.caption_header(rows, meta)
    assert header.startswith("Chart of 4 sensors on floor 5 (dB)")


def test_a_caption_without_metadata_still_states_period_and_count_and_no_invention():
    header = cp.caption_header(CO2_ROWS, {})
    assert header.startswith("Chart of the plotted series") and "2 readings" in header


def test_no_rows_no_caption():
    assert cp.caption_header([], CO2_META) == ""


def test_the_keyword_list_of_the_workflow_agrees_with_this_policy(monkeypatch):
    """The workflow's own trigger must never be broader than this policy on the failing question."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    wants = WorkflowOrchestrator._user_wants_visualization
    # The pre-fix keyword list matched "visual"; after wiring, both agree.
    assert wants(NOTIFICATION_Q) is False
