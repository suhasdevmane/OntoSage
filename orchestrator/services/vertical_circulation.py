# -*- coding: utf-8 -*-
"""Lifts and staircases the ONTOLOGY declares but the floor plans do not draw (CAVEAT-313).

Measured on bldg1's live route graph: 344 nodes across 6 floors, twelve space
types, and **zero** typed ``lift`` or ``staircase``. No node label mentions a lift
either. Cross-floor edges therefore numbered four in the whole building, and a
route from floor 0 to floor 3 returned nothing — with or without the step-free
requirement.

The graph knows better. It holds one ``ontosage:Lift`` ("Main passenger lift") and
two ``brick:Staircase``. The floor-plan pipeline simply never typed the shafts,
and the route finder can only see what the manifests say.

So this reads the declared cores out of the ontology and hands them to the route
finder, which attaches one node per served floor. **The position is not known and
is not invented**: a DWG that does not draw the shaft gives no coordinate to be
near. The attachment point is the floor's best-connected space — a graph-theoretic
stand-in for a lift lobby, derived from the building's own adjacency rather than
from a guessed coordinate — and every route that uses one is labelled approximate.

An approximate route beats no route here, but only if the reader is told which it
is. A route that silently invented a lift position would be the more confident
kind of wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: Classes that mean "this connects floors". ontosage:Lift is this project's own
#: term; the Brick spellings are here because a building onboarded from someone
#: else's export will use those and must work unchanged.
_LIFT_CLASSES = ("ontosage:Lift", "brick:Elevator")
_STAIR_CLASSES = ("brick:Staircase", "brick:Stairwell", "ontosage:Staircase")


@dataclass
class VerticalCore:
    """One shaft: a lift or a staircase, and the floors it serves."""

    entity_id: str
    label: str
    kind: str  # 'lift' | 'staircase' — matches route_finder's space types
    floors: List[int] = field(default_factory=list)
    #: True when the floors were assumed rather than declared. A lift that names no
    #: floors is assumed to serve all of them, which is usually right and is never
    #: reported as though the building had said so.
    floors_assumed: bool = False


def _query(namespace: str) -> str:
    lifts = " ".join(f"{{ ?c a {cls} }} UNION" for cls in _LIFT_CLASSES)
    stairs = " ".join(f"{{ ?c a {cls} }} UNION" for cls in _STAIR_CLASSES)
    both = (lifts + " " + stairs).rstrip("UNION ").strip()
    return (
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
        "SELECT ?c ?label ?type ?floor WHERE {\n"
        f"  {both}\n"
        "  ?c a ?type .\n"
        "  OPTIONAL { ?c rdfs:label ?label }\n"
        "  OPTIONAL { { ?c brick:isPartOf ?floor } UNION { ?floor brick:hasPart ?c } }\n"
        f'  FILTER(STRSTARTS(STR(?c), "{namespace}"))\n'
        "} LIMIT 200"
    )


def _kind_for(type_iri: str) -> str:
    local = str(type_iri or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
    if local in {"lift", "elevator"}:
        return "lift"
    if local in {"staircase", "stairwell"}:
        return "staircase"
    return ""


def _floor_number(iri_or_label: str) -> Optional[int]:
    """The storey a floor IRI names, or None when it cannot be read.

    Deliberately strict: a floor reference this cannot parse yields None and the
    core falls back to serving every floor, which is stated as an assumption. The
    alternative — picking a plausible number out of an unparseable string — is how
    a route ends up claiming a lift stops somewhere it does not.
    """
    import re

    s = str(iri_or_label or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    m = re.search(r"(-?\d+)\s*$", s)
    return int(m.group(1)) if m else None


def cores_from_rows(rows: Sequence[Any]) -> List[VerticalCore]:
    """Group SPARQL rows into one VerticalCore per shaft. Pure."""
    by_id: dict = {}
    for row in rows or []:
        get = row.get if isinstance(row, dict) else lambda k: getattr(row, k, None)
        cid = str(get("c") or "")
        if not cid:
            continue
        kind = _kind_for(str(get("type") or ""))
        if not kind:
            continue
        core = by_id.setdefault(
            cid,
            VerticalCore(
                entity_id=cid,
                label=str(get("label") or cid.rsplit("#", 1)[-1]),
                kind=kind,
            ),
        )
        n = _floor_number(str(get("floor") or ""))
        if n is not None and n not in core.floors:
            core.floors.append(n)
    for core in by_id.values():
        core.floors.sort()
    return sorted(by_id.values(), key=lambda c: c.entity_id)


def with_assumed_floors(cores: Sequence[VerticalCore], all_floors: Sequence[int]):
    """Cores that declared no floors are assumed to serve every floor there is.

    A passenger lift that names no storeys almost always serves them all, and the
    alternative is a lift that connects nothing. The assumption is recorded on the
    core so an answer can disclose it rather than presenting it as declared.
    """
    floors = sorted(set(int(f) for f in all_floors))
    out = []
    for c in cores:
        if c.floors:
            out.append(c)
            continue
        out.append(
            VerticalCore(
                entity_id=c.entity_id,
                label=c.label,
                kind=c.kind,
                floors=list(floors),
                floors_assumed=True,
            )
        )
    return out


async def declared_cores(
    namespace: str,
    run_select: Callable[..., Any],
    all_floors: Sequence[int] = (),
) -> List[VerticalCore]:
    """Vertical circulation this building declares. [] on any failure — never raises.

    A routing answer must degrade to the plans-only behaviour it had, not break,
    when the graph is unreachable.
    """
    try:
        res = await run_select(_query(namespace))
    except Exception as exc:
        logger.debug(f"[vertical] core lookup failed: {exc}")
        return []
    rows = res.get("rows") if isinstance(res, dict) else res
    if not rows:
        return []
    cores = cores_from_rows(rows)
    if all_floors:
        cores = with_assumed_floors(cores, all_floors)
    logger.info(
        f"[vertical] {len(cores)} declared core(s): "
        + ", ".join(f"{c.label} ({c.kind}, {len(c.floors)} floors)" for c in cores[:4])
    )
    return cores
