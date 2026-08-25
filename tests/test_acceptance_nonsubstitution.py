# -*- coding: utf-8 -*-
"""Master Report acceptance scenario 1, end to end (V6-T15).

> *"Remove the room sensor -> the system refuses a room-level claim rather than silently
> using the corridor value."*

The pieces are tested individually elsewhere (T13 classification, T16/T13 gating, T14
narration). This exercises them **composed**, which is where the scenario actually lives: a
classifier that grades correctly, a gate that blocks correctly, and narration that explains
correctly can still fail together if the wiring drops the verdict between them.

Deliberately built on a synthetic fixture rather than bldg1, so the test asserts BEHAVIOUR
and cannot pass for reasons peculiar to one building's layout.
"""

from datetime import datetime, timedelta

import pytest
import yaml

from orchestrator.services.evidence import load_policy
from orchestrator.services.evidence.gates import apply, spatial_gate
from orchestrator.services.evidence.narration import (
    describe_not_assessable,
    label_proxy,
)
from orchestrator.services.evidence.spatial_adequacy import PointFacts, best_verdict
from shared.models import AnswerStatus, SpatialAdequacy

pytestmark = pytest.mark.unit

# A fixture floor: one room WITH a sensor, one room WITHOUT, and the corridor that runs
# between them. Nothing here corresponds to any real building.
ROOM_WITH = "http://fixture/W-A1"
ROOM_WITHOUT = "http://fixture/W-A2"
CORRIDOR = "http://fixture/W-COR"

SENSORS = [
    PointFacts("p-inroom", containing_space=ROOM_WITH),
    PointFacts("p-corridor", containing_space=CORRIDOR),
]


@pytest.fixture
def enforcing(tmp_path):
    """Scenario 1 is about ENFORCED behaviour, so the gate is switched on for this test."""
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump({"gates": {"spatial_adequacy": {"mode": "enforcing"}}}), encoding="utf-8"
    )
    return load_policy("fixture", input_dir=tmp_path)


def _answer(space: str, policy):
    """The composed path: classify -> gate -> narrate."""
    verdict = best_verdict(space, SENSORS)
    gate = spatial_gate(policy, verdict.grade, "space", proxy_reason=verdict.reason)
    status = apply([gate], AnswerStatus.OBSERVED)
    if status is AnswerStatus.OBSERVED:
        text = f"The reading for {space.rsplit('/')[-1]} is 900 ppm."
    elif verdict.grade is SpatialAdequacy.PROXY:
        text = label_proxy(space, verdict.evidence_space, verdict.reason, "900 ppm", "14:02")
    else:
        text = describe_not_assessable(gate.reason, gate.remedy)
    return status, text, verdict, gate


# ── the scenario ─────────────────────────────────────────────────────────────


def test_a_room_with_its_own_sensor_answers_normally(enforcing):
    status, text, verdict, gate = _answer(ROOM_WITH, enforcing)
    assert verdict.grade is SpatialAdequacy.IN_ROOM
    assert gate.passed
    assert status is AnswerStatus.OBSERVED
    assert "900 ppm" in text


def test_removing_the_room_sensor_stops_the_room_level_claim(enforcing):
    """The scenario itself.

    W-A2 has no sensor of its own; a corridor sensor exists. The answer must NOT present a
    corridor number as a room number.
    """
    status, text, verdict, gate = _answer(ROOM_WITHOUT, enforcing)
    assert verdict.grade is SpatialAdequacy.PROXY
    assert not gate.passed
    assert status is not AnswerStatus.OBSERVED


def test_the_corridor_value_is_still_reported_as_context(enforcing):
    """Refusing outright would discard real evidence, which the rule never asks for."""
    _status, text, _v, _g = _answer(ROOM_WITHOUT, enforcing)
    assert "900 ppm" in text
    assert "W-COR" in text  # the proxy is NAMED
    assert "no sensor inside" in text
    assert "not a measurement of" in text


def test_the_answer_never_attributes_the_value_to_the_room(enforcing):
    """The precise failure: a corridor number presented as the room's."""
    _status, text, _v, _g = _answer(ROOM_WITHOUT, enforcing)
    assert "The reading for W-A2 is 900 ppm" not in text


def test_a_room_with_no_sensor_anywhere_near_is_not_assessable(enforcing):
    """Distinct from the proxy case, and a different remedy: connect a sensor."""
    verdict = best_verdict("http://fixture/W-B9", [PointFacts("p-elsewhere")])
    gate = spatial_gate(enforcing, verdict.grade, "space")
    assert verdict.grade is SpatialAdequacy.NONE
    assert apply([gate], AnswerStatus.OBSERVED) is AnswerStatus.NOT_ASSESSABLE
    assert "connect a sensor" in gate.remedy.lower()


def test_a_validated_served_zone_restores_the_room_level_answer(enforcing):
    """The one alternative the Master Report permits, and proof the gate is not blanket."""
    sensors = [
        PointFacts("p-ahu", containing_space=CORRIDOR, validated_zone_spaces=(ROOM_WITHOUT,))
    ]
    verdict = best_verdict(ROOM_WITHOUT, sensors)
    gate = spatial_gate(enforcing, verdict.grade, "space")
    assert verdict.grade is SpatialAdequacy.SERVED_ZONE
    assert gate.passed
    assert apply([gate], AnswerStatus.OBSERVED) is AnswerStatus.OBSERVED


def test_an_unvalidated_zone_does_not_restore_it(enforcing):
    """Fails closed: an unvalidated zone silently trusted is substitution with a label on it."""
    sensors = [
        PointFacts("p-ahu", containing_space=CORRIDOR, unvalidated_zone_spaces=(ROOM_WITHOUT,))
    ]
    gate = spatial_gate(enforcing, best_verdict(ROOM_WITHOUT, sensors).grade, "space")
    assert not gate.passed


# ── the test must fail if the guard is removed ───────────────────────────────


def test_the_scenario_would_fail_without_the_gate():
    """A scenario test that passes with the protection disabled is not testing it.

    With the gate advisory (the shipped default), the same evidence produces the OLD
    behaviour -- which is exactly why the rollout is staged, and why this assertion is worth
    making explicit rather than assuming.
    """
    advisory = load_policy("fixture")  # ships advisory
    verdict = best_verdict(ROOM_WITHOUT, SENSORS)
    gate = spatial_gate(advisory, verdict.grade, "space")
    assert not gate.passed  # the verdict is still correct...
    assert not gate.blocks  # ...but it does not act yet
    assert apply([gate], AnswerStatus.OBSERVED) is AnswerStatus.OBSERVED
