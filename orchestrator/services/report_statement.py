# -*- coding: utf-8 -*-
"""Filing a report needs a STATEMENT: a thing, a place or a condition, said as fact.

The failure this prevents (hand read of tail F, 2026-09-19, SERIOUS). *"if the building are safe or
not"* was classified `safety_report` and the intake node FILED IT: a high-priority ticket
(REP-051956), "An administrator has been notified". Nobody had reported anything. The message names
no place, no hazard and no fault; it is a hedged question about whether the building is safe, and a
ticket for it sends someone to look for a problem that was never described — while the person who
asked receives a tracking number instead of an answer.

Two things had to be true for that to happen, and neither is a bug on its own:

* the classifier is allowed to guess `safety_report` (its examples are "the fire door is broken"), and
* the intake node files whatever it is handed unless the text is an information QUESTION — and
  "if the building are safe or not" has no question mark, no wh-word and no auxiliary opening.

So the gate is here, decided by shape and shared by both consumers (the routing contract, which sends
the message to a clarification, and the intake node, which refuses to file even if routing changes).

THE TEST IS ASYMMETRIC ON PURPOSE. A missed report of a real hazard costs more than a bogus ticket,
so nothing is blocked because it merely looks unlike a fault. A message is NOT a report only when ALL
of these hold:

1. it is HEDGED or asks a whole-building verdict ("if ...", "whether ...", "... or not", "is the
   building safe");
2. it states NO fault or hazard (no "broken", "leaking", "smoke", "flooded" ...);
3. it names NO place (no room, floor, zone or equipment id).

"The stairs are unsafe" states a hazard and a thing, and files. "Is the lift safe?" names a thing and
is answered rather than filed. "If the building are safe or not" is none of the three, and does not.

Pure and building-agnostic: English only, no building, room or register names.
"""

from __future__ import annotations

import re
from typing import Optional

# ── 1. hedged, or a verdict on the whole building ───────────────────────────

_HEDGE_RE = re.compile(
    r"^\s*(?:if|whether|what\s+if|in\s+case|i\s+wonder|i\s+was\s+wondering|not\s+sure|"
    r"do\s+you\s+know\s+(?:if|whether)|can\s+you\s+(?:tell|say|check)\s+(?:me\s+)?(?:if|whether)|"
    r"tell\s+me\s+(?:if|whether)|let\s+me\s+know\s+(?:if|whether))\b"
    r"|\bor\s+not\b|\bwhether\b|\bif\s+(?:the|this|it|everything)\b[^?.!]{0,30}\b(?:safe|ok|okay|"
    r"fine|secure|dangerous|unsafe)\b",
    re.IGNORECASE,
)

#: A verdict on the WHOLE building, whatever the grammar: "is the building safe", "are we safe here",
#: "is it safe to be in". The subject must be the building or an equivalent, so "the stairs are
#: unsafe" (a statement about a thing) is not a verdict request.
_VERDICT_RE = re.compile(
    r"\b(?:is|are|be|was)\s+(?:the\s+|this\s+|our\s+)?(?:building|site|campus|place|premises|"
    r"everything|it|we|everyone|everybody)\b[^?.!]{0,20}\b(?:safe|unsafe|dangerous|secure|ok|okay|"
    r"fine|risky|hazardous|habitable)\b"
    # the subject FIRST, as people write it ("the building are safe or not")
    r"|\b(?:the\s+|this\s+|our\s+)?(?:building|site|campus|premises)\s+(?:is|are|was)\s+"
    r"(?:\w+\s+)?(?:safe|unsafe|dangerous|secure|ok|okay|fine|risky|hazardous|habitable)\b"
    r"|\bsafe\s+(?:to\s+(?:be|stay|work|enter|use)|in\s+(?:here|the\s+building))\b",
    re.IGNORECASE,
)

# ── 2. a fault or a hazard, stated ──────────────────────────────────────────

_FAULT_OR_HAZARD_RE = re.compile(
    r"\b(?:broken|breaks?|leak\w*|flood\w*|burst|smok\w+|fire|gas|fumes?|sparks?|sparking|"
    r"exposed\s+wires?|electrocut\w*|shock\w*|spill\w*|collaps\w*|crack(?:ed|s)?|smash\w*|"
    r"shatter\w*|trapped|stuck|jammed|blocked|obstruct\w*|slip\w*|tripp?\w*|fell|fallen|"
    r"injur\w*|hurt|bleed\w*|unconscious|faint\w*|intruder|threat\w*|suspicious|smell\w*|"
    r"stink\w*|mou?ld|asbestos|rats?|mice|pests?|infest\w*|"
    r"not\s+working|out\s+of\s+order|no\s+(?:power|heat|heating|water|light|lights|hot\s+water)|"
    r"won'?t\s+(?:open|close|turn|start|work)|doesn'?t\s+work|isn'?t\s+working|failed|failing|"
    r"freezing|boiling|overheat\w*|noisy|loud)\b",
    re.IGNORECASE,
)

# ── 3. a place or a thing ───────────────────────────────────────────────────

_PLACE_RE = re.compile(
    r"\b(?:room|rm|floor|level|zone|storey|wing|block|stair(?:s|case)?|lift|elevator|corridor|"
    r"toilet|lobby|atrium|kitchen|car\s+park|entrance|exit|door|window|roof|basement|lab|office|"
    r"area|space)s?\b"
    r"\s*[\d.]*|\b\d{1,2}\.\d{1,3}\b",
    re.IGNORECASE,
)

