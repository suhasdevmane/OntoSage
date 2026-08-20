"""
amenities.py — structured amenity individuals with real locations (V4-T12).

"Near water" can only be computed when a water point is an individual with
``ontosage:locatedIn <space IRI>`` — prose locationText can't join to geometry.
This builder instantiates per-instance amenities from the building's own space
inventory, deterministically (same graph state → same TTL), dual-typed
``a ontosage:Amenity, ontosage:<Subclass>`` so the CapabilityGraphResolver's
exact-type query keeps matching (the Cap_* convention).

Placement is deliberately simple and declared simulated: one drinking-water
point, one toilet facility and one study area per floor, assigned to that
floor's alphabetically-first spaces. Real buildings replace this file with
surveyed locations; the STRUCTURE (locatedIn + onFloor) is what the spatial
layer needs either way.
"""

from __future__ import annotations

from typing import Dict, List

from orchestrator.services.deliberation.coverage_audit import SpaceCoverage, _local

# amenity subclass -> (label prefix, lay terms) — vocabulary from the OCBV TBox
_AMENITY_KINDS = (
    (
        "DrinkingWater",
        "Drinking water point",
        "water, drinking water, water fountain, water cooler, bottle filling, fill my bottle",
    ),
    (
        "ToiletFacility",
        "Toilet facility",
        "toilet, toilets, washroom, restroom, bathroom, wc, accessible toilet",
    ),
    (
        "StudyArea",
        "Study area",
        "study area, study space, workspace, quiet study, place to work, place to sit and work",
    ),
)

_PREFIXES = (
    "@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .\n"
    "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
)


def plan_amenities(spaces: List[SpaceCoverage]) -> Dict[str, List[dict]]:
    """{amenity_kind: [placement]} — one of each kind per floor, deterministic."""
    by_floor: Dict[str, List[SpaceCoverage]] = {}
    for sc in spaces:
        by_floor.setdefault(sc.floor or "unknown", []).append(sc)
    plan: Dict[str, List[dict]] = {kind: [] for kind, _, _ in _AMENITY_KINDS}
    for floor in sorted(by_floor):
        rooms = sorted(by_floor[floor], key=lambda s: s.space_iri)
        for idx, (kind, label, lay) in enumerate(_AMENITY_KINDS):
            room = rooms[idx % len(rooms)]
            plan[kind].append(
                {
                    "floor": floor,
                    "space_iri": room.space_iri,
                    "space_label": room.label or _local(room.space_iri),
                    "label": label,
                    "lay_terms": lay,
                }
            )
    return plan


def build_amenity_ttl(namespace: str, plan: Dict[str, List[dict]]) -> str:
    """Turtle for the planned amenity individuals (Cap_* dual-typing convention)."""
    parts: List[str] = [
        "# SATURATE (V4-T12): per-instance amenities with STRUCTURED locations",
        "# (ontosage:locatedIn <space>) so proximity constraints are computable.",
        "# Placement is simulated and labeled as such; replace with surveyed",
        "# locations for a real building — the structure is what matters.",
        _PREFIXES + f"@prefix bldg:  <{namespace}> .\n",
    ]
    for kind in sorted(plan):
        for p in plan[kind]:
            floor = p["floor"]
            local = f"Amenity_{kind}_{floor}"
            parts += [
                f"<{namespace}{local}>",
                f"    a ontosage:Amenity , ontosage:{kind} ;",
                f'    rdfs:label "{p["label"]} — {p["space_label"]}"@en ;',
                f'    ontosage:layTerms "{p["lay_terms"]}" ;',
                f"    ontosage:locatedIn <{p['space_iri']}> ;",
                f'    ontosage:onFloor "{floor}" ;',
                f'    ontosage:locationText "{p["label"]} in {p["space_label"]} (floor {floor})" ;',
                f'    ontosage:answerText "There is a {p["label"].lower()} in {p["space_label"]} on floor {floor}." ;',
                '    ontosage:isSimulated "true"^^xsd:boolean .',
                "",
            ]
    return "\n".join(parts)
