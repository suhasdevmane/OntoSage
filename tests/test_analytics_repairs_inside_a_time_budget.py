# -*- coding: utf-8 -*-
"""The analytics lane could spend the whole turn repairing and say nothing (CAVEAT-467).

MEASURED on "Compare average CO2 on floor 1 versus floor 3 over the last week":

    63s   answered
    87s   answered
    109s  answered
    420s  WORKFLOW TIMED OUT — the user got nothing at all

Same question, same build, same data. The variance is entirely in how many times the
generated Python failed and had to be repaired: each repair is a full LLM call on the
local model, roughly a minute, and the loop had no idea what time it was. On the run that
died there were six minutes between the code executor returning and the deadline, with no
log line in between — the lane could not be told apart from a hang.

WHAT THE BOUND IS FOR
---------------------
Not speed. Spending the last of the request budget on one more repair trades a partial
answer for a total loss: the rows were already fetched, the failure was already known, and
the turn could have said so. Stopping early leaves the narration step its share.

WHY IT IS DERIVED
-----------------
From `WORKFLOW_TIMEOUT_S`, never written down separately. Two deadlines in two files that
cannot see each other is exactly BUG-473 — `LLM_TIMEOUT_S=180` against a workflow allowed
120s, where one legal LLM call outlived the whole request containing it. A budget for
"don't eat the request's time" has to be a fraction of the request's time.

WHAT WAS NOT DONE
-----------------
The real fix for the latency is a deterministic path for common aggregates, so a question
like this never needs generated Python at all. `config/recipes.yaml` already holds 41
recipes including `co2_average`, and they are injected into the code prompt as TEXT rather
than executed — the LLM still writes the loop. That is a change to the lane that answers
most data questions, and it is not a thing to land hours before a demo.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents import analytics_agent as _aa  # noqa: E402
from orchestrator.agents.analytics_agent import AnalyticsAgent  # noqa: E402

# `analytics_agent` binds `settings` at import time, and `tests/test_strict_secrets.py`
# reloads `shared.config` mid-session, so `shared.config.settings` becomes a DIFFERENT
# object while this agent keeps the original (lesson #159). Every read and patch of a
# setting in this file therefore goes through `_aa.settings` — the object the code under
# test actually reads, whatever the suite order.


def _agent_that_always_fails(monkeypatch, elapsed_per_attempt: float):
    """An agent whose code never runs, with each attempt costing `elapsed_per_attempt`."""
    agent = AnalyticsAgent()
    clock = {"t": 1000.0}
    calls = {"execute": 0, "fix": 0}

    # The lane does `import time as _t` inside the function, so `_t` IS the stdlib
    # module — patch it there rather than looking for a module-level attribute that
    # does not exist.
    import time as _time_mod

    monkeypatch.setattr(_time_mod, "time", lambda: clock["t"])

    async def _execute(code, data):
        calls["execute"] += 1
        clock["t"] += elapsed_per_attempt
        return {"success": False, "error": "boom"}

    async def _fix(code, error, user_query, sensor_metadata, data_filename):
        calls["fix"] += 1
        return code

    monkeypatch.setattr(agent, "_execute_code", _execute)
    monkeypatch.setattr(agent, "_fix_code", _fix)
    return agent, calls


def _run(agent):
    return asyncio.run(agent._execute_with_retries("code", {}, "q", {}, "f.json"))


def test_a_fast_failure_still_uses_every_attempt(monkeypatch):
    """The bound must not cost an answer that repairs would have found."""
    agent, calls = _agent_that_always_fails(monkeypatch, elapsed_per_attempt=1.0)
    res = _run(agent)
    assert res["success"] is False
    assert calls["execute"] == agent.max_retries
    assert not res.get("gave_up_early")


def test_slow_repairs_stop_before_the_turn_runs_out(monkeypatch):
    """One more attempt here is a total loss instead of a partial answer."""
    budget = AnalyticsAgent._repair_budget_s()
    agent, calls = _agent_that_always_fails(monkeypatch, elapsed_per_attempt=budget)
    res = _run(agent)
    assert res.get("gave_up_early") is True
    assert (
        calls["execute"] < agent.max_retries
    ), f"the lane still used all {agent.max_retries} attempts at {budget:.0f}s each"


def test_giving_up_early_still_reports_the_real_error(monkeypatch):
    """A bound that hides why it failed just moves the silence."""
    agent, _ = _agent_that_always_fails(monkeypatch, AnalyticsAgent._repair_budget_s())
    assert _run(agent)["error"] == "boom"


def test_the_budget_is_derived_from_the_workflow_deadline():
    """Two deadlines in two files that cannot see each other is BUG-473."""
    src = inspect.getsource(AnalyticsAgent._repair_budget_s)
    assert "WORKFLOW_TIMEOUT_S" in src
    assert AnalyticsAgent._repair_budget_s() > 0


def test_the_budget_leaves_room_for_the_rest_of_the_turn():
    total = float(_aa.settings.WORKFLOW_TIMEOUT_S)
    assert AnalyticsAgent._repair_budget_s() < total, (
        "the repair budget is the whole request budget, so the lane can still consume the "
        "turn and leave nothing for the answer"
    )


@pytest.mark.parametrize("missing", [0, None, "", "not-a-number", -30])
def test_a_missing_deadline_does_not_remove_the_bound(monkeypatch, missing):
    """An unset or garbled setting must not silently mean 'unlimited'.

    ``> 0`` was the assertion here, and it holds at the REAL WORKFLOW_TIMEOUT_S too — so
    when the patch stopped reaching this agent (lesson #159) nothing went red and the test
    went on proving nothing. Pinning the documented fallback instead means a detached patch
    fails: the derived budget is half of a live deadline and is never 120.0 by accident.
    """
    monkeypatch.setattr(_aa.settings, "WORKFLOW_TIMEOUT_S", missing, raising=False)
    assert AnalyticsAgent._repair_budget_s() == 120.0


def test_a_present_deadline_is_halved_not_ignored(monkeypatch):
    """The other half of the bound: it is DERIVED, so it has to move with the deadline."""
    monkeypatch.setattr(_aa.settings, "WORKFLOW_TIMEOUT_S", 300, raising=False)
    assert AnalyticsAgent._repair_budget_s() == 150.0
    monkeypatch.setattr(_aa.settings, "WORKFLOW_TIMEOUT_S", 400, raising=False)
    assert AnalyticsAgent._repair_budget_s() == 200.0


def test_it_says_why_it_stopped():
    """Silence is what made the 420s run indistinguishable from a hang."""
    src = inspect.getsource(AnalyticsAgent._execute_with_retries)
    assert "stopping repairs" in src
    assert "budget" in src


def test_nothing_here_names_a_building():
    body = inspect.getsource(AnalyticsAgent._repair_budget_s).split('"""')[-1].lower()
    for literal in ("bldg1", "bldg2", "abacws"):
        assert literal not in body
