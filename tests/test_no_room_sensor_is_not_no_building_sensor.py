# -*- coding: utf-8 -*-
"""A ranking decline must say what was measured: no ROOM has the sensor, not no BUILDING.

The deliberation admission gate counts sensors per space. Energy submeters sit on floors, so
"rank rooms by energy" declined with "No energy_submeter sensors are modelled with data for this
building" while those meters were fresh to the minute.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow._orchestrator import _no_room_sensor_text

pytestmark = pytest.mark.unit


def test_a_modality_held_outside_rooms_is_not_called_absent():
    text = _no_room_sensor_text(["energy_submeter"], {"energy_submeter": 48, "co2": 300})
    assert "No single room has its own energy submeter sensor" in text
    assert "48 energy submeter points" in text
    assert "modelled with data for this building" not in text
    assert "floor" in text


def test_a_modality_the_building_lacks_keeps_the_building_wide_sentence():
    text = _no_room_sensor_text(["radon"], {"co2": 300})
    assert text.startswith("**No radon sensors are modelled with data for this building**")


def test_unreadable_counts_fall_back_to_the_old_sentence():
    assert "modelled with data" in _no_room_sensor_text(["energy_submeter"], None)


def test_two_modalities_only_one_held_are_each_named_on_their_own_terms():
    text = _no_room_sensor_text(["energy_submeter", "radon"], {"energy_submeter": 48})
    assert "No single room has its own energy submeter sensor" in text
    assert "**No radon sensors are modelled with data for this building**" in text
    assert "energy submeter sensors are modelled" not in text
