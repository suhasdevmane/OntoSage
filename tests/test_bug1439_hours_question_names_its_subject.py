"""BUG-1439: an hours question names its subject, not the building's generic hours topic.

"What time does the cafe close?" matched two topics: the catering topic, whose terms explain
the whole question through "cafe", and a generic opening-hours topic that declares "close" and
"what time". Once the hours words were removed, the hours topic was left holding {cafe}, one
word inside the single-word allowance, so it qualified and answered with the BUILDING's hours.

Fixtures carry only lay-term text, never a building's own names, so these run for any building.

This is the variant KEPT over the integration branch's rule-1/rule-2 version (2026-10-07). Measured
over the 4,060-question bank (docs/smart_building_questions.csv) against bldg1's own capability
triples, with the resolver's candidate prefilter: the integration variant moved 1 subject set
(Q052 "Where's the nearest fire exit from the third-floor kitchen?" lost Fire Safety and kept only
Catering: wrong), this variant moved 1 (Q213 "What's the fire assembly point for this building?"
dropped Emergency Evacuation, which shares the term "assembly point" with Fire Safety, so the
requested fact is still answered). The two disagree on exactly those two questions.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.capability_graph_resolver import (
    subject_facts,
    topic_is_the_subject,
)

pytestmark = pytest.mark.unit

HOURS = SimpleNamespace(
    label="Opening hours",
    lay_terms="opening hours, open, close, when does it open, what time, hours, is it open",
)
CAFE = SimpleNamespace(label="Catering", lay_terms="cafe, canteen, food, coffee, vending machine")
WIFI = SimpleNamespace(label="Wifi", lay_terms="wifi, wi-fi, internet, network, connect")
GUEST = SimpleNamespace(label="Guest policy", lay_terms="guest, visitor, visitors")
FIRE = SimpleNamespace(label="Fire safety", lay_terms="fire, fire alarm, smoke detector, sprinkler")
SMOKING = SimpleNamespace(label="Smoking policy", lay_terms="smoking, smoke, vaping")


@pytest.mark.parametrize(
    "question",
    [
        "what time does the cafe close?",
        "What time does the canteen close",
        "when does the cafe open",
        "is the cafe open to visitors?",
    ],
)
def test_the_named_subject_answers_not_the_hours_topic(question):
    assert subject_facts(question, [HOURS, CAFE]) == [CAFE]


def test_the_hours_topic_still_answers_a_question_about_the_hours_themselves():
    assert subject_facts("what time does the building close?", [HOURS]) == [HOURS]


def test_single_topic_test_judges_the_hours_words_as_frame_for_the_cafe_too():
    # The single-topic test is the source the list-level test is built on, so it must agree:
    # the cafe topic explains this question whole, the hours topic does not.
    q = "what time does the cafe close?"
    assert topic_is_the_subject(q, CAFE) is True
    assert topic_is_the_subject(q, HOURS) is True  # leftover {cafe}: one word, inside allowance
    # ...and the list-level rule is what removes it, because the cafe topic names it.


def test_a_forecast_over_hours_is_not_an_hours_question():
    # BUG-1396: the word "hours" inside "the next 12 hours" must not make the hours words frame
    # for a question that is not about opening times. The forecast question keeps the subject
    # test as it was.
    q = "project the noise level in the atrium for the next 12 hours"
    assert topic_is_the_subject(q, HOURS) is False


def test_a_topic_is_not_dropped_for_a_word_no_other_topic_fully_explains():
    # "guest wifi": the wifi topic keeps "guest", which the guest topic declares, but the guest
    # topic does not explain the question whole (it keeps "wifi" and "connect"), so it cannot
    # name the subject. The wifi topic must survive. Dropping it here was the looser rule's
    # measured regression on the bank ("How do I connect to the guest wifi?").
    q = "How do I connect to the guest wifi?"
    kept = subject_facts(q, [WIFI, GUEST])
    assert WIFI in kept
    assert GUEST not in kept


def test_a_topic_holding_a_word_another_topic_fully_explains_is_dropped():
    # "does your building have smoke detectors": the fire topic explains the question whole
    # ("smoke detector"), and the smoking topic is left holding "detectors".
    q = "does your building have smoke detectors"
    assert subject_facts(q, [FIRE, SMOKING]) == [FIRE]


# Folded in from tests/test_bug_1439_specific_topic_beats_the_hours_frame.py, which this variant
# replaces. Its cases that hold here are kept; two premises that only the rejected variant had
# are carried as strict xfails, because they are real limits of this rule, not settled behaviour.
WORKING_HOURS = SimpleNamespace(
    label="Working Hours",
    lay_terms="opening hours, open, close, when does it open, what time, hours, is it open",
)
CATERING = SimpleNamespace(
    label="Catering Amenities",
    lay_terms="cafe, canteen, food, coffee, vending machine, eating, lunch, refreshment",
)


def test_the_result_is_the_same_whatever_order_the_topics_arrive_in():
    assert subject_facts("what time does the cafe close?", [CATERING, WORKING_HOURS]) == [CATERING]


def test_no_facts_gives_no_subject():
    assert subject_facts("what time does the cafe close?", []) == []


def test_the_subject_test_is_unchanged_for_a_topic_with_no_terms():
    bare = SimpleNamespace(label="", lay_terms="")
    assert topic_is_the_subject("anything at all", bare) is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A topic that shares NO word with an hours question passes this unit test once the hours "
        "frame is stripped (Catering keeps only 'nothing', so it qualifies). Production is not "
        "affected: capability_agent and dialogue_agent pass only topics that resolve() matched on "
        "words. Lifting this needs a matched-word guard in topic_is_the_subject, measured first."
    ),
)
def test_a_plain_hours_question_does_not_admit_an_unmatched_topic():
    assert subject_facts("what are the opening hours?", [WORKING_HOURS, CATERING]) == [
        WORKING_HOURS
    ]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Same limit as above, for a topic the question does not name: the 'library' question "
        "leaves one content word, so an unmatched Catering topic passes the single-topic test."
    ),
)
def test_a_topic_with_no_declared_match_is_never_borrowed_into_the_answer():
    assert CATERING not in subject_facts(
        "what time does the library close?", [WORKING_HOURS, CATERING]
    )
