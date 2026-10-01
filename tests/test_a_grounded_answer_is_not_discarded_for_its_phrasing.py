# -*- coding: utf-8 -*-
"""BUG-550: 'based on the data you shared' is reworded on a grounded answer, not suppressed."""

import pytest

from orchestrator.services.grounding_guard import (
    meta_answer_reason,
    reword_handover_phrasing,
)

pytestmark = pytest.mark.unit


def test_handover_phrasing_alone_is_reworded():
    text = (
        "Based on the data provided, three energy-saving opportunities stand out: floor 5 "
        "lighting runs overnight, and the data you shared shows AHU-3 at full duty on Sunday."
    )
    assert meta_answer_reason(text)
    out = reword_handover_phrasing(text)
    assert out and meta_answer_reason(out) is None
    assert "the building's data" in out and "AHU-3 at full duty on Sunday" in out


def test_a_substance_marker_is_not_rescued_by_rewording():
    text = (
        "The data you shared only tells us how many sensors there are. If you can run a "
        "query for the readings I can help further."
    )
    assert reword_handover_phrasing(text) is None


def test_clean_text_is_left_to_the_caller():
    assert reword_handover_phrasing("Floor 5 used 12% more energy overnight.") is None


def _response_node_ast():
    """`_response_node` parsed, so these checks read STRUCTURE and not a character window.

    Both assertions below used to slice the source by count -- `block[:400]`, `src[i:i+900]`
    -- which is a bet on how much code and comment sits around the line of interest.
    lessons #151: three such assertions broke in one day without a single behaviour
    changing, one of them "fixed" by widening the window twice. A condition found by
    walking the tree cannot be moved by `black`.
    """
    import ast
    import inspect
    import textwrap

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = textwrap.dedent(inspect.getsource(WorkflowOrchestrator._response_node))
    return ast, ast.parse(src)


def test_the_response_node_rewords_only_when_the_verifier_says_grounded():
    ast, tree = _response_node_ast()

    guards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.IfExp)
        and isinstance(node.body, ast.Call)
        and ast.unparse(node.body.func) == "reword_handover_phrasing"
    ]
    assert guards, "_response_node no longer rewords the handover phrasing at all"
    for guard in guards:
        condition = ast.unparse(guard.test)
        assert "grounded" in condition, (
            "the reword is no longer gated on the verifier calling the answer grounded: "
            + condition
        )


def test_a_whole_register_answer_is_exempt_from_the_pivot_marker():
    """BUG-564: the register narration's required 'what they do record' tripped the pivot guard."""
    ast, tree = _response_node_ast()

    def _clears_meta(node):
        return any(
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_meta" for t in stmt.targets)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is None
            for stmt in ast.walk(node)
        )

    exemptions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "whole_register" in ast.unparse(node.test)
        and _clears_meta(node)
    ]
    assert (
        exemptions
    ), "no branch clears the pivot marker for a whole-register answer — BUG-564 is back"
