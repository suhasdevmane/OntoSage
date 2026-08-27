# -*- coding: utf-8 -*-
"""Planning the defects, and the ground truth to score against (V6-T61).

The pathology harness landed on 2026-08-25 and left two things owed: live
injection into the provisioners (the catalogue's `rate` fields were declared and
unused) and the ground-truth manifest that makes whole-building precision/recall
scoring possible at all.

The unit assertions drive every gate from one clean case and one defective case,
which proves each gate WORKS. What they cannot show is whether the gates work on a
whole building -- for that you need a fixture defective at realistic rates and a
record of exactly which points were spoiled. Without the manifest a
precision/recall number is unfalsifiable: you can count how often a gate fired,
but not whether it fired on the points that deserved it.
"""

import pytest

from orchestrator.services.pathology_injection import (
    load_catalogue,
    manifest,
    plan_injection,
    score,
)

pytestmark = pytest.mark.unit

_POINTS = [f"uuid-{i:04d}" for i in range(2000)]


# -- the plan -----------------------------------------------------------------
def test_the_catalogue_rates_are_actually_consumed():
    """They were declared and unused since the harness landed."""
    plan = plan_injection(_POINTS)
    assert plan.spoiled, "no point was spoiled; the rates are still unused"


def test_the_plan_is_deterministic():
    """A re-run must reproduce the same building, or a changed score means a
    different dice roll rather than changed code."""
    a = plan_injection(_POINTS)
    b = plan_injection(_POINTS)
    assert [(s.point, s.defect) for s in a.spoiled] == [(s.point, s.defect) for s in b.spoiled]


def test_a_different_seed_gives_a_different_plan():
    a = plan_injection(_POINTS, seed="one")
    b = plan_injection(_POINTS, seed="two")
    assert {s.point for s in a.spoiled} != {s.point for s in b.spoiled}


def test_each_spoiled_point_carries_exactly_one_defect():
    """A point that is stale AND gapped AND uncalibrated tells you nothing about
    which gate caught it, so precision and recall stop being interpretable."""
    plan = plan_injection(_POINTS)
    points = [s.point for s in plan.spoiled]
    assert len(points) == len(set(points))


def test_rates_are_respected_within_tolerance():
    cat = {"x": {"gate": "g", "rate": 0.10, "defect": {"kind": "k", "value": 1}}}
    plan = plan_injection(_POINTS, catalogue=cat)
    assert 0.07 <= len(plan.spoiled) / len(_POINTS) <= 0.13


def test_a_zero_rate_injects_nothing_and_is_named():
    """Two catalogue entries are decided by the ASKER and the CLAIM, not by
    readings, so no fixture can provoke them. They are reported, never silently
    dropped -- a catalogue that quietly ignores entries looks more complete than it
    is."""
    plan = plan_injection(_POINTS)
    assert "causal_overclaim" in plan.not_injectable
    assert not any(s.defect == "causal_overclaim" for s in plan.spoiled)


def test_the_shipped_catalogue_still_declares_eleven_kinds():
    assert len(load_catalogue()) == 11


def test_no_points_or_no_catalogue_plans_nothing():
    assert plan_injection([]).spoiled == []
    assert plan_injection(_POINTS, catalogue={}).spoiled == []


# -- the manifest -------------------------------------------------------------
def test_the_manifest_records_every_spoiled_point_and_its_gate():
    plan = plan_injection(_POINTS)
    m = manifest(plan, building_id="bldg1")
    assert m["spoiled"] == len(plan.spoiled)
    assert m["clean"] == plan.total_points - len(plan.spoiled)
    assert set(m["by_gate"]) == set(plan.by_gate())
    assert len(m["points"]) == len(plan.spoiled)


def test_the_manifest_says_a_gate_firing_off_list_is_a_false_positive():
    """Otherwise a reader cannot tell what the file is FOR."""
    assert "false positive" in manifest(plan_injection(_POINTS))["_comment"]


def test_the_manifest_carries_the_seed():
    """Without it the ground truth cannot be regenerated to check a score."""
    assert manifest(plan_injection(_POINTS, seed="abc"))["seed"] == "abc"


# -- scoring ------------------------------------------------------------------
def test_a_perfect_detector_scores_one():
    plan = plan_injection(_POINTS)
    s = score(plan, {g: list(p) for g, p in plan.by_gate().items()})
    assert all(v["recall"] == 1.0 and v["precision"] == 1.0 for v in s.values())


def test_a_gate_that_never_fires_scores_zero_recall_not_a_pass():
    plan = plan_injection(_POINTS)
    s = score(plan, {})
    assert all(v["recall"] == 0.0 for v in s.values())


def test_a_gate_firing_on_a_clean_point_is_a_false_positive():
    plan = plan_injection(_POINTS)
    gate = sorted(plan.by_gate())[0]
    truth = plan.by_gate()[gate]
    s = score(plan, {gate: list(truth) + ["uuid-not-spoiled"]})
    assert s[gate]["false_positive"] == 1
    assert "uuid-not-spoiled" in s[gate]["false_positive_points"]


def test_a_gate_with_nothing_to_find_reports_none_not_zero():
    """0.0 reads as a failure; None says there was no evidence either way."""
    plan = plan_injection(_POINTS, catalogue={})
    s = score(plan, {"freshness": []})
    assert s["freshness"]["precision"] is None
    assert s["freshness"]["recall"] is None


def test_scores_are_per_gate_not_one_headline():
    """One number hides a gate that never fires behind one that fires on
    everything, and those need opposite fixes."""
    plan = plan_injection(_POINTS)
    s = score(plan, {g: list(p) for g, p in plan.by_gate().items()})
    assert len(s) > 1
    assert all("precision" in v and "recall" in v for v in s.values())
