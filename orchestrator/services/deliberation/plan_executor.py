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
from orchestrator.services.deliberation.cqir import (
    CQIR,
    SCORING_OPERATORS,
    FacetCriterion,
    FacetOperator,
    Hardness,
    TimeBasis,
)
from orchestrator.services.deliberation.fetch import Series, fetch_series
from orchestrator.services.deliberation.scorer import (
    CriterionScore,
    FacetScore,
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
    #: v2 — one check per (facet criterion, candidate evaluated): the evidence matrix's facet
    #: columns, with the value, the record id it came from and met / unmet / unknown.
    facet_checks: List[Any] = field(default_factory=list)
    #: v2 — facet key -> the reader's label for it.
    facet_labels: Dict[str, str] = field(default_factory=dict)
    #: v2 — sentences the answer must carry about the facet criteria: how a ranking criterion
    #: with no standard scale was normalised, and how many spaces had a value recorded.
    facet_notes: List[str] = field(default_factory=list)
    #: v2 — one sentence per criterion admission found not assessable; the answer names each.
    not_assessable: List[str] = field(default_factory=list)
    #: v2 — facet keys of the plan that were NOT checked (not assessable, or an availability
    #: check the deterministic fold already made). The answer never lists them as sources.
    facet_skipped: List[str] = field(default_factory=list)
    #: v2 — the result of an AGGREGATE_RANK plan (operations.AggregateResult), else None.
    aggregate: Optional[Any] = None
    #: v2 — the result of a COMPARE_FACETS plan (operations.CompareResult), else None.
    comparison: Optional[Any] = None
    #: v2 — the result of a PERIOD_COMPARE plan (operations.PeriodResult), else None.
    periods: Optional[Any] = None
    #: v2 — the result of a RELATE plan (operations.RelationResult), else None.
    relation: Optional[Any] = None
    #: v2 — sentences an operation plan carries: criteria it could not apply (a preference
    #: cannot decide which spaces are counted), a unit conversion, a relation it had to change.
    operation_notes: List[str] = field(default_factory=list)


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


# ── v2: facet criteria in the plan ──────────────────────────────────────────────────────

_REQUIREMENT_WORDS = {
    FacetOperator.BELOW: "below",
    FacetOperator.ABOVE: "above",
    FacetOperator.AT_LEAST: "at least",
    FacetOperator.AT_MOST: "at most",
    FacetOperator.NEAR: "near",
}


def requirement_text(criterion: FacetCriterion, label: str) -> str:
    """What a criterion asks for, in the reader's words: "seat count at least 12"."""
    op, value = criterion.operator, criterion.value
    if op in _REQUIREMENT_WORDS:
        shown = f"{value:g}" if isinstance(value, float) else str(value)
        return f"{label} {_REQUIREMENT_WORDS[op]} {shown}"
    if op == FacetOperator.MINIMIZE:
        return f"{label} as low as possible"
    if op == FacetOperator.MAXIMIZE:
        return f"{label} as high as possible"
    if op == FacetOperator.IS_TRUE:
        return f"{label}: yes"
    if op == FacetOperator.IS_FALSE:
        return f"{label}: no"
    if op == FacetOperator.FREE_FOR:
        hours = float(value) if isinstance(value, (int, float)) else 1.0
        return f"free for the next {hours:g} h"
    if op == FacetOperator.CONTAINS:
        return f"{label} mentions '{value}'"
    if isinstance(value, list):
        return f"{label} one of {', '.join(str(v) for v in value)}"
    return f"{label} {value}"


def _hard_facet_exclusions(
    checks: List[Any], criteria: List[FacetCriterion], labels: Dict[int, str]
) -> Dict[str, str]:
    """{space_iri: ledger reason} for every space failing a HARD facet criterion.

    The reason names the recorded value and the record it came from. A record group fails as
    ONE requirement -- "no single <register> record is X and Y" -- because that is what was
    asked; listing its parts separately would suggest each was checked on its own.
    """
    from orchestrator.services.deliberation.facet_resolvers import UNMET

    failing: Dict[str, Dict[str, List[Any]]] = {}
    for check in checks:
        if check.status != UNMET or check.criterion.hardness != Hardness.HARD:
            continue
        group = check.criterion.record_group or f"#{check.index}"
        failing.setdefault(check.space_iri, {}).setdefault(group, []).append(check)
    reasons: Dict[str, str] = {}
    for space, groups in failing.items():
        parts: List[str] = []
        for group_checks in groups.values():
            group_checks.sort(key=lambda c: c.index)
            asked = " and ".join(
                requirement_text(c.criterion, labels.get(c.index, c.criterion.facet))
                for c in group_checks
            )
            seen = "; ".join(dict.fromkeys(c.display for c in group_checks if c.display))
            source = ", ".join(dict.fromkeys(p for c in group_checks for p in c.provenance))
            found = f"{seen} ({source})" if source else seen
            if len(group_checks) > 1 and group_checks[0].criterion.record_group:
                parts.append(f"no single record meets {asked} — closest: {found}")
            else:
                parts.append(f"{found} — needs {asked}")
        reasons[space] = "; ".join(parts)
    return reasons


def _facet_scores(
    checks: List[Any],
    criteria: List[FacetCriterion],
    labels: Dict[int, str],
    candidates: List[Candidate],
) -> Tuple[Dict[str, List[FacetScore]], List[str]]:
    """Each candidate's facet contributions to its score, and the notes the answer carries.

    Filters (thresholds, enums, booleans, text, availability) score 1 when met and 0 when not.
    A ranking criterion (minimize / maximize / near) has no standard band, so it is scored
    min-max across the candidates compared -- and the answer says so, with the two ends.
    """
    from orchestrator.services.deliberation.facet_resolvers import MET, UNKNOWN, UNMET

    by_cell = {(c.space_iri, c.index): c for c in checks}
    iris = [c.space_iri for c in candidates]
    scores: Dict[str, List[FacetScore]] = {iri: [] for iri in iris}
    notes: List[str] = []
    for idx, criterion in enumerate(criteria):
        label = labels.get(idx, criterion.facet)
        hard = criterion.hardness == Hardness.HARD
        numbers: Dict[str, float] = {}
        if criterion.operator in SCORING_OPERATORS:
            for iri in iris:
                check = by_cell.get((iri, idx))
                if check is not None and check.status == MET and check.number is not None:
                    numbers[iri] = float(check.number)
        lo = min(numbers.values()) if numbers else 0.0
        hi = max(numbers.values()) if numbers else 0.0
        target = criterion.value if isinstance(criterion.value, float) else None
        max_dev = (
            max((abs(v - target) for v in numbers.values()), default=0.0)
            if target is not None
            else 0.0
        )
        for iri in iris:
            check = by_cell.get((iri, idx))
            status = check.status if check is not None else UNKNOWN
            utility: Optional[float]
            if criterion.operator in SCORING_OPERATORS:
                n = numbers.get(iri)
                if n is None:
                    utility = None
                elif criterion.operator == FacetOperator.NEAR and target is not None:
                    utility = 1.0 if max_dev <= 0 else 1.0 - abs(n - target) / max_dev
                elif hi <= lo:
                    utility = 1.0
                elif criterion.operator == FacetOperator.MAXIMIZE:
                    utility = (n - lo) / (hi - lo)
                else:
                    utility = (hi - n) / (hi - lo)
            else:
                utility = 1.0 if status == MET else (0.0 if status == UNMET else None)
            scores[iri].append(
                FacetScore(
                    score=CriterionScore(
                        criterion.facet,
                        check.number if check is not None else None,
                        None if utility is None else round(utility, 4),
                        criterion.weight,
                        "",
                        "" if utility is not None else "not recorded — not counted as met",
                        display=check.display if check is not None else "",
                        provenance=", ".join(check.provenance) if check is not None else "",
                    ),
                    hard=hard,
                    label=label,
                )
            )
        if numbers and criterion.operator in SCORING_OPERATORS:
            notes.append(
                f"'{criterion.source_phrase or label}' is scored relative to the "
                f"{len(numbers)} space(s) it is recorded for (from {lo:g} to {hi:g}), because "
                "no standard scale exists for it"
            )
        recorded = sum(
            1 for iri in iris if (by_cell.get((iri, idx)) or _NO_CHECK).status != UNKNOWN
        )
        if iris and recorded < len(iris):
            notes.append(
                f"{label} is recorded for {recorded} of the {len(iris)} space(s) compared"
                + (
                    "; the others are ranked below every space verified on it"
                    if hard
                    else "; for the others it is left out of the score"
                )
            )
    return scores, notes


@dataclass
class _NoCheck:
    status: str = "unknown"


_NO_CHECK = _NoCheck()


def _recount(ledger: CoverageLedger, candidates: List[Candidate]) -> None:
    """Keep the ledger's counts about the candidates that are actually still considered.

    The instrumented counts were taken at enumeration; after an exclusion they would describe
    spaces no longer in the answer ("noise: 6/3 instrumented"). v2 only -- the v1 event path
    keeps its own behaviour.
    """
    ledger.considered = len(candidates)
    for modality in list(ledger.instrumented):
        ledger.instrumented[modality] = sum(1 for c in candidates if modality in c.sensors)


async def execute(
    cqir: CQIR,
    admission: AdmissionResult,
    schema: BuildingCapabilitySchema,
    geometry: Optional[Dict[str, GeometryInfo]] = None,
    adapter_getter=None,
    forecaster: Optional[Forecaster] = None,
    *,
    catalogue=None,
    sparql_exec=None,
) -> ExecutionOutcome:
    """Run the admitted constraint program end-to-end, deterministically.

    v2: with facet criteria and the facet ``catalogue``, every candidate's facet values are
    read in code (``facet_resolvers.resolve_facets``, batched SPARQL), hard failures are
    excluded with the value and record id in the ledger, unrecorded hard criteria are kept but
    ranked below verified spaces, and soft ones are scored beside the readings. A plan without
    facet criteria runs exactly the v1 path.
    """
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
    # The determinism anchor is the COMPILED plan's, taken before anything below narrows it.
    fingerprint = cqir.plan_fingerprint()
    # v2 operations (C3 aggregate, C2 compare, C4 periods) read facets, so they need the
    # catalogue. Without one there is nothing to read them through, and ranking spaces instead
    # would answer a question nobody asked.
    operation = getattr(cqir, "operation", None)
    if operation and catalogue is None:
        return ExecutionOutcome(
            score=ScoreResult(ranked=[], excluded=[]),
            ledger=CoverageLedger(),
            candidates=[],
            refusal=(
                "I can't work that out this turn: it needs what the building records about its "
                "spaces, and that could not be read just now. Please ask again shortly."
            ),
        )
    operation_mode = bool(operation)
    # v2: a facet plan runs WITHOUT the criteria admission found not assessable -- including a
    # sensed one with no backed sensor -- and names them in the answer. A v1 plan is untouched.
    facet_mode = (
        bool(getattr(cqir, "facet_criteria", None)) or operation_mode
    ) and catalogue is not None
    not_assessable = list(getattr(admission, "not_assessable", None) or [])
    if facet_mode and not_assessable:
        cqir = cqir.model_copy(
            update={
                "constraints": [c for c in cqir.constraints if c.modality not in not_assessable]
            }
        )
    modalities = [c.modality for c in cqir.constraints]
    # v2 operations: other criteria only NARROW which spaces count. A stated limit on a reading
    # filters by that reading; a preference ("quiet") cannot decide which spaces are counted, so
    # it is not applied and the answer says so. The operation's own sensed facet is fetched.
    op_filters: List[Any] = []
    op_unapplied: List[str] = []
    if operation_mode:
        from orchestrator.services.deliberation.cqir import Direction

        op_filters = [
            c
            for c in cqir.constraints
            if c.direction in (Direction.BELOW, Direction.ABOVE) and c.threshold is not None
        ]
        op_unapplied = [
            c.source_phrase or c.modality for c in cqir.constraints if c not in op_filters
        ]
        op_sensed = [
            f.modality
            for f in (catalogue.get(k) for k in cqir.operation_facets())
            if f is not None and f.source_kind == "sensor" and f.modality
        ]
        modalities = list(dict.fromkeys([c.modality for c in op_filters] + op_sensed))
        if getattr(cqir, "period", None) is not None or getattr(cqir, "relate", None) is not None:
            # A limit on a reading says nothing about WHICH period it is a limit in, so a period
            # comparison does not apply one -- it names it; nor does a relation, which reads
            # every reading in its window. Both are reduced in the store, so nothing is fetched
            # row by row either.
            op_unapplied += [c.source_phrase or c.modality for c in op_filters]
            op_filters, modalities = [], []
    # Standards bands, overlaid with this building's own calibration where it
    # declares one (CAVEAT-162). Resolved ONCE so the preliminary forecast rank
    # and the final rank cannot be scored against different bands.
    _anchors = load_anchors(schema.building_id)

    t0 = time.time()
    candidates, ledger = enumerate_candidates(cqir, admission, schema, geometry)
    timings["enumerate_ms"] = int((time.time() - t0) * 1000)

    # v2: facet values are read BEFORE the fetch budget is checked and before any series is
    # fetched: a room that seats eight is out of "at least 12 seats" however quiet it is, and
    # dropping it first is what keeps a building-wide question inside the budget.
    facet_checks: List[Any] = []
    facet_criteria: List[FacetCriterion] = []
    facet_labels: Dict[int, str] = {}
    if facet_mode:
        from orchestrator.services.deliberation.candidates import LedgerEntry
        from orchestrator.services.deliberation.facet_resolvers import (
            facet_reader_label,
            resolve_facets,
        )

        facet_criteria = [c for c in cqir.facet_criteria if c.facet not in not_assessable]
        if cqir.event_criteria:
            # the deterministic fold already checks availability (the compiler drops the
            # duplicate; this guards a plan built by hand)
            facet_criteria = [c for c in facet_criteria if c.operator != FacetOperator.FREE_FOR]
        if operation_mode:
            # A preference on a recorded facet cannot decide which spaces an operation counts:
            # named as not applied, never resolved, never scored.
            op_unapplied += [
                c.source_phrase or (facet_reader_label(catalogue.get(c.facet)) or c.facet)
                for c in facet_criteria
                if c.operator in SCORING_OPERATORS
            ]
            facet_criteria = [c for c in facet_criteria if c.operator not in SCORING_OPERATORS]
        facet_labels = {
            i: facet_reader_label(catalogue.get(c.facet)) or c.facet
            for i, c in enumerate(facet_criteria)
        }
        if facet_criteria and candidates:
            if sparql_exec is None:  # pragma: no cover - live wiring
                from orchestrator.services.deliberation.live import sparql_exec as _live

                sparql_exec = _live
            t0 = time.time()
            facet_checks = await resolve_facets(
                facet_criteria,
                catalogue,
                [c.space_iri for c in candidates],
                sparql_exec,
                candidates=candidates,
                schema=schema,
                adapter_getter=adapter_getter,
            )
            failing = _hard_facet_exclusions(facet_checks, facet_criteria, facet_labels)
            for cand in candidates:
                if cand.space_iri in failing:
                    ledger.excluded.append(
                        LedgerEntry(cand.space_iri, cand.label, failing[cand.space_iri])
                    )
            candidates = [c for c in candidates if c.space_iri not in failing]
            _recount(ledger, candidates)
            timings["facets_ms"] = int((time.time() - t0) * 1000)
            logger.info(
                f"[executor] facets: {len(facet_criteria)} criterion(s), "
                f"{len(failing)} space(s) excluded on a hard requirement, "
                f"{len(candidates)} left"
            )

    if operation_mode and getattr(cqir, "period", None) is not None:
        # v2 (C4): one reading over two periods. The store reduces every reading of each period
        # (aggregate_lane.run_aggregates), so no row budget applies and nothing is truncated.
        if sparql_exec is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as _live

            sparql_exec = _live
        if cqir.event_criteria:
            op_unapplied.append("availability now, which says nothing about past periods")
        return await _run_period(
            cqir,
            catalogue,
            sparql_exec,
            schema=schema,
            candidates=candidates,
            ledger=ledger,
            facet_checks=facet_checks,
            facet_labels=facet_labels,
            unapplied=op_unapplied,
            adapter_getter=adapter_getter,
            timings=timings,
            fingerprint=fingerprint,
            admission=admission,
        )

    if operation_mode and getattr(cqir, "relate", None) is not None:
        # v2 (C5): a series related to recorded events or to a second series. Each series is
        # reduced IN THE STORE into time buckets over the whole window (aggregate_lane.run_buckets),
        # so no row budget applies; the work is bounded by RELATE_MAX_SPACES and RELATE_MAX_DAYS.
        if sparql_exec is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as _live

            sparql_exec = _live
        if cqir.event_criteria:
            op_unapplied.append("availability now, which says nothing about past periods")
        return await _run_relation(
            cqir,
            catalogue,
            sparql_exec,
            schema=schema,
            candidates=candidates,
            ledger=ledger,
            facet_checks=facet_checks,
            facet_labels=facet_labels,
            unapplied=op_unapplied,
            adapter_getter=adapter_getter,
            timings=timings,
            fingerprint=fingerprint,
            admission=admission,
        )

    # Too broad to fetch: decline NOW rather than time out in two minutes (V7-T24).
    #
    # Truncating instead would be worse than either. A "which rooms" answer computed over
    # an arbitrary slice of the candidates is wrong in a way that looks right, and the
    # reader has no way to tell — so the question is handed back with the narrowing that
    # would make it answerable, which the user can act on immediately.
    _plan_hours, _plan_limit, _plan_rows = fetch_plan(
        cqir.time.basis, cqir.time.window_hours, len(candidates), len(modalities)
    )
    # A facet plan with no sensed criterion fetches no series, so no row budget applies to it.
    _budget_applies = bool(modalities) or not facet_mode
    if _budget_applies and (
        len(candidates) > MAX_FETCH_SPACES_ABSOLUTE or _plan_rows > MAX_FETCH_ROWS
    ):
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
            if facet_mode:
                _recount(ledger, candidates)
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
    if facet_mode and not modalities:
        series_by_uuid: Dict[str, Series] = {}  # a facet-only plan reads no time series
    else:
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
    # An operation never forecasts: the compiler refuses a forecast of a figure per group, and a
    # hand-built plan is run on the history it fetched rather than on a shortlist of spaces.
    if cqir.time.basis == TimeBasis.FORECAST and not operation_mode:
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

    if operation_mode:
        # v2: group -> reduce -> rank (C3) or two facets side by side (C2), over the spaces the
        # filters left, from the readings just aggregated and the facet values read in code.
        if sparql_exec is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as _live

            sparql_exec = _live
        return await _run_operation(
            cqir,
            catalogue,
            sparql_exec,
            candidates=candidates,
            ledger=ledger,
            values=values,
            evidence=evidence,
            facet_checks=facet_checks,
            facet_criteria=facet_criteria,
            facet_labels=facet_labels,
            filters=op_filters,
            unapplied=op_unapplied,
            basis=agg_window_note,
            event_checks=event_checks,
            event_notes=([_coverage_note] if _coverage_note else []) + list(event_notes),
            impossible_readings=impossible_readings,
            timings=timings,
            fingerprint=fingerprint,
            fetch_window=fetch_window,
            admission=admission,
            modalities=modalities,
        )

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

    # v2: the facet criteria's contributions, computed over the candidates still standing.
    facet_scores: Optional[Dict[str, List[FacetScore]]] = None
    facet_notes: List[str] = []
    if facet_mode and facet_criteria:
        facet_scores, facet_notes = _facet_scores(
            facet_checks, facet_criteria, facet_labels, candidates
        )
        from orchestrator.services.record_entity_links import LINK_PREDICATES, ROUTE_TO

        if any(
            getattr(catalogue.get(c.facet), "join_predicate", None) == LINK_PREDICATES[ROUTE_TO]
            for c in facet_criteria
        ):
            # The plan has no slot for where a journey starts, so this is said, not hidden.
            facet_notes.append(
                "route facts are read from every recorded route that ends at a space, and the "
                "start of the route used is named beside it — no starting point was chosen for you"
            )

    t0 = time.time()
    if facet_scores is None:
        score = score_candidates(
            cqir, candidates, values, anchors=_anchors, provenance=_provenance or None
        )
    else:
        score = score_candidates(
            cqir,
            candidates,
            values,
            anchors=_anchors,
            provenance=_provenance or None,
            facet_scores=facet_scores,
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
            **({"facet_scores": facet_scores} if facet_scores is not None else {}),
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

    # The fingerprint covers the facet criteria (cqir.plan_fingerprint includes them whenever
    # there are some), so the plan hash does too.
    plan_hash = hashlib.sha256(
        (
            fingerprint
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
        plan_fingerprint=fingerprint,
        timings_ms=timings,
        facet_checks=facet_checks,
        facet_labels=_reader_labels(cqir, catalogue) if facet_mode else {},
        facet_notes=facet_notes,
        not_assessable=(
            list(getattr(admission, "not_assessable_notes", None) or []) if facet_mode else []
        ),
        facet_skipped=(
            [c.facet for c in cqir.facet_criteria if c not in facet_criteria] if facet_mode else []
        ),
    )


def _reader_labels(cqir: CQIR, catalogue) -> Dict[str, str]:
    """Facet key -> the reader's label, for EVERY facet criterion of the plan -- including the
    ones not checked, which the answer names too and must never name by their key."""
    from orchestrator.services.deliberation.facet_resolvers import facet_reader_label

    labels = {
        c.facet: facet_reader_label(catalogue.get(c.facet)) or c.source_phrase or "a criterion"
        for c in cqir.facet_criteria
    }
    for key in cqir.operation_facets():
        labels.setdefault(key, facet_reader_label(catalogue.get(key)) or key)
    return labels


# ── v2: running an operation (C3 aggregate -> rank, C2 compare two facets, C4 periods) ───


def _group_keys(candidate: Candidate, group_by: Any) -> List[str]:
    """The groups one space belongs to. A space of several room kinds is in each of them."""
    from orchestrator.services.deliberation.cqir import GroupBy

    if group_by == GroupBy.BUILDING:
        return ["building"]
    if group_by == GroupBy.SPACE_KIND:
        # ONE kind per space, in the building's own words: its label's descriptor ("Meeting
        # Room"), else its most specific Brick class (space_kinds.py). Grouping by every Brick
        # class counted a room under each of its classes, and two spellings of one class
        # (Break_Room, Breakroom) became two groups with the same four rooms (live, 2026-10-08).
        from orchestrator.services.deliberation.space_kinds import space_kinds

        kinds = space_kinds(candidate.label, candidate.kinds or ())
        return [kinds[0]] if kinds else []
    return [candidate.floor] if candidate.floor else []


def _unverified_on_facets(
    facet_checks: List[Any], facet_labels: Dict[int, str]
) -> Dict[str, List[str]]:
    """{space: the hard facet requirements nobody records for it}. Such a space is named and
    never counted by an operation: counting it would count a space nobody checked."""
    from orchestrator.services.deliberation.facet_resolvers import UNKNOWN

    unverified: Dict[str, List[str]] = {}
    for check in facet_checks:
        if check.status == UNKNOWN and check.criterion.hardness == Hardness.HARD:
            label = facet_labels.get(check.index) or check.criterion.facet
            bucket = unverified.setdefault(check.space_iri, [])
            if label not in bucket:
                bucket.append(label)
    return unverified


async def _group_labels(standing: List[Candidate], group_by: Any, sparql_exec) -> Dict[str, str]:
    """{group key: the reader's name for it}: a floor as the building labels it, a room kind in
    words, the building as "the building"."""
    from orchestrator.services.deliberation.cqir import GroupBy
    from orchestrator.services.deliberation.facet_resolvers import read_floor_labels

    labels: Dict[str, str] = {"building": "the building"}
    if group_by == GroupBy.FLOOR:
        floor_names = await read_floor_labels([c.space_iri for c in standing], sparql_exec)
        for cand in standing:
            if cand.floor:
                labels[cand.floor] = floor_names.get(cand.floor) or cand.floor
    elif group_by == GroupBy.SPACE_KIND:
        for cand in standing:
            for key in _group_keys(cand, GroupBy.SPACE_KIND):
                labels[key] = key.replace("_", " ")
    return labels


def _shown(start: str, end: str, tz_name: Optional[str], partial: bool) -> str:
    """A store-clock interval in building time, as the reader is shown it."""
    from datetime import datetime as _dt

    from orchestrator.services.requested_interval import STAMP, store_now, to_local

    try:
        a = to_local(_dt.strptime(str(start)[:19], STAMP), tz_name)
        b = _dt.strptime(str(end)[:19], STAMP)
    except ValueError:
        return f"{start} to {end}"
    if partial:
        b = min(b, store_now())
    b = to_local(b, tz_name)
    tail = ", so far" if partial else ""
    return f"{a:%a %d %b %H:%M} to {b:%a %d %b %H:%M}{tail}"


async def _run_period(
    cqir: CQIR,
    catalogue,
    sparql_exec,
    *,
    schema: BuildingCapabilitySchema,
    candidates: List[Candidate],
    ledger: CoverageLedger,
    facet_checks: List[Any],
    facet_labels: Dict[int, str],
    unapplied: List[str],
    adapter_getter,
    timings: Dict[str, int],
    fingerprint: str,
    admission: AdmissionResult,
) -> ExecutionOutcome:
    """One reading over two periods (C4), each period reduced IN THE STORE.

    REUSES aggregate_lane's store-side reduction (``run_aggregates``): per sensor and period, the
    count, sum, minimum and maximum of EVERY reading, by one GROUP BY -- so a week is read whole,
    never truncated to its newest rows the way a row fetch would be, and a reading outside the
    quantity's physical range is left out by the store itself. A weekday/weekend period is the sum
    of its local days, each reduced the same way.
    """
    from orchestrator.services import aggregate_lane as agl
    from orchestrator.services.deliberation import operations as ops
    from orchestrator.services.deliberation.facet_resolvers import facet_reader_label
    from orchestrator.services.requested_interval import building_tz, local_day_windows

    spec = cqir.period
    facet = catalogue.get(spec.facet)
    modality = facet.modality or spec.facet.split(":", 1)[-1]
    t0 = time.time()
    unverified = _unverified_on_facets(facet_checks, facet_labels)
    population = [c for c in candidates if c.space_iri not in unverified]
    ledger.instrumented.setdefault(modality, 0)
    _recount(ledger, population)

    handles = {c.space_iri: (c.sensors or {}).get(modality) or {} for c in population}
    storage = {
        h["uuid"]: h["stored_at"] for h in handles.values() if h.get("uuid") and h.get("stored_at")
    }
    if adapter_getter is None:  # pragma: no cover - live wiring
        from orchestrator.services.adapters.registry import adapter_registry

        adapter_getter = adapter_registry.get
    # aggregate_lane's own readiness check: the stores it can reduce in SQL, and the rest.
    ready, unsupported = await agl._stores_ready(
        list(storage), storage, adapter_getter, lambda key: key
    )
    bands: Optional[Dict[str, Tuple[float, float]]] = None
    try:
        from orchestrator.services.physical_bands import band_for_modality

        band = band_for_modality(modality, schema.building_id)
        if band is not None:
            bands = {u: (band.low, band.high) for u in storage}
    except Exception as exc:  # a band lookup never costs the answer
        logger.debug(f"[executor] physical band for {modality} unavailable: {exc}")

    tz_name = building_tz()
    windows: List[ops.PeriodWindow] = []
    reduced: List[Dict[str, Dict[str, Any]]] = []
    failed: set = set()
    excluded_readings = 0
    for period in spec.periods:
        if period.day_type:
            wanted_weekend = period.day_type == "weekend"
            days = [
                (s, e)
                for s, e, weekday in local_day_windows(period.start, period.end, tz_name)
                if (weekday >= 6) == wanted_weekend
            ]
        else:
            days = [(period.start, period.end)]
        totals: Dict[str, Dict[str, Any]] = {}
        for start, end in days:
            window = agl.Window(start, end, period.label)
            for _key, (adapter, members) in sorted(ready.items()):
                aggs, bad = await agl.run_aggregates(adapter, members, window, None, bands)
                failed.update(bad)
                for a in aggs:
                    held = totals.setdefault(a.uuid, {"n": 0, "sum": 0.0, "lo": None, "hi": None})
                    excluded_readings += int(a.excluded or 0)
                    if not a.n:
                        continue
                    held["n"] += int(a.n)
                    held["sum"] += float(a.total)
                    if a.minimum is not None:
                        held["lo"] = a.minimum if held["lo"] is None else min(held["lo"], a.minimum)
                    if a.maximum is not None:
                        held["hi"] = a.maximum if held["hi"] is None else max(held["hi"], a.maximum)
        reduced.append(totals)
        windows.append(
            ops.PeriodWindow(
                label=period.label,
                start=period.start,
                end=period.end,
                shown=_shown(period.start, period.end, tz_name, period.partial),
                day_type=period.day_type,
                partial=period.partial,
                days=len(days) if period.day_type else 0,
            )
        )

    spaces: List[ops.PeriodSpace] = []
    for cand in population:
        handle = handles.get(cand.space_iri) or {}
        uuid = handle.get("uuid") or ""
        groups = _group_keys(cand, spec.group_by) if spec.group_by is not None else ["all"]
        space = ops.PeriodSpace(space_iri=cand.space_iri, label=cand.label, groups=groups)
        if not uuid or uuid not in storage:
            space.reason = f"no {modality} sensor"
        elif uuid in unsupported:
            space.reason = "its readings are kept in a store this answer cannot reduce"
        elif uuid in failed:
            space.reason = "its readings could not be read just now"
        else:
            for side, totals in zip(("a", "b"), reduced):
                held = totals.get(uuid) or {}
                n = int(held.get("n") or 0)
                if n:
                    setattr(space, f"{side}_n", n)
                    setattr(space, f"{side}_mean", ops.rounded(held["sum"] / n))
                    setattr(space, f"{side}_low", ops.rounded(held["lo"]))
                    setattr(space, f"{side}_high", ops.rounded(held["hi"]))
            gaps = [
                w.label for w, side in zip(windows, ("a", "b")) if not getattr(space, f"{side}_n")
            ]
            if gaps:
                space.reason = "no readings " + " or ".join(gaps)
        spaces.append(space)

    notes: List[str] = [
        f"'{u}' was not applied: this comparison reads the same spaces in both periods"
        for u in dict.fromkeys(unapplied)
        if u
    ]
    for window in windows:
        if window.partial:
            notes.append(f"{window.label} is not over: its figure covers its readings so far")
    if excluded_readings:
        notes.append(
            f"{excluded_readings} reading(s) outside the physically possible range for {modality} "
            "were left out by the store"
        )
    held_back = sorted(
        f"{c.label} ({', '.join(unverified[c.space_iri])})"
        for c in candidates
        if c.space_iri in unverified
    )
    if held_back:
        notes.append(
            f"{len(held_back)} space(s) were not compared because what you asked for could not "
            f"be verified for them: {', '.join(held_back[: ops.MAX_NAMED])}"
            + (
                f", and {len(held_back) - ops.MAX_NAMED} more"
                if len(held_back) > ops.MAX_NAMED
                else ""
            )
        )
    group_labels = (
        await _group_labels(population, spec.group_by, sparql_exec)
        if spec.group_by is not None
        else {}
    )
    result = ops.compare_periods(
        spec.statistic,
        spaces,
        windows,
        facet=spec.facet,
        label=facet_reader_label(facet) or spec.facet,
        unit=ops.facet_unit(facet),
        group_by=spec.group_by.value if spec.group_by is not None else "",
        group_labels=group_labels,
        notes=notes,
    )
    timings["periods_ms"] = int((time.time() - t0) * 1000)
    try:  # every figure the comparison computed is evidence for the claim binder
        from orchestrator.services.evidence import computed

        computed.record("deliberate_operation", ops.computed_figures(result))
    except Exception as exc:  # pragma: no cover - a recorder never costs the answer
        logger.debug(f"[executor] period figures not recorded: {exc}")

    plan_hash = hashlib.sha256(
        (
            fingerprint
            + "|"
            + ",".join(sorted(c.space_iri for c in population))
            + "|"
            + ";".join(f"{w.start}..{w.end}:{w.day_type or ''}" for w in windows)
        ).encode("utf-8")
    ).hexdigest()[:16]
    logger.info(
        f"[executor] operation=period_compare plan={plan_hash} spaces={len(population)} "
        f"compared={result.overall.n if result.overall else 0} timings={timings}"
    )
    return ExecutionOutcome(
        score=ScoreResult(ranked=[], excluded=[]),
        ledger=ledger,
        candidates=candidates,
        plan_hash=plan_hash,
        plan_fingerprint=fingerprint,
        timings_ms=timings,
        facet_checks=facet_checks,
        facet_labels=_reader_labels(cqir, catalogue),
        not_assessable=list(getattr(admission, "not_assessable_notes", None) or []),
        periods=result,
        operation_notes=list(result.notes),
    )


def _sensed_values(
    facet: Any,
    population: List[Candidate],
    values: Dict[str, Dict[str, float]],
    basis: str,
) -> Dict[str, Tuple[Optional[float], str, str, str]]:
    """{space: (value, display, provenance, reason)} for a SENSED facet: the windowed reading."""
    from orchestrator.services.deliberation.operations import facet_unit, with_unit

    modality = facet.modality or facet.key.split(":", 1)[-1]
    unit = facet_unit(facet)
    out: Dict[str, Tuple[Optional[float], str, str, str]] = {}
    for cand in population:
        value = values.get(cand.space_iri, {}).get(modality)
        if value is None:
            reason = (
                "no usable reading in the window"
                if modality in (cand.sensors or {})
                else f"no {modality} sensor"
            )
            out[cand.space_iri] = (None, "", "", reason)
            continue
        shown = with_unit(value, unit)
        out[cand.space_iri] = (float(value), shown, f"{modality} sensor, {basis}", "")
    return out


async def _operation_values(
    facet: Any,
    population: List[Candidate],
    values: Dict[str, Dict[str, float]],
    basis: str,
    sparql_exec,
    catalogue,
    facet_criteria: List[FacetCriterion],
    adds_up: bool,
) -> Dict[str, Dict[str, Any]]:
    """{space: {value, flag, display, provenance, reason}} for one operation facet."""
    from orchestrator.services.deliberation.facet_resolvers import read_facet_values

    out: Dict[str, Dict[str, Any]] = {}
    if facet.source_kind == "sensor":
        for iri, (value, shown, source, reason) in _sensed_values(
            facet, population, values, basis
        ).items():
            out[iri] = {
                "value": value,
                "flag": None,
                "display": shown,
                "provenance": source,
                "reason": reason,
            }
        return out
    read = await read_facet_values(
        facet,
        [c.space_iri for c in population],
        sparql_exec,
        filters=facet_criteria,
        catalogue=catalogue,
        additive=adds_up,
    )
    for cand in population:
        fv = read.get(cand.space_iri)
        if fv is None:
            out[cand.space_iri] = {"value": None, "flag": None, "display": "", "provenance": ""}
            out[cand.space_iri]["reason"] = "not read"
            continue
        out[cand.space_iri] = {
            "value": fv.number,
            "flag": fv.flag,
            "display": fv.display,
            "provenance": ", ".join(fv.provenance),
            "reason": fv.reason,
        }
    return out


async def _run_operation(
    cqir: CQIR,
    catalogue,
    sparql_exec,
    *,
    candidates: List[Candidate],
    ledger: CoverageLedger,
    values: Dict[str, Dict[str, float]],
    evidence: List[EvidenceCell],
    facet_checks: List[Any],
    facet_criteria: List[FacetCriterion],
    facet_labels: Dict[int, str],
    filters: List[Any],
    unapplied: List[str],
    basis: str,
    event_checks: List[EventCheck],
    event_notes: List[str],
    impossible_readings: List[str],
    timings: Dict[str, int],
    fingerprint: str,
    fetch_window: float,
    admission: AdmissionResult,
    modalities: List[str],
) -> ExecutionOutcome:
    """Filter the candidates, read the operation's facet(s) per space, compute, and report."""
    from orchestrator.services.deliberation import operations as ops
    from orchestrator.services.deliberation.candidates import LedgerEntry
    from orchestrator.services.deliberation.cqir import Direction, Statistic
    from orchestrator.services.deliberation.facet_resolvers import facet_reader_label

    t0 = time.time()
    # 1. Who is out, and who cannot be verified. A stated limit on a reading is a filter by that
    #    reading; a hard facet requirement nobody records leaves a space UNVERIFIED -- it is named
    #    in its group and never counted, because counting it would count a space nobody checked.
    unverified = _unverified_on_facets(facet_checks, facet_labels)
    excluded: set = set()
    for cand in candidates:
        for c in filters:
            value = values.get(cand.space_iri, {}).get(c.modality)
            if value is None:
                bucket = unverified.setdefault(cand.space_iri, [])
                reading = f"{c.modality} (no reading)"
                if reading not in bucket:
                    bucket.append(reading)
                continue
            holds = value <= c.threshold if c.direction == Direction.BELOW else value >= c.threshold
            if not holds:
                ledger.excluded.append(
                    LedgerEntry(
                        cand.space_iri,
                        cand.label,
                        f"{c.modality} {value:g} — needs {c.direction.value} {c.threshold:g}",
                    )
                )
                excluded.add(cand.space_iri)
                break
    standing = [c for c in candidates if c.space_iri not in excluded]
    population = [c for c in standing if c.space_iri not in unverified]
    for modality in modalities:
        ledger.instrumented.setdefault(modality, 0)
    _recount(ledger, population)

    notes: List[str] = [
        f"'{u}' was not applied: a preference cannot decide which spaces are counted"
        for u in dict.fromkeys(unapplied)
        if u
    ]
    aggregate_spec = getattr(cqir, "aggregate", None)
    compare_spec = getattr(cqir, "compare", None)
    result: Any = None

    if aggregate_spec is not None:
        facet = catalogue.get(aggregate_spec.facet) if aggregate_spec.facet else None
        adds_up = ops.additive(facet)[0] if facet is not None else False
        is_boolean = facet is not None and facet.value_type == "boolean"
        if facet is None:
            read: Dict[str, Dict[str, Any]] = {
                c.space_iri: {"value": None, "flag": None, "display": "", "provenance": ""}
                for c in population
            }
            label, unit, how = "spaces", "", "spaces counted"
        else:
            read = await _operation_values(
                facet, population, values, basis, sparql_exec, catalogue, facet_criteria, adds_up
            )
            label = facet_reader_label(facet) or facet.key
            unit = ops.facet_unit(facet)
            how = basis if facet.source_kind == "sensor" else "recorded value"
        space_values: List[ops.SpaceValue] = []
        for cand in population:
            entry = read.get(cand.space_iri) or {}
            if facet is None:
                present = True
            elif is_boolean:
                present = entry.get("flag") is not None
            elif facet.value_type in ("number", "integer"):
                present = entry.get("value") is not None
            else:
                present = not entry.get("reason")
            space_values.append(
                ops.SpaceValue(
                    space_iri=cand.space_iri,
                    label=cand.label,
                    groups=_group_keys(cand, aggregate_spec.group_by),
                    value=entry.get("value"),
                    flag=entry.get("flag"),
                    present=present,
                    display=entry.get("display", ""),
                    provenance=entry.get("provenance", ""),
                    reason=entry.get("reason", "") if not present else "",
                )
            )
        group_labels = await _group_labels(standing, aggregate_spec.group_by, sparql_exec)
        unverified_by_group: Dict[str, List[str]] = {}
        by_iri = {c.space_iri: c for c in standing}
        for iri, missing in unverified.items():
            cand = by_iri.get(iri)
            if cand is None:
                continue
            for key in _group_keys(cand, aggregate_spec.group_by):
                unverified_by_group.setdefault(key, []).append(
                    f"{cand.label} ({', '.join(missing)})"
                )
        if aggregate_spec.statistic == Statistic.SUM and facet is not None and not adds_up:
            notes.append(ops.additive(facet)[1])  # the compiler refuses this; a hand plan does not
        result = ops.aggregate(
            aggregate_spec,
            space_values,
            label=label,
            unit=unit,
            adds_up=adds_up,
            is_boolean=is_boolean,
            basis=how,
            group_labels=group_labels,
            unverified=unverified_by_group,
            notes=notes,
        )
        if result.overlapping:
            result.notes.append(
                f"{result.overlapping} space(s) are of more than one kind and are counted under "
                "each of them"
            )
    elif compare_spec is not None:
        facet_a = catalogue.get(compare_spec.facet_a)
        facet_b = catalogue.get(compare_spec.facet_b)
        fit = ops.compare_fit(facet_a, facet_b, compare_spec.relation)
        # Why the relation shown is not the one asked, or how the two units were reconciled --
        # said once, from the same unit rules the compiler applied.
        asked = (
            ops.compare_fit(facet_a, facet_b, compare_spec.requested_relation)
            if compare_spec.requested_relation is not None
            else fit
        )
        if asked.note:
            notes.append(asked.note)
        adds_a, why_a = ops.additive(facet_a)
        adds_b, why_b = ops.additive(facet_b)
        if compare_spec.total and not (adds_a and adds_b):
            notes.append(
                "no building total is formed: " + (why_a if not adds_a else why_b).rstrip(".")
            )
        read_a = await _operation_values(
            facet_a, population, values, basis, sparql_exec, catalogue, facet_criteria, adds_a
        )
        read_b = await _operation_values(
            facet_b, population, values, basis, sparql_exec, catalogue, facet_criteria, adds_b
        )
        label_a = facet_reader_label(facet_a) or facet_a.key
        label_b = facet_reader_label(facet_b) or facet_b.key
        rows: List[ops.ComparisonRow] = []
        for cand in population:
            a = read_a.get(cand.space_iri) or {}
            b = read_b.get(cand.space_iri) or {}
            reasons = [
                f"{lbl}: {side.get('reason') or 'not recorded'}"
                for lbl, side in ((label_a, a), (label_b, b))
                if side.get("value") is None
            ]
            rows.append(
                ops.ComparisonRow(
                    space_iri=cand.space_iri,
                    label=cand.label,
                    a=a.get("value"),
                    b=b.get("value"),
                    a_display=a.get("display", ""),
                    b_display=b.get("display", ""),
                    a_provenance=a.get("provenance", ""),
                    b_provenance=b.get("provenance", ""),
                    reason="; ".join(reasons),
                )
            )
        sensed = any(f.source_kind == "sensor" for f in (facet_a, facet_b))
        result = ops.compare(
            compare_spec,
            rows,
            label_a=label_a,
            label_b=label_b,
            unit_a=ops.facet_unit(facet_a),
            unit_b=ops.facet_unit(facet_b),
            adds_up=adds_a and adds_b,
            basis=basis if sensed else "recorded values",
            convert_b=fit.convert_b,
            notes=notes,
        )
        label_of = {c.space_iri: c.label for c in standing}
        held_back = sorted(
            f"{label_of[iri]} ({', '.join(missing)})"
            for iri, missing in unverified.items()
            if iri in label_of
        )
        if held_back:
            shown = held_back[: ops.MAX_NAMED]
            more = len(held_back) - len(shown)
            result.notes.append(
                f"{len(held_back)} space(s) were not compared because what you asked for could "
                f"not be verified for them: {', '.join(shown)}"
                + (f", and {more} more" if more else "")
            )
    timings["operation_ms"] = int((time.time() - t0) * 1000)

    try:  # every figure the operation computed is evidence for the claim binder
        from orchestrator.services.evidence import computed

        computed.record("deliberate_operation", ops.computed_figures(result))
    except Exception as exc:  # pragma: no cover - a recorder never costs the answer
        logger.debug(f"[executor] operation figures not recorded: {exc}")

    plan_hash = hashlib.sha256(
        (
            fingerprint
            + "|"
            + ",".join(sorted(c.space_iri for c in population))
            + f"|{fetch_window}|{cqir.time.basis.value}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    logger.info(
        f"[executor] operation={cqir.operation} plan={plan_hash} spaces={len(population)} "
        f"excluded={len(excluded)} unverified={len(unverified)} timings={timings}"
    )
    return ExecutionOutcome(
        score=ScoreResult(ranked=[], excluded=[]),
        ledger=ledger,
        candidates=candidates,
        evidence=evidence,
        event_checks=event_checks,
        event_notes=event_notes,
        impossible_readings=impossible_readings,
        plan_hash=plan_hash,
        plan_fingerprint=fingerprint,
        timings_ms=timings,
        facet_checks=facet_checks,
        facet_labels=_reader_labels(cqir, catalogue),
        not_assessable=list(getattr(admission, "not_assessable_notes", None) or []),
        facet_skipped=[c.facet for c in cqir.facet_criteria if c not in facet_criteria],
        aggregate=result if aggregate_spec is not None else None,
        comparison=result if compare_spec is not None else None,
        operation_notes=list(getattr(result, "notes", []) or []),
    )


# ── v2: a series related to recorded events or to a second series (C5) ──────────────────

#: How finely a relation buckets each series: a quarter of an hour tells a session from the quarter
#: after it; an hour is the usual grain of a correlation between two building series.
RELATE_EVENT_BUCKET_S = 900
RELATE_SERIES_BUCKET_S = 3600
#: The window a relation reads when the question names none, declared in the answer: the days up
#: to the newest event of the kind (so the window holds events), or the last days for two series.
RELATE_DEFAULT_EVENT_DAYS = 14
RELATE_DEFAULT_SERIES_DAYS = 7
#: The bound on the work, said in the answer whenever it binds: the longest window and the most
#: spaces one relation reads. 31 days x 96 quarter-hours x 40 spaces x 2 series is ~238k bucket rows.
RELATE_MAX_DAYS = 31
RELATE_MAX_SPACES = 40
#: The store layouts that can reduce a series into time buckets (aggregate_lane.bucket_statements).
_BUCKET_LAYOUTS = frozenset({"mysql_narrow", "mysql_wide", "pg_narrow"})


def _relation_window_bounds(
    spec: Any,
    events: Dict[str, List[Any]],
    now: Any,
    source_label: str,
    lag_s: float,
) -> Tuple[Any, Any, str, bool, List[str]]:
    """(start, end, label, partial, notes) on the stores' clock for the window a relation reads."""
    from datetime import datetime, timedelta

    from orchestrator.services.requested_interval import STAMP

    notes: List[str] = []
    partial = False
    if spec.window_start and spec.window_end:
        start = datetime.strptime(str(spec.window_start)[:19], STAMP)
        end = datetime.strptime(str(spec.window_end)[:19], STAMP)
        label = spec.window_label or "the period you named"
        if end > now:
            end, partial = now, True
            notes.append(f"{label} is not over: its figures cover its readings so far")
    elif spec.window_hours:
        end = now
        start = now - timedelta(hours=float(spec.window_hours))
        label = spec.window_label or f"the last {float(spec.window_hours):g} hours"
    elif source_label:
        started = [ev for evs_ in events.values() for ev in evs_ if ev.start <= now]
        if started:
            end = min(now, max(ev.end + timedelta(seconds=lag_s) for ev in started))
            end = max(end, max(ev.start for ev in started))
            start = end - timedelta(days=RELATE_DEFAULT_EVENT_DAYS)
            label = (
                f"the {RELATE_DEFAULT_EVENT_DAYS} days up to the last {source_label} recorded here"
            )
            notes.append(
                f"no period was named, so the {RELATE_DEFAULT_EVENT_DAYS} days up to the last "
                f"{source_label} recorded in these spaces were read"
            )
        else:
            end = now
            start = now - timedelta(days=RELATE_DEFAULT_EVENT_DAYS)
            label = f"the last {RELATE_DEFAULT_EVENT_DAYS} days"
            notes.append(
                f"no period was named, and no {source_label} recorded in these spaces has started "
                f"yet, so the last {RELATE_DEFAULT_EVENT_DAYS} days were read"
            )
    else:
        end = now
        start = now - timedelta(days=RELATE_DEFAULT_SERIES_DAYS)
        label = f"the last {RELATE_DEFAULT_SERIES_DAYS} days"
        notes.append(
            f"no period was named, so the last {RELATE_DEFAULT_SERIES_DAYS} days were read"
        )
    if end - start > timedelta(days=RELATE_MAX_DAYS):
        start = end - timedelta(days=RELATE_MAX_DAYS)
        notes.append(
            f"the window was cut to its most recent {RELATE_MAX_DAYS} days, the most one relation "
            "reads"
        )
    return start, end, label, partial, notes


async def _select_rows(sparql_exec, query: str) -> List[Dict[str, str]]:
    """SPARQL-JSON bindings as plain {variable: value} rows."""
    from orchestrator.services.deliberation.coverage_audit import _bindings, _val

    payload = await sparql_exec(query)
    out: List[Dict[str, str]] = []
    for binding in _bindings(payload if isinstance(payload, dict) else {}):
        out.append({var: _val(binding, var) for var in binding})
    return out


async def _run_relation(
    cqir: CQIR,
    catalogue,
    sparql_exec,
    *,
    schema: BuildingCapabilitySchema,
    candidates: List[Candidate],
    ledger: CoverageLedger,
    facet_checks: List[Any],
    facet_labels: Dict[int, str],
    unapplied: List[str],
    adapter_getter,
    timings: Dict[str, int],
    fingerprint: str,
    admission: AdmissionResult,
) -> ExecutionOutcome:
    """One series related to recorded events, a yes/no reading, or a second series (C5).

    The events are read from the graph in code (``event_sources.events_query``) and placed on the
    stores' clock; each series is reduced IN THE STORE into fixed time buckets over the whole
    window (``aggregate_lane.run_buckets``, the bucketed form of the reduction ``_run_period``
    reuses), so nothing is cut to its newest rows; the statistics are ``operations.relate``.
    """
    from datetime import timedelta

    from orchestrator.services import aggregate_lane as agl
    from orchestrator.services.deliberation import event_sources as evs
    from orchestrator.services.deliberation import operations as ops
    from orchestrator.services.deliberation.cqir import RelationKind
    from orchestrator.services.deliberation.facet_resolvers import facet_reader_label
    from orchestrator.services.requested_interval import STAMP, building_tz, store_now

    spec = cqir.relate
    t0 = time.time()
    tz_name = building_tz()
    now = store_now()
    series = catalogue.get(spec.series)
    modality = series.modality or spec.series.split(":", 1)[-1]
    other = catalogue.get(spec.other_series) if spec.other_series else None
    other_modality = (other.modality or other.key.split(":", 1)[-1]) if other is not None else None
    source = catalogue.get(spec.events) if spec.events else None
    co_movement = spec.relation == RelationKind.CO_MOVEMENT
    state = other is not None and spec.relation == RelationKind.DURING
    bucket_s = RELATE_SERIES_BUCKET_S if co_movement else RELATE_EVENT_BUCKET_S
    lag_s = float(spec.lag_minutes or 0.0) * 60.0 if spec.relation == RelationKind.AFTER else 0.0
    label = facet_reader_label(series) or spec.series
    other_label = facet_reader_label(other) if other is not None else ""
    source_label = (source.label or source.key) if source is not None else ""
    notes: List[str] = [
        f"'{u}' was not applied: a relation reads every reading in its window"
        for u in dict.fromkeys(unapplied)
        if u
    ]

    # 1. Who can contribute: a space whose hard facet requirements were verified, with the sensors.
    unverified = _unverified_on_facets(facet_checks, facet_labels)
    population = [c for c in candidates if c.space_iri not in unverified]
    needed = [modality] + ([other_modality] if other_modality else [])
    for m in needed:
        ledger.instrumented.setdefault(m, 0)
    _recount(ledger, population)
    held_back = sorted(
        f"{c.label} ({', '.join(unverified[c.space_iri])})"
        for c in candidates
        if c.space_iri in unverified
    )
    if held_back:
        notes.append(
            f"{len(held_back)} space(s) were not read because what you asked for could not be "
            f"verified for them: {', '.join(held_back[: ops.MAX_NAMED])}"
            + (
                f", and {len(held_back) - ops.MAX_NAMED} more"
                if len(held_back) > ops.MAX_NAMED
                else ""
            )
        )

    def missing_sensor(cand: Candidate) -> str:
        absent = [m.replace("_", " ") for m in needed if m not in (cand.sensors or {})]
        return f"no {' or '.join(absent)} sensor" if absent else ""

    # 2. The events, read in code for every space in scope, placed on the stores' clock.
    events_by_space: Dict[str, List[Any]] = {}
    counts = evs.EventCounts()
    if source is not None and population:
        rows = await _select_rows(
            sparql_exec,
            evs.events_query(source.record_class, source.roles, [c.space_iri for c in population]),
        )
        if len(rows) >= evs.MAX_EVENT_ROWS:
            notes.append(
                f"the {source_label} read reached its {evs.MAX_EVENT_ROWS}-row limit, so some "
                "may be missing from these figures"
            )
        events, counts = evs.assemble_events(rows, source.roles, tz_name, now)
        for ev in events:
            events_by_space.setdefault(ev.space_iri, []).append(ev)

    # 3. The window: the question's own, or a declared default.
    start, end, window_label, partial, window_notes = _relation_window_bounds(
        spec, events_by_space, now, source_label, lag_s
    )
    notes += window_notes

    # 4. The spaces read, and the bound on the work.
    inputs: List[ops.RelationInput] = []
    if source is not None:
        in_window = {
            iri: [
                ev for ev in evs_ if ev.start <= end and ev.end + timedelta(seconds=lag_s) >= start
            ]
            for iri, evs_ in events_by_space.items()
        }
        in_window = {iri: evs_ for iri, evs_ in in_window.items() if evs_}
        contributing = [c for c in population if c.space_iri in in_window and not missing_sensor(c)]
        for cand in population:
            if cand.space_iri in in_window and missing_sensor(cand):
                # The events happened here, but nothing measured them: named, never dropped.
                inputs.append(
                    ops.RelationInput(cand.space_iri, cand.label, reason=missing_sensor(cand))
                )
        quiet = sum(1 for c in population if c.space_iri not in in_window and not missing_sensor(c))
        if quiet:
            notes.append(
                f"{quiet} other space(s) in scope with a {modality.replace('_', ' ')} sensor have "
                f"no {source_label} recorded in the window"
            )
        if len(contributing) > RELATE_MAX_SPACES:
            ranked = sorted(
                contributing, key=lambda c: (-len(in_window[c.space_iri]), c.label.lower())
            )
            notes.append(
                f"{len(contributing)} spaces have {source_label} records and readings in the "
                f"window; the {RELATE_MAX_SPACES} with the most {source_label} records were read"
            )
            contributing = ranked[:RELATE_MAX_SPACES]
    else:
        in_window = {}
        contributing = [c for c in population if not missing_sensor(c)]
        absent = [c for c in population if missing_sensor(c)]
        for cand in absent:
            inputs.append(
                ops.RelationInput(cand.space_iri, cand.label, reason=missing_sensor(cand))
            )
        if len(contributing) > RELATE_MAX_SPACES:
            ordered = sorted(contributing, key=lambda c: (c.label.lower(), c.space_iri))
            step = len(ordered) / float(RELATE_MAX_SPACES)
            picked = [ordered[int(i * step)] for i in range(RELATE_MAX_SPACES)]
            notes.append(
                f"{len(contributing)} spaces have both readings; an evenly spread "
                f"{RELATE_MAX_SPACES} of them, in name order, were read"
            )
            contributing = picked

    # 5. Each series reduced in the store, bucket by bucket, over the whole window.
    window = agl.Window(start.strftime(STAMP), end.strftime(STAMP), window_label)
    storage: Dict[str, str] = {}
    uuid_of: Dict[Tuple[str, str], str] = {}
    for cand in contributing:
        for m in needed:
            handle = (cand.sensors or {}).get(m) or {}
            if handle.get("uuid") and handle.get("stored_at"):
                storage[handle["uuid"]] = handle["stored_at"]
                uuid_of[(cand.space_iri, m)] = handle["uuid"]
    if adapter_getter is None:  # pragma: no cover - live wiring
        from orchestrator.services.adapters.registry import adapter_registry

        adapter_getter = adapter_registry.get
    ready, unsupported_list = await agl._stores_ready(
        list(storage), storage, adapter_getter, lambda key: key
    )
    unsupported = set(unsupported_list)
    bands: Dict[str, Tuple[float, float]] = {}
    try:
        from orchestrator.services.physical_bands import band_for_modality

        for m in needed:
            band = band_for_modality(m, schema.building_id)
            if band is None:
                continue
            for (iri, mod), uuid in uuid_of.items():
                if mod == m:
                    bands[uuid] = (band.low, band.high)
    except Exception as exc:  # a band lookup never costs the answer
        logger.debug(f"[executor] physical bands for a relation unavailable: {exc}")
    buckets: Dict[str, Dict[int, ops.Bucket]] = {}
    failed: set = set()
    for _key, (adapter, members) in sorted(ready.items()):
        if agl.layout_of(adapter) not in _BUCKET_LAYOUTS:
            unsupported.update(members)
            continue
        got, bad = await agl.run_buckets(adapter, members, window, bucket_s, bands or None)
        failed.update(bad)
        for b in got:
            buckets.setdefault(b.uuid, {})[b.index] = ops.Bucket(b.n, b.total)

    # 6. The statistics.
    group_by = spec.group_by.value if spec.group_by is not None else ""
    for cand in contributing:
        reason = ""
        for m in needed:
            uuid = uuid_of.get((cand.space_iri, m))
            if uuid is None:
                reason = f"no {m.replace('_', ' ')} sensor with a store"
            elif uuid in unsupported:
                reason = "its readings are kept in a store this answer cannot reduce by time"
            elif uuid in failed:
                reason = "its readings could not be read just now"
            if reason:
                break
        uy = uuid_of.get((cand.space_iri, modality))
        ux = uuid_of.get((cand.space_iri, other_modality)) if other_modality else None
        inputs.append(
            ops.RelationInput(
                cand.space_iri,
                cand.label,
                groups=_group_keys(cand, spec.group_by) if spec.group_by is not None else [],
                series=dict(buckets.get(uy, {})) if uy else {},
                other=dict(buckets.get(ux, {})) if ux else {},
                events=[
                    ((ev.start - start).total_seconds(), (ev.end - start).total_seconds())
                    for ev in in_window.get(cand.space_iri, [])
                ],
                reason=reason,
            )
        )
    if counts.cancelled:
        notes.append(
            f"{counts.cancelled} cancelled {source_label} record(s) were left out: a cancelled "
            "event did not happen"
        )
    if counts.untimed:
        notes.append(
            f"{counts.untimed} {source_label} record(s) carry no time that can be read, so they "
            "could not be placed"
        )
    if counts.open_ended:
        notes.append(
            f"{counts.open_ended} {source_label} record(s) have no recorded end and are taken as "
            "still in force"
        )
    group_labels = (
        await _group_labels(population, spec.group_by, sparql_exec)
        if spec.group_by is not None
        else {}
    )
    result = ops.relate(
        spec.relation,
        inputs,
        bucket_seconds=bucket_s,
        series=spec.series,
        label=label,
        unit=ops.facet_unit(series),
        lag_seconds=lag_s,
        state=state,
        other=spec.other_series or "",
        other_label=other_label,
        other_unit=ops.facet_unit(other) if other is not None else "",
        events=spec.events or "",
        events_label=source_label,
        window=ops.PeriodWindow(
            label=window_label,
            start=window.start,
            end=window.end,
            shown=_shown(window.start, window.end, tz_name, partial),
            partial=partial,
        ),
        group_by=group_by,
        group_labels=group_labels,
        lag_default=(
            spec.relation == RelationKind.AFTER
            and getattr(spec.lag_source, "value", spec.lag_source) != "user"
        ),
        notes=notes,
    )
    if result.instants and spec.relation == RelationKind.DURING and not state:
        result.notes.append(
            f"{result.instants} of the {source_label} records are instants with no duration, so "
            "nothing is 'during' them; ask what happens after them instead"
        )
    timings["relation_ms"] = int((time.time() - t0) * 1000)
    try:  # every figure the relation computed is evidence for the claim binder
        from orchestrator.services.evidence import computed

        computed.record("deliberate_operation", ops.computed_figures(result))
    except Exception as exc:  # pragma: no cover - a recorder never costs the answer
        logger.debug(f"[executor] relation figures not recorded: {exc}")

    plan_hash = hashlib.sha256(
        (
            fingerprint
            + "|"
            + ",".join(sorted(c.space_iri for c in contributing))
            + f"|{window.start}..{window.end}|{bucket_s}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    logger.info(
        f"[executor] operation=relate plan={plan_hash} relation={spec.relation.value} "
        f"spaces={len(contributing)} compared={result.overall.spaces if result.overall else 0} "
        f"timings={timings}"
    )
    return ExecutionOutcome(
        score=ScoreResult(ranked=[], excluded=[]),
        ledger=ledger,
        candidates=candidates,
        plan_hash=plan_hash,
        plan_fingerprint=fingerprint,
        timings_ms=timings,
        facet_checks=facet_checks,
        facet_labels=_reader_labels(cqir, catalogue),
        not_assessable=list(getattr(admission, "not_assessable_notes", None) or []),
        relation=result,
        operation_notes=list(result.notes),
    )
