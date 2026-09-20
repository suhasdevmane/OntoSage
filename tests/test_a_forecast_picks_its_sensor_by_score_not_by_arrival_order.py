# -*- coding: utf-8 -*-
"""A forecast question chooses the same sensor every time it is asked (B38, BUG-826).

"What will the temperature be tomorrow in Room 2.01?" forecast in one run and was refused in the
next. Part of the cause is here: `_select_primary_sensor` returned the FIRST sensor in the
metadata dict whose label shared any word longer than three letters with the question -- and
"room" is in the label of every sensor in the room (a door contact, a noise meter), so which one
was forecast depended on the order the dict happened to hold them. A door contact has no
temperature to forecast.
"""

from __future__ import annotations

import pytest

from orchestrator.agents.forecast_agent import ForecastAgent

pytestmark = pytest.mark.unit

U_DOOR = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
U_TEMP = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
U_NOISE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

META = {
    U_DOOR: {"label": "Room 2.01 door_contact"},
    U_NOISE: {"label": "Room 2.01 noise [dB]"},
    U_TEMP: {"label": "Air Temperature Sensor installed-node 2.01"},
}
QUESTION = "What will the temperature be tomorrow in Room 2.01?"


def _records(*uuids):
    return [{"uuid": u, "datetime": "2026-09-18 10:00:00", "value": 21.0} for u in uuids]


def test_the_temperature_sensor_is_chosen_whatever_the_dict_order():
    agent = ForecastAgent()
    records = _records(U_DOOR, U_NOISE, U_TEMP)
    for order in ([U_DOOR, U_NOISE, U_TEMP], [U_TEMP, U_NOISE, U_DOOR], [U_NOISE, U_DOOR, U_TEMP]):
        meta = {u: META[u] for u in order}
        uuid, label = agent._select_primary_sensor(records, meta, QUESTION)
        assert uuid == U_TEMP and "Temperature" in label


def test_a_sensor_with_no_data_is_never_chosen():
    agent = ForecastAgent()
    uuid, _ = agent._select_primary_sensor(_records(U_NOISE), META, "noise in Room 2.01 tomorrow")
    assert uuid == U_NOISE


def test_more_matching_words_beat_an_earlier_partial_match():
    agent = ForecastAgent()
    meta = {
        U_DOOR: {"label": "Room 2.01 humidity"},
        U_TEMP: {"label": "Room 2.01 air temperature"},
    }
    uuid, _ = agent._select_primary_sensor(
        _records(U_DOOR, U_TEMP), meta, "forecast the air temperature in Room 2.01"
    )
    assert uuid == U_TEMP


def test_with_no_discriminating_word_the_sensor_with_most_records_wins():
    agent = ForecastAgent()
    records = _records(U_DOOR) + _records(U_TEMP, U_TEMP, U_TEMP)
    uuid, _ = agent._select_primary_sensor(records, META, "what will it be tomorrow?")
    assert uuid == U_TEMP
