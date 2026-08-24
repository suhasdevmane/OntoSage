# -*- coding: utf-8 -*-
"""Saying which of the user's criteria the answer could not use (V6-T39).

Rule R-9, from the PhD-student and research-staff catalogues:
*"[criterion] was omitted because [missing / stale / restricted] source"*.

**Why this is a correctness feature and not a courtesy.** Asked for the quietest, warmest
room with a free socket, a system that silently drops "quietest" answers a different question
and looks complete doing it. The user gets a confident ranking, has no way to see that a third
of their request was discarded, and acts on it. Dropping a criterion is not a smaller answer
-- it is a different one.

**Why the reason must be specific.** `OmissionReason` distinguishes five causes where the
template names three, and the extra precision earns its place: *restricted* and *missing* look
identical to a user and lead to opposite actions. Telling someone the data does not exist,
when in truth they are not cleared to see it, is both false and a dead end -- it hides the
governance route that would actually get them the answer. The two refinements
(NOT_INSTRUMENTED, INADEQUATE_COVERAGE) render with their own wording and are reported in the
template's shape.

**Ordering is a design decision, not an implementation detail.** A criterion can be absent for
several reasons at once, and which one is reported changes what the user does next. The order
in :func:`classify` is argued there.

Pure and injectable throughout: the facts arrive from the caller, which is the only party that
knows whether it consulted the graph, the adapter or the PDP. Nothing here queries anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from shared.models import OmissionReason, OmittedCriterion
from shared.utils import get_logger

logger = get_logger(__name__)

#: How each reason is worded in the answer. The three the catalogues name keep their exact
#: words; the two refinements get wording that is specific about the same shape of gap.
_WORDING: Dict[OmissionReason, str] = {
    OmissionReason.MISSING: "a missing source",
    OmissionReason.STALE: "a stale source",
    OmissionReason.RESTRICTED: "a restricted source",
    OmissionReason.NOT_INSTRUMENTED: "the lack of any such sensor in this building",
    OmissionReason.INADEQUATE_COVERAGE: "a source that does not cover the place asked about",
}

#: The remedy that actually resolves each cause. A stated gap with no route out reads as an
#: excuse; these say who or what changes the answer.
_REMEDY: Dict[OmissionReason, str] = {
    OmissionReason.MISSING: "Connecting readings for it would let this criterion be scored.",
    OmissionReason.STALE: "The sensor exists but has stopped reporting; restoring it restores "
    "this criterion.",
    OmissionReason.RESTRICTED: "A user with the necessary permission can see it; this is an "
    "access decision, not a gap in the data.",
    OmissionReason.NOT_INSTRUMENTED: "Instrumenting it, then registering the readings, would "
    "make this answerable.",
    OmissionReason.INADEQUATE_COVERAGE: "A sensor in the space itself would let this criterion "
    "be scored there rather than nearby.",
}


@dataclass
class CriterionFacts:
    """What the caller knows about one requested criterion. All optional, all asserted."""

    #: The user's own words, kept verbatim -- "quiet" is what they asked for, not "noise".
    criterion: str
    #: The modality it resolved to, or "" when the question's term resolved to nothing.
    modality: str = ""
    #: Whether the building declares this modality at all.
    instrumented: bool = True
    #: Whether the requester is permitted to see it.
    permitted: bool = True
    #: Whether any reading was actually retrieved.
    has_readings: bool = True
    #: Whether what was retrieved is too old to use.
    is_stale: bool = False
    #: Whether the only evidence available is a proxy for the place asked about.
    proxy_only: bool = False
    #: Free-text specifics the caller wants carried through to the user.
    detail: str = ""


def classify(facts: CriterionFacts) -> Optional[OmissionReason]:
    """Why this criterion could not be used, or None if it could.

    The order below is the argued part:

    1. **Not instrumented** first. When the building has no such sensor, that is the whole
       truth and the only real remedy. Reporting "restricted" here would send the user to a
       data owner who has nothing to release.
    2. **Restricted** next, and specifically *before* missing. A permission failure and an
       absent reading look identical from outside and lead to opposite actions; the enum's own
       docstring makes this distinction the reason it exists.
    3. **Missing**, then **stale**: nothing recorded, versus recorded but too old. Both are
       gaps in the same stream, and the second implies the sensor exists -- which is a
       different remedy and a different conversation with the estate team.
    4. **Inadequate coverage** last, because it is the weakest failure: a reading exists and is
       current, and only its location disqualifies it. It is still an omission -- Master 8
       forbids substituting a proxy for a room-level claim -- but it is the one the user is
       most likely to want reported as context rather than as absence.
    """
    if not facts.instrumented or not facts.modality:
        return OmissionReason.NOT_INSTRUMENTED
    if not facts.permitted:
        return OmissionReason.RESTRICTED
    if not facts.has_readings:
        return OmissionReason.MISSING
    if facts.is_stale:
        return OmissionReason.STALE
    if facts.proxy_only:
        return OmissionReason.INADEQUATE_COVERAGE
    return None


def omission_for(facts: CriterionFacts) -> Optional[OmittedCriterion]:
    """One structured omission, or None when the criterion was usable."""
    reason = classify(facts)
    if reason is None:
        return None
    detail = facts.detail.strip() or _REMEDY[reason]
    return OmittedCriterion(criterion=facts.criterion, reason=reason, detail=detail)


def collect(all_facts: Iterable[CriterionFacts]) -> List[OmittedCriterion]:
    """Every omission among the requested criteria, in the order they were requested.

    Request order, not severity order: the user's own sequence is the one they can check
    their question against, and re-sorting would make a missing criterion harder to spot in
    the list precisely when there are several.
    """
    out: List[OmittedCriterion] = []
    for facts in all_facts:
        omission = omission_for(facts)
        if omission is not None:
            out.append(omission)
    return out


def render(omissions: Sequence[OmittedCriterion]) -> str:
    """The catalogues' template, one line per omission. Empty string when nothing was dropped.

    Empty rather than "all criteria were used": a reassurance printed on every answer is
    noise, and noise is what makes the one line that matters easy to miss.
    """
    lines = [_render_one(o) for o in omissions if o.criterion]
    if not lines:
        return ""
    head = (
        "**Not included in this answer**"
        if len(lines) > 1
        else "**One requested criterion was not included**"
    )
    return "\n".join([head, ""] + [f"- {line}" for line in lines])


def summarise(omissions: Sequence[OmittedCriterion]) -> str:
    """A one-line form, for places with no room for a list."""
    if not omissions:
        return ""
    names = ", ".join(o.criterion for o in omissions if o.criterion)
    return f"{names} could not be included in this ranking; see the evidence record for why."


def _render_one(o: OmittedCriterion) -> str:
    wording = _WORDING.get(o.reason, "an unavailable source")
    detail = (o.detail or "").strip()
    line = f"**{o.criterion}** was omitted because of {wording}."
    return f"{line} {detail}".strip() if detail else line


# -- deliberation integration -------------------------------------------------


def facts_from_ranking(
    requested: Sequence[Dict[str, str]],
    scored_modalities: Iterable[str],
    *,
    declared_modalities: Iterable[str] = (),
    restricted_modalities: Iterable[str] = (),
    stale_modalities: Iterable[str] = (),
    proxy_modalities: Iterable[str] = (),
) -> List[CriterionFacts]:
    """Turn what a ranking lane already tracks into criterion facts.

    `requested` is the lane's own constraint list -- each entry carrying the user's phrase and
    the modality it resolved to -- and `scored_modalities` is what the ranking actually used.
    Everything else narrows the reason. The difference between the first two is the omission;
    the rest of the arguments only decide how it is explained.

    Deliberately takes plain dicts and strings rather than the dossier types, so this stays
    testable without constructing an execution outcome, and so a second lane can reuse it
    without depending on the deliberation package.
    """
    scored = {m for m in scored_modalities if m}
    declared = {m for m in declared_modalities if m}
    restricted = {m for m in restricted_modalities if m}
    stale = {m for m in stale_modalities if m}
    proxy = {m for m in proxy_modalities if m}

    out: List[CriterionFacts] = []
    for entry in requested:
        modality = (entry.get("modality") or "").strip()
        phrase = (entry.get("phrase") or modality or "").strip()
        if not phrase:
            continue
        if modality and modality in scored and modality not in proxy:
            continue  # used, and used properly
        out.append(
            CriterionFacts(
                criterion=phrase,
                modality=modality,
                # An empty declared set means "not stated", not "nothing is instrumented".
                # Assuming the latter would report every criterion as uninstrumented on any
                # caller that has not wired the modality list yet -- a confident, wrong answer
                # about the building rather than about the data.
                instrumented=bool(modality) and (not declared or modality in declared),
                permitted=modality not in restricted,
                has_readings=modality in scored or modality in proxy or modality in stale,
                is_stale=modality in stale,
                proxy_only=modality in proxy,
                detail=(entry.get("detail") or "").strip(),
            )
        )
    return out
