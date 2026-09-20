# -*- coding: utf-8 -*-
"""Wave 9 (2D-16): the gate skips the new declines, the weather shape needs a weather subject, and
store vocabulary, class definitions and empty-result strings never reach a reader. Live texts."""

from __future__ import annotations

import glob
import json
import os

import pytest

from orchestrator.services import absence_wording as aw
from orchestrator.services import answer_relevance_gate as gate
from orchestrator.services import answer_shape as ash
from orchestrator.services import clarification as cl

pytestmark = pytest.mark.unit

CHANGE_Q = (
    "Did the recent operational change produce a sustained service benefit after timetable, "
    "weather, season and concurrent changes are accounted for?"
)


# ── (1) the gate does not judge a decline ────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        "I couldn't tie that question to a reading I can give you, so I will not guess at one.",
        "I couldn’t answer that from Abacws Building’s records, but here is what I hold.",
        "The Compliance register (82 records) cannot answer this: it records checks and due dates.",
        "This building doesn't keep a record of that, though it does keep maintenance records.",
        "**Asset Engineering Register** cannot answer this: it records asset status and owners only.",
        "**I don't hold a weather forecast.** Abacws Building's outdoor sensors last recorded a value.",
    ],
)
def test_the_new_standard_declines_cost_no_call(answer):
    assert gate.skip_reason(answer, "register") == "already an honest decline"


def test_a_real_answer_is_still_judged():
    text = (
        "The building has 234 rooms across six floors, and the library holds 12 study areas "
        "on level two with quiet seating for around 80 students."
    )
    assert gate.skip_reason(text, "register") == ""


# ── (2) weather must be the subject ──────────────────────────────────────────


def test_a_weather_word_among_confounders_is_not_a_weather_question():
    assert not cl.is_current_weather_question(CHANGE_Q)
    assert cl.classify(CHANGE_Q) != cl.KIND_WEATHER


@pytest.mark.parametrize(
    "q",
    [
        "What is the weather like?",
        "How hot is it outside?",
        "Is it raining?",
        "what's the weather outside right now",
        "how cold is it out there",
    ],
)
def test_a_question_about_the_weather_still_is(q):
    assert cl.is_current_weather_question(q)


@pytest.mark.parametrize(
    "q",
    [
        "Is there a muster point outside the building?",
        "Where is the nearest bike store outside?",
        "Will it rain tomorrow?",
        "Which weather, occupancy and tariff data does the building hold?",
    ],
)
def test_a_place_word_or_a_forecast_or_a_list_is_not(q):
    assert not cl.is_current_weather_question(q)


# ── (3) jargon and bare answers ──────────────────────────────────────────────

TRIPLE = (
    "I did not find any specific triple that states whether the shared meeting booth is "
    "currently available."
)


def test_a_sentence_in_the_stores_terms_becomes_the_honest_decline():
    out = aw.rewrite_semantic_absence(TRIPLE, "Is the shared meeting booth available?", "B")
    assert out and "triple" not in out.lower() and "found nothing" in out or "does not exist" in out


def test_store_vocabulary_is_dropped_from_a_longer_answer_and_the_rest_stays():
    text = (
        "The booth on level 2 is free until 15:00 today and holds four people. I did not find "
        "any triple that gives its booking owner."
    )
    out = aw.drop_store_vocabulary(text, "is the booth free?")
    assert "triple" not in out and out.startswith("The booth on level 2")


def test_a_reader_who_asks_about_the_ontology_is_answered_in_its_terms():
    text = "There are 12,000 triples in the graph."
    assert aw.drop_store_vocabulary(text, "how big is the ontology?") == text


def test_a_chart_is_still_a_graph():
    text = "The graph above shows CO2 across the week, peaking at 812 ppm on Tuesday afternoon."
    assert aw.drop_store_vocabulary(text, "plot CO2") == text


