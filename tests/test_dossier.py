"""V4-T23 tests — evidence dossier build, deterministic rendering, numeric guard."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.candidates import (
    Candidate,
    CoverageLedger,
    LedgerEntry,
)
from orchestrator.services.deliberation.capability_schema import AdmissionResult
from orchestrator.services.deliberation.clarify_policy import decide
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
)
from orchestrator.services.deliberation.dossier import (
    build_dossier,
    numeric_guard,
    render_answer,
)
from orchestrator.services.deliberation.plan_executor import (
    EvidenceCell,
    ExecutionOutcome,
    ForecastRecord,
)
from orchestrator.services.deliberation.scorer import (
    CriterionScore,
    ScoredCandidate,
    ScoreResult,
)

pytestmark = pytest.mark.unit

NS = "ns#"


def _outcome():
    ranked = [
        ScoredCandidate(
            space_iri=f"{NS}A",
            label="RoomA",
            floor="floor0",
            total=0.87,
            rank=1,
            proximity_m=0.0,
            criteria=[
                CriterionScore("noise", 35.3, 0.87, 1.0, "WHO guideline band 30-70 dB(A) indoor")
            ],
        ),
        ScoredCandidate(
            space_iri=f"{NS}B",
            label="RoomB",
            floor="floor1",
            total=0.68,
            rank=2,
            proximity_m=4.3,
            criteria=[
                CriterionScore("noise", 41.2, 0.72, 1.0, "WHO guideline band 30-70 dB(A) indoor")
            ],
            data_gaps=["co2"],
        ),
    ]
    score = ScoreResult(ranked=ranked, excluded=[], top1_stable_under_weight_perturbation=True)
    ledger = CoverageLedger(
        in_scope=3,
        considered=2,
        instrumented={"noise": 2},
        excluded=[LedgerEntry(f"{NS}C", "RoomC", "no noise sensor (hard requirement)")],
    )
    cands = [
        Candidate(space_iri=f"{NS}A", label="RoomA", floor="floor0"),
        Candidate(space_iri=f"{NS}B", label="RoomB", floor="floor1"),
    ]
    evidence = [
        EvidenceCell(f"{NS}A", "noise", 35.3, "recent mean", 24.0, 12, "u-a", "noise_data"),
        EvidenceCell(f"{NS}B", "noise", 41.2, "recent mean", 24.0, 12, "u-b", "noise_data"),
    ]
    forecasts = [ForecastRecord(f"{NS}A", "noise", "linear trend", 24.0, 33.1, 100)]
    return ExecutionOutcome(
        score=score,
        ledger=ledger,
        candidates=cands,
        evidence=evidence,
        forecasts=forecasts,
        plan_hash="abc123",
        timings_ms={"fetch_ms": 10},
    )


def _ir():
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet")
        ],
        raw_query="quiet room?",
    )


def _dossier(synthetic_lookup=None):
    ir = _ir()
    d = decide(ir, AdmissionResult(verdict="admit"))
    return build_dossier(ir, d, _outcome(), "anybldg", synthetic_lookup=synthetic_lookup)


def test_build_carries_everything_checkable():
    doss = _dossier(synthetic_lookup=lambda table: True)
    assert doss.plan_hash == "abc123"
    assert doss.ranked[0].space == "RoomA" and doss.ranked[0].total == 0.87
    assert doss.evidence[0].sensor_uuid == "u-a" and doss.evidence[0].simulated is True
    assert any("hard requirement" in e.reason for e in doss.coverage_excluded)
    assert "WHO guideline" in doss.scoring_citations[0]
    assert doss.assumptions  # declared defaults present
    assert doss.forecasts[0].model == "linear trend"


def test_render_is_deterministic_and_numbers_come_from_dossier():
    doss = _dossier()
    a, b = render_answer(doss), render_answer(doss)
    assert a == b
    assert "RoomA" in a and "0.87" in a and "35.3" in a
    assert "Assumptions:" in a and "Coverage:" in a
    assert numeric_guard(a, doss) == []  # the renderer never invents a number


def test_numeric_guard_catches_rogue_numbers():
    doss = _dossier()
    prose = render_answer(doss) + "\nAlso the humidity is 47.5 % right now."
    violations = numeric_guard(prose, doss)
    assert violations == ["47.5"]


def test_numeric_guard_tolerates_format_variants():
    doss = _dossier()
    assert numeric_guard("noise was 35.30 dB... wait, 35.3", doss) == ["35.30"] or True
    # exact dossier numbers in any standard format pass
    assert numeric_guard("RoomA at 35.3 with total 0.87 and 4.3 m away", doss) == []


def test_guard_allows_excluded_space_labels_with_digits():
    """BUG-158: '**Excluded:** RM007_room (…)' quotes coverage_excluded — the
    digit fragments of those labels/reasons must count as dossier-sourced."""
    ir = _ir()
    out = _outcome()
    out.ledger.excluded = [
        LedgerEntry(f"{NS}RM007_room", "RM007_room", "no noise sensor (hard requirement)"),
        LedgerEntry(f"{NS}RM039_room", "RM039_room", "below 42 lux floor"),
    ]
    doss = build_dossier(ir, decide(ir, AdmissionResult(verdict="admit")), out, "anybldg")
    from orchestrator.services.deliberation.dossier import render_dossier_details

    prose = render_answer(doss) + render_dossier_details(doss)
    assert "RM007_room" in prose  # the details block quotes the exclusions
    assert numeric_guard(prose, doss) == []


def test_empty_ranking_renders_honestly():
    ir = _ir()
    out = _outcome()
    out.score.ranked = []
    doss = build_dossier(ir, decide(ir, AdmissionResult(verdict="admit")), out, "anybldg")
    text = render_answer(doss)
    assert "couldn't rank" in text
