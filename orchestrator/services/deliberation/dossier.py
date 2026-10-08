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
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from orchestrator.services.deliberation.clarify_policy import Assumption, ClarifyDecision
from orchestrator.services.deliberation.cqir import CQIR
from orchestrator.services.deliberation.operations import (
    AggregateResult,
    CompareResult,
    GroupResult,
    PeriodFigure,
    PeriodResult,
    RelationFigure,
    RelationResult,
    fmt,
    with_unit,
)
from orchestrator.services.deliberation.plan_executor import ExecutionOutcome
from shared.utils import get_logger

logger = get_logger(__name__)

#: How many not-comparable spaces a comparison names before it counts the rest ("and N more").
#: One constant for the renderer and the numeric guard, so the count it prints is always backed.
_NOT_COMPARABLE_NAMED = 8
#: Below this many spaces a group's figure leads an answer with a caveat and a larger-group lead.
_SMALL_GROUP = 3


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


class DossierFacetValue(BaseModel):
    """v2 — one facet criterion's value for one space, with where it came from."""

    facet: str
    label: str = ""
    display: str = ""  # "seat count: 16"
    status: str = ""  # met | unmet | unknown
    provenance: str = ""  # "WorkspaceProfile WS-07"
    hardness: str = ""


class DossierRanked(BaseModel):
    rank: int
    space: str
    floor: str
    total: float
    proximity_m: Optional[float] = None
    criteria: Dict[str, Optional[float]] = Field(default_factory=dict)  # modality -> value
    data_gaps: List[str] = Field(default_factory=list)
    #: The reader's word for this space's kind when it is one somebody holds — "laboratory",
    #: "office". Empty when anyone may walk in. Set from the space's own class, never shown
    #: as a class name.
    access_controlled_as: str = ""
    #: v2 — the facet criteria's values for this space, beside its readings. Sensor readings
    #: stay in ``criteria``; nothing here is a sensor value.
    facets: List[DossierFacetValue] = Field(default_factory=list)
    #: v2 — hard facet criteria with no recorded value for this space: never presented as met.
    unverified: List[str] = Field(default_factory=list)


class DossierFacetCriterion(BaseModel):
    """v2 — one facet criterion of the compiled plan, as the dossier records it."""

    phrase: str = ""
    facet: str
    label: str = ""
    source_kind: str = ""  # record | ttl | event | spatial
    operator: str
    value: Optional[Any] = None
    hardness: str = ""
    record_group: Optional[str] = None
    threshold_source: str = ""
    #: False when the criterion was NOT checked (not assessable, or folded into the v1
    #: availability check): the answer names it under "Not checked", never as a source.
    checked: bool = True


class DossierFacetRow(BaseModel):
    """v2 — one cell of the evidence matrix's facet columns: space x criterion."""

    space: str
    facet: str
    label: str = ""
    display: str = ""
    status: str = ""
    provenance: str = ""
    hardness: str = ""


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
    #: What the executor said the reader could DO about a refusal. The plan executor
    #: already writes this — "narrow it to a floor and I can answer it directly" — and
    #: nothing carried it to the answer, so a question over the fetch budget came back as
    #: "I couldn't rank any spaces for this request" and stopped there. The advice was
    #: written, tested and unreachable, which is the shape this project keeps paying for.
    guidance_notes: List[str] = Field(default_factory=list)
    #: Values the executor refused to rank on because they cannot be a reading of the
    #: quantity they were filed under. Shown, never hidden: a ranking computed over the
    #: survivors and presented bare reads as a ranking over everything.
    impossible_readings: List[str] = Field(default_factory=list)
    #: Criteria whose readings run past the end of the range this answer scores them
    #: against, so the ranking cannot separate the spaces on them. Shown next to the list,
    #: because the band is quoted in the same answer and the reader can otherwise see a
    #: figure of 24 sitting under a stated 0-8 range with nothing said about it.
    band_notes: List[str] = Field(default_factory=list)
    #: Set when this lane must not answer at all (a route question). The renderer ships this
    #: sentence and nothing else — no ranking, no evidence table.
    refusal: str = ""
    #: v2 — the plan's facet criteria. Empty for every v1 plan, and then nothing below it is
    #: rendered: the answer is the v1 answer byte for byte.
    facet_criteria: List[DossierFacetCriterion] = Field(default_factory=list)
    #: v2 — every facet check the executor made (the evidence matrix's facet columns).
    facet_evidence: List[DossierFacetRow] = Field(default_factory=list)
    #: v2 — criteria that could not be assessed at all, one sentence each.
    not_assessable: List[str] = Field(default_factory=list)
    #: v2 — how facet criteria were scored and how widely they are recorded.
    facet_notes: List[str] = Field(default_factory=list)
    #: v2 — the operation the plan ran instead of ranking spaces ("aggregate_rank",
    #: "compare_facets"); "" for every ranking plan, and then nothing below is rendered.
    operation: str = ""
    #: v2 — the groups, their figures with n, and the dispersion of an aggregate plan.
    aggregate: Optional[AggregateResult] = None
    #: v2 — the side-by-side rows, the spaces not comparable and the total of a comparison.
    comparison: Optional[CompareResult] = None
    #: v2 — both periods' figures, overall and per group, and the spaces not compared (C4).
    periods: Optional[PeriodResult] = None
    #: v2 — a series related to recorded events or to a second series, every figure with its n (C5).
    relation: Optional[RelationResult] = None


def readable_space(name: str) -> str:
    """A space's own name, never its IRI.

    Row 99 of the 2026-09-17 stakeholder read showed a visitor an evidence table whose every
    row began `http://…#Room0.01`. The IRI is the key the pipeline joins on; it is not a
    place, and a reader has no use for it. The label is used wherever one is known and the
    local part of the IRI stands in where one is not — so an unlabelled space still reads as
    a room number rather than as a URL.
    """
    text = str(name or "").strip()
    if not text:
        return ""
    if "#" in text:
        text = text.rsplit("#", 1)[-1]
    elif text.startswith("http://") or text.startswith("https://"):
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text


def build_dossier(
    cqir: CQIR,
    decision: ClarifyDecision,
    outcome: ExecutionOutcome,
    building_id: str,
    synthetic_lookup: Optional[Callable[[str], Optional[bool]]] = None,
    applied_policies: Optional[List[str]] = None,
) -> EvidenceDossier:
    """Assemble the dossier from the executed outcome. Pure re-shaping — no new numbers."""
    from orchestrator.services.deliberation.candidates import access_word

    label_by_iri = {c.space_iri: c.label for c in outcome.candidates}
    kinds_by_iri = {c.space_iri: tuple(getattr(c, "kinds", ()) or ()) for c in outcome.candidates}

    # v2 — the facet side of the evidence matrix. Every structure below is empty for a v1 plan.
    facet_criteria = list(getattr(cqir, "facet_criteria", None) or [])
    facet_keys = {c.facet for c in facet_criteria}
    facet_labels = dict(getattr(outcome, "facet_labels", None) or {})
    facet_checks = list(getattr(outcome, "facet_checks", None) or [])
    checks_by_iri: Dict[str, List[Any]] = {}
    for check in facet_checks:
        checks_by_iri.setdefault(check.space_iri, []).append(check)
    excluded_labels = {
        getattr(e, "space_iri", ""): getattr(e, "label", "") for e in outcome.ledger.excluded
    }

    def _facet_value(check) -> "DossierFacetValue":
        return DossierFacetValue(
            facet=check.criterion.facet,
            label=check.label or facet_labels.get(check.criterion.facet, check.criterion.facet),
            display=check.display,
            status=check.status,
            provenance=", ".join(check.provenance),
            hardness=check.hardness,
        )

    def _ranked_entry(s) -> "DossierRanked":
        # G5 (2026-10-04): a duplicate constraint for one modality can put BOTH a
        # real-valued and a None-valued CriterionScore for it in `s.criteria` (a list).
        # A plain `{c.modality: c.value for c in s.criteria}` keeps whichever comes LAST,
        # which can be the None one -- silently dropping a real measurement from the row
        # (and, before this fix, leaving the gap note that then contradicted the OTHER
        # dict-building order). A real value must never be overwritten by a None for the
        # same modality, in either order.
        _criteria: Dict[str, Optional[float]] = {}
        for c in s.criteria:
            if c.modality in facet_keys:
                continue  # v2: a facet value is shown with its record, never as a reading
            if c.modality not in _criteria or c.value is not None:
                _criteria[c.modality] = c.value
        # G5 (2026-10-04): `s.criteria` is a LIST, and a duplicate constraint for one
        # modality (the same question naming it two ways -- "quiet" and, separately, a
        # second term that also resolves to the same modality) can put one real-valued
        # CriterionScore and one None-valued one in it. The dict comprehension above keeps
        # whichever comes last; `s.data_gaps` is a SEPARATE list appended independently of
        # the dict, so a modality the scorer found a value for could still be listed as
        # "no data" -- a row reading "(noise: 60.342, occupancy_status: 0.776) (no data:
        # occupancy_status)", contradicting itself in one sentence. The gap marker must
        # come from the SAME structure as the value: a modality present with a real number
        # in `_criteria` is not a gap, whatever the separate list says.
        _gaps = [m for m in s.data_gaps if _criteria.get(m) is None]
        return DossierRanked(
            rank=s.rank or 0,
            space=s.label,
            floor=s.floor,
            total=s.total or 0.0,
            proximity_m=None if s.proximity_m is None else round(s.proximity_m, 1),
            criteria=_criteria,
            data_gaps=_gaps,
            access_controlled_as=access_word(kinds_by_iri.get(s.space_iri, ())),
            facets=[
                _facet_value(c)
                for c in sorted(checks_by_iri.get(s.space_iri, []), key=lambda c: c.index)
            ],
            unverified=list(getattr(s, "unverified_hard", None) or []),
        )

    ranked = [_ranked_entry(s) for s in outcome.score.ranked]
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
                space=label_by_iri.get(e.space_iri) or readable_space(e.space_iri),
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
                space=label_by_iri.get(f.space_iri) or readable_space(f.space_iri),
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
                space=label_by_iri.get(ec.space_iri) or readable_space(ec.space_iri),
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
        refusal=str(getattr(outcome, "refusal", "") or ""),
        timings_ms=dict(outcome.timings_ms),
        guidance_notes=[str(n) for n in (getattr(outcome, "event_notes", None) or [])],
        impossible_readings=[
            str(n) for n in (getattr(outcome, "impossible_readings", None) or []) if n
        ],
        band_notes=[str(n) for n in (getattr(outcome, "band_notes", None) or []) if n],
        facet_criteria=[
            DossierFacetCriterion(
                phrase=c.source_phrase,
                facet=c.facet,
                label=facet_labels.get(c.facet) or c.source_phrase or c.facet,
                source_kind=c.facet.split(":", 1)[0] if ":" in c.facet else "",
                operator=c.operator.value,
                value=c.value,
                hardness=c.hardness.value,
                record_group=c.record_group,
                threshold_source=c.threshold_source.value,
                checked=c.facet not in set(getattr(outcome, "facet_skipped", None) or []),
            )
            for c in facet_criteria
        ],
        facet_evidence=[
            DossierFacetRow(
                space=label_by_iri.get(c.space_iri)
                or excluded_labels.get(c.space_iri)
                or readable_space(c.space_iri),
                facet=c.criterion.facet,
                label=c.label or facet_labels.get(c.criterion.facet, c.criterion.facet),
                display=c.display,
                status=c.status,
                provenance=", ".join(c.provenance),
                hardness=c.hardness,
            )
            for c in facet_checks
        ],
        not_assessable=[str(n) for n in (getattr(outcome, "not_assessable", None) or []) if n],
        facet_notes=[str(n) for n in (getattr(outcome, "facet_notes", None) or []) if n],
        operation=str(getattr(cqir, "operation", None) or ""),
        aggregate=getattr(outcome, "aggregate", None),
        comparison=getattr(outcome, "comparison", None),
        periods=getattr(outcome, "periods", None),
        relation=getattr(outcome, "relation", None),
    )


