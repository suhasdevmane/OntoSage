# -*- coding: utf-8 -*-
"""Wave 9 (tail K): retrieval narration in every spelling, and a design question finding its topic.

1. "do you have any liens or problems with the city or town" was answered "The 34 items returned by
   the query are all related to building systems (cooling capacity, sensor types ...)" on one run
   and a clean decline on the next: the same retrieval, narrated once and not the other. A reader
   never asked what a query returned. "items", "hits" and "matches" were not among the nouns the
   narration detector knew, and "the query returned ..." (the query as the SUBJECT) was not a shape
   it knew at all.

2. "How does the building collect rain water?" was answered from the sensor lane with an invented
   mechanism ("channelling it from the roof into a central drainage system monitored by the Water
   Flow Sensor Main") and a 5-second-resolution data footer. The building's own text states only
   "Rainwater harvesting for toilet flushing" (Cap_sustainability); nothing in it describes a
   collection mechanism. The capability lane can answer that, and did not because the topic's lay
   terms carried no rain word. Multi-word phrases were added — and they must not match a question
   about how MUCH was harvested, which is a measurement the building does not record.
"""

from __future__ import annotations

import pytest

from orchestrator.services import absence_wording as aw

pytestmark = pytest.mark.unit

QUESTION = "do you have any liens or problems with the city or town"


@pytest.mark.parametrize(
    "sentence",
    [
        "34 items returned by the query are all related to building systems.",
        "The 34 items returned by the query are all related to building systems (cooling capacity).",
        "The query returned 34 items about cooling.",
        "The SPARQL query found nothing about liens.",
        "The hits retrieved only list sensors.",
        "The 12 matches returned relate to plant rooms.",
        "The rows returned only list sensors.",
    ],
)
def test_prose_about_what_a_query_returned_is_recognised_as_retrieval_narration(
    sentence: str,
) -> None:
    assert aw.describes_retrieval(sentence), sentence


@pytest.mark.parametrize(
    "sentence",
    [
        "There are 12 records in the register.",
        "Three of the items are marked low.",
        "The register lists 24 work orders, 9 of them open.",
        "Two matches were found between the booking and the timetable: Room 1.06 and Room 1.04.",
        "The query returned a single record: Approval APR-030.",  # reworded in place, kept
        "No anomalies were detected in the dataset.",
    ],
)
def test_a_fact_about_the_building_is_never_mistaken_for_narration(sentence: str) -> None:
    assert not aw.describes_retrieval(sentence), sentence


def test_a_narrated_retrieval_is_removed_and_the_reader_gets_one_honest_sentence() -> None:
    answer = (
        "The building's records do not contain any information about liens. "
        "The 34 items returned by the query are all related to building systems (e.g., cooling "
        "capacity, sensor types) and none of them record any legal or municipal issues."
    )
    out = aw.rewrite_semantic_absence(answer, QUESTION, "Abacws Building")
    assert out is not None
    for phrase in ("returned by the query", "items returned", "the query"):
        assert phrase not in out.lower(), out


def test_the_single_record_form_is_still_reworded_and_kept() -> None:
    kept = aw.strip_store_addressing("The query returned a single record: Approval APR-030.")
    assert kept == "There is one record: Approval APR-030."


# ── the design question's topic ─────────────────────────────────────────────────────────────────

_SUSTAINABILITY_LAY = (
    "sustainability, green, environment, carbon, recycling, energy efficiency, solar, renewable, "
    "breeam, epc, environmental, eco, waste, bins, green building, rainwater harvesting, harvest "
    "rainwater, collect rainwater, collect rain water, rain water collection, rain water harvesting"
)


@pytest.mark.parametrize(
    "question, matches",
    [
        ("How does the building collect rain water?", True),
        ("Does the building have rainwater harvesting?", True),
        ("How is rainwater collected here? I mean rain water collection.", True),
        ("How much rainwater harvested is used?", False),  # a measurement nobody records
        ("What is the rainfall today?", False),  # a weather reading
    ],
)
def test_a_design_question_about_rain_finds_the_sustainability_topic_and_a_volume_question_does_not(
    question: str, matches: bool
) -> None:
    from orchestrator.services.capability_graph_resolver import _MIN_SCORE, _phrases, _score

    assert (_score(question.lower(), _phrases(_SUSTAINABILITY_LAY)) >= _MIN_SCORE) is matches
