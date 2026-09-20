# -*- coding: utf-8 -*-
"""The outdoor readings a building records, and when (2D-16 wave 2).

"How is the weather outside now?" was answered with "Which measurement or record do you mean by
**weather**?" while the graph types five weather-feed points with Brick's outdoor sensor classes.
The honest answer is "no forecast is held; here is what the outdoor sensors last recorded, and
when". Everything is offline: the graph and the stores are fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import clarification as cl
from orchestrator.services import outdoor_readings as orr

pytestmark = pytest.mark.unit

BRICK = "https://brickschema.org/schema/Brick#"
ROWS = [
    {
        "cls": BRICK + "Wind_Speed_Sensor",
        "uuid": "fc0e05a6-5606-36ab-d512-817cf3fdbe9f",
        "store": "http://x/abacws#database1",
    },
    {
        "cls": BRICK + "Outside_Air_Temperature_Sensor",
        "uuid": "89d4f4fe-8964-0587-a47c-46e18340908a",
        "store": "http://x/abacws#database1",
        "unit": "°C",
    },
    {
        "cls": "http://ontosage.org/capabilities#Rainfall_Sensor",
        "uuid": "76542d81-95bc-5090-881b-345bc65a832a",
        "store": "http://x/abacws#iaq_data",
    },
    {"cls": BRICK + "Outdoor_Area", "uuid": "11111111-1111-1111-1111-111111111111"},
    {"cls": BRICK + "Wind_Speed_Sensor", "uuid": "fc0e05a6-5606-36ab-d512-817cf3fdbe9f"},
    {"cls": BRICK + "Solar_Irradiance_Sensor", "uuid": "not a uuid; DROP TABLE x"},
]


def test_the_points_query_names_only_outdoor_classes_and_reads_the_reference_the_lanes_read():
    q = orr.points_query()
    for cls, _ in orr.OUTDOOR_POINTS:
        assert cls in q
    assert "ref:hasTimeseriesId" in q and "ref:storedAt" in q
    assert "abacws" not in q.lower(), "no building literal in a core service"


def test_rows_become_distinct_valid_points_in_a_stable_order():
    points = orr.parse_points(ROWS)
    assert [p["phrase"] for p in points] == ["outdoor temperature", "wind speed", "rainfall"]
    assert all(orr._UUID.match(p["uuid"]) for p in points)
    assert points[0]["unit"] == "°C" and points[1]["store"].endswith("#database1")


def test_a_row_that_is_not_an_outdoor_class_or_has_a_bad_id_is_left_out():
    assert (
        orr.parse_points(
            [{"cls": BRICK + "Outdoor_Area", "uuid": "22222222-2222-2222-2222-222222222222"}]
        )
        == []
    )
    assert orr.parse_points([{"cls": BRICK + "Wind_Speed_Sensor", "uuid": "x'; DROP"}]) == []


class _Adapter:
    """Answers the narrow shape (timestamp, uuid, value) or, when it builds no query, the wide one."""

    def __init__(self, rows, narrow=True, ok=True):
        self._rows, self._narrow, self._ok = rows, narrow, ok
        self.queries = []

    def build_timeseries_query(self, uuids, ts_col, start_date, end_date, limit=1000):
        assert limit == 1 and end_date is None
        return f"NARROW {uuids[0]}" if self._narrow else None

    async def execute_query(self, query):
        self.queries.append(query)
        return SimpleNamespace(success=self._ok, data=self._rows)


def _run(coro):
    return asyncio.run(coro)


POINT = {
    "cls": "Outside_Air_Temperature_Sensor",
    "phrase": "outdoor temperature",
    "uuid": "89d4f4fe-8964-0587-a47c-46e18340908a",
    "store": "s",
    "unit": "°C",
}


def test_a_narrow_store_is_read_through_its_own_query_and_the_time_is_shown():
    adapter = _Adapter(
        [{"timestamp": "2026-09-19 03:50:10", "uuid": POINT["uuid"], "value": 12.34}]
    )
    r = _run(orr.read_point(POINT, adapter, "Datetime", tz_name=None))
    assert r == cl.OutdoorReading("outdoor temperature", 12.34, "°C", "03:50 on 19 Sep")
    assert adapter.queries == [f"NARROW {POINT['uuid']}"]


def test_a_wide_store_gets_a_discovered_table_and_still_returns_a_time():
    schema = SimpleNamespace(
        tables=["weather_wide"], columns={"weather_wide": [(POINT["uuid"], "double")]}
    )
    adapter = _Adapter([{"timestamp": "2026-09-19 03:50:10", "value": 12.0}], narrow=False)
    adapter._schema = schema
    r = _run(orr.read_point(POINT, adapter, "Datetime"))
    assert r.value == 12.0 and r.when == "03:50 on 19 Sep"
    assert "`weather_wide`" in adapter.queries[0] and POINT["uuid"] in adapter.queries[0]


def test_building_time_is_used_for_the_time_shown():
    adapter = _Adapter([{"timestamp": "2026-07-01 12:00:00", "value": 20}])
    r = _run(orr.read_point(POINT, adapter, "Datetime", tz_name="Europe/London"))
    assert r.when == "13:00 on 1 Jul", "stores are UTC; the reader sees building time"


@pytest.mark.parametrize(
    "adapter",
    [_Adapter([], ok=True), _Adapter([{"value": None}]), _Adapter([{"value": 1}], ok=False)],
)
def test_a_point_that_cannot_be_read_is_left_out_never_guessed(adapter):
    assert _run(orr.read_point(POINT, adapter, "Datetime")) is None


def test_an_adapter_that_raises_does_not_raise_out():
    class Boom(_Adapter):
        async def execute_query(self, query):
            raise RuntimeError("store down")

    assert _run(orr.read_point(POINT, Boom([]), "Datetime")) is None


def test_the_unit_falls_back_to_the_modality_table_and_stays_blank_when_none_declares_one(
    monkeypatch,
):
    from orchestrator.services import modality_units

    monkeypatch.setattr(modality_units, "unit_for_sensor", lambda *_a, **_k: "m/s")
    point = dict(POINT, unit="", cls="Wind_Speed_Sensor", phrase="wind speed")
    adapter = _Adapter([{"timestamp": "2026-09-19 03:45:00", "value": 4.5}])
    assert _run(orr.read_point(point, adapter, "Datetime")).unit == "m/s"
    monkeypatch.setattr(modality_units, "unit_for_sensor", lambda *_a, **_k: "")
    assert _run(orr.read_point(point, adapter, "Datetime")).unit == ""


def test_the_whole_fetch_reads_every_declared_point_through_its_own_store():
    async def select(query, limit=1000):
        return {"ok": True, "rows": ROWS}

    stores = {
        "http://x/abacws#database1": _Adapter(
            [{"timestamp": "2026-09-19 03:50:10", "value": 12.3}]
        ),
        "http://x/abacws#iaq_data": None,  # a store with no adapter registered
    }
    out = _run(orr.fetch_outdoor_readings(run_select=select, adapter_for=lambda s: stores.get(s)))
    assert [r.label for r in out] == ["outdoor temperature", "wind speed"]


def test_an_unreadable_graph_gives_no_readings_and_no_error():
    async def select(query, limit=1000):
        return {"ok": False}

    assert _run(orr.fetch_outdoor_readings(run_select=select, adapter_for=lambda s: None)) == []

    async def boom(query, limit=1000):
        raise ConnectionError("graph down")

    assert _run(orr.fetch_outdoor_readings(run_select=boom, adapter_for=lambda s: None)) == []


def test_a_building_with_no_outdoor_points_gets_the_plain_no_forecast_statement():
    async def select(query, limit=1000):
        return {"ok": True, "rows": []}

    readings = _run(orr.fetch_outdoor_readings(run_select=select, adapter_for=lambda s: None))
    kind, text = cl.compose(
        building="B", question="how is the weather outside now?", outdoor=readings
    )
    assert kind == cl.KIND_WEATHER and "couldn't read B's outdoor sensors" in text
