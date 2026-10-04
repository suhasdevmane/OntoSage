# -*- coding: utf-8 -*-
"""D8 (QA-trial plan, 2026-10-02): the deliberation lane never calls `_prov.record` --
its evidence is the dossier, not a store-key list -- so its answers were the single
largest group of records carrying ZERO sources (32 of 70 non-declined zero-source
records measured live, all `deliberate`). `evidence_dossier.evidence` already carries
`sensor_uuid`, `stored_at` and `latest`; `_sources_from` and `contributing_uuids` now both
read it, extending an existing dossier reader rather than adding a new one.
"""
import pytest

from orchestrator.services.evidence.assemble import _sources_from, contributing_uuids

pytestmark = pytest.mark.unit

DOSSIER_ROW = {
    "space": "Room 3.16",
    "modality": "noise",
    "value": 59.9,
    "basis": "recent mean",
    "window_hours": 1.0,
    "n_points": 15,
    "sensor_uuid": "c5214bff-94d0-5960-a2f2-cc092e6a4b09",
    "stored_at": "noise_data",
    "simulated": False,
    "latest": "2026-10-02T13:00:00",
}


class TestDossierRowsBecomeSources:
    def test_a_dossier_row_becomes_a_source(self):
        out = _sources_from({"evidence_dossier": {"evidence": [DOSSIER_ROW]}})
        assert len(out) == 1
        assert out[0].source_id == DOSSIER_ROW["sensor_uuid"]
        assert out[0].store == "noise_data"
        assert out[0].simulated is False
        assert out[0].observed_at is not None

    def test_the_source_carries_a_readable_label_not_the_bare_uuid(self):
        out = _sources_from({"evidence_dossier": {"evidence": [DOSSIER_ROW]}})
        assert out[0].label == "Sensor reading"

    def test_several_dossier_rows_deduplicate_by_uuid(self):
        out = _sources_from({"evidence_dossier": {"evidence": [DOSSIER_ROW, DOSSIER_ROW]}})
        assert len(out) == 1

    def test_no_dossier_is_the_unchanged_empty_case(self):
        assert _sources_from({}) == []

    def test_a_malformed_row_does_not_break_the_rest(self):
        out = _sources_from(
            {"evidence_dossier": {"evidence": [{"not": "a real row"}, DOSSIER_ROW]}}
        )
        assert len(out) == 1
        assert out[0].source_id == DOSSIER_ROW["sensor_uuid"]


class TestContributingUuidsSeesTheDossierToo:
    def test_a_dossier_uuid_is_returned(self):
        out = contributing_uuids({"evidence_dossier": {"evidence": [DOSSIER_ROW]}})
        assert DOSSIER_ROW["sensor_uuid"] in out

    def test_sensor_metadata_and_the_dossier_both_contribute_without_duplicating(self):
        out = contributing_uuids(
            {
                "sensor_metadata": {DOSSIER_ROW["sensor_uuid"]: {}},
                "evidence_dossier": {"evidence": [DOSSIER_ROW]},
            }
        )
        assert out.count(DOSSIER_ROW["sensor_uuid"]) == 1

    def test_no_dossier_is_the_unchanged_empty_case(self):
        assert contributing_uuids({}) == []
