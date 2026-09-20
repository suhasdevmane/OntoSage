# -*- coding: utf-8 -*-
"""Owner policy 2026-09-19: a building-KNOWLEDGE question that needs no building data is answered
as labelled general guidance, and must never reach the sensor fetch.

"Does humidity affect CO2 sensor accuracy?", "how do I control CO2?", "how do BREEAM and LEED
differ?" and "what does a delta-T mean?" met the sensor pipeline and were refused with "that
question reaches N sensors" -- an honest sentence answering a question nobody asked. The shape test
is deliberately conservative, because a false positive takes a DATA question away from the lane that
can read the building: it needs a guidance frame, a building-domain term, and NO grounding (no
place, no time window, no "this/our building", no record kind, no sensor id).

The negative table is as important as the positive one: every entry is a question that names
something of THIS building, or a procedure of it, and must keep the lane that answers it.
"""

import pytest

from orchestrator.services.guidance_shape import (
    has_grounding,
    is_general_guidance_question,
    names_building_domain,
)

pytestmark = pytest.mark.unit

GUIDANCE = [
    "Does humidity affect CO2 sensor accuracy?",  # the owner's four examples
    "How do I control CO2?",
    "How do BREEAM and LEED differ?",
    "What does a delta-T mean?",
    "What is the difference between BREEAM and LEED?",
    "How does a heat pump work?",
    "Why does CO2 build up when a room is closed up?",
    "What causes condensation on windows?",
    "What is a safe CO2 level?",
    "What is the recommended humidity range for offices?",
    "How can I improve air quality?",
    "What does PUE stand for?",
    "Explain how demand response works",
    "What is HVAC?",
    "How do you calibrate a CO2 sensor?",
    "What happens when an air filter clogs?",
    "How do glare sensors work?",  # from the phase-0 bank: a genuine how-does-it-work question
    # Live, 2026-09-19: both were classified `sensor_data` and refused with "that question reaches
    # 296 sensors" / "250 sensors". "The CO2 sensor" is the KIND, not an instrument in a room, and
    # "how can X lead to Y" asks what a kind of sensor is FOR.
    "Can temperature or humidity affect the CO2 sensor?",
    "How can occupancy sensors lead to more efficient use?",
    "How do CO2 sensors help save energy?",
    "How can daylight sensors reduce lighting costs?",
]

DATA_OR_PROCEDURE_OF_THIS_BUILDING = [
    "What is the CO2 in room 5.01?",  # a reading
    "Is the CO2 too high?",
    "What is the maximum CO2 reading?",  # a data question, however abstract it sounds
    "How can I improve air quality in my lab?",  # my / lab
    "How do I control the temperature in Room 3.01?",  # a named place
    "Why is Room 5.01 stuffy?",
    "Does the CO2 on floor 3 affect comfort today?",
    "How has CO2 changed this week?",  # a time window
    "How do I report a faulty sensor?",  # a procedure of this building
    "How do I book a meeting room?",
    "How do I get to the seminar room from reception?",
    "Who do I contact about a broken thermostat?",
    "What does the fire policy say about temperature?",  # a record
    "Can you reduce the temperature?",  # a command, not a subject
    "Turn the heating off",
    "How does this building's heating work?",  # this building
    "What is the recommended CO2 limit in our policy?",  # our / policy
    "Which floor has the highest CO2?",
    "Do you have a CO2 sensor in the lab?",
    "How many sensors does the building have?",
    "When was the CO2 sensor calibrated?",
    "What can you tell me about this building?",
]

#: The first draft of the shape test claimed 21 of the project's 4,271 known questions and 18 were
#: DATA questions. Each is pinned here, verbatim from the stakeholder catalogue, so the frames
#: that let them through ("versus", "compare", "could ... cause", an unanchored "how would ...
#: affect", "meaning of") cannot come back.
FALSE_POSITIVES_OF_THE_FIRST_DRAFT = [
    "Kitchen extract versus dining room CO2 at lunch - is makeup air adequate?",
    "Old wing versus new wing: complaints per occupant, normalised.",
    "Show energy per visitor for event days versus normal days.",
    "Trend CO2 versus damper position for the lecture theatre - is demand control working?",
    "Show me the original commissioning setpoints versus current values, highlighting drift.",
    "What building systems are on the corporate network versus the OT network?",
    "How does the gym's air quality compare with the studios at peak times?",
    "How does observed occupancy compare with the design assumptions for each space?",
    "How do crowding, background noise and measured room conditions during this deadline week "
    "differ from ordinary teaching weeks?",
    "Which current HVAC alarms and abnormal signals could share the same upstream plant cause?",
    "What does the sprinkler or water-mist system indicate about activation, valves, pumps, tanks, "
    "flow and pressure?",
    "Before approval, how would a proposed timetable, room-use or layout change affect active "
    "service zones, peaks, energy and operational carbon?",
    "What's the meaning of life, building?",
    "How much energy did the weekend shutdown actually save versus a normal weekend?",
]

NOT_BUILDING_KNOWLEDGE = [
    "How do I bake bread?",  # a how-to, but not a building one: the off-topic decline owns it
    "What is the capital of France?",
    "What does the word 'ubiquitous' mean?",
    "Tell me a joke.",
]


