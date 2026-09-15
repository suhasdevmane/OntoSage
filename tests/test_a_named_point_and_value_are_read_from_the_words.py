"""BUG-594: "Set VAV-501-SP to 21 degrees." was answered "I need which writable point and the value"."""

import pytest

from orchestrator.agents.control_agent import point_and_value_from_text

pytestmark = pytest.mark.unit

CAPS = ["urn:x:AHU-F5-SP", "urn:x:LIGHTING-3F-SP", "urn:x:VAV-501-SP"]


def test_a_named_writable_point_and_value_are_read():
    assert point_and_value_from_text("Set VAV-501-SP to 21 degrees.", CAPS) == ("VAV-501-SP", "21")
    assert point_and_value_from_text("set vav 501 sp = 20.5", CAPS) == ("VAV-501-SP", "20.5")


def test_a_generic_request_names_no_point_and_no_value():
    assert point_and_value_from_text("Fix the temperature in here", CAPS) == ("", "")
    assert point_and_value_from_text("Open the windows on floor 3.", CAPS) == ("", "")


def test_a_room_number_is_not_a_setpoint():
    _, value = point_and_value_from_text("Make room 5.01 cooler", CAPS)
    assert value == ""
