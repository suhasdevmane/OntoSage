"""
Tests for the GUI create flow — registry.add_source + manager.create + overlay.

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from orchestrator.services.datasource_manager import DataSourceManager
from orchestrator.services.datasource_registry import DataSourceRegistry

pytestmark = pytest.mark.unit


PRIMARY = textwrap.dedent(
    """
    datasources:
      - id: occupancy
        label: "Occupancy Sensing"
        modality: occupancy
        kind: timeseries
        provenance_system: "Occupancy Sensing System"
        color: "#3B82F6"
        ts_table: occupancy_data
        unlocks: [desk_availability]
    """
)

NEW_SPEC = {
    "id": "footfall",
    "label": "Footfall Counting",
    "modality": "footfall",
    "kind": "timeseries",
    "provenance_system": "Footfall System",
    "color": "#22c55e",
    "ts_table": "occupancy_data",
    "unlocks": ["footfall_trends"],
    "match_keywords": ["footfall"],
    "points": [
        {
            "local": "Footfall_Sensor_Entrance",
            "brick_class": "brick:People_Count_Sensor",
            "location": "bldg:Floor0",
            "unit": "unit:NUM",
        }
    ],
    "generator": {"kind": "occupancy_profile", "window_days": 7, "interval_minutes": 60},
}


def _reg(tmp_path: Path) -> DataSourceRegistry:
    (tmp_path / "datasources.yaml").write_text(PRIMARY, encoding="utf-8")
    r = DataSourceRegistry("bldg1", input_root=tmp_path)
    r.load()
    return r


def test_add_source_persists_and_indexes(tmp_path):
    reg = _reg(tmp_path)
    spec = reg.add_source(NEW_SPEC)
    assert spec.id == "footfall"
    # indexed in memory
    assert reg.get("footfall") is not None
    # point UUID derived
    assert spec.points[0].uuid
    # persisted to the custom overlay (curated seed untouched)
    custom = tmp_path / "datasources.custom.yaml"
    assert custom.is_file()
    doc = yaml.safe_load(custom.read_text(encoding="utf-8"))
    assert doc["datasources"][0]["id"] == "footfall"
    # curated file unchanged
    assert "footfall" not in (tmp_path / "datasources.yaml").read_text(encoding="utf-8")


def test_reload_merges_custom_overlay(tmp_path):
    reg = _reg(tmp_path)
    reg.add_source(NEW_SPEC)
    # a fresh registry over the same dir merges primary + custom
    reg2 = DataSourceRegistry("bldg1", input_root=tmp_path)
    n = reg2.load()
    assert n == 2
    assert {s.id for s in reg2.list()} == {"occupancy", "footfall"}


def test_add_source_rejects_duplicate(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        reg.add_source({**NEW_SPEC, "id": "occupancy"})


def test_add_source_rejects_invalid(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(ValueError):
        reg.add_source({"label": "no id"})  # missing required id/modality/provenance_system


def test_curated_wins_on_id_clash(tmp_path):
    # hand-write a custom overlay that clashes with the curated id
    (tmp_path / "datasources.yaml").write_text(PRIMARY, encoding="utf-8")
    (tmp_path / "datasources.custom.yaml").write_text(
        yaml.safe_dump(
            {
                "datasources": [
                    {
                        "id": "occupancy",
                        "label": "HIJACK",
                        "modality": "occupancy",
                        "provenance_system": "x",
                        "ts_table": "occupancy_data",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    assert reg.get("occupancy").label == "Occupancy Sensing"  # curated wins


def test_manager_create_ok_and_duplicate(tmp_path):
    reg = _reg(tmp_path)
    mgr = DataSourceManager("bldg1", reg, state_path=tmp_path / "s.json")
    res = mgr.create(NEW_SPEC)
    assert res["ok"] and res["source_id"] == "footfall" and res["points"] == 1
    dup = mgr.create(NEW_SPEC)
    assert dup["ok"] is False and "already exists" in dup["error"]
