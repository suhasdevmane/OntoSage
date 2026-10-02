# -*- coding: utf-8 -*-
"""'How does the building do X?' is answered from what it wrote down, not from a table of readings.

MEASURED on tail P, 2026-10-02 (occupant01, /v1): 8 of 14 WEIRD answers were this shape --
"how are water leaks detected in hard-to-see areas" answered with nine flow readings and an
invented four-step detection procedure; "what systems are in place to keep the server room
cool" with the outside-air temperature; "how are common areas managed to maintain comfort"
with a list of occupancy sensors. Right subject, wrong kind of answer. The HVAC operating
regime, the Lighting topic and the continuity register hold the real answers one lane over.

Two changes, both measured over the 4,060 bank before landing:
  * `ungrounded_question.mechanism_question` (12 bank matches) hands the question to the
    capability lane -- documents, topics, regimes -- instead of a fetch;
  * `topic_is_the_subject` discounts the mechanism FRAME words ("automatically", "adjusting",
    "properly", "current conditions") before counting leftovers, so "are lights automatically
    adjusting properly?" reaches the Lighting topic, while "how does the building control
    pollen exposure during the spring" still leaves three real words and still fails.

And a third, for BUG-1397: a question about the ASSISTANT'S previous answer ("what is the
evidence behind your answer about the coolest room?") is a session-recall question -- the one
lane that can say whether there was an answer -- not a diagnosis. 4 bank moves, all of them
about the assistant's answers; "can I see the last result?" was matched by a first draft and
is a data question, so result/figure/number are not in the shape.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services import capability_graph_resolver as cgr
from orchestrator.services import session_recall as sr
from orchestrator.services import ungrounded_question as uq

pytestmark = pytest.mark.unit


class TestTheMechanismShape:
    @pytest.mark.parametrize(
        "q",
        [
            "how do we prevent over heating",
            "How does it ensure that the most important systems keep running?",
            "how are water leak detected in hard to see areas?",
            "How are common areas manages to maintain comfort during busy times?",
            "On a very hot summer day, what systems are in place to ensure that the server room does not overheat?",
            "are lights automatically adjusting properly to current conditions?",
            "how often are lights adjusted automatically in this building?",
            "Can you keep temperature stable?",
            "What does AI do if the air quality in the building gets too bad?",
            "Where does the background noise from the Building come from?",
        ],
    )
    def test_is_a_mechanism_question(self, q):
        assert uq.mechanism_question(q), q
        assert uq.handoff(q) == "capability"

    @pytest.mark.parametrize(
        "q",
        [
            "What is the temperature in room 2.01 right now?",
            "How hot is it on floor 3?",
            "How much energy did the building use yesterday?",
            "Is any area overheating right now?",
            "how does the temperature compare with last week?",
            "How is occupancy trending this month?",
            "Which rooms are occupied?",
        ],
    )
    def test_a_value_question_is_not(self, q):
        assert not uq.mechanism_question(q), q


class TestTheSubjectTestDiscountsTheFrame:
    LIGHTING = SimpleNamespace(
        label="Lighting",
        lay_terms="lighting, light, lux, brightness, dim, bright, lights, led, natural light, daylight",
    )
    CONTROLS = SimpleNamespace(
        label="Smart Controls", lay_terms="smart controls, control, bms, automation"
    )

    def test_lights_adjusting_automatically_reaches_the_lighting_topic(self):
        assert cgr.topic_is_the_subject(
            "are lights automatically adjusting properly to current conditions?", self.LIGHTING
        )
        assert cgr.topic_is_the_subject(
            "how often are lights adjusted automatically in this building?", self.LIGHTING
        )

    def test_a_real_second_subject_still_fails(self):
        assert not cgr.topic_is_the_subject(
            "How does the building control pollen exposure during the spring?", self.CONTROLS
        )

    def test_the_discount_applies_only_to_the_mechanism_shape(self):
        """BUG-601's cases are untouched: the frame words are not removed from a plain ask."""
        assert not cgr.topic_is_the_subject(
            "Where can I isolate the current conditions of the lights properly?", self.LIGHTING
        )

    def test_the_frame_holds_no_subject_noun(self):
        for noun in ("water", "temperature", "noise", "lights", "parking", "room", "pollen"):
            assert noun not in cgr._MECHANISM_FRAME


class TestAQuestionAboutMyAnswerIsRecall:
    @pytest.mark.parametrize(
        "q",
        [
            "What is the evidence behind your answer about the coolest room?",
            "How did you get that number?",
            "What was your previous answer based on?",
            "Which parts of your answer are confirmed facts?",
        ],
    )
    def test_recall(self, q):
        assert sr.is_recall_question(q), q

    @pytest.mark.parametrize(
        "q",
        [
            "How often is the drinking water tested, and can I see the last result?",
            "What's the timestamp of the newest reading behind that number?",
            "What is the answer to 2+2?",
            "Is the lift working?",
        ],
    )
    def test_not_recall(self, q):
        assert not sr.is_recall_question(q), q

    def test_with_nothing_asked_the_lane_says_so(self):
        text = sr.answer("What is the evidence behind your answer about the coolest room?", [])
        assert "Nothing has been asked in this conversation yet" in text