_WH_RE = re.compile(r"\b(?:what|which|who|whom|whose|where|when|how|why)\b", re.IGNORECASE)


def _is_information_question(message: str) -> bool:
    """True when the message asks something: a question mark or a wh-word."""
    return "?" in message or bool(_WH_RE.search(message))


_SAFETY_WORD_RE =re.compile(r"\b(?:safe|safety|unsafe|dangerous|secure|security|hazard\w*)\b", re.I)


def is_hedged_or_verdict(message: str) -> bool:
    """True for a hedged message or a request for a verdict on the whole building."""
    m = message or ""
    return bool(_HEDGE_RE.search(m) or _VERDICT_RE.search(m))


def states_a_fault_or_hazard(message: str) -> bool:
    """True when the message says something IS wrong: a fault or a hazard word."""
    return bool(_FAULT_OR_HAZARD_RE.search(message or ""))


def names_a_place_or_thing(message: str) -> bool:
    """True when the message names a room, a floor, or a piece of the building."""
    return bool(_PLACE_RE.search(message or ""))


def is_not_a_report(message: str) -> bool:
    """True when a message is hedged or a verdict request and reports nothing at all.

    ALL of: hedged (or a whole-building verdict), no fault or hazard stated, no place or thing named.
    Anything else keeps whatever lane it had — including being filed, which is the safe direction.
    """
    m = (message or "").strip()
    if not m:
        return False
    hedged = bool(_HEDGE_RE.search(m))
    verdict = bool(_VERDICT_RE.search(m))
    if not (hedged or verdict):
        return False
    # "If we host the conference here, can the building cope?" is hedged and is a QUESTION with a
    # question of its own to answer; only a bare hedge or a bare verdict is nothing at all.
    if not verdict and _is_information_question(m):
        return False
    if verdict and _WH_RE.search(m):
        return False
    return not (states_a_fault_or_hazard(m) or names_a_place_or_thing(m))


#: Someone asked for something to be DONE: a request to fix, send or check is a report even when it
#: is phrased as a question ("can someone fix the projector?").
_REQUEST_VERB_RE = re.compile(
    r"\b(?:fix|repair|replace|clean|clear|send|come|attend|sort|look\s+at|deal\s+with|reset|"
    r"restart|please|urgent\w*|asap)\b",
    re.IGNORECASE,
)

_QUESTION_OPENER_RE = re.compile(
    r"^\s*(?:is|are|was|were|do|does|did|can|could|will|would|should|has|have|had|which|what|"
    r"who|whom|where|when|why|how|any|are\s+there|is\s+there)\b",
    re.IGNORECASE,
)


def is_question_not_a_fault(message: str) -> bool:
    """True for an INTERROGATIVE that states no fault, names no place and asks for no action.

    A long question asking whether each piece of test equipment is correctly ranged and in
    calibration was filed as a maintenance request (REP-8AC1A1). It asks; it reports nothing. The same three-part test as :func:`is_not_a_report`,
    asymmetric for the same reason: a fault word, a place or a request verb keeps whatever lane
    it had, including being filed.
    """
    m = (message or "").strip()
    if not m:
        return False
    if not ("?" in m or _QUESTION_OPENER_RE.search(m)):
        return False
    return not (
        states_a_fault_or_hazard(m) or names_a_place_or_thing(m) or _REQUEST_VERB_RE.search(m)
    )


QUESTION_REPLY = (
    "**I read that as a question, so nothing has been filed.** If something is broken or unsafe, "
    "tell me what it is and where and I will log it; otherwise ask again as a question about the "
    "building's records, equipment or readings."
)


def is_building_verdict_request(message: str) -> bool:
    """True for "is the building safe?" and its variants, naming no fault, hazard or place.

    Narrower than :func:`is_not_a_report` on purpose: a message that is merely HEDGED ("whether CO2
    is high") is a data question whichever way it is phrased. Only a verdict on the whole building is
    a request no lane can answer as asked — the records show checks and equipment, never "safe".
    """
    m = (message or "").strip()
    if not m or not _VERDICT_RE.search(m) or _WH_RE.search(m):
        return False
    return not (states_a_fault_or_hazard(m) or names_a_place_or_thing(m))


def is_safety_ask(message: str) -> bool:
    """True when the message is about safety in general."""
    return bool(_SAFETY_WORD_RE.search(message or ""))


SAFETY_REPLY = (
    "**I can't certify a building as safe, and nothing has been filed** — no report was made, "
    "because nothing was described. What the records CAN show is whether safety checks are overdue "
    "and whether fire-safety equipment is defective. Try *which compliance checks are overdue?* or "
    "*which fire safety assets are defective?* — or, if you have seen a specific hazard, tell me "
    "what it is and where, and I will file it."
)

GENERIC_REPLY = (
    "**Nothing has been filed** — I need to know what is wrong and where. Tell me the fault and the "
    "room, floor or equipment and I will log it, or ask me a question about the building instead."
)


def reply_for(message: str) -> str:
    """What to say to a message that is not a report: an honest answer, never a tracking number."""
    return SAFETY_REPLY if is_safety_ask(message) else GENERIC_REPLY


def clarification_for(message: str) -> Optional[str]:
    """The clarification text when ``message`` is not a report, else None."""
    return reply_for(message) if is_not_a_report(message) else None
