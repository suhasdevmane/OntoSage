# -*- coding: utf-8 -*-
"""A question that names no place, time, record or measured thing must not reach the sensor fetch.

The failure this prevents (dev tail C, 2026-09-19). Five questions with NOTHING for a sensor read to
be about were classified `sensor_data` and refused with "that question reaches 296 sensors -- more
than I can read row by row":

* *"Can temperature or humidity affect the CO2 sensor?"* -- a knowledge question;
* *"How can occupancy sensors lead to more efficient use?"* -- a knowledge question;
* *"What lux level is maintained for reading tasks?"* -- a DESIGN-STANDARD question: it asks what
  level the lighting is designed to keep for a task, which a reading cannot answer;
* *"Which approved nearby space is suitable for a brief quiet pause before my next appointment?"* --
  a workspace-register question: it asks which spaces are approved and suitable, not what any sensor
  says.

The refusal is honest and useless: the reader named nothing, so no narrowing they could do would
help. The question never belonged to the fetch. This module is the SHAPE TEST that says where it does
belong; the routing contract applies it and the fetch lanes never see the question.

Hand-off, in the order the owner set (register reach first, design standard second, guidance last):

* a SPACE-SUITABILITY question ("which approved space is suitable for ...") -> the register lane
  (`metadata`), which holds the approved workspaces and their profiles;
* a DESIGN-STANDARD question ("what lux level is maintained for reading tasks") -> the documents and
  operating-regime records (`capability`), which say what the building keeps; a building that records
  no such level says so, and never gets a sensor's reading offered as if it were the design value;
* a KNOWLEDGE question -> labelled general guidance (`general_guidance`), decided by
  `guidance_shape`.

Grounding is the gate for all three: a named room or floor, a time window, "this/our building", a
record kind or a sensor id means the asker wants THIS building's answer and the data lanes own it.

Pure and building-agnostic: English only.
"""

from __future__ import annotations

import re
from typing import Optional

#: The intents whose next stop is the all-sensors fetch. A question already in any other lane is
#: never touched by the rule that uses this module.
FETCH_INTENTS = (
    "sensor_data",
    "analytics",
    "trend",
    "compare",
    "anomaly",
    "recommend",
    "compliance",
)

# ── grounding ────────────────────────────────────────────────────────────────

#: Something in the question ties it to a place, a moment or a record of THIS building.
_GROUNDING_RE = re.compile(
    # a time window, or "now"
    r"\b(?:today|tonight|tomorrow|yesterday|now|current(?:ly)?|at\s+the\s+moment|this\s+(?:morning|"
    r"afternoon|evening|week|month|year|term|semester)|last\s+(?:night|week|month|year|hour|\d+)|"
    r"past\s+\d+|recent(?:ly)?|lately|so\s+far|next\s+(?:week|month|year)|\d{1,2}\s?(?:am|pm)|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day)\b"
    # a NAMED place
    r"|\b(?:room|rm|floor|level|zone|storey|wing|block)\s*[\d.]+"
    r"|\b\d{1,2}\.\d{1,3}\b"
    # this / our building, or "here"
    r"|\b(?:this|our)\s+(?:building|site|campus|estate|atrium|library|canteen|reception|roof|"
    r"basement|car\s+park|floors?|rooms?|spaces?|zones?)\b"
    r"|\bhere\b|\bin\s+(?:this|the)\s+building\b"
    # a record kind
    r"|\b(?:register|records?|logs?|tickets?|work\s*orders?|bookings?|permits?|certificates?|"
    r"audits?|policy|policies|manual|documents?|according\s+to)\b"
    # a sensor id
    r"|\b\w+_sensor_[\d.]+\b|\buuid\b",
    re.IGNORECASE,
)


def has_grounding(question: str) -> bool:
    """True when the question is tied to a place, a time, a record or "this building"."""
    return bool(_GROUNDING_RE.search(question or ""))


# ── the shapes ───────────────────────────────────────────────────────────────

