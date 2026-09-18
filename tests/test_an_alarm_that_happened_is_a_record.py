"""An alarm that already went off is a record, not an alert to create (TODO-490).

"Have there been any alarms this week?" was answered by the alert-CREATION lane:

    I haven't created an alert yet. I need what to measure (for example CO2, temperature or
    humidity) and the value that should trigger it (for example 'above 1000').

A configuration form, in answer to a question about what occurred. The two shapes are
opposites — a standing alert is about the future and is created; an alarm history is about
the past and is read — and only the past is claimed here.
"""

import pytest

from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit


def _route(query: str, intent: str = "alert"):
    norm = {
        "intent": intent,
        "entities": [],
        "analytics": intent == "analytics",
        "general": intent == "general",
    }
    apply_contract(query, norm, stage="parse")
    return norm["intent"]


@pytest.mark.parametrize(
    "query",
    [
        "Have there been any alarms this week?",
        "Which alarms went off yesterday?",
        "How many alerts were raised today?",
        "was there an alarm last night",
        "did the alarm sound this morning",
        "what alarms were logged recently",
    ],
)
def test_a_past_alarm_question_reads_records(query):
    assert _route(query) != "alert", query


@pytest.mark.parametrize(
    "query",
    [
        "alert me when CO2 goes high",
        "notify me if a desk becomes free",
        "tell me when the lift is fixed",
        "warn me whenever the server room gets warm",
        "let me know once floor 3 is quiet",
    ],
)
def test_a_standing_request_keeps_the_alert_lane(query):
    """The opposite shape, and the reason the guard checks STANDING_ALERT_RE first."""
    assert _route(query) == "alert", query


def test_a_lane_that_is_not_alert_is_untouched():
    """The rule claims only questions the classifier already called `alert`."""
    for intent in ("sensor_data", "metadata", "control", "privacy_refusal"):
        assert _route("have there been any alarms this week?", intent=intent) == intent


def test_the_rule_sits_before_the_standing_request_rule():
    from orchestrator.services.routing_contract import PARSE_STAGE_RULES

    names = [r.name for r in PARSE_STAGE_RULES]
    assert names.index("alarm_history_is_a_record") == names.index("standing_alert_request") - 1


def test_the_two_patterns_do_not_both_claim_one_question():
    """If both matched, the order would decide it silently. They must be disjoint."""
    from orchestrator.services.routing_contract import ALARM_HISTORY_RE, STANDING_ALERT_RE

    for query in ("alert me when CO2 goes high", "notify me if a desk becomes free"):
        assert STANDING_ALERT_RE.search(query)
    for query in ("Have there been any alarms this week?", "Which alarms went off yesterday?"):
        assert ALARM_HISTORY_RE.search(query)
        assert not STANDING_ALERT_RE.search(query)
