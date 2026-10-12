"""Two named places forecast separately and compared with their bands (CAVEAT-1558).

"Will floor 3 be warmer than floor 4 tomorrow?" was first answered "**Floor 3 will be warmer
than Floor 4 tomorrow**" from two PAST means 0.1 C apart (BUG-1545); once the narration was told
no forecast had been made, the relevance gate rightly replaced that with a decline. A question
about the future comparison of two places is answered by forecasting each place and comparing
the forecasts -- and a difference is stated only when the 80% bands do not overlap, because
two forecasts whose uncertainty overlaps do not say which will be higher.

Building-agnostic: the places are read from the question (two floor numbers or two dotted room
ids) and each bound sensor is placed by the graph's own location query, never by its label.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_FLOOR_RE = re.compile(r"\bfloor\s*(\d{1,2})\b", re.IGNORECASE)
_ROOM_RE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{2,3})(?![\d])")
_HORIZON_RE = re.compile(
    r"\b(?:tomorrow|later\s+today|tonight|this\s+evening|next\s+(?:hour|day|week|\d+\s+hours?)|"
    r"in\s+\d+\s+(?:hours?|days?))\b",
    re.IGNORECASE,
)
_HIGHER = (
    "warmer",
    "hotter",
    "higher",
    "more",
    "noisier",
    "louder",
    "brighter",
    "busier",
    "more humid",
)
_LOWER = ("cooler", "colder", "lower", "less", "quieter", "darker", "fresher")


def named_places(question: str) -> List[Tuple[str, str]]:
    """The two places a question compares: ("floor", "3") / ("room", "5.01"), or []."""
    floors = list(dict.fromkeys(_FLOOR_RE.findall(question or "")))
    if len(floors) >= 2:
        return [("floor", f) for f in floors[:2]]
    rooms = list(dict.fromkeys(_ROOM_RE.findall(question or "")))
    if len(rooms) >= 2:
        return [("room", r) for r in rooms[:2]]
    return []


def horizon_phrase(question: str) -> str:
    m = _HORIZON_RE.search(question or "")
    return m.group(0) if m else "tomorrow"


def group_by_place(
    places: Sequence[Tuple[str, str]], located: Dict[str, Any]
) -> Dict[str, List[str]]:
    """{"Floor 3": [uuid, ...], ...} from the graph's placement of each sensor."""
    out: Dict[str, List[str]] = {}
    for kind, key in places:
        if kind == "floor":
            ids = [
                u for u, p in located.items() if str(getattr(p, "floor", "") or "").strip() == key
            ]
            out[f"Floor {key}"] = ids
        else:
            pat = re.compile(rf"(?<![\d.]){re.escape(key)}(?![\d])")
            ids = [u for u, p in located.items() if pat.search(str(getattr(p, "room", "") or ""))]
            out[f"Room {key}"] = ids
    return out


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def render(
    question: str,
    quantity: str,
    unit: str,
    results: Dict[str, Dict[str, Any]],
    horizon: str,
) -> Optional[str]:
    """The comparison of two forecasts, or None when either did not forecast."""
    rows = []
    for place, r in results.items():
        mid = _mean(r.get("forecast") or [])
        lo = _mean(r.get("lower_80") or [])
        hi = _mean(r.get("upper_80") or [])
        if mid is None or lo is None or hi is None:
            return None
        rows.append((place, mid, lo, hi, r))
    if len(rows) != 2:
        return None
    (pa, ma, la, ha, ra), (pb, mb, lb, hb, rb) = rows
    u = f" {unit}" if unit else ""
    ql = (question or "").lower()
    up_word = next((w for w in _HIGHER if w in ql), "")
    down_word = next((w for w in _LOWER if w in ql), "")
    # The question's own direction: "cooler" is answered with the cooler place first.
    asks_lower = bool(down_word) and not up_word
    word = down_word if asks_lower else (up_word or "higher")
    overlap = not (la > hb or lb > ha)
    name = quantity or "the quantity asked about"
    if overlap:
        lead = (
            f"**The forecasts for {horizon} overlap, so neither place can be said to be {word}.** "
            f"{pa} is forecast to average {ma:.1f}{u} and {pb} {mb:.1f}{u}; their 80% bands "
            f"({la:.1f}–{ha:.1f} and {lb:.1f}–{hb:.1f}{u}) overlap."
        )
    else:
        higher, lower_, gap = (pa, pb, ma - mb) if ma > mb else (pb, pa, mb - ma)
        first, second = (lower_, higher) if asks_lower else (higher, lower_)
        lead = (
            f"**{first} is forecast to be {word} than {second} {horizon}, by about "
            f"{abs(gap):.1f}{u}** (average {name}: {pa} {ma:.1f}{u}, band {la:.1f}–{ha:.1f}; "
            f"{pb} {mb:.1f}{u}, band {lb:.1f}–{hb:.1f})."
        )
    detail = []
    for place, mid, lo, hi, r in rows:
        mae = (r.get("metrics") or {}).get("mae")
        mae_s = f", hold-out MAE {float(mae):.2f}{u}" if isinstance(mae, (int, float)) else ""
        detail.append(
            f"- **{place}**: {r.get('model', 'a time-series model')} over "
            f"{r.get('n_history', '?')} hourly points{mae_s}"
        )
    return "\n".join(
        [
            lead,
            "",
            f"Each place was forecast separately ({horizon}, the average of its {name} sensors):",
            *detail,
            "",
            "_A forecast is not a measurement: the bands are the models' own uncertainty, and a "
            "difference smaller than the bands is not a finding._",
        ]
    )


