# -*- coding: utf-8 -*-
"""W6-02 — the turn's per-stage durations reach the caller, so a slow turn can be attributed.

Measured 2026-09-29, 48 requests over 12 register/metadata questions in 4 rounds with both
`resp_cache:*` and `cache:sparql*` flushed before every round. Median 4.46 s, p90 18.96 s,
slowest 74.77 s. Attributing that 74.77 s meant reading the orchestrator's container log,
and the container log CANNOT be attributed while more than one turn is in flight: the log
lines of one request close the gaps of another. The same 18,609-character narration prompt
was measured at 0.09 s, 0.44 s, 1.62 s and 57.80 s by that method, which is not a
measurement of anything.

The durations did not need to be invented. `_safe_node` has recorded `duration_ms` per lane
into `lane_outcomes` since V12-19; the trace that the response returns simply never carried
them, and the two stages that bracket every turn -- classification and narration -- were
registered bare and so were not recorded at all.

These tests pin the three things that made the number unusable before:
  * `dialogue` and `response` are TIMED, and timing them did not make them swallow errors;
  * the durations reach `plan_trace`, slowest first;
  * `response`'s own duration is in the payload, although the trace is assembled before the
    response node has returned.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow._orchestrator import (
    _stage_durations,
    build_plan_trace,
    plan_trace_for_response,
)

pytestmark = pytest.mark.unit


def _outcome(lane, ms, outcome="ok", first_pass=True):
    return {
        "lane": lane,
        "outcome": outcome,
        "detail": "",
        "first_pass": first_pass,
        "duration_ms": ms,
    }


# ── the durations reach the trace, slowest first ─────────────────────────────────────


def test_stage_durations_are_ordered_slowest_first():
    """The reader wants the top contributor, so it is the first row and not a row to find."""
    rows = _stage_durations(
        {
            "lane_outcomes": [
                _outcome("sparql", 120),
                _outcome("response", 57800),
                _outcome("sql", 900),
            ]
        }
    )
    assert [r["stage"] for r in rows] == ["response", "sql", "sparql"]
    assert [r["ms"] for r in rows] == [57800, 900, 120]


def test_plan_trace_carries_stage_ms():
    """`plan_trace` said WHICH stages ran and never how long any of them took."""
    trace = build_plan_trace(
        {
            "route_decision": {"intent_after_overrides": "metadata", "final_node": "sparql"},
            "lane_outcomes": [_outcome("dialogue", 300), _outcome("sparql", 4100)],
        }
    )
    assert [(r["stage"], r["ms"]) for r in trace["stage_ms"]] == [
        ("sparql", 4100),
        ("dialogue", 300),
    ]


def test_a_stage_that_ran_twice_is_two_rows_not_a_sum():
    """A retry summed into one row reports a recovered failure as a single slow call.

    V12-19 is explicit that re-deriving `first_pass` later is how that fold happens, so the
    flag is carried through from the record rather than recomputed here.
    """
    rows = _stage_durations(
        {
            "lane_outcomes": [
                _outcome("sql", 30000, "timeout", first_pass=True),
                _outcome("sql", 800, "ok", first_pass=False),
            ]
        }
    )
    assert len(rows) == 2
    assert [r["first_pass"] for r in rows] == [True, False]
    assert [r["outcome"] for r in rows] == ["timeout", "ok"]


def test_an_unrecorded_duration_is_absent_not_zero():
    """An unrecorded stage and an instant one are different claims; 0 ms would merge them."""
    rows = _stage_durations({"lane_outcomes": [_outcome("sparql", None), _outcome("sql", 5)]})
    assert rows[0]["stage"] == "sql" and rows[0]["ms"] == 5
    assert rows[1]["stage"] == "sparql" and rows[1]["ms"] is None


def test_stage_durations_survive_a_turn_that_recorded_nothing():
    """A turn that errored before any node ran must still produce a trace, not an exception."""
    assert _stage_durations({}) == []
    assert build_plan_trace({})["stage_ms"] == []


# ── the response node's own time reaches the payload ─────────────────────────────────


def test_response_stage_reaches_the_payload_although_the_trace_predates_it():
    """Narration is one of the two stages most worth attributing.

    The trace is assembled INSIDE the response node, so when it is built the response node
    has not returned and `lane_outcomes` has no entry for it. A trace that structurally
    could not contain narration would be the wrong instrument, so the payload re-reads the
    durations after the graph has finished.
    """
    results = {
        "route_decision": {"intent_after_overrides": "metadata", "final_node": "sparql"},
        "lane_outcomes": [_outcome("dialogue", 300), _outcome("sparql", 4100)],
    }
    results["plan_trace"] = build_plan_trace(results)
    assert "response" not in [r["stage"] for r in results["plan_trace"]["stage_ms"]]

    # ...the response node returns, and only now is its own duration recorded.
    results["lane_outcomes"].append(_outcome("response", 57800))

    payload = plan_trace_for_response(results)
    assert payload["stage_ms"][0] == {
        "stage": "response",
        "ms": 57800,
        "outcome": "ok",
        "first_pass": True,
    }
    # Nothing else about the trace may be rebuilt -- only that one field is refreshed.
    for field in ("kind", "intent", "final_node", "decision_source", "steps"):
        assert payload[field] == results["plan_trace"][field]


def test_plan_trace_for_response_passes_through_when_there_is_no_trace():
    """A turn that never built a trace must yield None, not a trace made of nothing."""
    assert plan_trace_for_response({}) is None
    assert plan_trace_for_response({"plan_trace": None}) is None


# ── timing the two bare stages did not change what they do on failure ────────────────


class _Recorder:
    """The smallest object `_timed_node` needs: it only calls the function and records."""

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as _W

    _timed_node = _W._timed_node


class _State:
    def __init__(self):
        self.intermediate_results = {}


async def test_a_timed_node_records_its_duration_and_returns_the_state():
    """Awaited directly rather than driven through `asyncio.get_event_loop()`.

    The first version of this test used `get_event_loop().run_until_complete(...)`. It
    passed alone and FAILED in a 307-test run with "There is no current event loop", because
    by then another test had closed the loop. A test that only passes when run by itself is
    not a regression test. pytest-asyncio is in auto mode here (`pytest.ini`), so an `async
    def` test is simply awaited.
    """
    state = _State()

    async def node(s):
        s.intermediate_results["ran"] = True
        return s

    out = await _Recorder()._timed_node(node, "dialogue")(state)
    assert out is state and state.intermediate_results["ran"] is True
    recorded = state.intermediate_results["lane_outcomes"]
    assert [e["lane"] for e in recorded] == ["dialogue"]
    assert recorded[0]["outcome"] == "ok"
    assert isinstance(recorded[0]["duration_ms"], int)


async def test_a_timed_node_RE_RAISES_where_safe_node_would_swallow():
    """This is the whole reason it is not `_safe_node`.

    `dialogue` and `response` are registered bare on purpose: swallowing an exception there
    hands the user a turn with no classification, or no answer, in place of an error. Timing
    them must not quietly convert those two stages to fail-open.
    """
    state = _State()

    async def node(_s):
        raise TimeoutError("backend gone")

    with pytest.raises(TimeoutError):
        await _Recorder()._timed_node(node, "response")(state)
    # ...and the failure was still recorded on the way past.
    recorded = state.intermediate_results["lane_outcomes"]
    assert [e["lane"] for e in recorded] == ["response"]
    assert recorded[0]["outcome"] != "ok"


def test_the_two_bracketing_stages_are_registered_through_the_timing_wrapper():
    """Registering either bare again would silently remove it from every attribution.

    Pinned against the graph source, because the defect this prevents is invisible at
    runtime: the turn still answers, the trace still lists its steps, and only the two
    largest durations quietly stop being reported.
    """
    from pathlib import Path

    src = Path("orchestrator/workflow/_graph.py").read_text(encoding="utf-8")
    assert 'workflow.add_node("dialogue", self._timed_node(self._dialogue_node, "dialogue"))' in src
    assert 'workflow.add_node("response", self._timed_node(self._response_node, "response"))' in src


# ── the endpoint the deployment actually uses must carry it too ──────────────────────


def test_the_v1_endpoint_publishes_the_stage_timings():
    """`/v1` is what Open WebUI calls, and it was the endpoint that could not be attributed.

    Measured 2026-09-29: a `/v1` body carried `ontosage_intent` and `ontosage_route` -- the
    lane, and the rules that chose it -- and nothing at all about what the turn cost. So the
    one endpoint whose latency a user actually experiences was the one whose latency could
    only be guessed at from the container log, which is the method that produced 0.09 s and
    57.80 s for the same call.

    Pinned against the source because the failure is silent: the turn still answers, the
    route record is still there, and only the timings quietly stop being published.
    """
    from pathlib import Path

    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    # Every site that emits `ontosage_route` must emit the trace beside it.
    assert src.count('"ontosage_route"') == src.count('"ontosage_plan_trace"')
    # The timed-out body reports None rather than an empty list: a turn that timed out did
    # not spend zero time in every stage, it recorded nowhere that it spent it.
    assert '"ontosage_plan_trace": None,' in src
