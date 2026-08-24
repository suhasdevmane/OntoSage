# -*- coding: utf-8 -*-
"""Physical state is not entitlement (V6-T22).

Rule R-8, given in the PhD catalogue as a list of four inference chains. Each is a sentence a
fluent assistant produces naturally, and each is a real-world harm:

    empty      is not  available   — telling someone a booked room is free
    open       is not  accessible  — sending a wheelchair user to a door that happens to be ajar
    quiet      is not  private     — assuring someone a conversation cannot be overheard
    presence   is not  permission  — inferring who is allowed somewhere from who is there

The common shape: a **measurement** answering a question only a **system of record** can
answer. So this guard is the consumer of :mod:`precedence` — it fires when an entitlement
claim rests on evidence below the authoritative tier.

**Why deterministic rather than a prompt instruction.** BUG-213 in this repository: the model
emitted an intent that existed in no registry, and because nothing validated it, it bypassed
every deterministic rule. A safety property that depends on model output being well-formed is
not a safety property. The claim shapes below are matched against the QUESTION, which the
system controls, not against the answer, which it does not.

**The decline names the route.** "I can't tell you whether it's free" is unhelpful and slightly
insulting; "occupancy sensors show nobody in it, but availability comes from the booking
system, which this building has not connected — check the room booking portal" tells the
person what to do and tells the estate what to connect. R-9's remedy discipline applied to
entitlement.

Pure and I/O-free. The caller supplies the claim shape and what tiers were available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EntitlementClaim:
    """One kind of claim that requires authority, and what it must not be inferred from."""

    kind: str
    #: What the question is asking to be told.
    asks: str
    #: The physical property a sensor could measure that LOOKS like an answer.
    physical_proxy: str
    #: The system of record that can actually answer it.
    authority: str
    #: What to tell the user when no authoritative source is connected.
    route: str


#: The four chains, as claim types rather than building facts — which is what makes this
#: building-agnostic: every building has availability, access, privacy and permission
#: questions, and none of them can be answered from a sensor.
CHAINS: Dict[str, EntitlementClaim] = {
    "availability": EntitlementClaim(
        kind="availability",
        asks="whether a space is free to use",
        physical_proxy="occupancy or motion",
        authority="the booking or room-reservation system",
        route="check the room booking system, which is the only record of what is reserved",
    ),
    "access": EntitlementClaim(
        kind="access",
        asks="whether someone may enter, or whether a route is usable",
        physical_proxy="a door contact or a path being physically open",
        authority="access control, or a verified accessibility survey",
        route="check access control for entitlement, and the accessibility register for "
        "verified step-free status",
    ),
    "privacy": EntitlementClaim(
        kind="privacy",
        asks="whether a space is private or a conversation confidential",
        physical_proxy="a low noise level or an empty room",
        authority="the room's declared use and the building's privacy policy",
        route="check the space's declared classification; quietness is not confidentiality",
    ),
    "permission": EntitlementClaim(
        kind="permission",
        asks="whether a person is allowed to do or be somewhere",
        physical_proxy="who is currently present",
        authority="the authorisation system for that space or action",
        route="check the authorisation record; who is present is not who is permitted",
    ),
}

#: Question shapes that ASK for an entitlement. Matched on the question, never the answer.
#:
#: The bounded gap excludes ? and ! but NOT the full stop: room identifiers are dotted in
#: this estate and in most others ("is room 2.14 free", "is the route to 3.02 step-free"),
#: so a class excluding '.' silently failed to match nearly every real question of this
#: shape while passing on the contrived ones. The 40-character cap is what keeps a pattern
#: from running across a clause.
#:
#: Bounded and specific: "is room 2.14 free" is an availability claim, while "is the corridor
#: clear of obstructions" is a physical question about the same word and must not be caught.
_PATTERNS: Sequence[tuple] = (
    (
        "availability",
        re.compile(
            # "step-free" contains "free" and would otherwise make every accessibility
            # question an availability claim — handing the reader the booking system when
            # what they need is the accessibility register. The lookbehinds are the whole
            # difference between a useful route and a confidently wrong one.
            r"\b(?:is|are)\b[^?!]{0,40}\b(?:(?<!step-)(?<!step )free|available|vacant"
            r"|unbooked|open)\b"
            r"|\b(?:can|could|may)\s+i\s+(?:use|book|have|take)\b"
            r"|\bwhich\b[^?!]{0,40}\b(?:free|available|unbooked)\b"
            r"|\bis\s+(?:it|this|that)\s+(?:free|available|taken|booked)\b",
            re.I,
        ),
    ),
    (
        "access",
        re.compile(
            r"\b(?:can|could|am\s+i\s+allowed\s+to|may)\s+i\s+(?:get\s+in|enter|access)\b"
            r"|\bis\b[^?!]{0,40}\b(?:step[- ]free|wheelchair[- ]accessible|accessible)\b"
            r"|\b(?:can|could)\s+(?:i|we|they)\s+get\s+(?:in|into|through)\b",
            re.I,
        ),
    ),
    (
        "privacy",
        re.compile(
            r"\bis\b[^?!]{0,40}\b(?:private|confidential|soundproof|overheard)\b"
            r"|\bcan\s+(?:anyone|someone|others?|people)\s+(?:hear|overhear|listen)\b"
            r"|\bsomewhere\s+private\b",
            re.I,
        ),
    ),
    (
        "permission",
        re.compile(
            r"\b(?:am|are)\s+(?:i|we|they)\s+(?:allowed|permitted|authorised|authorized)\b"
            r"|\bwho\s+(?:is|are)\s+(?:allowed|permitted|authorised|authorized)\b"
            r"|\bdo\s+i\s+need\s+(?:permission|authorisation|authorization|a\s+key|access)\b",
            re.I,
        ),
    ),
)

#: Phrases that make an otherwise-entitlement-shaped question a question about the RECORD
#: itself, which the authoritative lane answers properly and this guard must not intercept.
_ABOUT_THE_RECORD = re.compile(
    r"\b(?:booking|booked|reserved|reservation|timetable|schedule|access control|"
    r"permit|policy|register)\b",
    re.I,
)


def detect_claim(question: str) -> Optional[EntitlementClaim]:
    """Which entitlement, if any, this question asks to be told. None for everything else."""
    q = (question or "").strip()
    if not q:
        return None
    for kind, pattern in _PATTERNS:
        if pattern.search(q):
            return CHAINS[kind]
    return None


def names_its_authority(question: str) -> bool:
    """True when the question is ABOUT the record rather than asking to infer around it.

    "Is room 2.14 booked this afternoon?" is a booking-system question and belongs to the
    events lane; intercepting it would refuse the very question the authority can answer.
    """
    return bool(_ABOUT_THE_RECORD.search(question or ""))


def assess(
    question: str,
    has_authoritative_source: bool,
    available_tiers: Sequence[str] = (),
) -> Optional[Dict[str, str]]:
    """Is this an entitlement claim resting on evidence that cannot support it?

    Returns None when there is nothing to guard — no entitlement asked, or an authoritative
    source answered it. Otherwise a dict with the reason and the route, for the gate and the
    narration to use.
    """
    claim = detect_claim(question)
    if claim is None:
        return None
    if has_authoritative_source or "authoritative" in set(available_tiers):
        return None
    if names_its_authority(question):
        # Asking about the record itself. The right outcome is the authoritative lane's
        # honest answer (including "that system is not connected"), not this guard's refusal.
        return None
    return {
        "kind": claim.kind,
        "reason": (
            f"this asks {claim.asks}, which only {claim.authority} can establish; the "
            f"available evidence is {claim.physical_proxy}, and {claim.physical_proxy} is "
            f"not {claim.kind}"
        ),
        "remedy": claim.route,
    }


def unlicensed_kinds(question: str) -> List[str]:
    """Every chain the question triggers. Used by the trap bank to check coverage."""
    return [kind for kind, pattern in _PATTERNS if pattern.search(question or "")]


__all__ = [
    "CHAINS",
    "EntitlementClaim",
    "assess",
    "detect_claim",
    "names_its_authority",
    "unlicensed_kinds",
]
