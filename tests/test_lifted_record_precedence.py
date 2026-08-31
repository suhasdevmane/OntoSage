# -*- coding: utf-8 -*-
"""A lifted register is not the register (V7-T19).

A document is a statement ABOUT a system of record. Lifting it makes it queryable; it
must not make it authoritative. Without the lower rank a stale Markdown table silently
outranks a live register — which is exactly what BUG-194 was: a GUI policy edit shadowed
by an old copy, with the file right, the API wrong, and the editor reporting success.
"""

from __future__ import annotations

import pytest

from orchestrator.services.evidence.precedence import RANK, SourceClaim, _DEFAULT_KIND_TIER

pytestmark = pytest.mark.unit


def test_a_lifted_record_loses_to_authored_ttl():
    assert RANK["document_derived"] < RANK["authoritative"]


def test_a_lifted_record_still_beats_a_sensor_reading():
    """A transcribed permit log knows what a CO2 sensor cannot."""
    assert RANK["document_derived"] > RANK["measurement"]


def test_the_tier_ordering_is_total_and_unknown_is_lowest():
    ordered = sorted(RANK, key=lambda t: RANK[t])
    assert ordered == ["unknown", "inference", "measurement", "document_derived", "authoritative"]


def test_the_kind_maps_to_its_own_tier():
    assert _DEFAULT_KIND_TIER["document_derived"] == "document_derived"


def test_a_policy_document_is_still_authoritative():
    """A policy document IS the system of record for a policy — that must not regress."""
    assert _DEFAULT_KIND_TIER["document"] == "authoritative"


def test_a_lifted_claim_ranks_between_them():
    lifted = SourceClaim("ontosage:Permit", "document_derived")
    authored = SourceClaim("bldg:permit_register", "authoritative")
    sensor = SourceClaim("uuid-1", "measurement")
    assert sensor.rank < lifted.rank < authored.rank
