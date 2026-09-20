# -*- coding: utf-8 -*-
"""A building-knowledge question that needs NO building data (owner policy, 2026-09-19).

"Does humidity affect CO2 sensor accuracy?", "how do I control CO2?", "how do BREEAM and LEED
differ?", "what does a delta-T mean?" ask for knowledge, not for a reading. Sent through the data
pipeline they meet the sensor fetch and are refused with "that question reaches N sensors" -- an
honest sentence that answers a question nobody asked. Answered from the building's records they
would be invented, because no record holds a textbook. The policy is to answer them, and to LABEL
the answer as general guidance rather than as something this building's records say
(``general_guidance.py``); this module is only the SHAPE TEST that decides a question is one.

The test is conservative on purpose, because a false positive takes a data question away from the
lane that can read the building. It was measured against the 4,271 questions this project holds
(the 2,960-question stakeholder catalogue, the guard set, the probe, the demo script and every
answer file): the first draft claimed 21 of them, and 18 were data questions -- "kitchen extract
VERSUS dining room CO2", "how does the gym's air quality COMPARE with the studios", "which HVAC
alarms COULD share the same plant CAUSE". Each of those is now a negative case in the tests. Three
things must all hold:

1. a GUIDANCE FRAME at the START of the sentence -- "how do I <technical verb>", "what does X
   mean", "difference between", "does X affect Y", "why does X happen", "what causes", "how does X
   work", "what is the recommended". Anchored, because "Before approval, how would a timetable
   change affect ..." contains the same words as a knowledge question and is not one;
2. a BUILDING-DOMAIN TERM -- HVAC, air quality, a standard, a controls word -- so a how-to about
   anything else is not claimed (the off-topic decline owns those);
3. NO GROUNDING -- no named place, no time window, no "this/our/the <system>", no record kind, no
   measured-data word and no sensor id. Any of those means the asker wants THIS building's answer,
   and the data lanes own it.

Pure English and building-agnostic: nothing here names a room, a sensor or a building.
"""

from __future__ import annotations

import re
from typing import Optional

# ── 1. the frames ────────────────────────────────────────────────────────────

#: Technical verbs only. "how do I book / report / get to ..." are procedures OF THIS BUILDING,
#: answered from its documents; none of those verbs is here.
_TECH_VERB = (
    r"control|reduce|lower|raise|increase|improve|prevent|avoid|calibrate|balance|tune|optimi[sz]e|"
    r"ventilate|cool|heat|humidify|dehumidify|insulate|monitor|measure|detect|diagnose|"
    r"troubleshoot|save\s+energy|cut\s+(?:energy|emissions)|size|commission|design|maintain|test"
)

#: A sentence may open with a filler word; nothing else may come before the frame.
_LEAD = r"^\s*(?:(?:ok|okay|so|and|also|but|please|hi|hey)\b[,\s]*)*"

_FRAME_BODIES = (
    # how do I control CO2 / how can we reduce energy use / how should one ventilate a lab
    rf"how\s+(?:do|can|could|should|would|might)\s+(?:i|we|you|one|someone|people)\s+"
    rf"(?:\w+\s+){{0,2}}?(?:{_TECH_VERB})\b",
    # how does a heat pump work / how is CO2 measured
    r"how\s+(?:does|do|is|are)\b[^?.!]{0,50}\b(?:work|works|function|functions|operate|operates|"
    r"measured|calculated)\b",
    # how do BREEAM and LEED differ  (NOT "compare": "how does the gym compare" is a data question)
    r"how\s+(?:does|do|is|are)\b[^?.!]{0,50}\bdiffer\b",
    # what is the difference between BREEAM and LEED
    r"(?:what\s+(?:is|are)\s+)?(?:the\s+)?differences?\s+between\b",
    # what does a delta-T mean / what does PUE stand for  (NOT "indicate": that is a telemetry ask)
    r"what\s+(?:does|do)\b[^?.!]{0,40}\b(?:mean|stand\s+for)\b",
    # what is a delta-T / what is HVAC
    r"what\s+(?:is|are)\s+(?:a|an)\s+\w[\w\s-]{0,30}\??\s*$",
    r"what\s+is\s+(?:[A-Z]{2,7}|[a-z]+-[a-z]+)\b\??\s*$",
    r"define\b",
    # does humidity affect CO2 sensor accuracy
    r"(?:does|do|can|will|would|could)\s+(?!you\b|i\b|we\b|it\b|the\s+system\b)[\w\s,/-]{1,40}?\s"
    r"(?:affect|impact|influence|interfere\s+with|depend\s+on|cause|reduce|increase|change)\b",
    # why does CO2 build up when a room is shut
    r"why\s+(?:does|do|is|are|would|might)\b[^?.!]{0,60}"
    r"\b(?:matter|important|rise|rises|build|builds|increase|increases|drop|drops|happen|happens|"
    r"cause|causes|occur|occurs|fail|fails|leak|leaks|smell|smells)\b",
    # what causes condensation / what happens when a filter clogs
    r"what\s+(?:causes|happens\s+(?:if|when|to)|are\s+the\s+(?:benefits|risks|effects|causes|"
    r"signs|advantages|disadvantages|requirements))\b",
    # what is the recommended / safe level
    r"what\s+(?:is|are)\s+(?:the|a)\s+(?:recommended|ideal|safe|healthy|acceptable|legal|"
    r"required|target|guideline)\b",
    # explain how ... / how to ...
    r"explain\s+(?:how|what|why|the\s+(?:concept|idea|principle|term))\b",
    r"how\s+to\s+\w+",
    # how can occupancy sensors lead to more efficient use / how do meters help
    #
    # The BENEFIT frame, added 2026-09-19 after the live run: this question was classified
    # `sensor_data` and refused with "that question reaches 250 sensors", which answers nothing —
    # it asks what a kind of sensor is FOR. The subject may not be the asker ("how can I reduce
    # CO2" is the technical-verb frame above), so `i/we/you` are excluded here to keep one frame
    # per shape.
    r"how\s+(?:can|could|do|does|would)\s+(?!(?:i|we|you)\b)[\w\s,/-]{1,40}?\s"
    r"(?:lead\s+to|help|improve|save|reduce|contribute\s+to|enable|support|benefit|increase)\b",
)

