# -*- coding: utf-8 -*-
"""The actuation audit trail can be read back (2026-08-27).

``SimDriver.set_point()`` has written a row to ``actuation_log`` for every
approved setpoint change since T23 — who asked, which point, what value, why,
when — and bldg1 ships with ``actuation.driver: sim`` and three writable points,
so the path is live on the shipped building. Nothing ever read a row back.
"What did you change today?" and "who approved that?" were unanswerable about
actions this system had itself recorded.

Sixth instance of the same pattern: a capability present, correct, tested, and
uninvoked. Found mechanically by ``scripts/audit_unread_stores.py`` rather than
by noticing — which is the point, because the previous five were not noticed for
months.
"""

from datetime import datetime

import pytest

from orchestrator.services.actuation.audit_log import (
    _MAX_LIMIT,
    format_actions,
    read_actuation_log,
)

pytestmark = pytest.mark.unit


class _FakeConn:
    def __init__(self, rows, raises=None):
        self._rows = rows
        self._raises = raises
        self.calls = []

    async def fetch(self, sql, *args):
        if self._raises:
            raise self._raises
        self.calls.append((sql, args))
        return self._rows


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


class _FakePG:
    def __init__(self, pool):
        self.pool = pool


def _row(**kw):
    base = {
        "audit_id": "a-1",
        "building_id": "bldg1",
        "user_id": "alice",
        "point_uri": "urn:bldg1:VAV-501-SP",
        "value": "21.5",
        "reason": "too cold in 5.01",
        "status": "sim_ok",
        "created_at": datetime(2026, 8, 27, 9, 30),
    }
    base.update(kw)
    return base


# ── reading ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recorded_actions_come_back():
    conn = _FakeConn([_row(), _row(audit_id="a-2", point_uri="urn:bldg1:AHU-F5-SP")])
    out = await read_actuation_log("bldg1", postgres_manager=_FakePG(_FakePool(conn)))
    assert out["ok"] and out["count"] == 2
    assert out["actions"][0]["point_uri"] == "urn:bldg1:VAV-501-SP"
    assert out["actions"][0]["created_at"] == "2026-08-27T09:30:00"


@pytest.mark.asyncio
async def test_the_query_is_scoped_to_one_building():
    """Cross-building leakage in an audit trail would be a privacy defect, not a
    tidiness one."""
    conn = _FakeConn([])
    await read_actuation_log("bldg2", postgres_manager=_FakePG(_FakePool(conn)))
    sql, args = conn.calls[0]
    assert "WHERE building_id = $1" in sql
    assert args[0] == "bldg2"


@pytest.mark.asyncio
async def test_the_limit_is_capped():
    """An audit trail grows without limit; an unbounded read is a memory event."""
    conn = _FakeConn([])
    await read_actuation_log("bldg1", postgres_manager=_FakePG(_FakePool(conn)), limit=99999)
    assert conn.calls[0][1][-1] == _MAX_LIMIT


@pytest.mark.asyncio
async def test_a_time_window_uses_the_windowed_query():
    conn = _FakeConn([])
    await read_actuation_log("bldg1", postgres_manager=_FakePG(_FakePool(conn)), since_hours=24)
    assert "interval" in conn.calls[0][0]


# ── the states that are not errors ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_building_that_has_never_actuated_reports_zero_not_failure():
    """The table is created on first use, so its absence means nothing has been
    actuated — which is an answer, not a fault."""
    conn = _FakeConn([], raises=Exception('relation "actuation_log" does not exist'))
    out = await read_actuation_log("bldg3", postgres_manager=_FakePG(_FakePool(conn)))
    assert out["ok"] and out["count"] == 0


@pytest.mark.asyncio
async def test_no_database_is_reported_as_unreadable_not_as_empty():
    """'Nothing was changed' and 'I cannot see whether anything was changed' are
    different answers, and only one of them is safe to give about an audit trail."""
    out = await read_actuation_log("bldg1", postgres_manager=None)
    assert out["ok"] is False and "cannot be read" in out["error"]


@pytest.mark.asyncio
async def test_an_unexpected_database_error_is_surfaced():
    conn = _FakeConn([], raises=Exception("connection reset"))
    out = await read_actuation_log("bldg1", postgres_manager=_FakePG(_FakePool(conn)))
    assert out["ok"] is False and "connection reset" in out["error"]


# ── rendering ───────────────────────────────────────────────────────────────
def test_the_rendering_names_who_did_what_and_why():
    text = format_actions({"ok": True, "actions": [_row()], "count": 1})
    for expected in ("VAV-501-SP", "21.5", "alice", "too cold in 5.01"):
        assert expected in text


def test_an_empty_trail_says_so_plainly():
    text = format_actions({"ok": True, "actions": [], "window_hours": 24})
    assert "No control actions" in text and "24" in text


def test_a_truncated_list_says_what_it_cut():
    text = format_actions({"ok": True, "actions": [_row() for _ in range(15)]}, max_lines=10)
    assert "5 more" in text
    assert "15 control action(s)" in text


def test_an_unreadable_trail_does_not_render_as_an_empty_one():
    text = format_actions({"ok": False, "error": "connection reset"})
    assert "could not be read" in text and "connection reset" in text


# ── and the reader is actually reachable ────────────────────────────────────
def test_the_endpoint_exists_and_is_admin_gated():
    """An audit trail is accountability surface. It is also the sixth capability
    in this codebase to be written and never read, so 'exists' is not enough —
    something must call it."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    idx = src.index('"/api/v1/admin/actuation/log"')
    window = src[idx : idx + 1400]
    assert 'require_permission("system:admin")' in window
    assert "read_actuation_log(" in window


def test_nothing_in_the_reader_writes():
    """An audit trail whose own reader can amend it is not an audit trail."""
    import inspect

    from orchestrator.services.actuation import audit_log

    src = inspect.getsource(audit_log).upper()
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP "):
        assert verb not in src.replace("INSERT INTO ACTUATION_LOG`", ""), verb
