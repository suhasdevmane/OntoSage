# -*- coding: utf-8 -*-
"""The events store's time-based kinds are kept live, by the generator that seeded them (CAVEAT-672).

WHY THIS TEST EXISTS
--------------------
`events` (registry key `events_data`) held footfall, bookings, work orders and asset outages
seeded ONCE by scripts/backfill_events.py. Nothing continued them, so from 2026-09-05 "how
busy was the entrance today?" answered 0, 3,119 bookings that had already happened were
still "confirmed", and work orders raised weeks earlier were still "open". The sensor stores
stayed current throughout, so the building-wide freshness sweep reported everything live.

The data-publisher now writes those kinds on a timer, using the orchestrator's own generator
loaded by path, and scripts/extend_events_to_now.py closes the historical gap. These tests
pin the properties that make that safe to leave running:

* the scanner's `anomaly:*` rows are never written (a second writer is BUG-666);
* ids are deterministic, so a restart or an overlapping window writes nothing new;
* nothing that cannot exist before it happens is written ahead of now;
* each kind's daily volume stays inside the range the stored history shows;
* a missing or broken events map disables events publishing without raising;
* the catch-up script writes nothing without --apply.

All offline: a fake connection captures what WOULD be written. No database is touched.
"""

from __future__ import annotations

import inspect
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_PUB_DIR = _REPO / "mysql-dummy-publish-dev"
_GEN_DIR = _REPO / "orchestrator" / "services" / "deliberation"

pytest.importorskip("pymysql", reason="the publisher module imports pymysql at module scope")

if str(_PUB_DIR) not in sys.path:
    sys.path.insert(0, str(_PUB_DIR))

publisher = pytest.importorskip(
    "mysql_dummy_publisher", reason="publisher source not present in this checkout"
)

#: Any valid UUID works for the offline tests; parity with the orchestrator's real namespace
#: is pinned separately below.
_NS = "12345678-1234-5678-1234-567812345678"

#: A room list the size of the one the backfill discovered (234 spaces, measured 2026-09-17).
#: The names are neutral on purpose: the building's own names are not available offline.
_ROOMS = [f"Room{f}.{n:02d}" for f in range(6) for n in range(39)]
_ASSETS = [("lift_A", "lift"), ("lift_B", "lift"), ("av_R1", "av"), ("wifi_F1", "network")]

#: Per-day volumes MEASURED from the store on 2026-09-17 (UTC session), over the days written
#: by a single backfill run (2026-07-21..07-30 and 2026-08-27..09-04; days in between were
#: written twice over two room lists and are inflated). Widened by 25% because these tests
#: generate over neutral room names rather than the building's own.
_MEASURED = {
    # kind: {weekday: (min, max), weekend: (min, max)} — access counts arrivals, others rows
    "access": {"weekday": (3393, 4171), "weekend": (507, 581)},
    "booking": {"weekday": (156, 180), "weekend": (29, 44)},
    "workorder": {"weekday": (1, 12), "weekend": (1, 10)},
}
_TOLERANCE = 0.25


# ── fakes ──────────────────────────────────────────────────────────────────────────────────


class _Table:
    """An `events` table keyed by event_id, applying the publisher's upsert semantics."""

    def __init__(self):
        self.rows: Dict[str, List] = {}
        self.inserted = 0
        self.changed = 0
        self.statements: List[str] = []

    def upsert(self, sql: str, rows) -> None:
        self.statements.append(sql)
        for r in rows:
            r = list(r)
            cur = self.rows.get(r[0])
            if cur is None:
                self.rows[r[0]] = r
                self.inserted += 1
            elif cur[1] == r[1] and (cur[5], cur[4]) != (r[5], r[4]):
                cur[5], cur[4] = r[5], r[4]
                self.changed += 1


