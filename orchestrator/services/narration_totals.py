# -*- coding: utf-8 -*-
"""A total is not a daily average, and a computed total says how it was computed (2D-09, wave 2).

Two slips the wave-1 build still made, both on correct figures:

* **A total called a daily average.** *"Compare this week's electricity use with last week"* said
  "The 2026-W37 total of 12,077 kWh ... represents the highest daily average, while the 2026-W38
  total of 8,863 kWh ... represents the lowest" -- the week totals, one of them a part-week, were
  labelled with the per-day figures the same answer gave one line earlier.
* **A total with no method.** *"How much water did floor 3 use yesterday?"* printed
  "used 2,058,048 L" beside an average flow of 23.82 L/s and nothing else. 2,058,048 is exactly
  23.82 x 86,400: the average rate multiplied by a full day, whatever part of the day the readings
  actually covered. A reader who is told the total and not the method cannot tell an integral over
  the readings from an extrapolation.

Same contract as ``narration_validators``: pure string functions, no I/O, never raise, leave every
other byte of the answer alone, and change nothing when unsure. The first rewrites the sentence
from the totals it names (the daily averages stay where the answer already states them); the
second states the method whenever the answer gives the average rate the total was built from.
"""

from __future__ import annotations

import re
from typing import List, Optional

from orchestrator.services.narration_validators import (
    Change,
    NarrationResult,
    _classify,
    _edit_sentences,
    _narrated,
    _result,
    _strip_marks,
)

__all__ = ["fix_total_called_daily_average", "state_method_of_computed_total", "validate_totals"]

_NUM = r"\d[\d,]*(?:\.\d+)?"
_TOTAL_UNIT = r"(?:kWh|MWh|GWh|litres|liters|L|m³|m3)(?![A-Za-z/])"

# ── a total called a daily average ───────────────────────────────────────────

_DAILY_AVERAGE_RE = re.compile(
    r"\b(?:daily\s+average|average\s+daily|per[\s-]day\s+average|average\s+per\s+day|"
    r"average\s+day)\b",
    re.I,
)
#: "the 2026-W37 total of 12,077 kWh (3462 readings, 1.93-4.94 kWh)": a named total and its bracket.
_TOTAL_CLAUSE_RE = re.compile(
    r"(?P<label>[^,.;()]{1,50}?\btotal)\s+(?:of|was|is)\s+"
    r"(?P<val>" + _NUM + r"\s*" + _TOTAL_UNIT + r")(?P<paren>\s*\([^()]{0,90}\))?",
    re.I,
)
#: the words that tie a total to a "daily average": "... total of X represents the highest daily
#: average", "... total is the daily average". Decimals hold full stops, so only ";" ends the scan.
_TIED_TO_AVERAGE_RE = re.compile(
    r"\btotals?\b[^;]{0,160}?\b(?:represent\w*|is|are|gives?|as|being|equals?|show\w*|reflects?)\b"
    r"[^;]{0,30}?\b(?:daily|per[\s-]day|average)\b",
    re.I,
)
_LEADING_CONJUNCTION_RE = re.compile(r"^(?:while|whereas|and|but|whilst)\s+", re.I)
_ARTICLE_ONLY_RE = re.compile(r"^(?:a|an|the|this|that|its|their|each)?\s*(?:total)?$", re.I)


def _rewrite_total_sentence(sentence: str) -> Optional[str]:
    """None to keep; the sentence rebuilt from the totals it names, or "drop"."""
    core = _strip_marks(sentence)
    if not _DAILY_AVERAGE_RE.search(core) or not _TIED_TO_AVERAGE_RE.search(core):
        return None
    clauses = list(_TOTAL_CLAUSE_RE.finditer(core))
    if not clauses:
        return None  # no total in it: a genuine daily average is fine
    parts: List[str] = []
    for i, c in enumerate(clauses):
        label = _LEADING_CONJUNCTION_RE.sub("", c.group("label").strip())
        if _ARTICLE_ONLY_RE.match(label):
            return "drop"  # "a total ..." names nothing to rebuild the sentence around
        if i == 0:
            label = label[:1].upper() + label[1:]
        parts.append(f"{label} was {c.group('val')}{c.group('paren') or ''}")
    tail = re.search(r"([.!?][\"”’')\]*_]*)\s*$", sentence)
    return ", and ".join(parts) + (tail.group(1) if tail else ".")


def fix_total_called_daily_average(text: str) -> str:
    """Rewrite a sentence that calls a total a daily average from the totals it names."""
    return _fix_daily(text).text


def _fix_daily(text: str) -> NarrationResult:
    if not text or not _DAILY_AVERAGE_RE.search(text):
        return NarrationResult(text or "")
    changes: List[Change] = []
    lines = _classify(text)
    _edit_sentences(lines, _rewrite_total_sentence, "fix_total_called_daily_average", changes)
    return _result(text, lines, changes)


# ── a computed total states its method ───────────────────────────────────────

