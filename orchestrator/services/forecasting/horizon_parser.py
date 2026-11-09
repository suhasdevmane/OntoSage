"""
Horizon parser — extracts the forecast horizon from natural language queries.

Examples:
  "predict temperature for tomorrow"   → 24 hours, 1-hour steps
  "forecast CO2 next week"             → 7 days, 6-hour steps
  "what will humidity be next hour"    → 1 hour, 10-minute steps
  "predict energy for next month"      → 30 days, 12-hour steps
"""

import re
from dataclasses import dataclass
from datetime import timedelta


@dataclass
class ForecastHorizon:
    """Parsed forecast horizon with display metadata."""

    total: timedelta  # total horizon length
    step: timedelta  # resolution of each prediction point
    n_steps: int  # number of forecast steps
    label: str  # human-readable label, e.g. "next 24 hours"
    freq: str  # pandas frequency alias, e.g. "1h", "6h"


# Ordered by specificity (longer patterns first to avoid partial matches)
_HORIZON_RULES: list[tuple[str, timedelta, timedelta, str, str]] = [
    # (pattern, total, step, label, freq)
    (
        r"next\s+month|over\s+the\s+next\s+month|coming\s+month",
        timedelta(days=30),
        timedelta(hours=12),
        "next 30 days",
        "12h",
    ),
    (
        r"next\s+week|coming\s+week|over\s+the\s+next\s+week",
        timedelta(days=7),
        timedelta(hours=6),
        "next 7 days",
        "6h",
    ),
    (
        r"next\s+3\s+days|coming\s+3\s+days|over\s+the\s+next\s+3\s+days",
        timedelta(days=3),
        timedelta(hours=3),
        "next 3 days",
        "3h",
    ),
    (
        r"next\s+2\s+days|tomorrow\s+and\s+after",
        timedelta(days=2),
        timedelta(hours=2),
        "next 48 hours",
        "2h",
    ),
    (
        r"tomorrow|next\s+24\s+hours|over\s+the\s+next\s+24\s+hours",
        timedelta(hours=24),
        timedelta(hours=1),
        "next 24 hours",
        "1h",
    ),
    (
        r"next\s+12\s+hours|coming\s+12\s+hours",
        timedelta(hours=12),
        timedelta(minutes=30),
        "next 12 hours",
        "30min",
    ),
    (
        r"next\s+8\s+hours|coming\s+8\s+hours",
        timedelta(hours=8),
        timedelta(minutes=30),
        "next 8 hours",
        "30min",
    ),
    (
        r"next\s+6\s+hours|coming\s+6\s+hours|this\s+afternoon",
        timedelta(hours=6),
        timedelta(minutes=30),
        "next 6 hours",
        "30min",
    ),
    (
        r"next\s+4\s+hours|coming\s+4\s+hours",
        timedelta(hours=4),
        timedelta(minutes=30),
        "next 4 hours",
        "30min",
    ),
    (
        r"next\s+2\s+hours|coming\s+2\s+hours",
        timedelta(hours=2),
        timedelta(minutes=15),
        "next 2 hours",
        "15min",
    ),
    (
        r"next\s+hour|coming\s+hour|next\s+60\s+min",
        timedelta(hours=1),
        timedelta(minutes=10),
        "next hour",
        "10min",
    ),
    (
        r"next\s+30\s+min(?:utes?)?",
        timedelta(minutes=30),
        timedelta(minutes=5),
        "next 30 minutes",
        "5min",
    ),
]

_DEFAULT_HORIZON = ForecastHorizon(
    total=timedelta(hours=24),
    step=timedelta(hours=1),
    n_steps=24,
    label="next 24 hours",
    freq="1h",
)


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fourteen": 14,
    "twenty": 20,
    "thirty": 30,
    "forty-eight": 48,
    "a couple of": 2,
    "a few": 3,
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(w) for w in _NUMBER_WORDS), key=len, reverse=True)) + r")\b"
)
#: "the next 48 hours", "over the coming 10 days", "the following two weeks" -- any count of any
#: unit. The fixed table above was the only reading, so "the next three days" and "the next 48
#: hours" both fell through to the 24-hour default and were forecast for a day without a word
#: (2026-11-07).
_ANY_SPAN_RE = re.compile(
    r"\b(?:next|coming|following|upcoming)\s+(\d{1,3})\s*(min(?:ute)?s?|hours?|hrs?|days?|weeks?)\b"
)
_UNIT = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(days=7),
}
#: Steps the forecasters take, finest first, each with its pandas alias.
_STEPS = [
    (timedelta(minutes=5), "5min"),
    (timedelta(minutes=10), "10min"),
    (timedelta(minutes=15), "15min"),
    (timedelta(minutes=30), "30min"),
    (timedelta(hours=1), "1h"),
    (timedelta(hours=2), "2h"),
    (timedelta(hours=3), "3h"),
    (timedelta(hours=6), "6h"),
    (timedelta(hours=12), "12h"),
]
#: The longest horizon the table above offers; a longer ask is forecast to it and SAYS so.
_LONGEST = timedelta(days=30)


def _span_label(total: timedelta) -> str:
    if total % timedelta(days=1) == timedelta(0) and total >= timedelta(days=2):
        return f"next {total.days} days"
    hours = total / timedelta(hours=1)
    if hours >= 1:
        n = int(round(hours))
        return "next hour" if n == 1 else f"next {n} hours"
    return f"next {int(total / timedelta(minutes=1))} minutes"


def _any_span(q: str) -> "ForecastHorizon | None":
    m = _ANY_SPAN_RE.search(q)
    if not m or int(m.group(1)) <= 0:
        return None
    unit = m.group(2)[0]
    total = min(int(m.group(1)) * _UNIT[unit], _LONGEST)
    step, freq = next(((s, f) for s, f in _STEPS if total / s <= 60), _STEPS[-1])
    label = _span_label(total)
    if int(m.group(1)) * _UNIT[unit] > _LONGEST:
        label += " (the longest horizon this forecasts)"
    return ForecastHorizon(
        total=total, step=step, n_steps=max(1, int(total / step)), label=label, freq=freq
    )


def match_horizon(query: str) -> "ForecastHorizon | None":
    """Return the ForecastHorizon for a recognized phrase, or None (no default).

    V5-T12: this is the single deterministic horizon authority — the trend
    lane (via parse_horizon) and the deliberative CQ-IR compiler both resolve
    canonical phrases ("tomorrow", "next week") through THIS rule table, so
    identical phrases yield identical horizons in every lane.

    A count written as a word ("the next three days") is read as its digits first, and a count of
    any unit the table does not list ("the next 48 hours") is read by `_any_span`.
    """
    q = (query or "").lower()
    q = _NUMBER_WORD_RE.sub(lambda m: str(_NUMBER_WORDS[m.group(1)]), q)
    for pattern, total, step, label, freq in _HORIZON_RULES:
        if re.search(pattern, q):
            n_steps = max(1, int(total / step))
            return ForecastHorizon(
                total=total,
                step=step,
                n_steps=n_steps,
                label=label,
                freq=freq,
            )
    return _any_span(q)


def parse_horizon(query: str) -> ForecastHorizon:
    """Return a ForecastHorizon parsed from a natural language query."""
    return match_horizon(query) or _DEFAULT_HORIZON
