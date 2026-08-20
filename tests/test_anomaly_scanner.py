# -*- coding: utf-8 -*-
"""V5-T19: anomaly scanner — detection composition, episode merge, complaint join."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from orchestrator.services.anomaly.scanner import AnomalyScanner, join_complaints
from orchestrator.services.deliberation.candidates import Candidate

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 3, 0, 0, 0)
NOW = T0 + timedelta(days=3)


class _FakeCursor:
    def __init__(self, select_rows):
        self.select_rows = select_rows
        self.executed = []
        self.rowcount = 1
        self._last_select = None

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip().split()[0].upper(), sql, params))
        if sql.strip().upper().startswith("SELECT"):
            self._last_select = self.select_rows.pop(0) if self.select_rows else None

    async def fetchone(self):
        return self._last_select

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, cursor):
        self._conn = _FakeConn(cursor)

    def acquire(self):
        return self._conn


class _FakeEventsAdapter:
    def __init__(self, cursor):
        self._pool = _FakePool(cursor)

    async def _ensure_pool(self):
        return self._pool


def _scanner(cursor):
    return AnomalyScanner(
        "tb",
        "http://example.org/tb#",
        sparql_exec=None,
        adapter_getter=lambda key: (
            _FakeEventsAdapter(cursor) if key == "bldg:events_data" else None
        ),
    )


def _stuck_series():
    out = []
    for i in range(72):
        ts = T0 + timedelta(hours=i)
        v = 800.0 if 9 <= ts.hour < 18 else 420.0
        out.append((ts, v))
    freeze_from = out[-1][0] - timedelta(hours=10)
    return [(t, 613.0) if t >= freeze_from else (t, v) for t, v in out]


def test_detect_composes_per_point_and_pair_detectors():
    candidates = [
        Candidate(
            space_iri="s#A",
            label="A",
            floor="f0",
            sensors={
                "co2": {"uuid": "u-co2", "stored_at": "t"},
                "occupancy": {"uuid": "u-occ", "stored_at": "t"},
            },
        )
    ]
    # occupancy zero while co2 climbs — plus the co2 series itself is fine
    occ = [(T0 + timedelta(minutes=10 * i), 0.0) for i in range(48)]
    co2 = [(T0 + timedelta(minutes=10 * i), 420.0 + 8.0 * i) for i in range(48)]
    scanner = _scanner(_FakeCursor([]))
    findings = scanner._detect(candidates, {"u-occ": occ, "u-co2": co2})
    assert any(f.detector == "cross_modality" for f in findings)


def test_persist_inserts_then_extends_with_stable_id():
    from orchestrator.services.anomaly.detectors import stuck

    findings = stuck(_stuck_series(), "u-1", "co2")
    assert findings

    # first scan: no existing episode → INSERT
    cur1 = _FakeCursor(select_rows=[None])
    asyncio.run(_scanner(cur1).persist(findings, NOW))
    kinds1 = [k for k, _, _ in cur1.executed]
    assert kinds1 == ["SELECT", "INSERT"]
    insert_params = cur1.executed[1][2]
    episode_id = insert_params[0]

    # second scan: same episode still present → UPDATE the same row, no new id
    cur2 = _FakeCursor(select_rows=[(episode_id, findings[0].end)])
    asyncio.run(_scanner(cur2).persist(findings, NOW))
    kinds2 = [k for k, _, _ in cur2.executed]
    assert kinds2 == ["SELECT", "UPDATE"]
    assert cur2.executed[1][2][-1] == episode_id  # WHERE event_id = the ORIGINAL id


def test_persist_marks_stale_episodes_done():
    from orchestrator.services.anomaly.detectors import stuck

    findings = stuck(_stuck_series(), "u-1", "co2")
    cur = _FakeCursor(select_rows=[None])
    asyncio.run(_scanner(cur).persist(findings, NOW + timedelta(days=2)))
    params = cur.executed[1][2]
    assert params[5] == "done"  # status column
    attrs = json.loads(params[6])
    assert attrs["detector"] == "stuck" and attrs["severity"] in ("low", "medium", "high")


def test_join_complaints_matches_by_time_overlap():
    anomalies = [
        {
            "start_dt": NOW - timedelta(hours=5),
            "end_dt": NOW - timedelta(hours=1),
            "event_type": "anomaly:stuck",
        }
    ]
    complaints = [
        {"id": 1, "created_at": NOW - timedelta(hours=3)},  # inside episode
        {"id": 2, "created_at": NOW - timedelta(days=6)},  # long before
    ]
    joined = join_complaints(anomalies, complaints)
    assert joined[0]["anomalies"] and not joined[0]["data_looks_fine"]
    assert not joined[1]["anomalies"] and joined[1]["data_looks_fine"]
