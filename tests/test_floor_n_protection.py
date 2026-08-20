"""
Floor-N hijack protection tests — spec §15.2.

These queries each contain the word "floor" or "floors" but must NOT be routed
to the floor_plan node. They are data queries with floor as a *location qualifier*,
not requests to display the floor plan.

These were fixed in commits 4995a7f and a432d57 (2026-05-20). The semantic
capability router introduced in this refactor must NOT regress them.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


def test_temperature_floor_3_routes_to_sensor_data(chat_client, fresh_session_id):
    """'What is the temperature on floor 3?' → sensor_data, not floor_plan."""
    resp = chat_client.chat("What is the temperature on floor 3?", session_id=fresh_session_id)
    assert resp.success
    # Must NOT be the floor_plan menu
    assert not resp.contains(
        "I have floor plans for"
    ), "Routing regressed — floor_plan stole a sensor_data query (see §15.2)"
    # Should contain sensor reading markers
    assert resp.contains_any(
        "°c", "temperature", "sensor", "floor 3", "reading"
    ), f"Expected sensor reading, got: {resp.response_text[:200]}"


def test_analytics_floor_2_routes_to_analytics(chat_client, fresh_session_id):
    """'Show me analytics for floor 2 sensors' → analytics, not floor_plan."""
    resp = chat_client.chat("Show me analytics for floor 2 sensors", session_id=fresh_session_id)
    assert resp.success
    assert not resp.contains(
        "I have floor plans for"
    ), "Routing regressed — floor_plan stole an analytics query (see §15.2)"
    assert resp.contains_any(
        "sensor", "co2", "ppm", "floor 2", "second floor", "compliance", "analytics"
    ), f"Expected analytics response, got: {resp.response_text[:200]}"


def test_sensor_count_floor_1_routes_to_discovery(chat_client, fresh_session_id):
    """'How many CO2 sensors are on floor 1?' → sparql/discovery, not floor_plan."""
    resp = chat_client.chat("How many CO2 sensors are on floor 1?", session_id=fresh_session_id)
    assert resp.success
    assert not resp.contains(
        "I have floor plans for"
    ), "Routing regressed — floor_plan stole a discovery query (see §15.2)"
    # Discovery responses cite counts and types
    assert resp.contains_any(
        "sensor", "co2", "floor 1", "count", "first floor"
    ), f"Expected discovery response, got: {resp.response_text[:200]}"


def test_compare_floor_1_vs_3_routes_to_comparison(chat_client, fresh_session_id):
    """'Compare energy usage on floor 1 vs floor 3' → comparison/analytics, not floor_plan."""
    resp = chat_client.chat(
        "Compare energy usage on floor 1 vs floor 3", session_id=fresh_session_id
    )
    assert resp.success
    assert not resp.contains(
        "I have floor plans for"
    ), "Routing regressed — floor_plan stole a comparison query (see §15.2)"
    assert resp.contains_any(
        "energy", "consumption", "floor 1", "floor 3", "compare", "compliance"
    ), f"Expected comparison response, got: {resp.response_text[:200]}"
