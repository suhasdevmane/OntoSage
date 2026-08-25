# -*- coding: utf-8 -*-
"""Every gate fires on its defect, and stays silent on its near-miss (V6-T61).

Synthetic data generated cleanly is the wrong test set. Every gate this project built exists
because REAL buildings produce gaps, stale streams, disagreeing pairs, uncalibrated points and
relocated sensors — and a fixture with none of those cannot distinguish a working gate from one
that never fires at all.

`config/pathology.yaml` declares, per defect: the shape to inject, and a **near-miss** of the
same shape just inside the threshold. Both halves matter and they measure different things:

* the defect firing proves **recall** — the gate catches what it exists to catch;
* the near-miss staying silent proves **precision** — and a gate with no precision is one
  people learn to ignore, which protects nothing while looking like it protects everything.

Every gate is called **for real**, with the shipped policy. Nothing here mocks the thing under
test, so deleting a gate's logic fails its entry.

Deterministic and offline: no live stack, no active building, no random seeds.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator.services.evidence.policy import load_policy

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CATALOGUE = yaml.safe_load((REPO / "config" / "pathology.yaml").read_text(encoding="utf-8"))
DEFECTS = CATALOGUE["defects"]
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _fire(spec: dict, gate: str):
    """Run `gate` against one declared shape and return its verdict.

    One dispatcher for every gate so a new catalogue entry cannot quietly go unexercised: an
    unknown gate name raises rather than skipping.
    """
    policy = load_policy()
    kind = spec.get("kind")

    if gate == "freshness":
        from orchestrator.services.evidence.gates import freshness_gate

        if kind == "latest_observation":
            latest = None
        else:
            latest = NOW - timedelta(minutes=float(spec["value"]))
        return freshness_gate(policy, "temperature", latest, NOW, is_current_question=True)

    if gate == "completeness":
        from orchestrator.services.evidence.gates import completeness_gate

        return completeness_gate(policy, spec.get("value"), consequence_class="informational")

    if gate == "spatial_adequacy":
        from orchestrator.services.evidence.gates import spatial_gate
        from shared.models import SpatialAdequacy

        return spatial_gate(policy, SpatialAdequacy(spec["value"]), spec.get("scope", "room"))

    if gate == "calibration":
        from orchestrator.services.evidence.gates import calibration_gate

        return calibration_gate(policy, spec["value"], spec.get("consequence", "compliance"))

    if gate == "agreement":
        from orchestrator.services.evidence.conflict import Reading, detect

        readings = [
            Reading(sensor_id=f"http://x#S{i}", value=float(v))
            for i, v in enumerate(spec["values"])
        ]
        report = detect("http://x#Room", "temperature", readings, spec.get("tolerance"))
        return type(
            "V",
            (),
            {"passed": not report.conflicting, "reason": report.reason, "name": "agreement"},
        )()

    if gate == "trend_integrity":
        from orchestrator.services.evidence.history import ConfigurationPeriod
        from orchestrator.services.evidence.trend_integrity import (
            TrendVerdict,
            assess_trend,
        )

        start, end = datetime(2026, 3, 1), datetime(2026, 5, 1)
        moved_at = datetime(2026, 4, 1) if spec.get("inside_window") else datetime(2025, 4, 1)
        periods = [
            ConfigurationPeriod(effective_from=datetime(2025, 1, 1), location="http://x#A"),
            ConfigurationPeriod(
                effective_from=moved_at, location="http://x#B", change="relocation"
            ),
        ]
        outcome = assess_trend(periods, start, end)
        return type(
            "V",
            (),
            {
                "passed": outcome.verdict is TrendVerdict.REPORTABLE,
                "reason": outcome.caveat or "reportable",
                "name": "trend_integrity",
            },
        )()

    if gate == "causal_claim":
        from orchestrator.services.evidence.causal_guard import unlicensed_claims
        from shared.models import CausalSupport

        claims = unlicensed_claims(spec["text"], CausalSupport(spec["support"]))
        return type(
            "V",
            (),
            {
                "passed": not claims,
                "reason": f"{len(claims)} unlicensed claim(s)",
                "name": "causal",
            },
        )()

    raise AssertionError(f"catalogue names gate {gate!r}, which this harness cannot exercise")


# ── the catalogue itself ─────────────────────────────────────────────────────


def test_the_catalogue_is_not_empty():
    """POSITIVE CONTROL. Every parametrised test below iterates the catalogue; an empty or
    renamed file would make them all pass by testing nothing."""
    assert len(DEFECTS) >= 8, f"only {len(DEFECTS)} defects declared"


def test_every_defect_declares_a_gate_and_a_near_miss():
    """A defect with no near-miss measures recall and calls it done. Precision is the half that
    decides whether anyone keeps the gate switched on."""
    missing = [
        name for name, spec in DEFECTS.items() if not spec.get("gate") or not spec.get("near_miss")
    ]
    assert not missing, f"defects without a gate or a near-miss: {missing}"


def test_every_declared_gate_is_one_the_system_actually_has():
    """A catalogue entry naming a gate that does not exist would sit there forever, green and
    meaningless."""
    known = set(
        yaml.safe_load((REPO / "config" / "evidence_policy.yaml").read_text(encoding="utf-8"))[
            "gates"
        ]
    ) | {"trend_integrity"}
    unknown = {spec["gate"] for spec in DEFECTS.values()} - known
    assert not unknown, f"catalogue names gates the policy does not define: {unknown}"


def test_the_catalogue_covers_the_gates_that_can_be_provoked_by_data():
    """Not every gate is data-provokable — `permission` and `consequence` are decided by the
    ASKER and the CLAIM, not by the readings — so this asserts coverage of the ones a fixture
    can actually exercise, and names the exclusions rather than quietly having none."""
    covered = {spec["gate"] for spec in DEFECTS.values()}
    data_provokable = {
        "freshness",
        "completeness",
        "spatial_adequacy",
        "calibration",
        "agreement",
        "causal_claim",
        "trend_integrity",
    }
    assert data_provokable <= covered, f"no injected defect for: {data_provokable - covered}"


# ── recall: each defect trips its gate ───────────────────────────────────────


@pytest.mark.parametrize(
    "name", [n for n, s in DEFECTS.items() if s.get("defect")], ids=lambda n: f"defect:{n}"
)
def test_the_injected_defect_trips_its_gate(name):
    spec = DEFECTS[name]
    verdict = _fire(spec["defect"], spec["gate"])
    assert not verdict.passed, (
        f"{name} did not trip the {spec['gate']} gate — the defect is injected and invisible, "
        f"which is worse than not injecting it: the fixture now looks clean. "
        f"Gate said: {getattr(verdict, 'reason', '')!r}"
    )


@pytest.mark.parametrize(
    "name", [n for n, s in DEFECTS.items() if s.get("defect")], ids=lambda n: f"reason:{n}"
)
def test_a_tripped_gate_says_why(name):
    """A verdict a person cannot act on is a blocked answer with no remedy attached."""
    spec = DEFECTS[name]
    verdict = _fire(spec["defect"], spec["gate"])
    assert str(getattr(verdict, "reason", "")).strip(), f"{name} tripped with no reason"


# ── precision: the near-miss must stay silent ────────────────────────────────


@pytest.mark.parametrize("name", list(DEFECTS), ids=lambda n: f"near-miss:{n}")
def test_the_near_miss_does_not_trip_the_gate(name):
    spec = DEFECTS[name]
    verdict = _fire(spec["near_miss"], spec["gate"])
    assert verdict.passed, (
        f"{name}'s near-miss tripped the {spec['gate']} gate. A gate that fires just inside its "
        f"own threshold produces caveats on healthy data, and caveats on healthy data are how a "
        f"gate gets switched off. Gate said: {getattr(verdict, 'reason', '')!r}"
    )


# ── determinism ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(DEFECTS), ids=lambda n: f"stable:{n}")
def test_the_same_spec_yields_the_same_verdict_twice(name):
    """Injection has to be repeatable or the grader's precision/recall numbers mean nothing
    between runs."""
    spec = DEFECTS[name]
    shape = spec.get("defect") or spec["near_miss"]
    first = _fire(shape, spec["gate"])
    second = _fire(shape, spec["gate"])
    assert first.passed == second.passed


# ── the fail-open the catalogue exposed ──────────────────────────────────────


class TestConsequenceLookupDoesNotFailOpenSilently:
    """Every consequence requirement fails OPEN on an unknown class name — no calibration
    requirement, no authoritative-source requirement. That is correct for a genuinely NEW
    class, and catastrophic when a caller passes a SHAPE (`compliance`) where a CLASS
    (`safety_or_compliance`) belongs: the strictest gate in the system goes quietly permissive
    on exactly the claims it exists for.

    Found by writing this catalogue: the first draft named the shape, the calibration gate
    replied "not a calibration-sensitive claim", and nothing anywhere said the name was wrong.
    The consequence mechanism has already been inert once for a naming mismatch of this kind —
    see the `by_shape` comment in config/evidence_policy.yaml.
    """

    def test_a_real_class_requires_calibration(self):
        assert load_policy().requires_calibration("safety_or_compliance")

    def test_a_shape_name_resolves_instead_of_going_permissive(self):
        """`compliance` is an intent name, not a class. It must not disable the gate."""
        assert load_policy().requires_calibration(
            "compliance"
        ), "a shape passed where a class belongs silently switched off the calibration gate"

    def test_an_informational_claim_still_needs_no_calibration(self):
        """The precision half: hardening must not make every question calibration-gated."""
        assert not load_policy().requires_calibration("informational")

    def test_an_unknown_class_is_logged_not_silent(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            load_policy().requires_calibration("not_a_real_class")
        assert any(
            "unknown consequence class" in r.message for r in caplog.records
        ), "an unrecognised consequence class disabled the gate with no trace"
