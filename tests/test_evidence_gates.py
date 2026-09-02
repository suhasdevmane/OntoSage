# -*- coding: utf-8 -*-
"""Evidence gates (V6-T16 freshness, T17/T13 wiring, T32 consequence, T34 calibration).

The shape matters as much as the logic. Every gate returns a verdict, and **a verdict is not
an action**: policy decides per gate whether it enforces. That is what makes shadow mode
(V6-T55) possible without editing a single gate, and it is why `blocks` is the only place
enforcement is decided.

Failing a gate is not an error path. It downgrades the status and attaches a reason and a
remedy -- "not assessable, the newest reading is three days old, here is what to restart" is
a correct answer, and Master 15.5 calls that the most important requirement in the report.
"""

from datetime import datetime, timedelta

import pytest
import yaml

from orchestrator.services.evidence import load_policy
from orchestrator.services.evidence.gates import (
    advisory_failures,
    apply,
    blocking,
    calibration_gate,
    completeness_gate,
    freshness_gate,
    spatial_gate,
)
from orchestrator.services.evidence.policy import GateMode
from shared.models import AnswerStatus, SpatialAdequacy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 12, 0, 0)


@pytest.fixture
def policy():
    return load_policy("any")


@pytest.fixture
def enforcing(tmp_path):
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump(
            {
                "gates": {
                    g: {"mode": "enforcing"}
                    for g in ("freshness", "completeness", "spatial_adequacy", "calibration")
                }
            }
        ),
        encoding="utf-8",
    )
    return load_policy("bldgX", input_dir=tmp_path)


@pytest.fixture
def advisory(tmp_path):
    """A policy with every gate ADVISORY, written explicitly.

    The mechanism tests below are about advisory-vs-enforcing, not about which posture the
    shipped config happens to use. They used the live policy, so switching freshness to
    enforcing (CAVEAT-361) broke tests that were never about freshness. An explicit overlay
    keeps them testing the mechanism and immune to the next posture decision.
    """
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump(
            {
                "gates": {
                    g: {"mode": "advisory"}
                    for g in ("freshness", "completeness", "spatial_adequacy", "calibration")
                }
            }
        ),
        encoding="utf-8",
    )
    return load_policy("bldgY", input_dir=tmp_path)


# ── the shape ────────────────────────────────────────────────────────────────


def test_a_failing_gate_does_not_block_while_advisory(advisory):
    """The property the whole rollout plan depends on."""
    v = freshness_gate(advisory, "co2", NOW - timedelta(days=3), NOW)
    assert v.passed is False
    assert v.mode is GateMode.ADVISORY
    assert v.blocks is False
    assert v.advisory_failure is True


def test_the_same_failure_blocks_once_enforcing(enforcing):
    v = freshness_gate(enforcing, "co2", NOW - timedelta(days=3), NOW)
    assert v.blocks is True
    assert v.advisory_failure is False


def test_every_failure_carries_a_reason_and_a_remedy(policy):
    v = freshness_gate(policy, "co2", NOW - timedelta(days=3), NOW)
    assert v.reason and v.remedy
    assert "publisher" in v.remedy


# ── freshness (T16) ──────────────────────────────────────────────────────────


def test_fresh_reading_passes(policy):
    assert freshness_gate(policy, "co2", NOW - timedelta(minutes=2), NOW).passed


def test_stale_reading_fails_and_cites_the_limit(policy):
    v = freshness_gate(policy, "co2", NOW - timedelta(hours=3), NOW)
    assert not v.passed
    assert v.threshold == "5 min"  # from config, not from code
    assert "180 minutes old" in v.reason


def test_stale_downgrades_to_inferred_not_refused(policy):
    """The reading is real and still says something about the recent past.

    Refusing outright would discard usable evidence, which the non-substitution rule never
    asks for -- it asks for the limitation to be stated.
    """
    v = freshness_gate(policy, "co2", NOW - timedelta(hours=3), NOW)
    assert v.downgrade_to is AnswerStatus.INFERRED


def test_no_observation_at_all_is_not_assessable(policy):
    v = freshness_gate(policy, "co2", None, NOW)
    assert v.downgrade_to is AnswerStatus.NOT_ASSESSABLE


def test_historical_questions_are_not_gated_on_freshness(policy):
    """Last March is not stale for being a while ago."""
    v = freshness_gate(policy, "co2", NOW - timedelta(days=180), NOW, is_current_question=False)
    assert v.passed


def test_freshness_limit_is_per_modality(policy):
    """CO2 responds to occupancy in minutes; a booking is current until superseded."""
    old = NOW - timedelta(minutes=30)
    assert not freshness_gate(policy, "co2", old, NOW).passed
    assert freshness_gate(policy, "booking", old, NOW).passed