#: What level, setpoint or limit is KEPT / REQUIRED / SPECIFIED for a kind of task or space. The
#: answer is a design value, which a reading is not: "what lux level is maintained for reading
#: tasks?" asks what the lighting is designed to keep.
_QUANTITY = (
    r"level|levels|setpoint|set[- ]point|temperature|humidity|lux|illuminance|lighting|light|"
    r"ventilation|airflow|air\s+changes?|rate|limit|threshold|target|standard|value"
)
_KEPT = (
    r"maintained|required|specified|targeted|recommended|provided|kept|designed|needed|expected|"
    r"acceptable|allowed|permitted|appropriate|mandated|stipulated"
)
DESIGN_STANDARD_RE = re.compile(
    rf"\b(?:what|which)\b[^?.!]{{0,40}}\b(?:{_QUANTITY})\b[^?.!]{{0,25}}\b(?:{_KEPT})\b[^?.!]{{0,30}}"
    r"\b(?:for|in)\b\s+(?:a\s+|an\s+|the\s+)?(?!this\b|our\b)\w+",
    re.IGNORECASE,
)

#: Which SPACE is suitable / approved / available for an ACTIVITY a person does there. Asks for a
#: choice among the building's spaces, which the workspace register (approved, bookable, quiet,
#: private) answers. The activity after "for" must be one a PERSON does in a space: the first draft
#: took any "suitable ... for" and claimed "which zones have pre- and post-retrofit data suitable for
#: a natural experiment?", a question about data.
_PERSON_ACTIVITY = (
    r"call|calls|meeting|meetings|study|studying|work|working|pause|break|rest|resting|focus|"
    r"focused|reading|prayer|quiet|private|conversation|interview|nap|lunch|session|sessions|"
    r"appointment|wellbeing|recovery|reflection|thinking|writing|video|phone|group"
)
SUITABLE_SPACE_RE = re.compile(
    r"\b(?:which|what)\s+(?:\w+\s+){0,3}?(?:spaces?|rooms?|areas?|places?|spots?|zones?)\b"
    r"[^?.!]{0,40}\b(?:suitable|appropriate|approved|eligible|ideal|good|quiet|calm|private)\b"
    rf"[^?.!]{{0,40}}\bfor\b[^?.!]{{0,25}}\b(?:{_PERSON_ACTIVITY})\b",
    re.IGNORECASE,
)

#: Words that turn a "suitable for" question back into a question about DATA.
_DATA_WORDS_RE = re.compile(
    r"\b(?:data|readings?|sensors?|measurements?|experiment|retrofit|analysis|analytics|trend|"
    r"statistics|dataset|series)\b",
    re.IGNORECASE,
)

#: A live or located question: the ranking lane and the data lanes keep it.
_LIVE_OR_PLACED_RE = re.compile(
    r"\b(?:today|tonight|tomorrow|now|this\s+(?:morning|afternoon|evening)|right\s+now)\b"
    r"|\b(?:room|rm|floor|level|zone)\s*[\d.]+|\b\d{1,2}\.\d{1,3}\b",
    re.IGNORECASE,
)


def design_standard_question(question: str) -> bool:
    """True when the question asks what level or limit is KEPT for a task or kind of space."""
    q = question or ""
    return bool(DESIGN_STANDARD_RE.search(q)) and not has_grounding(q)


def suitable_space_question(question: str) -> bool:
    """True when the question asks which of the building's spaces suit an activity."""
    q = question or ""
    if not SUITABLE_SPACE_RE.search(q) or _DATA_WORDS_RE.search(q):
        return False
    return not _LIVE_OR_PLACED_RE.search(q)


# ── shapes that ask for ADVICE, PHYSICS or REQUIREMENTS, never a reading ─────

