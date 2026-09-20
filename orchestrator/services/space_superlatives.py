# -*- coding: utf-8 -*-
"""'What is the biggest room?' is answered with the biggest rooms, not the whole table (BUG-827).

WHAT WENT WRONG
---------------
    "What's the biggest room in the building?"
      -> "## All spaces -- 354 space(s) found:" and a 354-row table in floor order.

The spatial lane had a size FILTER ("rooms larger than 50 m2") and a per-room lookup ("how big is
room 3.01"), and no superlative, so the question fell through every branch to the default listing.
Nothing in that table is false; the reader was left to sort 354 rows by eye and the answer to the
question was somewhere inside it.

WHAT THIS DOES
--------------
Reads the superlative and the kind of space it is about from the question, ranks the spaces the floor
plans give an area for, and reports the top three. It says how many spaces were ranked and how many
the plans hold no area for, because a space with no recorded area cannot be ranked and might be the
biggest -- "the biggest room" is only ever "the biggest room the plans measure".

No LLM, no threshold: this is arithmetic over the floor-plan manifests, so the same question gives
the same answer twice.

Drawing artefacts are not rooms. A DWG text label ("\\A1;1622.88 m{\\H0.7x;...}") is stored as a
space with no area; it is excluded from the count of unranked spaces so it cannot inflate it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from orchestrator.services.amenity_floor_answer import floor_in_question
from shared.utils import get_logger

logger = get_logger(__name__)

#: How many spaces an answer names.
TOP_N = 3

_LARGEST = re.compile(r"\b(?:biggest|largest|most\s+spacious|greatest\s+floor\s+area)\b", re.I)
_SMALLEST = re.compile(r"\b(?:smallest|tiniest|least\s+spacious|littlest)\b", re.I)

#: A superlative is about space only when it sits beside a noun for one. "The biggest energy user"
#: names no room and is not this module's question.
_SPACE_NOUN = re.compile(
    r"\b(?:rooms?|spaces?|zones?|labs?|laborator(?:y|ies)|offices?|halls?|areas?|theatres?"
    r"|theaters?|classrooms?|kitchens?|lobbys?|atriums?|studios?|workshops?)\b",
    re.I,
)

#: A question about a room's state or booking, not its size. "The biggest room I can book on
#: Friday" is not answered by the biggest room the plans measure, whether or not it is free.
_STATE_OR_BOOKING = re.compile(
    r"\b(?:book\w*|reserv\w*|availab\w*|free|vacant|empty|occupied|busy|now|today|tomorrow"
    r"|tonight|currently|hire|rent\w*|cost\w*|cheap\w*)\b",
    re.I,
)

#: A drawing's own text objects are stored as spaces. Backslash codes and braces are DWG markup.
_DRAWING_MARKUP = re.compile(r"[\\{}]")
_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class SuperlativeAsk:
    """What a superlative question asks for."""

    largest: bool
    floor: Optional[int] = None
    space_type: Optional[str] = None
    #: The question's own noun ("room", "office"), so the answer repeats the word that was used.
    noun: str = "room"

    @property
    def word(self) -> str:
        return "largest" if self.largest else "smallest"


@dataclass(frozen=True)
class RankedSpace:
    """One ranked space, with the floor it is on and its measured area."""

    zone_id: str
    label: str
    floor: int
    area_m2: float
    space_type: str = ""
    ontology_iri: str = ""


def parse_superlative(question: str, space_type: Optional[str] = None) -> Optional[SuperlativeAsk]:
    """The ask, when the question is a biggest/smallest question about spaces; None otherwise."""
    q = question or ""
    big, small = _LARGEST.search(q), _SMALLEST.search(q)
    noun = _SPACE_NOUN.search(q)
    if not (big or small) or not noun or _STATE_OR_BOOKING.search(q):
        return None
    if big and small:
        # "the biggest and smallest room" is two questions; answering one would drop the other.
        return None
    return SuperlativeAsk(
        largest=bool(big),
        floor=floor_in_question(q),
        space_type=space_type,
        noun=_singular(noun.group(0).lower()),
    )


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _is_room_like(space: Any) -> bool:
    label = str(getattr(space, "label", "") or "")
    return not _DRAWING_MARKUP.search(label)


def rank_spaces(manifests: Sequence[Any], ask: SuperlativeAsk) -> Dict[str, Any]:
    """Rank the measurable spaces; returns the top of the ranking and how many were considered.

    Keys: `top` (List[RankedSpace]), `ranked` (int), `unmeasured` (int, spaces in scope that the
    plans give no area for).
    """
    measured: List[RankedSpace] = []
    unmeasured = 0
    for m in manifests or []:
        try:
            floor = int(getattr(m, "floor"))
        except (TypeError, ValueError):
            continue
        if ask.floor is not None and floor != ask.floor:
            continue
        for s in getattr(m, "spaces", []) or []:
            if not _is_room_like(s):
                continue
            stype = str(getattr(s, "type", "") or "")
            if ask.space_type and stype != ask.space_type:
                continue
            area = getattr(s, "area_m2", None)
            if not area or area <= 0:
                unmeasured += 1
                continue
            measured.append(
                RankedSpace(
                    zone_id=str(getattr(s, "zone_id", "") or ""),
                    label=str(getattr(s, "label", "") or ""),
                    floor=floor,
                    area_m2=float(area),
                    space_type=stype,
                    ontology_iri=str(getattr(s, "ontology_iri", "") or ""),
                )
            )
    # The same room can be drawn twice (a room and its label object); keep its measured polygon once.
    seen: Dict[tuple, RankedSpace] = {}
    for r in measured:
        seen.setdefault((r.floor, r.zone_id), r)
    unique = list(seen.values())
    unique.sort(key=lambda r: (-r.area_m2 if ask.largest else r.area_m2, r.floor, r.zone_id))
    return {"top": unique[:TOP_N], "ranked": len(unique), "unmeasured": unmeasured}


_SAFE_IRI = re.compile(r"^https?://[^\s<>\"{}|\\^`]+$")


async def graph_labels(iris: Sequence[str], sparql_exec: Optional[Any] = None) -> Dict[str, str]:
    """{iri: rdfs:label} for the given rooms; {} when there are none or the graph is unreachable.

    The IRIs come from the floor-plan manifests, not from the user, and are checked anyway before
    they are placed in a query.
    """
    safe = [i for i in dict.fromkeys(iris) if i and _SAFE_IRI.match(i)]
    if not safe:
        return {}
    try:
        if sparql_exec is None:
            from orchestrator.services.deliberation.live import sparql_exec as live_exec

            sparql_exec = live_exec
        values = " ".join(f"<{i}>" for i in safe)
        data = await sparql_exec(
            "SELECT ?r ?l WHERE { VALUES ?r { " + values + " } "
            "?r <http://www.w3.org/2000/01/rdf-schema#label> ?l }"
        )
    except Exception as exc:
        logger.debug(f"[space_superlatives] labels unavailable: {exc}")
        return {}
    out: Dict[str, str] = {}
    for b in (data or {}).get("results", {}).get("bindings", []):
        out.setdefault(b.get("r", {}).get("value", ""), b.get("l", {}).get("value", ""))
    return {k: v for k, v in out.items() if k and v}


def display_name(space: RankedSpace, graph_label: str = "") -> str:
    """The building's own name for the room when the graph has one, else the plan's label."""
    if graph_label:
        return graph_label
    if _BARE_NUMBER.match(space.label.strip()):
        return f"Room {space.label.strip()}"
    return space.label or f"Room {space.zone_id}"


def _kind_and_where(ask: SuperlativeAsk) -> tuple:
    kind = (ask.space_type or ask.noun or "room").replace("_", " ")
    where = f"on floor {ask.floor}" if ask.floor is not None else "in the building"
    return kind, where


def render(
    ask: SuperlativeAsk, ranking: Dict[str, Any], names: Optional[Dict[str, str]] = None
) -> str:
    """The answer: the winner in one line, the top three, and what could not be ranked."""
    names = names or {}
    top: List[RankedSpace] = ranking.get("top") or []
    kind, where = _kind_and_where(ask)
    if not top:
        return (
            f"**I cannot say which {kind} {where} is the {ask.word}.** The floor plans give no "
            f"measured area for any {kind} {where}, and I will not estimate one."
        )
    lead = top[0]
    lead_name = display_name(lead, names.get(lead.ontology_iri, ""))
    lines = [
        f"**The {ask.word} {kind} {where} by floor-plan area is {lead_name}** — "
        f"{lead.area_m2:,.1f} m² (floor {lead.floor})."
    ]
    if len(top) > 1:
        lines.append(f"\nThe {ask.word} {len(top)}:")
        for i, r in enumerate(top, 1):
            nm = display_name(r, names.get(r.ontology_iri, ""))
            lines.append(f"{i}. {nm} — {r.area_m2:,.1f} m² (floor {r.floor})")
    ranked, unmeasured = int(ranking.get("ranked", 0)), int(ranking.get("unmeasured", 0))
    tail = f"\n_Ranked from the {ranked} spaces the floor plans give an area for"
    if unmeasured:
        direction = "larger" if ask.largest else "smaller"
        if unmeasured == 1:
            tail += (
                f"; 1 more has no area recorded, so it could not be ranked and may be {direction}"
            )
        else:
            tail += (
                f"; {unmeasured} more have no area recorded, so they could not be ranked and may "
                f"be {direction}"
            )
    lines.append(tail + "._")
    return "\n".join(lines)
