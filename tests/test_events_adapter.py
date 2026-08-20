# -*- coding: utf-8 -*-
"""V5-T07: MySQLEventsAdapter query builders + registry dispatch (offline)."""

import pytest

from orchestrator.services.adapters.mysql_events_adapter import MySQLEventsAdapter

pytestmark = pytest.mark.unit

_U1 = "84ecac3e-df8d-564b-b041-34c8be294922"
_U2 = "41f9839a-b2cd-5e08-b4e3-d154ce49ca1b"


@pytest.fixture()
def adapter():
    return MySQLEventsAdapter(host="localhost", port=3306, user="x", password="x", database="db")


def test_active_now_shape(adapter):
    sql = adapter.build_active_now("booking", subject_uuids=[_U1, _U2])
    assert "`event_type` = 'booking'" in sql
    assert "`start_dt` <= NOW()" in sql and "`end_dt` IS NULL OR `end_dt` > NOW()" in sql
    assert _U1 in sql and _U2 in sql


def test_active_now_at_instant(adapter):
    sql = adapter.build_active_now("workorder", at="2026-08-15 14:00:00")
    assert "'2026-08-15 14:00:00'" in sql and "NOW()" not in sql


def test_overlap_window_is_the_availability_primitive(adapter):
    sql = adapter.build_overlap_window(
        "booking", "2026-08-15 14:00:00", "2026-08-15 16:00:00", subject_uuids=[_U1]
    )
    # overlap: starts before window end AND (open-ended OR ends after window start)
    assert "`start_dt` < '2026-08-15 16:00:00'" in sql
    assert "`end_dt` IS NULL OR `end_dt` > '2026-08-15 14:00:00'" in sql


def test_count_by_status_with_aging(adapter):
    sql = adapter.build_count_by_status("workorder", open_older_than="2026-08-01")
    assert "GROUP BY `status`" in sql
    assert "`end_dt` IS NULL" in sql and "'2026-08-01 00:00:00'" in sql


def test_latest_per_subject_uses_window_function(adapter):
    sql = adapter.build_latest_per_subject("anomaly:seasonal_residual")
    assert "ROW_NUMBER() OVER (PARTITION BY `subject_uuid`" in sql
    assert "rn = 1" in sql


def test_history_for_subject(adapter):
    sql = adapter.build_history(_U1, event_type="compliance", since="2026-01-01")
    assert f"`subject_uuid` = '{_U1}'" in sql and "'2026-01-01 00:00:00'" in sql


def test_injection_inputs_rejected(adapter):
    assert adapter.build_active_now("booking; DROP TABLE events") is None
    assert adapter.build_history("x' OR '1'='1") is None
    assert adapter.build_overlap_window("booking", "not-a-date", "2026-01-02") is None
    # bad uuids collapse to an explicit empty match, never a widened scope
    sql = adapter.build_active_now("booking", subject_uuids=["'; DROP--"])
    assert "1=0" in sql


def test_registry_dispatch_builds_events_adapter():
    from orchestrator.services.adapters.registry import AdapterRegistry

    reg = AdapterRegistry.__new__(AdapterRegistry)  # no init: test dispatch only
    adapter = reg._build_adapter(
        "mysql_events",
        {"host": "h", "port": 3306, "user": "u", "password": "p", "database": "d"},
    )
    assert isinstance(adapter, MySQLEventsAdapter)
