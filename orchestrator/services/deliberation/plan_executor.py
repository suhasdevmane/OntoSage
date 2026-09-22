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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

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
from orchestrator.services.requested_interval import store_now
from shared.utils import get_logger

logger = get_logger(__name__)

#: candidates that reach the forecasting stage (plan: forecast only the top-K)
FORECAST_TOP_K = 5

#: How many candidates this lane will fetch series for before it declines as too broad
#: (V7-T24).
#:
#: Measured 2026-08-31: "show me live setpoints versus measured temperature for all zones
#: on floor 5" enumerated the WHOLE building — 522 series across 8 tables — and died on
#: the 120 s workflow timeout, 121 s after the user asked. Sixteen of the 1,580 baseline
#: questions end that way.
#:
#: The cap declines rather than truncating. A "which rooms" answer computed over an
#: arbitrary slice of the candidates is a wrong answer that looks right, and this project
#: guards hardest against exactly that; a decline naming the narrower question costs the
#: user one second instead of two minutes and tells them what to ask.
#:
#: Sized to sit above a typical floor and well below a whole building. It is a fetch
#: budget rather than a property of any one building — a floor-scoped question stays
#: untouched wherever it is asked, and a building large enough to exceed it on one floor
#: gets the decline, which is the honest outcome for a question that genuinely cannot be
#: read inside a request.
MAX_FETCH_CANDIDATES = 120

#: The budget in the unit the fetch actually pays: ROWS (WB-04, 2026-09-15).
#:
#: A space count cannot tell a "right now" question — which needs the last few readings of
#: each series — from a three-day trend over the same spaces. Measured on the demo building:
#: every floor instrumented and live, yet "where's the coolest place to work in the
#: building?" declined at 234 spaces because the lane fetched 24 h × 500 rows per series to
#: use the newest sixth of it. Sized by rows, a NOW ranking over 234 spaces × 4 modalities ×
#: 90 rows is 84k rows and answers; a multi-day building-wide window still declines.
#: Raised to 750k (WB-12/20) so a building-wide part-of-day ranking over six criteria
#: (234 spaces × 6 × 500 rows ≈ 702k) is read. Windows longer than 500 rows per series are
#: still TRUNCATED to their newest rows by the per-series limit — CAVEAT-578, open.
MAX_FETCH_ROWS = 750_000

#: Hard ceiling regardless of rows, so a pathological graph cannot fan a request out without
#: bound. Well above any single building's room count seen here.
MAX_FETCH_SPACES_ABSOLUTE = 800

#: "Right now" needs recent readings only: 3 h covers short outages; 90 rows per series is
#: 1.5 h at one-minute cadence, and the scorer uses the newest sixth of whatever returns.
NOW_WINDOW_HOURS = 3.0
NOW_PER_UUID_LIMIT = 90
DEFAULT_PER_UUID_LIMIT = 500


def fetch_plan(basis: Any, window_hours: Optional[float], n_candidates: int, n_modalities: int):
    """(window_hours, per_uuid_limit, estimated_rows) for a deliberation fetch."""
    if basis == TimeBasis.NOW:
        hours, limit = NOW_WINDOW_HOURS, NOW_PER_UUID_LIMIT
    elif basis == TimeBasis.FORECAST:
        hours, limit = 72.0, DEFAULT_PER_UUID_LIMIT
    else:
        hours = float(window_hours or 24.0)
        # CAVEAT-578: the WHOLE window at one-minute cadence, where the row budget allows. The
        # limit used to be min(500, hours*60), so a 24 h or "yesterday" mean was the newest
        # ~8.3 h of it under a "mean over" label. A short window never asks for more than it
        # can hold.
        limit = int(min(MAX_WINDOW_PER_UUID, max(60, hours * 60)))
        if n_candidates * max(1, n_modalities) * limit > MAX_FETCH_ROWS:
            # Too wide to read whole: fall back to the old per-series read. The adapter keeps
            # the LATEST n rows, so the answer discloses what each mean covered
            # (window_coverage_note) rather than presenting it as the whole window (WB-12).
            limit = min(limit, DEFAULT_PER_UUID_LIMIT)
    return hours, limit, n_candidates * max(1, n_modalities) * limit


