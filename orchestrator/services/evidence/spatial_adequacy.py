# -*- coding: utf-8 -*-
"""Is this evidence actually about the place the question asked about? (V6-T13)

The Master Report's non-substitution rule (section 8) in code: *"never silently substitute
the nearest corridor observation for a missing room observation -- identify the proxy,
explain why it is limited, and decline a room-level judgement when the proxy is inadequate;
a corridor value is not a room value."*

The existing referent gate already refuses an UNKNOWN referent and refuses to swap one
measurement type for another. It does not cover the case the supervisors test hardest, and
the one that actually occurs on a real building: **the room exists, a sensor of the right
kind exists, just not in that room.** That is what this module decides.

**Graded, not binary.** The report explicitly permits proxy data *labelled as context*, so
collapsing this to has-sensor/no-sensor would be less useful AND less honest than the rule
it implements. "The corridor outside 2.15 read 900 ppm at 14:02; I have no sensor inside
2.15" is a good answer. "900 ppm" is a lie. "I don't know" throws away real evidence.

**Never geometric.** Proximity is not evidence of what a sensor measures -- ductwork is.
Allowing nearness to imply attribution is exactly how BUG-189 attributed one room's reading
to a corridor the building did not have, so distance appears nowhere in this file.

The decision logic is deliberately separated from graph access: :func:`classify` is pure and
takes already-fetched facts, so every branch is unit-testable without a live GraphDB, and
the same facts can be replayed in a fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set

from shared.models import SpatialAdequacy
from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PointFacts:
    """What the graph says about one point's spatial relationship to a space.

    Everything here is an ASSERTED fact. There is deliberately no distance field: adding one
    would invite exactly the inference this module exists to prevent.
    """

    point_iri: str
    #: ontosage:environmentalBoundary -- the space this point actually MEASURES. Authoritative
    #: when present, because it is the only property that distinguishes a duct-mounted sensor
    #: from the room it happens to sit in.
    environmental_boundary: Optional[str] = None
    #: brick:isPointOf / hasLocation -- the space that CONTAINS the point.
    containing_space: Optional[str] = None
    #: Spaces reached through a served zone whose zoneValidated is true.
    validated_zone_spaces: Sequence[str] = field(default_factory=tuple)
    #: Spaces reached through a served zone that is NOT validated. Kept separate on purpose:
    #: an unvalidated zone is proxy evidence, never coverage.
    unvalidated_zone_spaces: Sequence[str] = field(default_factory=tuple)
    #: Spaces sharing a parent with the point's own space (same floor, same wing).
    sibling_spaces: Sequence[str] = field(default_factory=tuple)


@dataclass
class AdequacyVerdict:
    grade: SpatialAdequacy
    #: Human-readable reason, used verbatim when a proxy has to be named in an answer.
    reason: str = ""
    #: The space the evidence is genuinely about, when that differs from the one asked for.
    evidence_space: Optional[str] = None

    @property
    def is_room_level(self) -> bool:
        """True when this evidence may carry a claim about the space itself."""
        return self.grade in (SpatialAdequacy.IN_ROOM, SpatialAdequacy.SERVED_ZONE)


def classify(target_space: str, facts: PointFacts) -> AdequacyVerdict:
    """Grade one point's evidence for one space. Pure; no I/O.

    Precedence, strongest first:

    1. **environmentalBoundary == target** -- the point declares it measures this space.
       Checked first because it is the only assertion that can OVERRIDE containment, and it
       exists precisely for sensors whose containing space is not what they measure.
    2. **environmentalBoundary names a DIFFERENT space** -- decisive in the negative. A
       sensor that declares it measures the corridor is not in-room evidence for the room,
       even if it is physically inside that room. Containment is not consulted after this,
       which is the whole point of having the property.
    3. **containing space == target** -- the ordinary case.
    4. **validated served zone** -- the single alternative the Master Report permits.
    5. **unvalidated zone, or a sibling space** -- proxy. Reportable as context, never as a
       room-level claim.
    6. otherwise **none**.
    """
    if not target_space:
        return AdequacyVerdict(SpatialAdequacy.NONE, "no space was resolved from the question")

    eb = facts.environmental_boundary
    if eb:
        if eb == target_space:
            return AdequacyVerdict(
                SpatialAdequacy.IN_ROOM,
                "the sensor declares this space as its environmental boundary",
                evidence_space=target_space,
            )
        # Decisive negative. Containment must NOT rescue this: a sensor sitting in a room
        # while measuring the corridor is corridor evidence, and treating it otherwise is
        # the substitution the rule forbids.
        return AdequacyVerdict(
            SpatialAdequacy.PROXY,
            f"the sensor measures {_short(eb)}, not the space asked about",
            evidence_space=eb,
        )

    if facts.containing_space and facts.containing_space == target_space:
        return AdequacyVerdict(
            SpatialAdequacy.IN_ROOM,
            "the sensor is located in this space",
            evidence_space=target_space,
        )

    if target_space in tuple(facts.validated_zone_spaces):
        return AdequacyVerdict(
            SpatialAdequacy.SERVED_ZONE,
            "this space is in a validated served zone for the sensor",
            evidence_space=target_space,
        )

    if target_space in tuple(facts.unvalidated_zone_spaces):
        return AdequacyVerdict(
            SpatialAdequacy.PROXY,
            "a served zone links these spaces, but the link is not validated",
            evidence_space=facts.containing_space,
        )

    if target_space in tuple(facts.sibling_spaces) or facts.containing_space:
        where = _short(facts.containing_space) if facts.containing_space else "elsewhere"
        # NOT "the nearest reading": this module has no notion of distance, so claiming
        # nearness would be an unsupported spatial assertion in the very text whose job is
        # to be precise about spatial support.
        return AdequacyVerdict(
            SpatialAdequacy.PROXY,
            f"the reading is from {where}, which is not the space asked about",
            evidence_space=facts.containing_space,
        )

    return AdequacyVerdict(
        SpatialAdequacy.NONE, "no sensor relates to this space", evidence_space=None
    )


def best_verdict(target_space: str, candidates: Sequence[PointFacts]) -> AdequacyVerdict:
    """The strongest grade available across several candidate points.

    Strongest rather than first: given an in-room sensor and a corridor one, the answer
    should use the in-room sensor. Order of arrival is a property of the query, not of the
    building, and letting it decide would make answers depend on SPARQL result ordering.
    """
    if not candidates:
        return AdequacyVerdict(SpatialAdequacy.NONE, "no sensor relates to this space")
    rank = {
        SpatialAdequacy.IN_ROOM: 3,
        SpatialAdequacy.SERVED_ZONE: 2,
        SpatialAdequacy.PROXY: 1,
        SpatialAdequacy.NONE: 0,
    }
    scored = [(classify(target_space, c), c) for c in candidates]
    best = max(rank[v.grade] for v, _ in scored)
    tied = [(v, c) for v, c in scored if rank[v.grade] == best]
    if len(tied) == 1:
        return tied[0][0]
    # Several candidates share the best grade -- typically two proxies in different spaces.
    # There is no principled "better proxy" available here: the only thing that could rank
    # them is distance, which this module refuses to consider. So the tie is broken
    # DETERMINISTICALLY by point identity rather than by list order. Order would make the
    # answer depend on SPARQL result ordering, which is the failure best_verdict exists to
    # prevent, and it would do so silently.
    return min(tied, key=lambda pair: pair[1].point_iri)[0]


def is_permitted(grade: SpatialAdequacy, scope: str, allowed: Sequence[str]) -> bool:
    """Whether policy lets an answer at this scope rest on this grade of evidence.

    `allowed` comes from EvidencePolicy.allowed_adequacy(scope) so the decision stays config-
    driven: a building that genuinely has only corridor coverage can widen it deliberately
    and visibly, rather than by a code change nobody reviews.
    """
    return grade.value in set(allowed)


def _short(iri: Optional[str]) -> str:
    if not iri:
        return "an unnamed space"
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
