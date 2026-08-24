# -*- coding: utf-8 -*-
"""Plant state: what the BMS already knows, joined to the space it serves (V6-T26).

Master Package D is explicit that the hundreds of points a BMS already holds should be
**integrated, not duplicated** with new IoT sensors. Duplication costs more and produces a
second, less authoritative copy of the same measurement — and the report warns against it by
name.

The integration is therefore config, not code: `saturation_modalities.yaml` now declares six
plant modalities (supply/return air temperature, fan state, damper position, filter
differential pressure, supply air flow), every Brick class verified present in the shipped TBox
before being written. A point typed with one of them and carrying
`ref:hasTimeseriesId + ref:storedAt` is answerable through the normal lanes with no code
change. That is the portability claim applied to the source family that most often lives
outside the sensor estate.

**What this module adds is the JOIN a diagnosis needs.** "Why is 5.16 stuffy?" is answerable
from a CO2 series alone only as a description. The useful answer — *the AHU serving it has its
damper at 5% and its supply fan off* — needs the path from a space to the plant that serves it,
and that path is `brick:feeds` / `brick:isPointOf`, already in the graph.

**Plant state is context, never the room's measurement.** A supply-air temperature of 14 °C is
a fact about the duct, not about the room, and reporting it as a room reading would be exactly
the substitution the non-substitution rule forbids. Everything here is labelled as equipment
state and carries the equipment's identity.

**Absence declines honestly.** A building with no plant points connected gets a statement
naming what would answer the question, not a silent omission that reads like "nothing is
wrong".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

_PREFIXES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
)


#: Modality names declared with `scope: equipment` — the plant family. Read from config rather
#: than listed here, so a building that declares its own plant modality is covered too.
def plant_modalities(building_id: Optional[str] = None) -> List[str]:
    """Modality names whose declared scope is `equipment`."""
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modality_raw

        # load_modality_raw returns the MERGED MODALITY MAP itself, not a document with a
        # "modalities" key. Written the other way first, this returned [] with no exception --
        # a plant lane that silently believed the building had no plant. The suite now holds a
        # positive control that fails if this list is ever empty for the shipped config.
        raw = load_modality_raw(building_id) or {}
        return sorted(
            name
            for name, spec in raw.items()
            if str(((spec or {}).get("sat") or {}).get("scope", "room")).lower() == "equipment"
        )
    except Exception as exc:
        logger.debug(f"[plant] modality config unavailable: {exc}")
        return []


def plant_brick_classes(building_id: Optional[str] = None) -> List[str]:
    """Brick class local names across every equipment-scoped modality."""
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        wanted = set(plant_modalities(building_id))
        out: List[str] = []
        for spec in load_modalities(building_id):
            if spec.name in wanted:
                out.extend(spec.brick_classes)
        return sorted(set(out))
    except Exception as exc:
        logger.debug(f"[plant] class list unavailable: {exc}")
        return []


def preferred_classes(building_id: Optional[str] = None) -> List[str]:
    """The class each equipment-scoped modality PROVISIONS with.

    Used only to break ties between equivalent Brick classes so one point is always named the
    same way. Config-driven on purpose: the alternative -- picking the longer name, or a
    hardcoded preference -- would be a building literal in building-agnostic code.
    """
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modality_raw

        raw = load_modality_raw(building_id) or {}
        out = []
        for spec in raw.values():
            sat = (spec or {}).get("sat") or {}
            if str(sat.get("scope", "room")).lower() == "equipment" and sat.get("brick_class"):
                out.append(str(sat["brick_class"]))
        return sorted(set(out))
    except Exception as exc:
        logger.debug(f"[plant] preferred classes unavailable: {exc}")
        return []


@dataclass
class PlantPoint:
    """One plant point, and the equipment it belongs to."""

    point_iri: str
    equipment_iri: str
    brick_class: str
    uuid: str = ""
    label: str = ""

    @property
    def equipment_name(self) -> str:
        return self.equipment_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    @property
    def kind(self) -> str:
        return self.brick_class.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


@dataclass
class PlantContext:
    """The plant serving one space, and whether anything was found."""

    space_iri: str
    points: List[PlantPoint] = field(default_factory=list)
    equipment: List[str] = field(default_factory=list)

    @property
    def has_points(self) -> bool:
        return bool(self.points)

    def describe(self) -> str:
        """One line for a diagnosis to cite — or an honest absence.

        The absence branch NAMES what would answer the question. "No plant state available"
        alone reads like "nothing is wrong with the plant", which is a different claim and one
        this building cannot make.
        """
        if self.points:
            kinds = sorted({p.kind for p in self.points})
            equip = ", ".join(sorted({p.equipment_name for p in self.points}))
            return (
                f"Plant serving this space: {equip} — {len(self.points)} point(s) available "
                f"({', '.join(kinds)}). These describe the EQUIPMENT, not the room."
            )
        if self.equipment:
            equip = ", ".join(e.rsplit("#", 1)[-1] for e in self.equipment)
            return (
                f"The graph says {equip} serves this space, but no plant points are connected "
                f"for it — so I cannot say whether the ventilation is actually running. "
                f"Connecting the BMS points for that equipment would answer it."
            )
        return (
            "No equipment is declared as serving this space, so plant state cannot be "
            "consulted. That is a gap in the graph, not a finding about the plant."
        )


def _serving_clause(space_iri: str) -> str:
    """The asserted paths from a space to the plant serving it.

    Probed against the live graph before being written, because the obvious form is wrong
    here: **an AHU feeds an HVAC_Zone, never a Room** (0 direct vs 73 zone-mediated in
    bldg1), and `?equip brick:feeds <room>` returns nothing on every building modelled this
    way. Zones are `brick:isPartOf` the room they condition -- direction verified, not
    assumed; the inverse reading returns zero rows.

    Both hops are asserted triples. No proximity, no name matching, no floor-number
    heuristic: the same rule that keeps distance out of `spatial_facts` after BUG-189, where
    an inferred containment produced a confident answer about a room that did not exist.
    """
    return (
        f"  {{ ?equip brick:feeds <{space_iri}> }}\n"
        "  UNION\n"
        f"  {{ ?equip brick:feeds ?zone . ?zone brick:isPartOf <{space_iri}> }}\n"
    )


def build_query(space_iri: str, classes: Sequence[str]) -> str:
    """Points on the equipment that serves one space."""
    values = " ".join(f"brick:{c}" for c in classes if c)
    return (
        _PREFIXES + "SELECT DISTINCT ?point ?equip ?cls ?uuid ?label WHERE {\n"
        f"  VALUES ?cls {{ {values} }}\n"
        f"{_serving_clause(space_iri)}"
        "  ?point brick:isPointOf ?equip ; a ?cls .\n"
        # Keep only the MOST SPECIFIC matched class. The repository reasons over the Brick
        # hierarchy, so a filter-dP point also has type Differential_Pressure_Sensor and a
        # supply-air-temperature point also has type Discharge_Air_Temperature_Sensor -- when
        # the modality config lists both, one physical point comes back twice and the count
        # inflates. Live: 9 "points" for 7 real ones, which is a fabricated number in an
        # answer, not a cosmetic duplicate.
        #
        # The inner NOT EXISTS is what makes this safe for EQUIVALENT classes. Brick declares
        # Supply_Air_Temperature_Sensor and Discharge_Air_Temperature_Sensor equivalent, so
        # under reasoning each is a subclass of the other. Without the guard both satisfy the
        # outer filter, they annihilate, and the point DISAPPEARS -- a connected sensor
        # reported as absent, which is worse than the double-count this filter exists to fix.
        # Observed live before the guard was added.
        "  FILTER NOT EXISTS {\n"
        "    ?point a ?sub . ?sub rdfs:subClassOf ?cls . FILTER(?sub != ?cls)\n"
        "    FILTER NOT EXISTS { ?cls rdfs:subClassOf ?sub }\n"
        "  }\n"
        "  OPTIONAL { ?point rdfs:label ?label }\n"
        "  OPTIONAL { ?point ref:hasExternalReference ?e . ?e ref:hasTimeseriesId ?uuid }\n"
        "}"
    )


def equipment_query(space_iri: str) -> str:
    """Equipment serving a space, regardless of whether it has points.

    Asked separately so "no equipment declared" and "equipment declared but unconnected" stay
    different answers — they are different jobs for different people.
    """
    return (
        _PREFIXES
        + "SELECT DISTINCT ?equip ?label WHERE {\n"
        + _serving_clause(space_iri)
        + "  OPTIONAL { ?equip rdfs:label ?label }\n}"
    )


def context_from_rows(
    space_iri: str,
    point_rows: Sequence[Dict],
    equip_rows: Sequence[Dict],
    building_id: Optional[str] = None,
):
    """Assemble a PlantContext from two SPARQL results. Pure."""
    ctx = PlantContext(space_iri=space_iri)
    # Deduplicate by point IRI. The SPARQL filter above already keeps the most specific class,
    # but this is the layer that owns the COUNT the answer prints, and a count is the one thing
    # that must not depend on a query staying subtle. A point reached by two paths (a VAV that
    # feeds a zone AND the room) is still one point.
    seen: Dict[str, PlantPoint] = {}
    preferred = set(preferred_classes(building_id))
    for row in point_rows or []:
        iri = str(row.get("point") or "")
        if not iri:
            continue
        existing = seen.get(iri)
        candidate = PlantPoint(
            point_iri=iri,
            equipment_iri=str(row.get("equip") or ""),
            brick_class=str(row.get("cls") or ""),
            uuid=str(row.get("uuid") or ""),
            label=str(row.get("label") or ""),
        )
        if existing is None:
            seen[iri] = candidate
            continue
        # Prefer the row that carries a uuid: a point with no timeseries id cannot be read,
        # and dropping the readable duplicate would make a connected point look unconnected.
        if not existing.uuid and candidate.uuid:
            seen[iri] = candidate
            continue
        # Equivalent classes both survive the SPARQL filter by design, so the surviving NAME
        # is decided here and must be DETERMINISTIC -- otherwise the same question names the
        # same point differently between runs. Preference comes from the modality config's own
        # provisioning class, so it is the building's declared vocabulary rather than a
        # hardcoded name or a longest-string heuristic.
        if candidate.kind in preferred and existing.kind not in preferred:
            seen[iri] = candidate
        elif candidate.kind == existing.kind and candidate.point_iri < existing.point_iri:
            seen[iri] = candidate
    ctx.points = sorted(seen.values(), key=lambda p: (p.equipment_name, p.kind))
    ctx.equipment = sorted({str(r.get("equip")) for r in (equip_rows or []) if r.get("equip")})
    return ctx


def rows_of(result: Any) -> List[Dict]:
    """Rows from EITHER SPARQL executor shape used in this codebase.

    Two conventions are live and they are not interchangeable:

    * ``ontology_manager.run_sparql_select`` returns ``{"ok": bool, "rows": [{col: value}]}``
    * ``deliberation.live.sparql_exec`` returns raw SPARQL-JSON,
      ``{"results": {"bindings": [{col: {"value": ...}}]}}``

    Normalising here is the whole point. Written against only the first shape, this module
    was handed the second by the diagnosis lane, the mismatch raised inside a broad
    ``except``, and the caller received an empty context that rendered as *"No equipment is
    declared as serving this space"* — a fluent, plausible, completely false statement about
    a room served by an AHU and a VAV with seven connected points.
    """
    if not result:
        return []
    if isinstance(result, dict) and isinstance(result.get("rows"), list):
        return result["rows"]
    bindings = ((result or {}).get("results") or {}).get("bindings") or []
    return [{k: (v or {}).get("value") for k, v in b.items()} for b in bindings]


async def _select(run_select, query: str) -> Any:
    """Call an executor that may or may not accept a ``limit`` keyword.

    Bounds live in the query text instead, so one call works for both. Probing with a keyword
    the callee does not accept is how the shape mismatch above stayed invisible.
    """
    return await run_select(query)


async def for_space(space_iri: str, run_select, building_id: Optional[str] = None):
    """Plant context for one space. Never raises: a diagnosis without plant context is still
    a diagnosis, while an exception here would cost the whole answer."""
    ctx = PlantContext(space_iri=space_iri)
    if not space_iri or run_select is None:
        return ctx
    try:
        classes = plant_brick_classes(building_id)
        equip = await _select(run_select, equipment_query(space_iri) + "\nLIMIT 50")
        points = (
            await _select(run_select, build_query(space_iri, classes) + "\nLIMIT 200")
            if classes
            else None
        )
        return context_from_rows(space_iri, rows_of(points), rows_of(equip), building_id)
    except Exception as exc:
        logger.debug(f"[plant] context unavailable for {space_iri}: {exc}")
        return ctx


__all__ = [
    "PlantContext",
    "PlantPoint",
    "build_query",
    "context_from_rows",
    "equipment_query",
    "for_space",
    "plant_brick_classes",
    "plant_modalities",
    "preferred_classes",
    "rows_of",
]