def _join(words: List[str]) -> str:
    """An English list — "a, b and c" — never a bare comma-joined one."""
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def _access_note(dossier: "EvidenceDossier", top: List[DossierRanked]) -> str:
    """One sentence when the rooms offered are ones somebody holds.

    Run-3 row 99 (2026-09-17) answered an undergraduate asking where to find "a calm,
    relatively quiet place ... close to my 4 p.m. class" with three research laboratories,
    and row 58 answered "which authorised seating area" with an academic office. The
    readings were right and the recommendation was unusable: a person cannot act on a room
    they may not enter, and the answer said nothing about it either way.

    Only for a question that asks where the ASKER may go. "Which space has the best
    conditions for focused work this afternoon?" is a survey of the building and an office
    is a perfectly good answer to it, so that ranking is left alone.
    """
    from orchestrator.services.deliberation.candidates import asks_where_i_may_go

    if not asks_where_i_may_go(dossier.raw_query):
        return ""
    held = [s for s in top if s.access_controlled_as]
    if not held:
        return ""
    rooms = _join([s.space for s in held])
    words = sorted({s.access_controlled_as for s in held})
    kinds = " or ".join(("an " if w[0] in "aeiou" else "a ") + w for w in words)
    every = "each of those is" if len(held) > 1 else "that is"
    return (
        f"**Check you can use it first.** {rooms} — {every} {kinds} someone else holds, "
        "not a room anyone may walk into. Readings describe what a room is like; they do "
        "not say who may be in it, and the building's records do not show you having the "
        "use of one. If you want somewhere you can simply go, ask me for a room that is "
        "open to everyone and I will rank only those."
    )


def _score_phrase(total: Optional[float], explain: bool = False) -> str:
    """A score with its meaning attached, at least once per answer.

    "score 0" told row 58's reader nothing: not the scale, not the direction, not whether 0
    was bad or simply the bottom of a band. The number is a weighted fit to the request on a
    0-to-1 scale, and one clause says so.
    """
    value = f"score {float(total or 0.0):g}"
    return f"{value} out of 1, where 1 fits everything you asked for" if explain else value


# ── v2: facet criteria in the answer ─────────────────────────────────────────────────────

#: Where a facet's value comes from, in the reader's words, by the facet key's source prefix.
_SOURCE_WORDS = {
    "record": "records",
    "ttl": "the building model",
    "event": "bookings",
    "spatial": "the building model",
}


def _source_of(criterion: "DossierFacetCriterion") -> str:
    if criterion.source_kind == "spatial" and criterion.facet != "spatial:floor":
        return "route records"
    return _SOURCE_WORDS.get(criterion.source_kind, "records")


def _facet_segment(row: DossierRanked) -> Tuple[str, List[str]]:
    """(the recorded values shown beside a space's readings, the criteria not recorded for it).

    Values from the same record are shown together with that record's id, so "a projector
    that is ready" reads as one component -- kind and state -- not two unrelated facts.
    """
    by_source: Dict[str, List[str]] = {}
    unknown: List[str] = []
    for value in row.facets:
        if value.status == "unknown":
            if value.label not in unknown:
                unknown.append(value.label)
            continue
        text = value.display + (" — not what you asked for" if value.status == "unmet" else "")
        bucket = by_source.setdefault(value.provenance, [])
        if text not in bucket:
            bucket.append(text)
    parts = [
        ", ".join(texts) + (f" ({source})" if source else "") for source, texts in by_source.items()
    ]
    return " · ".join(parts), unknown


def _facet_lines(dossier: EvidenceDossier, top: List[DossierRanked]) -> List[str]:
    """The ranked list of a facet plan: each space's readings, then its recorded values."""
    lines: List[str] = []
    for s in top:
        crits = ", ".join(f"{m}: {v:g}" for m, v in sorted(s.criteria.items()) if v is not None)
        prox = f"{s.proximity_m:g} m to the requested amenity" if s.proximity_m is not None else ""
        facets, unknown = _facet_segment(s)
        shown = "; ".join(p for p in (crits, prox) if p)
        unverified = [u for u in s.unverified if u]
        score = _score_phrase(s.total) + (" on what could be checked" if unverified else "")
        gaps = f" (no data: {', '.join(s.data_gaps)})" if s.data_gaps else ""
        lines.append(
            f"{s.rank}. **{s.space}** — {score}"
            + (f" ({shown})" if shown else "")
            + (f" · {facets}" if facets else "")
            + gaps
        )
        soft_unknown = [u for u in unknown if u not in unverified]
        if unverified:
            lines.append(
                f"   - **Not verified for {s.space}:** {_join(unverified)} — not recorded, so "
                "not counted as met; ranked below every space where it is recorded."
            )
        if soft_unknown:
            lines.append(f"   - {_join(soft_unknown)} not recorded for {s.space}.")
    return lines


def _facet_footer(dossier: EvidenceDossier) -> List[str]:
    """Which criteria came from records and which from sensors; what could not be checked."""
    lines: List[str] = []
    sources: Dict[str, List[str]] = {}
    sensed = sorted({c.modality for c in dossier.constraints})
    if sensed:
        sources["sensors"] = sensed
    for criterion in dossier.facet_criteria:
        if not criterion.checked:
            continue  # named under "Not checked", never as a source
        words = sources.setdefault(_source_of(criterion), [])
        label = criterion.label or criterion.phrase or "a recorded criterion"
        if label not in words:
            words.append(label)
    free_checks = [ec for ec in dossier.event_checks if ec.kind == "free_window"]
    if free_checks:
        # availability the deterministic fold checked (v1's path) is a bookings criterion too
        words = sources.setdefault("bookings", [])
        phrase = f"free for the next {free_checks[0].window_hours:g} h"
        if phrase not in words:
            words.append(phrase)
    if sources:
        lines.append(
            "**Where each criterion came from:** "
            + "; ".join(f"{source} — {', '.join(words)}" for source, words in sources.items())
            + "."
        )
    if dossier.not_assessable:
        lines.append(
            "**Not checked:** "
            + " ".join(n[:1].upper() + n[1:].rstrip(".") + "." for n in dossier.not_assessable)
            + " The ranking above does not use it."
        )
    if dossier.facet_notes:
        lines.append(
            "**About the recorded criteria:** "
            + " ".join(n[:1].upper() + n[1:].rstrip(".") + "." for n in dossier.facet_notes)
        )
    return lines


