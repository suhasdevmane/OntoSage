"""
dossier.py — the proof-of-analysis artifact + numeric-consistency guard (V4-T23).

The EvidenceDossier is what elevates an answer from plausible to checkable: the
compiled interpretation (with every declared assumption), the coverage ledger,
the candidate × criterion evidence table (value, window, points, sensor uuid,
storage table, simulated flag), forecast records, the scoring terms (citations,
tie-break, sensitivity) and the deterministic plan hash.

The renderer produces prose by TEMPLATE with numbers substituted
programmatically. numeric_guard() then enforces the invariant behind the
fabrication-rate claim: every number in the prose must exist in the dossier —
a violating sentence is rejected by the caller, never shipped.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from orchestrator.services.deliberation.clarify_policy import (
    Assumption,
    ClarifyDecision,
)
from orchestrator.services.deliberation.cqir import CQIR
from orchestrator.services.deliberation.plan_executor import ExecutionOutcome
from shared.utils import get_logger

logger = get_logger(__name__)


class DossierAssumption(BaseModel):
    text: str
    source: str = ""


class DossierConstraint(BaseModel):
    phrase: str = ""
    modality: str
    direction: str
    hardness: str
    threshold: Optional[float] = None
    threshold_source: str = ""


class DossierEvidenceRow(BaseModel):
    space: str
    modality: str
    value: float
    basis: str
    window_hours: float
    n_points: int
    sensor_uuid: str
    stored_at: str
    simulated: Optional[bool] = None  # None = provenance not declared for the table
    #: When the newest reading behind this value was taken (V6-T37).
    latest: str = ""


class DossierRanked(BaseModel):
    rank: int
    space: str
    floor: str
    total: float
    proximity_m: Optional[float] = None
    criteria: Dict[str, Optional[float]] = Field(default_factory=dict)  # modality -> value
    data_gaps: List[str] = Field(default_factory=list)


class DossierExcluded(BaseModel):
    space: str
    reason: str


class DossierForecast(BaseModel):
    space: str
    modality: str
    model: str
    horizon_hours: float
    forecast_value: float
    history_points: int
    # V5-T12 — present when the ModelSelector adapter produced the forecast
    ci80: Optional[Tuple[float, float]] = None
    ci95: Optional[Tuple[float, float]] = None
    backtest_mae: Optional[float] = None
    n_train: int = 0


class DossierEventCheck(BaseModel):
    """V5-T25 — availability/booking-pressure evidence for one candidate."""

    space: str
    kind: str
    free: Optional[bool] = None
    detail: str = ""
    window_hours: float = 0.0


class EvidenceDossier(BaseModel):
    building_id: str
    raw_query: str
    decision: str
    constraints: List[DossierConstraint] = Field(default_factory=list)
    assumptions: List[DossierAssumption] = Field(default_factory=list)
    coverage_summary: str = ""
    coverage_excluded: List[DossierExcluded] = Field(default_factory=list)
    evidence: List[DossierEvidenceRow] = Field(default_factory=list)
    ranked: List[DossierRanked] = Field(default_factory=list)
    scoring_citations: List[str] = Field(default_factory=list)
    tie_break_rule: str = ""
    top1_stable: Optional[bool] = None
    forecasts: List[DossierForecast] = Field(default_factory=list)
    event_checks: List[DossierEventCheck] = Field(default_factory=list)
    # V5-T39 — privacy provenance: policies the PDP applied to this answer
    applied_policies: List[str] = Field(default_factory=list)
    plan_hash: str = ""
    plan_fingerprint: str = ""
    timings_ms: Dict[str, int] = Field(default_factory=dict)


def build_dossier(
    cqir: CQIR,
    decision: ClarifyDecision,
    outcome: ExecutionOutcome,
    building_id: str,
    synthetic_lookup: Optional[Callable[[str], Optional[bool]]] = None,
    applied_policies: Optional[List[str]] = None,
) -> EvidenceDossier:
    """Assemble the dossier from the executed outcome. Pure re-shaping — no new numbers."""
    label_by_iri = {c.space_iri: c.label for c in outcome.candidates}
    ranked = [
        DossierRanked(
            rank=s.rank or 0,
            space=s.label,
            floor=s.floor,
            total=s.total or 0.0,
            proximity_m=None if s.proximity_m is None else round(s.proximity_m, 1),
            criteria={c.modality: c.value for c in s.criteria},
            data_gaps=list(s.data_gaps),
        )
        for s in outcome.score.ranked
    ]
    excluded = [
        DossierExcluded(space=e.label, reason=e.reason) for e in outcome.ledger.excluded
    ] + [
        DossierExcluded(space=s.label, reason=s.excluded_reason or "excluded")
        for s in outcome.score.excluded
    ]
    citations = sorted({c.citation for s in outcome.score.ranked for c in s.criteria if c.citation})
    return EvidenceDossier(
        building_id=building_id,
        raw_query=cqir.raw_query,
        decision=cqir.decision.value,
        constraints=[
            DossierConstraint(
                phrase=c.source_phrase,
                modality=c.modality,
                direction=c.direction.value,
                hardness=c.hardness.value,
                threshold=c.threshold,
                threshold_source=c.threshold_source.value,
            )
            for c in cqir.constraints
        ],
        assumptions=[DossierAssumption(text=a.text, source=a.source) for a in decision.assumptions]
        + [
            DossierAssumption(text=note, source="events")
            for note in getattr(outcome, "event_notes", [])
        ],
        coverage_summary=outcome.ledger.summary(),
        coverage_excluded=excluded,
        evidence=[
            DossierEvidenceRow(
                space=label_by_iri.get(e.space_iri, e.space_iri),
                modality=e.modality,
                value=e.value,
                basis=e.basis,
                window_hours=e.window_hours,
                n_points=e.n_points,
                sensor_uuid=e.uuid,
                stored_at=e.stored_at,
                simulated=synthetic_lookup(e.stored_at) if synthetic_lookup else None,
                latest=getattr(e, "latest", "") or "",
            )
            for e in outcome.evidence
        ],
        ranked=ranked,
        scoring_citations=citations,
        tie_break_rule=outcome.score.tie_break_rule,
        top1_stable=outcome.score.top1_stable_under_weight_perturbation,
        forecasts=[
            DossierForecast(
                space=label_by_iri.get(f.space_iri, f.space_iri),
                modality=f.modality,
                model=f.model,
                horizon_hours=f.horizon_hours,
                forecast_value=f.forecast_value,
                history_points=f.history_points,
                ci80=getattr(f, "ci80", None),
                ci95=getattr(f, "ci95", None),
                backtest_mae=getattr(f, "backtest_mae", None),
                n_train=getattr(f, "n_train", 0),
            )
            for f in outcome.forecasts
        ],
        event_checks=[
            DossierEventCheck(
                space=label_by_iri.get(ec.space_iri, ec.space_iri.rsplit("#", 1)[-1]),
                kind=ec.kind,
                free=ec.free,
                detail=ec.detail,
                window_hours=ec.window_hours,
            )
            for ec in getattr(outcome, "event_checks", [])
        ],
        applied_policies=list(applied_policies or []),
        plan_hash=outcome.plan_hash,
        plan_fingerprint=getattr(outcome, "plan_fingerprint", ""),
        timings_ms=dict(outcome.timings_ms),
    )


def render_answer(dossier: EvidenceDossier, top_k: int = 3) -> str:
    """Deterministic prose: every number is substituted from the dossier itself."""
    if not dossier.ranked:
        lines = ["I couldn't rank any spaces for this request."]
        if dossier.coverage_excluded:
            lines.append(
                f"{len(dossier.coverage_excluded)} spaces were excluded — see the evidence dossier."
            )
        return "\n".join(lines)

    lines: List[str] = []
    top = dossier.ranked[: max(1, top_k)]
    best = top[0]
    lines.append(f"**Best match: {best.space}** (floor {best.floor}, score {best.total:g}).")
    for s in top:
        crits = ", ".join(f"{m}: {v:g}" for m, v in sorted(s.criteria.items()) if v is not None)
        prox = (
            f", {s.proximity_m:g} m to the requested amenity" if s.proximity_m is not None else ""
        )
        gaps = f" (no data: {', '.join(s.data_gaps)})" if s.data_gaps else ""
        lines.append(f"{s.rank}. **{s.space}** — score {s.total:g} ({crits}{prox}){gaps}")
    if dossier.assumptions:
        lines.append("")
        lines.append("**Assumptions:** " + "; ".join(a.text for a in dossier.assumptions) + ".")
    lines.append(f"**Coverage:** {dossier.coverage_summary}.")
    if dossier.forecasts:
        f0 = dossier.forecasts[0]
        extra = ""
        if f0.ci95 is not None:
            extra += f", 95% CI {f0.ci95[0]:g}–{f0.ci95[1]:g}"
        if f0.backtest_mae is not None:
            extra += f", backtest MAE {f0.backtest_mae:g}"
        lines.append(
            f"Forecasts: {len(dossier.forecasts)} series projected {f0.horizon_hours:g}h ahead "
            f"({f0.model}{extra})."
        )
    free_checks = [ec for ec in dossier.event_checks if ec.kind == "free_window"]
    if free_checks:
        n_free = sum(1 for ec in free_checks if ec.free)
        lines.append(
            f"Availability: {n_free} of {len(free_checks)} candidate(s) free for the next "
            f"{free_checks[0].window_hours:g}h (booked spaces are listed under exclusions)."
        )
    if dossier.applied_policies:
        lines.append(
            "**Privacy:** computed under access policy — " + "; ".join(dossier.applied_policies)
        )
    if dossier.top1_stable is not None:
        lines.append(
            "The top choice is stable under ±25% preference-weight changes."
            if dossier.top1_stable
            else "Note: the top choice can flip under ±25% preference-weight changes — "
            "the leading options are close."
        )
    return "\n".join(lines)


def render_dossier_details(dossier: EvidenceDossier, max_rows: int = 12) -> str:
    """Collapsible 'How I worked this out' markdown block (Open WebUI renders
    <details>). Every number comes from the dossier, so the numeric guard holds
    over the full message."""
    lines: List[str] = [
        "",
        "<details>",
        "<summary>How I worked this out (evidence dossier)</summary>",
        "",
        # the plan hash stays in the structured payload only — its hex digits
        # would read as numbers to the guard, and it is an identifier, not a figure
        f"*Decision: {dossier.decision} over {len(dossier.ranked)} ranked candidates; "
        "plan fingerprint in the evidence payload.*",
        "",
        "| space | modality | value | basis | points | source table | simulated |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in dossier.evidence[:max_rows]:
        simulated = "yes" if e.simulated else ("no" if e.simulated is False else "undeclared")
        lines.append(
            f"| {e.space} | {e.modality} | {e.value:g} | {e.basis} "
            f"| {e.n_points} | {e.stored_at} | {simulated} |"
        )
    if len(dossier.evidence) > max_rows:
        lines.append("| … | | | further rows in the evidence payload | | | |")
    if dossier.coverage_excluded:
        lines.append("")
        lines.append(
            "**Excluded:** "
            + "; ".join(f"{x.space} ({x.reason})" for x in dossier.coverage_excluded[:6])
        )
    if dossier.scoring_citations:
        lines.append("")
        lines.append("**Scoring bands:** " + " · ".join(dossier.scoring_citations))
    lines += ["", "</details>"]
    return "\n".join(lines)


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _allowed_numbers(dossier: EvidenceDossier) -> set:
    allowed = set()

    def add(x) -> None:
        if x is None:
            return
        try:
            v = float(x)
        except (TypeError, ValueError):
            return
        for s in (
            f"{v:g}",
            f"{v:.1f}",
            f"{v:.2f}",
            f"{v:.3f}",
            str(int(v)) if v == int(v) else None,
        ):
            if s is not None:
                allowed.add(s.lstrip("-"))

    for r in dossier.ranked:
        add(r.rank), add(r.total), add(r.proximity_m), add(r.floor and None)
        for v in r.criteria.values():
            add(v)
    for e in dossier.evidence:
        add(e.value), add(e.window_hours), add(e.n_points)
    for f in dossier.forecasts:
        add(f.horizon_hours), add(f.forecast_value), add(f.history_points)
        add(f.backtest_mae), add(f.n_train)
        for level, band in (("80", f.ci80), ("95", f.ci95)):
            if band is not None:
                add(band[0]), add(band[1])
                allowed.add(level)  # the "95" in "95% CI" is backed by the band itself
    for c in dossier.constraints:
        add(c.threshold)
    for ec in dossier.event_checks:
        add(ec.window_hours)
    if dossier.event_checks:
        free_ecs = [ec for ec in dossier.event_checks if ec.kind == "free_window"]
        add(len(free_ecs)), add(sum(1 for ec in free_ecs if ec.free))
    add(len(dossier.forecasts)), add(len(dossier.coverage_excluded))
    # numbers appearing inside dossier text fields (coverage summary, assumptions,
    # citations, floors) are legitimate quotations of dossier content
    text_blobs = (
        [dossier.coverage_summary, dossier.tie_break_rule]
        + [a.text for a in dossier.assumptions]
        + [c for c in dossier.scoring_citations]
        + [r.floor for r in dossier.ranked]
        + [r.space for r in dossier.ranked]
        + [e.space for e in dossier.evidence]
        + [x.space for x in dossier.coverage_excluded]
        + [x.reason for x in dossier.coverage_excluded]
        + [ec.detail for ec in dossier.event_checks]
        + [ec.space for ec in dossier.event_checks]
        + list(dossier.applied_policies)
    )
    for blob in text_blobs:
        for tok in _NUM_RE.findall(blob or ""):
            allowed.add(tok.lstrip("-"))
    return allowed


#: numbers that carry no factual claim (list indices, the 25% sensitivity band)
_INNOCUOUS = {"25", "1", "2", "3"}


def numeric_guard(prose: str, dossier: EvidenceDossier) -> List[str]:
    """Every number in the prose must exist in the dossier. Returns violations.

    Inline code spans (`...`) are stripped first: back-ticked technical
    identifiers (uuids, hashes) are not factual figures.
    """
    allowed = _allowed_numbers(dossier)
    scannable = re.sub(r"`[^`]*`", " ", prose or "")
    violations = []
    for tok in _NUM_RE.findall(scannable):
        t = tok.lstrip("-")
        if t in allowed or t in _INNOCUOUS:
            continue
        # tolerate trailing-zero variants (35.0 vs 35)
        try:
            if f"{float(t):g}" in allowed:
                continue
        except ValueError:
            pass
        violations.append(tok)
    if violations:
        logger.warning(f"[dossier] numeric guard violations: {violations}")
    return violations
