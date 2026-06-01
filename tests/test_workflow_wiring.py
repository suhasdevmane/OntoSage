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
    assert "document" in g.nodes, (
        f"Expected 'document' node in graph; got: {sorted(g.nodes)}"
    )

    # _route_from_report is class-method, still load-bearing.
    assert hasattr(WorkflowOrchestrator, "_route_from_report"), (
        "_route_from_report routing function must exist on WorkflowOrchestrator"
    )
    # _document_node implementation also still required.
    assert hasattr(WorkflowOrchestrator, "_document_node"), (
        "_document_node implementation must exist on WorkflowOrchestrator"
    )


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
