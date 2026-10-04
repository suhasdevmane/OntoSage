# -*- coding: utf-8 -*-
"""G5 (2026-10-04, found live 2026-10-02): a deliberation row read
'(noise: 60.342, occupancy_status: 0.776) (no data: occupancy_status)' -- carrying a real
value AND a 'no data' marker for the SAME modality in one sentence.

Root cause: `s.criteria` is a LIST of CriterionScore, and a duplicate constraint for one
modality (two different source phrases resolving to the same modality) can put one
real-valued entry and one None-valued entry in it. `build_dossier`'s dict comprehension
kept whichever came last; `s.data_gaps` is a SEPARATE list appended independently of the
dict, so the gap marker could survive even where the dict ended up holding a real number.
"""
import pytest

from orchestrator.services.deliberation.candidates import Candidate, CoverageLedger
from orchestrator.services.deliberation.capability_schema import AdmissionResult
from orchestrator.services.deliberation.clarify_policy import decide
from orchestrator.services.deliberation.cqir import CQIR, Constraint, DecisionKind, Direction
from orchestrator.services.deliberation.dossier import build_dossier
from orchestrator.services.deliberation.plan_executor import ExecutionOutcome
from orchestrator.services.deliberation.scorer import CriterionScore, ScoredCandidate, ScoreResult

pytestmark = pytest.mark.unit

NS = "ns#"


def _outcome_with_duplicate_constraint():
    """Reproduces the live shape: occupancy_status appears TWICE in one candidate's
    criteria list -- once with a real value (a duplicate constraint that resolved), once
    with None (the duplicate that did not) -- and data_gaps records the None pass."""
    ranked = [
        ScoredCandidate(
            space_iri=f"{NS}A",
            label="Room 3.46 — Academic Office",
            floor="floor3",
            total=0.78,
            rank=1,
            criteria=[
                CriterionScore("noise", 60.342, 0.6, 1.0, "WHO guideline band 30-70 dB(A) indoor"),
                CriterionScore("occupancy_status", 0.776, 0.9, 1.0, "relative occupancy band"),
                CriterionScore("occupancy_status", None, None, 1.0, "", "no data"),
            ],
            data_gaps=["occupancy_status"],
        ),
    ]
    score = ScoreResult(ranked=ranked, excluded=[], top1_stable_under_weight_perturbation=True)
    ledger = CoverageLedger(in_scope=1, considered=1, instrumented={"noise": 1})
    cands = [Candidate(space_iri=f"{NS}A", label="Room 3.46 — Academic Office", floor="floor3")]
    return ExecutionOutcome(
        score=score, ledger=ledger, candidates=cands, evidence=[], forecasts=[], plan_hash="x"
    )


def _dossier():
    ir = CQIR(
        decision=DecisionKind.LIST_MATCHING,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet"),
            Constraint(
                modality="occupancy_status", direction=Direction.MINIMIZE, source_phrase="free"
            ),
        ],
        raw_query="quiet rooms that are free?",
    )
    d = decide(ir, AdmissionResult(verdict="admit"))
    return build_dossier(ir, d, _outcome_with_duplicate_constraint(), "anybldg")


class TestARowNeverContradictsItself:
    def test_the_real_value_wins_and_the_gap_is_dropped(self):
        doss = _dossier()
        row = doss.ranked[0]
        assert row.criteria.get("occupancy_status") == 0.776
        assert "occupancy_status" not in row.data_gaps

    def test_a_genuine_gap_with_no_value_anywhere_is_still_reported(self):
        """The fix must not swallow a REAL gap -- only one contradicted by a real value."""
        out = _outcome_with_duplicate_constraint()
        out.score.ranked[0].criteria = [
            CriterionScore("noise", 60.342, 0.6, 1.0, "band"),
            CriterionScore("co2", None, None, 1.0, "", "no data"),
        ]
        out.score.ranked[0].data_gaps = ["co2"]
        ir = CQIR(decision=DecisionKind.LIST_MATCHING, constraints=[], raw_query="x")
        d = decide(ir, AdmissionResult(verdict="admit"))
        doss = build_dossier(ir, d, out, "anybldg")
        assert "co2" in doss.ranked[0].data_gaps
        assert "co2" not in doss.ranked[0].criteria or doss.ranked[0].criteria["co2"] is None
