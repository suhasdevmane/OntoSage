# -*- coding: utf-8 -*-
"""Where 'reception' and 'the entrance' are, read from the graph and not from a drawing's text.

WHAT WENT WRONG
---------------
    "How do I get to the lifts from the entrance?"
      -> "Passenger Lift 1 and Passenger Lift 2 / Goods Lift serve Reception's floor (floor 4)."

The building's reception is Room 0.01 -- "Main Reception", floor 0, typed brick:Reception -- and its
own text says so ("Abacws Reception (Ground Floor, main entrance)"). The floor-4 plan carries two
labels the PDF text extraction read off the drawing, "Reception" and "Main Entrance": no polygon, no
area, no ontology IRI. Nothing on floor 0 is typed `reception` in the floor-plan manifest, so the
spatial lane's default starting point, and every lookup of the word "reception", found floor 4.

A drawing's text is a hint. The graph is the building's statement, and where the two disagree about
which floor a named place is on, the graph wins.

WHAT THIS DOES
--------------
* `locate` -- a place a question names ("nearest lift to reception") is resolved to the graph space
  of that kind, when exactly ONE such space exists, and mapped to the floor-plan zone that carries
  the same ontology IRI. Two spaces of one kind is ambiguous and yields nothing rather than a guess.
* `entrance` -- the building's default starting point: the entry-type space (entrance, reception,
  lobby, foyer) on the lowest floor, preferring one the floor plan also draws.

Neither names a room, floor or building: kinds come from the room labels and Brick classes the graph
holds, and the entry words are ordinary English.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from orchestrator.services.room_type_lookup import (
    RoomRecord,
    SparqlExec,
    _stem,
    _variants,
    load_rooms,
)
from shared.utils import get_logger

logger = get_logger(__name__)

#: Words that make a space an entry point. Ordinary English, not a building's vocabulary.
ENTRY_WORDS = frozenset({"entrance", "reception", "lobby", "foyer"})

#: Words that add nothing to a kind: "Main Entrance Zone" and "Server Room" name an entrance and a
#: server.
_GENERIC_WORDS = frozenset({"room", "space", "zone", "area"})

#: A numbered label ("Room 1.06 -- Computer Laboratory") keeps its kind AFTER the dash; any other
#: label ("Main Entrance Zone -- Ground Floor") names its kind BEFORE it.
_NUMBERED = re.compile(r"^(?:room|space|zone)\s+[\w.\-]+$", re.IGNORECASE)
_DASH = re.compile(r"\s[—–-]\s")
_PARENS = re.compile(r"\([^)]*\)")
_WORD = re.compile(r"[a-z0-9]+")

#: Words that may stand between a preposition and the place it names without modifying it.
_BEFORE_HEAD_OK = frozenset(
    "the a an to from at near by of my our this that nearest closest next beside around in on "
    "and or is are where get reach go".split()
)


@dataclass(frozen=True)
class Anchor:
    """A named place, resolved against the graph."""

    label: str
    floor: Optional[int]
    iri: str
    zone_id: Optional[str] = None
    kind: str = ""


def _ordered_words(text: str) -> List[str]:
    """Stemmed words in order, without the words that add nothing to a kind."""
    words = [_stem(w) for w in _WORD.findall((text or "").lower().replace("_", " "))]
    return [w for w in words if w not in _GENERIC_WORDS]


def kind_names(room: RoomRecord) -> List[str]:
    """The names a place answers to: its own kind words plus its non-generic Brick classes."""
    label = _PARENS.sub("", room.label or "").strip()
    parts = _DASH.split(label, maxsplit=1)
    if len(parts) == 2:
        named = parts[1] if _NUMBERED.match(parts[0].strip()) else parts[0]
    else:
        named = "" if _NUMBERED.match(label) else label
    names = list(_variants(named))
    names += [c.replace("_", " ") for c in room.classes]
    seen: List[str] = []
    for n in names:
        if n and n.lower() not in [s.lower() for s in seen]:
            seen.append(n)
    return seen


def _display(room: RoomRecord) -> str:
    """How to call the place in an answer: 'Room 0.01' for a numbered room, else its kind.

    The kind, not the whole label: "Main Entrance Zone — Ground Floor" reads as a place AND a floor,
    and an answer that already states the floor then says it twice ("… — Ground Floor's floor").
    """
    label = (room.label or "").strip()
    first = _DASH.split(label, maxsplit=1)[0].strip()
    if _NUMBERED.match(first):
        return first
    return room.descriptor or label or room.iri.rsplit("#", 1)[-1]


def _index(rooms: Iterable[RoomRecord]) -> Dict[str, Dict[str, Tuple[RoomRecord, str]]]:
    """head word -> {iri: (room, kind name)}: what each place could be called by its last word."""
    out: Dict[str, Dict[str, Tuple[RoomRecord, str]]] = {}
    for room in rooms:
        for name in kind_names(room):
            words = _ordered_words(name)
            if words:
                out.setdefault(words[-1], {}).setdefault(room.iri, (room, name))
    return out


def zone_for_iri(manifests: Sequence[Any], iri: str) -> Optional[str]:
    """The floor-plan zone id that carries this ontology IRI, or None when the plans do not draw it."""
    best: Optional[str] = None
    for m in manifests or []:
        for s in getattr(m, "spaces", []) or []:
            if getattr(s, "ontology_iri", None) == iri:
                zone = getattr(s, "zone_id", None)
                if zone and (getattr(s, "area_m2", None) or best is None):
                    best = zone
    return best


def _anchor(room: RoomRecord, name: str, manifests: Sequence[Any]) -> Anchor:
    return Anchor(
        label=_display(room),
        floor=room.floor,
        iri=room.iri,
        zone_id=zone_for_iri(manifests, room.iri),
        kind=name,
    )


def _modified_differently(q_words: List[str], head: str, name_words: List[str]) -> bool:
    """True when the word before the head in the question modifies it in a way the name does not.

    "the west entrance" must not resolve to a building whose only entrance is the "Main Entrance".
    """
    for i, w in enumerate(q_words):
        if w == head and i > 0:
            prev = q_words[i - 1]
            if prev not in _BEFORE_HEAD_OK and prev not in name_words:
                return True
    return False


def pick(
    question: str, rooms: Sequence[RoomRecord], exclude: Iterable[str] = ()
) -> Optional[Tuple[RoomRecord, str]]:
    """The single place of a unique kind the question names, with the kind's name; else None."""
    raw = [_stem(w) for w in _WORD.findall((question or "").lower())]
    q_words = [w for w in raw if w not in _GENERIC_WORDS]
    skip = {_stem(w.lower()) for w in exclude}
    found: Dict[str, Tuple[RoomRecord, str]] = {}
    for head, places in _index(rooms).items():
        if head not in q_words or head in skip or len(places) != 1:
            continue
        (room, name), *_ = places.values()
        if _modified_differently(q_words, head, _ordered_words(name)):
            continue
        found[room.iri] = (room, name)
    return next(iter(found.values())) if len(found) == 1 else None


