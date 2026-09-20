# -*- coding: utf-8 -*-
"""The kind of room a question names ("meeting rooms", "labs") as Brick room classes (BUG-828).

The failure this prevents (tail B row B11, 2026-09-18): "Which meeting rooms are booked this
afternoon?" was answered from a register of six bookings in August and September. Routed to the
live booking store it would have listed EVERY room with a booking -- offices and labs beside the
meeting rooms -- because nothing narrowed the list to the kind of room the asker named.

The building already knows each room's kinds: every space is typed with Brick classes
(``brick:Conference_Room``, ``brick:Laboratory``, ...). This module only translates the words a
person uses into those class names, so the narrowing is a lookup in the building's own data.

Building-agnostic: the words are English, the classes are Brick vocabulary. A building that has no
room of the named kind is told so by the caller -- a filter that matches nothing must never turn
into "no such bookings" (that is the stale-register failure this exists to prevent, in reverse).
"""

from __future__ import annotations

import re
from typing import List, Mapping, Optional, Sequence, Set, Tuple

#: (pattern for the words a person uses, Brick classes that mean it, how to say it back).
_KIND_WORDS: Tuple[Tuple["re.Pattern[str]", Tuple[str, ...], str], ...] = (
    (
        re.compile(r"\b(?:meeting|conference|seminar|board)\s*rooms?\b|\bboardrooms?\b", re.I),
        ("Conference_Room", "Meeting_Room", "Boardroom"),
        "meeting rooms",
    ),
    (
        re.compile(r"\b(?:labs?|laborator(?:y|ies))\b", re.I),
        ("Laboratory",),
        "laboratories",
    ),
    (
        re.compile(r"\boffices?\b", re.I),
        ("Office",),
        "offices",
    ),
    (
        re.compile(r"\b(?:class\s*rooms?|lecture\s+(?:rooms?|halls?|theat(?:re|er)s?))\b", re.I),
        ("Classroom", "Lecture_Hall", "Auditorium"),
        "teaching rooms",
    ),
)


def kinds_asked(question: str) -> Tuple[Tuple[str, ...], str]:
    """(Brick classes, plural phrase) for the kind of room a question names; ((), "") for none."""
    q = question or ""
    for pattern, classes, phrase in _KIND_WORDS:
        if pattern.search(q):
            return classes, phrase
    return (), ""


_SINGULAR = {
    "meeting rooms": "meeting room",
    "laboratories": "laboratory",
    "offices": "office",
    "teaching rooms": "teaching room",
}


def noun_for(plural: str, count: int) -> str:
    """The phrase for ``count`` rooms of a kind: "1 meeting room", "3 meeting rooms"."""
    return _SINGULAR.get(plural, plural) if count == 1 else plural


def rooms_of_kind(
    rooms: Sequence[str],
    kinds_by_room: Mapping[str, Set[str]],
    wanted: Sequence[str],
) -> Optional[List[str]]:
    """The rooms carrying any wanted class, or None when the building has none of the kind.

    None is different from []: it means "this building does not record that kind of room", and the
    caller must not filter on it -- an empty filter would report that nothing is booked when what
    is actually true is that the kind is not recorded.
    """
    if not wanted or not kinds_by_room:
        return None
    wanted_set = {w.lower() for w in wanted}
    held = [r for r in rooms if {k.lower() for k in kinds_by_room.get(r, ())} & wanted_set]
    return held or None