#: "How can we optimize lighting usage?" asks what to DO. The asker's own "we" makes the guidance
#: rule call it grounded (deliberately: "how can we cut OUR bill" is about an estate), but no reading
#: answers it, and the fetch refused it as "that covers 269 illuminance sensors".
ADVICE_RE = re.compile(
    r"^\s*(?:(?:and|so|ok|okay|please)\b[,\s]*)*how\s+(?:can|could|should|might|would)\s+"
    r"(?:we|i|you|one|the\s+building)\s+(?!know\b|tell\b|see\b|check\b|find\b|view\b|get\b|"
    r"access\b|book\b|report\b|reach\b|contact\b)\w+",
    re.IGNORECASE,
)

#: A physical process asked about in general: "in the windows how will the air flow".
PHYSICS_RE = re.compile(
    r"\bhow\s+(?:will|would|does|do|can|could)\s+(?:the\s+|a\s+)?(?:air|heat|warmth|light|sound|noise|"
    r"water|moisture|smoke|wind|humidity|sunlight|daylight|draughts?|drafts?)\s+"
    r"(?:flow|move|travel|spread|rise|circulate|escape|enter|behave|disperse|get\s+(?:in|out))\b",
    re.IGNORECASE,
)

#: What must be IN PLACE for a piece of work or a kind of hazard: "what containment and monitoring are
#: required for noise, dust ... from this job?" asks for requirements, which live in documents and
#: standards, not in a sensor's rows.
REQUIREMENTS_RE = re.compile(
    r"\bwhat\s+(?:\w+\s+(?:and\s+|or\s+)?){0,3}?(?:containment|monitoring|controls?|measures?|"
    r"precautions?|safeguards?|mitigations?|protection|permits?|approvals?|training|ppe)\b"
    r"[^?.!]{0,30}\b(?:is|are)\s+(?:required|needed|necessary|expected|specified|mandatory)\b",
    re.IGNORECASE,
)


_POSSESSIVE_RE = re.compile(r"\b(?:my|our)\s+\w+", re.IGNORECASE)


#: A DESIGN-ADEQUACY question: "is there sufficient exhaust ventilation to prevent mold growth?" asks
#: whether a provision is enough for a purpose. A judgement about design, answered from the
#: building's documents or not at all; it was refused as "that covers all 280 CO2 sensors".
ADEQUACY_RE = re.compile(
    r"\b(?:is|are)\s+there\s+(?:sufficient|enough|adequate|ample|any\s+adequate)\s+(?:\w+[\s-]+){1,3}?"
    r"to\s+\w+|\b(?:is|are)\s+(?:the\s+)?(?:\w+[\s-]+){1,3}?(?:sufficient|adequate)\s+(?:to|for)\s+\w+",
    re.IGNORECASE,
)


def adequacy_question(question: str) -> bool:
    """True when the question asks whether a provision is enough for a purpose."""
    q = question or ""
    return bool(ADEQUACY_RE.search(q)) and not has_grounding(q) and not _DATA_WORDS_RE.search(q)


def advice_or_physics_question(question: str) -> bool:
    """True for advice or a physical-process question that no reading of this building answers."""
    q = question or ""
    if not (ADVICE_RE.search(q) or PHYSICS_RE.search(q)):
        return False
    # "my lab", "our roof": the asker names a thing of THEIRS, which is a place to read from
    if has_grounding(q) or _DATA_WORDS_RE.search(q) or _POSSESSIVE_RE.search(q):
        return False
    return True


def requirements_question(question: str) -> bool:
    """True when the question asks what is REQUIRED for a job or hazard (a document question)."""
    q = question or ""
    return bool(REQUIREMENTS_RE.search(q)) and not has_grounding(q) and not _DATA_WORDS_RE.search(q)


def handoff(question: str) -> Optional[str]:
    """The lane a fetch-bound question should go to instead, or None when the fetch may keep it.

    "metadata" is the register lane, "capability" the documents and operating-regime records. The
    knowledge case is `guidance_shape`'s and is deliberately not decided here, so one definition
    owns it.
    """
    if suitable_space_question(question):
        return "metadata"
    if design_standard_question(question):
        return "capability"
    if requirements_question(question) or adequacy_question(question):
        return "capability"
    if advice_or_physics_question(question):
        return "general_guidance"
    return None