def resolve(
    question: str,
    rooms: Sequence[RoomRecord],
    manifests: Sequence[Any] = (),
    exclude: Iterable[str] = (),
) -> Optional[Anchor]:
    """The single place of a kind the question names, or None when none or several match.

    `exclude` holds the words of what is being SOUGHT ("toilet" in "nearest toilet to reception"),
    so a kind that is also the target is never taken as the reference point.
    """
    picked = pick(question, rooms, exclude)
    return _anchor(picked[0], picked[1], manifests) if picked else None


def named_place(
    question: str, rooms: Sequence[RoomRecord], frame: Iterable[str]
) -> Optional[Tuple[RoomRecord, str]]:
    """The place a question is ABOUT: a unique kind is named and nothing but framing is left.

    "Where is the entrance?" is about the entrance; "where is the entrance open at night?" is about
    its opening hours, and is somebody else's question.
    """
    picked = pick(question, rooms)
    if picked is None:
        return None
    room, name = picked
    covered = set(_ordered_words(name)) | set(frame)
    stems = [_stem(w) for w in _WORD.findall((question or "").lower())]
    leftover = [
        w for w in stems if w not in covered and w not in _GENERIC_WORDS and not w.isdigit()
    ]
    return picked if not leftover else None


def entrance_of(rooms: Sequence[RoomRecord], manifests: Sequence[Any] = ()) -> Optional[Anchor]:
    """The entry-type space on the lowest floor, preferring one the floor plans also draw."""
    candidates: List[Tuple[Tuple[int, int, str], RoomRecord, str]] = []
    for room in rooms:
        for name in kind_names(room):
            if ENTRY_WORDS & set(_ordered_words(name)):
                drawn = 0 if zone_for_iri(manifests, room.iri) else 1
                floor = room.floor if room.floor is not None else 999
                candidates.append(((drawn, floor, room.iri), room, name))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    _key, room, name = candidates[0]
    return _anchor(room, name, manifests)


# ── live access ────────────────────────────────────────────────────────────────────────────────

_TTL_S = 300.0
_RETRY_S = 60.0
_cache: Dict[str, Any] = {"at": 0.0, "rooms": None, "retry_at": 0.0}


async def _rooms(sparql_exec: Optional[SparqlExec] = None) -> List[RoomRecord]:
    now = time.monotonic()
    if now < _cache["retry_at"]:
        return []
    if _cache["rooms"] is not None and now - _cache["at"] <= _TTL_S:
        return _cache["rooms"]
    try:
        if sparql_exec is None:
            from orchestrator.services.deliberation.live import sparql_exec as live_exec

            sparql_exec = live_exec
        rooms = await load_rooms(sparql_exec)
    except Exception as exc:
        logger.debug(f"[place_anchor] graph unavailable: {exc}")
        rooms = []
    if not rooms:
        _cache["retry_at"] = now + _RETRY_S
        return []
    _cache["rooms"], _cache["at"] = rooms, now
    return rooms


async def locate(
    question: str,
    manifests: Sequence[Any] = (),
    exclude: Iterable[str] = (),
    sparql_exec: Optional[SparqlExec] = None,
) -> Optional[Anchor]:
    """`resolve` against the live graph; None when the graph cannot be read."""
    rooms = await _rooms(sparql_exec)
    return resolve(question, rooms, manifests, exclude) if rooms else None


async def entrance(
    manifests: Sequence[Any] = (), sparql_exec: Optional[SparqlExec] = None
) -> Optional[Anchor]:
    """`entrance_of` against the live graph; None when the graph cannot be read."""
    rooms = await _rooms(sparql_exec)
    return entrance_of(rooms, manifests) if rooms else None
