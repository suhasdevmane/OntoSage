# -*- coding: utf-8 -*-
"""A whole-building "what is free" question is the availability LIST, not a lookup of one room.

The failure this prevents (dev tail C, wave 1, 2026-09-19). *"can i get a real time map of available
spaces across the building?"* was classified by the events lane as a single-room availability check,
so it answered "I couldn't match that room name -- try the room id as it appears on the floor plan",
followed by a stray "No chart was drawn" note. Nobody named a room. The building does hold what the
question wants -- which rooms have no booking right now -- and says so in one sentence when asked as
"which rooms are free?".

Two things were wrong and both are decided here, once:

* the shape "available/free/vacant + spaces/rooms", with a whole-building scope ("across the
  building", "anywhere", "in the building", "any") and no named room, is an OVERVIEW;
* "real time", "live" and "at the moment" mean NOW, so the window is the present instant and not the
  whole day, and a request for a "map" is answered honestly: the building has no occupancy map, only
  the bookings, so the answer says which rooms have no booking right now and that walk-in use is not
  tracked.

Pure and building-agnostic: English only, no room names.
"""

from __future__ import annotations

import re

#: A room the question NAMES. Present means the question is about that room, not the building.
_NAMED_ROOM_RE = re.compile(
    r"\b(?:room|rm|lab|office|studio)\s*[A-Za-z]?\d[\w.]*\b|\b\d{1,2}\.\d{1,3}\b|\bRoom\d", re.IGNORECASE
)

_FREE_WORDS = r"(?:available|free|vacant|unoccupied|unbooked|empty)"
_PLACE_WORDS = r"(?:spaces?|rooms?|areas?|desks?|seats?|study\s+(?:spaces?|areas?)|meeting\s+rooms?)"

#: The overview shapes. Each alternative is a REQUEST for the list of what is free, so a question
#: that merely contains both words ("is the free-standing room available?") does not match.
OVERVIEW_RE = re.compile(
    # "a map / overview / list / view / dashboard of available spaces"
    rf"\b(?:map|overview|list|view|dashboard|summary|picture|snapshot)\b[^?.!]{{0,30}}\b{_FREE_WORDS}\b"
    rf"[^?.!]{{0,20}}\b{_PLACE_WORDS}\b"
    # "which / what / any / are there / show me  available spaces"
    rf"|\b(?:which|what|any|show(?:\s+me)?|are\s+there|is\s+there|find|list)\b[^?.!]{{0,25}}"
    rf"\b{_FREE_WORDS}\b[^?.!]{{0,10}}\b{_PLACE_WORDS}\b"
    # "which spaces are free / what rooms are available"
    rf"|\b(?:which|what|any|list|show(?:\s+me)?)\s+(?:\w+\s+){{0,2}}{_PLACE_WORDS}\b[^?.!]{{0,25}}"
    rf"\b{_FREE_WORDS}\b"
    # "spaces that are free / rooms which are available"
    rf"|\b{_PLACE_WORDS}\b[^?.!]{{0,20}}\b(?:that|which)\s+(?:are|is)\s+{_FREE_WORDS}\b"
    # "what's free / what is available right now / anywhere free"
    rf"|\bwhat(?:'s|\s+is)\s+{_FREE_WORDS}\b"
    rf"|\banywhere\s+{_FREE_WORDS}\b|\b{_FREE_WORDS}\s+anywhere\b",
    re.IGNORECASE,
)

#: A whole-building scope. Without it "are there available rooms on floor 3?" is a floor question.
_BUILDING_SCOPE_RE = re.compile(
    r"\b(?:across|throughout|around|in|within|of)\s+(?:the\s+)?(?:whole\s+|entire\s+)?(?:building|site|"
    r"campus|estate)\b|\banywhere\b|\bany\s+(?:rooms?|spaces?)\b|\beverywhere\b",
    re.IGNORECASE,
)

#: "real time", "live" and "at the moment": the present instant, not the day.
NOW_RE = re.compile(
    r"\breal[-\s]?time\b|\blive\b|\bat\s+the\s+moment\b|\bright\s+now\b|\bcurrently\b|\bnow\b",
    re.IGNORECASE,
)

#: A request for a picture. The building has bookings, not an occupancy map, and says so.
MAP_RE = re.compile(r"\b(?:map|floor\s*plan|dashboard|visuali[sz]ation|heat\s*map)\b", re.IGNORECASE)


def names_a_room(question: str) -> bool:
    """True when the question names a particular room."""
    return bool(_NAMED_ROOM_RE.search(question or ""))


def asks_free_overview(question: str) -> bool:
    """True for a request to see which spaces are free across the building, naming no room."""
    q = question or ""
    if names_a_room(q) or not OVERVIEW_RE.search(q):
        return False
    return True


def asks_for_a_map(question: str) -> bool:
    """True when the asker wants a map or picture rather than a list."""
    return bool(MAP_RE.search(question or ""))


def asks_now(question: str) -> bool:
    """True when the question is about the present instant ("real time", "live", "right now")."""
    return bool(NOW_RE.search(question or ""))


def whole_building(question: str) -> bool:
    """True when the scope is the whole building (or there is no narrower scope at all)."""
    return bool(_BUILDING_SCOPE_RE.search(question or ""))


#: The sentence that answers the "map" half honestly, ahead of the list.
NO_MAP_SENTENCE = (
    "**There is no live occupancy map.** What the building records is bookings, so this lists the "
    "rooms with no booking right now."
)
