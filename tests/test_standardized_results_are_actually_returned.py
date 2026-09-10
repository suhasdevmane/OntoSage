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
import textwrap
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


def _terminates(stmts: list) -> bool:
    """True when this block cannot fall through — every path returns or raises.

    REPLACES a one-line heuristic that was wrong in both directions (V12-12):

    * **Too permissive.** ``return not isinstance(last, (..., ast.If, ...))`` treated ANY
      trailing ``if`` as terminating. A function ending ``if hit: return hit`` with no
      ``else`` is precisely the BUG-476 shape — annotated, returns a value on one path,
      silently returns None on the other — and the guard for BUG-476 could not see it.
    * **Too strict**, once scope was widened. Reading the same line as "a trailing ``if``
      falls through" flags ``get_llm_config()``, whose ``if/elif/else`` returns on all
      three branches. Two false positives in ``shared/config.py`` alone, and a guard that
      cries wolf is one people learn to skip.

    Also fixes the ``Try`` arm, which asked whether ANY tail returned. One handler
    returning does not stop the others falling through.
    """
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If):
        # No `else` means the false branch falls straight through.
        return bool(last.orelse) and _terminates(last.body) and _terminates(last.orelse)
    if isinstance(last, ast.Try):
        if last.finalbody and _terminates(last.finalbody):
            return True  # a finally that returns ends the function whatever happened
        body_ok = _terminates(last.body) and (not last.orelse or _terminates(last.orelse))
        return body_ok and all(_terminates(h.body) for h in last.handlers)
    if isinstance(last, (ast.With, ast.AsyncWith)):
        return _terminates(last.body)
    if isinstance(last, ast.Match):
        return bool(last.cases) and all(_terminates(c.body) for c in last.cases)
    if isinstance(last, ast.While):
        # `while True:` with no break cannot fall through. Any other loop can run zero
        # times, so it can.
        constant_true = isinstance(last.test, ast.Constant) and bool(last.test.value)
        has_break = any(isinstance(n, ast.Break) for n in ast.walk(last))
        return constant_true and not has_break
    return False  # a for-loop, an expression, an assignment: all fall through


def _falls_off_the_end(fn: ast.AST) -> bool:
    """True when execution can reach the end of the body without returning or raising."""
    return not _terminates(fn.body)


def test_no_annotated_function_can_return_none_by_accident():
    """A function that promises a value and sometimes returns nothing is this bug.

    Scoped to functions that DO return a value somewhere — an annotation alone proves
    nothing, but an annotation plus a real return plus a reachable fall-through is the
    exact shape that cost a correct SPARQL result and produced a fabricated answer.
    """
    offenders = []
    # SCOPE WIDENED to shared/ (V12-12). It scanned `orchestrator/` alone, which is the
    # literal guard's mistake — that one covered two directories, reported "clean", and
    # fifteen real literals sat outside its scope. shared/ is 3,920 lines of core code and
    # `shared/config.py` is read by every service.
    for path in sorted(
        list(pathlib.Path("orchestrator").rglob("*.py"))
        + list(pathlib.Path("shared").rglob("*.py"))
    ):
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


# ── the analyser itself, pinned (V12-12) ─────────────────────────────────────
#
# The sweep above is only as good as `_terminates`, and its predecessor was wrong in both
# directions: it treated any trailing `if` as terminating (missing the BUG-476 shape) and,
# read the other way, would have flagged `get_llm_config()`'s exhaustive if/elif/else.
# Neither error is visible from the sweep's own result — it just reports a number.


def _fn(src: str):
    return ast.parse(textwrap.dedent(src)).body[0]


def test_a_trailing_if_with_no_else_falls_through():
    """The BUG-476 shape. The old heuristic called this terminating and could not see it."""
    assert _falls_off_the_end(_fn("""
        def f() -> dict:
            if hit:
                return hit
    """))


def test_an_exhaustive_if_elif_else_does_not_fall_through():
    """`shared/config.py:get_llm_config` — flagging it would be a false alarm, and a guard
    that cries wolf gets skipped."""
    assert not _falls_off_the_end(_fn("""
        def f() -> dict:
            if a:
                return 1
            elif b:
                return 2
            else:
                return 3
    """))


def test_one_returning_handler_does_not_excuse_the_others():
    """The Try arm asked whether ANY tail returned. One handler returning does not stop
    another falling through."""
    assert _falls_off_the_end(_fn("""
        def f() -> dict:
            try:
                return go()
            except ValueError:
                return {}
            except KeyError:
                log()
    """))


def test_a_finally_that_returns_ends_the_function():
    assert not _falls_off_the_end(_fn("""
        def f() -> dict:
            try:
                risky()
            finally:
                return {}
    """))


def test_a_for_loop_can_run_zero_times():
    assert _falls_off_the_end(_fn("""
        def f() -> dict:
            for x in xs:
                return x
    """))


def test_while_true_without_break_cannot_fall_through():
    assert not _falls_off_the_end(_fn("""
        def f() -> dict:
            while True:
                if ready():
                    return {}
    """))
