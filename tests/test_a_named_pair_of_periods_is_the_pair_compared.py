# -*- coding: utf-8 -*-
"""BUG-936 — "this week against last week" must compare this week against last week.

Measured live on Tuesday 2026-09-29, ISO week 40:

    "Compare energy use this week against last week."
    -> "**The daily average energy use FELL by 426 kWh per day, from 2,239 kWh per day in
        2026-W38 to 1,813 kWh per day in 2026-W39 (a 19.0 % DECREASE).**"

Measured directly against `sensordb.energy_data`, session pinned to `+00:00`, summed over the
six meters that carry rows in each window: this week 3,764 kWh over 1.689 d = 2,229 per day;
last week 12,621 kWh over 6.948 d = 1,816 per day. **The true change is UP 22.7 %.**

Every figure in that answer is correct and neither week it names was asked for. Two mechanisms
compose into it, and each gets its own tests below:

1.  The CURRENT period is partial by definition, so `_complete_buckets` — which exists for a
    good reason (BUG-627: a half-filled edge bucket read as a change in the building) — drops
    it, and the comparison falls back to the two newest COMPLETE periods. The week the user
    asked about is not in the answer at all.
2.  The fetch was additionally truncated (`[sql] group energy_data returned exactly its
    1000-row limit`), which cut the window off INSIDE 2026-W38 — and the answer then told the
    user that a week which had ended nine days earlier was "still in progress, covering only
    77 of 168 hours". A bucket short at the OLD end is truncated; only the newest can be
    filling.

The first root cause recorded for this defect was wrong (it guessed a bad week label used as a
sort key) and was falsified by one line of the orchestrator log. See lessons.md #145.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import series_summary
from orchestrator.services.series_summary import _names_this_against_last

pytestmark = pytest.mark.unit


# ── which two periods get compared ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,size,expected",
    [
        ("Compare energy use this week against last week.", "week", True),
        ("compare this week's electricity use with last week", "week", True),
        ("energy use this month versus the previous month", "month", True),
        ("how did this year compare with the prior year", "year", True),
        # one half only — a single period, not a pair
        ("how much energy did we use this week?", "week", False),
        ("how much energy did we use last week?", "week", False),
        # a pair, but not of the same unit: nothing here can order those two buckets
        ("this week against last month", "week", False),
        # the generic change question `_complete_buckets` is right for
        ("how has energy use changed over the last few weeks", "week", False),
        ("is energy use trending up?", "week", False),
        # the bucket size must match the words, or a day-bucketed answer would claim the pair
        ("Compare energy use this week against last week.", "day", False),
    ],
)
def test_it_recognises_a_named_pair_and_only_a_named_pair(question, size, expected):
    assert _names_this_against_last(question, size) is expected, question


def test_a_named_pair_takes_the_two_newest_buckets_not_the_two_newest_complete_ones():
    src = inspect.getsource(series_summary.summarise_periods)
    assert "named_pair = _names_this_against_last(question, size)" in src
    assert "cmp_from, cmp_to = ordered[-2], ordered[-1]" in src


def test_everything_else_still_compares_complete_buckets():
    """BUG-627 is not being undone. "How has energy use changed" must keep dropping a
    half-filled edge bucket, or the measurement window is reported as a change in the
    building."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "cmp_from, cmp_to = whole[0], whole[-1]" in src
    assert "_complete_buckets(ordered, per_bucket)" in src


def test_the_change_and_the_in_progress_set_both_follow_the_chosen_pair():
    """If these came apart, the headline would describe one pair and the caveats another."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "first, last = _cmp(cmp_from), _cmp(cmp_to)" in src
    assert "dict.fromkeys((cmp_from, cmp_to))" in src
    assert "in {cmp_from} to " in src and "in {cmp_to} " in src


def test_a_period_asked_for_by_name_is_not_also_reported_as_excluded():
    """It would be incoherent to compare a period and then say it was left out."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "partial = [b for b in partial if b not in (cmp_from, cmp_to)]" in src


def test_the_partial_period_is_compared_as_a_rate_not_dropped():
    """This is what makes including the current period safe: a shorter period must never be
    reported as a smaller total. The machinery already existed; it is now reachable."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "by_rate = is_energy and bool(in_progress)" in src


def test_the_extremes_survive_an_empty_complete_set():
    """`whole` is never empty today, but the named pair must not depend on that staying true."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "_extremes = whole or [cmp_from, cmp_to]" in src


# ── short at which end? ──────────────────────────────────────────────────────────────


def test_only_the_newest_short_bucket_is_called_in_progress():
    src = inspect.getsource(series_summary.summarise_periods)
    assert "if b == cmp_to:" in src, "the current period is the only one that can be filling"
    block = src[src.index("if b == cmp_to:") :]
    assert "still in progress" in block


def test_an_older_short_bucket_is_described_as_truncated_and_forbidden_the_other_wording():
    """The live answer said a week that ended nine days earlier was "still in progress". That
    is false on its face, and it is the sentence a reader uses to discount the figure."""
    src = inspect.getsource(series_summary.summarise_periods)
    assert "TRUNCATED AT THE START" in src
    older = src[src.index("TRUNCATED AT THE START") :]
    # the instruction to the narrator has to be explicit, because the other branch's wording
    # is the one it has seen most often
    assert "NOT still in progress" in older
    assert "BEGIN INSIDE IT" in older


def test_the_truncated_wording_says_it_is_a_fact_about_the_query():
    """ "because the fetched readings begin inside it, not because anything changed in the
    building" — a reader must not take a short bucket as a quiet week."""
    src = inspect.getsource(series_summary.summarise_periods)
    older = src[src.index("TRUNCATED AT THE START") :]
    assert "not " in older and "changed in the building" in older


def test_the_reason_is_recorded_beside_the_code():
    src = inspect.getsource(series_summary.summarise_periods)
    assert "BUG-936" in src
    assert "BUG-627" in src, "the rule being narrowed must be named where it is narrowed"


# ── BUG-937: a derived figure the narrator can get wrong ─────────────────────────────


def test_the_spread_is_given_to_the_narrator_not_left_as_a_subtraction():
    """Live 2026-09-29, "Is floor 3 warmer than floor 4?": "Floor 4 ... range from 20.4 C to
    25.4 C. The spread on Floor 4 is 4.0 C compared to 4.6 C on Floor 3, indicating a
    marginally wider variation on Floor 4."

    25.4 - 20.4 = 5.0, not 4.0. And 4.0 is not wider than 4.6, so the clause contradicts even
    the wrong number. Both halves are checkable without touching the store, which is what makes
    this a narration defect rather than a data one. The verdict itself ("they are tied") was
    correct and is what BUG-885 was opened about.
    """
    src = inspect.getsource(series_summary.summarise_groups)
    assert "spread {_fmt(max(values) - min(values))}" in src
    assert "BUG-937" in src


def test_the_range_is_still_given_too():
    """The spread replaces a subtraction, not the extremes: "how warm does it get" needs the
    max, and a spread alone cannot answer it."""
    src = inspect.getsource(series_summary.summarise_groups)
    assert "range {_fmt(min(values))} to {_fmt(max(values))}" in src


def test_the_narrator_is_still_told_not_to_recompute():
    """Handing it the figure only helps if it is also told to quote rather than derive."""
    src = inspect.getsource(series_summary.summarise_groups)
    assert "do not " in src and "recompute them" in src
