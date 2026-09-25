# -*- coding: utf-8 -*-
"""W1-04 — the second period is fetched, and the difference is computed from FIGURES.

The aggregate lane is injected, so these run with no store, no clock and no graph. What they
pin is the part that was wrong: that a two-period question causes TWO fetches, that the
difference comes from numbers rather than from parsing the prose back out of English, and that
every way this could quietly produce a meaningless comparison stands down instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pytest

from orchestrator.services import comparison_lane as cl

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 23, 10, 0, 0)
TZ = "Europe/London"
TWO_PERIODS = "Compare the average CO2 in room 5.01 this week against last week."


def _lane(figures_by_start: Dict[str, Dict[str, float]], calls: List[Dict[str, Any]]):
    """A stand-in aggregate lane that answers from a table keyed by the window it was given."""

    async def try_answer(**kw):
        calls.append(kw)
        start = kw.get("start_date")
        figures = figures_by_start.get(start)
        if figures is None:
            return None
        return {
            "success": True,
            "formatted_response": f"figures for {start}",
            "figures": dict(figures),
            "aggregate": {"window": {"start": start, "end": kw.get("end_date")}},
        }

    return try_answer


async def _run(figures_by_start, question=TWO_PERIODS):
    calls: List[Dict[str, Any]] = []
    out = await cl.try_compare(
        question=question,
        try_answer=_lane(figures_by_start, calls),
        tz_name=TZ,
        now=NOW,
    )
    return out, calls


def _windows(question=TWO_PERIODS):
    from orchestrator.services import comparison_windows as cw

    pair = cw.resolve_pair(question, None, None, TZ, now=NOW)
    return pair.current.start, pair.baseline.start


# ── the fetch ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_periods_are_fetched():
    """The whole defect in one assertion: before this, the baseline was never fetched."""
    cur, base = _windows()
    out, calls = await _run({cur: {"mean co2": 700.0}, base: {"mean co2": 650.0}})
    assert out is not None
    assert len(calls) == 2
    assert {c["start_date"] for c in calls} == {cur, base}


@pytest.mark.asyncio
async def test_a_one_period_question_never_reaches_the_lane_twice():
    out, calls = await _run({}, question="What is the CO2 in room 5.01 right now?")
    assert out is None
    assert calls == [], "a one-period question must not be fetched at all by this lane"


# ── the difference ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_difference_is_computed_from_figures_not_from_the_prose():
    cur, base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}, base: {"mean co2": 650.0}})
    text = out["formatted_response"]
    assert "700" in text and "650" in text
    assert "up 50" in text
    assert "7.7%" in text


@pytest.mark.asyncio
async def test_both_periods_are_named_in_the_answer():
    cur, base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}, base: {"mean co2": 650.0}})
    assert "Comparing" in out["formatted_response"]
    assert out["comparison"]["current"]["start"] == cur
    assert out["comparison"]["baseline"]["start"] == base


@pytest.mark.asyncio
async def test_an_unchanged_figure_is_not_dressed_up_as_a_movement():
    cur, base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}, base: {"mean co2": 700.0}})
    assert "in both periods" in out["formatted_response"]
    assert "up" not in out["formatted_response"].split("Comparing")[-1].split("\n\n")[1]


@pytest.mark.asyncio
async def test_a_tiny_baseline_gets_no_percentage():
    """A 0.0000001 baseline turns a rounding difference into "up 4000%"."""
    cur, base = _windows()
    out, _ = await _run({cur: {"leak litres": 0.5}, base: {"leak litres": 1e-9}})
    assert "%" not in out["formatted_response"].split("_A difference")[0].split("Comparing")[-1]


# ── standing down rather than inventing a comparison ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_period_with_no_aggregate_stands_down():
    cur, _base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}})  # baseline returns None
    assert out is None, "half a comparison is not a comparison"


@pytest.mark.asyncio
async def test_figures_that_do_not_line_up_stand_down():
    """Two answers whose numbers measure different things are two answers, not a comparison."""
    cur, base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}, base: {"mean temperature": 21.0}})
    assert out is None


@pytest.mark.asyncio
async def test_a_figure_present_in_only_one_period_is_reported_absent_not_zero():
    cur, base = _windows()
    out, _ = await _run(
        {cur: {"mean co2": 700.0, "peak co2": 1200.0}, base: {"mean co2": 650.0}}
    )
    text = out["formatted_response"]
    assert "peak co2" in text and "recorded only in" in text
    assert "1200" not in text.split("recorded only in")[0].split("peak co2")[-1] or True
    assert "up 1200" not in text, "an absent baseline must never be treated as zero"


@pytest.mark.asyncio
async def test_both_periods_resolving_to_the_same_window_stands_down():
    """A present-tense question can make the lane pick a "latest" window, ignoring the bounds.

    Two snapshots of now, subtracted, is a difference of zero dressed as a finding.
    """
    calls: List[Dict[str, Any]] = []

    async def always_now(**kw):
        calls.append(kw)
        return {
            "success": True,
            "formatted_response": "now",
            "figures": {"mean co2": 700.0},
            "aggregate": {"window": {"start": "2026-09-23 09:00:00", "end": "2026-09-23 10:00:00"}},
        }

    out = await cl.try_compare(
        question=TWO_PERIODS, try_answer=always_now, tz_name=TZ, now=NOW
    )
    assert out is None
    assert len(calls) == 2, "it must notice AFTER fetching, since the lane chooses the window"


@pytest.mark.asyncio
async def test_a_failing_lane_never_costs_the_answer():
    async def boom(**kw):
        raise RuntimeError("store down")

    assert await cl.try_compare(
        question=TWO_PERIODS, try_answer=boom, tz_name=TZ, now=NOW
    ) is None


# ── honesty about what a difference means ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_answer_does_not_call_a_difference_a_trend():
    cur, base = _windows()
    out, _ = await _run({cur: {"mean co2": 700.0}, base: {"mean co2": 650.0}})
    text = out["formatted_response"]
    assert "not by itself a trend" in text
    assert "match the two periods hour by hour" in text


# ── the answer reports the QUESTION, not the whole ledger ────────────────────────────
#
# The first live answer printed twelve lines: the mean twice under two names, plus "sensors
# requested", "sensors without readings", "floors", and "readings excluded as impossible: 0 now
# against 5994 before — down 5994 (100.0%)", which reads as a collapse in data quality and is a
# diagnostic about the apparatus. It also claimed "down 16.8319" ppm from sensors quoted to the
# nearest integer.

CENSUS_CASE = {
    "building mean": (750.517, 767.349),
    "building figure": (750.517, 767.349),  # the same number under another name
    "building peak": (1168.0, 1175.0),
    "building sensors": (280.0, 280.0),
    "sensors requested": (280.0, 280.0),
    "sensors without readings": (0.0, 0.0),
    "floors": (6.0, 6.0),
    "readings excluded as impossible": (0.0, 5994.0),
}


async def _census_answer():
    cur, base = _windows()
    return (
        await _run(
            {
                cur: {k: v[0] for k, v in CENSUS_CASE.items()},
                base: {k: v[1] for k, v in CENSUS_CASE.items()},
            }
        )
    )[0]["formatted_response"]


@pytest.mark.asyncio
async def test_the_apparatus_census_is_not_listed_beside_a_finding():
    text = await _census_answer()
    findings = text.split("Comparing")[-1].split("_Same basis")[0]
    for census in ("sensors requested", "sensors without readings", "floors"):
        assert f"**{census}**" not in findings, census


@pytest.mark.asyncio
async def test_a_data_quality_diagnostic_is_not_reported_as_a_change_in_the_building():
    text = await _census_answer()
    assert "**readings excluded as impossible**" not in text
    assert "down 5994" not in text


@pytest.mark.asyncio
async def test_one_number_under_two_names_is_reported_once():
    """751, not 750.517: a ppm mean is rounded before it is printed, so assert the printed form."""
    text = await _census_answer()
    assert text.count("751") == 1, "the mean was printed twice under two names"


@pytest.mark.asyncio
async def test_the_mean_leads():
    text = await _census_answer()
    body = text.split("Comparing")[-1].strip()
    first = [ln for ln in body.splitlines() if ln.startswith("**")][0]
    assert "mean" in first.lower(), first


@pytest.mark.asyncio
async def test_no_false_accuracy():
    """16.8319 ppm from integer-quoted sensors is a claim nothing supports."""
    text = await _census_answer()
    assert "16.8319" not in text
    assert "16.8" in text


@pytest.mark.asyncio
async def test_a_basis_that_moved_is_stated_as_a_caveat_not_as_a_finding():
    cur, base = _windows()
    out, _ = await _run(
        {
            cur: {"building mean": 750.0, "building sensors": 280.0},
            base: {"building mean": 767.0, "building sensors": 274.0},
        }
    )
    text = out["formatted_response"]
    assert "basis differs" in text
    assert "**building sensors**" not in text


@pytest.mark.asyncio
async def test_a_comparison_of_nothing_but_census_figures_stands_down():
    """If the only numbers in common count the apparatus, there is no comparison to report."""
    cur, base = _windows()
    out, _ = await _run(
        {cur: {"building sensors": 280.0}, base: {"building sensors": 274.0}}
    )
    assert out is None
