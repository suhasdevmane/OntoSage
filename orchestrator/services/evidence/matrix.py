# -*- coding: utf-8 -*-
"""The Question-to-Observability Matrix (V6-T09).

Master 13.1 calls this the artefact that *"prevents the project from claiming capabilities
that the physical deployment cannot support"*. For each question shape it states what
answering that shape REQUIRES — variables, spatial resolution, cadence, non-sensor context,
quality conditions, access level, abstention rule — and whether this building has it.

**Requirements are derived, not listed.** A hand-written table of shapes would go stale the
moment a modality is added, and would be a third place (after the intent registry and the
evidence policy) where the system's own vocabulary is restated. So a shape's requirements come
from what the pipeline already declares:

* the **intent registry** supplies the shapes themselves;
* `evidence_policy.yaml` supplies the freshness limit, completeness floor, consequence class,
  and whether the shape needs calibration or an authoritative source;
* the **modality config** supplies which Brick classes count as which measurand;
* the **live graph** supplies what the building actually has.

**Every row names the specific missing element.** Reporting aggregate coverage hides the
actionable part: "62% observable" tells an estate manager nothing, while "occupancy: no sensor
in 41 of 52 spaces" and "availability: no booking system connected" are two different jobs for
two different people. That distinction is the deliverable — it is what turns the 6/63/31
readiness split from an embarrassment into a work list.

**Unsatisfied is not failure.** A building with 6% instrumentation and a precise account of
its own blindness is the plan's definition of success (plan §0). The matrix exists to make the
blindness legible, not to grade the estate.

Pure and I/O-free: the caller supplies the observed facts. The script that gathers them is
`scripts/build_observability_matrix.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ShapeRequirement:
    """What answering one question shape needs from the building."""

    shape: str
    #: Measurands the shape reads, by modality name. Empty for shapes that read no sensor.
    modalities: Sequence[str] = ()
    #: 'space' | 'floor' | 'building' — the resolution a claim of this shape makes.
    spatial_resolution: str = "space"
    #: Freshness limit in minutes, from policy, for the tightest modality involved.
    max_age_minutes: Optional[float] = None
    #: Completeness floor for aggregates of this consequence class.
    min_completeness: Optional[float] = None
    consequence_class: str = "informational"
    requires_calibration: bool = False
    requires_authoritative_source: bool = False
    #: The non-sensor system this shape depends on, when it depends on one.
    authoritative_system: str = ""
    access_tier: str = "public"
    #: What the system does when the requirement is unmet — the abstention rule.
    abstention: str = ""


@dataclass
class ShapeObservability:
    """Whether this building satisfies one shape's requirements, and what is missing."""

    requirement: ShapeRequirement
    #: Specific unmet elements, each phrased as a job someone could act on.
    missing: List[str] = field(default_factory=list)
    #: Facts worth reporting even when satisfied (coverage share, declared cadence count).
    notes: List[str] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        return not self.missing

    @property
    def verdict(self) -> str:
        return "satisfied" if self.satisfied else "unsatisfied"


