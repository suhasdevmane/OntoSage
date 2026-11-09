# -*- coding: utf-8 -*-
"""What is reported faulty in the building right now, from every record that says so (BUG-1682).

"Are any sensors or building services reporting faults right now?" was answered *"No faults
reported. All sensors show no fault status"* from a handful of air-quality readings, while the
building held uncleared alarms, open equipment outages and sensors that had stopped reporting.
No lane owned the building-wide question: `asset_state` reads the status of an asset the question
NAMES ("are the lifts working?"), the anomaly lane reads readings, and the register lane reads one
register at a time. A reading lane can only ever answer "none" here, because a reading is not where
a fault is recorded.

Four sources, each read for what is wrong NOW, each reported separately and never merged:

* **alarms** -- `ontosage:AlarmEvent` records that are neither closed by status nor ended;
* **outages** -- `asset_outage` episodes in the events store that are in progress now;
* **asset status** -- `ontosage:AssetStatus` records whose state is out of service or degraded;
* **sensors** -- instrument faults (a sensor stuck on one value, or one that stopped reporting)
  the anomaly detector recorded in the last 24 hours.

A source that cannot be read is said to be NOT CHECKED, never counted as zero: "no faults" is only
said when every source was read and every one came back empty. All vocabulary here is OntoSage's
own (class and property names, event types); nothing names this building.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

O = "http://ontosage.org/capabilities#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

#: A record status that says the alarm is over. Anything else (detected, open, active,
#: acknowledged...) is still standing.
_CLOSED_STATUS = {"resolved", "closed", "cleared", "done", "completed", "cancelled", "normal"}
#: An asset state that says the asset is not doing its job.
_FAULTY_STATE_RE = re.compile(
    r"out[_ ]of[_ ](?:service|order)|degraded|fault|failed|broken|offline|down|unavailable",
    re.IGNORECASE,
)
#: Instrument faults the anomaly detector records, as opposed to unusual readings.
SENSOR_FAULT_TYPES = ("anomaly:stuck", "anomaly:dropout")
_SENSOR_FAULT_WORDS = {
    "anomaly:stuck": "stuck on one value",
    "anomaly:dropout": "stopped reporting",
}
_PRIORITY_ORDER = {"URGENT": 0, "CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# ── which questions these are ──────────────────────────────────────────────────────────────

#: The fault words, strict on purpose: "issue", "problem", "failure", "wrong" and "down" each
#: name far more than a standing fault, and over the 4,060-question bank they pulled in
#: specialist compound questions ("which upstream failure could stop delivery?").
#: "issues" and "problems" are back (2026-11-07, "What are the top issues in the building right
#: now?" was declined): the every-other-word-is-generic rule below is what keeps them narrow,
#: and with it they match 0 of the 4,060 bank questions.
_FAULT_PHRASE_RE = re.compile(
    r"\b(?:faults?|faulty|broken|not\s+working|out\s+of\s+(?:order|service)|malfunction\w*|"
    r"in\s+alarm|alarms?|issues?|problems?)\b",
    re.IGNORECASE,
)
_OPENER_RE = re.compile(
    r"^\s*(?:are|is|do|does|have|has|any|what|which|how\s+many|show|list|tell\s+me|give\s+me|"
    r"can\s+you|could\s+you)\b",
    re.IGNORECASE,
)
#: Every other word of the question must be one of these: a question about the building as a
#: whole, naming nothing. A room, a floor, a period, a kind of asset or a purpose leaves a word
#: over, and the question then belongs to the lane that owns that thing.
_GENERIC_WORDS = frozenset(
    """a an the any anything something everything what which how many are is do does have has
    there show list tell me give can could you please of in on at with or and all its it our
    this now right currently current moment today at present presently still being live
    building buildings services service systems system sensors sensor equipment plant devices
    device assets asset kit reporting reported report showing flagged raised standing open active
    outstanding uncleared unresolved going off sounding faults fault faulty broken working not
    out order alarm alarms malfunctioning malfunction anywhere top main biggest major key
    issue issues problem problems""".split()
)
_WORDS_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def is_building_fault_question(question: str) -> bool:
    """True for "is anything faulty / are any services reporting faults / any active alarms?".

    Measured over the 4,060-question bank on 2026-11-07: see the test that pins the count.
    """
    q = (question or "").strip()
    if not q or not _OPENER_RE.search(q) or not _FAULT_PHRASE_RE.search(q):
        return False
    if re.search(r"\d", q):
        return False  # a room, a floor, a date or a count: something is named
    if re.match(r"^\s*what\s+(?:is|are)\s+(?:an?\s+)?(?:faults?|alarms?)\s*\??\s*$", q, re.I):
        return False  # "what is a fault?" asks what the word means
    words = [w for w in _WORDS_RE.findall(q.lower()) if w not in _GENERIC_WORDS]
    return not words


# ── what the records say ────────────────────────────────────────────────────────────────────


@dataclass
class Source:
    """One source's reading: ``checked`` False means it could not be read (never zero)."""

    name: str
    checked: bool = False
    items: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""


