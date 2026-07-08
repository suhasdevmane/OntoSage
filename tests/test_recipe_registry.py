"""T04 — RecipeRegistry unit tests.

Covers:
  1. Base config/recipes.yaml loads correctly
  2. Recipe count >= 15 (seeded from T01 recipe_kinds)
  3. get() returns correct recipe with expected keys
  4. Per-building override file takes precedence over base
  5. Missing recipe returns None
  6. Missing override is silently skipped
  7. reload() picks up changes
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_registry(tmp_path: Path, base_yaml: str, override_yaml: str = "") -> "RecipeRegistry":
    """Instantiate a fresh RecipeRegistry pointing at tmp_path fixtures."""
    from orchestrator.services.recipe_registry import RecipeRegistry

    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "recipes.yaml").write_text(base_yaml)

    bldg_dir = tmp_path / "input" / "testbldg"
    if override_yaml:
        bldg_dir.mkdir(parents=True, exist_ok=True)
        (bldg_dir / "recipes.yaml").write_text(override_yaml)

    import orchestrator.services.recipe_registry as mod
    import unittest.mock as mock

    reg = RecipeRegistry()
    # Patch the search paths to point at tmp_path
    with mock.patch.object(
        mod,
        "_BASE_CONFIG_PATHS",
        [tmp_path / "config" / "recipes.yaml"],
    ), mock.patch.object(
        mod,
        "_PER_BUILDING_PATHS",
        [str(tmp_path / "input" / "{building_id}" / "recipes.yaml")],
    ):
        reg.load(building_id="testbldg" if override_yaml else None)
    return reg


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_recipe_registry_loads_base(tmp_path):
    """Base recipes.yaml loads and returns expected count."""
    base = """
recipes:
  co2_threshold:
    kind: threshold
    params:
      co2_ppm_alert: 1000
  temperature_average:
    kind: aggregate
    params:
      window_minutes: 30
"""
    reg = _make_registry(tmp_path, base)
    assert reg.get("co2_threshold") is not None
    assert len(reg.all_ids()) == 2


def test_recipe_get_returns_expected_keys(tmp_path):
    base = """
recipes:
  co2_threshold:
    kind: threshold
    description: CO2 check
    params:
      co2_ppm_alert: 1000
      unit: ppm
    answer_template: CO2 is {value} ppm.
"""
    reg = _make_registry(tmp_path, base)
    r = reg.get("co2_threshold")
    assert r is not None
    assert r["kind"] == "threshold"
    assert r["params"]["co2_ppm_alert"] == 1000
    assert "answer_template" in r


def test_recipe_missing_returns_none(tmp_path):
    base = "recipes:\n  r1:\n    kind: threshold\n"
    reg = _make_registry(tmp_path, base)
    assert reg.get("no_such_recipe") is None


def test_per_building_override_takes_precedence(tmp_path):
    """Building-specific override replaces the base recipe value."""
    base = """
recipes:
  co2_threshold:
    kind: threshold
    params:
      co2_ppm_alert: 1000
"""
    override = """
recipes:
  co2_threshold:
    kind: threshold
    params:
      co2_ppm_alert: 800
"""
    reg = _make_registry(tmp_path, base, override)
    r = reg.get("co2_threshold")
    assert r is not None
    assert r["params"]["co2_ppm_alert"] == 800


def test_per_building_override_adds_new_recipe(tmp_path):
    """Building override can add a recipe that doesn't exist in base."""
    base = "recipes:\n  r1:\n    kind: threshold\n"
    override = "recipes:\n  custom_recipe:\n    kind: aggregate\n    params:\n      window: 60\n"
    reg = _make_registry(tmp_path, base, override)
    assert reg.get("custom_recipe") is not None
    assert reg.get("r1") is not None


def test_missing_override_file_silently_skipped(tmp_path):
    """No override file → base loads fine, no error."""
    base = "recipes:\n  r1:\n    kind: threshold\n"
    reg = _make_registry(tmp_path, base)  # no override
    assert reg.get("r1") is not None


def test_base_recipes_yaml_has_at_least_15(tmp_path):
    """Real config/recipes.yaml must have >= 15 recipes (T04 acceptance criterion)."""
    import orchestrator.services.recipe_registry as mod

    reg = mod.RecipeRegistry()
    count = reg.load()
    assert count >= 15, f"Expected >= 15 recipes in config/recipes.yaml, got {count}"


def test_all_ids_returns_sorted_list(tmp_path):
    base = "recipes:\n  zzz:\n    kind: trend\n  aaa:\n    kind: threshold\n"
    reg = _make_registry(tmp_path, base)
    ids = reg.all_ids()
    assert ids == sorted(ids)


def test_all_recipes_returns_copy(tmp_path):
    base = "recipes:\n  r1:\n    kind: threshold\n"
    reg = _make_registry(tmp_path, base)
    d = reg.all_recipes()
    d["r1"]["kind"] = "MUTATED"
    # Original should be unchanged
    assert reg.get("r1")["kind"] == "threshold"


def test_reload_picks_up_changes(tmp_path):
    """reload() re-reads the YAML so new recipes appear."""
    import orchestrator.services.recipe_registry as mod
    import unittest.mock as mock

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "recipes.yaml"
    cfg_file.write_text("recipes:\n  r1:\n    kind: threshold\n")

    reg = mod.RecipeRegistry()
    with mock.patch.object(mod, "_BASE_CONFIG_PATHS", [cfg_file]):
        reg.load()
        assert reg.get("r1") is not None
        assert reg.get("r2") is None

        # Add a new recipe and reload
        cfg_file.write_text("recipes:\n  r1:\n    kind: threshold\n  r2:\n    kind: aggregate\n")
        with mock.patch.object(mod, "_BASE_CONFIG_PATHS", [cfg_file]):
            reg.reload()
        assert reg.get("r2") is not None
