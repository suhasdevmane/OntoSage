# -*- coding: utf-8 -*-
"""Fetch the facts the spatial-adequacy classifier needs (V6-T13's missing half).

`spatial_adequacy.classify()` was written pure and unit-tested, and nothing ever called it —
because nothing fetched a :class:`PointFacts`. Every evidence source therefore carried the
default grade ``NONE``, the spatial gate would have failed every answer in the building, and
so it was left unwired (BUG-237). This module is the missing half: graph access, deliberately
kept out of the decision logic so that logic stays replayable in a fixture.

**What the building actually declares**, measured before writing any of this rather than
assumed:

    hasLocation            3304     the containing space — the workhorse
    isPointOf               638
    hasPart / isPartOf      637     gives siblings through a shared parent
    feeds                    85     zone service
    environmentalBoundary     0     absent
    zoneValidated             0     absent

The two absent ones are the two that could *strengthen* a grade — `environmentalBoundary`
declares what a sensor really measures, and `zoneValidated` is the only thing that turns zone
service into coverage rather than proximity. With neither present the classifier can reach
IN_ROOM (containment) and PROXY, and can never claim SERVED_ZONE. That is the conservative
direction, and it is the correct one to be wrong in: a building that has not validated its
zones has not earned the right to answer for a room from a zone.

**One query, not one per point.** A building with thousands of streams would otherwise issue
thousands of round trips per answer. Everything below is a single SELECT with OPTIONALs.

**Never geometric.** No distance, no nearest-neighbour, nothing that would let proximity imply
attribution — that is how BUG-189 attributed one room's reading to a corridor the building did
not have.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from orchestrator.services.evidence.spatial_adequacy import PointFacts
from shared.utils import get_logger

logger = get_logger(__name__)

_PREFIXES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
    "PREFIX ontosage: <http://ontosage.org/schema#>\n"
)

#: Ceiling on how many streams one answer's spatial check will consider. An answer resting on
#: more points than this is a building-wide aggregate, where a room-level adequacy grade is not
#: the right question anyway.
MAX_POINTS = 60


def _esc(text: str) -> str:
    """Escape a literal for SPARQL. Values here come from resolved entities, not raw user
    input, but a stray quote would still turn a query into a syntax error at answer time."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


async def resolve_space_iri(name: str, namespace: str, run_select) -> str:
    """The IRI of the space a question named, or "" when it cannot be resolved.

    Matches on local name or ``rdfs:label``, case-insensitively — the same basis
    ``referent_resolver`` uses, on purpose. Two different definitions of "does this building
    have a space called X" is the drift shape this codebase keeps paying for.

    Returns "" rather than guessing when several spaces match: an ambiguous referent graded
    against an arbitrary one of them would produce a confident grade about the wrong room.
    """
    token = (name or "").strip().lower()
    if not token or not namespace:
        return ""
    q = (
        _PREFIXES + "SELECT DISTINCT ?s WHERE {\n"
        "  ?s a ?cls .\n"
        "  ?cls rdfs:subClassOf* brick:Location .\n"
        "  OPTIONAL { ?s rdfs:label ?l }\n"
        f'  FILTER(STRSTARTS(STR(?s), "{_esc(namespace)}"))\n'
        f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
        f'  FILTER(CONTAINS(?local, "{_esc(token)}") '
        f'|| CONTAINS(LCASE(COALESCE(STR(?l), "")), "{_esc(token)}"))\n'
        "} LIMIT 5"
    )
    try:
        res = await run_select(q, limit=5)
    except Exception as exc:
        logger.debug(f"[spatial_facts] space resolution failed: {exc}")
        return ""
    rows = (res or {}).get("rows") or []
    iris = [r.get("s") for r in rows if r.get("s")]
    if len(iris) != 1:
        # 0 = the building has no such space; >1 = ambiguous. Both are honestly "unknown",
        # and the gate treats an unresolved target as "no space was resolved" rather than
        # grading against a coin flip.
        return ""
    return str(iris[0])


