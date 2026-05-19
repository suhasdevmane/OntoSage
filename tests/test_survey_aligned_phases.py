"""
Tests for Phase 0-5 survey-aligned implementation.

Covers:
  Phase 0 — CapabilityKB / CapabilityAgent
  Phase 1 — VerifierAgent
  Phase 2 — SelfCorrectionPolicy
  Phase 3 — PersonaRegistry
  Phase 4 — dialogue_state on ConversationState
  Phase 5 — agent_memory failure/correction stores
  G1 six-tuple — _derive_g1_taxonomy
  Workflow wiring — capability node registered and routed
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Phase 0: CapabilityKB ────────────────────────────────────────────────────

class TestCapabilitySchema:
    def test_from_yaml_loads_bldg1(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        assert kb.building_info.id == "bldg1"
        assert kb.building_info.name == "Abacws Building"
        assert len(kb.capabilities) >= 10

    def test_building_property_alias(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        # .building is an alias for .building_info
        assert kb.building is kb.building_info

    def test_search_fire_safety(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        results = kb.search("fire alarm evacuation")
        assert len(results) >= 1
        cats = [e.category for e in results]
        assert "FIRE_SAFETY" in cats

    def test_search_returns_empty_for_unrelated_query(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        results = kb.search("xenon plasma reactor antimatter")
        assert results == []

    def test_search_max_results_cap(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        # A broad query matching many entries should still cap at max_results
        results = kb.search("building", max_results=2)
        assert len(results) <= 2

    def test_search_hvac_keywords(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        kb = CapabilityKB.from_yaml(yaml_path)
        results = kb.search("heating zone thermostat temperature control")
        cats = [e.category for e in results]
        assert "HVAC" in cats

    def test_building_info_key_not_picked_up_as_multi_building(self):
        from shared.capability_schema import CapabilityKB
        yaml_path = Path(__file__).resolve().parents[1] / "input" / "bldg1" / "capability.yaml"
        import yaml
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        # Must NOT have a bare 'building:' key (would be picked up by multi_building_manager)
        assert "building" not in raw, "YAML must use 'building_info:', not 'building:'"
        assert "building_info" in raw


# ─── Phase 0: CapabilityAgent ─────────────────────────────────────────────────

def _make_state(query: str, building_id: str = "bldg1") -> Any:
    """Build a minimal ConversationState for capability testing."""
    from shared.models import ConversationState, Message
    state = ConversationState(
        conversation_id="test-session",
        user_message=query,
        building_id=building_id,
    )
    state.messages.append(Message(role="user", content=query))
    state.current_intent = "capability"
    return state


class TestCapabilityAgent:
    def test_answers_fire_safety_query(self):
        from orchestrator.agents.capability_agent import CapabilityAgent
        agent = CapabilityAgent()
        state = _make_state("What are the fire safety features?")
        result_state = asyncio.get_event_loop().run_until_complete(agent.answer(state))
        cap = result_state.intermediate_results.get("capability_result", {})
        assert cap.get("success") is True
        assert "FIRE_SAFETY" in cap.get("matched_categories", [])
        assert "fire" in cap["response"].lower() or "sprinkler" in cap["response"].lower()

    def test_answers_power_outage_query(self):
        from orchestrator.agents.capability_agent import CapabilityAgent
        agent = CapabilityAgent()
        state = _make_state("What happens during a power outage?")
        result_state = asyncio.get_event_loop().run_until_complete(agent.answer(state))
        cap = result_state.intermediate_results.get("capability_result", {})
        assert cap.get("success") is True
        assert "POWER" in cap.get("matched_categories", [])

    def test_no_match_returns_explicit_boundary(self):
        from orchestrator.agents.capability_agent import CapabilityAgent, _KB_CACHE
        from shared.capability_schema import CapabilityKB, BuildingInfo
        from shared.models import ConversationState, Message
        # Build an empty KB and inject it into the cache
        empty_kb = CapabilityKB(
            building_info=BuildingInfo(id="bldg_test", name="Test Building"),
            capabilities=[],
        )
        _KB_CACHE["bldg_test"] = empty_kb
        agent = CapabilityAgent()
        state = ConversationState(
            conversation_id="nomatch-test",
            user_message="anything at all",
            building_id="bldg_test",
        )
        state.messages.append(Message(role="user", content="anything at all"))
        state.current_intent = "capability"
        result_state = asyncio.get_event_loop().run_until_complete(agent.answer(state))
        cap = result_state.intermediate_results.get("capability_result", {})
        assert cap.get("success") is True
        assert cap.get("provenance") == "kb_no_match"
        # Cleanup cache to avoid affecting other tests
        _KB_CACHE.pop("bldg_test", None)

    def test_missing_building_returns_no_kb_message(self):
        from orchestrator.agents.capability_agent import CapabilityAgent
        agent = CapabilityAgent()
        state = _make_state("Fire exits?", building_id="bldg999")
        result_state = asyncio.get_event_loop().run_until_complete(agent.answer(state))
        cap = result_state.intermediate_results.get("capability_result", {})
        assert cap.get("success") is False
        assert cap.get("provenance") == "no_kb"

    def test_response_includes_provenance_source(self):
        from orchestrator.agents.capability_agent import CapabilityAgent
        agent = CapabilityAgent()
        state = _make_state("How does access control work?")
        result_state = asyncio.get_event_loop().run_until_complete(agent.answer(state))
        cap = result_state.intermediate_results.get("capability_result", {})
        assert cap.get("provenance") == "capability_kb"


# ─── Phase 1: VerifierAgent ───────────────────────────────────────────────────

def _make_verify_state(
    intent: str = "sensor_data",
    sparql_bindings: Optional[List] = None,
    sql_rows: int = 0,
    analytics_success: bool = False,
    capability_success: bool = False,
    time_range: Optional[Dict] = None,
) -> Any:
    from shared.models import ConversationState, Message
    state = ConversationState(
        conversation_id="verify-test",
        user_message="test query",
        building_id="bldg1",
    )
    state.messages.append(Message(role="user", content="test query"))
    state.current_intent = intent
    if sparql_bindings is not None:
        state.intermediate_results["sparql_result"] = {
            "success": True,
            "results": {"results": {"bindings": sparql_bindings}},
        }
    if sql_rows > 0:
        state.intermediate_results["sql_result"] = {
            "data": [{"ts": i, "val": float(i)} for i in range(sql_rows)]
        }
    if analytics_success:
        state.intermediate_results["analytics_result"] = {"success": True, "output": "42°C"}
    if capability_success:
        state.intermediate_results["capability_result"] = {"success": True, "response": "OK"}
    if time_range:
        state.intermediate_results["time_range"] = time_range
    return state


class TestVerifierAgent:
    def test_grounded_from_capability_kb(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        state = _make_verify_state(intent="capability", capability_success=True)
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["grounded"] is True
        assert v["source"] == "capability_kb"
        assert v["confidence"] >= 0.9

    def test_grounded_from_sql(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        state = _make_verify_state(intent="sensor_data", sql_rows=5)
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["grounded"] is True
        assert v["source"] == "sql"

    def test_grounded_from_sparql_only(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        binding = [{"sensor": {"value": "uuid-123"}}]
        state = _make_verify_state(intent="discovery", sparql_bindings=binding)
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["grounded"] is True
        assert v["source"] == "sparql"

    def test_ungrounded_when_no_data(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        state = _make_verify_state(intent="sensor_data")
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["grounded"] is False
        assert v["source"] == "none"
        assert "time_series_data" in v["missing"]

    def test_time_window_populated_from_time_range(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        state = _make_verify_state(
            intent="sensor_data",
            sql_rows=3,
            time_range={"start": "2026-05-01", "end": "2026-05-02"},
        )
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["time_window"] is not None
        assert "2026-05-01" in v["time_window"]

    def test_analytics_grounded_at_correct_confidence(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        agent = VerifierAgent()
        state = _make_verify_state(intent="analytics", analytics_success=True)
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        v = result.intermediate_results["verification"]
        assert v["grounded"] is True
        assert v["source"] == "analytics"
        assert 0.8 <= v["confidence"] <= 1.0

    def test_verifier_does_not_raise_on_empty_state(self):
        from orchestrator.agents.verifier_agent import VerifierAgent
        from shared.models import ConversationState
        agent = VerifierAgent()
        state = ConversationState(
            conversation_id="empty",
            user_message="test",
            building_id="bldg1",
        )
        # Should not raise
        result = asyncio.get_event_loop().run_until_complete(agent.verify(state))
        assert "verification" in result.intermediate_results


# ─── Phase 2: SelfCorrectionPolicy ───────────────────────────────────────────

class TestSelfCorrectionPolicy:
    def test_importable(self):
        from orchestrator.services.self_correction_policy import SelfCorrectionPolicy, MAX_ATTEMPTS
        p = SelfCorrectionPolicy()
        assert MAX_ATTEMPTS >= 1

    def test_repair_succeeds_on_first_attempt(self):
        from orchestrator.services.self_correction_policy import SelfCorrectionPolicy
        from shared.models import ConversationState
        p = SelfCorrectionPolicy()
        state = ConversationState(conversation_id="s1", user_message="test", building_id="bldg1")
        call_count = {"n": 0}

        async def attempt(s, attempt_number, last_error):
            call_count["n"] += 1
            s.intermediate_results["test"] = "fixed"
            return s

        def success(s):
            return s.intermediate_results.get("test") == "fixed"

        def error(s):
            return s.intermediate_results.get("error_detail", "")

        result = asyncio.get_event_loop().run_until_complete(
            p.repair("test_node", state, attempt, success, error, "test_strategy")
        )
        assert call_count["n"] == 1
        assert result.intermediate_results["test"] == "fixed"

    def test_repair_retries_on_failure(self):
        from orchestrator.services.self_correction_policy import SelfCorrectionPolicy
        from shared.models import ConversationState
        p = SelfCorrectionPolicy()
        state = ConversationState(conversation_id="s2", user_message="test", building_id="bldg1")
        call_count = {"n": 0}

        async def attempt(s, attempt_number, last_error):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                s.intermediate_results["test"] = "fixed"
            return s

        def success(s):
            return s.intermediate_results.get("test") == "fixed"

        def error(s):
            return "still broken"

        result = asyncio.get_event_loop().run_until_complete(
            p.repair("test_node", state, attempt, success, error, "test_strategy")
        )
        assert call_count["n"] == 2

    def test_correction_trace_emitted(self):
        from orchestrator.services.self_correction_policy import SelfCorrectionPolicy
        from shared.models import ConversationState
        p = SelfCorrectionPolicy()
        state = ConversationState(conversation_id="s3", user_message="test", building_id="bldg1")

        async def attempt(s, attempt_number, last_error):
            s.intermediate_results["test"] = "ok"
            return s

        def success(s):
            return True

        def error(s):
            return ""

        result = asyncio.get_event_loop().run_until_complete(
            p.repair("trace_node", state, attempt, success, error, "trace_strat")
        )
        assert "correction_trace" in result.intermediate_results


# ─── Phase 3: PersonaRegistry ────────────────────────────────────────────────

class TestPersonaRegistry:
    def test_get_priors_all_known_personas(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        for persona in ["occupant", "facility_manager", "researcher", "it_admin",
                         "safety_officer", "student", "executive",
                         "sustainability_officer", "visitor", "general"]:
            p = reg.get_priors(persona)
            assert p.name is not None
            assert len(p.top_domains) >= 1
            assert 0.0 <= p.lookup_share <= 1.0
            assert p.default_complexity in ("SIMPLE", "MODERATE", "COMPLEX")

    def test_unknown_persona_falls_back_to_general(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        p = reg.get_priors("some_unknown_role_xyz")
        assert p.name == "general"

    def test_alias_energy_manager_maps_to_sustainability(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        p = reg.get_priors("energy_manager")
        assert p.name == "sustainability_officer"

    def test_alias_facilities_maps_to_facility_manager(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        p = reg.get_priors("facilities")
        assert p.name == "facility_manager"

    def test_domain_score_boosts_top_domain(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        # Occupant's top domain is THERMAL — should score higher than ENERGY
        thermal_score = reg.domain_score("occupant", "THERMAL")
        energy_score = reg.domain_score("occupant", "ENERGY")
        assert thermal_score > energy_score

    def test_domain_score_no_boost_for_unrelated_domain(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        base = reg.domain_score("occupant", "XENON_DOMAIN", base_score=1.0)
        assert base == 1.0  # no boost for unknown domain

    def test_should_clarify_student_low_threshold(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        # Student has low clarification_threshold (0.25) — only clarify on high ambiguity
        assert reg.should_clarify("student", 0.1) is False
        assert reg.should_clarify("student", 0.9) is True

    def test_should_clarify_researcher_higher_threshold(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        # Researcher threshold is 0.6 — should clarify at 0.7 but not 0.5
        assert reg.should_clarify("researcher", 0.5) is False
        assert reg.should_clarify("researcher", 0.7) is True

    def test_safety_officer_top_domain_is_fire_safety(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        p = reg.get_priors("safety_officer")
        assert p.top_domains[0] == "FIRE_SAFETY"

    def test_none_persona_returns_general(self):
        from shared.persona_registry import get_persona_registry
        reg = get_persona_registry()
        p = reg.get_priors(None)
        assert p.name == "general"


# ─── Phase 4: dialogue_state in ConversationState ─────────────────────────────

class TestDialogueState:
    def test_dialogue_state_field_exists(self):
        from shared.models import ConversationState
        state = ConversationState(conversation_id="d1", user_message="test", building_id="bldg1")
        assert hasattr(state, "dialogue_state")
        assert state.dialogue_state is None

    def test_dialogue_state_can_be_set(self):
        from shared.models import ConversationState
        state = ConversationState(conversation_id="d2", user_message="test", building_id="bldg1")
        state.dialogue_state = {
            "pending_candidates": ["Zone 5.28", "Zone 5.12"],
            "pending_type": "zone",
        }
        assert state.dialogue_state["pending_type"] == "zone"

    def test_dialogue_state_persists_through_dict_serialization(self):
        from shared.models import ConversationState
        state = ConversationState(conversation_id="d3", user_message="test", building_id="bldg1")
        state.dialogue_state = {"key": "value"}
        d = state.model_dump()
        assert d["dialogue_state"] == {"key": "value"}


# ─── Phase 5: agent_memory store_failure / store_correction ──────────────────

class TestAgentMemoryPhase5:
    def test_store_failure_importable(self):
        from orchestrator.services.agent_memory import AgentMemoryService
        mem = AgentMemoryService.__new__(AgentMemoryService)
        assert hasattr(mem, "store_failure")

    def test_store_correction_importable(self):
        from orchestrator.services.agent_memory import AgentMemoryService
        mem = AgentMemoryService.__new__(AgentMemoryService)
        assert hasattr(mem, "store_correction")

    def test_store_failure_method_signature(self):
        import inspect
        from orchestrator.services.agent_memory import AgentMemoryService
        sig = inspect.signature(AgentMemoryService.store_failure)
        params = list(sig.parameters)
        assert "user_id" in params
        assert "query" in params
        assert "intent" in params
        assert "error_summary" in params

    def test_store_correction_method_signature(self):
        import inspect
        from orchestrator.services.agent_memory import AgentMemoryService
        sig = inspect.signature(AgentMemoryService.store_correction)
        params = list(sig.parameters)
        assert "user_id" in params
        assert "query" in params
        assert "wrong_answer" in params
        assert "corrected_answer" in params


# ─── G1 six-tuple: _derive_g1_taxonomy ───────────────────────────────────────

class TestG1Taxonomy:
    def _derive(self, query: str, intent: str = "sensor_data",
                entities: Optional[List] = None, time_range: Optional[Dict] = None):
        from orchestrator.agents.dialogue_agent import _derive_g1_taxonomy
        return _derive_g1_taxonomy(query, intent, entities or [], time_range or {})

    def test_thermal_domain_for_temperature_query(self):
        g1 = self._derive("What is the temperature in Zone 5.28?")
        assert g1["domain_l1"] == "THERMAL"

    def test_air_quality_domain_for_co2_query(self):
        g1 = self._derive("Show me the CO2 levels today")
        assert g1["domain_l1"] == "AIR_QUALITY"

    def test_fire_safety_domain(self):
        g1 = self._derive("Where is the fire assembly point?", intent="capability")
        assert g1["domain_l1"] == "FIRE_SAFETY"

    def test_temporal_flag_for_last_24h(self):
        g1 = self._derive("Show me temperature for the last 24 hours")
        assert g1["temporal"] is True

    def test_spatial_flag_for_zone_query(self):
        g1 = self._derive("What is temperature in Zone 5?")
        assert g1["spatial"] is True

    def test_complexity_simple_for_current_reading(self):
        g1 = self._derive("What is the current temperature?", intent="sensor_data")
        assert g1["complexity"] in ("SIMPLE", "MODERATE")

    def test_complexity_moderate_for_forecast(self):
        g1 = self._derive("Forecast tomorrow's temperature trend", intent="forecast")
        assert g1["complexity"] in ("MODERATE", "COMPLEX")

    def test_returns_all_six_fields(self):
        g1 = self._derive("test query")
        required = {"domain_l1", "query_type_l2", "intent", "temporal", "spatial", "complexity"}
        assert required == set(g1.keys())

    def test_aggregation_type_for_average_query(self):
        g1 = self._derive("What is the average CO2 today?")
        assert g1["query_type_l2"] in ("AGGREGATION", "LOOKUP", "STATUS")


# ─── Workflow wiring ──────────────────────────────────────────────────────────

class TestCapabilityWorkflowWiring:
    def test_capability_node_registered(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert 'add_node("capability"' in content

    def test_capability_edge_to_response(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert '"capability", "response"' in content or "capability.*response" in content

    def test_capability_routing_in_route_function(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert '"capability"' in content
        assert "capability" in content

    def test_capability_agent_instantiated_in_workflow(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert "CapabilityAgent()" in content

    def test_verifier_agent_instantiated_in_workflow(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert "VerifierAgent()" in content

    def test_capability_intent_override_in_dialogue_agent(self):
        content = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
        assert "_CAPABILITY_KW" in content
        assert '"capability"' in content

    def test_g1_taxonomy_emitted_in_dialogue_agent(self):
        content = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
        assert "_derive_g1_taxonomy" in content
        assert "g1_taxonomy" in content

    def test_persona_registry_used_in_workflow(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert "persona" in content.lower()

    def test_store_failure_called_in_response_node(self):
        content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
        assert "store_failure" in content
