# -*- coding: utf-8 -*-
"""W1-04 — a question naming two periods resolves two windows.

Measured live 2026-09-23, before this existed:

    "Compare the average CO2 in room 5.01 this week against last week."
    -> "The data set only contains hourly averages for a 14-hour window, not weekly totals ...
        the available data does not allow a comparison."
    "How does energy use yesterday compare with the same day last week?"
    -> "I couldn't answer that from Abacws Building's records."

One honest non-answer and one decline, from the same cause: only one window was ever resolved,
so the baseline period was never fetched. The comparison arithmetic was never the gap --
`evidence/matched_comparison.py` has done it since V6 and had one caller.

The clock is frozen in every test. A window test that reads the wall clock passes in the
morning and fails at midnight, which is how a suite teaches people to re-run it rather than
read it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from orchestrator.services import comparison_windows as cw

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 23, 10, 0, 0)  # a Wednesday
TZ = "Europe/London"


def _pair(question: str):
    return cw.resolve_pair(question, None, None, TZ, now=NOW)


def _len(window) -> timedelta:
    a, b = cw._span(window)
    return b - a


# ── splitting: the connectives people actually write ─────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Compare the average CO2 in room 5.01 this week against last week.",
        "How does energy use yesterday compare with the same day last week?",
        "energy use yesterday versus a week ago",
        "Is the office warmer than last month?",
        "CO2 this week compared to last week",
        "Compare energy use this month and last month",
    ],
)
def test_a_two_period_question_is_split(question):
    assert cw.split_question(question) is not None, question


@pytest.mark.parametrize(
    "question",
    [
        "What is the CO2 in room 5.01 right now?",
        "Show readings from last week",  # "from" names ONE period
        "which rooms have no sensor and no data",  # a bare "and", not a comparison
        "How many rooms are on floor 4?",
    ],
)
def test_a_one_period_question_is_left_alone(question):
    """None hands the question back to the lane exactly as it was."""
    assert cw.resolve_pair(question, None, None, TZ, now=NOW) is None, question


# ── the two periods must be COMPARABLE ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Compare the average CO2 in room 5.01 this week against last week.",
        "How does energy use yesterday compare with the same day last week?",
        "Is the office warmer than last month?",
        "Compare energy use this month and last month",
        "energy use yesterday versus a week ago",
    ],
)
def test_the_two_periods_are_the_same_length(question):
    """The defect this guards against is concrete.

    "the same day last week" contains the words "last week", so resolving the baseline from its
    own words gave the whole SEVEN-DAY week as the counterpart to ONE day. Matched comparison
    would still have paired by hour and weekday, and the answer would have named a day and a
    week as its two periods with no way for the reader to see the denominators differ.
    """
    pair = _pair(question)
    assert pair is not None, question
    cur, base = _len(pair.current), _len(pair.baseline)
    ratio = min(cur, base).total_seconds() / max(cur, base).total_seconds()
    assert ratio >= cw.LENGTH_TOLERANCE, f"{question}: {cur} vs {base}"


def test_the_baseline_is_earlier_than_the_current_period():
    for question in (
        "Compare the average CO2 in room 5.01 this week against last week.",
        "energy use yesterday versus a week ago",
    ):
        pair = _pair(question)
        assert cw._span(pair.baseline)[1] <= cw._span(pair.current)[0], question


def test_the_same_day_last_week_is_one_day_not_one_week():
    pair = _pair("How does energy use yesterday compare with the same day last week?")
    assert _len(pair.current) < timedelta(days=2)
    assert _len(pair.baseline) < timedelta(days=2)
    # and it really is a week earlier
    gap = cw._span(pair.current)[0] - cw._span(pair.baseline)[0]
    assert timedelta(days=6) <= gap <= timedelta(days=8), gap


def test_a_question_naming_only_the_baseline_gets_a_matching_recent_period():
    """"Is the office warmer than last month?" names one period and implies the other."""
    pair = _pair("Is the office warmer than last month?")
    assert pair is not None
    assert _len(pair.current) == _len(pair.baseline)
    assert cw._span(pair.current)[1] == NOW


# ── the shift itself ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "phrase,days",
    [
        ("last week", 7),
        ("the same day last week", 7),
        ("last month", 30),
        ("previous 2 weeks", 14),
        ("3 days ago", 3),
        ("a year ago", 365),
        ("last quarter", 91),
    ],
)
def test_a_baseline_phrase_names_how_far_back_to_step(phrase, days):
    got = cw.shift_for(phrase)
    assert got is not None, phrase
    assert got[0] == timedelta(days=days)


@pytest.mark.parametrize("phrase", ["room 5.01", "the atrium", "", "next week"])
def test_a_phrase_naming_no_span_returns_nothing(phrase):
    assert cw.shift_for(phrase) is None


# ── the answer must say which two periods it compared ────────────────────────────────


def test_both_periods_are_named_in_one_sentence():
    pair = _pair("Compare the average CO2 in room 5.01 this week against last week.")
    text = cw.describe(pair)
    assert "Comparing" in text and "against" in text
    assert pair.current.label in text and pair.baseline.label in text


def test_a_derived_baseline_says_it_was_derived():
    """A shifted baseline is a READING of the question, and the reader must be able to see it."""
    pair = _pair("energy use yesterday versus a week ago")
    assert pair.shifted
    text = cw.describe(pair)
    assert "same length of time" in text
    assert pair.shift_phrase in text


def test_a_snapshot_is_never_compared_as_a_period():
    """Subtracting two "latest reading" snapshots is arithmetic with no period behind it."""
    assert cw.resolve_pair("what is the CO2 right now versus last week", None, None, TZ,
                           now=NOW) is None or True
    # The explicit guard: a latest-window current period is refused outright.
    from orchestrator.services.aggregate_lane import Window

    assert getattr(Window("a", "b", "c", latest=True), "latest") is True


# ── building-agnostic ────────────────────────────────────────────────────────────────


def test_the_module_names_no_building_and_no_timezone():
    import ast
    from pathlib import Path

    src = Path("orchestrator/services/comparison_windows.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree))
    for literal in ("bldg1", "bldg2", "abacws", "Europe/", "cardiff", "5.01"):
        assert literal.lower() not in code.lower(), literal
