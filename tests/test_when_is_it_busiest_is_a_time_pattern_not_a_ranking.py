# -*- coding: utf-8 -*-
"""BUG-828 (tail B row B12): "When is the atrium busiest?" asks for a TIME.

Both runs answered it from the deliberation lane -- "Best match: Room 3.48 - Academic Office ...
occupancy: 13.867" (run 1) and "Room 2.57 - Research Laboratory" (run 2) -- a ranking of rooms by
CURRENT occupancy that named a room, not the atrium and not a moment. "Busiest" is in the
deliberation vocabulary because "which room is the busiest?" is a ranking. The difference is the
dimension being asked for, and that is what these tests pin.
"""

import pytest

from orchestrator.services.temporal_pattern import asks_time_pattern

pytestmark = pytest.mark.unit

ASKS_FOR_A_TIME = [
    "When is the atrium busiest?",  # B12, the failing question
    "When is the building busiest?",
    "What time is the library busiest?",
    "What are the peak hours in the atrium?",
    "Which day is the atrium quietest?",
    "When does the reception get busy?",
    "At what time is the canteen most crowded?",
    "When was the atrium busiest last week?",
    "When are the labs quiet?",
]

ASKS_FOR_A_PLACE_OR_SOMETHING_ELSE = [
    "Which room is the busiest right now?",  # a ranking: deliberation's own
    "Which rooms on floor 2 are the quietest?",
    "Show me the zone with minimum occupancy.",
    "What is the quietest room on floor 3?",
    "Where can I sit that is quiet?",
    "When is the quietest room free?",  # wants a room, and a booking answer
    "Which room is busiest at 3pm?",
    "When is Room 5.01 booked?",  # no peak quality named
    "When was the fire alarm last tested?",
    "Is the atrium busy right now?",  # a moment already fixed: "now"
    "How busy is the atrium?",
    # The first draft moved 33 of the project's 4,271 known questions to the trend lane and eight
    # were wrong. Each is verbatim from the stakeholder catalogue:
    "When did we last empty the attenuation tank, and is it silting?",  # "empty" is a verb here
    "When is the lecture theatre free for a full-day rehearsal this month?",  # "full-day"
    "Model peak demand if we add 20 more EV chargers with smart charging.",  # a scenario
    "Is the authorised entrance or main public route likely to be busy when I arrive?",  # "when I"
    "Can each proposed decant space support the required activity, peak demand, equipment, "
    "storage, routes, environment and user support for the full tempo?",  # "peak demand" is a quantity
    "When should I start today's service-desk handover so it is complete before the final "
    "likely demand peak?",  # advice on WHEN TO ACT, not a pattern
    "When demand peaks, will lift waiting create an avoidable participation delay?",  # "when demand"
    # found by the second measurement, after the first round of fixes:
    "How does the gym's air quality compare with the studios at peak times?",  # a comparison
    "Is there an authorised quiet or lower-stimulation space I can use, and when is it officially "
    "available?",  # "quiet" modifies a space
    "The queue peaked after classes yesterday. Which time-aligned factors were associated with "
    "the peak, and is a similar aggregate pattern likely today?",  # "which time-aligned"
    "When is the least disruptive window for cleaning a busy corridor, staircase or lift lobby?",
]


@pytest.mark.parametrize("question", ASKS_FOR_A_TIME)
def test_a_when_question_about_a_peak_is_a_time_pattern(question):
    assert asks_time_pattern(question), question


@pytest.mark.parametrize("question", ASKS_FOR_A_PLACE_OR_SOMETHING_ELSE)
def test_a_ranking_or_a_plain_lookup_is_not_a_time_pattern(question):
    assert not asks_time_pattern(question), question


def test_empty_input_is_not_a_time_pattern():
    assert not asks_time_pattern("")
    assert not asks_time_pattern(None)
