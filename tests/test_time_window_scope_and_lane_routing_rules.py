# -*- coding: utf-8 -*-
"""Row 2D-07 (BUG-828, BUG-812, BUG-815): the routing rules for time windows, scope and lane choice.

Each rule cites the question that failed on 2026-09-18 and the lane it reached, and each has a
negative case: the neighbour that must keep its lane. The classifier's own label is simulated by
the STARTING intent, because the contract's job is to correct a label, not to produce one.

* "Has anything been reported broken this week?" reached the capability lane and was answered from
  two uploaded registers (BUG-828, B23) -> the events lane, which reads the report store.
* "Which meeting rooms are booked this afternoon?" reached a register of six bookings (BUG-828,
  B11) -> the events lane, which reads the live booking store.
* "When is the atrium busiest?" reached the ranking lane (BUG-828, B12) -> a series over history.
* "What's the weather forecast for tomorrow?" asked which city; "Should I buy Bitcoin?" gave
  investment guidance (BUG-812, F39/F40) -> a brief scope statement.
* "What can you tell me about this building?" listed measurand names (BUG-815, F34) -> the
  building's own description, which "Describe this building." already reaches.
"""

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit


def _route(question: str, start: str, stage: str = "parse"):
    normalized = {
        "intent": start,
        "entities": [],
        "analytics": start == "analytics",
        "general": start == "general",
    }
    applied = apply_contract(question, normalized, stage=stage)
    return normalized["intent"], applied


def _final(question: str, start: str) -> str:
    intent, _ = _route(question, start)
    intent, _ = _route_from(question, intent, "post")
    return intent


def _route_from(question, start, stage):
    return _route(question, start, stage)


# ── what people filed: the report store, through the events lane ────────────

WHAT_WAS_REPORTED = [
    "Has anything been reported broken this week?",  # B23
    "Have any faults been reported today?",
    "What has been reported this week?",
    "How many faults were reported yesterday?",
]


@pytest.mark.parametrize("question", WHAT_WAS_REPORTED)
@pytest.mark.parametrize("classified_as", ["capability", "general", "metadata", "analytics"])
def test_a_question_about_what_was_reported_reaches_the_events_lane(question, classified_as):
    assert _final(question, classified_as) == "events"


@pytest.mark.parametrize("classified_as", ["maintenance", "report"])
def test_the_same_question_wins_over_intake_when_the_classifier_reads_it_as_a_fault(classified_as):
    # an interrogative is never filed as a ticket (BUG-166's rule, in a new place)
    assert _final("Has anything been reported broken this week?", classified_as) == "events"


@pytest.mark.parametrize(
    "statement",
    [
        "The projector in Room 2.01 is broken",
        "Something is broken and I already reported it",
        "I want to report a broken light in the corridor",
    ],
)
def test_a_report_being_made_still_reaches_intake(statement):
    assert _final(statement, "maintenance") == "maintenance"


def test_how_do_i_report_a_fault_keeps_the_capability_lane():
    assert _final("How do I report a fault?", "capability") == "capability"


def test_an_events_question_now_covers_reports_and_still_excludes_no_cost_free():
    assert rc.events_question("Has anything been reported broken this week?")
    assert not rc.events_question("Is tap water free somewhere, or do I have to buy bottles?")
    assert not rc.events_question("Is the lift broken?")


# ── which rooms are booked: the live booking store ──────────────────────────

BOOKED_ROOMS = [
    "Which meeting rooms are booked this afternoon?",  # B11
    "Which rooms are booked tomorrow morning?",
    "What rooms are reserved on Friday?",
    "List the meeting rooms that are booked today",
]


@pytest.mark.parametrize("question", BOOKED_ROOMS)
@pytest.mark.parametrize("classified_as", ["metadata", "capability", "general", "sensor_data"])
def test_which_rooms_are_booked_reaches_the_events_lane(question, classified_as):
    assert _final(question, classified_as) == "events"


