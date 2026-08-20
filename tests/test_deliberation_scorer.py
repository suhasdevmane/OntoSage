"""V4-T20 tests — deterministic scorer: pure, honest about gaps, sensitivity-checked."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.candidates import Candidate
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
)
from orchestrator.services.deliberation.scorer import score_candidates

pytestmark = pytest.mark.unit

NS = "ns#"


def _cand(label, dist=None):
    return Candidate(
        space_iri=f"{NS}{label}",
        label=label,
        floor="floor0",
        sensors={},
        distance_to_anchor_m=dist,
    )


def _ir(*constraints):
    return CQIR(decision=DecisionKind.RANK_ALL, constraints=list(constraints))


def test_minimize_ranks_quietest_first_deterministically():
    ir = _ir(Constraint(modality="noise", direction=Direction.MINIMIZE))
    cands = [_cand("Loud"), _cand("Quiet"), _cand("Mid")]
    values = {
        f"{NS}Loud": {"noise": 60.0},
        f"{NS}Quiet": {"noise": 32.0},
        f"{NS}Mid": {"noise": 45.0},
    }
    res = score_candidates(ir, cands, values)
    assert [s.label for s in res.ranked] == ["Quiet", "Mid", "Loud"]
    assert res.ranked[0].rank == 1
    assert res.ranked[0].criteria[0].citation  # anchor citation carried for the dossier
    # identical inputs -> identical output (determinism)
    res2 = score_candidates(ir, cands, values)
    assert [s.total for s in res2.ranked] == [s.total for s in res.ranked]


def test_hard_below_threshold_excludes_with_reason():
    ir = _ir(
        Constraint(modality="co2", direction=Direction.BELOW, hardness=Hardness.HARD, threshold=800)
    )
    cands = [_cand("Ok"), _cand("Bad"), _cand("NoData")]
    values = {f"{NS}Ok": {"co2": 600.0}, f"{NS}Bad": {"co2": 1200.0}, f"{NS}NoData": {}}
    res = score_candidates(ir, cands, values)
    assert [s.label for s in res.ranked] == ["Ok"]
    reasons = {s.label: s.excluded_reason for s in res.excluded}
    assert "fails hard below" in reasons["Bad"]
    assert "no co2 data" in reasons["NoData"]


def test_soft_gap_renormalizes_never_imputes():
    ir = _ir(
        Constraint(modality="noise", direction=Direction.MINIMIZE),
        Constraint(modality="co2", direction=Direction.MINIMIZE),
    )
    cands = [_cand("Full"), _cand("NoCO2")]
    values = {
        f"{NS}Full": {"noise": 40.0, "co2": 800.0},
        f"{NS}NoCO2": {"noise": 40.0},  # same noise, missing co2
    }
    res = score_candidates(ir, cands, values)
    by = {s.label: s for s in res.ranked}
    assert by["NoCO2"].data_gaps == ["co2"]
    # renormalized: NoCO2 scored on noise alone (0.75), Full averages noise+co2
    assert by["NoCO2"].total == pytest.approx(0.75, abs=1e-3)
    assert by["Full"].total < by["NoCO2"].total  # co2=800 drags Full below
    gap_note = [c for c in by["NoCO2"].criteria if c.modality == "co2"][0]
    assert "no data" in gap_note.note and gap_note.utility is None


def test_proximity_is_relative_to_the_field():
    ir = _ir(Constraint(modality="noise", direction=Direction.MINIMIZE))
    cands = [_cand("Near", dist=0.0), _cand("Far", dist=20.0)]
    values = {f"{NS}Near": {"noise": 40.0}, f"{NS}Far": {"noise": 40.0}}
    res = score_candidates(ir, cands, values)
    by = {s.label: s for s in res.ranked}
    assert by["Near"].proximity_utility == 1.0
    assert by["Far"].proximity_utility == 0.0
    assert res.ranked[0].label == "Near"


def test_tie_breaks_alphabetically_and_rule_is_stated():
    ir = _ir(Constraint(modality="noise", direction=Direction.MINIMIZE))
    cands = [_cand("Zeta"), _cand("Alpha")]
    values = {f"{NS}Zeta": {"noise": 40.0}, f"{NS}Alpha": {"noise": 40.0}}
    res = score_candidates(ir, cands, values)
    assert [s.label for s in res.ranked] == ["Alpha", "Zeta"]
    assert "alphabetically" in res.tie_break_rule


def test_sensitivity_flag_reports_stability():
    ir = _ir(
        Constraint(modality="noise", direction=Direction.MINIMIZE, weight=1.0),
        Constraint(modality="co2", direction=Direction.MINIMIZE, weight=1.0),
    )
    # clear winner on both criteria -> stable under +/-25% weights
    cands = [_cand("Win"), _cand("Lose")]
    values = {
        f"{NS}Win": {"noise": 32.0, "co2": 500.0},
        f"{NS}Lose": {"noise": 60.0, "co2": 1400.0},
    }
    res = score_candidates(ir, cands, values)
    assert res.top1_stable_under_weight_perturbation is True
    # knife-edge trade-off -> a 25% weight shift flips the winner
    values2 = {
        f"{NS}Win": {"noise": 30.0, "co2": 1500.0},
        f"{NS}Lose": {"noise": 70.0, "co2": 420.0},
    }
    res2 = score_candidates(ir, cands, values2)
    assert res2.top1_stable_under_weight_perturbation is False


def test_no_scorable_data_excluded_not_zeroed():
    ir = _ir(Constraint(modality="noise", direction=Direction.MINIMIZE))
    cands = [_cand("Ghost")]
    res = score_candidates(ir, cands, {f"{NS}Ghost": {}})
    assert res.ranked == []
    assert res.excluded[0].excluded_reason == "no scorable data on any criterion"