CLASS_DEF = (
    "The building's records define the *Entrance* class as \"the location and space of a "
    'building where people enter", but they do not list emergency exits."'
)


def test_an_ontology_class_definition_is_not_an_answer():
    q = "Where is the nearest emergency exit from the lab on floor 3?"
    assert ash.non_answer_reason(CLASS_DEF, q).startswith("an ontology class definition")
    assert ash.non_answer_reason("The records define the Entrance class as a space.", q)


def test_asking_what_a_class_means_gets_the_definition():
    assert ash.non_answer_reason(CLASS_DEF, "what does the Entrance class mean?") is None


@pytest.mark.parametrize(
    "text", ["No data found for your query.", "No results found.", "**No records were found.**"]
)
def test_a_bare_empty_result_is_not_an_answer(text):
    assert ash.non_answer_reason(text, "which rooms are booked?")


def test_an_empty_result_that_names_its_subject_is_left_alone():
    assert not ash.is_bare_no_data("No data found for room 5.01 between 09:00 and 10:00 today.")


# ── (4) a decline is not followed by unrelated advice ────────────────────────

ROUTE_Q = (
    "Before I set out, can you summarise my verified route, support contacts, recheck points "
    "and contingencies?"
)
ADVICE = (
    "You'll need to pull those from the building management database or the facility-operations "
    "team. ### 1. Use the CO₂ sensor to control ventilation **Why:** high CO₂ slows "
    "thinking. ### 2. Dim the lights **Why:** it saves energy."
)


def test_advice_that_follows_a_decline_and_is_not_about_the_question_is_dropped():
    out = aw.strip_unrelated_body_after_decline(ADVICE, ROUTE_Q)
    assert out.startswith("You'll need to pull those") and "CO" not in out and "###" not in out


def test_advice_with_a_blank_line_and_a_typographic_apostrophe_too():
    text = ADVICE.replace("You'll", "You’ll").replace(" ### 1.", "\n\n### 1.")
    out = aw.strip_unrelated_body_after_decline(text, ROUTE_Q)
    assert "CO" not in out


def test_a_decline_that_goes_on_to_say_something_about_the_question_is_untouched():
    text = (
        "I did not find a verified route for you.\n\nThe building does keep evacuation route "
        "records, which I can read for you."
    )
    assert (
        aw.strip_unrelated_body_after_decline(text, "what is my verified evacuation route?") == text
    )


def test_an_answer_that_does_not_open_with_a_decline_is_untouched():
    text = "Use the CO2 sensor.\n\n### 1. Ventilate\n\nOpen the vents."
    assert aw.strip_unrelated_body_after_decline(text, ROUTE_Q) == text


# ── the standard: nothing the hand read called good may change ───────────────

_PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "phase0")


def _recorded():
    for path in sorted(glob.glob(os.path.join(_PH, "*.jsonl"))):
        base = os.path.basename(path)
        if base.endswith("_read.jsonl") or "tail_L" in base or "answer_judge" in base:
            continue
        rp = path.replace(".jsonl", "_read.jsonl")
        reads = (
            [json.loads(x) for x in open(rp, encoding="utf-8") if x.strip()]
            if os.path.exists(rp)
            else []
        )
        try:
            rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
        except ValueError:
            continue
        for i, row in enumerate(rows):
            verdict = (reads[i].get("verdict") if i < len(reads) else None) or "?"
            yield row.get("q") or "", row.get("answer") or "", verdict


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_no_recorded_good_answer_or_decline_is_changed_by_the_wave_nine_guards():
    changed = []
    for q, a, v in _recorded():
        if not a.strip() or not v.startswith("GOOD"):
            continue
        if (
            ash.non_answer_reason(a, q)
            or aw.drop_store_vocabulary(a, q) != a
            or aw.strip_unrelated_body_after_decline(a, q) != a
        ):
            changed.append((q[:70], a[:100].replace("\n", " ")))
    assert not changed, "\n".join(f"{q} -> {a}" for q, a in changed)
