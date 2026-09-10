# -*- coding: utf-8 -*-
"""The row limit was reported as the building's reading count (BUG-479).

MEASURED 2026-09-07, live. The report said:

    "Room 5.01 recorded 1,000 CO₂ sensor readings yesterday, with an average
     concentration of 995 ppm."

1,000 is `LIMIT 1000`. The window actually held 2,770 readings. The statistics were
correctly computed over the 1,000 rows fetched — min, max and average all checked out
against the database — and the sentence around them was a false claim about the building.

This is the recurring shape: **a cap on an exhaustive query does not fail, it
under-reports.** What is new is that it reached PROSE. A truncated table still looks
truncated; a sentence saying a room "recorded 1,000 readings" looks like a fact, and the
figure is real, so every check aimed at fabrication passes it.

WHY THE NARRATOR COULD NOT HAVE KNOWN
-------------------------------------
`overview.data_points` was `len(records)` and nothing else. The fetch knew it had stopped
at the limit and dropped that on the floor; by the time the number reached the prompt it
was indistinguishable from a complete count. The fix carries the truncation WITH the
number — a flag from the fetch, a note in the sections, and an explicit rule in the
narration prompt, because a note buried in serialised JSON competes with an instruction
that says "be specific".

The flag is READ, never re-derived. Comparing `len(rows)` to a literal 1000 in a second
file is how the cap and the check that detects it drift apart.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.report_agent import ReportAgent, ReportType, _is_capped  # noqa: E402


def _code(fn) -> str:
    """Source with docstrings stripped — these assertions are about code, not prose.

    The comments beside the fix quote the old figure and the old sentence verbatim, which
    is the point of them; a naive substring search fails on the documentation of the bug
    it is checking.
    """
    import ast

    tree = ast.parse(inspect.getsource(fn).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _sql_result(n: int, capped: bool) -> dict:
    """A SQL lane result of the shape `fetch_data_for_uuids` actually returns."""
    return {
        "success": True,
        "results": {"data": [{"timestamp": "t", "value": 900.0 + i} for i in range(n)]},
        "rows_capped": capped,
        "row_limit": 1000,
    }


# ── the flag survives the trip ──────────────────────────────────────────────


def test_a_capped_result_is_recognised():
    assert _is_capped(_sql_result(1000, capped=True)) is True


def test_an_uncapped_result_is_not():
    assert _is_capped(_sql_result(412, capped=False)) is False


def test_an_absent_flag_is_not_treated_as_capped():
    """Claiming a truncation that did not happen is its own false statement."""
    assert _is_capped({"results": {"data": []}}) is False
    assert _is_capped({}) is False
    assert _is_capped(None) is False


def test_the_flag_is_read_not_recomputed():
    """`len(rows) == 1000` in a second file is how the cap and its detector drift apart."""
    src = _code(_is_capped)
    assert "rows_capped" in src
    assert "1000" not in src, "the cap is hardcoded here too; now there are two of them"


# ── the sections carry it ───────────────────────────────────────────────────


def _sections(n: int, capped: bool) -> dict:
    import asyncio

    return asyncio.run(
        ReportAgent()._build_sections(
            "Give me a report on the CO2 in room 5.01 yesterday.",
            ReportType.SUMMARY,
            _sql_result(n, capped),
            {},
            building_id=None,
        )
    )


def test_a_capped_report_says_the_number_is_not_a_count():
    ov = _sections(1000, capped=True)["overview"]
    assert ov["data_points"] == 1000
    assert ov["data_points_are_complete"] is False
    note = ov.get("data_points_note", "").lower()
    assert "not the number" in note and "recorded" in note
    assert "true count is higher" in note


def test_an_uncapped_report_makes_no_such_claim():
    """The caveat must not appear on a complete result — a false hedge is still false."""
    ov = _sections(412, capped=False)["overview"]
    assert ov["data_points"] == 412
    assert ov["data_points_are_complete"] is True
    assert "data_points_note" not in ov


# ── the narrator is told, not left to infer ─────────────────────────────────


def test_the_prompt_forbids_the_exact_sentence_that_went_out():
    src = _code(ReportAgent._narrate)
    assert "data_points_are_complete" in src, (
        "the narration prompt does not consult the completeness flag, so it can still "
        "state a capped sample as a count"
    )
    assert "recorded" in src, "the prompt does not name the wrong verb it must avoid"


def test_the_prompt_differs_between_a_capped_and_a_complete_report():
    """A rule present in both cases teaches the model nothing about this one."""
    src = _code(ReportAgent._narrate)
    assert "counts_rule" in src
    assert "else" in src


def test_the_prompt_still_forbids_inventing_figures():
    assert "Do not estimate" in _code(ReportAgent._narrate)


def test_nothing_here_names_a_building():
    for fn in (_is_capped, ReportAgent._narrate):
        body = _code(fn).lower()
        for literal in ("bldg1", "bldg2", "abacws"):
            assert literal not in body
