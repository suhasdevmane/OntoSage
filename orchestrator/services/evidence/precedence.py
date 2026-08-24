# -*- coding: utf-8 -*-
"""Which source wins when two of them disagree? (V6-T21)

Rule R-7, stated near-verbatim in the PhD, RS and AO catalogues: *bookings, access events,
timetables and alarms come from authorised systems, never from environmental inference.*

Today nothing stops an occupancy sensor contradicting the booking system in an answer about
availability. Both are real evidence; they are not equal evidence, and the failure is not that
the sensor is wrong — it is that the sensor is answering a question it cannot answer. A room
with nobody in it is not an available room, and the booking register is the only thing that
knows which it is.

**Three tiers, ordered, declared in config** (`evidence_policy.yaml: source_precedence`):

    authoritative   a system of record for the claim — booking, access control, timetable,
                    the compliance register, an alarm panel
    measurement     a sensor reading, or a calculation over sensor readings
    inference       anything derived without measuring the thing itself

**A lower tier never OVERRIDES a higher one — and never silently AGREES with it either.**
Silent agreement is the subtler error: reporting only the authoritative value while a sensor
disagrees hides a real fault (a booking says occupied, the room is empty — that is worth
knowing, and it is exactly how a no-show is detected). So a disagreement is REPORTED, with the
authoritative value leading.

**Absence of an authoritative source is not permission to substitute one.** When a claim needs
a system of record the building has not connected, the honest outcome is the decline that names
it — which is what :mod:`permission_guard` does with this module's verdict.

Pure and I/O-free, like every other decision module here: it takes source kinds the caller
already holds. Deciding tiers from prose, or from which lane happened to answer first, would
put the ordering back into the least auditable place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: Tier ranks. Higher wins. Values are spaced so a building may declare an intermediate tier in
#: config without renumbering these.
RANK: Dict[str, int] = {"authoritative": 30, "measurement": 20, "inference": 10, "unknown": 0}

#: Fallback mapping from an EvidenceSource.kind to a tier, used when the policy declares none.
#: Deliberately conservative: an unrecognised kind is `unknown`, which can never outrank
#: anything and can never satisfy a claim that demands authority.
_DEFAULT_KIND_TIER: Dict[str, str] = {
    "authoritative": "authoritative",
    "register": "authoritative",
    "booking": "authoritative",
    "timetable": "authoritative",
    "access_control": "authoritative",
    "alarm": "authoritative",
    "sensor": "measurement",
    "document": "authoritative",  # a policy document IS the system of record for a policy
    "human_report": "inference",  # a person's account is evidence, not a measurement
}


@dataclass
class SourceClaim:
    """One source's answer to the same question, with the identity to name it."""

    source_id: str
    tier: str
    value: Optional[float] = None
    label: str = ""
    kind: str = ""

    @property
    def rank(self) -> int:
        return RANK.get(self.tier, 0)

    def describe(self) -> str:
        name = self.label or self.source_id.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        val = "" if self.value is None else f" ({self.value:g})"
        return f"{name}{val}"


@dataclass
class PrecedenceVerdict:
    """Which tier answered, and whether a lower tier disagreed with it."""

    winning_tier: str = "unknown"
    winner: Optional[SourceClaim] = None
    overridden: List[SourceClaim] = field(default_factory=list)
    disagreement: bool = False
    reason: str = ""

    @property
    def has_authority(self) -> bool:
        return self.winning_tier == "authoritative"

    def describe(self) -> str:
        """The sentence an answer uses when tiers disagree. Empty when they do not."""
        if not self.disagreement or self.winner is None:
            return ""
        others = "; ".join(c.describe() for c in self.overridden)
        return (
            f"The {self.winning_tier} source {self.winner.describe()} is reported here. "
            f"Lower-tier evidence disagrees: {others}. The disagreement is stated rather than "
            "resolved, because a sensor cannot overrule a system of record — and a mismatch "
            "between them is itself worth knowing."
        )


def tier_for_kind(kind: str, declared: Optional[Dict[str, str]] = None) -> str:
    """The tier a source kind belongs to — policy first, conservative default second."""
    k = (kind or "").strip().lower()
    if declared and k in declared:
        return str(declared[k])
    return _DEFAULT_KIND_TIER.get(k, "unknown")


def resolve(claims: Sequence[SourceClaim], tolerance: Optional[float] = None) -> PrecedenceVerdict:
    """Apply the ordering to competing claims about one thing.

    ``tolerance`` is the numeric agreement window for this modality, when the claims carry
    values. Without one, two different numbers are reported as a disagreement rather than
    judged — the same rule the conflict module follows, and for the same reason: an
    undeclared tolerance means nobody has said how close is close enough.
    """
    ranked = sorted([c for c in claims if c], key=lambda c: -c.rank)
    if not ranked:
        return PrecedenceVerdict(reason="no sources contributed")
    winner = ranked[0]
    lower = [c for c in ranked[1:] if c.rank < winner.rank]

    verdict = PrecedenceVerdict(winning_tier=winner.tier, winner=winner)
    if not lower:
        verdict.reason = f"only {winner.tier} evidence contributed"
        return verdict

    # A lower tier is only a DISAGREEMENT when it actually says something different. Two
    # sources agreeing is the ordinary case and must not be narrated as a conflict.
    differing = []
    for c in lower:
        if c.value is None or winner.value is None:
            continue
        if tolerance is None or abs(c.value - winner.value) > tolerance:
            differing.append(c)
    verdict.overridden = differing
    verdict.disagreement = bool(differing)
    verdict.reason = (
        f"{winner.tier} evidence leads; {len(differing)} lower-tier source(s) disagree"
        if differing
        else f"{winner.tier} evidence leads; lower-tier sources agree"
    )
    return verdict


def claims_from_sources(
    sources: Sequence, values: Optional[Dict[str, float]] = None, declared: Optional[Dict] = None
) -> List[SourceClaim]:
    """Lift EvidenceSource objects into claims. Unknown kinds keep the `unknown` tier."""
    out: List[SourceClaim] = []
    vals = values or {}
    for s in sources or []:
        sid = str(getattr(s, "source_id", "") or "")
        if not sid:
            continue
        kind = str(getattr(s, "kind", "") or "")
        out.append(
            SourceClaim(
                source_id=sid,
                tier=tier_for_kind(kind, declared),
                value=vals.get(sid),
                kind=kind,
            )
        )
    return out


__all__ = [
    "RANK",
    "PrecedenceVerdict",
    "SourceClaim",
    "claims_from_sources",
    "resolve",
    "tier_for_kind",
]