#: Three days at one-minute cadence — the longest window read whole per series.
MAX_WINDOW_PER_UUID = 4320


def window_coverage_note(
    series_by_uuid: Dict[str, Series],
    limit: int,
    window_start: str,
    window_hours: float,
    tz_name: Optional[str] = None,
) -> Optional[str]:
    """Say so when a window mean was computed from only the newest part of the window.

    A series that returned exactly ``limit`` rows AND whose first reading is well after the
    window opened was cut by the per-series read, not by the data. None when every series
    covers its window.
    """
    from datetime import datetime, timedelta

    from orchestrator.services.requested_interval import to_local

    try:
        opened = datetime.fromisoformat(str(window_start)[:19])
    except ValueError:
        return None
    slack = timedelta(hours=max(0.5, window_hours * 0.1))
    cut: List[datetime] = []
    for series in series_by_uuid.values():
        if len(series) < limit or not series:
            continue
        try:
            first = datetime.fromisoformat(str(series[0][0])[:19])
        except ValueError:
            continue
        if first > opened + slack:
            cut.append(first)
    if not cut:
        return None
    earliest = to_local(min(cut), tz_name).strftime("%H:%M")
    return (
        f"**Partial window.** {len(cut)} of {len(series_by_uuid)} sensor series hold more "
        f"readings than one request reads, so their means use the newest {limit} readings "
        f"(from about {earliest} building time), not the whole {window_hours:g} h asked for."
    )


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
    #: Sentences naming values that were dropped because they cannot be a reading of the
    #: quantity they were filed under. Carried rather than folded into the prose, so the
    #: dossier and the answer say the same thing and a reader can tell a filtered ranking
    #: from an unfiltered one.
    impossible_readings: List[str] = field(default_factory=list)
    #: Sentences naming criteria whose readings run past the end of the range they are
    #: scored against, so that criterion cannot separate the spaces shown.
    band_notes: List[str] = field(default_factory=list)
    #: The whole answer, when this lane must not answer at all. A ranking of spaces is an
    #: answer to "which space"; handed a question about something else — a ROUTE — it would
    #: put real numbers behind the wrong question. The dossier renders this instead of a
    #: ranking, and nothing is fetched.
    refusal: str = ""


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
    # The STORES' clock (UTC). Bookings are generated from utcnow() and read on a +00:00
    # session. From 2026-09-12 to 2026-09-15 this used building-local time on the false
    # premise that bookings were local (BUG-518, withdrawn), which displaced the overlap
    # window by the zone's offset — the exact error it claimed to fix.
    now = store_now()

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


def _evidence_policy(building_id: str) -> str:
    """How this building wants evidence origin to affect an answer.

    Declared in `building.yaml` under `provenance.evidence_policy`:

        all_connected_readings  every attached reading is authoritative; an answer does
                                not distinguish simulated from measured (DEFAULT)
        measured_only           a simulated candidate is excluded before ranking

    Defaults to `all_connected_readings` on purpose. A building whose synthetic points
    stand in for instruments not yet connected is answering correctly when it reports
    them; refusing would say "I cannot tell you about that floor" about a floor whose
    data is present. A deployment where someone ACTS on the answer sets `measured_only`,
    and the machinery is already there.

    Unreadable config yields the default rather than an exception — a malformed YAML key
    must not decide a ranking.
    """
    try:
        from orchestrator.services.building_context import _load_building_yaml

        cfg = _load_building_yaml(building_id) or {}
        block = cfg.get("provenance") or {}
        value = str(block.get("evidence_policy") or "").strip().lower()
        return (
            value
            if value in ("all_connected_readings", "measured_only")
            else "all_connected_readings"
        )
    except Exception:  # pragma: no cover - config is best-effort by design
        return "all_connected_readings"


