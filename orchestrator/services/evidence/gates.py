# -*- coding: utf-8 -*-
"""Evidence gates: freshness, completeness, spatial adequacy, calibration (V6-T16/T32).

Every gate returns the same :class:`GateVerdict`, and **a verdict is not an action**. Whether
it changes the answer is decided by policy, per gate, per building. That separation is what
makes V6-T55's shadow mode possible without touching any gate: run them all, record what they
would do, and change nothing until each has been reviewed.

Getting this shape right early matters more than it looks. A gate written to raise or to
return a bare bool would have to be rewritten to support advisory mode, and six gates each
rewritten once is six chances to change behaviour by accident during the rewrite.

**Failing a gate is not an error.** It downgrades the answer's status and attaches a reason
and a remedy. "Not assessable, because the newest reading is three days old, and here is what
to restart" is a correct answer -- Master 15.5 calls that the single most important design
requirement -- and treating it as a failure path would invert the incentive V6 exists to set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence

from orchestrator.services.evidence.policy import EvidencePolicy, GateMode
from shared.models import AnswerStatus, SpatialAdequacy
from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class GateVerdict:
    """What one gate concluded, and whether policy lets it act."""

    gate: str
    passed: bool
    mode: GateMode = GateMode.ADVISORY
    reason: str = ""
    remedy: str = ""
    #: Status the answer must fall back to when this gate is enforcing and failed.
    downgrade_to: Optional[AnswerStatus] = None
    #: The policy figure the verdict was measured against, so an answer can cite it.
    threshold: Optional[str] = None

    @property
    def blocks(self) -> bool:
        """True only when the gate FAILED and policy has it ENFORCING.

        The single place enforcement is decided. An advisory failure is recorded on the
        evidence record and reported by the impact tooling, and changes nothing else.
        """
        return not self.passed and self.mode is GateMode.ENFORCING

    @property
    def advisory_failure(self) -> bool:
        """Would have blocked, but is not enforcing yet. This is what T55 counts."""
        return not self.passed and self.mode is GateMode.ADVISORY

    def describe(self) -> str:
        if self.passed:
            return ""
        tail = f" {self.remedy}" if self.remedy else ""
        return f"{self.reason}.{tail}".strip()


def freshness_gate(
    policy: EvidencePolicy,
    modality: str,
    latest_observation: Optional[datetime],
    now: datetime,
    is_current_question: bool = True,
) -> GateVerdict:
    """Is the newest observation recent enough to answer about NOW? (V6-T16)

    *"Stale evidence is not current status"* -- stakeholder catalogues 02, 05 and 06.

    This is not hypothetical: CAVEAT-207 in this project was exactly this failure. One table
    stopped writing while another kept going, every "right now" answer silently came from
    days-old data, and nothing in the output said so.

    Only applies to present-tense questions. A historical question about last March is not
    stale merely because March was a while ago, and gating it would be nonsense.
    """
    mode = policy.gate_mode("freshness")
    if not is_current_question:
        return GateVerdict("freshness", True, mode, "not a current-status question")

    limit = policy.max_age_minutes(modality)
    if latest_observation is None:
        return GateVerdict(
            "freshness",
            False,
            mode,
            f"no {modality} observation is available for this space",
            remedy="Connect the stream, or check whether the publisher has stopped.",
            downgrade_to=AnswerStatus.NOT_ASSESSABLE,
            threshold=f"{limit:.0f} min",
        )

    age = (now - latest_observation).total_seconds() / 60.0
    if age <= limit:
        return GateVerdict(
            "freshness",
            True,
            mode,
            f"newest reading is {age:.0f} min old",
            threshold=f"{limit:.0f} min",
        )

    return GateVerdict(
        "freshness",
        False,
        mode,
        (
            f"the newest {modality} reading is {age:.0f} minutes old, beyond the "
            f"{limit:.0f}-minute limit for a current-status answer"
        ),
        remedy=(
            "The value is reported as a past observation rather than as current conditions; "
            "check whether the publisher for this stream is still running."
        ),
        # INFERRED, not NOT_ASSESSABLE: the reading is real and still informative about the
        # recent past. Refusing outright would discard usable evidence, which the
        # non-substitution rule never asks for.
        downgrade_to=AnswerStatus.INFERRED,
        threshold=f"{limit:.0f} min",
    )


def completeness_gate(
    policy: EvidencePolicy,
    coverage: Optional[float],
    consequence_class: str = "informational",
    detail: str = "",
) -> GateVerdict:
    """Did we observe enough of the window to aggregate over it? (V6-T17 wiring)"""
    mode = policy.gate_mode("completeness")
    floor = policy.min_completeness(consequence_class)

    if coverage is None:
        return GateVerdict(
            "completeness",
            False,
            mode,
            "the share of the window actually observed could not be established",
            remedy="Declare this stream's archival interval so coverage can be computed.",
            downgrade_to=AnswerStatus.NOT_ASSESSABLE,
            threshold=f"{floor:.0%}",
        )
    if coverage >= floor:
        return GateVerdict(
            "completeness",
            True,
            mode,
            detail or f"{coverage:.0%} of the window observed",
            threshold=f"{floor:.0%}",
        )
    return GateVerdict(
        "completeness",
        False,
        mode,
        (detail or f"only {coverage:.0%} of the requested window was observed")
        + f", below the {floor:.0%} needed for an aggregate",
        remedy="Narrow the window to a covered period, or restore the missing data.",
        downgrade_to=AnswerStatus.NOT_ASSESSABLE,
        threshold=f"{floor:.0%}",
    )


def spatial_gate(
    policy: EvidencePolicy,
    grade: SpatialAdequacy,
    scope: str,
    proxy_reason: str = "",
) -> GateVerdict:
    """May an answer at this scope rest on evidence of this grade? (V6-T13 wiring)"""
    mode = policy.gate_mode("spatial_adequacy")
    allowed = policy.allowed_adequacy(scope)
    if grade.value in set(allowed):
        return GateVerdict("spatial_adequacy", True, mode, f"{grade.value} evidence for a {scope}")

    if grade is SpatialAdequacy.NONE:
        return GateVerdict(
            "spatial_adequacy",
            False,
            mode,
            "no sensor covers the space asked about",
            remedy="Install or connect a sensor in this space to answer it directly.",
            downgrade_to=AnswerStatus.NOT_ASSESSABLE,
            threshold=", ".join(allowed),
        )
    return GateVerdict(
        "spatial_adequacy",
        False,
        mode,
        proxy_reason or f"only {grade.value} evidence is available for this {scope}",
        remedy=(
            "The nearby reading is reported as context, but it cannot carry a claim about "
            "this space itself."
        ),
        # INFERRED: proxy evidence is genuinely informative when LABELLED as proxy, which is
        # exactly what Master 8 permits. Refusing would throw away real evidence.
        downgrade_to=AnswerStatus.INFERRED,
        threshold=", ".join(allowed),
    )


def calibration_gate(
    policy: EvidencePolicy, calibration_state: str, consequence_class: str
) -> GateVerdict:
    """May a claim of this consequence rest on a sensor in this calibration state? (V6-T34)

    Acceptance scenario 7. A standards verdict from an uncalibrated sensor carries the
    authority of the standard with none of its rigour -- the most dangerous shape of answer
    the system can produce, because the caveat gets skimmed while the verdict gets quoted.
    """
    mode = policy.gate_mode("calibration")
    if not policy.requires_calibration(consequence_class):
        return GateVerdict("calibration", True, mode, "not a calibration-sensitive claim")

    state = (calibration_state or "unknown").lower()
    if state == "calibrated":
        return GateVerdict("calibration", True, mode, "supporting sensors are calibrated")

    if state == "unknown" and not policy.forbids_unknown_calibration(consequence_class):
        return GateVerdict("calibration", True, mode, "calibration unknown, but permitted here")

    return GateVerdict(
        "calibration",
        False,
        mode,
        (
            f"a {consequence_class.replace('_', ' ')} claim cannot rest on a sensor whose "
            f"calibration is {state}"
        ),
        remedy=(
            "The raw reading is still reported as an observation; record the calibration "
            "date and method for these points to enable a standards verdict."
        ),
        downgrade_to=AnswerStatus.NOT_ASSESSABLE,
        threshold=consequence_class,
    )


def apply(verdicts: Sequence[GateVerdict], proposed: AnswerStatus) -> AnswerStatus:
    """Resolve a proposed status against every gate that ran.

    Only ENFORCING failures move the status, and the most conservative downgrade wins: a
    single NOT_ASSESSABLE outranks any number of INFERRED downgrades, because one missing
    prerequisite is enough to make a claim unsupportable no matter what else held.
    """
    rank = {
        AnswerStatus.NOT_ASSESSABLE: 0,
        AnswerStatus.INFERRED: 1,
        AnswerStatus.PREDICTED: 2,
        AnswerStatus.RECOMMENDED: 3,
        AnswerStatus.CALCULATED: 4,
        AnswerStatus.OBSERVED: 5,
    }
    worst = proposed
    for v in verdicts:
        if v.blocks and v.downgrade_to is not None:
            if rank[v.downgrade_to] < rank[worst]:
                worst = v.downgrade_to
    return worst


def blocking(verdicts: Sequence[GateVerdict]) -> List[GateVerdict]:
    return [v for v in verdicts if v.blocks]


def advisory_failures(verdicts: Sequence[GateVerdict]) -> List[GateVerdict]:
    """What each gate WOULD have done. The measurement behind V6-T55's impact report."""
    return [v for v in verdicts if v.advisory_failure]
