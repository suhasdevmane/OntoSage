# -*- coding: utf-8 -*-
"""Turning gate verdicts into the sentences an answer has to carry (V6-T14/T30/T35).

Three related jobs, kept together because they share one principle: **a limitation is only
useful if it is stated in terms the reader can act on.**

* **T14 proxy labelling.** Master 8 requires the proxy to be identified and its limitation
  explained -- not silently used, and not silently dropped. *"The corridor outside 2.15 read
  900 ppm at 14:02; I have no sensor inside 2.15"* is a good answer. *"900 ppm"* is a lie.
  *"I don't know"* throws away real evidence.

* **T30 omission reasons.** *Missing*, *stale* and **restricted** are three different things
  with three different remedies. Collapsing restricted into missing tells a user that data
  does not exist when in fact they simply may not see it -- misleading, and it hides the
  governance route that would actually get it.

* **T35 not-assessable.** The reason and the remedy are what make a refusal a *correct
  answer* rather than a failure. Master 15.5 calls this the single most important design
  requirement, and a refusal with neither is indistinguishable from the system giving up.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from shared.models import (
    AnswerStatus,
    OmissionReason,
    OmittedCriterion,
    SpatialAdequacy,
)

#: Wording per omission reason. Each says what the user can DO, because a bare
#: "unavailable" leaves them unable to tell a broken sensor from a permission boundary.
_OMISSION_PHRASING = {
    OmissionReason.MISSING: "was omitted because no source for it is connected",
    OmissionReason.STALE: "was omitted because the only source for it has stopped reporting",
    OmissionReason.RESTRICTED: (
        "was omitted because it is restricted at your access level; it exists, and there is "
        "a formal route to request it"
    ),
    OmissionReason.NOT_INSTRUMENTED: "was omitted because this building does not measure it",
    OmissionReason.INADEQUATE_COVERAGE: (
        "was omitted because too little of the requested window was observed to report it"
    ),
}


def describe_omission(item: OmittedCriterion) -> str:
    """One line per omitted criterion, in the catalogues' own template."""
    base = _OMISSION_PHRASING.get(item.reason, "was omitted")
    detail = f" ({item.detail})" if item.detail else ""
    return f"**{item.criterion}** {base}{detail}."


def describe_omissions(items: Sequence[OmittedCriterion]) -> str:
    """A block naming everything the answer does NOT cover.

    Silently dropping a requested criterion answers a different question from the one asked,
    and looks complete doing it.
    """
    if not items:
        return ""
    lines = "\n".join(f"- {describe_omission(i)}" for i in items)
    return f"**Not covered by this answer:**\n{lines}"


def label_proxy(
    asked_about: str,
    proxy_space: Optional[str],
    reason: str,
    value_text: str = "",
    observed_at_text: str = "",
) -> str:
    """Name the proxy, report it as context, and decline the room-level claim (T14).

    The proxy is NAMED. A caveat like "this may not reflect the room" is unactionable,
    whereas "the corridor outside" lets the reader judge for themselves how much it tells
    them -- which is the difference between a hedge and an explanation.
    """
    where = _short(proxy_space) if proxy_space else "a nearby location"
    asked = _short(asked_about)
    head = f"I have no sensor inside **{asked}**."
    if value_text:
        when = f" at {observed_at_text}" if observed_at_text else ""
        return (
            f"{head} The nearest reading is from **{where}**{when}: {value_text}. "
            f"That is context, not a measurement of {asked} -- {reason}."
        )
    return f"{head} {reason.capitalize()}."


def describe_not_assessable(reason: str, remedy: str = "") -> str:
    """A refusal that is an ANSWER (T35).

    Reason plus remedy, always. Without them a refusal is indistinguishable from the system
    giving up, and a grader cannot tell a justified refusal from an unjustified one -- which
    is the distinction the whole scoring approach rests on.
    """
    if not reason:
        reason = "the available evidence does not support an answer to this question"
    text = f"**Not assessable.** {reason[0].upper()}{reason[1:]}."
    if remedy:
        text += f"\n\n**What would make this answerable:** {remedy}"
    return text


def status_badge(status: AnswerStatus) -> str:
    """A short, honest label for the top of an answer.

    Plain words, not jargon: a reader has to be able to tell a measurement from a forecast
    without knowing the Master Report's vocabulary.
    """
    return {
        AnswerStatus.OBSERVED: "Observed — measured directly",
        AnswerStatus.CALCULATED: "Calculated — computed from measurements",
        AnswerStatus.INFERRED: "Inferred — reasoned from related evidence, not measured",
        AnswerStatus.PREDICTED: "Predicted — a forecast, not an observation",
        AnswerStatus.RECOMMENDED: "Recommended — a suggested action",
        AnswerStatus.NOT_ASSESSABLE: "Not assessable — the evidence does not support an answer",
    }[status]


def adequacy_note(grade: SpatialAdequacy, reason: str = "") -> str:
    """One line stating how well the evidence matches the place asked about."""
    return {
        SpatialAdequacy.IN_ROOM: "",
        SpatialAdequacy.SERVED_ZONE: (
            "Measured by a sensor serving this space through a validated zone rather than "
            "inside it."
        ),
        SpatialAdequacy.PROXY: reason or "Based on a nearby sensor, not one in this space.",
        SpatialAdequacy.NONE: "No sensor covers this space.",
    }[grade]


def collect_omissions(
    requested: Sequence[str],
    used: Sequence[str],
    reason_for: Optional[dict] = None,
) -> List[OmittedCriterion]:
    """Everything asked for that the answer did not use (T30/T39 groundwork).

    Tracked structurally rather than narrated by the model: a criterion the LLM forgets to
    mention is exactly the one that needed mentioning.
    """
    reason_for = reason_for or {}
    used_set = {u.lower() for u in used}
    out: List[OmittedCriterion] = []
    for crit in requested:
        if crit.lower() in used_set:
            continue
        out.append(
            OmittedCriterion(
                criterion=crit,
                reason=reason_for.get(crit, OmissionReason.MISSING),
                detail="",
            )
        )
    return out


def _short(iri: Optional[str]) -> str:
    if not iri:
        return "an unnamed space"
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
