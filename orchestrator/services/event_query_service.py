# -*- coding: utf-8 -*-
"""
event_query_service.py — the S2 event query lane (V5-T24).

Deterministic service answering booking / work-order / access questions from
the generic events store. No LLM anywhere: question kind, time window and the
subject room are resolved by rules; the numbers come from the adapter; the
narration is a template over those numbers (guard-compatible: everything the
prose says exists in the payload).

Join contract (matches synthetic_events.py): subject_uuid =
derive_point_uuid(building_id, "evt_subject", room_local); the entrance
pseudo-subject is "entrance_main".

Honesty: when the building has no events_data source registered, every kind
returns an honest decline naming the unlock path — never an empty guess.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.services.datasource_registry import derive_point_uuid
from shared.utils import get_logger

logger = get_logger(__name__)

EVENTS_STORE_KEY = "bldg:events_data"

# ── question-kind classification (deterministic) ─────────────────────────────

_KIND_RES: List[Tuple[str, re.Pattern]] = [
    # V5-T21 — FIRST: "any anomalies this week?" must never read as tickets
    (
        "anomaly_summary",
        re.compile(
            r"\banomal(?:y|ies|ous)\b|\bunusual (?:readings?|behaviou?rs?|activity|patterns?)\b"
            r"|\bweird (?:data|readings?|values?)\b|\boutliers?\b"
            r"|\banything (?:strange|odd|unusual)\b|\bsensor (?:faults?|glitch(?:es)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "workorder_summary",
        re.compile(
            r"\b(work ?orders?|tickets?|maintenance (backlog|jobs|requests)|repair (jobs|requests))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "access_summary",
        re.compile(
            r"\b(entrance|footfall|how busy (was|is) the building|people (came|come) in"
            r"|visitors? (came|arrived|counted)|arrivals)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "availability_list",
        re.compile(
            r"\b(which|what|any|list)\b.{0,40}\b(rooms?|spaces?)\b.{0,40}\b(free|available|unbooked)\b"
            r"|\b(free|available)\b.{0,20}\brooms?\b",
            re.IGNORECASE,
        ),
    ),
    ("bookings_list", re.compile(r"\b(bookings?|reservations?|booked)\b", re.IGNORECASE)),
]


def classify_event_question(question: str) -> Optional[str]:
    """Kind or None (None => not an event question; router should not have sent it)."""
    q = question or ""
    for kind, pat in _KIND_RES:
        if pat.search(q):
            return kind
    # specific-room availability ("is RM101 free at 3pm?")
    if re.search(r"\b(free|available|booked|in use)\b", q, re.IGNORECASE):
        return "availability_check"
    return None


# ── time-window parsing (calendar windows, deterministic) ─────────────────────


#: Weekday names, in the order date.weekday() uses.
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

#: Part-of-day windows as (start_hour, end_hour, label). Deliberately coarse: a
#: questioner who says "morning" is not asking for a boundary to the minute, and
#: pretending otherwise would put false precision into the answer's label.
_PARTS = {
    "morning": (6, 12, "morning"),
    "afternoon": (12, 18, "afternoon"),
    "evening": (18, 22, "evening"),
    "tonight": (18, 23, "evening"),
}


def _named_day(q: str, day0: datetime):
    """('friday', that day's midnight) when the question names a weekday, else (None, None).

    Resolves FORWARD: "on Friday" asked on a Wednesday means the coming Friday, and
    asked on a Friday means today. A question about a named day is almost always about
    the next one — nobody asks whether a room is free last Friday.
    """
    if "tomorrow" in q:
        return "tomorrow", day0 + timedelta(days=1)
    for idx, name in enumerate(_WEEKDAYS):
        if re.search(r"\b" + name + r"\b", q):
            delta = (idx - day0.weekday()) % 7
            return name.capitalize(), day0 + timedelta(days=delta)
    return None, None


def _part_of_day(q: str):
    """(start_hour, end_hour, label) for morning/afternoon/evening, else None."""
    for word, window in _PARTS.items():
        if re.search(r"\b" + word + r"\b", q):
            return window
    return None


def parse_window(question: str, now: datetime) -> Tuple[datetime, datetime, str]:
    """(start, end, label). Default: today so far -> end of day."""
    q = (question or "").lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", q)
    if m:
        h = int(m.group(1)) % 12 + (12 if (m.group(3) or "").lower() == "pm" else 0)
        base = day0 + timedelta(days=1) if "tomorrow" in q else day0
        start = base + timedelta(hours=h, minutes=int(m.group(2) or 0))
        return (
            start,
            start + timedelta(hours=1),
            start.strftime("%H:%M–") + (start + timedelta(hours=1)).strftime("%H:%M %d %b"),
        )
    # A NAMED DAY and a PART OF DAY are resolved together, because they are asked
    # together. "Is Room1.06 free on Friday morning?" previously matched none of the
    # phrases below and fell through to the default, so it was answered about TODAY —
    # visibly, since the label is printed, but it is still an answer to a different
    # question than the one asked (measured 2026-08-25).
    _day_name, _day_start = _named_day(q, day0)
    _part = _part_of_day(q)
    if _day_name or _part:
        base = _day_start if _day_start is not None else day0
        # "this morning", not "today morning" — the questioner's phrasing is the
        # right label, and a part-of-day window with no named day is always "this".
        base_label = _day_name or ("tomorrow" if "tomorrow" in q else "this")
        if not _part:
            base_label = _day_name or "today"
        if _part:
            lo, hi, part_label = _part
            return (
                base + timedelta(hours=lo),
                base + timedelta(hours=hi),
                f"{base_label} {part_label}",
            )
        return base, base + timedelta(days=1), base_label
    if "tomorrow" in q:
        d = day0 + timedelta(days=1)
        return d, d + timedelta(days=1), "tomorrow"
    if "yesterday" in q:
        return day0 - timedelta(days=1), day0, "yesterday"
    if "last week" in q:
        start = day0 - timedelta(days=day0.weekday() + 7)
        return start, start + timedelta(days=7), "last week"
    if "this week" in q:
        start = day0 - timedelta(days=day0.weekday())
        return start, start + timedelta(days=7), "this week"
    if re.search(r"\b(right now|now|currently|at the moment)\b", q):
        return now, now + timedelta(minutes=1), "right now"
    return day0, day0 + timedelta(days=1), "today"


# ── service ───────────────────────────────────────────────────────────────────


class EventQueryService:
    """Answers event questions; adapter + room resolver are injected (testable)."""

    def __init__(
        self,
        building_id: str,
        adapter,
        room_locals: List[str],
        point_map: Optional[Dict[str, Tuple[str, str]]] = None,
    ):
        self._bid = building_id
        self._adapter = adapter  # MySQLEventsAdapter or None (source absent)
        self._rooms = room_locals
        # V5-T21: sensor uuid -> (room_local, modality), for anomaly episodes
        self._points = point_map or {}

    # room mention -> local name (longest match wins; case/sep tolerant)
    def resolve_room(self, question: str) -> Optional[str]:
        qn = re.sub(r"[^a-z0-9]", "", (question or "").lower())
        best = None
        for local in self._rooms:
            key = re.sub(r"[^a-z0-9]", "", local.lower())
            trimmed = key[:-4] if key.endswith("room") else key
            for probe in (key, trimmed):
                if probe and len(probe) >= 3 and probe in qn:
                    if best is None or len(probe) > best[0]:
                        best = (len(probe), local)
        return best[1] if best else None

    def _decline(self, kind: str) -> Dict[str, Any]:
        return {
            "success": False,
            "kind": kind,
            "formatted_response": (
                "**This building has no events source registered**, so I can't answer "
                "booking, work-order or entrance questions from data. Register an "
                "`events_data` source (see the onboarding contract) and this unlocks."
            ),
        }

    async def answer(self, question: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or datetime.utcnow()
        kind = classify_event_question(question) or "bookings_list"
        if self._adapter is None:
            return self._decline(kind)
        start, end, label = parse_window(question, now)
        handler = {
            "availability_check": self._availability_check,
            "availability_list": self._availability_list,
            "bookings_list": self._bookings_list,
            "workorder_summary": self._workorder_summary,
            "access_summary": self._access_summary,
            "anomaly_summary": self._anomaly_summary,
        }[kind]
        try:
            return await handler(question, start, end, label, now)
        except Exception as exc:
            logger.error(f"[events] {kind} failed: {exc}", exc_info=True)
            return {
                "success": False,
                "kind": kind,
                "formatted_response": "I couldn't read the events store just now — please try again.",
            }

    # ── handlers ─────────────────────────────────────────────────────────────

    async def _rows(self, sql: str) -> List[Any]:
        result = await self._adapter.execute_query(sql)
        data = getattr(result, "rows", None) or getattr(result, "data", None) or []
        return list(data)

    @staticmethod
    def _col(row: Any, idx: int, name: str) -> Any:
        """Row field by name (live DictCursor) or position (tuple fixtures)."""
        if isinstance(row, dict):
            return row.get(name)
        return row[idx]

    @staticmethod
    def _fmt_dt(v: Any) -> str:
        return v.strftime("%H:%M") if isinstance(v, datetime) else str(v)[11:16]

    async def _availability_check(self, question, start, end, label, now):
        room = self.resolve_room(question)
        if not room:
            return {
                "success": False,
                "kind": "availability_check",
                "formatted_response": (
                    "I couldn't match that room name — try the room id as it appears "
                    "on the floor plan (e.g. the label shown in 'show me floor 1')."
                ),
            }
        su = derive_point_uuid(self._bid, "evt_subject", room)
        sql = self._adapter.build_overlap_window(
            "booking",
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            subject_uuids=[su],
        )
        rows = await self._rows(sql)
        clashes = [
            f"{self._fmt_dt(self._col(r, 3, 'start_dt'))}–"
            f"{self._fmt_dt(self._col(r, 4, 'end_dt'))}"
            for r in rows
        ]
        free = not rows
        text = (
            f"**{room} is free {label}** — no bookings overlap that window."
            if free
            else f"**{room} is booked {label}**: " + ", ".join(clashes[:4]) + "."
        )
        return {
            "success": True,
            "kind": "availability_check",
            "room": room,
            "window": label,
            "clashes": clashes,
            "free": free,
            "source": "events_data",
            "formatted_response": text,
        }

    async def _availability_list(self, question, start, end, label, now):
        sql = self._adapter.build_overlap_window(
            "booking",
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        rows = await self._rows(sql)
        busy_uuids = {self._col(r, 2, "subject_uuid") for r in rows}
        uuid_to_room = {derive_point_uuid(self._bid, "evt_subject", r): r for r in self._rooms}
        free_rooms = sorted(r for u, r in uuid_to_room.items() if u not in busy_uuids)
        shown = free_rooms[:12]
        text = (
            f"**{len(free_rooms)} of {len(self._rooms)} rooms have no booking {label}**: "
            + ", ".join(shown)
            + (" …" if len(free_rooms) > len(shown) else "")
            + "\n\n_Availability = no booking on record; walk-in use isn't tracked here._"
        )
        return {
            "success": True,
            "kind": "availability_list",
            "window": label,
            "free_count": len(free_rooms),
            "total_rooms": len(self._rooms),
            "free_rooms": shown,
            "source": "events_data",
            "formatted_response": text,
        }

    async def _bookings_list(self, question, start, end, label, now):
        room = self.resolve_room(question)
        subj = [derive_point_uuid(self._bid, "evt_subject", room)] if room else None
        sql = self._adapter.build_overlap_window(
            "booking",
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            subject_uuids=subj,
        )
        rows = await self._rows(sql)
        scope = room or "the building"
        lines = []
        for r in rows[:10]:
            attrs_raw = self._col(r, 6, "attrs")
            att = ""
            if attrs_raw:
                try:
                    att = f" · {json.loads(attrs_raw).get('attendees', '?')} attendees"
                except Exception:
                    att = ""
            lines.append(
                f"- {self._fmt_dt(self._col(r, 3, 'start_dt'))}–"
                f"{self._fmt_dt(self._col(r, 4, 'end_dt'))}" + att
            )
        text = f"**{len(rows)} booking(s) for {scope} {label}**" + (
            ":\n" + "\n".join(lines) if lines else " — none on record."
        )
        return {
            "success": True,
            "kind": "bookings_list",
            "room": room,
            "window": label,
            "count": len(rows),
            # The rendered lines travel WITH the answer, the same way
            # availability_check carries its `clashes`. This branch printed up to
            # ten booking times and attendee counts and then reported only the
            # count, so the numeric guard found thirteen figures in the narration
            # that nothing in the payload could account for and suppressed a
            # correct answer (measured 2026-08-25: "how many room bookings are
            # there today?" returned the suppression text against 224 real
            # bookings). The guard was right — an answer must carry the evidence
            # for every number it states, and the fix belongs here rather than in
            # a guard exemption for clock times.
            "bookings": lines,
            "source": "events_data",
            "formatted_response": text,
        }

    async def _workorder_summary(self, question, start, end, label, now):
        aged = None
        if re.search(r"\boverdue|older than\b", question, re.IGNORECASE):
            aged = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        sql = self._adapter.build_count_by_status("workorder", open_older_than=aged)
        rows = await self._rows(sql)
        counts = {str(self._col(r, 0, "status")): int(self._col(r, 1, "n")) for r in rows}
        total = sum(counts.values())
        if aged:
            text = (
                f"**{counts.get('open', 0)} work order(s) open for more than 7 days.**"
                if counts
                else "**No work orders open beyond 7 days.**"
            )
        else:
            parts = ", ".join(f"{v} {k}" for k, v in counts.items()) or "none on record"
            text = f"**Work orders: {parts}** ({total} total)."
        # V6-T24: a work-order count that ignores what people actually reported answers the
        # estate's question and not the building's. The joined view adds unlinked user
        # reports and counts a linked pair ONCE, then states how the figure reconciles with
        # the two raw ones — otherwise a reader who knows one store's number cannot tell a
        # correction from a contradiction.
        joined, joined_counts = await self._joined_ticket_note()
        if joined:
            text = text + "\n\n" + joined
        payload = {
            "success": True,
            "kind": "workorder_summary",
            "counts": counts,
            "total": total,
            "aged_filter_days": 7 if aged else None,
            "source": "events_data + user_reports",
            "formatted_response": text,
        }
        # This module's own contract, stated in its docstring: everything the prose says must
        # exist in the payload so the numeric guard can trace it. The joined note introduces
        # figures the work-order counts do not carry, and without them the guard correctly
        # refused the entire answer — a number in the text with no counterpart in the data is
        # precisely what it exists to stop.
        if joined_counts:
            payload["joined_tickets"] = joined_counts
        return payload

    async def _joined_ticket_note(self) -> Tuple[str, Dict[str, int]]:
        """One line reconciling work orders with what people reported (V6-T24).

        Degrades to "" — never raises and never blocks the work-order answer. A building with
        no intake store keeps the events-only behaviour it had, which is the portability
        contract: the join is additive where both stores exist.
        """
        try:
            from orchestrator.services.report_intake_service import (
                get_report_intake_service,
            )
            from orchestrator.services.tickets import counts as ticket_counts
            from orchestrator.services.tickets import (
                merge,
                reconciliation_note,
                ticket_from_event,
            )

            svc = get_report_intake_service()
            reports = await svc.tickets_from_reports(self._bid)
            if not reports:
                return "", {}
            rows = await self._rows(
                self._adapter.build_overlap_window(
                    "workorder", "1970-01-01 00:00:00", "2999-01-01 00:00:00", limit=2000
                )
            )
            wos = []
            for r in rows:
                wos.append(
                    ticket_from_event(
                        r
                        if isinstance(r, dict)
                        else {
                            "event_id": self._col(r, 0, "event_id"),
                            "status": self._col(r, 5, "status"),
                            "start_dt": self._col(r, 3, "start_dt"),
                            "attrs": self._col(r, 6, "attrs"),
                        }
                    )
                )
            merged = merge(reports, wos)
            note = reconciliation_note(len(reports), len(wos), merged)
            tcounts = {
                **ticket_counts(merged),
                "raw_reports": len(reports),
                "raw_work_orders": len(wos),
            }
            open_reports = [t for t in merged if t.origin == "user_report" and t.is_open]
            if open_reports:
                note += (
                    f" {len(open_reports)} report(s) filed by people are not yet linked to a "
                    "work order."
                )
            return f"_{note}_", tcounts
        except Exception as exc:
            logger.debug(f"[events] joined ticket note skipped: {exc}")
            return "", {}

    async def _access_summary(self, question, start, end, label, now):
        su = derive_point_uuid(self._bid, "evt_subject", "entrance_main")
        sql = self._adapter.build_overlap_window(
            "access",
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            subject_uuids=[su],
            limit=5000,
        )
        rows = await self._rows(sql)
        total = 0
        for r in rows:
            attrs_raw = self._col(r, 6, "attrs")
            try:
                total += int(json.loads(attrs_raw).get("count", 1)) if attrs_raw else 1
            except Exception:
                total += 1
        text = (
            f"**About {total} arrivals through the main entrance {label}** "
            f"(aggregate counts only — individuals are never tracked)."
        )
        return {
            "success": True,
            "kind": "access_summary",
            "window": label,
            "arrivals": total,
            "source": "events_data",
            "formatted_response": text,
        }

    async def _anomaly_summary(self, question, start, end, label, now):
        """V5-T21 — 'any anomalies this week?' answered from the scanner's
        persisted episodes (events store), never a fresh z-score pass."""
        _limit = 500
        sql = self._adapter.build_anomaly_episodes(
            start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), limit=_limit
        )
        rows = await self._rows(sql) if sql else []
        capped = len(rows) >= _limit  # no silent caps — say so when truncated
        by_detector: Dict[str, int] = {}
        episodes = []
        for row in rows:
            etype = str(self._col(row, 1, "event_type") or "")
            detector = etype.split(":", 1)[-1] or "unknown"
            by_detector[detector] = by_detector.get(detector, 0) + 1
            subj = str(self._col(row, 2, "subject_uuid") or "")
            room, modality = self._points.get(subj, ("", ""))
            s_dt = self._col(row, 3, "start_dt")
            e_dt = self._col(row, 4, "end_dt")
            try:
                dur_h = round((e_dt - s_dt).total_seconds() / 3600.0, 1)
            except TypeError:
                dur_h = None
            attrs_raw = self._col(row, 6, "attrs")
            try:
                attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
            except (TypeError, ValueError):
                attrs = {}
            episodes.append(
                {
                    "detector": detector,
                    "room": room,
                    "modality": modality or attrs.get("modality", ""),
                    "duration_h": dur_h,
                    "status": str(self._col(row, 5, "status") or ""),
                    "severity": str(attrs.get("severity", "")),
                }
            )
        if not episodes:
            return {
                "success": True,
                "kind": "anomaly_summary",
                "window": label,
                "count": 0,
                "source": "events store (anomaly scanner)",
                "formatted_response": (
                    f"**No anomaly episodes are recorded for {label}.** The detector "
                    "suite sweeps every backed sensor hourly (seasonal-residual, stuck, "
                    "dropout, drift, spikes, schedule, cross-modality) — a quiet log "
                    "means nothing crossed its thresholds in that window."
                ),
            }
        counts_txt = ", ".join(f"{k}: {v}" for k, v in sorted(by_detector.items()))
        highlights = (
            sorted(
                (e for e in episodes if e["severity"] == "high" or e["status"] == "open"),
                key=lambda e: (e["status"] != "open", -(e["duration_h"] or 0)),
            )[:5]
            or episodes[:5]
        )
        bullets = []
        for e in highlights:
            where = e["room"] or "unresolved point"
            dur = f", {e['duration_h']:g}h" if e["duration_h"] is not None else ""
            bullets.append(
                f"- **{e['detector']}** · {where} ({e['modality'] or '?'}){dur} "
                f"[{e['status']}{'/' + e['severity'] if e['severity'] else ''}]"
            )
        count_txt = f"at least {len(episodes)}" if capped else f"{len(episodes)}"
        text = (
            f"**{count_txt} anomaly episode(s) recorded {label}** — {counts_txt}.\n"
            + "\n".join(bullets)
            + (
                "\n\n_(showing the most recent "
                f"{_limit}; narrow the window for the full picture)_"
                if capped
                else ""
            )
            + "\n\n_Episodes come from the hourly detector sweep over this building's "
            "own sensors; ask 'why was <room> <symptom>?' to see the evidence behind one._"
        )
        return {
            "success": True,
            "kind": "anomaly_summary",
            "window": label,
            "count": len(episodes),
            "by_detector": by_detector,
            "episodes": episodes[:20],
            "source": "events store (anomaly scanner)",
            "formatted_response": text,
        }
