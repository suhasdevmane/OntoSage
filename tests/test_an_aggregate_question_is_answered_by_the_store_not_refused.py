# -*- coding: utf-8 -*-
"""A per-floor or whole-building question is answered by the store's aggregates (row 2D-10).

"Which floor had the highest CO2 this week?" reached the SQL lane with 276 sensors and was refused
as "more than I can read row by row" (BUG-808). "How much water did floor 3 use yesterday?" was told
to install a volume meter (BUG-814). Both are answerable by a GROUP BY the store already knows how
to run, so a refusal was the wrong outcome.

These tests use a fake adapter and pin the properties that make the answer trustworthy:

* the statements the store receives are aggregates, never a row-level read;
* the window is built on the stores' UTC clock and only DISPLAYED in building time;
* a verdict ("high") is given only against a limit cited in the standards file, and the limit and
  its source are printed with it;
* a level (ppm, degrees) is never summed into "how much was used";
* a volume from a rate is an integral, labelled as computed, refused when the series has too many
  holes, and never taken from a flow that is not water;
* what was left out (no readings, out of range, unsupported store) is said, not dropped.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)  # store (UTC) time; building time is one hour later (BST)
TZ = "Europe/London"

# uuids the SQL builders accept: 8-64 characters of letters, digits and hyphens
F1A, F1B = "sensor-f1-aaaa", "sensor-f1-bbbb"
F2A, F2B = "sensor-f2-aaaa", "sensor-f2-bbbb"
F3A = "sensor-f3-aaaa"

STORE = "http://example.org/bldg#co2_data"


class FakeAdapter:
    """A narrow store that records every statement and answers from `handler`."""

    adapter_type = AdapterType.MYSQL

    def __init__(self, handler: Callable[[str], List[Dict[str, Any]]], table: str = "co2_data"):
        self.table = table
        self.handler = handler
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = self.handler(sql)
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


class FakeWide(FakeAdapter):
    """A wide store: one column per sensor, no table attribute."""

    def __init__(self, handler, columns=()):
        super().__init__(handler)
        self.table = None
        self._columns_cache = {"Datetime", *columns}

    def _wide_table(self) -> str:
        return "sensor_data"


def _uuids_in(sql: str) -> List[str]:
    return re.findall(r"'(sensor-[0-9a-z-]+)'", sql)


def agg_row(uuid: str, n=100, mn=400.0, mx=800.0, sm=60000.0, ex=0, bad=0):
    return {
        "uuid": uuid,
        "n": n,
        "mn": mn,
        "mx": mx,
        "sm": sm,
        "ex": ex,
        "bad": bad,
        "t0": "2026-09-14 00:00:00",
        "t1": "2026-09-18 11:55:00",
    }


def narrow_handler(stats: Dict[str, Dict[str, Any]], peak_at: str = "2026-09-16 09:15:00"):
    def handle(sql: str):
        if "AS ts FROM" in sql and "MIN(`datetime`) AS ts" in sql:
            return [{"ts": peak_at}]
        return [agg_row(u, **stats[u]) for u in _uuids_in(sql) if u in stats]

    return handle


META = {
    F1A: {"label": "CO2 Level Sensor 1.01", "unit": "ppm", "floor": "1"},
    F1B: {"label": "CO2 Level Sensor 1.02", "unit": "ppm", "floor": "1"},
    F2A: {"label": "CO2 Level Sensor 2.01", "unit": "ppm", "floor": "2"},
    F2B: {"label": "CO2 Level Sensor 2.02", "unit": "ppm", "floor": "2"},
    F3A: {"label": "CO2 Level Sensor 3.01", "unit": "ppm", "floor": "3"},
}
SMAP = {u: STORE for u in META}


def places_exec(extra: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None):
    """A fake SPARQL executor: locations by uuid, plus whatever `extra` answers first."""

    async def run(query: str) -> Dict[str, Any]:
        if extra:
            got = extra(query)
            if got is not None:
                return got
        rooms = {
            F1A: ("Room 1.01 - Office", "1"),
            F1B: ("Room 1.02 - Lab", "1"),
            F2A: ("Room 2.01 - Office", "2"),
            F2B: ("Room 2.02 - Lab", "2"),
            F3A: ("Room 3.01 - Meeting", "3"),
        }
        binds = []
        for u, (label, floor) in rooms.items():
            if f'"{u}"' in query:
                binds.append(
                    {
                        "uuid": {"value": u},
                        "locLabel": {"value": label},
                        "floorNum": {"value": floor},
                        "onFloor": {"value": "false"},
                    }
                )
        return {"results": {"bindings": binds}}

    return run


async def ask(question: str, adapter: Any, meta=None, smap=None, **kw):
    meta = META if meta is None else meta
    smap = SMAP if smap is None else smap
    args = dict(
        question=question,
        uuids=list(meta),
        storage_map=smap,
        metadata=meta,
        start_date=None,
        end_date=None,
        budget_hit=True,
        tz_name=TZ,
        adapter_for=lambda uri: adapter,
        store_key=lambda uri: uri.split("#")[-1] or "default",
        sparql_exec=places_exec(),
        now=NOW,
        bands={},
    )
    args.update(kw)
    return await al.try_answer(**args)


# ── what is asked ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, stat, group",
    [
        ("Which floor had the highest CO2 this week?", "max", "floor"),
        ("Which floor is the warmest at the moment?", "max", "floor"),
        ("Which floor has the most people in it right now?", "max", "floor"),
        ("Which room had the lowest temperature yesterday?", "min", "room"),
        ("Has CO2 been high anywhere this week?", "exceed", "room"),
        ("Where is it hottest?", "max", "room"),
        ("How much gas did we use this week?", "total", "building"),
        ("How much water did floor 3 use yesterday?", "total", "floor"),
        ("What is the average CO2 on each floor?", "mean", "floor"),
        ("What was the peak CO2 in the building today?", "max", "building"),
    ],
)
def test_an_aggregate_question_is_recognised(question, stat, group):
    intent = al.parse_intent(question)
    assert intent is not None and (intent.stat, intent.group) == (stat, group)


@pytest.mark.parametrize(
    "question",
    [
        "Where is the nearest lift?",  # a lookup: no statistic
        "What is the temperature in room 5.01?",
        "Plot CO2 for the last 24 hours in the atrium.",
        "Which floor will have the highest CO2 tomorrow?",  # a forecast, not a maximum
        "Which floor's temperature rose most this week?",  # a change, not a maximum
        "When is the atrium busiest?",  # a time of day
        "Show me the floor plan for floor 3",
    ],
)
def test_a_question_that_only_sounds_like_an_aggregate_is_left_alone(question):
    assert al.parse_intent(question) is None


def test_a_named_floor_scopes_the_question():
    intent = al.parse_intent("How much water did floor 3 use yesterday?")
    assert intent.floors == ("3",)


# ── over what period: the stores are UTC ──────────────────────────────────────


def test_the_pipelines_own_window_wins_over_a_second_reading_of_the_words():
    w = al.resolve_window("highest CO2 this week", "2026-09-10 00:00:00", "2026-09-11 00:00:00", TZ)
    assert (w.start, w.end) == ("2026-09-10 00:00:00", "2026-09-11 00:00:00")


def test_this_week_starts_at_building_midnight_on_monday_expressed_in_store_time():
    w = al.resolve_window("highest CO2 this week", None, None, TZ, now=NOW)
    # Monday 14 Sep 00:00 in London (BST, UTC+1) is Sunday 13 Sep 23:00 on the stores' clock
    assert w.start == "2026-09-13 23:00:00"
    assert w.end == "2026-09-18 12:00:00"
    assert "Mon 14 Sep 00:00" in w.label and "building time" in w.label


def test_yesterday_is_a_whole_calendar_day_not_a_rolling_24_hours():
    w = al.resolve_window("water used yesterday", None, None, TZ, now=NOW)
    assert (w.start, w.end) == ("2026-09-16 23:00:00", "2026-09-17 22:59:59")


def test_right_now_is_a_short_recent_window_and_says_so():
    w = al.resolve_window("people right now", None, None, TZ, latest=True, now=NOW)
    assert w.latest and w.end == "2026-09-18 12:00:00" and w.start == "2026-09-18 11:00:00"
    assert "newest reading" in w.label


def test_no_window_named_means_no_answer_rather_than_a_guess():
    assert al.resolve_window("highest CO2 on each floor", None, None, TZ, now=NOW) is None


# ── what counts as high: only a cited limit ───────────────────────────────────


def test_the_default_limit_is_read_from_the_standards_file_and_names_its_source():
    t = al.cited_threshold("co2", "has CO2 been high anywhere")
    assert (t.value, t.unit) == (1000.0, "ppm") and "ASHRAE" in t.standard


def test_the_standard_the_reader_names_is_used():
    assert al.cited_threshold("co2", "has CO2 exceeded the WELL limit").value == 900.0


def test_a_quantity_the_standards_file_does_not_cover_gets_no_limit():
    assert al.cited_threshold("sound", "is it too loud") is None
    assert al.cited_threshold(None, "is it too high") is None


def test_a_named_standard_that_lacks_the_quantity_is_not_silently_swapped_for_another():
    # BREEAM in the file has no humidity band worth a different answer; the point is that when the
    # reader names a standard that does not cover the quantity, no other standard is substituted.
    assert al.cited_threshold("sound", "does it exceed the BREEAM limit") is None


# ── the statements are aggregates ─────────────────────────────────────────────


def _window() -> al.Window:
    return al.Window("2026-09-13 23:00:00", "2026-09-18 12:00:00", "the week")


def test_a_narrow_store_gets_one_group_by_and_no_row_level_read():
    adapter = FakeAdapter(lambda sql: [])
    sts = al.aggregate_statements("mysql_narrow", adapter, [F1A, F1B], _window(), limit=1000.0)
    assert len(sts) == 1
    sql = sts[0].sql
    assert "GROUP BY `uuid`" in sql and "LIMIT" not in sql and "ORDER BY" not in sql
    assert (
        "`datetime` >= '2026-09-13 23:00:00'" in sql
        and "`datetime` <= '2026-09-18 12:00:00'" in sql
    )
    assert "FROM `co2_data`" in sql and "SUM(`value` > 1000.0)" in sql


def test_a_wide_store_is_read_in_one_pass_over_the_window_per_chunk():
    cols = [f"sensor-w{i:03d}-aaaa" for i in range(130)]
    adapter = FakeWide(lambda sql: [], columns=cols)
    sts = al.aggregate_statements("mysql_wide", adapter, cols, _window())
    assert len(sts) == 3  # 60 + 60 + 10 columns
    for st in sts:
        assert st.sql.count("FROM `sensor_data`") == 1 and "LIMIT" not in st.sql
        assert "`Datetime` >= '2026-09-13 23:00:00'" in st.sql and "COUNT(" in st.sql


def test_a_column_the_wide_store_does_not_have_is_not_queried():
    adapter = FakeWide(lambda sql: [], columns=[F1A])
    sts = al.aggregate_statements("mysql_wide", adapter, [F1A, F1B], _window())
    assert F1B not in sts[0].sql and F1A in sts[0].sql


def test_a_physical_range_is_applied_inside_the_statement_and_the_excluded_are_counted():
    adapter = FakeAdapter(lambda sql: [])
    sts = al.aggregate_statements(
        "mysql_narrow", adapter, [F1A], _window(), bands={F1A: (350.0, 40000.0)}
    )
    assert "BETWEEN 350.0 AND 40000.0" in sts[0].sql and "AS bad" in sts[0].sql


def test_sensors_with_different_ranges_get_different_statements():
    adapter = FakeAdapter(lambda sql: [])
    sts = al.aggregate_statements(
        "mysql_narrow", adapter, [F1A, F2A], _window(), bands={F1A: (0.0, 10.0), F2A: (0.0, 99.0)}
    )
    assert len(sts) == 2


def test_an_unsafe_identifier_or_window_bound_never_reaches_sql():
    adapter = FakeAdapter(lambda sql: [])
    assert (
        al.aggregate_statements("mysql_narrow", adapter, ["x'; DROP TABLE t;--"], _window()) == []
    )
    bad = al.Window("2026-09-13'; DROP", "2026-09-18 12:00:00", "x")
    with pytest.raises(ValueError):
        al.aggregate_statements("mysql_narrow", adapter, [F1A], bad)
    hostile = FakeAdapter(lambda sql: [], table="t; DROP TABLE x")
    with pytest.raises(ValueError):
        al.aggregate_statements("mysql_narrow", hostile, [F1A], _window())


def test_a_postgres_hypertable_gets_the_same_shape_of_statement():
    adapter = SimpleNamespace(
        adapter_type=AdapterType.TIMESCALEDB,
        _narrow={"table": "sensor_data", "uuid": "uuid", "ts": "time", "value": "value"},
    )
    assert al.layout_of(adapter) == "pg_narrow"
    sql = al.aggregate_statements("pg_narrow", adapter, [F1A], _window(), limit=1000.0)[0].sql
    assert 'GROUP BY "uuid"' in sql and '"time" >= ' in sql and "LIMIT" not in sql


def test_cassandra_is_aggregated_per_partition_and_exceedance_is_a_second_count():
    adapter = SimpleNamespace(
        adapter_type=AdapterType.CASSANDRA, _keyspace="bldg", _default_table="sensor_data"
    )
    sts = al.aggregate_statements("cassandra", adapter, [F1A], _window(), limit=1000.0)
    assert [s.kind for s in sts] == ["cql_agg", "cql_exceed"]
    assert all(f"uuid = '{F1A}'" in s.sql for s in sts) and "ALLOW FILTERING" in sts[1].sql


def test_the_layout_is_read_from_the_adapter_not_from_a_class_name():
    assert al.layout_of(FakeAdapter(lambda s: [])) == "mysql_narrow"
    assert al.layout_of(FakeWide(lambda s: [])) == "mysql_wide"
    assert al.layout_of(SimpleNamespace(adapter_type=AdapterType.MONGODB)) == "unsupported"
    assert (
        al.layout_of(SimpleNamespace(adapter_type=AdapterType.POSTGRESQL, _narrow=None))
        == "pg_wide"
    )


def test_the_integral_is_computed_in_the_store_with_lead_and_reports_its_gaps():
    adapter = FakeAdapter(lambda sql: [])
    sql = al.integral_statements("mysql_narrow", adapter, [F1A], _window())[0].sql
    assert "LEAD(`value`)" in sql and "TIMESTAMPDIFF(SECOND" in sql
    assert "max_gap" in sql and "gap_s" in sql and "GROUP BY uuid" in sql


# ── the answer, end to end, against a fake store ──────────────────────────────


def _stats():
    return {
        F1A: dict(n=100, mn=400.0, mx=900.0, sm=60000.0),
        F1B: dict(n=100, mn=410.0, mx=950.0, sm=62000.0),
        F2A: dict(n=100, mn=420.0, mx=1175.0, sm=80000.0),
        F2B: dict(n=100, mn=430.0, mx=1000.0, sm=70000.0),
        F3A: dict(n=100, mn=405.0, mx=880.0, sm=61000.0),
    }


async def test_which_floor_had_the_highest_reading_is_answered_with_the_boundary_stated():
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask("Which floor had the highest CO2 this week?", adapter)
    text = res["formatted_response"]
    assert res["aggregate_lane"] and res["analytics_required"] is False
    assert text.startswith("**Floor 2 had the highest CO2 in the period: 1,175 ppm**")
    assert (
        "Room 2.01 - Office" in text and "Wed 16 Sep 10:15" in text
    )  # where, and when (local time)
    assert "| Floor 2 | 1,175 | 2 |" in text and "| Floor 3 | 880 | 1 |" in text
    # the boundary: which sensors, which window, how it was computed
    assert "Based on 5 CO2 sensors on 3 floors" in text and "building time" in text
    assert "computed in the store" in text


async def test_the_store_only_ever_receives_aggregates():
    adapter = FakeAdapter(narrow_handler(_stats()))
    await ask("Which floor had the highest CO2 this week?", adapter)
    assert adapter.sql, "the store was never asked"
    for sql in adapter.sql:
        assert (
            "GROUP BY" in sql or "MIN(`datetime`) AS ts" in sql
        ), sql  # aggregate or one peak lookup
        assert not re.search(r"SELECT\s+`?(?:datetime|timestamp)`?\s+AS\s+timestamp", sql)


async def test_the_lowest_floor_and_the_highest_average_use_the_right_extreme():
    adapter = FakeAdapter(narrow_handler(_stats()))
    low = await ask("Which floor had the lowest CO2 this week?", adapter)
    assert low["formatted_response"].startswith(
        "**Floor 1 had the lowest CO2 in the period: 400 ppm**"
    )
    avg = await ask("Which floor had the highest average CO2 this week?", adapter)
    # mean is total over count, not a mean of means: floor 2 = 150000 / 200
    assert "Floor 2 had the highest average CO2 in the period: 750 ppm" in avg["formatted_response"]


async def test_out_of_range_readings_are_excluded_and_said():
    stats = _stats()
    stats[F1A]["bad"] = 7
    adapter = FakeAdapter(narrow_handler(stats))
    res = await ask(
        "Which floor had the highest CO2 this week?",
        adapter,
        bands={u: (350.0, 40000.0) for u in META},
    )
    assert "7 readings from 1 sensor fell outside the physically possible range for CO2" in (
        res["formatted_response"]
    )
    assert "350 to 40,000 ppm" in res["formatted_response"]


async def test_sensors_with_no_readings_are_named_as_not_counted():
    stats = _stats()
    del stats[F3A]
    adapter = FakeAdapter(narrow_handler(stats))
    res = await ask("Which floor had the highest CO2 this week?", adapter)
    assert "1 of the 5 sensors returned no readings in this period and are not counted" in (
        res["formatted_response"]
    )


async def test_a_store_that_fails_costs_the_answer_nothing_but_is_reported():
    calls = {"n": 0}

    def flaky(sql: str):
        calls["n"] += 1
        if "GROUP BY" in sql and calls["n"] == 1:
            raise RuntimeError("connection lost")
        return narrow_handler(_stats())(sql)

    adapter = FakeAdapter(flaky)
    assert await ask("Which floor had the highest CO2 this week?", adapter) is None


async def test_when_no_store_can_be_summarised_the_lane_steps_aside():
    mongo = SimpleNamespace(adapter_type=AdapterType.MONGODB)
    assert await ask("Which floor had the highest CO2 this week?", mongo) is None


async def test_a_question_it_should_not_take_is_returned_untouched():
    adapter = FakeAdapter(narrow_handler(_stats()))
    # budget not hit and the sensors carry floors: the row-based lane already answers this
    assert (
        await ask("Which floor had the highest CO2 this week?", adapter, budget_hit=False) is None
    )
    assert adapter.sql == []


async def test_a_sensor_set_with_no_floors_is_grouped_by_the_graph_when_the_reader_asks_by_floor():
    meta = {u: {k: v for k, v in m.items() if k != "floor"} for u, m in META.items()}
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask(
        "Which floor had the highest CO2 this week?", adapter, meta=meta, budget_hit=False
    )
    assert res and "Floor 2 had the highest CO2" in res["formatted_response"]


# ── "has X been high": only against a cited limit ─────────────────────────────


async def test_has_it_been_high_answers_against_the_cited_limit_and_names_its_source():
    stats = _stats()
    stats[F2A]["ex"] = 40
    stats[F2B]["ex"] = 5
    adapter = FakeAdapter(narrow_handler(stats))
    res = await ask("Has CO2 been high anywhere this week?", adapter)
    text = res["formatted_response"]
    assert text.startswith("**Yes.** CO2 was above 1,000 ppm")
    assert "ASHRAE Standard 55 entry of this system's standards table" in text
    assert "on 2 of 5 sensors" in text and "45 of 500 readings (9.0%)" in text
    assert "Room 2.01 - Office" in text and "By floor: Floor 2 45 readings above the limit" in text
    assert "SUM(`value` > 1000.0)" in adapter.sql[0]


async def test_a_no_is_a_no_with_the_highest_figure_for_context():
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask("Has CO2 been high anywhere this week?", adapter)
    assert res["formatted_response"].startswith("**No.** No CO2 reading was above 1,000 ppm")
    assert "The highest was 1,175 ppm at Room 2.01 - Office" in res["formatted_response"]


async def test_a_quantity_with_no_cited_limit_is_ranked_and_not_called_high():
    meta = {
        u: {**m, "label": m["label"].replace("CO2 Level", "Noise Level"), "unit": "dB"}
        for u, m in META.items()
    }
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask("Has noise been high anywhere this week?", adapter, meta=meta)
    text = res["formatted_response"]
    assert "cites no limit for" in text and "not calling any of them high or low" in text
    assert "**Yes.**" not in text and "**No.**" not in text


# ── totals: additive quantities only ──────────────────────────────────────────


async def test_a_level_is_never_summed_into_how_much_was_used():
    meta = {
        F1A: {"label": "Floor1 gas [ppm]", "unit": "ppm", "floor": "1"},
        F2A: {"label": "Floor2 gas [ppm]", "unit": "ppm", "floor": "2"},
    }
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask(
        "How much gas did we use this week?", adapter, meta=meta, smap={u: STORE for u in meta}
    )
    text = res["formatted_response"]
    # Wave 2: one sentence, and no statistics. A paragraph of ppm figures beside "no usage data"
    # reads as an attempt at the question that was asked (see the wave-2 test file).
    assert "I can't say how much gas was used" in text
    assert "|" not in text and chr(10) not in text


async def test_a_how_much_question_about_a_level_is_not_treated_as_consumption():
    meta = {F1A: {"label": "CO2 1.01", "unit": "ppm", "floor": "1"}}
    adapter = FakeAdapter(narrow_handler(_stats()))
    assert (
        await ask("How much CO2 is on floor 1 this week?", adapter, meta=meta, smap={F1A: STORE})
        is None
    )


async def test_energy_is_summed_because_each_reading_is_the_energy_of_its_interval():
    meta = {
        F1A: {"label": "Floor 1 energy", "unit": "kWh", "floor": "1"},
        F2A: {"label": "Floor 2 energy", "unit": "kWh", "floor": "2"},
    }
    stats = {F1A: dict(n=10, mn=1.0, mx=9.0, sm=50.0), F2A: dict(n=10, mn=1.0, mx=9.0, sm=70.0)}
    adapter = FakeAdapter(narrow_handler(stats))
    res = await ask(
        "How much electricity did we use this week?",
        adapter,
        meta=meta,
        smap={u: STORE for u in meta},
    )
    assert res["formatted_response"].startswith("**120 kWh was used in the building**")
    assert "| Floor 2 | 70 kWh |" in res["formatted_response"]


# ── volume from a flow rate: an integral, labelled, and only when regular ─────

W1, W2, AIR = "sensor-water1-aa", "sensor-water2-bb", "sensor-airflow-cc"
WATER_META = {
    W1: {"label": "Floor3 water_flow_rate [L/s]", "unit": "L/s", "floor": "3"},
    AIR: {"label": "Air Handling Unit - Floor 3 supply air flow", "unit": "L/s", "floor": "3"},
}


def integral_handler(rows: Dict[str, Dict[str, Any]]):
    def handle(sql: str):
        return [{"uuid": u, **rows[u]} for u in _uuids_in(sql) if u in rows]

    return handle


def _integral(
    integral=2_051_447.0,
    n=258,
    max_gap=2504,
    mean_gap=336.0,
    gap_s=6974.0,
    t0="2026-09-16 23:04:16",
    t1="2026-09-17 22:56:41",
):
    return dict(
        n=n, integral=integral, max_gap=max_gap, mean_gap=mean_gap, gap_s=gap_s, t0=t0, t1=t1
    )


async def test_a_volume_is_integrated_from_the_flow_and_labelled_as_computed():
    adapter = FakeAdapter(integral_handler({W1: _integral()}))
    res = await ask(
        "How much water did floor 3 use yesterday?",
        adapter,
        meta=WATER_META,
        smap={u: STORE for u in WATER_META},
        budget_hit=False,
    )
    text = res["formatted_response"]
    assert text.startswith("**About 2,051 m³ (2,051,447 L) of water on floor 3**")
    assert (
        "integrating the flow readings over the window" in text
        and "not read from a volume meter" in text
    )
    assert "about every 5.6 min" in text and "a gap of 42 min was bridged" in text
    assert (
        "Left out: Air Handling Unit - Floor 3 supply air flow, because it measures air, not water"
        in text
    )
    assert all("LEAD(" in s for s in adapter.sql)  # the integral was computed in the store


async def test_a_rate_in_litres_per_minute_is_converted_before_it_is_called_litres():
    meta = {W1: {"label": "Water Main Flow Sensor", "unit": "L/min", "floor": "3"}}
    adapter = FakeAdapter(integral_handler({W1: _integral(integral=60_000.0)}))
    res = await ask(
        "How much water did floor 3 use yesterday?",
        adapter,
        meta=meta,
        smap={W1: STORE},
        budget_hit=False,
    )
    assert "About 1 m³ (1,000 L) of water" in res["formatted_response"]  # 60,000 L/min*s / 60


async def test_a_series_with_too_many_holes_is_not_integrated():
    holey = _integral(gap_s=40_000.0, max_gap=30_000)  # far more than a tenth of the span
    adapter = FakeAdapter(integral_handler({W1: holey}))
    meta = {W1: WATER_META[W1]}
    # Wave 2: it says so rather than returning None. Handing the question back sent the live run
    # to a lane that multiplied a mean flow by 86,400 s and stated no method at all.
    res = await ask(
        "How much water did floor 3 use yesterday?",
        adapter,
        meta=meta,
        smap={W1: STORE},
        budget_hit=False,
    )
    assert "I can't total the water used" in res["formatted_response"]
    assert "too much to bridge honestly" in res["formatted_response"]
    assert "2,051" not in res["formatted_response"]


async def test_a_series_covering_a_sliver_of_the_window_is_not_integrated():
    short = _integral(t0="2026-09-17 20:00:00", t1="2026-09-17 21:00:00")
    adapter = FakeAdapter(integral_handler({W1: short}))
    meta = {W1: WATER_META[W1]}
    res = await ask(
        "How much water did floor 3 use yesterday?",
        adapter,
        meta=meta,
        smap={W1: STORE},
        budget_hit=False,
    )
    assert "I can't total the water used" in res["formatted_response"]
    assert "cover only 1.0 h of the 24.0 h asked about" in res["formatted_response"]


async def test_a_flow_that_is_not_named_as_water_is_never_reported_as_water():
    meta = {AIR: WATER_META[AIR]}
    adapter = FakeAdapter(integral_handler({AIR: _integral()}))
    assert (
        await ask(
            "How much water did floor 3 use yesterday?",
            adapter,
            meta=meta,
            smap={AIR: STORE},
            budget_hit=False,
        )
        is None
    )
    assert adapter.sql == []


# ── "who has the most people": a floor's own counter is the floor's figure ────

ROOM_A, ROOM_B, FLOOR_1, FLOOR_2 = (
    "sensor-room-aaaa",
    "sensor-room-bbbb",
    "sensor-fl1-cccc",
    "sensor-fl2-dddd",
)


def latest_handler(values: Dict[str, float]):
    def handle(sql: str):
        return [
            {"uuid": u, "value": v, "ts": "2026-09-18 11:58:00"}
            for u, v in values.items()
            if f"'{u}'" in sql
        ]

    return handle


def companion_exec(query: str):
    if "VALUES ?seed" in query:
        return {
            "results": {
                "bindings": [
                    {
                        "uuid": {"value": FLOOR_1},
                        "storage": {"value": STORE},
                        "floorNum": {"value": "1"},
                        "label": {"value": "Occupancy Count Sensor - Floor 1"},
                    },
                    {
                        "uuid": {"value": FLOOR_2},
                        "storage": {"value": STORE},
                        "floorNum": {"value": "2"},
                        "label": {"value": "Occupancy Count Sensor - Floor 2"},
                    },
                ]
            }
        }
    return None


async def test_the_floor_with_the_most_people_uses_the_floors_own_counter_not_the_sum_of_rooms():
    meta = {
        ROOM_A: {"label": "Room 1.01 occupancy [persons]", "unit": "count", "kind": "occupancy"},
        ROOM_B: {"label": "Room 2.01 occupancy [persons]", "unit": "count", "kind": "occupancy"},
    }
    adapter = FakeAdapter(latest_handler({FLOOR_1: 11.0, FLOOR_2: 14.0, ROOM_A: 9.0, ROOM_B: 8.0}))
    res = await al.try_answer(
        question="Which floor has the most people in it right now?",
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        metadata=meta,
        start_date=None,
        end_date=None,
        budget_hit=False,
        tz_name=TZ,
        adapter_for=lambda uri: adapter,
        store_key=lambda uri: "co2_data",
        sparql_exec=places_exec(companion_exec),
        now=NOW,
        bands={},
    )
    text = res["formatted_response"]
    assert text.startswith("**Floor 2 has the most people in it right now: 14**")
    assert "| Floor 1 | 11 | 1 |" in text
    assert "room-level counters are not added to it, so nobody is counted twice" in text
    assert ROOM_A not in " ".join(adapter.sql)


async def test_without_a_floor_counter_the_room_sum_is_labelled_as_such():
    meta = {
        ROOM_A: {
            "label": "Room 1.01 occupancy",
            "unit": "count",
            "kind": "occupancy",
            "floor": "1",
        },
        ROOM_B: {
            "label": "Room 1.02 occupancy",
            "unit": "count",
            "kind": "occupancy",
            "floor": "1",
        },
    }
    adapter = FakeAdapter(latest_handler({ROOM_A: 3.0, ROOM_B: 4.0}))
    res = await al.try_answer(
        question="Which floor has the most people right now?",
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        metadata=meta,
        start_date=None,
        end_date=None,
        budget_hit=True,
        tz_name=TZ,
        adapter_for=lambda uri: adapter,
        store_key=lambda uri: "co2_data",
        sparql_exec=places_exec(),
        now=NOW,
        bands={},
    )
    assert "sum of one reading per room that has a counter" in res["formatted_response"]
    assert res["formatted_response"].startswith(
        "**Floor 1 has the most people in it right now: 7**"
    )


# ── the wording rules of the project ──────────────────────────────────────────


async def test_no_answer_calls_the_data_synthetic_or_simulated():
    adapter = FakeAdapter(narrow_handler(_stats()))
    for q in (
        "Which floor had the highest CO2 this week?",
        "Has CO2 been high anywhere this week?",
    ):
        res = await ask(q, adapter)
        assert not re.search(
            r"synthetic|simulated|fake|placeholder", res["formatted_response"], re.I
        )


def test_the_module_names_no_building_and_carries_no_floor_count():
    import inspect

    src = inspect.getsource(al)
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "Abacws", "cardiff"):
        assert literal not in src, literal


def test_the_result_is_marked_so_no_later_lane_rewrites_it():
    res = al._result("text", al.AggregateIntent("max", "floor"), _window(), 3)
    assert res["aggregate_lane"] is True and res["analytics_required"] is False
    assert res["results"] == {"data": []} and res["aggregate"]["sensors"] == 3


# ── the policy decision's limits travel with the question ─────────────────────


async def test_a_reader_held_to_a_coarser_resolution_gets_no_right_now_answer():
    adapter = FakeAdapter(latest_handler({F1A: 700.0}))
    res = await ask(
        "Which floor has the highest CO2 right now?", adapter, resolution_clamp_s=3600.0
    )
    assert res is None and adapter.sql == []


async def test_a_clamped_reader_is_not_told_the_minute_a_peak_was_reached():
    adapter = FakeAdapter(narrow_handler(_stats()))
    res = await ask(
        "Which floor had the highest CO2 this week?", adapter, resolution_clamp_s=3600.0
    )
    assert res and "Wed 16 Sep" not in res["formatted_response"]
    assert not any("MIN(`datetime`) AS ts" in sql for sql in adapter.sql)


async def test_an_aggregation_only_reader_is_never_given_a_list_of_rooms():
    adapter = FakeAdapter(narrow_handler(_stats()))
    assert await ask("Where was CO2 highest this week?", adapter, aggregate_only=True) is None
    by_floor = await ask("Which floor had the highest CO2 this week?", adapter, aggregate_only=True)
    assert by_floor is not None  # a floor is an aggregate; a room is not


# ── what the answer quotes is recorded as computed evidence ───────────────────


async def test_the_figures_in_the_answer_are_recorded_as_computed_evidence():
    from orchestrator.services.evidence import computed

    computed.reset()
    adapter = FakeAdapter(narrow_handler(_stats()))
    await ask("Which floor had the highest CO2 this week?", adapter)
    figures = computed.recorded().get("aggregate_lane") or {}
    assert figures.get("2 peak") == 1175.0 and figures.get("2 sensors") == 2.0
    assert figures.get("sensors used") == 5.0
    computed.reset()


def test_a_date_with_no_time_from_the_pipeline_is_read_as_the_start_of_that_day():
    w = al.resolve_window("highest CO2 this week", "2026-09-14", None, TZ, now=NOW)
    assert (w.start, w.end) == ("2026-09-14 00:00:00", "2026-09-18 12:00:00")
