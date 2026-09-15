"""BUG-592: "What about room 2.01?" after a 24 h CO2 plot came back as text, with a minimum
taken from the newest rows ("lowest 842 ppm at 17:23"; the store held 704 ppm at 04:08)."""

import inspect
from types import SimpleNamespace as NS

import pytest

from orchestrator.agents.dialogue_agent import keep_the_asked_action
from orchestrator.services.series_summary import summarise_series

pytestmark = pytest.mark.unit


def _msgs(*pairs):
    return [NS(role=r, content=c) for r, c in pairs]


def test_an_elliptical_follow_up_to_a_plot_is_still_a_plot():
    msgs = _msgs(("user", "Plot the CO2 in room 5.01 over the last 24 hours."),
                 ("assistant", "chart"), ("user", "What about room 2.01?"))
    out = keep_the_asked_action("What about room 2.01?",
                                "What is the CO2 level in room 2.01 over the last 24 hours?", msgs)
    assert out == "Plot the CO2 level in room 2.01 over the last 24 hours."


def test_a_follow_up_to_a_reading_is_left_alone():
    msgs = _msgs(("user", "What is the CO2 in room 5.01?"), ("assistant", "900"),
                 ("user", "What about room 2.01?"))
    rw = "What is the CO2 in room 2.01?"
    assert keep_the_asked_action("What about room 2.01?", rw, msgs) == rw


def test_a_new_question_is_not_turned_into_a_plot():
    msgs = _msgs(("user", "Plot the CO2 in room 5.01."), ("assistant", "chart"),
                 ("user", "Is the lift working?"))
    assert keep_the_asked_action("Is the lift working?", "Is the lift working?", msgs) == "Is the lift working?"


def test_the_summary_says_when_the_extremes_happened():
    rows = [
        {"uuid": "u", "timestamp": "2026-09-15 03:08:06", "value": 704},
        {"uuid": "u", "timestamp": "2026-09-15 15:49:15", "value": 916},
        {"uuid": "u", "timestamp": "2026-09-15 16:38:56", "value": 847},
    ]
    text, _ = summarise_series(rows, {"u": {"label": "CO2 2.01", "unit": "ppm"}}, None)
    assert "minimum 704 at 15 Sep 03:08" in text and "maximum 916 at 15 Sep 15:49" in text


def test_the_sql_narration_is_given_statistics_over_every_row():
    from orchestrator.agents import sql_agent

    src = inspect.getsource(sql_agent.SQLAgent._format_results)
    assert "summarise_series(results" in src and "Statistics over ALL" in src
