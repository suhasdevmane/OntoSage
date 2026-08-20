"""Phase 4a — BuildingRegistry alias mechanism tests.

Verifies:
  1. BuildingConfig accepts a floor_plan_aliases list (defaults to []).
  2. BuildingRegistry.resolve_id translates aliases to primary IDs.
  3. get/get_or_default/floors_for/pdf_path are all alias-aware.
  4. Pre-scan picks up input/<bldg>/building.yaml even without matching PDFs.
  5. FloorPlanPipeline.load_manifest honours the alias via the registry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.services.building_registry import BuildingRegistry
from shared.floor_plan_config import BuildingConfig, default_config

# ─────────────────────────────────────────────────────────────────────────────
# BuildingConfig model
# ─────────────────────────────────────────────────────────────────────────────


def test_building_config_defaults_to_empty_alias_list():
    cfg = BuildingConfig(building_id="bldg2")
    assert cfg.floor_plan_aliases == []


def test_building_config_accepts_aliases():
    cfg = BuildingConfig(
        building_id="bldg1",
        floor_plan_aliases=["abacws", "cardiff_abacws"],
    )
    assert cfg.floor_plan_aliases == ["abacws", "cardiff_abacws"]


# ─────────────────────────────────────────────────────────────────────────────
# BuildingRegistry alias map
# ─────────────────────────────────────────────────────────────────────────────


def test_register_records_aliases():
    reg = BuildingRegistry()
    reg._register(
        BuildingConfig(
            building_id="bldg1",
            building_name="Test Bldg",
            floor_plan_aliases=["abacws", "cardiff_abacws"],
        )
    )
    assert reg.aliases() == {"abacws": "bldg1", "cardiff_abacws": "bldg1"}


def test_self_alias_is_ignored():
    """If a config lists itself as an alias, the registry skips it."""
    reg = BuildingRegistry()
    reg._register(
        BuildingConfig(
            building_id="bldg1",
            building_name="Test Bldg",
            floor_plan_aliases=["bldg1", "abacws"],
        )
    )
    assert reg.aliases() == {"abacws": "bldg1"}


def test_resolve_id_returns_primary_for_known_id():
    reg = BuildingRegistry()
    reg._register(BuildingConfig(building_id="bldg1", floor_plan_aliases=["abacws"]))
    assert reg.resolve_id("bldg1") == "bldg1"


def test_resolve_id_returns_primary_for_alias():
    reg = BuildingRegistry()
    reg._register(BuildingConfig(building_id="bldg1", floor_plan_aliases=["abacws"]))
    assert reg.resolve_id("abacws") == "bldg1"


def test_resolve_id_returns_none_for_unknown():
    reg = BuildingRegistry()
    reg._register(BuildingConfig(building_id="bldg1"))
    assert reg.resolve_id("bldg99") is None


def test_resolve_id_handles_none_and_empty():
    reg = BuildingRegistry()
    assert reg.resolve_id(None) is None
    assert reg.resolve_id("") is None


def test_get_is_alias_aware():
    reg = BuildingRegistry()
    cfg = BuildingConfig(building_id="bldg1", floor_plan_aliases=["abacws"])
    reg._register(cfg)
    assert reg.get("bldg1") is cfg
    assert reg.get("abacws") is cfg
    assert reg.get("missing") is None


def test_floors_for_is_alias_aware(tmp_path):
    reg = BuildingRegistry()
    reg._register(BuildingConfig(building_id="bldg1", floor_plan_aliases=["abacws"]))
    fake_pdf = tmp_path / "f0.pdf"
    fake_pdf.touch()
    reg._floor_map["bldg1"] = {0: fake_pdf}
    assert reg.floors_for("bldg1") == {0: fake_pdf}
    assert reg.floors_for("abacws") == {0: fake_pdf}


def test_pdf_path_is_alias_aware(tmp_path):
    reg = BuildingRegistry()
    reg._register(BuildingConfig(building_id="bldg1", floor_plan_aliases=["abacws"]))
    fake_pdf = tmp_path / "f0.pdf"
    fake_pdf.touch()
    reg._floor_map["bldg1"] = {0: fake_pdf}
    assert reg.pdf_path("bldg1", 0) == fake_pdf
    assert reg.pdf_path("abacws", 0) == fake_pdf


# ─────────────────────────────────────────────────────────────────────────────
# Pre-scan of input/<bldg>/building.yaml
# ─────────────────────────────────────────────────────────────────────────────


def _write_bldg_yaml(input_dir: Path, building_id: str, body: dict) -> None:
    d = input_dir / building_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "building.yaml").write_text(yaml.dump(body))


def test_scan_prescans_per_building_yaml_without_pdfs(tmp_path):
    """input/<bldg>/building.yaml is picked up even when no PDFs match the slug."""
    _write_bldg_yaml(
        tmp_path,
        "bldgA",
        {
            "building_id": "bldgA",
            "building_name": "Building A",
            "floor_plan_aliases": ["legacyA"],
        },
    )
    reg = BuildingRegistry(pdf_dir=tmp_path)
    reg.scan()
    assert "bldgA" in reg.building_ids()
    assert reg.resolve_id("legacyA") == "bldgA"


def test_scan_invents_no_building(tmp_path):
    """An empty input folder yields an empty registry (CAVEAT-094).

    A hardcoded "abacws" config used to be registered here unconditionally, so
    every deployment reported a building it did not have. The PDF scan already
    registers whatever slug it finds, for any building, which is the
    building-agnostic path that replaced it.
    """
    reg = BuildingRegistry(pdf_dir=tmp_path)
    reg.scan()
    assert reg.building_ids() == [], f"registry invented {reg.building_ids()}"


def test_the_fallback_config_describes_the_building_it_was_asked_about(tmp_path):
    """Never another building's identity — the whole point of CAVEAT-094."""
    cfg = default_config("bldg7")
    assert cfg.building_id == "bldg7"
    assert "abacws" not in cfg.building_name.lower()
    assert "abacws" not in (cfg.ontology_namespace or "").lower()
    assert cfg.effective_display_name


def test_realistic_bldg1_alias_to_abacws(tmp_path):
    """Phase 4 production scenario: bldg1 logical ID aliases to abacws floor data."""
    _write_bldg_yaml(
        tmp_path,
        "bldg1",
        {
            "building_id": "bldg1",
            "building_name": "Abacws",
            "floor_plan_aliases": ["abacws"],
        },
    )
    # Simulate a top-level Abacws PDF that the slug discovery would catch
    pdf = tmp_path / "Abacws floor 3.pdf"
    pdf.touch()
    reg = BuildingRegistry(pdf_dir=tmp_path)
    reg.scan()
    # Both keys resolve to bldg1
    assert reg.resolve_id("bldg1") == "bldg1"
    assert reg.resolve_id("abacws") == "bldg1"
    # PDF path is accessible from either ID
    assert reg.pdf_path("bldg1", 3) == pdf
    assert reg.pdf_path("abacws", 3) == pdf
