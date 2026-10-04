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
from typing import Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: Tier ranks. Higher wins. Values are spaced so a building may declare an intermediate tier in
#: config without renumbering these.
#:
#: ``document_derived`` sits between authority and measurement, and the gap on each side is
#: the point (V7-T19). A register LIFTED from a document beats a sensor reading for a
#: records question — a transcribed permit log still knows what a CO2 sensor cannot — but
#: it loses to authored TTL, because a document is a statement ABOUT a system of record and
#: not the record itself. Without the lower rank a stale Markdown table silently outranks a
#: live register, which is exactly what BUG-194 was: a GUI policy edit shadowed by an old
#: copy, with the file right, the API wrong, and the editor reporting success.
RANK: Dict[str, int] = {
    "authoritative": 30,
    "document_derived": 25,
    "measurement": 20,
    "inference": 10,
    "unknown": 0,
}

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
    # ...but a REGISTER lifted out of a document is a transcription of one, and the two
    # must not rank alike. The policy document says what the policy is; the lifted permit
    # row says what someone wrote down about the permit register, and the register can
    # have moved on since.
    "document_derived": "document_derived",
    "human_report": "inference",  # a person's account is evidence, not a measurement
}


@dataclass
class SourceClaim:
    """One source's answer to the same question, with the identity to name it.

    ``supersedes`` and ``effective_from`` (E4/E6, QA-trial plan 2026-10-04) are the ONLY
    evidence `resolve()` may use to pick between two claims tied at the same tier — never
    arrival order in the input sequence. Both default to None/"" because, before E6 lands a
    reader that populates them from the schema's own ``ontosage:supersedes`` and
    ``ontosage:effectiveFrom`` predicates, no claim carries either, and a same-tier tie is
    then correctly reported as UNRESOLVED rather than silently decided by whichever claim
    happened to be built first.
    """

    source_id: str
    tier: str
    value: Optional[float] = None
    label: str = ""
    kind: str = ""
    #: The source_id of another same-tier claim this one explicitly supersedes, or "".
    supersedes: str = ""
    #: ISO date/datetime string, or "" when unknown. A later value wins a same-tier tie
    #: that no `supersedes` link settles.
    effective_from: str = ""

    @property
    def rank(self) -> int:
        return RANK.get(self.tier, 0)

    def describe(self) -> str:
        name = self.label or self.source_id.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        val = "" if self.value is None else f" ({self.value:g})"
        return f"{name}{val}"


@dataclass
class PrecedenceVerdict:
    """Which tier answered, and whether a lower tier — or an equal one — disagreed with it."""

    winning_tier: str = "unknown"
    winner: Optional[SourceClaim] = None
    overridden: List[SourceClaim] = field(default_factory=list)
    disagreement: bool = False
    reason: str = ""
    #: E4: TWO claims at the WINNING tier disagreed on the value. Distinct from
    #: `disagreement`, which is a LOWER tier contradicting the winner — this is the one
    #: path that can produce a confidently-wrong answer rather than a missing disclosure,
    #: because sorting by tier alone has no way to represent "two systems of record,
    #: same rank, different values" at all.
    same_tier_disagreement: bool = False
    #: How a same-tier tie was settled: "" (no tie), "supersedes", "effective_from", or
    #: "unresolved" (tied, no evidence to settle it — the winner is still ONE of them,
    #: picked by rank-stable order, and `same_tier_disagreement` says that pick is not
    #: backed by evidence).
    tiebreak: str = ""
    #: The other same-tier claim(s) that disagreed with the winner, when unresolved or
    #: resolved by evidence (kept separate from `overridden`, which is lower-tier only).
    tied_with: List[SourceClaim] = field(default_factory=list)

    @property
    def has_authority(self) -> bool:
        return self.winning_tier == "authoritative"

    def describe(self) -> str:
        """The sentence an answer uses when tiers (or tied sources) disagree. Empty when
        nothing disagreed."""
        if self.same_tier_disagreement and self.winner is not None:
            others = "; ".join(c.describe() for c in self.tied_with)
            if self.tiebreak == "unresolved":
                return (
                    f"Two {self.winning_tier} sources disagree and neither states which "
                    f"supersedes the other: {self.winner.describe()} is shown; {others} "
                    "also claims this. This is not resolved — it is reported as a "
                    "disagreement between equally-ranked sources."
                )
            return (
                f"{self.winner.describe()} is the current {self.winning_tier} value "
                f"({self.tiebreak.replace('_', ' ')}); the superseded source disagreed: "
                f"{others}."
            )
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

    top_rank = ranked[0].rank
    tied = [c for c in ranked if c.rank == top_rank]
    winner, tied_with, tiebreak = _settle_tie(tied)
    lower = [c for c in ranked[1:] if c.rank < winner.rank]

    verdict = PrecedenceVerdict(winning_tier=winner.tier, winner=winner)
    if tied_with:
        verdict.same_tier_disagreement = True
        verdict.tiebreak = tiebreak
        verdict.tied_with = tied_with
    if not lower:
        verdict.reason = (
            f"only {winner.tier} evidence contributed; {len(tied_with)} same-tier source(s) "
            f"disagree ({tiebreak})"
            if tied_with
            else f"only {winner.tier} evidence contributed"
        )
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
    if tied_with:
        verdict.reason += f"; {len(tied_with)} same-tier source(s) also disagree ({tiebreak})"
    return verdict


def _settle_tie(tied: List[SourceClaim]) -> Tuple[SourceClaim, List[SourceClaim], str]:
    """Pick the winner among claims tied at the top rank, and say how (E4).

    Evidence order, never arrival order: an explicit ``supersedes`` link first, then the
    later ``effective_from``. A tie this cannot settle still returns a winner — one of the
    tied claims has to be reported as THE value — but marks it "unresolved" so the caller
    knows that pick carries no evidentiary weight, rather than quietly presenting whichever
    claim happened to sort first as if it had been decided.
    """
    if len(tied) <= 1:
        return tied[0], [], ""

    by_id = {c.source_id: c for c in tied}
    # 1) An explicit supersedes link among the tied claims.
    for c in tied:
        if c.supersedes and c.supersedes in by_id and by_id[c.supersedes] is not c:
            disagreeing = [
                o
                for o in tied
                if o is not c and (o.value is None or c.value is None or o.value != c.value)
            ]
            if disagreeing:
                return c, disagreeing, "supersedes"

    # 2) The values may simply agree — not every tie is a disagreement.
    values = {c.value for c in tied if c.value is not None}
    if len(values) <= 1:
        return tied[0], [], ""

    # 3) A later effective_from, when every tied claim states one.
    if all(c.effective_from for c in tied):
        newest = max(tied, key=lambda c: c.effective_from)
        disagreeing = [c for c in tied if c is not newest and c.value != newest.value]
        if disagreeing:
            return newest, disagreeing, "effective_from"
        return newest, [], ""

    # 4) No evidence to settle it. Still differing values -> genuinely unresolved.
    winner = tied[0]
    disagreeing = [c for c in tied[1:] if c.value != winner.value]
    return winner, disagreeing, "unresolved" if disagreeing else ""


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
