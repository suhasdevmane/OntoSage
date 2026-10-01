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
    """The subject filter still gates what ANSWERS, wherever the test itself now lives.

    THIS TEST PINNED THE SPELLING AND BROKE ON A MOVE, not on a behaviour change (BUG-1396,
    lesson #151 again). It required the literal line

        _subject = [f for f in _facts if _is_subject(f)]

    which was a closure inside this method. The judgement is now
    `capability_graph_resolver.subject_facts`, because the ROUTING CONTRACT needs the same one
    a stage earlier -- it had been standing down in favour of this lane for topics this lane
    then discarded. Pinning the call site is what this test is for; pinning the closure's
    spelling only guaranteed it would fail when the duplication was removed.
    """
    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent.CapabilityAgent._answer_unchecked)
    assert "subject_facts" in src, "the lane no longer filters its topics to the question's subject"
    assert "_subject = subject_facts(" in src
    # the filter must apply to what ANSWERS, before the answer is assembled
    assert src.index("_facts = _subject") < src.index("Here is what I found for")


def test_the_subject_test_has_exactly_one_definition():
    """Two matchers for one judgement is BUG-947's shape, and it is why this moved.

    The decline pointer and the register selector disagreed for months because each had its own
    matcher. When the routing contract needed the subject test, copying it would have recreated
    that. So the closure was deleted rather than duplicated, and this fails if it comes back.
    """
    from orchestrator.agents import capability_agent
    from orchestrator.services import capability_graph_resolver

    assert callable(capability_graph_resolver.subject_facts)
    assert callable(capability_graph_resolver.topic_is_the_subject)
    lane_src = inspect.getsource(capability_agent)
    assert "def _is_subject(" not in lane_src, (
        "the subject test has been re-inlined in the capability lane; the routing contract "
        "reads the shared one, so a second copy can drift away from it"
    )


def test_the_routing_contract_reads_the_subject_qualified_count():
    """The stand-down must key on what the question is ABOUT, not on what its words touched.

    Live, gate case #4: 'Working Hours' matched the word "hours" inside "the next 12 hours",
    one amenity triple was counted, the contract stood down, and the capability lane then said
    those topics "match words but are not the subject" and declined a forecast question.
    """
    from orchestrator.services import routing_contract

    src = inspect.getsource(routing_contract._r_capability_measurand_is_data)
    assert "capability_amenity_subject" in src, (
        "the amenity stand-down is keyed on the raw match count again; it will defer to a lane "
        "that discards the topic"
    )


def test_the_pre_classification_short_circuit_is_unchanged():
    """The fix is in the ANSWER path; the earlier attempt on the short-circuit was reverted."""
    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    assert "require_subject" not in src


def test_a_hotel_is_not_this_building(capsys=None):
    """BUG-1395: BUG-601's own first example had quietly stopped holding.

    'Book me a hotel near the building' leaves exactly {hotel} -- WITHIN the one-leftover
    threshold -- so the room-booking topic qualified and answered a request to book a hotel.
    It was found only because BUG-1392's measurement printed the four BUG-601 cases with their
    BASELINE verdict beside the candidate one, so a pre-existing failure could not be mistaken
    for a new one.

    The test is on the WORD, not the count: lowering the threshold to 0 would also refuse
    'What happens during a power outage?', whose single leftover is {happens}.
    """
    from orchestrator.services.capability_graph_resolver import topic_is_the_subject

    class _Fact:
        def __init__(self, label, lay_terms):
            self.label = label
            self.lay_terms = lay_terms

    bookings = _Fact(
        "Bookings Reservations", "book, booking, bookings, reserve, reservation, room booking"
    )
    assert not topic_is_the_subject("Book me a hotel near the building", bookings)
    assert not topic_is_the_subject("Book me a hotel near the building for tomorrow.", bookings)
    # the topic's REAL question still qualifies
    assert topic_is_the_subject("How do I book a room?", bookings)

    power = _Fact("Power Resilience", "power outage, power cut, backup power, generator, ups")
    assert topic_is_the_subject(
        "What happens during a power outage?", power
    ), "a single leftover word must not disqualify on its own; only an off-site NOUN does"


def test_the_offsite_set_excludes_everything_a_building_might_hold():
    """A guard on the guard. Each of these is a real amenity of a real building in this repo.

    Measured over the 2,960 catalogue and the 4,060 bank: the set as written moves 0 questions.
    Adding any word below would start refusing questions the building can answer.
    """
    from orchestrator.services.capability_graph_resolver import _NOT_THIS_BUILDING

    for word in (
        "cafe",
        "canteen",
        "parking",
        "toilet",
        "lift",
        "bus",
        "train",
        "bike",
        "shower",
        "kitchen",
        "reception",
        "library",
    ):
        assert word not in _NOT_THIS_BUILDING, (
            "%r is something a building can hold; refusing it would cost real answers" % word
        )
