"""TODO-050 — the question-shape → intent routing contract.

Table-driven tests for every rule in ``orchestrator/services/routing_contract.py``:
each rule has at least one firing and one non-firing case, precedence conflicts are
pinned, the audit trail is asserted, and the contract is proven building-agnostic
(no building literals in the module source).

The contract is pure question-shape logic — these tests run fully offline.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit


def _norm(intent: str = "general", entities=None, **kw):
    d = {
        "intent": intent,
        "entities": entities or [],
        "analytics": intent == "analytics",
        "general": intent == "general",
    }
    d.update(kw)
    return d


def _apply(query: str, intent: str = "general", entities=None, stage: str = "parse"):
    n = _norm(intent, entities)
    applied = apply_contract(query, n, stage=stage)
    return n, applied


# ─────────────────────────────────────────────────────────────────────────────
# Individual rules — fires / does not fire
# ─────────────────────────────────────────────────────────────────────────────


def test_compare_two_floors_beats_compliance():
    n, applied = _apply("Compare CO2 on floor 2 vs floor 3", intent="compliance")
    assert n["intent"] == "compare"
    assert "compare_two_referents" in applied


def test_compare_needs_two_referents():
    n, _ = _apply("Is the CO2 higher than the limit?", intent="compliance")
    assert n["intent"] == "compliance"  # one referent → no override


def test_sensor_id_plus_trend_is_analytics_not_compliance():
    n, applied = _apply(
        "Show Temperature_Sensor_5.04 trend over the last 7 days", intent="compliance"
    )
    assert n["intent"] == "analytics" and n["analytics"] is True
    assert "sensor_trend_not_compliance" in applied


def test_vague_complaint_becomes_clarification_with_question():
    n, applied = _apply("Please fix everything, things seem off", intent="control")
    assert n["intent"] == "clarification"
    assert n["clarification_question"]
    assert "vague_complaint_clarify" in applied


def test_specific_control_keeps_control():
    n, _ = _apply("Things seem off — set temperature to 21 in zone 3", intent="control")
    assert n["intent"] == "control"  # specific target → no clarification demotion


def test_correlation_promotes_clarification_to_analytics():
    n, applied = _apply(
        "What is the correlation between CO2 and occupancy?", intent="clarification"
    )
    assert n["intent"] == "analytics"
    assert "correlation_is_analytics" in applied


def test_floor_plan_navigation_forced():
    n, applied = _apply("Show me floor 3 please", intent="discovery")
    assert n["intent"] == "floor_plan"
    assert "floor_plan_navigation" in applied


def test_floor_plan_not_forced_when_already_spatial():
    n, applied = _apply("Show me floor 3 please", intent="spatial_query")
    assert n["intent"] == "spatial_query" and not applied


def test_count_of_sensors_is_metadata_not_spatial():
    n, applied = _apply("How many temperature sensors are there?", intent="spatial_query")
    assert n["intent"] == "metadata"
    assert "countable_metadata" in applied


def test_room_area_count_stays_spatial():
    n, _ = _apply("How many square metres is room 2.01?", intent="spatial_query")
    assert n["intent"] == "spatial_query"


def test_building_identity_is_metadata():
    n, applied = _apply("What building is this?", intent="general")
    assert n["intent"] == "metadata"
    assert "countable_metadata" in applied


def test_forecast_with_metric_routes_to_trend():
    n, applied = _apply("Predict the temperature tomorrow", intent="general")
    assert n["intent"] == "trend" and n["analytics"] is True
    assert "forecast_to_trend" in applied


def test_forecast_without_metric_untouched():
    n, _ = _apply("Predict who will win the game", intent="general")
    assert n["intent"] == "general"


def test_actuation_command_routes_to_control():
    n, applied = _apply("Open the windows on floor 2", intent="floor_plan")
    assert n["intent"] == "control"
    assert "actuation_control" in applied


def test_external_action_email_routes_to_control():
    n, applied = _apply("Email the report to my manager", intent="general")
    assert n["intent"] == "control"
    assert "actuation_control" in applied


def test_maintenance_schedule_phrase_routes_to_maintenance():
    n, applied = _apply("What maintenance is scheduled this week?", intent="metadata")
    assert n["intent"] == "maintenance"
    assert "maintenance_schedule" in applied


def test_report_statement_beats_capability():
    n, applied = _apply("The toilet on floor 2 is leaking", intent="capability")
    assert n["intent"] in ("maintenance", "complaint")
    assert "report_intake_statement" in applied


def test_comfort_question_not_logged_as_complaint():
    n, applied = _apply("Is it too warm in zone 5.28?", intent="complaint")
    assert n["intent"] == "analytics"
    assert "comfort_question_not_report" in applied


# ─────────────────────────────────────────────────────────────────────────────
# New automation-shape rules (L6 corpus gap, 2026-07-30 replay evidence)
# ─────────────────────────────────────────────────────────────────────────────


def test_standing_notification_request_routes_to_alert():
    n, applied = _apply("Notify me when a desk becomes available nearby", intent="general")
    assert n["intent"] == "alert"
    assert "standing_alert_request" in applied


def test_alert_me_if_routes_to_alert():
    n, applied = _apply("Alert me if CO2 goes above 1000 ppm", intent="capability")
    assert n["intent"] == "alert"
    assert "standing_alert_request" in applied


def test_can_system_automatically_routes_to_automation_capability():
    n, applied = _apply(
        "Can the system automatically increase outdoor air intake if CO2 exceeds 800 ppm?",
        intent="general",
    )
    assert n["intent"] == "automation_capability"
    assert "automation_capability_question" in applied


def test_can_it_notify_shape_routes_to_automation_capability():
    n, applied = _apply(
        "Could the building notify security when a door is left open?", intent="general_knowledge"
    )
    assert n["intent"] == "automation_capability"


def test_automation_shape_never_stomps_confident_intents():
    n, applied = _apply(
        "Can the system automatically adjust the ventilation?", intent="automation_capability"
    )
    assert n["intent"] == "automation_capability" and not applied
    n2, applied2 = _apply("Notify me when CO2 is high", intent="alert")
    assert n2["intent"] == "alert" and not applied2


def test_actuation_command_wins_over_automation_shape():
    # An imperative actuation ask is control, even though it mentions 'automatically'.
    n, _ = _apply("Turn on the lights automatically every morning", intent="general")
    assert n["intent"] == "control"


# ─────────────────────────────────────────────────────────────────────────────
# Post stage — data-query promotion
# ─────────────────────────────────────────────────────────────────────────────


def test_post_stage_promotes_reading_question_to_sensor_data():
    n, applied = _apply("What is the temperature on floor 5?", intent="metadata", stage="post")
    assert n["intent"] == "sensor_data"
    assert "data_query_promotion" in applied


def test_post_stage_never_demotes_count_questions():
    n, _ = _apply("How many sensors are on floor 5?", intent="metadata", stage="post")
    assert n["intent"] == "metadata"


def test_post_stage_preserves_analytics_flag():
    n = _norm("metadata")
    n["analytics"] = True  # must survive the promotion untouched
    apply_contract("What is the temperature on floor 5?", n, stage="post")
    assert n["intent"] == "sensor_data" and n["analytics"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Contract-level properties
# ─────────────────────────────────────────────────────────────────────────────


def test_rule_names_unique_and_documented():
    rules = rc.PARSE_STAGE_RULES + rc.POST_STAGE_RULES
    names = [r.name for r in rules]
    assert len(names) == len(set(names))
    assert all(r.shape.strip() for r in rules)


def test_precedence_order_is_pinned():
    """The rule order IS the contract — changing it must be a conscious decision."""
    assert [r.name for r in rc.PARSE_STAGE_RULES] == [
        "compare_two_referents",
        "sensor_trend_not_compliance",
        "vague_complaint_clarify",
        "correlation_is_analytics",
        "floor_plan_navigation",
        "countable_metadata",
        # Sits directly after countable_metadata so a COUNT question keeps its
        # historical route and only the open "what kinds of X" shape is claimed.
        "inventory_to_discovery",
        "forecast_to_trend",
        "actuation_control",
        "maintenance_schedule",
        "report_intake_statement",
        "self_description",
        "history_question_not_report",
        "comfort_question_not_report",
        "standing_alert_request",
        "automation_capability_question",
    ]
    assert [r.name for r in rc.POST_STAGE_RULES] == ["data_query_promotion"]


def test_contract_is_building_agnostic():
    """The contract keys on question SHAPE only — no building may ever be named."""
    src = inspect.getsource(rc).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff", "buildsys"):
        assert literal not in src, f"building literal '{literal}' found in routing contract"


def test_audit_trail_records_applied_rules():
    n, _ = _apply("How many sensors are there in total?", intent="spatial_query")
    assert n["routing_rules_applied"] == ["countable_metadata"]


def test_no_rules_fire_on_plain_greeting():
    n, applied = _apply("Hello there!", intent="greeting")
    assert n["intent"] == "greeting" and not applied


# ── inventory questions reach one handler (BUG-122) ──────────────────────────


@pytest.mark.parametrize(
    "query,start",
    [
        ("What equipment is installed in this building?", "capability"),
        ("what sensors are there?", "sensor_data"),
        ("What sensor types are available in this building?", "sensor_data"),
        ("which meters do we have?", "general"),
        ("list the chillers", "metadata"),
    ],
)
def test_inventory_questions_all_land_on_discovery(query, start):
    """Before this rule the same question reached three different handlers
    depending on phrasing — the capability agent, the sensor-map lister and the
    SPARQL agent — each grouping its answer differently, so "what equipment is
    here?" and "what sensors are here?" disagreed about the building."""
    n, applied = _apply(query, intent=start)
    assert n["intent"] == "discovery"
    assert "inventory_to_discovery" in applied


