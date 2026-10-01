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

from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

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


@dataclass
class DesignOccupancy:
    """Every design-occupancy figure the building declares for one space."""

    space_iri: str
    label: str
    #: predicate IRI -> declared count. More than one entry is normal; more than one VALUE
    #: is a contradiction the building has to resolve, not one this code may resolve for it.
    declarations: Dict[str, int] = field(default_factory=dict)

    @property
    def values(self) -> List[int]:
        return sorted(set(self.declarations.values()))

    @property
    def conflicted(self) -> bool:
        """Two declarations, two numbers. Neither is authoritative and neither is discarded."""
        return len(self.values) > 1

    @property
    def value(self) -> Optional[int]:
        """The declared figure — only when the building declares exactly one."""
        vals = self.values
        return vals[0] if len(vals) == 1 else None


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
    query = _ALL_QUERY.format(brick=_BRICK, rdfs=_RDFS, terms=_terms_for_sparql())
    try:
        payload = await sparql_exec(query)
    except Exception as exc:
        logger.warning(f"[design_occupancy] graph query failed: {exc}")
        return {}

    out: Dict[str, DesignOccupancy] = {}
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
        entry = out.setdefault(
            iri,
            DesignOccupancy(
                space_iri=iri,
                label=(row.get("label") or {}).get("value") or _local(iri),
            ),
        )
        entry.declarations[pred] = count
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