def assess_shape(
    req: ShapeRequirement,
    *,
    instrumented_modalities: Sequence[str],
    space_coverage: Optional[Dict[str, float]] = None,
    cadence_declared: Optional[Dict[str, bool]] = None,
    calibration_declared: Optional[Dict[str, float]] = None,
    connected_systems: Sequence[str] = (),
) -> ShapeObservability:
    """Judge one shape against one building's facts. Pure.

    Each unmet element is recorded as its own entry rather than collapsed into a score,
    because the remedies differ: installing a sensor, declaring a cadence, connecting a
    booking system and commissioning a calibration are four different jobs.
    """
    out = ShapeObservability(requirement=req)
    have = {m.lower() for m in instrumented_modalities}
    coverage = space_coverage or {}
    cadences = cadence_declared or {}
    calibrated = calibration_declared or {}
    systems = {s.lower() for s in connected_systems}

    for modality in req.modalities:
        m = modality.lower()
        if m not in have:
            out.missing.append(
                f"no {modality} sensor exists in this building — the variable cannot be read "
                f"at all"
            )
            continue
        share = coverage.get(m)
        if req.spatial_resolution == "space" and share is not None and share < 1.0:
            # A space-resolution claim needs a sensor IN the space. Partial coverage is not a
            # failure of the shape, it is a list of rooms that cannot be answered about.
            out.missing.append(
                f"{modality}: only {share:.0%} of spaces have an in-room sensor, so a "
                f"room-level {modality} claim is unavailable in the remainder"
            )
        elif share is not None:
            out.notes.append(f"{modality} covers {share:.0%} of spaces")
        if req.min_completeness is not None and not cadences.get(m, False):
            out.missing.append(
                f"{modality}: no archival cadence declared, so completeness of a historical "
                f"window cannot be computed (ontosage:archivalIntervalS)"
            )
        if req.requires_calibration:
            # A SHARE, not a boolean. One commissioned instrument must not vouch for a whole
            # building's standards claims — a safety verdict needs every contributing sensor
            # calibrated, so anything short of full coverage is named with its number.
            cal_share = calibrated.get(m)
            cal_share = 0.0 if cal_share is None else float(cal_share)
            if cal_share < 1.0:
                shortfall = (
                    "no calibration state declared"
                    if cal_share == 0.0
                    else f"only {cal_share:.0%} of {modality} sensors declare a calibration state"
                )
                out.missing.append(
                    f"{modality}: {shortfall}, and a "
                    f"{req.consequence_class.replace('_', ' ')} claim may not rest on an "
                    f"uncalibrated instrument"
                )

    if req.requires_authoritative_source:
        wanted = (req.authoritative_system or "").lower()
        if wanted and wanted not in systems:
            out.missing.append(
                f"no {req.authoritative_system} is connected; this shape asks for something "
                f"only a system of record can establish, and inferring it from sensors is "
                f"forbidden (rule R-8)"
            )
    return out


def summarise(rows: Sequence[ShapeObservability]) -> Dict[str, int]:
    """Counts, for the header of a report. Never a single percentage.

    A single number would hide which shapes are blocked and by what — the whole reason the
    Master Report asks for a matrix rather than a coverage figure.
    """
    total = len(rows)
    satisfied = sum(1 for r in rows if r.satisfied)
    by_cause = {
        "no sensor": 0,
        "partial coverage": 0,
        "no cadence": 0,
        "no calibration": 0,
        "no authoritative system": 0,
    }
    for r in rows:
        for m in r.missing:
            if "no " in m and "sensor exists" in m:
                by_cause["no sensor"] += 1
            elif "of spaces have an in-room sensor" in m:
                by_cause["partial coverage"] += 1
            elif "archival cadence" in m:
                by_cause["no cadence"] += 1
            elif "calibration state" in m or "calibration state" in m.lower():
                by_cause["no calibration"] += 1
            elif "is connected" in m:
                by_cause["no authoritative system"] += 1
    return {"shapes": total, "satisfied": satisfied, "unsatisfied": total - satisfied, **by_cause}


#: Which non-sensor system each entitlement shape depends on. Claim types, not building facts
#: — every building has booking and access questions, and none of them is answerable from a
#: sensor (rule R-8, and `permission_guard` enforces the same mapping at answer time).
AUTHORITATIVE_SYSTEM_BY_SHAPE: Dict[str, str] = {
    "events": "booking system",
    "lab_booking": "booking system",
    "compliance": "compliance register",
    "control": "actuation gateway",
    "maintenance": "work-order system",
    "register": "asset register",
}

__all__ = [
    "AUTHORITATIVE_SYSTEM_BY_SHAPE",
    "ShapeObservability",
    "ShapeRequirement",
    "assess_shape",
    "summarise",
]
