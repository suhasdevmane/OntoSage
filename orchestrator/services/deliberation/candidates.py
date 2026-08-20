"""
candidates.py — candidate-space enumeration + coverage ledger (V4-T17).

Turns the admitted CQ-IR + capability schema into the concrete list the executor
fans out over: every space in scope, with its per-modality sensor handles,
geometry (centroid/area from the floor-plan manifests via the repaired
ontology_iri bridge) and, when a near-amenity qualifier is present, the metric
distance to the nearest located amenity of that kind.

The CoverageLedger is the anti-survivor-bias guarantee: every space that was in
scope but excluded is recorded WITH its reason — an answer may rank a subset,
but it must say which spaces it never considered and why.

Geometry access is injected (mapping ontology_iri -> GeometryInfo) so tests run
offline; the live loader reads the registry manifests. Spaces sharing one
ontology IRI (unmerged DWG/PDF duplicates, CAVEAT-154) dedupe here by IRI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from orchestrator.services.deliberation.capability_schema import (
    AdmissionResult,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.coverage_audit import STATUS_PRESENT, _local
from orchestrator.services.deliberation.cqir import CQIR, Hardness
from shared.utils import get_logger

logger = get_logger(__name__)

#: metres charged for changing floors when measuring "near X" across floors —
#: a documented convention (stairs/lift detour), not a claim about the building
FLOOR_CHANGE_PENALTY_M = 30.0


@dataclass
class GeometryInfo:
    centroid_m: Tuple[float, float]  # de-normalized to metres within the floor
    floor_index: Optional[int] = None
    area_m2: Optional[float] = None


@dataclass
class Candidate:
    space_iri: str
    label: str
    floor: str
    sensors: Dict[str, Dict[str, str]] = field(
        default_factory=dict
    )  # modality -> {uuid, stored_at}
    geometry: Optional[GeometryInfo] = None
    distance_to_anchor_m: Optional[float] = None


@dataclass
class LedgerEntry:
    space_iri: str
    label: str
    reason: str


@dataclass
class CoverageLedger:
    in_scope: int = 0
    considered: int = 0
    excluded: List[LedgerEntry] = field(default_factory=list)
    instrumented: Dict[str, int] = field(default_factory=dict)  # modality -> count among considered

    def summary(self) -> str:
        parts = [f"{self.considered} of {self.in_scope} spaces considered"]
        for modality, n in sorted(self.instrumented.items()):
            parts.append(f"{modality}: {n}/{self.considered} instrumented")
        if self.excluded:
            parts.append(f"{len(self.excluded)} excluded (listed)")
        return "; ".join(parts)


def enumerate_candidates(
    cqir: CQIR,
    admission: AdmissionResult,
    schema: BuildingCapabilitySchema,
    geometry: Optional[Dict[str, GeometryInfo]] = None,
) -> Tuple[List[Candidate], CoverageLedger]:
    """Scope -> filter -> annotate. Deterministic; excludes only with a recorded reason."""
    geometry = geometry or {}
    ledger = CoverageLedger()

    # 1. scope: floor / single-space anchors narrow the field
    scoped = []
    for s in schema.spaces:
        if admission.floor_anchor and s.floor != admission.floor_anchor:
            continue
        if admission.space_anchor and s.space_iri != admission.space_anchor:
            continue
        scoped.append(s)
    ledger.in_scope = len(scoped)

    # 2. dedupe by IRI (CAVEAT-154 manifests can carry DWG/PDF duplicates upstream)
    seen = set()
    hard = [c.modality for c in cqir.constraints if c.hardness == Hardness.HARD]
    soft = [c.modality for c in cqir.constraints if c.hardness == Hardness.SOFT]

    candidates: List[Candidate] = []
    for s in sorted(scoped, key=lambda x: x.space_iri):
        if s.space_iri in seen:
            continue
        seen.add(s.space_iri)
        sensors = {
            m: {"uuid": e["uuid"], "stored_at": e["stored_at"]}
            for m, e in s.modalities.items()
            if e.get("status") == STATUS_PRESENT
        }
        # hard constraints exclude un-instrumented spaces — WITH a ledger entry
        missing_hard = [m for m in hard if m not in sensors]
        if missing_hard:
            ledger.excluded.append(
                LedgerEntry(
                    s.space_iri,
                    s.label or _local(s.space_iri),
                    f"no {'/'.join(missing_hard)} sensor (hard requirement)",
                )
            )
            continue
        candidates.append(
            Candidate(
                space_iri=s.space_iri,
                label=s.label or _local(s.space_iri),
                floor=s.floor,
                sensors=sensors,
                geometry=geometry.get(s.space_iri),
            )
        )

    # 3. near-amenity annotation (soft by default: no geometry -> recorded, not dropped)
    if admission.amenity_anchor:
        anchors = [a for a in schema.amenities if a.kind == admission.amenity_anchor]
        anchor_geo = [(a, geometry.get(a.space_iri)) for a in anchors]
        for cand in candidates:
            cand.distance_to_anchor_m = _nearest_distance(cand, anchor_geo)
            if cand.distance_to_anchor_m is None:
                ledger.excluded.append(
                    LedgerEntry(
                        cand.space_iri, cand.label, "no geometry to measure amenity distance"
                    )
                )
        candidates = [
            c
            for c in candidates
            if not (admission.amenity_anchor and c.distance_to_anchor_m is None)
        ]

    ledger.considered = len(candidates)
    for m in set(hard + soft):
        ledger.instrumented[m] = sum(1 for c in candidates if m in c.sensors)
    logger.info(f"[candidates] {ledger.summary()}")
    return candidates, ledger


def _nearest_distance(cand: Candidate, anchor_geo) -> Optional[float]:
    """Metric distance to the nearest amenity instance; None when unmeasurable."""
    if cand.geometry is None:
        return None
    best: Optional[float] = None
    for amenity, geo in anchor_geo:
        if amenity.space_iri == cand.space_iri:
            d = 0.0
        elif geo is None:
            continue
        else:
            dx = cand.geometry.centroid_m[0] - geo.centroid_m[0]
            dy = cand.geometry.centroid_m[1] - geo.centroid_m[1]
            d = math.hypot(dx, dy)
            if (
                cand.geometry.floor_index is not None
                and geo.floor_index is not None
                and cand.geometry.floor_index != geo.floor_index
            ):
                d += FLOOR_CHANGE_PENALTY_M * abs(cand.geometry.floor_index - geo.floor_index)
        best = d if best is None else min(best, d)
    return best


def live_geometry(building_id: str) -> Dict[str, GeometryInfo]:
    """ontology_iri -> GeometryInfo from the persisted floor-plan manifests."""
    out: Dict[str, GeometryInfo] = {}
    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        registry = get_floor_plan_registry()
        manifests = []
        # list_manifests() is active-building-scoped and returns (building_id, floor)
        for bid, floor in registry.list_manifests() or []:
            m = registry.load_manifest(bid, floor)
            if m is not None:
                manifests.append(m)
        for manifest in manifests:
            bbox = getattr(manifest, "bounding_box", None) or {}
            width = float(
                getattr(bbox, "width_m", None)
                or (bbox.get("width_m") if isinstance(bbox, dict) else 0)
                or 0
            )
            height = float(
                getattr(bbox, "height_m", None)
                or (bbox.get("height_m") if isinstance(bbox, dict) else 0)
                or 0
            )
            floor_idx = getattr(manifest, "floor", None)
            spaces = getattr(manifest, "spaces", []) or []
            # CAVEAT-154: DWG/PDF twins are unmerged — geometry rides the DWG
            # space, ontology_iri rides the PDF space, both share the label.
            # Join by label here so linked spaces get their twin's centroid.
            geo_by_label: Dict[str, GeometryInfo] = {}
            for space in spaces:
                centroid = getattr(space, "centroid", None)
                label = (getattr(space, "label", "") or "").strip().lower()
                if centroid is None or not label or not width or not height:
                    continue
                geo_by_label[label] = GeometryInfo(
                    centroid_m=(
                        float(getattr(centroid, "x", 0.0)) * width,
                        float(getattr(centroid, "y", 0.0)) * height,
                    ),
                    floor_index=floor_idx,
                    area_m2=getattr(space, "area_m2", None),
                )
            for space in spaces:
                iri = getattr(space, "ontology_iri", "") or ""
                if not iri or iri in out:
                    continue
                centroid = getattr(space, "centroid", None)
                if centroid is not None and width and height:
                    out[iri] = GeometryInfo(
                        centroid_m=(
                            float(getattr(centroid, "x", 0.0)) * width,
                            float(getattr(centroid, "y", 0.0)) * height,
                        ),
                        floor_index=floor_idx,
                        area_m2=getattr(space, "area_m2", None),
                    )
                    continue
                twin = geo_by_label.get((getattr(space, "label", "") or "").strip().lower())
                if twin is not None:
                    out[iri] = twin
    except Exception as exc:  # geometry is an annotation, never a crash
        logger.warning(f"[candidates] live geometry unavailable: {exc}")
    return out
