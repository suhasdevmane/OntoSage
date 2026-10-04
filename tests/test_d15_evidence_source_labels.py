# -*- coding: utf-8 -*-
"""D15 (QA-trial plan, 2026-10-02): every EvidenceSource `_sources_from` builds carries a
reader-facing `label`, never a bare source_id -- a timeseries UUID or a record IRI printed
verbatim is BUG-1407's shape at the evidence layer, and D11's inline panel would have shipped
it on every answer with sources.
"""
import pytest

from orchestrator.services.evidence.assemble import _sources_from

pytestmark = pytest.mark.unit

UUID = "c5214bff-94d0-5960-a2f2-cc092e6a4b09"


class TestEveryBuiltSourceCarriesALabel:
    def test_a_dict_entry_with_no_label_gets_a_derived_one(self):
        out = _sources_from({"_prov_stores": [{"source_id": "ontosage:WorkOrder"}]})
        assert out[0].label and out[0].label != "ontosage:WorkOrder"

    def test_a_dict_entry_with_an_explicit_label_keeps_it(self):
        out = _sources_from(
            {
                "_prov_stores": [
                    {"source_id": "store:energy_data", "label": "Energy Metering System"}
                ]
            }
        )
        assert out[0].label == "Energy Metering System"

    def test_a_builtin_string_key_gets_its_real_label_not_a_generic_one(self):
        out = _sources_from({"_prov_stores": ["ontology"]})
        assert out[0].label == "Building model"

    def test_a_raw_uuid_from_contributing_uuids_gets_a_generic_label_not_the_uuid(self):
        out = _sources_from({"_prov_stores": [], "sensor_metadata": {UUID: {}}})
        assert out
        assert out[0].source_id == UUID
        assert out[0].label == "Sensor reading"

    def test_no_built_source_has_an_empty_label(self):
        out = _sources_from(
            {
                "_prov_stores": [
                    "ontology",
                    "store:energy_data",
                    {"source_id": "ontosage:WorkOrder"},
                ],
                "sensor_metadata": {UUID: {}},
            }
        )
        assert out
        assert all(s.label for s in out)
