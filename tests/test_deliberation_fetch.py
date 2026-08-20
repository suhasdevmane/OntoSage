"""V4-T18 tests — per-candidate fetch with per-UUID limits (offline, fake adapters)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from orchestrator.services.deliberation.candidates import Candidate
from orchestrator.services.deliberation.fetch import fetch_series

pytestmark = pytest.mark.unit


@dataclass
class FakeResult:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class FakeAdapter:
    def __init__(self, data, fail=False):
        self._data = data
        self._fail = fail
        self.queries: List[str] = []
        self.limits: List[int] = []

    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        self.limits.append(limit)
        return f"SELECT ... {','.join(uuids)} LIMIT_PER_UUID {limit}"

    async def execute_query(self, sql):
        self.queries.append(sql)
        if self._fail:
            return FakeResult(success=False, error="boom")
        return FakeResult(data=self._data)


def _cand(local, uuid_, table="noise_data", modality="noise"):
    return Candidate(
        space_iri=f"ns#{local}",
        label=local,
        floor="floor0",
        sensors={modality: {"uuid": uuid_, "stored_at": table}},
    )


def _run(coro):
    return asyncio.run(coro)


def test_groups_by_table_and_orders_series():
    noise = FakeAdapter(
        [
            {"timestamp": "2026-08-13 10:00:00", "uuid": "u1", "value": 40.0},
            {"timestamp": "2026-08-13 09:00:00", "uuid": "u1", "value": 38.0},
            {"timestamp": "2026-08-13 10:00:00", "uuid": "u2", "value": 35.0},
        ]
    )
    out = _run(
        fetch_series(
            [_cand("A", "u1"), _cand("B", "u2")],
            ["noise"],
            adapter_getter=lambda table: noise,
        )
    )
    assert len(noise.queries) == 1  # ONE query covers both uuids
    assert [v for _, v in out["u1"]] == [38.0, 40.0]  # newest-last
    assert out["u2"] == [("2026-08-13 10:00:00", 35.0)]


def test_per_uuid_limit_passed_through():
    a = FakeAdapter([])
    _run(
        fetch_series([_cand("A", "u1")], ["noise"], per_uuid_limit=144, adapter_getter=lambda t: a)
    )
    assert a.limits == [144]


def test_failed_table_yields_no_rows_never_raises():
    bad = FakeAdapter([], fail=True)
    out = _run(fetch_series([_cand("A", "u1")], ["noise"], adapter_getter=lambda t: bad))
    assert out == {}


def test_missing_adapter_or_modality_skipped():
    out = _run(fetch_series([_cand("A", "u1")], ["co2"], adapter_getter=lambda t: None))
    assert out == {}  # candidate has no co2 handle; and no adapter anyway


def test_non_numeric_values_dropped():
    a = FakeAdapter(
        [
            {"timestamp": "t1", "uuid": "u1", "value": "not-a-number"},
            {"timestamp": "t2", "uuid": "u1", "value": 41.5},
        ]
    )
    out = _run(fetch_series([_cand("A", "u1")], ["noise"], adapter_getter=lambda t: a))
    assert out["u1"] == [("t2", 41.5)]
