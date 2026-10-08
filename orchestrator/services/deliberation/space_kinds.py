# -*- coding: utf-8 -*-
"""space_kinds.py -- what KIND of space each space is, in the building's own words (v2).

WHY THIS EXISTS
---------------
"Which meeting rooms are over their seating capacity?", "which floor has the most meeting rooms?",
"which seminar rooms ...": the kind of room is the commonest filter a compound question applies,
and v1 never applied it -- ARBITER only DECLARED that it could not (BUG-949). The first v2 build
filtered on the two kind-like facets it had, a capacity register's ``spaceFunction`` (42 of 234
spaces) and the workspace register's ``workspaceKind`` (28), and measured live on 2026-10-08 it
answered "Floor 5 has the most meeting rooms: 2" for a building whose own labels put four meeting
rooms on Floor 3: 176 spaces were "not verified" because neither register mentions them.

The building already says what every space is, twice: the descriptor its label carries ("Room 5.17
— Meeting Room") and its Brick room classes (``brick:Conference_Room``). This module reads both,
with the descriptor rule ``room_type_lookup`` already uses, so the two cannot drift apart.

MATCHING
--------
A requested kind matches a space when every content word of the request -- stemmed, the generic
"room / space / area / zone" set aside -- is a word of one of the space's kinds. So "seminar rooms"
matches "Seminar Room", "Conference/Seminar Room" and "Seminar / Conference Room"; "meeting rooms"
matches "Meeting Room" and not the seminar rooms (whose Brick class is also Conference_Room); "labs"
matches "Research Laboratory" and "Computer Laboratory". A request of nothing but generic words
("rooms") names every space. No building's words appear here.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, Sequence, Tuple

from orchestrator.services.room_type_lookup import _GENERIC_CLASSES, RoomRecord, _stem

#: The catalogue key of the facet (facets.py builds it, facet_resolvers.py resolves it).
SPACE_KIND_FACET = "spatial:space_kind"

_WORD_RE = re.compile(r"[a-z0-9]+")
#: A label without a separator is returned whole by the descriptor rule ("Studio 1"); its trailing
#: identifier names one space, not a kind of space.
_TRAILING_ID_RE = re.compile(r"(?:\s+[\w.\-]*\d[\w.\-]*)+$")
#: Words that name no kind on their own: every space is a room, space, area or zone.
_GENERIC_WORDS = frozenset({"room", "space", "area", "zone", "of", "and", "the", "a", "an"})


def space_kinds(label: str, classes: Iterable[str]) -> Tuple[str, ...]:
    """The kinds a space is, in words: its label's descriptor first, then its Brick room classes.

    ``classes`` are Brick local names ("Conference_Room"); the generic ones every room carries
    under reasoning ("Room", "Space", ...) are left out. Duplicates (a class that spells the
    descriptor) are kept once.
    """
    out = []
    seen = set()
    descriptor = RoomRecord("", label or "", None, "", ()).descriptor.strip()
    descriptor = _TRAILING_ID_RE.sub("", descriptor).strip()
    if descriptor and not kind_words(descriptor):
        descriptor = ""  # nothing left but generic words ("Room"): no kind
    if descriptor:
        out.append(descriptor)
        seen.add(descriptor.lower())
    for cls in sorted(classes or ()):
        if not cls or cls.lower() in _GENERIC_CLASSES:
            continue
        words = cls.replace("_", " ").strip()
        if words.lower() not in seen:
            out.append(words)
            seen.add(words.lower())
    return tuple(out)


def kind_words(text: str) -> FrozenSet[str]:
    """The content words of a kind, stemmed: "Conference/Seminar Room" -> {conference, seminar}."""
    return frozenset(
        _stem(w) for w in _WORD_RE.findall((text or "").lower()) if _stem(w) not in _GENERIC_WORDS
    )


def kind_matches(wanted: str, kinds: Sequence[str]) -> bool:
    """True when every content word of ``wanted`` is a word of one of the space's ``kinds``."""
    want = kind_words(wanted)
    if not want:
        return True  # "rooms": a generic word names every space
    return any(want <= kind_words(k) for k in kinds)


__all__ = ["SPACE_KIND_FACET", "kind_matches", "kind_words", "space_kinds"]