async def compare_forecasts(
    state: Any,
    question: str,
    sensor_metadata: Dict[str, Dict[str, Any]],
    sql_data: Optional[Dict[str, Any]],
    sparql_exec: Optional[Callable[[str], Awaitable[Dict[str, Any]]]],
    predict: Callable[..., Awaitable[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Forecast each named place and compare, or None to leave the turn as it was."""
    places = named_places(question)
    if len(places) != 2 or not sensor_metadata or sparql_exec is None:
        return None
    from orchestrator.services.aggregate_lane import (
        build_location_query,
        parse_locations,
        question_measurands,
    )

    try:
        located = parse_locations(await sparql_exec(build_location_query(list(sensor_metadata))))
    except Exception as exc:  # placement is the grouping; without it, stand down
        logger.info(f"[forecast_comparison] placement unavailable: {exc}")
        return None
    groups = group_by_place(places, located)
    if any(not ids for ids in groups.values()):
        logger.info(
            f"[forecast_comparison] a place has no bound sensors: { {k: len(v) for k, v in groups.items()} }"
        )
        return None
    quantity = next(iter(sorted(question_measurands(question))), "")
    horizon = horizon_phrase(question)
    rows = ((sql_data or {}).get("results") or {}).get("data") or []
    results: Dict[str, Dict[str, Any]] = {}
    unit = ""
    for place, ids in groups.items():
        idset = set(ids)
        sub_rows = [r for r in rows if isinstance(r, dict) and str(r.get("uuid") or "") in idset]
        sub_sql = {"success": True, "results": {"data": sub_rows}}
        sub_meta = {u: sensor_metadata[u] for u in ids if u in sensor_metadata}
        where = f"on {place.lower()}" if place.startswith("Floor") else f"in {place.lower()}"
        q = f"Forecast the average {quantity or 'reading'} {where} {horizon}"
        r = await predict(state, q, sub_sql, sub_meta)
        if not (r or {}).get("success"):
            logger.info(f"[forecast_comparison] {place} did not forecast: {(r or {}).get('error')}")
            return None
        results[place] = r
        unit = unit or str(r.get("unit") or "")
    text = render(question, quantity, unit, results, horizon)
    if not text:
        return None
    logger.info(f"[forecast_comparison] {' vs '.join(results)} over {horizon}")
    return {
        "success": True,
        "formatted_response": text,
        "source": "forecast_comparison",
        "places": {p: {"model": r.get("model")} for p, r in results.items()},
    }
