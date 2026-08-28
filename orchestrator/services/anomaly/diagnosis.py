# -*- coding: utf-8 -*-
"""
diagnosis.py — deterministic evidence assembly for indirect why-questions (V5-T20).

"Why was floor 2 freezing on Tuesday?" → resolve (referent, modality, window),
assemble what the data actually shows (window stats vs the week before, vs
floor peers), pull coinciding anomaly episodes from the events store and
complaints from user_reports, then rank CANDIDATE causes by time-coincidence.

Language discipline: every explanation is templated as "consistent with …" /
"coincides with …" — correlation in time, never a causal claim. Every number
in the narration comes from the assembled evidence. Anything missing (no
complaints table, no contact sensors) silently drops out of the evidence —
it never blocks the answer.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from orchestrator.services.anomaly.detectors import _clean
from shared.utils import get_logger

logger = get_logger(__name__)

#: generic comfort vocabulary → modality (domain English, never building names)
#:
#: COMPARATIVES ADMITTED (BUG-354, second half). These are the forms people actually use
#: in a why-question: nobody asks "why is it warm here", they ask "why is it WARMER in
#: the corner". ``\bwarm\b`` does not match "warmer" — the word boundary stops it —
#: exactly as ``\bhumid\b`` did not match "humidity".
#:
#: "Why is it so much warmer in the corner than by the windows?" therefore reached no
#: lane and returned "I processed your request, but couldn't generate a response." It was
#: the single 'wrong' answer in bldg1's clean certification — found in the very next run
#: after I closed this defect as fixed on two other examples.
_MODALITY_WORDS: List[Tuple[re.Pattern, str, str]] = [
    (
        re.compile(
            r"\bfreez|\bcold(?:er|est)?\b|\bchill(?:y|ier|iest)\b|\bcool(?:er|est)?\b", re.I
        ),
        "temperature",
        "low",
    ),
    (
        re.compile(r"\bhot(?:ter|test)?\b|\bboiling\b|\boverheat|\bwarm(?:er|est)?\b", re.I),
        "temperature",
        "high",
    ),
    (
        re.compile(r"\bstuff(?:y|ier|iest)\b|\bco2\b|\bairless\b|\bventilat", re.I),
        "co2",
        "high",
    ),
    (
        re.compile(r"\bloud(?:er|est)?\b|\bnois(?:y|ier|iest)\b|\bnoise\b", re.I),
        "noise",
        "high",
    ),
    (
        re.compile(r"\bdark(?:er|est)?\b|\bdim(?:mer|mest)?\b|\bgloom(?:y|ier|iest)\b", re.I),
        "illuminance",
        "low",
    ),
    (
        re.compile(
            r"\bhumid\w*\b|\bdamp(?:er|est)?\b|\bmugg(?:y|ier|iest)\b|\bdr(?:y|ier|iest)\b", re.I
        ),
        "humidity",
        "high",
    ),
    (
        re.compile(
            r"\bdust(?:y|ier|iest)\b|\bsmok(?:y|ier|iest)\b|\bair quality\b|\bpm2\.?5\b", re.I
        ),
        "pm25",
        "high",
    ),
    (
        re.compile(r"\bbus(?:y|ier|iest)\b|\bcrowded\b|\bpacked\b", re.I),
        "occupancy",
        "high",
    ),
]

#: The modality NAMES, which the lay list above does not contain (BUG-354).
#:
#: Graded 'wrong' on bldg1: "Why does the temperature keep changing?" returned "I processed
#: your request, but couldn't generate a response." WHY_RE matched; the modality lookup did
#: not, because "temperature", "illuminance" and "occupancy" appear nowhere in it and
#: ``\bhumid\b`` does not match "humidity" -- the trailing word boundary stops it.
#:
#: So an occupant asking "why is it stuffy" was served and a facility manager asking "why is
#: the humidity high" was not. Design contract 6 requires the same system to serve lay users
#: AND experts; this list is the half that was missing.
#:
#: Direction comes from an accompanying word where there is one. A bare name carries no
#: direction, so it falls back to the side of the range people normally complain about --
#: named in the tuple rather than guessed at per call.
_MODALITY_NAMES: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\btemperature\b|\btemp\b", re.I), "temperature", "high"),
    (re.compile(r"\bhumidity\b|\brelative humidity\b|\brh\b", re.I), "humidity", "high"),
    (re.compile(r"\bco2\b|\bcarbon dioxide\b", re.I), "co2", "high"),
    (re.compile(r"\bnoise level\b|\bsound level\b|\bacoustics?\b", re.I), "noise", "high"),
    (
        re.compile(r"\billuminance\b|\blight level\b|\blux\b|\blighting\b", re.I),
        "illuminance",
        "low",
    ),
    (re.compile(r"\bpm2\.?5\b|\bparticulate\b", re.I), "pm25", "high"),
    (re.compile(r"\boccupancy\b|\bfootfall\b|\bhead ?count\b", re.I), "occupancy", "high"),
]

#: Words that flip a bare modality name to the other end of the range.
_LOW_DIRECTION_RE = re.compile(
    r"\b(?:low|lower|dropping|falling|too\s+little|not\s+enough|below)\b", re.I
)
_HIGH_DIRECTION_RE = re.compile(
    r"\b(?:high|higher|rising|climbing|too\s+much|excessive|above)\b", re.I
)

WHY_RE = re.compile(
    r"^\s*why\b|\bwhy (?:was|is|were|are|did|does)\b|\bwhat(?:'s| is) (?:wrong|going on|the reason)\b",
    re.IGNORECASE,
)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def is_why_question(question: str) -> Optional[Tuple[str, str]]:
    """(modality, direction) when this is a diagnosable why-question, else None."""
    if not WHY_RE.search(question or ""):
        return None
    # Lay terms first: they carry a direction of their own ("chilly" is not merely
    # "temperature"), so a question that uses one should keep that reading.
    for pat, modality, direction in _MODALITY_WORDS:
        if pat.search(question):
            return modality, direction
    # Then the modality names themselves, with the direction taken from an accompanying
    # word where the asker supplied one (BUG-354).
    for pat, modality, default_direction in _MODALITY_NAMES:
        if pat.search(question):
            if _LOW_DIRECTION_RE.search(question):
                return modality, "low"
            if _HIGH_DIRECTION_RE.search(question):
                return modality, "high"
            return modality, default_direction
    return None


def parse_day_window(question: str, now: datetime) -> Tuple[datetime, datetime, str]:
    """Deterministic day-window resolution; defaults to the last 24 hours."""
    q = (question or "").lower()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b(?:on |last )?{name}\b", q):
            delta = (today.weekday() - i) % 7 or 7  # most recent PAST occurrence
            day = today - timedelta(days=delta)
            return day, day + timedelta(days=1), f"last {name.capitalize()}"
    if "yesterday" in q:
        return today - timedelta(days=1), today, "yesterday"
    if "this morning" in q:
        return today + timedelta(hours=6), min(now, today + timedelta(hours=12)), "this morning"
    if "last night" in q:
        return today - timedelta(hours=2), today + timedelta(hours=6), "last night"
    if "today" in q:
        return today, now, "today"
    return now - timedelta(hours=24), now, "the last 24 hours"


def _squash(text: str) -> str:
    """Lowercase, strip every non-alphanumeric. Used on BOTH sides of a label comparison.

    One function so the two sides cannot drift apart again -- they already did once, and the
    result was a comparison that could never match.
    """
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


class DiagnosisService:
    """All I/O injectable; every gatherer degrades to 'no evidence' silently."""

    def __init__(
        self,
        building_id: str,
        namespace: str,
        sparql_exec: Optional[Callable] = None,
        adapter_getter: Optional[Callable[[str], Any]] = None,
        pg_pool: Any = None,
    ) -> None:
        self.building_id = building_id
        self.namespace = namespace
        self._sparql = sparql_exec
        self._adapter_getter = adapter_getter
        self._pg_pool = pg_pool

    # ── referent resolution ────────────────────────────────────────────────

    @staticmethod
    def resolve_referent(question: str, spaces) -> Tuple[str, List]:
        """('room'|'floor'|'building', matching SpaceCoverage list)."""
        q = (question or "").lower()
        m = re.search(r"\b(?:room\s*)?(rm\s?\w{2,6}|\d{1,2}\.\d{2,3})\b", q, re.IGNORECASE)
        if m:
            # BOTH sides must be normalised the same way. The token dropped "." while the
            # label kept it, so "5.01" became "501" and was compared against "room 5.01" --
            # a match that could never succeed for ANY label form (Room 5.01, Room5.01,
            # Room_5.01, 5.01 all fail). Every room-scoped why-question therefore fell
            # through to the building branch below and was answered from a whole-building
            # average, which is a wrong-scope answer that reads exactly like a right one:
            # "why is 5.01 stuffy" returned the mean across 233 rooms with no indication the
            # room had not been found.
            token = _squash(m.group(1))
            hits = [sc for sc in spaces if token in _squash(sc.label)]
            if hits:
                return "room", hits[:1]
        m = re.search(r"\b(?:floor|level)\s*(\w{1,3})\b", q)
        if m:
            token = m.group(1).lower()
            hits = [sc for sc in spaces if str(sc.floor).lower().endswith(token)]
            if hits:
                return "floor", hits
        return "building", list(spaces)

    # ── evidence gatherers ─────────────────────────────────────────────────

    async def _series_for(
        self,
        targets,
        modality: str,
        start: datetime,
        end: datetime,
        deep: bool = False,
    ):
        from orchestrator.services.deliberation.candidates import Candidate
        from orchestrator.services.deliberation.fetch import fetch_series

        candidates = []
        for sc in targets:
            h = (sc.modalities or {}).get(modality) or {}
            if str(h.get("status", "")) == "present" and h.get("uuid"):
                candidates.append(
                    Candidate(
                        space_iri=sc.space_iri,
                        label=sc.label,
                        floor=sc.floor,
                        sensors={modality: {"uuid": h["uuid"], "stored_at": h["stored_at"]}},
                    )
                )
        if not candidates:
            return {}, []
        window_hours = max(
            24.0, (datetime.utcnow() - (start - timedelta(days=7))).total_seconds() / 3600.0
        )
        # `per_uuid_limit` defaults to 500 rows, which at a ten-minute cadence covers about 83
        # hours -- so the WEEK-EARLIER window this method deliberately reaches back for was
        # never in the result. The "same window a week earlier" line could not appear for any
        # sensor sampling faster than about twenty minutes, and nothing said why: the fetch
        # succeeded, the rows were simply the wrong ones.
        #
        # Raised only for the TARGET series (`deep`). The peer call asks for every space in the
        # building, and widening that would multiply a 233-room fetch by five for a comparison
        # that only ever needs the current window.
        limit = 500
        if deep:
            limit = max(500, min(5000, int(window_hours * 12)))
        series = await fetch_series(
            candidates,
            [modality],
            window_hours=window_hours,
            per_uuid_limit=limit,
            adapter_getter=self._adapter_getter,
        )
        return series, candidates

    async def _plant_state(
        self, targets, start: datetime, end: datetime, room_series=None, room_mean=None
    ):
        """What the plant serving this space was DOING during the window (V6-T26).

        This is the difference between describing a problem and explaining it. Before this,
        "why is 5.01 stuffy?" answered with the CO2 mean and then guessed -- "the elevated
        average suggests that ventilation is insufficient" -- while the AHU's fan state and
        the VAV's damper position sat connected and readable in the graph the whole time. A
        guess phrased as a suggestion is still a claim the data did not support.

        Returns (notes, figures). Figures ride in the payload because the numeric guard
        refuses an answer whose prose contains numbers the evidence does not carry -- the
        same rule that caught the T24 note.
        """
        notes: List[Tuple[float, str]] = []
        figures: Dict[str, Any] = {}
        if not targets:
            return notes, figures
        try:
            from orchestrator.services.deliberation.candidates import Candidate
            from orchestrator.services.deliberation.fetch import fetch_series
            from orchestrator.services.evidence import plant_state as _plant

            sparql = self._sparql
            if sparql is None:  # pragma: no cover - live wiring
                from orchestrator.services.deliberation.live import (
                    sparql_exec as sparql,
                )

            ctx = await _plant.for_space(targets[0].space_iri, sparql, self.building_id)
            figures["plant_equipment"] = [e.rsplit("#", 1)[-1] for e in ctx.equipment]
            figures["plant_points"] = len(ctx.points)
            if not ctx.has_points:
                # Named, not silent. "No plant data" read as an omission is indistinguishable
                # from "the plant is fine", and they are opposite messages to a facilities team.
                figures["plant_note"] = ctx.describe()
                return notes, figures

            wanted = {"Fan_Status": "fan_state", "Damper_Position_Sensor": "damper_position"}
            cands, byuuid = [], {}
            for pt in ctx.points:
                mod = wanted.get(pt.kind)
                if not mod or not pt.uuid:
                    continue
                byuuid[pt.uuid] = (mod, pt.equipment_name)
                cands.append(
                    Candidate(
                        space_iri=pt.equipment_iri,
                        label=pt.equipment_name,
                        floor="",
                        sensors={mod: {"uuid": pt.uuid, "stored_at": "plant_data"}},
                    )
                )
            if not cands:
                return notes, figures

            hours = max(24.0, (datetime.utcnow() - start).total_seconds() / 3600.0)
            series = await fetch_series(
                cands,
                sorted({m for m, _ in byuuid.values()}),
                window_hours=hours,
                adapter_getter=self._adapter_getter,
            )
            for uuid, (mod, equip) in byuuid.items():
                pts = [v for t, v in _clean(series.get(uuid) or []) if start <= t < end]
                if not pts:
                    continue
                mean = sum(pts) / len(pts)
                if mod == "fan_state":
                    on_pct = round(100.0 * sum(1 for v in pts if v >= 0.5) / len(pts), 1)
                    figures[f"fan_on_pct::{equip}"] = on_pct
                    # A LOW RUNTIME IS NOT A FINDING. The first version raised this whenever
                    # the fan ran under half the window, and 39.6% of 24 hours is roughly one
                    # working day -- a NORMAL schedule, presented as the leading explanation
                    # for a warm room. That is a plausible-sounding diagnosis of nothing, and
                    # it is exactly the class of answer this project exists to avoid.
                    #
                    # The measured signal is COINCIDENCE, not runtime: the fan being off while
                    # the room was above its own average for the window. Overnight downtime
                    # never triggers it, because the room is not elevated then.
                    off_pct = self._off_while_elevated(
                        series.get(uuid) or [], room_series, room_mean, start, end
                    )
                    # LIFT OVER THE BASE RATE, not the raw coincidence. A fan that is off every
                    # night in a building whose rooms are warmest at night coincides with the
                    # elevation 100% of the time -- in EVERY room, EVERY night. That is the
                    # diurnal cycle, not a fault, and reporting it as the leading explanation
                    # is the "normal schedule presented as a cause" failure wearing a better
                    # statistic. The finding is that the fan was off MORE during the elevated
                    # time than it was overall.
                    base_off = round(100.0 - on_pct, 1)
                    lift = None if off_pct is None else round(off_pct - base_off, 1)
                    if off_pct is not None:
                        figures[f"fan_off_while_elevated_pct::{equip}"] = off_pct
                        figures[f"fan_off_lift_pts::{equip}"] = lift
                        if off_pct >= 50.0 and (lift or 0) >= 20.0:
                            notes.append(
                                (
                                    6.0,
                                    f"{equip}'s supply fan was off for {off_pct}% of the time "
                                    f"this space was above its own average, against {base_off}% "
                                    f"of the window overall — the downtime is concentrated in "
                                    f"the elevated periods rather than spread evenly",
                                )
                            )
                elif mod == "damper_position":
                    figures[f"damper_mean::{equip}"] = round(mean, 1)
                    if mean < 20.0:
                        notes.append(
                            (
                                5.0,
                                f"{equip}'s damper averaged {mean:.1f}% open — near-minimum "
                                f"fresh-air position",
                            )
                        )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"[diagnosis] plant state unavailable: {exc}")
        return notes, figures

    @staticmethod
    def _off_while_elevated(fan_series, room_series, room_mean, start, end):
        """Share of the ELEVATED room time during which the fan was off, or None.

        `None` means the question cannot be asked -- no room series, no mean, or no elevated
        samples -- and is reported as no finding rather than as a clean bill of health.

        Each elevated room sample is matched to the fan sample in force at that moment (the
        most recent one at or before it). Fan state is a step function: interpolating it would
        invent half-running fans, and taking the nearest sample in EITHER direction would let a
        fan that started later explain an earlier elevation.
        """
        if not fan_series or not room_series or room_mean is None:
            return None
        fan = sorted(
            ((t, v) for t, v in _clean(fan_series) if start <= t < end), key=lambda p: p[0]
        )
        room = [(t, v) for t, v in _clean(room_series) if start <= t < end and v > room_mean]
        if not fan or not room:
            return None

        import bisect

        stamps = [t for t, _ in fan]
        off = 0
        for t, _v in room:
            idx = bisect.bisect_right(stamps, t) - 1
            if idx < 0:
                continue  # the room reading predates any fan sample: unknown, not "off"
            if fan[idx][1] < 0.5:
                off += 1
        return round(100.0 * off / len(room), 1)

    @staticmethod
    def _window_mean(series, start: datetime, end: datetime) -> Optional[float]:
        pts = [v for t, v in _clean(series) if start <= t < end]
        return (sum(pts) / len(pts)) if pts else None

    async def _anomalies_overlapping(self, uuids: List[str], start, end) -> List[Dict]:
        adapter_getter = self._adapter_getter
        if adapter_getter is None:  # pragma: no cover - live wiring
            from orchestrator.services.adapters.registry import adapter_registry

            adapter_getter = adapter_registry.get
        adapter = adapter_getter("bldg:events_data")
        if adapter is None or not uuids:
            return []
        try:
            pool = await adapter._ensure_pool()
            placeholders = ",".join(["%s"] * len(uuids))
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"SELECT event_type, subject_uuid, start_dt, end_dt, attrs FROM events "  # nosec B608 — placeholders only
                        f"WHERE event_type LIKE 'anomaly:%%' AND subject_uuid IN ({placeholders}) "
                        f"AND start_dt <= %s AND end_dt >= %s",
                        (*uuids, end, start),
                    )
                    rows = await cur.fetchall()
            out = []
            for etype, subj, s, e, attrs in rows:
                try:
                    a = json.loads(attrs) if attrs else {}
                except (TypeError, ValueError):
                    a = {}
                out.append(
                    {
                        "event_type": etype,
                        "subject_uuid": subj,
                        "start_dt": s,
                        "end_dt": e,
                        "attrs": a,
                    }
                )
            return out
        except Exception as exc:
            logger.warning(f"[diagnosis] anomaly lookup failed (evidence dropped): {exc}")
            return []

    async def _complaints_in_window(self, start, end) -> List[Dict]:
        if self._pg_pool is None:
            return []
        try:
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT category, title, location, created_at FROM user_reports "
                    "WHERE building_id=$1 AND created_at >= $2 AND created_at <= $3 LIMIT 20",
                    self.building_id,
                    start,
                    end,
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"[diagnosis] complaint lookup failed (evidence dropped): {exc}")
            return []

    # ── the diagnosis ──────────────────────────────────────────────────────

    async def diagnose(self, question: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or datetime.utcnow()
        hit = is_why_question(question)
        if hit is None:
            return {"success": False, "formatted_response": ""}
        modality, direction = hit
        start, end, window_label = parse_day_window(question, now)

        from orchestrator.services.deliberation.capability_schema import build_schema
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        sparql = self._sparql
        if sparql is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as sparql
        schema = await build_schema(
            self.building_id, self.namespace, sparql, load_modalities(self.building_id)
        )
        kind, targets = self.resolve_referent(question, schema.spaces)
        label = (
            targets[0].label
            if kind == "room"
            else (f"floor {targets[0].floor}" if kind == "floor" else "the building")
        )

        series, candidates = await self._series_for(targets, modality, start, end, deep=True)
        target_uuids = [c.sensors[modality]["uuid"] for c in candidates]
        merged: List = []
        for uid in target_uuids:
            merged.extend(series.get(uid) or [])
        window_mean = self._window_mean(merged, start, end)
        prior_mean = self._window_mean(merged, start - timedelta(days=7), end - timedelta(days=7))

        if window_mean is None:
            # The referent and window MUST ride in the payload, not only in the prose. The
            # numeric guard checks every number in the narration against the payload's own
            # fields, and a room name like "Room 5.01" is numerically indistinguishable from a
            # reading -- the same shape as BUG-242, where report id REP-571188 was judged as a
            # measurement. Without these fields the guard suppressed this message and replaced
            # a correct, useful "I have no readings for 5.01" with "a number could not be
            # traced back to the underlying data": an honest answer destroyed by the mechanism
            # meant to protect honesty. The success path already carries them; only this
            # early return did not.
            return {
                "success": False,
                "kind": "diagnosis",
                "modality": modality,
                "referent": label,
                "window": [start.isoformat(), end.isoformat()],
                "window_label": window_label,
                "formatted_response": (
                    f"**I have no {modality} readings for {label} over {window_label}**, so I "
                    "can't reconstruct what happened — nothing to diagnose from."
                ),
            }

        # peer comparison: same modality across the whole building for context
        peer_series, peer_cands = await self._series_for(schema.spaces, modality, start, end)
        peer_means = []
        for c in peer_cands:
            if c.sensors[modality]["uuid"] in target_uuids:
                continue
            m = self._window_mean(peer_series.get(c.sensors[modality]["uuid"]) or [], start, end)
            if m is not None:
                peer_means.append(m)
        peer_median = sorted(peer_means)[len(peer_means) // 2] if peer_means else None

        # contact-sensor coincidence (windows/doors open while temperature complained)
        contact_note = None
        if modality == "temperature":
            for contact_mod in ("window_contact", "door_contact"):
                c_series, c_cands = await self._series_for(targets, contact_mod, start, end)
                for c in c_cands:
                    m = self._window_mean(
                        c_series.get(c.sensors[contact_mod]["uuid"]) or [], start, end
                    )
                    if m is not None and m > 0.3:
                        contact_note = (
                            f"{contact_mod.replace('_', ' ')} sensors read open "
                            f"~{round(m * 100)}% of {window_label}"
                        )
                        break
                if contact_note:
                    break

        anomalies = await self._anomalies_overlapping(target_uuids, start, end)
        complaints = await self._complaints_in_window(start, end)

        # ── candidate causes by coincidence ────────────────────────────────
        causes: List[Tuple[float, str]] = []
        for a in anomalies:
            det = a["event_type"].split(":", 1)[-1]
            score = float(a["attrs"].get("score", 1.0) or 1.0)
            if det == "dropout":
                causes.append(
                    (
                        score,
                        "a sensor reporting gap overlaps the window — readings may be incomplete",
                    )
                )
            elif det == "stuck":
                causes.append(
                    (
                        score,
                        "the sensor was reporting a frozen value — the reading itself may be the fault",
                    )
                )
            elif det == "drift_vs_peers":
                causes.append(
                    (
                        score,
                        "this space was drifting away from its peers — consistent with a local fault (equipment or sensor)",
                    )
                )
            elif det == "seasonal_residual":
                causes.append(
                    (score, f"{modality} was far outside its usual pattern for those hours")
                )
            elif det == "schedule_violation":
                causes.append((score, "out-of-hours activity coincides with the window"))
            elif det == "cross_modality":
                causes.append(
                    (
                        score,
                        "correlated signals disagree (e.g. rising CO2 with zero occupancy) — consistent with a ventilation or sensing issue",
                    )
                )
        if contact_note:
            causes.append((2.0, f"consistent with windows/doors open: {contact_note}"))
        if end.weekday() >= 5 or end.hour < 7 or start.hour >= 19:
            causes.append(
                (
                    1.0,
                    "the window falls outside typical occupied hours — systems often run a setback schedule then",
                )
            )
        if complaints:
            causes.append(
                (
                    1.5,
                    f"{len(complaints)} user report(s) were filed in the same window — occupants noticed something too",
                )
            )
        plant_notes, plant_figures = await self._plant_state(
            targets, start, end, room_series=merged, room_mean=window_mean
        )
        causes.extend(plant_notes)
        # Deduplicate before ranking. Live: "why is 5.16 so warm?" listed "a sensor reporting
        # gap overlaps the window" as explanations 1, 2, 3 AND 4 -- one finding per overlapping
        # episode, presented as four independent explanations. Repetition reads as corroboration
        # and it is the same fact four times.
        _seen_cause = set()
        _unique = []
        for _score, _text in causes:
            if _text in _seen_cause:
                continue
            _seen_cause.add(_text)
            _unique.append((_score, _text))
        causes = _unique
        causes.sort(key=lambda c: -c[0])

        # ── narration (numbers only from assembled evidence) ───────────────
        lines = [f"**What the data shows for {label}, {window_label}:**"]
        lines.append(f"- mean {modality}: **{window_mean:.1f}** over the window")
        # Initialised here, not inside the branch below. Reaching for it through `locals()` at
        # the return statement left the matched figures out of the payload whenever the branch
        # did not run -- and the narration had already printed an interval, so the numeric
        # guard suppressed the whole answer. A number in the prose and not in the payload is
        # exactly what that guard exists to catch; it was right and I had given it nothing.
        figures_matched: Dict[str, Any] = {}
        if prior_mean is not None:
            # V6-T41: the week-on-week line used to be two means subtracted, which reports a
            # 0.3-degree wobble in exactly the same words as a real shift. The matched
            # comparison pairs samples by hour-of-day and day-type, carries an interval, and
            # NAMES what it could not adjust for -- silently omitting an adjustment produces a
            # number indistinguishable from a properly adjusted one.
            # The raw means are DATA and are shown as such. The direction word used to be
            # asserted here -- "(higher now)" -- and the matched comparison immediately below
            # then said the difference was indistinguishable from noise. Two lines, one
            # contradicting the other, with the confident one first: a reader takes the
            # headline. The adjudication belongs to the matched line alone.
            lines.append(f"- same window a week earlier: {prior_mean:.1f}")
            try:
                from orchestrator.services.evidence.matched_comparison import (
                    compare as _matched,
                )

                prior_series = [
                    (t, v)
                    for t, v in _clean(merged)
                    if (start - timedelta(days=7)) <= t < (end - timedelta(days=7))
                ]
                current_series = [(t, v) for t, v in _clean(merged) if start <= t < end]
                matched = _matched(
                    current_series,
                    prior_series,
                    available_covariates=[],
                    # Declared for THIS estate: both move indoor conditions and neither is
                    # connected here, so both are stated rather than quietly ignored.
                    declared_confounders=["outdoor weather", "occupancy"],
                )
                if matched.effect is not None:
                    lines.append(f"- week-on-week, matched: {matched.describe(modality)}")
                    figures_matched = {
                        "effect": matched.effect,
                        "ci_low": matched.ci_low,
                        "ci_high": matched.ci_high,
                        "n_matched": matched.n_matched,
                        # The prose prints the share as a PERCENTAGE ("97% survived matching");
                        # carrying only the fraction 0.97 left "97" unbacked and the numeric
                        # guard suppressed the whole answer. Every number the narration prints
                        # has to be in the payload in the FORM it is printed.
                        "kept_share_pct": round(matched.kept_share * 100),
                        "unadjusted_for": matched.unadjusted_for,
                    }
                else:
                    figures_matched = {"declined": matched.reason}
            except Exception as _mc:  # pragma: no cover - a comparison must not cost the answer
                logger.debug(f"[diagnosis] matched comparison skipped: {_mc}")
                figures_matched = {}
        if peer_median is not None:
            lines.append(f"- rest of the building over the same window: median {peer_median:.1f}")
        if anomalies:
            kinds = sorted({a["event_type"].split(":", 1)[-1] for a in anomalies})
            lines.append(
                f"- {len(anomalies)} recorded anomaly episode(s) overlap ({', '.join(kinds)})"
            )
        lines.append("")
        if causes:
            lines.append(
                "**Most consistent explanations** (correlation in time, not proven cause):"
            )
            for i, (_s, text) in enumerate(causes[:4], 1):
                lines.append(f"{i}. {text}")
        else:
            lines.append(
                "**No coinciding evidence found** — no anomaly episodes, open windows or "
                "reports overlap that window. The readings alone don't explain it."
            )
        return {
            "success": True,
            "kind": "diagnosis",
            "modality": modality,
            "referent": label,
            "window": [start.isoformat(), end.isoformat()],
            "window_mean": round(window_mean, 2),
            "prior_week_mean": round(prior_mean, 2) if prior_mean is not None else None,
            # The matched figures ride in the payload so the numeric guard can back the
            # interval the narration prints.
            "matched_comparison": figures_matched,
            "peer_median": round(peer_median, 2) if peer_median is not None else None,
            "n_overlapping_anomalies": len(anomalies),
            "causes": [c[1] for c in causes[:4]],
            "plant": plant_figures,
            "source": "diagnosis (series + events store + reports + plant state)",
            "formatted_response": "\n".join(lines),
        }