class _Cursor:
    def __init__(self, table: _Table):
        self.table = table
        self._result: List[Tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        self.table.upsert(sql, rows)

    def execute(self, sql, args=None):
        s = " ".join(sql.split())
        if not s.upper().startswith("SELECT"):
            self.table.statements.append(sql)
            return
        kind = args[0] if args else None
        mine = [r for r in self.table.rows.values() if r[1] == kind]
        if s.startswith("SELECT MIN(start_dt), MAX(start_dt), COUNT(*)"):
            starts = sorted(r[3] for r in mine)
            self._result = [
                (starts[0] if starts else None, starts[-1] if starts else None, len(mine))
            ]
        elif s.startswith("SELECT MIN(start_dt) FROM"):
            statuses, now = set(args[1:-1]), args[-1]
            stale = sorted(r[3] for r in mine if r[5] in statuses and r[3] <= now)
            self._result = [(stale[0] if stale else None,)]
        elif s.startswith("SELECT event_id, status, end_dt"):
            self._result = [(r[0], r[5], r[4]) for r in mine]
        elif s.startswith("SELECT COUNT(*), MAX(start_dt)"):
            starts = sorted(r[3] for r in mine)
            self._result = [(len(mine), starts[-1] if starts else None)]
        else:
            self._result = [(None,)]

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _Conn:
    def __init__(self, table: Optional[_Table] = None):
        self.table = table or _Table()
        self.commits = 0

    def cursor(self):
        return _Cursor(self.table)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class _Untouchable:
    """A connection that fails the test if anything asks it for a cursor."""

    def cursor(self):
        raise AssertionError("events publishing touched the database while disabled")


def _spec(**over):
    spec = {
        "building_id": "bldgT",
        "table": "events",
        "rooms": list(_ROOMS),
        "assets": [list(a) for a in _ASSETS],
        "subject_uuid_namespace": _NS,
        "kinds": {k: {} for k in publisher.EVENT_KINDS},
        "nature": "synthetic",
    }
    spec.update(over)
    return spec


@pytest.fixture(autouse=True)
def _reset_publisher_events():
    publisher._disable_events()
    yield
    publisher._disable_events()


@pytest.fixture
def enabled():
    assert publisher.configure_events(_spec(), str(_GEN_DIR)) == len(publisher.EVENT_KINDS)
    return publisher


#: A weekday afternoon, and the same instant a restart later.
_NOW = datetime(2026, 9, 16, 13, 51, 0)


# ── the anomaly kind belongs to the scanner ───────────────────────────────────────────────


def test_anomaly_kinds_in_a_map_are_refused():
    kinds = {"anomaly:zscore": {}, "anomaly": {}, "booking": {}}
    assert publisher.configure_events(_spec(kinds=kinds), str(_GEN_DIR)) == 1
    assert list(publisher.EVENTS_SPEC["kinds"]) == ["booking"]


def test_a_map_naming_only_anomaly_kinds_enables_nothing():
    assert publisher.configure_events(_spec(kinds={"anomaly:iforest": {}}), str(_GEN_DIR)) == 0
    assert publisher.publish_events(_Untouchable(), now_dt=_NOW, now_s=0.0, force=True) == 0


def test_the_window_function_refuses_an_anomaly_kind(enabled):
    with pytest.raises(ValueError):
        publisher.event_rows_for_window(
            publisher.EVENTS_GEN, publisher.EVENTS_SPEC, "anomaly:zscore", _NOW, _NOW, _NOW
        )


def test_an_anomaly_row_from_the_generator_is_still_never_written(enabled, monkeypatch):
    real = publisher.EVENTS_GEN.access_events_for_day

    def with_anomaly(building_id, rooms, day):
        out = real(building_id, rooms, day)
        if out:
            rogue = dict(out[0])
            rogue["event_type"] = "anomaly:zscore"
            rogue["event_id"] = str(uuid.uuid4())
            out.append(rogue)
        return out

    monkeypatch.setattr(publisher.EVENTS_GEN, "access_events_for_day", with_anomaly)
    conn = _Conn()
    assert publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True) > 0
    assert conn.table.rows, "the positive half: ordinary events were written"
    assert not [r for r in conn.table.rows.values() if str(r[1]).startswith("anomaly")]


def test_the_write_itself_refuses_an_anomaly_row(enabled, monkeypatch):
    """The last line of defence, independent of how the rows were derived."""
    rogue = ("r-1", "anomaly:zscore", "s", "2026-09-16 09:00:00", None, "open", "{}")
    fine = ("f-1", "access", "s", "2026-09-16 09:00:00", "2026-09-16 09:10:00", "done", "{}")
    monkeypatch.setattr(publisher, "events_due_rows", lambda *a, **k: [rogue, fine])
    conn = _Conn()
    assert publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True) == 1
    assert list(conn.table.rows) == ["f-1"]


# ── idempotence ────────────────────────────────────────────────────────────────────────────


def test_rerunning_the_same_window_writes_nothing(enabled):
    conn = _Conn()
    first = publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True)
    assert first > 0 and conn.table.inserted == first
    assert publisher.publish_events(conn, now_dt=_NOW, now_s=1.0, force=True) == 0