@pytest.mark.parametrize(
    "query", ["How many sensors are there in total?", "how many floors does this building have?"]
)
def test_count_questions_keep_their_existing_route(query):
    """countable_metadata is ordered first and must still win."""
    n, applied = _apply(query, intent="spatial_query")
    assert n["intent"] == "metadata"
    assert "inventory_to_discovery" not in applied


@pytest.mark.parametrize(
    "query,intent",
    [
        ("What is a VAV box?", "general"),
        ("What is the supply air temperature of AHU01N?", "sensor_data"),
        ("Show me floor 1", "floor_plan"),
    ],
)
def test_non_inventory_questions_are_not_rerouted(query, intent):
    n, applied = _apply(query, intent=intent)
    assert "inventory_to_discovery" not in applied


# ── a question about past maintenance is not a report (BUG-104) ──────────────


@pytest.mark.parametrize(
    "query",
    [
        "When was chiller 7 last serviced?",
        "when was the AHU last inspected?",
        "what date was the lift last maintained?",
        "show me the service history for the boiler",
        "when was equipment last checked?",
    ],
)
def test_a_past_maintenance_question_does_not_file_a_ticket(query):
    """Asking a question and being told a work order was raised is a bad answer and
    a real side effect. It routes to the capability chain, which answers from a
    service-history topic where one is authored and declines honestly where none is."""
    n, applied = _apply(query, intent="maintenance")
    assert n["intent"] == "capability"
    assert "history_question_not_report" in applied


@pytest.mark.parametrize(
    "query",
    [
        "The lift is broken and trapped someone",
        "There is a water leak on floor 2",
        "the toilet is leaking",
    ],
)
def test_a_genuine_report_is_still_filed(query):
    n, applied = _apply(query, intent="maintenance")
    assert n["intent"] != "capability"
    assert "history_question_not_report" not in applied


def test_scheduled_maintenance_questions_keep_their_own_route():
    """'what maintenance is scheduled this week?' is about the FUTURE — the
    maintenance node answers it and must not be diverted."""
    n, _ = _apply("What maintenance is scheduled this week?", intent="metadata")
    assert n["intent"] == "maintenance"
