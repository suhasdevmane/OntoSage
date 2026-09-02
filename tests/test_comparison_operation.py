# -*- coding: utf-8 -*-
"""Comparison is an act the system performs, and the record must say so (CAVEAT-365).

`compare` is a `data` pipeline intent with no lane of its own: it flows through
sparql -> sql -> analytics. The evidence record derives the operation from the lane, so
every comparison was stamped OBSERVATION or CALCULATION depending on which of those
produced the numbers. Neither names the act.

Two things were wrong, and the caveat only recorded the first:

1. `Operation` had no COMPARISON member — the taxonomy was derived from six of the
   thirty-seven catalogues and never re-derived.
2. `EvidenceRecord.comparison_baseline`, the one place comparison survived, was defined
   and read but **never written by anything**. So comparison was not merely mislabelled;
   it was absent from the record entirely.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services.answer_provenance import render
from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus, Operation

pytestmark = pytest.mark.unit


def _results(intent="compare", entities=None, **extra):
    base = {
        "intent": intent,
        "entities": entities if entities is not None else ["floor 1", "floor 5"],
        "analytics_result": {"formatted_response": "Floor 1 is 1.8 C warmer than floor 5."},
    }
    base.update(extra)
    return base


def test_comparison_is_a_member_of_the_operation_enum():
    assert Operation.COMPARISON.value == "comparison"


def test_a_comparison_is_recorded_as_a_comparison_not_as_the_lane_that_computed_it():
    rec = build_evidence_record(_results(), now=datetime.now(timezone.utc))
    assert rec.operation is Operation.COMPARISON, (
        "a comparison computed by the analytics lane was stamped "
        f"{rec.operation} — the lane, not the act"
    )


def test_the_baseline_names_what_it_was_compared_against():
    rec = build_evidence_record(_results(entities=["floor 1", "floor 5"]))
    assert rec.comparison_baseline == "floor 5"


def test_a_single_referent_names_no_baseline():
    """With one referent there is nothing to compare against; inventing one is fabrication."""
    rec = build_evidence_record(_results(entities=["floor 1"]))
    assert rec.comparison_baseline == ""


def test_the_alias_is_treated_the_same_as_the_canonical_name():
    """`comparison` is a declared alias of `compare` in intent_definitions.yaml."""
    rec = build_evidence_record(_results(intent="comparison"))
    assert rec.operation is Operation.COMPARISON


def test_a_non_comparison_keeps_the_operation_its_lane_gave_it():
    """The safety property: this must not relabel everything that touches two numbers."""
    rec = build_evidence_record(_results(intent="sensor_data"))
    assert rec.operation is not Operation.COMPARISON


def test_a_comparison_with_no_lane_is_not_relabelled_as_an_act_it_never_performed():
    """A declined comparison performed nothing. Stamping COMPARISON would dress up a refusal."""
    rec = build_evidence_record({"intent": "compare", "entities": ["floor 1", "floor 5"]})
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.operation is not Operation.COMPARISON


def test_provenance_describes_the_act_rather_than_its_ingredients():
    text = render(
        {
            "status": "calculated",
            "operation": "comparison",
            "comparison_baseline": "floor 5",
            "sources": [],
        }
    )
    assert text is not None
    assert "set against each other" in text
    assert "Compared against:** floor 5" in text