#: Any phrase that already says how a total was obtained. The meter-boundary line ("summed across
#: 6 meters") and the energy-total block are methods too, so an answer that carries one is left alone.
_METHOD_RE = re.compile(
    r"\b(?:computed|calculated|derived|integrat\w+|summed|summing|sum\s+of|sum|multipl\w+|"
    r"extrapolat\w+|obtained|per[\s-]interval|based\s+on\s+the\s+(?:sum|average|integral))\b|×",
    re.I,
)
_TOTAL_CLAIM_RE = re.compile(
    r"\b(?:used|consumed|drew|flowed|totall?ed|amounted\s+to|came\s+to|total(?:\s+\w+){0,3}?\s+of|"
    r"total(?:\s+\w+){0,3}?\s+(?:was|is))\s+(?:about\s+|approximately\s+|roughly\s+)?"
    r"(?P<n>" + _NUM + r")\s*(?P<u>" + _TOTAL_UNIT + r")",
    re.I,
)
_RATE_RE = re.compile(
    r"\b(?:average|mean)\s+(?P<what>flow(?:\s+rate)?|rate|power|demand|consumption\s+rate)"
    r"(?:\s+\w+){0,2}?\s+(?:was|is|of|at|=|:)?\s*\**(?P<r>" + _NUM + r")\s*"
    r"(?P<ru>L/s|L/min|L/h|m³/s|m³/min|m³/h|kW)(?![A-Za-z])",
    re.I,
)
#: hours per rate time-unit
_PER_HOUR = (("/s", 3600.0), ("/min", 60.0), ("/h", 1.0))
_FOOTER_SEPARATOR = re.compile(r"\n[ \t]*---[ \t]*(?:\n|$)")


def _num(raw: str) -> float:
    return float(raw.replace(",", ""))


def _quantity(value: float, unit: str) -> Optional[tuple]:
    """``(family, amount)``: litres for a volume, kWh for an energy total."""
    u = unit.lower().replace("m3", "m³")
    if u in ("l", "litres", "liters"):
        return "volume", value
    if u == "m³":
        return "volume", value * 1000.0
    if u == "kwh":
        return "energy", value
    if u == "mwh":
        return "energy", value * 1000.0
    if u == "gwh":
        return "energy", value * 1_000_000.0
    return None


def _per_hour(value: float, unit: str) -> Optional[tuple]:
    """``(family, amount per hour)`` for a rate: litres/hour for a flow, kWh/hour for a power."""
    if unit == "kW":
        return "energy", value
    for suffix, factor in _PER_HOUR:
        if unit.endswith(suffix):
            return "volume", value * factor * (1000.0 if unit.startswith("m³") else 1.0)
    return None


def _effective_hours(total: float, per_hour: float) -> Optional[float]:
    """The hours of the average rate that add up to ``total`` (None when the pairing is absurd)."""
    if per_hour <= 0:
        return None
    hours = total / per_hour
    return hours if 0.05 <= hours <= 24 * 31 else None


def _span(hours: float) -> str:
    whole = round(hours)
    if whole >= 1 and abs(hours - whole) / whole <= 0.005:
        return f"{whole} h" if whole < 48 else f"{whole} h ({whole / 24:g} days)"
    return f"{hours:.1f} h"


def state_method_of_computed_total(text: str) -> str:
    """Add the method to a volume/energy total that is stated beside its average rate."""
    return _method(text).text


def _method(text: str) -> NarrationResult:
    if not text or _METHOD_RE.search(text):
        return NarrationResult(text or "")
    footer = _FOOTER_SEPARATOR.search(text)
    body = text[: footer.start()] if footer else text
    claim = _TOTAL_CLAIM_RE.search(body)
    rate = _RATE_RE.search(body)
    if not claim or not rate:
        # a total with no stated rate beside it: there is nothing to show the method with, and
        # withdrawing a metered or summed total that is right would be worse than the silence
        return NarrationResult(text)
    total = _quantity(_num(claim.group("n")), claim.group("u"))
    per_hour = _per_hour(_num(rate.group("r")), rate.group("ru"))
    if total is None or per_hour is None or total[0] != per_hour[0]:
        return NarrationResult(text)
    hours = _effective_hours(total[1], per_hour[1])
    if hours is None:
        return NarrationResult(text)
    what = "flow rate" if total[0] == "volume" else "power"
    line = (
        f"**Method:** computed as the average {what} ({rate.group('r')} {rate.group('ru')}) "
        f"× {_span(hours)}, so it is only as good as that average."
    )
    rest = text[footer.start() :] if footer else ("\n" if text.endswith("\n") else "")
    new = body.rstrip() + "\n\n" + line + rest
    return NarrationResult(
        new, [Change("state_method_of_computed_total", "add_method", claim.group(0), line)]
    )


# ── the pair, for validate_narration ─────────────────────────────────────────


def validate_totals(text: str, intent: Optional[str] = None) -> NarrationResult:
    """Both checks over a narrated answer; content lanes are left alone. Never raises."""
    if not text or not _narrated(intent):
        return NarrationResult(text or "")
    current = text
    changes: List[Change] = []
    for step in (_fix_daily, _method):
        try:
            res = step(current)
        except Exception:  # pragma: no cover - a wording pass must never cost the answer
            continue
        current = res.text
        changes.extend(res.changes)
    return NarrationResult(current, changes)
