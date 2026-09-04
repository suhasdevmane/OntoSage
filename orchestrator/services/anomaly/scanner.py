# -*- coding: utf-8 -*-
"""
scanner.py — scheduled anomaly scan persisting episodes to the events store (V5-T19).

Anomalies become durable S2 records (kills D4): every scan sweeps the backed
points of the ACTIVE building, runs the deterministic detector suite, and
merges findings into `events` rows (event_type='anomaly:<detector>') with
STABLE episode IDs — an ongoing anomaly extends its row's end_dt instead of
minting a new ID per scan, so "anomalies this week" is a plain lookup and a
complaint can be joined to the episode that overlaps it.

Design decisions (recorded for the handoff):
- subject_uuid on an anomaly event is the SENSOR uuid (not the room pseudo-
  subject): detectors judge signals; the room is recoverable via the graph.
- Writes go through the events adapter's OWN aiomysql pool with code-authored
  parameterized SQL — execute_query stays SELECT-only because it guards
  LLM-generated SQL; this module never interpolates untrusted text.
- Building-agnostic: points come from the live capability schema, activity
  modalities are a fixed GENERIC set, peer groups are (modality, floor).
"""

from __future__ import annotations

import inspect
import json
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from orchestrator.services.anomaly import detectors as _detector_module
from orchestrator.services.anomaly.detectors import (
    FLOW_MODALITIES,
    AnomalyFinding,
    cross_modality_inconsistency,
    drift_vs_peers,
    dropout,
    minimum_flow_persistence,
    schedule_violation,
    seasonal_residual,
    spike,
    stuck,
)
from orchestrator.services.deliberation.synthetic_events import event_id
from shared.utils import get_logger

logger = get_logger(__name__)

#: modalities where out-of-hours activity is meaningful (generic, not per-building)
ACTIVITY_MODALITIES = {"occupancy", "illuminance", "energy_submeter", "water_flow"}
# water_flow appears in BOTH sets deliberately: schedule_violation catches a burst large
# enough to rival daytime demand, minimum_flow_persistence catches a trickle that never
# stops. Neither sees the other's failure, so dropping either would leave a real gap.

#: driver → response pairs for the cross-modality detector
CROSS_MODALITY_PAIRS = (("occupancy", "co2"),)

#: a finding whose episode end is within this window is still "open"
OPEN_GRACE = timedelta(hours=1)

#: a new finding within this gap of an existing episode EXTENDS it
MERGE_GRACE = timedelta(hours=2)


