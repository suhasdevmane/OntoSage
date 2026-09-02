# -*- coding: utf-8 -*-
"""A filed report is evidence, and says what kind (TODO-229, 2026-08-27).

A report-intake turn -- "the tap in 5.16 is dripping" -- wrote report_intake_result
and produced a fail-closed record: NOT_ASSESSABLE, "no lane produced evidence for
this answer". The chokepoint was working as designed; the lane simply was not in
its table. T02's objective names ten lanes and report intake is an eleventh, so it
was deliberately out of that task's scope.

The design question the tracker flagged was what KIND of claim a filed report is,
with a standing instruction not to force it into an existing category to make a
probe go green: that would blur a human report into a sensor reading.

It did not need inventing. evidence/precedence.py already grades a human_report as
"inference -- a person's account is evidence, not a measurement", and
EvidenceSource.kind has documented 'human_report' since the model was written
while nothing ever emitted one. Both were already the right answer.

So: INFERRED, never OBSERVED. Nobody measured the tap; somebody said so. The ACT
is an authoritative one on the system's own register, which is why the operation
matches register_result.
"""

import pytest

from orchestrator.services.evidence.assemble import (
    T02_LANES,
    build_evidence_record,
    infer_lane,
)
from shared.models import AnswerStatus, Operation

pytestmark = pytest.mark.unit


def _intake(**kw):
    base = {
        "category": "maintenance",
        "action": "filed",
        "report_id": "R-123",
        "location": "Room 5.16",
    }
    base.update(kw)
    return {"report_intake_result": base}


# -- the lane is recognised ---------------------------------------------------
def test_a_report_turn_is_no_longer_unassessable():
    """The defect: a filed report produced "no lane produced evidence"."""
    rec = build_evidence_record(_intake())
    assert rec.status is not AnswerStatus.NOT_ASSESSABLE
    assert infer_lane(_intake()) == "report_intake_result"


def test_a_report_is_inferred_never_observed():
    """The whole point. OBSERVED would invite a downstream reader to treat "the tap
    is dripping" as something the building measured."""
    rec = build_evidence_record(_intake())
    assert rec.status is AnswerStatus.INFERRED
    assert rec.status is not AnswerStatus.OBSERVED


def test_the_act_is_an_authoritative_one_on_the_register():
    rec = build_evidence_record(_intake())
    assert rec.operation is Operation.AUTHORITATIVE_LOOKUP


# -- and it cites the person, not an instrument -------------------------------
def test_the_report_is_cited_as_a_human_report():
    rec = build_evidence_record(_intake())
    kinds = [s.kind for s in rec.sources]
    assert kinds == ["human_report"]
    assert rec.sources[0].source_id == "R-123"


def test_a_human_report_carries_no_instrument_timestamp():
    """A person's account has no observation time, and inventing one would make it
    look like a reading."""
    rec = build_evidence_record(_intake())
    assert rec.sources[0].observed_at is None
    assert rec.sources[0].calibration_state == "unknown"


def test_a_real_report_is_declared_real_not_undeclared():
    """Everywhere else a missing provenance degrades to None, because None and False
    are different claims. Here the claim is known: a person really did file it."""
    rec = build_evidence_record(_intake())
    assert rec.sources[0].simulated is False


def test_a_report_with_no_id_still_produces_a_source():
    """An unciteable report is still evidence; it just cannot be pointed at."""
    rec = build_evidence_record(_intake(report_id=""))
    assert [s.kind for s in rec.sources] == ["human_report"]
    assert rec.sources[0].source_id == "user_report"


# -- and nothing else changes -------------------------------------------------
def test_a_turn_with_no_report_gets_no_human_source():
    rec = build_evidence_record({"sql_result": {"rows": [1]}})
    assert not any(s.kind == "human_report" for s in rec.sources)


def test_report_intake_is_not_smuggled_into_the_ten_T02_lanes():
    """It is an ELEVENTH lane. T02's objective names ten, and quietly widening that
    list would make the task look like it covered something it did not."""
    assert "report_intake_result" not in T02_LANES
    assert len(T02_LANES) == 10


def test_the_status_matches_the_decision_precedence_already_made():
    """Two places must not disagree about what a person's account is worth."""
    import inspect

    from orchestrator.services.evidence import precedence

    src = inspect.getsource(precedence)
    assert '"human_report": "inference"' in src
