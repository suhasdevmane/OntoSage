# -*- coding: utf-8 -*-
"""D13 (QA-trial plan, 2026-10-02): SpatialAdequacy gets a fourth state, UNGRADED, distinct
from the MEASURED state NONE ("no sensor covers the space asked about"). Before this, both
"grading never ran" and "grading ran and found nothing" shared one value, so the field
carried no information on the 400 of 400 live records where it was never written (the
Pydantic default, never overwritten with a real grade).
"""
import pytest

from shared.models import EvidenceRecord, EvidenceSource, SpatialAdequacy

pytestmark = pytest.mark.unit


class TestTheDefaultIsUngradedNotNone:
    def test_evidence_record_defaults_to_ungraded(self):
        rec = EvidenceRecord(status="observed", operation="observation")
        assert rec.spatial_adequacy == SpatialAdequacy.UNGRADED
        assert rec.spatial_adequacy != SpatialAdequacy.NONE

    def test_evidence_source_defaults_to_ungraded(self):
        src = EvidenceSource(source_id="x", kind="sensor")
        assert src.spatial_adequacy == SpatialAdequacy.UNGRADED

    def test_a_real_measured_absence_is_still_representable(self):
        rec = EvidenceRecord(
            status="not_assessable", operation="observation", spatial_adequacy=SpatialAdequacy.NONE
        )
        assert rec.spatial_adequacy == SpatialAdequacy.NONE


class TestNoConsumerKeyErrorsOnTheNewState:
    def test_narration_adequacy_note_does_not_raise(self):
        from orchestrator.services.evidence.narration import adequacy_note

        assert adequacy_note(SpatialAdequacy.UNGRADED) == ""
        # the three real grades are unchanged
        assert adequacy_note(SpatialAdequacy.NONE) == "No sensor covers this space."
        assert adequacy_note(SpatialAdequacy.IN_ROOM) == ""

    def test_spatial_gate_does_not_refuse_an_ungraded_answer(self):
        from orchestrator.services.evidence.gates import spatial_gate
        from orchestrator.services.evidence.policy import load_policy

        verdict = spatial_gate(load_policy(), SpatialAdequacy.UNGRADED, "space")
        assert verdict.passed is True

    def test_spatial_gate_still_refuses_a_real_measured_none(self):
        from orchestrator.services.evidence.gates import spatial_gate
        from orchestrator.services.evidence.policy import load_policy

        verdict = spatial_gate(load_policy(), SpatialAdequacy.NONE, "space")
        assert verdict.passed is False
        assert "no sensor covers" in verdict.reason.lower()

    def test_best_verdict_rank_lookup_does_not_raise_on_an_unlisted_grade(self):
        from orchestrator.services.evidence.spatial_adequacy import best_verdict

        # an empty candidate list is the one call shape this function must always accept
        verdict = best_verdict("Room 2.01", [])
        assert verdict.grade == SpatialAdequacy.NONE
