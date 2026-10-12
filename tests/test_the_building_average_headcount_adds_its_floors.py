"""The building's average headcount over a period is the SUM of its floor counters' means.

2026-10-11 (r7 pool): "What was the average occupancy of the building this week?" had no lane that
computed it; the narration gave per-floor figures and the relevance gate deleted them. A mean over
the floor counters would be people PER FLOOR labelled as the building (BUG-1464's shape).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import aggregate_lane as al

pytestmark = pytest.mark.unit


def test_the_claim_is_a_building_mean_of_a_headcount_over_a_named_period():
    q = "What was the average occupancy of the building this week?"
    assert al.wants_lane(q, 6, False, True, ["count"], headcount=True).stat == "mean"


def test_the_figure_is_the_sum_of_the_floor_means(monkeypatch):
    facts = {
        "f0": SimpleNamespace(floor="0", on_floor=True),
        "f1": SimpleNamespace(floor="1", on_floor=True),
        "r1": SimpleNamespace(floor="1", on_floor=False),  # a room counter is not added
    }

    async def ready(uuids, storage_map, adapter_for, store_key):
        return {"s": (object(), list(uuids))}, []

    async def run(adapter, members, window, limit, bands):
        means = {"f0": (100.0, 10), "f1": (300.0, 10)}
        return [al.SensorAgg(uuid=u, n=means[u][1], total=means[u][0]) for u in members], []

    monkeypatch.setattr(al, "_stores_ready", ready)
    monkeypatch.setattr(al, "run_aggregates", run)
    intent = al.AggregateIntent("mean", "building", True, False, False, ())
    window = al.Window("2026-10-04 23:00:00", "2026-10-11 22:59:59", "this week")
    out = asyncio.run(al._answer_headcount_mean(intent, list(facts), {}, facts, window, None, None))
    assert out["figures"]["building mean"] == pytest.approx(40.0)  # 10 + 30, not their mean 20
    assert "On average about 40 people were in the building" in out["formatted_response"]