@pytest.mark.parametrize("question", GUIDANCE)
def test_a_building_knowledge_question_is_general_guidance(question):
    assert is_general_guidance_question(question), question


@pytest.mark.parametrize("question", DATA_OR_PROCEDURE_OF_THIS_BUILDING)
def test_a_question_that_names_this_building_keeps_its_own_lane(question):
    assert not is_general_guidance_question(question), question


@pytest.mark.parametrize("question", FALSE_POSITIVES_OF_THE_FIRST_DRAFT)
def test_the_data_questions_the_first_draft_wrongly_claimed_keep_their_lane(question):
    assert not is_general_guidance_question(question), question


@pytest.mark.parametrize("question", NOT_BUILDING_KNOWLEDGE)
def test_a_how_to_about_something_else_is_not_building_guidance(question):
    assert not is_general_guidance_question(question), question


def test_the_three_halves_are_each_required():
    # frame without domain
    assert not is_general_guidance_question("How do I improve my golf swing?")
    # domain without frame
    assert not is_general_guidance_question("CO2 sensors are useful.")
    # frame and domain, grounded
    assert not is_general_guidance_question("How do I reduce CO2 in Room 5.01?")
    assert names_building_domain("How do I reduce CO2 in Room 5.01?")
    assert has_grounding("How do I reduce CO2 in Room 5.01?")


def test_empty_input_is_not_guidance():
    assert not is_general_guidance_question("")
    assert not is_general_guidance_question(None)


@pytest.mark.parametrize(
    "question",
    [
        "What happens to the control strategy if the outside air sensor fails?",  # "the ... strategy"
        "Do you have a CO2 sensor in the lab?",  # "the lab"
        "How many sensors does the building have?",  # "the building"
        "When was the CO2 sensor in Room 5.01 last calibrated?",  # a named room
        "How can I improve air quality in my lab?",  # "my lab"
        "How can we reduce our energy use?",  # "our"
    ],
)
def test_dropping_sensor_from_the_grounding_list_does_not_take_a_grounded_question(question):
    """`sensor` and `meter` left the definite-article grounding clause so "the CO2 sensor" reads as
    the kind. Every sentence here really does name this building's kit, and carries another ground."""
    assert not is_general_guidance_question(question), question


# ── a lay term may not OPEN a hyphen compound (live 2026-09-19) ──────────────────────────────


def _lay_terms():
    import re as _re
    from pathlib import Path

    terms = set()
    for ttl in ("ontology/hbco_mappings.ttl", "ontology/hbco_core.ttl"):
        text = Path(ttl).read_text(encoding="utf-8", errors="replace")
        terms |= {m.lower() for m in _re.findall(r'hbco:layTerm\s+"([^"]+)"', text)}
    return terms


@pytest.mark.parametrize(
    "term, text, names_it",
    [
        # "Will clock drift, time-zone settings or a daylight-saving transition change any access
        # window?" named no quantity and was refused as covering 269 illuminance sensors.
        ("daylight", "a daylight-saving transition", False),
        ("privacy", "privacy-safe aggregate evidence", False),
        ("energy", "energy-efficient lighting", False),
        ("emergency", "emergency-access constraints", False),
        # the HEAD decides: a coordinate pair keeps both, and a term that CLOSES a compound is
        # the head
        ("temperature", "a temperature-humidity combination", True),
        ("meter", "the sub-meter reading", True),
        # and an ordinary mention is untouched
        ("daylight", "how much daylight does the room get", True),
        ("temperature", "what is the temperature in room 5.01", True),
    ],
)
def test_a_term_that_only_modifies_a_compound_does_not_name_the_subject(term, text, names_it):
    from orchestrator.services.concept_resolver import term_names_the_subject

    assert term_names_the_subject(term, text, _lay_terms()) is names_it


def test_the_judge_is_the_whole_term_list_not_the_words_inside_it():
    """"saving", "safe" and "efficient" each sit inside some multi-word lay term ("energy
    saving"), so judging the head by WORDS would have let every failing compound through."""
    from orchestrator.services.concept_resolver import term_names_the_subject

    words = {w for t in _lay_terms() for w in t.split()}
    assert "saving" in words and "safe" in words  # the trap
    assert term_names_the_subject("daylight", "a daylight-saving transition", words) is True
    assert term_names_the_subject("daylight", "a daylight-saving transition", _lay_terms()) is False


# ── the guidance rule took a DATA question (live 2026-09-19) ─────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        # "what happens to the buildingS enery use overnight" was answered as labelled general
        # guidance although the building records per-floor night-time means. Two holes: the place
        # list knew only the singular, and "overnight" was not a time word.
        "what happens to the buildings enery use overnight",
        "What happens to the buildings energy use overnight?",
        "What happens to energy use overnight?",
        "What happens to CO2 at night?",
        "What happens to the offices temperature after hours?",
        "What happens to our sites energy use out of hours?",
    ],
)
def test_a_place_in_the_plural_or_a_part_of_the_day_is_grounding(question):
    assert not is_general_guidance_question(question), question


def test_the_knowledge_questions_that_must_still_be_guidance_are_untouched():
    for question in GUIDANCE:
        assert is_general_guidance_question(question), question
