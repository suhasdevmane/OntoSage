# -*- coding: utf-8 -*-
"""Recurring time-of-day windows: "every night", "after hours", "by lunchtime" (V6-T40).

The time-series path builds only ``ts >= start AND ts <= end``. There is no way to express
*"every night between 00:00 and 05:00 across the last 30 days"*, so a whole family of
questions is unanswerable for a structural reason rather than a data one -- night-time water
baselines, after-hours energy waste, "the bins are full by lunchtime", overnight conditioning.

One shared primitive unlocks all of them, which is why it is worth doing properly rather than
adding a special case per question. `config/recipes.yaml` even declares a
``night_leak_threshold`` that nothing can currently evaluate at night.

**The default window comes from the building, not from this file.** A building declaring
07:00-21:00 has different "after hours" from one running 24/7, and hard-coding 08:00-18:00
would be a building literal wearing a clock face. Where a building declares nothing, the mask
is left unset and the caller answers over the whole range rather than inventing a schedule.

**Masks wrap.** A night window is 22:00-06:00, which is not a range in the arithmetic sense.
Getting this wrong silently returns zero rows and looks like "no data at night".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class HourMask:
    """A recurring daily window, optionally restricted to weekdays or weekends."""

    start_hour: int
    end_hour: int
    weekdays_only: bool = False
    weekends_only: bool = False
    label: str = ""

    @property
    def wraps(self) -> bool:
        """True for a window crossing midnight, e.g. 22:00-06:00."""
        return self.end_hour <= self.start_hour

    def covers(self, when: datetime) -> bool:
        if self.weekdays_only and when.weekday() >= 5:
            return False
        if self.weekends_only and when.weekday() < 5:
            return False
        h = when.hour
        if self.wraps:
            return h >= self.start_hour or h < self.end_hour
        return self.start_hour <= h < self.end_hour

    def sql_predicate(self, column: str = "datetime") -> str:
        """A dialect-neutral HOUR() predicate for the adapters.

        Emitted as SQL text rather than applied in Python on purpose: filtering after the
        fetch would drag a month of one-minute rows across the wire to keep the 6 hours the
        question asked about.
        """
        if self.wraps:
            clause = f"(HOUR({column}) >= {self.start_hour} OR HOUR({column}) < {self.end_hour})"
        else:
            clause = f"(HOUR({column}) >= {self.start_hour} AND HOUR({column}) < {self.end_hour})"
        if self.weekdays_only:
            clause += f" AND DAYOFWEEK({column}) BETWEEN 2 AND 6"
        elif self.weekends_only:
            clause += f" AND DAYOFWEEK({column}) IN (1, 7)"
        return clause

    def describe(self) -> str:
        base = self.label or f"{self.start_hour:02d}:00-{self.end_hour:02d}:00"
        if self.weekdays_only:
            return f"{base} on weekdays"
        if self.weekends_only:
            return f"{base} at weekends"
        return base


#: Phrase -> mask builder. Deliberately conservative: a phrase that could mean several things
#: ("this morning" -- of which day?) is left out, because a wrong window silently answers a
#: different question and looks authoritative doing it.
_PATTERNS: List[Tuple[str, str]] = [
    (r"\bovernight\b|\bat night\b|\bnight-?time\b|\bevery night\b|\bduring the night\b", "night"),
    (
        r"\bafter hours\b|\bout of hours\b|\boutside (?:of )?(?:opening |working )?hours\b",
        "after_hours",
    ),
    (
        r"\bworking hours\b|\bduring the (?:working )?day\b|\bin hours\b|\boffice hours\b",
        "in_hours",
    ),
    (r"\bby lunchtime\b|\bat lunchtime\b|\bover lunch\b|\blunch ?time\b", "lunchtime"),
    (r"\bmornings?\b|\bin the morning\b", "morning"),
    (r"\bafternoons?\b|\bin the afternoon\b", "afternoon"),
    (r"\bevenings?\b|\bin the evening\b", "evening"),
    (r"\bweekends?\b", "weekend"),
    (r"\bweekdays?\b", "weekday"),
]


def detect_mask(
    question: str,
    occupied_start_hour: Optional[int] = None,
    occupied_end_hour: Optional[int] = None,
) -> Optional[HourMask]:
    """Read a recurring window out of the question, or return None.

    None means "no recurring window was asked for" and the caller uses the whole range. It
    must never be read as a default schedule: inventing one would answer a question about
    all hours as though it were about business hours.
    """
    q = (question or "").lower()
    kind = next((k for pat, k in _PATTERNS if re.search(pat, q)), None)
    if kind is None:
        return None

    # Occupied hours come from the building; the fallbacks below are used ONLY when it
    # declares none, and only for phrases that need a schedule to mean anything.
    start = occupied_start_hour
    end = occupied_end_hour

    if kind == "night":
        return HourMask(22, 6, label="overnight")
    if kind == "lunchtime":
        return HourMask(11, 14, label="around lunchtime")
    if kind == "morning":
        return HourMask(6, 12, label="mornings")
    if kind == "afternoon":
        return HourMask(12, 18, label="afternoons")
    if kind == "evening":
        return HourMask(18, 22, label="evenings")
    if kind == "weekend":
        return HourMask(0, 24, weekends_only=True, label="weekends")
    if kind == "weekday":
        return HourMask(0, 24, weekdays_only=True, label="weekdays")

    if kind in ("after_hours", "in_hours"):
        if start is None or end is None:
            # Without the building's own schedule these phrases have no fixed meaning, and
            # guessing would answer a different question. Decline the mask instead.
            logger.info(
                "[time_windows] '%s' needs the building's occupied hours, which are not "
                "declared; answering over the whole range instead",
                kind,
            )
            return None
        if kind == "in_hours":
            return HourMask(start, end, weekdays_only=True, label="during opening hours")
        return HourMask(end, start, label="outside opening hours")

    return None


def filter_samples(
    samples: Sequence[Tuple[datetime, float]], mask: Optional[HourMask]
) -> List[Tuple[datetime, float]]:
    """Apply a mask in Python. For fixtures and adapters with no HOUR() support."""
    if mask is None:
        return list(samples)
    return [(t, v) for t, v in samples if mask.covers(t)]


def nightly_minimums(
    samples: Sequence[Tuple[datetime, float]], mask: HourMask
) -> List[Tuple[str, float]]:
    """The minimum value per night, which is the standard slow-leak test (feeds V6-T44).

    A leak shows as a night minimum that never returns to zero. A single-reading threshold
    cannot see it -- 0.3 L/min against a daytime median of 12 L/min sits far below any
    sensible daytime threshold, which is exactly why the existing check never fires.
    """
    per_night: dict = {}
    for t, v in samples:
        if not mask.covers(t):
            continue
        # A window crossing midnight belongs to the night it STARTED, so 02:00 Tuesday is
        # part of Monday night. Bucketing by calendar date would split every night in two
        # and halve the apparent minimum.
        night = (
            t.date().isoformat()
            if t.hour >= mask.start_hour
            else (t.replace(hour=12) - __import__("datetime").timedelta(days=1)).date().isoformat()
        )
        per_night[night] = min(per_night.get(night, v), v)
    return sorted(per_night.items())
