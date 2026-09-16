"""A sensor's band comes from its most specific class (2026-09-16).

Boiler flow water is a Leaving_Water_Temperature_Sensor, which is a Water_Temperature_Sensor
and also a Temperature_Sensor — and Temperature_Sensor declares the AIR band, -30..70 degC. The
loader sampled one of the matching classes, so 1,035 readings of an ordinary 72 degC heating
flow were announced to the reader as "physically impossible".
"""

import asyncio

import pytest

from orchestrator.services import physical_bands as mod

pytestmark = pytest.mark.unit


def _binding(uuid, kind, lo, hi, depth, unit="degC"):
    return {
        "uuid": {"value": uuid},
        "kind": {"value": f"http://ontosage.org/capabilities#{kind}"},
        "lo": {"value": str(lo)},
        "hi": {"value": str(hi)},
        "unit": {"value": unit},
        "depth": {"value": str(depth)},
    }


def _bands(bindings):
    async def _exec(_q):
        return {"results": {"bindings": bindings}}

    return asyncio.run(mod.PhysicalBands(_exec)._load())


def test_the_deeper_class_owns_the_band_whatever_the_row_order():
    air = _binding("u1", "AirTemperature", -30, 70, 2)
    water = _binding("u1", "WaterTemperature", -10, 120, 4)
    for rows in ([air, water], [water, air]):
        band = _bands(rows)["u1"]
        assert (band.kind, band.low, band.high) == ("WaterTemperature", -10.0, 120.0)


def test_a_single_declaration_is_used_as_is():
    band = _bands([_binding("u2", "AirTemperature", -30, 70, 2)])["u2"]
    assert band.kind == "AirTemperature" and band.holds(21.5) and not band.holds(95.0)


def test_a_heating_flow_is_ordinary_water_and_impossible_air():
    water = _bands([_binding("u3", "WaterTemperature", -10, 120, 4)])["u3"]
    air = _bands([_binding("u4", "AirTemperature", -30, 70, 2)])["u4"]
    assert water.holds(72.0) and not air.holds(72.0)


def test_the_query_asks_for_depth_and_does_not_sample_the_kind():
    assert "COUNT(DISTINCT ?anc) AS ?depth" in mod._BANDS_BY_UUID
    assert "SAMPLE(?m)" not in mod._BANDS_BY_UUID