def _render_facet_answer(dossier: EvidenceDossier, top_k: int) -> str:
    """The answer for a plan with facet criteria (v2). Every number comes from the dossier."""
    if not dossier.ranked:
        lines = ["I couldn't rank any spaces for this request."]
        reasons: List[str] = []
        for entry in dossier.coverage_excluded:
            reason = str(getattr(entry, "reason", "") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if reasons:
            lines.append("")
            lines.append("**Why:** " + "; ".join(reasons[:3]) + ".")
        for note in dossier.guidance_notes[:2]:
            lines.append("")
            lines.append(str(note))
        footer = _facet_footer(dossier)
        if footer:
            lines.append("")
            lines.extend(footer)
        return "\n".join(lines)

    top = dossier.ranked[: max(1, top_k)]
    best = top[0]
    totals = {round(s.total or 0.0, 6) for s in dossier.ranked}
    flat = len(dossier.ranked) > 1 and len(totals) == 1
    # A TIE AT THE TOP IS A TIE (BUG-868's rule, kept for facets): when the leading verified
    # spaces score the same, the order between them is alphabetical and no "best match" exists.
    # Filters make this the ordinary case -- every room that meets "at least 12 seats" scores 1.
    tied_top = (
        not best.unverified
        and len(dossier.ranked) > 1
        and not dossier.ranked[1].unverified
        and round(dossier.ranked[1].total or 0.0, 6) == round(best.total or 0.0, 6)
    )
    lines: List[str] = []
    if best.unverified:
        lines.append(
            f"**No space is confirmed on everything you asked for.** The closest is "
            f"**{best.space}** (floor {best.floor}) — {_join(best.unverified)} could not be "
            "checked for it."
        )
    elif flat or tied_top:
        if (best.total or 0.0) >= 1.0:
            lines.append(
                "**These spaces each meet everything you asked for that could be checked**; "
                "the order below is not a preference between them:"
            )
        else:
            lines.append(
                "**What you asked for does not separate the leading spaces**; the order below "
                "is not a preference between them:"
            )
        if len(dossier.ranked) > len(top) and round(
            dossier.ranked[len(top)].total or 0.0, 6
        ) == round(best.total or 0.0, 6):
            lines.append("Others score the same — every one is in the evidence dossier.")
    else:
        lines.append(
            f"**Best match: {best.space}** (floor {best.floor}, "
            f"{_score_phrase(best.total, explain=True)})."
        )
    for note in dossier.guidance_notes[:2]:
        lines.append(str(note))
    lines.extend(_facet_lines(dossier, top))
    for note in dossier.impossible_readings:
        lines.append("")
        lines.append(str(note))
    access_note = _access_note(dossier, top)
    if access_note:
        lines.append("")
        lines.append(access_note)
    if dossier.band_notes:
        lines.append("")
        lines.append(" ".join(str(n) for n in dossier.band_notes))
    lines.append("")
    lines.extend(_facet_footer(dossier))
    if dossier.assumptions:
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
            "**Privacy:** computed under this building's access rules for your role, which "
            "limit how finely individual readings can be shown."
        )
    if dossier.top1_stable is not None and not (flat or tied_top):
        lines.append(
            "The top choice is stable under ±25% preference-weight changes."
            if dossier.top1_stable
            else "Note: the top choice can flip under ±25% preference-weight changes — "
            "the leading options are close."
        )
    return "\n".join(lines)


def _facet_attr(dossier: Any, name: str) -> list:
    """A v2 dossier field, or [] for a dossier-shaped object that predates it."""
    return list(getattr(dossier, name, None) or [])


# ── v2: operations in the answer (C3 aggregate -> rank, C2 compare two facets) ───────────
#
# Every figure below is read from the operation's result (operations.AggregateResult /
# CompareResult), which the dossier carries whole, and printed with ``operations.fmt`` -- the one
# rounding the result was computed with -- so the numeric guard finds each one in the dossier.

#: How many groups or rows the answer's table shows; the dossier holds every one.
_OPERATION_ROWS = 12

#: The reader's noun for a group, singular and plural.
_GROUP_NOUNS = {
    "floor": ("floor", "floors"),
    "space_kind": ("kind of space", "kinds of space"),
    "building": ("building", "buildings"),
}


def _with_unit(value: Optional[float], unit: str) -> str:
    return with_unit(value, unit)


def _sentence(text: str) -> str:
    """Upper-case the first letter of a line, past any markdown emphasis: a facet label is
    lower case ("occupancy"), and a sentence beginning with one should not be."""
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1 :]
    return text


def _spaces(n: int) -> str:
    return f"{n} space" if n == 1 else f"{n} spaces"


def _aggregate_words(agg: AggregateResult) -> Tuple[str, str]:
    """(the headline's superlative, the table's column) for an aggregate's statistic."""
    up = agg.order == "desc"
    label, unit = agg.label, agg.unit
    stat = agg.statistic
    if stat == "sum":
        return f"{'highest' if up else 'lowest'} total {label}", f"total {label}"
    if stat == "mean":
        return f"{'highest' if up else 'lowest'} average {label}", f"average {label}"
    if stat == "min":
        return f"{'highest' if up else 'lowest'} minimum {label}", f"lowest {label}"
    if stat == "max":
        return f"{'highest' if up else 'lowest'} maximum {label}", f"highest {label}"
    if stat == "range":
        return f"{'largest' if up else 'smallest'} spread in {label}", f"spread in {label}"
    if stat == "stdev":
        return f"{'least' if up else 'most'} even {label}", f"std. deviation of {label}"
    most = "most" if up else "fewest"
    if stat in ("count_above", "count_below"):
        side = "above" if stat == "count_above" else "below"
        limit = _with_unit(agg.threshold, unit)
        return (
            f"{most} spaces with {label} {side} {limit}",
            f"spaces {side} {limit}",
        )
    if not agg.facet:
        return f"{most} spaces meeting what you asked for", "spaces"
    if agg.yes_no:
        return f"{most} spaces where {label} is yes", f"spaces where {label} is yes"
    return f"{most} spaces with {label} recorded", f"spaces with {label} recorded"


def _group_figure(agg: AggregateResult, group: GroupResult) -> str:
    """A group's figure as printed: a count bare, anything else with its unit."""
    if group.value is None:
        return "—"
    if agg.statistic.startswith("count"):
        return fmt(group.value)
    return _with_unit(group.value, agg.unit)


def _group_n_clause(agg: AggregateResult, group: GroupResult) -> str:
    """The n the headline states beside a group's figure."""
    stat = agg.statistic
    if stat == "count" and not agg.facet:
        return ""
    if stat == "count":
        return f" (of {_spaces(group.n)} with it recorded)"
    if stat in ("count_above", "count_below"):
        return f" (of {_spaces(group.n)} with a value)"
    where = ""
    if stat == "range" and group.spread is not None:
        where = (
            f" — from {_with_unit(group.low, agg.unit)} ({group.low_space}) to "
            f"{_with_unit(group.high, agg.unit)} ({group.high_space})"
        )
    elif stat == "min" and group.low_space:
        where = f" ({group.low_space})"
    elif stat == "max" and group.high_space:
        where = f" ({group.high_space})"
    return f"{where}, over {_spaces(group.n)} with a value"


def _dispersion_lines(agg: AggregateResult, groups: bool = True) -> List[str]:
    """Spread across the groups' averages (``groups``) and across the spaces, each with its n."""
    d = agg.dispersion
    if d is None:
        return []
    noun = _GROUP_NOUNS.get(agg.group_by, ("group", "groups"))[1]
    unit = agg.unit
    lines: List[str] = []
    if groups and d.groups_n >= 2:
        lines.append(
            f"**Across {d.groups_n} {noun}:** averages run from "
            f"{_with_unit(d.groups_low, unit)} ({d.groups_low_label}) to "
            f"{_with_unit(d.groups_high, unit)} ({d.groups_high_label}); standard deviation "
            f"{_with_unit(d.groups_stdev, unit)}."
        )
    if d.spaces_n >= 2:
        lines.append(
            f"**Across {d.spaces_n} individual spaces:** from "
            f"{_with_unit(d.spaces_low, unit)} ({d.spaces_low_label}) to "
            f"{_with_unit(d.spaces_high, unit)} ({d.spaces_high_label}); standard deviation "
            f"{_with_unit(d.spaces_stdev, unit)}."
        )
    return lines


def _filter_texts(dossier: EvidenceDossier) -> List[str]:
    """The criteria that narrowed which spaces an operation counted, in the reader's words."""
    words = {"below": "below", "above": "above", "at_least": "at least", "at_most": "at most"}
    out: List[str] = []
    # A limit on a reading narrows an aggregate or a comparison, but not a comparison of two
    # periods or a relation: the executor names it as not applied there, so it is never listed
    # as applied.
    applied_limits = (
        [] if dossier.operation in ("period_compare", "relate") else dossier.constraints
    )
    for c in applied_limits:
        if c.threshold is not None and c.direction in ("below", "above"):
            out.append(f"{c.modality} {c.direction} {c.threshold:g}")
    for c in dossier.facet_criteria:
        if not c.checked or c.operator in ("minimize", "maximize", "near"):
            continue
        value = c.value
        if c.operator in words and isinstance(value, (int, float)):
            out.append(f"{c.label} {words[c.operator]} {value:g}")
        elif c.operator == "is_true":
            out.append(f"{c.label}: yes")
        elif c.operator == "is_false":
            out.append(f"{c.label}: no")
        elif c.operator == "free_for" and isinstance(value, (int, float)):
            out.append(f"free for the next {value:g} h")
        elif c.operator == "one_of" and isinstance(value, list):
            out.append(f"{c.label} one of {', '.join(str(v) for v in value)}")
        elif c.operator == "contains":
            out.append(f"{c.label} mentions '{value}'")
        else:
            out.append(f"{c.label} {value}" if value is not None else c.label)
    free_checks = [ec for ec in dossier.event_checks if ec.kind == "free_window"]
    if free_checks:
        out.append(f"free for the next {free_checks[0].window_hours:g} h")
    return list(dict.fromkeys(out))


