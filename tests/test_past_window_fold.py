# -*- coding: utf-8 -*-
"""BUG-183: "yesterday" must resolve in code, not depend on the compiler LLM's mood.

Forecast horizons are folded deterministically so "tomorrow" always means the same
thing. Past windows had no equivalent pass, so they rested entirely on the LLM —
which flagged "yesterday" as unparseable. That became an AmbiguitySignal, which made
the CQ-IR non-executable, which made the admission gate CLARIFY before any fetch: a
facility manager asking "which rooms had the highest occupancy yesterday?" was told
the request could not be mapped.

Genuinely vague anchors must STILL clarify — the fix resolves known phrases, it does
not guess.

V12-08 MOVED TWO PHRASES OUT OF THIS TABLE
------------------------------------------
"yesterday" and "today" used to live here, both mapped to 24.0 hours. A table of DURATIONS
cannot express a DATE, and mapping both to the same number meant ARBITER could not tell the
two commonest time words in the corpus apart: `fetch.py` turned either into `utcnow() - 24h`
with no upper bound, so an answer about yesterday was computed over a rolling window ending
now, half of it today, in the wrong zone. They are resolved to absolute local bounds by
`_fold_named_calendar_day` instead. BUG-183's invariant — a question saying "yesterday" must
never come back as a clarification — is unchanged and is pinned below against that fold.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.deliberation.compiler import (
    _fold_deterministic_past_window,
    _fold_named_calendar_day,
    match_past_window,
)
from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec

pytestmark = pytest.mark.unit


# ── the phrase table ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query, hours",
    [
        ("how noisy was it last night", 12.0),
        ("CO2 this morning", 12.0),
        ("temperature in the last hour", 1.0),
        ("noise over the past 6 hours", 6.0),
        ("occupancy over the last 3 days", 72.0),
        ("humidity last week", 168.0),
        ("energy last month", 720.0),
        ("what happened overnight", 12.0),
    ],
)
def test_known_past_phrases_resolve_to_a_window(query, hours):
    assert match_past_window(query) == hours


@pytest.mark.parametrize(
    "query",
    [
        "how was it recently",
        "occupancy a while back",
        "noise lately",
        "temperature at some point",
        "Which room is quietest right now?",
        "what will it be tomorrow",
    ],
)
def test_vague_or_future_phrases_are_not_resolved(query):
    """A vague anchor SHOULD clarify — resolving it would be a guess."""
    assert match_past_window(query) is None


@pytest.mark.parametrize("query", ["occupancy yesterday", "occupancy today"])
def test_a_named_day_is_not_in_the_hours_table_at_all(query):
    """Not an oversight: a date has no hours-of-history answer (V12-08).

    Both used to return 24.0 — the SAME duration for two different days — and the fetch
    layer read that as "the last 24 hours ending now". A phrase that names a day has to
    resolve to bounds or not at all; there is no correct number to put here.
    """
    assert match_past_window(query) is None


# ── the fold ─────────────────────────────────────────────────────────────────


def test_the_flagged_yesterday_case_is_resolved_and_the_signal_dropped():
    """BUG-183's invariant, now carried by the calendar-day fold.

    The facility manager's question must not come back as "I couldn't map part of your
    request (yesterday)". What changed in V12-08 is WHAT it resolves to: an interval with
    both ends, not a duration.
    """
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True, source_phrase="yesterday")
    dropped = _fold_named_calendar_day(
        spec,
        "Which rooms had the highest occupancy yesterday?",
        now=datetime(2026, 9, 12, 16, 0, 0),
    )
    assert dropped is True
    assert spec.basis == TimeBasis.WINDOW
    assert spec.unparseable is False
    assert (spec.resolved_start, spec.resolved_end) == (
        "2026-09-11 00:00:00",
        "2026-09-11 23:59:59",
    )
    assert spec.is_resolved_interval is True


def test_a_flagged_but_genuinely_vague_phrase_still_clarifies():
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True, source_phrase="recently")
    assert _fold_deterministic_past_window(spec, "how was occupancy recently", "recently") is False
    assert spec.unparseable is True, "the clarify signal must survive"


def test_a_clean_compile_is_never_second_guessed_by_the_hours_table():
    """No flag and a usable window -> the DURATION fold must not touch it."""
    spec = TimeSpec(basis=TimeBasis.WINDOW, window_hours=3.0)
    assert _fold_deterministic_past_window(spec, "occupancy last night", "") is False
    assert spec.window_hours == 3.0


def test_a_named_day_DOES_override_a_clean_compile():
    """The one deliberate exception, and the same rule the dialogue agent applies.

    A compiled `window_hours=3` against a question that says "yesterday" is not a third
    opinion worth preserving — it is the compile disagreeing with the question, and the
    question is the authoritative source. Overriding it is what stops "yesterday" being
    answered over three hours of this afternoon.
    """
    spec = TimeSpec(basis=TimeBasis.WINDOW, window_hours=3.0)
    assert (
        _fold_named_calendar_day(spec, "occupancy yesterday", now=datetime(2026, 9, 12, 16, 0))
        is True
    )
    assert spec.resolved_start == "2026-09-11 00:00:00"
    assert spec.window_hours != 3.0


def test_a_window_basis_missing_its_window_is_filled_from_the_phrase():
    spec = TimeSpec(basis=TimeBasis.WINDOW, window_hours=None)
    assert _fold_deterministic_past_window(spec, "occupancy over the last 3 days", "") is True
    assert spec.window_hours == 72.0


def test_a_forecast_compile_is_left_alone():
    """'tomorrow' belongs to the horizon fold; this one must not claim it."""
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=24.0)
    assert _fold_deterministic_past_window(spec, "what will CO2 be tomorrow", "") is False
    assert spec.basis == TimeBasis.FORECAST


def test_the_source_phrase_is_preserved_for_the_dossier():
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True)
    _fold_deterministic_past_window(spec, "occupancy last night", "last night")
    assert spec.source_phrase == "last night"


def test_a_forecast_compile_is_left_alone_by_the_calendar_fold_too():
    """"How will it be today" asks about hours that have not happened. Resolving it to a
    past interval would answer a question nobody asked."""
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=24.0)
    assert _fold_named_calendar_day(spec, "what will CO2 be like today", now=datetime.now()) is False
    assert spec.basis == TimeBasis.FORECAST
    assert spec.is_resolved_interval is False
