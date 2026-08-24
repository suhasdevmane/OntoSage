# -*- coding: utf-8 -*-
"""The evidence chokepoint (V6-T02).

One assembler for all ten lanes. The alternative -- a record per lane -- was rejected on
direct evidence: BUG-210 in this repository was two copies of one step drifting until
identical inputs produced different results depending which path ran. Ten copies would
reproduce that ten times, and every drift would be invisible because each lane would still
be producing *a* record.

Two guarantees are load-bearing and both are asserted here:

* a lane that emits nothing yields NOT_ASSESSABLE **with a reason** -- silence is never read
  as success, which is what makes the chokepoint safe to add ahead of the lanes that do not
  populate it yet;
* assembly can never break an answer. A describer that can take down the thing it describes
  is worse than not having one.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.assemble import (
    _LANE_SEMANTICS,
    build_evidence_record,
    infer_lane,
    record_for_response,
)
from orchestrator.services.evidence.gates import GateVerdict
from orchestrator.services.evidence.policy import GateMode
from shared.models import AnswerStatus, Operation

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


# ── silence is never success ─────────────────────────────────────────────────


def test_a_lane_that_emitted_nothing_is_not_assessable():
    rec = build_evidence_record({}, now=NOW)
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert "no lane produced evidence" in rec.not_assessable_reason


def test_a_refusal_lane_is_a_correct_outcome_not_a_gap():
    """Declining by policy is an answer; it must not read as a missing record."""
    rec = build_evidence_record({"privacy_refusal_result": {"formatted_response": "no"}}, now=NOW)
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert "declined by policy" in rec.not_assessable_reason


# ── each lane implies a kind of claim ────────────────────────────────────────


# Derived from the table itself rather than restated. This list used to be a third
# hand-maintained copy of _LANE_SEMANTICS, and it carried the same wrong key name
# (`sql_data`) as the table did -- so the test agreed with the code about a string neither
# had checked against the pipeline, and the sql lane was unidentifiable in production while
# this file stayed green. Deriving it means the test can only ever disagree with the table
# by failing, and tests/test_evidence_chokepoint.py checks the table against the code.
@pytest.mark.parametrize(
    "key,operation,status",
    [(k, op, st) for k, op, st in _LANE_SEMANTICS],
    ids=[k for k, _o, _s in _LANE_SEMANTICS],
)
def test_lane_determines_operation_and_status(key, operation, status):
    rec = build_evidence_record({key: {"x": 1}}, now=NOW)
    assert rec.operation is operation
    assert rec.status is status


def test_a_register_lookup_is_not_an_observation():
    """A compliance date is looked up, not measured.

    Calling it OBSERVED would blur a register entry into a sensor reading, and the
    catalogues are explicit that the two must never be blurred.
    """
    rec = build_evidence_record({"register_result": {"x": 1}}, now=NOW)
    assert rec.operation is Operation.AUTHORITATIVE_LOOKUP


def test_the_most_derived_lane_wins():
    """A forecast built on an aggregate is a forecast, not a calculation."""
    results = {"analytics_result": {"a": 1}, "forecast_result": {"f": 1}}
    assert infer_lane(results) == "forecast_result"
    assert build_evidence_record(results, now=NOW).status is AnswerStatus.PREDICTED


# ── provenance ───────────────────────────────────────────────────────────────


def test_undeclared_provenance_is_none_not_false():
    """None and False are different claims: False asserts real, None says nobody said."""
    rec = build_evidence_record({"sql_result": [1], "uuids": ["u1"]}, now=NOW)
    assert rec.sources
    assert rec.sources[0].simulated is None
    assert rec.declared_simulated() is False


def test_declared_synthetic_provenance_is_carried():
    rec = build_evidence_record(
        {
            "sql_result": [1],
            "_prov_stores": [{"source_id": "s1", "store": "mysql:x", "synthetic": True}],
        },
        now=NOW,
    )
    assert rec.declared_simulated() is True


def test_a_malformed_provenance_tag_does_not_cost_the_record():
    rec = build_evidence_record({"sql_result": [1], "_prov_stores": [None, 42]}, now=NOW)
    assert rec.status is AnswerStatus.OBSERVED


def test_retrieved_at_is_always_set():
    assert build_evidence_record({}, now=NOW).retrieved_at == NOW


# ── a lane may override inference ────────────────────────────────────────────


def test_a_lane_partial_overrides_inference():
    """The lane knows things the bus does not."""
    rec = build_evidence_record(
        {"sql_result": [1], "evidence": {"interpreted_location": "Room 2.15", "completeness": 0.5}},
        now=NOW,
    )
    assert rec.interpreted_location == "Room 2.15"
    assert rec.completeness == 0.5


def test_an_unknown_field_in_a_partial_is_ignored():
    rec = build_evidence_record({"sql_result": [1], "evidence": {"nonsense_field": 1}}, now=NOW)
    assert rec.status is AnswerStatus.OBSERVED


def test_entities_and_time_range_are_lifted():
    rec = build_evidence_record(
        {
            "sql_result": [1],
            "entities": ["Room 2.15"],
            "time_range": {"start": "2026-08-01", "end": "2026-08-07"},
        },
        now=NOW,
    )
    assert rec.interpreted_location == "Room 2.15"
    assert "2026-08-01" in rec.requested_period


# ── gates restrict, never upgrade ────────────────────────────────────────────


def test_an_advisory_gate_failure_does_not_change_the_status():
    verdict = GateVerdict(
        "freshness", False, GateMode.ADVISORY, "stale", downgrade_to=AnswerStatus.INFERRED
    )
    rec = build_evidence_record({"sql_result": [1]}, now=NOW, gate_verdicts=[verdict])
    assert rec.status is AnswerStatus.OBSERVED
    assert rec.gates_applied == []


def test_an_enforcing_gate_failure_downgrades_and_records_itself():
    verdict = GateVerdict(
        "freshness",
        False,
        GateMode.ENFORCING,
        "the reading is 3 days old",
        remedy="restart the publisher",
        downgrade_to=AnswerStatus.NOT_ASSESSABLE,
    )
    rec = build_evidence_record({"sql_result": [1]}, now=NOW, gate_verdicts=[verdict])
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.gates_applied == ["freshness"]
    assert "3 days old" in rec.not_assessable_reason
    assert "restart" in rec.remedy


def test_gates_applied_is_what_separates_tightening_from_regression():
    """A refusal naming its gate is intended; one naming none is a regression."""
    rec = build_evidence_record({}, now=NOW)
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.gates_applied == []  # no gate claims responsibility


# ── assembly must never break an answer ──────────────────────────────────────


def test_record_for_response_returns_json_safe_output():
    out = record_for_response({"sql_result": [1]})
    assert isinstance(out, dict)
    assert out["status"] == "observed"


def test_record_for_response_survives_a_hostile_bus():
    """Whatever is on the bus, an answer still goes out."""

    class Explodes(dict):
        def get(self, *a, **k):
            raise RuntimeError("bus is on fire")

    out = record_for_response(Explodes())
    assert out["status"] == "not_assessable"
    assert "could not be assembled" in out["not_assessable_reason"]


def test_chokepoint_is_wired_into_the_response_node():
    """Pin the wiring: the assembler existing is not the same as it running."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator" / "workflow" / "_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert "record_for_response" in src
    assert 'results["evidence_record"]' in src


def test_record_is_surfaced_on_the_api_response():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text("utf-8")
    assert '"evidence_record"' in src
    # It must NOT replace the V4 dossier: an absent dossier and an absent record are
    # different facts, and merging the keys would make them indistinguishable.
    assert '"evidence": updated_state.intermediate_results.get("evidence_dossier")' in src
