# -*- coding: utf-8 -*-
"""CAVEAT-1002 and CAVEAT-1006 — the two halves of BUG-939 that live in the response path.

BUG-939 had three parts. The window itself was fixed in the SQL lane (the bounds a question
names are now the bounds fetched). These are the other two, and both are about a fact the
system ALREADY KNEW failing to reach anyone.

**CAVEAT-1002 — a capped fetch is said to be capped.** `rows_capped` has been on the bus since
BUG-479 with exactly ONE reader (`report_agent`): a fact recorded rather than a fact used. The
live consequence, measured 2026-09-30:

    "Across **all** 1,000 readings taken between 21 Sep 21:36..."

published TWO LINES BELOW the lane's own log line `the set is TRUNCATED and its size is not a
count of what exists`. The guard fired and nobody heard it, because when the dispatch picks
model prose the lane's own wording never reaches the reader. So the disclosure belongs in
`_response_node`, beside its sibling — the SUBSTITUTED-window note, which is there for exactly
the same reason.

**CAVEAT-1006 — the bus carries the window the fetch used.** `resolve_named_window` corrects
the bounds inside the lane, but `time_range` on the bus was left as the classifier wrote it —
and `time_range` is what the analytics node, the verifier and the evidence record all read. The
rows could come from one period while every downstream consumer described another: BUG-936's
shape arriving through a different door.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.disclosure_gate import truncation_in, truncation_note
from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _capped_bus(limit=1000, label="the last 30 days"):
    return {
        "sql_result": {
            "rows_capped": True,
            "row_limit": limit,
            "rows_earliest": "2026-09-18 02:27",
            "rows_latest": "2026-09-30 04:31",
            "requested_window": {"label": label},
            "data": [{}] * limit,
        }
    }


# ── CAVEAT-1002: the disclosure ───────────────────────────────────────────────────────


def test_a_capped_fetch_produces_a_marker():
    marker = truncation_in(_capped_bus())
    assert marker and marker["capped"] is True
    assert marker["row_limit"] == 1000


def test_an_uncapped_fetch_produces_nothing():
    assert truncation_in({"sql_result": {"rows_capped": False}}) is None
    assert truncation_in({}) is None
    assert truncation_in(None) is None
    assert truncation_note(None) == ""


def test_the_note_says_the_count_is_a_sample():
    """The first of the two facts. A number derived from the row COUNT is not a count of what
    the period holds — which is precisely the claim "across all 1,000 readings" makes."""
    note = truncation_note(truncation_in(_capped_bus()))
    assert "sample" in note.lower()
    assert "not a count of what the period holds" in note


def test_the_note_says_the_period_covered_begins_later():
    """The second fact, and it is independent: the rows are the NEWEST ones, so the span
    actually covered starts after the span asked for. Either fact alone is misleading."""
    note = truncation_note(truncation_in(_capped_bus()))
    assert "2026-09-18 02:27" in note and "2026-09-30 04:31" in note
    assert "newest part of the last 30 days" in note


def test_it_is_appended_in_the_response_node_beside_its_sibling():
    """Not in the lane. When the dispatch picks model prose the lane's own wording never
    reaches the reader, which is how the defect was published in the first place."""
    src = inspect.getsource(WorkflowOrchestrator._response_node)
    assert "truncation_in as _truncation_in" in src
    assert "CAVEAT-1002" in src
    # the substituted-window note must still be there: they are siblings, not replacements
    assert "window_substitution_in as _window_substitution_in" in src


def test_the_disclosure_is_read_from_the_marker_not_from_prose():
    """A check that guessed from wording would be wrong exactly where it matters — where the
    wording is confident and the rows are not complete."""
    src = inspect.getsource(WorkflowOrchestrator._response_node)
    block = src[src.index("CAVEAT-1002") :]
    assert "_truncation_in(state.intermediate_results)" in block


def test_it_is_idempotent_and_never_costs_an_answer():
    src = inspect.getsource(WorkflowOrchestrator._response_node)
    block = src[src.index("CAVEAT-1002") :]
    assert "_cnote not in final_response" in block
    assert "except Exception" in block


# ── CAVEAT-1006: the bus agrees with the rows ─────────────────────────────────────────


def test_the_resolved_window_is_written_back_to_the_bus():
    src = inspect.getsource(WorkflowOrchestrator._sql_node)
    assert "CAVEAT-1006" in src
    assert 'state.intermediate_results["time_range"]' in src
    assert 'state.intermediate_results["start_date"]' in src


def test_resolving_twice_gives_the_same_window():
    """The property that makes it safe to call in the node AND in the lane. Verified rather
    than assumed, because the whole fix rests on it."""
    from orchestrator.agents.sql_agent import resolve_named_window

    q = "Compare energy use this week against last week."
    first = resolve_named_window(q, None, None)
    second = resolve_named_window(q, first[0], first[1])
    assert (first[0], first[1]) == (second[0], second[1])
    assert first[0] and first[1], "a named period must produce bounds at all"


def test_a_question_naming_no_period_is_left_alone():
    """`default_lookback` returns None/None, so the builders' own fallback still applies and
    nothing changes for the commonest question shape there is."""
    from orchestrator.agents.sql_agent import resolve_named_window

    start, end, window = resolve_named_window(
        "What is the temperature in room 5.01 right now?", None, None
    )
    assert start is None and end is None
    assert window.get("source") == "default_lookback"


def test_the_bus_carries_the_fields_the_window_actually_has():
    """`label` is not one of them. Writing `.get("label", "")` would put an empty string on
    every turn and look like a working disclosure — checked against the real dict rather than
    assumed from the sibling's shape."""
    from orchestrator.agents.sql_agent import resolve_named_window

    _, _, window = resolve_named_window("What was the energy use last month?", None, None)
    assert "label" not in window
    for key in ("source", "unit", "offsets"):
        assert key in window, key
    src = inspect.getsource(WorkflowOrchestrator._sql_node)
    assert '"unit": _w.get("unit", "")' in src


def test_the_write_back_fails_open():
    src = inspect.getsource(WorkflowOrchestrator._sql_node)
    block = src[src.index("CAVEAT-1006") :]
    assert "except Exception" in block
    assert "not written back to the bus" in block