def _operation_footer(dossier: EvidenceDossier, notes: List[str], basis: str) -> List[str]:
    """What every operation answer ends with: the basis, the filters, the caveats, the coverage."""
    lines: List[str] = [""]
    if basis:
        lines.append(f"**Each space's figure:** {basis}.")
    filters = _filter_texts(dossier)
    if filters:
        lines.append("**Counted only where:** " + "; ".join(filters) + ".")
    if dossier.not_assessable:
        lines.append(
            "**Not checked:** "
            + " ".join(n[:1].upper() + n[1:].rstrip(".") + "." for n in dossier.not_assessable)
            + " The figures above do not use it."
        )
    caveats = [n for n in notes if n]
    if caveats:
        lines.append(
            "**About this answer:** "
            + " ".join(n[:1].upper() + n[1:].rstrip(".") + "." for n in caveats)
        )
    for note in dossier.impossible_readings:
        lines.append(str(note))
    if dossier.assumptions:
        lines.append("**Assumptions:** " + "; ".join(a.text for a in dossier.assumptions) + ".")
    lines.append(f"**Coverage:** {dossier.coverage_summary}.")
    if dossier.applied_policies:
        lines.append(
            "**Privacy:** computed under this building's access rules for your role, which "
            "limit how finely individual readings can be shown."
        )
    return lines


