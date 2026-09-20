# -*- coding: utf-8 -*-
"""An abstract question is not answered with one odd word quoted back (2D-16 wave 2).

Wave-1 development read: "I couldn't answer that from Abacws Building's records. Which measurement
or record do you mean by **specialist** / **whole** / **weather**?" The questions were abstract or
about the weather, not missing a measurement. Three shapes now get three answers.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from orchestrator.services import clarification as cl
from orchestrator.services.grounding_guard import names_internal_vocabulary

pytestmark = pytest.mark.unit

B = "Example Building"
MEASURED = ["fan state", "lift state", "air quality"]


def _rec(label, instances=10, terms=()):
    return SimpleNamespace(label=label, instances=instances, terms=tuple(terms))


RECORDS = [
    _rec("Compliance check", 40, ("compliance check",)),
    _rec("Stakeholder group", 30, ("stakeholder group",)),
    _rec("Approval and evidence record", 22, ("approval", "evidence")),
    _rec("Incident and near-miss record", 17, ("incident", "near miss")),
    _rec("Room booking", 88, ("booking",)),
]

SPECIALIST_Q = (
    "Does the verified timeline support the stated root cause, what alternatives remain "
    "plausible, and which specialist evidence is still needed?"
)
WHOLE_Q = (
    "Which eligible rooms have a currently verified whole route that meets the functional "
    "requirements the requester chose to state?"
)


def _compose(question, unmatched=(), outdoor=None, records=RECORDS):
    return cl.compose(
        building=B,
        question=question,
        unmatched=unmatched,
        measured=MEASURED,
        records=records,
        outdoor=outdoor,
    )


# ── abstract ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,unmatched",
    [(SPECIALIST_Q, ["specialist", "plausible"]), (WHOLE_Q, ["whole", "requester"])],
)
def test_an_abstract_question_gets_no_question_back_and_no_bare_word(question, unmatched):
    kind, text = _compose(question, unmatched)
    assert kind == cl.KIND_ABSTRACT
    assert "?" not in text, f"an abstract question is not answered with a question:\n{text}"
    assert "Which measurement or record do you mean" not in text
    for word in unmatched:
        assert f"**{word}**" not in text, "one odd word was quoted as if it were a field"
    assert names_internal_vocabulary(text) is None


def test_it_quotes_no_fragment_of_the_question_as_a_topic():
    """Wave 6: two arbitrary tokens ("exported unavailable") were presented as the subject."""
    _, text = _compose(SPECIALIST_Q, ["specialist"])
    assert "nothing came back about" not in text
    assert text.startswith("I couldn't answer that from ")


def test_it_lists_the_two_or_three_nearest_things_the_building_can_answer():
    _, text = _compose(SPECIALIST_Q, ["specialist"])
    assert "The nearest things I can answer are" in text
    assert "Approval and evidence record" in text, "ranked by closeness to 'evidence'"
    assert text.count("records") >= 1 and "air quality" in text


def test_a_word_with_no_neighbour_is_dropped_rather_than_quoted():
    assert cl.phrases_for("what about the whole?", ["whole"]) == []
    assert cl.phrases_for("which specialist evidence is needed", ["specialist"]) == [
        "specialist evidence"
    ]


def test_an_unreadable_building_is_not_padded():
    _, text = cl.compose(
        building=B, question=SPECIALIST_Q, unmatched=[], measured=[], records=[], outdoor=None
    )
    assert "nearest things" not in text and text.startswith("I couldn't answer that")


# ── a genuinely missing referent ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,noun",
    [
        ("What happened during the incident?", "incident"),
        ("Who owns this service?", "service"),
        ("When does that contract end?", "contract"),
        ("Is the meeting confirmed?", "meeting"),
    ],
)
def test_a_short_question_that_points_at_a_thing_asks_which_one_once(question, noun):
    kind, text = _compose(question)
    assert kind == cl.KIND_REFERENT and cl.referent_noun(question) == noun
    assert text.count("?") == 1 and text.startswith(f"Which {noun} do you mean?")


def test_the_candidates_named_are_the_record_kinds_the_building_holds():
    _, text = _compose("What happened during the incident?")
    assert "Incident and near-miss record" in text
    assert "Room booking" not in text


def test_no_matching_record_kind_asks_for_a_place_or_date_instead_of_inventing_candidates():
    _, text = _compose("Who owns this service?", records=[_rec("Room booking")])
    assert "Room booking" not in text and "give a room, floor or date" in text


def test_a_long_question_that_mentions_the_incident_is_abstract_not_a_missing_referent():
    q = (
        "Does the verified timeline of the incident support the stated root cause, and which "
        "alternative explanations remain plausible given the recorded evidence?"
    )
    assert cl.referent_noun(q) == ""
    assert cl.classify(q) == cl.KIND_ABSTRACT


# ── weather ──────────────────────────────────────────────────────────────────


def test_current_weather_questions_are_recognised_and_forecasts_are_left_to_the_scope_policy():
    assert cl.is_current_weather_question("how is the weather outside now?")
    assert cl.is_current_weather_question("is it raining?")
    assert not cl.is_current_weather_question("will it rain tomorrow?")
    assert not cl.is_current_weather_question("what is the weather forecast for next week")
    assert not cl.is_current_weather_question("how stuffy is Room 1.06?")


def test_weather_gives_the_outdoor_readings_the_building_records_with_their_time():
    readings = [
        cl.OutdoorReading("outdoor temperature", 12.34, "°C", "03:50 on 19 Sep"),
        cl.OutdoorReading("outdoor humidity", 78.0, "%", "03:50 on 19 Sep"),
        cl.OutdoorReading("wind speed", 4.5, "m/s", "03:45 on 19 Sep"),
    ]
    kind, text = _compose("how is the weather outside now?", outdoor=readings)
    assert kind == cl.KIND_WEATHER
    assert text.startswith("**I don't hold a weather forecast.**")
    assert "outdoor temperature 12.3 °C (at 03:50 on 19 Sep)" in text
    assert "outdoor humidity 78 % (at 03:50 on 19 Sep)" in text
    assert "wind speed 4.5 m/s (at 03:45 on 19 Sep)" in text
    assert "Those are readings, not a forecast." in text
    assert "?" not in text and "Which measurement" not in text


def test_weather_when_the_outdoor_sensors_could_not_be_read_says_so_plainly():
    _, text = _compose("how is the weather outside now?", outdoor=[])
    assert (
        text
        == "**I don't hold a weather forecast.** I also couldn't read Example Building's outdoor sensors just now."
    )


def test_weather_when_nobody_tried_makes_no_claim_about_the_sensors():
    _, text = _compose("how is the weather outside now?", outdoor=None)
    assert text == "**I don't hold a weather forecast.**"


def test_no_shape_states_a_figure_it_was_not_given():
    for q in (SPECIALIST_Q, "What happened during the incident?"):
        _, text = _compose(q, ["specialist"])
        assert not re.search(r"(?<![A-Za-z])\d", text), text


def test_a_short_unclassified_question_is_answered_plainly_with_no_question_back():
    kind, text = _compose("Anything about Fridays?", ["fridays"])
    assert kind == cl.KIND_PLAIN and "?" not in text


def test_a_named_place_is_kept_in_the_readers_words_in_an_abstract_answer():
    _, text = cl.compose(
        building=B,
        question=SPECIALIST_Q,
        unmatched=["specialist"],
        measured=MEASURED,
        records=RECORDS,
        entities=["Room 5.04"],
    )
    assert text.startswith(
        "I couldn't answer that about **Room 5.04** from Example Building's records"
    )
