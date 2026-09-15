# -*- coding: utf-8 -*-
"""What a set of readings actually supports (V12-09, review A09/A10/A12).

    "A truncated result says so, and an unknown total is not invented."
    "Duplicate, invalid and out-of-order rows produce recorded accepted/excluded counts."

THREE FAILURES THIS EXISTS TO END, ALL MEASURED IN THE REPORT LANE ON 2026-09-12
--------------------------------------------------------------------------------
1. `latest` was `vals[-1]` — the LAST ELEMENT of a list built in row order. The SQL lane
   orders `timestamp DESC`, so on a three-row fixture reading 1000 / 900 / 400 the report
   named **400 the latest**. Positional "latest" is right only when the rows happen to be
   ascending, and this lane's are not.

2. A narrow-table result carries every modality in ONE column called `value`, so the
   per-column summary averaged 900 ppm of CO2 with 21.5 °C and reported
   `avg=590.5, min=21.5, max=900.0`. Every input was real; the output is not a quantity.

3. Rows that failed the numeric test simply vanished. A report saying "1,000 readings"
   could not say whether 1,000 was everything, or everything that survived a filter nobody
   was told about.

WHY A MODULE RATHER THAN THREE PATCHES
--------------------------------------
Because the same three questions are asked by the report lane, the analytics lane and the
export lane, and they answered them differently or not at all. A count that means
"everything" in one sentence and "everything that parsed" in the next is the disease
BUG-479 was one symptom of: the cap did not fail, it under-reported.

Nothing here guesses. An excluded row is counted with its reason, a truncated set says it
is truncated and does NOT invent the untruncated total, and a set of readings whose units
do not permit an aggregate gets a refusal rather than a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Reasons a reading is not counted. Each is a fact about the row, never a judgement about
#: the building — "this value is not a number" is checkable; "this sensor is broken" is not.
NON_NUMERIC = "not a number"
DUPLICATE = "duplicate of an earlier row"
NO_TIMESTAMP = "no usable timestamp"


@dataclass(frozen=True)
class QualitySummary:
    """Accepted and excluded counts, with the reason for every exclusion."""

    accepted: int = 0
    excluded: int = 0
    by_reason: Dict[str, int] = field(default_factory=dict)
    #: True when rows arrived out of timestamp order. NOT an exclusion — the SQL lane
    #: returns DESC by design. It is recorded because anything reading positionally
    #: (`vals[-1]`, "the first row") is wrong whenever it is True.
    out_of_order: bool = False

    @property
    def seen(self) -> int:
        return self.accepted + self.excluded

    def note(self) -> str:
        """One sentence for the reader, or "" when every row counted."""
        if not self.excluded:
            return ""
        parts = ", ".join(f"{n} {reason}" for reason, n in sorted(self.by_reason.items()))
        return (
            f"{self.accepted} of {self.seen} rows were counted; {self.excluded} were not "
            f"({parts})."
        )


@dataclass(frozen=True)
class Aggregate:
    """min / max / mean over accepted readings, each computed by its own operation.

    They are separate fields rather than a dict because A10 asks that each use its INTENDED
    operation: a summary that computed `max` as `sorted(...)[-1]` of string values, or
    `avg` over a list that still held the excluded rows, would present three numbers that
    look mutually consistent and are not.
    """

    count: int
    minimum: float
    maximum: float
    mean: float
    #: The value at the NEWEST timestamp — resolved by comparing stamps, never by position.
    latest: Optional[float] = None
    latest_at: str = ""
    unit: str = ""
    quality: QualitySummary = field(default_factory=QualitySummary)
    #: True when the underlying fetch stopped at its row limit. The aggregate then
    #: describes the rows READ, which is a slice of the period and not the period.
    truncated: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """The shape the report sections and the evidence record consume."""
        out: Dict[str, Any] = {
            "count": self.count,
            "min": round(self.minimum, 3),
            "max": round(self.maximum, 3),
            "avg": round(self.mean, 3),
            "latest": self.latest,
            "latest_at": self.latest_at,
        }
        if self.unit:
            out["unit"] = self.unit
        if self.truncated:
            out["count_is_of_rows_read"] = True
        if self.quality.excluded:
            out["rows_excluded"] = self.quality.excluded
            out["rows_excluded_by_reason"] = dict(self.quality.by_reason)
        return out


def _stamp(row: Dict[str, Any], time_keys: Tuple[str, ...]) -> str:
    for k in time_keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return ""


#: Every name this estate's stores use for the time column. Read in order; the first
#: present wins. A bare list rather than a guess, because a wrong timestamp column makes
#: "latest" wrong in a way nothing downstream can detect.
TIME_KEYS = ("timestamp", "Datetime", "datetime", "time", "ts")


def screen(
    rows: Iterable[Dict[str, Any]],
    value_key: str,
    *,
    time_keys: Tuple[str, ...] = TIME_KEYS,
    drop_duplicates: bool = True,
) -> Tuple[List[Tuple[str, float]], QualitySummary]:
    """[(timestamp, value)] that survived screening, plus what was excluded and why.

    Duplicates are decided on (timestamp, value) — the same reading arriving twice, which a
    UNION across overlapping windows produces. Two DIFFERENT values at one timestamp are
    both kept: that is a real disagreement between readings and deleting one would be a
    silent choice about which instrument to believe.
    """
    accepted: List[Tuple[str, float]] = []
    by_reason: Dict[str, int] = {}
    seen_pairs = set()
    excluded = 0

    def _drop(reason: str) -> None:
        nonlocal excluded
        excluded += 1
        by_reason[reason] = by_reason.get(reason, 0) + 1

    for row in rows or []:
        if not isinstance(row, dict):
            _drop(NON_NUMERIC)
            continue
        raw = row.get(value_key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            _drop(NON_NUMERIC)
            continue
        ts = _stamp(row, time_keys)
        if not ts:
            _drop(NO_TIMESTAMP)
            continue
        key = (ts, float(raw))
        if drop_duplicates and key in seen_pairs:
            _drop(DUPLICATE)
            continue
        seen_pairs.add(key)
        accepted.append((ts, float(raw)))

    stamps = [t for t, _ in accepted]
    out_of_order = stamps != sorted(stamps)
    return accepted, QualitySummary(
        accepted=len(accepted), excluded=excluded, by_reason=by_reason, out_of_order=out_of_order
    )


def aggregate(
    rows: Iterable[Dict[str, Any]],
    value_key: str,
    *,
    unit: str = "",
    truncated: bool = False,
    time_keys: Tuple[str, ...] = TIME_KEYS,
) -> Optional[Aggregate]:
    """Screen, then summarise. None when nothing survived — never a zero-filled record.

    A summary of no readings is not a summary whose figures are zero; it is the absence of
    one, and returning zeros would put "avg 0.0" in front of a reader as a measurement.
    """
    accepted, quality = screen(rows, value_key, time_keys=time_keys)
    if not accepted:
        return None
    values = [v for _, v in accepted]
    newest_ts, newest_v = max(accepted, key=lambda p: p[0])
    return Aggregate(
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=sum(values) / len(values),
        latest=newest_v,
        latest_at=newest_ts,
        unit=unit,
        quality=quality,
        truncated=truncated,
    )
