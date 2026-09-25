# -*- coding: utf-8 -*-
"""Two periods named in one question, resolved as two windows (W1-04).

WHAT WAS MISSING, MEASURED 2026-09-23
--------------------------------------
    "Compare the average CO2 in room 5.01 this week against last week."
    -> "The data set only contains hourly averages for a 14-hour window, not weekly totals ...
        the available data does not allow a comparison of this week's average CO2 to last
        week's."

    "How does energy use yesterday compare with the same day last week?"
    -> "I couldn't answer that from Abacws Building's records."

The first answer is honest and the second is a decline, and both have the same cause: ONE
window is resolved per turn, so the baseline period is never fetched and there is nothing to
compare against. The arithmetic was never the gap.

WHAT ALREADY EXISTED, AND IS NOT REBUILT HERE
----------------------------------------------
`evidence/matched_comparison.py` (V6-T41) already compares two series like with like: it pairs
samples on hour-of-day and weekday so a Tuesday afternoon meets Tuesday afternoons, DISCARDS
what it cannot pair and says how many, reports the effect with a confidence interval, and names
the confounders it could not adjust for. It had exactly one caller. This module's whole job is
to produce the second series for it.

`aggregate_lane.resolve_window` already turns "this week", "last week", a calendar day or
"the last N hours" into a store-clock window, timezone-correctly. It is reused verbatim for
each half rather than reimplemented -- a second reading of "this week" would be a second answer
to a question that already has one owner, which is the defect shape this repo keeps paying for.

HOW A BASELINE IS RESOLVED, AND WHY THE SHIFT IS THE FALLBACK AND NOT THE RULE
------------------------------------------------------------------------------
A baseline phrase that names a period outright ("last week", "March") is resolved by the same
function as the current window. Only when that fails does this fall back to SHIFTING the
current window back by the span the phrase names -- which is what "the same day last week"
means and what no calendar parser would get from those four words. The shift preserves the
current window's length and its position within the period, so "yesterday vs the same day last
week" compares one day against one day, not one day against seven.

BUILDING-AGNOSTIC. No building, zone, sensor or timezone is named here; the timezone is the
caller's and the clock is `requested_interval`'s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: The connectives people put between two periods. The question is split at the FIRST one, so
#: everything before it describes the current period and everything after it the baseline.
#:
#: "than" earns its place from "is it warmer than last month"; "from" does NOT, because
#: "readings from last week" names one period, not two.
_SPLIT_RE = re.compile(
    # "compare(d|s) with/to/against" covers both "energy use yesterday COMPARED WITH last week"
    # and "how does energy use yesterday COMPARE WITH the same day last week" -- the second is
    # the commoner spoken form and matching only the past participle missed it entirely.
    r"\s+(?:compares?d?\s+(?:with|to|against)|as\s+compared\s+to|versus|vs\.?|against|"
    r"than|relative\s+to|but\s+for)\s+",
    re.IGNORECASE,
)

#: "compare X with Y" / "compare X and Y" -- the verb-first shape, where the connective is a
#: bare "with"/"and" that would be far too common to split on unconditionally.
_COMPARE_LEAD_RE = re.compile(r"^\s*compare\b", re.IGNORECASE)
_LEAD_SPLIT_RE = re.compile(r"\s+(?:with|and|to)\s+", re.IGNORECASE)

#: A baseline phrase that names no period of its own but names a SPAN to step back by. The
#: number is optional: "last week" is one week.
_SHIFT_RE = re.compile(
    r"\b(?:the\s+)?(?:same\s+\w+\s+)?"
    r"(?:last|previous|prior|preceding)\s+(?:(\d+)\s+)?"
    r"(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    re.IGNORECASE,
)

#: A whole-period word on its own ("a year ago", "12 months ago").
_AGO_RE = re.compile(
    r"\b(?:(\d+)\s+)?(day|days|week|weeks|month|months|quarter|quarters|year|years)\s+(?:ago|earlier|before)\b",
    re.IGNORECASE,
)

_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 91, "year": 365}

#: How close in length two periods must be to be compared as given. A calendar month
#: against a calendar month varies by up to 10%, and a day against a week does not come
#: close, which is the case this exists to reject.
LENGTH_TOLERANCE = 0.8


@dataclass
class WindowPair:
    """The two periods an answer must state. ``shifted`` records how the baseline was found."""

    current: object  # aggregate_lane.Window
    baseline: object  # aggregate_lane.Window
    #: True when the baseline was derived by stepping the current window back rather than by
    #: reading a period out of the words. Worth saying in the answer: a derived baseline is an
    #: interpretation of the question, and a reader who meant something else should be able to see
    #: that it was interpreted.
    shifted: bool = False
    shift_phrase: str = ""


def split_question(question: str) -> Optional[Tuple[str, str]]:
    """``(current_phrase, baseline_phrase)``, or None when the question names one period."""
    q = " ".join(str(question or "").split())
    if not q:
        return None
    parts = _SPLIT_RE.split(q, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    if _COMPARE_LEAD_RE.search(q):
        # "Compare the average CO2 this week with last week" -- only split on a bare with/and
        # when the sentence opens with the verb, so "the rooms with no sensor and the ones
        # without data" is never torn in half.
        parts = _LEAD_SPLIT_RE.split(q, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None


def shift_for(phrase: str) -> Optional[Tuple[timedelta, str]]:
    """How far back a baseline phrase steps, and the words it was read from."""
    text = str(phrase or "")
    for rx in (_SHIFT_RE, _AGO_RE):
        m = rx.search(text)
        if not m:
            continue
        n = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2).rstrip("s")
        days = _DAYS.get(unit)
        if not days:
            continue
        return timedelta(days=n * days), m.group(0).strip()
    return None


def _span_words(delta: timedelta) -> str:
    """"7 days" / "24 hours" — the length of a period, for a label a reader can check."""
    days = delta.days
    if days >= 1:
        return f"{days} day" + ("s" if days != 1 else "")
    hours = max(1, round(delta.total_seconds() / 3600))
    return f"{hours} hour" + ("s" if hours != 1 else "")


def _span(window) -> Optional[Tuple[datetime, datetime]]:
    from orchestrator.services.aggregate_lane import _stamp

    a, b = _stamp(getattr(window, "start", None)), _stamp(getattr(window, "end", None))
    return (a, b) if a and b else None


def resolve_pair(
    question: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tz_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[WindowPair]:
    """Both periods a comparison question names, or None when it names only one.

    None is the normal answer for most questions and leaves the lane exactly as it was.
    """
    from orchestrator.services.aggregate_lane import STAMP, Window, resolve_window

    halves = split_question(question)
    if not halves:
        return None
    current_text, baseline_text = halves

    shift = shift_for(baseline_text)

    current = resolve_window(current_text, start_date, end_date, tz_name, now=now)
    if current is None and (start_date or end_date):
        # The pipeline's bounds describe the CURRENT period; without words of its own the
        # current half still has them. Only consulted when bounds exist -- re-reading the WHOLE
        # question here would find the BASELINE's words ("warmer than last month") and set the
        # current period to the baseline, comparing a period against itself.
        current = resolve_window(current_text or question, start_date, end_date, tz_name, now=now)
    if current is None and shift:
        # "Is the office warmer than last month?" names one period and implies the other: the
        # comparison is against the recent past of the SAME LENGTH, which is the only reading
        # that keeps the two sides comparable. Stated in `describe`, because it is a reading of
        # the question and not something the question said.
        from orchestrator.services.requested_interval import store_now

        end_dt = now or store_now()
        current = Window(
            (end_dt - shift[0]).strftime(STAMP),
            end_dt.strftime(STAMP),
            f"the last {_span_words(shift[0])} (building time)",
        )
    if current is None or current.latest:
        # A "latest reading" window is a snapshot, not a period, and subtracting two snapshots
        # is the confidently-wrong arithmetic this lane exists to avoid.
        return None
    cur_span = _span(current)
    if not cur_span:
        return None

    # 1. the baseline names its own period -- but only if it is the SAME LENGTH.
    #
    # "How does energy use yesterday compare with the same day last week?" resolved its baseline
    # to the whole of last week, because "last week" is in those words: one DAY against seven.
    # Matched comparison would still pair by hour and weekday, but the periods named in the
    # answer would be a day and a week, and the reader has no way to see that the denominators
    # differ. Comparing like with like is the entire point, so a baseline that is not the same
    # size as the current period loses to the shift below, which is the same size by
    # construction. `LENGTH_TOLERANCE` leaves room for a month against a month.
    baseline = resolve_window(baseline_text, None, None, tz_name, now=now)
    base_span = _span(baseline) if baseline is not None else None
    if baseline is not None and not baseline.latest and base_span and base_span != cur_span:
        cur_len = (cur_span[1] - cur_span[0]).total_seconds()
        base_len = (base_span[1] - base_span[0]).total_seconds()
        comparable = cur_len > 0 and base_len > 0 and (
            min(cur_len, base_len) / max(cur_len, base_len) >= LENGTH_TOLERANCE
        )
        if comparable or not shift:
            if not comparable:
                logger.info(
                    "[comparison_windows] periods differ in length "
                    f"({cur_len / 3600:.1f}h vs {base_len / 3600:.1f}h) and the words name no "
                    "shift — comparing them as given"
                )
            return WindowPair(current=current, baseline=baseline)

    # 2. otherwise step the current window back by the span the words name
    if not shift:
        return None
    delta, phrase = shift
    start, end = cur_span[0] - delta, cur_span[1] - delta
    label = f"{phrase} — the same period shifted back"
    return WindowPair(
        current=current,
        baseline=Window(start.strftime(STAMP), end.strftime(STAMP), label),
        shifted=True,
        shift_phrase=phrase,
    )


def describe(pair: WindowPair) -> str:
    """One sentence naming BOTH periods.

    An answer that reports a difference without saying which two periods it is between cannot be
    checked by the person reading it, and this comparison has an interpretation in it whenever
    `shifted` is true.
    """
    line = f"Comparing {pair.current.label} against {pair.baseline.label}."
    if pair.shifted:
        line += (
            f" I read “{pair.shift_phrase}” as the same length of time one step earlier,"
            " so the two periods are the same size."
        )
    return line