_FRAMES = re.compile(_LEAD + r"(?:" + "|".join(_FRAME_BODIES) + r")", re.IGNORECASE)

# ── 2. the domain ────────────────────────────────────────────────────────────

_DOMAIN = re.compile(
    r"\b(?:hvac|ventilat\w*|air\s+quality|iaq|indoor\s+air|co2|carbon\s+(?:dioxide|monoxide)|"
    r"vocs?|tvoc|pm\s?2\.?5|pm\s?10|particulate\w*|humidity|humidif\w*|dehumidif\w*|dew\s?point|"
    r"temperature|thermal|comfort|heating|cooling|chillers?|boilers?|heat\s+pumps?|ahus?|"
    r"air\s+handl\w*|vavs?|dampers?|ducts?|ductwork|fan\s+coils?|filters?|filtration|refrigerant\w*|"
    r"delta[- ]?t|set\s?points?|thermostats?|bms|bas|building\s+(?:management|automation|"
    r"energy|services|controls?|regulations?)|commissioning|calibrat\w*|sensors?|meters?|"
    r"sub-?meter\w*|energy|electric\w*|kwh|power\s+factor|demand\s+response|lighting|daylight\w*|"
    r"glare|lux|illuminance|acoustic\w*|noise|reverberation|occupancy|occupant\w*|buildings?|"
    r"breeam|leed|well\s+(?:standard|building|certification)|ashrae|cibse|passivhaus|epc|"
    r"iso\s*\d{4,5}|net[- ]?zero|carbon\s+(?:footprint|emissions?)|decarboni[sz]\w*|"
    r"sustainab\w*|insulat\w*|airtight\w*|thermal\s+bridg\w*|condensation|mou?ld|legionella|"
    r"fire\s+(?:safety|alarm|door|detection)|sprinklers?|water\s+(?:quality|efficiency|leak\w*|"
    r"hygiene)|rainwater|greywater|recycl\w*|facilit(?:y|ies)|maintenance|fault\s+detection|"
    r"digital\s+twin|brick\s+schema|bacnet|modbus|smart\s+building|pue|cop|seer|eer|hepa|merv|"
    r"u-?value|r-?value|radon|nox|no2|ozone|formaldehyde|photovoltaic\w*|solar\s+(?:panels?|pv))\b",
    re.IGNORECASE,
)

# ── 3. the grounding that hands the question back to the data lanes ──────────

