# -*- coding: utf-8 -*-
"""Say when a request's second half went unserved (V12-06, review T07, case B14).

    "A lane merely claiming a question must not be treated as evidence that the entire
     request was answered."   — architecture review, p. 5

THE GAP, VERIFIED IN THE CODE RATHER THAN ASSUMED
--------------------------------------------------
`dialogue_agent._promote_to_capability_from_documents` returns immediately unless the
intent is one of `("general", "general_knowledge", "clarification", None)`. So:

    "Which rooms were stuffy yesterday, and what does the manual say to do about it?"

classifies as a data question, gets the observations, and **the procedure half is never
attempted and never mentioned**. The user cannot tell the difference between "the manual
says nothing" and "nobody looked".

That inversion was the right fix for BUG-440 — before it, the document lane claimed the
WHOLE question and answered a structural query from a cleaning register with 6 of 48 rooms.
The review accepts the fix and names its limit (p. 5): it does not establish that documents
should always be ignored once any other lane can answer part of a request.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
A small bounded rule over a few documented combinations. The review is specific that the
answer here is NOT an autonomous planner (p. 5: *"begin with a small, bounded composition
rule, not an unrestricted autonomous planner"*), and this does not decompose, dispatch or
re-route anything. It notices that a request had two halves, sees which one the answering
lane could possibly have served, and says the other was not attempted.

Saying so is the whole contribution. An unserved half that is NAMED costs the reader one
follow-up question; an unserved half that is silent costs them a wrong belief.

DETERMINISTIC ON PURPOSE
------------------------
No LLM call. `MultiIntentDetector` exists and is gated behind `MULTI_INTENT_ENABLED`, and
it is a decomposer — exactly the thing the review says not to reach for first. A regex over
a handful of connectors cannot mis-decompose a question, because it never decomposes one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

#: The two halves this rule knows about. Deliberately two, not a taxonomy.
OBSERVATIONS = "observations"
GUIDANCE = "guidance"

#: Intents that answer from readings, the graph or computation. These serve OBSERVATIONS
#: and cannot serve GUIDANCE — documented prose is not on their path.
_OBSERVATION_INTENTS = frozenset({
    "sensor_data", "analytics", "compare", "trend", "report", "metadata", "discovery",
    "anomaly", "recommend", "compliance", "deliberate", "spatial_query", "floor_plan",
    "register", "events", "asset_state", "readiness_check", "diagnosis",
})

#: Intents that answer from uploaded documents. These serve GUIDANCE.
_GUIDANCE_INTENTS = frozenset({"capability"})

#: A request asks for GUIDANCE when it asks what to DO, or what a document SAYS.
#: Each pattern was chosen to need an explicit document-ish or action-ish cue — "what
#: should I do", "what does the manual say" — never a bare "how" or "why", which the data
#: lanes answer perfectly well on their own.
_GUIDANCE_CUES = (
    r"what (?:does|do) the (?:manual|policy|procedure|guidance|handbook|documentation|docs?)\b",
    r"\b(?:manual|policy|procedure|guidance|handbook|sop)\s+(?:say|says|state|states|require)",
    r"what should (?:i|we|they|it)\b.*\bdo\b",
    r"what (?:do|should) (?:i|we) (?:do|follow)\b",
    r"\bwho (?:do|should) (?:i|we) (?:contact|call|notify|report)\b",
    r"\bwhat(?:'s| is) the (?:policy|procedure|process|protocol)\b",
    r"\bhow (?:do|should) (?:i|we) (?:report|escalate|fix|resolve)\b",
)

#: A request asks for OBSERVATIONS when it asks for readings, counts or a comparison.
_OBSERVATION_CUES = (
    r"\b(?:which|what|how many|list|show)\b.*\b(?:rooms?|zones?|floors?|spaces?|sensors?)\b",
    r"\b(?:temperature|co2|humidity|noise|occupancy|illuminance|energy|readings?)\b",
    r"\b(?:stuffy|warm|cold|hot|noisy|busy|crowded|bright|dark)\b",
    r"\b(?:average|mean|max|min|highest|lowest|compare|trend)\b",
)

#: The connectors that join two halves. Without one of these a question is single, however
#: many cues it happens to contain — "what should I do about the temperature" is ONE
#: request for guidance, not two.
_CONNECTORS = (
    r",?\s+and\s+(?:also\s+)?",
    r",?\s+then\s+",
    r";\s*",
    r",?\s+plus\s+",
    r"\?\s+(?:and\s+)?",
)


@dataclass(frozen=True)
class Composition:
    """A request that asked for two different kinds of thing."""

    parts: Tuple[str, ...]
    #: The clause carrying the half a data lane cannot serve, for the reader's benefit.
    guidance_clause: str = ""


def _matches(text: str, cues) -> bool:
    return any(re.search(c, text, re.IGNORECASE) for c in cues)


def detect(question: str) -> Optional[Composition]:
    """Does this request ask for BOTH observations and documented guidance?

    Returns None for the ordinary single-purpose question, which is almost all of them.
    A rule that fires often is a rule that annotates every answer with a caveat, and a
    caveat on every answer is read as boilerplate and then not read at all.
    """
    text = (question or "").strip()
    if not text:
        return None

    clauses = re.split("|".join(_CONNECTORS), text)
    clauses = [c.strip() for c in clauses if c and c.strip()]
    if len(clauses) < 2:
        return None

    has_obs = any(_matches(c, _OBSERVATION_CUES) for c in clauses)
    guidance_clause = next((c for c in clauses if _matches(c, _GUIDANCE_CUES)), "")
    if not (has_obs and guidance_clause):
        return None
    return Composition(parts=(OBSERVATIONS, GUIDANCE), guidance_clause=guidance_clause)


def unserved_note(question: str, served_intent: Optional[str]) -> Optional[str]:
    """The sentence to append, or None when nothing was left unserved.

    Returns None — silently — whenever the request was single-purpose, the lane that
    answered could have served both, or the intent is unknown. Being quiet in the ordinary
    case is what keeps the note meaningful in the rare one.
    """
    comp = detect(question)
    if comp is None:
        return None
    intent = (served_intent or "").strip()

    if intent in _OBSERVATION_INTENTS:
        clause = comp.guidance_clause.rstrip("?.").strip()
        tail = f' — "{clause}"' if clause else ""
        return (
            "**I answered only the first half of that.** The second part"
            f"{tail} asks what the building's documents say, and I did not consult them "
            "for this answer. I am not telling you they are silent on it — I did not look. "
            "Ask that part on its own and I will search the uploaded documents."
        )
    if intent in _GUIDANCE_INTENTS:
        return (
            "**I answered only the documented half of that.** The other part asks for "
            "readings, which I did not retrieve here. Ask it on its own and I will."
        )
    return None
