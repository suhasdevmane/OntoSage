# -*- coding: utf-8 -*-
"""'Which rooms are computer laboratories?' and 'which floor is the server room on?' (BUG-810, 827).

WHAT WENT WRONG
---------------
    "Which rooms are computer laboratories?"   -> a prose description of the schools and facilities
    "Which floor are the computer labs on?"     -> the same prose topic, and no floor
    "Which floor is the server room on?"        -> a menu of the floors that have plans

The building's graph types every room, and names it in its own words: `Room 1.06 — Computer
Laboratory` on floor 1, `brick:Server_Room` on floors 2, 4 and 5. The lanes that took these
questions looked elsewhere -- a topic about the departments, a floor-plan menu -- so a fact the
building states in two places was reported as absent or never reached.

WHAT THIS DOES
--------------
Reads the rooms and their floors from the graph, lets a question select them by the two vocabularies
the graph already has -- the Brick class of the room and the descriptor in the room's own label --
and answers with the rooms grouped by floor. The most specific match wins ("computer laboratory" over
"laboratory"), and a question that says anything else at all (a temperature, an opening time, a
booking) is left alone, because this answers WHICH rooms, never what is true of them.

BUILDING-AGNOSTIC
-----------------
No room, floor or department is named here. Brick is the vocabulary; the descriptor is whatever the
building put after the room number. A building whose rooms carry no descriptor is matched on Brick
classes alone, and one whose rooms are untyped gets None.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Tuple,
)

from orchestrator.services.amenity_floor_answer import declared_floor, floor_in_question
from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

_BRICK = "https://brickschema.org/schema/Brick#"

#: Every space on a floor, with the Brick classes it is typed with. Spaces whose parent is not a
#: floor (a server room drawn as part of a room) are the SAME place described twice and are left out.
#:
#: Space OR Room, not Room alone: the places people ask for by name are not all rooms. "Where is the
#: main entrance?" is about `Main_Entrance_Zone`, typed brick:Space and parented to Floor 0 -- asking
#: only for rooms missed it, and the answer came from a "Main Entrance" text label on the floor-4
#: drawing instead (BUG-838).
#:
#: THREE WAYS TO BE A ROOM, because a building states it in whichever of them its store supports.
#: This building's metadata asserts `brick:Server_Room` and nothing else: `brick:Room` is the
#: STORE's inference, so asking for Room alone returns 234 rooms against GraphDB and NOTHING
#: against a store with the same data and no reasoner. The third branch walks Brick's own
#: subClassOf chain instead, which needs only the TBox the building already loads (measured: 224
#: rooms in 0.3 s with no reasoner at all).
_ROOMS_QUERY = f"""
PREFIX brick: <{_BRICK}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?r ?l ?f ?fl (GROUP_CONCAT(DISTINCT ?t; separator=" ") AS ?types) WHERE {{
  {{ ?r a brick:Space }} UNION {{ ?r a brick:Room }}
  UNION {{ ?r a ?rc . ?rc rdfs:subClassOf* brick:Room }}
  ?r brick:isPartOf ?f .
  ?f a brick:Floor .
  OPTIONAL {{ ?r rdfs:label ?l }}
  OPTIONAL {{ ?f rdfs:label ?fl }}
  OPTIONAL {{ ?r a ?t . FILTER(STRSTARTS(STR(?t), "{_BRICK}")) }}
}} GROUP BY ?r ?l ?f ?fl
"""

#: Places whose location is a SAFETY fact. A fire exit, an escape stairwell, a refuge point and an
#: assembly point are published by the evacuation register and by the notices people are briefed on.
#: This lookup reads room LABELS, which is not that source, so it must never be the thing that tells
#: somebody where to evacuate to -- a plausible wrong answer there costs more than no answer.
_SAFETY_PLACES = re.compile(
    r"\b(?:fire\s+exit|emergency\s+exit|escape\s+route|stairwell|staircase|stairs|refuge|"
    r"assembly\s+point|muster)\b",
    re.IGNORECASE,
)

#: A numbered label ("Room 1.06 — Computer Laboratory") names its KIND after the dash; any other
#: label ("Main Entrance Zone — Ground Floor") names its kind BEFORE it, and what follows is where
#: it is. Reading every label the first way made the main entrance a kind of place called "Ground
#: Floor".
_NUMBERED = re.compile(r"^(?:room|space|zone)\s+[\w.\-]+$", re.IGNORECASE)

#: Brick classes every room has. Matching on these would select every room in the building.
_GENERIC_CLASSES = frozenset(
    {"room", "space", "location", "class", "entity", "resource", "collection", "zone", "area"}
)

#: A label's own separator: "Room 1.06 — Computer Laboratory".
_LABEL_SPLIT = re.compile(r"\s[—–-]\s")
_PARENS = re.compile(r"\([^)]*\)")
_WORD = re.compile(r"[a-z0-9]+")

#: Words a reader uses for a kind the building spells differently. "Where is the store?" found
#: nothing while the building holds four rooms labelled "Storage Room" and one "Loading and Goods
#: Storage". A verb reading ("do you store conversations?") is harmless: it leaves content words
#: over, and a question with leftovers is not answered from the room records at all.
_ALIASES = {
    "lab": "laboratory",
    "labs": "laboratory",
    "laboratories": "laboratory",
    "store": "storage",
    "stores": "storage",
    "storeroom": "storage",
    "storerooms": "storage",
    "stockroom": "storage",
    "stockrooms": "storage",
}

#: Words that carry no kind of room. Anything left over after the matched kind and these means
#: the question is about something else, and this module leaves it to the lane that owns it.
_FRAME = frozenset(
    "a an the is are was were be been which what who whom whose list show name give tell me us "
    "all any every each there here in on at of for to from by with building floor floors level "
    "levels storey rooms room spaces space located location locations found have has do does can "
    "could would will i we you please called kind kinds type types many how count number total "
    "recorded record records held hold holds exist exists it its this that these those and or "
    "as one ones storeys where".split()
)

_LIST_SHAPE = re.compile(r"\b(?:which|what|list|show|name|give|how\s+many)\b", re.I)
#: "Where is the server room?" asks the same thing as "which floor is it on", and is answered the
#: same way. A question about the NEAREST one is not this: that needs a starting point and belongs
#: to the spatial lane, so "nearest"/"closest" are left out of the framing words and any question
#: carrying them keeps its own lane.
_FLOOR_SHAPE = re.compile(
    r"\b(?:which|what)\s+floors?\b|\bon\s+which\s+floors?\b|\bwhat\s+level\b|\bwhich\s+level\b"
    r"|\bwhere\s+(?:is|are)\b",
    re.I,
)

#: Above this many rooms an answer counts by floor and names none, and says how to narrow it.
_LIST_LIMIT = 40


@dataclass(frozen=True)
class RoomRecord:
    """One room, as the graph records it."""

    iri: str
    label: str
    floor: Optional[int]
    floor_label: str
    classes: Tuple[str, ...]

    @property
    def prefix(self) -> str:
        """What to call it: 'Room 1.06' for a numbered room, else the whole label it was given."""
        parts = _LABEL_SPLIT.split(self.label or "", maxsplit=1)
        head = parts[0].strip() if parts else ""
        if head and _NUMBERED.match(head):
            return head
        return (self.label or "").strip() or self.iri.rsplit("#", 1)[-1]

    @property
    def descriptor(self) -> str:
        """The building's own words for the KIND: 'Computer Laboratory', 'Main Entrance Zone'."""
        label = _PARENS.sub("", self.label or "").strip()
        parts = _LABEL_SPLIT.split(label, maxsplit=1)
        if len(parts) == 2:
            return (parts[1] if _NUMBERED.match(parts[0].strip()) else parts[0]).strip()
        return "" if _NUMBERED.match(label) else label


