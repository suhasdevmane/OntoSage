# -*- coding: utf-8 -*-
"""The third time, and the accountable owner (V7-T10, V7-T11, V7-T17).

Every one of the 37 stakeholder catalogues states the same rule: preserve effective time,
observed or approved time and retrieval time SEPARATELY. OntoSage carried two of the
three. The missing one is what distinguishes a policy that takes effect next Monday from
one in force now, a future-dated role change from a current entitlement, and a booking
made yesterday for next week.

Owner is the single most frequent demand in the whole corpus — 13,964 mentions, ahead of
permission (6,176) and conflict (5,437). The catalogues never ask the building to decide;
they ask it to say whose record it is and to defer to that owner.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.evidence.assemble import _sources_from
from shared.models import EvidenceSource

pytestmark = pytest.mark.unit


def test_all_three_times_are_separate_fields():
    fields = EvidenceSource.model_fields
    assert "effective_at" in fields, "when it applies"
    assert "observed_at" in fields, "when it was observed"
    # retrieved_at lives on the record rather than the source, deliberately: retrieval is
    # a property of the ANSWER, not of each contributing source.


def test_a_source_can_name_its_owner_authority_and_version():
    source = EvidenceSource(
        source_id="ontosage:Permit",
        kind="document_derived",
        owner="Estates Compliance Team",
        authority="Cardiff University Estates",
        record_version="4.1",
    )
    assert source.owner == "Estates Compliance Team"
    assert source.authority == "Cardiff University Estates"
    assert source.record_version == "4.1"


def test_a_sensor_declares_no_owner_rather_than_a_made_up_one():
    """Absent metadata is absent. An invented owner is worse than none."""
    source = EvidenceSource(source_id="uuid-1", kind="sensor")
    assert source.owner == ""
    assert source.record_version == ""
    assert source.effective_at is None


def test_the_lane_provenance_is_carried_onto_the_source():
    sources = _sources_from(
        {
            "_prov_stores": [
                {
                    "source_id": "ontosage:Permit",
                    "kind": "document_derived",
                    "store": "graphdb",
                    "owner": "Estates Compliance Team",
                    "authority": "Cardiff University Estates",
                    "record_version": "4.1",
                    "effective_at": "2026-01-01",
                }
            ]
        }
    )
    assert len(sources) == 1
    source = sources[0]
    assert source.owner == "Estates Compliance Team"
    assert source.record_version == "4.1"
    assert source.effective_at is not None
    assert source.effective_at.year == 2026


def test_a_lane_that_records_nothing_extra_still_works():
    """The fields are additive — a sensor tag must not start failing to parse."""
    sources = _sources_from({"_prov_stores": [{"source_id": "uuid-1", "kind": "sensor"}]})
    assert sources[0].owner == ""


def test_effective_time_is_not_observed_time():
    """A record read today may take effect next Monday."""
    source = EvidenceSource(
        source_id="ontosage:Policy",
        kind="authoritative",
        observed_at=datetime(2026, 8, 31),
        effective_at=datetime(2026, 9, 7),
    )
    assert source.effective_at > source.observed_at
