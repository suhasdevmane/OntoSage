# -*- coding: utf-8 -*-
"""What to say when a data question really is too wide to answer directly.

The SQL lane refuses a question that would need every reading of hundreds of sensors, and for years
it said so in the vocabulary of the mechanism: "more than I can read row by row and summarise in one
request without either timing out or quietly answering from a fraction of them", followed by two
bullets and a paragraph of justification. A stakeholder reads that as a wall of jargon, and in the
stakeholder reads it turned up on questions that were not data questions at all.

The refusal is still right for the questions the aggregate lane cannot answer (row-level dumps such
as "show me CO2 for every sensor this week"), so it stays. What changes is the sentence. It names
what was asked and offers the two cheapest questions that DO get an answer, written with the
reader's own quantity and period so they can be asked as they stand:

    for CO2: "Which floor had the highest CO2 this week?" or "What is the CO2 level in Room <n>
    right now?"

Nothing here names a building. The example room is taken from the sensors that were resolved (their
own labels), and when no label carries one the reply says "a room" rather than invent one.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

#: Words the reply must never use: the mechanism, not the reader's question.
JARGON = ("row by row", "summarise", "summarize", "in one request", "timing out", "fetch budget")

_PERIOD = re.compile(
    r"\b(this week|last week|this month|last month|yesterday|today|this morning|"
    r"last \d+ (?:hours?|days?|weeks?)|past \d+ (?:hours?|days?|weeks?)|last 24 hours)\b",
    re.IGNORECASE,
)
_ROOM = re.compile(r"\bRoom\s+\d+(?:\.\d+)?\b", re.IGNORECASE)

#: A quantity that is a level in the air reads better with the word "level".
_LEVEL_WORD = {
    "co2": "CO2 level",
    "pm25": "PM2.5 level",
    "voc": "VOC level",
    "sound": "sound level",
}


def _quantity(question: str, labels: Iterable[str]) -> Optional[str]:
    """The measurand the sensors and the question agree on, as a reader would say it."""
    from orchestrator.services.aggregate_lane import measurand_key

    return measurand_key(list(labels)) or measurand_key([question])


def _period(question: str) -> Optional[str]:
    """The period the reader used, so the suggested question keeps it; None when none was named."""
    m = _PERIOD.search(question or "")
    return m.group(1).lower() if m else None


def _example_room(labels: Iterable[str]) -> Optional[str]:
    """A room that exists, read from the resolved sensors' own labels (never a literal here)."""
    for label in labels:
        m = _ROOM.search(str(label or ""))
        if m:
            return f"Room {m.group(0).split(None, 1)[1]}"
    return None


def _decline(question: str, labels: Iterable[str]) -> str:
    """The honest decline the rest of the system gives: no sensor count, no limit, a way forward.

    Used for every question that reached the breadth guard WITHOUT asking for the readings sensor
    by sensor. Those questions (a wish, a knowledge question, a route, a design question) were
    told "that covers all 233 sound sensors", which reads as a limit of the system and is not an
    answer; the sensor set was whatever retrieval bound, and often not even the quantity asked.
    The quantity is named only when the QUESTION names it; otherwise the way forward is generic.
    """
    from orchestrator.services.aggregate_lane import (
        display_name,
        measurand_key,
        question_asks_about,
    )
    from orchestrator.services.aggregate_support import is_readings_question

    lead = "I couldn't tie that question to a reading I can give you, so I have no figure for it."
    label_list = [str(x) for x in labels]
    key = measurand_key(label_list) or measurand_key([question])
    if key and is_readings_question(question) and question_asks_about(question, key):
        name = display_name(key)
        if key == "occupancy":
            floor_q = "Which floor has the most people right now?"
        else:
            floor_q = f"Which floor had the highest {name} this week?"
        room = _example_room(label_list) or "one room"
        room_q = (
            f"How many people are in {room} right now?"
            if key == "occupancy"
            else f"What is the {_LEVEL_WORD.get(key, name)} in {room} right now?"
        )
        return f'{lead} For {name}, I can answer "{floor_q}" or "{room_q}".'
    return (
        f"{lead} I can answer about a room, a floor or a quantity the building measures, for "
        'example "What is the temperature in a named room right now?" or "Which floor has the '
        'most people right now?".'
    )


def too_broad_reply(question: str, sensor_count: int, labels: Iterable[str] = ()) -> str:
    """The reply for a question that reached the breadth guard.

    A REQUEST FOR THE READINGS SENSOR BY SENSOR ("show me CO2 for every sensor") is the one shape
    where the size of the set is the honest reason, and it keeps its sentence. Everything else gets
    the plain decline.
    """
    from orchestrator.services.aggregate_support import asks_for_per_sensor_detail

    if not asks_for_per_sensor_detail(question):
        return _decline(question, labels)
    from orchestrator.services.aggregate_lane import display_name

    label_list = [str(x) for x in labels]
    key = _quantity(question, label_list)
    if not key:
        return (
            f"That covers all {sensor_count} sensors at once, which is too wide to answer "
            "directly; name a floor or a room, or ask which floor has the highest value of what "
            "you are after."
        )
    name = display_name(key)
    period = _period(question)
    room = _example_room(label_list) or "one room"
    if key == "occupancy":
        floor_q = f"Which floor has the most people {period or 'right now'}?"
        room_q = f"How many people are in {room} right now?"
    else:
        floor_q = f"Which floor had the highest {name} {period or 'this week'}?"
        room_q = f"What is the {_LEVEL_WORD.get(key, name)} in {room} right now?"
    return (
        f"That covers all {sensor_count} {name} sensors at once, which is too wide to answer "
        f'directly; for {name}, try "{floor_q}" or "{room_q}".'
    )
