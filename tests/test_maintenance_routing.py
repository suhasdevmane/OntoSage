"""Test maintenance schedule query routing (Task 2 fix).

Validates that:
1. Maintenance schedule queries bypass the KB capability router (is_data_query).
2. Maintenance schedule keywords trigger the dialogue agent override.
3. Non-maintenance queries are not affected.
"""

import pytest


MAINTENANCE_SCHEDULE_QUERIES = [
    "What maintenance work is scheduled this week?",
    "What maintenance is planned for next month?",
    "Show me all open maintenance tickets",
    "List outstanding maintenance tasks",
    "Any planned maintenance on floor 3?",
]

NON_MAINTENANCE_QUERIES = [
    "the light in room 3.01 is broken",
    "What sensors are installed?",
    "Show me floor 2 layout",
    "I am scheduled for a meeting tomorrow",
    "She is scheduled for an appointment",
]


def _router_would_bypass(query: str) -> bool:
    from orchestrator.services.semantic_router import SemanticRouter

    return SemanticRouter.is_data_query(query)


def _dialogue_would_override(query: str) -> bool:
    from orchestrator.agents.dialogue_agent import _MAINTENANCE_SCHEDULE_KWS

    q = query.lower()
    return any(kw in q for kw in _MAINTENANCE_SCHEDULE_KWS)


@pytest.mark.unit
def test_maintenance_schedule_bypasses_kb():
    """Maintenance schedule queries should bypass KB router (is_data_query check)."""
    for q in MAINTENANCE_SCHEDULE_QUERIES:
        assert _router_would_bypass(q), f"KB not bypassed for: {q!r}"


@pytest.mark.unit
def test_non_maintenance_not_bypassed():
    """Non-maintenance queries should not be incorrectly bypassed."""
    assert not _router_would_bypass("the light in room 3.01 is broken")


@pytest.mark.unit
def test_maintenance_schedule_kws_exported():
    """_MAINTENANCE_SCHEDULE_KWS should be defined at module level."""
    from orchestrator.agents.dialogue_agent import _MAINTENANCE_SCHEDULE_KWS

    assert len(_MAINTENANCE_SCHEDULE_KWS) >= 4


@pytest.mark.unit
def test_maintenance_override_fires_on_schedule_queries():
    """Dialogue agent should override intent to maintenance for schedule queries."""
    for q in MAINTENANCE_SCHEDULE_QUERIES:
        assert _dialogue_would_override(q), f"Override not triggered for: {q!r}"


@pytest.mark.unit
def test_false_positive_probe_meeting_not_maintenance():
    """Non-maintenance queries with 'scheduled for' should NOT trigger override."""
    probes = [
        "I am scheduled for a meeting tomorrow",
        "She is scheduled for an appointment",
        "the light in room 3.01 is broken",
    ]
    for q in probes:
        assert not _dialogue_would_override(q), f"False positive maintenance override for: {q!r}"


# ── Room/floor locator + measurement keyword bypass (fix 2026-06-12) ──────────
# "What is the latest CO2 in room 5.01?" was hijacked by a high-confidence
# capability-KB override (OpenAI embedding score 0.684 > override_min 0.60,
# thresholds calibrated for local MiniLM). Natural reading questions with a
# room/floor locator + measurement word must bypass the KB router.

_DATA_LOCATOR_QUERIES = [
    "What is the latest CO2 in room 5.01?",
    "what is the current temperature in room 3.02",
    "humidity reading in rm 2.11 please",
    "what is the latest co2 on floor 3?",
    "energy usage for floor 5 today",
]

_NON_DATA_LOCATOR_QUERIES = [
    # Locator but NO measurement word — must NOT bypass (wayfinding/capability)
    "how do I get to room 5.01 from reception",
    "is room 5.01 available this afternoon",
    "who sits in room 3.02",
    # Measurement word but NO locator — falls through to LLM classification
    "is the building energy efficient?",
]


@pytest.mark.unit
def test_room_floor_locator_with_measurement_bypasses_kb():
    for q in _DATA_LOCATOR_QUERIES:
        assert _router_would_bypass(q), f"data question not bypassed: {q!r}"


@pytest.mark.unit
def test_locator_without_measurement_does_not_bypass():
    for q in _NON_DATA_LOCATOR_QUERIES:
        assert not _router_would_bypass(q), f"non-data question wrongly bypassed: {q!r}"


# ── Control-command guards: questions are not commands (fix 2026-06-12) ───────


def _is_control(query: str) -> bool:
    from orchestrator.services.semantic_router import SemanticRouter

    return SemanticRouter.is_control_command(query)


@pytest.mark.unit
def test_capability_and_advice_questions_are_not_control_commands():
    for q in [
        "Can the building automatically close the blinds when it gets sunny?",
        "Could the system detect a water leak by itself?",
        "Should I open the windows in room 5.08 to improve air quality?",
        "Would it help to turn down the heating overnight?",
        "Do you recommend opening the windows now?",
    ]:
        assert not _is_control(q), f"question treated as command: {q!r}"


@pytest.mark.unit
def test_real_commands_still_detected():
    for q in [
        "Open the windows on floor 3.",
        "Turn off the HVAC in Zone 5.28.",
        "Can you please unlock the main door so everyone can get out",
        "Make sure all the doors are locked tonight",
    ]:
        assert _is_control(q), f"command not detected: {q!r}"