def test_a_restart_rederiving_the_window_adds_no_row_and_changes_no_value():
    conn = _Conn()
    publisher.configure_events(_spec(), str(_GEN_DIR))
    publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True)
    before = {k: list(v) for k, v in conn.table.rows.items()}
    inserted = conn.table.inserted

    publisher.configure_events(_spec(), str(_GEN_DIR))  # a fresh process: empty caches
    publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True)
    assert conn.table.inserted == inserted
    assert conn.table.changed == 0
    assert conn.table.rows == before


def test_ids_do_not_depend_on_when_or_how_often_they_are_derived(enabled):
    day = datetime(2026, 9, 15)
    a = publisher.event_rows_for_window(
        publisher.EVENTS_GEN, publisher.EVENTS_SPEC, "booking", day, day, _NOW
    )
    b = publisher.event_rows_for_window(
        publisher.EVENTS_GEN, publisher.EVENTS_SPEC, "booking", day, day, _NOW + timedelta(days=9)
    )
    assert a and [r[0] for r in a] == [r[0] for r in b]


def test_a_lifecycle_change_updates_the_row_in_place(enabled):
    """A booking that has started stops being 'confirmed'; it does not become a second row."""
    conn = _Conn()
    morning = datetime(2026, 9, 16, 6, 0)
    publisher.publish_events(conn, now_dt=morning, now_s=0.0, force=True)
    confirmed_today = [
        r
        for r in conn.table.rows.values()
        if r[1] == "booking" and r[3].startswith("2026-09-16") and r[5] == "confirmed"
    ]
    assert confirmed_today, "a weekday has bookings still ahead at 06:00"
    ids_before = set(conn.table.rows)

    publisher.publish_events(conn, now_dt=datetime(2026, 9, 16, 23, 0), now_s=1.0, force=True)
    assert all(conn.table.rows[r[0]][5] == "done" for r in confirmed_today)
    new_bookings = [
        i for i in set(conn.table.rows) - ids_before if conn.table.rows[i][1] == "booking"
    ]
    assert not new_bookings, "the same bookings, re-stamped — not duplicates"
    assert conn.table.changed >= len(confirmed_today)


# ── nothing is written ahead of now ────────────────────────────────────────────────────────


def test_generated_timestamps_never_exceed_now_except_future_bookings(enabled):
    conn = _Conn()
    publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True)
    now_s = _NOW.strftime("%Y-%m-%d %H:%M:%S")
    kinds = {r[1] for r in conn.table.rows.values()}
    assert {"access", "booking", "workorder"} <= kinds
    for r in conn.table.rows.values():
        if r[1] == "booking":
            # A calendar holds the future, but never as something that already happened.
            if r[3] > now_s:
                assert r[5] == "confirmed", r
            else:
                assert r[5] != "confirmed", r
            continue
        assert r[3] <= now_s, r
        assert r[4] is None or r[4] <= now_s, r


def test_an_access_bucket_is_written_only_once_it_has_closed(enabled):
    mid_bucket = datetime(2026, 9, 16, 9, 5)
    rows = publisher.event_rows_for_window(
        publisher.EVENTS_GEN, publisher.EVENTS_SPEC, "access", mid_bucket, mid_bucket, mid_bucket
    )
    assert rows
    assert max(r[4] for r in rows) <= "2026-09-16 09:00:00"


def test_bookings_reach_the_forward_horizon_and_nothing_else_does(enabled):
    conn = _Conn()
    publisher.publish_events(conn, now_dt=_NOW, now_s=0.0, force=True)
    horizon = (_NOW + timedelta(days=14)).strftime("%Y-%m-%d")
    later = [r for r in conn.table.rows.values() if r[3][:10] > _NOW.strftime("%Y-%m-%d")]
    assert later and {r[1] for r in later} == {"booking"}
    assert max(r[3][:10] for r in later) <= horizon


# ── volume stays inside the measured history ───────────────────────────────────────────────


def _band(kind: str, weekend: bool) -> Tuple[float, float]:
    lo, hi = _MEASURED[kind]["weekend" if weekend else "weekday"]
    return lo * (1 - _TOLERANCE), hi * (1 + _TOLERANCE)