_GROUNDING = re.compile(
    # a time window, or "now" / "current"
    r"\b(?:today|tonight|tomorrow|yesterday|now|current(?:ly)?|at\s+the\s+moment|this\s+(?:morning|"
    r"afternoon|evening|week|month|year|term|semester)|last\s+(?:night|week|month|year|hour|\d+)|"
    r"past\s+\d+|recent(?:ly)?|lately|so\s+far|next\s+(?:week|month|year)|\d{1,2}\s?(?:am|pm)|"
    # a part of the DAY is a window as much as a date is: "overnight", "at night", "out of hours"
    r"overnight|at\s+night|during\s+the\s+night|after\s+hours|out\s+of\s+hours|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day)\b"
    # a NAMED place: room 5.01, floor 3, zone 2.14, a bare 5.01
    r"|\b(?:room|rm|floor|level|zone|storey|wing|block)\s*[\d.]+"
    r"|\b\d{1,2}\.\d{1,3}\b"
    # this / our / my building, or "here"
    # The PLURAL is grounding too: "what happens to the buildingS energy use overnight" named a
    # place and a window and was answered as general guidance, because "buildings" failed a list
    # that only knew the singular (live 2026-09-19). An apostrophe is not required either — people
    # write "the buildings energy use".
    r"|\b(?:this|our|my|your|the)\s+(?:buildings?|sites?|campus(?:es)?|estates?|atrium|librar(?:y|ies)|"
    r"canteens?|receptions?|labs?|laborator(?:y|ies)|offices?|plant\s+rooms?|server\s+rooms?|"
    r"roofs?|basements?|car\s+parks?|floors?|rooms?|spaces?|zones?)\b"
    r"|\bhere\b|\bin\s+(?:this|the)\s+building\b"
    # "the sprinkler system", "the control strategy": a DEFINITE article before a system noun
    # points at this building's own equipment.
    #
    # `sensor` and `meter` are NOT in this list, and that is measured: "Can temperature or humidity
    # affect the CO2 sensor?" was refused as "that question reaches 296 sensors" because "the CO2
    # sensor" read as a named instrument, when English uses the definite article for the KIND
    # ("the CO2 sensor" = CO2 sensors in general). Over the 4,420 questions this project holds,
    # dropping the two words moves exactly that question and its sibling; the sentences that really
    # do name this building's kit carry another ground ("the outside air sensor fails" also says
    # "the control strategy", "a CO2 sensor in the lab" says "the lab").
    r"|\bthe\s+(?:[\w-]+\s+){0,3}(?:system|systems|plant|equipment|"
    r"unit|units|alarm|alarms|setpoints?|controls?|strategy|schedule)\b"
    # the asker's own estate
    r"|\b(?:my|our|we|we're|we've|us|mine)\b"
    # a measured-data word: the asker wants what THIS building recorded
    r"|\b(?:measured|observed|actual(?:ly)?|recorded|readings?|data|trend(?:s|ing)?|drift|"
    r"baseline|normali[sz]ed|per\s+(?:occupant|visitor|person|m2|square)|shutdown|deadline)\b"
    # a record kind, or "according to"
    r"|\b(?:register|records?|logs?|tickets?|work\s*orders?|bookings?|permits?|certificates?|"
    r"audits?|policy|policies|manual|documents?|according\s+to)\b"
    # a PROCEDURE of this building ("how do I report a faulty sensor?") is answered from its own
    # documents, never from a textbook
    r"|\b(?:report|book|reserve|contact|request|submit|apply|complain|access\s+card|"
    r"who\s+(?:do|should)\s+i|phone|email|call)\b"
    # a sensor id
    r"|\b\w+_sensor_[\d.]+\b|\buuid\b",
    re.IGNORECASE,
)


_TECHNIQUE_RE = re.compile(
    r"^\s*(?:(?:and|so|ok|okay|also|but|please)\b[,\s]*)*(?:can|could|does|do|will|would|is|are)\s+"
    r"(?:predictive\s+(?:analytics|maintenance|modell?ing)|(?:machine|deep)\s+learning|"
    r"(?:artificial\s+intelligence|ai)|forecasting|analytics|digital\s+twins?|iot|smart\s+meters?|"
    r"(?:building\s+)?automation|benchmarking|data\s+analytics)\s+"
    r"(?:\w+\s+){0,2}(?:help|improve|reduce|save|cut|work|differ|predict|detect|lower|enable|support|"
    r"benefit|useful|worth)\b",
    re.IGNORECASE,
)

_RULE_OF_THUMB_RE = re.compile(
    r"\bhow\s+(?:many|much|long|often|big|large)\s+(?:\w+\s+){0,2}(?:is|are)\s+"
    r"(?:enough|ideal|optimal|optimum|best|too\s+(?:many|much|few|little|long)|a\s+good\s+number|"
    r"typical|normal|reasonable|recommended)\b",
    re.IGNORECASE,
)


def has_grounding(question: str) -> bool:
    """True when the question names a place, a time, a record or "this building"."""
    return bool(_GROUNDING.search(question or ""))


def names_building_domain(question: str) -> bool:
    """True when the question uses building-science or building-operations vocabulary."""
    return bool(_DOMAIN.search(question or ""))


def is_general_guidance_question(question: str) -> bool:
    """True for a building-knowledge question that needs no data from THIS building."""
    q = (question or "").strip()
    if not q:
        return False
    if _GROUNDING.search(q):
        return False
    if _FRAMES.search(q) and _DOMAIN.search(q):
        return True
    # A question about a TECHNIQUE or a rule of thumb needs no building vocabulary to be general:
    # "can predictive analytics help reduce future resource consumption?" was declined to the
    # facilities team, and "how many people is enough for a meeting?" was answered from sensors
    # (66 s). Neither is about this building.
    return bool(_TECHNIQUE_RE.search(q) or _RULE_OF_THUMB_RE.search(q))


def guidance_frame(question: str) -> Optional[str]:
    """The text the guidance frame matched, for logs and tests; None when there is none."""
    m = _FRAMES.search(question or "")
    return m.group(0).strip() if m else None
