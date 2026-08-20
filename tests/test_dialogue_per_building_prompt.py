"""Phase 10B — dialogue prompt uses per-building SCOPE name.

Verifies that `_build_intent_detection_prompt(building_id=...)` reads the
building name from the resolver, not from process-global settings.  This is
the foundation for per-request multi-tenant operation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.services import building_context as bc_mod
from orchestrator.services.building_context import BuildingContext


def _stub_resolver(*, name="StubBuilding", namespace="http://stub#", prefix="stub", tz="UTC"):
    """Patch resolve_building_context to return a known context."""

    def _fake(bid):
        return BuildingContext(
            building_id=bid or "stub",
            name=name,
            namespace=namespace,
            prefix=prefix,
            timezone=tz,
        )

    return _fake


def test_prompt_includes_per_building_name_when_building_id_provided():
    """When building_id is passed, the SCOPE rule names that building."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    # Bypass __init__ to avoid LLM client setup
    agent = DialogueAgent.__new__(DialogueAgent)

    with patch.object(
        bc_mod, "resolve_building_context", side_effect=_stub_resolver(name="Cardiff Eng")
    ):
        prompt = agent._build_intent_detection_prompt(
            user_query="hello",
            ontology_context=[],
            conversation_history="",
            persona="general",
            memory_context="",
            building_id="bldgX",
        )

    # The SCOPE rule must mention the building we asked about
    assert "Cardiff Eng" in prompt, (
        "Prompt did not include the per-building name " f"(found: {prompt[:300]!r}...)"
    )


def test_prompt_falls_back_to_settings_name_when_no_building_id():
    """When building_id is None, the resolver falls back to settings."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    agent = DialogueAgent.__new__(DialogueAgent)

    # No patch on resolver — it will use real settings (Abacws)
    prompt = agent._build_intent_detection_prompt(
        user_query="hello",
        ontology_context=[],
        conversation_history="",
        persona="general",
        memory_context="",
        building_id=None,
    )

    # Should mention Abacws (the active building's name)
    assert "Abacws" in prompt


def test_different_building_ids_produce_different_prompts():
    """The same query for two buildings yields different SCOPE rules."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    agent = DialogueAgent.__new__(DialogueAgent)

    with patch.object(
        bc_mod, "resolve_building_context", side_effect=_stub_resolver(name="BuildingAlpha")
    ):
        prompt_a = agent._build_intent_detection_prompt(
            user_query="hi",
            ontology_context=[],
            conversation_history="",
            persona="general",
            memory_context="",
            building_id="alpha",
        )

    with patch.object(
        bc_mod, "resolve_building_context", side_effect=_stub_resolver(name="BuildingOmega")
    ):
        prompt_o = agent._build_intent_detection_prompt(
            user_query="hi",
            ontology_context=[],
            conversation_history="",
            persona="general",
            memory_context="",
            building_id="omega",
        )

    assert "BuildingAlpha" in prompt_a
    assert "BuildingOmega" in prompt_o
    assert "BuildingAlpha" not in prompt_o
    assert "BuildingOmega" not in prompt_a
