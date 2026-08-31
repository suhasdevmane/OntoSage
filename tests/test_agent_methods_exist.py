# -*- coding: utf-8 -*-
"""Every `self.<name>(...)` an agent calls must actually be a method (V7-T23, BUG-375).

`SpatialAgent.resolve` called `self._load_manifests(...)`. That function existed — nested
four indents too deep inside the module-level `_blocked_vertical_nodes_for`, after that
function's return, so it was a local of a function nobody called it from and was never a
method at all. Every spatial question that reached `resolve()` raised AttributeError, and
the broad `except` there turned it into "I encountered an error analysing the spatial
data". 29 measured questions, all wayfinding, none of them a data problem.

A behavioural test could not have caught it: any test that stubs the manifest loader
supplies the very attribute that is missing. The defect is structural, so the check is
too — it reads the source and asks whether what an agent calls on itself exists.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

import pytest

pytestmark = pytest.mark.unit

AGENTS = sorted((Path(__file__).resolve().parents[1] / "orchestrator" / "agents").glob("*.py"))


def _classes(tree: ast.Module) -> List[ast.ClassDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def _defined(cls: ast.ClassDef) -> Set[str]:
    """Names bound on the class: methods, class attributes, annotated attributes."""
    names: Set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _self_attrs_called(cls: ast.ClassDef) -> Set[str]:
    """Every `self.NAME(...)` invoked anywhere in the class body."""
    called: Set[str] = set()
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            called.add(node.func.attr)
    return called


def _assigned_on_self(cls: ast.ClassDef) -> Set[str]:
    """Names bound as `self.NAME = ...` anywhere (including in __init__)."""
    names: Set[str] = set()
    for node in ast.walk(cls):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "self"
            ):
                names.add(t.attr)
    return names


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.name)
def test_every_self_call_resolves_to_something_the_class_defines(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for cls in _classes(tree):
        # Inherited members are invisible to a source read, so a subclass is skipped
        # rather than reported as broken.
        if cls.bases:
            continue
        known = _defined(cls) | _assigned_on_self(cls)
        missing = sorted(n for n in _self_attrs_called(cls) if n not in known)
        assert not missing, (
            f"{path.name}: {cls.name} calls self.{{{', '.join(missing)}}} "
            "but the class defines no such attribute — check for a method that drifted "
            "out of the class body (BUG-375)"
        )


def test_the_spatial_loader_is_a_method_and_not_a_nested_function():
    """The specific regression, named, so a future re-indent is caught by name."""
    from orchestrator.agents.spatial_agent import SpatialAgent

    assert callable(getattr(SpatialAgent, "_load_manifests", None))


def test_no_module_level_function_hides_a_would_be_method():
    """A def taking `self` as its first argument does not belong at module scope."""
    for path in AGENTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            inner = [
                n
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.args.args
                and n.args.args[0].arg == "self"
            ]
            assert not inner, (
                f"{path.name}: {node.name} nests {[n.name for n in inner]}, which takes "
                "`self` — that is a method that landed inside a function"
            )
