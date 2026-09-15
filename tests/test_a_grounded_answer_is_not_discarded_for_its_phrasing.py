# -*- coding: utf-8 -*-
"""BUG-550: 'based on the data you shared' is reworded on a grounded answer, not suppressed."""

import pytest

from orchestrator.services.grounding_guard import meta_answer_reason, reword_handover_phrasing

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


def test_the_response_node_rewords_only_when_the_verifier_says_grounded():
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    block = src[src.index("reword_handover_phrasing(final_response)") - 200:]
    assert 'get("grounded") is True' in block[:400]


def test_a_whole_register_answer_is_exempt_from_the_pivot_marker():
    """BUG-564: the register narration's required 'what they do record' tripped the pivot guard."""
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    i = src.index("_meta = meta_answer_reason(final_response)")
    block = src[i : i + 900]
    assert '_sr.get("method") == "whole_register"' in block and "_meta = None" in block