def _stem(word: str) -> str:
    if word in _ALIASES:
        return _ALIASES[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


#: Words that name no kind of place on their own: every place is a room, space, zone or area, so
#: keeping them would make "Main Entrance Zone" and "the main entrance" different things.
_GENERIC_WORDS = frozenset({"room", "space", "zone", "area"})


def tokens(text: str) -> FrozenSet[str]:
    """The comparable words of a phrase: lower-cased, singular, without room/space/zone/area."""
    words = (_stem(w) for w in _WORD.findall((text or "").lower().replace("_", " ")))
    return frozenset(w for w in words if w not in _GENERIC_WORDS)


def _variants(descriptor: str) -> List[str]:
    """'Staff Break Room / Kitchen' names two kinds of room; each is matched on its own."""
    return [v.strip() for v in re.split(r"\s*/\s*", descriptor or "") if v.strip()]


async def load_rooms(sparql_exec: SparqlExec) -> List[RoomRecord]:
    """Every room the graph places on a floor; [] when the graph cannot be read."""
    try:
        data = await sparql_exec(_ROOMS_QUERY)
    except Exception as exc:
        logger.warning(f"[room_type_lookup] room fetch failed: {exc}")
        return []
    rooms: List[RoomRecord] = []
    for b in (data or {}).get("results", {}).get("bindings", []):
        iri = b.get("r", {}).get("value", "")
        if not iri:
            continue
        label = b.get("l", {}).get("value", "")
        if _SAFETY_PLACES.search(label):
            continue
        floor_iri = b.get("f", {}).get("value", "")
        floor_label = b.get("fl", {}).get("value", "") or floor_iri.rsplit("#", 1)[-1]
        number = declared_floor(floor_iri.rsplit("#", 1)[-1])
        classes = tuple(
            t.rsplit("#", 1)[-1]
            for t in (b.get("types", {}).get("value", "") or "").split()
            if t.rsplit("#", 1)[-1].lower() not in _GENERIC_CLASSES
        )
        rooms.append(
            RoomRecord(
                iri=iri,
                label=label,
                floor=number,
                floor_label=floor_label,
                classes=classes,
            )
        )
    return rooms


def _candidates(rooms: Sequence[RoomRecord]) -> Dict[str, Tuple[FrozenSet[str], List[RoomRecord]]]:
    """name -> (comparable words, rooms of that kind), from descriptors and Brick classes."""
    out: Dict[str, Tuple[FrozenSet[str], List[RoomRecord]]] = {}
    for room in rooms:
        names = [v for v in _variants(room.descriptor)] + [
            c.replace("_", " ") for c in room.classes
        ]
        for name in names:
            words = tokens(name)
            if not words:
                continue
            entry = out.setdefault(name.lower(), (words, []))
            if room not in entry[1]:
                entry[1].append(room)
    return out


def _matched_kind(
    question: str, rooms: Sequence[RoomRecord]
) -> Optional[Tuple[List[str], List[RoomRecord], FrozenSet[str]]]:
    """The most specific kind of room the question names: (names, rooms, words used)."""
    q_words = tokens(question)
    candidates = _candidates(rooms)
    hits = [
        (name, words, members) for name, (words, members) in candidates.items() if words <= q_words
    ]
    if not hits:
        # THE HEAD WORD, when the building has only one place of that kind. "Where is the entrance?"
        # names no place in full -- the building calls it the "Main Entrance Zone" -- and a reader
        # who asks that in a building with ONE entrance is not being ambiguous. Only when the head
        # word picks out exactly one kind: two "... Office" kinds leave the question unanswered
        # here rather than answered about the wrong one.
        by_head: Dict[str, List[Tuple[str, FrozenSet[str], List[RoomRecord]]]] = {}
        for name, (words, members) in candidates.items():
            ordered = [w for w in _WORD.findall(name.lower()) if _stem(w) not in _GENERIC_WORDS]
            if ordered:
                by_head.setdefault(_stem(ordered[-1]), []).append((name, words, members))
        heads = [h for h in by_head if h in q_words and len(by_head[h]) == 1]
        if len(heads) != 1:
            return None
        hits = by_head[heads[0]]
    widest = max(len(w) for _n, w, _m in hits)
    top = [h for h in hits if len(h[1]) == widest]
    used: FrozenSet[str] = frozenset().union(*(h[1] for h in top))
    # Everything else the question says must be framing, or it is asking something about the rooms.
    # Judged on the raw word too: stemming "does" and "this" would otherwise leave them as content.
    leftover = {
        w
        for w in _WORD.findall((question or "").lower())
        if not w.isdigit()
        and w not in _FRAME
        and _stem(w) not in _FRAME
        and _stem(w) not in used
        and _stem(w) not in ("room", "space")
    }
    if leftover:
        return None
    members: List[RoomRecord] = []
    for _n, _w, ms in top:
        for m in ms:
            if m not in members:
                members.append(m)
    return [h[0] for h in top], members, used


def _number_key(room: RoomRecord) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", room.prefix)]
    return (room.floor if room.floor is not None else 999, nums, room.prefix)


def _floor_head(floor: Optional[int], label: str) -> str:
    return f"Floor {floor}" if floor is not None else (label or "Floor not recorded")


def _group(rooms: Sequence[RoomRecord]) -> List[Tuple[str, List[RoomRecord]]]:
    grouped: Dict[Tuple[Any, str], List[RoomRecord]] = {}
    for r in sorted(rooms, key=_number_key):
        grouped.setdefault((r.floor if r.floor is not None else 999, r.floor_label), []).append(r)
    return [
        (_floor_head(k[0] if k[0] != 999 else None, k[1]), v) for k, v in sorted(grouped.items())
    ]


def _kind_title(names: Sequence[str], rooms: Sequence[RoomRecord]) -> str:
    """How to name the kind: the most specific name the question matched, in the building's words."""
    longest = sorted(names, key=len, reverse=True)[0]
    for r in rooms:
        for d in _variants(r.descriptor):
            if d.lower() == longest.lower():
                return d
    return longest.title()


def _breakdown(rooms: Sequence[RoomRecord], title: str) -> str:
    """The descriptors behind a broad kind: 'Laboratory' -> 61 Research Laboratory, 10 Computer …"""
    counts: Dict[str, int] = {}
    for r in rooms:
        if r.descriptor:
            counts[r.descriptor] = counts.get(r.descriptor, 0) + 1
    if not counts or set(d.lower() for d in counts) <= {title.lower()}:
        return ""
    parts = [f"{n} {d}" for d, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    return " (" + ", ".join(parts) + ")"


def _and_join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def render_rooms(names: Sequence[str], rooms: Sequence[RoomRecord], on_floor: Optional[int]) -> str:
    """Which rooms: the count, then the rooms by floor (counts only when there are very many)."""
    title = _kind_title(names, rooms)
    scope = f" on floor {on_floor}" if on_floor is not None else ""
    n = len(rooms)
    head = (
        f"**{n} room{'s are' if n != 1 else ' is'} recorded as {title}{scope}**"
        f"{_breakdown(rooms, title)}:"
    )
    lines = [head, ""]
    for label, members in _group(rooms):
        if n > _LIST_LIMIT:
            lines.append(f"- {label}: {len(members)}")
        else:
            lines.append(f"- {label} ({len(members)}): " + ", ".join(m.prefix for m in members))
    if n > _LIST_LIMIT:
        lines.append("\nAsk for one floor to see its rooms by name.")
    lines.append("\n_From the building's own room records._")
    return "\n".join(lines)


def _numbered_names(members: Sequence[RoomRecord]) -> List[str]:
    """The room numbers worth naming beside the kind.

    A place whose whole label IS its kind ("Main Entrance Zone") would otherwise be printed twice,
    once as the kind and once as its own name.
    """
    return [m.prefix for m in members if _NUMBERED.match(m.prefix)]


def render_floors(names: Sequence[str], rooms: Sequence[RoomRecord]) -> str:
    """Which floor: the floors that hold this kind of room, with the rooms on each."""
    title = _kind_title(names, rooms)
    groups = _group(rooms)
    floors = [label.replace("Floor ", "") for label, _m in groups]
    if len(groups) == 1:
        label, members = groups[0]
        head = f"**The building records a {title} on {label.lower()}"
        numbered = _numbered_names(members)
        head += (":** " + _and_join(numbered) + ".") if numbered else ".**"
        return head + "\n\n_From the building's own room records._"
    lines = [f"**The building records a {title} on floors {_and_join(floors)}:**", ""]
    for label, members in groups:
        numbered = _numbered_names(members)
        lines.append(f"- {label}: " + ", ".join(numbered) if numbered else f"- {label}")
    lines.append("\n_From the building's own room records._")
    return "\n".join(lines)


def wants_rooms_or_floors(question: str) -> Optional[str]:
    """'floors' when the question asks which floor, 'rooms' when it asks which rooms, else None."""
    if _FLOOR_SHAPE.search(question or ""):
        return "floors"
    if _LIST_SHAPE.search(question or ""):
        return "rooms"
    return None


async def answer(
    question: str,
    sparql_exec: SparqlExec,
    rooms: Optional[Sequence[RoomRecord]] = None,
    only: Optional[str] = None,
) -> Optional[str]:
    """The rooms (or floors) of the kind the question names, or None when it names no such kind.

    None is the ordinary result: it means "not this module's question", and the caller carries on
    exactly as it did before. `rooms` lets a caller that already holds the list skip the fetch;
    `only` ("floors" or "rooms") restricts which shape of question is answered -- the floor-plan
    lane takes only "which floor", because "show me the meeting rooms" wants the drawing.
    """
    shape = wants_rooms_or_floors(question)
    if shape is None or (only is not None and shape != only):
        return None
    rooms = list(rooms) if rooms is not None else await load_rooms(sparql_exec)
    if not rooms:
        return None
    on_floor = floor_in_question(question)
    hit = _matched_kind(question, rooms)
    if hit is None:
        return None
    names, members, _used = hit
    if on_floor is not None:
        members = [m for m in members if m.floor == on_floor]
        if not members:
            title = _kind_title(names, hit[1])
            return (
                f"**No room on floor {on_floor} is recorded as {title}.** "
                f"{title} is recorded on floor"
                f"{'s' if len({m.floor for m in hit[1]}) > 1 else ''} "
                + _and_join(sorted({str(m.floor) for m in hit[1] if m.floor is not None}))
                + "."
            )
    if not members:
        return None
    return (
        render_floors(names, members)
        if shape == "floors"
        else render_rooms(names, members, on_floor)
    )


#: The rooms change when the building's model does, not per question; five minutes is the same
#: freshness the amenity resolver allows itself.
_LIVE_TTL_S = 300.0
#: A graph that could not be read is not asked again for a minute, so a lane that runs this on every
#: question does not add a connection timeout to each one while the graph is down.
_LIVE_RETRY_S = 60.0
_live_cache: Dict[str, Any] = {"at": 0.0, "rooms": None, "retry_at": 0.0}


async def answer_live(question: str, only: Optional[str] = None) -> Optional[str]:
    """`answer` against the live graph; None when the graph is unreachable, never an exception."""
    shape = wants_rooms_or_floors(question)
    if shape is None or (only is not None and shape != only):
        return None
    now = time.monotonic()
    if now < _live_cache["retry_at"]:
        return None
    try:
        from orchestrator.services.deliberation.live import sparql_exec

        if _live_cache["rooms"] is None or now - _live_cache["at"] > _LIVE_TTL_S:
            fetched = await load_rooms(sparql_exec)
            if not fetched:
                _live_cache["retry_at"] = now + _LIVE_RETRY_S
                return None
            _live_cache["rooms"], _live_cache["at"] = fetched, now
        return await answer(question, sparql_exec, _live_cache["rooms"], only)
    except Exception as exc:
        _live_cache["retry_at"] = now + _LIVE_RETRY_S
        logger.warning(f"[room_type_lookup] live lookup skipped: {exc}")
        return None


def capability_result(text: str, building_name: str) -> Dict[str, Any]:
    """The capability lane's result dict for a room-records answer."""
    return {
        "success": True,
        "response": text,
        "provenance": "room_records",
        "building_name": building_name,
    }
