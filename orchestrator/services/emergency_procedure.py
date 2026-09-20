# -*- coding: utf-8 -*-
"""What a person should DO when something dangerous happens is a procedure, never an asset list.

The failure this prevents (live hand read, 2026-09-19, safety-relevant). *"What should I do if the
fire alarm goes off?"* was answered:

    **1 of the 30 records in the Fire safety asset register matches** (fire asset kind: alarm):
    **FSA-001** — Fire alarm control panel

The building holds the answer and gives it perfectly to "What is the evacuation procedure?" — leave
by the nearest marked fire exit, do not use the lifts, assemble on the road outside, report to the
floor warden. A person hearing an alarm was instead given the panel's inventory number.

The register is not at fault: the question says "fire alarm", the register holds fire alarms, and
its vocabulary matched. What the register cannot know is that the question asks for an ACTION, and
an asset record has no actions in it. That is decided here, by shape:

* an ACTION frame about the asker — "what should I do", "what do I do", "where do I go", "who do I
  call", "how do I get out" — pointed at
* an EMERGENCY — fire, alarm, evacuation, smoke, flood, injury, lockdown, a trapped lift.

Both halves are required, so "which fire doors are defective?" keeps the register and "what should I
do about my booking?" is no emergency. Deliberately broad on the emergency side and narrow on the
frame: routing a safety question to prose the building authored costs an inventory answer nobody
wanted, while the reverse costs someone the procedure while an alarm is sounding.

Pure and building-agnostic: English only, no register, room or building names.
"""

from __future__ import annotations

import re

#: The asker wants to know what to DO, where to GO, or whom to TELL.
_ACTION_FRAME = (
    r"\bwhat\s+(?:should|do|must|ought|can|would)\s+(?:i|we|you|people|staff|occupants|visitors)\b"
    r"|\bwhat(?:'s| is)\s+the\s+(?:procedure|protocol|drill|process|routine|plan|guidance|"
    r"instruction)s?\b"
    r"|\bwhat\s+happens\s+(?:if|when)\b"
    r"|\bwhere\s+(?:do|should|must)\s+(?:i|we|people|staff|everyone)\s+go\b"
    r"|\bwho\s+(?:do|should|must)\s+(?:i|we)\s+(?:call|tell|contact|report\s+to|inform)\b"
    r"|\bhow\s+(?:do|should|can)\s+(?:i|we)\s+(?:get\s+out|evacuate|escape|leave|exit|raise)\b"
    r"|\bwhat\s+(?:are|is)\s+the\s+(?:steps|actions)\b"
    r"|\bwhat\s+to\s+do\b"
)

#: The dangerous thing. A lift someone is stuck in belongs here; a lift that is merely out of
#: service does not, which is why "trapped" and "stuck" must accompany it.
_EMERGENCY = (
    r"\bfire\b|\bfire\s+alarm\b|\balarm\s+(?:goes?\s+off|sounds?|is\s+sounding|activat\w+)\b"
    r"|\bthe\s+alarm\b|\bevacuat\w+\b|\bsmoke\b|\bflood(?:ing|s)?\b|\bgas\s+leak\b|\bexplosion\b"
    r"|\bfire\s+drill\b|\blockdown\b|\bintruder\b|\bbomb\s+threat\b|\bterror\w*\b"
    r"|\bmedical\s+emergency\b|\binjur(?:y|ed|ies)\b|\bfirst\s+aid\b|\bunconscious\b|\bcollapsed?\b"
    r"|\bemergency\b|\bpower\s+(?:cut|failure|outage)\b|\bchemical\s+spill\b|\bspillage\b"
    r"|\b(?:trapped|stuck)\s+(?:in|inside)\s+(?:the\s+)?(?:lift|elevator|room|building)\b"
    r"|\bcarbon\s+monoxide\s+alarm\b|\bsevere\s+weather\b"
)

EMERGENCY_ACTION_RE = re.compile(
    rf"(?:{_ACTION_FRAME})[^?.!]{{0,60}}(?:{_EMERGENCY})"
    rf"|(?:{_EMERGENCY})[^?.!]{{0,60}}(?:{_ACTION_FRAME})",
    re.IGNORECASE,
)

#: A question about the KIT, its condition or its records. These keep the register, which is the
#: only place that knows them.
_ABOUT_THE_EQUIPMENT_RE = re.compile(
    r"\b(?:defective|faulty|broken|overdue|due|tested|test(?:ing)?\s+date|serviced|inspected|"
    r"how\s+many|where\s+(?:is|are)\s+the|which\s+\w*\s*(?:assets?|panels?|extinguishers?|doors?|"
    r"alarms?|detectors?)\b|register|record|inventory|asset\s+id|last\s+checked|expiry|expires)\b",
    re.IGNORECASE,
)


def is_emergency_action_question(question: str) -> bool:
    """True when the asker wants to know what to DO in an emergency."""
    q = question or ""
    if not q.strip() or not EMERGENCY_ACTION_RE.search(q):
        return False
    # "Which fire doors are overdue a test?" is about the equipment, and the register answers it.
    return not _ABOUT_THE_EQUIPMENT_RE.search(q)
