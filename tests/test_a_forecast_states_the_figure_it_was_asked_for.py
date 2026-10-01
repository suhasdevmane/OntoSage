# -*- coding: utf-8 -*-
"""BUG-874 — a forecast asked for a MEAN over a named window states the mean.

WHAT WAS MEASURED (2026-09-23, rendered answer captured verbatim)
----------------------------------------------------------------
    "Based on the last two weeks, what is the expected mean humidity in room 2.01
     tomorrow afternoon?"

produced a 24-row hourly prediction table — 52.66 %RH and so on — and never stated the
expected mean for tomorrow afternoon, which is the only number asked for. The sensor, the
horizon and the fit were all right. The output SHAPE is fixed (horizon, model selection,
per-step predictions with intervals) and nothing read the AGGREGATE the question names or
the SUB-WINDOW it names.

W2-02 closed the other half of this row: an aggregate over SENSORS, with its denominator
stated. This is the aggregate over the WINDOW.

WHAT THESE TESTS PIN
--------------------
  the reduction    which figure each wording asks for, and that the ordinary "forecast the
                   temperature tomorrow" asks for NONE and keeps the table
  the local clock  "afternoon" is the occupants' afternoon: the mask is applied to
                   future steps CONVERTED out of store time, so a building on BST does not
                   get 13:00-19:00 under a heading about 12:00-18:00
  the empty mask   a horizon that does not reach the window says so instead of quietly
                   averaging every step it does have
  the quantity     a TOTAL is offered only where adding readings is meaningful (lesson #139)
  the wiring       `_format_response` puts the figure above the table, and a failure in the
                   reduction cannot cost the forecast
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.forecast_agent import ForecastAgent  # noqa: E402
from orchestrator.services.forecasting.window_aggregate import (  # noqa: E402
    reduce_to_requested_figure,
    requested_reduction,
)

#: Twenty-four hourly steps from 18:00 UTC, so an afternoon window falls inside the horizon
#: and its position differs between UTC and a summer-time zone.
START = datetime(2026, 9, 29, 18, 0, 0)
INDEX = [(START + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S") for i in range(24)]


def _series(values):
    return list(values), [v - 1.0 for v in values], [v + 1.0 for v in values]


# ── which figure the question asks for ───────────────────────────────────────


@pytest.mark.parametrize(
    "question,kind",
    [
        ("what is the expected mean humidity in room 2.01 tomorrow afternoon?", "mean"),
        ("what will the average temperature be tomorrow?", "mean"),
        ("what is the typical CO2 expected overnight?", "mean"),
        ("what is the peak temperature expected tomorrow?", "max"),
        ("what is the highest CO2 forecast for tomorrow afternoon?", "max"),
        ("what is the maximum humidity expected tomorrow?", "max"),
        ("what is the lowest temperature expected overnight?", "min"),
        ("what is the total energy use expected tomorrow?", "total"),
        # The ordinary case: the SHAPE is the answer and reducing it would lose the question.
        ("forecast the temperature for tomorrow", None),
        ("predict CO2 next week", None),
        ("what will the temperature be tomorrow in Room 2.01?", None),
        ("", None),
    ],
)
def test_the_reduction_asked_for(question, kind):
    assert requested_reduction(question) == kind


def test_a_question_asking_for_no_figure_leaves_the_table_as_the_answer():
    fc, lo, hi = _series([20.0 + i for i in range(24)])
    assert (
        reduce_to_requested_figure(
            "forecast the temperature for tomorrow", INDEX, fc, lo, hi, unit="°C"
        )
        is None
    )


def test_an_empty_forecast_states_nothing():
    assert (
        reduce_to_requested_figure("the expected mean tomorrow afternoon", [], [], [], []) is None
    )


# ── the figure, and the window it covers ─────────────────────────────────────


def test_the_mean_over_a_named_sub_window_is_stated_and_its_denominator_named():
    """The question BUG-874 was opened on, with a series whose answer is checkable by eye."""
    # 18:00 UTC + i hours. With no zone the afternoon mask (12:00-18:00) selects the steps
    # at 12:00-17:00 the following day, which are i = 18..23 — values 38..43, mean 40.5.
    fc, lo, hi = _series([20.0 + i for i in range(24)])
    note = reduce_to_requested_figure(
        "what is the expected mean humidity in room 2.01 tomorrow afternoon?",
        INDEX,
        fc,
        lo,
        hi,
        unit="%RH",
        horizon_label="next 24 hours",
    )
    assert note is not None
    assert "40.50%RH" in note
    assert "afternoon" in note
    assert "6 predicted step(s)" in note and "out of 24" in note
    assert "95% interval 39.50 to 41.50%RH" in note


def test_the_maximum_is_the_maximum_of_the_window_not_of_the_horizon():
    fc, lo, hi = _series([20.0 + i for i in range(24)])
    note = reduce_to_requested_figure(
        "what is the peak humidity tomorrow afternoon?", INDEX, fc, lo, hi, unit="%RH"
    )
    # The horizon's maximum is the last step, 43.0, which lies OUTSIDE the afternoon.
    assert "43.00" in note  # i=23 is 17:00, inside 12:00-18:00
    fc2, lo2, hi2 = _series([20.0] * 23 + [99.0])
    note2 = reduce_to_requested_figure(
        "what is the peak humidity overnight?", INDEX, fc2, lo2, hi2, unit="%RH"
    )
    # 17:00 the next day is not overnight (22:00-06:00), so 99.0 must not be the answer.
    assert "99.00" not in note2 and "20.00" in note2


def test_no_window_named_means_the_whole_horizon():
    fc, lo, hi = _series([10.0, 20.0, 30.0, 40.0])
    note = reduce_to_requested_figure(
        "what is the average temperature expected tomorrow?",
        INDEX[:4],
        fc,
        lo,
        hi,
        unit="°C",
        horizon_label="next 24 hours",
    )
    assert "25.00°C" in note and "next 24 hours" in note
    assert "4 predicted step(s)" in note and "out of 4" in note


# ── the local clock ──────────────────────────────────────────────────────────


def test_the_afternoon_is_the_occupants_afternoon_not_the_stores():
    """`future_index` is UTC; the hours "afternoon" names are local.

    With a +2 zone the same 12:00-18:00 local window lands two store-hours earlier, so a
    resolver comparing raw UTC stamps picks a DIFFERENT set of steps. The two are asserted
    to differ, which is the whole point — and then the +2 answer is checked against
    arithmetic done here.
    """
    fc, lo, hi = _series([float(i) for i in range(24)])
    utc = reduce_to_requested_figure(
        "the expected mean tomorrow afternoon", INDEX, fc, lo, hi, unit="u"
    )
    plus_two = reduce_to_requested_figure(
        "the expected mean tomorrow afternoon",
        INDEX,
        fc,
        lo,
        hi,
        unit="u",
        tz_name="Europe/Paris",  # UTC+2 in September
    )
    assert utc != plus_two
    # Local 12:00-18:00 is store 10:00-16:00, which from an 18:00 start is i = 16..21.
    assert f"{sum(range(16, 22)) / 6:.2f}u" in plus_two


def test_an_unknown_zone_does_not_break_the_reduction():
    fc, lo, hi = _series([float(i) for i in range(24)])
    note = reduce_to_requested_figure(
        "the expected mean tomorrow afternoon", INDEX, fc, lo, hi, tz_name="Not/AZone"
    )
    assert note is not None and "mean" in note


def test_an_unreadable_timestamp_states_no_figure_rather_than_a_guess():
    """A reduction whose window cannot be established is a guess about which steps it used."""
    fc, lo, hi = _series([float(i) for i in range(4)])
    assert (
        reduce_to_requested_figure(
            "the expected mean tomorrow afternoon", ["not a time"] * 4, fc, lo, hi
        )
        is None
    )


# ── the honest empty window ──────────────────────────────────────────────────


def test_a_horizon_that_does_not_reach_the_window_says_so():
    """Averaging the steps it DOES have would put a figure about the next hour under a
    heading about tomorrow afternoon."""
    # Four steps from 18:00 UTC: 18:00, 19:00, 20:00, 21:00 — none in 12:00-18:00.
    fc, lo, hi = _series([10.0, 11.0, 12.0, 13.0])
    note = reduce_to_requested_figure(
        "the expected mean tomorrow afternoon",
        INDEX[:4],
        fc,
        lo,
        hi,
        unit="°C",
        horizon_label="next 4 hours",
    )
    assert "No mean is stated" in note
    assert "next 4 hours" in note
    for value in ("10.00", "11.00", "11.50", "12.00", "13.00"):
        assert value not in note


# ── the quantity decides whether a total exists ──────────────────────────────


def test_a_total_is_given_for_a_summable_quantity():
    fc, lo, hi = _series([1.0, 2.0, 3.0, 4.0])
    note = reduce_to_requested_figure(
        "what is the total energy use expected tomorrow?", INDEX[:4], fc, lo, hi, unit="kWh"
    )
    assert "total for" in note and "10.00kWh" in note


def test_a_total_of_an_instantaneous_quantity_becomes_a_mean_and_says_so():
    """Lesson #139: mean or total comes from the QUANTITY, never from the wording."""
    fc, lo, hi = _series([20.0, 21.0, 22.0, 23.0])
    note = reduce_to_requested_figure(
        "what is the total temperature tomorrow?", INDEX[:4], fc, lo, hi, unit="°C"
    )
    assert "21.50°C" in note
    assert "does not produce a quantity" in note
    assert "86.00" not in note


