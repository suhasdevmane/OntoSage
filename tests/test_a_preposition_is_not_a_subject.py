# -*- coding: utf-8 -*-
"""A function word must not decide whether a topic may answer (BUG-1392).

THE DEFECT THESE TESTS WERE WRITTEN FROM, in the words the reader saw:

    Q: "What happens during a power outage?"
    A: "I don't have that specific information on record for **Abacws Building**. For
        building-specific queries please contact your building's facilities / estates
        management team."

while the building declares `bldg:Cap_power_resilience` with the lay term "power outage"
VERBATIM and an answer naming the UPS, the diesel standby generator and its ~30 second
changeover. The log shows the whole chain working and then throwing the answer away:

    [ttl-route] capability via ontology triples: ['Power Resilience'] - skipping LLM intent call
    [capability] topics ['Power Resilience'] match words but are not the subject - not answering

The subject test allows at most ONE leftover content word. `leftover_content_words` drops every
word of two letters or fewer, so "in" never reached it and "during" did:

    "What happens IN a power cut?"        leftover {happens}          -> ANSWERED
    "What happens DURING a power outage?" leftover {during, happens}  -> DECLINED

Nothing about the subject differs. A preposition decided it.

These tests are deliberately written against `leftover_content_words` and `_FRAME_WORDS`
directly rather than against a live turn: the live route also passes through the retrieval
floor and the register pointer, so a live assertion would not say WHICH stage changed.
"""

import pytest

from orchestrator.services.capability_graph_resolver import (
    _FRAME_WORDS,
    leftover_content_words,
)

#: THE UNIT MARKER IS NOT AUTOMATIC, and without it this file is DESELECTED by `pytest -m
#: unit` -- the suite that gates a commit. Three test files written on 2026-10-01 were
#: missing it, so 61 tests ran green when invoked by name and protected nothing in the
#: gate. The tell was the summary line: `deselected` rose by exactly the number of tests
#: added while `passed` did not move.
pytestmark = pytest.mark.unit

#: Exactly as `bldg1_capabilities.ttl` declares them for `bldg:Cap_power_resilience`.
POWER_LAY_TERMS = [
    "power outage",
    "power cut",
    "backup power",
    "generator",
    "ups",
    "electricity failure",
    "power failure",
    "can the building operate",
    "emergency power",
]

#: What `capability_agent._is_subject` permits.
SUBJECT_THRESHOLD = 1


def _is_subject(question: str, lay_terms) -> bool:
    return len(leftover_content_words(question.lower(), list(lay_terms))) <= SUBJECT_THRESHOLD


class TestThePairThatFoundIt:
    def test_during_and_in_reach_the_same_verdict(self):
        """The two wordings differ by one preposition and must not differ in outcome."""
        during = _is_subject("What happens during a power outage?", POWER_LAY_TERMS)
        inside = _is_subject("What happens in a power cut?", POWER_LAY_TERMS)
        assert during == inside, (
            "a preposition changed whether the building may answer from its own declared "
            "topic: during=%r in=%r" % (during, inside)
        )

    def test_the_question_the_reader_asked_is_answerable(self):
        left = leftover_content_words("what happens during a power outage?", POWER_LAY_TERMS)
        assert _is_subject("What happens during a power outage?", POWER_LAY_TERMS), (
            "the building declares 'power outage' verbatim and still would not answer; "
            "leftover=%r" % (sorted(left),)
        )

    def test_the_fire_alarm_question_passes_the_subject_test(self):
        """The subject test is not the whole route, and this test says only what it says.

        MY FIRST VERSION OF THIS TEST ASSERTED AGAINST A LAY-TERM LIST I INVENTED
        (`["fire", "alarm", "evacuate", ...]`). It passed, and it proved nothing about this
        building: a test whose fixture is made up measures the fixture. The list below is
        `bldg1_capabilities.ttl` line 22, verbatim.

        AND THE STAGE IS NOT THE ROUTE. Measured live after this fix landed, the question
        "The fire alarm is sounding. What should I do?" never reaches the capability lane at
        all -- `[ttl-route] metadata via held record class: FireSafetyAsset (30 instances)`
        sends it to the register, which declines the procedure and then writes generic advice
        of its own ("follow the building's standard fire-alarm procedures (e.g., evacuate,
        contact the fire department"). That is BUG-1393, and it is NOT fixed by this change.
        Passing here means the subject test would permit the answer if the question arrived.
        """
        declared = [
            "fire",
            "fire alarm",
            "evacuation",
            "emergency exit",
            "fire escape",
            "smoke detector",
            "sprinkler",
            "fire safety",
            "assembly point",
            "muster point",
            "fire warden",
            "extinguisher",
            "fire drill",
            "fire door",
            "fire exit",
            "fire suppression",
        ]
        left = leftover_content_words("the fire alarm is sounding. what should i do?", declared)
        assert _is_subject(
            "The fire alarm is sounding. What should I do?", declared
        ), "the subject test would refuse the building's own fire-safety topic; leftover=%r" % (
            sorted(left),
        )


class TestTheWordsAreInTheSet:
    @pytest.mark.parametrize(
        "word",
        [
            "during",
            "and",
            "before",
            "after",
            "through",
            "without",
            "within",
            "between",
            "should",
            "happens",
            "whether",
            "because",
        ],
    )
    def test_function_word_is_framing(self, word):
        assert word in _FRAME_WORDS, (
            "%r can never be the SUBJECT of a question, but is counted as content and so can "
            "cost an answer on its own (the threshold is one leftover word)" % word
        )

    @pytest.mark.parametrize("word", ["today", "tomorrow", "tonight", "yesterday"])
    def test_a_time_scoping_word_is_NOT_framing(self, word):
        """Deliberately excluded: these change WHICH answer is right, not what is asked about.

        A static topic answering "what time does the building close to visitors today" with its
        standard hours is a different defect, and widening the set to admit it would hide it.
        """
        assert word not in _FRAME_WORDS, (
            "%r scopes a question to a day; admitting it as framing lets a static topic answer "
            "a time-bound question" % word
        )


class TestCounterfactual:
    """Without these, the tests above could pass on a set that frames away everything."""

    def test_a_content_noun_is_still_content(self):
        """BUG-601: a topic must not answer a question that merely NAMES it."""
        toilets = ["toilet", "toilets", "wc", "restroom"]
        left = leftover_content_words(
            "where can i isolate the water supply for the second-floor toilets?", toilets
        )
        assert not _is_subject(
            "Where can I isolate the water supply for the second-floor toilets?", toilets
        ), "a plumbing question became answerable from a toilet-location topic; leftover=%r" % (
            sorted(left),
        )

    def test_the_hotel_question_leaves_a_content_word(self):
        """'Book me a hotel near the building' must leave 'hotel' behind."""
        bookings = ["book", "booking", "bookings", "reserve", "reservation", "room booking"]
        assert "hotel" in leftover_content_words(
            "book me a hotel near the building", bookings
        ), "'hotel' was absorbed as framing; the room-booking topic could then answer it"

    def test_the_set_did_not_swallow_the_language(self):
        """A guard on the guard: these must never be framing, or the subject test is inert."""
        for word in ("toilet", "lift", "power", "humidity", "hotel", "piano", "generator"):
            assert word not in _FRAME_WORDS, "%r is a thing a building question is ABOUT" % word
