"""BUG-601: a static topic answered questions that merely shared one of its words (run #3).

"Book me a hotel", "is the building pushchair-friendly from the car park?", "where can I
isolate the water supply for the second-floor toilets?" and "what systems are specific for the
meeting room?" were each answered in about a second from the bookings, travel, toilet and study
topics. The topic must be what the question is ABOUT before it may answer.
"""

import inspect

import pytest

from orchestrator.services.capability_graph_resolver import leftover_content_words as left

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q,phrases",
    [
        ("Where are the toilets?", ["toilet", "toilets"]),
        ("Is tap water free somewhere, or do I have to buy bottles?", ["tap water", "bottles"]),
        ("Where can I get coffee?", ["coffee"]),
        ("Are there showers for cyclists?", ["showers", "cyclists"]),
        ("Is there a lift in the building?", ["lift"]),
    ],
)
def test_the_amenity_is_the_subject(q, phrases):
    assert len(left(q.lower(), phrases)) <= 1


@pytest.mark.parametrize(
    "q,phrases",
    [
        ("Where can I isolate the water supply for the second-floor toilets?", ["toilets"]),
        ("Book me a hotel near the building for tomorrow.", ["book"]),
        ("Is the building pushchair-friendly from the car park?", ["car park"]),
        ("What systems are specific for the meeting room?", ["meeting room"]),
    ],
)
def test_a_question_that_only_names_the_amenity_is_not_about_it(q, phrases):
    assert len(left(q.lower(), phrases)) > 1


def test_the_capability_lane_answers_only_from_subject_topics():
    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent.CapabilityAgent._answer_unchecked)
    assert "leftover_content_words" in src
    assert "_subject = [f for f in _facts if _is_subject(f)]" in src
    # the filter must apply to what ANSWERS, before the answer is assembled
    assert src.index("_facts = _subject") < src.index('Here is what I found for')


def test_the_pre_classification_short_circuit_is_unchanged():
    """The fix is in the ANSWER path; the earlier attempt on the short-circuit was reverted."""
    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    assert "require_subject" not in src
