# -*- coding: utf-8 -*-
"""What a narration over sensor READINGS may conclude from them (BUG-1298/1302/1332).

This module was written for the anomaly lane and is now the home for every lane whose rows
are numeric readings — the sql lane included. The three defects it answers are one defect:
*a free-text model narration was asked to answer a question its rows cannot answer, and it
supplied the missing part.*

WHAT A READING LANE STRUCTURALLY CANNOT KNOW
--------------------------------------------
Its rows are ``(uuid, timestamp, value)`` plus a label and a unit. From that:

1. **No capacity, and no occupancy limit.** Family A, and family A2 for the limit stated as a
   figure — BUG-1302 tabled five *"Overcrowded areas"* against *"exceed 10 occupants"*, a
   threshold that exists nowhere in this building (its 62 ``hbco:roomCapacity`` values are all
   stamped *"estimated … Not certified"* and none is 10).
2. **No status, no fault, no issue.** A reading is a number. Family D — BUG-1332 narrated the
   six static ``ontosage:MaintenanceIssue`` KnowledgeTopics, a taxonomy of what a user *can
   report* carrying no timestamp and no status, as *"six active issues … the only recorded
   problems at the moment"*. Nothing was leaking and no lift was out of order.
3. **No order of work.** Families B and C — the fourth ask of BUG-1332 wrote a five-step
   *"Recommended recovery sequence (dependency-aware)"* addressed to an incident leader, built
   from a charger occupancy point read as "available" and a booked room read as one to re-open.
   BUG-709's rule against exactly this has lived in a prompt since 2026-09-18; **it held on
   three asks of four.** That is the whole argument for this file.

LANE SCOPE IS PART OF THE GUARD, MEASURED NOT ASSUMED
-----------------------------------------------------
BUG-1302's row says this module is "lane-agnostic by construction … a two-line call". Over the
2,912 stored answers in this repo (the 73-probe evidence pack plus every ``docs/phase0/*.jsonl``)
that is **false for families B and C**: applied lane-blind, the original family B hit 69 answers
and **24 of them were hand-read GOOD**, among them *"What is the evacuation procedure?"* — a
scripted demo question — because it matched the noun ``evacuat\\w+``. Every one of those 24 is a
``capability`` or register answer QUOTING A RECORDED PROCEDURE, which is the one thing a reading
lane never does. Family B was therefore narrowed to instruction shapes (11 hits, 8 GOOD, all
still on non-reading lanes) and the families here are applied by the reading lanes only, through
:func:`reading_lane_claims`. On the 295 stored answers whose recorded lane IS a reading lane, all
five families together hit **0**, GOOD or otherwise.

    A guard that notices less is blind; a guard that acts more carefully is still watching
    (lesson #135). Scope is the action, not the detection.

THE ORIGINAL DEFECT, FOR THE RECORD
-----------------------------------
Asked *"Can you tell me which areas are currently overcrowded?"* the anomaly lane answered:

Asked *"Can you tell me which areas are currently overcrowded?"* the anomaly lane answered:

    Two high-severity anomalies indicate that a monitored zone's occupancy sensor has spiked
    from 1.0 to 14.0 ... THIS SUGGESTS THE AREA IS CURRENTLY OVERCROWDED AND EXCEEDING SAFE
    CAPACITY LIMITS ... immediately activate the building's crowd-control protocol -- close
    adjacent access points, redirect foot traffic, and alert security ... Yes.

`planner_agent` carries a written refusal to build a lane for that question (BUG-1244),
because every capacity figure this building holds is stamped *"estimated ... Not certified"*
and the occupancy count itself was wrong by ~190x (BUG-954). The anomaly lane made the claim
anyway, through a different door than the one that was guarded.

WHY THIS IS A GUARD AND NOT A PROMPT RULE
-----------------------------------------
The prompt now says not to. A prompt is a request; this is the part that cannot be declined.
The narration is a free-text LLM completion over rows the detectors produced, and those rows
are the whole of what the lane knows.

**The lane structurally cannot know a capacity.** `_threshold_detection` emits a comfort band
from `shared.constants.COMFORT_RANGES`, `_zscore_detection` emits a distance from a series'
own mean, `_spike_detection` emits a step change. None of the three reads a room's capacity,
an occupancy limit or a fire-code figure, because nothing hands them one. So a sentence in
the narration asserting that a space is over capacity is derived from nothing, every time,
by construction -- which is why family A below is checked unconditionally rather than being
weighed against the evidence. `claims_are_supportable()` states that invariant as a test on
the rows, so a future detector that DOES carry a capacity stands the guard down instead of
silently outliving it.

**A statistic never licenses an instruction to escalate.** "Alert security", "activate the
crowd-control protocol", "evacuate" are actions about people, and the strongest thing the
rows support is "this reading is unusual for this sensor". Family B is likewise unconditional.

WHAT THE GUARD DOES, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------------
On a hit it does not decline and does not edit the sentence: it replaces the narration with
`factual_summary()`, the same deterministic bullet list the agent already falls back to when
the model is unreachable. The reader still gets every anomaly, with its column, its numbers
and its severity -- only the inference is dropped. That is lesson #135's rule applied on
purpose: *narrow what a guard is allowed to DO, not what it is allowed to notice.* A guard
that rewrote the offending clause would leave the rest of a paragraph written around it.

It is also why the patterns match CLAIM SHAPES rather than words. "capacity" alone is not a
hit -- "the ventilation capacity is unchanged" and "this is not a capacity issue" both pass;
"exceeding safe capacity limits" does not.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: Family A -- a claim about how full a space is, measured against a limit.
#: Unfounded whenever no anomaly row carries a capacity (see ``claims_are_supportable``).
_CAPACITY_CLAIM = re.compile(
    r"""
    over[-\s]?crowd\w*
  | exceed\w*\s+(the\s+)?(safe\s+|maximum\s+|permitted\s+|recommended\s+)?
        (capacity|occupancy\s+limit|occupancy\s+threshold)
  | (above|beyond|over)\s+(the\s+)?(safe\s+|maximum\s+|permitted\s+)?
        (capacity|occupancy\s+limit)
  | capacity\s+limit
  | (safe|maximum|max|permitted|legal|allowed)\s+(capacity|occupancy)
  | occupancy\s+limit
  | at\s+(or\s+near\s+)?(full\s+)?capacity
  | too\s+many\s+(people|occupants|persons)
  | fire[-\s]code
    """,
    re.I | re.X,
)

#: A CAPACITY THAT IS NOT ABOUT PEOPLE. Measured over the stored corpus: 2 of the 4 answers
#: family A hit on a recorded reading lane were *"you might want to check whether the boilers
#: are running at full capacity during peak demand"* -- a delta-T answer, about thermal
#: output, hand-readable as fine. Replacing it with a bullet list of statistics would be
#: lesson #135 for the fourth time. A capacity-word hit is therefore dropped when its
#: surrounding clause names plant and names nobody. ``lift`` is deliberately NOT here: a lift
#: at full capacity is a claim about people.
_PLANT = re.compile(
    r"\b(boiler|chiller|pump|fan|ahu|air[-\s]handling|plant|compressor|charger|batter\w+|"
    r"meter|valve|duct|pipe|circuit|tank|storage|disk|bandwidth|server|network|heater|"
    r"radiator|generator)\w*",
    re.I,
)
_OCCUPANCY_SUBJECT = re.compile(
    r"\b(occupan\w+|people|persons?|crowd\w*|headcount|head\s+count|visitors?|students?|"
    r"staff|attend\w+|seats?|seating|egress|circulation|room|space|area|zone|floor|building)\w*",
    re.I,
)
#: How far either side of a match counts as "the clause".
_WINDOW = 90

#: A SENTENCE THAT SAYS THE THING IS NOT RECORDED IS NOT A CLAIM THAT IT IS.
#:
#: This was found by the guard destroying two CORRECT answers at the lane, with the real
#: local model, on 2026-10-01 -- the third time in this repository that the apparatus was
#: the bug. Both completions had obeyed the new prompt rules and said so explicitly:
#:
#:     "No capacity limits or thresholds were supplied, so no assessment of overcrowding
#:      or safety limits can be made."
#:     "Because no capacity or threshold figures are available, I can't determine whether
#:      any of these areas are overcrowded."
#:
#: The guard replaced both, because ``overcrowd\\w*`` and ``capacity limit`` match inside a
#: refusal exactly as they match inside a claim. BUG-1298's own row records the same shape
#: one level up: *"a regex cannot tell a claim from a quotation, and mine counted a
#: quotation as a claim."*
#:
#: The markers below are deliberately EPISTEMIC rather than any negation -- the shapes a
#: correct refusal actually takes -- so "the area is not merely busy, it is overcrowded"
#: is still caught. The residual hole is accepted on purpose: a missed claim leaves the
#: prompt rule as the only defence, which is where we already were, while a destroyed
#: refusal costs a correct answer, and that is the worse of the two (lesson #135).
_ABSENCE_FRAME = re.compile(
    r"""
    \bno\s+(capacit\w+|limit\w*|threshold\w*|figure|figures|information|assessment|data|
        record\w*|basis|evidence|such)\b
  | \bnot\s+(recorded|supplied|available|provided|given|known|declared|certified|held)\b
  | \b(cannot|can\s*not|can[''’]t|could\s*not|couldn[''’]?t|unable\s+to|no\s+way\s+to)\b
  | \b(do|does|did)\s*(not|n[''’]t)\s+(have|hold|contain|record|include|know)\b
  | \b(doesn|don|didn)[''’]?t\s+(have|hold|contain|record|include|know)\b
  | \bwithout\s+(a\s+|any\s+)?(capacit\w+|limit\w*|threshold\w*|figure)\b
  | \bnothing\s+(records|in\s+the\s+records|recorded)\b
  | \bis\s+not\s+(a\s+)?(capacity|limit|threshold|rating|setpoint)\b
  | \bnone\s+(of\s+them\s+)?is\s+a\s+(declared|recorded)\b
  | \bno\s+[\w-]+(\s+[\w-]+){0,2}\s+(is|are|was|were)\s+
        (recorded|held|available|supplied|known|declared|provided)\b
    """,
    re.I | re.X,
)
#: Sentence-ish boundaries. A markdown table cell is its own clause, so the "not recorded"
#: in a `| sensor name not recorded |` row cannot excuse a claim in the prose below it.
_CLAUSE_SPLIT = re.compile(r"[.!?\n|;]")


def _clause_around(text: str, start: int, end: int) -> str:
    """The sentence or table cell the match sits in."""
    left = 0
    for m in _CLAUSE_SPLIT.finditer(text, 0, start):
        left = m.end()
    right = len(text)
    m = _CLAUSE_SPLIT.search(text, end)
    if m:
        right = m.start()
    return text[left:right]


#: Family A2 -- an occupancy LIMIT stated as a figure (BUG-1302). Distinct from family A
#: because the sentence can be entirely unemotional: *"the only ones that exceed 10
#: occupants"*. Deliberately restricted to counts of PEOPLE. An earlier draft also matched
#: ``(limit|threshold|capacity|maximum|minimum) of <n>`` and hit seven hand-read-GOOD answers
#: in the stored corpus -- six of them reporting a series' own ``minimum of 450.0 ppm`` /
#: ``maximum of 1,101.0 ppm``, which is a COMPUTED STATISTIC, and one quoting a register's
#: recorded ``CO2 limit of 900 ppm``, which is a RECORDED FACT. Neither is an invention.
_OCCUPANCY_LIMIT = re.compile(
    r"""
    (exceed\w*|above|over|more\s+than)
        \s+(the\s+)?(\w+\s+){0,2}\d[\d,.]*\s*(occupants?|people|persons?|person)\b
  | (limit|threshold|capacity|cap)\s+of\s+\d[\d,.]*\s*(occupants?|people|persons?|person)\b
  | \d[\d,.]*\s*(occupants?|people|persons?)\s+(limit|maximum|capacity|threshold)\b
    """,
    re.I | re.X,
)

#: Family B -- an instruction to escalate to people. Never supported by a statistic.
#:
#: ``evacuat\w+`` used to be one alternative here. Measured over the 2,912 stored answers it
#: matched 132 times across 69 answers and 24 of those answers were hand-read GOOD --
#: "Evacuation provision", "evacuation chair", "Evacuation And Peeps", "the evacuation route,
#: record RTE-013", and the whole scripted answer to "What is the evacuation procedure?". The
#: noun is a thing this building RECORDS; only the instruction is unsupportable, so the
#: alternatives below match the instruction.
_ESCALATION = re.compile(
    r"""
    crowd[-\s]?control
  | (alert|notify|contact|inform|call)\s+(the\s+)?(security|emergency|fire\s+brigade|
        fire\s+service|police|first\s+responders)
  | call\s+emergency\s+services
  | (should|must)\s+be\s+evacuated
  | evacuate\s+(the\s+|this\s+)?(building|floor|room|area|space|zone|premises)
  | (begin|start|initiate|order|commence)\s+(an?\s+)?(evacuation|emergency\s+evacuation)
  | evacuation\s+(of\s+the\s+\w+\s+|is\s+)?(advised|recommended|required|necessary|warranted)
  | recommend\w*\s+(an?\s+)?evacuation
  | close\s+(the\s+|adjacent\s+)*(access\s+points|entrances|exits)
  | redirect\s+(the\s+)?foot\s+traffic
  | sound\s+the\s+alarm
  | raise\s+the\s+alarm
  | (activate|trigger|initiate)\s+(the\s+)?\w*\s*(protocol|emergency\s+procedure)
    """,
    re.I | re.X,
)

#: Family C -- an order of work addressed to a person (BUG-1332, BUG-709's prompt rule made
#: deterministic). A reading lane may report a number and say it is unusual; it may not tell
#: anyone what to do about the building. ``recommended investigation`` is excluded by name
#: because the anomaly prompt asks for exactly that and it is the right thing to ask for.
_OPERATIONAL_ORDER = re.compile(
    r"""
    recommended\s+(?!investigation)([\w-]+[-\s])?\s*
        (sequence|order|procedure|plan|steps?|actions?)
  | (recovery|restoration|remediation|response)\s+(sequence|order|plan|priority|steps?)
  | \bwhat\s+to\s+restore\b
  | \b(restore|restoring|re-?establish\w*)\s+(the\s+|both\s+|all\s+)?([\w-]+\s+){0,2}
        (power|supply|service|services|monitoring|ventilation|heating|cooling|lighting)\b
  | \bbefore\s+allowing\s+[\w-]+\s+(to\s+)?(enter|re-?enter|return|occupy)
  | \b(ensure|make\s+sure)\s+(that\s+)?(all|every|each)\b[^.\n]{0,100}
        \b(are|is)\s+(powered|operational|functional|working|reporting|on|energised)\b
  | \bshould\s+(be\s+)?(restored|re-?opened|powered|reset|isolated|energised)\b
  | \bre-?open\s+(the\s+)?([\w-]+\s+){0,3}(rooms?|spaces?|areas?|floors?|suites?)\b
  | \b(dispatch|send)\s+(a\s+|an\s+)?(technician|engineer|team|maintenance|warden)\b
  | \b(switch|turn)\s+(the\s+\w+\s+|them\s+|it\s+)?(back\s+)?on\s+(again|first|now)\b
    """,
    re.I | re.X,
)

#: Family D -- a static thing narrated as a live one (BUG-1332). A currency claim
#: ("at the moment", "currently listed") or an exhaustiveness claim ("the only recorded")
#: about ISSUES, when the rows carry no status column at all. See
#: :func:`rows_record_a_state`, which stands this family down if a lane ever supplies one.
_STATE_AS_LIVE = re.compile(
    r"""
    \b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+
        (currently\s+)?(active|open|outstanding|ongoing|live|unresolved|reported)\s+
        (issues?|problems?|faults?|defects?|incidents?)
  | \b(active|open|outstanding|ongoing|unresolved)\s+(issues?|problems?|faults?|incidents?)\s+
        (that|which|currently|at\s+the\s+moment|right\s+now)
  | \bthe\s+only\s+(recorded\s+|currently\s+|known\s+)?
        (issues?|problems?|faults?|defects?|incidents?)\b
  | \b(issues?|problems?|faults?|defects?|incidents?)\s+
        (currently\s+)?(listed|recorded|logged|open)\s+
        (at\s+the\s+moment|right\s+now|currently|now)\b
    """,
    re.I | re.X,
)

#: Every family a lane whose rows are numeric readings must apply. Ordered for a stable log.
_READING_LANE_FAMILIES = (
    ("capacity", _CAPACITY_CLAIM),
    ("occupancy_limit", _OCCUPANCY_LIMIT),
    ("escalation", _ESCALATION),
    ("operational_order", _OPERATIONAL_ORDER),
    ("live_state", _STATE_AS_LIVE),
)


def claims_are_supportable(anomalies: Sequence[Dict[str, Any]]) -> bool:
    """True when the rows themselves carry a capacity, so family A may stand.

    Today this is always False: no detector in this lane emits one. It is expressed as a
    question about the DATA rather than hard-coded, so that adding a capacity-aware detector
    lifts the guard by itself instead of leaving a stale prohibition behind.
    """
    for row in anomalies or ():
        if not isinstance(row, dict):
            continue
        for key in ("capacity", "room_capacity", "occupancy_limit", "declared_capacity"):
            if row.get(key) not in (None, "", 0):
                return True
    return False


def rows_record_a_state(rows: Sequence[Dict[str, Any]]) -> bool:
    """True when the rows themselves carry a status, so family D may stand.

    Today this is always False for a reading lane: its rows are ``(uuid, timestamp, value)``
    and nothing in them says a thing is broken, open or resolved. Expressed as a question
    about the DATA for the same reason as :func:`claims_are_supportable` -- a lane that one
    day hands over an issue register with a status column lifts the family by itself instead
    of leaving a stale prohibition behind.
    """
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        for key in ("status", "state", "issue_status", "condition", "fault", "resolved"):
            if row.get(key) not in (None, "", 0):
                return True
    return False


def _dedupe(hits: Sequence[str]) -> List[str]:
    """Stable order, no duplicates -- this list is logged and asserted on."""
    seen = set()
    out: List[str] = []
    for h in hits:
        h = h.strip()
        key = " ".join(h.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(h)
    return out


def _is_about_plant(text: str, start: int, end: int) -> bool:
    """True when the clause around a capacity-word hit names plant and names nobody."""
    window = text[max(0, start - _WINDOW) : end + _WINDOW]
    return bool(_PLANT.search(window)) and not _OCCUPANCY_SUBJECT.search(window)


#: What the REPORT lane may be checked for. ``operational_order`` is deliberately absent:
#: that lane's prompt asks for "Recommendations (2-3 actionable items)" on purpose, its own
#: rule already separates a system limit from a building action (BUG-506), and the stored
#: corpus holds a hand-read-GOOD report recommending "Investigate the 6.21 kWh peak … Check
#: the schedule of the equipment". Forbidding an action there would delete the feature.
#: ``escalation`` IS included: a report may recommend an investigation, never an evacuation.
REPORT_LANE_FAMILIES = ("capacity", "occupancy_limit", "escalation", "live_state")


def reading_lane_claims(
    text: str,
    rows: Sequence[Dict[str, Any]] = (),
    families: Optional[Sequence[str]] = None,
) -> List[str]:
    """The phrases in ``text`` that rows of numeric readings cannot support. [] when clean.

    ``rows`` is whatever the lane fetched. It is read only to stand a family down when the
    rows really do carry the thing the family forbids claiming (a capacity, a status).

    ``families`` selects which checks apply; all five by default. Pass
    :data:`REPORT_LANE_FAMILIES` from a lane whose job includes recommending something.

    Call this from a lane whose evidence is readings. Do NOT call it on a register,
    capability or document answer: those legitimately quote recorded procedures, and
    measured over the stored corpus that is where every false positive lives.
    """
    if not text:
        return []
    wanted = set(families) if families is not None else {n for n, _ in _READING_LANE_FAMILIES}
    hits: List[str] = []
    for name, rx in _READING_LANE_FAMILIES:
        if name not in wanted:
            continue
        if name in ("capacity", "occupancy_limit") and claims_are_supportable(rows):
            continue
        if name == "live_state" and rows_record_a_state(rows):
            continue
        for m in rx.finditer(text):
            if name == "capacity" and _is_about_plant(text, m.start(), m.end()):
                continue
            if _ABSENCE_FRAME.search(_clause_around(text, m.start(), m.end())):
                continue
            hits.append(m.group(0))
    return _dedupe(hits)


def unfounded_claims(text: str, anomalies: Sequence[Dict[str, Any]]) -> List[str]:
    """The phrases in ``text`` that the anomaly rows cannot support. [] when clean."""
    return reading_lane_claims(text, anomalies)


def factual_summary(anomalies: Sequence[Dict[str, Any]], total_records: int, cap: int = 10) -> str:
    """The detectors' own findings, with no inference added.

    Used both when the model is unreachable and when the guard replaces its narration, so the
    two paths cannot drift apart.
    """
    rows = list(anomalies or ())
    lines = [f"⚠️ {len(rows)} anomalies detected in {total_records} readings:"]
    for a in rows[:cap]:
        sev = str(a.get("severity", "")).upper() or "?"
        lines.append(f"  • [{sev}] {a.get('message', '')}")
    if len(rows) > cap:
        lines.append(f"  • … and {len(rows) - cap} more.")
    lines.append(
        "\n_These are statistical findings about individual sensor readings. They do not "
        "establish that any space is over its capacity: no capacity figure was read._"
    )
    return "\n".join(lines)


def guard(text: str, anomalies: Sequence[Dict[str, Any]], total_records: int) -> str:
    """Return ``text``, or the factual summary when it claims what the rows cannot support."""
    hits = unfounded_claims(text, anomalies)
    if not hits:
        return text
    logger.warning(
        "[anomaly_guard] ACTED: replaced a narration making %d unsupported claim(s) %r "
        "over %d anomaly row(s) (BUG-1298)",
        len(hits),
        hits[:6],
        len(anomalies or ()),
    )
    return factual_summary(anomalies, total_records)
