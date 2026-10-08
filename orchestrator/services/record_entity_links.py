# -*- coding: utf-8 -*-
"""Resolve a register's location text to the building's own spaces and floors (v2, P1).

WHY THIS EXISTS
---------------
A lifted record says where it is in WORDS -- ``ontosage:locationText "Room 1.06 - Computer
Laboratory"``, ``ontosage:onFloor "1"`` -- while every sensor is keyed by the room's IRI. A
question that combines a record criterion with a sensed one ("a room that seats twelve AND is
quiet") therefore had no join in the graph, only string matching, which nothing does. This
module turns the words into an explicit link at lift time, so the join is a triple pattern.

THE RULE, IN ORDER, AND NOTHING ELSE
------------------------------------
(a) A dotted room id that ends the text's first clause ("Room 1.06 - ...", "Fan Coil Unit
    Room 5.03") and that exactly ONE space carries as its own identifier. The identifier is
    read with ``building_lexicon.strip_type_word`` -- the same reading of a space's name the
    routing layer uses -- so a sub-space whose label merely mentions its parent ("Server Room
    - Floor 4 (Room 4.44)") does not claim the parent's number.
(b) An exact label match to exactly one space. Case, runs of whitespace and dash typography
    (hyphen, en dash, em dash) are normalised; nothing else is.
(c) A floor reference ("3", "Level 3", "Floor 3") to the one floor whose number matches --
    ``rec:levelNumber`` when the graph declares it, else the number in the floor's own name --
    or an exact label match to exactly one floor.

Anything ambiguous or unmatched is NOT linked, and the reason is returned. No fuzzy match, no
nearest room, no "probably": a wrong link is worse than none, because a join over it would
attribute one room's readings to another room's record with complete confidence.

A dotted id is only taken as THE location when it ends the first clause and no reference-point
word precedes it. "Corridor outside 2.01" names a corridor, and "2.01 adjacent corridor" names
one too; both are left for rule (b), and unlinked when (b) cannot place them exactly.

BUILDING-AGNOSTIC
-----------------
The spaces and floors come from the active building's own graph in one SELECT. No identifier,
label or namespace of any building appears here; the vocabulary is generic English.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from orchestrator.services.building_lexicon import label_head, strip_type_word
from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

KIND_SPACE = "space"
KIND_FLOOR = "floor"

#: The link kinds a mapping column may declare (``link:`` in ontology/record_documents/*.yaml).
LOCATED_IN = "located_in"
ON_FLOOR = "on_floor"
ROUTE_FROM = "route_from"
ROUTE_TO = "route_to"
SERVES = "serves"
LINK_KINDS: Tuple[str, ...] = (LOCATED_IN, ON_FLOOR, ROUTE_FROM, ROUTE_TO, SERVES)

#: The object property each link kind writes. Declared in ontology/ontosage_schema.ttl,
#: Module R.11, with no rdfs:domain.
#:
#: NOT ``ontosage:locatedIn`` and NOT ``ontosage:servesSpace``, although those names exist.
#: Both carry an rdfs:domain (Capability, ServedZone) and the repository reasons with
#: rdfsplus-optimized, so writing them on a record would TYPE the record: every linked booking
#: would become an inferred Capability, and every asset an inferred ServedZone -- a subclass of
#: brick:Location, so it would then be listed among the building's spaces. ``locatedIn`` is also
#: read as "an amenity located in a space" by the deliberation lane's capability schema.
LINK_PREDICATES: Dict[str, str] = {
    LOCATED_IN: _ONTOSAGE + "locatedInSpace",
    ON_FLOOR: _ONTOSAGE + "onFloorEntity",
    ROUTE_FROM: _ONTOSAGE + "routeFromSpace",
    ROUTE_TO: _ONTOSAGE + "routeToSpace",
    SERVES: _ONTOSAGE + "servesAreaSpace",
}
#: Whatever column named it, a FLOOR is linked with onFloorEntity: "located in a space" must
#: never return a floor to a query that asks which room a record is in.
FLOOR_PREDICATE = LINK_PREDICATES[ON_FLOOR]
LINK_PREDICATE_IRIS: FrozenSet[str] = frozenset(LINK_PREDICATES.values())

#: Which kinds of place each link kind may point at.
_TARGETS: Dict[str, Tuple[str, ...]] = {
    LOCATED_IN: (KIND_SPACE, KIND_FLOOR),
    ON_FLOOR: (KIND_FLOOR,),
    ROUTE_FROM: (KIND_SPACE,),
    ROUTE_TO: (KIND_SPACE,),
    SERVES: (KIND_SPACE,),
}


def link_predicate(link: str, target_kind: str) -> str:
    """The predicate a resolved value is written with."""
    return FLOOR_PREDICATE if target_kind == KIND_FLOOR else LINK_PREDICATES[link]


def exclude_link_predicates(var: str = "?p") -> str:
    """A SPARQL FILTER keeping the lift's entity links out of a record's FIELDS.

    The links are join keys, not content: the text beside each one already says the same thing
    in words. A register handover that pivots every predicate into a column would otherwise
    hand the narration a bare IRI per row, count it against the prompt budget, and give a
    "which floors have ..." grouping two floor columns where it needs exactly one.
    """
    iris = ", ".join(f"<{iri}>" for iri in sorted(LINK_PREDICATE_IRIS))
    return f"FILTER({var} NOT IN ({iris}))"


# ── text normalisation ───────────────────────────────────────────────────────────

_DASH_RUN_RE = re.compile(r"\s*[‐-―−-]+\s*")

#: A dotted room id standing on its own: "1.06", "5.28A". Not inside a longer number or word.
_DOTTED_ID_RE = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3}[A-Za-z]?)(?!\w|\.\d)")
_DOTTED_ID_FULL_RE = re.compile(r"\d{1,3}\.\d{1,3}[A-Za-z]?")

#: "3", "-1", "Floor 3", "Level 3", "level_3", "Storey 2". Generic English floor words only.
_FLOOR_REF_RE = re.compile(
    r"(?:(?:floor|level|storey|story)[\s_\-]*)?([+-]?\d{1,3})", re.IGNORECASE
)

#: Words that make a room a REFERENCE POINT rather than the location: "corridor outside 2.01",
#: "riser next to 3.15", "route from 0.01". Generic English.
_REFERENCE_POINT_WORDS = frozenset(
    """outside near nearby beside behind opposite facing between adjacent next towards toward
    from to via past beyond above below under over off around serving serves for""".split()
)

_WORD_RE = re.compile(r"[a-z]+")


def normalise_label(text: str) -> str:
    """Case, whitespace and dash typography normalised; every other character kept.

    "Room 0.04 - Mechanical Plant Room" and "Room 0.04 — Mechanical Plant Room" are the same
    label written with two different dashes, and both spellings occur in one building's own
    documents. Nothing beyond that is folded: this is an exact match, not a similarity.
    """
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = _DASH_RUN_RE.sub(" - ", text)
    return " ".join(text.split())


def floor_number_in(text: str) -> Optional[int]:
    """The floor number a whole text names ("3", "Level 3"), or None."""
    match = _FLOOR_REF_RE.fullmatch(str(text or "").strip())
    return int(match.group(1)) if match else None


def _dotted_identifier(name: str) -> str:
    """The dotted id a space's NAME carries as its identifier, or ""."""
    ident = strip_type_word(name)
    return ident if _DOTTED_ID_FULL_RE.fullmatch(ident or "") else ""


