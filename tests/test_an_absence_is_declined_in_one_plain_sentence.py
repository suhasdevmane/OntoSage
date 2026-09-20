# -*- coding: utf-8 -*-
"""'Which rooms are swimming pools?' and 'Is there a swimming pool?' get the same kind of decline.

Wave-1 development read: the first was answered "I'm sorry, but the building model does not record
which rooms are swimming pools. The 100 query results you received only list spaces ... you would
need a field that explicitly marks a space as a pool ... I can help you filter", the second with one
plain sentence. Narrating the pipeline ("the results you received") and telling a reader to add a
field to a model they cannot edit are both defects; one honest sentence replaces them.
"""

from __future__ import annotations

import pytest

from orchestrator.services import absence_wording as aw

pytestmark = pytest.mark.unit

WAVE1_PROSE = (
    "I’m sorry, but the building model does not record which rooms are swimming pools.  \n"
    "The 100 query results you received only list spaces (floors and rooms) and how many sensors "
    "each space contains; none of those records indicate a “swimming pool” classification.\n\n"
    "If you need to identify swimming‑pool rooms, you would need a field that explicitly marks a "
    "space as a pool (e.g., a “room_type” or “facility” attribute). Once that field is available, "
    "I can help you filter the list accordingly."
)


def test_the_wave_one_prose_is_recognised_and_replaced_by_one_sentence():
    out = aw.rewrite_semantic_absence(
        WAVE1_PROSE, "Which rooms are swimming pools?", "Abacws Building"
    )
    assert out == (
        "'swimming pool' does not exist in this building, so there is nothing to report about it."
    ), "the same sentence the referent gate gives 'Is there a swimming pool?'"
    assert "query results" not in out and "field" not in out and "sorry" not in out.lower()
    assert out.count(".") == 1 and "?" not in out


@pytest.mark.parametrize(
    "prose",
    [
        "The building model does not record air-handling duty. The results you received only list rooms.",
        "The data does not contain a pool flag; you would need an attribute marking it.",
        "The records returned do not include that. You would need a new property for it.",
    ],
)
def test_narrating_the_pipeline_or_asking_for_a_new_field_is_recognised(prose):
    assert aw.is_internal_absence_prose(prose)


@pytest.mark.parametrize(
    "fine",
    [
        "The register lists eight waste streams. It does not include specialist rules.",
        "There are 24 waste collection points on floors 0 to 3.",
        "The building has no swimming pool.",
        "Room 5.01 is a research laboratory; add it to your booking.",
    ],
)
def test_ordinary_answers_and_plain_absences_are_left_alone(fine):
    assert not aw.is_internal_absence_prose(fine)
    assert aw.rewrite_semantic_absence(fine, "which rooms are labs?") is None


@pytest.mark.parametrize(
    "question,subject",
    [
        ("Which rooms are swimming pools?", "swimming pool"),
        ("Which spaces have a sauna?", "sauna"),
        ("Is there a squash court?", "squash court"),
        ("Are there any prayer rooms in the building?", "prayer room"),
        ("Does the building have a helipad?", "helipad"),
        ("Where is the rooftop garden?", "rooftop garden"),
        ("How many electric vehicle chargers?", "electric vehicle charger"),
    ],
)
def test_the_subject_is_read_from_the_question(question, subject):
    assert aw.subject_of(question) == subject


def test_a_question_with_no_recognisable_subject_gets_a_generic_but_honest_sentence():
    out = aw.rewrite_semantic_absence(WAVE1_PROSE, "tell me stuff", "B")
    assert out == "I found nothing in B's records that answers that."


def test_both_phrasings_of_the_same_question_get_the_same_sentence():
    """A reader who asks twice must not be told two different things (wave-2 live read)."""
    gate = "'swimming pool' does not exist in this building, so there is nothing to report about it."
    assert aw.absence_sentence("swimming pool", "Abacws Building") == gate
    assert "model" not in gate and "ontology" not in gate


def test_an_instruction_to_find_another_data_source_is_recognised():
    """The live wave-2 text: 'you would need to look for a different data source'."""
    live = (
        "I'm sorry, but the building model does not record which rooms are swimming pools. If you "
        "need that information, you would need to look for a different data source that includes "
        "room type or function."
    )
    assert aw.is_internal_absence_prose(live)
    out = aw.rewrite_semantic_absence(live, "Which rooms are swimming pools?", "Abacws Building")
    assert out.startswith("'swimming pool' does not exist")
    for banned in ("data source", "sorry", "you would need"):
        assert banned not in out
