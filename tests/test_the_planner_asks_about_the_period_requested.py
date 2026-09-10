# -*- coding: utf-8 -*-
"""A planned report described the wrong day (BUG-478).

MEASURED 2026-09-07, live, on "Give me a report on the CO2 in room 5.01 yesterday."

`PlannerAgent._run_sql` called:

    await SQLAgent().fetch_data_for_uuids(uuids, query, storage_map)

`fetch_data_for_uuids` takes `start_date` and `end_date` after `storage_map`, and the
planner passed neither. It fell back to its default window:

    WHERE `a66ca165-...` IS NOT NULL AND `datetime` >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    ORDER BY `datetime` DESC LIMIT 1000
    Sample row: {'timestamp': '2026-09-07T17:00:23', 'value': 913}

The sample row is from the afternoon the question was asked. The report came back headed
"Room 5.01 – Yesterday" and described today.

WHAT IT REPORTED vs WHAT WAS TRUE
---------------------------------
    reported:  1,000 readings, avg 993.81 ppm, min 817, max 1,112
    yesterday:  2,874 readings, avg 781.01 ppm, min 461, max 1,102

Every figure was real and measured. Every one was about the wrong period — and the
reported maximum EXCEEDS yesterday's actual maximum, which is the only reason it was
catchable at all. This is harder to spot than a fabrication: there is no tell in the
prose, the numbers are internally consistent, and the header says the right day.

The main workflow's SQL lane has always passed these dates (`_orchestrator.py`, the
`fetch_data_for_uuids` call). Only the planner-driven lane dropped them, so the defect
appeared exactly on multi-step questions — reports, comparisons, trends — which are the
ones where the period matters most.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.planner_agent import PlannerAgent  # noqa: E402


class _State:
    def __init__(self, **ir):
        self.intermediate_results = dict(ir)


def _call_run_sql(monkeypatch, state, uuids):
    """Capture the arguments `_run_sql` actually forwards."""
    captured = {}

    class _FakeSQLAgent:
        async def fetch_data_for_uuids(self, uuids, query, storage_map=None, *args, **kwargs):
            captured["uuids"] = uuids
            captured["positional"] = args
            captured["kwargs"] = kwargs
            return {"success": True, "results": {"data": []}}

        async def generate_and_execute(self, state, query):
            captured["fallback"] = True
            return {"success": True, "results": {"data": []}}

    import orchestrator.agents.sql_agent as sql_mod

    monkeypatch.setattr(sql_mod, "SQLAgent", _FakeSQLAgent)
    asyncio.run(PlannerAgent()._run_sql(state, "q", uuids, {}, {}))
    return captured


def test_the_requested_period_reaches_the_query(monkeypatch):
    state = _State(start_date="2026-09-06 00:00:00", end_date="2026-09-06 23:59:59")
    captured = _call_run_sql(monkeypatch, state, ["uuid-1"])
    forwarded = list(captured["positional"]) + list(captured["kwargs"].values())
    assert "2026-09-06 00:00:00" in forwarded, (
        "the planner still drops the start date, so a report about a named day describes "
        "whatever the default window returns"
    )
    assert "2026-09-06 23:59:59" in forwarded


def test_no_period_forwards_nothing_rather_than_inventing_one(monkeypatch):
    """An absent window must stay absent — the SQL lane's own default is then correct."""
    captured = _call_run_sql(monkeypatch, _State(), ["uuid-1"])
    forwarded = [a for a in captured["positional"] if a] + [
        v for v in captured["kwargs"].values() if v
    ]
    assert not [f for f in forwarded if isinstance(f, str)]


def test_the_uuid_path_is_still_preferred_over_letting_the_llm_guess(monkeypatch):
    captured = _call_run_sql(monkeypatch, _State(), ["uuid-1"])
    assert "fallback" not in captured


def test_no_uuids_still_falls_back(monkeypatch):
    captured = _call_run_sql(monkeypatch, _State(), [])
    assert captured.get("fallback") is True


def test_the_two_lanes_pass_the_same_things():
    """The main workflow lane and the planner lane must not drift apart again.

    They call the same function for the same purpose; one of them having a shorter
    argument list is what produced a report about the wrong day.
    """
    from orchestrator.workflow import _orchestrator

    planner_src = inspect.getsource(PlannerAgent._run_sql)
    workflow_src = inspect.getsource(_orchestrator)
    for arg in ("start_date", "end_date", "sensor_metadata"):
        assert arg in planner_src, f"the planner lane no longer forwards {arg}"
        assert arg in workflow_src
