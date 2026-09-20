# -*- coding: utf-8 -*-
"""Small, pure helpers the aggregate lane leans on (row 2D-10, wave 2).

Kept apart from `aggregate_lane` so each can be tested without a store: which unit a sensor really
reports, whether a set of sensors is a headcount, and which floors an answer left out.

WHY THE UNIT NEEDS ITS OWN RULE
-------------------------------
The pipeline builds a sensor's unit from the class the SPARQL row carried, and a floor-scoped row
carries no class, only the sensor's IRI. So a sensor called "Floor3 water_flow_rate [L/s]" arrived
with NO unit, and, when the class was known, with the unit of the class's modality entry: "L", a
volume, for a series that is a flow RATE. A lane that trusts the metadata then either never
recognises the series as a flow (the wave-1 live run: the question fell through to the analytics
lane, which multiplied a mean by 86,400 seconds and said nothing about it) or converts it as though
it were litres. The sensor's own label is the more specific statement, so a unit written in square
brackets at the end of the label, when it is one the unit contract knows, outranks a class-level
guess of a different kind. Two DIFFERENT units of the SAME kind (L/min against L/s) are a genuine
conflict and are reported, not resolved: nothing here can tell which is right.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_BRACKET_UNIT = re.compile(r"\[([^\[\]]{1,16})\]\s*$")
_STATUS_WORDS = re.compile(
    r"(?<![a-z])(?:status|state|flag|detected|presence)(?![a-z])", re.IGNORECASE
)


def unit_from_label(label: str) -> str:
    """The unit a label declares in trailing square brackets, only if the unit contract knows it."""
    from orchestrator.services.units import _KIND, normalise

    m = _BRACKET_UNIT.search(label or "")
    if not m:
        return ""
    unit = normalise(m.group(1).strip())
    return unit if unit in _KIND else ""


def resolve_unit(meta_unit: str, label: str) -> Tuple[str, str]:
    """(unit to use, the label's unit when it CONFLICTS with the recorded one, else "").

    A label unit of a different kind than the recorded unit wins (the recorded one is a class-level
    guess); the same kind with a different symbol is a conflict and the recorded unit is kept.
    """
    from orchestrator.services.units import _KIND, normalise

    recorded = normalise(meta_unit)
    declared = unit_from_label(label)
    if declared and recorded and declared != recorded:
        if _KIND.get(declared) == _KIND.get(recorded):
            return recorded, declared
        return declared, ""
    return declared or recorded, ""


def counts_people(label: str, kind: str = "") -> bool:
    """Does THIS series count people, rather than report whether a space is occupied?

    A 0/1 occupancy status and a percentage of capacity both answer "is anyone there" and neither
    is a headcount; summing them gives a number that looks like one. Judged per series, because
    the store holds both: 256 counting series and 243 status series share one table, and a
    question about people binds a mixture of the two.
    """
    return not _STATUS_WORDS.search(str(label or "")) and kind != "ratio"


def is_headcount(measurand: Optional[str], labels: Iterable[str], kinds: Iterable[str]) -> bool:
    """True when the bound sensors include series that count people.

    ANY, NOT ALL (the defect this wording fixes). This asked whether NO label anywhere carried a
    status word, so a single status series among two hundred counters made the whole question
    "not a headcount": the live per-floor question fell through to a lane that summed room
    readings and reported 114 people on one floor while the floor counter read 29. The caller
    narrows the set to the counting series with `counts_people`; here the question is only
    whether any exist.
    """
    if measurand != "occupancy":
        return False
    seen = {k for k in kinds if k}
    if seen and seen <= {"ratio"}:
        return False  # every series is a percentage of capacity: not people
    return any(counts_people(label) for label in labels)


#: A period a question names. "Which floor has the most people?" names none, and for a headcount
#: that means now — a floor's headcount over an unstated period is not a quantity anyone means.
_NAMES_PERIOD = re.compile(
    r"\b(?:this|last|past|previous|next)\s+\w+|\byesterday\b|\btoday\b|\bover the\b|\bsince\b|"
    r"\bbetween\b|\btrend\b|\bhistor\w*\b|\bevery (?:day|week|hour)\b|\bweekend\b|\bovernight\b",
    re.IGNORECASE,
)


def names_a_period(question: str) -> bool:
    """Does the question name a period other than the present moment?"""
    return bool(_NAMES_PERIOD.search(question or ""))


#: A SPECIFIC place the question names. The noun must follow a spatial preposition, so "which
#: zones show elevated CO2" (a grouping) is not read as naming one, while "in the atrium" is.
_NAMED_PLACE = re.compile(
    r"\b(?:floor|level|storey)\s*\d+\b"
    r"|\b(?:room|zone|space)\s*\d+(?:\.\d+)?\b"
    r"|\b(?:in|at|on|inside|within|near|outside)\s+(?:the\s+|my\s+|a\s+)?"
    r"(?:atrium|lobby|foyer|reception|corridor|kitchen|toilet|washroom|canteen|cafe|"
    r"library|auditorium|theatre|gym|plant\s*room|server\s*room|lift|stairwell|"
    r"room|zone|floor|level|storey|lab|laboratory|office|studio|workshop)\b"
    # A specific place named with a bare article and no preposition ("when is the atrium busiest").
    # Only nouns that are unmistakably ONE place: "the room" is not here, because it is as likely
    # to mean "each room" as one.
    r"|\b(?:the|my|our)\s+(?:atrium|lobby|foyer|reception|canteen|cafe|library|auditorium|"
    r"theatre|gym|plant\s*room|server\s*room|stairwell)\b"
    # A DEICTIC place: "this room's usual pre-class levels", "the same across the space". The
    # speaker means one particular space the question cannot name, and a building-wide summary
    # answers another. "the room" alone is left out (it can mean "each room"); "this", "that",
    # "my", "our" cannot.
    r"|\b(?:this|that)\s+(?:room|space|zone|area|office|classroom|class|"
    r"lab|laboratory|studio|desk)(?:'s|’s)?\b"
    r"|\bthe\s+space\b|\bacross\s+the\s+(?:room|space)\b",
    re.IGNORECASE,
)

#: A request for the readings THEMSELVES, sensor by sensor. This is the one shape the breadth
#: refusal is still right for: no summary answers "show me every sensor's readings".
_PER_SENSOR = re.compile(
    r"\b(?:every|each|all)\s+(?:the\s+)?(?:sensor|reading|value|measurement|point|series|device)s?\b"
    r"|\b(?:sensor|reading|value|measurement)s?\s+(?:for|from)\s+(?:every|each|all)\b"
    r"|\blist\s+(?:all|every|the)\b|\bper[- ]sensor\b|\bsensor[- ]by[- ]sensor\b"
    r"|\braw\s+(?:data|readings|values)\b|\bdump\b|\bexport\s+(?:all|every)\b",
    re.IGNORECASE,
)

#: A question about what the building PROVIDES, or about how a technique works in general.
#: Neither is answered by this building's readings, and both were answered with a breadth refusal
#: in the fresh read. They belong to the capability, register and knowledge lanes, so this lane
#: must decline to claim them rather than answer them badly.
#:
#: Deliberately narrow. "How does the building prevent overheating in sun-exposed areas?" is NOT
#: in it: it asks about this building, and what its temperatures actually do is a real part of the
#: answer. The generic-method pattern therefore requires an indefinite subject ("a system", "a
#: sensor", "an algorithm"), never "the building".
_NOT_READINGS = re.compile(
    r"\bhow\s+(?:can|do|does|would|should)\s+(?:a|an|any|one)\s+"
    r"(?:system|sensor|device|algorithm|model|meter|detector|computer|program)\b"
    r"|\bhow\s+(?:do|does)\s+(?:sensors|systems|algorithms|detectors)\s+work\b"
    r"|\bwhat\s+(?:official\s+)?(?:support|help|assistance|provision|facilities|amenities)\b"
    r"|\b(?:is|are)\s+(?:there\s+)?(?:any\s+)?\w*\s*(?:available|provided|offered)\b"
    r"|\b(?:medication|medicine|first[- ]aid|well-?being|wellbeing|prayer|nursing|"
    r"breastfeeding|quiet\s+room)\b"
    r"|\b(?:policy|policies|procedure|guidance|regulation|entitled|allowed|permitted)\b"
    # Where can I WAIT / WORK / RELAX: a question about which spaces exist and suit, which the
    # workspace register answers. Live readings may inform it; they are not the answer.
    r"|\bwhere\s+(?:can|could|should|do|would)\s+(?:i|we|you)\s+(?:go\s+to\s+)?"
    r"(?:wait|work|study|sit|relax|rest|meet|eat|park|charge|pray|nap|hang\s+out|find)\b"
    r"|\b(?:appointment|nearby|near\s+me|close\s+to\s+me)\b"
    # CAPACITY is a property of a space, not a reading: how many people it can HOLD.
    r"|\bhow\s+many\s+(?:people|persons|students|occupants|visitors|staff)\s+"
    r"(?:can|could|does|do|will|would)\b[^?]*\b(?:hold|fit|accommodate|seat|contain|take)\b"
    r"|\b(?:capacity|maximum\s+occupancy|max\s+occupancy|fire\s+(?:limit|capacity)|seating)\b"
    # HOW ONE QUANTITY AFFECTS ANOTHER, or what would happen IF: causal and hypothetical questions
    # ("can temperature or humidity affect the CO2 sensor?", "what happens if temperature
    # spikes?"). They are answered from knowledge of the physics, not from a building-wide table.
    r"|\b(?:can|could|does|do|will|would)\s+\w+(?:\s+or\s+\w+)?\s+(?:affect|influence|impact|"
    r"cause|change)\b"
    r"|\bwhat\s+(?:happens|would\s+happen|will\s+happen)\s+if\b"
    r"|\bhow\s+(?:can|could|would|does|do)\s+(?:\w+\s+){0,2}(?:sensors?|systems?|monitoring|"
    r"meters?)\s+(?:lead|help|improve|reduce|save|contribute|support)\b"
    # A REQUIREMENT or a design target ("what lux level is maintained for reading tasks"), which
    # the standards and documents answer; and a FORECAST, which nothing here predicts.
    r"|\b(?:maintained|required|recommended|specified|targeted)\s+(?:for|by|in)\b"
    r"|\b(?:tomorrow|forecast|predict\w*)\b|\bnext\s+(?:hour|day|week|month)\b"
    r"|\bwill\s+(?:have|be|reach|exceed)\s+the\s+(?:highest|lowest|most|least)\b"
    # An ANALYTICAL or register question about zones over a period, not a look at the readings.
    r"|\b(?:incident|defensible|setback|warm-?up|cool-?down|stabili[sz]\w*|recover\w*|"
    r"clock\s+drift)\b"
    r"|\bbalance\s+of\b|\bbest\s+supported\s+balance\b",
    re.IGNORECASE,
)

#: WHEN does a quantity do something: a time-of-day question, answered by the hourly profile. It
#: is neither a forecast (nothing here predicts) nor a "how is it now" summary.
_TIME_PATTERN = re.compile(
    r"\bbest\s+(?:remaining\s+)?(?:time|hour|period)\b|\bremaining\s+time\b"
    r"|\b(?:quietest|busiest|calmest|warmest|coolest)\s+(?:time|hour|period)\b"
    r"|\bwhen\b[^?]*\b(?:busiest|quietest|busy|crowded|emptiest|worsen|worse|peak|peaks|highest|"
    r"lowest|hottest|coldest|stuffiest|"
    r"noisiest|likely|get|gets|become|becomes|rise|rises|climb|climbs|drop|drops|start|starts|"
    r"begin|exceed|exceeds)\b"
    r"|\bwhat\s+time\b|\btime\s+of\s+day\b|\bwhich\s+hours?\b|\bat\s+what\s+(?:time|hour)s?\b"
    r"|\bduring\s+the\s+day\b|\bthroughout\s+the\s+day\b",
    re.IGNORECASE,
)


#: "MY office", "OUR class": the speaker's own space. It is not a place the lane can resolve, so it
#: cannot be answered locally, but it is not a reason to refuse either: the building's figures are
#: the nearest honest answer, provided the reply says they are the building's and not the office's.
_POSSESSIVE_PLACE = re.compile(
    r"\b(?:my|our)\s+(?:shared\s+)?(?:room|space|zone|area|office|classroom|class|lab|"
    r"laboratory|studio|desk|team|department)\b",
    re.IGNORECASE,
)

WHOLE_BUILDING_NOTE = (
    "These figures are for the whole building; I can't tell which of its spaces is yours, so name "
    "a room if you want its own readings."
)


def names_a_possessive_place(question: str) -> bool:
    """Does the question speak of the reader's own space ("my shared office")?"""
    return bool(_POSSESSIVE_PLACE.search(question or ""))


def names_a_place(question: str) -> bool:
    """Does the question name a SPECIFIC place, so a building-wide summary would answer another?"""
    return bool(_NAMED_PLACE.search(question or ""))


#: A question whose HEAD is "which <place or route>" ("which exit", "which student-accessible study
#: area", "which room"), or which asks about routes, exits and bookings. The quantity in such a
#: question is a CONSTRAINT ("after dark", "without worse CO2"), and a building-wide summary of it
#: answers a different question. "Which FLOOR" is deliberately absent: a floor ranking is what the
#: lane exists to answer.
_WHICH_PLACE = re.compile(
    r"\bwhich\s+(?:[\w'-]+\s+){0,3}?(?:exit|route|path|entrance|door|stairs|stairwell|"
    r"lift|study\s+area|area|room|space|desk|seat|spot|location|zone|"
    r"office|classroom|lab|building|place)\b"
    r"|\b(?:onward|evacuation|escape)\s+route\b|\b(?:book|booking|reserve|reservation)\w*\b",
    re.IGNORECASE,
)


def asks_which_place(question: str) -> bool:
    """Does the question ask WHICH place or route to use (the quantity is only a constraint)?"""
    return bool(_WHICH_PLACE.search(question or ""))


def asks_for_time_pattern(question: str) -> bool:
    """Does the question ask WHEN a quantity does something (a daily-pattern question)?"""
    return bool(_TIME_PATTERN.search(question or ""))


def asks_for_per_sensor_detail(question: str) -> bool:
    """Is this a request for the readings sensor by sensor, which no summary can stand in for?"""
    return bool(_PER_SENSOR.search(question or ""))


def is_readings_question(question: str) -> bool:
    """Would this building's own readings be part of an honest answer?

    False for a question about what the building PROVIDES (a well-being break, a visitor space)
    and for a question about how a technique works in general (telling background hum from a noise
    event). Both were answered with "that covers all N sensors at once" in the fresh read, and
    both belong to another lane: this one declines so they can reach it.
    """
    return not _NOT_READINGS.search(question or "")


def build_floors_query() -> str:
    """SPARQL: every floor the building declares, as its number where it has one."""
    return (
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "SELECT DISTINCT ?floorNum WHERE {\n"
        "  ?f a brick:Floor .\n"
        '  BIND(REPLACE(STR(?f), "^.*[Ff]loor", "") AS ?floorNum)\n'
        "} ORDER BY ?floorNum"
    )


def parse_floors(result: Dict[str, Any]) -> List[str]:
    """The NUMBERED floors from a floors query. A rooftop or a car-park level has no number and
    is not a floor whose absence from a ranking needs explaining."""
    out: List[str] = []
    for b in ((result or {}).get("results") or {}).get("bindings") or []:
        value = str((b.get("floorNum") or {}).get("value") or "")
        if re.fullmatch(r"-?\d+", value) and value not in out:
            out.append(value)
    return sorted(out, key=lambda v: (int(v), v))


def missing_floors_note(all_floors: Sequence[str], present: Iterable[str], noun: str) -> str:
    """One sentence naming the floors that have no figure, or "" when every floor has one."""
    have = set(present)
    missing = [f for f in all_floors if f not in have]
    if not missing:
        return ""
    names = [f"Floor {f}" for f in missing]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
    return f"No figure for {joined}: none of the {noun} sensors matched there returned a reading."
