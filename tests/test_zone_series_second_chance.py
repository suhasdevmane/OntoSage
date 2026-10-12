"""BUG-1487: a room whose own series is empty for the asked window reads its zone's series instead.

Offline: the graph and the SQL agent are fakes. The rule under test: the second chance fires only
on an EMPTY result for a room bound on its own sensors, and adopts the zone series only if it has
rows, so every answer that already had data is unchanged.
"""

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import sensor_binder
from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

pytestmark = pytest.mark.unit
NS = "http://example.org/b#"


def _zone_rows():
    def b(**kv):
        return {k: {"value": v} for k, v in kv.items()}

    return {
        "results": {
            "bindings": [
                b(
                    sensor=NS + "CO2_Level_Sensor_5.17",
                    label="CO2 Level Sensor installed-node 5.17",
                    uuid="0de774e6-ec3b-46af-b24a-513089931bcd",
                    storage=NS + "database1",
                    cls="https://brickschema.org/schema/Brick#CO2_Level_Sensor",
                    zone=NS + "Zone_5.17",
                    zlabel="HVAC Zone 5.17",
                ),
            ]
        }
    }


async def _run(query):
    return _zone_rows()


RECORD = {
    "status": "bound",
    "basis": "own",
    "scope": "Room 5.17",
    "scope_iri": NS + "Room5.17",
    "sensors": ["ae38bb70-c21d-51fd-827b-6a02005e1c76"],
    "zone": "",
}


def test_zone_alternates_returns_the_zone_instrument_not_already_bound(monkeypatch):
    spec = SimpleNamespace(
        label="co2",
        classes=("CO2_Level_Sensor",),
        catalogued=True,
        matches=lambda classes, text: "CO2_Level_Sensor" in classes,
    )
    monkeypatch.setattr(sensor_binder, "detect_quantities", lambda q, c, b: [spec])
    alts, label = asyncio.run(
        sensor_binder.zone_alternates(RECORD, "highest CO2 in room 5.17", [], "bx", run=_run)
    )
    assert [a.uuid for a in alts] == ["0de774e6-ec3b-46af-b24a-513089931bcd"]
    assert label == "HVAC Zone 5.17"


def test_zone_alternates_does_nothing_for_a_zone_basis_or_unbound_record(monkeypatch):
    monkeypatch.setattr(sensor_binder, "detect_quantities", lambda q, c, b: [object()])
    for rec in ({**RECORD, "basis": "zone"}, {**RECORD, "scope_iri": ""}):
        assert asyncio.run(sensor_binder.zone_alternates(rec, "q", [], "bx", run=_run)) == ([], "")


class _FakeSQL:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch_data_for_uuids(self, uuids, question, storage_map, start, end, meta, **kw):
        self.calls.append((list(uuids), storage_map, start, end))
        return {"success": True, "results": {"data": self.rows}}


def _orchestrator(sql):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    o = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    o.sql_agent = sql
    return o


def _state():
    return SimpleNamespace(
        intermediate_results={
            "sensor_binding": dict(RECORD),
            "concepts": [],
            "sensor_metadata": {},
        },
        building_id="bx",
    )


def test_second_chance_adopts_the_zone_series_only_when_it_has_rows(monkeypatch):
    alt = sensor_binder.BoundSensor(
        iri=NS + "CO2_Level_Sensor_5.17", label="CO2 zone", uuid="zzz-1", storage=NS + "database1"
    )

    async def fake_alts(*a, **k):
        return [alt], "HVAC Zone 5.17"

    monkeypatch.setattr(sensor_binder, "zone_alternates", fake_alts)
    empty = {"success": True, "results": {"data": []}}
    sql = _FakeSQL([{"uuid": "zzz-1", "timestamp": "2025-01-31 10:00:00", "value": 600}])
    st = _state()
    out = asyncio.run(
        _orchestrator(sql)._zone_series_second_chance(
            st, empty, ["ae38"], "q", "2025-01-31 10:00:00", "2025-01-31 16:00:00", None, False
        )
    )
    assert out["results"]["data"] and sql.calls[0][0] == ["zzz-1"]
    assert sql.calls[0][2:] == ("2025-01-31 10:00:00", "2025-01-31 16:00:00")  # the SAME window
    assert st.intermediate_results["sensor_binding"]["basis"] == "zone"

    sql_empty = _FakeSQL([])
    st2 = _state()
    out2 = asyncio.run(
        _orchestrator(sql_empty)._zone_series_second_chance(
            st2, empty, ["ae38"], "q", None, None, None, False
        )
    )
    assert out2 is empty and st2.intermediate_results["sensor_binding"]["basis"] == "own"


