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


def _delta_line(name: str, current: float, baseline: float) -> str:
    diff = current - baseline
    cur_s, base_s = f"{_round(current):g}", f"{_round(baseline):g}"
    if cur_s == base_s:
        return f"**{name}**: {cur_s} in both periods."
    arrow = "up" if diff > 0 else "down"
    body = f"**{name}**: {cur_s} now against {base_s} before — {arrow} {_round(abs(diff)):g}"
    if abs(baseline) > _PCT_FLOOR:
        body += f" ({abs(diff) / abs(baseline) * 100:.1f}%)"
    return body + "."


def render(pair, current: Dict[str, Any], baseline: Dict[str, Any]) -> Optional[str]:
    """Both periods and their difference, or None when there is nothing comparable to say."""
    from orchestrator.services import comparison_windows as cw

    cur_f = {k: v for k, v in (current.get("figures") or {}).items() if isinstance(v, (int, float))}
    base_f = {
        k: v for k, v in (baseline.get("figures") or {}).items() if isinstance(v, (int, float))
    }
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
        (k for k in shared if not _is_census(k)), key=lambda k: (_rank_of(k), k)
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
    for key in deduped:
        lines.append(_delta_line(key, float(cur_f[key]), float(base_f[key])))
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
            question=question,
            start_date=window.start,
            end_date=window.end,
            tz_name=tz_name,
            now=now,
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

    text = render(pair, current, baseline)
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
