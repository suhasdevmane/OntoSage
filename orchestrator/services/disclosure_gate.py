# -*- coding: utf-8 -*-
"""A policy refusal applies to EVERY channel, not just the prose (V12-17, review B11).

    "A policy applied to the text but not to the dossier or the chart is not applied."

WHY THIS IS A SEPARATE MODULE FROM publication_gate.py
-------------------------------------------------------
They sit at the same chokepoint and answer superficially similar questions, and folding
this into that one would be the single worst thing that could happen to it — because their
FAILURE DIRECTIONS ARE OPPOSITE, and that is not a stylistic difference.

`publication_gate` fails OPEN on purpose, and says so: a verification gate that blocked
answers because it could not read its own inputs would turn a verifier outage into a total
outage and take every honest answer down with the unverified ones. Withholding an answer
that was fine is a cost; publishing one that was fine is not.

A DISCLOSURE gate has the reverse arithmetic. If it cannot tell whether a refusal applies,
publishing is the irreversible outcome: a chart, once rendered, has been seen, and a
spreadsheet outlives every caveat that sat beside it on screen. So this one fails CLOSED on
the surfaces it governs, and an exception here withholds rather than releases.

Two gates, two defaults, two modules. A single module with a `fail_open=` parameter is the
same thing with one switch between correct and catastrophic.

WHAT IT GOVERNS
---------------
Not the decision — the PDP owns that, at the four consult chokepoints (sparql, sql,
deliberate, events). This governs the DISCLOSURE that follows a decision already made:
when any lane on the bus returned a refusal, everything DERIVED from that lane goes with
it. BUG-195 was the missing decision point; this is the missing propagation.

  text     the refusal is what the user reads
  chart    `visualization_path` — a chart of restricted rows is the restricted rows
  export   `export_result` — the surface that outlives the conversation
  dossier  `evidence_dossier` and `evidence_record` — the deliberation lane CITES its
           applied policy in the dossier, and a dossier still listing the per-space values
           the policy restricted has published them in a footnote

IDENTITY IS NOT A PROPERTY OF THE QUESTION
-------------------------------------------
The same question from two accounts can have two correct answers. Nothing here reads a
role: it reads the verdict the PDP returned FOR THIS TURN'S IDENTITY, so two identities
diverge because their verdicts differed, not because this module has an opinion about
either. That is what makes the >1-identity case in the acceptance meaningful rather than a
restatement of the single-identity one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Bus keys a lane writes when it refuses. Each carries `denied_by_policy` — the policy
#: IRI — which is set in exactly one place (`enforcement.refusal_payload`), so detection
#: cannot drift from production.
LANE_RESULT_KEYS = (
    "sql_result",
    "sparql_result",
    "analytics_result",
    "deliberate_result",
    "events_result",
    "report_result",
    "anomaly_result",
)

#: Derived surfaces. A refusal on any lane withholds all of these, because every one of
#: them is built FROM a lane's rows and none of them can be built without them.
DERIVED_KEYS = (
    "visualization_path",
    "export_result",
    "evidence_dossier",
    "evidence_record",
)

#: The sub-key a data lane writes on its OWN bus result when it answered a question from a
#: period other than the one the question asked for.
#:
#: A refusal and a substitution are different events with the same obligation. A refusal
#: withholds; a substitution publishes — and publishing figures from one period under a
#: question about another is the more dangerous of the two, because nothing about the
#: answer looks wrong. So the detection and the wording live here, beside the refusal
#: propagation, and a lane records the fact rather than composing the sentence itself.
SUBSTITUTION_KEY = "window_substituted"


@dataclass
class DisclosureDecision:
    """What a policy refusal on this turn withholds."""

    refused: bool = False
    policy_iri: str = ""
    lane: str = ""
    withhold: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def any_withheld(self) -> bool:
        return bool(self.withhold)


def _refusal_in(payload: Any) -> Optional[str]:
    """The policy IRI this lane result was refused under, or None.

    Reads the marker `refusal_payload` writes rather than sniffing the prose. Text matching
    is how BUG-191's grader came to count the "2" inside `bldg2` as a sensor reading, and a
    disclosure gate that guessed from wording would make the same class of mistake with
    worse consequences.
    """
    if not isinstance(payload, dict):
        return None
    iri = payload.get("denied_by_policy")
    return str(iri) if iri else None


def evaluate(results: Optional[Dict[str, Any]]) -> DisclosureDecision:
    """What must be withheld, given the whole bus for this turn.

    Fails CLOSED: a bus this cannot read is a bus whose refusals it cannot see, and the
    honest response to not knowing is to withhold the derived surfaces. The TEXT is never
    withheld here — a lane's refusal message IS the answer, and blanking it would replace a
    clear explanation with silence.
    """
    d = DisclosureDecision()
    try:
        if not isinstance(results, dict):
            if results is None:
                return d  # genuinely nothing on the bus: nothing was computed to disclose
            raise TypeError(f"bus is {type(results).__name__}, not a dict")

        for key in LANE_RESULT_KEYS:
            iri = _refusal_in(results.get(key))
            if iri:
                d.refused = True
                d.policy_iri = iri
                d.lane = key
                break
        if not d.refused:
            return d

        d.withhold = [k for k in DERIVED_KEYS if results.get(k)]
        d.reason = (
            f"{d.lane} was refused under {d.policy_iri}; everything derived from it is "
            "withheld with it"
        )
        return d
    except Exception as exc:  # FAIL CLOSED — see the module docstring
        return DisclosureDecision(
            refused=True,
            policy_iri="unknown",
            lane="unknown",
            withhold=list(DERIVED_KEYS),
            reason=(
                f"the disclosure gate could not read this turn's results ({exc}); the "
                "derived surfaces are withheld because it cannot be shown that no policy "
                "refusal applies"
            ),
        )


def window_substitution_in(results: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The window substitution a lane recorded on this turn's bus, or None.

    Reads the structured marker, never the prose — the same rule as `_refusal_in`, and for
    the same reason: a gate that guessed from wording would be wrong in exactly the cases
    that matter, where the wording is confident and the period is not the one asked for.
    """
    if not isinstance(results, dict):
        return None
    for key in LANE_RESULT_KEYS:
        payload = results.get(key)
        if not isinstance(payload, dict):
            continue
        marker = payload.get(SUBSTITUTION_KEY)
        if isinstance(marker, dict) and marker.get("substituted"):
            return marker
    return None


