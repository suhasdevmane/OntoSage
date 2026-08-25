# -*- coding: utf-8 -*-
"""Can this building answer that? — the observability self-knowledge lane (V6-T10).

*"Can you measure formaldehyde in room 5.01?"* is not a sensor question. It is a question about
the **system's own reach**, and answering it from prose is how a building claims instrumentation
it does not have, or denies instrumentation it does — BUG-192, where the model asserted a
building had no temperature sensors minutes after quoting one of their readings.

So this answers from the graph and from the store, never from a retrieval window:

* is a point of that modality **located** in that space?
* is it **connected** — a timeseries id resolving to rows in a registered store (contract #8,
  and both halves are required)?
* is it **reporting** — has it produced a reading recently?

Four outcomes, deliberately distinct because they need four different actions from four
different people:

``observable``      a connected point that is reporting — the question can be answered now
``stale``           connected, but silent; the instrument or its feed needs attention
``unconnected``     described in the ontology and pointing at no rows; a data-plumbing job
``uninstrumented``  no such point in that space; a procurement or installation decision

**Every negative names its unlock step.** "No" on its own tells a facilities manager nothing
they can act on, and an unanswerable question that explains what would make it answerable is
worth more than a confident guess.

**Silence is never read as absence.** If the coverage matrix cannot be built, the answer says
the reach is unknown rather than reporting an empty building — the degrade-to-a-legal-value
failure this codebase keeps paying for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: "can you measure X in Y" and the ways people actually ask it. Generic English only — a
#: building name here would make the lane un-portable, which is design contract #3.
CAN_MEASURE_RE = re.compile(
    r"\b(?:can|could|do|does|are)\s+(?:you|we|i|this building|the system|it)\b"
    r".{0,40}\b(?:measure|monitor|track|sense|detect|read|report|tell me)\b"
    r"|\bis\s+(?:there|any)\b.{0,30}\b(?:sensor|monitor|meter)\b"
    r"|\bdo\s+you\s+have\b.{0,30}\b(?:sensor|monitor|meter|data)\b"
    r"|\bwhat\s+can\s+you\s+(?:measure|monitor|tell me about)\b"
    r"|\bis\s+.{0,30}\b(?:instrumented|monitored|measured)\b"
    # "what detection covers it", "what monitoring covers the plant room". Asking what
    # INSTRUMENTATION watches something is a reach question, and it is the shape a safety
    # question takes. Measured on the golden bank: "Where is lithium battery charging
    # happening, and what detection covers it?" was classified floor_plan and answered with a
    # floor-plan menu — a picker, in response to a fire-safety question.
    r"|\bwhat\s+(?:detection|monitoring|coverage|sensors?|instrumentation)\b"
    r".{0,20}\b(?:covers?|is in place|do(?:es)? (?:we|you) have|exists?)\b"
    r"|\b(?:detection|monitoring|coverage)\s+(?:is\s+)?in place\b",
    re.IGNORECASE,
)

#: Asking whether a question is answerable, rather than asking it.
CAN_ANSWER_RE = re.compile(
    r"\bcan you answer\b|\bare you able to answer\b|\bdo you know whether you can\b"
    r"|\bwould you be able to\b.{0,30}\b(?:answer|tell)\b",
    re.IGNORECASE,
)

OBSERVABLE = "observable"
STALE = "stale"
UNCONNECTED = "unconnected"
UNINSTRUMENTED = "uninstrumented"
UNKNOWN = "unknown"


@dataclass
class Reach:
    """What the building can observe of one modality in one space."""

    modality: str
    space_label: str
    status: str = UNKNOWN
    sensor: str = ""
    stored_at: str = ""
    fresh: Optional[bool] = None
    lay_term: str = ""
    alternatives: List[str] = field(default_factory=list)

    @property
    def answerable(self) -> bool:
        return self.status == OBSERVABLE

    def describe(self) -> str:
        """The answer, and for every negative the step that would change it."""
        what = self.lay_term or self.modality.replace("_", " ")
        where = self.space_label or "this building"

        if self.status == OBSERVABLE:
            line = f"**Yes — {what} is measured in {where}** and the sensor is reporting."
            if self.sensor:
                line += f" Source: `{self.sensor}`."
            return line

        if self.status == STALE:
            line = (
                f"**Partly.** {what.capitalize()} is instrumented in {where} and the point is "
                f"connected, but it has not reported recently, so I would be answering from "
                f"stale readings rather than current ones."
            )
            if self.stored_at:
                line += f" Its readings are stored in `{self.stored_at}`."
            return (
                line + "\n\nUnlock: check the sensor or its feed — the wiring is already in place."
            )

        if self.status == UNCONNECTED:
            return (
                f"**Not yet.** {what.capitalize()} is described in the ontology for {where}, but "
                f"the point has no readings behind it — no timeseries id resolving to rows in a "
                f"registered database.\n\nUnlock: give the point a `ref:hasTimeseriesId` and a "
                f"`ref:storedAt`, and register the database that holds its rows. No code change "
                f"is needed."
            )

        if self.status == UNINSTRUMENTED:
            line = (
                f"**No — {what} is not measured in {where}.** There is no point of that kind "
                f"located there, so any figure I gave you would be invented."
            )
            if self.alternatives:
                line += (
                    f"\n\nWhat IS measured there: {', '.join(self.alternatives[:8])}"
                    f"{' and more' if len(self.alternatives) > 8 else ''}."
                )
            return line + (
                "\n\nUnlock: install a sensor and describe it in the ontology, or upload a TTL "
                "for one that already exists."
            )

        return (
            f"**I can't tell you reliably.** I could not build the coverage picture for {where}, "
            f"so I don't know whether {what} is measured there — and guessing either way would "
            f"be worse than saying so."
        )


def is_observability_question(text: str) -> bool:
    """True when the question is about the system's REACH rather than about a reading.

    "What is the CO2 in 5.01?" asks for a value. "Can you measure CO2 in 5.01?" asks whether a
    value exists to be had. Answering the second with the first is a non-answer; answering the
    first with the second is worse — it withholds data the building has.
    """
    if not text or not text.strip():
        return False
    return bool(CAN_MEASURE_RE.search(text) or CAN_ANSWER_RE.search(text))


#: "what can you measure here" — the OPEN question, asking for the menu rather than about one
#: quantity. Distinguished from a NAMED substance so "can you measure formaldehyde?" answers
#: about formaldehyde instead of listing what is measured and leaving the asker to notice the
#: absence themselves.
OPEN_QUESTION_RE = re.compile(
    r"\bwhat\s+can\s+you\s+(?:measure|monitor|tell me about)\b"
    r"|\bwhat\s+(?:sensors?|data|readings?)\b.{0,20}\b(?:do you have|are there|exist)\b"
    r"|\bwhat\s+is\s+(?:measured|monitored|instrumented)\b",
    re.IGNORECASE,
)

#: The quantity a reach question names, when it names one.
NAMED_QUANTITY_RE = re.compile(
    r"\b(?:measure|monitor|track|sense|detect|read)\s+"
    r"(?:the\s+|any\s+)?([a-z][a-z0-9 \-]{2,30}?)"
    r"(?=\s+(?:in|at|for|on|inside|within|here|there)\b|\s*\?|$)",
    re.IGNORECASE,
)


def is_open_question(text: str) -> bool:
    """True when the asker wants the menu rather than a verdict on one quantity."""
    return bool(OPEN_QUESTION_RE.search(text or ""))


def named_quantity(text: str) -> str:
    """The quantity a reach question names, or "".

    Used only to say "formaldehyde is not measured here" instead of listing what is. It is
    NEVER resolved to a sensor -- an unrecognised word must not be matched to the nearest
    modality, which is how "can you measure radon?" would get answered about CO2.
    """
    m = NAMED_QUANTITY_RE.search(text or "")
    return (m.group(1).strip() if m else "").strip()


def reach_from_coverage(
    modality: str,
    space_label: str,
    entry: Optional[Dict[str, Any]],
    lay_term: str = "",
    present_modalities: Optional[List[str]] = None,
) -> Reach:
    """Turn one cell of the coverage matrix into an answer about reach.

    `entry` is the `SpaceCoverage.modalities[modality]` dict. `None` means the modality was
    never assessed for this space, which is UNINSTRUMENTED — distinct from an entry whose
    status says so, and reached by a different route.
    """
    reach = Reach(
        modality=modality,
        space_label=space_label,
        lay_term=lay_term,
        alternatives=sorted(present_modalities or []),
    )
    if entry is None:
        reach.status = UNINSTRUMENTED
        return reach

    status = str(entry.get("status") or "")
    reach.sensor = str(entry.get("sensor") or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    reach.stored_at = str(entry.get("stored_at") or "")
    fresh = entry.get("fresh")
    reach.fresh = fresh if isinstance(fresh, bool) else None

    if status == "present":
        # `fresh is None` means freshness could not be MEASURED, which must not be reported as
        # stale. Unknown recency on a connected point is still answerable; the answer's own
        # freshness gate is the place that judges the reading, not this one.
        reach.status = STALE if reach.fresh is False else OBSERVABLE
    elif status == "unbacked":
        reach.status = UNCONNECTED
    elif status == "missing":
        reach.status = UNINSTRUMENTED
    else:
        reach.status = UNKNOWN
    return reach


def present_modalities(space_entry: Dict[str, Any]) -> List[str]:
    """Modalities this space actually has a connected point for.

    Offered when the answer is "no", because "we don't measure formaldehyde, but we do measure
    CO2, PM2.5 and humidity here" is an answer somebody can act on.
    """
    out = []
    for name, entry in (space_entry or {}).items():
        if isinstance(entry, dict) and str(entry.get("status") or "") == "present":
            out.append(name.replace("_", " "))
    return sorted(out)


__all__ = [
    "CAN_ANSWER_RE",
    "CAN_MEASURE_RE",
    "OBSERVABLE",
    "STALE",
    "UNCONNECTED",
    "UNINSTRUMENTED",
    "UNKNOWN",
    "Reach",
    "is_observability_question",
    "is_open_question",
    "named_quantity",
    "present_modalities",
    "reach_from_coverage",
]
