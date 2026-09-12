# -*- coding: utf-8 -*-
"""The kinds of nothing, kept apart (V12-05, review risk R3 / ticket T04).

    "Absence in a graph, absence in a time window, failed retrieval and forbidden access
     are different facts. Keeping them separate is part of factual correctness, not
     merely operational convenience."   — architecture review, p. 8

WHY THIS IS NOT PEDANTRY
------------------------
Every one of those currently reaches a user as some form of "no data", and one of them —
a missing ``ref:storedAt`` — produced a confident recommendation to **install a sensor that
already exists**, for a room recording 77,088 readings a day (BUG-475). The room had a CO2
sensor. The graph said so. The reference that routes its readings was absent, the fetch came
back empty, and the narrator explained the emptiness as a fact about the building.

Two point repairs followed — BUG-475 on the report lane, BUG-487 on the register lane — and
the review's judgement is that the distinction is systemic rather than per-lane. This module
is that distinction, in one place, so a lane classifies rather than narrates.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No lane is forced through this. It is a classifier, not a framework: a caller states the
facts it has and receives an outcome plus the wording authorised for it. Lanes already
carrying good declines — ``absence_guard``, ``enablement_hint``, ``absent_record_class`` —
keep them; this gives the ones that do not a place to go, and gives all of them one
vocabulary.

THE C08 QUALIFICATION, WHICH IS THE SUBTLE PART
-----------------------------------------------
The review corrected its own first edition here (C08, p. 32):

    "The former acceptance wording assumed that every adapter could distinguish an invalid
     identifier from an empty time window. The revision requires separate
     series-resolution evidence or an explicit unknown state when that distinction cannot
     be established."

So an empty result does **not** establish that a series is missing. Without a series
catalogue, "no rows" cannot tell a broken identifier from a quiet sensor, and the honest
answer is that the resolution is unknown — not a guess in either direction. That is why
``SeriesResolution`` is a separate input rather than something inferred from row count.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SeriesResolution(str, Enum):
    """Whether the identifier behind a reading was shown to exist in its store.

    Separate from the query result on purpose (review C08). An adapter that can list its
    series answers CONFIRMED or ABSENT; one that cannot answers UNKNOWN, and UNKNOWN is a
    real answer rather than a missing one.
    """

    CONFIRMED = "confirmed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class RetrievalOutcome(str, Enum):
    """The seven states on review p. 8. Each has exactly one authorised external wording."""

    NOT_DECLARED = "not_declared"
    REFERENCE_MISSING = "reference_missing"
    SERIES_UNRESOLVED = "series_unresolved"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    NO_OBSERVATIONS = "no_observations"
    INSUFFICIENT_QUALITY = "insufficient_quality"
    ACCESS_RESTRICTED = "access_restricted"


#: What each state means internally, and what a user may be told.
#:
#: The external wording is the POINT of this module. An internal state that every lane
#: renders in its own words is a taxonomy nobody experiences; BUG-475's "critical
#: monitoring gap" was a lane inventing prose for a state it had not identified.
#:
#: `{subject}` is substituted with what was asked about. Nothing else is interpolated —
#: a wording that can absorb arbitrary text is one that can absorb a fabrication.
_WORDING = {
    RetrievalOutcome.NOT_DECLARED: (
        "no matching sensor is declared in the authorised graph scope",
        "There is no {subject} recorded for this building, so I have nothing to read. "
        "This describes what the building's model declares — not a fault.",
        "Add the sensor to the ontology and register its readings, and this becomes "
        "answerable.",
    ),
    RetrievalOutcome.REFERENCE_MISSING: (
        "a declared sensor lacks the reference that routes its readings",
        "The building's model declares {subject}, but I could not retrieve its readings "
        "because the link to its data store is incomplete. I cannot tell you its values, "
        "and I am NOT telling you the sensor is absent.",
        "The sensor needs a timeseries reference (ref:hasTimeseriesId and ref:storedAt) "
        "before its readings can be read.",
    ),
    RetrievalOutcome.SERIES_UNRESOLVED: (
        "series identity not resolved; absence is NOT established",
        "I could not establish whether readings for {subject} exist. The store did not "
        "return any, and it cannot tell me whether that means the identifier is wrong or "
        "the period was simply quiet — so I will not guess either way.",
        "An operator can confirm the identifier against the store's series list.",
    ),
    RetrievalOutcome.BACKEND_UNAVAILABLE: (
        "retrieval did not complete because of a store or connection failure",
        "I could not reach the store that holds {subject}'s readings just now. This is a "
        "temporary retrieval problem on my side, not a statement about the building.",
        "Ask again shortly; if it persists an operator should check the data source.",
    ),
    RetrievalOutcome.NO_OBSERVATIONS: (
        "query succeeded and returned no rows; series identity is confirmed",
        "{subject} is connected and working, but recorded nothing in the period you "
        "asked about.",
        "Widening the period usually finds readings.",
    ),
    RetrievalOutcome.INSUFFICIENT_QUALITY: (
        "data exist but are too stale, invalid or incomplete for the claim",
        "I have readings for {subject}, but not of a quality I can base this answer on.",
        "A narrower claim, or a period with better coverage, may be answerable.",
    ),
    RetrievalOutcome.ACCESS_RESTRICTED: (
        "policy prevents access at the requested resolution",
        "I cannot share {subject} at that level of detail.",
        "",
    ),
}


@dataclass(frozen=True)
class RetrievalResult:
    """One classified nothing."""

    outcome: RetrievalOutcome
    #: For an operator, a log, the evidence record. May name identifiers.
    internal: str
    #: For the user. The ONLY wording authorised for this state.
    external: str
    #: What would make the question answerable, or "" when nothing would.
    remedy: str

    @property
    def is_absence_of_data(self) -> bool:
        """True only where the building genuinely has nothing to say.

        `REFERENCE_MISSING`, `SERIES_UNRESOLVED` and `BACKEND_UNAVAILABLE` are OUR
        failures, not the building's, and a lane must never narrate them as absence —
        that is BUG-475 exactly.
        """
        return self.outcome in (RetrievalOutcome.NOT_DECLARED, RetrievalOutcome.NO_OBSERVATIONS)

    @property
    def may_recommend_installation(self) -> bool:
        """Only NOT_DECLARED can ever justify "you could add a sensor here".

        BUG-475 recommended installing a CO2 sensor in a room that had one, because a
        retrieval failure was read as physical absence. This property is the guard: any
        other state and the suggestion is false.
        """
        return self.outcome is RetrievalOutcome.NOT_DECLARED


def classify(
    *,
    declared: bool,
    has_reference: bool = True,
    store_registered: bool = True,
    backend_reachable: bool = True,
    series: SeriesResolution = SeriesResolution.UNKNOWN,
    rows: int = 0,
    quality_ok: bool = True,
    access_permitted: bool = True,
    subject: str = "that",
) -> RetrievalResult:
    """Name the nothing.

    Order is precedence, and it is not arbitrary: the earliest fact that settles the
    question wins, because a later one cannot be trusted once an earlier one has failed.
    A store that was never reached says nothing about whether rows exist.
    """
    if not access_permitted:
        return _result(RetrievalOutcome.ACCESS_RESTRICTED, subject)
    if not declared:
        return _result(RetrievalOutcome.NOT_DECLARED, subject)
    if not has_reference:
        return _result(RetrievalOutcome.REFERENCE_MISSING, subject)
    if not store_registered:
        # A04: an unregistered store is a configuration failure with a NAMED cause, and
        # must never fall back to another backend. Substituting one would answer with
        # some other sensor's readings, which is worse than any refusal.
        return _result(
            RetrievalOutcome.BACKEND_UNAVAILABLE,
            subject,
            internal_suffix=" — the store this sensor names is not registered; no "
            "substitute backend was used",
        )
    if not backend_reachable:
        return _result(RetrievalOutcome.BACKEND_UNAVAILABLE, subject)

    if rows > 0:
        if not quality_ok:
            return _result(RetrievalOutcome.INSUFFICIENT_QUALITY, subject)
        raise ValueError("classify() describes a retrieval that produced nothing usable")

    # Zero rows. What that MEANS depends on whether the series was ever resolved (C08).
    if series is SeriesResolution.CONFIRMED:
        return _result(RetrievalOutcome.NO_OBSERVATIONS, subject)
    if series is SeriesResolution.ABSENT:
        return _result(RetrievalOutcome.SERIES_UNRESOLVED, subject)
    return _result(RetrievalOutcome.SERIES_UNRESOLVED, subject)


def _result(
    outcome: RetrievalOutcome, subject: str, internal_suffix: str = ""
) -> RetrievalResult:
    internal, external, remedy = _WORDING[outcome]
    subject = (subject or "that").strip() or "that"
    return RetrievalResult(
        outcome=outcome,
        internal=internal + internal_suffix,
        external=external.format(subject=subject),
        remedy=remedy,
    )


def describe(result: RetrievalResult) -> str:
    """The user-facing sentence, with its remedy when there is one.

    A refusal that knows the remedy and withholds it was already a defect in this project,
    so the remedy is part of the rendering rather than an optional extra.
    """
    if result.remedy:
        return f"{result.external}\n\n{result.remedy}"
    return result.external
