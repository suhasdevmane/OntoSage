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
    "What is scheduled for building maintenance?",
    "Any planned maintenance on floor 3?",
]

NON_MAINTENANCE_QUERIES = [
    "the light in room 3.01 is broken",
    "What sensors are installed?",
    "Show me floor 2 layout",
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