#: A question about HOW TO GET SOMEWHERE, which this lane must not answer by ranking rooms.
#:
#: Row 61 of the 2026-09-17 stakeholder read: "I need a step-free route to supervision that
#: avoids the busiest and noisiest areas around class changeover. Which verified route should
#: I take?" was answered "**Best match: Room 5.22 — Academic Office**", with "'step-free
#: route' isn't a sensed modality here — ignored" printed in the assumptions. Every number in
#: it was real and the question it answered was not the one asked.
_ROUTE_QUESTION_RE = re.compile(
    r"\broutes?\b|\bwayfinding\b|\bdirections\b|\bhow (?:do|can|should) i get (?:to|from)\b",
    re.IGNORECASE,
)

#: What the reader is told instead. It names what the building DOES record about getting
#: around, so the decline is a place to go next rather than a dead end — and it names no
#: sensor, policy or identifier.
ROUTE_REFUSAL = (
    "**You asked about a route, and I answer by comparing spaces — so I won't hand you a "
    "room instead.** Sensors record the conditions inside a space; they don't record how "
    "you travel between spaces, and ranking rooms on how quiet or how busy they are would "
    "answer a different question from the one you asked.\n\n"
    "What this building keeps about getting around is held separately: the step-free ways "
    "between two places, the lifts they depend on and whether those are in service. Name "
    "the two places — where you are and where you need to be — and the answer has to come "
    "from those records, not from readings."
)


def route_question(query: str) -> bool:
    """True when the question asks for a way THROUGH the building, not a space in it."""
    return bool(_ROUTE_QUESTION_RE.search(query or ""))


#: How many ranked spaces the answer shows. The out-of-band check reads the same ones the
#: reader sees, because a note about a figure nobody is shown explains nothing.
_SHOWN_RANKS = 3