#: Samples fetched per sensor per sweep.
#:
#: Derived, not chosen: stuck's `min_hours` at the fastest publish cadence this system runs,
#: doubled so the frozen run is a MINORITY of the fetched history — a detector that sees only
#: the fault has no baseline to call it a fault against.
#:
#: THIS IS NOT THE LONGEST DETECTOR WINDOW, and the comment here said it was until
#: 2026-09-03. `seasonal_residual` requires 48 hours; covering that at 30 seconds would be
#: 11,520 samples per sensor across 1,859 sensors — 21M rows a sweep, which this cannot
#: afford. So the limit stays sized for the detectors it can serve and
#: `detectors_starved()` REPORTS the one it cannot, because the alternative is what
#: happened for as long as this scanner has existed: seasonal_residual returned [] on every
#: point, in silence, and the fault-injection harness scored it 0/1 and read it as broken.
#: A tradeoff that is stated is engineering; the same tradeoff unstated is a defect.
def _fastest_publish_cadence_s(default: float = 30.0) -> float:
    """The shortest interval anything actually writes at, read from the publisher.

    Restated as a constant `30.0` until 2026-09-04, and CAVEAT-405 then changed every
    cadence underneath it: the fastest is now 60s and most modalities are at 300s. The limit
    derived from 30s was therefore about DOUBLE what any detector needs, and the cost is not
    theoretical -- a sweep fetched ~2.7M rows and took 598 SECONDS, during which GraphDB
    slowed enough that the capability lane's 15s SPARQL timeout fired and 52 answers silently
    left the TTL-first path (CAVEAT-414/415).

    CAVEAT-401's own note said to re-check this whenever the cadence or a detector threshold
    changes. It changed and nothing re-checked, because the coupling lived in a comment
    rather than in code. Now it is read, so the two cannot drift apart again.

    The publisher is a separate build context and is not importable from here, so its map is
    read as data with a stated fallback -- a building whose publisher this cannot see keeps
    the old conservative value rather than silently shrinking its detectors' view.
    """
    import re as _re
    from pathlib import Path as _Path

    candidates = [
        _Path("/app/mysql-dummy-publish-dev/sensor_signal.py"),
        _Path(__file__).resolve().parents[3] / "mysql-dummy-publish-dev" / "sensor_signal.py",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            block = path.read_text(encoding="utf-8")
            start = block.index("CADENCE_S")
            values = [int(v) for v in _re.findall(r":\s*(\d+)\s*,", block[start : start + 900])]
            if values:
                return float(min(values))
        except Exception:  # pragma: no cover - a missing publisher is not an error here
            continue
    return default


#: Seconds between writes at the fastest-reporting modality, and the longest window any
#: detector requires. Their ratio is how many samples that window holds.
_FASTEST_CADENCE_S = _fastest_publish_cadence_s()
_LONGEST_DETECTOR_WINDOW_H = 6.0
_PER_UUID_LIMIT = int((_LONGEST_DETECTOR_WINDOW_H * 3600.0 / _FASTEST_CADENCE_S) * 2)


def detectors_starved(series_by_uuid: Dict[str, Any]) -> Dict[str, str]:
    """Which detectors cannot possibly fire on the history that was fetched, and why.

    A detector whose minimum-history requirement exceeds the span of every fetched series
    returns ``[]`` for every point — correctly, and in total silence. `seasonal_residual`
    declares ``min_history_hours=48.0`` while a sweep fetches roughly 24 hours, so it has
    never once been able to fire, and the fault-injection harness read that as a detector
    scoring 0/1.

    That is the same mistake as CAVEAT-401 wearing a different hat, and the same one this
    project has now made four times: a limit expressed in samples, a requirement expressed
    in hours, and nothing connecting them. ``_PER_UUID_LIMIT``'s own comment claims to be
    derived from "the longest detector window", and it is derived from stuck's 6 hours —
    the longest is 48.

    The requirement is read from each detector's signature BY NAME, so raising a threshold
    shows up here rather than becoming a silent no-op.
    """
    spans = []
    for series in series_by_uuid.values():
        if series and len(series) >= 2:
            try:
                first, last = series[0][0], series[-1][0]
                if isinstance(first, str):
                    first = datetime.fromisoformat(first)
                    last = datetime.fromisoformat(last)
                spans.append((last - first).total_seconds() / 3600.0)
            except Exception:  # pragma: no cover - a malformed stamp is not this job
                continue
    if not spans:
        return {}
    spans.sort()
    best = spans[-1]  # the most history ANY point has: nothing can beat it
    out: Dict[str, str] = {}
    for name in ("seasonal_residual", "stuck", "dropout", "spike", "drift_vs_peers"):
        fn = getattr(_detector_module, name, None)
        if fn is None:
            continue
        need = 0.0
        for param in ("min_history_hours", "min_hours"):
            found = inspect.signature(fn).parameters.get(param)
            if found is not None and isinstance(found.default, (int, float)):
                need = max(need, float(found.default))
        if need and best < need:
            out[name] = (
                f"needs {need:g}h of history; the longest series fetched spans "
                f"{best:.1f}h, so it cannot fire on any point this sweep"
            )
    return out


class AnomalyScanner:
    """One instance per active building; ``scan_once`` is re-entrant safe."""

    def __init__(
        self,
        building_id: str,
        namespace: str,
        sparql_exec: Optional[Callable] = None,
        adapter_getter: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.building_id = building_id
        self.namespace = namespace
        self._sparql = sparql_exec
        self._adapter_getter = adapter_getter

    # ── discovery + fetch ──────────────────────────────────────────────────

    async def _spaces(self):
        from orchestrator.services.deliberation.capability_schema import build_schema
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        sparql = self._sparql
        if sparql is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as sparql

        modalities = load_modalities(self.building_id)
        schema = await build_schema(self.building_id, self.namespace, sparql, modalities)
        return schema.spaces

    async def _fetch(self, spaces, window_hours: float):
        from orchestrator.services.deliberation.candidates import Candidate
        from orchestrator.services.deliberation.fetch import fetch_series

        candidates = []
        for sc in spaces:
            sensors = {
                m: {"uuid": h["uuid"], "stored_at": h["stored_at"]}
                for m, h in (sc.modalities or {}).items()
                if str(h.get("status", "")) == "present" and h.get("uuid") and h.get("stored_at")
            }
            if sensors:
                candidates.append(
                    Candidate(
                        space_iri=sc.space_iri, label=sc.label, floor=sc.floor, sensors=sensors
                    )
                )
        all_modalities = sorted({m for c in candidates for m in c.sensors})
        series_by_uuid = await fetch_series(
            candidates,
            all_modalities,
            window_hours=window_hours,
            # 600 samples is not a window; it is a window DIVIDED BY CADENCE, and the
            # cadence changed underneath it. At the dev publisher's 30-second interval 600
            # samples spans FIVE HOURS — shorter than stuck()'s own `min_hours=6.0`, so a
            # genuinely stuck sensor could not be detected at all through this sweep, and
            # worse: when every fetched sample fell inside the frozen run the historical
            # range was zero and stuck() correctly classified the signal as "flat by nature,
            # not by fault". Called directly against the same sensor with more history the
            # detector returns an 8.0-hour finding at score 1.339. The detector was right;
            # it was being handed a truncated view.
            #
            # Sized so the fetch clears the longest window any detector requires with room
            # for contrast on either side, at the fastest cadence this system publishes at.
            per_uuid_limit=_PER_UUID_LIMIT,
            adapter_getter=self._adapter_getter,
        )
        return candidates, series_by_uuid

    # ── detection ──────────────────────────────────────────────────────────

    def _detect(self, candidates, series_by_uuid) -> List[AnomalyFinding]:
        findings: List[AnomalyFinding] = []
        # per-point detectors + peer-group collection in one pass
        peer_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for cand in candidates:
            for modality, handle in cand.sensors.items():
                series = series_by_uuid.get(handle["uuid"]) or []
                if not series:
                    continue
                uid = handle["uuid"]
                findings += seasonal_residual(series, uid, modality)
                findings += stuck(series, uid, modality)
                findings += dropout(series, uid, modality)
                findings += spike(series, uid, modality)
                if modality in ACTIVITY_MODALITIES:
                    findings += schedule_violation(series, uid, modality)
                if modality in FLOW_MODALITIES:
                    # V6-T44: a slow leak is invisible by magnitude and obvious by
                    # persistence, so it needs its own detector rather than a threshold.
                    findings += minimum_flow_persistence(series, uid, modality)
                peer_groups.setdefault((modality, cand.floor), {})[uid] = series
        # drift vs the peer group (same modality + floor)
        for (modality, _floor), group in peer_groups.items():
            if len(group) < 4:  # target + >=3 peers
                continue
            for uid, series in group.items():
                peers = {u: s for u, s in group.items() if u != uid}
                findings += drift_vs_peers(series, peers, uid, modality)
        # cross-modality pairs within each space
        for cand in candidates:
            for driver, response in CROSS_MODALITY_PAIRS:
                dh, rh = cand.sensors.get(driver), cand.sensors.get(response)
                if not dh or not rh:
                    continue
                d_series = series_by_uuid.get(dh["uuid"]) or []
                r_series = series_by_uuid.get(rh["uuid"]) or []
                if d_series and r_series:
                    findings += cross_modality_inconsistency(
                        d_series, r_series, rh["uuid"], response
                    )
        return findings

    # ── persistence ────────────────────────────────────────────────────────

    async def _events_pool(self):
        adapter_getter = self._adapter_getter
        if adapter_getter is None:  # pragma: no cover - live wiring
            from orchestrator.services.adapters.registry import adapter_registry

            adapter_getter = adapter_registry.get
        adapter = adapter_getter("bldg:events_data")
        if adapter is None:
            return None
        return await adapter._ensure_pool()

    async def persist(self, findings: List[AnomalyFinding], now: datetime) -> Tuple[int, int]:
        """Merge findings into the events store; returns (inserted, extended)."""
        pool = await self._events_pool()
        if pool is None:
            logger.warning("[anomaly-scan] no events adapter — findings not persisted")
            return 0, 0
        inserted = extended = 0
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for f in findings:
                    etype = f"anomaly:{f.detector}"
                    status = "open" if f.end >= now - OPEN_GRACE else "done"
                    attrs = json.dumps(
                        {
                            "detector": f.detector,
                            "modality": f.modality,
                            "score": f.score,
                            "severity": f.severity,
                            "baseline": f.baseline,
                            "evidence": f.evidence,
                        },
                        default=str,
                    )
                    await cur.execute(
                        "SELECT event_id, end_dt FROM events "
                        "WHERE event_type=%s AND subject_uuid=%s AND end_dt >= %s "
                        "ORDER BY end_dt DESC LIMIT 1",
                        (etype, f.subject_uuid, f.start - MERGE_GRACE),
                    )
                    row = await cur.fetchone()
                    if row:
                        await cur.execute(
                            "UPDATE events SET end_dt=GREATEST(end_dt, %s), status=%s, attrs=%s "
                            "WHERE event_id=%s",
                            (f.end, status, attrs, row[0]),
                        )
                        extended += 1
                    else:
                        eid = event_id(self.building_id, etype, f.subject_uuid, f.start)
                        await cur.execute(
                            "INSERT IGNORE INTO events "
                            "(event_id, event_type, subject_uuid, start_dt, end_dt, status, attrs) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (eid, etype, f.subject_uuid, f.start, f.end, status, attrs),
                        )
                        inserted += int(cur.rowcount or 0)
            await conn.commit()
        return inserted, extended

    # ── the scan ───────────────────────────────────────────────────────────

    async def scan_once(
        self, window_hours: float = 72.0, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Sweep every backed point once; persist episodes; return a summary."""
        t0 = time.time()
        now = now or datetime.utcnow()
        spaces = await self._spaces()
        candidates, series_by_uuid = await self._fetch(spaces, window_hours)
        findings = self._detect(candidates, series_by_uuid)
        inserted, extended = await self.persist(findings, now)
        # V5-T23 — standing "alert me if…" subscriptions fire on NEW episodes
        # only (persist() reports how many were inserted this sweep).
        alerts = 0
        if inserted:
            try:
                alerts = await self._dispatch_subscriptions(findings, now)
            except Exception as exc:
                logger.warning(f"[anomaly-scan] subscription dispatch failed: {exc}")
        by_detector: Dict[str, int] = {}
        for f in findings:
            by_detector[f.detector] = by_detector.get(f.detector, 0) + 1
        starved = detectors_starved(series_by_uuid)
        summary = {
            "building_id": self.building_id,
            "points_scanned": len(series_by_uuid),
            "findings": len(findings),
            "by_detector": by_detector,
            # Detectors that could not fire on ANY point for want of history. Reported so a
            # zero is legible as "not run" rather than read as "found nothing".
            "detectors_starved": starved,
            "inserted": inserted,
            "extended": extended,
            "alerts_sent": alerts,
            "duration_ms": int((time.time() - t0) * 1000),
        }
        logger.info(f"[anomaly-scan] {summary}")
        return summary

    async def _dispatch_subscriptions(self, findings, now) -> int:
        """Deliver standing anomaly subscriptions for episodes found this sweep.

        Subscriptions live in Redis (written by the alert lane when a user says
        "tell me if a sensor goes dead"); with no store or no subscriptions the
        sweep is unaffected. Delivery de-dupes per (user, episode).
        """
        from orchestrator.services.anomaly.subscriptions import (
            AnomalySubscription,
            SubscriptionDispatcher,
        )

        subs = await self._load_subscriptions()
        if not subs:
            return 0
        episodes = [
            {
                "event_id": event_id(
                    self.building_id, f"anomaly:{f.detector}", f.subject_uuid, f.start
                ),
                "event_type": f"anomaly:{f.detector}",
                "subject_uuid": f.subject_uuid,
                "start_dt": f.start,
                "end_dt": f.end,
                "status": "open" if f.end >= now - OPEN_GRACE else "done",
                "attrs": {
                    "modality": f.modality,
                    "severity": f.severity,
                    "score": f.score,
                },
            }
            for f in findings
        ]
        delivered = await SubscriptionDispatcher(notifier=self._notify_subscriber).dispatch(
            subs, episodes
        )
        return len(delivered)

    async def _load_subscriptions(self) -> list:
        """Read anomaly subscriptions from Redis; [] when the store is absent."""
        from orchestrator.services.anomaly.subscriptions import AnomalySubscription

        try:
            from orchestrator.redis_manager import redis_manager

            raw = await redis_manager.get_cache("anomaly_subs")
        except Exception:
            return []
        out = []
        for item in raw or []:
            try:
                out.append(AnomalySubscription(**item))
            except (TypeError, ValueError):
                continue
        return out

    async def _notify_subscriber(self, sub, episode, text) -> None:
        """Dispatch through the building's configured channels (channels.yaml)."""
        try:
            from orchestrator.services.notification_service import (
                get_notification_service,
            )

            svc = get_notification_service(self.building_id)
            await svc.dispatch(
                title="OntoSage anomaly alert",
                message=text,
                severity=str((episode.get("attrs") or {}).get("severity", "info")),
                building_id=self.building_id,
                source="anomaly_subscription",
                extra={"user_id": sub.user_id, "episode_id": str(episode.get("event_id", ""))},
            )
        except Exception as exc:
            logger.info(f"[anomaly-subs] alert for {sub.user_id} (no channel dispatch): {exc}")


def join_complaints(
    anomaly_rows: List[Dict[str, Any]], complaints: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Time-overlap join: complaints ↔ anomaly episodes (V5-T19 step 3).

    Pure function over already-fetched rows (events live in MySQL, complaints
    in Postgres — the join happens here, not in either database). A complaint
    joined to zero episodes is the interesting class the plan calls
    'complaints where the data looks fine' — it is RETURNED with an empty
    match list, never dropped.
    """
    out = []
    for c in complaints:
        c_start = c.get("created_at")
        if c_start is None:
            continue
        c_end = c.get("resolved_at") or c_start
        matches = []
        for a in anomaly_rows:
            a_start, a_end = a.get("start_dt"), a.get("end_dt") or a.get("start_dt")
            if a_start is None:
                continue
            if a_start <= c_end + timedelta(hours=2) and a_end >= c_start - timedelta(hours=24):
                matches.append(a)
        out.append({"complaint": c, "anomalies": matches, "data_looks_fine": not matches})
    return out