def _tail(text: str) -> str:
    """The description after a name's first clause: `Room 1.06 — Lab` -> `Lab`."""
    head = label_head(text)
    return str(text or "")[len(head) :].strip(" \t—–-:(/)") if head else ""


# ── outcomes ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LinkOutcome:
    """What one location value resolved to, or why it did not resolve."""

    target: str = ""
    target_kind: str = ""
    #: dotted_id | label | floor_number | floor_label
    rule: str = ""
    #: Why nothing was linked. Empty when linked.
    reason: str = ""
    #: Linked by its room id, but the text describes the room differently from the building's
    #: own label. Reported for the document's owner; it does not block the link, because the
    #: id is the identifier and the description is what drifts.
    note: str = ""

    @property
    def linked(self) -> bool:
        return bool(self.target)


def _unlinked(reason: str) -> LinkOutcome:
    return LinkOutcome(reason=reason)


# ── the index ────────────────────────────────────────────────────────────────────


@dataclass
class PlaceIndex:
    """The active building's spaces and floors, keyed for exact lookup."""

    namespace: str = ""
    space_ids: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    space_labels: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    floor_numbers: Dict[int, Tuple[str, ...]] = field(default_factory=dict)
    floor_labels: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    labels: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    spaces: int = 0
    floors: int = 0

    @property
    def usable(self) -> bool:
        return bool(self.spaces or self.floors)

    @classmethod
    def from_rows(cls, namespace: str, rows: Iterable[Dict[str, Any]]) -> "PlaceIndex":
        """Build the index from ``{place, kind, label, level}`` rows (one per binding)."""
        kinds: Dict[str, Set[str]] = {}
        labels: Dict[str, List[str]] = {}
        levels: Dict[str, Set[int]] = {}
        for row in rows or []:
            iri = _cell(row, "place")
            kind = _cell(row, "kind")
            if not iri or kind not in (KIND_SPACE, KIND_FLOOR):
                continue
            if namespace and not iri.startswith(namespace):
                continue
            kinds.setdefault(iri, set()).add(kind)
            label = _cell(row, "label")
            if label and label not in labels.setdefault(iri, []):
                labels[iri].append(label)
            level = _cell(row, "level")
            if level:
                try:
                    levels.setdefault(iri, set()).add(int(float(level)))
                except ValueError:
                    pass

        space_ids: Dict[str, List[str]] = {}
        space_labels: Dict[str, List[str]] = {}
        floor_numbers: Dict[int, List[str]] = {}
        floor_labels: Dict[str, List[str]] = {}
        spaces = floors = 0
        for iri in sorted(kinds):
            names = [_local(iri, namespace)] + labels.get(iri, [])
            if KIND_SPACE in kinds[iri]:
                spaces += 1
                for ident in sorted({_dotted_identifier(n) for n in names} - {""}):
                    space_ids.setdefault(ident, []).append(iri)
                for label in labels.get(iri, []):
                    _add(space_labels, normalise_label(label), iri)
            if KIND_FLOOR in kinds[iri]:
                floors += 1
                number = _floor_number(levels.get(iri, set()), names)
                if number is not None:
                    floor_numbers.setdefault(number, []).append(iri)
                for label in labels.get(iri, []):
                    _add(floor_labels, normalise_label(label), iri)

        return cls(
            namespace=namespace,
            space_ids={k: tuple(v) for k, v in space_ids.items()},
            space_labels={k: tuple(v) for k, v in space_labels.items()},
            floor_numbers={k: tuple(v) for k, v in floor_numbers.items()},
            floor_labels={k: tuple(v) for k, v in floor_labels.items()},
            labels={k: tuple(v) for k, v in labels.items()},
            spaces=spaces,
            floors=floors,
        )

    # ── resolution ──────────────────────────────────────────────────────────────

    def resolve(self, text: str, link: str) -> LinkOutcome:
        """Resolve one location value for one link kind. Never guesses."""
        text = str(text or "").strip()
        targets = _TARGETS.get(link)
        if not text or not targets:
            return _unlinked("nothing to resolve")
        if targets == (KIND_FLOOR,):
            return self._resolve_floor(text)
        space = self._resolve_space(text)
        if space.linked or KIND_FLOOR not in targets:
            return space
        # A located-in text that names a whole FLOOR and nothing else ("Level 3") is a floor
        # reference, and is linked as one. Anything longer ("Level 3 riser cupboard") is not.
        if floor_number_in(text) is not None:
            return self._resolve_floor(text)
        floor = self._resolve_floor(text)
        return floor if floor.linked else space

    def _resolve_space(self, text: str) -> LinkOutcome:
        head = label_head(text)
        in_head = list(_DOTTED_ID_RE.finditer(head))
        reason_a = ""
        candidates: Tuple[str, ...] = ()
        if in_head:
            distinct = sorted({m.group(1) for m in in_head})
            if len(distinct) > 1:
                return _unlinked(f"names {len(distinct)} rooms ({', '.join(distinct)})")
            room = distinct[0]
            last = in_head[-1]
            before = _WORD_RE.findall(head[: last.start()].lower())
            point = next((w for w in before if w in _REFERENCE_POINT_WORDS), "")
            if head[last.end() :].strip():
                reason_a = f"names room {room} inside a longer description"
            elif point:
                reason_a = f"names room {room} as a reference point ('{point}'), not the location"
            else:
                candidates = self.space_ids.get(room, ())
                if len(candidates) == 1:
                    return LinkOutcome(
                        target=candidates[0],
                        target_kind=KIND_SPACE,
                        rule="dotted_id",
                        note=self._description_note(text, room, candidates[0]),
                    )
                if not candidates:
                    reason_a = f"no space in the building carries the id {room}"
                else:
                    reason_a = (
                        f"{len(candidates)} spaces carry the id {room} and the text matches "
                        f"none of their labels exactly"
                    )
        else:
            elsewhere = sorted({m.group(1) for m in _DOTTED_ID_RE.finditer(text)})
            if elsewhere:
                reason_a = f"names room {', '.join(elsewhere)} only in its description"

        matches = self.space_labels.get(normalise_label(text), ())
        if candidates:
            # An id several spaces carry is settled ONLY by an exact label among those same
            # spaces -- never by a label match somewhere else in the building.
            matches = tuple(m for m in matches if m in candidates)
        if len(matches) == 1:
            return LinkOutcome(target=matches[0], target_kind=KIND_SPACE, rule="label")
        if len(matches) > 1:
            return _unlinked(f"matches the label of {len(matches)} spaces")
        return _unlinked(reason_a or "matches no space's label exactly")

    def _resolve_floor(self, text: str) -> LinkOutcome:
        number = floor_number_in(text)
        if number is not None:
            floors = self.floor_numbers.get(number, ())
            if len(floors) == 1:
                return LinkOutcome(target=floors[0], target_kind=KIND_FLOOR, rule="floor_number")
            if floors:
                return _unlinked(f"{len(floors)} floors are numbered {number}")
            return _unlinked(f"no floor is numbered {number}")
        matches = self.floor_labels.get(normalise_label(text), ())
        if len(matches) == 1:
            return LinkOutcome(target=matches[0], target_kind=KIND_FLOOR, rule="floor_label")
        if matches:
            return _unlinked(f"matches the label of {len(matches)} floors")
        return _unlinked("names no floor number and matches no floor's label exactly")

    def _description_note(self, text: str, room: str, iri: str) -> str:
        """Say so when the record describes a room differently from the building's label."""
        said = _tail(text)
        known = [t for t in (_tail(label) for label in self.labels.get(iri, ())) if t]
        if not said or not known:
            return ""
        if normalise_label(said) in {normalise_label(t) for t in known}:
            return ""
        return f"the record calls room {room} '{said}'; the building calls it '{known[0]}'"