# ── completeness (T17 wiring) ────────────────────────────────────────────────


def test_sufficient_coverage_passes(policy):
    assert completeness_gate(policy, 0.95).passed


def test_thin_coverage_fails_with_the_floor_named(policy):
    v = completeness_gate(policy, 0.40)
    assert not v.passed
    assert "40%" in v.reason and "90%" in v.reason


def test_unknown_coverage_fails_rather_than_passing(policy):
    """Unestablished completeness must not read as checked."""
    v = completeness_gate(policy, None)
    assert not v.passed
    assert v.downgrade_to is AnswerStatus.NOT_ASSESSABLE


def test_a_safety_claim_demands_more_coverage_than_an_informational_one(policy):
    """Consequence scaling (T32), visible at the gate."""
    assert completeness_gate(policy, 0.92, "informational").passed
    assert not completeness_gate(policy, 0.92, "safety_or_compliance").passed


# ── spatial adequacy (T13 wiring) ────────────────────────────────────────────


def test_in_room_evidence_passes_for_a_space(policy):
    assert spatial_gate(policy, SpatialAdequacy.IN_ROOM, "space").passed


def test_proxy_fails_for_a_space_but_passes_for_the_building(policy):
    assert not spatial_gate(policy, SpatialAdequacy.PROXY, "space").passed
    assert spatial_gate(policy, SpatialAdequacy.PROXY, "building").passed


def test_proxy_downgrades_to_inferred_and_keeps_the_reason(policy):
    v = spatial_gate(policy, SpatialAdequacy.PROXY, "space", proxy_reason="the corridor outside")
    assert v.downgrade_to is AnswerStatus.INFERRED
    assert "corridor" in v.reason
    assert "cannot carry a claim" in v.remedy


def test_no_coverage_is_not_assessable_and_names_the_fix(policy):
    v = spatial_gate(policy, SpatialAdequacy.NONE, "space")
    assert v.downgrade_to is AnswerStatus.NOT_ASSESSABLE
    assert "connect a sensor" in v.remedy.lower()


# ── calibration (T34) ────────────────────────────────────────────────────────


def test_calibration_is_irrelevant_to_an_informational_claim(policy):
    assert calibration_gate(policy, "unknown", "informational").passed


def test_a_standards_verdict_needs_a_calibrated_sensor(policy):
    """Acceptance scenario 7."""
    assert calibration_gate(policy, "calibrated", "safety_or_compliance").passed
    assert not calibration_gate(policy, "unknown", "safety_or_compliance").passed
    assert not calibration_gate(policy, "expired", "safety_or_compliance").passed


def test_a_blocked_standards_verdict_still_offers_the_raw_reading(policy):
    v = calibration_gate(policy, "unknown", "safety_or_compliance")
    assert "raw reading is still reported" in v.remedy


# ── resolving several gates ──────────────────────────────────────────────────


def test_advisory_failures_never_move_the_status(advisory):
    verdicts = [
        freshness_gate(advisory, "co2", NOW - timedelta(days=3), NOW),
        completeness_gate(advisory, 0.2),
    ]
    assert apply(verdicts, AnswerStatus.OBSERVED) is AnswerStatus.OBSERVED
    assert len(advisory_failures(verdicts)) == 2
    assert blocking(verdicts) == []


def test_the_most_conservative_downgrade_wins(enforcing):
    """One missing prerequisite is enough, whatever else held."""
    verdicts = [
        freshness_gate(enforcing, "co2", NOW - timedelta(hours=3), NOW),  # -> INFERRED
        completeness_gate(enforcing, None),  # -> NOT_ASSESSABLE
    ]
    assert apply(verdicts, AnswerStatus.OBSERVED) is AnswerStatus.NOT_ASSESSABLE


def test_a_passing_set_leaves_the_proposed_status_alone(enforcing):
    verdicts = [
        freshness_gate(enforcing, "co2", NOW - timedelta(minutes=1), NOW),
        completeness_gate(enforcing, 0.99),
        spatial_gate(enforcing, SpatialAdequacy.IN_ROOM, "space"),
    ]
    assert apply(verdicts, AnswerStatus.OBSERVED) is AnswerStatus.OBSERVED
    assert blocking(verdicts) == []


def test_a_gate_cannot_upgrade_a_status(enforcing):
    """Gates only ever restrict. An INFERRED answer must not become OBSERVED."""
    verdicts = [freshness_gate(enforcing, "co2", NOW - timedelta(minutes=1), NOW)]
    assert apply(verdicts, AnswerStatus.INFERRED) is AnswerStatus.INFERRED
