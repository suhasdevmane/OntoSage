# -*- coding: utf-8 -*-
"""Wave 2 (2D-07): a question that names no place, time, record or measured thing has nothing for a
sensor read to be about, and was refused with "that question reaches 296 sensors".

Five dev-tail questions, all classified `sensor_data`:

* "Can temperature or humidity affect the CO2 sensor?" and "How can occupancy sensors lead to more
  efficient use?" -- knowledge questions (the guidance-shape tests own them);
* "What lux level is maintained for reading tasks?" -- a DESIGN-STANDARD question: the level the
  lighting is designed to keep for a task, which no reading answers;
* "Which approved nearby space is suitable for a brief quiet pause before my next appointment?" --
  a workspace-register question: which spaces are approved and suitable.

This file pins the two shapes this module owns and, above all, what they must NOT take: a question
that names a room, a time or a record is the asker wanting THIS building's answer.
"""

import pytest

from orchestrator.services import ungrounded_question as uq

pytestmark = pytest.mark.unit

DESIGN_STANDARD = [
    "What lux level is maintained for reading tasks?",  # the failing question
    "What temperature is maintained for offices?",
    "What ventilation rate is required for classrooms?",
    "Which humidity level is recommended for a server room?",
    "What lighting level is specified for corridors?",
    "What CO2 limit is acceptable for meeting rooms?",
]

SUITABLE_SPACE = [
    "Which approved nearby space is suitable for a brief quiet pause before my next appointment?",
    "Which spaces are suitable for a confidential call?",
    "Which rooms are appropriate for a quiet study session?",
    "What area is approved for a private conversation?",
]

STAYS_WITH_THE_DATA_LANES = [
    "What lux level is maintained in Room 1.06?",  # a named room
    "What lux level is maintained on floor 3 today?",  # a place and a time
    "What is the lux level in the atrium?",  # a reading, no design shape
    "What temperature is Room 5.01 at?",
    "What is the average temperature this week?",
    "Which room is the quietest right now?",  # a ranking of live readings
    "Which rooms on floor 2 are suitable for a class tomorrow?",  # placed and timed
    "Which room is best for a meeting this afternoon?",
    "What lighting level does the policy specify for corridors?",  # names a record: documents own it
    "How many rooms are suitable for a meeting?",  # a count, not a choice
]


@pytest.mark.parametrize("question", DESIGN_STANDARD)
def test_a_design_standard_question_goes_to_the_documents_and_regime_records(question):
    assert uq.design_standard_question(question), question
    assert uq.handoff(question) == "capability"


@pytest.mark.parametrize("question", SUITABLE_SPACE)
def test_a_which_space_is_suitable_question_goes_to_the_workspace_register(question):
    assert uq.suitable_space_question(question), question
    assert uq.handoff(question) == "metadata"


@pytest.mark.parametrize("question", STAYS_WITH_THE_DATA_LANES)
def test_a_question_that_names_this_building_keeps_the_data_lanes(question):
    assert uq.handoff(question) is None, question


@pytest.mark.parametrize(
    "question, grounded",
    [
        ("What lux level is maintained for reading tasks?", False),
        ("What lux level is maintained in Room 1.06?", True),
        ("Is it too bright today?", True),
        ("What does our policy say?", True),
        ("Which work orders are open?", True),
        ("Can humidity affect a CO2 sensor?", False),
    ],
)
def test_grounding_is_a_named_place_a_time_a_record_or_this_building(question, grounded):
    assert uq.has_grounding(question) is grounded


def test_only_fetch_intents_are_the_rules_business():
    assert "sensor_data" in uq.FETCH_INTENTS and "analytics" in uq.FETCH_INTENTS
    for lane in ("capability", "metadata", "events", "deliberate", "register", "general_guidance"):
        assert lane not in uq.FETCH_INTENTS


def test_empty_input_is_no_shape():
    assert uq.handoff("") is None and uq.handoff(None) is None


