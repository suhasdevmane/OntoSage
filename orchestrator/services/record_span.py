"""How far back the building's readings of a quantity go, and where they stop (2026-10-11).

"How long has CO2 been recorded?" -- a researcher's first question about any dataset -- had no
lane: it was answered with current readings or declined. The answer is a fact about the STORES,
derived on every ask like the silence sweep (``sensor_silence``): the earliest and latest reading
of the quantity's points, and the calendar months in between that hold none. The gaps matter as
much as the start: a store can hold a snapshot from one year, nothing for months, then a live
record, and "since January 2025" alone would claim a continuity it does not have.

Which points carry the quantity comes from the graph (the modality's Brick classes, the same
specification the coverage audit uses); which store holds each comes from ``ref:storedAt``.
A store whose adapter cannot be asked is named, never counted as empty.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: Generic English for "how much history is there". Measured over the 4,060 bank before wiring.
RECORD_SPAN_RE = re.compile(
    r"\bhow\s+long\s+(?:has|have)\b[^.?!]{0,60}?\bbeen\s+"
    r"(?:recorded|measured|monitored|logged|collected|tracked|stored|sensed|recording|measuring"
    r"|monitoring|logging|collecting|tracking)\b"
    r"|\bsince\s+when\b[^.?!]{0,60}?\b(?:recorded|measured|monitored|logged|collected|data|readings?)\b"
    r"|\bhow\s+far\s+back\b[^.?!]{0,60}?\b(?:data|readings?|records?|history|go)\b"
    r"|\b(?:earliest|oldest)\s+(?:reading|record|data|measurement)s?\b"
    r"|\bwhen\s+did\b[^.?!]{0,50}?\b(?:recording|monitoring|measuring|logging|data\s+collection)"
    r"\s+(?:start|begin)\b"
    r"|\bhow\s+much\s+(?:history|historical\s+data)\b",
    re.IGNORECASE,
)

_SHOWN = {"co2": "CO2", "pm25": "PM2.5", "pm10": "PM10", "pm1": "PM1", "voc": "VOC"}

#: Everyday words for a quantity whose modality name is technical (shared with the units answer).
_SYNONYMS = {
    "light": "illuminance",
    "lighting": "illuminance",
    "brightness": "illuminance",
    "sound": "noise",
    "carbon dioxide": "co2",
    "people": "occupancy",
    "headcount": "occupancy",
    "electricity": "energy_submeter",
    "energy": "energy_submeter",
    "power": "electric_power",
    "pm2.5": "pm25",
}

_POINTS_QUERY = """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?c ?l ?u ?store WHERE {{
  VALUES ?c {{ {classes} }}
  ?s a ?c ; ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?u ; ref:storedAt ?store .
  OPTIONAL {{ ?s rdfs:label ?l }}
  FILTER(STRSTARTS(STR(?s), "{ns}"))
}}"""


def is_record_span_question(text: str) -> bool:
    """True when the question asks how far back readings go."""
    return bool(RECORD_SPAN_RE.search(text or ""))


def asked_modalities(question: str, specs: Sequence[Any]) -> List[Any]:
    """The modality specifications a question names, by name or an everyday synonym."""
    q = (question or "").lower()
    by_name = {s.name: s for s in specs}
    asked = [
        s
        for s in specs
        if re.search(r"\b" + re.escape(s.name.replace("_", " ")) + r"\b", q)
        or re.search(r"\b" + re.escape(s.name) + r"\b", q)
    ]
    for word, name in _SYNONYMS.items():
        spec = by_name.get(name)
        if spec and spec not in asked and re.search(r"\b" + re.escape(word) + r"\b", q):
            asked.append(spec)
    return asked


def month_gaps(months: Sequence[str]) -> List[Tuple[str, str]]:
    """Runs of calendar months missing between the first and last month held ('YYYY-MM')."""
    held = sorted(set(months))
    gaps: List[Tuple[str, str]] = []
    for a, b in zip(held, held[1:]):
        ay, am = int(a[:4]), int(a[5:7])
        by, bm = int(b[:4]), int(b[5:7])
        nxt = (ay + (am // 12), am % 12 + 1)
        if nxt != (by, bm):
            prev = (by, bm - 1) if bm > 1 else (by - 1, 12)
            gaps.append((f"{nxt[0]:04d}-{nxt[1]:02d}", f"{prev[0]:04d}-{prev[1]:02d}"))
    return gaps


def _month_name(ym: str) -> str:
    return datetime(int(ym[:4]), int(ym[5:7]), 1).strftime("%B %Y")


def _span_name(a: str, b: str) -> str:
    return _month_name(a) if a == b else f"{_month_name(a)} to {_month_name(b)}"


def format_span(
    what: str,
    first: Optional[datetime],
    last: Optional[datetime],
    months: Sequence[str],
    points: int,
    stores: int,
    not_probed: Sequence[str],
    tz_name: Optional[str] = None,
) -> str:
    """One quantity's history, in the reader's words, with its gaps stated."""
    from orchestrator.services.requested_interval import to_local

    if first is None or last is None:
        line = f"I found no stored **{what}** readings"
        if not_probed:
            line += " in the stores I could ask"
        return line + "."
    f_local, l_local = to_local(first, tz_name), to_local(last, tz_name)
    lead = what[:1].upper() + what[1:]
    out = (
        f"**{lead}** readings go back to **{f_local.day} {f_local:%B %Y}**; the latest is from "
        f"**{l_local.day} {l_local:%B %Y, %H:%M}**."
    )
    gaps = month_gaps(months)
    if gaps:
        named = "; ".join(_span_name(a, b) for a, b in gaps)
        out += f"\n\nThe record is **not continuous**: there are no {what} readings for {named}."
    else:
        out += "\n\nEvery calendar month in between holds readings."
    out += (
        f"\n\n_From {points} {what} point{'s' if points != 1 else ''} across {stores} "
        f"store{'s' if stores != 1 else ''}, read from the stores now._"
    )
    if not_probed:
        out += f"\n_Not checked: {'; '.join(not_probed)}._"
    return out


async def _points_by_store(spec: Any, namespace: str, sparql_exec: Any) -> Dict[str, List[str]]:
    classes = " ".join(f"brick:{c}" for c in spec.brick_classes if re.fullmatch(r"\w+", c))
    if not classes:
        return {}
    res = await sparql_exec(_POINTS_QUERY.format(classes=classes, ns=namespace))
    out: Dict[str, List[str]] = defaultdict(list)
    for b in (res or {}).get("results", {}).get("bindings", []):
        cls = b.get("c", {}).get("value", "").rsplit("#", 1)[-1]
        label = b.get("l", {}).get("value", "")
        uid, store = b.get("u", {}).get("value"), b.get("store", {}).get("value")
        if uid and store and spec.matches(cls, label):
            out[store].append(uid)
    return dict(out)


async def record_span_answer(
    question: str,
    building_id: Optional[str],
    namespace: str,
    sparql_exec: Any,
    tz_name: Optional[str] = None,
    timeout_s: float = 30.0,
) -> Optional[str]:
    """The answer to a 'how far back' question, or None when it is not one or names no quantity."""
    if not is_record_span_question(question):
        return None
    from orchestrator.services.adapters.registry import adapter_registry
    from orchestrator.services.deliberation.coverage_audit import load_modalities

    specs = asked_modalities(question, load_modalities(building_id))
    if not specs:
        return None
    parts: List[str] = []
    for spec in specs[:3]:
        what = _SHOWN.get(spec.name, spec.name.replace("_", " "))
        by_store = await _points_by_store(spec, namespace, sparql_exec)
        firsts, lasts, months, not_probed = [], [], set(), []
        for store, uuids in sorted(by_store.items()):
            adapter = adapter_registry.get(store)
            probe = getattr(adapter, "months_with_readings", None) if adapter else None
            short = store.rsplit("#", 1)[-1]
            if probe is None:
                not_probed.append(f"{short} ({len(uuids)} points: this store cannot be asked)")
                continue
            try:
                got = await asyncio.wait_for(probe(sorted(set(uuids))), timeout_s)
            except Exception as exc:
                logger.warning(f"[record_span] {short} not read: {type(exc).__name__}: {exc}")
                not_probed.append(f"{short} ({len(uuids)} points: the read did not complete)")
                continue
            if not got:
                not_probed.append(f"{short} ({len(uuids)} points: the read failed)")
                continue
            if got.get("first"):
                firsts.append(got["first"])
            if got.get("last"):
                lasts.append(got["last"])
            months.update(got.get("months") or [])
        points = len({u for us in by_store.values() for u in us})
        parts.append(
            format_span(
                what,
                min(firsts) if firsts else None,
                max(lasts) if lasts else None,
                sorted(months),
                points,
                len(by_store),
                not_probed,
                tz_name,
            )
        )
        logger.info(
            f"[record_span] {spec.name}: {points} points in {len(by_store)} stores, "
            f"{len(months)} months held, {len(not_probed)} not probed"
        )
    return "\n\n---\n\n".join(parts)
