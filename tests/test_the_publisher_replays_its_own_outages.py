"""BUG-1502: generated history no longer has a hole wherever the publisher was down.

Measured 2026-10-10: every generated table carried the same ~24 outages over 30 days (about
176 h), the newest covering all of 9 October, so "yesterday" found nothing on the 10th. The
publisher now (a) replays from each table's newest row to now on start, and (b) can replay past
outage windows with `--backfill-gaps --since`. Both drive the LIVE publish functions with an
explicit timestamp. These tests pin the three properties that make that safe: a replay writes
only inside a table's own gap, at the live cadence, and the catch-up only ever writes forward.
No database is touched.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pytest

pytestmark = pytest.mark.unit

_PUB_DIR = Path(__file__).resolve().parents[1] / "mysql-dummy-publish-dev"
pytest.importorskip("pymysql", reason="the publisher imports pymysql at module scope")
if str(_PUB_DIR) not in sys.path:
    sys.path.insert(0, str(_PUB_DIR))

import mysql_dummy_publisher as pub  # noqa: E402
import sensor_signal  # noqa: E402

T0 = datetime(2026, 10, 8, 12, 0, 0)


def test_a_silence_longer_than_the_threshold_is_a_window_and_a_short_one_is_not():
    b = int(pub._epoch(T0) // 300)
    buckets = [b, b + 1, b + 2, b + 20, b + 21, b + 23]  # 17 empty buckets (85 min), then 1 (5 min)
    gaps = pub.gaps_from_buckets(buckets, 300, 1800)
    assert gaps == [(T0 + timedelta(minutes=15), T0 + timedelta(minutes=100))]


def test_windows_clip_and_merge():
    w = [(T0, T0 + timedelta(hours=2)), (T0 + timedelta(hours=1), T0 + timedelta(hours=3))]
    assert pub.merge_windows(w) == [(T0, T0 + timedelta(hours=3))]
    assert pub.clip_windows(w, T0 + timedelta(hours=1, minutes=30), T0 + timedelta(hours=4)) == [
        (T0 + timedelta(hours=1, minutes=30), T0 + timedelta(hours=2)),
        (T0 + timedelta(hours=1, minutes=30), T0 + timedelta(hours=3)),
    ]


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        self.conn.written.append((sql, list(rows)))

    def execute(self, sql, args=None):
        table = sql.split("`")[3] if "MAX(" in sql else ""
        self._result = {"t": self.conn.newest.get(table)}

    def fetchone(self):
        return self._result


class _Conn:
    def __init__(self, newest: Dict[str, datetime] = None):
        self.written: List[tuple] = []
        self.newest = newest or {}

    def cursor(self):
        return _Cur(self)


@pytest.fixture()
def two_tables(monkeypatch):
    sensor_signal.reset_state()
    monkeypatch.setattr(
        pub,
        "NARROW_SENSORS",
        [
            {
                "uuid": "co2-1",
                "table": "co2_data",
                "value_col": "co2_ppm",
                "lo": 400,
                "hi": 1200,
                "dec": 0,
            },
            {
                "uuid": "kwh-1",
                "table": "energy_data",
                "value_col": "kwh",
                "lo": 1,
                "hi": 6,
                "dec": 2,
            },
        ],
    )
    monkeypatch.setattr(pub, "EXTENDED_SENSORS", [])
    monkeypatch.setattr(pub, "PLANT_GROUPS", [])
    monkeypatch.setattr(pub, "WASTE_BINS", [])
    yield
    sensor_signal.reset_state()


def _rows(conn) -> Dict[str, List[tuple]]:
    out: Dict[str, List[tuple]] = {}
    for sql, rows in conn.written:
        out.setdefault(sql.split("`")[1], []).extend(rows)
    return out


def test_a_replay_writes_each_table_only_inside_its_own_gap_and_at_the_live_cadence(two_tables):
    conn = _Conn()
    windows = {
        "co2_data": [(T0, T0 + timedelta(hours=2))],
        "energy_data": [(T0 + timedelta(hours=1), T0 + timedelta(hours=2))],  # a shorter gap
    }
    counts = pub.replay(conn, windows, wide=None, interval_s=30)
    rows = _rows(conn)
    co2 = sorted(r[1] for r in rows["co2_data"])
    kwh = sorted(r[1] for r in rows["energy_data"])
    assert all(T0 <= t < T0 + timedelta(hours=2) for t in co2)
    assert all(T0 + timedelta(hours=1) <= t < T0 + timedelta(hours=2) for t in kwh)
    # the live cadence, not the replay tick: CO2 every 60 s, energy every 15 min
    co2_step = {(b - a).total_seconds() for a, b in zip(co2, co2[1:])}
    kwh_step = {(b - a).total_seconds() for a, b in zip(kwh, kwh[1:])}
    assert co2_step == {float(sensor_signal.cadence_for("co2_ppm"))}
    assert kwh_step == {float(sensor_signal.cadence_for("kwh"))}
    assert counts == {"co2_data": len(co2), "energy_data": len(kwh)}
    # replayed rows go in with INSERT IGNORE: a replay never overwrites a row that exists
    assert all("INSERT IGNORE" in sql for sql, _ in conn.written)


def test_a_dry_run_counts_and_writes_nothing(two_tables):
    conn = _Conn()
    counts = pub.replay(conn, {"co2_data": [(T0, T0 + timedelta(minutes=30))]}, dry_run=True)
    assert counts["co2_data"] > 0 and conn.written == []


def test_the_catch_up_only_writes_forward_from_each_tables_newest_row(two_tables, monkeypatch):
    now = datetime.utcnow().replace(microsecond=0)
    newest = {"co2_data": now - timedelta(hours=3), "energy_data": now - timedelta(minutes=10)}
    conn = _Conn(newest)
    pub.catch_up(conn, wide=None, interval_s=30, plant_interval_s=300)
    rows = _rows(conn)
    assert rows.get("co2_data"), "a table three hours behind is caught up"
    assert (
        min(r[1] for r in rows["co2_data"]) > newest["co2_data"]
    ), "nothing at or before its newest row"
    # ten minutes behind is an ordinary interval for a 15-minute meter, not an outage
    assert "energy_data" not in rows


def test_the_catch_up_never_reaches_further_back_than_its_bound(two_tables, monkeypatch):
    monkeypatch.setattr(pub, "CATCHUP_MAX_DAYS", 1.0)
    now = datetime.utcnow()
    conn = _Conn({"co2_data": now - timedelta(days=30)})
    pub.catch_up(conn, wide=None, interval_s=300, plant_interval_s=300)
    first = min(r[1] for r in _rows(conn)["co2_data"])
    assert first >= now - timedelta(days=1, minutes=1)


def test_a_replayed_wide_row_takes_its_values_from_its_own_hour(monkeypatch):
    """The wide generator read datetime.utcnow(): a replayed 03:00 row got the current hour."""
    seen = []
    monkeypatch.setattr(pub, "SENSOR_MAP", {"u1": "Air_Temperature_Sensor_5.01"})
    monkeypatch.setattr(
        pub._signal,
        "next_value",
        lambda u, k, lo, hi, dec, when=None, step_s=None: (seen.append(when) or (21.0, 21.0)),
    )
    at = datetime(2026, 10, 9, 3, 0, 0)
    row = pub.make_row_values([{"cname": "u1", "dtype": "float", "ctype": "float"}], at=at)
    assert row[0] == at and seen == [at]


def test_live_rows_carry_their_own_utc_timestamp(two_tables):
    conn = _Conn()
    before = datetime.utcnow()
    pub.publish_narrow(conn)
    (sql, rows), *_ = conn.written
    assert "NOW()" not in sql and all(before <= r[1] <= datetime.utcnow() for r in rows)