# ── ALL THREE STAGES, because the concept stage runs last ────────────────────────────────────
#
# The wave-2 rule was verified over parse and post only, and live "What lux level is maintained for
# reading tasks?" still hit the fetch: the parse rule sent it to `capability`, then the CONCEPT
# stage's `capability_measurand_is_data` saw "lux" resolve to an illuminance sensor and converted it
# to a reading, and the fetch refused it ("that covers all 268 illuminance sensors at once").
# Checking two stages of a three-stage contract is checking the wrong thing; these run all three.

from orchestrator.services.routing_contract import apply_contract  # noqa: E402

ILLUMINANCE = [{"brick_classes": ["brick:Illuminance_Sensor"]}]
TEMPERATURE = [{"brick_classes": ["brick:Temperature_Sensor"]}]


def _all_stages(question, start, concepts):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": concepts}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


@pytest.mark.parametrize("start", ["sensor_data", "analytics", "capability", "compare"])
def test_the_lux_question_survives_the_concept_stage(start):
    assert _all_stages("What lux level is maintained for reading tasks?", start, ILLUMINANCE) == "capability"


@pytest.mark.parametrize(
    "question, concepts",
    [
        ("What temperature is maintained for offices?", TEMPERATURE),
        ("What ventilation rate is required for classrooms?", TEMPERATURE),
    ],
)
def test_other_design_standards_survive_it_too(question, concepts):
    assert _all_stages(question, "sensor_data", concepts) == "capability"


@pytest.mark.parametrize(
    "question, concepts, expected",
    [
        ("What is the lux level in the atrium?", ILLUMINANCE, "sensor_data"),  # a reading
        ("What lux level is maintained in Room 1.06?", ILLUMINANCE, "sensor_data"),  # named room
        ("Is it too warm in Room 5.01?", TEMPERATURE, "sensor_data"),
        ("What is the average CO2 last week?", TEMPERATURE, "analytics"),
    ],
)
def test_a_reading_question_naming_a_measurand_still_reaches_its_data_lane(question, concepts, expected):
    # the concept-stage rule exists to rescue these from the capability lane (BUG-225): the guard
    # must not cost it that job
    assert _all_stages(question, "capability", concepts) == expected


def test_a_documentary_question_keeps_the_lane_it_always_had():
    assert _all_stages("What does the policy say about temperature?", "capability", TEMPERATURE) == "capability"


# ── wave 3: the same blind spot, two doors over (hand read, 2026-09-19) ───────────────────────

NOISE = [{"brick_classes": ["brick:Sound_Level_Sensor"]}]


@pytest.mark.parametrize("start", ["capability", "sensor_data", "recommend", "analytics"])
def test_the_quiet_pause_variant_reaches_the_workspace_register(start):
    """Live: refused as covering 234 sound sensors. "quiet" resolves to a sound sensor, so the
    concept stage converted a question about WHICH SPACES ARE APPROVED into a reading lookup —
    the lux mechanism exactly, from a `capability` label the parse-stage rule cannot claim."""
    q = "Which approved nearby space is suitable for a brief quiet pause before my next appointment?"
    assert _all_stages(q, start, NOISE) == "metadata"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Is the temperature the same across the space?", "compare"),  # live: 296 sensors refused
        ("Is the temperature consistent across the building?", "compare"),
        ("Is CO2 even across the floors?", "compare"),
        ("Does the temperature vary much between floors?", "compare"),
    ],
)
@pytest.mark.parametrize("start", ["sensor_data", "analytics"])
def test_a_uniformity_question_is_a_comparison_not_a_reading(question, expected, start):
    assert _all_stages(question, start, TEMPERATURE) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Is the temperature the same across Room 5.01?",  # one named room: that room's own spread
        "What is the temperature in Room 5.01?",
        "Is the signage the same across the building?",  # no measurable quantity
    ],
)
@pytest.mark.parametrize("start", ["sensor_data", "analytics"])
def test_a_named_room_or_an_unmeasured_subject_is_not_turned_into_a_comparison(question, start):
    assert _all_stages(question, start, TEMPERATURE) != "compare"


def test_a_uniformity_phrase_without_a_quantity_claims_nothing():
    from orchestrator.services.routing_contract import uniformity_question

    assert uniformity_question("Is the temperature the same across the building?")
    assert not uniformity_question("Is the signage the same across the building?")
    assert not uniformity_question("Are the opening hours consistent across the site?")
