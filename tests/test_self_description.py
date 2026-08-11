# -*- coding: utf-8 -*-
"""OntoSage describing itself — from configuration, not from a written-out blurb.

Questions about the ASSISTANT were reaching the open-domain answerer, which knows
nothing about this system and supplied a plausible substitute. Observed live:

    "How do you work?"   -> "I'm a large-language model built by OpenAI"
    "What can you do?"   -> guidance on BACnet, Modbus and ISO 50001, naming none
                            of OntoSage's actual abilities
    "What is OntoSage?"  -> answered only because ONE building's governance
                            document happens to mention it

Same failure as BUG-123, one step over: a question the system cannot ground,
answered anyway.

The answer is composed from live configuration — the intent registry, the schema's
source types, and the active building's own figures — so it cannot drift from what
the system actually does, and it differs per building because the building does.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services.self_description import describe, is_self_question

pytestmark = pytest.mark.unit


# ── telling a question about the assistant from one about the building ───────


@pytest.mark.parametrize(
    "query",
    [
        "What is OntoSage?",
        "What can you do?",
        "what can you help with?",
        "How do you work?",
        "how does ontosage work?",
        "What kind of questions can I ask you?",
        "What are your capabilities?",
        "who are you?",
        "tell me about ontosage",
    ],
)
def test_questions_about_the_assistant_are_recognised(query):
    assert is_self_question(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What is the temperature on floor 3?",
        "What can you tell me about the chiller?",
        "How many sensors are there?",
        "What is a VAV box?",
        "How does a heat pump work?",
        "What is this building?",
        "Show me floor 1",
    ],
)
def test_questions_about_the_building_or_the_world_are_not_claimed(query):
    """The narrow case that matters: "what can you tell me about the chiller?" is
    about the building and must reach the data path."""
    assert is_self_question(query) is False


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_input_is_not_a_self_question(blank):
    assert is_self_question(blank) is False


# ── the answer is built from configuration ───────────────────────────────────


def _registry(names):
    return SimpleNamespace(intents=[SimpleNamespace(name=n) for n in names])


def test_capabilities_come_from_the_registry_not_a_fixed_list():
    """Adding an intent must change the answer without anyone editing prose."""
    out = describe(_registry(["sensor_data", "floor_plan", "maintenance"]), "Test Building")
    assert "sensor data" in out and "floor plan" in out and "maintenance" in out

    grown = describe(
        _registry(["sensor_data", "floor_plan", "maintenance", "lab_booking"]), "Test Building"
    )
    assert "lab booking" in grown, "a per-building intent must appear without a code change"


def test_an_ungrouped_intent_is_still_listed():
    """Grouping is presentation, never a filter — a new intent cannot be hidden."""
    out = describe(_registry(["sensor_data", "something_brand_new"]), "Test Building")
    assert "something brand new" in out


def test_plumbing_intents_are_not_offered_to_the_user():
    out = describe(_registry(["sensor_data", "clarification", "greeting", "planner"]), "T")
    for internal in ("clarification", "greeting", "planner"):
        assert internal not in out


def test_the_building_is_named_and_its_own_figures_are_used():
    out = describe(
        _registry(["sensor_data"]),
        "Some Other Building",
        facts={"Sensors in the ontology": "1,318", "Connected databases": "database1"},
    )
    assert "Some Other Building" in out
    assert "1,318" in out and "database1" in out


def test_grounding_sources_are_listed_when_the_schema_provides_them():
    out = describe(
        _registry(["sensor_data"]), "T", source_types=["Knowledge graph (SPARQL/GraphDB)"]
    )
    assert "Knowledge graph" in out


def test_it_answers_even_when_every_optional_source_is_missing():
    """A building with no metrics and an unavailable registry must still get a
    truthful answer rather than an error."""
    out = describe(None, "T")
    assert "OntoSage" in out and len(out) > 100


def test_it_claims_no_capability_it_cannot_name():
    """The live failure was inventing abilities. Nothing may appear that did not
    come from the registry."""
    out = describe(_registry(["sensor_data"]), "T")
    for invented in ("BACnet", "Modbus", "ISO 50001", "OpenAI", "large-language model"):
        assert invented.lower() not in out.lower()


def test_the_module_names_no_building():
    import inspect

    from orchestrator.services import self_description as sd

    src = inspect.getsource(sd).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys", "cardiff"):
        assert literal not in src, f"self-description must not name a building: {literal}"


# ── the identity is the FRAMEWORK, not the connected building ────────────────


def test_it_describes_itself_as_a_framework_not_as_one_building_s_product():
    """Saying "I am a conversational layer over <this building>" made the identity
    sound built for one site. The building is what it is CONNECTED to."""
    out = describe(_registry(["sensor_data"]), "Some Specific Building")
    head = out[:400].lower()
    assert "building-agnostic" in head or "framework" in head
    assert "some specific building" not in head, "the site must not define the identity"


def test_the_connected_building_appears_but_only_as_the_current_connection():
    out = describe(_registry(["sensor_data"]), "Some Specific Building", facts={"Sensors": "12"})
    assert "Currently connected to: Some Specific Building" in out
    assert out.index("Currently connected") > out.index("What you can ask me")


def test_a_building_with_no_data_yet_still_gets_the_full_identity():
    """A building onboarded today, before any TTL or database, must still be told
    what OntoSage is and what it will be able to answer."""
    out = describe(_registry(["sensor_data", "floor_plan"]), "Brand New Site", facts={})
    assert "framework" in out.lower()
    assert "sensor data" in out and "floor plan" in out
    assert "No data loaded yet" in out


def test_it_names_the_stakeholders_it_serves():
    out = describe(_registry(["sensor_data"]), "T")
    for role in ("facility manager", "occupant", "researcher"):
        assert role in out.lower()


def test_it_states_that_onboarding_needs_no_code_change():
    out = describe(_registry(["sensor_data"]), "T")
    assert "no code change" in out.lower()
