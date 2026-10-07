# -*- coding: utf-8 -*-
"""What a space was DESIGNED to hold, read from the graph, beside what it actually holds (W3-04).

WHAT THE ROW ASKED FOR, AND WHY IT IS NOT WHAT WAS BUILT
--------------------------------------------------------
W3-04 says "``ontosage:designOccupancy`` on spaces". The building already declares design
occupancy, twice::

    <building>:maxOccupancy   29 spaces
    hbco:roomCapacity         19 spaces

Authoring a third term would have made the problem worse rather than solved it, which is
lesson #127 exactly. Nothing here authors anything; it READS whatever the active building
already declares.

THE FINDING THAT CHANGES THE ANSWER
-----------------------------------
Six spaces carry both properties and **three of the six disagree**::

    Room 1.04   maxOccupancy 50   roomCapacity 25
    Room 4.01   maxOccupancy 25   roomCapacity 20
    Room 5.01   maxOccupancy 25   roomCapacity 20

There is no basis in the graph for preferring either: ``ontosage:capacityBasis``, which would
say where a figure came from, is declared in no triple. So a resolver that picked one and
answered would be choosing by accident which of two numbers a fire-safety or booking question
is answered with. **A disagreement is reported as a disagreement.** "The building states two
different design occupancies for this room" is a true and useful answer; "the design occupancy
is 50" is a coin toss presented as a fact.

BUILDING-AGNOSTIC
-----------------
The predicate is DISCOVERED, never named. Any property whose local name normalises to one of
:data:`DESIGN_OCCUPANCY_TERMS`, carried by something the ontology types as a location, with a
numeric value, is a declaration of design occupancy. Measured against bldg1's live graph this
finds exactly the two above and correctly excludes ``capabilities:capacityLitres`` (a bin),
``capabilities:alternativeCapacity`` (a continuity note) and ``rec:capacity`` on the building
("about 500 people" — not numeric, and not a space).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from orchestrator.services.evidence.precedence import SourceClaim, resolve
from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

#: Where a capacity figure came from. Stored on a record as ``ontosage:capacitySource``.
#: ``ttl`` is the building's own model; ``drawing`` is the architect's drawing, read as a
#: second source. The values are the only vocabulary the reader recognises: anything else
#: is ignored, never guessed at.
CAPACITY_SOURCE_TTL = "ttl"
CAPACITY_SOURCE_DRAWING = "drawing"

#: THE AUTHORITY ORDER. Owner decision, binding, 2026-10-07: the TTL figure for a space is
#: authoritative whenever the TTL holds one; the drawing-derived figure is a SECOND source,
#: used only when the TTL has no figure for that space; otherwise the answer is "none". Never
#: an average, and never "the larger value". The order is a precedence tier pair: TTL is
#: ``authoritative``, a drawing is ``document_derived`` (a statement ABOUT the building, not the
#: model itself), and the two are never resolved together -- the drawing is consulted only
#: when the TTL verdict is empty.
_TIER_TTL = "authoritative"
_TIER_DRAWING = "document_derived"

#: Local names, normalised (lowercased, non-alphanumerics dropped), that declare how many
#: PEOPLE a space was designed for. Matched by EQUALITY, never by substring: `capacityLitres`
#: is a bin's volume and `alternativeCapacity` is a continuity note, and a substring match on
#: "capacity" would report a 1,100-litre bin as a room for 1,100 people.
DESIGN_OCCUPANCY_TERMS = frozenset(
    {
        "designoccupancy",
        "maxoccupancy",
        "maximumoccupancy",
        "occupantcapacity",
        "occupancycapacity",
        "roomcapacity",
        "seatingcapacity",
        "seatcapacity",
        "personcapacity",
        "peoplecapacity",
        "capacity",
    }
)

_BRICK = "https://brickschema.org/schema/Brick#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

#: Enough of a room name to match on: "1.25", "Room 1.25", "room1.25".
_SPACE_TOKEN_RE = re.compile(r"\b(?:room|space|zone)?\s*0*(\d{1,2}[.\-]\d{1,3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class CapacityAuthority:
    """The one figure a space is answered with, and where it came from."""

    #: The authoritative count, or None when there is none or the sources disagree.
    value: Optional[int]
    #: ``CAPACITY_SOURCE_TTL``, ``CAPACITY_SOURCE_DRAWING``, or "" when neither has a figure.
    source: str
    #: Two sources at the deciding tier state different figures and no supersedes link says
    #: which is current. Reported, never picked.
    unresolved: bool = False
    note: str = ""


def authoritative_capacity(
    ttl: Dict[str, int],
    drawing: Dict[str, int],
    supersedes: Optional[Dict[str, str]] = None,
) -> CapacityAuthority:
    """TTL first, then the drawing, then none (owner decision 2026-10-07).

    ``ttl`` and ``drawing`` map a record key to its count; ``supersedes`` maps a key to the key
    it replaces. A superseded TTL record is retained for the audit trail and does not count
    as a disagreement once its successor is in place. Keys are compared by identity only, so
    a value is never looked up by the room it sits in.
    """
    supersedes = supersedes or {}
    if ttl:
        return _settle(CAPACITY_SOURCE_TTL, ttl, supersedes, _TIER_TTL)
    if drawing:
        return _settle(CAPACITY_SOURCE_DRAWING, drawing, {}, _TIER_DRAWING)
    return CapacityAuthority(value=None, source="")


def _settle(
    source: str, figures: Dict[str, int], supersedes: Dict[str, str], tier: str
) -> CapacityAuthority:
    # Sorted by key so the verdict's wording cannot depend on the order the graph returned rows.
    claims = [
        SourceClaim(
            source_id=key,
            tier=tier,
            value=float(count),
            label=_local(key),
            supersedes=supersedes.get(key, ""),
        )
        for key, count in sorted(figures.items())
    ]
    verdict = resolve(claims)
    winner = verdict.winner
    if winner is None:
        return CapacityAuthority(value=None, source="")
    # Every disagreeing claim must be one the winner explicitly supersedes. A third figure
    # with no link to the winner is a real disagreement, whatever tiebreak the winner got.
    stray = [
        c for c in verdict.tied_with if c.value != winner.value and c.source_id != winner.supersedes
    ]
    if verdict.tiebreak == "unresolved" or stray:
        return CapacityAuthority(
            value=None, source=source, unresolved=True, note=verdict.describe()
        )
    return CapacityAuthority(value=int(winner.value), source=source)


@dataclass
class DesignOccupancy:
    """Every design-occupancy figure the building declares for one space."""

    space_iri: str
    label: str
    #: record key -> count, from the building's own TTL. Keys are the predicate IRI for a
    #: figure on the space itself, and the record IRI for a retained capacity record. More
    #: than one entry is normal; more than one VALUE is a contradiction the building has to
    #: resolve, unless a supersedes link says which record is current.
    declarations: Dict[str, int] = field(default_factory=dict)
    #: record key -> count, from an architect's drawing. Read only when ``declarations`` is
    #: empty (the owner's order: TTL first, drawing second).
    drawing: Dict[str, int] = field(default_factory=dict)
    #: superseding record key -> the record key it replaces.
    supersedes: Dict[str, str] = field(default_factory=dict)

    @property
    def authority(self) -> CapacityAuthority:
        return authoritative_capacity(self.declarations, self.drawing, self.supersedes)

    @property
    def source(self) -> str:
        """Which source the answer rests on: ``ttl``, ``drawing`` or "" for none."""
        return self.authority.source

    @property
    def active_declarations(self) -> Dict[str, int]:
        """The figures of the source in use (TTL when it has any, else the drawing). Includes
        superseded TTL records, so use it to describe a conflict, never to state a value."""
        return self.declarations or self.drawing

    @property
    def values(self) -> List[int]:
        """The figures a reader may see. One authoritative figure when there is one; every
        figure of the source in use when the sources disagree, so a conflicted space can be
        described in full. A superseded record never appears here as a live value."""
        if not self.conflicted and self.value is not None:
            return [self.value]
        return sorted(set(self.active_declarations.values()))

    @property
    def conflicted(self) -> bool:
        """The TTL holds figures that disagree and nothing says which is current."""
        return self.authority.unresolved

    @property
    def value(self) -> Optional[int]:
        """The authoritative figure, or None when there is none or it is unresolved."""
        return self.authority.value


def _local(iri: str) -> str:
    text = str(iri or "")
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


def _normalise(iri: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _local(iri).lower())


def is_design_occupancy_predicate(iri: str) -> bool:
    """Does this property declare how many people a space was designed for?"""
    return _normalise(iri) in DESIGN_OCCUPANCY_TERMS


def _terms_for_sparql() -> str:
    return ", ".join(f'"{t}"' for t in sorted(DESIGN_OCCUPANCY_TERMS))


#: One query for the whole building. Filtering in SPARQL rather than in Python keeps the
#: predicate list off the wire and means a building with thousands of spaces costs one round
#: trip. The subject must be typed as a location, so a numeric "capacity" on a bin, a switch
#: or a policy never reaches the answer.
_ALL_QUERY = """
PREFIX brick: <{brick}>
PREFIX rdfs: <{rdfs}>
SELECT ?space ?label ?p ?v WHERE {{
  ?space ?p ?v .
  FILTER(isNumeric(?v))
  ?space a ?t . ?t rdfs:subClassOf* brick:Location .
  BIND(REPLACE(LCASE(REPLACE(STR(?p), "^.*[#/]", "")), "[^a-z0-9]", "") AS ?norm)
  FILTER(?norm IN ({terms}))
  OPTIONAL {{ ?space rdfs:label ?label }}
}}
"""


#: The retained capacity RECORDS for a space: a record that points at a location with
#: ``rdfs:seeAlso`` and says which source it came from. Records are not typed as locations,
#: so `_ALL_QUERY` never sees them; they are read here and nowhere else.
_RECORDS_QUERY = """
PREFIX brick: <{brick}>
PREFIX rdfs: <{rdfs}>
PREFIX ontosage: <{onto}>
SELECT ?space ?rec ?label ?p ?v ?src ?sup WHERE {{
  ?rec rdfs:seeAlso ?space .
  ?space a ?t . ?t rdfs:subClassOf* brick:Location .
  ?rec ?p ?v .
  FILTER(isNumeric(?v))
  BIND(REPLACE(LCASE(REPLACE(STR(?p), "^.*[#/]", "")), "[^a-z0-9]", "") AS ?norm)
  FILTER(?norm IN ({terms}))
  ?rec ontosage:capacitySource ?src .
  OPTIONAL {{ ?rec ontosage:supersedes ?sup }}
  OPTIONAL {{ ?space rdfs:label ?label }}
}}
"""

_ONTOSAGE = "http://ontosage.org/capabilities#"


def _bindings(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, dict):
        return []
    rows = results.get("bindings")
    return rows if isinstance(rows, list) else []


async def declared_design_occupancy(sparql_exec: SparqlExec) -> Dict[str, DesignOccupancy]:
    """``{space IRI: DesignOccupancy}`` for every space the building gives a figure for.

    Returns an EMPTY map when the query fails. Callers must treat that as "not known", never as
    "no space has a declared occupancy" — an unreachable graph and a building that declares
    nothing must not produce the same answer.
    """
    terms = _terms_for_sparql()
    figures_q = _ALL_QUERY.format(brick=_BRICK, rdfs=_RDFS, terms=terms)
    records_q = _RECORDS_QUERY.format(brick=_BRICK, rdfs=_RDFS, onto=_ONTOSAGE, terms=terms)
    try:
        payload = await sparql_exec(figures_q)
        records = await sparql_exec(records_q)
    except Exception as exc:
        logger.warning(f"[design_occupancy] graph query failed: {exc}")
        return {}

    out: Dict[str, DesignOccupancy] = {}

    def _entry(iri: str, label: str) -> DesignOccupancy:
        return out.setdefault(
            iri,
            DesignOccupancy(space_iri=iri, label=label or _local(iri)),
        )

    for row in _bindings(payload):
        iri = (row.get("space") or {}).get("value") or ""
        pred = (row.get("p") or {}).get("value") or ""
        raw = (row.get("v") or {}).get("value")
        if not iri or not pred or raw is None:
            continue
        try:
            count = int(float(raw))
        except (TypeError, ValueError):
            continue
        label = (row.get("label") or {}).get("value") or ""
        _entry(iri, label).declarations[pred] = count

    for row in _bindings(records):
        iri = (row.get("space") or {}).get("value") or ""
        rec = (row.get("rec") or {}).get("value") or ""
        src = (row.get("src") or {}).get("value") or ""
        raw = (row.get("v") or {}).get("value")
        if (
            not iri
            or not rec
            or raw is None
            or src
            not in (
                CAPACITY_SOURCE_TTL,
                CAPACITY_SOURCE_DRAWING,
            )
        ):
            continue
        try:
            count = int(float(raw))
        except (TypeError, ValueError):
            continue
        label = (row.get("label") or {}).get("value") or ""
        entry = _entry(iri, label)
        bucket = entry.declarations if src == CAPACITY_SOURCE_TTL else entry.drawing
        bucket[rec] = count
        superseded = (row.get("sup") or {}).get("value") or ""
        if superseded and src == CAPACITY_SOURCE_TTL:
            entry.supersedes[rec] = superseded
    return out


def _space_key(text: str) -> str:
    """The room number inside a label or a question, normalised. '' when there is none."""
    match = _SPACE_TOKEN_RE.search(str(text or ""))
    return match.group(1).replace("-", ".") if match else ""


def match_space(named: str, declared: Dict[str, DesignOccupancy]) -> Optional[DesignOccupancy]:
    """The declared space a question names, or None.

    Matched on the room NUMBER rather than on the whole label, because the question says
    "room 1.25" and the graph says "Room 1.25 — Conference/Seminar Room". Never matched
    fuzzily: naming a space the building does not declare must produce nothing, so the caller
    can say the figure is not recorded instead of answering about the nearest room.
    """
    key = _space_key(named)
    if not key:
        return None
    for entry in declared.values():
        if _space_key(entry.label) == key or _space_key(_local(entry.space_iri)) == key:
            return entry
    return None


async def design_occupancy_for(named: str, sparql_exec: SparqlExec) -> Optional[DesignOccupancy]:
    """The declared design occupancy of the space a question names, or None."""
    if not _space_key(named):
        return None
    return match_space(named, await declared_design_occupancy(sparql_exec))


#: An occupancy question about a NAMED space. The design figure is only ever offered beside a
#: count of people in a particular room: "how busy is the building" has no single declared
#: capacity to be compared against, and offering one room's would be an answer to a question
#: nobody asked.
_OCCUPANCY_WORD_RE = re.compile(
    r"\b(?:occupanc\w*|occupied|occupants?|headcount|people|persons?|"
    r"capacity|seats?|seating|full|over[- ]?crowd\w*)\b",
    re.IGNORECASE,
)


def is_design_occupancy_question(text: str) -> bool:
    """True when a question asks about people in a space the building names."""
    return bool(_OCCUPANCY_WORD_RE.search(text or "")) and bool(_space_key(text))


def describe_design(design: Optional[DesignOccupancy]) -> str:
    """One sentence about what the building says the space was designed to hold."""
    if design is None:
        return ""
    if design.conflicted:
        parts = ", ".join(
            f"{count} under {_local(pred)}"
            for pred, count in sorted(design.declarations.items(), key=lambda kv: -kv[1])
        )
        return (
            f"{design.label} has no single design occupancy on record: the building states "
            f"{parts}. Nothing in the model says which is authoritative, so I will not pick one."
        )
    if design.value is None:
        return ""
    if design.source == CAPACITY_SOURCE_DRAWING:
        return (
            f"{design.label} has a design occupancy of {design.value} people, taken from the "
            "architect's drawing; the building model holds no figure for it."
        )
    return f"{design.label} has a design occupancy of {design.value} people."


def compare_observed_with_design(
    observed: Optional[float],
    design: Optional[DesignOccupancy],
    observed_basis: str = "the latest reading",
) -> str:
    """Observed against design, with BOTH numbers and the arithmetic done here.

    The comparison is computed rather than narrated. BUG-885 is the reason: left to the
    wording, a 0.06 degree gap was twice asserted in bold as a difference. A percentage of a
    declared capacity is the same kind of claim and gets the same treatment.
    """
    if design is None:
        return (
            "The building records no design occupancy for that space, so I cannot compare the "
            "count against one. That is a gap in the building model, not a count of zero."
        )
    if observed is None:
        return describe_design(design) + " I have no occupancy reading to compare it against."
    if design.conflicted:
        spread = ", ".join(
            f"{count} ({_local(pred)})"
            for pred, count in sorted(design.declarations.items(), key=lambda kv: -kv[1])
        )
        lo, hi = design.values[0], design.values[-1]
        verdict = (
            "over every figure on record"
            if observed > hi
            else (
                "within every figure on record"
                if observed <= lo
                else "over one of them and within the other"
            )
        )
        return (
            f"{observed:g} people observed ({observed_basis}) against a design occupancy the "
            f"building states two ways — {spread}. The count is {verdict}. Which figure applies "
            f"is a question for whoever maintains the building model; I will not choose for it."
        )
    limit = design.value or 0
    share = (observed / limit * 100.0) if limit else None
    if limit and observed > limit:
        head = f"Over its design occupancy: {observed:g} people against {limit}"
    elif limit:
        head = f"Within its design occupancy: {observed:g} people against {limit}"
    else:
        head = f"{observed:g} people observed; the declared design occupancy is {limit}"
    tail = f" ({share:.0f}% of capacity)" if share is not None else ""
    return f"{head}{tail}, {observed_basis} for {design.label}."
