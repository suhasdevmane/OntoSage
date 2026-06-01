"""Phase 15C — ConversationState persistence round-trip.

Phase 14A added `personas: List[str]` to ConversationState.  Redis stores the
state as JSON via `state.dict() → json.dumps`; on load it deserializes back to
ConversationState.  These tests pin the round-trip so a serializer regression
(e.g. someone forgetting `default_factory=list` or adding a non-JSON-safe
default) breaks loudly rather than silently dropping fields.

We do NOT spin up Redis here — we exercise the Pydantic boundary directly,
which is the actual contract that can break.  Redis just shuttles bytes.
"""

from __future__ import annotations

import json

from shared.models import ConversationState, Message


def _round_trip(state: ConversationState) -> ConversationState:
    """Simulate Redis save+load: state -> dict -> json -> dict -> state."""
    state_dict = state.dict()
    state_json = json.dumps(state_dict, default=str)
    loaded_dict = json.loads(state_json)
    return ConversationState(**loaded_dict)


# ─────────────────────────────────────────────────────────────────────────────
# Single-persona round-trip (the legacy path)
# ─────────────────────────────────────────────────────────────────────────────


def test_single_persona_survives_round_trip():
    state = ConversationState(
        conversation_id="rt-1",
        user_id="alice",
        user_message="hi",
        building_id="bldg1",
        persona="facility_manager",
        messages=[Message(role="user", content="hi")],
    )
    out = _round_trip(state)
    assert out.persona == "facility_manager"
    assert out.personas == []           # default factory empty list
    assert out.building_id == "bldg1"


def test_personas_list_survives_round_trip():
    """Phase 14A — multi-persona list must round-trip intact."""
    state = ConversationState(
        conversation_id="rt-2",
        user_id="bob",
        user_message="test",
        building_id="bldg1",
        persona="facility_manager",
        personas=["facility_manager", "researcher", "occupant"],
        messages=[Message(role="user", content="test")],
    )
    out = _round_trip(state)
    assert out.personas == ["facility_manager", "researcher", "occupant"]
    assert out.persona == "facility_manager"


def test_empty_personas_round_trips_as_empty():
    state = ConversationState(
        conversation_id="rt-3",
        user_id="carol",
        user_message="test",
        building_id="bldg1",
        messages=[Message(role="user", content="test")],
    )
    out = _round_trip(state)
    assert out.personas == []
    assert isinstance(out.personas, list)


def test_personas_list_order_preserved():
    state = ConversationState(
        conversation_id="rt-4",
        user_id="dave",
        user_message="test",
        personas=["occupant", "researcher", "facility_manager"],
    )
    out = _round_trip(state)
    # Order must match — blending semantics depend on it.
    assert out.personas == ["occupant", "researcher", "facility_manager"]


def test_personas_with_intermediate_results_round_trip():
    """Real-world: state carries both personas AND intermediate_results
    (route_decision, persona_blended, etc.) — both must survive together."""
    state = ConversationState(
        conversation_id="rt-5",
        user_id="eve",
        user_message="test",
        personas=["facility_manager", "sustainability_officer"],
        intermediate_results={
            "route_decision": {
                "intent_from_dialogue": "sensor_data",
                "final_node": "sparql",
                "overrides_applied": [],
                "decision_source": "registry",
            },
            "persona_blended": {
                "personas": ["facility_manager", "sustainability_officer"],
                "top_domains": ["ENERGY", "THERMAL"],
                "complexity": "MODERATE",
                "clarification_threshold": 0.5,
            },
        },
    )
    out = _round_trip(state)
    assert out.personas == ["facility_manager", "sustainability_officer"]
    assert out.intermediate_results["route_decision"]["final_node"] == "sparql"
    assert out.intermediate_results["persona_blended"]["top_domains"] == ["ENERGY", "THERMAL"]


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compat: legacy state JSON without personas must still load
# ─────────────────────────────────────────────────────────────────────────────


def test_legacy_state_json_without_personas_loads():
    """Conversations saved BEFORE Phase 14A don't have the `personas` field.
    Loading them must succeed with personas defaulting to [].
    """
    legacy_dict = {
        "conversation_id": "legacy-1",
        "user_id": "old_user",
        "user_message": "test",
        "building_id": "bldg1",
        "persona": "occupant",
        "messages": [],
        # NOTE: no `personas` key
    }
    state = ConversationState(**legacy_dict)
    assert state.persona == "occupant"
    assert state.personas == []


def test_unknown_persona_string_round_trips():
    """Phase 14A removed Literal constraint on persona.  Unknown strings
    must round-trip without ValidationError.  The PersonaRegistry resolves
    them to 'general' at lookup time."""
    state = ConversationState(
        conversation_id="rt-7",
        user_id="mallory",
        user_message="test",
        persona="custom_yaml_persona_xyz",
    )
    out = _round_trip(state)
    assert out.persona == "custom_yaml_persona_xyz"
