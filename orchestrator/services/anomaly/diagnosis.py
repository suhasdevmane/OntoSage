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
_MODALITY_WORDS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bfreez|\bcold\b|\bchilly\b|\bcool\b", re.I), "temperature", "low"),
    (re.compile(r"\bhot\b|\bboiling\b|\boverheat|\bwarm\b", re.I), "temperature", "high"),
    (re.compile(r"\bstuffy\b|\bco2\b|\bairless\b|\bventilat", re.I), "co2", "high"),
    (re.compile(r"\bloud\b|\bnoisy\b|\bnoise\b", re.I), "noise", "high"),
    (re.compile(r"\bdark\b|\bdim\b|\bgloomy\b", re.I), "illuminance", "low"),
    (re.compile(r"\bhumid\b|\bdamp\b|\bmuggy\b|\bdry\b", re.I), "humidity", "high"),
    (re.compile(r"\bdusty\b|\bsmoky\b|\bair quality\b|\bpm2\.?5\b", re.I), "pm25", "high"),
    (re.compile(r"\bbusy\b|\bcrowded\b|\bpacked\b", re.I), "occupancy", "high"),
]

WHY_RE = re.compile(
    r"^\s*why\b|\bwhy (?:was|is|were|are|did|does)\b|\bwhat(?:'s| is) (?:wrong|going on|the reason)\b",
    re.IGNORECASE,
)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def is_why_question(question: str) -> Optional[Tuple[str, str]]:
    """(modality, direction) when this is a diagnosable why-question, else None."""
    if not WHY_RE.search(question or ""):
        return None
    for pat, modality, direction in _MODALITY_WORDS:
        if pat.search(question):
            return modality, direction
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
            token = m.group(1).replace(" ", "").replace(".", "").lower()
            hits = [sc for sc in spaces if token in sc.label.replace("_", "").lower()]
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

    async def _series_for(self, targets, modality: str, start: datetime, end: datetime):
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
        series = await fetch_series(
            candidates, [modality], window_hours=window_hours, adapter_getter=self._adapter_getter
        )
        return series, candidates

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

        series, candidates = await self._series_for(targets, modality, start, end)
        target_uuids = [c.sensors[modality]["uuid"] for c in candidates]
        merged: List = []
        for uid in target_uuids:
            merged.extend(series.get(uid) or [])
        window_mean = self._window_mean(merged, start, end)
        prior_mean = self._window_mean(merged, start - timedelta(days=7), end - timedelta(days=7))

        if window_mean is None:
            return {
                "success": False,
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
        causes.sort(key=lambda c: -c[0])

        # ── narration (numbers only from assembled evidence) ───────────────
        lines = [f"**What the data shows for {label}, {window_label}:**"]
        lines.append(f"- mean {modality}: **{window_mean:.1f}** over the window")
        if prior_mean is not None:
            direction_word = "lower" if window_mean < prior_mean else "higher"
            lines.append(f"- same window a week earlier: {prior_mean:.1f} ({direction_word} now)")
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
            "peer_median": round(peer_median, 2) if peer_median is not None else None,
            "n_overlapping_anomalies": len(anomalies),
            "causes": [c[1] for c in causes[:4]],
            "source": "diagnosis (series + events store + reports)",
            "formatted_response": "\n".join(lines),
        }
