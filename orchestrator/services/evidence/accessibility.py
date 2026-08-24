# -*- coding: utf-8 -*-
"""Accessibility is a hard filter, not a preference (V6-T38).

Rule R-11, stated in three of the six stakeholder catalogues: *"step-free routes, adjustable
furniture, accessible entrances must be verified; if route or furniture status is unverified,
do not label it step-free/accessible and recommend neither option if both fail."*

**This is the highest-consequence answer in the whole question bank.** Every other failure
mode here produces a wrong number; this one strands a person. An unverified step-free claim
sends a wheelchair user to a route that may end at a staircase, and the cost of being wrong
is not measured in credibility.

So the design is deliberately asymmetric, and each choice rejects something reasonable-
sounding:

* **Filter, not rank.** Ranking accessible options higher still RETURNS the inaccessible
  ones, and a ranked list is read as a list of answers. A hard filter removes them.
* **Unverified is excluded, not "included with a caveat".** A caveat attached to a route is
  read after the person has decided to take it, if at all.
* **An empty result is a valid, explained answer.** "No verified step-free route exists
  between these points; contact Estates on x1234" is far better than a route that might work,
  and it is what the catalogues explicitly ask for.
* **A lift out of service invalidates every route that depends on it** -- a verified route
  through a failed lift is not a verified route today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AccessibilityRequirement:
    """What the asker actually needs. Absent means not required, never "prefer"."""

    step_free: bool = False
    kinds: Sequence[str] = field(default_factory=tuple)  # e.g. hearing_loop, accessible_wc

    @property
    def any_requirement(self) -> bool:
        return self.step_free or bool(self.kinds)


@dataclass
class AccessibleOption:
    """One candidate route, space or facility, with its verification state."""

    option_id: str
    label: str = ""
    #: True only when someone inspected it and confirmed. Absent/False = UNVERIFIED, which is
    #: NOT a synonym for inaccessible -- but it is a synonym for "may not be presented as
    #: accessible".
    verified: bool = False
    verified_on: Optional[str] = None
    kinds: Sequence[str] = field(default_factory=tuple)
    #: Assets this option depends on (lifts, powered doors). A failure in any of them
    #: invalidates the option regardless of its verification record.
    depends_on: Sequence[str] = field(default_factory=tuple)


@dataclass
class FilterResult:
    admissible: List[AccessibleOption] = field(default_factory=list)
    rejected: List[tuple] = field(default_factory=list)  # (option, reason)

    @property
    def has_answer(self) -> bool:
        return bool(self.admissible)

    def explain_empty(self, assistance_contact: str = "") -> str:
        """Why nothing qualified, and what to do instead.

        An empty result must never be silent. The catalogues are explicit that when both
        options fail, the system recommends neither AND says so -- because somebody is
        standing there waiting to move.
        """
        if self.has_answer:
            return ""
        if not self.rejected:
            return "No route or facility of that kind is recorded for this building."
        reasons = sorted({r for _, r in self.rejected})
        head = (
            f"None of the {len(self.rejected)} candidate(s) can be confirmed accessible: "
            + "; ".join(reasons)
            + "."
        )
        if assistance_contact:
            return head + f" For assistance, contact {assistance_contact}."
        return head + (
            " I will not suggest an unverified route, because an accessibility claim that "
            "turns out to be wrong can leave somebody stranded."
        )


def filter_options(
    options: Sequence[AccessibleOption],
    requirement: AccessibilityRequirement,
    out_of_service: Optional[Set[str]] = None,
) -> FilterResult:
    """Keep only options that can be CONFIRMED to meet the requirement."""
    result = FilterResult()
    blocked = out_of_service or set()

    if not requirement.any_requirement:
        # Nothing was required, so nothing is filtered. The hard filter must not quietly
        # narrow ordinary questions that never mentioned accessibility.
        result.admissible = list(options)
        return result

    for opt in options:
        failed = _reject_reason(opt, requirement, blocked)
        if failed:
            result.rejected.append((opt, failed))
        else:
            result.admissible.append(opt)
    return result


def _reject_reason(
    opt: AccessibleOption, req: AccessibilityRequirement, blocked: Set[str]
) -> Optional[str]:
    down = [d for d in opt.depends_on if d in blocked]
    if down:
        # Checked BEFORE verification: a verified route through a failed lift is not a
        # verified route today, and the verification record is the thing most likely to
        # mislead here because it was true when it was written.
        return (
            f"{_name(opt)} depends on {', '.join(_short(d) for d in down)}, which is out of service"
        )

    if not opt.verified:
        return f"{_name(opt)} has not been verified as accessible"

    missing = [k for k in req.kinds if k not in set(opt.kinds)]
    if missing:
        return f"{_name(opt)} does not provide {', '.join(missing)}"

    return None


def _name(opt: AccessibleOption) -> str:
    return opt.label or _short(opt.option_id)


def _short(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if iri else "an unnamed asset"
