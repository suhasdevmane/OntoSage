# -*- coding: utf-8 -*-
"""D2/D3 of the QA-trial readiness plan (2026-10-02): `build_tags` must not crash on the
dict shape `_prov_stores` already carries, and the capability lane's answering provenance
values must resolve to a chip instead of being silently dropped.

Reproduced before the fix: `build_tags([{...}], None)` raised
`TypeError: unhashable type: 'dict'`, which escaped the caller's bare `except Exception`
logged at DEBUG and killed the ENTIRE footer -- including correctly-recorded string keys in
the same list -- on every register-lane turn (sparql_agent.py writes the dict shape).
"""
import pytest

from orchestrator.services import provenance as prov
from orchestrator.services.datasource_registry import BUILTIN_PROVENANCE

pytestmark = pytest.mark.unit


class TestTheDictShapeNoLongerCrashes:
    def test_a_dict_entry_does_not_raise(self):
        tags = prov.build_tags(
            [{"source_id": "ontosage:WorkOrder", "kind": "authoritative", "store": "graphdb"}],
            None,
        )
        assert len(tags) == 1
        assert tags[0].source_id == "ontosage:WorkOrder"

    def test_a_dict_entry_beside_a_string_entry_both_survive(self):
        """The TypeError used to kill the WHOLE list, string keys included."""
        tags = prov.build_tags(
            [{"source_id": "ontosage:WorkOrder", "store": "graphdb"}, "ontology"],
            None,
        )
        ids = {t.source_id for t in tags}
        assert "ontosage:WorkOrder" in ids
        assert "ontology" in ids

    def test_a_dict_entry_with_no_label_gets_a_readable_one_not_a_bare_id(self):
        tags = prov.build_tags([{"source_id": "ontosage:WorkOrder"}], None)
        assert tags[0].label != "ontosage:WorkOrder"
        assert "Work Order" in tags[0].label or "WorkOrder" not in tags[0].label

    def test_a_bare_uuid_source_id_gets_a_generic_label_not_the_uuid(self):
        tags = prov.build_tags([{"source_id": "c5214bff-94d0-5960-a2f2-cc092e6a4b09"}], None)
        assert tags[0].label == "Sensor reading"
        # the footer renders t.label, never t.source_id -- confirm the chip text is clean
        footer = prov.render_chips(tags)
        assert "c5214bff" not in footer

    def test_an_explicit_label_in_the_dict_is_kept(self):
        tags = prov.build_tags(
            [{"source_id": "store:energy_data", "label": "Energy Metering System"}], None
        )
        assert tags[0].label == "Energy Metering System"

    def test_a_dict_entry_records_the_synthetic_flag(self):
        tags = prov.build_tags([{"source_id": "x", "synthetic": True}], None)
        assert tags[0].synthetic is True
        tags2 = prov.build_tags([{"source_id": "x"}], None)
        assert tags2[0].synthetic is False

    def test_an_empty_or_malformed_list_is_still_safe(self):
        assert prov.build_tags([], None) == []
        assert prov.build_tags(None, None) == []


class TestCapabilityProvenanceAliases:
    @pytest.mark.parametrize(
        "value,expect_key",
        [
            ("building_profile", "ontology"),
            ("live_metrics", "live_sensors"),
            ("capability_graph", "ontology"),
            ("ontology_inventory", "ontology"),
            ("document_answered", "documents"),
            ("held_register_named", "ontology"),
        ],
    )
    def test_an_answering_capability_value_resolves_to_a_chip(self, value, expect_key):
        tags = prov.build_tags([value], None)
        assert len(tags) == 1
        assert tags[0].source_id == BUILTIN_PROVENANCE[expect_key].source_id

    @pytest.mark.parametrize(
        "value",
        [
            "referent_unverified",
            "referent_not_found",
            "building_profile_absent",
            "scenario_out_of_scope",
            "absent_system_of_record",
            "document_cannot_answer_live_state",
            "documents_do_not_answer",
            "no_match",
            "answer_provenance",
        ],
    )
    def test_a_decline_or_self_answer_value_gets_no_chip(self, value):
        """A decline must not cite a source (BUG-1401); the provenance lane's own
        self-answer names no NEW data source, so it gets no chip either."""
        assert prov.build_tags([value], None) == []

    def test_every_alias_target_is_a_real_builtin_key(self):
        for target in prov._CAPABILITY_PROVENANCE_ALIASES.values():
            assert target in BUILTIN_PROVENANCE