def test_a_comfort_constrained_room_search_keeps_the_ranking_lane():
    assert _final("Which quiet rooms are free this afternoon?", "deliberate") == "deliberate"
    assert _final("Which bookable rooms are suitable for a confidential call?", "capability") != "events"


# ── when is it busiest: a time, not a room ──────────────────────────────────


@pytest.mark.parametrize(
    "classified_as", ["deliberate", "general", "capability", "metadata", "sensor_data", "analytics"]
)
def test_when_is_the_atrium_busiest_is_a_series_over_time_not_a_room_ranking(classified_as):
    intent, applied = _route("When is the atrium busiest?", classified_as)
    assert intent == "trend", (classified_as, intent, applied)


@pytest.mark.parametrize(
    "question",
    [
        "Which room is the busiest right now?",
        "What is the quietest room on floor 3?",
        "Show me the zone with minimum occupancy.",
        "Which rooms on floor 5 are stuffy right now?",
    ],
)
def test_a_ranking_of_rooms_keeps_the_ranking_lane(question):
    assert _route(question, "deliberate")[0] == "deliberate"


# ── out of scope ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("classified_as", ["clarification", "general", "general_knowledge", "trend"])
def test_a_weather_forecast_gets_a_scope_statement_not_a_which_city_question(classified_as):
    assert _final("What's the weather forecast for tomorrow?", classified_as) == "scope_boundary"


@pytest.mark.parametrize("classified_as", ["general", "general_knowledge", "capability"])
def test_financial_advice_gets_a_scope_statement_not_investment_guidance(classified_as):
    assert _final("Should I buy Bitcoin?", classified_as) == "scope_boundary"


@pytest.mark.parametrize(
    "question", ["Tell me a joke.", "What's the capital of France?", "Write me a poem about spring"]
)
@pytest.mark.parametrize("classified_as", ["general", "general_knowledge"])
def test_a_joke_or_trivia_gets_the_scope_statement_not_an_unlabelled_general_answer(
    question, classified_as
):
    # owner policy 2026-09-19: not about buildings at all -> brief scope decline (B39 / C12)
    assert _final(question, classified_as) == "scope_boundary"


@pytest.mark.parametrize(
    "question, start",
    [
        ("What is Bitcoin?", "general"),
        ("Predict the temperature in Room 3.01 for tomorrow afternoon.", "trend"),
        ("Forecast energy use for next week.", "trend"),
        ("Is it raining?", "sensor_data"),
        ("Tell me a joke about HVAC.", "general"),  # names a building term: not the bare request
        ("Hello", "greeting"),
        ("Thanks!", "greeting"),
    ],
)
def test_neighbours_of_the_scope_rule_keep_their_lane(question, start):
    assert _final(question, start) not in ("scope_boundary", "general_guidance")


# ── building knowledge that needs no building data: labelled general guidance ─────────────────

GUIDANCE_QUESTIONS = [
    "Does humidity affect CO2 sensor accuracy?",
    "How do I control CO2?",
    "How do BREEAM and LEED differ?",
    "What does a delta-T mean?",
]


@pytest.mark.parametrize("question", GUIDANCE_QUESTIONS)
@pytest.mark.parametrize(
    "classified_as",
    ["general", "general_knowledge", "recommend", "analytics", "capability", "sensor_data", "compare"],
)
def test_building_knowledge_never_reaches_the_sensor_fetch(question, classified_as):
    assert _final(question, classified_as) == "general_guidance"


@pytest.mark.parametrize(
    "question, start",
    [
        ("How can I improve air quality in my lab?", "recommend"),  # my / lab: this building's data
        ("How do I control the temperature in Room 3.01?", "recommend"),
        ("What is the CO2 in room 5.01?", "sensor_data"),
        ("How has CO2 changed this week?", "trend"),
        ("Can you reduce the temperature?", "control"),  # a command
        ("The heating is broken", "maintenance"),  # a fault being reported
        ("How do I report a faulty sensor?", "capability"),  # a procedure of this building
        ("What does the fire policy say about temperature?", "capability"),
    ],
)
def test_a_question_that_names_this_building_keeps_the_lane_that_can_read_it(question, start):
    assert _final(question, start) != "general_guidance"


