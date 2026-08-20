# -*- coding: utf-8 -*-
"""
scenarios.py — scenario-conditioned answers with DECLARED assumptions (V5-T15/T28).

"Will RM101 be uncomfortable with 200 people at 2pm?" is not a forecast — it
is a forecast *plus a counterfactual*. The dishonest way to answer is to let
an LLM apply invented physics. The honest way, implemented here:

1. Parse the scenario override from the question (occupancy count, and
   optionally a time) — deterministic, no LLM.
2. MEASURE the sensitivity from this building's own history: regress the
   response modality on occupancy across the recorded range
   (Δresponse per person), keeping the fit quality.
3. Apply it to the baseline and DECLARE the method, the measured coefficient,
   its fit quality and the extrapolation distance in the answer.
4. If the sensitivity cannot be measured (no occupancy series, no variation,
   a hopeless fit), DECLINE the counterfactual and say why — never fall back
   to a textbook constant pretending to be this building.

Extrapolation honesty: if the scenario sits far outside the observed range
(e.g. 200 people when the room never exceeded 12), the answer says the
estimate is an extrapolation of N× the observed range, because a linear
sensitivity measured at 0–12 people says little about 200.

Pure functions over series — no I/O, unit-testable, building-agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: response modalities a headcount plausibly drives (others decline)
OCCUPANCY_DRIVEN = ("co2", "temperature", "humidity", "noise")

#: below this R² the measured relationship is not usable
MIN_R2 = 0.15


@dataclass
class ScenarioSpec:
    """The counterfactual the user asked about."""

    occupancy: Optional[float] = None
    hour: Optional[int] = None
    raw_phrase: str = ""

    def is_empty(self) -> bool:
        return self.occupancy is None and self.hour is None


@dataclass
class Sensitivity:
    """A measured Δresponse-per-person relationship, with its own quality."""

    slope: float
    intercept: float
    r2: float
    n_points: int
    occ_min: float
    occ_max: float

    def usable(self) -> bool:
        return self.n_points >= 12 and self.r2 >= MIN_R2 and self.occ_max > self.occ_min


_OCC_RE = re.compile(
    r"\b(?:with|for|if there (?:are|were)|assuming)\s+(?:about\s+|around\s+|~)?(\d{1,4})\s*"
    r"(?:people|persons?|occupants?|students?|attendees?|guests?)\b",
    re.IGNORECASE,
)
_OCC_RE_ALT = re.compile(
    r"\b(\d{1,4})\s*(?:people|persons?|occupants?|students?|attendees?|guests?)\b",
    re.IGNORECASE,
)
_HOUR_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)


def parse_scenario(question: str) -> ScenarioSpec:
    """Extract the counterfactual overrides; empty spec when there are none."""
    q = question or ""
    spec = ScenarioSpec()
    m = _OCC_RE.search(q) or _OCC_RE_ALT.search(q)
    if m:
        spec.occupancy = float(m.group(1))
        spec.raw_phrase = m.group(0).strip()
    h = _HOUR_RE.search(q)
    if h:
        hour = int(h.group(1)) % 12
        if (h.group(3) or "").lower() == "pm":
            hour += 12
        spec.hour = hour
    return spec


def measure_sensitivity(
    occupancy: Sequence[Tuple[Any, float]], response: Sequence[Tuple[Any, float]]
) -> Optional[Sensitivity]:
    """Least-squares Δresponse per person from THIS building's own history.

    Series are paired on their timestamps (string or datetime, compared as
    strings so adapter shapes do not matter).
    """
    occ_by_ts: Dict[str, float] = {}
    for ts, v in occupancy:
        try:
            occ_by_ts[str(ts)[:16]] = float(v)
        except (TypeError, ValueError):
            continue
    xs: List[float] = []
    ys: List[float] = []
    for ts, v in response:
        key = str(ts)[:16]
        if key in occ_by_ts:
            try:
                ys.append(float(v))
                xs.append(occ_by_ts[key])
            except (TypeError, ValueError):
                continue
    n = len(xs)
    if n < 12:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None  # occupancy never varied — nothing to measure
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 0.0
    return Sensitivity(
        slope=round(slope, 4),
        intercept=round(intercept, 3),
        r2=round(r2, 3),
        n_points=n,
        occ_min=min(xs),
        occ_max=max(xs),
    )


def apply_scenario(
    baseline_value: float,
    baseline_occupancy: float,
    spec: ScenarioSpec,
    sens: Sensitivity,
) -> Dict[str, Any]:
    """Baseline → scenario estimate, with the extrapolation distance stated."""
    delta_people = float(spec.occupancy) - float(baseline_occupancy)
    delta_value = sens.slope * delta_people
    observed_span = max(1e-9, sens.occ_max - sens.occ_min)
    beyond = max(0.0, float(spec.occupancy) - sens.occ_max)
    return {
        "baseline": round(baseline_value, 2),
        "scenario": round(baseline_value + delta_value, 2),
        "delta": round(delta_value, 2),
        "delta_people": round(delta_people, 1),
        "slope_per_person": sens.slope,
        "r2": sens.r2,
        "n_points": sens.n_points,
        "observed_range": [round(sens.occ_min, 1), round(sens.occ_max, 1)],
        "extrapolation_factor": round(beyond / observed_span, 1) if beyond else 0.0,
    }


def render_scenario_answer(
    modality: str, unit: str, space_label: str, spec: ScenarioSpec, result: Dict[str, Any]
) -> str:
    """Templated narration — every number comes from ``result``."""
    lines = [
        f"**{space_label} — {modality} with {spec.occupancy:g} people"
        + (f" at {spec.hour:02d}:00" if spec.hour is not None else "")
        + "**",
        "",
        f"- Baseline (recent conditions): **{result['baseline']:g}{unit}**",
        f"- Scenario estimate: **{result['scenario']:g}{unit}** "
        f"({result['delta']:+g}{unit} for {result['delta_people']:+g} people)",
        "",
        "**Method (measured on this building, not assumed):** "
        f"{result['slope_per_person']:+g}{unit} per person, fitted across "
        f"{result['n_points']} paired readings spanning "
        f"{result['observed_range'][0]:g}–{result['observed_range'][1]:g} occupants "
        f"(R² {result['r2']:g}).",
    ]
    if result["extrapolation_factor"]:
        lines.append(
            f"\n⚠️ **This is an extrapolation.** The scenario sits "
            f"{result['extrapolation_factor']:g}× the observed occupancy range beyond "
            f"anything recorded here, so treat the number as an order-of-magnitude "
            f"indication, not a prediction."
        )
    return "\n".join(lines)


def decline_reason(modality: str, sens: Optional[Sensitivity]) -> str:
    """Honest decline when the counterfactual cannot be grounded."""
    if modality not in OCCUPANCY_DRIVEN:
        return (
            f"**I can't answer that as a what-if.** Occupancy has no measured "
            f"relationship with {modality} in this building, so changing the headcount "
            "would only let me invent a number. I can give you the current and "
            f"forecast {modality} instead."
        )
    if sens is None:
        return (
            "**I can't answer that as a what-if.** This space has no paired "
            "occupancy history to measure a per-person effect from — without it any "
            "figure would be a textbook constant dressed up as this building. Add "
            "occupancy sensing (or ask about a space that has it) and this unlocks."
        )
    return (
        "**I can't answer that as a what-if.** I measured the occupancy effect here "
        f"and the relationship is too weak to use (R² {sens.r2:g} over {sens.n_points} "
        "readings). Reporting a scenario number from that fit would be false precision."
    )
