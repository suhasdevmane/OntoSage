# -*- coding: utf-8 -*-
"""The bare-measurand summary must not answer a question that names no quantity (2026-09-20).

Three tail-G questions were answered with a building-wide TEMPERATURE or FLOW summary although they
named neither: "Which approved paths have abnormal latency, jitter or packet loss?", "If we can
investigate only one BMS/HVAC control issue this shift, which verified issue has the strongest case
for attention?" and "Is the domestic hot-water plant recovering and circulating as intended?". The
lane voted its measurand from the labels of whatever sensors the pipeline had bound, and an
unrelated question binds whatever retrieval falls back to. The question's own words are the only
evidence of what it is about.
"""

from __future__ import annotations

import pytest

from orchestrator.services.aggregate_lane import measurand_key, question_names_a_quantity

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Which approved paths have abnormal latency, jitter or packet loss, and when did the "
        "deviation start?",
        "If we can investigate only one BMS/HVAC control issue this shift, which verified issue "
        "has the strongest case for attention?",
        "Which served zones should be verified first before the next heating or cooling changeover?",
        "Is the domestic hot-water plant recovering and circulating as intended?",
    ],
)
def test_a_question_that_names_no_quantity_resolves_none(question):
    assert measurand_key([question]) is None, question


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Rooms temperature?", "temperature"),
        ("Is the air quality good today?", "air quality"),
        ("What is the CO2 level right now?", "co2"),
    ],
)
def test_a_question_that_does_name_one_still_resolves_it(question, expected):
    assert measurand_key([question]) == expected


@pytest.mark.parametrize(
    "question",
    [
        "how does the building prevent overheating in sun exposed areas?",
        "Last week's class felt hot and stuffy. What did the measurements show?",
        "Is it too cold in here?",
    ],
)
def test_a_lay_word_for_a_quantity_counts_as_naming_it(question):
    assert question_names_a_quantity(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        "Is the domestic hot-water plant recovering and circulating as intended?",
        "Which served zones should be verified first before the next heating or cooling changeover?",
        "Which approved paths have abnormal latency, jitter or packet loss?",
    ],
)
def test_equipment_and_process_words_do_not(question):
    """'hot-water' and 'heating or cooling' name a plant and a process, not the air's temperature."""
    assert question_names_a_quantity(question) is False, question


def test_the_lane_gate_reads_the_question_not_only_the_sensors():
    """The guard lives in the source, so a refactor that drops it fails here rather than live."""
    import inspect

    from orchestrator.services import aggregate_lane

    src = inspect.getsource(aggregate_lane.try_answer)
    gate = src[src.index("summary_ok = bool(") : src.index("profile_ok")]
    # Wave 7 tightened the gate: the question must be about the SAME quantity the sensors measure,
    # which implies naming one. Either form keeps the guard; neither may be removed.
    assert "question_names_a_quantity(question)" in gate or "question_asks_about(question" in gate