def _operation_decline(dossier: EvidenceDossier, what: str) -> str:
    """Nothing could be computed: say why, and what would work, as a ranking decline does."""
    lines = [f"I couldn't work out {what} for this request."]
    reasons: List[str] = []
    for entry in dossier.coverage_excluded:
        reason = str(getattr(entry, "reason", "") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    if reasons:
        lines += ["", "**Why:** " + "; ".join(reasons[:3]) + "."]
    for note in dossier.guidance_notes[:2]:
        lines += ["", str(note)]
    return "\n".join(lines)


def _render_aggregate(dossier: EvidenceDossier, agg: AggregateResult) -> str:
    """Groups ranked by one figure each, every figure with its n (C3)."""
    noun, nouns = _GROUP_NOUNS.get(agg.group_by, ("group", "groups"))
    sup, column = _aggregate_words(agg)
    ranked = [g for g in agg.groups if g.value is not None]
    lines: List[str] = []
    if not ranked:
        what = f"the {column} per {noun}" if agg.group_by != "building" else f"the {column}"
        text = _operation_decline(dossier, what)
        empty = [g for g in agg.groups if g.note]
        if empty:
            text += "\n\n" + "; ".join(f"{g.label}: {g.note}" for g in empty[:6]) + "."
        return text + "\n" + "\n".join(_operation_footer(dossier, agg.notes, agg.basis))
    top = ranked[0]
    if agg.group_by == "building" or len(agg.groups) == 1:
        lines.append(
            f"**Across {top.label}, the {column} is {_group_figure(agg, top)}**"
            f"{_group_n_clause(agg, top)}."
        )
    elif agg.statistic == "stdev":
        lines.append(f"**How evenly {agg.label} is spread across the {nouns}:**")
        lines.extend(_dispersion_lines(agg))
        lines.append(
            f"{top.label} is the {sup.split(' even')[0]} even: standard deviation "
            f"{_group_figure(agg, top)}{_group_n_clause(agg, top)}."
        )
    elif len(agg.tied_top) > 1:
        lines.append(
            f"**{_join(agg.tied_top)} share the {sup}: {_group_figure(agg, top)} each.** "
            "The order between them is not a preference."
        )
    else:
        lines.append(
            f"**{top.label} has the {sup}: {_group_figure(agg, top)}**"
            f"{_group_n_clause(agg, top)}."
        )
        # A leader of one or two spaces is a fact about those spaces more than about a kind of
        # room or a floor. Measured live, 2026-10-08: "which kind of room is the warmest" was led
        # by a kind with one room in it. Say so, and name the leader among the larger groups.
        if top.n < _SMALL_GROUP:
            sturdy = [g for g in ranked if g.n >= _SMALL_GROUP]
            if sturdy:
                best = sturdy[0]
                lines.append(
                    f"{top.label} is {_spaces(top.n)} only; among {nouns} of at least "
                    f"{_SMALL_GROUP} spaces, {best.label} has the {sup}: "
                    f"{_group_figure(agg, best)}{_group_n_clause(agg, best)}."
                )
    for note in dossier.guidance_notes[:2]:
        lines.append(str(note))

    shown = ranked[: agg.top_k] if agg.top_k else ranked
    shown = shown[:_OPERATION_ROWS]
    extra_header, extra_rule = "", ""
    if agg.statistic == "range":
        extra_header, extra_rule = " highest | lowest |", "---|---|"
    elif agg.statistic == "stdev":
        extra_header, extra_rule = f" average {agg.label} | spread |", "---|---|"
    lines += [
        "",
        f"| {noun} | {column} |{extra_header} spaces with a value | without a value |",
        f"|---|---|{extra_rule}---|---|",
    ]
    for g in shown:
        extra = ""
        if agg.statistic == "range":
            extra = (
                f" {_with_unit(g.high, agg.unit)} ({g.high_space}) |"
                f" {_with_unit(g.low, agg.unit)} ({g.low_space}) |"
            )
        elif agg.statistic == "stdev":
            extra = f" {_with_unit(g.mean, agg.unit)} | {_with_unit(g.spread, agg.unit) or '—'} |"
        lines.append(f"| {g.label} | {_group_figure(agg, g)} |{extra} {g.n} | {g.n_missing} |")
    if len(ranked) > len(shown):
        lines.append(f"| … | further {nouns} in the evidence dossier | | |")
    no_figure = [g for g in agg.groups if g.value is None]
    if no_figure:
        lines.append("")
        lines.append(
            "**No figure for:** "
            + "; ".join(f"{g.label} ({g.note or 'no value'})" for g in no_figure[:6])
            + "."
        )
    if agg.statistic == "range":
        lines += [""] + _dispersion_lines(agg, groups=False)
    missing = [g for g in agg.groups if g.missing]
    if missing:
        lines.append("")
        lines.append(
            "**Without a value, so not counted:** "
            + "; ".join(f"{g.label} — {', '.join(g.missing)}" for g in missing[:4])
            + "."
        )
    held = [g for g in agg.groups if g.unverified]
    if held:
        lines.append(
            "**Could not be verified on what you asked for, so not counted:** "
            + "; ".join(f"{g.label} — {', '.join(g.unverified)}" for g in held[:4])
            + "."
        )
    if agg.unplaced:
        lines.append(f"**On no {noun} in the building model:** {', '.join(agg.unplaced)}.")
    lines += _operation_footer(dossier, agg.notes, agg.basis)
    return "\n".join(lines)


def _render_comparison(dossier: EvidenceDossier, cmp: CompareResult) -> str:
    """Two facts about the same spaces side by side, with the spaces that lack one (C2)."""
    a, b = cmp.label_a, cmp.label_b
    same_unit = cmp.unit_a == cmp.unit_b
    lines: List[str] = []
    if not cmp.rows:
        text = _operation_decline(dossier, f"{a} against {b}")
        text += (
            f"\n\n**No space in scope has both {a} and {b} recorded**, so nothing could be "
            "compared — nothing is filled in for the missing side."
        )
    else:
        text = ""
        t = cmp.total
        if t is not None:
            share = f" ({fmt(t.percent)}%)" if t.percent is not None else ""
            verdict = ""
            if cmp.relation == "exceeds":
                verdict = f" — {a} is {'above' if t.exceeds else 'not above'} {b}"
            lines.append(
                f"**Over the {_spaces(t.n)} with both figures: {a} totals "
                f"{_with_unit(t.a, cmp.unit_a)} against {b} {_with_unit(t.b, cmp.unit_b)}"
                f"{share}{verdict}.**"
            )
        elif cmp.relation == "exceeds":
            lines.append(
                f"**{cmp.n_exceeding} of the {_spaces(cmp.n_comparable)} with both figures "
                f"{'has' if cmp.n_exceeding == 1 else 'have'} {a} above {b}.**"
            )
        elif cmp.relation == "ratio":
            first = cmp.rows[0]
            lines.append(
                f"**{a} as a share of {b}, for the {_spaces(cmp.n_comparable)} with both "
                f"figures** — highest: {first.label} at {fmt(first.percent)}%."
                if first.percent is not None
                else f"**{a} against {b}, for the {_spaces(cmp.n_comparable)} with both figures.**"
            )
        else:
            first = cmp.rows[0]
            unit = f" {cmp.unit_a}" if same_unit and cmp.unit_a else ""
            lines.append(
                f"**{a} minus {b}, for the {_spaces(cmp.n_comparable)} with both figures** — "
                f"largest: {first.label} at {fmt(first.difference)}{unit}."
            )
        lines[0] = _sentence(lines[0])
        for note in dossier.guidance_notes[:2]:
            lines.append(str(note))
        third = {"ratio": "share", "exceeds": "share", "difference": "difference"}[cmp.relation]
        header = f"| space | {a} | {b} | {third} |"
        rule = "|---|---|---|---|"
        if cmp.relation == "exceeds":
            header += " above? |"
            rule += "---|"
        lines += ["", header, rule]
        for row in cmp.rows[:_OPERATION_ROWS]:
            if third == "share":
                rel = f"{fmt(row.percent)}%" if row.percent is not None else "—"
            else:
                rel = _with_unit(row.difference, cmp.unit_a if same_unit else "")
            cells = (
                f"| {row.label} | {_with_unit(row.a, cmp.unit_a)} | "
                f"{_with_unit(row.b, cmp.unit_b)} | {rel} |"
            )
            if cmp.relation == "exceeds":
                cells += f" {'yes' if row.exceeds else 'no'} |"
            lines.append(cells)
        if len(cmp.rows) > _OPERATION_ROWS:
            lines.append("| … | further spaces in the evidence dossier | | |")
        if t is not None and (t.a_only_n or t.b_only_n):
            parts = []
            if t.a_only_n:
                parts.append(
                    f"{_spaces(t.a_only_n)} with {a} but no {b} "
                    f"({_with_unit(t.a_only_sum, cmp.unit_a)} not in the total)"
                )
            if t.b_only_n:
                parts.append(
                    f"{_spaces(t.b_only_n)} with {b} but no {a} "
                    f"({_with_unit(t.b_only_sum, cmp.unit_b)} not in the total)"
                )
            lines += ["", "**Left out of the total:** " + "; ".join(parts) + "."]
    apart = cmp.not_comparable
    if apart:
        cap = _NOT_COMPARABLE_NAMED
        named = "; ".join(f"{r.label} ({r.reason})" for r in apart[:cap])
        more = f"; and {len(apart) - cap} more" if len(apart) > cap else ""
        lines += ["", f"**Not comparable ({len(apart)}):** {named}{more}."]
    lines += _operation_footer(dossier, cmp.notes, cmp.basis)
    body = "\n".join(lines)
    return f"{text}\n{body}" if text else body


#: How a period comparison reduced the spaces of each period, in the reader's words.
_PERIOD_STAT_WORDS = {
    "mean": "averaged across spaces",
    "sum": "added up across spaces (each space's average over the period)",
    "min": "lowest reading",
    "max": "highest reading",
}


def _period_side(per: PeriodResult, figure: PeriodFigure, side: str) -> str:
    """One period's figure as printed, with the space that holds it for a lowest / highest."""
    text = _with_unit(getattr(figure, side), per.unit) or "—"
    where = getattr(figure, f"{side}_space")
    return f"{text} ({where})" if where else text


def _period_change(per: PeriodResult, figure: PeriodFigure) -> str:
    if figure.change is None:
        return "—"
    if figure.direction == "the same":
        return "the same"
    size = _with_unit(abs(figure.change), per.unit)
    share = f", {fmt(abs(figure.percent))}%" if figure.percent is not None else ""
    return f"{figure.direction} by {size}{share}"


def _render_periods(dossier: EvidenceDossier, per: PeriodResult) -> str:
    """One reading over two periods, like against like, every figure with its n (C4)."""
    a, b = per.periods[0], per.periods[1]
    overall = per.overall
    lines: List[str] = []
    if overall is None or overall.n == 0:
        lines.append(_operation_decline(dossier, f"{per.label} for {b.label} against {a.label}"))
        lines += [
            "",
            f"**No space has {per.label} readings in both periods**, so nothing could be "
            "compared like with like — nothing is filled in for a missing period.",
        ]
    else:
        how = _PERIOD_STAT_WORDS.get(per.statistic, per.statistic)
        lines.append(
            _sentence(
                f"**{per.label}, {how}: {b.label} {_period_side(per, overall, 'b')} against "
                f"{a.label} {_period_side(per, overall, 'a')} — "
                f"{_period_change(per, overall)}**, over {_spaces(overall.n)} with readings in "
                "both periods."
            )
        )
        for note in dossier.guidance_notes[:2]:
            lines.append(str(note))
        if per.groups:
            noun = _GROUP_NOUNS.get(per.group_by, ("group", "groups"))[0]
            lines += [
                "",
                f"| {noun} | {a.label} | {b.label} | change | spaces in both |",
                "|---|---|---|---|---|",
            ]
            for g in per.groups[:_OPERATION_ROWS]:
                lines.append(
                    f"| {g.label} | {_period_side(per, g, 'a')} | {_period_side(per, g, 'b')} "
                    f"| {_period_change(per, g)} | {g.n} |"
                )
            if len(per.groups) > _OPERATION_ROWS:
                lines.append("| … | further groups in the evidence dossier | | | |")
    shown = []
    for w in (a, b):
        days = f" ({w.days} {'day' if w.days == 1 else 'days'})" if w.day_type else ""
        shown.append(f"{w.label} — {w.shown}{days}")
    lines += ["", "**Periods (building time):** " + "; ".join(shown) + "."]
    if per.not_compared:
        lines.append(
            f"**Not compared ({per.n_not_compared}):** " + "; ".join(per.not_compared) + "."
        )
    lines += _operation_footer(
        dossier, per.notes, "the mean of every reading in the period, reduced in the store"
    )
    return "\n".join(lines)


#: What a relation's figures may and may not be read as. Said with every relation answer.
_CO_OCCURRENCE = "This shows how the two co-occur in these spaces, not that one causes the other."
_CO_MOVEMENT = (
    "A correlation says the two moved together in these readings, not that one causes the other."
)


def _plural(label: str, n: int) -> str:
    """A record label for n of them: "timetabled session" -> "timetabled sessions"."""
    words = str(label or "").split()
    if n == 1 or not words:
        return " ".join(words)
    from orchestrator.services.record_registry import plural_of

    return " ".join(words[:-1] + [plural_of(words[-1])])


def _relation_sides(rel: RelationResult) -> Tuple[str, str]:
    """(the 'in' side, the 'out' side) in the reader's words, for the table's columns."""
    if rel.relation == "after":
        return f"after (within {fmt(rel.lag_minutes)} min)", "baseline"
    if rel.state:
        return f"while {rel.other_label} on", "while off"
    return "during", "outside"


def _relation_lead(rel: RelationResult, o: RelationFigure) -> str:
    """The lead sentence: both sides with their n, and the difference -- co-occurrence only."""
    unit = rel.unit
    first = _with_unit(o.in_mean, unit)
    second = _with_unit(o.out_mean, unit)
    if o.difference is None or o.difference == 0:
        change = "the same"
    else:
        share = f" ({fmt(abs(o.percent))}%)" if o.percent is not None else ""
        change = (
            f"{_with_unit(abs(o.difference), unit)} {'higher' if o.difference > 0 else 'lower'}"
            f"{share}"
        )
    where = _spaces(o.spaces)
    if rel.relation == "after":
        events = _plural(rel.events_label, o.events)
        return (
            f"**In the {fmt(rel.lag_minutes)} minutes after each of the {o.events} {events} in "
            f"{where}, {rel.label} averaged {first}, against {second} at other times with no "
            f"{_plural(rel.events_label, 2)} — {change}.**"
        )
    if rel.state:
        return (
            f"**{rel.label} averaged {first} while {rel.other_label} read on and {second} while "
            f"it read off, over {where} — {change} while on.**"
        )
    events = _plural(rel.events_label, o.events)
    return (
        f"**{rel.label} averaged {first} during the {o.events} {events} in {where} and "
        f"{second} outside them — {change} during them.**"
    )


def _relation_level_lines(rel: RelationResult, o: RelationFigure) -> List[str]:
    """The per-space directions and the per-event count behind a during / after / state lead."""
    lines: List[str] = []
    word = "after them" if rel.relation == "after" else ("while on" if rel.state else "during them")
    if o.spaces > 1:
        # One space's own difference IS the pooled one; the line only adds something for several.
        parts = [f"higher {word} in {o.spaces_higher} of the {_spaces(o.spaces)}"]
        if o.spaces_lower:
            parts.append(f"lower in {o.spaces_lower}")
        if o.spaces_same:
            parts.append(f"the same in {o.spaces_same}")
        tail = ""
        if o.mean_space_difference is not None:
            tail = (
                f"; the spaces' own differences average "
                f"{_with_unit(o.mean_space_difference, rel.unit)}"
            )
        lines.append(_sentence(", ".join(parts)) + tail + ".")
    if o.events_read:
        if rel.state:
            what = f"spells while {rel.other_label} read on"
            outside = "while it read off"
        elif rel.relation == "after":
            what = f"{_plural(rel.events_label, 2)} with readings after them"
            outside = "at other times"
        else:
            what = f"{_plural(rel.events_label, 2)} with readings"
            outside = "outside them"
        lines.append(
            f"{o.events_above} of the {o.events_read} {what} had {rel.label} above that "
            f"space's own figure {outside}."
        )
    return lines


def _relation_method(rel: RelationResult, o: Optional[RelationFigure]) -> str:
    """How each figure was made, with the bucket size and what was left out."""
    size = f"{rel.bucket_minutes}-minute"
    neither = o.neither_buckets if o is not None else 0
    if rel.relation == "co_movement":
        return (
            f"**How the figures were made:** each reading was averaged in {size} periods by the "
            "store and paired where both have readings; r is Pearson's correlation of the pairs "
            "(rank r is Spearman's), each space's own averages removed before spaces are pooled."
        )
    if rel.state:
        how = (
            f"a period counts as on when {rel.other_label} read on for at least half of it and as "
            "off when it read off throughout"
        )
    elif rel.relation == "after":
        how = (
            f"a period counts as after when at least half of it lies within "
            f"{fmt(rel.lag_minutes)} minutes of an event's end and none of it during one, and as "
            "baseline when it is neither during nor after one"
        )
    else:
        how = (
            "a period counts as during when at least half of it lies inside an event and as "
            "outside when none of it does"
        )
    left = f"; {neither} periods are in neither figure" if neither else ""
    return (
        f"**How the figures were made:** each reading was averaged in {size} periods by the "
        f"store; {how}{left}. Every figure is the mean of every reading in its periods."
    )


def _render_relation(dossier: EvidenceDossier, rel: RelationResult) -> str:
    """A series against recorded events, a yes/no reading, or a second series (C5)."""
    o = rel.overall
    lines: List[str] = []
    against = rel.events_label or rel.other_label
    if o is None or o.spaces == 0:
        lines.append(_operation_decline(dossier, f"how {rel.label} relates to {against}"))
        if rel.relation == "co_movement":
            lines += [
                "",
                f"**No space had at least 3 periods with both {rel.label} and {rel.other_label} "
                "readings, both changing**, so no correlation could be computed — nothing is "
                "filled in for a missing reading.",
            ]
        else:
            side = "after" if rel.relation == "after" else "during"
            lines += [
                "",
                f"**No space had {rel.label} readings both {side} and outside the "
                f"{_plural(against, 2)} in this window**, so nothing could be compared — "
                "nothing is filled in for a missing side.",
            ]
    elif rel.relation == "co_movement":
        if o.pearson is None:
            direction = "could not be correlated when pooled"
        elif o.pearson > 0:
            direction = "rose and fell together"
        elif o.pearson < 0:
            direction = "moved in opposite directions"
        else:
            direction = "showed no linear co-movement"
        r = f": r = {fmt(o.pearson)} over {o.pairs} periods" if o.pearson is not None else ""
        lines.append(
            _sentence(
                f"**Within each of these {_spaces(o.spaces)}, {rel.label} and {rel.other_label} "
                f"{direction}{r} ({rel.bucket_minutes}-minute averages, each space's own averages "
                "removed first).**"
            )
        )
        if o.change_pearson is not None:
            lines.append(
                f"Period-to-period changes: r = {fmt(o.change_pearson)} over {o.changes} pairs of "
                "consecutive periods."
            )
        lines.append(
            f"The correlation is positive in {o.spaces_positive} of the {_spaces(o.spaces)} and "
            f"negative in {o.spaces_negative}; the median space's r is {fmt(o.median_pearson)}."
        )
        lines.append(_CO_MOVEMENT)
    else:
        lines.append(_sentence(_relation_lead(rel, o)))
        lines += _relation_level_lines(rel, o)
        lines.append(_CO_OCCURRENCE)
    for note in dossier.guidance_notes[:2]:
        lines.append(str(note))

    shown = [s for s in rel.spaces if s.compared][:_OPERATION_ROWS]
    if shown:
        if rel.relation == "co_movement":
            lines += [
                "",
                "| space | periods with both | r (Pearson) | rank r (Spearman) | change r |",
                "|---|---|---|---|---|",
            ]
            for s in shown:
                lines.append(
                    f"| {s.label} | {s.pairs} | {fmt(s.pearson) or '—'} | "
                    f"{fmt(s.spearman) or '—'} | {fmt(s.change_pearson) or '—'} |"
                )
        else:
            first, second = _relation_sides(rel)
            count = "spells on" if rel.state else _plural(rel.events_label, 2)
            lines += [
                "",
                f"| space | {count} | {first}: mean (periods) | {second}: mean (periods) "
                "| difference |",
                "|---|---|---|---|---|",
            ]
            for s in shown:
                lines.append(
                    f"| {s.label} | {s.events} | {_with_unit(s.in_mean, rel.unit) or '—'} "
                    f"({s.in_buckets}) | {_with_unit(s.out_mean, rel.unit) or '—'} "
                    f"({s.out_buckets}) | {_with_unit(s.difference, rel.unit) or '—'} |"
                )
        compared = [s for s in rel.spaces if s.compared]
        if len(compared) > len(shown):
            lines.append("| … | further spaces in the evidence dossier | | | |")
    groups = [g for g in rel.groups if g.spaces]
    if groups:
        noun = _GROUP_NOUNS.get(rel.group_by, ("group", "groups"))[0]
        if rel.relation == "co_movement":
            lines += [
                "",
                f"| {noun} | spaces | r (pooled within spaces) | periods |",
                "|---|---|---|---|",
            ]
            for g in groups[:_OPERATION_ROWS]:
                lines.append(f"| {g.label} | {g.spaces} | {fmt(g.pearson) or '—'} | {g.pairs} |")
        else:
            first, second = _relation_sides(rel)
            lines += [
                "",
                f"| {noun} | spaces | {first} | {second} | difference |",
                "|---|---|---|---|---|",
            ]
            for g in groups[:_OPERATION_ROWS]:
                lines.append(
                    f"| {g.label} | {g.spaces} | {_with_unit(g.in_mean, rel.unit) or '—'} | "
                    f"{_with_unit(g.out_mean, rel.unit) or '—'} | "
                    f"{_with_unit(g.difference, rel.unit) or '—'} |"
                )
    if rel.window is not None:
        lines += ["", f"**Window (building time):** {rel.window.label} — {rel.window.shown}."]
    lines.append(_relation_method(rel, o))
    if rel.not_compared:
        lines.append(
            f"**Not compared ({rel.n_not_compared}):** " + "; ".join(rel.not_compared) + "."
        )
    basis = (
        "Pearson's r over its paired periods"
        if rel.relation == "co_movement"
        else "the mean of every reading in its periods, reduced in the store"
    )
    lines += _operation_footer(dossier, rel.notes, basis)
    return "\n".join(lines)


def _render_operation_answer(dossier: EvidenceDossier) -> str:
    """The answer of a plan that aggregates or compares instead of ranking spaces (v2)."""
    agg = getattr(dossier, "aggregate", None)
    cmp = getattr(dossier, "comparison", None)
    per = getattr(dossier, "periods", None)
    rel = getattr(dossier, "relation", None)
    if agg is not None:
        return _render_aggregate(dossier, agg)
    if cmp is not None:
        return _render_comparison(dossier, cmp)
    if per is not None:
        return _render_periods(dossier, per)
    if rel is not None:
        return _render_relation(dossier, rel)
    # Nothing was computed (the question was too broad to read, say): the executor's reason.
    what = "that comparison" if dossier.operation == "compare_facets" else "those figures"
    return _operation_decline(dossier, what)


def render_answer(dossier: EvidenceDossier, top_k: int = 3) -> str:
    """Deterministic prose: every number is substituted from the dossier itself."""
    if getattr(dossier, "operation", "") and not getattr(dossier, "refusal", ""):
        # v2: the plan aggregated or compared instead of ranking spaces. A ranking plan carries
        # no operation, so every branch below is reached exactly as before.
        return _render_operation_answer(dossier)
    if _facet_attr(dossier, "facet_criteria") and not getattr(dossier, "refusal", ""):
        # v2: a plan with facet criteria. A plan without them takes the v1 renderer below,
        # unchanged, so its answer is byte-identical to what v1 shipped.
        return _render_facet_answer(dossier, top_k)
    if dossier.refusal:
        # The lane declined to answer at all. Nothing was fetched, so there is no ranking,
        # no coverage and no evidence to qualify — the sentence IS the answer.
        return dossier.refusal
    if not dossier.ranked:
        # SAY WHY, AND WHAT WOULD WORK. "I couldn't rank any spaces for this request" is
        # true and useless: the reader cannot tell a building with no such space from a
        # question that was merely too broad to fetch, and the second is fixable in one
        # edit of the question.
        #
        # The reason is already recorded against each exclusion — "question spans 234
        # spaces, above the 120-space fetch budget" — and the plan executor already writes
        # the narrowing that would make it answerable. Neither reached the answer. A
        # decline that names what a real answer would require is a specification; one that
        # does not is a dead end.
        lines = ["I couldn't rank any spaces for this request."]
        reasons: List[str] = []
        for entry in dossier.coverage_excluded:
            reason = str(getattr(entry, "reason", "") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if reasons:
            lines.append("")
            lines.append("**Why:** " + "; ".join(reasons[:3]) + ".")
        for note in dossier.guidance_notes[:2]:
            lines.append("")
            lines.append(str(note))
        if not reasons and dossier.coverage_excluded:
            lines.append(
                f"{len(dossier.coverage_excluded)} spaces were excluded — see the evidence dossier."
            )
        return "\n".join(lines)

    lines: List[str] = []
    top = dossier.ranked[: max(1, top_k)]
    best = top[0]
    # A RANKING NOBODY CAN ACT ON MUST NOT BE PRESENTED AS ONE.
    #
    # Row 58 of the 2026-09-17 stakeholder read: three rooms offered as "Best match ... score
    # 0", "score 0", "score 0", every one reading about 24 against the 0-8 band the answer
    # itself quoted. Each utility had saturated at the bottom of its band, so the order came
    # from the tie-break and meant nothing — but "Best match" is a recommendation, and the
    # reader has no way to see that it was a coin toss. Saying so costs one sentence.
    #
    # BUG-868, 2026-09-23: this caught a tie at the BOTTOM of the band and missed the mirror
    # image at the top, which is the commoner one. "Which rooms are both warm and stuffy right
    # now?" compiles as list_matching with `above` and NO threshold, so the scorer falls back
    # to the band edge and every room above it lands at exactly 1.0. The answer then read
    # "Best match: Room 2.24 — score 1 out of 1, where 1 fits everything you asked for" for a
    # room at 22.675 C in a 20-26 band. `_fold_unbounded_threshold_direction` fixes this for
    # RANKING decisions and deliberately leaves list_matching alone, because an unbounded
    # filter there really is under-specified — so the ambiguity is kept on purpose, and the
    # answer is where it has to be disclosed. A tie is a tie at either end of the range.
    _totals = {round(s.total or 0.0, 6) for s in dossier.ranked}
    _flat = all((s.total or 0.0) <= 0.0 for s in dossier.ranked) or (
        len(dossier.ranked) > 1 and len(_totals) == 1
    )
    if _flat:
        lines.append(
            "**The readings don't separate these spaces.** On what you asked for, every "
            "space I could measure scores the same, so picking a best one would be "
            "arbitrary. Here is what they read:"
        )
    else:
        lines.append(
            f"**Best match: {best.space}** (floor {best.floor}, "
            f"{_score_phrase(best.total, explain=True)})."
        )
    # WB-05: a note about the EVIDENCE (e.g. "Simulated readings.") belongs above the list it
    # qualifies. Guidance notes reached declines only, so a scenario ranking read as measured.
    for note in dossier.guidance_notes[:2]:
        lines.append(str(note))
    for s in top:
        crits = ", ".join(f"{m}: {v:g}" for m, v in sorted(s.criteria.items()) if v is not None)
        prox = (
            f", {s.proximity_m:g} m to the requested amenity" if s.proximity_m is not None else ""
        )
        gaps = f" (no data: {', '.join(s.data_gaps)})" if s.data_gaps else ""
        if _flat:
            lines.append(f"- **{s.space}** ({crits}{prox}){gaps}")
        else:
            lines.append(
                f"{s.rank}. **{s.space}** — {_score_phrase(s.total)} ({crits}{prox}){gaps}"
            )
    if _flat:
        lines.append("")  # a bullet list runs into the next line without one
    # Directly under the list it qualifies, not in a footer. Row 99's reader saw
    # "occupancy: -7.719" inside the recommendation itself; a note three blocks below
    # would not have reached them either.
    for note in dossier.impossible_readings:
        lines.append("")
        lines.append(str(note))
    access_note = _access_note(dossier, top)
    if access_note:
        lines.append("")
        lines.append(access_note)
    if dossier.band_notes:
        lines.append("")
        lines.append(" ".join(str(n) for n in dossier.band_notes))
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
        # THE POLICY'S NAME IS NOT THE READER'S BUSINESS, AND ITS MECHANISM IS NOT EITHER.
        #
        # This line used to print the rule verbatim: "policy_facility_manager_any: resolution
        # clamped to 5s for data 0 min old". Three internal facts — a policy identifier, a
        # sampling resolution and a data age — none of which a person asking where to sit can
        # do anything with. What they can act on is the fact itself: an access rule applied.
        # The rule, its identifier and its reason stay on `applied_policies` in the structured
        # payload, which is what provenance and audit read.
        lines.append(
            "**Privacy:** computed under this building's access rules for your role, which "
            "limit how finely individual readings can be shown."
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
    if getattr(dossier, "operation", "") and not getattr(dossier, "refusal", ""):
        return _render_operation_details(dossier, max_rows)
    # An empty working-out is not working-out. A decline fetched nothing, so this block was
    # an empty table under a heading promising evidence — it read as a failure of the answer
    # rather than as the answer it was.
    if not dossier.evidence and not dossier.ranked and not _facet_attr(dossier, "facet_evidence"):
        return ""
    if _facet_attr(dossier, "facet_criteria"):
        return _render_facet_details(dossier, max_rows)
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
        # NO "simulated" COLUMN. This table is rendered to the reader inside every ranking
        # answer, and the building's readings are placeholder data standing in for its real
        # feeds - the owner's standing instruction is that nothing a user sees calls them
        # simulated, synthetic or fake. Found live in the 2026-09-17 stakeholder baseline:
        # workspace and wayfinding answers carried a column headed `simulated`. The
        # declaration itself is unchanged and stays on each evidence item in the structured
        # payload (e.simulated), which is what provenance accounting reads.
        "| space | modality | value | basis | points | source table |",
        "|---|---|---|---|---|---|",
    ]
    for e in dossier.evidence[:max_rows]:
        lines.append(
            f"| {e.space} | {e.modality} | {e.value:g} | {e.basis} "
            f"| {e.n_points} | {e.stored_at} |"
        )
    if len(dossier.evidence) > max_rows:
        lines.append("| … | | | further rows in the evidence payload | | |")
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


def _render_operation_details(dossier: EvidenceDossier, max_rows: int) -> str:
    """The working-out of an operation: the readings, then every space's figure and its source."""
    agg, cmp = dossier.aggregate, dossier.comparison
    table: List[str] = []
    if agg is not None:
        names = {g.key: g.label for g in agg.groups}
        valued = [s for s in agg.spaces if s.groups]
        if valued:
            noun = _GROUP_NOUNS.get(agg.group_by, ("group", "groups"))[0]
            table += ["", f"| space | {noun} | {agg.label} | source |", "|---|---|---|---|"]
            for s in valued[: max_rows * 2]:
                if not s.present:
                    shown = f"— ({s.reason})" if s.reason else "—"
                elif s.display:
                    shown = s.display
                elif s.flag is not None:
                    shown = "yes" if s.flag else "no"
                else:
                    shown = _with_unit(s.value, agg.unit) or "counted"
                where = ", ".join(names.get(k, k) for k in s.groups)
                table.append(f"| {s.label} | {where} | {shown} | {s.provenance or '—'} |")
            if len(valued) > max_rows * 2:
                table.append("| … | | further rows in the evidence payload | |")
        spaces = agg.n_spaces
    elif cmp is not None:
        both = cmp.rows + cmp.not_comparable
        if both:
            table += [
                "",
                f"| space | {cmp.label_a} | source | {cmp.label_b} | source |",
                "|---|---|---|---|---|",
            ]
            for r in both[: max_rows * 2]:
                table.append(
                    f"| {r.label} | {r.a_display or _with_unit(r.a, cmp.unit_a) or '—'} "
                    f"| {r.a_provenance or '—'} | {r.b_display or _with_unit(r.b, cmp.unit_b) or '—'} "
                    f"| {r.b_provenance or '—'} |"
                )
            if len(both) > max_rows * 2:
                table.append("| … | | further rows in the evidence payload | | |")
        spaces = cmp.n_comparable
    elif getattr(dossier, "periods", None) is not None:
        per = dossier.periods
        a, b = per.periods[0], per.periods[1]
        if per.spaces:
            table += [
                "",
                f"| space | {a.label}: mean (readings) | {b.label}: mean (readings) | note |",
                "|---|---|---|---|",
            ]
            for s in per.spaces[: max_rows * 2]:
                table.append(
                    f"| {s.label} | {_with_unit(s.a_mean, per.unit) or '—'} ({s.a_n}) "
                    f"| {_with_unit(s.b_mean, per.unit) or '—'} ({s.b_n}) | {s.reason or '—'} |"
                )
            if len(per.spaces) > max_rows * 2:
                table.append("| … | further rows in the evidence payload | | |")
        spaces = per.overall.n if per.overall is not None else 0
    elif getattr(dossier, "relation", None) is not None:
        rel = dossier.relation
        if rel.spaces and rel.relation == "co_movement":
            table += [
                "",
                "| space | periods with both | r | rank r | change r (pairs) | note |",
                "|---|---|---|---|---|---|",
            ]
            for s in rel.spaces[: max_rows * 2]:
                table.append(
                    f"| {s.label} | {s.pairs} | {fmt(s.pearson) or '—'} | "
                    f"{fmt(s.spearman) or '—'} | {fmt(s.change_pearson) or '—'} ({s.changes}) | "
                    f"{s.reason or '—'} |"
                )
        elif rel.spaces:
            first, second = _relation_sides(rel)
            table += [
                "",
                f"| space | events | {first}: mean (periods, readings) | "
                f"{second}: mean (periods, readings) | in neither | note |",
                "|---|---|---|---|---|---|",
            ]
            for s in rel.spaces[: max_rows * 2]:
                table.append(
                    f"| {s.label} | {s.events} | {_with_unit(s.in_mean, rel.unit) or '—'} "
                    f"({s.in_buckets}, {s.in_readings}) | "
                    f"{_with_unit(s.out_mean, rel.unit) or '—'} ({s.out_buckets}, "
                    f"{s.out_readings}) | {s.neither_buckets} | {s.reason or '—'} |"
                )
        if len(rel.spaces) > max_rows * 2:
            table.append("| … | further rows in the evidence payload | | | | |")
        spaces = rel.overall.spaces if rel.overall is not None else 0
    else:
        spaces = 0
    if not table and not dossier.evidence:
        return ""
    what = {
        "aggregate_rank": "groups ranked by one figure",
        "compare_facets": "two figures side by side",
        "period_compare": "one reading over two periods",
        "relate": "one reading related to recorded events or to another reading",
    }.get(dossier.operation, "an operation")
    lines: List[str] = [
        "",
        "<details>",
        "<summary>How I worked this out (evidence dossier)</summary>",
        "",
        f"*Operation: {what}, from {_spaces(spaces)}; plan fingerprint in the evidence payload.*",
    ]
    if dossier.evidence:
        lines += [
            "",
            "| space | modality | value | basis | points | source table |",
            "|---|---|---|---|---|---|",
        ]
        for e in dossier.evidence[:max_rows]:
            lines.append(
                f"| {e.space} | {e.modality} | {e.value:g} | {e.basis} "
                f"| {e.n_points} | {e.stored_at} |"
            )
        if len(dossier.evidence) > max_rows:
            lines.append("| … | | | further rows in the evidence payload | | |")
    lines += table
    if dossier.coverage_excluded:
        lines.append("")
        lines.append(
            "**Excluded:** "
            + "; ".join(f"{x.space} ({x.reason})" for x in dossier.coverage_excluded[:6])
        )
    lines += ["", "</details>"]
    return "\n".join(lines)


def _render_facet_details(dossier: EvidenceDossier, max_rows: int) -> str:
    """The working-out of a facet plan: the sensor evidence table, then the facet matrix."""
    lines: List[str] = [
        "",
        "<details>",
        "<summary>How I worked this out (evidence dossier)</summary>",
        "",
        f"*Decision: {dossier.decision} over {len(dossier.ranked)} ranked candidates; "
        "plan fingerprint in the evidence payload.*",
    ]
    if dossier.evidence:
        lines += [
            "",
            "| space | modality | value | basis | points | source table |",
            "|---|---|---|---|---|---|",
        ]
        for e in dossier.evidence[:max_rows]:
            lines.append(
                f"| {e.space} | {e.modality} | {e.value:g} | {e.basis} "
                f"| {e.n_points} | {e.stored_at} |"
            )
        if len(dossier.evidence) > max_rows:
            lines.append("| … | | | further rows in the evidence payload | | |")
    if dossier.facet_evidence:
        lines += [
            "",
            "| space | criterion | recorded | check | source |",
            "|---|---|---|---|---|",
        ]
        for row in dossier.facet_evidence[: max_rows * 2]:
            lines.append(
                f"| {row.space} | {row.label} | {row.display} | {row.status} "
                f"| {row.provenance or '—'} |"
            )
        if len(dossier.facet_evidence) > max_rows * 2:
            lines.append("| … | | further rows in the evidence payload | | |")
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
        # BUG-588: the basis label ("mean over 2026-09-14") and the latest-reading stamp are
        # dossier content too; quoting the date tripped the guard on "2026" and the whole
        # ranking was replaced by a recheck template.
        + [str(getattr(e, "basis", "") or "") for e in dossier.evidence]
        + [str(getattr(e, "latest", "") or "") for e in dossier.evidence]
        + [x.space for x in dossier.coverage_excluded]
        + [x.reason for x in dossier.coverage_excluded]
        + [ec.detail for ec in dossier.event_checks]
        + [ec.space for ec in dossier.event_checks]
        + list(dossier.applied_policies)
        # The excluded-reading and out-of-band sentences are dossier content too, and both
        # quote figures that are deliberately NOT in the ranking: a value is named here
        # precisely because it was dropped from `values`, and a band's edges are named to
        # say what the value ran past. Without these two lines the guard fired on the very
        # sentences that exist to be honest about a number, and its remedy is to replace
        # the entire answer — so the honest ranking was the one that could not ship.
        + list(dossier.impossible_readings)
        + list(dossier.band_notes)
        # v2: every recorded value, record id and facet sentence is dossier content. All of
        # these are empty for a v1 dossier, which leaves its allowed set unchanged.
        + [f.display for r in dossier.ranked for f in _facet_attr(r, "facets")]
        + [f.provenance for r in dossier.ranked for f in _facet_attr(r, "facets")]
        + [f.label for r in dossier.ranked for f in _facet_attr(r, "facets")]
        + [u for r in dossier.ranked for u in _facet_attr(r, "unverified")]
        + [row.display for row in _facet_attr(dossier, "facet_evidence")]
        + [row.provenance for row in _facet_attr(dossier, "facet_evidence")]
        + [row.label for row in _facet_attr(dossier, "facet_evidence")]
        + [row.space for row in _facet_attr(dossier, "facet_evidence")]
        + [c.label for c in _facet_attr(dossier, "facet_criteria")]
        + [str(c.value) for c in _facet_attr(dossier, "facet_criteria") if c.value is not None]
        + _facet_attr(dossier, "not_assessable")
        + _facet_attr(dossier, "facet_notes")
        # a facet answer names the sensed modalities in its sources line ("pm10" is a word
        # there, not a figure); a v1 dossier adds nothing here
        + (
            [c.modality for c in dossier.constraints]
            if _facet_attr(dossier, "facet_criteria")
            else []
        )
    )
    for c in _facet_attr(dossier, "facet_criteria"):
        if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
            add(c.value)
    # v2 operations: every figure an aggregate or a comparison computed, every n it states and
    # every name and note it quotes. Both are None for any other plan, which adds nothing.
    agg = getattr(dossier, "aggregate", None)
    if agg is not None:
        for x in (agg.threshold, agg.n_spaces, len(agg.groups), agg.n_unplaced, agg.overlapping):
            add(x)
        for g in agg.groups:
            for x in (g.rank, g.value, g.n, g.mean, g.stdev, g.low, g.high, g.spread, g.total):
                add(x)
            add(g.n_missing), add(g.n_unverified)
            text_blobs += [g.label, g.low_space, g.high_space, g.note] + g.missing + g.unverified
        if agg.dispersion is not None:
            d = agg.dispersion
            for x in (
                d.groups_n,
                d.groups_stdev,
                d.groups_low,
                d.groups_high,
                d.spaces_n,
                d.spaces_stdev,
                d.spaces_low,
                d.spaces_high,
            ):
                add(x)
            text_blobs += [
                d.groups_low_label,
                d.groups_high_label,
                d.spaces_low_label,
                d.spaces_high_label,
            ]
        for s in agg.spaces:
            add(s.value)
            text_blobs += [s.label, s.display, s.provenance, s.reason]
        text_blobs += [agg.label, agg.unit, agg.basis] + agg.unplaced + agg.notes
    cmp = getattr(dossier, "comparison", None)
    if cmp is not None:
        add(cmp.n_comparable), add(cmp.n_exceeding), add(len(cmp.not_comparable))
        # "...; and 146 more": the renderer names the first few spaces it could not compare and
        # counts the rest. That count is the renderer's own arithmetic on a list the dossier
        # holds, and without it the guard suppressed a whole comparison (live, 2026-10-08).
        if len(cmp.not_comparable) > _NOT_COMPARABLE_NAMED:
            add(len(cmp.not_comparable) - _NOT_COMPARABLE_NAMED)
        for r in cmp.rows + cmp.not_comparable:
            for x in (r.a, r.b, r.ratio, r.percent, r.difference):
                add(x)
            text_blobs += [r.label, r.a_display, r.b_display, r.a_provenance, r.b_provenance]
            text_blobs.append(r.reason)
        t = cmp.total
        if t is not None:
            for x in (t.n, t.a, t.b, t.ratio, t.percent, t.difference, t.a_only_n, t.b_only_n):
                add(x)
            add(t.a_only_sum), add(t.b_only_sum)
        text_blobs += [cmp.label_a, cmp.label_b, cmp.unit_a, cmp.unit_b, cmp.basis] + cmp.notes
    per = getattr(dossier, "periods", None)
    if per is not None:
        add(per.n_not_compared)
        for figure in ([per.overall] if per.overall else []) + list(per.groups):
            for x in (figure.n, figure.a, figure.b, figure.change, figure.percent):
                add(x)
            add(figure.readings_a), add(figure.readings_b)
            text_blobs += [figure.label, figure.a_space, figure.b_space]
        for w in per.periods:
            add(w.days)
            text_blobs += [w.label, w.shown]
        for s in per.spaces:
            for x in (s.a_mean, s.a_low, s.a_high, s.a_n, s.b_mean, s.b_low, s.b_high, s.b_n):
                add(x)
            text_blobs += [s.label, s.reason]
        text_blobs += [per.label, per.unit] + per.not_compared + per.notes
    rel = getattr(dossier, "relation", None)
    if rel is not None:
        from orchestrator.services.deliberation.operations import (
            _RELATION_FIGURE_FIELDS,
            _RELATION_SPACE_FIELDS,
        )

        add(rel.lag_minutes), add(rel.bucket_minutes), add(rel.n_not_compared), add(rel.instants)
        for figure in ([rel.overall] if rel.overall else []) + list(rel.groups):
            for name in _RELATION_FIGURE_FIELDS:
                add(getattr(figure, name))
            text_blobs.append(figure.label)
        for s in rel.spaces:
            for name in _RELATION_SPACE_FIELDS:
                add(getattr(s, name))
            text_blobs += [s.label, s.reason]
        if rel.window is not None:
            text_blobs += [rel.window.label, rel.window.shown]
        text_blobs += [rel.label, rel.unit, rel.other_label, rel.other_unit, rel.events_label]
        text_blobs += rel.not_compared + rel.notes
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
