# -*- coding: utf-8 -*-
"""A chart, and the words about it, exist only when a series was actually fetched (defect class C19).

Two failures on the 2026-09-18 held-out reads:

* a question about notification provisions produced *"The bar chart compares the availability of
  audible alerts ... across monitoring scenarios"* with an image link and NO data behind it. The
  visualization step received rows that were not a series (graph bindings), asked a model to invent
  plotting code for them, and asked a model to describe the result -- so the description was
  fiction about a chart made of nothing;
* another answer ended *"I summarised the data above but couldn't render the chart this time"*
  after an answer that had no data to summarise.

The rules, all pure functions so they are tested without a model:

1. only rows that carry a measured value are plottable; graph bindings and empty results are not;
2. plotting code written by a model may not contain figures that are not in the data it was given;
3. a caption states figures only when statistics were computed from the plotted rows; otherwise it
   says what was plotted and nothing more;
4. a chart that could not be drawn is said ONCE, and only when a chart was asked for; and it never
   claims to have summarised data the answer does not contain.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── what can be plotted ──────────────────────────────────────────────────────────────────────


def _rows_of(data: Any) -> List[Any]:
    if isinstance(data, dict):
        if "bindings" in data or (
            isinstance(data.get("results"), dict) and "bindings" in data["results"]
        ):
            return []  # graph query bindings are not a series
        rows = data.get("data")
        return rows if isinstance(rows, list) else []
    if isinstance(data, list):
        return data
    return []


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def plottable_rows(data: Any) -> List[Dict[str, Any]]:
    """Rows of ``data`` that carry at least one number; [] when nothing can be plotted.

    A time-series row is ``{timestamp, value, ...}``; any other row is plottable when one of its
    fields is numeric. Rows that are graph bindings (``{"var": {"type": ..., "value": ...}}``) are
    not, and neither are rows whose only numbers are identifiers.
    """
    out: List[Dict[str, Any]] = []
    for row in _rows_of(data):
        if not isinstance(row, dict):
            continue
        if any(isinstance(v, dict) and "type" in v and "value" in v for v in row.values()):
            continue  # a SPARQL binding
        if "value" in row:
            if _number(row["value"]) is not None:
                out.append(row)
            continue
        if any(
            _number(v) is not None
            for k, v in row.items()
            if not re.search(r"(?:^|_)(?:id|uuid|idx|index|floor|level|number|no)$", str(k).lower())
        ):
            out.append(row)
    return out


def has_plottable_series(data: Any) -> bool:
    """True when at least one row of ``data`` can be plotted."""
    return bool(plottable_rows(data))


# ── model-written plotting code ──────────────────────────────────────────────────────────────

_LITERAL_RE = re.compile(r"[\[\{(][^\[\]{}()]{0,400}?[\]\})]")
_NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")


def invented_numbers(code: str, data: Any) -> List[str]:
    """Numbers written into list/dict literals in ``code`` that are not in ``data``.

    Only literals holding three or more numbers are considered (a data series, not a size or a
    colour), and small whole numbers are ignored (indices, tick positions, figure sizes). What is
    left is a value the model made up.
    """
    haystack = str(data)
    found: List[str] = []
    for literal in _LITERAL_RE.findall(code or ""):
        nums = _NUM_RE.findall(literal)
        if len(nums) < 3:
            continue
        for n in nums:
            if re.fullmatch(r"-?\d{1,2}", n):
                continue
            if n not in haystack and n.rstrip("0").rstrip(".") not in haystack:
                found.append(n)
    return found


# ── captions ─────────────────────────────────────────────────────────────────────────────────

NO_STATISTICS = ("", "not specified", "not available")


def has_statistics(summary: Optional[str]) -> bool:
    """True when a series summary was actually computed (not a placeholder)."""
    return str(summary or "").strip().lower() not in NO_STATISTICS


def plain_caption(chart_type: str, rows: List[Dict[str, Any]]) -> str:
    """A caption that says what was plotted and states no figure and no pattern."""
    kind = str(chart_type or "chart").replace("_", " ")
    n = len(rows or [])
    series = len({str(r.get("uuid") or r.get("sensor_uuid") or "") for r in rows or []} - {""})
    of = f" across {series} series" if series > 1 else ""
    return f"A {kind} of the {n} value(s) retrieved{of}."


# ── the note about a chart that was not drawn ────────────────────────────────────────────────

NOTE_NO_DATA = "*No chart was drawn: there was no data to plot for this question.*"
NOTE_FAILED = (
    "*I couldn't render the chart this time; the figures above are unchanged. Please try again, "
    "or ask for one sensor over a stated period as a line chart.*"
)
#: An answer that has ALREADY told the reader why there is no picture gets no note (2026-09-19):
#: "can i get a real time map of available spaces?" was answered with the free rooms, the sentence
#: "there is no live occupancy map", and then "No chart was drawn: there was no data to plot" --
#: which contradicts the list above it and explains nothing the answer had not just explained.
_NOTE_MARKERS = (
    "couldn't render the chart",
    "could not render the chart",
    "no chart was drawn",
    "no live occupancy map",
)
_UNIT_NUMBER_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|°\s?[CF]|ppm|ppb|kwh|kw|mw|lux|db|pa|µg|ug|mg|m²|m2|l/s|hours?|" r"°)",
    re.IGNORECASE,
)
_PLACE_RE = re.compile(r"\b(?:room|rm|floor|level|zone|wing)\s*[\d.]+", re.IGNORECASE)


def answer_states_figures(text: str) -> bool:
    """True when the answer carries figures (a number with a unit, or several bare numbers)."""
    body = _PLACE_RE.sub(" ", text or "")
    if _UNIT_NUMBER_RE.search(body):
        return True
    return len(re.findall(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])", body)) >= 3


def chart_note(
    *,
    wants_chart: bool,
    has_media: bool,
    viz_result: Optional[Dict[str, Any]],
    answer: str,
) -> str:
    """The line to append when a chart was asked for and not drawn; '' otherwise.

    Said once (an answer already carrying the note gets none), only when a chart was asked for and
    no image exists, and never as "I summarised the data above" unless the answer has figures.
    """
    if not wants_chart or has_media:
        return ""
    low = (answer or "").lower()
    if any(marker in low for marker in _NOTE_MARKERS):
        return ""
    skipped = (viz_result or {}).get("skipped") if isinstance(viz_result, dict) else None
    if skipped or not answer_states_figures(answer):
        return f"\n\n---\n{NOTE_NO_DATA}"
    return f"\n\n---\n{NOTE_FAILED}"