def _describe_requested(marker: Dict[str, Any]) -> str:
    """What the question asked for, in words. Never empty — silence here reads as agreement."""
    label = str(marker.get("requested_label") or "").strip()
    if label:
        return label
    start = str(marker.get("requested_start") or "").strip()
    end = str(marker.get("requested_end") or "").strip()
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"on or after {start}"
    if end:
        return f"on or before {end}"
    return "the period this question asked about"


def substitution_note(marker: Optional[Dict[str, Any]]) -> str:
    """The sentence that tells the user the figures are not from the period they asked for.

    "We substituted" is the weak half of this. The strong half is the SPAN — a reader who is
    told the readings run to a date months behind the question can judge the answer; a reader
    told only that a fallback occurred cannot. So the span is stated whenever the rows carry
    one, and when they do not, that is itself stated rather than quietly dropped.

    Never raises. A disclosure that failed to render would leave the substituted figures on
    screen with nothing beside them, which is the exact outcome this exists to prevent — so
    the failure path still says that a substitution happened.
    """
    if not isinstance(marker, dict) or not marker.get("substituted"):
        return ""
    try:
        requested = _describe_requested(marker)
        earliest = str(marker.get("actual_earliest") or "").strip()
        latest = str(marker.get("actual_latest") or "").strip()
        rows = marker.get("rows")
        if earliest and latest and earliest != latest:
            span = f"readings recorded between {earliest} and {latest}"
        elif latest or earliest:
            span = f"the reading recorded at {latest or earliest}"
        else:
            span = "the most recent readings on record, whose timestamps could not be read"
        counted = f" ({rows} reading(s))" if isinstance(rows, int) and rows > 0 else ""
        return (
            f"\n\n_No readings were recorded for {requested}, so the figures above are not "
            f"from that period: they come from {span}{counted}. Treat them as the latest "
            f"available, not as current._"
        )
    except Exception as exc:  # the substitution is disclosed even when its detail is not
        return (
            f"\n\n_The figures above are not from the period this question asked about — "
            f"the requested period held no readings, and the detail of the period they do "
            f"come from could not be read ({exc}). Treat them as the latest available, not "
            f"as current._"
        )


def note(decision: DisclosureDecision) -> str:
    """The sentence appended when a derived surface was withheld, or "".

    Said explicitly because a chart that silently does not appear reads as a bug, and a
    user who thinks the system is broken asks again rather than asking differently.
    """
    if not decision.any_withheld:
        return ""
    surfaces = {
        "visualization_path": "the chart",
        "export_result": "the export",
        "evidence_dossier": "the evidence dossier",
        "evidence_record": "the evidence record",
    }
    named = [surfaces.get(k, k) for k in decision.withhold]
    listed = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
    return (
        f"\n\n_{listed.capitalize()} {'was' if len(named) == 1 else 'were'} withheld too: "
        f"the same policy governs every form this answer could take, not only its wording._"
    )
