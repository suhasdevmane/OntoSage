"""Phase 12A — multi-tenant fixture tests.

OntoSage v1 is single-building at a time (one orchestrator serves one
`BUILDING_ID`). The per-building infrastructure in code (registry cache keyed
by `building_id`, BuildingContextResolver, etc.) is forward-compat for the
future Onto-community multi-building version.

These tests exercise that infrastructure against a fixture building
(`tests/fixtures/buildings/bldg2/`) so the swap-and-restart workflow stays
verified WITHOUT polluting the live `input/` directory with multiple
buildings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "buildings" / "bldg2"


@pytest.fixture
def fixture_input_dir(tmp_path, monkeypatch):
    """Stage the bldg2 fixture under a temp `input/` so loaders find it.

    Mirrors the production layout: `input/<building_id>/building.yaml`,
    `input/<building_id>/intents.yaml`, etc.  The loaders search both
    `/app/input/...` (container) and `input/...` (dev) — we redirect the
    latter to a temp dir by `chdir`-ing.
    """
    bldg = tmp_path / "input" / "bldg2"
    bldg.mkdir(parents=True)
    for src in FIXTURE_ROOT.rglob("*"):
        if src.is_file():
            dst = bldg / src.relative_to(FIXTURE_ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_fixture_dir_intact():
    """The fixture must contain the four artifacts the loaders look for."""
    assert (FIXTURE_ROOT / "building.yaml").exists()
    assert (FIXTURE_ROOT / "intents.yaml").exists()
    assert (FIXTURE_ROOT / "capability.yaml").exists()
    assert (FIXTURE_ROOT / "personas").is_dir()


def test_building_context_resolves_bldg2_from_yaml(fixture_input_dir):
    """resolve_building_context('bldg2') should return Cardiff Research Tower,
    not the global settings default."""
    from orchestrator.services.building_context import (
        resolve_building_context,
    )
    resolve_building_context.cache_clear()

    bctx = resolve_building_context("bldg2")
    assert bctx.building_id == "bldg2"
    assert bctx.name == "Cardiff Research Tower"
    assert bctx.namespace == "http://cardiff-research-tower.example/bldg2#"
    assert bctx.prefix == "bldg2"


def test_intent_registry_loads_bldg2_overlay(fixture_input_dir):
    """The per-building intent registry must surface `lab_equipment`
    when keyed by building_id='bldg2'."""
    from orchestrator.intents import get_intent_registry
    get_intent_registry.cache_clear()

    reg = get_intent_registry("bldg2")
    names = reg.names()
    assert "lab_equipment" in names, (
        f"Expected 'lab_equipment' from bldg2 overlay, got: {sorted(names)}"
    )

    lab = reg.get("lab_equipment")
    assert lab is not None
    assert lab.pipeline_group == "standalone"


def test_intent_registry_caches_per_building(fixture_input_dir):
    """Calls for different building_ids must return distinct registries
    (lru_cache(maxsize=None) keyed by building_id)."""
    from orchestrator.intents import get_intent_registry
    get_intent_registry.cache_clear()

    reg_bldg2 = get_intent_registry("bldg2")
    reg_default = get_intent_registry(None)

    # bldg2 has lab_equipment override; default doesn't.
    assert "lab_equipment" in reg_bldg2.names()
    assert "lab_equipment" not in reg_default.names()


def test_persona_loader_finds_bldg2_facility_manager(fixture_input_dir):
    """The persona loader's per-building dir search must pick up
    bldg2's facility_manager override."""
    from shared.persona_loader import load_persona_overlays

    data, _aliases = load_persona_overlays(building_id="bldg2")
    fm = data.get("facility_manager")
    assert fm is not None, (
        "bldg2 facility_manager persona should be loaded from "
        f"tests/fixtures/buildings/bldg2/personas/. Got keys: {sorted(data.keys())}"
    )
    # Sanity check that the OVERRIDE values came from bldg2's YAML,
    # not the shipped defaults.
    desc = fm.get("description", "")
    assert "research" in desc.lower() or "hpc" in desc.lower() or "tower" in desc.lower(), (
        f"Expected research-tower-specific description; got: {desc!r}"
    )