def _floor_number(levels: Set[int], names: List[str]) -> Optional[int]:
    """A floor's number: its declared rec:levelNumber, else the one number its names agree on."""
    if levels:
        return next(iter(levels)) if len(levels) == 1 else None
    found = {floor_number_in(strip_type_word(n)) for n in names} - {None}
    return next(iter(found)) if len(found) == 1 else None


def _add(index: Dict[str, List[str]], key: str, iri: str) -> None:
    if key and iri not in index.setdefault(key, []):
        index[key].append(iri)


def _cell(row: Dict[str, Any], key: str) -> str:
    """A row value whether it arrived plain (run_sparql_select) or as a SPARQL-JSON binding."""
    value = row.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    return str(value).strip() if value not in (None, "") else ""


def _local(iri: str, namespace: str) -> str:
    if namespace and iri.startswith(namespace):
        return iri[len(namespace) :]
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# ── loading from the graph ───────────────────────────────────────────────────────

#: Every space and floor the active building declares, with labels and any declared level
#: number. Spaces are brick:Space and its subclasses -- rooms, laboratories, common spaces --
#: and NOT zones: an HVAC zone shares a room's number in many buildings and is not the place a
#: record is located in.
PLACES_QUERY = """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rec:   <https://w3id.org/rec#>
SELECT DISTINCT ?place ?kind ?label ?level WHERE {
  {
    ?place a ?cls . ?cls rdfs:subClassOf* brick:Space .
    BIND("space" AS ?kind)
  } UNION {
    ?place a ?cls . ?cls rdfs:subClassOf* brick:Floor .
    BIND("floor" AS ?kind)
    OPTIONAL { ?place rec:levelNumber ?level }
  }
  OPTIONAL { ?place rdfs:label ?label }
  FILTER(STRSTARTS(STR(?place), "%(ns)s"))
}
LIMIT %(limit)d"""

