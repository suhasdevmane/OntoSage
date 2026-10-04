# -*- coding: utf-8 -*-
"""D6 (QA-trial plan, 2026-10-02): `rec.source_tier` -- the answer to "what kind of thing
answered you" (W4-02) -- used to be set only when at least two sources AND at least two
distinct tiers contributed. Measured live over 400 stored records that was 327 of them
(81.8%): the field was empty on almost every turn, because most turns have exactly one
tier's worth of evidence behind them. `resolve()` already degrades correctly with a single
claim; the early returns just never let it run.
"""
import pytest

from orchestrator.services.evidence.assemble import _precedence_verdicts
from shared.models import EvidenceRecord, EvidenceSource

pytestmark = pytest.mark.unit


def _rec(sources):
    r = EvidenceRecord(status="observed", operation="observation")
    r.sources = sources
    return r


class TestSingleSourceStillSetsTheTier:
    def test_one_sensor_source_sets_the_measurement_tier(self):
        rec = _rec([EvidenceSource(source_id="u1", kind="sensor")])
        _precedence_verdicts({}, rec)
        assert rec.source_tier == "measurement"
        assert rec.conflicts == []  # one source cannot disagree with itself

    def test_one_authoritative_source_sets_the_authoritative_tier(self):
        rec = _rec([EvidenceSource(source_id="r1", kind="authoritative")])
        _precedence_verdicts({}, rec)
        assert rec.source_tier == "authoritative"

    def test_two_sources_of_the_same_tier_still_set_it_with_no_conflict(self):
        rec = _rec(
            [
                EvidenceSource(source_id="u1", kind="sensor"),
                EvidenceSource(source_id="u2", kind="sensor"),
            ]
        )
        _precedence_verdicts({}, rec)
        assert rec.source_tier == "measurement"
        assert rec.conflicts == []

    def test_no_sources_leaves_the_tier_unset(self):
        rec = _rec([])
        _precedence_verdicts({}, rec)
        assert rec.source_tier == ""
