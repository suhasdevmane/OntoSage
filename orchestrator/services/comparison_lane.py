# -*- coding: utf-8 -*-
"""One question, two periods, both fetched and both stated (W1-04).

`comparison_windows` says WHICH two periods a question names. This runs the aggregate lane
once for each of them and puts the two answers, and their difference, in front of the reader.

WHY IT RUNS THE EXISTING LANE TWICE RATHER THAN FETCHING ANYTHING ITSELF
-------------------------------------------------------------------------
`aggregate_lane.try_answer` already resolves the statistic, the grouping, the units, the
threshold citations, the privacy clamps and the store dialect, and it already prefers explicit
bounds over the words in the question -- "the pipeline's own bounds win", which is exactly the
hook a second window needs. Fetching the baseline any other way would be a second answer to
every one of those questions, and the two would drift.

WHAT IT REFUSES TO DO
----------------------
* It never subtracts prose. The difference is computed from the FIGURES the lane now returns
  alongside its text, keyed by what they measure, and a figure present in one period and absent
  from the other is reported as absent rather than treated as zero.
* It never reports a difference between periods of different length -- `comparison_windows`
  guarantees they match, and this re-checks that both answers used the window it asked for.
* It never claims a change is meaningful. It states both figures and their difference; whether
  that difference survives matching on hour-of-day and weekday is
  `evidence/matched_comparison.py`'s question, and this says so rather than implying an answer.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: Below this the two periods are not comparable as a percentage and only the absolute change is
#: given: a 0.01 baseline turns a rounding difference into "up 4000%".
_PCT_FLOOR = 1e-6

#: Figures that describe the MEASUREMENT APPARATUS rather than the building. The lane records
#: them because a claim binder needs every number the text quotes, and a reader comparing two
#: periods does not need them: the first version of this answer reported twelve lines including
#: "sensors requested", "sensors without readings" and "readings excluded as impossible: 0 now
#: against 5994 before — down 100%", which reads as a collapse in data quality and is a
#: diagnostic. The census is stated once, in a sentence, instead.
_CENSUS_WORDS = (
    "sensor",
    "reading",
    "excluded",
    "requested",
    "without",
    "floors",
    "spaces",
    "rooms",
)

#: How the lead figure is chosen when several describe the same quantity. A mean is what
#: "compare the average" asks for; a peak and a low are context.
_RANK = ("mean", "average", "total", "figure", "peak", "highest", "max", "lowest", "min")


def _rank_of(key: str) -> int:
    low = key.lower()
    for i, word in enumerate(_RANK):
        if word in low:
            return i
    return len(_RANK)


def _is_census(key: str) -> bool:
    low = key.lower()
    return any(word in low for word in _CENSUS_WORDS)


def _round(value: float) -> float:
    """Enough precision to be useful, not enough to look like false accuracy.

    "down 16.8319 ppm" claims a ten-thousandth of a part per million from a mean of 371,272
    readings taken by sensors quoted to the nearest integer.
    """
    a = abs(value)
    if a >= 100:
        return round(value)
    if a >= 1:
        return round(value, 1)
    return round(value, 3)


def _num(value: float, unit: str = "") -> str:
    """A rounded figure with thousands grouped and its unit: '66,882 L', not '66882'."""
    text = f"{_round(value):,g}" if abs(value) < 1e15 else f"{value:g}"
    return f"{text} {unit}" if unit else text


def _delta_line(name: str, current: float, baseline: float, unit: str = "") -> str:
    diff = current - baseline
    # readings and sensor counts carry no unit; the quantity's figures carry the answer's
    u = "" if any(w in name.lower() for w in ("reading", "sensor", "series")) else unit
    cur_s, base_s = _num(current, u), _num(baseline, u)
    if cur_s == base_s:
        return f"**{name}**: {cur_s} in both periods."
    arrow = "up" if diff > 0 else "down"
    body = f"**{name}**: {cur_s} now against {base_s} before — {arrow} {_num(abs(diff), u)}"
    if abs(baseline) > _PCT_FLOOR:
        body += f" ({abs(diff) / abs(baseline) * 100:.1f}%)"
    return body + "."


def _named(figures: Dict[str, Any], group: str) -> Dict[str, Any]:
    """Figures keyed by what a reader calls them (BUG-1559).

    A per-floor aggregate keys its figures by the bare floor number, so the comparison printed
    "**4 mean**: 23 in both periods" and "4 sensors 58". A bare leading number is that floor.
    A "readings above the limit" count is dropped when it is zero: no limit was asked for.
    """
    out: Dict[str, Any] = {}
    for key, value in figures.items():
        if "above the limit" in key and not value:
            continue
        name = key
        # A building total carries its per-floor breakdown under the same bare keys (2026-10-11:
        # "**0 mean**", "**1 figure**" in an electricity week-on-week answer).
        if group in ("floor", "building") and re.match(r"^-?\d+\s", key):
            name = f"Floor {key}"
        out[name] = value
    return out


#: Units whose readings are each an interval's amount, so a period's figure is a SUM.
_ADDITIVE_UNITS = {"kwh", "wh", "mwh", "l", "litres", "m³", "m3"}


def _additive_view(figures: Dict[str, Any], unit: str) -> Dict[str, Any]:
    """For interval energy or volume: each place's TOTAL, without the per-reading means.

    The mean of 15-minute kWh readings ("Floor 1 mean: 3.8 kWh") is not a figure anyone asked
    for and reads as a floor's consumption; the period figure beside it is the total.
    """
    if (unit or "").strip().lower() not in _ADDITIVE_UNITS:
        return figures
    out: Dict[str, Any] = {}
    per_reading = (" mean", " peak", " lowest", " highest", " max", " min")
    for key, value in figures.items():
        tail = next((t for t in per_reading if key.endswith(t)), None)
        if tail and f"{key[: -len(tail)]} figure" in figures:
            continue
        out[key[: -len(" figure")] + " total" if key.endswith(" figure") else key] = value
    return out


#: Comparatives a question asks with, by the direction they ask about (BUG-1588).
_HIGHER_WORDS = re.compile(
    r"\b(?:warmer|hotter|noisier|louder|busier|brighter|stuffier|higher|more\s+humid|"
    r"more\s+crowded|more|(?:gone|went|go|goes)\s+up|risen|rose|increased|climbed)\b",
    re.IGNORECASE,
)
_LOWER_WORDS = re.compile(
    r"\b(?:cooler|colder|quieter|darker|lower|less|fewer|drier|emptier|fresher|"
    r"(?:gone|went|go|goes)\s+down|fallen|fell|dropped|decreased)\b",
    re.IGNORECASE,
)


_YES_NO_OPENING = re.compile(
    r"^\s*(?:is|was|were|are|has|have|had|did|does|do|will|would|can|could)\b", re.IGNORECASE
)


def comparative_lead(question: str, key: str, current: float, baseline: float) -> str:
    """'**No — the Floor 2 average was lower …**' for a question that asks 'was it noisier?'.

    "Was floor 2 noisier yesterday than the day before?" was answered with three delta lines and
    no answer to the question asked (BUG-1588). The direction is the question's own word; the
    figure is the period average the lines below already state.
    """
    q = question or ""
    # Only a YES/NO question gets a yes or a no: "which was warmer, Monday or Tuesday?" and "is it
    # warmer this week or last week?" ask for a choice, and "Yes" would answer nothing.
    if not _YES_NO_OPENING.search(q) or re.search(r"\bor\b", q, re.IGNORECASE):
        return ""
    up = bool(_HIGHER_WORDS.search(q))
    down = bool(_LOWER_WORDS.search(q))
    if up == down:  # no comparative, or both: there is no single yes/no to give
        return ""
    cur_s, base_s = f"{_round(current):g}", f"{_round(baseline):g}"
    name = key.replace(" mean", " average")
    if cur_s == base_s:
        return f"**No — the {name} was the same in both periods ({cur_s}).**"
    higher = current > baseline
    yes = higher == up
    return (
        f"**{'Yes' if yes else 'No'} — the {name} was {'higher' if higher else 'lower'} in the "
        f"later period: {cur_s} against {base_s}.**"
    )


def render(
    pair, current: Dict[str, Any], baseline: Dict[str, Any], question: str = ""
) -> Optional[str]:
    """Both periods and their difference, or None when there is nothing comparable to say."""
    from orchestrator.services import comparison_windows as cw

    group = str((current.get("aggregate") or {}).get("group") or "")
    cur_f = _named(
        {k: v for k, v in (current.get("figures") or {}).items() if isinstance(v, (int, float))},
        group,
    )
    base_f = _named(
        {k: v for k, v in (baseline.get("figures") or {}).items() if isinstance(v, (int, float))},
        group,
    )
    _unit = str((current.get("aggregate") or {}).get("unit") or "")
    cur_f, base_f = _additive_view(cur_f, _unit), _additive_view(base_f, _unit)
    shared = [k for k in cur_f if k in base_f]
    if not shared:
        # Two answers whose figures do not line up are two answers, not a comparison. Saying so
        # beats subtracting whatever happens to share a name.
        logger.info("[comparison] no figure appears in both periods — not claiming a comparison")
        return None

    # The quantities, best first; the census set aside for one sentence at the end. Two keys
    # holding the SAME pair of numbers are one figure under two names ("building figure" and
    # "building mean" were both the mean), and printing both reads as corroboration.
    quantities = sorted(
        (k for k in shared if not _is_census(k)),
        key=lambda k: (_rank_of(k), k.startswith("Floor "), k),  # the whole before its floors
    )
    seen_values: set = set()
    deduped = []
    for key in quantities:
        signature = (round(float(cur_f[key]), 6), round(float(base_f[key]), 6))
        if signature in seen_values:
            continue
        seen_values.add(signature)
        deduped.append(key)

    lines = [cw.describe(pair), ""]
    _avg = next((k for k in deduped if "mean" in k), deduped[0] if deduped else "")
    _lead = (
        comparative_lead(question, _avg, float(cur_f[_avg]), float(base_f[_avg])) if _avg else ""
    )
    if _lead:
        lines = [_lead, ""] + lines
    for key in deduped:
        lines.append(
            _delta_line(
                key,
                float(cur_f[key]),
                float(base_f[key]),
                str((current.get("aggregate") or {}).get("unit") or ""),
            )
        )
    if not deduped:
        logger.info("[comparison] only census figures line up — not claiming a comparison")
        return None

    census = [k for k in shared if _is_census(k) and cur_f[k] == base_f[k]]
    if census:
        lines.append("")
        lines.append(
            "_Same basis in both periods: "
            + ", ".join(f"{k} {_round(float(cur_f[k])):g}" for k in sorted(census)[:4])
            + "._"
        )
    moved = [k for k in shared if _is_census(k) and cur_f[k] != base_f[k]]
    if moved:
        # A basis that MOVED is worth one line, because it changes what the comparison rests on
        # -- but it is not a finding about the building and must not be listed beside one.
        lines.append(
            "_The basis differs between the periods ("
            + ", ".join(
                f"{k}: {_round(float(base_f[k])):g} → {_round(float(cur_f[k])):g}"
                for k in sorted(moved)[:4]
            )
            + "), so the two figures rest on slightly different data._"
        )
    only_now = sorted(set(cur_f) - set(base_f))
    only_before = sorted(set(base_f) - set(cur_f))
    for missing, when in ((only_before, "the earlier period"), (only_now, "the current period")):
        if missing:
            lines.append(
                f"_{', '.join(missing)} — recorded only in {when}, so no change is given for "
                f"{'it' if len(missing) == 1 else 'those'}._"
            )
    lines.append("")
    lines.append(
        "_A difference between two periods is not by itself a trend: it can come from the "
        "weather, the timetable or who was in the building. Ask me to check it like for like "
        "and I will match the two periods hour by hour before reporting an effect._"
    )
    return "\n".join(lines)


async def try_compare(
    *,
    question: str,
    try_answer: Callable[..., Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tz_name: Optional[str] = None,
    now=None,
    **lane_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Answer a two-period question, or None to leave the lane exactly as it was.

    ``try_answer`` is injected so this is testable without a store.
    """
    from orchestrator.services import comparison_windows as cw

    pair = cw.resolve_pair(question, start_date, end_date, tz_name, now=now)
    if pair is None:
        return None

    async def _one(window):
        return await try_answer(
            question=pair.lane_question or question,
            start_date=window.start,
            end_date=window.end,
            tz_name=tz_name,
            now=now,
            # BUG-879. The aggregate lane vetoes any question naming a place, because a
            # BUILDING-WIDE summary would then answer a different question. That reasoning does
            # not carry here: both windows are the same place, the place scopes them equally,
            # and the lane groups by the place so its figures are keyed "Room 5.01 mean" rather
            # than "building mean". This is the only caller that can know that, which is why the
            # flag is explicit and never inferred from the question.
            allow_named_place=True,
            **lane_kwargs,
        )

    try:
        current = await _one(pair.current)
        baseline = await _one(pair.baseline)
    except Exception as exc:  # pragma: no cover - a comparison must never cost the lane
        logger.warning(f"[comparison] stood down: {exc}")
        return None
    if not current or not baseline:
        logger.info("[comparison] one of the two periods produced no aggregate — standing down")
        return None

    # THE LANE MUST HAVE USED THE WINDOWS IT WAS GIVEN. A present-tense question can make the
    # aggregate lane choose a "latest reading" window, which ignores the bounds -- and two
    # snapshots of now, subtracted, is a difference of zero dressed as a finding.
    used = [
        ((r.get("aggregate") or {}).get("window") or {}).get("start") for r in (current, baseline)
    ]
    if used[0] == used[1]:
        logger.info("[comparison] both periods resolved to the same window — standing down")
        return None

    text = render(pair, current, baseline, question)
    if not text:
        return None
    logger.info(
        f"[comparison] {pair.current.label} vs {pair.baseline.label} "
        f"(shifted={pair.shifted})"
    )
    out = dict(current)
    out["formatted_response"] = text
    out["comparison"] = {
        "current": {"start": pair.current.start, "end": pair.current.end},
        "baseline": {"start": pair.baseline.start, "end": pair.baseline.end},
        "shifted": pair.shifted,
    }
    return out
