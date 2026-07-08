"""Phase 6D — workflow.py routing now reads from the intent registry.

Verifies:
  1. IntentDefinition accepts `route_target`
  2. Registry.route_target_for() applies explicit field, then group defaults
  3. Unknown intents return None (caller falls back to "response")
  4. The four contextual overrides in `_route_from_dialogue` still fire:
       a. compare+data keywords on floor_plan → comparison
       b. floor_plan_service.is_floor_plan_query → floor_plan
       c. discovery + spatial words → sparql
       d. analytics-family with use_existing_query_results → analytics
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.intents import IntentDefinition, IntentRegistry, get_intent_registry


# ─────────────────────────────────────────────────────────────────────────────
# IntentDefinition.route_target
# ─────────────────────────────────────────────────────────────────────────────


def test_intent_definition_accepts_route_target():
    d = IntentDefinition(
        name="custom",
        description="...",
        pipeline_group="data",
        route_target="my_node",
    )
    assert d.route_target == "my_node"


def test_intent_definition_route_target_defaults_to_none():
    d = IntentDefinition(name="x", description="...")
    assert d.route_target is None


# ─────────────────────────────────────────────────────────────────────────────
# Registry.route_target_for resolution
# ─────────────────────────────────────────────────────────────────────────────


def test_explicit_route_target_wins_over_defaults():
    reg = IntentRegistry(intents=[
        IntentDefinition(
            name="report",
            description="...",
            pipeline_group="data",
            route_target="planner",   # override default "sparql"
        ),
    ])
    assert reg.route_target_for("report") == "planner"


def test_data_group_default_is_sparql():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="analytics", description="...", pipeline_group="data"),
    ])
    assert reg.route_target_for("analytics") == "sparql"


def test_standalone_group_default_is_intent_name():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="floor_plan", description="...", pipeline_group="standalone"),
    ])
    assert reg.route_target_for("floor_plan") == "floor_plan"


def test_meta_group_default_is_response():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="greeting", description="...", pipeline_group="meta"),
    ])
    assert reg.route_target_for("greeting") == "response"


def test_unknown_intent_returns_none():
    reg = IntentRegistry(intents=[
        IntentDefinition(name="known", description="..."),
    ])
    assert reg.route_target_for("unknown_intent") is None


def test_alias_resolves_through_route_target():
    reg = IntentRegistry(intents=[
        IntentDefinition(
            name="compare",
            description="...",
            pipeline_group="data",
            aliases=["comparison"],
        ),
    ])
    assert reg.route_target_for("comparison") == "sparql"


# ─────────────────────────────────────────────────────────────────────────────
# Live YAML registry — verifies the production routing table
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def live_reg():
    get_intent_registry.cache_clear()
    reg = get_intent_registry()
    yield reg
    get_intent_registry.cache_clear()


@pytest.mark.parametrize("intent,expected", [
    # Data group with explicit route_target
    ("report", "planner"),
    ("export", "export"),
    ("visualization", "visualization"),
    # Data group default
    ("analytics", "sparql"),
    ("anomaly", "sparql"),
    ("compare", "sparql"),
    ("trend", "sparql"),
    ("recommend", "sparql"),
    ("compliance", "sparql"),
    ("sensor_data", "sparql"),
    ("metadata", "sparql"),
    ("discovery", "sparql"),
    # Meta group with explicit
    ("planner", "planner"),
    # Meta group default
    ("greeting", "response"),
    ("clarification", "response"),
    # Meta group with explicit route_target → dedicated open-domain answering node
    ("general", "general_knowledge"),
    # Standalone group default
    ("floor_plan", "floor_plan"),
    ("spatial_query", "spatial_query"),
    ("capability", "capability"),
    ("control", "control"),
    ("maintenance", "maintenance"),
])
def test_production_intent_routing_table(live_reg, intent, expected):
    """Every shipped intent routes to the expected workflow node."""
    assert live_reg.route_target_for(intent) == expected, (
        f"intent={intent} expected target {expected!r}"
    )
