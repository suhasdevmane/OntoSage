"""Regression test for BuildingRegistry flat-layout discovery (Finding B).

The active deployment uses the FLAT layout (input/building.yaml) after the
nested input/<id>/building.yaml was removed. The pre-scan previously only read
input/<subdir>/building.yaml, so bldg1's floor_plan_aliases (=> abacws) were
never registered and floor_plan / spatial_query could not resolve the abacws
manifests. It also choked on the _templates/ scaffolding placeholder.
"""

import pytest

from orchestrator.services.building_registry import BuildingRegistry

pytestmark = pytest.mark.unit

_FLAT_YAML = """\
building_id: bldg1
building_name: Test Building
floor_plan_aliases:
  - abacws
"""

# A placeholder template that is NOT valid YAML — mirrors input/_templates/.
_TEMPLATE_YAML = "building_id: {{BUILDING_ID}}\n:::not valid:::\n"


def _make_input(tmp_path):
    (tmp_path / "building.yaml").write_text(_FLAT_YAML, encoding="utf-8")
    templates = tmp_path / "_templates"
    templates.mkdir()
    (templates / "building.yaml").write_text(_TEMPLATE_YAML, encoding="utf-8")
    return tmp_path


def test_flat_layout_registers_building_and_alias(tmp_path):
    reg = BuildingRegistry(pdf_dir=_make_input(tmp_path))
    reg.scan()

    # bldg1 registered from the flat input/building.yaml.
    assert reg.get("bldg1") is not None
    # The abacws alias resolves to bldg1 (so floor-plan data keyed under
    # "abacws" is reachable from the logical BUILDING_ID).
    assert reg.resolve_id("abacws") == "bldg1"
    # Alias-aware get() also returns the config.
    assert reg.get("abacws") is not None


def test_templates_scaffolding_is_skipped(tmp_path):
    reg = BuildingRegistry(pdf_dir=_make_input(tmp_path))
    reg.scan()  # must not raise despite the malformed _templates/building.yaml

    # The placeholder must not have been registered as a real building.
    assert reg.resolve_id("{{BUILDING_ID}}") is None
    assert reg.get("bldg1") is not None
