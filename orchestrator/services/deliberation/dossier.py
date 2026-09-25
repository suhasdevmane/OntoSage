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
    #: The reader's word for this space's kind when it is one somebody holds — "laboratory",
    #: "office". Empty when anyone may walk in. Set from the space's own class, never shown
    #: as a class name.
    access_controlled_as: str = ""


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
    ranked = [
        DossierRanked(
            rank=s.rank or 0,
            space=s.label,
            floor=s.floor,
            total=s.total or 0.0,
            proximity_m=None if s.proximity_m is None else round(s.proximity_m, 1),
            criteria={c.modality: c.value for c in s.criteria},
            data_gaps=list(s.data_gaps),
            access_controlled_as=access_word(kinds_by_iri.get(s.space_iri, ())),
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


def render_answer(dossier: EvidenceDossier, top_k: int = 3) -> str:
    """Deterministic prose: every number is substituted from the dossier itself."""
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
    # An empty working-out is not working-out. A decline fetched nothing, so this block was
    # an empty table under a heading promising evidence — it read as a failure of the answer
    # rather than as the answer it was.
    if not dossier.evidence and not dossier.ranked:
        return ""
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
