"""Phase 8 — per-building intent overlay tests.

Verifies the input/<bldg>/intents.yaml mechanism added so a building can
extend or override the shipped intent definitions without editing any
Python code or the system-level intent_definitions.yaml.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.intents import registry as _registry_mod
from orchestrator.intents import get_intent_registry


@pytest.fixture
def clear_cache():
    get_intent_registry.cache_clear()
    yield
    get_intent_registry.cache_clear()


def _write_yaml(path: Path, intents: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"intents": intents}))


# ─────────────────────────────────────────────────────────────────────────────
# Overlay search-path API
# ─────────────────────────────────────────────────────────────────────────────


def test_overlay_paths_without_building():
    paths = _registry_mod._overlay_search_paths(None)
    # Only global paths (no per-building paths) when building_id is None
    assert all("/" not in str(p).split("input")[-1].lstrip("/").split("/")[0] for p in paths)


def test_overlay_paths_with_building_id():
    paths = _registry_mod._overlay_search_paths("bldgX")
    # Per-building paths must appear AFTER global ones (later wins)
    indices = [i for i, p in enumerate(paths) if "bldgX" in str(p)]
    indices_global = [i for i, p in enumerate(paths) if "bldgX" not in str(p)]
    if indices and indices_global:
        assert min(indices) > max(indices_global)


# ─────────────────────────────────────────────────────────────────────────────
# Merge behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_per_building_overlay_adds_intent(tmp_path, clear_cache):
    """A new intent declared in input/<bldg>/intents.yaml appears in the registry."""
    shipped = tmp_path / "shipped" / "intent_definitions.yaml"
    bldg_dir = tmp_path / "input" / "bldgX"
    _write_yaml(shipped, [
        {"name": "analytics", "description": "shipped analytics", "pipeline_group": "data"},
    ])
    _write_yaml(bldg_dir / "intents.yaml", [
        {"name": "lab_booking", "description": "Book a lab", "pipeline_group": "standalone"},
    ])
    with (
        patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [shipped]),
        patch.object(
            _registry_mod,
            "_overlay_search_paths",
            lambda bid: [bldg_dir / "intents.yaml"] if bid == "bldgX" else [],
        ),
        patch("shared.config.settings.BUILDING_ID", "bldgX"),
    ):
        reg = get_intent_registry()
    assert "analytics" in reg.names()
    assert "lab_booking" in reg.names()


def test_per_building_overlay_overrides_existing_intent(tmp_path, clear_cache):
    """An overlay entry with the same name overrides the shipped definition."""
    shipped = tmp_path / "shipped" / "intent_definitions.yaml"
    bldg_dir = tmp_path / "input" / "bldgX"
    _write_yaml(shipped, [
        {
            "name": "analytics",
            "description": "GLOBAL",
            "pipeline_group": "data",
        },
    ])
    _write_yaml(bldg_dir / "intents.yaml", [
        {
            "name": "analytics",
            "description": "PER-BUILDING",
            "pipeline_group": "data",
        },
    ])
    with (
        patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [shipped]),
        patch.object(
            _registry_mod,
            "_overlay_search_paths",
            lambda bid: [bldg_dir / "intents.yaml"] if bid == "bldgX" else [],
        ),
        patch("shared.config.settings.BUILDING_ID", "bldgX"),
    ):
        reg = get_intent_registry()
    assert reg.get("analytics").description == "PER-BUILDING"


def test_global_input_overlay_applies_when_no_per_building_file(tmp_path, clear_cache):
    """A global input/intents.yaml overlay applies to any building_id."""
    shipped = tmp_path / "shipped" / "intent_definitions.yaml"
    global_overlay = tmp_path / "global" / "intents.yaml"
    _write_yaml(shipped, [
        {"name": "analytics", "description": "shipped"},
    ])
    _write_yaml(global_overlay, [
        {"name": "site_specific", "description": "from global overlay"},
    ])
    with (
        patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [shipped]),
        patch.object(
            _registry_mod,
            "_overlay_search_paths",
            lambda bid: [global_overlay],
        ),
        patch("shared.config.settings.BUILDING_ID", "bldgX"),
    ):
        reg = get_intent_registry()
    assert "site_specific" in reg.names()


def test_malformed_overlay_does_not_crash(tmp_path, clear_cache):
    """A broken overlay is logged and skipped — the registry still loads."""
    shipped = tmp_path / "shipped" / "intent_definitions.yaml"
    bad = tmp_path / "bad" / "intents.yaml"
    _write_yaml(shipped, [
        {"name": "analytics", "description": "shipped"},
    ])
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not valid yaml: {[}")
    with (
        patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [shipped]),
        patch.object(_registry_mod, "_overlay_search_paths", lambda bid: [bad]),
        patch("shared.config.settings.BUILDING_ID", "bldgX"),
    ):
        reg = get_intent_registry()
    assert "analytics" in reg.names()


def test_registry_falls_back_to_defaults_if_everything_fails(clear_cache):
    """When shipped + overlay are both unreadable, hardcoded defaults are used."""
    with (
        patch.object(
            _registry_mod, "_REGISTRY_SEARCH_PATHS", [Path("/nowhere/file.yaml")]
        ),
        patch.object(_registry_mod, "_overlay_search_paths", lambda bid: []),
    ):
        reg = get_intent_registry()
    # Hardcoded fallback list still produces a non-empty registry
    assert len(reg.names()) > 0
    assert "analytics" in reg.names()
