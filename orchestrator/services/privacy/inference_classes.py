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
    r"someone specific|my (?:boss|manager|colleague|neighbou?r)"
    # PRONOUNS. Found 2026-09-06 while narrowing the "and who" clause (BUG-442), and it
    # predates that: "Is he at his desk?" and "…and is she in her office right now?" both
    # passed every rule and reached the data lanes. A pronoun is the most natural way to
    # ask where a named person is once the name has been said, so the leak sits exactly
    # where a real conversation puts it.
    #
    # Only he/she/him/her, which always refer to a person. "they" and "it" are excluded on
    # purpose: "are they in the room?" is how people ask about a delivery, a meeting or a
    # set of sensors, and refusing those protects nobody.
    #
    # Safe here because every alternative using _PERSON also requires a PRESENCE PREDICATE
    # nearby -- the pronoun alone never triggers a refusal.
    r"|he|she|him|her)"
)

_PRESENCE_PRED = r"(?:in (?:his|her|their|the)? ?office|at (?:his|her|their) desk|in the (?:building|room|lab|office)|present|on site|at work)"

INDIVIDUAL_PRESENCE_RE = re.compile(
    rf"\b(?:is|was|are)\s+(?:the\s+)?{_PERSON}\b.{{0,40}}\b{_PRESENCE_PRED}"
    rf"|\bwho(?:'s| is| was| were)\b.{{0,50}}\b(?:in|inside|occupying|present|using)\b"
    # "…and who?" -- the follow-up that turns a COUNT into an IDENTIFICATION, which is
    # the case this clause exists for: "is anyone in the wellness room?" passes and
    # "…and who?" must not.
    #
    # IT USED TO BE A BARE `\b(?:and|but)\s+who\b`, and that refused any compound
    # question whose second clause began with those words. Measured 2026-09-06:
    #
    #     "What is this building and who runs it?"
    #       -> privacy_refusal: "The system explains the building; it never tracks
    #          individuals."
    #
    # The governance register that answers it holds 82 stakeholder groups and never ran.
    # A refusal that fires on grammar rather than on meaning teaches people to stop
    # asking, and it protects nobody: naming the organisation responsible for a building
    # is not tracking a person.
    #
    # Two admissible shapes now, both requiring the question to be ABOUT identifying
    # someone: a trailing "…and who?" (nothing follows, so the whole point is the
    # identity), or "and who is/are/was/were" followed by a location word.
    rf"|\b(?:and|but)\s+who\b\s*[?.!]?\s*$"
    rf"|\b(?:and|but)\s+who\s+(?:exactly\s+)?(?:is|are|was|were)\b"
    rf"\s*(?:\w+\s+){{0,3}}?\b(?:in|inside|there|here|present|occupying|using)\b"
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

#: Metered resources. A meter measures a BOUNDARY (a circuit, a floor, a building) — never a
#: person — so any question asking what one individual consumed is asking for an attribution
#: the metering cannot support (V6-T27, Master Package E).
_RESOURCE = (
    r"(?:energy|electricity|power|kwh|kw ?h|water|gas|heating|cooling|"
    r"carbon|emissions|co2 footprint|utilit(?:y|ies)|consumption|usage)"
)
_CONSUME = r"(?:use[sd]?|using|usage|consume[sd]?|consumption|spend[s]?|spent|cost[s]?|waste[sd]?)"

#: Aggregate metrics that merely NORMALISE by headcount. "Energy per capita" is a total divided
#: by a number of people; it identifies nobody, and refusing it would deny a standard
#: sustainability metric while protecting no one. Checked BEFORE the attribution patterns.
_PER_CAPITA_RE = re.compile(
    r"\bper[- ](?:capita|head|person|employee|occupant|fte|desk|workstation)\b"
    r"|\baverage\b.{0,20}\bper\b.{0,20}\b(?:person|employee|occupant|head)\b",
    re.IGNORECASE,
)

INDIVIDUAL_ATTRIBUTION_RE = re.compile(
    # first person: "how much energy did I use", "my electricity usage", "my carbon footprint"
    rf"\b(?:did|do|have)\s+i\s+{_CONSUME}\b"
    # "my <resource>" ONLY when a quantity is actually being asked about. Possessing a
    # noun is not attribution: this alternative used to fire on any "my ... water",
    # which refused "where can I fill my water bottle on floor 3?" as a privacy
    # violation (measured live, 2026-08-27) and would equally have refused "my heating
    # is not working" -- a maintenance report -- as one. The lookahead stops at
    # sentence end so a cue from the NEXT sentence cannot rescue the match.
    rf"|\bmy\s+(?:own\s+)?(?:\w+\s+){{0,2}}{_RESOURCE}\b"
    rf"(?=[^?.!]{{0,40}}\b(?:{_CONSUME}|footprint|bill|billed|total|kwh|figure)\b)"
    rf"|\bmy\s+{_RESOURCE}\s+{_CONSUME}\b"
    rf"|\bhow much\b.{{0,30}}\bdid i\b"
    # a person-superlative: "which employee uses the most electricity"
    rf"|\bwh(?:ich|o)\b.{{0,30}}\b(?:employee|staff|person|people|individual|occupant|"
    rf"colleague|tenant|resident|member of staff|user)s?\b.{{0,40}}\b{_CONSUME}\b"
    rf"|\bwh(?:ich|o)\b.{{0,30}}\b(?:employee|staff|person|individual|occupant|colleague|"
    rf"tenant|resident|user)s?\b.{{0,30}}\b{_RESOURCE}\b"
    # a named role's consumption: "the professor's energy use", "my manager's electricity"
    rf"|\b{_PERSON}(?:'s)?\b.{{0,30}}\b{_RESOURCE}\b"
    # explicit per-individual breakdowns (NOT per-capita, guarded above)
    rf"|\b(?:break ?down|split|itemi[sz]e|attribute|allocate)\b.{{0,40}}"
    rf"\bby\s+(?:person|employee|occupant|individual|staff member|name)\b"
    rf"|\b{_RESOURCE}\b.{{0,30}}\bby\s+(?:person|employee|occupant|individual|name)\b"
    rf"|\b(?:bill|charge|invoice)\b.{{0,30}}\beach\s+(?:person|employee|occupant|tenant)\b",
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


#: Asking WHO RUNS a building is a governance question, not a presence question.
#:
#: "Who manages this building?", "who is responsible for the lifts?", "who do I contact
#: about a leak?" are answered from the stakeholder and department registers -- an
#: ORGANISATION or a ROLE, never a named individual's location. They were being refused by
#: the presence rule (BUG-442), which is the worst kind of false positive: the refusal text
#: says the system never tracks individuals, which is true and has nothing to do with the
#: question asked.
#:
#: Deliberately about ROLES and ORGANISATIONS. "who is in charge" is here; "who is in the
#: building" is not, and the two are one letter apart, which is why the presence predicates
#: below are required to be absent rather than merely outranked.
_GOVERNANCE_RE = re.compile(
    r"\bwho\s+(?:runs|manages|owns|operates|maintains|cleans|looks after|is responsible"
    r"|are responsible|is in charge|do i (?:contact|call|tell|report|email|ask)"
    r"|should i (?:contact|call|tell|report|email|ask))\b"
    r"|\bwho(?:'s| is)\s+(?:the\s+)?(?:owner|operator|landlord|manager|contact|"
    r"responsible party|facilities? (?:manager|team|provider))\b",
    re.IGNORECASE,
)

#: A governance question that ALSO asks where somebody is stays refused. "Who manages this
#: building and is she in her office?" is two questions and the second one is denied.
_PRESENCE_ANYWHERE_RE = re.compile(
    rf"{_PRESENCE_PRED}|\bright now\b|\bat the moment\b|\bcurrently\b",
    re.IGNORECASE,
)


def is_governance_question(question: str) -> bool:
    """True when the question asks WHO RUNS something rather than WHERE SOMEBODY IS."""
    q = question or ""
    return bool(_GOVERNANCE_RE.search(q)) and not _PRESENCE_ANYWHERE_RE.search(q)


def classify_inference(question: str) -> Optional[str]:
    """The class this question would infer about individuals, or None."""
    q = question or ""
    if POLICY_OVERRIDE_RE.search(q):
        return "policy_override"
    # Checked BEFORE the presence rule, and only when no presence predicate is anywhere in
    # the question. An override placed after would never fire: the presence rule returns
    # first, which is exactly how "and who runs it" came to be refused.
    if is_governance_question(q):
        return None
    if INDIVIDUAL_PRESENCE_RE.search(q):
        return "individual_presence"
    if INDIVIDUAL_PATTERN_RE.search(q):
        return "individual_pattern"
    if PRIVATE_CONTENT_RE.search(q):
        return "private_content"
    # V6-T27. Guarded by the per-capita check FIRST: "energy per capita" divides a total by a
    # headcount and identifies nobody, so refusing it would deny a standard sustainability
    # metric while protecting no one.
    if not _PER_CAPITA_RE.search(q) and INDIVIDUAL_ATTRIBUTION_RE.search(q):
        return "individual_attribution"
    return None
