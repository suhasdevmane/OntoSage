"""
scorer.py — the deterministic ranker: numbers never come from the LLM (V4-T20).

Pure functions from (candidates, per-candidate aggregated values, CQ-IR) to a
ranked table. Every utility is anchored to a cited normalization band — physical
standards, not building facts — and every exclusion or data gap is explicit:

  * HARD constraints filter (candidate fails threshold / has no value → excluded
    with a recorded reason);
  * SOFT constraints score in [0,1]; a candidate missing a soft value keeps its
    other criteria (weights renormalize) and carries a data-gap note — never a
    silent zero, never an imputed number;
  * proximity (when the query asked "near X") scores RELATIVE to the candidate
    field (1 − d/d_max) so no absolute walking-distance scale is invented;
  * ties break lexicographically by label (stated in the dossier);
  * a ±25% weight-perturbation sensitivity check reports whether the top choice
    is robust — a result the dossier must carry, per the plan's scoring-
    legitimacy mitigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from orchestrator.services.deliberation.candidates import Candidate
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    Direction,
    Hardness,
)
from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class ScoreAnchor:
    """Normalization band for one modality, with its citation for the dossier."""

    lo: float  # the "good" end for minimize-style constraints
    hi: float  # the "bad" end
    citation: str = ""


#: Standards-anchored default bands (physical/comfort standards — not building
#: facts). The executor may override per constraint from the RecipeRegistry;
#: whichever band is used, its citation lands in the dossier.
DEFAULT_ANCHORS: Dict[str, ScoreAnchor] = {
    "noise": ScoreAnchor(30.0, 70.0, "WHO guideline band 30-70 dB(A) indoor"),
    "co2": ScoreAnchor(420.0, 1500.0, "ASHRAE 62.1 comfort band 420-1500 ppm"),
    "temperature": ScoreAnchor(20.0, 26.0, "ASHRAE 55 comfort range 20-26 °C"),
    "humidity": ScoreAnchor(30.0, 70.0, "ASHRAE 55 comfort range 30-70 %RH"),
    "occupancy": ScoreAnchor(0.0, 8.0, "relative occupancy band (0 = empty)"),
    "illuminance": ScoreAnchor(0.0, 500.0, "CIBSE office task range up to 500 lux"),
    "pm25": ScoreAnchor(0.0, 15.0, "WHO 2021 AQG 24-h PM2.5 guideline 15 ug/m3"),
    "door_contact": ScoreAnchor(0.0, 1.0, "binary contact state"),
    "window_contact": ScoreAnchor(0.0, 1.0, "binary contact state"),
    "lift_state": ScoreAnchor(0.0, 1.0, "binary availability state (1 = in service)"),
}

#: Preferred direction for a ranking that states NO preference of its own
#: ("rank the zones by CO2" — the user named the criterion but not which end is
#: better). Only modalities where a health/physical standard names the good end
#: appear here, and the citation for that end is the modality's anchor above.
#:
#: Deliberately ABSENT, because for these a direction-less rank is genuinely
#: ambiguous and must be ASKED, never guessed: temperature and humidity (a
#: comfort BAND — neither extreme is better), occupancy (busy is good for a cafe
#: and bad for a study room), water_flow, and the binary contact/state
#: modalities (an ordering of open/closed carries no meaning).
#:
#: The consumption modalities (energy_submeter, water_flow) are absent for a
#: second reason: they carry no calibrated band on purpose (BUG-180 — there is
#: no standard "good" kWh), so the scorer skips them. Claiming a better end for
#: something nothing can score would produce a ranking with no basis.
DEFAULT_PREFERENCE: Dict[str, Direction] = {
    "co2": Direction.MINIMIZE,
    "pm25": Direction.MINIMIZE,
    "noise": Direction.MINIMIZE,
    "illuminance": Direction.MAXIMIZE,
}

# DELIBERATELY UNANCHORED (V5-T10): energy_submeter (kWh), water_flow (L) and
# parking_free (bays). Comfort modalities have standards bands that hold in any
# building; consumption and count quantities do not — "good" kWh depends on floor
# area, occupancy and tariff, and free bays depend on the size of the car park.
# Inventing a band here would let the scorer emit a confident ranking off a scale
# nobody calibrated, which is precisely the fabrication the honesty contract
# forbids. A building that HAS a defensible band supplies it per-building via the
# RecipeRegistry / benchmarks.csv; until then score_candidates skips the criterion
# and says why, rather than guessing.


@dataclass
class CriterionScore:
    modality: str
    value: Optional[float]
    utility: Optional[float]
    weight: float
    citation: str = ""
    note: str = ""  # e.g. 'no data — criterion skipped, weights renormalized'


@dataclass
class ScoredCandidate:
    space_iri: str
    label: str
    floor: str
    criteria: List[CriterionScore] = field(default_factory=list)
    proximity_m: Optional[float] = None
    proximity_utility: Optional[float] = None
    total: Optional[float] = None
    rank: Optional[int] = None
    excluded_reason: Optional[str] = None
    data_gaps: List[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    ranked: List[ScoredCandidate]  # rank order, excluded ones NOT here
    excluded: List[ScoredCandidate]
    top1_stable_under_weight_perturbation: Optional[bool] = None
    tie_break_rule: str = "equal totals break alphabetically by label"


def load_anchors(building_id: Optional[str] = None) -> Dict[str, ScoreAnchor]:
    """Standards bands, overlaid with this building's own calibration.

    DEFAULT_ANCHORS are physical/comfort STANDARDS expressed in standard units —
    CO2 in ppm, noise in dB(A). Real hardware does not always publish those
    units: some CO2 sensors report an air-quality index in the 60-90 range, which
    is a correct reading on its own scale but sits entirely below the 420 ppm
    "good" edge. Every room then scores a perfect 1.0 and the ranking silently
    degenerates to whatever other cue is present (CAVEAT-162) — the values are
    right, the BAND is being read in the wrong unit.

    A building declares its own band by adding an ``anchors:`` block to its
    ``saturation_modalities.yaml`` overlay, next to the ``sat.unit`` it already
    declares for the same modality::

        modalities:
          co2:
            anchors: {lo: 60, hi: 95, citation: "index scale, vendor datasheet"}

    Only named modalities are overridden; everything else keeps its standard
    band and its citation, so an overlay is a statement about one sensor fleet
    rather than an opt-out from standards. A band whose citation is missing gets
    one naming the building, because an uncited band in a dossier is exactly the
    unfalsifiable number this system refuses to print.
    """
    from orchestrator.services.deliberation.coverage_audit import load_modality_raw

    anchors = dict(DEFAULT_ANCHORS)
    if not building_id:
        return anchors
    try:
        raw = load_modality_raw(building_id)
    except Exception as exc:
        logger.warning(f"[scorer] anchor overlay unreadable, using standards only: {exc}")
        return anchors
    for modality, spec in (raw or {}).items():
        block = (spec or {}).get("anchors")
        if not isinstance(block, dict):
            continue
        try:
            lo = float(block["lo"])
            hi = float(block["hi"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                f"[scorer] {building_id}/{modality}: anchors block needs numeric lo and hi "
                f"- ignoring, standard band kept"
            )
            continue
        if hi <= lo:
            logger.warning(
                f"[scorer] {building_id}/{modality}: anchors hi ({hi}) must exceed lo ({lo}) "
                f"- ignoring, standard band kept"
            )
            continue
        citation = str(block.get("citation") or "").strip()
        anchors[str(modality)] = ScoreAnchor(
            lo, hi, citation or f"{building_id} calibration ({lo}-{hi})"
        )
        logger.info(f"[scorer] {building_id}/{modality}: band {lo}-{hi} from building overlay")
    return anchors


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _utility(c: Constraint, value: float, anchor: ScoreAnchor) -> float:
    span = max(1e-9, anchor.hi - anchor.lo)
    if c.direction == Direction.MINIMIZE:
        return _clamp01((anchor.hi - value) / span)
    if c.direction == Direction.MAXIMIZE:
        return _clamp01((value - anchor.lo) / span)
    if c.direction == Direction.BELOW:
        t = c.threshold if c.threshold is not None else anchor.hi
        return 1.0 if value <= t else _clamp01((anchor.hi - value) / max(1e-9, anchor.hi - t))
    if c.direction == Direction.ABOVE:
        t = c.threshold if c.threshold is not None else anchor.lo
        return 1.0 if value >= t else _clamp01((value - anchor.lo) / max(1e-9, t - anchor.lo))
    # NEAR_VALUE
    t = c.threshold if c.threshold is not None else (anchor.lo + anchor.hi) / 2.0
    return _clamp01(1.0 - abs(value - t) / (span / 2.0))


def score_candidates(
    cqir: CQIR,
    candidates: List[Candidate],
    values: Dict[str, Dict[str, float]],  # space_iri -> {modality: aggregated value}
    anchors: Optional[Dict[str, ScoreAnchor]] = None,
    proximity_weight: float = 1.0,
) -> ScoreResult:
    """Deterministic rank. `values` comes from the executor's aggregation — code, not LLM."""
    anchors = {**DEFAULT_ANCHORS, **(anchors or {})}
    hard = [c for c in cqir.constraints if c.hardness == Hardness.HARD]
    soft = [c for c in cqir.constraints if c.hardness == Hardness.SOFT]
    want_proximity = any(c.distance_to_anchor_m is not None for c in candidates)
    max_d = max((c.distance_to_anchor_m or 0.0) for c in candidates) if want_proximity else 0.0

    scored: List[ScoredCandidate] = []
    excluded: List[ScoredCandidate] = []
    for cand in candidates:
        vals = values.get(cand.space_iri, {})
        sc = ScoredCandidate(
            space_iri=cand.space_iri,
            label=cand.label,
            floor=cand.floor,
            proximity_m=cand.distance_to_anchor_m,
        )
        # hard constraints: no value or failing value -> excluded, with the reason
        failed = None
        for c in hard:
            v = vals.get(c.modality)
            if v is None:
                failed = f"no {c.modality} data for hard requirement"
                break
            anchor = anchors.get(c.modality)
            if anchor is None:
                # V5-T10: an un-anchored modality used to fall through to a 0-1
                # band, which silently clamps quantities on any other scale
                # (litres, kWh, bays) and emits a confident ranking with an empty
                # citation. A user-supplied threshold is still a real band, so
                # honour that; otherwise refuse to assert the requirement holds.
                if c.direction in (Direction.BELOW, Direction.ABOVE) and c.threshold is not None:
                    ok = v <= c.threshold if c.direction == Direction.BELOW else v >= c.threshold
                    if not ok:
                        failed = (
                            f"{c.modality}={v:g} fails hard {c.direction.value} {c.threshold:g}"
                        )
                        break
                    continue
                failed = f"no calibrated band for {c.modality} — hard requirement not verifiable"
                break
            if _utility(c, v, anchor) < 1.0 and c.direction in (Direction.BELOW, Direction.ABOVE):
                failed = f"{c.modality}={v:g} fails hard {c.direction.value} {c.threshold:g}"
                break
        if failed:
            sc.excluded_reason = failed
            excluded.append(sc)
            continue

        weights_total = 0.0
        weighted_sum = 0.0
        for c in hard + soft:
            v = vals.get(c.modality)
            anchor = anchors.get(c.modality)
            if v is None:
                sc.criteria.append(
                    CriterionScore(
                        c.modality,
                        None,
                        None,
                        c.weight,
                        anchor.citation if anchor else "",
                        "no data — criterion skipped, weights renormalized",
                    )
                )
                sc.data_gaps.append(c.modality)
                continue
            if anchor is None:
                # Scoring needs a band to normalize against. Consumption and count
                # modalities (kWh, litres, free bays) have no standards band that
                # holds across buildings — a per-building one belongs in the
                # RecipeRegistry / benchmarks.csv. Until then, say so rather than
                # rank on a number nobody calibrated.
                sc.criteria.append(
                    CriterionScore(
                        c.modality,
                        v,
                        None,
                        c.weight,
                        "",
                        f"no calibrated band for {c.modality} — "
                        "criterion skipped, weights renormalized",
                    )
                )
                sc.data_gaps.append(c.modality)
                continue
            u = _utility(c, v, anchor)
            sc.criteria.append(CriterionScore(c.modality, v, u, c.weight, anchor.citation))
            weighted_sum += u * c.weight
            weights_total += c.weight
        if want_proximity and sc.proximity_m is not None:
            sc.proximity_utility = 1.0 if max_d <= 0 else _clamp01(1.0 - sc.proximity_m / max_d)
            weighted_sum += sc.proximity_utility * proximity_weight
            weights_total += proximity_weight
        if weights_total <= 0:
            sc.excluded_reason = "no scorable data on any criterion"
            excluded.append(sc)
            continue
        sc.total = round(weighted_sum / weights_total, 4)
        scored.append(sc)

    scored.sort(key=lambda s: (-(s.total or 0.0), s.label))
    for i, s in enumerate(scored, 1):
        s.rank = i

    result = ScoreResult(ranked=scored, excluded=excluded)
    if len(scored) >= 2:
        result.top1_stable_under_weight_perturbation = _top1_stable(
            cqir, candidates, values, anchors, proximity_weight, scored[0].space_iri
        )
    logger.info(
        f"[scorer] ranked {len(scored)}, excluded {len(excluded)}"
        + (
            f", top1 stable: {result.top1_stable_under_weight_perturbation}"
            if len(scored) >= 2
            else ""
        )
    )
    return result


