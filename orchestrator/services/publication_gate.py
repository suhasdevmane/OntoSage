# -*- coding: utf-8 -*-
"""A failed verification must WITHHOLD, not annotate (V12-03, review R1/T03, cases B04/B05).

WHAT WENT WRONG
---------------
``verification["grounded"]`` was read in exactly one place in the whole orchestrator, and
all it decided was whether the turn was filed under ``store_success`` or ``store_failure``
in agent memory. **It gated publication not at all.** That is why BUG-475's report -- the
one telling a room with 77,088 readings a day that it had no CO2 sensor and recommending
one be installed -- went out carrying ``grounded=False, confidence=0.20``. The check ran,
failed, and changed nothing the user saw.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
The review is precise about the meaning of a failed check (p. 12):

    "A failed verifier means the required check did not pass; it does not by itself prove
    the underlying calculation false."

So the action is to **withhold the affected claim and say so**, never to assert the answer
is wrong. Withholding is reversible by the reader -- they can re-ask, or ask an operator to
look at the diagnostic. A confident denial is not.

Three surfaces, because prose alone is not publication (case B04):

* **text**    -- the claim is removed and replaced with a statement of what could not be
                established;
* **chart**   -- ``visualization_path`` is cleared, because a chart of a withheld figure is
                the same claim with better typography;
* **export**  -- the export payload is refused, because a spreadsheet outlives the caveat
                that accompanied it on screen.

WHAT MUST NOT BE TOUCHED
------------------------
An honest decline is already the correct answer and has no claim to withhold. Gating it
would turn *"I don't have readings for that room"* into *"I could not verify..."*, which is
worse: it converts a clear, actionable answer into a vague one, and it would make the
system look broken on precisely the questions it handles best. `is_decline` exists for
that, and the tests pin it.

Nor does this gate fire on a lane it does not understand. It starts narrow, on the four
quantitative lanes the acceptance names -- analytics, report, compare, trend -- because a
guard added for one question shape quietly taking another with it is the most expensive
mistake this project keeps making (BUG-431's first fix corrected "how many CO2 sensors" and
began answering it with the building-wide total).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: Lanes whose answers are quantitative claims about the building, where an unverified
#: figure is a misrepresentation rather than a stylistic problem. Deliberately narrow;
#: widen it only with a probe case per addition.
GATED_INTENTS = frozenset({"analytics", "report", "compare", "trend"})

#: A confidence at or below this is treated as no support at all, independent of the
#: boolean. BUG-475 published at 0.20 with grounded=False; both signals agreed and neither
#: was consulted.
CONFIDENCE_FLOOR = 0.25

#: Phrases that mark an answer as an honest decline rather than a claim. Matched against a
#: TYPOGRAPHY-NORMALISED copy: a model writes curly quotes and en dashes wherever prose
#: calls for them, and the W0 meta-answer guard shipped with a hole for exactly that reason
#: -- "If you'd like" never matched because the pattern expected a straight apostrophe.
_DECLINE_MARKERS = (
    "i don't have",
    "i do not have",
    "no data",
    "not measured",
    "no readings",
    "could not retrieve",
    "cannot assess",
    "is not recorded",
    "no point of that kind",
    "would be invented",
    "not in this building",
    "does not exist",
    "i couldn't verify",
    "i could not verify",
    "unable to answer",
    # BUG-1252's lead (`clarification.lead_read_but_off_topic`) was built on THIS line on
    # purpose, so this list needed no change at all to recognise the new decline.
    #
    # THE UNCONTRACTED FORM WAS ADDED HERE AND TAKEN BACK OUT, and the measurement is the
    # reason. "could not put an answer together" — the pairing every other lead in this file
    # has ("i couldn't verify" / "i could not verify") — moves 33 stored answers, because the
    # RETIRED `_unanswered_response` text read "I understood the question but could not put an
    # answer together for it." Those 33 really are declines and this classifier really does
    # miss them, but that is a separate finding with its own number (CAVEAT-1281); folding it
    # into a wording change would be lessons #141 a fourth time. The emitter only ever writes
    # the contraction, so nothing is lost by leaving it out.
    "couldn't put an answer together",
    # THE COMMONEST DECLINE THIS SYSTEM EMITS WAS NOT IN THIS LIST (CAVEAT-952, BUG-992).
    #
    # `clarification.compose_abstract` opens with "I couldn't answer that from <building>'s
    # records", and it appears on six of 62 held-out answers. `is_decline` returned False for all
    # three of its surface forms, which cost two different things:
    #   * inside `evaluate` it was INERT — the next guard, `has_quantitative_claim`, catches a
    #     decline anyway because a decline carries no figure;
    #   * in `session_summary.outcome_of`, the only other caller, it was LIVE: a turn that ended
    #     in that decline was remembered as `answered`, and that summary goes into the
    #     classification prompt on every `/v1` turn. The system was telling itself it had answered
    #     questions it had declined.
    #
    # CLAUDE.md's rule for this list was followed rather than assumed: every change is checked
    # against all 73 stored answers, because an intermediate broader pattern moved two of them and
    # was rejected for it (lessons #141). These two move FIVE — pack indexes 1, 4, 27, 37 and 51 —
    # and every one of the five OPENS with exactly this decline, so the move is the point.
    # `"answer that from"` was tried and REJECTED: it also captures "I can answer that from the
    # building's records: the mean is 22.9 C", which is an answer.
    "i couldn't answer that",
    "i could not answer that",
)

#: A figure that makes an answer a quantitative claim. Bare integers are NOT enough on
#: their own -- "floor 3" and "Room 5.01" are identifiers, not measurements -- so a unit or
#: a decimal is required. This is the BUG-191 lesson: a grader that counted any digit as a
#: reading scored refusals as PASS and manufactured a perfect run.
#:
#: BUG-904: the integer part was `\d{1,3}(?:,\d{3})*`, which requires a COMMA before a
#: fourth digit. So "1,240 ppm" was a claim and "1200 ppm" was not -- and an unseparated
#: four-digit ppm value is the commonest reading in this building. `has_quantitative_claim`
#: returned False for it, so `evaluate` published it unchanged on a FAILED verification,
#: which is the one thing this module exists to prevent. Found by the W5-01 redaction
#: tests, not by the gate's own, because the gate's fixtures all used "1,240".
_CLAIM_NUMBER = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*"
    r"(ppm|ppb|°?c\b|°?f\b|celsius|kwh|kw\b|wh\b|pa\b|kpa|%|percent|lux|db\b|dba|"
    r"m2|m²|m3|m³|l/s|litres?|liters?|people|occupants?)",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    """Fold the typography a model varies freely, so a marker match is about meaning."""
    return (
        (text or "")
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace(" ", " ")
    )


def is_decline(text: str) -> bool:
    """True when the answer already declines, and so has no claim to withhold."""
    low = _normalise(text)
    return any(m in low for m in _DECLINE_MARKERS)


def has_quantitative_claim(text: str) -> bool:
    """True when the answer states a measurement, as opposed to naming things."""
    return bool(_CLAIM_NUMBER.search(text or ""))


#: What a redacted measurement is replaced with. Deliberately digit-free, so a
#: redacted string can never re-form a match with the text around it.
REDACTED_QUANTITY = "[value]"

#: A redaction pass can only shrink the text, and the marker carries no digits, so
#: this loop reaches a fixed point immediately in every case observed. The bound
#: exists so a pathological input cannot spin here.
_REDACTION_PASSES = 3


def redact_quantities(text: str) -> str:
    """Remove every measurement-shaped figure, leaving identifiers intact.

    ``has_quantitative_claim(redact_quantities(x))`` is False for every ``x`` — that
    is the point, and ``tests/test_a_remembered_turn_carries_no_figure.py`` pins it.
    Used by the rolling session summary (W5-01), which must be able to name what a
    past turn was ABOUT without carrying a number that a later turn could restate as
    current. ``brick:Room 5.01`` and ``floor 3`` survive, because ``_CLAIM_NUMBER``
    requires a unit — the BUG-191 lesson, one definition of "this is a measurement".
    """
    out = text or ""
    for _ in range(_REDACTION_PASSES):
        folded = _CLAIM_NUMBER.sub(REDACTED_QUANTITY, out)
        if folded == out:
            return out
        out = folded
    return out


@dataclass
class PublicationDecision:
    """What may be published, and why anything was withheld."""

    publish: bool = True
    text: str = ""
    withhold_chart: bool = False
    withhold_export: bool = False
    reason: str = ""
    checks_failed: List[str] = field(default_factory=list)

    @property
    def withheld(self) -> bool:
        return not self.publish or self.withhold_chart or self.withhold_export


def _withheld_text(reason: str, source: str, missing: List[str]) -> str:
    """What the user sees instead of the unsupported claim.

    States what could not be established and what would change it. It never says the
    figure was wrong, because a failed check does not establish that -- and it never
    silently drops the answer, because an empty reply is indistinguishable from a crash.

    THE WORDING MOVED OUT (2D-16 wave 2). This text used to print the verifier's own record at
    the reader: *"The grounding check did not pass (grounded=False and confidence=0.20) ... What
    the answer claimed but the data did not support: time_series_data ... Attempted via the sql
    path."* A boolean, a score, a bus key and a lane name, none of which a facility manager can
    act on, and "grounded=False" reads as a fault report. `reason` and `source` stay on the
    decision, where the log and the evidence record want them; the reader gets plain words.
    """
    from orchestrator.services.withheld_wording import withheld_text

    return withheld_text(missing)


def evaluate(
    *,
    intent: Optional[str],
    final_response: str,
    verification: Optional[Dict[str, Any]],
    has_chart: bool = False,
    has_export: bool = False,
) -> PublicationDecision:
    """Decide what may be published for this turn.

    Fails OPEN by design. A gate that blocks an answer because it could not read its own
    inputs would turn a verifier outage into a system-wide outage, and every honest answer
    would disappear with the dishonest ones. Every early return below is an explicit
    "not my business", not an oversight.
    """
    d = PublicationDecision(publish=True, text=final_response)

    if (intent or "") not in GATED_INTENTS:
        return d
    if not isinstance(verification, dict) or not verification:
        # No verification record at all: the check did not run, which is not the same as
        # having failed. V12-19 makes that a typed outcome; here it stays open.
        return d
    if verification.get("applicable") is False:
        # THE CHECK DID NOT RUN FOR THIS LANE. The verifier reads four buses -- sparql,
        # sql, analytics, capability -- and reports `grounded=False, source="none",
        # confidence=0.20` for every lane whose evidence lives somewhere else. Gating on
        # that would withhold every register, floor-plan, deliberation and events answer
        # in the system.
        #
        # This is not hypothetical. The first deployment of this gate withheld a REPORT
        # that had 1,000 real rows behind it, because the verifier counted them with a
        # reader that was one level too shallow (BUG-508) and then reported the resulting
        # blindness as a grounding failure. The live regression check caught it; the unit
        # tests could not, because they supplied the verification record by hand.
        return d
    if is_decline(final_response):
        return d
    if not has_quantitative_claim(final_response):
        # Nothing measurable is being asserted, so there is no figure to withhold.
        return d

    grounded = verification.get("grounded", True)
    try:
        confidence = float(verification.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0

    failed: List[str] = []
    if grounded is False:
        failed.append("grounded=False")
    if confidence <= CONFIDENCE_FLOOR:
        failed.append(f"confidence={confidence:.2f}")

    if not failed:
        return d

    reason = " and ".join(failed)
    missing = verification.get("missing") or []
    return PublicationDecision(
        publish=False,
        text=_withheld_text(reason, str(verification.get("source") or ""), list(missing)),
        withhold_chart=has_chart,
        withhold_export=has_export,
        reason=reason,
        checks_failed=failed,
    )