# ── the wiring ───────────────────────────────────────────────────────────────


def test_the_figure_is_rendered_above_the_prediction_table():
    src = inspect.getsource(ForecastAgent._format_response)
    assert "reduce_to_requested_figure" in src
    head = src.split("### Model Selection", 1)[0]
    assert "reduce_to_requested_figure" in head and "if headline:" in head


def test_the_question_reaches_the_formatter():
    """It did not, which is part of why nothing could read the aggregate it names."""
    assert "user_query" in inspect.signature(ForecastAgent._format_response).parameters
    assert "_format_response(result, unit, prep_info, user_query)" in inspect.getsource(
        ForecastAgent.predict
    )


def test_a_reduction_failure_never_costs_the_forecast():
    src = inspect.getsource(ForecastAgent._format_response)
    block = src.split("reduce_to_requested_figure", 1)[1].split("### Model Selection", 1)[0]
    assert "except Exception" in block


def test_the_building_declares_its_own_hours_and_none_are_invented():
    """No 08:00-18:00 anywhere: an undeclared schedule declines the mask (contract #3)."""
    src = inspect.getsource(ForecastAgent._occupied_hours)
    assert "resolve_building_context" in src
    assert ForecastAgent._occupied_hours() == (None, None) or all(
        isinstance(h, int) for h in ForecastAgent._occupied_hours()
    )
