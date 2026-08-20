"""
capability_schema.py — the live Building Capability Schema + admission gate (V4-T16).

Before ANY data is fetched, a compiled CQ-IR is validated against what the active
building actually is: which spaces exist, which modalities each space has backed
sensors for, which amenity kinds have located instances, which floors exist.
The verdict is one of:

  ADMIT    — every hard requirement is satisfiable; execution may proceed
             (partial soft coverage is allowed and lands in the coverage ledger).
  CLARIFY  — an anchor is ambiguous/unknown but real alternatives exist; carries
             ONE targeted question with concrete options.
  DECLINE  — a required modality has zero backed sensors anywhere (or the IR
             itself was not executable); carries the honest explanation inputs.

Asymmetric failure (the fabrication-gate rule): if the schema cannot be built,
the caller must decline — never assume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    CoverageAuditor,
    ModalitySpec,
    SpaceCoverage,
    SparqlExec,
    _local,
)
from orchestrator.services.deliberation.cqir import CQIR, SpatialRelation
from shared.utils import get_logger

logger = get_logger(__name__)

ADMIT = "admit"
CLARIFY = "clarify"
DECLINE = "decline"


@dataclass
class AmenityInstance:
    iri: str
    kind: str  # e.g. DrinkingWater
    space_iri: str
    floor: str
    label: str = ""


@dataclass
class BuildingCapabilitySchema:
    """What the building can answer with, resolved live from its own graph."""

    building_id: str
    namespace: str
    spaces: List[SpaceCoverage]
    amenities: List[AmenityInstance]

    @property
    def floors(self) -> List[str]:
        return sorted({s.floor for s in self.spaces if s.floor})

    @property
    def amenity_kinds(self) -> List[str]:
        return sorted({a.kind for a in self.amenities})

    def coverage_for(self, modality: str) -> Dict[str, int]:
        present = sum(
            1 for s in self.spaces if s.modalities.get(modality, {}).get("status") == STATUS_PRESENT
        )
        return {"present": present, "total": len(self.spaces)}


@dataclass
class ClarifyQuestion:
    slot: str  # 'floor' | 'amenity' | 'space' | 'signals'
    question: str
    options: List[str] = field(default_factory=list)


@dataclass
class AdmissionResult:
    verdict: str  # ADMIT | CLARIFY | DECLINE
    reason: str = ""
    question: Optional[ClarifyQuestion] = None
    missing_modalities: List[str] = field(default_factory=list)
    # normalized anchors execution can trust
    floor_anchor: Optional[str] = None  # floor local name (e.g. 'floor1')
    amenity_anchor: Optional[str] = None  # amenity kind (e.g. 'DrinkingWater')
    space_anchor: Optional[str] = None  # space IRI
    coverage: Dict[str, Dict[str, int]] = field(default_factory=dict)


_AMENITY_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ontosage: <http://ontosage.org/capabilities#>
SELECT ?a ?kind ?space ?label WHERE {
    ?a a ontosage:Amenity ; a ?kind ; ontosage:locatedIn ?space .
    OPTIONAL { ?a rdfs:label ?label }
    FILTER(?kind != ontosage:Amenity && ?kind != ontosage:Capability)
    FILTER(STRSTARTS(STR(?kind), "http://ontosage.org/capabilities#"))
} LIMIT 500
"""


async def build_schema(
    building_id: str,
    namespace: str,
    sparql_exec: SparqlExec,
    modalities: List[ModalitySpec],
) -> BuildingCapabilitySchema:
    """Resolve the live schema (spaces × modalities + located amenities)."""
    auditor = CoverageAuditor(sparql_exec, modalities)
    spaces = await auditor.audit(namespace)
    space_floor = {s.space_iri: s.floor for s in spaces}

    amenities: List[AmenityInstance] = []
    result = await sparql_exec(_AMENITY_QUERY)
    for b in (result.get("results", {}) or {}).get("bindings", []):
        space_iri = b.get("space", {}).get("value", "")
        amenities.append(
            AmenityInstance(
                iri=b.get("a", {}).get("value", ""),
                kind=_local(b.get("kind", {}).get("value", "")),
                space_iri=space_iri,
                floor=space_floor.get(space_iri, ""),
                label=b.get("label", {}).get("value", ""),
            )
        )
    logger.info(
        f"[capability_schema] {building_id}: {len(spaces)} spaces, "
        f"{len(amenities)} located amenities ({', '.join(sorted({a.kind for a in amenities}))})"
    )
    return BuildingCapabilitySchema(
        building_id=building_id, namespace=namespace, spaces=spaces, amenities=amenities
    )