def test_a_privacy_denial_is_never_taken_over_by_a_scope_statement():
    intent, _ = _route("Where is Professor Smith right now?", "privacy_refusal")
    assert intent == "privacy_refusal"


# ── tell me about this building ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "classified_as", ["observability", "general", "capability", "metadata", "clarification"]
)
def test_what_can_you_tell_me_about_this_building_is_the_buildings_own_description(classified_as):
    assert _final("What can you tell me about this building?", classified_as) == "capability"


@pytest.mark.parametrize(
    "question",
    [
        "What can you measure in this building?",  # the menu of measurands IS this lane's answer
        "Can you measure formaldehyde in Room 5.01?",
        "Do you have a noise sensor in the lab?",
    ],
)
def test_genuine_reach_questions_keep_the_observability_lane(question):
    assert _final(question, "observability") == "observability"


# ── when was it last serviced / what is overdue: dated records, the register lane ─────────────

MAINTENANCE_RECORDS = [
    "When was the lift last serviced?",  # Agent B's three questions, 2026-09-19
    "Which assets are overdue for maintenance?",
    "Which maintenance tasks are overdue?",
    "When was the chiller last maintained?",
    "Which cleaning tasks are overdue?",
    "What date was the boiler last serviced?",
    "Are any repairs overdue?",
    "How long ago was the lift serviced?",
]

#: Stakeholder-catalogue questions that contain the same verbs ("WHEN an asset is replaced") and ask
#: nothing about the last service. The first draft of the rule claimed all three.
NOT_ABOUT_THE_LAST_SERVICE = [
    "What information must be retained, linked or access-restricted when an asset is replaced, "
    "moved or disposed of?",
    "When assets were moved, replaced, isolated, recommissioned or retired, were active controls "
    "transferred while prior evidence remained linked?",
    "Which assurance, inspection, warranty or competence requirements may change when an asset is "
    "modified, replaced, relocated or used differently?",
]


@pytest.mark.parametrize("question", MAINTENANCE_RECORDS)
@pytest.mark.parametrize(
    "classified_as", ["capability", "metadata", "maintenance", "general", "clarification"]
)
def test_a_question_about_when_it_was_serviced_or_what_is_overdue_reaches_the_register_lane(
    question, classified_as
):
    # `metadata` is the register lane: with a held record class it answers from that register's rows
    assert _final(question, classified_as) == "metadata"


@pytest.mark.parametrize("question", NOT_ABOUT_THE_LAST_SERVICE)
def test_a_when_clause_about_replacing_an_asset_is_not_a_last_serviced_question(question):
    assert not rc.maintenance_record_question(question)


@pytest.mark.parametrize(
    "question, start, expected",
    [
        ("When was the fire alarm last tested?", "capability", "register"),  # dated COMPLIANCE item
        ("Which inspections are overdue?", "metadata", "register"),
        # Settled 2026-09-19 by `register_owns_work_orders_and_timetable` and verified live: a
        # WORK-ORDER question is the register's (it carries the ids, WO-008 and the rest); a
        # TICKET question is about aging, which only the events store tracks.
        ("How many open work orders are there?", "maintenance", "metadata"),
        ("Are there any overdue tickets?", "capability", "events"),
        ("Show me the maintenance schedule", "maintenance", "maintenance"),
        ("The lift is overdue for maintenance", "maintenance", "maintenance"),  # a statement
        ("The chiller is broken, it was last serviced in June", "maintenance", "maintenance"),
    ],
)
def test_compliance_items_work_orders_schedules_and_statements_keep_their_lane(
    question, start, expected
):
    assert _final(question, start) == expected


