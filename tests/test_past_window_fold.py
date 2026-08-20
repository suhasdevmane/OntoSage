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
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.compiler import (
    _fold_deterministic_past_window,
    match_past_window,
)
from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec

pytestmark = pytest.mark.unit


# ── the phrase table ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query, hours",
    [
        ("Which rooms had the highest occupancy yesterday?", 24.0),
        ("how noisy was it last night", 12.0),
        ("CO2 this morning", 12.0),
        ("occupancy today", 24.0),
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


# ── the fold ─────────────────────────────────────────────────────────────────


def test_the_flagged_yesterday_case_is_resolved_and_the_signal_dropped():
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True, source_phrase="yesterday")
    dropped = _fold_deterministic_past_window(
        spec, "Which rooms had the highest occupancy yesterday?", "yesterday"
    )
    assert dropped is True
    assert spec.basis == TimeBasis.WINDOW
    assert spec.window_hours == 24.0
    assert spec.unparseable is False


def test_a_flagged_but_genuinely_vague_phrase_still_clarifies():
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True, source_phrase="recently")
    assert _fold_deterministic_past_window(spec, "how was occupancy recently", "recently") is False
    assert spec.unparseable is True, "the clarify signal must survive"


def test_a_clean_compile_is_never_second_guessed():
    """No flag and a usable window -> the fold must not touch it."""
    spec = TimeSpec(basis=TimeBasis.WINDOW, window_hours=3.0)
    assert _fold_deterministic_past_window(spec, "occupancy yesterday", "") is False
    assert spec.window_hours == 3.0


def test_a_window_basis_missing_its_window_is_filled_from_the_phrase():
    spec = TimeSpec(basis=TimeBasis.WINDOW, window_hours=None)
    assert _fold_deterministic_past_window(spec, "occupancy yesterday", "") is True
    assert spec.window_hours == 24.0


def test_a_forecast_compile_is_left_alone():
    """'tomorrow' belongs to the horizon fold; this one must not claim it."""
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=24.0)
    assert _fold_deterministic_past_window(spec, "what will CO2 be tomorrow", "") is False
    assert spec.basis == TimeBasis.FORECAST


def test_the_source_phrase_is_preserved_for_the_dossier():
    spec = TimeSpec(basis=TimeBasis.NOW, unparseable=True)
    _fold_deterministic_past_window(spec, "occupancy yesterday", "yesterday")
    assert spec.source_phrase == "yesterday"
