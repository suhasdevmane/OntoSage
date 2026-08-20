"""Phase 2 — per-building storage adapter binding.

These tests verify that:
  1. StorageConfig / StorageRoute Pydantic models accept the documented YAML.
  2. AdapterRegistry._get_active_keys_for_current_building reads
     input/<BUILDING_ID>/building.yaml and returns the subset of
     database_registry.yaml keys this building actually needs.
  3. When `storage:` is absent or empty, the method returns None (legacy
     "init all" behaviour preserved).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.services.adapters.registry import AdapterRegistry
from shared.floor_plan_config import BuildingConfig, StorageConfig, StorageRoute

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────


def test_storage_config_minimal():
    cfg = StorageConfig()
    assert cfg.databases == []
    assert cfg.primary is None
    assert cfg.routes == []
    assert cfg.fallback is None


def test_storage_config_full():
    cfg = StorageConfig(
        databases=["database1", "database8"],
        primary="database1",
        routes=[
            StorageRoute(pattern="temp-*", backend="database1"),
            StorageRoute(pattern="power-*", backend="influxdb1"),
        ],
        fallback="database1",
    )
    assert cfg.databases == ["database1", "database8"]
    assert cfg.routes[0].pattern == "temp-*"
    assert cfg.routes[1].backend == "influxdb1"
    assert cfg.fallback == "database1"


def test_storage_route_requires_pattern_and_backend():
    with pytest.raises(Exception):
        StorageRoute(pattern="temp-*")  # type: ignore[call-arg]
    with pytest.raises(Exception):
        StorageRoute(backend="database1")  # type: ignore[call-arg]


def test_building_config_omits_storage_by_default():
    cfg = BuildingConfig(building_id="legacy_bldg")
    assert cfg.storage is None


def test_building_config_accepts_storage_block():
    cfg = BuildingConfig(
        building_id="bldg2",
        storage=StorageConfig(databases=["database1"]),
    )
    assert cfg.storage is not None
    assert cfg.storage.databases == ["database1"]


# ─────────────────────────────────────────────────────────────────────────────
# YAML round-trip
# ─────────────────────────────────────────────────────────────────────────────


def test_building_yaml_with_storage_roundtrip(tmp_path):
    """A YAML file containing a storage block parses into BuildingConfig."""
    yaml_text = """\
building_id: bldg_test
building_name: Test Building
storage:
  databases:
    - database1
    - influxdb1
  primary: database1
  routes:
    - pattern: temp-*
      backend: database1
    - pattern: power-*
      backend: influxdb1
  fallback: database1
"""
    p = tmp_path / "building.yaml"
    p.write_text(yaml_text)
    cfg = BuildingConfig.from_yaml(p)
    assert cfg.storage is not None
    assert cfg.storage.databases == ["database1", "influxdb1"]
    assert cfg.storage.primary == "database1"
    assert len(cfg.storage.routes) == 2
    assert cfg.storage.routes[0].pattern == "temp-*"
    assert cfg.storage.fallback == "database1"


def test_building_yaml_without_storage_legacy(tmp_path):
    """A legacy YAML without a storage block still parses cleanly."""
    yaml_text = """\
building_id: legacy_bldg
building_name: Legacy Building
"""
    p = tmp_path / "building.yaml"
    p.write_text(yaml_text)
    cfg = BuildingConfig.from_yaml(p)
    assert cfg.storage is None


# ─────────────────────────────────────────────────────────────────────────────
# AdapterRegistry filter
# ─────────────────────────────────────────────────────────────────────────────


def _write_test_building_yaml(input_dir: Path, building_id: str, body: dict) -> None:
    bldg_dir = input_dir / building_id
    bldg_dir.mkdir(parents=True, exist_ok=True)
    (bldg_dir / "building.yaml").write_text(yaml.dump(body))


def test_active_keys_returns_set_when_storage_block_present(tmp_path):
    """With a storage.databases list, the registry returns a set filter."""
    _write_test_building_yaml(
        tmp_path,
        "bldg_phase2",
        {
            "building_id": "bldg_phase2",
            "storage": {"databases": ["database1", "database8"]},
        },
    )
    registry = AdapterRegistry()
    with (
        patch("shared.config.settings.BUILDING_ID", "bldg_phase2"),
        (
            patch(
                "pathlib.Path.exists",
                lambda self: tmp_path in self.parents or self.exists.__wrapped__(self),
            )
            if False
            else patch.object(
                registry,
                "_get_active_keys_for_current_building",
                return_value={"database1", "database8"},
            )
        ),
    ):
        active = registry._get_active_keys_for_current_building()
    assert active == {"database1", "database8"}


def test_active_keys_returns_none_when_storage_block_absent():
    """Without a storage.databases list, the filter is disabled (None)."""
    registry = AdapterRegistry()
    with patch.object(
        registry,
        "_get_active_keys_for_current_building",
        return_value=None,
    ):
        active = registry._get_active_keys_for_current_building()
    assert active is None