def test_second_chance_never_touches_a_result_that_has_rows():
    sql = _FakeSQL([])
    full = {"success": True, "results": {"data": [{"uuid": "ae38", "value": 1}]}}
    out = asyncio.run(
        _orchestrator(sql)._zone_series_second_chance(
            _state(), full, ["ae38"], "q", None, None, None, False
        )
    )
    assert out is full and sql.calls == []


def test_a_zone_aggregate_names_the_room_asked_about_and_its_source(monkeypatch):
    """BUG-1493: 'in HVAC Zone 5.17' answered a question about Room 5.17 and was deleted as off-topic."""
    alt = sensor_binder.BoundSensor(
        iri=NS + "CO2_Level_Sensor_5.17",
        label="CO2 zone",
        uuid="zzz-1",
        storage=NS + "database1",
        type_iri="https://brickschema.org/schema/Brick#CO2_Level_Sensor",
    )

    async def fake_alts(*a, **k):
        return [alt], "HVAC Zone 5.17"

    class _AggSQL(_FakeSQL):
        async def fetch_data_for_uuids(self, uuids, question, storage_map, start, end, meta, **kw):
            self.calls.append((list(uuids), storage_map, start, end, meta))
            return {
                "success": True,
                "results": {"data": []},
                "aggregate_lane": True,
                "formatted_response": "**The highest CO2 in HVAC Zone 5.17 in the period was 862 ppm**.",
            }

    monkeypatch.setattr(sensor_binder, "zone_alternates", fake_alts)
    sql = _AggSQL([])
    empty = {"success": True, "results": {"data": []}}
    out = asyncio.run(
        _orchestrator(sql)._zone_series_second_chance(
            _state(), empty, ["ae38"], "q", None, None, None, False
        )
    )
    first = out["formatted_response"].splitlines()[0]
    assert "in Room 5.17 in the period was 862 ppm" in first
    assert "HVAC Zone 5.17, the HVAC zone that contains it" in out["formatted_response"]
    # the zone sensor's class and declared unit reach the lane (BUG-1489 / BUG-1491)
    meta = sql.calls[0][4]["zzz-1"]
    assert meta["brick_class"].endswith("CO2_Level_Sensor") and meta["unit"] == "ppm"


def test_second_chance_treats_an_aggregate_lane_answer_as_an_answer():
    """An aggregate-lane answer has no rows by design; it must not look 'empty'."""
    sql = _FakeSQL([])
    agg = {
        "success": True,
        "results": {"data": []},
        "aggregate_lane": True,
        "formatted_response": "mean 22.1",
    }
    out = asyncio.run(
        _orchestrator(sql)._zone_series_second_chance(
            _state(), agg, ["ae38"], "q", None, None, None, False
        )
    )
    assert out is agg and sql.calls == []


def test_wide_adapter_keeps_an_iso_window_instead_of_reading_the_last_30_days():
    a = MySQLAdapter.__new__(MySQLAdapter)
    a._columns_cache = {"0de774e6-ec3b-46af-b24a-513089931bcd"}
    a._wide_table = lambda: "sensor_data"
    sql = a.build_timeseries_query(
        ["0de774e6-ec3b-46af-b24a-513089931bcd"],
        "datetime",
        "2025-01-31T10:00:00",
        "2025-01-31T16:00:00",
    )
    assert "'2025-01-31 10:00:00'" in sql and "'2025-01-31 16:00:00'" in sql
    assert "INTERVAL 30 DAY" not in sql
