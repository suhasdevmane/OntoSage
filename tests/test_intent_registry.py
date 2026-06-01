"""Phase 6 — intent registry tests.

Verifies:
  1. The IntentDefinition Pydantic model has sensible defaults.
  2. The registry loads YAML from disk.
  3. Falls back to hardcoded defaults when YAML is missing.
  4. Alias resolution works.
  5. Pipeline group partitioning returns the right sets.
  6. The markdown rendering produces the expected shape.
  7. Consumers (multi_intent_detector, planner_agent) read from the registry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.intents import IntentDefinition, IntentRegistry, get_intent_registry
from orchestrator.intents import registry as _registry_mod


# ─────────────────────────────────────────────────────────────────────────────
# IntentDefinition model
# ─────────────────────────────────────────────────────────────────────────────


def test_intent_definition_defaults():
    d = IntentDefinition(name="foo", description="bar")
    assert d.examples == []
    assert d.pipeline_group == "standalone"
    assert d.aliases == []
    assert d.cacheable is True


def test_intent_definition_requires_name_and_description():
    with pytest.raises(Exception):
        IntentDefinition(description="missing name")  # type: ignore[call-arg]


# ─────────────────────────────────────────────────────────────────────────────
# Registry basics
# ─────────────────────────────────────────────────────────────────────────────


def test_registry_lookup_by_name():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="analytics", description="...", pipeline_group="data"),
        IntentDefinition(name="floor_plan", description="...", pipeline_group="standalone"),
    ])
    assert reg.get("analytics").name == "analytics"
    assert reg.get("missing") is None


def test_registry_alias_resolution():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="compare", description="...", aliases=["comparison"]),
    ])
    assert reg.resolve_name("comparison") == "compare"
    assert reg.get("comparison").name == "compare"


def test_registry_alias_lookup_is_case_insensitive():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="compare", description="...", aliases=["Comparison"]),
    ])
    assert reg.resolve_name("COMPARISON") == "compare"


def test_registry_names_excludes_aliases():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="compare", description="...", aliases=["comparison"]),
        IntentDefinition(name="trend", description="..."),
    ])
    assert reg.names() == frozenset({"compare", "trend"})


def test_registry_partitions_pipeline_groups():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="analytics", description="...", pipeline_group="data"),
        IntentDefinition(name="capability", description="...", pipeline_group="standalone"),
        IntentDefinition(name="greeting", description="...", pipeline_group="meta"),
    ])
    assert reg.in_group("data") == frozenset({"analytics"})
    assert reg.in_group("standalone") == frozenset({"capability"})
    assert reg.in_group("meta") == frozenset({"greeting"})


# ─────────────────────────────────────────────────────────────────────────────
# YAML loading + fallback
# ─────────────────────────────────────────────────────────────────────────────


def test_loader_falls_back_to_defaults_when_yaml_missing():
    get_intent_registry.cache_clear()
    with patch.object(
        _registry_mod, "_REGISTRY_SEARCH_PATHS", [Path("/nonexistent.yaml")]
    ):
        reg = get_intent_registry()
    assert len(reg.names()) > 0
    # Legacy core intents must be present
    assert "analytics" in reg.names()
    assert "floor_plan" in reg.names()
    get_intent_registry.cache_clear()


def test_loader_reads_yaml(tmp_path):
    get_intent_registry.cache_clear()
    yaml_path = tmp_path / "intent_definitions.yaml"
    yaml_path.write_text(yaml.dump({
        "intents": [
            {
                "name": "yaml_only",
                "description": "Loaded from YAML",
                "pipeline_group": "standalone",
            },
        ]
    }))
    with patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [yaml_path]):
        reg = get_intent_registry()
    assert "yaml_only" in reg.names()
    assert reg.get("yaml_only").description == "Loaded from YAML"
    get_intent_registry.cache_clear()


def test_loader_falls_back_when_yaml_malformed(tmp_path):
    get_intent_registry.cache_clear()
    yaml_path = tmp_path / "broken.yaml"
    yaml_path.write_text("not valid YAML: {[}")
    with patch.object(_registry_mod, "_REGISTRY_SEARCH_PATHS", [yaml_path]):
        reg = get_intent_registry()
    # malformed file leads to fallback — defaults populated
    assert "analytics" in reg.names()
    get_intent_registry.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# Markdown rendering for LLM prompt
# ─────────────────────────────────────────────────────────────────────────────


def test_descriptions_markdown_format():
    reg = IntentRegistry(intents=[
        IntentDefinition(
            name="foo",
            description="The foo intent.",
            examples=['"bar baz"'],
        ),
    ])
    md = reg.descriptions_markdown()
    assert '   - "foo"' in md
    assert "The foo intent." in md
    assert 'e.g. "bar baz"' in md


def test_descriptions_markdown_handles_no_examples():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="silent", description="No examples here."),
    ])
    md = reg.descriptions_markdown()
    assert '   - "silent"' in md
    assert "No examples here." in md
    assert "e.g." not in md


# ─────────────────────────────────────────────────────────────────────────────
# Consumer integration: multi_intent_detector + planner_agent read the registry
# ─────────────────────────────────────────────────────────────────────────────


def test_multi_intent_detector_uses_registry():
    from orchestrator.services.multi_intent_detector import VALID_INTENTS
    # Anything in the registry's `names()` should also be in VALID_INTENTS
    # (the detector loads it from the registry).
    from orchestrator.intents import get_intent_registry
    get_intent_registry.cache_clear()
    reg_names = get_intent_registry().names()
    # Re-import to pick up the registry-driven value.  We assert at least the
    # core intents flow through.
    assert "analytics" in VALID_INTENTS
    assert "floor_plan" in VALID_INTENTS
    # And the registry should contain them
    assert "analytics" in reg_names


def test_planner_agent_pipeline_groups_from_registry():
    from orchestrator.agents.planner_agent import (
        _DATA_PIPELINE_AGENTS,
        _STANDALONE_AGENTS,
    )
    # sparql / sql are always in the data group (they're pipeline stages,
    # not user-facing intents — added unconditionally by the loader).
    assert "sparql" in _DATA_PIPELINE_AGENTS
    assert "sql" in _DATA_PIPELINE_AGENTS
    # Data intents from the registry must flow through
    assert "analytics" in _DATA_PIPELINE_AGENTS
    assert "anomaly" in _DATA_PIPELINE_AGENTS
    # Standalone intents likewise
    assert "floor_plan" in _STANDALONE_AGENTS
    assert "capability" in _STANDALONE_AGENTS
    # No overlap
    assert _DATA_PIPELINE_AGENTS.isdisjoint(_STANDALONE_AGENTS)
