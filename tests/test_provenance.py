"""
Phase 3 tests — provenance helper (record / build_tags / render).

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services import provenance as prov
from orchestrator.services.datasource_registry import DataSourceRegistry

pytestmark = pytest.mark.unit


MANIFEST = textwrap.dedent(
    """
    datasources:
      - id: occupancy
        label: "Occupancy Sensing"
        modality: occupancy
        kind: timeseries
        synthetic: true
        provenance_system: "Occupancy Sensing System"
        color: "#3B82F6"
        ts_table: occupancy_data
        unlocks: [desk_availability]
    """
)


def _state():
    return SimpleNamespace(intermediate_results={})


def test_record_dedups_and_keeps_order():
    st = _state()
    prov.record(st, "ontology")
    prov.record(st, "store:occupancy_data")
    prov.record(st, "ontology")  # dup
    assert st.intermediate_results["_prov_stores"] == ["ontology", "store:occupancy_data"]


def test_record_sql_stores_maps_storedat_uris():
    st = _state()
    prov.record_sql_stores(st, {"u1": "bldg:occupancy_data", "u2": "http://x#energy_data"})
    assert st.intermediate_results["_prov_stores"] == ["store:occupancy_data", "store:energy_data"]


def test_record_sql_stores_fallback_live():
    st = _state()
    prov.record_sql_stores(st, {})
    assert st.intermediate_results["_prov_stores"] == ["live_sensors"]


def test_build_tags_builtin_and_datasource(tmp_path: Path):
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    tags = prov.build_tags(["ontology", "store:occupancy_data", "analytics"], reg)
    by_id = {t.source_id: t for t in tags}
    assert by_id["ontology"].synthetic is False
    assert by_id["occupancy"].synthetic is True
    assert by_id["occupancy"].label == "Occupancy Sensing System"
    assert by_id["occupancy"].color == "#3B82F6"
    assert by_id["analytics"].source_id == "analytics"


def test_build_tags_unknown_table_falls_back_to_unknown_source(tmp_path: Path):
    """BUG-145: an unregistered table must never be chip-labeled as real data."""
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    tags = prov.build_tags(["store:mystery_table"], reg)
    assert tags[0].source_id == "unknown_source"
    assert tags[0].label == "Unknown Source"
    assert tags[0].synthetic is False
    assert all(t.label != "Live Sensor Data" for t in tags)


def test_build_tags_no_registry():
    tags = prov.build_tags(["ontology", "store:occupancy_data"], None)
    ids = {t.source_id for t in tags}
    assert ids == {"ontology", "unknown_source"}


def test_build_tags_multiple_unknown_tables_dedup_to_one_chip(tmp_path: Path):
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    tags = prov.build_tags(["store:mystery_a", "store:mystery_b"], reg)
    assert [t.source_id for t in tags] == ["unknown_source"]


def test_build_tags_explicit_live_sensors_key_still_real():
    """The built-in 'live_sensors' store key keeps its real tag — only the
    unregistered-table fallback changed."""
    tags = prov.build_tags(["live_sensors"], None)
    assert tags[0].source_id == "live_sensors"
    assert tags[0].label == "Live Sensor Data"


def test_render_chips_unknown_source_not_marked_simulated():
    chips = prov.render_chips(prov.build_tags(["store:mystery_table"], None))
    assert "Unknown Source" in chips
    assert "simulated" not in chips


def test_render_chips_marks_synthetic(tmp_path: Path):
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    tags = prov.build_tags(["ontology", "store:occupancy_data"], reg)
    chips = prov.render_chips(tags)
    assert "Building Ontology" in chips
    assert "Occupancy Sensing System · simulated" in chips


def test_render_chips_empty():
    assert prov.render_chips([]) == ""


def test_tags_to_dicts_serializable(tmp_path: Path):
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    dicts = prov.tags_to_dicts(prov.build_tags(["store:occupancy_data"], reg))
    assert dicts[0]["source_id"] == "occupancy"
    assert dicts[0]["color"] == "#3B82F6"
    assert dicts[0]["synthetic"] is True