#: Rows, not places. A building would need tens of thousands of labelled spaces to reach it,
#: and reaching it means the read may be incomplete -- see load_place_index.
MAX_PLACE_ROWS = 20000

RunSelect = Callable[..., Awaitable[Dict[str, Any]]]


async def load_place_index(
    namespace: str, run_select: RunSelect, limit: int = MAX_PLACE_ROWS
) -> Optional[PlaceIndex]:
    """The building's places, or None when linking must not be attempted.

    None -- never an empty index -- when the graph cannot be read, holds no space or floor, or
    returned as many rows as the limit allows. Each of those would make a link look unique
    when a second candidate was simply not read, and a lift that then wrote links would
    overwrite good ones on a degraded boot. None means "not attempted", and callers keep
    whatever the graph already holds.
    """
    if not namespace:
        return None
    escaped = namespace.replace("\\", "\\\\").replace('"', '\\"')
    try:
        res = await run_select(PLACES_QUERY % {"ns": escaped, "limit": limit}, limit=limit)
    except Exception as exc:
        logger.warning(f"[record_links] place index unavailable, no links this run: {exc}")
        return None
    if not isinstance(res, dict) or res.get("ok") is False:
        error = (res or {}).get("error") if isinstance(res, dict) else res
        logger.warning(f"[record_links] place index query failed, no links this run: {error}")
        return None
    rows = res.get("rows") or []
    if len(rows) >= limit:
        logger.warning(
            f"[record_links] place index hit its {limit}-row limit; a partial read could make "
            f"an ambiguous room look unique, so no links are written this run"
        )
        return None
    index = PlaceIndex.from_rows(namespace, rows)
    if not index.usable:
        logger.info("[record_links] the graph holds no space or floor yet; links not attempted")
        return None
    logger.info(
        f"[record_links] place index: {index.spaces} space(s), {index.floors} floor(s), "
        f"{len(index.space_ids)} room id(s), {len(index.floor_numbers)} numbered floor(s)"
    )
    return index


__all__ = [
    "FLOOR_PREDICATE",
    "KIND_FLOOR",
    "KIND_SPACE",
    "LINK_KINDS",
    "LINK_PREDICATES",
    "LINK_PREDICATE_IRIS",
    "LinkOutcome",
    "PLACES_QUERY",
    "PlaceIndex",
    "exclude_link_predicates",
    "floor_number_in",
    "link_predicate",
    "load_place_index",
    "normalise_label",
]
