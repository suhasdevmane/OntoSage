# -*- coding: utf-8 -*-
"""BUG-873 (P1) — the relevance gate may object, but not by saying something untrue.

Measured twice on 2026-09-23, on two unrelated questions:

    [deliberate] answered: plan=319aa153 ranked=195 guard_violations=0
    [response] relevance gate replaced a deliberate answer: OFF_TOPIC
    [response] nothing to say: intent=deliberate ... error=none

    [forecast_agent] Done. Model=Holt-Winters (seasonal=24) MAE=0.473%RH  success=True
    [response] relevance gate replaced a trend answer: OFF_TOPIC

In both the lane answered from the building's records, and in both the reader was given
"I couldn't answer that from Abacws Building's records" — a sentence that is false precisely
when a lane has just done so, and that discards the grounded answer disproving it.

THE GATE IS NOT WRONG TO OBJECT. Both answers were incomplete: one ranked the rooms without
saying what the two readings together suggest, the other forecast hour by hour without ever
giving the mean that was asked for. Incomplete is a reason to say so. It is not a reason to
substitute nothing.

So the gate keeps its judgement and loses one action, in one case: where the turn produced
visible evidence. With no evidence it replaces exactly as before — which is the case it was
built for, a model generalising from a retrieval window.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow._orchestrator import _grounded_evidence_behind

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, results):
        self.intermediate_results = results


# ── what counts as evidence worth protecting ─────────────────────────────────────────


def test_a_ranking_over_candidates_is_evidence():
    state = _State(
        {"evidence_dossier": {"ranked": [{"space": "Room 1.01"}] * 195, "evidence": [{}] * 400}}
    )
    got = _grounded_evidence_behind(state)
    assert got, "a lane that ranked 195 candidates produced evidence"
    assert "195" in got and "400" in got, got


def test_readings_alone_are_evidence_even_with_nothing_ranked():
    state = _State({"evidence_dossier": {"ranked": [], "evidence": [{}, {}]}})
    assert _grounded_evidence_behind(state)


def test_figures_computed_in_the_store_are_evidence():
    state = _State({"aggregate_result": {"figures": {"building mean": 750.0}}})
    assert "figures" in _grounded_evidence_behind(state)


# ── and what does NOT, so the gate keeps working where it was built to ───────────────


@pytest.mark.parametrize(
    "results",
    [
        {},
        {"evidence_dossier": {}},
        {"evidence_dossier": {"ranked": [], "evidence": []}},
        {"aggregate_result": {}},
        {"aggregate_result": {"figures": {}}},
        {"evidence_dossier": None},
        {"sparql_result": {"formatted_response": "some prose with no evidence behind it"}},
    ],
)
def test_an_empty_or_absent_dossier_is_not_evidence(results):
    """The original failure -- a model generalising from a retrieval window -- has no dossier.

    The gate must still replace there, which is the whole reason it exists.
    """
    assert _grounded_evidence_behind(_State(results)) == ""


def test_a_malformed_state_reports_no_evidence_rather_than_raising():
    """Positive-only by design: "" means none VISIBLE, never none exists.

    A describer that can break the thing it describes is worse than none.
    """

    class _Broken:
        intermediate_results = "not a dict"

    assert _grounded_evidence_behind(_Broken()) == ""
    assert _grounded_evidence_behind(object()) == ""


# ── the rule this encodes, stated once ───────────────────────────────────────────────


def test_the_withholding_is_justified_in_the_source_by_the_falsehood_it_prevents():
    """This is a change to a SAFETY mechanism.

    The next person to read it must find the reason beside it, not in a tracker they have to
    know exists -- otherwise the safe-looking edit is to delete the condition.
    """
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator._relevance_gated)
    assert "BUG-873" in src
    assert "false" in src.lower()
    assert "_grounded_evidence_behind" in src
    # and it must still replace when there is nothing to protect
    assert "_unanswered_response" in src


# ── the forecast lane, which the first version of this fix MISSED ────────────────────
#
# BUG-873 was first observed on a forecast, and the first version of `_grounded_evidence_behind`
# checked the dossier, the aggregate lane and the comparison lane — and not `forecast_result`.
# So the gate went on replacing completed forecasts, and the answerability gate caught it on
# pack index 6 during the very run meant to confirm the fix:
#
#   [forecast_agent] Done. Model=SeasonalNaive MAE=8.681ppm RMSE=10.952ppm
#   [response] relevance gate replaced a trend answer: OFF_TOPIC
#   [response] nothing to say: intent=trend ... error=none
#
# The keys below are the ones the lane actually writes — `model`, not `model_name`, which the
# first attempt also got wrong.


def test_a_fitted_forecast_is_evidence():
    state = _State(
        {
            "forecast_result": {
                "success": True,
                "model": "SeasonalNaive",
                "forecast": [700.0] * 24,
            }
        }
    )
    got = _grounded_evidence_behind(state)
    assert got, "a fitted model over real history is evidence"
    assert "SeasonalNaive" in got and "24" in got


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "model": "SeasonalNaive", "forecast": [1, 2]},  # it failed
        {"success": True, "model": "SeasonalNaive", "forecast": []},  # nothing predicted
        {"success": True, "model": "SeasonalNaive"},  # no forecast at all
        {},
    ],
)
def test_a_forecast_that_produced_nothing_is_not_evidence(payload):
    """A lane that ran and produced nothing must not shelter its own non-answer."""
    assert _grounded_evidence_behind(_State({"forecast_result": payload})) == ""


def test_the_lanes_that_can_shelter_an_answer_are_named_in_one_place():
    """If a fifth lane is added, this is the list to extend — say so where it is read."""
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator._grounded_evidence_behind)
    for lane_key in ("evidence_dossier", "aggregate_result", "comparison", "forecast_result"):
        assert lane_key in src, lane_key
