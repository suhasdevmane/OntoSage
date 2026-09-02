# -*- coding: utf-8 -*-
"""A lane that ran and found nothing has not OBSERVED anything (BUG-386).

Measured across the V7 regression-gate candidates: Q393, Q424, Q404, AO-035 and Q041 all
carry ``answer_status=observed`` while their text refuses outright. Q040 states the problem
in its own answer — *"I found 1 sensor in the ontology, but none of their identifiers appear
in the store they are registered to"* — and the evidence record still called that an
observation.

The cause was one line: ``infer_lane`` returned the first lane whose result dict was TRUTHY,
and a result with zero rows is truthy. So "ran and found nothing" and "observed something"
were the same thing to the record.

Judged structurally, from the ``success`` flag and row count the lanes already report. The
alternative — reading the prose to decide whether it was a refusal — is what the regression
gate does, and that approach moved its own blocking count from 3 to 22 across four runs over
ONE unchanged capture. The system must not adopt a technique that unreliable to describe its
own evidence.

This is not cosmetic. The evidence record feeds the provenance answer, the precedence tiers
and any downstream audit; a record that labels a refusal an OBSERVATION is wrong on its own
terms, and every consumer inherits the error.
"""

import pytest

from orchestrator.services.evidence.assemble import (
    build_evidence_record,
    infer_lane,
    lane_produced_evidence,
)
from shared.models import AnswerStatus, Operation

pytestmark = pytest.mark.unit


# ── the structural predicate ───────────────────────────────────────────────────────────


def test_a_row_lane_with_no_rows_produced_no_evidence():
    assert lane_produced_evidence("sql_result", {"success": True, "results": {"data": []}}) is False


def test_a_row_lane_with_rows_produced_evidence():
    assert (
        lane_produced_evidence("sql_result", {"success": True, "results": {"data": [{"v": 1}]}})
        is True
    )


def test_a_failed_lane_produced_no_evidence_whatever_it_returned():
    assert lane_produced_evidence("sql_result", {"success": False, "error": "timeout"}) is False


def test_a_prose_lane_is_not_judged_on_row_count():
    """A document answer's evidence IS the passage; 'no rows' says nothing about it."""
    assert (
        lane_produced_evidence("capability_result", {"formatted_response": "The policy says..."})
        is True
    )


def test_an_absent_lane_produced_no_evidence():
    assert lane_produced_evidence("sql_result", None) is False


# ── what that changes about the record ─────────────────────────────────────────────────


def test_a_lane_that_found_nothing_yields_not_assessable_rather_than_observed():
    """The Q040 shape: sensors resolved, no rows behind them."""
    rec = build_evidence_record(
        {"intent": "sensor_data", "sql_result": {"success": True, "results": {"data": []}}}
    )
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.status is not AnswerStatus.OBSERVED


def test_an_empty_earlier_lane_no_longer_masks_a_later_one_that_found_something():
    """The ordered table meant an empty analytics_result claimed the sql lane's answer."""
    lane = infer_lane(
        {
            "analytics_result": {"success": True, "results": {"data": []}},
            "sql_result": {"success": True, "results": {"data": [{"value": 21.4}]}},
        }
    )
    assert lane == "sql_result"


def test_a_lane_with_real_rows_is_still_observed():
    """The safety property: this must not turn every answer into a refusal."""
    rec = build_evidence_record(
        {
            "intent": "sensor_data",
            "sql_result": {"success": True, "results": {"data": [{"value": 612}]}},
        }
    )
    assert rec.status is AnswerStatus.OBSERVED
    assert rec.operation is Operation.OBSERVATION


def test_a_document_answer_is_unaffected():
    """Prose lanes carry no rows and must keep answering."""
    rec = build_evidence_record(
        {"intent": "capability", "capability_result": {"formatted_response": "Guest-WiFi is..."}}
    )
    assert rec.status is AnswerStatus.OBSERVED


def test_the_reason_is_stated_rather_than_left_blank():
    rec = build_evidence_record(
        {"intent": "sensor_data", "sql_result": {"success": True, "results": {"data": []}}}
    )
    assert rec.not_assessable_reason
