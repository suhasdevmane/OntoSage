# -*- coding: utf-8 -*-
"""When a chart may be drawn, and what its caption must say (2D-16 wave 2, defect class C19).

The wave-1 held-out read still found an unrelated chart: *"I may not see visual alerts. Which
verified audible or staff-assisted notification provision is available?"* returned "The line chart
tracks 1,000 noise sensor readings on Floor 5 ...". Two faults stacked:

* the trigger read the ADJECTIVE "visual" in "visual alerts" as a request for a picture (the
  keyword list also carries "image", "picture", "display", "map", "panel", "figure" ...), and
* "audible" resolved to noise sensors, so a series was fetched and plotted for a question that named
  no quantity to plot.

The rule, in three parts, all pure and offline:

1. **The question asks for a chart.** A chart word (plot, chart, graph, histogram, heat map,
   sparkline, scatter, visualise ...), a trend phrase ("show the trend of energy use", "over
   time"), or a picture word (image, picture, display, map, snapshot, ...) that is asking for a
   picture OF a measured quantity. A bare picture word, and the adjective "visual" in "visual
   alerts", "visual impairment" or "visual display", never are.
2. **The fetched series is the quantity asked for.** When the question names a quantity, at least
   one plotted series must be a sensor of that quantity; a chart of something else is not drawn.
3. **The caption says which quantity, where and when**, from the plotted rows, so a reader can see
   at a glance what the picture is a picture of.

When any part fails, no chart is drawn and the turn falls back to the lane that owns the subject,
instead of a chart nobody asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

# ── 1. does the question ask for a chart ─────────────────────────────────────────────────────

#: Words that ARE a request for a chart, wherever they stand.
_EXPLICIT = re.compile(
    r"(?<![a-z0-9])(?:plot(?:s|ted|ting)?|chart(?:s|ed|ing)?|graph(?:s|ed|ing)?|histograms?|"
    r"heat[ -]?maps?|sparklines?|scatter(?:[ -]?(?:plot|chart|graph))?|box[ -]?plots?|"
    r"violin plots?|time[- ]series (?:chart|plot|graph)|trend[ -]?lines?|"
    r"(?:line|bar|pie|area|bubble|radar|gantt|waterfall|candlestick) (?:chart|graph|plot)s?|"
    r"visuali[sz](?:e|es|ed|ing|ation|ations)|graphically|visually|as a figure|"
    r"in a (?:chart|graph|plot))(?![a-z0-9])",
    re.IGNORECASE,
)

#: A trend, asked for as one.
_TREND = re.compile(
    r"(?<![a-z0-9])(?:show|see|view|draw|give me|display)\b[^.?!]{0,30}\b"
    r"(?:trends?|patterns?|over time|history)\b"
    r"|\btrends? (?:of|in|for|over)\b|\bover time\b|\bhow (?:has|have)\b[^.?!]{0,60}\bchanged\b",
    re.IGNORECASE,
)

#: A picture word. Ambiguous on its own: "display screens", "the map on level 2", "a figure of 12%".
_PICTURE = re.compile(
    r"(?<![a-z0-9])(?:images?|pictures?|illustrations?|screenshots?|snapshots?|thumbnails?|"
    r"displays?|rendered?|draw|diagrams?|maps?|dashboards?|panels?|overlay|png|svg|jpe?g)"
    r"(?![a-z0-9])",
    re.IGNORECASE,
)

#: "visual" as a NOUN asking for a picture ("give me a visual of CO2"), never as an adjective.
_VISUAL_NOUN = re.compile(
    r"\b(?:a|the|some|any)\s+visuals?\s+(?:of|for|showing|on)\b|\bvisual (?:summary|representation)\b",
    re.IGNORECASE,
)

_VERB = re.compile(
    r"\b(?:show|give|draw|make|create|generate|produce|build|see|view|get|send|render|display|"
    r"want|need|can i have|could i have)\b",
    re.IGNORECASE,
)

#: Quantities a picture can be OF, as the question words them. Generic English measurand words plus
#: the classes' own vocabulary (plausibility.measurand_of is consulted as well).
_QUANTITY = re.compile(
    r"\b(?:temperature|humidity|co2|carbon dioxide|air quality|noise|sound|light|lux|illuminance|"
    r"pressure|occupancy|energy|electricity|power|consumption|usage|flow|voltage|current|"
    r"particulate|pm2\.?5|pm10|vocs?|wind|rain|solar|readings?|levels?|sensors?)\b",
    re.IGNORECASE,
)


def names_a_quantity(question: str) -> bool:
    """True when the question names something a chart could show."""
    q = question or ""
    if _QUANTITY.search(q):
        return True
    try:
        from orchestrator.services.plausibility import measurand_of

        return measurand_of(q) is not None
    except Exception:  # pragma: no cover - the regex above is the fallback
        return False


def asks_for_chart(question: str) -> bool:
    """True only when the question asks for a chart, plot, graph or trend of something.

    A picture word counts only with a request verb AND a measured quantity ("show me an image of
    the CO2"), so "display screens", "the map on level 2" and "I may not see visual alerts" ask for
    nothing.
    """
    q = question or ""
    if _EXPLICIT.search(q) or _VISUAL_NOUN.search(q):
        return True
    if _TREND.search(q) and names_a_quantity(q):
        return True
    if _TREND.search(q) and re.search(r"\b(?:draw|plot|chart|graph)\b", q, re.IGNORECASE):
        return True
    return bool(_PICTURE.search(q) and _VERB.search(q) and names_a_quantity(q))


# ── 2. does the fetched series match the quantity ────────────────────────────────────────────

#: Words a sensor label may use for the same quantity. Small and generic; a building's own names
#: arrive through the metadata (label, kind, class), not from here.
_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "temperature": ("temperature", "temp"),
    "humidity": ("humidity", "humid"),
    "co2": ("co2", "carbon dioxide"),
    "air quality": ("air quality", "co2", "pm", "voc", "particulate", "aqi", "iaq"),
    "sound": ("sound", "noise", "acoustic", "decibel"),
    "illuminance": ("illuminance", "lux", "light"),
    "occupancy": ("occupancy", "people", "presence", "motion"),
    "pressure": ("pressure",),
    "flow": ("flow",),
    "voltage": ("voltage",),
    "current": ("current", "amp"),
    "wind": ("wind",),
    "energy": ("energy", "electric", "power", "kwh", "meter"),
    "power": ("power", "electric", "energy", "kw"),
}

_WORD_TO_MEASURAND = {
    "noise": "sound",
    "sound": "sound",
    "temperature": "temperature",
    "temp": "temperature",
    "humidity": "humidity",
    "co2": "co2",
    "light": "illuminance",
    "lux": "illuminance",
    "illuminance": "illuminance",
    "occupancy": "occupancy",
    "energy": "energy",
    "electricity": "energy",
    "consumption": "energy",
    "usage": "energy",
    "power": "power",
    "pressure": "pressure",
    "flow": "flow",
    "voltage": "voltage",
    "wind": "wind",
    "particulate": "air quality",
    "pm2.5": "air quality",
    "pm25": "air quality",
    "pm10": "air quality",
    "voc": "air quality",
    "vocs": "air quality",
}


def quantities_named(question: str) -> List[str]:
    """The measurands the question names, in the order they appear ([] when none)."""
    q = (question or "").lower()
    found: List[str] = []
    for m in re.finditer(r"[a-z0-9.]+", q):
        kind = _WORD_TO_MEASURAND.get(m.group(0))
        if kind and kind not in found:
            found.append(kind)
    if "carbon dioxide" in q and "co2" not in found:
        found.append("co2")
    if "air quality" in q and "air quality" not in found:
        found.append("air quality")
    return found


def _meta_text(meta: Dict[str, Any]) -> str:
    return " ".join(
        str(meta.get(k, "")) for k in ("label", "kind", "sensor_uri", "unit", "type")
    ).lower()


def _uuid_of(row: Dict[str, Any]) -> str:
    return str(row.get("uuid") or row.get("sensor_uuid") or row.get("sensor") or "")


def series_matches(
    quantities: Sequence[str],
    rows: Iterable[Dict[str, Any]],
    metadata: Optional[Dict[str, Dict[str, Any]]],
) -> bool:
    """True when at least one plotted series is a sensor of a named quantity.

    No named quantity means nothing to contradict, so it matches. A named quantity with no
    metadata at all cannot be checked and is not drawn: an unverifiable chart is what this rule
    exists to stop.
    """
    if not quantities:
        return True
    metadata = metadata or {}
    plotted = {_uuid_of(r) for r in rows if isinstance(r, dict)} - {""}
    if not plotted or not metadata:
        return False
    for uuid in plotted:
        text = _meta_text(metadata.get(uuid) or {})
        for kind in quantities:
            if any(word in text for word in _SYNONYMS.get(kind, (kind,))):
                return True
    return False


# ── 3. the caption's facts ───────────────────────────────────────────────────────────────────


@dataclass
class Decision:
    """Whether to draw, and why not when not."""

    draw: bool
    reason: str = ""
    quantities: Tuple[str, ...] = ()


def decide(
    question: str,
    rows: Sequence[Dict[str, Any]],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    follow_up: bool = False,
) -> Decision:
    """Draw only a chart that was asked for, of the quantity asked for.

    ``follow_up`` marks "plot that" over data an earlier turn fetched; the earlier question named
    the quantity, so this one is not held to naming it again.
    """
    if not asks_for_chart(question):
        return Decision(False, "not_a_chart_request")
    quantities = tuple(quantities_named(question))
    if follow_up and not quantities:
        return Decision(True, "follow_up", ())
    if quantities and not series_matches(quantities, rows, metadata):
        return Decision(False, "series_is_not_the_quantity_asked_for", quantities)
    return Decision(True, "ok", quantities)


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _fmt(ts: datetime) -> str:
    return f"{ts.day} {_MONTHS[ts.month - 1]} {ts:%H:%M}"


def caption_header(
    rows: Sequence[Dict[str, Any]], metadata: Optional[Dict[str, Dict[str, Any]]] = None
) -> str:
    """'CO2 (ppm) — Room 5.01 CO2 sensor — 18 Sep 22:50 to 19 Sep 03:50 (60 readings).' or ''.

    Built from the plotted rows and the sensor metadata only: the quantity is the metadata's own
    label and unit, the place is the sensor's label (and floor when it declares one), the period is
    the first and last timestamp actually plotted.
    """
    metadata = metadata or {}
    plotted = [r for r in rows or [] if isinstance(r, dict)]
    if not plotted:
        return ""
    by_uuid: Dict[str, int] = {}
    stamps: List[datetime] = []
    for r in plotted:
        by_uuid[_uuid_of(r)] = by_uuid.get(_uuid_of(r), 0) + 1
        ts = _parse_ts(r.get("timestamp") or r.get("datetime") or r.get("time"))
        if ts:
            stamps.append(ts)
    labels: List[str] = []
    units: List[str] = []
    floors: List[str] = []
    for uuid in by_uuid:
        meta = metadata.get(uuid) or {}
        label = str(meta.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        unit = str(meta.get("unit") or "").strip()
        if unit and unit not in units:
            units.append(unit)
        floor = str(meta.get("floor") or "").strip()
        if floor and floor not in floors:
            floors.append(floor)
    if not labels:
        what = "the plotted series"
    elif len(labels) <= 2:
        what = " and ".join(labels)
    else:
        where = f" on floor {floors[0]}" if len(floors) == 1 else ""
        what = f"{len(labels)} sensors{where}"
    unit_part = f" ({units[0]})" if len(units) == 1 else ""
    period = ""
    if stamps:
        period = f" — {_fmt(min(stamps))} to {_fmt(max(stamps))}"
    return f"Chart of {what}{unit_part}{period}, {len(plotted)} readings."
