# -*- coding: utf-8 -*-
"""A question about WHEN something happens in a space asks for a pattern over time (BUG-828).

The failure this prevents (tail B row B12, both runs, 2026-09-18): "When is the atrium busiest?"
was answered *"Best match: Room 3.48 - Academic Office ... occupancy: 13.867"* by the deliberation
lane, which ranks rooms by their CURRENT occupancy. The question asked for a TIME (an hour, a day
of the week); the answer named a ROOM, and not even the one asked about. The word "busiest" sits in
the deliberation vocabulary because "which room is the busiest?" IS a ranking; what makes this a
different question is the dimension being asked for.

The test is therefore the asked-for dimension, not the peak word:

* "when is", "what time", "which day", "peak hours" -> a time is wanted -> a series over history;
* "which room is the busiest", "the quietest room on floor 2" -> a place is wanted -> a ranking.

Measured against the 4,271 questions this project holds, the first draft moved 33 to the trend lane
and eight were wrong -- "when did we last EMPTY the attenuation tank", "when is the lecture theatre
free for a FULL-day rehearsal", "MODEL PEAK DEMAND if we add 20 chargers", "is the entrance busy
WHEN I arrive". Each is a negative case in the tests: "when" counts only as a question word
(followed by an auxiliary verb), "empty" and "full" are not peak qualities on their own, and "peak
demand" is a quantity, not a moment.

Pure and building-agnostic: English only, no room or sensor names.
"""

from __future__ import annotations

import re

#: The asker wants a MOMENT: an hour, a day, a period. "when" is a QUESTION word only when an
#: auxiliary follows it ("when is", "when does"); "when I arrive" and "when demand peaks" are
#: conjunctions, and a sentence that only contains one is asking about something else.
_ASKS_A_TIME = (
    r"\bwhen\s+(?:is|are|was|were|does|do|did|will)\b"
    r"|\bwhen's\b"
    r"|\bwhat\s+(?:time|times|hour|hours|day|days|part\s+of\s+the\s+day)\b"
    r"|\bat\s+what\s+(?:time|hour)\b"
    r"|\bwhich\s+(?:day|days|hour|hours|time|times)\b(?!-)"
    # "the peak hours" asks for a moment; "at peak times" only says WHEN some other thing is compared
    r"|(?<!\bat\s)(?<!\bduring\s)(?<!\bin\s)\b(?:busiest|quietest|emptiest|calmest|peak)\s+"
    r"(?:time|times|hour|hours|day|days|period|periods)\b"
)

#: The quality whose moment is being asked about. "empty" and "full" are absent on purpose: they
#: are verbs and modifiers as often as qualities ("empty the tank", "a full-day rehearsal"); the
#: superlatives ("emptiest") are unambiguous and stay.
_PEAK_WORD = (
    r"busiest|quietest|emptiest|calmest|noisiest|loudest|"
    r"peak|peaks|peaked|most\s+(?:used|crowded|popular)|least\s+(?:used|crowded|busy)|"
    # an ADJECTIVE counts only as a predicate ("when does the reception get busy"), never as a
    # modifier ("a quiet space", "a busy corridor")
    r"(?:is|are|was|were|gets?|becomes?|be)\s+(?:\w+\s+){0,2}?(?:busy|quiet|crowded|packed)"
)

#: The asker wants a PLACE: this is the ranking the deliberation lane exists for.
_ASKS_A_PLACE = (
    r"\bwhere\b"
    r"|\bwhich\s+(?:\w+\s+){0,2}(?:rooms?|spaces?|zones?|areas?|floors?|desks?|seats?|spots?)\b"
    r"|\b(?:busiest|quietest|emptiest|calmest|noisiest|loudest)\s+(?:\w+\s+){0,2}"
    r"(?:rooms?|spaces?|zones?|areas?|floors?|desks?|seats?|spots?)\b"
)

#: A request to MODEL, FORECAST or change something is not a lookup of when a space is busy.
_SCENARIO = (
    r"\b(?:model|simulate|what\s+if|if\s+we\s+(?:add|install|move|change|remove)|compare|compared|"
    r"comparison|versus|vs\.?)\b"
)

_TIME_RE = re.compile(_ASKS_A_TIME, re.IGNORECASE)
_PEAK_RE = re.compile(rf"\b(?:{_PEAK_WORD})\b", re.IGNORECASE)
_PLACE_RE = re.compile(_ASKS_A_PLACE, re.IGNORECASE)
_SCENARIO_RE = re.compile(_SCENARIO, re.IGNORECASE)


def asks_time_pattern(question: str) -> bool:
    """True when the question asks WHEN a space is busy, quiet, crowded or at its peak.

    Requires both halves -- a moment is asked for AND a peak quality is named -- and yields to a
    question that also asks for a place, so "when is the quietest room free?" and "which room is
    busiest at 3pm?" keep the lanes that already handle them, and to a scenario ("model peak demand
    if we add 20 chargers").
    """
    q = question or ""
    if not (_TIME_RE.search(q) and _PEAK_RE.search(q)):
        return False
    return not (_PLACE_RE.search(q) or _SCENARIO_RE.search(q))