async def facts_for_uuids(
    uuids: Sequence[str], namespace: str, run_select, target: str = ""
) -> Dict[str, PointFacts]:
    """``{timeseries uuid: PointFacts}`` for the points behind an answer.

    Keyed by uuid because that is what the data lanes carry; the point IRI is an internal
    hop. One query for the whole set.
    """
    ids = [str(u) for u in (uuids or []) if u][:MAX_POINTS]
    if not ids or not namespace:
        return {}
    values = " ".join(f'"{_esc(u)}"' for u in ids)
    q = (
        _PREFIXES + "SELECT ?uuid ?point ?loc ?boundary ?zoneSpace ?zv ?sibling WHERE {\n"
        f"  VALUES ?uuid {{ {values} }}\n"
        "  ?extref ref:hasTimeseriesId ?uuid .\n"
        "  ?point ref:hasExternalReference ?extref .\n"
        "  OPTIONAL { ?point ontosage:environmentalBoundary ?boundary }\n"
        "  OPTIONAL { ?point brick:hasLocation ?loc }\n"
        "  OPTIONAL { ?point brick:isPointOf ?loc }\n"
        # Zone service: the equipment/zone this point belongs to, and what that zone feeds.
        # Nothing here checks validation, because no building in this repo declares it — so
        # every space reached this way is reported as UNVALIDATED, i.e. proxy.
        "  OPTIONAL { ?point brick:isPointOf ?zone . ?zone brick:feeds ?zoneSpace .\n"
        "             OPTIONAL { ?zone ontosage:zoneValidated ?zv } }\n"
        # Siblings: spaces sharing the point's own parent. Structural, not geometric.
        "  OPTIONAL { ?point brick:hasLocation ?own . ?parent brick:hasPart ?own ;\n"
        "             brick:hasPart ?sibling . FILTER(?sibling != ?own) }\n"
        "}"
    )
    try:
        res = await run_select(q, limit=4000)
    except Exception as exc:
        logger.debug(f"[spatial_facts] point facts query failed: {exc}")
        return {}
    if not (res or {}).get("ok", True):
        return {}

    acc: Dict[str, Dict[str, object]] = {}
    for row in (res or {}).get("rows") or []:
        uid = row.get("uuid")
        if not uid:
            continue
        e = acc.setdefault(
            str(uid),
            {
                "point": "",
                "locs": set(),
                "boundary": None,
                "zone": set(),
                "vzone": set(),
                "sib": set(),
            },
        )
        e["point"] = e["point"] or str(row.get("point") or "")
        if row.get("loc"):
            # A point can carry SEVERAL asserted locations (bldg1's native sensors declare
            # both a room-zone and a floor-wing). Keep them all: first-wins made the grade
            # depend on SPARQL row order, which is not a fact about the building.
            e["locs"].add(str(row["loc"]))  # type: ignore[union-attr]
        if row.get("boundary") and not e["boundary"]:
            e["boundary"] = str(row["boundary"])
        if row.get("zoneSpace"):
            # Validated only on an EXPLICIT zoneValidated=true. Absent is unvalidated --
            # upgrading proximity to coverage on an assertion nobody made is the
            # substitution this module exists to prevent.
            zv = str(row.get("zv") or "").lower() in ("true", "1")
            e["vzone" if zv else "zone"].add(str(row["zoneSpace"]))  # type: ignore[union-attr]
        if row.get("sibling"):
            e["sib"].add(str(row["sibling"]))  # type: ignore[union-attr]

    out: Dict[str, PointFacts] = {}
    for uid, e in acc.items():
        locs = sorted(e["locs"])  # type: ignore[arg-type]
        out[uid] = PointFacts(
            point_iri=str(e["point"]),
            environmental_boundary=e["boundary"],  # type: ignore[arg-type]
            # classify() compares one containing_space against the target, so when the
            # target is among the asserted locations it is the one handed over — an exact
            # asserted containment must not lose to row order. Others fall back to the
            # first sorted, and the rest still count as context via the sibling path.
            containing_space=None if not locs else (target if target in locs else locs[0]),
            # Fed ONLY by an explicit ontosage:zoneValidated true on the zone (T65's
            # floor-5 pilot authors the first ones). Anything else stays unvalidated.
            validated_zone_spaces=tuple(sorted(e["vzone"])),  # type: ignore[arg-type]
            unvalidated_zone_spaces=tuple(sorted(e["zone"])),  # type: ignore[arg-type]
            sibling_spaces=tuple(sorted(e["sib"])),  # type: ignore[arg-type]
        )
    return out


