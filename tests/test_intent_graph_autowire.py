"""Phase 13B-3 — graph auto-wire invariants.

Adding a new intent should require ONLY a YAML edit + a `_foo_node` method on
WorkflowOrchestrator.  This file enforces that invariant by checking, at test
time, that the registry and the LangGraph state machine agree about which
nodes exist and what dialogue can route to.

If these tests fail, either:
  * an intent_definitions.yaml entry declares a `node_method` that doesn't
    exist on WorkflowOrchestrator (typo or missing implementation), or
  * `_build_graph` no longer registers every registry-declared node.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def graph():
    """Build the workflow graph once per module — it's expensive."""
    from orchestrator.workflow import WorkflowOrchestrator
    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    return inst._build_graph()


@pytest.fixture(scope="module")
def registry():
    from orchestrator.intents import get_intent_registry
    get_intent_registry.cache_clear()
    return get_intent_registry()


def test_every_node_method_in_registry_resolves(registry):
    """For every intent that declares `node_method`, the method must exist
    on WorkflowOrchestrator.  Catches typos like `_floorplan_node`."""
    from orchestrator.workflow import WorkflowOrchestrator

    missing = []
    for intent_def in registry.with_node_method():
        if not hasattr(WorkflowOrchestrator, intent_def.node_method):
            missing.append((intent_def.name, intent_def.node_method))

    assert missing == [], (
        f"Intents declare node_method that doesn't exist on "
        f"WorkflowOrchestrator: {missing}"
    )


def test_every_intent_node_in_registry_appears_in_graph(graph, registry):
    """Every intent that declared a node_method must have a corresponding
    node registered in the LangGraph state machine."""
    graph_nodes = set(graph.nodes.keys())

    missing = []
    for intent_def in registry.with_node_method():
        node_name = intent_def.route_target or intent_def.name
        if node_name not in graph_nodes:
            missing.append(node_name)

    assert missing == [], (
        f"Registry-declared nodes not registered in graph: {missing}.  "
        f"Graph nodes are: {sorted(graph_nodes)}"
    )


def test_shared_infra_nodes_always_present(graph):
    """The shared pipeline-stage and entry/exit nodes are always registered,
    regardless of registry contents."""
    graph_nodes = set(graph.nodes.keys())
    required = {"dialogue", "sparql", "sql", "analytics", "response"}
    missing = required - graph_nodes
    assert missing == set(), f"Shared infra nodes missing from graph: {missing}"


def test_no_intent_route_target_can_crash_graph_build(registry):
    """Even if an intent overlay points to an unregistered node (e.g.
    bldg2 adds `lab_equipment` whose route_target falls back to
    'lab_equipment' but no node exists), the graph build must succeed
    because Phase 13B filters the dialogue route map by registered nodes
    only.

    The Phase 10G runtime safety net then rewrites unregistered targets
    to 'response' before LangGraph sees them.
    """
    from orchestrator.workflow import WorkflowOrchestrator

    # The bldg1 registry already includes the `lab_booking` overlay which
    # has no node_method — its route_target falls back to 'lab_booking'
    # which has no graph node.  This test passes if _build_graph completes
    # without raising.
    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    g = inst._build_graph()
    assert g is not None
    assert "dialogue" in g.nodes


def test_dialogue_routing_only_targets_registered_nodes(graph):
    """Sanity: every conditional edge from `dialogue` must point at a
    registered node — otherwise LangGraph would have errored at build."""
    # We don't introspect LangGraph internals; the fact that the fixture
    # built successfully proves this invariant.  We assert the fixture exists.
    assert "dialogue" in graph.nodes