@dataclass
class FaultOverview:
    alarms: Source
    outages: Source
    assets: Source
    sensors: Source
    open_work_orders: Optional[int] = None

    @property
    def sources(self) -> List[Source]:
        return [self.alarms, self.outages, self.assets, self.sensors]

    @property
    def total(self) -> int:
        return sum(len(s.items) for s in self.sources)


def _bindings(res: Any) -> List[Dict[str, str]]:
    return [
        {k: (v.get("value", "") if isinstance(v, dict) else str(v)) for k, v in b.items()}
        for b in ((res or {}).get("results", {}) or {}).get("bindings", []) or []
    ]


def _parse_dt(text: str) -> Optional[datetime]:
    t = str(text or "").strip()
    if not t:
        return None
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _rows(result: Any) -> List[Any]:
    """execute_query returns a RESULT OBJECT, not rows (see asset_state_service)."""
    return list(getattr(result, "rows", None) or getattr(result, "data", None) or [])


def _col(row: Any, idx: int, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else (row[idx] if len(row) > idx else None)


async def _alarms(sparql_exec: Callable, namespace: str, now: datetime) -> Source:
    src = Source("the alarm log")
    q = f"""PREFIX o: <{O}>
PREFIX rdfs: <{RDFS}>
SELECT ?a ?label ?id ?prio ?status ?from ?to WHERE {{
  ?a a o:AlarmEvent .
  OPTIONAL {{ ?a rdfs:label ?label }} OPTIONAL {{ ?a o:recordId ?id }}
  OPTIONAL {{ ?a o:alarmPriority ?prio }} OPTIONAL {{ ?a o:recordStatus ?status }}
  OPTIONAL {{ ?a o:effectiveFrom ?from }} OPTIONAL {{ ?a o:effectiveTo ?to }}
  FILTER(STRSTARTS(STR(?a), "{namespace}"))
}} LIMIT 5000"""
    try:
        rows = _bindings(await sparql_exec(q))
    except Exception as exc:
        logger.warning(f"[fault_overview] alarm records unread: {exc}")
        return src
    src.checked = True
    seen = set()
    for r in rows:
        if r["a"] in seen:
            continue
        seen.add(r["a"])
        if str(r.get("status") or "").strip().lower() in _CLOSED_STATUS:
            continue
        ended = _parse_dt(r.get("to", ""))
        if ended is not None and ended <= now:
            continue
        src.items.append(
            {
                "what": re.sub(r"@\w+$", "", r.get("label") or r.get("id") or "alarm"),
                "id": r.get("id", ""),
                "priority": str(r.get("prio") or "").upper(),
                "status": r.get("status", ""),
                "since": _parse_dt(r.get("from", "")),
            }
        )
    src.items.sort(
        key=lambda i: (_PRIORITY_ORDER.get(i["priority"], 9), -(i["since"] or now).timestamp())
    )
    return src


def _asset_name(asset: str, kind: str) -> str:
    """'av_Room0.19' -> 'AV equipment, Room 0.19'. Never an IRI; falls back to the id's words."""
    kinds = {"av": "AV equipment", "network": "network / Wi-Fi", "lift": "lift"}
    place = asset.split("_", 1)[1] if "_" in asset else ""
    place = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", place).replace("_", " ")
    what = kinds.get((kind or "").lower(), (kind or "").replace("_", " ") or "equipment")
    return f"{what}, {place}" if place else what


async def _outages(events: Any, now: datetime) -> Source:
    src = Source("the events log")
    if events is None:
        src.note = "no events store is registered"
        return src
    try:
        sql = events.build_active_now("asset_outage")
        rows = _rows(await events.execute_query(sql)) if sql else []
    except Exception as exc:
        logger.warning(f"[fault_overview] outages unread: {exc}")
        return src
    src.checked = True
    for row in rows:
        attrs = _col(row, 6, "attrs")
        try:
            a = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
        except ValueError:
            a = {}
        src.items.append(
            {
                "what": _asset_name(str(a.get("asset") or ""), str(a.get("asset_kind") or "")),
                "reason": str(a.get("reason") or ""),
                "since": _parse_dt(str(_col(row, 3, "start_dt") or "")),
            }
        )
    return src


async def _asset_states(sparql_exec: Callable, namespace: str) -> Source:
    src = Source("the asset status records")
    q = f"""PREFIX o: <{O}>
PREFIX rdfs: <{RDFS}>
SELECT ?s ?asset ?label ?v ?reason ?at WHERE {{
  ?s a o:AssetStatus ; o:statusOf ?asset ; o:statusValue ?v .
  OPTIONAL {{ ?asset rdfs:label ?label }} OPTIONAL {{ ?s o:statusReason ?reason }}
  OPTIONAL {{ ?s o:statusObservedAt ?at }}
  FILTER(STRSTARTS(STR(?s), "{namespace}"))
}} LIMIT 5000"""
    try:
        rows = _bindings(await sparql_exec(q))
    except Exception as exc:
        logger.warning(f"[fault_overview] asset status unread: {exc}")
        return src
    src.checked = True
    seen = set()
    for r in rows:
        if r["s"] in seen or not _FAULTY_STATE_RE.search(r.get("v") or ""):
            continue
        seen.add(r["s"])
        local = r["asset"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        src.items.append(
            {
                "what": re.sub(r"@\w+$", "", r.get("label") or local.replace("_", " ")),
                "state": (r.get("v") or "").replace("_", " "),
                "reason": r.get("reason", ""),
                "since": _parse_dt(r.get("at", "")),
            }
        )
    return src


async def _sensor_faults(events: Any, now: datetime) -> Source:
    src = Source("the sensor fault detector")
    if events is None:
        src.note = "no events store is registered"
        return src
    start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")
    by_kind: Dict[str, set] = {}
    try:
        for kind in SENSOR_FAULT_TYPES:
            sql = events.build_overlap_window(kind, start, end, limit=5000)
            if not sql:
                continue
            for row in _rows(await events.execute_query(sql)):
                by_kind.setdefault(kind, set()).add(str(_col(row, 2, "subject_uuid") or ""))
    except Exception as exc:
        logger.warning(f"[fault_overview] sensor faults unread: {exc}")
        return src
    src.checked = True
    for kind, uuids in sorted(by_kind.items()):
        for u in sorted(uuids):
            src.items.append({"what": _SENSOR_FAULT_WORDS.get(kind, kind), "uuid": u})
    return src


async def _open_work_orders(events: Any) -> Optional[int]:
    if events is None:
        return None
    try:
        sql = events.build_count_by_status("workorder")
        rows = _rows(await events.execute_query(sql)) if sql else []
    except Exception as exc:
        logger.debug(f"[fault_overview] work orders unread: {exc}")
        return None
    total = 0
    for row in rows:
        status = str(_col(row, 0, "status") or "").lower()
        if status not in _CLOSED_STATUS:
            total += int(_col(row, 1, "n") or 0)
    return total


async def collect(
    sparql_exec: Callable,
    namespace: str,
    events: Any = None,
    now: Optional[datetime] = None,
) -> FaultOverview:
    """Read all four sources. ``now`` is store time (UTC, naive)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return FaultOverview(
        alarms=await _alarms(sparql_exec, namespace, now),
        outages=await _outages(events, now),
        assets=await _asset_states(sparql_exec, namespace),
        sensors=await _sensor_faults(events, now),
        open_work_orders=await _open_work_orders(events),
    )


# ── what to say ─────────────────────────────────────────────────────────────────────────────


def _day(d: Optional[datetime], fmt_local: Optional[Callable[[datetime], str]]) -> str:
    if d is None:
        return ""
    if fmt_local is not None:
        try:
            return fmt_local(d)
        except Exception:
            pass
    return f"{d.day} {d.strftime('%b %Y')}"


def _and(items: Sequence[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def render(
    ov: FaultOverview,
    building: str,
    fmt_local: Optional[Callable[[datetime], str]] = None,
    max_items: int = 5,
    yes_no: bool = True,
) -> str:
    """The answer, deterministic. Every count comes from a list the reader can see the head of.

    ``yes_no`` False ("what are the top issues?") leads with the count, not with "Yes".
    """
    name = building or "the building"
    unread = [s.name for s in ov.sources if not s.checked]
    lines: List[str] = []
    if ov.total:
        n_src = sum(1 for s in ov.sources if s.items)
        lines.append(
            f"**{'Yes — ' if yes_no else ''}{ov.total} fault{'s are' if ov.total != 1 else ' is'} "
            f"recorded as standing right now** across {n_src} of {name}'s records:"
        )
    elif not unread:
        lines.append(
            f"**No fault is recorded as standing right now** in {name}'s records: no alarm left "
            "uncleared, no equipment outage in progress, no asset marked out of service or "
            "degraded, and no sensor stuck or silent in the last 24 hours."
        )
    else:
        lines.append(
            f"**I found no standing fault in the records I could read**, but {_and(unread)} "
            "could not be read just now, so this is not a clean bill of health."
        )

    def _block(src: Source, head: str, fmt: Callable[[Dict[str, Any]], str]) -> None:
        if not src.items:
            return
        lines.append("")
        lines.append(f"**{head}: {len(src.items)}** (from {src.name})")
        for it in src.items[:max_items]:
            lines.append(f"- {fmt(it)}")
        if len(src.items) > max_items:
            lines.append(f"- … and {len(src.items) - max_items} more")

    n_high = sum(1 for a in ov.alarms.items if _PRIORITY_ORDER.get(a["priority"], 9) <= 1)
    _block(
        ov.alarms,
        "Alarms not cleared" + (f", {n_high} of them high priority" if n_high else ""),
        lambda a: (
            f"{a['what']}"
            + (f" — {a['priority'].lower()} priority" if a["priority"] else "")
            + (f", {a['status']}" if a["status"] else "")
            + (f", raised {_day(a['since'], fmt_local)}" if a["since"] else "")
            + (f" ({a['id']})" if a["id"] else "")
        ),
    )
    _block(
        ov.outages,
        "Equipment outages in progress",
        lambda o: (
            o["what"]
            + (f" — {o['reason']}" if o["reason"] else "")
            + (f", since {_day(o['since'], fmt_local)}" if o["since"] else "")
        ),
    )
    _block(
        ov.assets,
        "Assets marked out of service or degraded",
        lambda s: (
            f"{s['what']} — {s['state']}"
            + (f" ({s['reason']})" if s["reason"] else "")
            + (f", as of {_day(s['since'], fmt_local)}" if s["since"] else "")
        ),
    )
    if ov.sensors.items:
        kinds: Dict[str, int] = {}
        for it in ov.sensors.items:
            kinds[it["what"]] = kinds.get(it["what"], 0) + 1
        lines.append("")
        lines.append(
            f"**Sensors with an instrument fault in the last 24 hours: {len(ov.sensors.items)}** "
            f"(from {ov.sensors.name}) — "
            + _and([f"{n} {w}" for w, n in sorted(kinds.items(), key=lambda kv: -kv[1])])
            + ". These are faults in the sensor, not unusual readings."
        )
    if ov.total and unread:
        lines.append("")
        lines.append(f"Not checked, because it could not be read just now: {_and(unread)}.")
    if ov.open_work_orders:
        lines.append("")
        lines.append(
            f"For context, {ov.open_work_orders} maintenance work orders are open or assigned; "
            "a work order is planned or requested work, not itself a fault."
        )
    return "\n".join(lines)


async def answer(
    question: str,
    sparql_exec: Callable,
    namespace: str,
    events: Any = None,
    building: str = "",
    fmt_local: Optional[Callable[[datetime], str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The lane payload: ``formatted_response`` plus the counts, for the evidence record."""
    ov = await collect(sparql_exec, namespace, events, now)
    logger.info(
        "[fault_overview] alarms=%s outages=%s assets=%s sensors=%s unread=%s",
        len(ov.alarms.items),
        len(ov.outages.items),
        len(ov.assets.items),
        len(ov.sensors.items),
        [s.name for s in ov.sources if not s.checked] or "none",
    )

    # THE ITEMS RIDE ON THE PAYLOAD, field by field, so the numeric guard can back every figure in
    # the text against a record field (a date as shown, a room number inside a label, a count).
    # Without them the guard rightly withheld the whole answer: the text quoted 16 Sep 2026 and
    # "Room 0.19" and the payload held nothing but four totals.
    def _shown(item: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in item.items() if k != "since"}
        if item.get("since") is not None:
            out["since"] = item["since"].isoformat()
            out["since_shown"] = _day(item["since"], fmt_local)
        return out

    kinds: Dict[str, int] = {}
    for it in ov.sensors.items:
        kinds[it["what"]] = kinds.get(it["what"], 0) + 1
    n_high = sum(1 for a in ov.alarms.items if _PRIORITY_ORDER.get(a["priority"], 9) <= 1)
    return {
        "success": True,
        "formatted_response": render(
            ov,
            building,
            fmt_local,
            yes_no=bool(
                re.match(r"^\W*(?:are|is|do|does|any|has|have|anything)\b", question or "", re.I)
            ),
        ),
        "source": "alarm log, events log and asset status records",
        "fault_overview": {s.name: (len(s.items) if s.checked else None) for s in ov.sources},
        "counts": {
            "total": ov.total,
            "sources_with_faults": sum(1 for s in ov.sources if s.items),
            "sources": len(ov.sources),
            "high_priority_alarms": n_high,
            "sensor_fault_kinds": kinds,
            "more_alarms": max(0, len(ov.alarms.items) - 5),
            "more_outages": max(0, len(ov.outages.items) - 5),
            "more_assets": max(0, len(ov.assets.items) - 5),
            "window_hours": 24,
        },
        "items": {
            "alarms": [_shown(a) for a in ov.alarms.items],
            "outages": [_shown(o) for o in ov.outages.items],
            "assets": [_shown(s) for s in ov.assets.items],
        },
        "open_work_orders": ov.open_work_orders,
    }
