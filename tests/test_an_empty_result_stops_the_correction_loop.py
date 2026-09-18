# -*- coding: utf-8 -*-
"""An empty SPARQL result stops the correction loop instead of mutating a valid query.

WHAT WENT WRONG
---------------
``SelfCorrectionEngine`` has a fast path whose comment states the reasoning exactly: an
empty result is a data-absence, not a query bug, so stop and let the caller fall through.
It compared against the literal ``"Empty result set"`` -- a string the engine SYNTHESISES
itself, and only when the executor reported no error at all::

    error = result.get("error") or ("Empty result set" if is_success and count == 0 else None)

The sparql lane reports its own error for this case: ``"error": None if bindings else
"Empty results"``. That value is truthy, so the ``or`` short-circuits, ``error`` is
``"Empty results"``, and the literal tested below never matched.

So on the main path the branch NEVER FIRED. Every honest "no data" answer paid for up to
three further SPARQL executions at a 30 s timeout each and then fell through to exactly the
same place.

WHY IT IS ALSO A CORRECTNESS FIX, NOT ONLY LATENCY
---------------------------------------------------
``success=True`` with zero rows means the query PARSED AND RAN. The syntax and prefix
strategies therefore cannot be repairing anything -- they can only mutate a valid query into
a different one. If that mutation happens to return rows, those rows become the answer to a
question the user did not ask. Stopping removes that substitution vector.

WHAT THESE TESTS PIN
--------------------
The behaviour, through the public entry point, counting real executor calls -- not the
string. Two modules agreeing on a magic string is the thing that failed; asserting on the
string would rebuild the same coupling in the test suite.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.self_correction_engine import SelfCorrectionEngine  # noqa: E402

QUERY = "SELECT ?s WHERE { ?s a brick:Nonexistent_Sensor } LIMIT 10"

CONTEXT = {
    "building_namespace": "http://example.org/b#",
    "building_prefix": "bldg",
    "user_query": "how many unicorn sensors are there?",
}


def _empty_as_the_sparql_lane_reports_it() -> Dict:
    """The exact shape sparql_agent returns for a query that ran and matched nothing."""
    return {
        "success": True,
        "results": {"results": {"bindings": []}},
        "error": "Empty results",
    }


def _empty_with_no_error_field() -> Dict:
    """The other spelling: an executor that reports emptiness by saying nothing."""
    return {"success": True, "results": {"results": {"bindings": []}}, "error": None}


def _rows() -> Dict:
    return {
        "success": True,
        "results": {"results": {"bindings": [{"s": {"value": "http://example.org/b#S1"}}]}},
        "error": None,
    }


def _run(responses: List[Dict]) -> Dict:
    """Execute with a scripted executor; returns {'calls': [...], 'result': ...}."""
    calls: List[str] = []

    async def execute_fn(q: str) -> Dict:
        calls.append(q)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    engine = SelfCorrectionEngine()
    result = asyncio.run(engine.execute_with_correction(QUERY, execute_fn, dict(CONTEXT)))
    return {"calls": calls, "result": result}


# ── the defect ───────────────────────────────────────────────────────────────


def test_an_empty_result_is_executed_once_not_repeatedly():
    """Before the fix this ran the executor up to max_attempts+1 times."""
    out = _run([_empty_as_the_sparql_lane_reports_it()])
    assert len(out["calls"]) == 1, (
        f"executed {len(out['calls'])} times for a query that parsed and returned nothing; "
        "the correction strategies cannot repair a query that already ran"
    )


def test_the_query_is_never_mutated_when_it_ran_and_matched_nothing():
    """The substitution vector: a mutated valid query can answer a different question."""
    out = _run([_empty_as_the_sparql_lane_reports_it()])
    assert out["calls"] == [QUERY]


def test_both_spellings_of_empty_stop_the_loop():
    """The executor may report emptiness with an error string or with silence."""
    for responses in ([_empty_as_the_sparql_lane_reports_it()], [_empty_with_no_error_field()]):
        out = _run(responses)
        assert len(out["calls"]) == 1


def test_the_empty_result_is_still_returned_to_the_caller():
    """Stopping early must not swallow the rows -- the caller reads them, not the flag.

    NOTE, measured rather than assumed: the engine stamps ``success=False`` and a
    "please try rephrasing" message onto this result, which is a category error -- the
    query PARSED AND RAN and the building simply holds nothing matching it, so blaming
    the user's phrasing is the wrong kind of nothing. It is currently harmless because
    ``sparql_agent`` ignores both fields: it re-reads the bindings itself and falls
    through to the semantic-RAG lane when there are none. This test pins what the caller
    ACTUALLY depends on. The mislabelling is logged separately (BUG-653) rather than
    fixed here, because changing ``success`` for this path changes what every downstream
    reader sees and that is not a code-freeze-day change.
    """
    out = _run([_empty_as_the_sparql_lane_reports_it()])
    assert out["result"] is not None
    assert out["result"].get("results", {}).get("results", {}).get("bindings") == []


# ── what must NOT change ─────────────────────────────────────────────────────


def test_a_query_that_returns_rows_is_executed_once_and_succeeds():
    out = _run([_rows()])
    assert len(out["calls"]) == 1
    assert out["result"].get("success") is True


def test_a_real_failure_still_gets_corrected():
    """The loop exists for broken queries. A syntax error must still be retried."""
    broken = {"success": False, "error": "MALFORMED QUERY: Lexical error", "results": {}}
    out = _run([broken])
    assert len(out["calls"]) > 1, (
        "a query that FAILED to parse must still go through the correction strategies; "
        "the fast path is only for queries that ran"
    )


def test_a_failure_that_later_returns_rows_uses_them():
    out = _run([{"success": False, "error": "MALFORMED QUERY", "results": {}}, _rows()])
    assert len(out["calls"]) >= 2
    assert out["result"].get("success") is True
