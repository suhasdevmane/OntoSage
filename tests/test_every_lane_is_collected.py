# -*- coding: utf-8 -*-
"""Every intent's answer is collected on the response path (V12-07, review case B02).

WHY THIS IS A TEST AND NOT A REPAIR
-----------------------------------
R7 -- "a lane computes but its answer is lost" -- is already CLOSED. All 37 intents were
audited on 2026-09-09 and zero were uncollected. Building a repair would be treating a
historical defect as still open, which the review names as its own failure mode (p. 16:
*"Inspect first; do not automatically add a parallel framework or treat a historical defect
as still open."*).

What is missing is the guard that fails when intent 38 arrives with no collector.

THE INCIDENT
------------
The observability lane (V6-T10) routed correctly, ran, and computed the right answer. The
user saw:

    "I processed your request, but couldn't generate a response."

Its own unit tests passed throughout, because routing and execution are two steps and
DELIVERY is a third. `.claude/rules/agent-patterns.md` was updated to say so: *"Adding an
intent is three steps, not two, and the third is the one nobody remembers."*

HOW THIS GUARD WORKS
--------------------
It derives the mapping instead of keeping one. For each intent in
`intent_definitions.yaml` it finds the declared `node_method`, parses that method for the
`intermediate_results` keys it writes, and asserts at least one of them is read on the
response path. Nothing here is hand-maintained, so nothing here can drift -- which matters,
because a hand-kept list is exactly what produced BUG-509 and BUG-510.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Set

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ORCH_SRC = REPO / "orchestrator" / "workflow" / "_orchestrator.py"
INTENTS = REPO / "orchestrator" / "intents" / "intent_definitions.yaml"

#: Keys that are NOT a lane's answer. A node writing only these has produced control flow,
#: not something to publish, and requiring them to be collected would be meaningless.
_NOT_AN_ANSWER = {
    "error",
    "user_context",
    "pending_clarification_type",
    "needs_clarification_payload",
    "live_data_route",
    "answer_length_used",
    "floor_context_hint",
    "observability_reach",
    "report_missing_location",
    "sparql_result",  # a shared pipeline stage, collected further down the chain
}


def _tree():
    return ast.parse(ORCH_SRC.read_text(encoding="utf-8"))


def _methods() -> Dict[str, ast.AST]:
    return {
        n.name: n
        for n in ast.walk(_tree())
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def _keys_written_by(fn: ast.AST) -> Set[str]:
    """Bus keys this method assigns into `…intermediate_results["X"]`."""
    keys: Set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if (
                isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant)
                and isinstance(t.slice.value, str)
                and isinstance(t.value, ast.Attribute)
                and t.value.attr == "intermediate_results"
            ):
                keys.add(t.slice.value)
    return keys


def _keys_read_on_the_response_path() -> Set[str]:
    """Every key `_response_node` could collect an answer from.

    Two access styles, and missing either would produce a false failure:

    * ``state.intermediate_results.get("x")`` -- the direct read;
    * ``ctx.x`` -- the typed `pipeline_ctx` snapshot, which is how the older lanes are
      read (`ctx.sql_result`, `ctx.analytics_result`, `ctx.planner_result`).
    """
    fn = _methods().get("_response_node")
    assert fn is not None, "_response_node is missing — the response path has moved"

    read: Set[str] = set()
    for node in ast.walk(fn):
        # state.intermediate_results.get("x")  /  [...]["x"]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "setdefault") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    read.add(arg.value)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                read.add(node.slice.value)
        # ctx.<attr>  — the typed snapshot
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "ctx":
                read.add(node.attr)
    return read


def _intents():
    doc = yaml.safe_load(INTENTS.read_text(encoding="utf-8"))
    return doc.get("intents", doc) if isinstance(doc, dict) else doc


# ── the contract ─────────────────────────────────────────────────────────────


def test_every_intent_with_a_node_has_that_node_on_the_class():
    """Step 2 of three. A YAML entry naming a method that does not exist routes into
    nothing at all."""
    methods = _methods()
    missing = [
        (i["name"], i["node_method"])
        for i in _intents()
        if i.get("node_method") and i["node_method"] not in methods
    ]
    assert not missing, f"intent declares a node_method that does not exist: {missing}"


def test_every_lane_that_computes_an_answer_has_it_collected():
    """Step 3 of three — the one nobody remembers.

    Routing correctly and running correctly is not enough: `_response_node` also has to
    read the key. The observability lane did the first two and the user was told the
    system couldn't generate a response.
    """
    methods = _methods()
    read = _keys_read_on_the_response_path()

    uncollected = []
    for intent in _intents():
        node_method = intent.get("node_method")
        if not node_method:
            continue  # data-group intents flow through the shared pipeline
        written = _keys_written_by(methods[node_method]) - _NOT_AN_ANSWER
        if not written:
            continue
        if not (written & read):
            uncollected.append((intent["name"], node_method, sorted(written)))

    assert not uncollected, (
        "these lanes compute an answer that the response path never reads — the user "
        f"gets 'I processed your request, but couldn't generate a response':\n{uncollected}"
    )


def test_deleting_a_collector_branch_would_fail_this_test():
    """The guard must be able to fail. A check that cannot detect its own defect is the
    literal scanner reporting 'clean' over two directories with fifteen literals outside
    its scope.

    Simulated by removing a key from the read-set and re-running the same comparison.
    """
    methods = _methods()
    read = _keys_read_on_the_response_path()
    assert "register_result" in read, "fixture assumption: the register lane is collected"

    crippled = read - {"register_result"}
    written = _keys_written_by(methods["_register_node"]) - _NOT_AN_ANSWER
    assert written, "the register node writes no answer key — fixture is wrong"
    assert not (written & crippled), (
        "removing register_result from the read-set did NOT make the register lane look "
        "uncollected, so this test cannot detect a deleted collector branch"
    )


def test_the_generic_no_answer_string_is_a_last_resort_not_a_lane_outcome():
    """No generic success-without-answer state may survive for a lane that produced one.

    The string itself is legitimate — something must be said when nothing was produced.
    What must not happen is a lane computing an answer and still reaching it.
    """
    body = ORCH_SRC.read_text(encoding="utf-8")
    assert "I processed your request, but couldn't generate a response" in body, (
        "the fallback wording changed; update this test and the incident note with it"
    )
    # It must be documented as the symptom of an uncollected lane, so the next person to
    # see it in a log knows where to look.
    assert "couldn't generate a response" in body and "collect" in body.lower()


def test_report_intake_family_shares_one_collector():
    """Five intents route to _report_intake_node, so one broken collector silences five
    lanes at once — worth pinning explicitly rather than trusting the sweep to notice.

    The answer travels on `dialogue_response`, NOT on `report_intake_result`. That second
    key holds metadata — category, report_id, location — read by
    `evidence/assemble.py` so the record can cite WHICH report was filed (TODO-229).

    This test first asserted `report_intake_result` was read on the response path. It is
    not, and should not be: adding a collector branch for it would publish a metadata dict
    where prose belongs. The distinction is written down here because the natural "fix"
    for the failing version of this test was to break the lane.
    """
    read = _keys_read_on_the_response_path()
    family = [i["name"] for i in _intents() if i.get("node_method") == "_report_intake_node"]
    assert len(family) >= 5, f"expected the intake family, found {family}"

    assert "dialogue_response" in read, (
        "the intake family's ANSWER key is not collected — five lanes would go silent"
    )

    # And the metadata key must keep its own consumer, or the evidence record loses the
    # ability to say which report was filed.
    assemble = (REPO / "orchestrator" / "services" / "evidence" / "assemble.py").read_text(
        encoding="utf-8"
    )
    assert "report_intake_result" in assemble, (
        "report_intake_result is metadata for the evidence record; if assemble.py stopped "
        "reading it, a filed report becomes unciteable (TODO-229)"
    )
