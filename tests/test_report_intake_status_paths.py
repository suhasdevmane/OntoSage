"""The status and list paths of report intake must not crash on unset locals.

`location`, `device` and `res` were assigned only in the `create` branch while the result dict at
the end of the node read all three for every action, so asking for a report's status without an id
raised UnboundLocalError and the composed answer was replaced by the generic failure text.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path("orchestrator/workflow/_orchestrator.py")


def _node_body() -> ast.AST:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_report_intake_node":
            return node
    raise AssertionError("_report_intake_node not found")


@pytest.mark.parametrize("name", ["location", "device", "res"])
def test_name_is_bound_before_any_branch(name):
    """The first binding of each name must not sit inside an if/elif/else branch."""
    fn = _node_body()
    first = None
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        for t in targets:
            if t.id == name and (first is None or t.lineno < first):
                first = t.lineno
    assert first is not None, f"{name} is never assigned"

    for branch in ast.walk(fn):
        if isinstance(branch, ast.If):
            inner = [n for b in (branch.body, branch.orelse) for n in b]
            lines = [getattr(n, "lineno", -1) for n in inner]
            if lines and min(lines) <= first <= max(
                getattr(n, "end_lineno", getattr(n, "lineno", -1)) for n in inner
            ):
                raise AssertionError(
                    f"first binding of '{name}' (line {first}) is inside a conditional branch; "
                    "it must be initialised before the action branches"
                )
