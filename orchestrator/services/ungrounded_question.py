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
    r"|\b(?:room|rm|floor|level|zone|storey|wing|block)\s*[\d.]+" r"|\b\d{1,2}\.\d{1,3}\b"
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


#: "How does the building prevent overheating?", "how are water leaks detected?", "what systems
#: are in place to keep the server room cool?", "are lights automatically adjusting?" -- a question
#: about HOW a thing is done. The answer is a procedure, a regime or a topic the building wrote
#: down; a table of readings is the right subject and the wrong kind of answer. MEASURED
#: 2026-10-02: 11 of the 4,060 bank questions, 3 of tail O, 8 of tail P -- and 8 of tail P's 14
#: WEIRD answers were this shape answered by the reading lane.
_MECHANISM_RE = re.compile(
    r"^\s*(?:"
    r"how\s+(?:does|do|is|are|would|will|can|could)\s+(?:the\s+|this\s+|your\s+|our\s+|it\s+)?"
    r"(?:building|system|it|you|we|they|[a-z]+\s+(?:sensors?|system|units?))?\b[^?]{0,80}?"
    r"\b(?:manag\w*|control\w*|detect\w*|monitor\w*|kept|keep\w*|maintain\w*|prevent\w*|"
    r"ensur\w*|handl\w*|regulat\w*|respond\w*|react\w*|adjust\w*|know\w*|decide\w*|protect\w*|"
    r"work\w*|operat\w*|track\w*|measur\w*|cope\w*|deal\w*)\b"
    r"|what\s+(?:does|do)\s+(?:the\s+)?(?:building|system|ai|it)\s+do\s+(?:if|when|to|about)"
    r"|what\s+happens\s+(?:if|when)"
    r"|can\s+(?:you|the\s+building|the\s+system|it)\s+(?:keep|maintain|control|regulate)\b"
    r")"
    r"|\bwhat\s+(?:systems?|measures?|mechanisms?|controls?|provisions?)\s+(?:are|is)\s+in\s+place\b"
    r"|\b(?:are|is|do|does)\b[^?]{0,40}\bautomatically\b"
    r"|\bwhere\s+does\b[^?]{0,40}\bcome\s+from\b",
    re.IGNORECASE,
)
#: A mechanism question that ALSO asks for a present value keeps the data lane: "how is the
#: temperature controlled and what is it right now?" wants the reading too.
_MECHANISM_VALUE_RE = re.compile(
    r"\b(?:right\s+now|currently|at\s+the\s+moment|today|this\s+(?:week|month)|yesterday|"
    r"how\s+(?:much|many|hot|cold|warm|high|low|busy)|what\s+is\s+the\s+(?:current|latest|"
    r"average|mean|max|min)|reading|value|level\s+(?:is|of)|trend\w*|compare\w*)\b",
    re.IGNORECASE,
)


def mechanism_question(question: str) -> bool:
    """True when the question asks HOW something is done, managed or detected (a procedure,
    regime or topic), and not for a present value."""
    q = question or ""
    return bool(_MECHANISM_RE.search(q)) and not _MECHANISM_VALUE_RE.search(q)


#: G2 (QA-trial plan, 2026-10-04): "How many bathrooms do you have and where are they
#: located." declined although "bathrooms" IS a declared ToiletFacility lay term. The
#: leftover words were ["many", "they"] -- "many" quantifies the counted noun, "they"
#: refers back to it -- and the subject test's one-leftover-word threshold refused at
#: two. Deliberately narrow to the "how many ... and where/is/are/do they/it" shape: a
#: bare "many"/"they" subtracted everywhere would also excuse a genuine second subject
#: ("how many complaints have THEY made about the lift" -- "they" there is a different
#: party, not the lift).
_QUANTIFIER_RE = re.compile(
    r"\bhow\s+many\b[^?.!]{0,60}\b(?:do\s+you\s+have|are\s+there|is\s+there|"
    r"where\s+(?:are|is)\s+they|where\s+(?:are|is)\s+it|they\s+located|it\s+located)\b",
    re.IGNORECASE,
)
#: Subtracted ONLY when quantifier_question() matches AND a genuine back-reference
#: pronoun is already in the leftover -- never applied on the question's shape alone.
QUANTIFIER_FRAME = frozenset("many they them their".split())
#: The pronoun half of the frame above -- confirms a counting BACK-REFERENCE is really
#: present before "many" (which, alone, is too generic a word to drop unconditionally) is
#: also dropped. See capability_graph_resolver.topic_is_the_subject for the measured false
#: positive this guards against.
QUANTIFIER_PRONOUNS = frozenset("they them their".split())


def quantifier_question(question: str) -> bool:
    """True for a 'how many <counted noun> ... and where are they/is it' shape, where a
    bare quantifier or back-reference pronoun is part of the COUNTING frame, not a second
    subject."""
    return bool(_QUANTIFIER_RE.search(question or ""))


def handoff(question: str) -> Optional[str]:
    """The lane a fetch-bound question should go to instead, or None when the fetch may keep it.

    "metadata" is the register lane, "capability" the documents and operating-regime records. The
    knowledge case is `guidance_shape`'s and is deliberately not decided here, so one definition
    owns it.
    """
    if suitable_space_question(question):
        return "metadata"
    if mechanism_question(question):
        return "capability"
    if design_standard_question(question):
        return "capability"
    if requirements_question(question) or adequacy_question(question):
        return "capability"
    if advice_or_physics_question(question):
        return "general_guidance"
    return None