def _out_of_band_notes(score, anchors) -> List[str]:
    """Say when a shown criterion runs past the range the same answer scores it against.

    Row 58 of the stakeholder read offered three rooms, quoted "the 0-8 band" in its own
    assumptions, and printed occupancy readings of about 24 beside them. Every utility had
    saturated at the end of the band, so the order between those rooms came from the
    tie-break and carried no meaning — and nothing in the answer said so. The reader saw a
    recommendation.

    Reported, not repaired. The band is the right band and the reading is the right
    reading; what is wrong is presenting an order the band cannot support. A reader told
    that a criterion is off the end of its scale can weigh the rest of the answer, which
    is exactly what the silent version denied them.
    """
    notes: List[str] = []
    shown = list(getattr(score, "ranked", []) or [])[:_SHOWN_RANKS]
    if len(shown) < 2:
        return notes  # nothing is being ordered, so nothing is being ordered wrongly
    modalities = sorted({c.modality for s in shown for c in (s.criteria or [])})
    for modality in modalities:
        anchor = (anchors or {}).get(modality)
        if anchor is None:
            continue
        values = [
            c.value
            for s in shown
            for c in (s.criteria or [])
            if c.modality == modality and c.value is not None
        ]
        if not values or not all(v < anchor.lo or v > anchor.hi for v in values):
            continue
        end = "below" if values[0] < anchor.lo else "above"
        # WHAT THE ORDER THEN RESTS ON, which is the part the reader can act on. With
        # another criterion in play the ranking still means something; with only this one
        # it does not, and saying "the order comes from the others" when there are no
        # others would be the same confident nothing this note exists to replace.
        rest = (
            "the order between them comes from the other things you asked for"
            if len(modalities) > 1
            else "the order between them is not something these readings support"
        )
        notes.append(
            f"**Every {modality} reading above sits {end} the {anchor.lo:g} to "
            f"{anchor.hi:g} range used to weigh it**, so on that count these spaces are "
            f"all at the same end of the scale and {rest}."
        )
    return notes


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

    # A ROUTE IS NOT A SPACE. Checked before anything is enumerated or fetched: there is no
    # ranking of rooms that answers it, so computing one would only make the wrong answer
    # look expensive.
    if route_question(cqir.raw_query):
        logger.info("[deliberate] route question — declining rather than ranking spaces")
        return ExecutionOutcome(
            score=ScoreResult(ranked=[], excluded=[]),
            ledger=CoverageLedger(),
            candidates=[],
            refusal=ROUTE_REFUSAL,
        )

    timings: Dict[str, int] = {}
    modalities = [c.modality for c in cqir.constraints]
    # Standards bands, overlaid with this building's own calibration where it
    # declares one (CAVEAT-162). Resolved ONCE so the preliminary forecast rank
    # and the final rank cannot be scored against different bands.
    _anchors = load_anchors(schema.building_id)

    t0 = time.time()
    candidates, ledger = enumerate_candidates(cqir, admission, schema, geometry)
    timings["enumerate_ms"] = int((time.time() - t0) * 1000)

    # Too broad to fetch: decline NOW rather than time out in two minutes (V7-T24).
    #
    # Truncating instead would be worse than either. A "which rooms" answer computed over
    # an arbitrary slice of the candidates is wrong in a way that looks right, and the
    # reader has no way to tell — so the question is handed back with the narrowing that
    # would make it answerable, which the user can act on immediately.
    _plan_hours, _plan_limit, _plan_rows = fetch_plan(
        cqir.time.basis, cqir.time.window_hours, len(candidates), len(modalities)
    )
    if len(candidates) > MAX_FETCH_SPACES_ABSOLUTE or _plan_rows > MAX_FETCH_ROWS:
        from orchestrator.services.deliberation.candidates import LedgerEntry

        floors = ", ".join(schema.floors[:8]) or "the building's floors"
        ledger.excluded.append(
            LedgerEntry(
                space_iri="*",
                label="all in scope",
                reason=(
                    f"question spans {len(candidates)} spaces (~{_plan_rows:,} rows to read), "
                    f"above the {MAX_FETCH_ROWS:,}-row fetch budget"
                ),
            )
        )
        logger.info(
            f"[deliberate] declining as too broad: {len(candidates)} candidates, "
            f"~{_plan_rows} rows > {MAX_FETCH_ROWS}"
        )
        return ExecutionOutcome(
            score=ScoreResult(ranked=[], excluded=[]),
            ledger=ledger,
            candidates=[],
            event_notes=[
                f"That question covers {len(candidates)} spaces — more than I can read "
                f"within one request. Narrow it to a floor ({floors}) or to a named room "
                "and I can answer it directly. I would rather say that than answer from "
                "part of the building without telling you which part."
            ],
            timings_ms=timings,
        )

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
    # V12-08 — when the question named a calendar day the interval was ALREADY RESOLVED,
    # once, at compile time. It is passed through verbatim; nothing here re-derives it.
    fetch_start = fetch_end = None
    # WB-04: the window and per-series limit come from the same plan the budget was checked
    # against, so what is fetched is what was estimated.
    fetch_window = _plan_hours
    if cqir.time.basis == TimeBasis.FORECAST:
        agg_window_note = "forecast"
    elif cqir.time.basis == TimeBasis.WINDOW:
        agg_window_note = "window mean"
        if cqir.time.is_resolved_interval:
            fetch_start, fetch_end = cqir.time.resolved_start, cqir.time.resolved_end
            # BUG-588: the interval is in store time (UTC); the day it names is the building's.
            # A BST "yesterday" starts at 23:00 UTC the day before, so fetch_start[:10] labelled
            # 14 September's mean "mean over 2026-09-13".
            try:
                from datetime import datetime as _dt

                from orchestrator.services.requested_interval import building_tz, to_local

                _day = to_local(_dt.fromisoformat(str(fetch_start)[:19]), building_tz()).date()
                agg_window_note = f"mean over {_day.isoformat()}"
            except Exception:
                agg_window_note = f"mean over {fetch_start[:10]}"
    else:
        agg_window_note = "recent mean (last readings)"

    t0 = time.time()
    series_by_uuid = await fetch_series(
        candidates,
        modalities,
        window_hours=fetch_window,
        adapter_getter=adapter_getter,
        start=fetch_start,
        end=fetch_end,
        per_uuid_limit=_plan_limit,
    )
    timings["fetch_ms"] = int((time.time() - t0) * 1000)
    _coverage_note: Optional[str] = None
    if cqir.time.basis == TimeBasis.WINDOW:
        try:
            from datetime import timedelta

            from orchestrator.services.requested_interval import STAMP, building_tz

            _opened = fetch_start or (store_now() - timedelta(hours=fetch_window)).strftime(STAMP)
            _coverage_note = window_coverage_note(
                series_by_uuid, _plan_limit, _opened, float(fetch_window), building_tz()
            )
        except Exception as exc:  # the disclosure must never cost the answer
            logger.debug(f"[executor] window coverage check skipped: {exc}")

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

    # ── A NUMBER THAT CANNOT BE A READING IS NOT EVIDENCE ───────────────────
    #
    # Run-3 row 99 (2026-09-17) recommended a room to a visitor and showed its evidence as
    # `occupancy: -7.719, co2: -260.986`. Minus seven people and minus 261 ppm of carbon
    # dioxide. Both came from the tier-2 forecaster: a least-squares trend on a falling
    # series extrapolates straight through zero, and nothing between the model and the
    # answer asked whether the result could be a quantity at all.
    #
    # Checked HERE, at the point the value is selected, rather than in the prose: by the
    # time it is a sentence it has already been scored, ranked and turned into a
    # recommendation. Both bases are covered because both reach `values` -- the window
    # mean above and the forecast that overwrites it.
    #
    # Excluded, counted and NAMED. Dropping it silently would leave the ranking looking
    # authoritative over whatever survived, which is the failure this guards against; and
    # the criterion is then simply absent, so the scorer renormalizes the remaining weights
    # and records a data gap, exactly as it does for a sensor that returned nothing.
    impossible_readings: List[str] = []
    try:
        from orchestrator.services.physical_bands import (
            Implausible,
            band_for_modality,
            excluded_sentence,
        )

        _cand_of = {c.space_iri: c for c in candidates}
        _label_of = {c.space_iri: (c.label or "") for c in candidates}
        _bad: List[Implausible] = []
        for _iri in list(values.keys()):
            for _modality in list(values[_iri].keys()):
                _band = band_for_modality(_modality, schema.building_id)
                _value = values[_iri][_modality]
                if _band is None or _band.holds(float(_value)):
                    continue
                _handle = (getattr(_cand_of.get(_iri), "sensors", {}) or {}).get(_modality) or {}
                _bad.append(
                    Implausible(
                        uuid=str(_handle.get("uuid") or ""),
                        value=float(_value),
                        band=_band,
                        label=f"{_label_of.get(_iri) or _iri} {_modality}",
                    )
                )
                values[_iri].pop(_modality, None)
        if _bad:
            _gone = {(i.label) for i in _bad}
            evidence = [
                e
                for e in evidence
                if f"{_label_of.get(e.space_iri) or e.space_iri} {e.modality}" not in _gone
            ]
            forecasts = [
                f
                for f in forecasts
                if f"{_label_of.get(f.space_iri) or f.space_iri} {f.modality}" not in _gone
            ]
            logger.warning(
                f"[deliberate] {len(_bad)} value(s) excluded as physically impossible "
                f"across {len({i.label for i in _bad})} space/modality pair(s)"
            )
            impossible_readings.append(excluded_sentence(_bad))
    except Exception as exc:  # a failed check must never cost the answer
        logger.warning(f"[deliberate] plausibility check skipped: {exc}")

    # ── V12-04: what each candidate's evidence actually is ──────────────────
    #
    # Built here rather than inside the scorer so the scorer stays a pure function of
    # (candidates, values, verdicts) and can be tested without a graph.
    #
    # The verdict is per POINT. A store may also declare a `measured_through` boundary,
    # in which case `observation_provenance` judges a reading by its timestamp — that
    # stays supported for an estate whose store genuinely changed character on a date.
    # Where no boundary is declared, every reading from a point inherits the point's own
    # origin, which is the ordinary case.
    #
    # What this catches is what R4 is actually about: SATURATE-provisioned points, which
    # have no physical instrument at all and must not win a recommendation about a real
    # building. An UNDECLARED origin still ranks — excluding it would empty most rankings
    # in any estate that has not finished labelling — but is not counted as measured
    # coverage, so nothing claims it is a measurement.
    #
    # The BUILDING decides whether origin may affect an answer, via
    # `provenance.evidence_policy` in its building.yaml.
    #
    #   all_connected_readings (default) — every attached reading is authoritative and an
    #       answer does not distinguish simulated from measured. Right for an estate whose
    #       synthetic points STAND IN for instruments not yet connected: refusing them
    #       would answer "I cannot tell you about that floor" about a floor whose data is
    #       present and correct for what it represents.
    #
    #   measured_only — RETIRED 2026-09-22. It excluded a candidate whose evidence declared
    #       `ontosage:isSimulated true` before ranking. No record declares an origin any more:
    #       the building's 680 installed sensors report real readings and the rest of the estate
    #       is modelled on them, disclosed once in the paper rather than per answer. A building
    #       that sets this value still gets `all_connected_readings` behaviour, which is what
    #       every building here already set.
    _policy = _evidence_policy(schema.building_id)
    _provenance: Dict[str, Dict[str, Any]] = {}
    if _policy == "measured_only":
        try:
            from orchestrator.services.observation_provenance import observation_origin

            for cand in candidates:
                per_modality: Dict[str, Any] = {}
                for modality, handle in (cand.sensors or {}).items():
                    raw = str((handle or {}).get("simulated", "")).strip().lower()
                    declared = True if raw == "true" else (False if raw == "false" else None)
                    per_modality[modality] = observation_origin(point_simulated=declared)
                if per_modality:
                    _provenance[cand.space_iri] = per_modality
        except Exception as _prov_err:  # pragma: no cover - live wiring
            # Fails OPEN. A provenance outage must not empty every ranking in the system;
            # an empty dict means the scorer excludes nothing, which is the old behaviour.
            logger.warning(f"[executor] provenance not resolved: {_prov_err}")
            _provenance = {}

    t0 = time.time()
    score = score_candidates(
        cqir, candidates, values, anchors=_anchors, provenance=_provenance or None
    )
    # WB-05: SCENARIO FALLBACK, SAID OUT LOUD. When the operational ranking is empty only
    # because every candidate's evidence is simulated, rank on the simulated readings and put
    # that in the answer's first line. Where measured evidence exists this never runs, so a
    # simulated point still cannot beat a measured one (V12-04). Measured 2026-09-15: noise,
    # illuminance and occupancy are simulated in every room of the demo building, so "which
    # is the quietest room?" could never be answered at all.
    if not score.ranked and score.excluded_for_provenance and candidates:
        score = score_candidates(
            cqir,
            candidates,
            values,
            anchors=_anchors,
            provenance=_provenance or None,
            evidence_mode="scenario",
        )
        if score.ranked:
            _sim = ", ".join(sorted({c.modality for c in cqir.constraints}))
            # The basis is still stated in the first lines, but in the reader's terms. The owner's
            # standing rule (2026-09-17): no user-visible text calls the building's data
            # simulated, synthetic or fake — the readings are placeholders for the real feeds and
            # are replaced at connection. What stays true and useful is WHICH points ranked it.
            event_notes = [
                f"**Ranking basis.** None of the rooms in scope has a {_sim} point declared as "
                "measured, so this ranking uses the points the building model declares for them."
            ] + list(event_notes)
            logger.info(
                f"[executor] operational ranking empty on provenance — scenario mode for {_sim}"
            )
    timings["score_ms"] = int((time.time() - t0) * 1000)
    if _coverage_note and score.ranked:
        event_notes = [_coverage_note] + list(event_notes)

    band_notes = _out_of_band_notes(score, _anchors)

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
        impossible_readings=impossible_readings,
        band_notes=band_notes,
        plan_hash=plan_hash,
        plan_fingerprint=cqir.plan_fingerprint(),
        timings_ms=timings,
    )
