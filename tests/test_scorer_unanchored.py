# -*- coding: utf-8 -*-
"""V5-T10: a modality with no calibrated band must not be scored against a guess.

Comfort modalities carry standards bands that hold in any building. Consumption
and count quantities (kWh, litres, free bays) do not — a "good" value depends on
floor area, tariff, or car-park size. The scorer previously fell back to a 0-1
band for any unanchored modality, which silently clamped such readings and
produced a confident ranking with an empty citation. These tests pin the honest
behaviour: skip the criterion, say why, and keep ranking on what IS calibrated.
"""

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
from orchestrator.services.deliberation.scorer import DEFAULT_ANCHORS, score_candidates

pytestmark = pytest.mark.unit


def _cands():
    return [
        Candidate(space_iri="urn:a", label="Room A", floor="1"),
        Candidate(space_iri="urn:b", label="Room B", floor="1"),
    ]


def _cqir(*constraints):
    return CQIR(decision=DecisionKind.RANK_ALL, constraints=list(constraints))


def _soft(modality, direction=Direction.MINIMIZE, weight=1.0):
    return Constraint(modality=modality, direction=direction, hardness=Hardness.SOFT, weight=weight)


# ── the omission is deliberate, so pin it ────────────────────────────────────


def test_consumption_modalities_have_no_default_band():
    """If someone adds a band for these, it must be a conscious decision."""
    for modality in ("energy_submeter", "water_flow", "parking_free"):
        assert modality not in DEFAULT_ANCHORS


def test_comfort_modalities_are_anchored_and_cited():
    for modality in ("noise", "co2", "temperature", "humidity", "illuminance", "pm25"):
        assert modality in DEFAULT_ANCHORS
        assert DEFAULT_ANCHORS[modality].citation, f"{modality} band has no citation"


# ── soft constraints ─────────────────────────────────────────────────────────


def test_unanchored_soft_criterion_is_skipped_not_guessed():
    res = score_candidates(
        _cqir(_soft("water_flow")),
        _cands(),
        {"urn:a": {"water_flow": 12.0}, "urn:b": {"water_flow": 940.0}},
    )
    # nothing calibrated -> nothing scorable -> no ranking invented
    assert res.ranked == []
    assert len(res.excluded) == 2
    assert all("no scorable data" in c.excluded_reason for c in res.excluded)


def test_the_skip_reason_names_the_modality_and_the_value_survives():
    res = score_candidates(
        _cqir(_soft("noise"), _soft("water_flow")),
        _cands(),
        {"urn:a": {"noise": 35.0, "water_flow": 12.0}, "urn:b": {"noise": 60.0, "water_flow": 9.0}},
    )
    top = res.ranked[0]
    water = [c for c in top.criteria if c.modality == "water_flow"][0]
    assert water.utility is None, "an unanchored criterion must not produce a utility"
    assert water.value == pytest.approx(12.0), "the measured value is still reported"
    assert "no calibrated band" in water.note and "water_flow" in water.note
    assert water.citation == "", "no band means no citation to claim"
    assert "water_flow" in top.data_gaps


def test_ranking_still_happens_on_the_calibrated_criterion():
    """The unanchored criterion must not drag the ranking — quiet room still wins."""
    res = score_candidates(
        _cqir(_soft("noise"), _soft("water_flow")),
        _cands(),
        # B uses far less water; if water_flow were scored on a 0-1 band it would
        # be clamped and could flip the winner. Noise is what was asked about.
        {
            "urn:a": {"noise": 35.0, "water_flow": 900.0},
            "urn:b": {"noise": 65.0, "water_flow": 1.0},
        },
    )
    assert res.ranked[0].label == "Room A"


def test_anchored_modalities_are_unaffected_by_the_change():
    res = score_candidates(
        _cqir(_soft("noise")),
        _cands(),
        {"urn:a": {"noise": 30.0}, "urn:b": {"noise": 70.0}},
    )
    assert [c.label for c in res.ranked] == ["Room A", "Room B"]
    noise = res.ranked[0].criteria[0]
    assert noise.utility == pytest.approx(1.0)
    assert "WHO" in noise.citation


# ── hard constraints ─────────────────────────────────────────────────────────


def test_unanchored_hard_threshold_is_still_enforced():
    """A user-supplied threshold IS a band, so pass/fail stays well defined."""
    cqir = _cqir(
        Constraint(
            modality="water_flow",
            direction=Direction.BELOW,
            hardness=Hardness.HARD,
            threshold=100.0,
            weight=1.0,
        ),
        _soft("noise"),
    )
    res = score_candidates(
        cqir,
        _cands(),
        {
            "urn:a": {"water_flow": 50.0, "noise": 40.0},
            "urn:b": {"water_flow": 900.0, "noise": 32.0},
        },
    )
    assert [c.label for c in res.ranked] == ["Room A"]
    assert res.excluded[0].label == "Room B"
    assert "fails hard" in res.excluded[0].excluded_reason


def test_unanchored_hard_requirement_without_a_threshold_is_refused():
    """No band and no threshold means the requirement cannot be verified — say so."""
    cqir = _cqir(
        Constraint(
            modality="water_flow",
            direction=Direction.MINIMIZE,
            hardness=Hardness.HARD,
            weight=1.0,
        )
    )
    res = score_candidates(
        cqir, _cands(), {"urn:a": {"water_flow": 5.0}, "urn:b": {"water_flow": 9.0}}
    )
    assert res.ranked == []
    assert all("no calibrated band" in c.excluded_reason for c in res.excluded)
    assert all("not verifiable" in c.excluded_reason for c in res.excluded)
