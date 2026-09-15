# -*- coding: utf-8 -*-
"""V12-19 — timeout, outage and defect are three facts, and were one (review B15).

    B15  "An injected lane timeout, backend outage and delayed completion each produce an
          explicit partial or failure outcome; first-pass and retry status remain
          separately reportable everywhere a number is published."

WHAT `_safe_node` USED TO RECORD
---------------------------------
    except Exception as e:
        logger.error(f"Node '{node_name}' failed: {e}", exc_info=True)
        state.intermediate_results[f"{node_name}_error"] = str(e)

One catch, one string, three different events. Worse: `str(e)` on a message-less exception
— `httpx.ReadTimeout`, `asyncio.TimeoutError`, a bare `Exception()` — is the EMPTY STRING,
so the record was not merely untyped but blank. That is CAVEAT-415 from the other end: 62
warnings in six hours that said nothing, 52 of them the capability lane abandoning the
ontology on a SPARQL timeout — roughly 11% of capability answers leaving the TTL-first path
with no record of why.

WHY TIMEOUT IS ITS OWN TYPE AND NOT A KIND OF FAILURE
-------------------------------------------------------
CAVEAT-500: the same question measured 10.7 s, 61.1 s and 13.3 s on three consecutive asks,
every answer correct, once past a 121 s client timeout. A timeout here is frequently
LATENCY. Folding it in with a real failure makes a probe run unreadable in both directions —
the defect hides among the slow cases, and the slow case is reported as broken.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.turn_outcome import (  # noqa: E402
    LaneOutcome,
    Outcome,
    TurnOutcome,
    classify,
    from_state,
)
from shared.utils import describe_exception, get_logger  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── the three injected conditions B15 names ──────────────────────────────────


class ReadTimeout(Exception):
    """Stands in for httpx.ReadTimeout.

    Named EXACTLY as the real class is. `classify` matches on the class name so that this
    module imports no transport — a classifier that imported httpx to recognise an httpx
    error would depend on the thing it classifies. The first version of this test called it
    `_ReadTimeout` and failed, which is the contract working: a near-miss name is a near-miss
    name.
    """


class ConnectError(Exception):
    """Stands in for httpx.ConnectError."""


def test_an_injected_lane_timeout_is_typed_as_a_timeout():
    assert classify(asyncio.TimeoutError()) is Outcome.TIMEOUT
    assert classify(ReadTimeout()) is Outcome.TIMEOUT
    assert classify(TimeoutError()) is Outcome.TIMEOUT


def test_an_injected_backend_outage_is_typed_as_unavailable():
    assert classify(ConnectError()) is Outcome.BACKEND_UNAVAILABLE
    assert classify(ConnectionRefusedError()) is Outcome.BACKEND_UNAVAILABLE


def test_an_ordinary_defect_is_typed_as_a_failure():
    assert classify(ValueError("bad column")) is Outcome.FAILED
    assert classify(KeyError("uuid")) is Outcome.FAILED


def test_a_timeout_wrapped_by_a_helper_is_still_a_timeout():
    """The wrapper is the arbitrary thing, so the cause chain is walked. A RuntimeError
    around a ReadTimeout is a slow store, not a broken one."""
    try:
        try:
            raise asyncio.TimeoutError()
        except asyncio.TimeoutError as inner:
            raise RuntimeError("fetch helper gave up") from inner
    except RuntimeError as e:
        assert classify(e) is Outcome.TIMEOUT


def test_the_cause_walk_terminates_on_a_cycle():
    """A self-referencing __context__ must not hang the classifier."""
    a = ValueError("a")
    b = ValueError("b")
    a.__context__ = b
    b.__context__ = a
    assert classify(a) is Outcome.FAILED


# ── first pass is carried, not re-derived ────────────────────────────────────


def test_a_turn_that_recovered_on_retry_is_ok_and_not_first_pass_ok():
    """The distinction the review is explicit about. A retry that succeeds is still a
    first-pass failure, and every place that re-derived this has folded it into a total."""
    turn = TurnOutcome()
    turn.record(LaneOutcome("sql", Outcome.TIMEOUT, first_pass=True))
    turn.record(LaneOutcome("sql", Outcome.OK, first_pass=False))

    assert turn.first_pass_ok is False
    assert turn.retried == ["sql"]


def test_a_clean_turn_is_both():
    turn = TurnOutcome()
    turn.record(LaneOutcome("sparql", Outcome.OK))
    turn.record(LaneOutcome("sql", Outcome.OK))
    assert turn.outcome is Outcome.OK
    assert turn.first_pass_ok is True
    assert turn.note() == ""


def test_a_defect_outranks_a_timeout_in_the_roll_up():
    """Reporting the timeout would send the reader to re-ask a question that will fail the
    same way. The reproducible fact is the more actionable one."""
    turn = TurnOutcome()
    turn.record(LaneOutcome("sql", Outcome.TIMEOUT))
    turn.record(LaneOutcome("analytics", Outcome.FAILED))
    assert turn.outcome is Outcome.FAILED


def test_each_kind_has_exactly_one_authorised_wording():
    """A taxonomy the reader cannot perceive has achieved nothing, and two wordings for one
    state is how a reader learns to ignore both."""
    seen = set()
    for kind in (Outcome.TIMEOUT, Outcome.BACKEND_UNAVAILABLE, Outcome.FAILED, Outcome.PARTIAL):
        turn = TurnOutcome()
        turn.record(LaneOutcome("x", kind))
        note = turn.note()
        assert note, f"{kind} has no wording"
        assert note not in seen, f"{kind} reuses another state's wording"
        seen.add(note)


def test_the_timeout_wording_does_not_say_the_data_is_missing():
    """CAVEAT-500 again: the data is probably there. Saying otherwise turns a latency
    problem into a false statement about the building."""
    turn = TurnOutcome()
    turn.record(LaneOutcome("sql", Outcome.TIMEOUT))
    note = turn.note().lower()
    assert "may well be there" in note
    assert "no data" not in note and "does not exist" not in note


def test_a_turn_outcome_survives_the_round_trip_through_the_bus():
    turn = TurnOutcome()
    turn.record(LaneOutcome("sql", Outcome.TIMEOUT, detail="ReadTimeout (no message)"))
    turn.record(LaneOutcome("sql", Outcome.OK, first_pass=False))

    rebuilt = from_state({"lane_outcomes": [lo.as_dict() for lo in turn.lanes]})
    assert rebuilt.as_dict() == turn.as_dict()


def test_an_unknown_outcome_value_on_the_bus_is_skipped_not_guessed():
    rebuilt = from_state({"lane_outcomes": [{"lane": "x", "outcome": "invented"}]})
    assert rebuilt.lanes == []


def test_an_empty_bus_is_a_clean_turn():
    assert from_state({}).outcome is Outcome.OK
    assert from_state(None).first_pass_ok is True


# ── the empty message, closed at the logger rather than at 871 call sites ────


def test_a_message_less_exception_cannot_produce_a_silent_warning():
    """`describe_exception` fixes a call site. There are 871 bare `{e}` interpolations, and
    this closes all of them plus every one not yet written."""
    buf = logging.StreamHandler()
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    log = get_logger("test_v12_19_probe")
    cap = _Capture()
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    try:
        for exc in (asyncio.TimeoutError(), Exception()):
            log.warning(f"[capability_graph] amenity fetch failed, deferring to KB: {exc}")
        log.warning("a warning with real content")
    finally:
        log.removeHandler(cap)
        buf.close()

    assert len(records) == 3
    for silent in records[:2]:
        assert "NO DETAIL" in silent
        assert "describe_exception" in silent
    assert "NO DETAIL" not in records[2], "a normal warning was annotated"


def test_the_filter_leaves_debug_alone():
    """An empty debug line costs nothing, and filtering every record would not be free."""
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    log = get_logger("test_v12_19_debug")
    cap = _Capture()
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    try:
        log.debug("something ended in a colon: ")
    finally:
        log.removeHandler(cap)
    assert records == ["something ended in a colon: "]


def test_describe_exception_still_names_the_class():
    assert describe_exception(asyncio.TimeoutError()) == "TimeoutError (no message)"
    assert describe_exception(ValueError("bad")) == "ValueError: bad"


# ── the step nobody remembers ────────────────────────────────────────────────


def test_the_safe_node_records_a_typed_outcome_for_success_and_failure():
    """Successes too. Without the denominator, "3 lanes timed out" cannot be told apart
    from "3 of 3" and "3 of 40"."""
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._safe_node)
    assert "_record_lane_outcome" in src
    assert "_Outcome.OK" in src, "only failures are recorded, so there is no denominator"
    assert "_classify_failure" in src, "the failure is still recorded untyped"
    # The ASSIGNMENT, not the word: the wrapper's own comment explains why `str(e)` was
    # wrong, and a substring check on the source flagged the explanation. A guard that
    # fires on its own rationale is the measurement being wrong again.
    for sink in ('= str(e)', '"error": str(e)', "{str(e)}"):
        assert sink not in src, (
            f"a message-less exception still stringifies to nothing via {sink!r}"
        )


def test_first_pass_is_decided_where_the_outcome_is_recorded():
    """Not reconstructed by whoever publishes a number — that is how a recovered retry ends
    up inside a success total."""
    import inspect

    from orchestrator.workflow import _orchestrator as wf

    src = inspect.getsource(wf._record_lane_outcome)
    assert '"first_pass": first' in src
    assert 'e.get("lane") == lane' in src, "first_pass is not derived from a prior attempt"


def test_the_outcome_reaches_the_response_and_is_cleared_between_turns():
    src = (REPO / "orchestrator" / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    assert "turn_outcome" in src

    call_at = src.index("_turn_from_state(")
    append_at = src.index('role="assistant"')
    assert call_at < append_at, "the outcome is added after the answer is transcribed"

    from orchestrator.workflow._orchestrator import _PER_TURN_LANE_KEYS

    assert "lane_outcomes" in _PER_TURN_LANE_KEYS
    assert "turn_outcome" in _PER_TURN_LANE_KEYS


def test_the_probe_still_reports_first_pass_separately():
    """"Everywhere a number is published" includes the probe, which is where the review's
    rule came from."""
    src = (REPO / "scripts" / "regression_probe.py").read_text(encoding="utf-8")
    assert "first-pass" in src.lower()
    assert "no retries" in src.lower() or "asked once" in src.lower()