def _top1_stable(cqir, candidates, values, anchors, proximity_weight, top_iri) -> bool:
    """Does the winner survive every single-weight ±25% perturbation?"""
    for idx in range(len(cqir.constraints)):
        for factor in (0.75, 1.25):
            perturbed = (
                cqir.model_copy(deep=True) if hasattr(cqir, "model_copy") else cqir.copy(deep=True)
            )
            perturbed.constraints[idx].weight = cqir.constraints[idx].weight * factor
            # single-pass rescore (no recursion back into the sensitivity check)
            res = _plain_rank(perturbed, candidates, values, anchors, proximity_weight)
            if res and res[0] != top_iri:
                return False
    return True


def _plain_rank(cqir, candidates, values, anchors, proximity_weight) -> List[str]:
    """Rank IRIs without the sensitivity pass (helper for _top1_stable)."""
    hard = [c for c in cqir.constraints if c.hardness == Hardness.HARD]
    soft = [c for c in cqir.constraints if c.hardness == Hardness.SOFT]
    want_proximity = any(c.distance_to_anchor_m is not None for c in candidates)
    max_d = max((c.distance_to_anchor_m or 0.0) for c in candidates) if want_proximity else 0.0
    rows: List[Tuple[float, str, str]] = []
    for cand in candidates:
        vals = values.get(cand.space_iri, {})
        if any(vals.get(c.modality) is None for c in hard):
            continue
        total = 0.0
        wsum = 0.0
        skip = False
        for c in hard:
            anchor = anchors.get(c.modality, ScoreAnchor(0.0, 1.0))
            u = _utility(c, vals[c.modality], anchor)
            if u < 1.0 and c.direction in (Direction.BELOW, Direction.ABOVE):
                skip = True
                break
            total += u * c.weight
            wsum += c.weight
        if skip:
            continue
        for c in soft:
            v = vals.get(c.modality)
            if v is None:
                continue
            anchor = anchors.get(c.modality, ScoreAnchor(0.0, 1.0))
            total += _utility(c, v, anchor) * c.weight
            wsum += c.weight
        if want_proximity and cand.distance_to_anchor_m is not None:
            pu = 1.0 if max_d <= 0 else _clamp01(1.0 - cand.distance_to_anchor_m / max_d)
            total += pu * proximity_weight
            wsum += proximity_weight
        if wsum > 0:
            rows.append((-(total / wsum), cand.label, cand.space_iri))
    rows.sort()
    return [iri for _, _, iri in rows]