def test_the_dialogue_agents_capability_probe_yields_to_the_register_lane_for_these_questions():
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    probe = inspect.getsource(DialogueAgent.detect_intent).split("capability via ontology triples")[0]
    assert "_maintenance_record_question(user_query)" in probe
    assert rc.maintenance_record_question("When was the lift last serviced?")
    assert not rc.maintenance_record_question("Is the lift working?")


# ── wave 2: a question with nothing to read never reaches the sensor fetch ────────────────────

NOTHING_TO_READ = {
    # live 2026-09-19, all classified `sensor_data` and refused as "that question reaches N sensors"
    "What lux level is maintained for reading tasks?": "capability",  # a design standard
    "Which approved nearby space is suitable for a brief quiet pause before my next appointment?": "metadata",
    "Can temperature or humidity affect the CO2 sensor?": "general_guidance",
    "How can occupancy sensors lead to more efficient use?": "general_guidance",
}


@pytest.mark.parametrize("question, expected", sorted(NOTHING_TO_READ.items()))
@pytest.mark.parametrize("classified_as", ["sensor_data", "analytics", "recommend", "compare", "anomaly"])
def test_a_question_with_nothing_to_read_leaves_the_fetch_lanes(question, expected, classified_as):
    assert _final(question, classified_as) == expected


@pytest.mark.parametrize(
    "question, start",
    [
        ("What is the lux level in the atrium?", "sensor_data"),  # a reading
        ("What lux level is maintained in Room 1.06?", "sensor_data"),  # a named room
        ("Which rooms on floor 2 are suitable for a class tomorrow?", "deliberate"),  # placed, timed
        ("Which room is quietest right now?", "deliberate"),
        ("Show me CO2 for every sensor this week.", "analytics"),  # genuinely a big fetch
    ],
)
def test_a_real_reading_question_still_reaches_its_data_lane(question, start):
    assert _final(question, start) not in ("general_guidance", "scope_boundary")


def test_the_register_wins_over_guidance_because_it_runs_last():
    # the owner's order: register reach, then design standard, then guidance. Every rule in a stage
    # runs and the LAST match wins, so ungrounded_question_never_fetches sits after guidance.
    names = [r.name for r in rc.PARSE_STAGE_RULES]
    assert names.index("ungrounded_question_never_fetches") > names.index("general_guidance_question")
    assert names.index("scope_boundary") > names.index("ungrounded_question_never_fetches")


# ── wave 2: a maintenance schedule is a record, not an unknown ───────────────────────────────


@pytest.mark.parametrize("classified_as", ["events", "capability", "general", "maintenance", "metadata"])
def test_maintenance_scheduled_for_today_reaches_the_register_lane(classified_as):
    # live: the events lane has no kind for it and said "this building doesn't keep a record of that"
    assert _final("are there any maintenance task scheduled for today?", classified_as) == "metadata"


@pytest.mark.parametrize(
    "question",
    [
        "What maintenance is planned for tomorrow?",
        "Is any servicing scheduled this week?",
        "Which cleaning tasks are due today?",
    ],
)
def test_the_same_shape_in_other_words(question):
    assert rc.maintenance_record_question(question), question


@pytest.mark.parametrize(
    "question, start, expected",
    [
        # a POLICY question about schedules is not a schedule lookup: no near period
        (
            "Are planned maintenance tasks aligned with each asset type, duty, environment, "
            "criticality and governing obligation?",
            "maintenance",
            "maintenance",
        ),
        ("Any overdue tickets?", "capability", "events"),  # ticket AGING stays with the events store
        ("How many open tickets are there?", "general", "events"),
        ("The lift needs maintenance", "maintenance", "maintenance"),  # a statement files a report
    ],
)
def test_policy_questions_ticket_aging_and_statements_are_untouched(question, start, expected):
    assert _final(question, start) == expected
