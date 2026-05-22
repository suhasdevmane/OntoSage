"""
Unit tests for shared.capability_schema.CapabilityRoutingConfig.

Covers §16.1.4 of the capability semantic routing spec.
Eight tests:
  1. Defaults applied when block absent
  2. Invalid threshold (> 1.0) rejected
  3. threshold > override_min rejected (cross-field validator)
  4. Negative top_k rejected
  5. embedding_model 'auto' is a valid Literal
  6. Existing bldg1 capability.yaml still validates with new schema (no schema break)
  7. CapabilityKB.search() still exists during Phase 1 (gets removed in Phase 3)
  8. Building without capability_routing block loads successfully (defaults applied)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.capability_schema import (
    CapabilityEntry,
    CapabilityKB,
    CapabilityRoutingConfig,
)


def test_defaults_applied_when_block_absent():
    """Test 1: No fields specified → all defaults applied."""
    cfg = CapabilityRoutingConfig()
    assert cfg.enabled is True
    assert cfg.embedding_model == "auto"
    assert cfg.threshold == 0.65
    assert cfg.override_min == 0.85
    assert cfg.top_k == 5
    assert cfg.fallback_on_qdrant_failure == "skip"


def test_invalid_threshold_rejected():
    """Test 2: threshold > 1.0 raises ValidationError."""
    with pytest.raises(ValidationError):
        CapabilityRoutingConfig(threshold=1.5)
    with pytest.raises(ValidationError):
        CapabilityRoutingConfig(threshold=-0.1)


def test_threshold_above_override_min_rejected():
    """Test 3: threshold > override_min is semantically invalid (cross-field)."""
    with pytest.raises(ValidationError) as exc_info:
        CapabilityRoutingConfig(threshold=0.9, override_min=0.8)
    # message should explain *why*
    assert "override_min" in str(exc_info.value)
    assert "threshold" in str(exc_info.value)


def test_negative_top_k_rejected():
    """Test 4: top_k must be >= 1."""
    with pytest.raises(ValidationError):
        CapabilityRoutingConfig(top_k=-1)
    with pytest.raises(ValidationError):
        CapabilityRoutingConfig(top_k=0)


def test_embedding_model_auto_is_valid():
    """Test 5: 'auto' is accepted; arbitrary strings are not."""
    cfg_auto = CapabilityRoutingConfig(embedding_model="auto")
    assert cfg_auto.embedding_model == "auto"

    cfg_openai = CapabilityRoutingConfig(embedding_model="openai")
    assert cfg_openai.embedding_model == "openai"

    cfg_local = CapabilityRoutingConfig(embedding_model="local")
    assert cfg_local.embedding_model == "local"

    with pytest.raises(ValidationError):
        CapabilityRoutingConfig(embedding_model="bogus")


def test_existing_bldg1_yaml_still_validates():
    """Test 6: bldg1's actual capability.yaml loads with the updated schema.

    This is the non-regression guarantee: adding CapabilityRoutingConfig must
    NOT change the schema of CapabilityKB / CapabilityEntry / BuildingInfo.
    """
    yaml_path = Path(__file__).resolve().parent.parent / "input" / "bldg1" / "capability.yaml"
    if not yaml_path.exists():
        pytest.skip(f"bldg1 capability.yaml not present at {yaml_path}")

    kb = CapabilityKB.from_yaml(yaml_path)
    # bldg1 currently has 32 entries (post-2026-05-20 KB extension)
    assert len(kb.capabilities) >= 25
    assert kb.building_info.id == "bldg1"

    # Spot-check the recently added entry that motivated the refactor
    lift = next((c for c in kb.capabilities if c.id == "lift_accessibility_detail"), None)
    assert lift is not None, "lift_accessibility_detail should be in the bldg1 KB"
    assert "lift dimensions" in lift.keywords


def test_capability_kb_search_method_removed_after_phase3():
    """Test 7 (Phase 3 inversion): CapabilityKB.search() has been removed.

    Phase 3 cleanup deleted the legacy substring-search method.  Semantic
    routing is now the single source of truth for capability lookup.
    """
    assert not hasattr(CapabilityKB, "search"), (
        "CapabilityKB.search() should be removed after Phase 3 cleanup"
    )


def test_routing_config_at_boundary_values():
    """Test 8: threshold == override_min is allowed (boundary inclusive)."""
    cfg = CapabilityRoutingConfig(threshold=0.80, override_min=0.80)
    assert cfg.threshold == cfg.override_min == 0.80

    # threshold == 0.0 and override_min == 1.0 are valid boundaries
    cfg_extreme = CapabilityRoutingConfig(threshold=0.0, override_min=1.0)
    assert cfg_extreme.threshold == 0.0
    assert cfg_extreme.override_min == 1.0
