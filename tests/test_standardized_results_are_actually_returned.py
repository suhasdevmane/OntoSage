# -*- coding: utf-8 -*-
"""`_standardize_results` had no return statement (BUG-476).

It is annotated `-> Dict[str, Any]`. It builds the dict, fills it from the SPARQL
bindings, and then fell off the end — returning None on every call, on every path, since
it was written.

Nothing raised, because everything downstream reads it defensively:

    standardized = sparql_result.get("standardized", {})
    results = standardized.get("results", []) if isinstance(standardized, dict) else []

`isinstance(None, dict)` is False, so `results` was `[]`. Every time. The planner's
`_extract_uuids`, `_extract_storage_map` and `_extract_sensor_metadata` therefore returned
empty on every multi-step plan this system has ever run.

WHAT THAT COST
--------------
`PlannerAgent._run_sql` reads:

    if uuids:
        return await SQLAgent().fetch_data_for_uuids(uuids, query, storage_map)
    return await SQLAgent().generate_and_execute(state, query)

With `uuids` permanently empty it always took the second branch — let the LLM write the
SQL — and the LLM, handed a room called "5.01" and no sensor id, wrote:

    SELECT `Datetime` AS timestamp, `value` AS value, '5.01' AS uuid
    FROM `co2_data` WHERE `uuid` = '5.01'

Zero rows. Downstream, the report agent turned that into "No CO₂ sensor was active or
present in Room 5.01", "a critical monitoring gap", and a recommendation to install a
sensor — for a room whose CO₂ readings run to 77,088 rows a day. See
`test_an_empty_report_does_not_diagnose_the_building.py` for that half.

The SPARQL was CORRECT the whole time. It resolved `bldg:Zone_5.01`, picked
`brick:CO2_Level_Sensor` from the HBCO concept, ran, and logged `results=1`. The one row
it found was handed to a function that dropped it on the floor.

WHY NOTHING CAUGHT IT
---------------------
Defensive reads. Every consumer had a `.get(..., {})` fallback, so a total failure of the
data handoff was indistinguishable from "this question had no sensors", which is a real
and common case. Silence was already a legal answer.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.sparql_agent import SPARQLAgent  # noqa: E402

BINDINGS = {
    "results": {
        "bindings": [
            {
                "sensor": {
                    "type": "uri",
                    "value": "http://example.org/bldg#CO2_Level_Sensor_5.01",
                },
                "uuid": {"type": "literal", "value": "a66ca165-1e06-4901-a997-780fafc8581a"},
                "storage": {"type": "literal", "value": "database1"},
                "label": {"type": "literal", "value": "CO2 5.01"},
            }
        ]
    }
}


def test_it_returns_the_dict_it_builds():
    out = SPARQLAgent()._standardize_results(BINDINGS, "q", "SELECT ...")
    assert out is not None, "returns None: every downstream consumer sees no results at all"
    assert isinstance(out, dict)


def test_the_row_survives():
    out = SPARQLAgent()._standardize_results(BINDINGS, "q", "SELECT ...")
    rows = out["results"]
    assert len(rows) == 1
    assert rows[0]["uuid"] == "a66ca165-1e06-4901-a997-780fafc8581a"


def test_an_empty_binding_set_still_returns_a_dict():
    """No results is a real answer and must be distinguishable from a broken handoff."""
    out = SPARQLAgent()._standardize_results({"results": {"bindings": []}}, "q", "SELECT ...")
    assert isinstance(out, dict) and out["results"] == []


def test_a_malformed_result_returns_the_error_not_none():
    """The except branch fell off the end too — it set `error` and returned nothing."""
    out = SPARQLAgent()._standardize_results("not a dict at all", "q", "SELECT ...")
    assert isinstance(out, dict), "the failure path still returns None"


def test_the_planner_extractors_now_see_the_uuid():
    """The three consumers whose emptiness was the actual damage."""
    from orchestrator.agents.planner_agent import PlannerAgent

    result = {"standardized": SPARQLAgent()._standardize_results(BINDINGS, "q", "SELECT ...")}
    p = PlannerAgent()
    assert p._extract_uuids(result) == ["a66ca165-1e06-4901-a997-780fafc8581a"]
    assert p._extract_storage_map(result) == {"a66ca165-1e06-4901-a997-780fafc8581a": "database1"}
    assert "a66ca165-1e06-4901-a997-780fafc8581a" in p._extract_sensor_metadata(result)


# ── the class, not just the instance ────────────────────────────────────────


def _falls_off_the_end(fn: ast.AST) -> bool:
    """True when execution can reach the end of the body without returning or raising."""
    body = fn.body
    if not body:
        return True
    last = body[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return False
    if isinstance(last, ast.Try):
        tails = [last.body[-1] if last.body else None]
        tails += [h.body[-1] if h.body else None for h in last.handlers]
        if last.finalbody:
            tails.append(last.finalbody[-1])
        return not any(isinstance(t, (ast.Return, ast.Raise)) for t in tails)
    return not isinstance(last, (ast.While, ast.For, ast.If, ast.With, ast.AsyncWith, ast.Match))


def test_no_annotated_function_can_return_none_by_accident():
    """A function that promises a value and sometimes returns nothing is this bug.

    Scoped to functions that DO return a value somewhere — an annotation alone proves
    nothing, but an annotation plus a real return plus a reachable fall-through is the
    exact shape that cost a correct SPARQL result and produced a fabricated answer.
    """
    offenders = []
    for path in sorted(pathlib.Path("orchestrator").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.returns:
                continue
            ann = ast.unparse(node.returns)
            # `Optional[...]` and `X | None` say None is a legal answer. It isn't here.
            if ann in ("None", "NoReturn") or "Optional" in ann or ann.endswith("| None"):
                continue
            returns_a_value = any(
                isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node)
            )
            if returns_a_value and _falls_off_the_end(node):
                offenders.append(f"{path}:{node.lineno} {node.name}() -> {ann}")

    assert not offenders, (
        "these promise a value and can fall off the end returning None; downstream reads "
        "are defensive, so the failure is SILENT:\n  " + "\n  ".join(offenders)
    )
