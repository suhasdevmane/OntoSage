# -*- coding: utf-8 -*-
"""When sensors that should agree do not, say so (V6-T18).

Master 14.1 acceptance scenario 4: *"create conflicting sensors -> the answer reports the
disagreement rather than averaging it away."*

Averaging is the failure mode this prevents, and it is worth naming precisely: two sensors
reading 21 C and 27 C produce a mean of 24 C, **a value neither instrument measured**, with
nothing in the output to suggest anything is wrong. That is fabrication by arithmetic rather
than by prose, and it slips past every guard aimed at generated text.

Three rejected alternatives:

* **Average them** -- the documented failure above.
* **Pick the "better" sensor** -- requires a trustworthiness model that does not exist, and
  hides a real fault. The disagreement itself is the finding: one of those sensors needs
  attention, and silently preferring the other loses that.
* **Refuse to answer** -- overreacts. "The two sensors in this room disagree: 21.0 and 27.4"
  is a genuinely useful answer, and more useful than either number alone.

Sensors count as *comparable* only when the graph says they measure the same property in the
same place -- same modality plus same space or the same validated served zone. Co-location by
distance is not used, for the same reason it is absent from spatial adequacy.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class Reading:
    """One sensor's current value, with enough identity to name it in an answer."""

    sensor_id: str
    value: float
    label: str = ""
    unit: str = ""

    def describe(self) -> str:
        name = self.label or self.sensor_id.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        unit = f" {self.unit}" if self.unit else ""
        return f"{name} reads {self.value:g}{unit}"


@dataclass
class ConflictReport:
    """Whether a set of comparable readings disagree, and by how much."""

    space: str
    modality: str
    readings: List[Reading] = field(default_factory=list)
    tolerance: Optional[float] = None
    spread: Optional[float] = None
    conflicting: bool = False
    reason: str = ""

    @property
    def judged(self) -> bool:
        """False when there was nothing to compare or no declared tolerance.

        Callers must not read `conflicting is False` as agreement without checking this: an
        unjudged set has not been found to agree, it has not been assessed.
        """
        return len(self.readings) >= 2 and self.tolerance is not None

    def describe(self) -> str:
        if not self.conflicting:
            return ""
        parts = "; ".join(r.describe() for r in self.readings)
        return (
            f"The sensors covering {_short(self.space)} disagree by {self.spread:g} "
            f"(tolerance {self.tolerance:g}): {parts}. Both values are reported because "
            f"averaging them would produce a figure neither sensor measured."
        )

    def representative(self) -> Optional[float]:
        """A single number to use when the readings AGREE.

        Returns None on conflict, deliberately: there is no honest single value, and a
        caller that wants one must handle the disagreement instead of receiving a silent
        average.
        """
        if self.conflicting or not self.readings:
            return None
        return statistics.median(r.value for r in self.readings)


def detect(
    space: str,
    modality: str,
    readings: Sequence[Reading],
    tolerance: Optional[float],
) -> ConflictReport:
    """Compare readings that the graph says are measuring the same thing."""
    rs = list(readings)
    report = ConflictReport(space=space, modality=modality, readings=rs, tolerance=tolerance)

    if len(rs) < 2:
        report.reason = "only one sensor covers this space, so there is nothing to cross-check"
        return report
    if tolerance is None:
        report.reason = (
            f"no agreement tolerance is declared for {modality}, so these readings cannot be "
            "judged against each other"
        )
        return report

    values = [r.value for r in rs]
    report.spread = round(max(values) - min(values), 3)
    report.conflicting = report.spread > tolerance
    report.reason = (
        f"spread of {report.spread:g} across {len(rs)} sensors, "
        f"{'beyond' if report.conflicting else 'within'} the {tolerance:g} tolerance"
    )
    return report


def detect_all(
    grouped: Dict[Tuple[str, str], List[Reading]],
    tolerances: Dict[str, Optional[float]],
) -> List[ConflictReport]:
    """Run detection over every (space, modality) group; return only real conflicts.

    Only conflicts, because a report per agreeing group would bury the ones that matter.
    Agreement is the normal case and needs no narration.
    """
    out: List[ConflictReport] = []
    for (space, modality), readings in grouped.items():
        rep = detect(space, modality, readings, tolerances.get(modality))
        if rep.conflicting:
            out.append(rep)
    return out


def _short(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if iri else "this space"
