# -*- coding: utf-8 -*-
"""The evidence record and its taxonomies (V6-T01).

Master Report 12.1 and Table 16. Every other V6 task writes into this structure, so its
shape and its defaults are load-bearing: a record that defaults to "answered" would make
every un-instrumented lane look confident, which is the failure the whole plan exists to
prevent.
"""

import json
from datetime import datetime, timedelta

import pytest

from shared.models import (
    AnswerStatus,
    EvidenceRecord,
    EvidenceSource,
    OmissionReason,
    OmittedCriterion,
    Operation,
    SpatialAdequacy,
)

pytestmark = pytest.mark.unit


# ── the taxonomies are the supervisors', and must stay exactly as given ──────


def test_answer_status_has_exactly_the_six_master_report_members():
    """Six, no more. A seventh reopens the ambiguity the taxonomy exists to close."""
    assert [s.value for s in AnswerStatus] == [
        "observed",
        "calculated",
        "inferred",
        "predicted",
        "recommended",
        "not_assessable",
    ]


def test_operation_covers_the_eight_acts_the_catalogues_require():
    """Eight since CAVEAT-365. The list is pinned so it cannot drift silently.

    It was seven, and the seven were derived when only SIX of the thirty-seven stakeholder
    catalogues had been extracted. Nothing re-derived the taxonomy when the other 31
    arrived, so COMPARISON — the most demanded act in the corpus — had no member, and every
    comparison was labelled with whatever lane computed it.

    Update this list in the SAME commit as any change to `Operation`, the way the routing
    contract's precedence order is pinned. A pin that is edited afterwards to make a suite
    green is not a pin.
    """
    assert {o.value for o in Operation} == {
        "observation",
        "authoritative_lookup",
        "calculation",
        "comparison",
        "estimate",
        "forecast",
        "diagnosis",
        "recommendation",
    }


def test_spatial_adequacy_is_graded_not_binary():
    """Master 8 permits proxy data LABELLED as context while forbidding substitution."""
    assert {s.value for s in SpatialAdequacy} == {"in_room", "served_zone", "proxy", "none"}


def test_restricted_is_distinct_from_missing():
    """Collapsing them tells a user data does not exist when they simply may not see it."""
    assert OmissionReason.RESTRICTED != OmissionReason.MISSING
    assert "restricted" in {r.value for r in OmissionReason}


# ── defaults must fail closed ─────────────────────────────────────────────────


def test_an_empty_record_is_not_assessable():
    """The default must be the humble one.

    A record defaulting to OBSERVED would let any lane that forgot to populate it present
    a guess as a measurement.
    """
    r = EvidenceRecord()
    assert r.status is AnswerStatus.NOT_ASSESSABLE
    assert r.is_answerable() is False
    assert r.spatial_adequacy is SpatialAdequacy.NONE
    assert r.calibration_state == "unknown"
    assert r.completeness is None


def test_unknown_calibration_is_not_an_assumed_good_default():
    assert EvidenceSource(source_id="s1", kind="sensor").calibration_state == "unknown"


def test_source_provenance_none_is_not_the_same_as_real():
    """None means the source declares nothing; only False means declared-real."""
    s = EvidenceSource(source_id="s1", kind="sensor")
    assert s.simulated is None
    assert EvidenceRecord(sources=[s]).declared_simulated() is False


# ── behaviour ────────────────────────────────────────────────────────────────


def test_any_simulated_source_makes_the_whole_answer_simulated():
    """An answer mixing a real reading with a simulated booking is not a real answer."""
    rec = EvidenceRecord(
        status=AnswerStatus.CALCULATED,
        sources=[
            EvidenceSource(source_id="real", kind="sensor", simulated=False),
            EvidenceSource(source_id="sim", kind="authoritative", simulated=True),
        ],
    )
    assert rec.declared_simulated() is True


def test_observed_at_and_retrieved_at_are_separate():
    """Without both, 'stale evidence is not current status' cannot be enforced."""
    observed = datetime(2026, 8, 1, 9, 0, 0)
    rec = EvidenceRecord(
        status=AnswerStatus.OBSERVED,
        latest_evidence_at=observed,
        retrieved_at=observed + timedelta(days=3),
    )
    assert rec.retrieved_at > rec.latest_evidence_at
    assert (rec.retrieved_at - rec.latest_evidence_at).days == 3


def test_gates_applied_is_what_separates_tightening_from_regression():
    """A refusal naming its gate is a tightening; one naming none is a regression."""
    tightened = EvidenceRecord(
        status=AnswerStatus.NOT_ASSESSABLE,
        gates_applied=["freshness"],
        not_assessable_reason="newest observation is 3 days old",
        remedy="restart the publisher for co2_data",
    )
    silent = EvidenceRecord(status=AnswerStatus.NOT_ASSESSABLE)
    assert tightened.gates_applied and tightened.remedy
    assert not silent.gates_applied


def test_completeness_is_bounded():
    EvidenceRecord(completeness=0.0)
    EvidenceRecord(completeness=1.0)
    with pytest.raises(Exception):
        EvidenceRecord(completeness=1.4)


def test_conflicts_are_recorded_rather_than_resolved():
    """Averaging two disagreeing sensors yields a value neither measured."""
    rec = EvidenceRecord(
        status=AnswerStatus.OBSERVED,
        conflicts=["sensor A 21.0 C vs sensor B 27.4 C, both in space 2.15"],
    )
    assert len(rec.conflicts) == 1


def test_record_round_trips_through_json():
    """It is a MACHINE-readable record; if it cannot serialise it is not one."""
    rec = EvidenceRecord(
        status=AnswerStatus.CALCULATED,
        operation=Operation.CALCULATION,
        interpreted_location="Room 2.15",
        spatial_scope="space",
        requested_period="last 7 days",
        sources=[
            EvidenceSource(
                source_id="uuid-1",
                kind="sensor",
                store="mysql:co2_data",
                simulated=False,
                observed_at=datetime(2026, 8, 21, 8, 0, 0),
                calibration_state="calibrated",
                spatial_adequacy=SpatialAdequacy.IN_ROOM,
            )
        ],
        completeness=0.94,
        spatial_adequacy=SpatialAdequacy.IN_ROOM,
        thresholds_applied=["ASHRAE 62.1 (cited in config/recipes.yaml)"],
        omitted_criteria=[
            OmittedCriterion(
                criterion="noise level",
                reason=OmissionReason.NOT_INSTRUMENTED,
                detail="no acoustic sensor in this space",
            )
        ],
        gates_applied=["completeness"],
    )
    restored = EvidenceRecord.model_validate(json.loads(rec.model_dump_json()))
    assert restored.status is AnswerStatus.CALCULATED
    assert restored.sources[0].spatial_adequacy is SpatialAdequacy.IN_ROOM
    assert restored.omitted_criteria[0].reason is OmissionReason.NOT_INSTRUMENTED
    assert restored.completeness == pytest.approx(0.94)


def test_every_master_report_field_group_is_present():
    """Guards against a field being dropped in a later refactor."""
    fields = set(EvidenceRecord.model_fields)
    for required in (
        "interpreted_location",
        "spatial_scope",
        "requested_period",
        "sources",
        "latest_evidence_at",
        "retrieved_at",
        "completeness",
        "spatial_adequacy",
        "calibration_state",
        "analysis_method",
        "comparison_baseline",
        "uncertainty",
        "thresholds_applied",
        "access_tier",
        "omitted_criteria",
    ):
        assert required in fields, f"Master Report 12.1 field missing: {required}"