@pytest.mark.parametrize("kind", ["access", "booking", "workorder"])
def test_per_day_volume_stays_within_the_measured_range(enabled, kind):
    start = datetime(2026, 8, 31)
    for k in range(28):
        day = start + timedelta(days=k)
        end_of_day = day + timedelta(days=1)
        rows = publisher.event_rows_for_window(
            publisher.EVENTS_GEN, publisher.EVENTS_SPEC, kind, day, day, end_of_day
        )
        if kind == "access":
            volume = sum(json.loads(r[6])["count"] for r in rows)
        else:
            volume = len(rows)
        lo, hi = _band(kind, day.weekday() >= 5)
        if kind == "workorder":
            # The generator raises 0..rooms//18 a day; zero is a legitimate quiet day.
            lo, hi = 0, max(1, len(_ROOMS) // 18)
        assert lo <= volume <= hi, f"{kind} on {day:%a %Y-%m-%d}: {volume} outside [{lo}, {hi}]"


def test_the_publisher_adds_nothing_to_what_the_generator_makes_for_a_day(enabled):
    """A whole past day through the publisher equals the generator's own output for it."""
    conn = _Conn()
    now = datetime(2026, 9, 17, 0, 30)
    publisher.publish_events(conn, now_dt=now, now_s=0.0, force=True)
    day = datetime(2026, 9, 16)
    gen = publisher.EVENTS_GEN
    expected = {e["event_id"] for e in gen.generate_building_day("bldgT", _ROOMS, day, now)}
    written = {i for i, r in conn.table.rows.items() if r[3].startswith("2026-09-16")}
    written_generated_kinds = {
        i for i in written if conn.table.rows[i][1] in ("access", "booking", "workorder")
    }
    assert written_generated_kinds == expected


# ── a missing or broken map disables events publishing, quietly ────────────────────────────


def test_a_missing_map_disables_events_without_raising(tmp_path):
    assert publisher.load_events(str(tmp_path / "absent.json"), str(_GEN_DIR)) == 0
    assert publisher.publish_events(_Untouchable(), now_dt=_NOW, force=True) == 0


def test_an_unreadable_map_disables_events_without_raising(tmp_path):
    bad = tmp_path / "bldgT_events_publish_map.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert publisher.load_events(str(bad), str(_GEN_DIR)) == 0
    assert publisher.publish_events(_Untouchable(), now_dt=_NOW, force=True) == 0


@pytest.mark.parametrize(
    "broken",
    [
        {"rooms": []},
        {"building_id": ""},
        {"subject_uuid_namespace": ""},
        {"kinds": {"not_a_kind": {}}},
    ],
)
def test_an_incomplete_map_disables_events_without_raising(tmp_path, broken):
    path = tmp_path / "bldgT_events_publish_map.json"
    path.write_text(json.dumps(_spec(**broken)), encoding="utf-8")
    assert publisher.load_events(str(path), str(_GEN_DIR)) == 0
    assert publisher.publish_events(_Untouchable(), now_dt=_NOW, force=True) == 0


def test_a_missing_generator_mount_disables_events_without_raising(tmp_path):
    path = tmp_path / "bldgT_events_publish_map.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    assert publisher.load_events(str(path), str(tmp_path / "no_generator_here")) == 0
    assert publisher.publish_events(_Untouchable(), now_dt=_NOW, force=True) == 0


def test_a_valid_map_on_disk_enables_events(tmp_path):
    """The positive half of the four tests above: the same path with a good map works."""
    path = tmp_path / "bldgT_events_publish_map.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    assert publisher.load_events(str(path), str(_GEN_DIR)) == len(publisher.EVENT_KINDS)
    assert publisher.publish_events(_Conn(), now_dt=_NOW, force=True) > 0


def test_a_database_failure_is_contained(enabled):
    class _Failing:
        def cursor(self):
            raise RuntimeError("server has gone away")

    assert publisher.publish_events(_Failing(), now_dt=_NOW, force=True) == 0
    # Nothing was recorded as written, so the next tick retries everything.
    assert publisher.publish_events(_Conn(), now_dt=_NOW, force=True) > 0


def test_each_kind_is_evaluated_no_faster_than_its_cadence(enabled):
    conn = _Conn()
    assert publisher.publish_events(conn, now_dt=_NOW, now_s=1000.0) > 0
    later = _NOW + timedelta(minutes=5)
    # Five minutes on, no kind's cadence (10-15 min) has elapsed, so nothing is even derived.
    assert publisher.events_due_rows(later, 1300.0) == []
    assert publisher.events_due_rows(later, 1000.0 + 600) != []


def test_the_main_loop_loads_and_publishes_events():
    src = inspect.getsource(publisher.main)
    assert "load_events()" in src
    assert "publish_events(conn" in src


# ── the generator is the orchestrator's, loaded rather than copied ─────────────────────────


def test_the_publisher_does_not_carry_its_own_copy_of_the_generator():
    src = (_PUB_DIR / "mysql_dummy_publisher.py").read_text(encoding="utf-8")
    for name in ("def occupancy_series", "def bookings_for_room_day", "def access_events_for_day"):
        assert name not in src, f"{name} was copied into the publisher"


def test_loading_the_generator_leaves_the_module_table_as_it_was():
    before = {k: v for k, v in sys.modules.items() if k.startswith("orchestrator")}
    publisher.load_event_generator(str(_GEN_DIR))
    after = {k: v for k, v in sys.modules.items() if k.startswith("orchestrator")}
    assert before.keys() == after.keys()
    assert all(before[k] is after[k] for k in before)


def test_subject_uuids_match_the_orchestrators_own_derivation():
    registry = pytest.importorskip("orchestrator.services.datasource_registry")
    real_ns = str(registry._UUID_NS)
    assert publisher.configure_events(_spec(subject_uuid_namespace=real_ns), str(_GEN_DIR))
    for local in _ROOMS[:20] + [a for a, _k in _ASSETS] + ["entrance_main"]:
        assert publisher._subject_uuid_from_spec("bldgT", "evt_subject", local) == (
            registry.derive_point_uuid("bldgT", "evt_subject", local)
        )


def test_loaded_generator_produces_what_the_orchestrator_module_produces():
    events = pytest.importorskip("orchestrator.services.deliberation.synthetic_events")
    registry = pytest.importorskip("orchestrator.services.datasource_registry")
    publisher.configure_events(_spec(subject_uuid_namespace=str(registry._UUID_NS)), str(_GEN_DIR))
    day, now = datetime(2026, 9, 16), datetime(2026, 9, 16, 12, 0)
    ours = [
        publisher.EVENTS_GEN.to_row(e)
        for e in publisher.EVENTS_GEN.generate_building_day("bldgT", _ROOMS, day, now)
    ]
    theirs = [events.to_row(e) for e in events.generate_building_day("bldgT", _ROOMS, day, now)]
    assert ours == theirs


# ── the catch-up script ────────────────────────────────────────────────────────────────────


def _script():
    return pytest.importorskip("scripts.extend_events_to_now")


def _discover():
    return "bldgT", list(_ROOMS), list(_ASSETS), _NS


def test_the_catch_up_script_writes_nothing_without_apply(tmp_path):
    script = _script()
    conn = _Conn()
    rc = script.run(
        [],
        connect=lambda: conn,
        discover=_discover,
        now=_NOW,
        generator_dir=_GEN_DIR,
        input_dir=tmp_path,
    )
    assert rc == 0
    assert conn.table.rows == {} and conn.table.statements == [] and conn.commits == 0
    assert list(tmp_path.iterdir()) == [], "no events map may be written on a dry run"


def test_the_catch_up_script_writes_with_apply_and_never_an_anomaly(tmp_path):
    """The positive half: the same call with --apply does write, so the test above can fail."""
    script = _script()
    conn = _Conn()
    rc = script.run(
        ["--apply"],
        connect=lambda: conn,
        discover=_discover,
        now=_NOW,
        generator_dir=_GEN_DIR,
        input_dir=tmp_path,
    )
    assert rc == 0 and conn.commits == 1 and conn.table.rows
    assert not [r for r in conn.table.rows.values() if str(r[1]).startswith("anomaly")]
    written_map = json.loads((tmp_path / "bldgT_events_publish_map.json").read_text("utf-8"))
    assert written_map["rooms"] == sorted(_ROOMS)
    assert not [k for k in written_map["kinds"] if k.startswith("anomaly")]
    # The map it writes is one the publisher accepts.
    assert publisher.configure_events(written_map, str(_GEN_DIR)) == len(publisher.EVENT_KINDS)


def test_the_catch_up_does_not_add_rows_to_a_period_already_written(tmp_path):
    """Before the last stored row, only lifecycles are refreshed; no new row is inserted."""
    script = _script()
    publisher.configure_events(_spec(), str(_GEN_DIR))
    table = _Table()
    # An old unfinished order pulls the window back to 09-01; the last row is on 09-10.
    old = ("x-old", "workorder", "s", "2026-09-01 10:00:00", None, "open", "{}")
    last = ("x-last", "workorder", "s", "2026-09-10 12:00:00", None, "done", "{}")
    for row in (old, last):
        table.rows[row[0]] = list(row)
    cur = _Conn(table).cursor()
    plan = script.plan_kind(cur, publisher.EVENTS_SPEC, "workorder", _NOW, max_days_back=60)
    assert plan["window"][0] == "2026-09-01"
    assert plan["skipped_in_written_period"] > 0, "the generator does raise orders 09-01..09-09"
    assert plan["insert"] and all(r[3] >= "2026-09-10" for r in plan["insert"])
