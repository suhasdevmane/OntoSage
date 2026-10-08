"""Workflow wiring invariants.

Phase 17A converted `orchestrator/workflow.py` into the `orchestrator/workflow/`
package; these tests were previously string-matching against the old monolithic
file path.  They are now BEHAVIORAL — they exercise the actual workflow
construction so they survive any future internal refactors.
"""

from pathlib import Path


def _orchestrator_source() -> str:
    """Read the post-Phase-17A workflow source (now under workflow/_orchestrator.py)."""
    return Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")


def test_workflow_contains_document_node():
    """The document node must be registered and the report routing
    function must exist on the orchestrator."""
    from orchestrator.workflow import WorkflowOrchestrator

    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    g = inst._build_graph()
    assert "document" in g.nodes, f"Expected 'document' node in graph; got: {sorted(g.nodes)}"

    # _route_from_report is class-method, still load-bearing.
    assert hasattr(
        WorkflowOrchestrator, "_route_from_report"
    ), "_route_from_report routing function must exist on WorkflowOrchestrator"
    # _document_node implementation also still required.
    assert hasattr(
        WorkflowOrchestrator, "_document_node"
    ), "_document_node implementation must exist on WorkflowOrchestrator"


def test_workflow_routes_report_to_planner():
    """Phase 6D — the explicit elif branch was replaced by a registry lookup;
    the contract is preserved by `report.route_target = planner` in YAML."""
    from orchestrator.intents import get_intent_registry

    get_intent_registry.cache_clear()
    reg = get_intent_registry()
    assert reg.route_target_for("report") == "planner"
    get_intent_registry.cache_clear()


def test_response_includes_document_result():
    """The response node reads `document_result` from intermediate_results
    so document agent output reaches the user.  This is a SOURCE-level
    check because the data-flow contract lives in the response node body."""
    assert "document_result" in _orchestrator_source()


def test_dialogue_chain_preserves_registry_intents():
    """Registry-known intents the legacy dispatch chain does not name (alert,
    automation_capability, preference_management, overlays) must be preserved
    as current_intent, not defaulted into the sparql data pipeline.

    Regression for 2026-06-12 finding: "list my alerts" ran SPARQL and listed
    power sensors because the chain's else-branch forced current_intent=sparql
    for every label it did not recognise.
    """
    src = _orchestrator_source()
    assert "_registry_known" in src, (
        "dialogue chain must consult the intent registry before defaulting "
        "unrecognised intents to the sparql pipeline"
    )
    # The override re-sync must also be present: T22/T34/benchmark overrides
    # write intermediate_results["intent"], and the chain must re-read it.
    assert "_post_override_intent" in src, (
        "dialogue node must re-sync the local intent variable after "
        "deterministic overrides so they reach routing"
    )


def test_registry_standalone_intents_route_to_registered_nodes():
    """Every standalone intent in the registry must resolve to a node that
    _route_from_dialogue would accept (the Phase 10G safety-net set)."""
    from orchestrator.intents import get_intent_registry
    from orchestrator.workflow import WorkflowOrchestrator

    reg = get_intent_registry(None)
    # Behavioural, like the rest of this file: ask the graph the orchestrator really builds.
    # This used to demand the literal string "<target>" in _orchestrator.py, which a lane that
    # is auto-registered from the YAML and routed by the routing contract (comfort_history,
    # session_recall, ...) never needs to contain -- the lane worked and the test went red.
    graph_nodes = set(WorkflowOrchestrator.__new__(WorkflowOrchestrator)._build_graph().nodes)
    wired = 0
    for name in reg.names():
        d = reg.get(name)
        if getattr(d, "pipeline_group", None) != "standalone":
            continue
        target = reg.route_target_for(name)
        assert target, f"standalone intent {name} has no route target"
        # Intents WITHOUT a node_method (e.g. per-building overlays like
        # lab_booking) deliberately fall through the Phase 10G safety net to
        # "response" — only intents that DECLARE a handler must be wired.
        if getattr(d, "node_method", None):
            wired += 1
            assert hasattr(WorkflowOrchestrator, d.node_method), (
                f"standalone intent {name} declares node_method {d.node_method!r}, "
                "which WorkflowOrchestrator does not define"
            )
            assert target in graph_nodes, (
                f"standalone intent {name} declares node_method "
                f"{d.node_method!r} but its target {target!r} is not a node in the "
                f"compiled graph ({sorted(graph_nodes)}) -- an unregistered node"
            )
    # The inner check is the one that matters, and a registry that stopped declaring
    # node_method anywhere would skip it entirely while the test stayed green.
    assert wired, "no standalone intent declares a node_method — nothing was verified"


def test_registry_intent_nodes_have_response_edge():
    """Auto-registered intent nodes must terminate at response, not dangle to
    END (fix 2026-06-12: alert_mgmt / preference_management /
    automation_capability_check ran but their dialogue_response was dropped
    because no outgoing edge existed — users got an echo of their question)."""
    from orchestrator.workflow import WorkflowOrchestrator

    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    g = inst._build_graph()
    edges = {(e.source, e.target) for e in g.get_graph().edges}
    for node in ("alert_mgmt", "preference_management", "automation_capability_check"):
        assert (
            node,
            "response",
        ) in edges, f"{node} has no edge to response — its dialogue_response would be dropped"
