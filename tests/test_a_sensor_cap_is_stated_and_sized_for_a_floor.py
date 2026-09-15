# -*- coding: utf-8 -*-
"""BUG-534 — a sensor cap is sized for a floor, deterministic, and said.

Live, 2026-09-15, "Compare the average CO2 on floor 1 versus floor 3": 61 matching sensors in
one store, and `grouped_uuids[key][:30]` kept 5 of floor 1's 13 and 25 of floor 3's 48. The
answer stated a floor-1 average computed over 5 of 13 sensors, and which 5 depended on the
order SPARQL happened to return. The regression probe PASSED, because its marker checks the
shape of the answer.

Structural checks (AST, not prose — lessons.md #102), because the cap lives inside a long
async method whose behaviour is otherwise only reachable with a live store.
"""

from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.sql_agent import MAX_FETCH_UUIDS, SQLAgent  # noqa: E402


def _method_tree():
    src = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    return src, ast.parse("class _X:\n" + src)


def _cap_value() -> int:
    _, tree = _method_tree()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_UUID_CAP" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            return int(node.value.value)
    raise AssertionError("_UUID_CAP is not assigned a constant any more")


def test_the_cap_clears_a_whole_floor():
    """The measured case needed 61 sensors across two floors. A cap below that silently
    averages part of a floor and calls it the floor."""
    assert _cap_value() >= 61


def test_the_cap_stays_inside_the_lane_budget():
    assert _cap_value() <= MAX_FETCH_UUIDS


def test_the_kept_set_does_not_depend_on_result_order():
    """`sorted(...)` before the slice. Without it, which sensors survive is whatever order
    the graph returned — the same question could compare floor 3 against nothing."""
    _, tree = _method_tree()
    sliced_sorted = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if isinstance(fn, ast.Name) and fn.id == "sorted":
                sliced_sorted = True
    assert sliced_sorted, "the cap slices without sorting first"


def test_a_binding_cap_reaches_the_answer_and_the_result():
    src, _ = _method_tree()
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert '"points_capped"' in code, "the cap is not recorded on the result"
    assert "matching sensors" in code, "the cap is not said in the answer"
