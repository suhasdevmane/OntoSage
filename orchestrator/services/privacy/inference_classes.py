# -*- coding: utf-8 -*-
"""
inference_classes.py — question-shape → privacy inference class (V5-T42).

The policy triples deny three inference CLASSES for every role
(individual_presence, individual_pattern, private_content), but nothing
mapped a QUESTION to a class — so "Is the professor in her office?" sailed
past the denial into a clarification that helpfully invented professor names
(leak-benchmark traps P201/P202). This module is that mapping: deterministic
shapes over generic English (person words + presence/tracking predicates),
never a building name or a real person's name.

Classes returned:
  individual_presence  — where a specific person is right now / was
  individual_pattern   — tracking a person over time (badge history, how often)
  private_content      — other people's messages, complaints, preferences, CCTV
  policy_override      — "ignore your policies / maintenance mode" injections

A room-level aggregate is NEVER matched: "is anyone in the wellness room?"
(a count) passes; "…and who?" (identification) does not.
"""

from __future__ import annotations

import re
from typing import Optional

#: words that refer to a specific person (generic English, no names)
_PERSON = (
    r"(?:professor|lecturer|doctor|dr\.?|manager|boss|director|colleague|"
    r"co[- ]?worker|office[- ]?mate|officemate|neighbou?r|secretary|"
    r"receptionist|cleaner|janitor|caretaker|technician|the person|that person|"
    r"someone specific|my (?:boss|manager|colleague|neighbou?r))"
)

_PRESENCE_PRED = r"(?:in (?:his|her|their|the)? ?office|at (?:his|her|their) desk|in the (?:building|room|lab|office)|present|on site|at work)"

INDIVIDUAL_PRESENCE_RE = re.compile(
    rf"\b(?:is|was|are)\s+(?:the\s+)?{_PERSON}\b.{{0,40}}\b{_PRESENCE_PRED}"
    rf"|\bwho(?:'s| is| was| were)\b.{{0,50}}\b(?:in|inside|occupying|present|using)\b"
    rf"|\b(?:and|but)\s+who\b"
    rf"|\bwhich (?:single|one|specific) (?:office|room|desk) (?:is|was) occupied\b"
    rf"|\bwho occupie[sd]\b"
    rf"|\b(?:everyone|everybody)(?:'s)? (?:presence|location|whereabouts)\b"
    rf"|\bwho is in the building\b|\bwho'?s in the building\b"
    rf"|\bexactly who is\b|\broom by room\b.{{0,30}}\bwho\b|\bwho\b.{{0,30}}\broom by room\b",
    re.IGNORECASE,
)

INDIVIDUAL_PATTERN_RE = re.compile(
    rf"\btrack\b.{{0,50}}\b(?:{_PERSON}|person|someone|anyone|individual)\b"
    rf"|\bhow often\b.{{0,40}}\b(?:{_PERSON}|is at their desk|at the desk)\b"
    rf"|\bbadge (?:history|records?|swipes?|data)\b"
    rf"|\bwhen did\b.{{0,50}}\b(?:leave|arrive|last leave|come in)\b.{{0,30}}\b(?:office|building|work)?\b"
    rf"|\b{_PERSON}(?:'s)?\b.{{0,30}}\b(?:movements?|comings and goings|schedule|attendance)\b"
    rf"|\bper[- ]minute\b.{{0,60}}\b(?:single|one)[- ]occupant\b"
    rf"|\b(?:single|one)[- ]occupant\b.{{0,60}}\bper[- ]minute\b"
    # differencing / isolation attacks: aggregates crafted to isolate ONE person
    rf"|\bexcept the {_PERSON}'?s?\b"
    rf"|\bthe (?:one|single|only) occupied (?:office|room|desk)\b"
    rf"|\bbefore anyone else arrive[sd]?\b"
    rf"|\bjust the \w+ office and the empty\b"
    rf"|\bsame (?:private|single|individual) office\b.{{0,60}}\b(?:each|every) hour\b"
    # reconstruction attacks: repeating shifted aggregates to defeat the k-floor
    rf"|\brepeat(?:ing)?\b.{{0,60}}\b(?:aggregate|quer(?:y|ies)|question)\b.{{0,60}}"
    rf"\b(?:\d+\s*times|shifting|rotating|varying)\b"
    rf"|\bshift(?:ing)? the room set\b"
    rf"|\bk[- ]protected\b|\bnarrow(?:ing)? down\b.{{0,40}}\b(?:aggregate|who)\b",
    re.IGNORECASE,
)

PRIVATE_CONTENT_RE = re.compile(
    rf"\bcctv\b|\bcamera(?:s)?\b.{{0,30}}\b(?:saw|see|footage|recorded)\b"
    rf"|\bwhat did the (?:cctv|cameras?)\b"
    rf"|\bcomplaints?\b.{{0,40}}\b(?:my|filed by|from)\b.{{0,30}}\b(?:colleague|coworker|{_PERSON})\b"
    rf"|\b(?:my|the) colleague(?:'s)? (?:complaints?|reports?|requests?)\b"
    rf"|\bwith (?:his|her|their) names?\b|\bby name\b"
    rf"|\bwhat (?:preferences?|settings?) (?:has|have|did)\b.{{0,40}}\b(?:saved|set|stored)\b"
    rf"|\bwhat did the previous user\b|\bother users?'? (?:questions?|queries|chats?)\b"
    rf"|\b{_PERSON}(?:'s)? (?:preferences?|settings?|profile|messages?)\b",
    re.IGNORECASE,
)

POLICY_OVERRIDE_RE = re.compile(
    r"\bignore (?:your|the|all) (?:access )?polic(?:y|ies)\b"
    r"|\bignore (?:your|the) privacy\b"
    r"|\bprivacy (?:rules?|checks?) (?:are|is) (?:disabled|off)\b"
    r"|\bmaintenance mode\b.{0,50}\b(?:privacy|rules?|polic)"
    r"|\bdisable (?:the )?privacy\b"
    r"|\byou are now in\b.{0,40}\bmode\b.{0,60}\b(?:privacy|rules|polic)"
    r"|\bbypass (?:the )?(?:polic|privacy|protection)"
    r"|\bfor this one query\b.{0,60}\b(?:polic|privacy|per[- ]office|motion)"
    r"|\b(?:manager|boss|admin) (?:asked|told) me to collect\b.{0,50}\b(?:presence|everyone)"
    r"|\bexport it as\b.{0,40}\beveryone'?s presence\b"
    r"|\beveryone'?s presence data\b",
    re.IGNORECASE,
)


def classify_inference(question: str) -> Optional[str]:
    """The class this question would infer about individuals, or None."""
    q = question or ""
    if POLICY_OVERRIDE_RE.search(q):
        return "policy_override"
    if INDIVIDUAL_PRESENCE_RE.search(q):
        return "individual_presence"
    if INDIVIDUAL_PATTERN_RE.search(q):
        return "individual_pattern"
    if PRIVATE_CONTENT_RE.search(q):
        return "private_content"
    return None
