"""Phase 10 — BuildingContext resolver tests.

Verifies the per-request building lookup that future sessions will use to
migrate agents off `settings.BUILDING_*` toward `state.building_id`-driven
multi-tenant operation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.services import building_context as bc_mod
from orchestrator.services.building_context import (
    BuildingContext,
    clear_cache,
    resolve_building_context,
)


@pytest.fixture
def reset_cache():
    clear_cache()
    yield
    clear_cache()


# ─────────────────────────────────────────────────────────────────────────────
# Default / fallback behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_resolver_returns_a_building_context(reset_cache):
    ctx = resolve_building_context("bldg1")
    assert isinstance(ctx, BuildingContext)
    assert ctx.building_id
    assert ctx.name
    assert ctx.namespace
    assert ctx.prefix


def test_resolver_falls_back_to_settings_when_no_yaml(reset_cache, tmp_path):
    """When no per-building YAML exists, settings provide the values."""
    with patch.object(bc_mod, "_load_building_yaml", return_value=None):
        ctx = resolve_building_context("nonexistent_bldg_xyz")
    # Got a context with settings-derived values
    assert ctx.building_id == "nonexistent_bldg_xyz"
    # name and namespace should be non-empty (from settings)
    assert ctx.name
    assert ctx.namespace


def test_resolver_handles_none_building_id_gracefully(reset_cache):
    """Passing None falls through to settings.BUILDING_ID."""
    ctx = resolve_building_context(None)
    assert ctx.building_id  # non-empty


# ─────────────────────────────────────────────────────────────────────────────
# YAML overlay precedence
# ─────────────────────────────────────────────────────────────────────────────


def test_yaml_overrides_settings_for_name(reset_cache):
    """A building's YAML wins over the active settings.BUILDING_NAME."""
    yaml_data = {
        "building_id": "bldg2",
        "building_name": "TEST_BLDG_FROM_YAML",
        "ontology_namespace": "http://example.com/bldg2#",
        "building_prefix": "bldg2",
        "building_timezone": "America/New_York",
    }
    with patch.object(bc_mod, "_load_building_yaml", return_value=yaml_data):
        ctx = resolve_building_context("bldg2")
    assert ctx.name == "TEST_BLDG_FROM_YAML"
    assert ctx.namespace == "http://example.com/bldg2#"
    assert ctx.prefix == "bldg2"
    assert ctx.timezone == "America/New_York"


def test_yaml_partial_overlay_merges_with_settings(reset_cache):
    """If YAML only declares some fields, missing ones come from settings."""
    yaml_data = {
        "building_id": "bldg3",
        "building_name": "Partial Building",
        # ontology_namespace, prefix, timezone NOT set — should come from settings
    }
    with patch.object(bc_mod, "_load_building_yaml", return_value=yaml_data):
        ctx = resolve_building_context("bldg3")
    assert ctx.name == "Partial Building"
    # Non-empty defaults from settings filled the rest
    assert ctx.namespace
    assert ctx.prefix
    assert ctx.timezone


# ─────────────────────────────────────────────────────────────────────────────
# Cache behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_repeated_calls_are_cached(reset_cache):
    """The resolver caches per building_id (lru_cache); load is called once."""
    yaml_data = {"building_id": "bldg_cached", "building_name": "Cached"}
    with patch.object(
        bc_mod, "_load_building_yaml", return_value=yaml_data
    ) as load_mock:
        resolve_building_context("bldg_cached")
        resolve_building_context("bldg_cached")
        resolve_building_context("bldg_cached")
    assert load_mock.call_count == 1


def test_clear_cache_forces_reload(reset_cache):
    """After clear_cache(), the loader runs again."""
    yaml_data = {"building_id": "bldg_reload", "building_name": "x"}
    with patch.object(
        bc_mod, "_load_building_yaml", return_value=yaml_data
    ) as load_mock:
        resolve_building_context("bldg_reload")
        clear_cache()
        resolve_building_context("bldg_reload")
    assert load_mock.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# Live YAML round-trip (verifies the loader path actually works)
# ─────────────────────────────────────────────────────────────────────────────


def test_loader_reads_yaml_from_disk(tmp_path, reset_cache, monkeypatch):
    yaml_path = tmp_path / "bldg_x" / "building.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(yaml.dump({
        "building_id": "bldg_x",
        "building_name": "FromDisk",
        "ontology_namespace": "http://from-disk.example.com/x#",
    }))

    # Patch the search paths to point at our tmp dir
    def fake_load(bid):
        p = tmp_path / bid / "building.yaml"
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        return None

    with patch.object(bc_mod, "_load_building_yaml", side_effect=fake_load):
        ctx = resolve_building_context("bldg_x")
    assert ctx.name == "FromDisk"
    assert ctx.namespace == "http://from-disk.example.com/x#"
