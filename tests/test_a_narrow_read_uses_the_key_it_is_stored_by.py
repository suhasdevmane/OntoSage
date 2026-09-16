"""A per-sensor read is a range scan per sensor, not one window over the table (2026-09-16).

Measured on the live 10.1M-row narrow table, 174 sensors x 60 readings:
  ROW_NUMBER() OVER (PARTITION BY uuid ...)   20.21 s
  UNION ALL of per-uuid ORDER BY ... LIMIT n   2.33 s   (identical 10,440 rows)
Those 20 seconds were most of what "which floor is the warmest right now?" cost.
"""

import pytest

from orchestrator.services.adapters import mysql_narrow_adapter as mod

pytestmark = pytest.mark.unit

U = [f"{i:08d}-0000-0000-0000-000000000000" for i in range(1, 6)]


def _adapter(table="sensor_data_floors04"):
    a = mod.MySQLNarrowAdapter.__new__(mod.MySQLNarrowAdapter)
    a._table = table
    return a


def test_many_sensors_with_a_small_limit_read_per_sensor():
    q = _adapter().build_timeseries_query(U, "datetime", None, None, limit=60)
    assert q.count("UNION ALL") == len(U) - 1
    assert "ROW_NUMBER" not in q
    assert q.count("ORDER BY `datetime` DESC LIMIT 60") == len(U)
    for u in U:
        assert f"`uuid` = '{u}'" in q


def test_the_interval_is_applied_to_every_branch():
    q = _adapter().build_timeseries_query(U, "datetime", "2026-09-14", "2026-09-15", limit=10)
    assert q.count("`datetime` >= '2026-09-14'") == len(U)
    assert q.count("`datetime` <= '2026-09-15'") == len(U)
    assert "`uuid` IN (" not in q  # the per-branch equality replaces the IN list


def test_a_very_wide_or_very_deep_read_keeps_the_window_form():
    many = [f"{i:08d}-0000-0000-0000-000000000000" for i in range(mod._MAX_UNION_BRANCHES + 1)]
    assert "ROW_NUMBER" in _adapter().build_timeseries_query(many, "datetime", None, None, 60)
    deep = _adapter().build_timeseries_query(U, "datetime", None, None,
                                             limit=mod._MAX_UNION_ROWS_PER_UUID + 1)
    assert "ROW_NUMBER" in deep


def test_an_unsafe_uuid_is_still_refused():
    assert _adapter().build_timeseries_query(["'; DROP TABLE x; --"], "datetime", None, None, 5) is None
