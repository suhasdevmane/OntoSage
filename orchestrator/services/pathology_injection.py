# -*- coding: utf-8 -*-
"""Plan which points carry which declared defect, and record it (V6-T61).

``config/pathology.yaml`` declares eleven defect kinds, each with the gate it must
trigger and a near-miss of the same shape just inside the threshold. The unit
assertions drive every gate from one clean and one defective case, which proves
each gate works. What they cannot show is whether the gates work **on a whole
building** — for that you need a fixture that is defective at realistic rates, and
a record of exactly which points were spoiled so precision and recall can be
scored against ground truth.

The catalogue's ``rate`` fields have been declared and unused since the harness
landed. This is what consumes them.

Three properties everything here depends on:

* **Deterministic.** Selection is seeded from the point's own id, so the plan is a
  pure function of (catalogue, points, seed). The manifest and the injection
  cannot disagree, and a re-run reproduces the same building — which is what lets
  a changed score mean changed code rather than a different dice roll.
* **One defect per point.** A point that is stale AND has a gap AND is
  uncalibrated tells you nothing about which gate caught it. Precision and recall
  are only interpretable when each spoiled point has exactly one expected gate.
* **A rate of 0 injects nothing.** Two entries — a prose overclaim and an
  informational-consequence case — are decided by the ASKER and the CLAIM, not by
  readings, so no fixture can provoke them. They stay in the catalogue with rate
  0 and are reported as not-injectable rather than quietly dropped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_CATALOGUE = _REPO / "config" / "pathology.yaml"


@dataclass
class Spoiled:
    """One point, the defect it carries, and the gate that should catch it."""

    point: str
    defect: str
    gate: str
    kind: str
    value: Any = None


@dataclass
class Plan:
    """Which points are spoiled, and what the catalogue could not inject."""

    spoiled: List[Spoiled] = field(default_factory=list)
    not_injectable: List[str] = field(default_factory=list)
    total_points: int = 0
    seed: str = ""

    @property
    def clean(self) -> int:
        return self.total_points - len(self.spoiled)

    def by_point(self) -> Dict[str, Spoiled]:
        return {s.point: s for s in self.spoiled}

    def by_gate(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for s in self.spoiled:
            out.setdefault(s.gate, []).append(s.point)
        return out


def load_catalogue(path: Optional[Path] = None) -> Dict[str, Any]:
    """The declared defects. {} when the file is absent — injection is optional."""
    p = path or _CATALOGUE
    if not p.is_file():
        logger.debug("[pathology] no catalogue; nothing will be injected")
        return {}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - a malformed catalogue must not crash a build
        logger.warning(f"[pathology] catalogue unreadable: {exc}")
        return {}
    return data.get("defects") or {}


def _draw(point: str, defect: str, seed: str) -> float:
    """A stable [0,1) for this (point, defect, seed). Same inputs, same draw."""
    h = hashlib.sha256(f"{seed}|{defect}|{point}".encode()).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def plan_injection(
    points: Sequence[str],
    *,
    seed: str = "v6-t61",
    catalogue: Optional[Dict[str, Any]] = None,
) -> Plan:
    """Decide which points carry which defect. Pure and deterministic.

    Defects are considered in catalogue order and a point already spoiled is
    skipped, so each spoiled point carries exactly one — the property that makes
    a precision/recall score interpretable at all.
    """
    defects = catalogue if catalogue is not None else load_catalogue()
    plan = Plan(total_points=len(points), seed=seed)
    if not defects or not points:
        return plan

    taken: set = set()
    for name, spec in defects.items():
        rate = float((spec or {}).get("rate") or 0.0)
        shape = (spec or {}).get("defect") or {}
        if rate <= 0 or not shape.get("kind"):
            # Declared but not data-provokable: the asker and the claim decide it,
            # so no fixture can produce it. Named, never silently dropped.
            plan.not_injectable.append(name)
            continue
        gate = str((spec or {}).get("gate") or "")
        for point in points:
            if point in taken:
                continue
            if _draw(point, name, seed) < rate:
                taken.add(point)
                plan.spoiled.append(
                    Spoiled(
                        point=point,
                        defect=name,
                        gate=gate,
                        kind=str(shape.get("kind") or ""),
                        value=shape.get("value"),
                    )
                )
    logger.info(
        f"[pathology] planned {len(plan.spoiled)} spoiled of {plan.total_points} point(s); "
        f"{len(plan.not_injectable)} defect kind(s) are not data-injectable"
    )
    return plan


def manifest(plan: Plan, *, building_id: str = "") -> Dict[str, Any]:
    """The ground truth a whole-building grader scores against.

    Without this a precision/recall number is unfalsifiable: you can count how often
    a gate fired, but not whether it fired on the points that deserved it.
    """
    return {
        "_comment": (
            "GROUND TRUTH for pathology scoring (V6-T61). Generated by "
            "orchestrator/services/pathology_injection.py from config/pathology.yaml. "
            "Each entry is a point that was DELIBERATELY spoiled and the gate that "
            "should catch it; every other point is expected to pass clean. A gate "
            "firing on a point absent from this list is a false positive."
        ),
        "building_id": building_id,
        "seed": plan.seed,
        "total_points": plan.total_points,
        "spoiled": len(plan.spoiled),
        "clean": plan.clean,
        "not_injectable": sorted(plan.not_injectable),
        "by_gate": {g: sorted(ps) for g, ps in sorted(plan.by_gate().items())},
        "points": [
            {"point": s.point, "defect": s.defect, "gate": s.gate, "kind": s.kind, "value": s.value}
            for s in sorted(plan.spoiled, key=lambda x: x.point)
        ],
    }


def score(plan: Plan, fired: Dict[str, Sequence[str]]) -> Dict[str, Dict[str, Any]]:
    """Precision and recall per gate, against the plan as ground truth.

    ``fired`` is {gate: [points it flagged]}. Reported per gate rather than as one
    number: a headline figure hides a gate that never fires behind one that fires
    on everything, and those need opposite fixes.
    """
    truth = plan.by_gate()
    gates = sorted(set(truth) | set(fired))
    out: Dict[str, Dict[str, Any]] = {}
    for gate in gates:
        expected = set(truth.get(gate, ()))
        got = set(fired.get(gate, ()))
        tp = len(expected & got)
        fp = len(got - expected)
        fn = len(expected - got)
        out[gate] = {
            "expected": len(expected),
            "fired": len(got),
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            # None, not 0.0: a gate with nothing to find has no precision to report,
            # and printing 0.0 would read as a failure rather than as no evidence.
            "precision": (tp / (tp + fp)) if (tp + fp) else None,
            "recall": (tp / (tp + fn)) if (tp + fn) else None,
            "false_positive_points": sorted(got - expected)[:10],
            "missed_points": sorted(expected - got)[:10],
        }
    return out