def _norm_floor(anchor: str, floors: List[str]) -> Optional[str]:
    """'Floor 1' / '1' / 'floor1' -> the matching floor local name."""
    token = anchor.strip().lower().replace(" ", "").replace("_", "")
    for f in floors:
        f_norm = f.lower().replace(" ", "").replace("_", "")
        if token == f_norm or token == f_norm.replace("floor", "") or f"floor{token}" == f_norm:
            return f
    return None


def validate(cqir: CQIR, schema: BuildingCapabilitySchema) -> AdmissionResult:
    """Admission gate: ADMIT / CLARIFY(one question) / DECLINE — before any data fetch."""
    # 0. compiler-level ambiguity: surface as ONE clarify question (policy owns wording)
    if not cqir.is_executable():
        phrases = [s.phrase for s in cqir.signals][:3]
        return AdmissionResult(
            verdict=CLARIFY,
            reason="query has unresolved parts",
            question=ClarifyQuestion(
                slot="signals",
                question=(
                    "I couldn't map part of your request"
                    + (f" ({'; '.join(p for p in phrases if p)})" if phrases else "")
                    + " — could you rephrase or drop that part?"
                ),
            ),
        )

    # 1. every constrained modality must have at least one BACKED sensor somewhere
    missing = []
    coverage: Dict[str, Dict[str, int]] = {}
    for c in cqir.constraints:
        cov = schema.coverage_for(c.modality)
        coverage[c.modality] = cov
        if cov["present"] == 0:
            missing.append(c.modality)
    if missing:
        return AdmissionResult(
            verdict=DECLINE,
            reason=f"no backed sensors anywhere for: {', '.join(missing)}",
            missing_modalities=missing,
            coverage=coverage,
        )

    # 2. spatial anchors must resolve against the building's own inventory
    floor_anchor = amenity_anchor = space_anchor = None
    for q in cqir.spatial:
        if q.relation == SpatialRelation.ON_FLOOR:
            floor_anchor = _norm_floor(q.anchor, schema.floors)
            if floor_anchor is None:
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown floor '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="floor",
                        question=f"Which floor did you mean? I know: {', '.join(schema.floors)}",
                        options=schema.floors,
                    ),
                    coverage=coverage,
                )
        elif q.relation == SpatialRelation.NEAR_AMENITY:
            kinds = {k.lower(): k for k in schema.amenity_kinds}
            amenity_anchor = kinds.get(q.anchor.strip().lower().replace(" ", ""))
            if amenity_anchor is None:
                if not schema.amenity_kinds:
                    return AdmissionResult(
                        verdict=DECLINE,
                        reason="no located amenities are modelled for this building",
                        coverage=coverage,
                    )
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown amenity '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="amenity",
                        question=(
                            f"I don't know '{q.anchor}' here — nearest what? "
                            f"I have located: {', '.join(schema.amenity_kinds)}"
                        ),
                        options=schema.amenity_kinds,
                    ),
                    coverage=coverage,
                )
        elif q.relation in (SpatialRelation.IN_SPACE, SpatialRelation.ADJACENT_TO):
            token = q.anchor.strip().lower()
            matches = [
                s.space_iri
                for s in schema.spaces
                if token in s.space_iri.lower() or token in (s.label or "").lower()
            ]
            if len(matches) == 1:
                space_anchor = matches[0]
            elif not matches:
                sample = [(_local(s.space_iri)) for s in schema.spaces[:5]]
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown space '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="space",
                        question=f"I can't find '{q.anchor}'. Did you mean one of: {', '.join(sample)}?",
                        options=sample,
                    ),
                    coverage=coverage,
                )
            else:
                opts = [_local(m) for m in matches[:5]]
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"'{q.anchor}' matches {len(matches)} spaces",
                    question=ClarifyQuestion(
                        slot="space",
                        question=f"'{q.anchor}' matches several spaces — which one? {', '.join(opts)}",
                        options=opts,
                    ),
                    coverage=coverage,
                )

    return AdmissionResult(
        verdict=ADMIT,
        floor_anchor=floor_anchor,
        amenity_anchor=amenity_anchor,
        space_anchor=space_anchor,
        coverage=coverage,
    )