async def cadences_for_uuids(uuids: Sequence[str], namespace: str, run_select) -> Dict[str, int]:
    """``{timeseries uuid: declared archival interval, seconds}`` (V6-T17/T65).

    Reads ontosage:archivalIntervalS off the POINT that carries the uuid — the binding the
    T65 instance data asserts. Absent declarations are absent from the map: the completeness
    module treats an unknown cadence as unknown coverage, and inventing one here would let a
    series with a hole score itself complete (the circularity its docstring forbids).
    """
    ids = [str(u) for u in (uuids or []) if u][:MAX_POINTS]
    if not ids or not namespace:
        return {}
    values = " ".join(f'"{_esc(u)}"' for u in ids)
    q = (
        _PREFIXES + "SELECT ?uuid ?cad WHERE {\n"
        f"  VALUES ?uuid {{ {values} }}\n"
        "  ?e ref:hasTimeseriesId ?uuid .\n"
        "  ?point ref:hasExternalReference ?e ;\n"
        "         ontosage:archivalIntervalS ?cad .\n"
        "}"
    )
    try:
        res = await run_select(q, limit=2000)
    except Exception as exc:
        logger.debug(f"[spatial_facts] cadence query failed: {exc}")
        return {}
    out: Dict[str, int] = {}
    for row in (res or {}).get("rows") or []:
        u, c = row.get("uuid"), row.get("cad")
        try:
            if u and c is not None:
                out[str(u)] = int(float(c))
        except (TypeError, ValueError):
            continue
    return out


async def calibration_for_uuids(
    uuids: Sequence[str], namespace: str, run_select
) -> Dict[str, Dict[str, str]]:
    """``{uuid: {"calibrated_on": iso, "due_on": iso}}`` (V6-T34).

    Absent declarations are absent from the map. The caller renders that as `unknown`, which
    the policy treats as disqualifying for a standards verdict — an undeclared calibration is
    not a passing one, and defaulting it to `calibrated` would be the single most dangerous
    default in the system.
    """
    ids = [str(u) for u in (uuids or []) if u][:MAX_POINTS]
    if not ids or not namespace:
        return {}
    values = " ".join(f'"{_esc(u)}"' for u in ids)
    q = (
        _PREFIXES + "SELECT ?uuid ?cal ?due WHERE {\n"
        f"  VALUES ?uuid {{ {values} }}\n"
        "  ?e ref:hasTimeseriesId ?uuid .\n"
        "  ?point ref:hasExternalReference ?e .\n"
        "  OPTIONAL { ?point ontosage:calibratedOn ?cal }\n"
        "  OPTIONAL { ?point ontosage:calibrationDueOn ?due }\n"
        "  FILTER(BOUND(?cal) || BOUND(?due))\n"
        "}"
    )
    try:
        res = await run_select(q, limit=2000)
    except Exception as exc:
        logger.debug(f"[spatial_facts] calibration query failed: {exc}")
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for row in (res or {}).get("rows") or []:
        u = row.get("uuid")
        if not u:
            continue
        entry = out.setdefault(str(u), {})
        if row.get("cal"):
            entry["calibrated_on"] = str(row["cal"])
        if row.get("due"):
            entry["due_on"] = str(row["due"])
    return out


async def default_run_select(query: str, limit: int = 1000):
    """The ordinary SPARQL path, injected by default so callers can substitute a fake."""
    from orchestrator.services.ontology_manager import run_sparql_select

    return await run_sparql_select(query, limit=limit)


def active_namespace() -> str:
    """The ACTIVE building's namespace. Never a literal — see contract rule 3."""
    try:
        from shared.config import settings

        return settings.BUILDING_NAMESPACE or ""
    except Exception:
        return ""


__all__ = [
    "cadences_for_uuids",
    "calibration_for_uuids",
    "facts_for_uuids",
    "resolve_space_iri",
    "default_run_select",
    "active_namespace",
    "MAX_POINTS",
]
