# -*- coding: utf-8 -*-
"""Every documented reserved bus key has a writer, and the planner is one of them.

V12-14, covering BUG-509 and BUG-241.

WHY AN AUDIT AND NOT A REVIEW
-----------------------------
`.claude/rules/agent-patterns.md` documented ``uuids`` as a reserved bus key. It is not one
-- it is a local inside the sql node and nothing has ever written it to the bus. Three
readers believed the document, and ``_sources_from`` created no per-sensor sources at all
as a result. The same file also documented ``sparql_results`` and ``sql_data``, strings
that appear nowhere in the pipeline, and ``assemble.py`` was written from that list rather
than from the code -- so the two most important data lanes could never be identified and
their answers were recorded as having no evidence.

A hand-kept list of reserved names has no failure mode. Nothing breaks when it drifts, so
nothing catches it. This derives the answer from the source instead.

THE DEFECT THIS EXISTS TO HAVE CAUGHT
-------------------------------------
``PlannerAgent._execute_step`` wrote ``sparql_result``, ``sql_result``, ``report_result``
and six more into a LOCAL dict that was never merged onto the bus. Only ``planner_result``
was published. So every consumer keyed off the reserved names -- the verifier, the evidence
record, V12-03's publication gate -- read an EMPTY bus for any planner-routed turn, which
is the whole ``report`` intent.

Measured live 2026-09-10: a report built from real rows verified as
``sensors=0, sql_rows=0, report_rows=0`` while the adapter logs for the same turn showed
dozens of successful queries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Set

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ORCH = REPO / "orchestrator"
RULES = REPO / ".claude" / "rules" / "agent-patterns.md"


def _python_files():
    for p in ORCH.rglob("*.py"):
        if "__pycache__" in p.parts or "/tests/" in p.as_posix():
            continue
        yield p


def _keys_written() -> Dict[str, Set[str]]:
    """Every string key assigned into an `intermediate_results` mapping, by file.

    Found by PARSING, not by grepping: a grep for `intermediate_results["x"] =` misses
    `state.intermediate_results.setdefault(...)`, misses assignment through an alias, and
    matches the string inside a docstring that merely discusses the key. The literal guard
    in this repo learned the same lesson -- its first version reported 16 hits of which 14
    were prose inside docstrings.
    """
    out: Dict[str, Set[str]] = {}
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        found: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        base = target.value
                        name = ""
                        if isinstance(base, ast.Attribute):
                            name = base.attr
                        elif isinstance(base, ast.Name):
                            name = base.id
                        if name in ("intermediate_results", "context", "results"):
                            found.add(target.slice.value)
        if found:
            out[str(path.relative_to(REPO))] = found
    return out


def _documented_keys() -> Set[str]:
    """Reserved keys as `.claude/rules/agent-patterns.md` DECLARES them.

    Only the first backticked token of a list item counts -- ``- `sql_result` — set by...``
    -- because the section is full of prose that names keys in order to say they are NOT
    keys. The first version of this reader took every backticked token in the section and
    so re-reported ``analytics_output`` the moment the fix explained why it was wrong,
    which would have trained the next person to delete the check rather than the key.

    Structure, not grep. It is the same lesson the building-literal scanner learned when
    its first version reported 16 hits of which 14 were prose inside docstrings.
    """
    if not RULES.is_file():
        pytest.skip("agent-patterns.md not present")
    body = RULES.read_text(encoding="utf-8", errors="replace")
    section = body.split("Reserved keys")[-1].split("## 4.")[0]
    keys: Set[str] = set()
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- `"):
            continue  # prose, a blockquote, or a continuation line
        m = re.match(r"- `([a-z_]+)`", stripped)
        if m:
            keys.add(m.group(1))
    return keys


def test_every_documented_reserved_key_has_a_writer():
    """Zero documented keys may have no writer. `uuids` was documented for months."""
    written: Set[str] = set()
    for keys in _keys_written().values():
        written |= keys
    documented = _documented_keys()
    assert documented, "could not parse any reserved keys out of agent-patterns.md"

    orphans = sorted(k for k in documented if k not in written)
    assert not orphans, (
        f"documented as reserved bus keys but nothing writes them: {orphans}. "
        "Either a writer was removed, or the documentation names a key that never "
        "existed — which is what happened with `uuids`, `sparql_results` and `sql_data`."
    )


def test_uuids_is_not_claimed_as_a_bus_key():
    """The specific false entry, pinned so it cannot come back."""
    body = RULES.read_text(encoding="utf-8", errors="replace")
    assert "**`uuids` is\n  NOT a bus key**" in body or "NOT a bus key" in body, (
        "agent-patterns.md must keep stating that `uuids` is a local, not a bus key"
    )


# ── BUG-509: the planner must reach the bus ──────────────────────────────────


def test_the_planner_publishes_its_results_to_the_bus():
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState

    state = ConversationState(conversation_id="t", user_message="q")
    planner = PlannerAgent()
    context = {
        "sparql_result": {"success": True, "results": {"results": {"bindings": [{"a": 1}]}}},
        "sql_result": {"results": {"data": [{"v": 1}, {"v": 2}]}},
        "report_result": {"sections": {"overview": {"data_points": 1000}}},
        "uuids": ["should-not-be-published"],
        "storage_map": {"also": "internal"},
    }
    planner._publish_context_to_bus(state, context)

    assert state.intermediate_results["sql_result"] == context["sql_result"]
    assert state.intermediate_results["report_result"] == context["report_result"]
    assert state.intermediate_results["sparql_result"] == context["sparql_result"]
    # planner-internal locals must NOT become bus keys — that is the `uuids` mistake
    assert "uuids" not in state.intermediate_results
    assert "storage_map" not in state.intermediate_results


def test_publishing_never_clobbers_a_real_lane_result():
    """The reserved-key contract: a lane does not overwrite another lane's key."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState

    state = ConversationState(conversation_id="t", user_message="q")
    state.intermediate_results["sql_result"] = {"from": "the real sql node"}
    PlannerAgent()._publish_context_to_bus(state, {"sql_result": {"from": "the planner"}})
    assert state.intermediate_results["sql_result"] == {"from": "the real sql node"}


