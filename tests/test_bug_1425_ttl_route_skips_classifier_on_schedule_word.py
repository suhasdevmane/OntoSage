# -*- coding: utf-8 -*-
"""BUG-1425: the ttl-route short-circuit skipped the LLM classifier on a schedule word.

MEASURED, live: "Is Level 1 computer lab 1.06 (WS-02) free this afternoon?" matched two
knowledge topics by vocabulary alone -- 'Wifi It' (on the word "computer") and 'Schools
And Key Facilities' (on the phrase "computer lab") -- and logged:

    [ttl-route] capability via ontology triples: [Schools And Key Facilities, Wifi It]
    -- skipping LLM intent call

G3 (2026-10-04) added `subject_facts` at this exact decision point for exactly this
example and did not fully close it: 'Wifi It' is correctly rejected (its leftover is
{lab, afternoon}, two words), but 'Schools And Key Facilities' passes
`topic_is_the_subject`'s one-leftover-word tolerance because its only leftover word is
"afternoon" -- not one of the tiny `_NOT_THIS_BUILDING` disqualifying words BUG-1395
added that same tolerance to guard against. So the short-circuit still fired, and the
capability lane then declined a room-availability question.

Fixtures carry only lay-term text, never a building's own names, so these run for any
building.
"""

from types import SimpleNamespace

import pytest

from orchestrator.agents.dialogue_agent import _not_merely_scheduled
from orchestrator.services.capability_graph_resolver import subject_facts

pytestmark = pytest.mark.unit

SCHOOLS = SimpleNamespace(
    label="Schools And Key Facilities",
    lay_terms="computer lab, cybersecurity lab, research lab, what facilities, what rooms",
)
WIFI_IT = SimpleNamespace(
    label="Wifi It",
    lay_terms="wifi, wireless, internet, network, it, broadband, computer",
)
HVAC = SimpleNamespace(label="Hvac Zoning", lay_terms="heating, hvac zone, zoning, thermostat")
FIRE = SimpleNamespace(
    label="Fire Safety", lay_terms="fire, fire alarm, smoke detector, sprinkler, fire exit"
)
HOURS = SimpleNamespace(
    label="Working Hours", lay_terms="opening hours, open, close, what time, hours"
)

MOTIVATING_Q = "Is Level 1 computer lab 1.06 (WS-02) free this afternoon?"


# ── the short-circuit's own subject test is insufficient on its own ──────────────────


def test_g3s_own_subject_test_still_lets_the_motivating_example_through():
    """COUNTERFACTUAL, pinned: this is the gap G3 left, not a strawman.

    If this ever returns [] unaided, BUG-1425's diagnosis no longer holds and the new
    filter below would have nothing left to do.
    """
    assert subject_facts(MOTIVATING_Q, [SCHOOLS, WIFI_IT]) == [SCHOOLS]


def test_wifi_it_is_already_correctly_rejected_by_the_subject_test_alone():
    assert WIFI_IT not in subject_facts(MOTIVATING_Q, [SCHOOLS, WIFI_IT])


# ── the new filter closes it ──────────────────────────────────────────────────────────


def test_the_motivating_example_no_longer_skips_the_classifier():
    before = subject_facts(MOTIVATING_Q, [SCHOOLS, WIFI_IT])
    after = _not_merely_scheduled(MOTIVATING_Q, before)
    assert after == []


@pytest.mark.parametrize(
    "question,still_matched",
    [
        # The bank's own case (measured in docs/smart_building_questions.csv): a reading
        # question, not a static fact about zoning.
        ("Is the heating on today?", "Hvac Zoning"),
        # The motivating shape restated with a different room code.
        ("Is room 2.14 free this afternoon?", "Schools And Key Facilities"),
    ],
)
def test_a_schedule_word_alone_never_qualifies_a_topic(question, still_matched):
    """Each of these matches a real topic by vocabulary, leaving only a time word."""
    matched = [SCHOOLS, WIFI_IT, HVAC]
    before = subject_facts(question, matched)
    assert before, f"fixture drifted: {question!r} no longer matches anything to drop"
    assert still_matched in [f.label for f in before]
    after = _not_merely_scheduled(question, before)
    assert after == [], f"{question!r} should drop to no subject, got {[f.label for f in after]}"


# ── genuine topic questions must keep firing (no regression) ─────────────────────────


def test_a_fully_explained_topic_is_never_dropped():
    """'what time does the building close?' leaves the hours topic FULLY explained."""
    before = subject_facts("what time does the building close?", [HOURS])
    after = _not_merely_scheduled("what time does the building close?", before)
    assert after == before == [HOURS]


def test_a_non_schedule_single_word_leftover_is_unaffected():
    """BUG-1395's own control: 'hotel' is not a schedule word and must still disqualify
    on its own terms, unaffected by this filter."""
    question = "Book me a hotel near the building"
    before = subject_facts(question, [SCHOOLS])
    after = _not_merely_scheduled(question, before)
    assert after == before  # this filter changes nothing here either way


def test_a_route_question_with_no_schedule_word_is_untouched():
    question = "Where's the nearest fire exit from the third-floor kitchen?"
    before = subject_facts(question, [FIRE])
    after = _not_merely_scheduled(question, before)
    assert after == before == [FIRE]


def test_an_empty_subject_list_stays_empty():
    assert _not_merely_scheduled("anything", []) == []


def test_nothing_here_names_a_building():
    import inspect

    import orchestrator.agents.dialogue_agent as mod

    src = inspect.getsource(mod._not_merely_scheduled)
    for literal in ("bldg1", "bldg2", "abacws"):
        assert literal not in src.lower()
