"""
plan_executor.py — deterministic execution of an admitted CQ-IR (V4-T19).

Composes the already-verified stages into one run:
  enumerate → fetch (per-UUID limits) → aggregate → [forecast top-K] → score

Everything numeric is code: aggregation is a windowed mean, the ranking is the
deterministic scorer. Forecasting is two-tier (V5-T12/T13): tier-1 ranks EVERY
candidate with a deterministic seasonal-naive profile (hour-of-week means, no
fitting — whole-building economics), then tier-2 refines only the top-K with
the ModelSelector adapter (hold-out MAE picks linear / exp-smoothing / ARIMA /
seasonal-naive; records carry model, 80/95 % CIs and backtest MAE). The
forecaster is injectable for tests — injected callables may return the legacy
``(value, model)`` tuple or the adapter's richer dict.

The outcome carries everything the dossier needs: per-cell evidence rows
(value, window, n_points, uuid, table), forecast records (model + horizon),
the coverage ledger, timings, and the deterministic plan hash that anchors the
provider-swap determinism proof.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from orchestrator.services.deliberation.candidates import (
    Candidate,
    CoverageLedger,
    GeometryInfo,
    enumerate_candidates,
)
from orchestrator.services.deliberation.capability_schema import (
    AdmissionResult,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.cqir import CQIR, TimeBasis
from orchestrator.services.deliberation.fetch import Series, fetch_series
from orchestrator.services.deliberation.scorer import (
    ScoreResult,
    load_anchors,
    score_candidates,
)
from shared.utils import get_logger

logger = get_logger(__name__)

#: candidates that reach the forecasting stage (plan: forecast only the top-K)
FORECAST_TOP_K = 5

Forecaster = Callable[[Series, float], Awaitable[Tuple[float, str]]]


@dataclass
class EvidenceCell:
    space_iri: str
    modality: str
    value: float
    basis: str  # 'window mean' | 'forecast mean (linear trend)'
    window_hours: float
    n_points: int
    uuid: str
    stored_at: str
    #: Timestamp of the newest reading behind `value`. Without it a recommendation cannot say
    #: WHEN it was true, and a snapshot sitting in a chat window reads as a standing fact
    #: (V6-T37). Carried as the raw string the store returned; parsing belongs to the reader.
    latest: str = ""


@dataclass
class ForecastRecord:
    space_iri: str
    modality: str
    model: str
    horizon_hours: float
    forecast_value: float
    history_points: int
    # V5-T12 — populated when the ModelSelector adapter produced the forecast
    ci80: Optional[Tuple[float, float]] = None
    ci95: Optional[Tuple[float, float]] = None
    backtest_mae: Optional[float] = None
    n_train: int = 0


@dataclass
class EventCheck:
    """V5-T25 — availability/booking evidence for one candidate."""

    space_iri: str
    kind: str  # 'free_window' | 'low_booking_pressure'
    free: Optional[bool] = None
    detail: str = ""  # e.g. 'booked 14:00–16:00' / 'booked 22% of next 7 days'
    window_hours: float = 0.0


@dataclass
class ExecutionOutcome:
    score: ScoreResult
    ledger: CoverageLedger
    candidates: List[Candidate]
    evidence: List[EvidenceCell] = field(default_factory=list)
    forecasts: List[ForecastRecord] = field(default_factory=list)
    event_checks: List[EventCheck] = field(default_factory=list)
    event_notes: List[str] = field(default_factory=list)
    #: plan + EXECUTION CONTEXT (candidate set, window, basis) — a provenance id
    #: for what was actually computed. It legitimately changes between runs on a
    #: live building, because the candidate set excludes currently-busy rooms.
    plan_hash: str = ""
    #: the REASONING PLAN alone (CQ-IR behavioural core). This is the determinism
    #: anchor: identical question -> identical fingerprint, whatever the data or
    #: the model was doing at the time. Surfaced because comparing plan_hash
    #: across runs measures the building's state, not the system's reasoning.
    plan_fingerprint: str = ""
    timings_ms: Dict[str, int] = field(default_factory=dict)


async def _linear_forecast(series: Series, horizon_hours: float) -> Tuple[float, str]:
    """Deterministic least-squares trend, extrapolated to the horizon midpoint."""
    values = [v for _, v in series]
    n = len(values)
    if n < 4:
        return values[-1] if values else 0.0, "last-value (history too short)"
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    # series cadence from count/window is unknown here; extrapolate by index
    # one horizon's worth of steps beyond the end, assuming uniform cadence
    steps_per_hour = max(1.0, n / max(1.0, horizon_hours))
    target_x = (n - 1) + steps_per_hour * horizon_hours / 2.0  # horizon midpoint
    return mean_y + slope * (target_x - mean_x), "linear trend"


def _tier1_point(series: Series, horizon_hours: float) -> Tuple[float, str]:
    """Cheap deterministic forecast for shortlist ranking: seasonal profile,
    falling back to the last-value/linear ladder when history is too thin."""
    try:
        from orchestrator.services.forecasting.models.seasonal_naive_forecaster import (
            seasonal_naive_point,
        )

        point = seasonal_naive_point(series, horizon_hours)
        if point is not None:
            return point
    except Exception as exc:  # never let tier-1 sink the whole plan
        logger.warning(f"[executor] tier-1 seasonal point failed: {exc}")
    values = [v for _, v in series]
    return (values[-1] if values else 0.0), "last-value (history too short)"


def _normalize_forecast(result) -> Dict:
    """Accept ``(value, model)`` tuples (legacy/injected) or adapter dicts."""
    if isinstance(result, dict):
        return {
            "value": float(result.get("value", 0.0)),
            "model": str(result.get("model", "unknown")),
            "ci80": result.get("ci80"),
            "ci95": result.get("ci95"),
            "backtest_mae": result.get("backtest_mae"),
            "n_train": int(result.get("n_train") or 0),
        }
    value, model = result
    return {
        "value": float(value),
        "model": str(model),
        "ci80": None,
        "ci95": None,
        "backtest_mae": None,
        "n_train": 0,
    }


async def _default_forecaster(series: Series, horizon_hours: float):
    """ModelSelector adapter first (model + CIs + hold-out MAE); deterministic
    seasonal/linear ladder when the scientific stack declines or fails."""
    try:
        from orchestrator.services.forecasting.adapter import model_selector_forecast

        rich = await model_selector_forecast(series, horizon_hours)
        if rich is not None:
            return rich
    except Exception as exc:
        logger.warning(f"[executor] adapter unavailable, using fallback ladder: {exc}")
    point = _tier1_point(series, horizon_hours)
    if "history too short" in point[1]:
        return await _linear_forecast(series, horizon_hours)
    return point


async def _event_availability(
    cqir: CQIR,
    schema: BuildingCapabilitySchema,
    candidates: List[Candidate],
    adapter_getter,
) -> Tuple[Dict[str, EventCheck], List[str]]:
    """{space_iri: EventCheck} for the requested event criteria (V5-T25).

    Admission honesty: with no events adapter the criteria CANNOT be verified —
    the caller keeps every candidate and states that in the dossier instead of
    silently pretending everything is free.
    """
    from datetime import datetime, timedelta

    from orchestrator.services.datasource_registry import derive_point_uuid

    checks: Dict[str, EventCheck] = {}
    notes: List[str] = []
    free_crit = next((e for e in cqir.event_criteria if e.kind == "free_window"), None)
    pressure = any(e.kind == "low_booking_pressure" for e in cqir.event_criteria)
    if not (free_crit or pressure):
        return checks, notes
    if adapter_getter is None:  # pragma: no cover - live wiring
        from orchestrator.services.adapters.registry import adapter_registry

        adapter_getter = adapter_registry.get
    adapter = adapter_getter("bldg:events_data")
    builder = getattr(adapter, "build_overlap_window", None) if adapter else None
    if builder is None:
        notes.append(
            "availability was requested but this building has no booking/event store — "
            "candidates are ranked WITHOUT availability filtering"
        )
        return checks, notes
    subject_by_iri = {
        c.space_iri: derive_point_uuid(schema.building_id, "evt_subject", c.label)
        for c in candidates
    }
    iri_by_subject = {v: k for k, v in subject_by_iri.items()}
    now = datetime.utcnow()

    async def _overlaps(start, end):
        sql = builder(
            "booking",
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            subject_uuids=sorted(iri_by_subject),
        )
        if not sql:
            return []
        result = await adapter.execute_query(sql)
        return list(result.data or []) if getattr(result, "success", False) else []

    if free_crit:
        rows = await _overlaps(now, now + timedelta(hours=free_crit.hours))
        busy: Dict[str, str] = {}
        for row in rows:
            subj = str(row.get("subject_uuid") or (row[2] if not isinstance(row, dict) else ""))
            iri = iri_by_subject.get(subj)
            if not iri:
                continue
            s = row.get("start_dt") if isinstance(row, dict) else row[3]
            e = row.get("end_dt") if isinstance(row, dict) else row[4]
            busy[iri] = f"booked {str(s)[11:16]}–{str(e)[11:16]}"
        for iri in subject_by_iri:
            checks[iri] = EventCheck(
                space_iri=iri,
                kind="free_window",
                free=iri not in busy,
                detail=busy.get(iri, f"no booking in the next {free_crit.hours:g}h"),
                window_hours=free_crit.hours,
            )
    if pressure:
        rows = await _overlaps(now, now + timedelta(days=7))
        seconds: Dict[str, float] = {}
        for row in rows:
            subj = str(row.get("subject_uuid") if isinstance(row, dict) else row[2])
            iri = iri_by_subject.get(subj)
            if not iri:
                continue
            s = row.get("start_dt") if isinstance(row, dict) else row[3]
            e = row.get("end_dt") if isinstance(row, dict) else row[4]
            try:
                seconds[iri] = seconds.get(iri, 0.0) + max(
                    0.0, (e - s).total_seconds() if e and s else 0.0
                )
            except TypeError:
                continue
        for iri in subject_by_iri:
            frac = seconds.get(iri, 0.0) / (7 * 24 * 3600.0)
            checks.setdefault(
                iri,
                EventCheck(space_iri=iri, kind="low_booking_pressure"),
            )
            existing = checks[iri]
            pressure_txt = f"booked {round(frac * 100)}% of the next 7 days"
            existing.detail = (
                f"{existing.detail}; {pressure_txt}" if existing.detail else pressure_txt
            )
    return checks, notes


async def execute(
    cqir: CQIR,
    admission: AdmissionResult,
    schema: BuildingCapabilitySchema,
    geometry: Optional[Dict[str, GeometryInfo]] = None,
    adapter_getter=None,
    forecaster: Optional[Forecaster] = None,
) -> ExecutionOutcome:
    """Run the admitted constraint program end-to-end, deterministically."""
    forecaster = forecaster or _default_forecaster
    timings: Dict[str, int] = {}
    modalities = [c.modality for c in cqir.constraints]
    # Standards bands, overlaid with this building's own calibration where it
    # declares one (CAVEAT-162). Resolved ONCE so the preliminary forecast rank
    # and the final rank cannot be scored against different bands.
    _anchors = load_anchors(schema.building_id)

    t0 = time.time()
    candidates, ledger = enumerate_candidates(cqir, admission, schema, geometry)
    timings["enumerate_ms"] = int((time.time() - t0) * 1000)

    # V5-T25: availability filter BEFORE the expensive fetch — a booked room is
    # out no matter how quiet it is, and the exclusion is ledger-visible.
    event_checks: List[EventCheck] = []
    event_notes: List[str] = []
    if cqir.event_criteria:
        t0 = time.time()
        checks_by_iri, event_notes = await _event_availability(
            cqir, schema, candidates, adapter_getter
        )
        event_checks = list(checks_by_iri.values())
        busy_iris = {
            i for i, ch in checks_by_iri.items() if ch.kind == "free_window" and ch.free is False
        }
        if busy_iris:
            from orchestrator.services.deliberation.candidates import LedgerEntry

            for cand in candidates:
                if cand.space_iri in busy_iris:
                    ledger.excluded.append(
                        LedgerEntry(
                            space_iri=cand.space_iri,
                            label=cand.label,
                            reason=f"{checks_by_iri[cand.space_iri].detail} — not free for the "
                            f"requested {checks_by_iri[cand.space_iri].window_hours:g}h window",
                        )
                    )
            candidates = [c for c in candidates if c.space_iri not in busy_iris]
            ledger.considered = len(candidates)
        timings["events_ms"] = int((time.time() - t0) * 1000)

    # window selection by time basis: NOW ranks on the last hour's mean but
    # fetches more so short outages don't blank the field; FORECAST needs a
    # longer history for a meaningful trend.
    if cqir.time.basis == TimeBasis.FORECAST:
        fetch_window = 72.0
        agg_window_note = "forecast"
    elif cqir.time.basis == TimeBasis.WINDOW:
        fetch_window = float(cqir.time.window_hours or 24.0)
        agg_window_note = "window mean"
    else:
        fetch_window = 24.0
        agg_window_note = "recent mean (last hour, else latest window)"

    t0 = time.time()
    series_by_uuid = await fetch_series(
        candidates, modalities, window_hours=fetch_window, adapter_getter=adapter_getter
    )
    timings["fetch_ms"] = int((time.time() - t0) * 1000)

    values: Dict[str, Dict[str, float]] = {}
    evidence: List[EvidenceCell] = []
    per_candidate_series: Dict[Tuple[str, str], Series] = {}
    for cand in candidates:
        for modality in modalities:
            handle = cand.sensors.get(modality)
            if not handle:
                continue
            series = series_by_uuid.get(handle["uuid"]) or []
            if not series:
                continue
            per_candidate_series[(cand.space_iri, modality)] = series
            if cqir.time.basis == TimeBasis.NOW:
                # mean of the newest sixth of the window ≈ the last few hours
                tail = series[-max(1, len(series) // 6) :]
                value = sum(v for _, v in tail) / len(tail)
                n_points = len(tail)
            else:
                value = sum(v for _, v in series) / len(series)
                n_points = len(series)
            values.setdefault(cand.space_iri, {})[modality] = round(value, 3)
            evidence.append(
                EvidenceCell(
                    space_iri=cand.space_iri,
                    modality=modality,
                    value=round(value, 3),
                    basis=agg_window_note,
                    window_hours=fetch_window,
                    n_points=n_points,
                    uuid=handle["uuid"],
                    stored_at=handle["stored_at"],
                    latest=str(series[-1][0]) if series else "",
                )
            )

    forecasts: List[ForecastRecord] = []
    if cqir.time.basis == TimeBasis.FORECAST:
        # tier-1 (V5-T13): deterministic seasonal-naive point for EVERY
        # candidate — the shortlist is chosen on predicted values, not on
        # history means (a room that is cool now but heats up tomorrow must
        # not make the cut on its history)
        t0 = time.time()
        horizon = float(cqir.time.horizon_hours or 24.0)
        tier1_values: Dict[str, Dict[str, float]] = {}
        for cand in candidates:
            for modality in modalities:
                series = per_candidate_series.get((cand.space_iri, modality))
                if not series:
                    continue
                point, _ = _tier1_point(series, horizon)
                tier1_values.setdefault(cand.space_iri, {})[modality] = round(point, 3)
        prelim = score_candidates(cqir, candidates, tier1_values or values, anchors=_anchors)
        shortlist = {s.space_iri for s in prelim.ranked[:FORECAST_TOP_K]}
        # tier-2 (V5-T12): the injected/default forecaster refines the top-K;
        # the default runs ModelSelector (hold-out MAE, CIs) per series
        for cand in candidates:
            if cand.space_iri not in shortlist:
                continue
            for modality in modalities:
                series = per_candidate_series.get((cand.space_iri, modality))
                if not series:
                    continue
                rec = _normalize_forecast(await forecaster(series, horizon))
                values[cand.space_iri][modality] = round(rec["value"], 3)
                # V5-T14: widen bands by the building's MEASURED coverage
                # deficit (T17 graded raw bands at ~2x over-confident);
                # uncalibrated modalities pass through untouched
                ci80, ci95 = rec["ci80"], rec["ci95"]
                try:
                    from orchestrator.services.forecasting.calibration import (
                        band_factors,
                        calibrate_band,
                    )

                    f80, f95 = band_factors(schema.building_id, modality, horizon)
                    ci80 = calibrate_band(ci80, rec["value"], f80)
                    ci95 = calibrate_band(ci95, rec["value"], f95)
                except Exception as _cal_err:
                    logger.debug(f"[executor] band calibration skipped: {_cal_err}")
                forecasts.append(
                    ForecastRecord(
                        space_iri=cand.space_iri,
                        modality=modality,
                        model=rec["model"],
                        horizon_hours=horizon,
                        forecast_value=round(rec["value"], 3),
                        history_points=len(series),
                        ci80=ci80,
                        ci95=ci95,
                        backtest_mae=rec["backtest_mae"],
                        n_train=rec["n_train"],
                    )
                )
        # candidates outside the shortlist keep history values; the dossier's
        # forecast records make the two bases distinguishable
        candidates = [c for c in candidates if c.space_iri in shortlist] or candidates
        timings["forecast_ms"] = int((time.time() - t0) * 1000)

    t0 = time.time()
    score = score_candidates(cqir, candidates, values, anchors=_anchors)
    timings["score_ms"] = int((time.time() - t0) * 1000)

    plan_hash = hashlib.sha256(
        (
            cqir.plan_fingerprint()
            + "|"
            + ",".join(sorted(c.space_iri for c in candidates))
            + f"|{fetch_window}|{cqir.time.basis.value}"
        ).encode("utf-8")
    ).hexdigest()[:16]

    logger.info(
        f"[executor] plan={plan_hash} candidates={len(candidates)} "
        f"ranked={len(score.ranked)} timings={timings}"
    )
    return ExecutionOutcome(
        score=score,
        ledger=ledger,
        candidates=candidates,
        evidence=evidence,
        forecasts=forecasts,
        event_checks=event_checks,
        event_notes=event_notes,
        plan_hash=plan_hash,
        plan_fingerprint=cqir.plan_fingerprint(),
        timings_ms=timings,
    )