def test_an_empty_planner_result_is_not_published():
    """An empty dict on the bus is indistinguishable from a lane that ran and found
    nothing, which is exactly the confusion V12-05 exists to remove."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState

    state = ConversationState(conversation_id="t", user_message="q")
    PlannerAgent()._publish_context_to_bus(state, {"sql_result": {}, "report_result": None})
    assert "sql_result" not in state.intermediate_results
    assert "report_result" not in state.intermediate_results


def test_both_planner_exit_paths_publish():
    """The multi-intent path takes a different return. Patching only one would leave the
    compound question — the shape whose evidence a reader most needs — invisible while
    looking fixed."""
    src = (ORCH / "agents" / "planner_agent.py").read_text(encoding="utf-8")
    assert src.count("_publish_context_to_bus(state, context)") >= 2, (
        "both _execute_plan and _execute_multi_intent must publish"
    )


def test_what_the_planner_publishes_is_cleared_between_turns():
    """Anything readable on the bus is as stale next turn as any other lane's result
    (BUG-392: turn 1's answer was returned verbatim for turn 2)."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from orchestrator.workflow._orchestrator import (
        _CARRIED_FORWARD_ON_PURPOSE,
        _PER_TURN_LANE_KEYS,
    )

    for key in PlannerAgent._BUS_KEYS_THE_PLANNER_PRODUCES:
        assert key in _PER_TURN_LANE_KEYS or key in _CARRIED_FORWARD_ON_PURPOSE, (
            f"the planner publishes {key!r} but nothing clears it between turns"
        )
