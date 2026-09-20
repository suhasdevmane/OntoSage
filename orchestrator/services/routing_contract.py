"""Question-shape → intent routing contract (TODO-050).

One ordered, declarative, TESTED home for every deterministic intent override that
corrects the LLM classifier. Before this module the rules lived as ~12 ad-hoc inline
blocks accreted one bug-fix at a time across ``dialogue_agent._parse_llm_response``
and ``dialogue_agent.detect_intent`` — each new override risked silently breaking an
old one, and nothing documented their precedence.

THE CONTRACT
────────────
Each rule maps a *question shape* (lexical/structural signals in the user's phrasing)
to the intent that the pipeline can actually ground. Rules are:

* **building-agnostic** — they key on phrasing shape only (count words, comparison
  words, modal-automation phrasing…). No building names, namespaces, zone ids, or
  sensor names may ever appear here; the same contract must route every building
  unchanged (a test scans this module's source to enforce it).
* **ordered** — earlier rules win; each rule sees the intent as (possibly) rewritten
  by the rules above it. The order below is load-bearing and mirrors the historical
  override sequence, so behaviour is preserved exactly.
* **conservative** — a rule only overrides FROM the intents it names. A confident,
  correct LLM classification outside that set is never stomped.

Two stages, matching where the historical overrides ran:

* ``stage="parse"``  — inside ``_parse_llm_response``, BEFORE the G1 taxonomy is
  derived (so the taxonomy sees the corrected intent).
* ``stage="post"``   — in ``detect_intent`` after parsing (including the JSON-parse
  fallback path), where the data-query promotion has always run.

Every applied rule is logged and recorded in ``normalized["routing_rules_applied"]``
for the audit trail and for tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Question-shape keyword sets (building-agnostic by construction)
# ═══════════════════════════════════════════════════════════════════════════════

COMPARE_KWS = (
    "compare ",
    "comparison",
    " vs ",
    " vs.",
    " versus ",
    "difference between",
    "higher than",
    "lower than",
    "more than",
    "less than",
)

TREND_KWS = (
    "trend",
    "over the last",
    "past week",
    "last 7 days",
    "weekly",
    "over time",
    "history",
    "historical",
    "last week",
    "past 7 days",
    "daily trend",
)

VAGUE_COMPLAINT_KWS = (
    "fix everything",
    "things seem off",
    "something seems off",
    "something is wrong",
    "all broken",
    "fix it all",
    "sort everything out",
    "not working today",
)

SPECIFIC_CONTROL_KWS = (
    "hvac",
    "thermostat",
    "turn off",
    "turn on",
    "set temperature",
    "set hvac",
    "lights",
    "ventilation rate",
    "override",
    "setpoint",
)

CORRELATION_KWS = (
    "correlat",
    "correlation between",
    "relationship between",
    "relationship of",
    "pattern between",
    "link between",
)

FLOOR_PLAN_KWS = (
    "show me floor",
    "floor plan",
    "floor layout",
    "floor map",
    "building map",
    "building layout",
    "building overview",
    "all floors",
    "where is room",
    "where is zone",
    "locate room",
    "find room",
    "navigate to room",
    "directions to room",
    "how do i get to",
)

# BUG-045: a COUNT of sensors/devices/equipment is metadata (a SPARQL COUNT on the
# graph), never spatial_query (which reads DWG room geometry).
COUNT_TRIGGER_KWS = (
    "how many",
    "how much",
    "number of",
    "count of",
    "count the",
    "total number",
)

COUNTABLE_DEVICE_KWS = (
    "sensor",
    "sensors",
    "device",
    "devices",
    "equipment",
    "meter",
    "meters",
    "actuator",
    "actuators",
)

# Room/space geometry words that KEEP a count on spatial_query — areas and
# adjacency of rooms live in the DWG floor-plan manifests, not the RDF graph.
ROOM_GEOMETRY_KWS = (
    "room",
    "rooms",
    "space",
    "spaces",
    "adjacent",
    "adjacency",
    "area",
    "how big",
    "square met",
    "square feet",
    "dimensions",
)

# Building-STRUCTURE counts answered by a SPARQL COUNT on TBOX types (brick:Floor,
# brick:Storey, brick:HVAC_Zone) — never a floor-plan geometry read.
STRUCTURE_COUNT_KWS = (
    "floor",
    "floors",
    "storey",
    "storeys",
    "story",
    "stories",
    "zone",
    "zones",
    "level",
    "levels",
)

# Whole-building identity questions (name / description) → metadata (brick:Building label).
BUILDING_INFO_KWS = (
    "what building",
    "which building",
    "building name",
    "name of the building",
    "name of this building",
    "about this building",
    "about the building",
    "tell me about this building",
    "what is this building",
)

FORECAST_KWS = (
    "predict",
    "forecast",
    "projected",
    "projection",
    "what will",
    "what would",
    "expected to be",
    "likely to be",
)

SENSOR_METRIC_KWS = (
    "temperature",
    "temp",
    "co2",
    "humidity",
    "energy",
    "consumption",
    "power",
    "air quality",
    "occupancy",
    "noise",
    "pressure",
    "sensor",
    "reading",
)

# An explicit ASK for a document about the data: "give me a report on ...",
# "monthly summary", "breakdown of ...". Deliberately requires the noun —
# "report the average temperature" is a data question wearing the verb, and
# belongs in the reading lane, not here.
REPORT_REQUEST_RE = re.compile(
    r"\b(?:give|show|send|generate|create|produce|prepare|make|provide|need|want)\b"
    r"[^?]*?\b(?:report|summary|breakdown)\b"
    r"|\b(?:report|summary|breakdown)\s+(?:on|of|for|about)\b"
    r"|\b(?:monthly|weekly|daily|annual|quarterly)\s+(?:report|summary|breakdown)\b",
    re.IGNORECASE,
)


EXTERNAL_ACTION_KWS = (
    "email it",
    "email this",
    "email the report",
    "email the",
    "send it to",
    "send this to",
    "forward it",
    "forward this",
    "send the report to",
    "activate the",
    "deactivate the",
)

MAINTENANCE_SCHEDULE_KWS = (
    "maintenance schedule",
    "scheduled maintenance",
    "planned maintenance",
    "maintenance this week",
    "maintenance this month",
    "maintenance next",
    "open maintenance tickets",
    "outstanding maintenance",
    "maintenance tasks",
    "maintenance work scheduled",
    "what maintenance is",
    "what maintenance work",
    "list maintenance",
    "show maintenance",
)

COMFORT_SIGNAL_KWS = (
    "temperature",
    "warm",
    "cold",
    "hot",
    "humid",
    "co2",
    "air quality",
    "stuffy",
    "comfortable",
    "comfort",
    "sensor",
    "zone",
    "reading",
    "level",
)

# ── Automation / standing-notification shapes (L6 corpus gap, 2026-07-30) ──────
# "notify me when a desk becomes available" / "alert me if CO2 goes high" are
# STANDING requests → the alert intent (which creates/lists personal alerts).
STANDING_ALERT_RE = re.compile(
    r"\b(alert me|notify me|warn me|let me know|tell me)\b.{0,60}\b(if|when|whenever|once)\b",
    re.IGNORECASE,
)
# "can/could/does the system|building|it automatically … (if|when …)" is a question
# about whether the building CAN self-act → automation_capability, answered honestly
# from the building's own configuration (rules engine, actuation driver).
AUTOMATION_Q_RE = re.compile(
    r"\b(can|could|does|do|will|would|is it possible)\b.{0,50}"
    r"\b(system|building|it|ontosage)\b.{0,90}"
    r"\b(automatic|automatically|auto[- ]|on its own|by itself|self[- ]|"
    r"notify|alert|adjust|respond|react|make sure|ensure|optimi[sz]e)\b",
    re.IGNORECASE,
)

_SENSOR_ID_RE = re.compile(r"[A-Za-z0-9]+_[Ss]ensor_[\d.]+")
_TWO_FLOORS_RE = re.compile(r"\bfloor\s*\d+")


# ═══════════════════════════════════════════════════════════════════════════════
# Rule machinery
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _Ctx:
    """Everything a rule may inspect. ``sr`` is the SemanticRouter class."""

    query: str
    ql: str  # lowercased query
    normalized: Dict[str, Any]
    sr: Any

    def __post_init__(self) -> None:
        """A rule may always call ``c.sr``.

        Three separate rules shipped with an unguarded ``c.sr.is_control_command(...)`` and each
        one crashed the moment a caller built a context without the router — always a test, never
        production, but a rule that raises is a rule that stops routing. The field means "the
        SemanticRouter", so an absent one is filled in here rather than defended against in every
        rule that will ever be written.
        """
        if self.sr is None:
            from orchestrator.services.semantic_router import SemanticRouter

            self.sr = SemanticRouter

    @property
    def intent(self) -> Optional[str]:
        return self.normalized.get("intent")


# A rule returns the new intent (str) to apply, or None to pass.
# ``extras`` lets a rule set additional normalized fields (e.g. clarification text).
@dataclass
class Rule:
    name: str
    shape: str  # human description of the question shape → intent mapping
    fn: Callable[[_Ctx], Optional[str]]
    sets_analytics: bool = False
    # Historical data-query promotion never touched the analytics flag — rules that
    # must preserve it verbatim set this True.
    preserve_analytics: bool = False
    extras: Optional[Callable[[_Ctx], Dict[str, Any]]] = None


def _any(ql: str, kws: Tuple[str, ...]) -> bool:
    return any(kw in ql for kw in kws)


# ═══════════════════════════════════════════════════════════════════════════════
# The rules — order is the precedence contract
# ═══════════════════════════════════════════════════════════════════════════════


def _r_compare(c: _Ctx) -> Optional[str]:
    if not _any(c.ql, COMPARE_KWS):
        return None
    if c.intent not in ("compliance", "analytics", "trend"):
        return None
    two_entities = len(c.normalized.get("entities", [])) >= 2
    two_floors = len(set(_TWO_FLOORS_RE.findall(c.ql))) >= 2
    return "compare" if (two_entities or two_floors) else None


def _r_sensor_trend(c: _Ctx) -> Optional[str]:
    if c.intent != "compliance":
        return None
    if _SENSOR_ID_RE.search(c.query) and _any(c.ql, TREND_KWS):
        return "analytics"
    return None


def _r_vague_complaint(c: _Ctx) -> Optional[str]:
    if c.intent not in ("control", "clarification"):
        return None
    if _any(c.ql, VAGUE_COMPLAINT_KWS) and not _any(c.ql, SPECIFIC_CONTROL_KWS):
        return "clarification"
    return None


def _vague_complaint_extras(c: _Ctx) -> Dict[str, Any]:
    return {
        "clarification_question": (
            "Could you be more specific? Which area or system seems to have an issue? "
            "I can check sensor readings, anomalies, or HVAC status for specific zones."
        )
    }


#: Asking for a DAY to be arranged — an order of activities, not a fact about the building.
_PLAN_MY_TIME_RE = re.compile(
    r"\bplan\s+(?:me\s+)?(?:a|an|my|the|out)\b"
    r"|\bplan\s+(?:a\s+)?(?:practical\s+)?(?:sequence|order|route|day|visit|itinerary)\b"
    r"|\b(?:work\s+out|map\s+out|lay\s+out|sort\s+out|organise|organize|schedule)\s+"
    r"(?:me\s+)?(?:a|an|my|the)\b.{0,30}\b(?:day|visit|sequence|order|itinerary|time)\b"
    r"|\bitinerary\b",
    re.IGNORECASE,
)

#: The asker's OWN commitments, which no record in the building ties to a person. A
#: timetable says a session happens in a room at a time; it does not say whose it is.
_MY_OWN_COMMITMENTS_RE = re.compile(
    r"\bmy\s+(?:own\s+)?(?:class|classes|lecture|lectures|seminar|seminars|session|sessions|"
    r"tutorial|tutorials|lab|labs|teaching|timetable|schedule|diary|calendar|meetings?|"
    r"appointments?|bookings?|commitments?|deadlines?)\b",
    re.IGNORECASE,
)


def _r_plan_around_my_own_commitments(c: _Ctx) -> Optional[str]:
    """ "Plan my day around my classes" → ask which sessions are yours.

    Run-3 row 90 (2026-09-17) answered this with a four-line plan naming specific rooms
    and specific timetabled sessions — "Study in Room 4.55 before 15:00 (TS-0670 Advanced
    Computer Science 15:00-17:00)" — as though it knew which of them the asker had to be
    at. It cannot: a timetable records that a session happens in a room at a time, and
    nothing in it ties a session to a person. Every room and every time in that answer was
    real, which is what makes it dangerous — a reader has no way to see that the one fact
    holding the plan together was invented.

    Asking costs one turn and the asker already knows the answer. Deliberately narrow:
    both halves must be present, so "what conservative travel buffer should I allow
    between appointments on different floors?" — which needs no knowledge of whose
    appointments they are — keeps the lane that can give it a figure.
    """
    if c.intent in ("maintenance", "complaint", "report", "safety_report", "suggestion"):
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    q = c.query or ""
    if _PLAN_MY_TIME_RE.search(q) and _MY_OWN_COMMITMENTS_RE.search(q):
        return "clarification"
    return None


def _plan_around_my_own_commitments_extras(c: _Ctx) -> Dict[str, Any]:
    return {
        "clarification_question": (
            "Which of the building's sessions are yours? I can build a sequence around "
            "fixed times, but the timetable records that a session happens in a room at a "
            "time, not whose it is — so a plan built around somebody else's class would "
            "look right and put you in the wrong place. Give me the times you have to be "
            "somewhere, with the rooms if you know them, and I will fit the rest of what "
            "you asked for around them."
        )
    }


def _r_correlation(c: _Ctx) -> Optional[str]:
    if c.intent == "clarification" and _any(c.ql, CORRELATION_KWS):
        return "analytics"
    return None


def _r_floor_plan(c: _Ctx) -> Optional[str]:
    if c.intent in ("floor_plan", "spatial_query"):
        return None
    return "floor_plan" if _any(c.ql, FLOOR_PLAN_KWS) else None


#: "How much <mass noun>" asks for a QUANTITY and can never be a census of devices.
#: "How much electricity does the lab on floor 5 use?" contains "how much" and "floor",
#: which was enough to make the guard call it a device count (BUG-266). The rule lived in
#: consumption_question as a pre-emptive workaround; it belongs here, because one decision
#: with two owners is the drift this contract exists to prevent.
_QUANTITY_NOT_CENSUS_RE = re.compile(
    r"\bhow much\b.{0,20}\b(?:energy|electricity|power|water|gas|kwh|fuel|heat)\b",
    re.IGNORECASE,
)


def _is_countable_meta(ql: str) -> bool:
    """Device/structure COUNT or building-identity question shape (BUG-045)."""
    count_q = _any(ql, COUNT_TRIGGER_KWS)
    devices = _any(ql, COUNTABLE_DEVICE_KWS)
    structure = _any(ql, STRUCTURE_COUNT_KWS)
    geometry = _any(ql, ROOM_GEOMETRY_KWS)
    info = _any(ql, BUILDING_INFO_KWS)
    # A quantity of a metered resource is not a census -- unless the question also
    # names a countable device ("how much energy do the meters use?"), where the
    # counting behaviour this guard owns still applies.
    if not devices and _QUANTITY_NOT_CENSUS_RE.search(ql):
        return bool(info)
    return (count_q and (devices or structure) and not geometry) or info


def _r_countable_metadata(c: _Ctx) -> Optional[str]:
    if c.intent not in (
        "spatial_query",
        "floor_plan",
        "sensor_data",
        "general",
        "general_knowledge",
        "capability",
    ):
        return None
    return "metadata" if _is_countable_meta(c.ql) else None


def _r_room_count_is_spatial(c: _Ctx) -> Optional[str]:
    """ "How many rooms are on floor 2?" → spatial_query (BUG-628).

    `countable_metadata` correctly DECLINES this one — a room count is geometry, not a
    SPARQL census — but declining only leaves the classifier's own answer in place, and it
    called this `sensor_data`. The building then said it "doesn't keep a record of how many
    rooms are on a specific floor", seconds after another answer reported floor 4's 57 rooms
    from the same manifests. Declining to force the wrong lane is not the same as naming the
    right one.

    A device count stays where it was ("how many sensors on floor 2" is a graph census); this
    claims only counts whose subject is a room or a space.
    """
    if c.intent not in ("sensor_data", "general", "metadata", "discovery", "capability"):
        return None
    if not _any(c.ql, COUNT_TRIGGER_KWS):
        return None
    if _any(c.ql, COUNTABLE_DEVICE_KWS):
        return None
    return "spatial_query" if _any(c.ql, ROOM_GEOMETRY_KWS) else None


#: The predicate that makes a question a CENSUS: it asks what exists, or asks to be
#: shown it. Generic English; no building's vocabulary and no Brick class list.
_INVENTORY_EXISTENTIAL_RE = re.compile(
    r"\b(?:are|is)\s+there\b"
    r"|\bdo(?:es)?\s+(?:\w+\s+){0,3}?have\b"
    r"|\bhave\s+(?:we|you)\b"
    r"|\b(?:are|is)\s+(?:there\s+)?(?:any\s+)?"
    r"(?:installed|available|present|fitted|deployed|in\s+use|in\s+place|connected)\b"
    r"|\b(?:are|is)\s+(?:in|inside|on|at)\s+(?:the|this)\b"
    r"|\b(?:what|which)\s+(?:kinds?|types?|sorts?)\s+of\b"
    r"|\b(?:list|show|tell\s+me\s+about|give\s+me\s+a\s+list)\b"
    r"|\b(?:exist|exists)\b",
    re.IGNORECASE,
)


def _r_inventory_to_discovery(c: _Ctx) -> Optional[str]:
    """ "What/which X does this building have?" → discovery (BUG-122).

    Runs AFTER countable_metadata, so a COUNT question keeps its existing route;
    this claims only the open "what kinds of X are here" shape. Without it the
    same question reached three different handlers depending on phrasing — the
    capability agent, the sensor-map lister, and the SPARQL agent — each grouping
    the answer its own way, so "what equipment is here?" and "what sensors are
    here?" disagreed about what the building contains.
    """
    if c.intent not in ("sensor_data", "capability", "metadata", "general", "general_knowledge"):
        return None
    # Any COUNT question keeps its existing route. _is_countable_meta alone is not
    # enough of a guard: its device list covers sensors and meters but not plant,
    # so "how many air handling units are there?" slipped past it and lost the
    # metadata answer (16) that already worked.
    if _any(c.ql, COUNT_TRIGGER_KWS) or _is_countable_meta(c.ql):
        return None
    from orchestrator.services.ontology_inventory import is_inventory_question

    if not is_inventory_question(c.query):
        return None
    # A CENSUS ANSWERS "WHAT IS HERE", NOTHING ELSE (C19).
    #
    # The inventory test pairs an interrogative anywhere in the sentence with an
    # inventory noun anywhere else, so two questions that are not about what the
    # building contains were answered with a list of its sensor classes:
    #
    #   "Which approved plant, sensor … endpoints have LOST expected connectivity,
    #    and is the fault local, segment-wide or upstream?"
    #   "For each local, shared or inherited control, WHO OPERATES, monitors and
    #    evidences each component, and what must be tested within this UNIT?"
    #
    # Both name inventory nouns; neither asks which of them exist. The first asks
    # which are in a fault state, the second who is accountable for them — and a
    # census of 3,248 sensors is the wrong answer to each in the same way.
    #
    # The discriminator is the PREDICATE, not more nouns: a census question puts an
    # existential verb on the things ("are there", "do we have", "is installed",
    # "are available"), or simply asks to be shown them. Requiring that is a
    # positive test and does not need a list of every way a question can be about
    # something else, which is the list that never finishes.
    return "discovery" if _INVENTORY_EXISTENTIAL_RE.search(c.query) else None


def _r_forecast_skill(c: _Ctx) -> Optional[str]:
    """How ACCURATE the forecasts are -> observability, not another forecast.

    Runs BEFORE forecast_to_trend, which claims anything pairing a predict word with
    a sensor metric. "How good are your predictions for CO2?" pairs both, so it was
    routed to the trend pipeline and answered with a CO2 forecast -- the system
    demonstrating a prediction instead of reporting its track record (CAVEAT-324).

    The distinction is what the questioner wants back: a number, or the measured
    skill behind the numbers.
    """
    from orchestrator.services.forecast_skill import is_skill_question

    if c.intent in ("control", "privacy_refusal"):
        return None
    return "observability" if is_skill_question(c.query) else None


def _r_forecast(c: _Ctx) -> Optional[str]:
    if c.intent in ("trend", "analytics"):
        return None
    # A question about forecast ACCURACY is not a request for a forecast. This
    # contract applies every matching rule in order and the LAST one wins, so
    # forecast_skill_to_observability firing earlier is not enough on its own --
    # this rule ran afterwards and overwrote it, answering "how good are your
    # predictions for CO2?" with a CO2 forecast. The later rule guards itself, the
    # same way inventory_to_discovery yields to a COUNT question.
    from orchestrator.services.forecast_skill import is_skill_question

    if is_skill_question(c.query):
        return None
    # V5-T16: an EXPLICIT forecast verb ("forecast/predict humidity for the
    # next 6 hours") classified as sensor_data would answer with the CURRENT
    # reading — a wrong answer to a predictive question. Future-time phrasing
    # keeps it in the forecast pipeline; bare metric questions do not move.
    if c.intent == "sensor_data":
        explicit = re.search(
            r"\b(?:forecast|predict|projection|projected)\b|\bwhat will\b|\bwhat would\b",
            c.query,
            re.IGNORECASE,
        )
        future = re.search(
            r"\b(?:tomorrow|next (?:hour|week|month|day|\d+\s*(?:hours?|days?|weeks?))"
            r"|later today|this evening|in \d+\s*(?:hours?|days?))\b",
            c.query,
            re.IGNORECASE,
        )
        return "trend" if (explicit and future) else None
    if _any(c.ql, FORECAST_KWS) and _any(c.ql, SENSOR_METRIC_KWS):
        return "trend"
    return None


def _r_control(c: _Ctx) -> Optional[str]:
    if c.intent == "control":
        return None
    if c.sr.is_control_command(c.query) or _any(c.ql, EXTERNAL_ACTION_KWS):
        return "control"
    return None


def _r_maintenance_schedule(c: _Ctx) -> Optional[str]:
    if c.intent == "maintenance":
        return None
    return "maintenance" if _any(c.ql, MAINTENANCE_SCHEDULE_KWS) else None


def _r_report_intake(c: _Ctx) -> Optional[str]:
    # "report" is in this set on purpose (BUG-200). "The toilet on floor 1 is
    # leaking." is a FAULT STATEMENT, but the word "report" lives in the same
    # semantic neighbourhood as reporting a problem, so the classifier reaches
    # for the summary intent and returns an executive summary of the leak
    # instead of filing it. Nothing then records the fault.
    #
    # Widening the set is safe because the rescue is conditional on
    # report_intake_intent() ALSO firing, and that only recognises statement
    # shapes: "give me a report on energy use", "show me the monthly report"
    # and "report on CO2 last week" all return None and keep the summary lane.
    if c.intent not in (
        "capability",
        "general",
        "greeting",
        "metadata",
        "clarification",
        "discovery",
        "report",
        None,
    ):
        return None
    return c.sr.report_intake_intent(c.query)


# "when was chiller 7 last serviced?" asks about the PAST. It states no problem, so
# nothing needs reporting — but it names maintenance, so the classifier reaches for
# the maintenance intent and the node files a ticket. Asking a question then being
# told a work order was raised is a bad answer and a real side effect.
SERVICE_HISTORY_RE = re.compile(
    r"\b(?:when|what date|which date|how long ago)\b.{0,60}"
    r"\b(?:serviced|servicing|inspected|maintained|repaired|replaced|checked|overhauled)\b"
    r"|\blast\s+(?:serviced|inspected|maintained|repaired|replaced|checked|service|inspection)\b"
    r"|\b(?:service|maintenance|repair|inspection)\s+(?:history|record|records|log)\b",
    re.IGNORECASE,
)


#: The explicit request to be told about the building as an entity (BUG-815).
_TELL_ME_ABOUT_THE_BUILDING_RE = re.compile(
    r"\b(?:tell\s+me\s+about|what\s+(?:do\s+you\s+know|can\s+you\s+tell\s+me)\s+about|describe)"
    r"\s+(?:this|the)\s+building\b",
    re.IGNORECASE,
)


def _r_building_profile(c: _Ctx) -> Optional[str]:
    """A question about the BUILDING AS AN ENTITY is not open-domain knowledge.

    "How old is this building?", "who built it?", "what type of building is
    this?" — the largest class of unanswered question in the survey corpus, and
    the shape an open-domain answerer handles worst: a plausible year is trivial
    to generate and impossible for the reader to falsify. Routed to capability,
    these are answered from the building's own triples or honestly declined.

    Narrow by construction: the detector ignores anything asking about the
    building's CONTENTS or live state ("how many sensors", "temperature right
    now"), so the metrics and sensor paths keep their questions.
    """
    from orchestrator.services.building_profile import detect_facet

    facet = detect_facet(c.query)
    # A CAPACITY question ("how many people can this building hold?") is a fact the building
    # records, yet the classifier reads "how many people" as a count of occupants and sends it to
    # the readings; it may take it from those lanes too.
    _takes = (
        "general",
        "general_knowledge",
        "clarification",
        "greeting",
        "metadata",
        "observability",
    )
    if facet == "capacity":
        _takes += ("sensor_data", "analytics", "recommend", "compare", "trend")
    if c.intent not in _takes:
        return None
    # `observability` is claimable, but ONLY for the explicit request to be told about the
    # building: "What can you tell me about this building?" matches the reach patterns on "can you
    # ... tell me" and listed 44 measurand names (BUG-815, F34). Measured over the 4,271 known
    # questions, letting it take every facet moved 89 out of the reach lane on words like
    # "check-in" (the "access" facet), and letting it take every whole-profile shape moved
    # "which questions can you NOT answer about this building yet?" -- a genuine reach question.
    if c.intent == "observability" and not _TELL_ME_ABOUT_THE_BUILDING_RE.search(c.query or ""):
        return None
    return "capability" if facet else None


def report_request_about_data(query: str) -> bool:
    """True when the query ASKS FOR A DOCUMENT about something measured.

    Public because two places need the SAME answer and must not drift: the
    parse-stage rule below, and the capability short-circuit in dialogue_agent,
    which returns intent="capability" before the LLM is ever called and
    therefore before any contract rule can run. A rule alone could not fix
    CAVEAT-201 — the request never reached it.
    """
    if not query or not REPORT_REQUEST_RE.search(query):
        return False
    return _any(query.lower(), SENSOR_METRIC_KWS)


def _r_report_request_not_capability(c: _Ctx) -> Optional[str]:
    """A request for a report ABOUT MEASURED DATA is a report, not an amenity.

    "Give me a report on energy use last week." was answered with the building's
    sustainability blurb: the ontology holds a KnowledgeTopic whose lay terms
    cover "energy", nothing in the query looks like a sensor reading, so the
    classifier picked capability and the question was answered by prose that
    contains no data at all.

    Three conditions, all required, keep this narrow:

    * the query must ASK for a document — the noun "report"/"summary"/
      "breakdown", not merely the verb, so "report the average temperature"
      stays a reading question;
    * it must name something MEASURED (SENSOR_METRIC_KWS — the same vocabulary
      the other data-promotion rules use), so "give me a report on the parking
      policy" keeps its capability answer, which is the correct one;
    * it must not be a fault STATEMENT, so "send someone a report, the toilet is
      leaking" still files a ticket rather than generating a document.
    """
    if c.intent not in ("capability", "general", "metadata", None):
        return None
    if not report_request_about_data(c.query):
        return None
    if c.sr.report_intake_intent(c.query):
        return None
    return "report"


def _r_self_description(c: _Ctx) -> Optional[str]:
    """A question about the ASSISTANT is not open-domain general knowledge.

    The open-domain answerer knows nothing about this system, so it supplies a
    plausible substitute — live it claimed to be "a large-language model built by
    OpenAI" and offered guidance on BACnet and ISO 50001 while naming none of
    OntoSage's actual abilities. The same failure as BUG-123, one step over.
    """
    if c.intent not in ("general", "general_knowledge", "capability", "clarification", "greeting"):
        return None
    from orchestrator.services.self_description import is_self_question

    return "self_description" if is_self_question(c.query) else None


def _r_history_question_not_report(c: _Ctx) -> Optional[str]:
    """A question about past maintenance is a question, not a report (BUG-104).

    Sends it to the capability chain, which answers from a service-history topic
    where the building has authored one and honestly declines where it has not —
    either way without creating a ticket. A genuine report still wins: the semantic
    router is consulted first, so "the lift is broken, when was it last serviced?"
    is still filed.
    """
    if c.intent not in ("maintenance", "complaint", "safety_report", "feedback", "suggestion"):
        return None
    if c.sr.report_intake_intent(c.query) is not None:
        return None
    return "capability" if SERVICE_HISTORY_RE.search(c.query) else None


def _r_comfort_question(c: _Ctx) -> Optional[str]:
    if c.intent not in ("complaint", "maintenance", "suggestion", "safety_report", "feedback"):
        return None
    if c.sr.report_intake_intent(c.query) is None and _any(c.ql, COMFORT_SIGNAL_KWS):
        return "analytics"
    return None


_WEAK_INTENTS = (
    "general",
    "general_knowledge",
    "capability",
    "clarification",
    "greeting",
    "discovery",
    "metadata",
    None,
)


#: A question about alarms that have ALREADY HAPPENED. "Have there been any alarms this
#: week?" was answered by the alert-CREATION lane — "I haven't created an alert yet. I need
#: what to measure … and the value that should trigger it" — a configuration form, in answer
#: to a question about what occurred (TODO-490).
#:
#: The two shapes are opposites: a standing alert is about the future and is created; an
#: alarm history is about the past and is read. Only the past is claimed here.
ALARM_HISTORY_RE = re.compile(
    r"\b(?:have|has|had|were|was|did)\b[^?]{0,40}\b(?:alarm|alarms|alert|alerts)\b"
    r"|\b(?:alarm|alarms|alert|alerts)\b[^?]{0,30}\b(?:went off|sounded|triggered|fired"
    r"|activated|raised|logged|recorded)\b"
    r"|\b(?:any|which|what|how many|list the)\b[^?]{0,20}\b(?:alarms|alerts)\b"
    r"[^?]{0,40}\b(?:this|last|past|today|yesterday|recently|so far)\b",
    re.IGNORECASE,
)


def _r_alarm_history_is_a_record(c: _Ctx) -> Optional[str]:
    """An alarm that already happened is a RECORD, not an alert to create (TODO-490).

    Guarded against the opposite shape: "alert me when CO2 goes high" is a standing request
    and keeps its lane, because this fires only when STANDING_ALERT_RE does not.
    """
    if c.intent != "alert":
        return None
    if STANDING_ALERT_RE.search(c.query):
        return None
    return "metadata" if ALARM_HISTORY_RE.search(c.query) else None


def _r_standing_alert(c: _Ctx) -> Optional[str]:
    """'notify me when X' / 'alert me if X' → alert (standing personal alert)."""
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    if _ASKS_WHEN_RE.search(c.query):
        return None
    return "alert" if STANDING_ALERT_RE.search(c.query) else None


#: "Could you tell me: when is X next due?" is a QUESTION with a polite frame, not a request to be
#: told when something happens later. The inverted verb after when/if ("when IS", "if WAS") marks it;
#: a standing request has a subject there ("tell me when THE CO2 …", "let me know if IT …").
_ASKS_WHEN_RE = re.compile(
    r"\b(?:tell|let)\s+me(?:\s+know)?\b\s*[:,]?\s*(?:when|if|whether)\s+"
    r"(?:is|was|are|were|does|did|do|has|have|will)\b",
    re.IGNORECASE,
)


def _r_automation_question(c: _Ctx) -> Optional[str]:
    """'can the system automatically …?' → automation_capability (honest answer)."""
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    if not (AUTOMATION_Q_RE.search(c.query) and _acts_on_a_building_system(c.query)):
        return None
    return "automation_capability"


#: What a question about AUTOMATION must be about: the building's own control acting on something
#: (lights, heating, doors, an alarm), or telling someone. "Does the system do an automatic back-up
#: of data in case of outages?" has the word "automatic" and none of this: it asks about IT
#: infrastructure, which the building's control does not own, and was answered "here is what this
#: building can do about alerts" (live 2026-09-20). A topic word ("back-up", "data", "outage") never
#: qualifies; a verb or an object the building actually controls does.
_ACTS_ON_A_SYSTEM_RE = re.compile(
    r"\b(?:turn(?:s|ed|ing)?\s+(?:on|off)|switch\w*|adjust\w*|dim\w*|open\w*|clos\w*|lock\w*|"
    r"unlock\w*|start\w*|stop\w*|shut\w*|regulat\w*|control\w*|heat\w*|cool\w*|ventilat\w*|"
    r"lights?|lighting|blinds?|shades?|thermostats?|hvac|doors?|windows?|fans?|dampers?|"
    r"setpoints?|valves?|alarms?|sprinklers?|lifts?|elevators?|generators?|fail-?over|"
    r"notif\w*|alert\w*|warn\w*|remind\w*|respond\w*|react\w*|optimi[sz]\w*|make\s+sure|ensure|"
    r"trigger\w*|detect\w*|increas\w*|decreas\w*|rais\w*|lower\w*|reduc\w*|boost\w*|"
    r"activat\w*|deactivat\w*|enabl\w*|disabl\w*|intake|exhaust|pumps?|chillers?|boilers?|"
    r"ahus?|vavs?|cut\w*)\b",
    re.IGNORECASE,
)


def _acts_on_a_building_system(query: str) -> bool:
    """True when an automation question names an action or a controlled thing, not just a topic."""
    return bool(_ACTS_ON_A_SYSTEM_RE.search(query or ""))


#: What an automation/alert question must SAY: something acting by itself, or a standing request.
_AUTOMATION_SHAPE_RE = re.compile(
    r"\bautomat\w*|\bon\s+its\s+own\b|\bby\s+itself\b|\bself[- ]\w+|\bnotif\w*|\balert\w*|"
    r"\bremind\w*|\bwarn\w*|\btrigger\w*|\bstanding\b|\bschedul\w*|\bwhenever\b|"
    r"\bevery\s+time\b|\bas\s+soon\s+as\b|\b(?:tell|let|message|email|text|ping|call)\s+me\s+"
    r"(?:know\s+)?(?:when|if|once|as|whenever)\b|\bwhen\b.{1,60}\b(?:tell|let|message|email|text|ping)\s+me\b|\bif\s+.{1,40}\b(?:let|tell|send)\s+me\b|\brules?\b",
    re.IGNORECASE,
)


#: The shapes that need no controlled thing: telling, reminding, a standing rule, a trigger.
_STRONG_SHAPE_RE = re.compile(
    r"\bnotif\w*|\balert\w*|\bremind\w*|\bwarn\w*|\btrigger\w*|\bstanding\b|\bschedul\w*|"
    r"\bwhenever\b|\bevery\s+time\b|\bas\s+soon\s+as\b|\brules?\b|"
    r"\b(?:tell|let|message|email|text|ping|call)\s+me\b",
    re.IGNORECASE,
)


def _r_automation_needs_a_shape(c: _Ctx) -> Optional[str]:
    """An automation/alert label with no automate/alert/notify/standing-rule shape → capability."""
    if c.intent not in ("automation_capability", "alert"):
        return None
    if _WHAT_TO_AUTOMATE_RE.search(c.query or ""):
        return None
    if _ENV_REQUEST_RE.search(c.query or ""):
        return "control"  # "can you reduce noise?" is a request to act, not an automation question
    if _ASKS_WHEN_RE.search(c.query or ""):
        return "capability"
    if not _AUTOMATION_SHAPE_RE.search(c.query or ""):
        return "capability"
    # "automatic" / "by itself" alone only count when something the building controls is acted on
    if not _STRONG_SHAPE_RE.search(c.query or "") and not _acts_on_a_building_system(c.query):
        return "capability"
    return None


# V4 ARBITER — constraint-recommendation shapes: choose/rank spaces under
# comfort constraints. Conservative from-set: weak intents + 'recommend' (which
# has no dedicated logic and collapses to generic analytics today); analytics/
# spatial_query classifications keep their proven routes.
#: Words that describe how a space FEELS — the vocabulary a person uses when they are not
#: naming a measurand. Each one resolves to a quantity through the concept resolver ("stuffy"
#: → CO2); none of them names a building, a room or a sensor.
_CONDITION_ADJECTIVES = (
    r"stuffy|noisy|loud|humid|damp|dry|dark|bright|cold|chilly|warm|hot|cool|quiet|"
    r"crowded|busy|smelly|draughty|drafty|muggy|stale"
)

#: "Is it stuffy ANYWHERE in the building?" — the existential shape of a comfort question,
#: with no space noun to hang a superlative on (TODO-629).
#:
#: It reached the capability lane, which probed 274 sensors and returned the row-budget
#: refusal: honest, and useless to someone who cannot be expected to know which floor to ask
#: about. The building can already rank every room on that quantity — "which room is the
#: warmest" answers in one step — and the only thing standing between the two questions was
#: a pattern that required the word "room".
#:
#: Both orders, because people write it both ways: "is it stuffy anywhere" and "is there
#: anywhere stuffy". A question that names neither a condition nor an existential scope is
#: untouched.
_EXISTENTIAL_SCOPE = r"anywhere|somewhere|any\s+(?:room|rooms|space|spaces|zone|zones|area|areas)"

EXISTENTIAL_COMFORT_RE = re.compile(
    r"\b(?:is|are|does|do|has|have)\b[^?]{0,40}?\b(?:" + _CONDITION_ADJECTIVES + r")\b"
    r"[^?]{0,40}?\b(?:" + _EXISTENTIAL_SCOPE + r")\b"
    r"|\b(?:is|are|does|do|has|have)\b[^?]{0,40}?\b(?:" + _EXISTENTIAL_SCOPE + r")\b"
    r"[^?]{0,40}?\b(?:" + _CONDITION_ADJECTIVES + r")\b",
    re.IGNORECASE,
)

DELIBERATE_RE = re.compile(
    r"(?:\bfind\s+(?:me\s+)?an?\s+[\w,\- ]{0,30}(?:room|space|spot|desk|place)\b"
    r"|\bwhere\s+(?:can|should|could)\s+i\s+(?:sit|work|study|go|be|stay)\b"
    # "where's a quiet place to sit" -- the same request without the pronoun.
    r"|\bwhere(?:'s|\s+is)\s+(?:a|an|the)\s+(?:\w+\s+){0,2}(?:place|spot|room|space|desk|seat|area)\b"
    r"|\b(?:quietest|noisiest|busiest|emptiest|calmest)\b"
    # Same intervening-adjective fix as WAYFIND_RE: "which STUDY spaces had the best air
    # quality" was measured landing in the document lane because "study" sat here.
    r"|\bwhich\s+(?:\w+\s+){0,2}(?:room|rooms|zone|zones|space|spaces|area|areas|desk|desks|seat|seats|spot|spots)\b"
    r".{0,50}\b(?:lowest|highest|least|most|best|worst|minimum|maximum"
    r"|warmest|coolest|coldest|hottest|brightest|darkest|loudest|driest|stuffiest)\b"
    # superlative-first shape: 'warmest room', 'brightest space on floor 2'
    r"|\b(?:warmest|coolest|coldest|hottest|brightest|darkest|loudest|quietest)\s+"
    r"(?:room|zone|space|area)s?\b"
    # "which desk should I take this afternoon" -- a recommendation request with
    # no superlative in it. Narrow on purpose: it needs a space noun AND an explicit
    # should-I verb, so "which policy should I read" and "which room is 2.14" stay out.
    r"|\bwhich\s+(?:\w+\s+){0,2}(?:room|zone|space|area|desk|seat|spot|floor)s?\s+"
    r"should\s+i\s+(?:take|book|use|choose|pick|sit|work)\b"
    # CAVEAT-563: the FILTER shape of the same question. "Which rooms on floor 5 are stuffy
    # right now?" reached the single-sensor lane, which saw one room's rows and said "no
    # other floor-5 rooms have recent data" of a floor with 46 instrumented rooms. Plural
    # space noun + a condition adjective is a question over every room, which is ARBITER's.
    r"|\bwhich\s+(?:\w+\s+){0,2}(?:rooms|zones|spaces|areas)\b.{0,40}\b(?:are|feel|seem|look)\s+"
    r"(?:too\s+|very\s+|quite\s+)?(?:stuffy|noisy|loud|humid|damp|dry|dark|bright|cold|chilly|"
    r"warm|hot|cool|quiet|crowded|busy)\b"
    r"|\brank\s+(?:the\s+)?\w*\s*(?:rooms|zones|spaces|areas)\b"
    r"|\b(?:zone|room|space|area)s?\s+with\s+(?:the\s+)?(?:minimum|maximum|least|most|lowest|highest)\b)",
    re.IGNORECASE,
)


def _r_constraint_recommendation(c: _Ctx) -> Optional[str]:
    """Constraint/recommendation question over spaces → deliberate (weak intents only)."""
    if c.intent not in _WEAK_INTENTS + ("recommend",):
        return None
    return "deliberate" if DELIBERATE_RE.search(c.query) else None


# V5-T24 — event-store questions: bookings/availability, work orders, entrance
# footfall. Combined comfort+availability phrasings ("QUIET room free at 3")
# must stay deliberate, so this rule sits BELOW the deliberate rules and its
# regex targets pure event vocabulary.
#: BUG-549: "free" meaning NO COST. "Is tap water free somewhere, or do I have to buy
#: bottles?" matched "is <subject> free" and went to the bookings lane, which answered "I
#: couldn't match that room name" to an occupant asking where to get water. The cost sense
#: always travels with money words, so their presence (and no booking vocabulary) decides it.
COST_SENSE_OF_FREE_RE = re.compile(
    r"\b(?:buy|buying|bought|pay|paying|paid|cost|costs|charge|charged|charges|price|priced|"
    r"fee|fees|purchase|free of charge|for free|free to use|complimentary)\b",
    re.IGNORECASE,
)

EVENTS_RE = re.compile(
    # "is <subject> free/booked" — single-subject availability; the subject
    # token keeps inventory questions ("what sensor types are available") out.
    #
    # The subject is up to THREE tokens, not one. With one, "is 5.01 booked"
    # matched but "is room 5.01 booked" did not, and neither did "is the seminar
    # room reserved" — so the most natural way to ask about a booking fell through
    # to the capability lane and was answered from a stale uploaded document while
    # 8,339 live booking records sat in the event store (measured 2026-08-25).
    # Three is deliberate: it covers "the seminar room" without reaching across a
    # prepositional phrase, so "is the temperature in room 5.01 available" — five
    # tokens — still belongs to the data lane rather than to bookings.
    # The subject cannot be a PARTICIPLE or an adverb: "which authorised key ... is confirmed
    # available" asks whether an access resource is confirmed, not whether a room is free, and it
    # was answered "about 19 arrivals through the main entrance today" (live 2026-09-20).
    r"(?:\bis\s+(?!there\b)(?!(?:confirmed|verified|currently|officially|formally|actually|now|still|"
    r"also|already|not|recorded|listed|held|approved|authori[sz]ed|shown|stated|marked|noted|"
    r"considered|deemed|reported|known|found|kept|made|being)\s)"
    r"(?:\S{2,}\s+){1,3}(?:free|booked|available|in use|reserved|occupied|taken)\b"
    # "step-free" is an ACCESSIBILITY term, not an availability one. Without the
    # lookbehind, "which rooms are step-free accessible?" matched here and was answered
    # with "69 of 233 rooms have no booking today" — a booking answer to an
    # accessibility question (measured 2026-08-25). Any hyphen-prefixed "free"
    # (step-free, barrier-free) is excluded: nobody asks whether a room is "X-free"
    # meaning unoccupied.
    r"|\b(?:which|what|any|list)\b.{0,40}\brooms?\b.{0,30}\b(?:(?<!-)free|available)\b"
    r"|\b(?:a|any)\s+rooms?\s+(?:(?<!-)free|available)\b"
    r"|\bbookings?\b|\breservations?\b"
    # "Which meeting rooms are booked this afternoon?" (BUG-828, B11): booked/reserved AFTER a
    # room noun. `bookings?` needs the noun and `is <subject> booked` needs "is", so this shape
    # fell to the six-booking document register instead of the live store.
    r"|\b(?:which|what|any|list|show)\b.{0,40}\brooms?\b.{0,30}\b(?:booked|reserved)\b"
    # Timetabled teaching. These land in the SAME event store as bookings (V6-T25
    # routes a timetable export there deliberately), so the vocabulary has to reach
    # the same lane — without it "what is scheduled in Room1.06 tomorrow?" and
    # "which rooms have teaching sessions this week?" were answered from an uploaded
    # bookings document showing June dates, while 675 timetable records for the right
    # weeks sat in the store (measured 2026-08-25).
    # "scheduled" is qualified: scheduled MAINTENANCE is a compliance-register
    # question and must keep going there.
    r"|\btimetabled?\b|\bteaching\s+(?:session|slot|hour)s?\b"
    # "lecture" but NOT "lecture theatre/hall/room" — those name a SPACE, and
    # "is there a step-free route to the lecture theatre?" is a wayfinding question.
    # Matching the bare noun stole it from the route finder.
    r"|\blectures?\b(?!\s+(?:theatre|theater|hall|room))"
    r"|\b(?:what(?:'s| is)?|anything)\s+(?:scheduled|booked|on)\b"
    r"|\bscheduled\s+(?:in|for)\s+(?!.*\b(?:maintenance|service|inspection|test)\b)"
    r"|\bwork ?orders?\b|\b(?:open|overdue|outstanding)\s+tickets?\b"
    r"|\bmaintenance backlog\b"
    r"|\bfootfall\b|\bentrance\b.{0,30}\b(?:busy|arrivals|count)\b"
    r"|\bhow busy was\b.{0,30}\b(?:entrance|building)\b"
    # RECURRENCE over the report history (V7-T73). "Which cleaning-related defects keep
    # recurring in the same place?" reached the capability lane, which searched the
    # cleaning SCHEDULE and honestly said it did not answer — it cannot, because a
    # schedule says when cleaning happens, not where a fault returns. The building holds
    # 203 reports with a location, a category and a date, and nothing was asking them.
    #
    # "persistent" and "chronic" are admitted only over a REPORTED thing: a catalogue
    # question asks about "persistent temperature, CO2 or particulate exceptions", which
    # is analytics over readings, and answering it from report history would return the
    # wrong kind of evidence entirely.
    r"|\b(?:recur|recurs|recurring|recurrence|repeatedly)\b"
    r"|\bkeeps? (?:happening|coming back|breaking|failing|being reported)\b"
    r"|\b(?:persistent|chronic)\s+\w*\s?"
    r"(?:issues?|problems?|faults?|defects?|complaints?|reports?|breakdowns?)\b)",
    re.IGNORECASE,
)


#: A booking question about the RECORD, not the moment (2D-06 wave 7). "How many bookings are
#: recorded in total?" and "How many bookings in Room 5.15 are confirmed?" were answered by the
#: events lane ("32 booking(s) for the building today", "0 booking(s) for Room 5.15 today — none on
#: record") while the room-booking register holds the whole record. The events lane is right for
#: today / now / free / available; it is wrong for in total / recorded / confirmed / every one /
#: giving each reference. A live-time word keeps the question with the events lane.
_BOOKING_NOUN_RE = re.compile(r"\b(?:bookings?|reservations?)\b", re.IGNORECASE)
_BOOKING_RECORD_SCOPE_RE = re.compile(
    r"\bin total\b|\brecorded\b|\bconfirmed\b|\bevery one\b|\bgiving each\b|\beach reference\b"
    r"|\bon record\b|\bprovisional\b|\bcancelled\b|\bbooking references?\b",
    re.IGNORECASE,
)
_LIVE_TIME_RE = re.compile(
    r"\b(?:today|tonight|tomorrow|now|currently|right now|free|available|vacant|"
    r"this\s+(?:morning|afternoon|evening|hour)|next\s+hour|at\s+\d)\b",
    re.IGNORECASE,
)


def booking_register_question(query: str) -> bool:
    """A booking question that asks about the record as a whole, never about the present moment."""
    q = query or ""
    return bool(
        _BOOKING_NOUN_RE.search(q)
        and _BOOKING_RECORD_SCOPE_RE.search(q)
        and not _LIVE_TIME_RE.search(q)
    )


def events_question(query: str) -> bool:
    """A booking / availability question: EVENTS_RE, less "free" in the sense of NO COST.

    ONE OWNER for a decision three places were making (BUG-549's second half, found 2026-09-18).
    The events rule and the event service applied the cost-sense exclusion and the capability
    route's veto did not: it imported the raw regex, so "Is tap water free somewhere, or do I have
    to buy bottles?" was vetoed as a booking question and never reached the deterministic amenity
    route that answers "Can I get free water in this building?" in a second. The building has
    drinking-water points on every floor; the recommend lane said no sensor tells whether tap water
    is free. Two consumers held the fix and one held the bug, which is what a decision with several
    owners does.

    The cost sense travels with money words; booking vocabulary overrides it, so "is the room free
    for a meeting, I'll pay for it" (rare) still counts as a booking question.
    """
    q = query or ""
    if booking_register_question(q):
        return False  # the record as a whole belongs to the room-booking register
    if COST_SENSE_OF_FREE_RE.search(q) and not re.search(
        r"\b(?:bookings?|reservations?|booked|reserved)\b", q, re.IGNORECASE
    ):
        return False
    # "Has anything been reported broken this week?" asks the REPORT store (BUG-828, B23); the
    # events lane reads it, so the shape has one definition, owned by report_activity.
    from orchestrator.services.report_activity import is_report_activity_question

    return bool(EVENTS_RE.search(q)) or is_report_activity_question(q)


_INTERROGATIVE_RE = re.compile(
    r"^\s*(?:how many|how much|any|are there|is there|what|which|when|show|list|count|do we have)\b"
    r"|\?\s*$",
    re.IGNORECASE,
)


#: Work orders and timetabled teaching exist in TWO places: the authored registers, whose rows carry
#: ids, statuses and dates a person can act on (WO-008, TS-0670), and the events store, whose rows are
#: generated operational fill. Only the register can answer "which ones" and "whose id".
#: "tickets" is deliberately absent: a ticket question is about AGING ("any overdue tickets?"),
#: which the events store tracks and the work-order register cannot — it records no due date.
_WORK_ORDER_RECORD_RE = re.compile(r"\bwork\s*orders?\b", re.IGNORECASE)
_TIMETABLE_RECORD_RE = re.compile(
    r"\b(?:timetabled?|teaching|lecture|seminar|tutorial)\s+"
    r"(?:session|slot|class|classes|hour)s?\b|\bteaching\s+sessions?\b",
    re.IGNORECASE,
)


def register_owns_the_record(query: str) -> bool:
    """True when an authored register, not the events store, is the source for this question.

    Both regressed on the probe the same way (2026-09-19): the classifier sent "How many work
    orders are open?" and "Which teaching sessions are scheduled in Room 1.06?" to the events lane,
    which answered 517 generated work orders instead of the register's three open ones (WO-008,
    WO-013, WO-015) and, for the timetable, said the building "doesn't keep a record of that" while
    675 session rows sat in the register — the events lane has no timetable kind at all, so its
    vocabulary claims a question it cannot serve. Which lane answers must not depend on the
    classifier's mood, so the contract decides it here.

    A statement still files a ticket: only interrogative shapes are claimed.
    """
    q = query or ""
    if not (_INTERROGATIVE_RE.search(q) or q.rstrip().endswith("?")):
        return False
    return bool(
        _WORK_ORDER_RECORD_RE.search(q)
        or _TIMETABLE_RECORD_RE.search(q)
        or booking_register_question(q)
    )


def _r_register_owns_work_orders_and_timetable(c: _Ctx) -> Optional[str]:
    """Work-order and teaching-timetable questions → the register lane (`metadata`).

    Claims from `events` as well as the weak intents, because the classifier reaches that lane
    directly. Every rule in a stage runs and each one SETS the intent, so this must sit AFTER
    `event_store_query` to survive it — placing it before merely had that rule overwrite the
    answer, which is how the first attempt at this fix changed nothing live.
    """
    if c.intent not in _WEAK_INTENTS + ("events", "sensor_data", "analytics", "recommend"):
        return None
    if c.sr is not None and (
        c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query)
    ):
        return None  # a fault statement files a ticket; a command is declined
    return "metadata" if register_owns_the_record(c.query) else None


def _r_event_store_query(c: _Ctx) -> Optional[str]:
    """Pure event-store question → events lane (never fault reports/actions).

    BUG-166: work-order vocabulary classifies as maintenance and the intake
    path FILES A TICKET even for questions ("how many open work orders?").
    Interrogative shapes flip to the events lane; statements keep filing.
    """
    from_set = _WEAK_INTENTS + ("sensor_data", "analytics", "recommend")
    interrogative = bool(_INTERROGATIVE_RE.search(c.query or ""))
    if c.intent in ("maintenance", "complaint", "report"):
        if not interrogative:
            return None  # a statement — intake is correct
    elif c.intent not in from_set:
        return None
    if c.sr.is_control_command(c.query):
        return None
    if c.intent not in ("maintenance", "complaint", "report") and c.sr.report_intake_intent(
        c.query
    ):
        return None  # statement shapes stay with intake
    if DELIBERATE_RE.search(c.query):
        return None  # comfort-constrained phrasing keeps the deliberative lane
    # "is tap water free, or do I have to buy bottles?" is about cost (BUG-549): the exclusion lives
    # in `events_question`, which the capability route's veto uses too.
    return "events" if events_question(c.query) else None


# V5-T26 — compliance-REGISTER questions (dated checks), distinct from both the
# sensor-standards 'compliance' intent and workorder/ticket questions (events).
REGISTER_RE = re.compile(
    r"(?:\b(?:overdue|past due|missed)\b.{0,40}\b(?:check|test|inspection|assessment|"
    r"compliance|certificate|service|flush|examination)s?\b"
    r"|\b(?:check|test|inspection|assessment|compliance|certificate)s?\b.{0,30}\b(?:overdue|past due)\b"
    r"|\bwhen (?:was|did)\b.{0,60}\blast\b.{0,30}\b(?:tested|serviced|inspected|checked|flushed|examined|done)\b"
    r"|\blast (?:tested|serviced|inspected|checked|flushed|examined)\b"
    r"|\b(?:fire alarm|emergency lighting|legionella|fire door|extinguisher|loler|pat test"
    r"|f-?gas|risk assessment)\b.{0,40}\b(?:due|overdue|test|record|history|when|last)\b"
    r"|\bcompliance (?:calendar|register|record)s?\b"
    r"|\bwhat(?:'s| is)?\s+(?:due|coming up)\b.{0,30}\b(?:month|week|days|quarter)\b"
    # "what inspections are due this month?", "any checks due next week?"
    r"|\b(?:check|test|inspection|assessment|certificate)s?\s+(?:are\s+|is\s+)?"
    r"(?:due|coming up)\b)",
    re.IGNORECASE,
)


def register_question(query: str) -> bool:
    """True when the register lane would claim this query (shape + known item).

    Shared by the ``compliance_register`` rule below AND the dialogue agent's
    capability short-circuit bypass — "when was the fire alarm last tested?"
    matches the fire-safety KnowledgeTopic by lay-term, and without the bypass
    the topic prose (which holds no dates) answers instead of the register.
    """
    if not REGISTER_RE.search(query or ""):
        return False
    # last-done shapes are claimed only for KNOWN register items ("fire alarm",
    # "PAT", …). Generic equipment service-history ("when was chiller 7 last
    # serviced?") stays with history_question_not_report → capability chain.
    from orchestrator.services.compliance_register_service import (  # local: no cycle
        classify_register_question,
        match_item,
    )

    return not (classify_register_question(query) == "last_done" and match_item(query) is None)


def _r_asset_state_query(c: _Ctx) -> Optional[str]:
    """Service/asset STATE question -> asset_state lane (V6-T58/T60).

    The same BUG-166 shape as the events rule, in a second place: "are there any planned
    closures coming up?" classified as MAINTENANCE and the intake path FILED A TICKET
    (REP-E1A800, measured 2026-08-25) instead of answering a plainly interrogative
    question. A closure is a scheduled state change the building already records; asking
    about one is not reporting a fault.

    Statements keep filing: "the lift is broken" is a report and must reach intake.
    """
    from orchestrator.services.asset_state_service import is_asset_state_question

    interrogative = bool(_INTERROGATIVE_RE.search(c.query or ""))
    from_set = _WEAK_INTENTS + ("sensor_data", "analytics", "capability", "compliance")
    if c.intent in ("maintenance", "complaint", "report", "safety_report"):
        if not interrogative:
            return None  # a statement — intake is correct
    elif c.intent not in from_set:
        return None
    if c.sr.is_control_command(c.query):
        return None
    if c.intent not in ("maintenance", "complaint", "report", "safety_report") and (
        c.sr.report_intake_intent(c.query)
    ):
        return None  # statement shapes stay with intake
    if EVENTS_RE.search(c.query or ""):
        return None  # a booking/availability question belongs to the events lane
    if register_question(c.query or ""):
        return None  # a dated compliance question belongs to the register
    return "asset_state" if is_asset_state_question(c.query) else None


#: A named standard or scheme the compliance lane can actually check a reading against.
#: International standards, not any building's own vocabulary.
_NAMED_STANDARD_RE = re.compile(
    r"\bashrae\b|\bwell\s*(?:v\d|standard|building)\b|\bbreeam\b|\bleed\b|\bcibse\b"
    r"|\biso\s*\d{3,}\b|\ben\s*\d{3,}\b|\bbs\s*\d{3,}\b|\bwcag\b|\bpart\s+[a-l]\b",
    re.IGNORECASE,
)


def _r_compliance_without_a_measurable_check(c: _Ctx) -> Optional[str]:
    """A compliance question with nothing measurable in it is not a compliance check.

    The compliance lane reads sensors and compares them against a standard. Asked "do
    local procedures and work instructions implement the current institutional policies
    without omissions, contradictions or unauthorised local variation?" it had neither a
    reading nor a standard, and emitted its own template — "**Compliance Check — Zone or
    Sensor Required**", followed by three worked examples about a zone's temperature. A
    question about whether two sets of DOCUMENTS agree was answered with an instruction
    to ask about a thermometer (C19).

    Three conditions, all required, keep it narrow: the question must name no measurand
    (so "is the temperature within limits?" stays), no space (so "check zone 5.28"
    stays), and no standard (so "are we compliant with ASHRAE 55?" keeps the template,
    whose ask is exactly right for it). What is left is a policy question, and the
    capability lane holds the documents — or says honestly that it holds none.

    Sits BEFORE compliance_register on purpose: this contract is last-wins, so a dated
    register question ("when was the fire alarm last tested?") is still taken back by
    the rule that owns it.
    """
    if c.intent != "compliance":
        return None
    if _NAMED_STANDARD_RE.search(c.query or ""):
        return None
    from orchestrator.services.plausibility import measurand_of
    from orchestrator.services.referent_resolver import names_a_specific_space

    if measurand_of(c.query or ""):
        return None
    if names_a_specific_space(c.query or ""):
        return None
    return "capability"


def _r_compliance_register(c: _Ctx) -> Optional[str]:
    """Dated register question → register lane; sensor-limit checks stay put."""
    interrogative = bool(_INTERROGATIVE_RE.search(c.query or ""))
    if c.intent in ("maintenance", "complaint", "report"):
        if not interrogative:
            return None
    elif c.intent not in _WEAK_INTENTS + ("sensor_data", "analytics", "compliance", "recommend"):
        return None
    if c.sr.is_control_command(c.query):
        return None
    if c.intent not in ("maintenance", "complaint", "report") and c.sr.report_intake_intent(
        c.query
    ):
        return None  # statement shapes ("the fire door is broken") stay with intake
    if EVENTS_RE.search(c.query) and re.search(
        r"\btickets?|work ?orders?\b", c.query, re.IGNORECASE
    ):
        return None  # workorder aging stays with the events lane
    return "register" if register_question(c.query) else None


def _r_why_diagnosis(c: _Ctx) -> Optional[str]:
    """Comfort why-question -> diagnosis lane (V5-T20). Runs LAST: comfort
    questions were already flipped to analytics by comfort_question, so
    analytics is in the from-set; statements keep their intake route."""
    from orchestrator.services.anomaly.diagnosis import (
        is_why_question,  # local: no cycle
    )

    if c.intent in ("maintenance", "complaint", "report"):
        if not _INTERROGATIVE_RE.search(c.query or ""):
            return None
    elif c.intent not in _WEAK_INTENTS + ("sensor_data", "analytics", "anomaly", "recommend"):
        return None
    if c.sr.is_control_command(c.query):
        return None
    return "diagnosis" if is_why_question(c.query) else None


# The `(?:\w+\s+){0,2}` gaps are load-bearing. Every one of these was measured failing on
# the golden baseline because an adjective sat between the cue word and the noun: "the nearest
# ACCESSIBLE toilet", "the nearest FIRE exit". Bounded at two words rather than `.*` so the
# pattern cannot run across a clause and claim an unrelated question.
WAYFIND_RE = re.compile(
    r"\bdirections?\s+(?:to|for)\b"
    r"|\broute\s+to\b"
    r"|\bnavigate\s+to\b"
    r"|\bguide\s+me\s+to\b"
    r"|\btake\s+me\s+to\b"
    r"|\bfind\s+my\s+way\s+to\b"
    r"|\bhow\s+(?:do|can|would)\s+i\s+(?:get|reach|go)\s+to\b"
    r"|\b(?:nearest|closest)\s+(?:\w+\s+){0,2}(?:toilet|wc|restroom|bathroom|lift|elevator"
    r"|stair\w*|kitchen|exit|reception|meeting\s+room|desk|office|room|space)s?\b"
    r"|\b(?:step[- ]?free|wheelchair(?:[- ]accessible)?)\s+(?:route|way|path|access)\b",
    re.IGNORECASE,
)

#: BUG-597: routes COMPARED with each other — recorded circulation data, not a way to go.
#: A reading ACROSS a plant circuit: delta-T, flow vs return, approach temperature. The
#: measurand plus the circuit word is what separates "what is the delta-T across the
#: heating circuit" from "which checkpoints are on the north circuit".
PLANT_READING_RE = re.compile(
    r"\bdelta[- ]?t\b"
    r"|\b(flow|return|supply|leaving|entering)\s+(water|air)\s+temperature\b"
    r"|\b(heating|chilled|cooling|hot[- ]water|primary)\s+(circuit|loop)\b.{0,40}\b(temperature|delta|reading|performance)\b"
    r"|\bapproach\s+temperature\b",
    re.IGNORECASE,
)


#: A MEASURED QUANTITY ASKED FOR AS A READING is never a register question (2D-06 wave 9).
#: "are VOC levels safe in my workspace?" selected the workspace register on "workspace" and was
#: answered "the building's records do not contain any information about VOC concentrations" — the
#: building has VOC sensors. A quantity a sensor measures, plus a reading shape (levels, readings,
#: safe, ppm, how high), belongs to the readings lane, or to a clarification about the place.
#: Noise, light and daylight are deliberately NOT here: the registers record those as attributes.
_MEASURED_QUANTITY_RE = re.compile(
    r"\b(?:t?vocs?|volatile organic|particulates?|pm\s?(?:1|2\.5|10)|dust|formaldehyde|radon|"
    r"carbon (?:mono|di)oxide|co2?|air quality|temperature|humidity|smoke|fumes?)\b",
    re.IGNORECASE,
)
_READING_SHAPE_RE = re.compile(
    r"\b(?:levels?|readings?|concentrations?|safe|unsafe|ppm|how (?:high|much|bad)|"
    r"too (?:high|low|hot|cold|humid|dry)|is it|are they)\b",
    re.IGNORECASE,
)


def measured_reading_question(query: str) -> bool:
    """A question that asks for the value of something a sensor measures."""
    q = query or ""
    return bool(_MEASURED_QUANTITY_RE.search(q) and _READING_SHAPE_RE.search(q))


ROUTE_COMPARISON_RE = re.compile(
    r"\b(?:slower|faster|quicker|longer|shorter)\s+than\b|\bfloor\s+pairs?\b"
    r"|\bcompare\s+(?:the\s+)?(?:routes?|travel\s+times?)\b",
    re.IGNORECASE,
)


#: Equipment classes whose points a plant question names. These are BRICK vocabulary, not
#: building literals -- every Brick building that has an air handler types it brick:AHU -- so
#: they are portable in a way a room id or a zone name would not be.
_PLANT_EQUIP_RE = re.compile(
    r"\b(?:ahu[-_ ]?\w{0,8}|air[- ]handl\w+(?:\s+unit)?|vav\b\w{0,20}"
    r"|air[- ]handler|fan[- ]coil|fcu\b|chiller|boiler|heat pump)\b",
    re.IGNORECASE,
)


#: Measurands nothing in a ROOM has, so they identify a plant question on their own without
#: an equipment id in the text. Deliberately short: every entry here is a phrase that would be
#: meaningless about a room, because a false positive drags a room reading into the plant lane.
_PLANT_ONLY_RE = re.compile(
    r"\b(?:damper"
    r"|filter\s+(?:d[/\s]?p|differential|pressure|loading)"
    r"|supply\s+fan|return\s+fan|extract\s+fan"
    r"|fan\s+(?:state|status)"
    r"|supply\s+air\b|return\s+air\b)",
    re.IGNORECASE,
)


@lru_cache(maxsize=8)
def _plant_measurand_re(building_id: Optional[str] = None) -> "re.Pattern":
    """Phrases naming a plant measurand, BUILT FROM THE MODALITY CONFIG.

    Derived rather than written out so a building that declares a seventh equipment-scoped
    modality is recognised without a code change -- the same rule that keeps sensor
    vocabulary out of this file. `supply_air_temperature` becomes `supply\s+air\s+temperature`.

    Falls back to matching nothing when the config is unreadable. That is the safe direction:
    an unmatched plant question is misrouted, whereas a catch-all pattern would drag ordinary
    room-temperature questions into the plant lane.
    """
    try:
        from orchestrator.services.evidence.plant_state import plant_modalities

        names = plant_modalities(building_id)
    except Exception:
        names = []
    if not names:
        return re.compile(r"(?!x)x")
    alts = [r"\s+".join(re.escape(part) for part in n.split("_")) for n in names]
    # Common shorthands operators actually type. Tied to the modality that licenses them, so
    # they disappear from the pattern if the building does not declare that modality.
    if "fan_state" in names:
        alts += [r"(?:supply\s+)?fan\s+(?:is\s+)?(?:running|on|off|state|status)"]
    if "filter_differential_pressure" in names:
        alts += [r"filter\s+(?:d[/\s]?p|pressure|loading)", r"filter\s+differential"]
    if "damper_position" in names:
        alts += [r"damper\b"]
    if "supply_air_flow" in names:
        alts += [r"air\s*flow\b", r"airflow\b"]
    return re.compile(r"\b(?:" + "|".join(alts) + r")", re.IGNORECASE)


def plant_point_question(query: str, building_id: Optional[str] = None) -> bool:
    """True when a question asks about a plant/BMS point rather than a room reading.

    BOTH halves are required -- a plant measurand AND a named equipment kind. "What is the
    air temperature in room 5.01" names a measurand this config knows about (`return air
    temperature` shares the word) but is a ROOM question, and answering it from a duct sensor
    would be exactly the substitution the non-substitution rule forbids. Requiring the
    equipment reference keeps the two populations apart.

    The exception is a measurand only plant has: nothing in a room has a damper position, a
    filter differential pressure or a supply fan, so those stand alone. "Is the supply fan
    running on floor 5?" carries no equipment id at all -- it names the fan, which IS the
    equipment -- and was measured landing in a maintenance-log document without this.
    """
    if not query or not query.strip():
        return False
    mre = _plant_measurand_re(building_id)
    if not mre.search(query):
        return False
    if _PLANT_EQUIP_RE.search(query):
        return True
    return bool(_PLANT_ONLY_RE.search(query))


#: Mass nouns for a metered resource. A quantity OF one of these is never a count of devices.
_RESOURCE_NOUN = r"(?:energy|electricity|power|water|gas|kwh|fuel|heat)"

#: A question about METERED CONSUMPTION of a utility. Generic English and generic resources --
#: no building literals -- so the same rule serves any estate with a meter.
CONSUMPTION_RE = re.compile(
    r"\b(?:how much|what(?:'s| is| was)|total|monthly|weekly|daily|annual)\b.{0,40}"
    r"\b(?:energy|electricity|power|water|gas|kwh|consumption|utilit(?:y|ies))\b"
    r"|\b(?:energy|electricity|power|water|gas)\s+(?:use|usage|consumption|consumed|bill|cost)\b"
    r"|\b(?:consumption|kwh)\b.{0,30}\b(?:floor|building|room|zone|lab|last|this|yesterday)\b"
    r"|\bhow (?:much|many) kwh\b",
    re.IGNORECASE,
)


def consumption_question(query: str) -> bool:
    """True when the question asks what something CONSUMED, rather than about a device.

    "How many energy meters are there?" is a census and must stay with the inventory guard that
    already owns that distinction -- giving one decision two owners is how the two drift.
    """
    if not query or not query.strip():
        return False
    # "How much <resource>" asks for a QUANTITY of a mass noun and can never be a
    # device census. That used to be stated HERE, pre-empting the inventory guard,
    # because narrowing the shared guard looked riskier than working around it. The
    # workaround left one decision with two owners, which is the drift this contract
    # exists to prevent, so the rule now lives in _is_countable_meta and this simply
    # agrees with it (BUG-266). The behaviour is unchanged; the ownership is not.
    if re.search(rf"\bhow much\b.{{0,20}}\b{_RESOURCE_NOUN}\b", query, re.IGNORECASE):
        return True
    if _is_countable_meta(query.lower()):
        return False
    return bool(CONSUMPTION_RE.search(query))


def _r_observability_query(c: _Ctx) -> Optional[str]:
    """Questions about the SYSTEM'S REACH -> the observability lane (V6-T10).

    "Can you measure formaldehyde in 5.01?" asks whether a value exists to be had; "What is
    the CO2 in 5.01?" asks for the value. Answering the first from prose is how BUG-192
    happened -- a model denying a sensor class from its retrieval window minutes after quoting
    one of its readings.

    Runs BEFORE the consumption and plant rules: "can you measure the energy use of floor 2?"
    is a reach question that happens to name a metered resource, and a figure is the wrong
    answer to it.
    """
    # `floor_plan` is in the claimable set because the classifier reaches for it on
    # "where is X happening, and what detection covers it?" -- measured, and answered with a
    # floor-plan PICKER in response to a fire-safety question. The reach patterns never match
    # "show me floor 3" or "where is the server room", so no genuine floor-plan request moves.
    if c.intent not in _WEAK_INTENTS + ("sensor_data", "metadata", "discovery", "floor_plan"):
        return None
    if c.sr.is_control_command(c.query):
        return None
    from orchestrator.services.building_profile import detect_facet
    from orchestrator.services.observability import is_observability_question

    # A question about the BUILDING AS AN ENTITY is not about the system's reach, however the
    # words fall: "what can you tell me about this building?" contains "can you ... tell me" and
    # was answered with a menu of measurands (BUG-815). building_profile_question, which runs
    # earlier, has already claimed it; without this guard THIS rule, running later, took it back.
    if detect_facet(c.query):
        return None
    return "observability" if is_observability_question(c.query) else None


def _r_consumption_query(c: _Ctx) -> Optional[str]:
    """Metered-consumption questions -> analytics, not a document (V6-T27).

    Measured before the rule existed: "How much energy did the building use last week?" was
    answered "I don't have that specific information on record" while six floor meters held the
    data, and "How much electricity does the lab on floor 5 use?" returned the room-bookings
    document. Both were classified `capability` and never reached a lane that could state a
    figure -- so they could not state a BOUNDARY either, which is what this turn is for.
    """
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query):
        return None
    # An attribution question is refused, not answered — the privacy rule owns it and runs first.
    from orchestrator.services.privacy.inference_classes import classify_inference

    if classify_inference(c.query):
        return None
    return "analytics" if consumption_question(c.query) else None


def _r_plant_point_query(c: _Ctx) -> Optional[str]:
    """Plant / BMS point questions -> sensor_data (V6-T26).

    Measured before the rule existed: "what is the filter differential pressure on AHU_F5?"
    and "is the supply fan running on floor 5?" were classified `capability` and answered from
    a maintenance-log document and a building-statistics block respectively -- with the points
    connected and readable the whole time. `is_data_query` could not catch them because an
    equipment id matches none of its sensor / zone / room / floor patterns.
    """
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query):
        return None
    return "sensor_data" if plant_point_question(c.query) else None


def _r_route_comparison_is_data(c: _Ctx) -> Optional[str]:
    """ "Is the step-free route slower than the stairs?" → metadata (the register holds it).

    BUG-597 stopped the route finder claiming these ("No staircase spaces found"). The
    classifier then read the comparison as `compare`, whose canned template asked for zone ids
    and offered to compare CO2 — while the circulation register holds a walking time and a
    step-free time for every floor pair. A comparison of RECORDED times is a data question
    about records, not a measurement.
    """
    if c.intent not in _WEAK_INTENTS + ("compare", "trend", "analytics", "sensor_data"):
        return None
    return "metadata" if ROUTE_COMPARISON_RE.search(c.query) else None


def _r_wayfinding_spatial(c: _Ctx) -> Optional[str]:
    """Route/nearest-facility questions -> spatial_query (V5-T27).

    The spatial agent's route finder answers with hop paths, metres and
    step-free handling; the floor_plan node only LOCATES. Claims floor_plan
    too (the LLM's habitual label for these) but never 'where is room X' /
    'show me floor N', which carry none of these shapes.
    """
    if c.intent not in _WEAK_INTENTS + ("floor_plan",):
        return None
    if c.sr.is_control_command(c.query):
        return None
    # BUG-597: "On which floor pairs is the step-free route slower than the stairs?" compares
    # RECORDED travel times; "step-free route" matched and the route finder answered "No
    # staircase spaces found." A comparison between routes asks for data, not directions.
    if ROUTE_COMPARISON_RE.search(c.query):
        return None
    return "spatial_query" if WAYFIND_RE.search(c.query) else None


#: A journey somebody has WALKED AND RECORDED, as against one computed from a drawing.
#:
#: The building publishes surveyed routes: which entrance, whether the way is step-free,
#: how many places there are to sit, how the doors operate, which lift and whether it is
#: in service, how much time to allow and how busy it is. The record spec says plainly why
#: that is the source for these questions — a route inferred from geometry is a guess about
#: somebody's journey, and a wrong guess costs them the journey.
#:
#: Deliberately narrow: an accessibility word must sit beside a JOURNEY noun. "Take me to
#: the nearest accessible toilet" and "where is the accessible entrance" name a place, not
#: a way through, and keep the route finder and the amenity lanes they already reach.
ACCESSIBLE_ROUTE_RE = re.compile(
    r"\b(?:step[-\s]?free|barrier[-\s]?free|wheelchair(?:[-\s]accessible)?|push[-\s]?chair|"
    r"pushchair|buggy|pram|level[-\s]access|accessible|mobility)\b"
    r"(?:\s+\w+){0,2}\s+\b(?:routes?|ways?|paths?|journeys?|access)\b"
    r"|\b(?:routes?|ways?|paths?|journeys?)\b[^.?!]{0,40}?"
    r"\b(?:step[-\s]?free|barrier[-\s]?free|wheelchair|push[-\s]?chair|pushchair|"
    r"level[-\s]access)\b",
    re.IGNORECASE,
)


def _r_accessible_route_is_a_surveyed_record(c: _Ctx) -> Optional[str]:
    """ "Which verified step-free route should I take?" → the surveyed route records.

    Run-3 row 61 (2026-09-17): "I need a step-free route to supervision that avoids the
    busiest and noisiest areas around class changeover. Which verified route should I
    take?" was classified as a request to rank spaces, so the ranking lane took it and
    then honestly declined — a decline that cost the reader the answer the building holds.
    Rows 72 and 111 of the same run, whose wording missed the route patterns by accident,
    reached the surveyed records and answered with the route, its lift, its doors and its
    rest stops.

    Claims from `deliberate` and `spatial_query` as well as the weak intents, because both
    of those are exactly where this shape was going wrong: one ranks rooms, the other
    computes a path from a drawing, and neither can say when the way was last walked or
    whether its lift is in service today.
    """
    if c.intent not in _WEAK_INTENTS + (
        "deliberate",
        "spatial_query",
        "floor_plan",
        "recommend",
        "compare",
    ):
        return None
    if c.sr.is_control_command(c.query):
        return None
    return "metadata" if ACCESSIBLE_ROUTE_RE.search(c.query or "") else None


def _r_room_geometry_spatial(c: _Ctx) -> Optional[str]:
    """ "How big is room X" -> spatial_query, not capability.

    Room areas live in the DWG floor-plan manifests, so only the spatial agent
    can answer them. The classifier reads a question about a named room as a
    capability lookup, which then reports having no information -- while the
    manifest holds that room's measured area. That failure is worse than a wrong
    number: it tells the user to go add data the system already has, and it hides
    exactly the geometry that surveying a building's floor plans produced.

    The shape test lives on SemanticRouter, shared with the capability bypass, so
    the two cannot disagree about what a geometry question is. Adjacency is NOT
    claimed here; it already routes correctly and its rules run earlier.
    """
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query):
        return None
    return "spatial_query" if c.sr.is_space_geometry_question(c.query) else None


ANOMALY_HISTORY_RE = re.compile(
    r"\banomal(?:y|ies|ous)\b|\bunusual (?:readings?|behaviou?rs?|activity|patterns?)\b"
    r"|\bweird (?:data|readings?|values?)\b|\boutliers?\b|\bsensor (?:faults?|glitch(?:es)?)\b",
    re.IGNORECASE,
)


def _r_anomaly_history_to_events(c: _Ctx) -> Optional[str]:
    """Anomaly questions -> the scanner's persisted episodes (V5-T21).

    The events store holds durable anomaly episodes with stable IDs (T19); a
    fresh z-score pass over one fetch cannot see stuck/dropout/drift history.
    Claims 'report' too — the LLM labelled "any anomalies this week?" a
    report and GENERATED a document asserting zero data (live shakedown) —
    but an explicit document ask ("generate the anomaly report") keeps the
    report pipeline."""
    if c.intent == "report":
        if re.search(
            r"\b(?:generate|create|produce|prepare|compile|write|draft)\b.{0,40}\breport\b",
            c.query,
            re.IGNORECASE,
        ):
            return None  # a document request, not a question
    elif c.intent not in _WEAK_INTENTS + ("anomaly", "sensor_data", "analytics"):
        return None
    if c.sr.is_control_command(c.query):
        return None
    return "events" if ANOMALY_HISTORY_RE.search(c.query) else None


#: Intents a room-superlative question is observed to land in when the classifier
#: wobbles. CAVEAT-327 measured lane entry at 6/8 per arm, and the downgrades were TWO
#: of the three plan mismatches — a bigger contributor than compile wobble. All ten
#: benchmark questions match DELIBERATE_RE, so the pattern was never the gap: the two
#: deliberate rules gate on DISJOINT intent sets (weak+recommend, and analytics+
#: sensor_data) and everything between them fell through to a reflex answer.
#:
#: floor_plan and spatial_query are the ones that actually bite: naming a floor pulls
#: "which room on floor 2 is quietest" toward floor_plan, and "where can I sit near the
#: cafe" toward spatial_query. Widening is safe because DELIBERATE_RE still has to
#: match — it requires a superlative or an explicit should-I shape, so "show me floor 2"
#: and "where is room 2.14" are untouched and stay with their own lanes.
_SUPERLATIVE_TAKEOVER_INTENTS = (
    "analytics",
    "sensor_data",
    "floor_plan",
    "spatial_query",
    "compare",
    "trend",
)


def _r_superlative_room_takeover(c: _Ctx) -> Optional[str]:
    """Room-superlative shape classified analytics/sensor_data → deliberate (BUG-163).

    Post-saturation the deliberative path holds full per-room coverage on every
    modality; generic analytics demonstrably cannot rank rooms (it aggregated a
    hardware-scale column into '0.00 ppm' answers). Lowest precedence: it fires
    only when no earlier rule (comfort question, compare, data promotion) did.
    """
    if c.intent not in _SUPERLATIVE_TAKEOVER_INTENTS:
        return None
    return "deliberate" if DELIBERATE_RE.search(c.query) else None


#: Intents an existential comfort question is observed to land in. `capability` leads, which
#: is where "is it stuffy anywhere in the building?" actually went — the classifier reads it
#: as asking whether the building CAN tell you, and the honest capability answer ("that
#: reaches 274 sensors") is not the answer the person wanted.
_EXISTENTIAL_COMFORT_INTENTS = (
    "capability",
    "general",
    "general_knowledge",
    "sensor_data",
    "analytics",
    "metadata",
    "discovery",
    "observability",
    # "Is it too warm anywhere right now?" was classified `compliance`, and the compliance
    # lane handed the model a prompt with no question in it — the answer came back "No
    # question was provided." after 116 seconds (BUG-630 owns that prompt). A comfort
    # condition over an existential scope is a ranking question whichever lane the
    # classifier guessed, so the shape is claimed here rather than chased lane by lane.
    "compliance",
)


def _r_existential_comfort_is_deliberate(c: _Ctx) -> Optional[str]:
    """ "Is it stuffy anywhere?" → deliberate: rank the rooms and name the worst (TODO-629).

    The same question with a space noun in it — "which room is the stuffiest" — has been
    ARBITER's since BUG-163. Without one it fell to a lane that reads 274 sensors and gives
    up, so the building's ability to answer depended on the questioner already knowing to
    phrase it as a superlative over rooms. A person who has never seen this building does
    not know that, and they are the people this has to serve.

    Guarded twice over: the question must carry BOTH a condition word and an existential
    scope, so "is there a cafe anywhere?" (no condition) and "is it raining?" (no scope)
    are untouched.
    """
    if c.intent not in _EXISTENTIAL_COMFORT_INTENTS:
        return None
    return "deliberate" if EXISTENTIAL_COMFORT_RE.search(c.query) else None


def _r_data_query_promotion(c: _Ctx) -> Optional[str]:
    """A value/reading question naming a place + measurable → sensor_data (post stage).

    Guard: a countable/structure/building-identity question is metadata, never
    demoted to a per-sensor reading.

    Second guard, same reasoning: a question about the INSTRUMENT is metadata too.
    "When was the CO2 sensor in Room 5.01 last calibrated?" names a place and a measurable,
    so `is_data_query` says yes and this promoted it straight back out of the lane the
    parse-stage rule had just put it in — the answer read "there is no record of a
    calibration event in this dataset" while the graph held 2025-11-17. The parse rule alone
    was not enough, and neither is this one alone: both halves are needed, the same shape
    as CAVEAT-324.
    """
    if c.intent not in ("metadata", "general", "capability", "general_knowledge"):
        return None
    if not c.sr.is_data_query(c.query):
        return None
    if _is_countable_meta(c.ql):
        return None
    if _METROLOGY_RE.search(c.query or ""):
        return None
    # "Which maintenance tasks are overdue?" names things that ARE recorded, and the register lane
    # has just been chosen for it: promoting it back to a reading lookup would undo that.
    if maintenance_record_question(c.query or ""):
        return None
    return "sensor_data"


def _r_building_not_general(c: _Ctx) -> Optional[str]:
    """A question about this building must never be answered open-domain (BUG-123).

    Runs in the ``concept`` stage — after lay-term resolution, which is the only
    signal that distinguishes "is it stuffy in RM157?" (a CO2 question about a
    real room) from "what is stuffiness?" (a vocabulary question). The keyword
    lists the earlier stages rely on cannot see it: "stuffy" is not a
    measurement word, so the reading question looks like small talk and reaches
    the open-domain answerer, which has no data and invents plausible values.
    """
    if c.intent not in ("general", "general_knowledge", "clarification", "greeting"):
        return None
    # "WHICH ROOM?" IS NOT AN OPEN-DOMAIN GUESS (BUG-735).
    #
    # This rule rescues a clarification the CLASSIFIER produced because it could not
    # ground the question. A clarification the system RAISED — because the question is
    # scoped to a room nobody has named — is the opposite: it is the grounded answer.
    # Converted to analytics it becomes exactly the failure it was raised to prevent:
    # "are CO2 and temperature back near this room's usual levels?" was answered by a
    # data lane with "that question reaches 296 sensors", about a question that names
    # one room and two measurands.
    #
    # It cannot read the marker the gate sets — the concept stage is handed a fresh
    # three-key dict — so it re-derives the condition from the query, using the same
    # detector the gate used. One definition, no second opinion.
    from orchestrator.services.referent_resolver import (
        detect_space_deixis,
        names_a_specific_space,
    )

    if (
        c.intent == "clarification"
        and detect_space_deixis(c.query)
        and not names_a_specific_space(c.query)
    ):
        return None
    from orchestrator.services.grounding_guard import is_building_specific

    if not is_building_specific(c.query, c.normalized.get("concepts")):
        return None
    return "analytics"


#: A question ABOUT a document rather than about the building's state. These name a measurand
#: and still belong in the capability lane: "what does the policy say about temperature?" wants
#: the policy, not a thermometer.
_DOCUMENTARY_RE = re.compile(
    r"\b(?:polic(?:y|ies)|manual|handbook|procedure|guidance|guideline|regulation|"
    r"standard|specification|documentation|say about|says about|stated in|written in|"
    r"according to)\b",
    re.IGNORECASE,
)

#: Shapes that want a COMPUTATION over a period rather than a current reading. Routed to
#: analytics so the answer is an average or a trend; sending these to sensor_data would return
#: one instantaneous value to a question about a week, which is a wrong answer that looks right.
#: A question asking whether something is WRONG with the readings, rather than what they are.
#:
#: Wider than ANOMALY_HISTORY_RE, which is about persisted episodes and deliberately does not
#: match "spike" — the word that sends "any energy spikes" to the detector. Kept separate
#: rather than widening that one: the history rule routes to the events store and matching
#: "spike" there would send a live-detection question to a log of past episodes.
_ANOMALY_SHAPE_RE = re.compile(
    r"\bspikes?\b|\bspiking\b|\banomal(?:y|ies|ous)\b|\boutliers?\b"
    r"|\bunusual\b|\babnormal\b|\berratic\b|\bout of range\b|\bmisbehav"
    r"|\bsomething wrong\b|\bfaulty\b|\bmisreading\b",
    re.IGNORECASE,
)

#: "is there a VOLTAGE fluctuation", "any RADON readings" — a question about a quantity,
#: written without the "can you measure…" verb the observability lane looks for.
_UNVERBED_QUANTITY_RE = re.compile(
    r"\b(?:is|are|any|the)\s+(?:there\s+)?(?:a|an|the)?\s*([a-z][a-z0-9 \-]{2,24}?)\s+"
    # "levels?" NOT FOLLOWED BY A NUMBER: "the Level 5 general waste" names a FLOOR, not a level of
    # something. Measured live (2D-06 wave 7): "Who is in charge of the Level 5 general waste?"
    # read "in charge of the" as a quantity and was answered "In Room 5.01 I can measure ...".
    r"(?:fluctuations?|spikes?|readings?|levels?(?!\s*\d)|measurements?|anomal(?:y|ies)|"
    r"concentrations?|values?)\b",
    re.IGNORECASE,
)

#: A question that asks WHO, WHEN DUE or WHAT STATE is about a record, never about a reading, and
#: must not be taken for a quantity question because a word like "level" sits in it.
_RECORD_ASK_RE = re.compile(
    r"\bin charge\b|\bwho\s+(?:owns|is\s+responsible|is\s+accountable|manages|looks after)\b"
    r"|\b(?:owner|responsible|accountable)\b|\bnext\s+due\b|\bdue\s+(?:date|for)\b"
    r"|\bwhen\s+is\b.{0,60}\bdue\b",
    re.IGNORECASE,
)

#: Words that fill the same slot but name no physical quantity, so they must not be reported
#: as "not measured here" — that would answer a question about the building's data with a
#: statement about a word.
_NOT_A_QUANTITY = frozenset(
    {
        "any",
        "these",
        "those",
        "some",
        "other",
        "such",
        "recent",
        "latest",
        "new",
        "current",
        "unusual",
        "abnormal",
        "high",
        "low",
        "sensor",
        "data",
        "same",
        "last",
        # determiners and prepositions: "in charge of THE level" captured a phrase, not a quantity
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "for",
        "to",
    }
)


def _r_unmeasured_quantity_is_reach(c: _Ctx) -> Optional[str]:
    """A question about a quantity this building does not measure -> the reach lane.

    "Is there a voltage fluctuation that could put our hardware at risk?" classified as
    general_knowledge, which answers from the model rather than from the building, and
    reached the anomaly lane's "No sensor data available for anomaly detection" when it
    reached anything — a sentence about the detector's input, not about the building.

    The building it was measured on has no voltage sensors at all. The honest answer is
    "voltage is not measured here", and the observability lane already renders exactly that,
    including what IS measured. Nothing new had to be written; the question never arrived.

    NARROW BY CONSTRUCTION. It fires only when a measurement-shaped question names a quantity
    AND the concept resolver found no measurand — so anything this building actually
    instruments has already been claimed by `capability_measurand_is_data` above, and a word
    that names no quantity at all is excluded outright. Being wrong here costs a reach answer
    to a question that deserved a data answer; being absent costs a confident non-answer.
    """
    if c.intent in {
        "observability",
        "control",
        "privacy_refusal",
        "clarification",
        "scope_boundary",
        "general_guidance",
    }:
        return None

    from orchestrator.services.grounding_guard import has_measurand_concept

    if has_measurand_concept(c.normalized.get("concepts")):
        return None  # the building measures it — an earlier rule owns this question
    if _RECORD_ASK_RE.search(c.ql or ""):
        return None  # who owns / when is it due: a record is asked for, not a reading

    match = _UNVERBED_QUANTITY_RE.search(c.ql)
    if not match:
        return None
    quantity = match.group(1).strip().lower()
    # Take the last word: "a sudden voltage fluctuation" names voltage, not "sudden".
    head = quantity.split()[-1] if quantity.split() else ""
    if not head or head in _NOT_A_QUANTITY:
        return None
    return "observability"


_AGGREGATE_SHAPE_RE = re.compile(
    r"\b(?:average|mean|median|total|sum|trend|typical|"
    r"over the (?:last|past)|during the (?:last|past)|this (?:week|month|term|year)|"
    r"last (?:week|month|term|year)|per (?:square|floor|room|day|week|hour)|"
    r"peak|minimum|maximum|distribution|breakdown|correlat)\b",
    re.IGNORECASE,
)


def _r_capability_measurand_is_data(c: _Ctx) -> Optional[str]:
    """A capability question naming something this building MEASURES -> a data lane (BUG-225).

    The capability lane absorbed 87% of the corpus and 88% of all measurement-shaped
    questions, so the building's connected sensors were unreachable by ordinary phrasing.

    Runs in the CONCEPT stage because the measurand test needs HBCO lay-term resolution --
    "stuffy" is a CO2 question and no keyword list available at parse time can know that.
    """
    if c.intent != "capability":
        return None

    from orchestrator.services.grounding_guard import has_measurand_concept

    if not has_measurand_concept(c.normalized.get("concepts")):
        return None
    # A question about what a document SAYS keeps its lane, even though it names a measurand.
    if _DOCUMENTARY_RE.search(c.ql):
        return None
    # A QUESTION WITH NOTHING TO READ KEEPS THE LANE THAT CAN ANSWER IT (measured live, twice).
    #
    # "What lux level is maintained for reading tasks?" resolves "lux" to an illuminance sensor and
    # "Which approved nearby space is suitable for a brief quiet pause?" resolves "quiet" to a sound
    # sensor, so this rule converted both to readings and the fetch refused them -- "that covers all
    # 268 illuminance sensors at once", "234 sound sensors". The first asks what the lighting is
    # DESIGNED to keep (the regimes record 300 lux); the second which spaces are approved (the
    # workspace register). Naming a measurand is not the same as asking for its value.
    #
    # `ungrounded_question.handoff` already owns both shapes and names the lane, so this returns it
    # rather than merely declining: the parse-stage rule cannot help here, because it fires only
    # from a fetch intent and the classifier had said `capability`.
    from orchestrator.services.ungrounded_question import handoff

    lane = handoff(c.query)
    if lane:
        return lane
    # And an EMERGENCY ACTION is never a reading, whatever its words resolve to: "what should I do
    # if the fire alarm goes off?" must reach the procedure the building authored (2026-09-19).
    from orchestrator.services.emergency_procedure import is_emergency_action_question

    if is_emergency_action_question(c.query):
        return None
    # "How many people can this building hold?" resolves "people" to an occupancy sensor, but asks
    # for a recorded CAPACITY, a fact about the building; converted to a reading it reached the
    # all-sensors fetch and was refused.
    from orchestrator.services.building_profile import detect_facet as _profile_facet

    if _profile_facet(c.query) == "capacity":
        return None
    # Provenance / verification / permission questions name a measurand in passing and are not
    # asking for its value.
    from orchestrator.services.governance_question import is_governance_question

    if is_governance_question(c.query):
        return None
    # A proactive-notice or "what can people do if ..." question names a measurand in passing.
    if _PROACTIVE_RE.search(c.query or "") or _WHAT_CAN_I_DO_IF_RE.search(c.query or ""):
        return None
    # "How many CO2 sensors are there?" is a census, not a reading. The existing guard owns
    # that distinction; reimplementing it here would give one decision two owners.
    if _is_countable_meta(c.ql):
        return None
    # A WHY-question about a measurand is a diagnosis, not a reading lookup, and the
    # diagnosis rule must get it. Rules stop at the first claim, and this one sits in an
    # earlier stage than `why_diagnosis` -- so without this guard EVERY "why is 5.01 stuffy?"
    # the LLM labels `capability` was converted to sensor_data here and the V5-T20 diagnosis
    # lane never ran. Measured live: the answer reported the CO2 mean and then guessed
    # ("ventilation is insufficient") while the AHU fan state and VAV damper position that
    # would have ANSWERED it sat connected and readable.
    #
    # Deliberately narrow: only why-questions move, and only to the lane already designed for
    # them. Everything else this rule was built for (BUG-225's 88% absorption) is untouched.
    from orchestrator.services.anomaly.diagnosis import (
        is_why_question,  # local: no cycle
    )

    if is_why_question(c.query):
        return None

    # "Is it stuffy ANYWHERE?" resolves a measurand through its lay term, so the test above
    # says yes — but the answer is a ranking across every room, not a reading (TODO-629).
    # Converted to a data lane it reached 274 sensors and returned the row-budget refusal:
    # honest, and useless to someone who cannot be expected to know which floor to ask
    # about. The parse-stage rule of the same name cannot catch this one, because the
    # capability intent is assigned AFTER that stage runs.
    if EXISTENTIAL_COMFORT_RE.search(c.query):
        return "deliberate"

    # An ANOMALY-shaped question goes to the detector, not to a reading lookup (BUG-395).
    #
    # This rule could previously return only `sensor_data` or `analytics`, so "any energy
    # spikes" — a capability-classified question naming a measurand this building
    # instruments — was converted to a reading lookup or left in capability, and the
    # detector was never reached. Measured live: it returned "I don't have that specific
    # information on record ... contact your facilities team" while all 8 energy sensors
    # were live and the scanner had found 24,317 spike findings that hour.
    #
    # No new rule and no change to the precedence order: this widens the LANE an existing
    # rule may choose. A new rule would have had to be placed relative to seventeen others,
    # and the file's own history is that placement is where routing goes wrong.
    if _ANOMALY_SHAPE_RE.search(c.ql):
        return "anomaly"
    return "analytics" if _AGGREGATE_SHAPE_RE.search(c.ql) else "sensor_data"


# Precedence order is the contract. Historical rules keep their historical order;
# the two automation-shape rules (2026-07-30) slot after the report-intake pair so
# genuine reports and comfort questions still win.
def _r_inference_privacy(c: _Ctx) -> Optional[str]:
    """Person-tracking / private-content / policy-override shapes → the
    privacy-refusal lane, FIRST — before clarification can ask 'which
    professor?' and before any data lane runs (V5-T42, traps P2xx/P5xx/P6xx).
    Fires from ANY intent: these denials are absolute in every profile."""
    from orchestrator.services.privacy.inference_classes import (  # local: no cycle
        classify_inference,
    )

    return "privacy_refusal" if classify_inference(c.query) else None


#: A hypothetical premise: the question posits a state the building is not in.
_HYPOTHETICAL_RE = re.compile(
    r"\bwhat if\b|\bwhat would happen\b|\bsuppose\b|\bassuming\b|\bhypothetical"
    r"|\bin the event (?:of|that)\b|\bwere (?:the|a|an|it)\b.{0,40}\bto (?:fail|stop|go)\b"
    r"|\bif (?:the|a|an|we|power|it|there)\b.{0,60}\b(?:fail|fails|failed|lost|lose|"
    r"were to|goes? (?:down|off)|stops?|stopped|breaks?|broke)\b",
    re.IGNORECASE,
)

#: ...and asks for its consequence. Both halves are required: "if you can, show me floor 3"
#: has a conditional and no consequence, and must keep its normal route.
_CONSEQUENCE_RE = re.compile(
    r"\bhow long\b|\bhow many\b|\bwould (?:it|they|we|the)\b|\bwill (?:it|they|we|the)\b"
    r"|\bimpact\b|\baffect(?:ed|s)?\b|\bconsequence|\bsafe for\b|\blast\b|\bsurvive\b"
    r"|\bcope\b|\bwithstand\b|\bhappen\b",
    re.IGNORECASE,
)


def scenario_question(query: str) -> bool:
    """True when a question asks the building to SIMULATE a state it is not in.

    Both a hypothetical premise and a request for its consequence are required. One
    without the other is ordinary language — "if you can, show me floor 3" is a
    conditional with no consequence, and "how long does the lift take" is a consequence
    with no hypothetical.
    """
    text = query or ""
    return bool(_HYPOTHETICAL_RE.search(text) and _CONSEQUENCE_RE.search(text))


def _r_answer_provenance(c: _Ctx) -> Optional[str]:
    """ "How do you know that?" -> capability, which reads the evidence record (V7-T74).

    Runs early, because these questions are about the previous ANSWER and every data lane
    would otherwise try to answer them as if they were about the building. Measured: "how
    do you know that?" was classified as a question about the system's own capabilities,
    and an auditor's "can every extraction and join be rerun from authorised inputs?" got
    a document search — while the record that answers both sat in the previous turn.
    """
    from orchestrator.services.answer_provenance import is_provenance_question

    return "capability" if is_provenance_question(c.query) else None


def _r_scenario_boundary(c: _Ctx) -> Optional[str]:
    """What-if questions → capability, which declines and names what is missing (V7-T80).

    The building holds no thermal, hydraulic or electrical model, so "if power fails, how
    long do the lab freezers stay safe?" has no grounded answer — and the model WILL
    produce a confident one from physical intuition if allowed to, which is the most
    dangerous answer this system could give. Deciding it here, before any data lane runs,
    keeps a plausible number from ever being computed.

    The decline names what a real answer would require, so it is a specification rather
    than a refusal.
    """
    return "capability" if scenario_question(c.query) else None


#: A question about the INSTRUMENT rather than about its readings.
#:
#: These properties live in the graph — ontosage:calibratedOn, calibrationDueOn,
#: samplingIntervalS, archivalIntervalS — and 2,728 sensors now carry them. The data lanes
#: read time-series rows and cannot see any of it, which produced three wrong answers on the
#: day the metrology landed:
#:
#:   "When was the CO2 sensor in Room 5.01 last calibrated?"
#:     -> analytics: "No calibration record found" — the graph says 2025-11-17.
#:   "How often does a CO2 sensor report?"
#:     -> sensor_data: "every 30 seconds", inferred from the spacing of the rows it
#:        happened to fetch. The declared interval is 60.
#:
#: The first is the serious one: a confident false negative about data the building holds,
#: which is exactly what contract 4 forbids. Both are the same mistake — measuring the
#: readings to answer a question about the instrument that produced them.
_METROLOGY_RE = re.compile(
    r"\bcalibrat\w*"
    r"|\bre-?calibrat\w*"
    r"|\bsampling\s+(?:interval|rate|period)"
    r"|\b(?:archival|reporting|logging|recording)\s+interval"
    r"|\bhow\s+often\s+(?:does|do|is|are)\b[^?]*\b(?:report|reports|sample|samples|"
    r"log|logs|record|records|update|updates)\b",
    re.IGNORECASE,
)

#: Lanes this rule may claim from. Deliberately NOT every intent: a register question that
#: already routed to metadata, a capability decline, or a report intake must keep its route.
#: Only the lanes that answer from time-series rows are taken, because those are the ones
#: that cannot see a calibration date however hard they look.
_METROLOGY_TAKES_FROM = (
    "sensor_data",
    "analytics",
    "trend",
    "compare",
    "general",
    "general_knowledge",
    "",
)


def _r_instrument_metrology(c: _Ctx) -> Optional[str]:
    """Calibration and cadence describe the instrument, not the measurement (BUG-427)."""
    if c.intent not in _METROLOGY_TAKES_FROM:
        return None
    return "metadata" if _METROLOGY_RE.search(c.query or "") else None


#: "Is this room ready for what is about to happen in it?"
#:
#: Distinct from every register that holds part of the answer. The AV register knows the
#: technology, the workspace register the network, the timetable when the session is — and a
#: question routed to any ONE of them gets that third of the answer with no date on it. The
#: readiness lane joins them and puts a source and a timestamp on every line.
#:
#: Deliberately narrow. "Is the projector working?" is an AV register question and stays
#: one; this fires on the shape that means *before something happens here*.
#: What a space is made ready FOR. The readiness lane joins the timetable, the AV
#: register, the network survey and the setup time — every one of those is about a
#: room being USED BY PEOPLE for a booked occasion.
_READINESS_OCCASION = (
    r"class|lecture|seminar|session|lesson|teaching|meeting|tutorial|workshop|exam|"
    r"practical|presentation|talk|lab|event|booking|students?|use"
)

_READINESS_RE = re.compile(
    r"\breadiness\s+check"
    # "ready for the next confirmed collection" is not a readiness check (C19). The
    # branch below used to accept ANY object after "ready for the", so a waste
    # exchange area awaiting a lorry reached the lane that reports what a room's
    # teaching technology last tested at — a lane that then asked which room to
    # check, about a question that was never about a teaching room. Naming the
    # occasions this lane can actually evidence keeps it honest, and costs nothing:
    # every phrasing it was built for names one.
    r"|\bready\s+for\s+(?:my|the|a|this|our|its)?\s*(?:next\s+|first\s+|\w+\s+){0,2}"
    r"(?:" + _READINESS_OCCASION + r")\b"
    r"|\b(?:before|ahead\s+of)\s+(?:my|the|our|each)\s+"
    r"(?:class|lecture|seminar|session|lesson|teaching|meeting)\b"
    r"|\bis\s+\S+\s+set\s+up\s+for\b"
    r"|\bwhat\s+should\s+i\s+know\s+before\s+(?:teaching|using|the)\b",
    re.IGNORECASE,
)

#: Lanes a readiness question may be taken from. A register route is included on purpose:
#: the AV register legitimately matches "ready", answers a third of the question and dates
#: none of it, and that partial answer is what this lane exists to replace.
_READINESS_TAKES_FROM = (
    "metadata",
    "capability",
    "sensor_data",
    "asset_state",
    "observability",
    "general",
    "general_knowledge",
    "",
)


def _r_readiness_check(c: _Ctx) -> Optional[str]:
    """A question about a space before it is used -> the readiness lane."""
    if c.intent not in _READINESS_TAKES_FROM:
        return None
    return "readiness_check" if _READINESS_RE.search(c.query or "") else None


#: A question about WHEN something was last serviced, or WHAT is overdue for maintenance. Three
#: questions from the 2026-09-18 hand reads -- "When was the lift last serviced?", "Which assets are
#: overdue for maintenance?", "Which maintenance tasks are overdue?" -- landed in the capability
#: lane, the metadata fallback or the maintenance intent (which files or lists TICKETS), while the
#: building holds them as dated records: a work-order log, an asset engineering register, service and
#: cleaning schedules. A dated register is answered by the register lane, which projects the answer
#: from the rows.
#:
#: "inspected", "tested" and "checked" ARE here for generic equipment ("when was chiller 7 last
#: inspected?"), and the dated COMPLIANCE items ("when was the fire alarm last tested?", "which
#: inspections are overdue?") still reach their own register lane: `compliance_register` runs first
#: and this rule takes nothing from the `register` intent it produces.
#:
#: "when" counts only as the QUESTION word ("when was ...", "when did ..."): "what information must
#: be retained WHEN an asset is replaced" and "requirements that may change WHEN an asset is
#: modified" contain the same verbs and ask nothing about the last service (measured: the first
#: draft moved three such catalogue questions).
#: A period close enough that the asker means a SCHEDULE, not a policy about schedules.
_NEAR_PERIOD = (
    r"(?:today|tomorrow|tonight|this\s+(?:week|month|morning|afternoon)|next\s+(?:week|month)|now)"
)

MAINTENANCE_RECORD_RE = re.compile(
    r"\bwhen\s+(?:was|were|did|has|have)\b[^?.!]{0,50}"
    r"\b(?:serviced|maintained|repaired|overhauled|inspected|cleaned|replaced)\b"
    r"|\b(?:what|which)\s+date\b[^?.!]{0,60}"
    r"\b(?:serviced|maintained|repaired|overhauled|inspected|cleaned|replaced)\b"
    r"|\bhow\s+long\s+ago\b[^?.!]{0,60}"
    r"\b(?:serviced|maintained|repaired|overhauled|inspected|cleaned|replaced)\b"
    r"|\blast\s+(?:serviced|maintained|repaired|overhauled|replaced|servicing|maintenance|"
    r"service|inspected|cleaned)\b"
    r"|\boverdue\b[^?.!]{0,30}\b(?:for\s+)?(?:maintenance|servicing|service|repairs?|cleaning|"
    r"replacement)\b"
    r"|\b(?:maintenance|servicing|repair|cleaning)\s+(?:tasks?|jobs?|work|items?|visits?)\b"
    r"[^?.!]{0,40}\b(?:overdue|outstanding|late|behind|lapsed|missed)\b"
    r"|\b(?:overdue|outstanding|late|missed)\s+(?:maintenance|servicing|repairs?|cleaning)\b"
    r"|\b(?:repairs?|maintenance|servicing)\b[^?.!]{0,20}\b(?:overdue|outstanding|lapsed)\b"
    # "are there any maintenance tasks scheduled for today?" — the service schedules and the work
    # orders hold exactly this, and the events lane (which has no kind for it) answered "this
    # building doesn't keep a record of that" (live, 2026-09-19). A NEAR period is required, so
    # "are planned maintenance tasks aligned with each asset type?" — a policy question — is not
    # claimed.
    r"|\b(?:maintenance|servicing|inspection|cleaning|repair)\s+(?:(?:tasks?|jobs?|work|visits?|"
    rf"items?|activities|activity)\s+)?[^?.!]{{0,40}}?\b(?:scheduled|planned|due|booked|coming\s+up)\b"
    rf"[^?.!]{{0,25}}\b{_NEAR_PERIOD}\b"
    rf"|\bwhat\s+(?:maintenance|servicing|cleaning|inspections?)\b[^?.!]{{0,30}}"
    rf"\b(?:scheduled|planned|due|on)\b[^?.!]{{0,25}}\b{_NEAR_PERIOD}\b"
    rf"|\b(?:scheduled|planned)\s+(?:maintenance|servicing|inspections?)\b[^?.!]{{0,25}}"
    rf"\b{_NEAR_PERIOD}\b",
    re.IGNORECASE,
)

#: Work orders and tickets are the events lane's own (`workorder_summary`), not a register's.
_TICKET_WORDS_RE = re.compile(r"\b(?:work\s*orders?|tickets?)\b", re.IGNORECASE)


def maintenance_record_question(query: str) -> bool:
    """True for a QUESTION about when something was last serviced or what is overdue for upkeep.

    Public because the dialogue agent's capability probe returns before classification, and so
    before any contract rule: "when was the lift last serviced?" matches the lift amenity's lay
    terms and was answered from prose. One definition, used by the rule and by that bypass.
    """
    q = query or ""
    if not q.strip() or _TICKET_WORDS_RE.search(q):
        return False
    if not (_INTERROGATIVE_RE.search(q) or q.rstrip().endswith("?")):
        return False  # "the lift is overdue for maintenance" is a statement: intake owns it
    return bool(MAINTENANCE_RECORD_RE.search(q))


def _r_maintenance_record_is_a_register_question(c: _Ctx) -> Optional[str]:
    """ "When was the lift last serviced?" / "which tasks are overdue?" -> the register lane.

    The register lane is the `metadata` route: with a held record class it answers from that
    register's rows (a work-order log, an asset engineering register, service and cleaning
    schedules). Comes AFTER `maintenance_schedule` and `history_question_not_report`, whose labels
    (`maintenance`, `capability`) it corrects, and after `compliance_register`, whose dated
    compliance items it must not take: it claims nothing from `register`, `events` or `asset_state`.
    """
    if c.intent not in (
        "maintenance",
        "capability",
        "general",
        "general_knowledge",
        "clarification",
        "discovery",
        "metadata",
        # `events` is claimable (2026-09-19): "are there any maintenance task scheduled for today?"
        # was classified `events`, and that lane has no kind for a maintenance schedule at all, so
        # it answered "this building doesn't keep a record of that" while the service schedules and
        # the work orders hold it. This rule runs AFTER event_store_query, so it survives it.
        "events",
        None,
    ):
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None  # a fault statement files a ticket; a command is declined
    return "metadata" if maintenance_record_question(c.query) else None


#: "Is the temperature the same across the space?" — a question about SPREAD, not about a value.
#: Live 2026-09-19 it reached the reading lane and was refused as covering 296 temperature sensors,
#: while the per-floor comparison answers it in one line ("the spread across floors is 0.4 C").
_UNIFORMITY_RE = re.compile(
    r"\b(?:the\s+)?same\s+(?:every|through|across|all\s+over|in\s+(?:all|every))"
    r"|\b(?:consistent|uniform|even|equal|balanced)\s+(?:across|through(?:out)?|between|"
    r"in\s+(?:all|every)|everywhere)\b"
    r"|\b(?:vary|varies|varying|differ|differs|different)\s+(?:much\s+)?"
    r"(?:across|between|from\s+(?:floor|room|zone))\b"
    r"|\bevenly\s+(?:distributed|spread|balanced)\b"
    r"|\b(?:spread|variation|difference)\s+(?:across|between)\s+(?:the\s+)?"
    r"(?:floors?|rooms?|zones?|spaces?|building)\b",
    re.IGNORECASE,
)

#: A uniformity question about ONE named room is a question about that room, and the reading lane
#: handles it; the comparison is across the building's places.
_NAMES_ONE_PLACE_RE = re.compile(
    r"\b(?:room|rm|zone|level|floor)\s*[\d.]+|\b\d{1,2}\.\d{1,3}\b", re.I
)


def uniformity_question(query: str) -> bool:
    """True when the question asks whether a measured quantity is EVEN across the building."""
    q = query or ""
    if not _UNIFORMITY_RE.search(q) or _NAMES_ONE_PLACE_RE.search(q):
        return False
    return _any(q.lower(), SENSOR_METRIC_KWS) or _any(q.lower(), COMFORT_SIGNAL_KWS)


_REPORT_INTENTS = ("safety_report", "maintenance", "complaint")


def _r_a_report_needs_a_statement(c: _Ctx) -> Optional[str]:
    """A hedged question is not a report: it asks, it does not file (2026-09-19, SERIOUS).

    *"if the building are safe or not"* was classified `safety_report` and the intake node filed a
    HIGH-PRIORITY ticket (REP-051956, "An administrator has been notified"). The message names no
    place, no hazard and no fault: nobody reported anything, and someone was sent to look for a
    problem that was never described.

    Two cases, decided by `report_statement`:

    * the classifier said a REPORT intent and the message is hedged and states nothing (no fault, no
      hazard, no place) -> a clarification, never a ticket. Asymmetric on purpose: anything that
      names a thing, a place or a fault keeps filing, because a missed hazard costs more than a
      bogus ticket;
    * the classifier said anything else and the message asks for a VERDICT on the whole building
      ("is the building safe?") -> the same clarification, which says what the records can show
      (overdue checks, defective equipment) instead of a lane that cannot answer "safe".

    Late in the parse stage, so nothing after it can re-label a clarification it produced.
    """
    from orchestrator.services.report_statement import (
        clarification_for,
        is_building_verdict_request,
    )

    if c.intent in _REPORT_INTENTS:
        text = clarification_for(c.query)
        if text:
            c.normalized["clarification_question"] = text
            return "clarification"
        # (A question that states no fault is refused FILING by the intake node itself, which
        # answers it from the records; moving it here shifted ~2,000 synthetic-label rows, so the
        # contract deliberately leaves it.)
        return None
    if c.intent in _WEAK_INTENTS + (
        "sensor_data",
        "analytics",
        "compliance",
        "recommend",
        "observability",
        "trend",
        "compare",
        "anomaly",
    ):
        if is_building_verdict_request(c.query):
            from orchestrator.services.report_statement import reply_for

            c.normalized["clarification_question"] = reply_for(c.query)
            return "clarification"
    return None


def _r_emergency_action_is_a_procedure(c: _Ctx) -> Optional[str]:
    """ "What should I do if the fire alarm goes off?" -> the procedure, never an asset register.

    Live 2026-09-19, and the worst kind of wrong answer this system can give: the fire-safety asset
    register matched on "fire alarm" and replied "1 of the 30 records matches: FSA-001 — Fire alarm
    control panel", to a person asking what to do while an alarm sounds. The building's own
    evacuation text answers it — leave by the nearest marked exit, do not use the lifts, assemble
    outside, report to the floor warden — and the capability lane reads it.

    Claims from `register`/`metadata` as well as the weak intents, because the register is exactly
    where this goes wrong, and runs late so a register rule cannot take it back. A question about
    the EQUIPMENT ("which fire doors are overdue a test?") is excluded by the shape test itself.
    """
    if c.intent in ("maintenance", "complaint", "safety_report", "report", "control"):
        return None  # reporting a fire is not asking what to do about one
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    from orchestrator.services.emergency_procedure import is_emergency_action_question

    return "capability" if is_emergency_action_question(c.query) else None


def _r_uniformity_is_a_comparison(c: _Ctx) -> Optional[str]:
    """ "Is the temperature the same across the space?" -> the per-floor comparison.

    Asked as a reading it reaches every sensor of that quantity and is refused as too wide (296
    temperature sensors, live 2026-09-19). It is not a request for a value at all: the answer is a
    SPREAD, which the comparison lane computes per floor from aggregates and states in one line.

    Narrow by construction: a uniformity phrase AND a measurable quantity, and never when one place
    is named — "is the temperature the same across Room 5.01?" is about that room.
    """
    if c.intent not in _WEAK_INTENTS + (
        "sensor_data",
        "analytics",
        "trend",
        "compliance",
        "anomaly",
    ):
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    return "compare" if uniformity_question(c.query) else None


def _r_time_pattern_is_not_a_ranking(c: _Ctx) -> Optional[str]:
    """ "When is the atrium busiest?" asks for a TIME, so it is a series over history (BUG-828).

    Both runs of tail B row B12 answered it from the deliberation lane — "Best match: Room 3.48 -
    Academic Office ... occupancy: 13.867" — a ranking of rooms by CURRENT occupancy that named a
    room, and not the one asked about. "Busiest" sits in DELIBERATE_RE because "which room is the
    busiest?" is a ranking; what separates the two questions is the dimension asked for, decided
    by `temporal_pattern.asks_time_pattern`.

    Claims only from `deliberate`, where the wrong answer was produced, and only after the two
    deliberate rules above have had their say (this contract is last-wins), so every question
    that reaches ARBITER by a superlative first arrives here already labelled and is judged on
    its shape. `trend` is the lane for how a metric varies over time; its analytics node already
    summarises readings by period for a question containing "busiest".
    """
    if c.intent != "deliberate":
        return None
    from orchestrator.services.temporal_pattern import asks_time_pattern

    return "trend" if asks_time_pattern(c.query) else None


#: Intents a request outside the building's scope is observed to land in: the classifier's guess
#: for "what's the weather forecast?" was `clarification` ("which city?") and, once a metric word
#: was present, `trend` (a forecast of a sensor that has no forecast to give).
_SCOPE_TAKES_FROM = _WEAK_INTENTS + ("trend", "analytics", "sensor_data", "recommend")


def _r_scope_boundary(c: _Ctx) -> Optional[str]:
    """A request the assistant cannot ground or should not advise on -> a brief scope statement.

    "What's the weather forecast for tomorrow?" asked which city (BUG-812, F39) and "Should I buy
    Bitcoin?" answered with investment guidance from general model knowledge (F40). The policy
    lives in `scope_policy`: only those two shapes are claimed; a definition, a joke and a data
    forecast keep their lanes. Last in the contract, and from a deliberately narrow set, so it can
    never take a question a data lane has already claimed for a reason of its own.
    """
    from orchestrator.services.scope_policy import KIND_TRANSACTION, out_of_scope_kind

    kind = out_of_scope_kind(c.query)
    if not kind:
        return None
    # "Can you make reservations in the cafe?" lands in events/control (it names bookings, or a verb
    # of acting); asking the ASSISTANT to transact is a scope statement, whichever label it got.
    _EXTRA = {
        KIND_TRANSACTION: ("events", "control"),
        # These three are declines of a shape no lane can answer, whichever lane the classifier
        # picked (wave 9): a fault timeline arrives as diagnosis or anomaly, a personal itinerary as
        # recommend or spatial, a distance comparison as spatial or floor_plan.
        "fault_timeline": ("diagnosis", "anomaly", "compliance", "events", "observability"),
        "personal_record": ("spatial_query", "floor_plan", "events", "metadata"),
        "distance_comparison": ("spatial_query", "floor_plan", "metadata", "discovery"),
    }
    takes = _SCOPE_TAKES_FROM + _EXTRA.get(kind, ())
    if c.intent not in takes:
        return None
    if kind != KIND_TRANSACTION and c.sr is not None and c.sr.is_control_command(c.query):
        return None
    return "scope_boundary"


#: Intents a building-knowledge question is observed to land in. `recommend` and `analytics` lead:
#: "how do I control CO2?" reads as advice, "does humidity affect CO2 sensor accuracy?" as an
#: analysis, and both then met the sensor fetch and were refused with "that question reaches N
#: sensors". `control` is included because "control CO2" contains the word; the command test below
#: keeps a genuine request out.
_GUIDANCE_TAKES_FROM = _WEAK_INTENTS + (
    "recommend",
    "analytics",
    "sensor_data",
    "compliance",
    "compare",
    "trend",
    "observability",
    "anomaly",
    "control",
)


def _r_ungrounded_never_fetches(c: _Ctx) -> Optional[str]:
    """A question with nothing for a sensor read to be about must not reach the fetch.

    Measured live 2026-09-19. *"What lux level is maintained for reading tasks?"* and *"Which
    approved nearby space is suitable for a brief quiet pause before my next appointment?"* were
    classified `sensor_data` and answered "that question reaches 268 sensors -- more than I can read
    row by row", with the advice to name a floor or a room. Neither question is about a reading at
    all: the first asks the level the lighting is DESIGNED to keep, the second which spaces are
    approved and suitable. No narrowing the reader could do would have helped.

    `ungrounded_question` decides both shapes and the lane each goes to, and it yields the moment
    the question names a room, a floor, a time window or a record -- then the asker wants THIS
    building's readings and the data lanes keep it.
    """
    from orchestrator.services.ungrounded_question import FETCH_INTENTS, handoff

    if c.intent not in FETCH_INTENTS:
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    return handoff(c.query)


def _r_general_guidance(c: _Ctx) -> Optional[str]:
    """A building-knowledge question that needs no building data -> labelled general guidance.

    Owner policy 2026-09-19 ("answer MORE, honestly"): "does humidity affect CO2 sensor
    accuracy?", "how do I control CO2?", "how do BREEAM and LEED differ?" and "what does a delta-T
    mean?" ask for knowledge, not a reading. Through the data pipeline they were refused as "that
    question reaches N sensors"; from the building's records they would be invented. They are
    answered as general guidance, labelled as not from this building's records
    (`general_guidance.py`), and never reach the sensor fetch.

    The shape test is `guidance_shape.is_general_guidance_question`, deliberately conservative: a
    guidance frame AND a building-domain term AND no grounding (no place, time window, "this/our
    building", record kind or sensor id). A command and a fault statement are excluded here as
    well, so "can you reduce the temperature?" and "the heating is broken" keep their lanes.
    """
    if c.intent not in _GUIDANCE_TAKES_FROM:
        return None
    if c.sr is not None and (
        c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query)
    ):
        return None
    from orchestrator.services.guidance_shape import is_general_guidance_question

    return "general_guidance" if is_general_guidance_question(c.query) else None


#: What a REPORT request says, and what a PLANNER request says. A question with neither is a
#: question: "Which full-day cohort patterns lack an authorised usable meal or rest break?" was
#: labelled `report` and answered "No data was retrieved for this request, so there is no report to
#: give" after 158 s of fetching; "A lift is officially unavailable. Which bookings no longer have a
#: verified route?" was labelled `planner` and got the same sentence after 47 s.
_REPORT_SHAPE_RE = re.compile(
    r"\b(?:report|summary|summari[sz]e|breakdown|overview|write[- ]?up|digest|briefing)\b",
    re.IGNORECASE,
)
_PLANNER_SHAPE_RE = re.compile(
    r"\bthen\b|\bafter\s+that\b|\bfollowed\s+by\b|\bstep[- ]by[- ]step\b|\bplan\b|"
    r"\band\s+(?:also\s+)?(?:export|plot|chart|graph|email|send|save|download|forecast|visuali[sz]e)\b|"
    r"\bmake\s+(?:the|this|our)\s+building\b|\beco[- ]?friendly\b|\bsustainab\w*|\bnet[- ]zero\b|"
    r"\bmandate\b|\bgoals?\b|\bstrategy\b",
    re.IGNORECASE,
)


#: A WISH, not a request: "it would be nice for the system to adjust the lighting". Nothing is being
#: ordered, so the control lane's "this service cannot operate equipment ... setpoints" list answers
#: a question nobody asked (tail H, 2026-09-20). It is a suggestion, which is acknowledged and logged.
_WISH_RE = re.compile(
    r"\b(?:it\s+would\s+be|it'?d\s+be|would\s+be)\s+(?:very\s+|really\s+|so\s+)?(?:nice|great|good|"
    r"helpful|useful|handy|better)\b|\bi\s+wish\b|\bwould\s+love\s+(?:it\s+)?(?:if|for)\b|"
    r"\bi'?d\s+(?:like|love)\s+(?:it\s+)?(?:if|for)\b|\bit\s+would\s+help\s+if\b",
    re.IGNORECASE,
)


def _r_wish_is_a_suggestion(c: _Ctx) -> Optional[str]:
    """A stated wish about what the system could do is a suggestion, not a control request."""
    if c.intent not in _WEAK_INTENTS + (
        "control",
        "recommend",
        "sensor_data",
        "analytics",
        "automation_capability",
    ):
        return None
    # "is there a way to notify the lighting system that this is occurring?" is a wish put as a
    # question, addressed to a system that does not exist yet: a suggestion (tail J, 2026-09-20).
    if _WAY_TO_TELL_A_SYSTEM_RE.search(c.query or ""):
        return "suggestion"
    if not _WISH_RE.search(c.query or ""):
        return None
    if _INTERROGATIVE_RE.search(c.query or "") and "?" in (c.query or ""):
        return None  # "would it be nice to know..." asked as a question
    return "suggestion"


_WAY_TO_TELL_A_SYSTEM_RE = re.compile(
    r"\bis\s+there\s+a\s+way\s+(?:to|for\s+\w+\s+to)\s+(?:notify|tell|let|inform|signal|alert|make|"
    r"get|have)\s+(?:the\s+|my\s+|our\s+)?(?:lighting|lights?|hvac|heating|cooling|ventilation|"
    r"blinds?|screen|projector|air\s+con\w*)\b",
    re.IGNORECASE,
)

#: What can I AUTOMATE? A question about the building's automation capability, answered by the
#: automation lane ("alerts on measured quantities; no actuation beyond the writable setpoints").
_WHAT_TO_AUTOMATE_RE = re.compile(
    r"\bwhat\s+(?:(?:kinds?|types?|sorts?)\s+of\s+)?(?:tasks?|things|jobs|actions|processes|rules)"
    r"\s+(?:can|could|might)\s+(?:i|we|you|one)\s+(?:automate|set\s+up)\b"
    r"|\bwhat\s+(?:can|could)\s+(?:i|we|one)\s+automate\b"
    r"|\bwhat\s+(?:can|could)\s+(?:the\s+)?(?:building|system)\s+(?:do\s+)?"
    r"(?:automatically|on\s+its\s+own|by\s+itself)\b",
    re.IGNORECASE,
)

#: "could the building proactively notice ... and offer ...?": it does not act on its own
#: initiative, which the capability lane says honestly.
_PROACTIVE_RE = re.compile(
    r"\b(?:could|can|would|will|does|do)\s+(?:the\s+)?(?:building|system|it|you)\s+"
    r"(?:proactively\s+\w+|(?:automatically|on\s+its\s+own|by\s+itself)\s+"
    r"(?:notice|suggest|offer|recommend|advise|realis\w+|realiz\w+))",
    re.IGNORECASE,
)

#: "what can people do if they don't like ...?": a PROCEDURE question, answered from the building's
#: own arrangements (who to ask, what needs approval), never with advice about supply air.
_WHAT_CAN_I_DO_IF_RE = re.compile(
    r"^\s*what\s+(?:can|could|should|do|would)\s+(?:people|occupants|users|staff|students|"
    r"visitors|i|we|one)\s+do\s+(?:if|when|about)\b"
    r"(?!.*\b(?:fire|smoke|gas|flood\w*|injur\w*|emergency|alarm|trapped|co2|high|low)\b)",
    re.IGNORECASE,
)

#: A polite request to CHANGE the environment: "can you reduce noise in this workspace?"
_ENV_REQUEST_RE = re.compile(
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:reduce|lower|cut|quieten|quiet|dim|"
    r"brighten|warm|cool|heat|ventilate|increase|raise|decrease|adjust|change)\s+"
    r"(?:the\s+|this\s+|my\s+|our\s+|some\s+)?(?:noise|temperature|heat|lights?|lighting|air|"
    r"humidity|ventilation|draught|glare|brightness|sound|volume|music|smell|odou?r)\b",
    re.IGNORECASE,
)

#: "Is MY office warmer than comparable offices?": a comparison against a reference set the
#: question never names. Which office?
_COMPARABLE_PLACES_RE = re.compile(
    r"\b(?:is|are)\s+(?:my|our)\s+\w+(?:\s+\w+)?\s+(?:significantly\s+|much\s+|noticeably\s+|any\s+)?"
    r"(?:warmer|cooler|hotter|colder|noisier|quieter|brighter|darker|more\s+\w+|less\s+\w+)\s+"
    r"than\s+(?:the\s+)?(?:comparable|similar|other|typical|average|neighbouring|nearby)\b",
    re.IGNORECASE,
)


def _r_what_to_automate(c: _Ctx) -> Optional[str]:
    """'What kind of tasks can I automate?' -> the automation-capability lane."""
    if c.intent in ("control", "alert") or c.sr.is_control_command(c.query):
        return None
    return "automation_capability" if _WHAT_TO_AUTOMATE_RE.search(c.query or "") else None


def _r_proactive_or_procedure_is_capability(c: _Ctx) -> Optional[str]:
    """Proactive-notice and 'what can people do if ...' questions -> capability (documents)."""
    if c.intent not in _WEAK_INTENTS + (
        "recommend",
        "sensor_data",
        "analytics",
        "automation_capability",
        "alert",
        "compare",
        "trend",
    ):
        return None
    if c.intent == "capability":
        return None
    if c.sr.is_control_command(c.query):
        return None
    q = c.query or ""
    if _PROACTIVE_RE.search(q) or _WHAT_CAN_I_DO_IF_RE.search(q):
        return "capability"
    return None


def _r_environment_request(c: _Ctx) -> Optional[str]:
    """'Can you reduce noise in this workspace?' -> control, which declines with what it can do."""
    if c.intent not in _WEAK_INTENTS + ("recommend", "sensor_data", "analytics", "compare"):
        return None
    return "control" if _ENV_REQUEST_RE.search(c.query or "") else None


def _r_place_vs_comparable_places(c: _Ctx) -> Optional[str]:
    """'Is my office warmer than comparable offices?' names no office -> ask which one."""
    # Any data label: the classifier says compare, deliberate, anomaly or analytics for this shape.
    if c.intent in ("control", "suggestion", "scope_boundary", "general_guidance"):
        return None
    q = c.query or ""
    if not _COMPARABLE_PLACES_RE.search(q) or re.search(
        r"\b\d{1,2}\.\d{1,3}\b|\b(?:room|floor)\s*\d", q, re.I
    ):
        return None
    # The classifier often says `clarification` already, so no intent CHANGES and the rule is not
    # recorded; this flag is what stops the document probe from flipping it back to capability.
    c.normalized["clarification_locked"] = True
    c.normalized["clarification_question"] = (
        'Which office do you mean? "My office" doesn\'t tell me which room to look at, and '
        '"comparable offices" needs a reference set. Give me the room number (for example '
        "*is room 2.14 warmer than the other rooms on its floor today?*) and I will compare its "
        "temperature with them."
    )
    return "clarification"


def _r_governance_question(c: _Ctx) -> Optional[str]:
    """Provenance, verification, permission and 'is an assessment required' -> the documents."""
    from orchestrator.services.governance_question import is_governance_question

    if c.intent not in _WEAK_INTENTS + (
        "sensor_data",
        "analytics",
        "recommend",
        "compare",
        "trend",
        "anomaly",
        "compliance",
        "discovery",
        "events",
        "observability",
        "maintenance",
        "complaint",
    ):
        return None
    if c.intent == "capability" or not is_governance_question(c.query):
        return None
    if _METROLOGY_RE.search(c.query or ""):
        return None  # a calibration question keeps the metrology lane (instrument_metrology)
    if c.sr.is_control_command(c.query):
        return None
    return "capability"


def _r_report_or_planner_needs_its_shape(c: _Ctx) -> Optional[str]:
    """A QUESTION labelled report or planner that asks for neither -> capability, never a fetch.

    Only interrogatives move: a fault statement the classifier called `report` is intake's (see
    `_r_event_store_query`, BUG-200), and a mandate ("make the building eco-friendly") keeps the
    planner. Runs FIRST so every later rule sees the corrected label: the bookings question then
    reaches the events rule and the register questions reach whichever lane claims them.
    """
    if c.intent not in ("report", "planner"):
        return None
    if not _INTERROGATIVE_RE.search(c.query or ""):
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    shape = _REPORT_SHAPE_RE if c.intent == "report" else _PLANNER_SHAPE_RE
    if shape.search(c.query or "") or (
        c.intent == "planner" and _REPORT_SHAPE_RE.search(c.query or "")
    ):
        return None
    # A question that names something MEASURED is a data question wearing the wrong label.
    if _any(c.ql, SENSOR_METRIC_KWS):
        return "sensor_data"
    return "capability"


PARSE_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "answer_provenance",
        "how do you know that / can it be rerun -> capability, reading the evidence record (V7-T74)",
        _r_answer_provenance,
    ),
    Rule(
        "scenario_boundary",
        "what-if / simulate-a-state questions -> capability, which declines (V7-T80)",
        _r_scenario_boundary,
    ),
    Rule(
        "inference_privacy_denial",
        "individual presence/pattern/private-content/override shapes → refusal (V5-T42)",
        _r_inference_privacy,
    ),
    Rule(
        "report_or_planner_needs_its_shape",
        "a question labelled report/planner that asks for neither a document nor a multi-step job "
        "-> capability, so it is answered from records instead of fetching for a report",
        _r_report_or_planner_needs_its_shape,
    ),
    Rule(
        "compare_two_referents",
        "comparison keywords + ≥2 entities/floors → compare (never compliance/analytics)",
        _r_compare,
    ),
    Rule(
        "sensor_trend_not_compliance",
        "explicit sensor id + trend window → analytics (historical), not compliance",
        _r_sensor_trend,
        sets_analytics=True,
    ),
    Rule(
        "vague_complaint_clarify",
        "vague 'fix everything' with no control target → clarification, not control",
        _r_vague_complaint,
        extras=_vague_complaint_extras,
    ),
    Rule(
        "plan_around_my_own_commitments",
        "'plan my day around my classes' → clarification: no record says which sessions "
        "are the asker's, and a plan that guesses is wrong in a way nobody can see "
        "(BUG-716 family, run-3 row 90). Beside vague_complaint_clarify, its sibling: "
        "both hand back a question rather than answer a different one",
        _r_plan_around_my_own_commitments,
        extras=_plan_around_my_own_commitments_extras,
    ),
    Rule(
        "correlation_is_analytics",
        "correlation/relationship phrasing → analytics, not clarification",
        _r_correlation,
        sets_analytics=True,
    ),
    Rule(
        "floor_plan_navigation",
        "'show me floor N' / 'where is room X' → floor_plan, never sparql/discovery",
        _r_floor_plan,
    ),
    Rule(
        "countable_metadata",
        "COUNT of devices/structure or building identity → metadata (SPARQL COUNT), "
        "not spatial geometry / reading / capability (BUG-045)",
        _r_countable_metadata,
    ),
    Rule(
        "room_count_is_spatial",
        "COUNT of rooms/spaces → spatial_query (the floor-plan manifests hold room "
        "geometry). Directly after countable_metadata, which declines this shape without "
        "naming a lane, leaving a room count on sensor_data (BUG-628)",
        _r_room_count_is_spatial,
    ),
    Rule(
        "inventory_to_discovery",
        "'what/which X does this building have' → discovery (one census handler), "
        "after countable_metadata so COUNT questions keep their route",
        _r_inventory_to_discovery,
    ),
    Rule(
        "forecast_skill_to_observability",
        "'how accurate are your forecasts' -> observability (the measured track "
        "record), never another forecast; forecast_to_trend guards itself against "
        "the same shape, because this contract is last-wins",
        _r_forecast_skill,
    ),
    Rule(
        "forecast_to_trend",
        "predict/forecast + sensor metric → trend pipeline",
        _r_forecast,
        sets_analytics=True,
    ),
    Rule(
        "actuation_control",
        "actuation or external-action command → control (which declines politely)",
        _r_control,
    ),
    Rule(
        "environment_change_request",
        "'can you reduce noise in this workspace?' -> control (declines with what it can do)",
        _r_environment_request,
    ),
    Rule(
        "wish_is_a_suggestion",
        "'it would be nice if the system ...' is a suggestion to log, not a control request",
        _r_wish_is_a_suggestion,
    ),
    Rule(
        "maintenance_schedule",
        "maintenance-schedule phrasing → maintenance, not metadata",
        _r_maintenance_schedule,
    ),
    Rule(
        "report_intake_statement",
        "fault/complaint/safety STATEMENT → report intake, beating capability/greeting",
        _r_report_intake,
    ),
    Rule(
        "report_request_not_capability",
        "'give me a report on <measured thing>' -> report, never a capability blurb",
        _r_report_request_not_capability,
    ),
    Rule(
        "self_description",
        "a question about the ASSISTANT → self_description, never open-domain",
        _r_self_description,
    ),
    Rule(
        "building_profile_question",
        "'how old / who built / what type is this building' → capability, never open-domain",
        _r_building_profile,
    ),
    Rule(
        "history_question_not_report",
        "past-maintenance QUESTION mis-tagged as report → capability (never files a ticket)",
        _r_history_question_not_report,
    ),
    Rule(
        "comfort_question_not_report",
        "comfort/data QUESTION mis-tagged as report → analytics",
        _r_comfort_question,
        sets_analytics=True,
    ),
    Rule(
        "alarm_history_is_a_record",
        "an alarm that ALREADY happened is a record to read, not an alert to create "
        "(TODO-490). Sits before standing_alert_request, which owns the opposite shape",
        _r_alarm_history_is_a_record,
    ),
    Rule(
        "standing_alert_request",
        "'notify me when X' standing request → alert",
        _r_standing_alert,
    ),
    Rule(
        "automation_capability_question",
        "'can the system automatically …?' → automation_capability",
        _r_automation_question,
    ),
    Rule(
        "what_can_i_automate",
        "'what kind of tasks can I automate?' -> automation_capability",
        _r_what_to_automate,
    ),
    Rule(
        "automation_needs_a_shape",
        "automation/alert label without an automate/alert/notify/standing shape → capability",
        _r_automation_needs_a_shape,
    ),
    Rule(
        "constraint_recommendation",
        "choose/rank spaces under comfort constraints → deliberate (V4 ARBITER)",
        _r_constraint_recommendation,
    ),
    Rule(
        "superlative_room_takeover",
        "room-superlative classified analytics/sensor_data → deliberate (BUG-163)",
        _r_superlative_room_takeover,
    ),
    Rule(
        "existential_comfort_is_deliberate",
        "'is it stuffy anywhere?' → deliberate: the same ranking as 'which room is "
        "stuffiest', for a questioner who does not know to phrase it that way (TODO-629). "
        "Directly after superlative_room_takeover, whose shape it completes",
        _r_existential_comfort_is_deliberate,
    ),
    Rule(
        "uniformity_is_a_comparison",
        "'is the temperature the same across the space?' asks for a SPREAD -> the per-floor "
        "comparison, not every sensor of that quantity and a too-wide refusal (2026-09-19)",
        _r_uniformity_is_a_comparison,
    ),
    Rule(
        "time_pattern_is_not_a_ranking",
        "'when is the atrium busiest?' asks for a TIME -> a series over history (trend), not "
        "the room ranking; after the two deliberate rules, whose label it corrects (BUG-828)",
        _r_time_pattern_is_not_a_ranking,
        sets_analytics=True,
    ),
    Rule(
        "event_store_query",
        "bookings / work orders / footfall → events lane (V5-T24)",
        _r_event_store_query,
    ),
    Rule(
        "register_owns_work_orders_and_timetable",
        "work-order and teaching-timetable questions → the register that holds their ids and "
        "statuses, never the events store's generated rows; AFTER event_store_query, whose "
        "vocabulary claims both, because each rule sets the intent and the last one wins "
        "(2026-09-19 probe regressions)",
        _r_register_owns_work_orders_and_timetable,
    ),
    Rule(
        "compliance_without_a_measurable_check",
        "a compliance question naming no measurand, space or standard → capability, "
        "which holds the documents or says it holds none — never the zone-required "
        "template (C19)",
        _r_compliance_without_a_measurable_check,
    ),
    Rule(
        "compliance_register",
        "dated compliance-register questions → register lane (V5-T26)",
        _r_compliance_register,
    ),
    Rule(
        "asset_state_query",
        "lift / AV / network state, cleaning schedules, closures → asset_state (V6-T58/T60)",
        _r_asset_state_query,
    ),
    Rule(
        "maintenance_record_is_a_register_question",
        "'when was X last serviced' / 'which tasks are overdue for maintenance' -> the register "
        "lane (metadata), not prose, a ticket list or the maintenance intake. After "
        "compliance_register and asset_state_query, whose intents it never takes",
        _r_maintenance_record_is_a_register_question,
    ),
    Rule(
        "why_diagnosis",
        "comfort why-questions → diagnosis lane (V5-T20)",
        _r_why_diagnosis,
    ),
    Rule(
        "observability_query",
        "can-you-measure questions → the reach lane, answered from the graph (V6-T10)",
        _r_observability_query,
    ),
    Rule(
        "consumption_query",
        "metered utility consumption → analytics, not a document (V6-T27)",
        _r_consumption_query,
    ),
    Rule(
        "plant_point_query",
        "BMS / plant point questions → sensor_data, not a document (V6-T26)",
        _r_plant_point_query,
    ),
    Rule(
        "route_comparison_is_recorded_data",
        "routes COMPARED with each other → the register that records the times, not a lane "
        "that measures sensors (BUG-614)",
        _r_route_comparison_is_data,
    ),
    Rule(
        "wayfinding_spatial",
        "route / nearest-facility questions → spatial route finder (V5-T27)",
        _r_wayfinding_spatial,
    ),
    Rule(
        "accessible_route_is_a_surveyed_record",
        "step-free / wheelchair / pushchair ROUTE questions → the surveyed route records, "
        "never a ranking of rooms and never a path computed from a drawing (BUG-744). "
        "Directly after wayfinding_spatial, which it takes these back from",
        _r_accessible_route_is_a_surveyed_record,
    ),
    Rule(
        "room_geometry_spatial",
        "area / size of a named room → floor-plan geometry, not capability",
        _r_room_geometry_spatial,
    ),
    Rule(
        "anomaly_history_to_events",
        "anomaly questions → persisted detector episodes (V5-T21)",
        _r_anomaly_history_to_events,
    ),
    Rule(
        "instrument_metrology",
        "calibration / reporting-interval questions describe the INSTRUMENT → metadata",
        _r_instrument_metrology,
    ),
    Rule(
        "readiness_check",
        "is this space ready for what happens next -> the readiness lane, dated per line",
        _r_readiness_check,
    ),
    Rule(
        "governance_question_never_reads_data",
        "a question about provenance, verification, permission or a professional judgement -> "
        "capability (documents, or an honest decline), never a census, a listing or a reading",
        _r_governance_question,
    ),
    # The last two are the scope rules and are deliberately LAST: they claim only shapes no data
    # lane has claimed for a reason of its own, so nothing earlier can be undone by them. Owner
    # policy 2026-09-19 -- answer building KNOWLEDGE as labelled guidance, decline what is not about
    # buildings at all.
    Rule(
        "a_report_needs_a_statement",
        "a hedged or verdict-seeking message that states no fault, hazard or place is a "
        "clarification, never a filed ticket ('if the building are safe or not' filed REP-051956); "
        "anything naming a thing, a place or a fault keeps filing (2026-09-19, serious)",
        _r_a_report_needs_a_statement,
    ),
    Rule(
        "proactive_or_procedure_is_capability",
        "'could the building proactively notice ...' and 'what can people do if ...' -> capability",
        _r_proactive_or_procedure_is_capability,
    ),
    Rule(
        "place_vs_comparable_places_needs_a_place",
        "'is my office warmer than comparable offices?' names no office -> ask which",
        _r_place_vs_comparable_places,
    ),
    Rule(
        "emergency_action_is_a_procedure",
        "'what should I do if the fire alarm goes off?' -> the building's own emergency procedure, "
        "never the fire-safety ASSET register that matched on the words (2026-09-19, safety). Late, "
        "because the register rules run late and this must survive them",
        _r_emergency_action_is_a_procedure,
    ),
    Rule(
        "general_guidance_question",
        "a building-knowledge question naming no place, time, record or 'this building' -> "
        "labelled general guidance; never the sensor fetch (owner policy 2026-09-19)",
        _r_general_guidance,
    ),
    Rule(
        "ungrounded_question_never_fetches",
        "a question naming no place, time, record or measured instance must not reach the "
        "all-sensors fetch: a space-suitability question -> the register lane, a design-standard "
        "question -> the documents and regime records. AFTER general_guidance_question, because "
        "every rule in a stage runs and the LAST one wins, and the owner's order is register "
        "reach, then design standard, then guidance",
        _r_ungrounded_never_fetches,
    ),
    Rule(
        "scope_boundary",
        "a weather forecast, financial advice, a joke or other non-building request -> a brief "
        "statement of what the assistant can answer from (BUG-812)",
        _r_scope_boundary,
    ),
)


def _r_asset_state_without_a_family(c: _Ctx) -> Optional[str]:
    """A turn the asset-state lane cannot serve is handed to the data pipeline, not refused.

    Measured live 2026-09-18, unscripted: *"Is the heat pump running?"* was answered "I couldn't
    tell which service or asset you meant, so I'm not guessing." The building has exactly one heat
    pump, so nothing was ambiguous. The classifier had chosen `asset_state` because the sentence
    has the shape "is the X running", and that lane knows three asset families (lifts, AV,
    network). Its own docstring says what a `None` classification means: "this lane should not have
    been asked, and the caller must not invent an answer from it." The caller printed a refusal
    that blamed the reader instead.

    The pipeline is the right place to send it: it finds the equipment's points and reports what
    they measure (the heat pump has entering and leaving water temperature and no run status), and
    its narration rule says to name the property the figures do carry and stop.

    Fires ONLY when the intent is already `asset_state` and the lane's own predicate says it cannot
    serve the question, so every turn that gets a correct asset-state answer today is untouched.
    """
    if c.intent != "asset_state":
        return None
    from orchestrator.services.asset_state_service import is_asset_state_question

    if is_asset_state_question(c.query):
        return None
    return "sensor_data"


POST_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "data_query_promotion",
        "place + measurable reading question → sensor_data (guarded against counts)",
        _r_data_query_promotion,
        preserve_analytics=True,
    ),
    # AFTER promotion, which never touches an asset_state intent, so the two cannot disagree.
    Rule(
        "asset_state_without_a_family",
        "the asset-state lane was chosen but knows no family for this asset -> sensor_data "
        "(never a refusal that blames the reader)",
        _r_asset_state_without_a_family,
        preserve_analytics=True,
    ),
)

CONCEPT_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "building_question_not_general",
        "lay-term measurand + a reference to this building → analytics, never open-domain",
        _r_building_not_general,
        sets_analytics=True,
    ),
    # AFTER the rule above: that one rescues open-domain questions, which is the more urgent
    # failure (an invented value beats no value in nobody's book). This one then handles the
    # far larger population that was landing in capability.
    Rule(
        "capability_measurand_is_data",
        "capability question naming a measurand this building instruments → sensor_data "
        "(or analytics for an aggregate shape)",
        _r_capability_measurand_is_data,
    ),
    # AFTER the rule above, and the order is the whole point: that one claims every question
    # naming something this building DOES measure. Whatever reaches here named a quantity and
    # resolved to no measurand at all.
    Rule(
        "unmeasured_quantity_is_reach",
        "measurement-shaped question naming a quantity this building does not instrument → "
        "observability, which can say so",
        _r_unmeasured_quantity_is_reach,
    ),
)

_STAGES: Dict[str, Tuple[Rule, ...]] = {
    "parse": PARSE_STAGE_RULES,
    "post": POST_STAGE_RULES,
    "concept": CONCEPT_STAGE_RULES,
}


def apply_contract(
    user_query: str,
    normalized: Dict[str, Any],
    stage: str = "parse",
) -> List[str]:
    """Apply the routing contract's ``stage`` rules to ``normalized`` in order.

    Mutates ``normalized`` exactly as the historical inline overrides did
    (``intent``, ``analytics``, ``general``, optional extras) and records every
    applied rule name in ``normalized["routing_rules_applied"]``. Returns the
    list of rule names applied in this call.
    """
    from orchestrator.services.semantic_router import (  # local import — avoids cycle
        SemanticRouter,
    )

    ctx = _Ctx(
        query=user_query or "",
        ql=(user_query or "").lower(),
        normalized=normalized,
        sr=SemanticRouter,
    )
    applied: List[str] = []
    for rule in _STAGES[stage]:
        try:
            new_intent = rule.fn(ctx)
        except Exception as e:  # a broken rule must never break routing
            logger.warning(f"[routing-contract] rule '{rule.name}' errored: {e}")
            continue
        if not new_intent or new_intent == ctx.intent:
            continue
        old = ctx.intent
        normalized["intent"] = new_intent
        if not rule.preserve_analytics:
            normalized["analytics"] = bool(rule.sets_analytics)
        normalized["general"] = False
        if rule.extras:
            normalized.update(rule.extras(ctx))
        applied.append(rule.name)
        logger.info(f"[routing-contract] {rule.name}: '{old}' → '{new_intent}' — {rule.shape}")
    if applied:
        normalized.setdefault("routing_rules_applied", []).extend(applied)
    # stamp which stages ran even when nothing applied, so callers can detect a
    # path that skipped the parse stage (CAVEAT: the JSON-parse fallback did)
    normalized.setdefault("routing_stages_run", []).append(stage)
    return applied


# ── Metered-quantity questions (V6, 2026-08-25) ─────────────────────────────
#: Modality-name tokens that carry no subject on their own. "parking_free" must
#: contribute "parking", never "free" — otherwise "how many rooms are free?"
#: becomes a parking question. Kept deliberately small: the discriminating word
#: is almost always the modality's own noun.
_MODALITY_STOPWORDS = frozenset(
    {
        "free",
        "state",
        "status",
        "level",
        "flow",
        "contact",
        "hours",
        "count",
        "data",
        "usage",
        "chilled",
        "submeter",
    }
)

_METERED_VOCAB_CACHE: Dict[str, frozenset] = {}


def metered_vocabulary(building_id: Optional[str] = None) -> frozenset:
    """Lay terms for the quantities THIS building actually meters.

    Read from the modality config, which is the declared source of truth for what a
    building measures ("the modality set is CONFIG, NOT CODE"). Deriving the routing
    vocabulary from it means adding a modality makes its questions routable with no
    code change, and every other building inherits the behaviour without a second list
    to keep in sync — the alternative being another hand-maintained phrase table that
    is wrong for every building except the one it was written on.
    """
    key = str(building_id or "")
    if key in _METERED_VOCAB_CACHE:
        return _METERED_VOCAB_CACHE[key]
    terms: set = set()
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        for spec in load_modalities(building_id):
            terms.update(t.lower() for t in (spec.label_contains or []) if len(t) >= 4)
            for token in str(spec.name).lower().split("_"):
                if len(token) >= 4 and token not in _MODALITY_STOPWORDS:
                    terms.add(token)
    except Exception as exc:  # a building with no config must still route
        logger.debug(f"[routing_contract] metered vocabulary unavailable: {exc}")
    vocab = frozenset(terms)
    _METERED_VOCAB_CACHE[key] = vocab
    return vocab


#: Asking WHERE something can be done or found, not what a sensor reads.
#:
#: `is_data_query` treats "a floor is named AND a measurement word appears" as a
#: reading request. "Where can I fill my water bottle on floor 3?" names floor 3
#: and contains "water", so it was promoted to sensor_data and answered with the
#: floor plan -- the building has twelve bottle-refill points and the question
#: never reached the lane that knows about them (BUG-337, measured live).
#:
#: The distinguishing signal is the SHAPE, not the noun. "Where can I <verb>" and
#: "where is the nearest <thing>" ask for a facility to use; no amount of water
#: being metered turns them into a request for a reading. Deliberately narrow:
#: "where is the water usage highest?" keeps its analytic reading, because that
#: asks which place holds an extreme of a measured value.
_AMENITY_SEEKING_RE = re.compile(
    r"\bwhere\s+(?:can|could|do|should|might)\s+(?:i|we|you|someone)\b"
    r"|\bwhere\s+(?:is|are)\s+(?:the\s+)?(?:nearest|closest)\b"
    r"|\bhow\s+(?:do|can)\s+i\s+(?:get|find|reach)\b"
    r"|\bis\s+there\s+(?:a|an|any)\b.{0,30}\b(?:near|nearby|on this floor|in the building)\b",
    re.IGNORECASE,
)

#: Words that turn a "where" question back into an analytic one: they ask which
#: place holds an extreme or a comparison of a measured value.
_EXTREMUM_RE = re.compile(
    r"\b(?:highest|lowest|hottest|coldest|warmest|coolest|most|least|maximum|minimum|"
    r"max|min|peak|worst|best|above|below|exceed(?:s|ing)?|over|under)\b",
    re.IGNORECASE,
)


def amenity_seeking_question(query: str) -> bool:
    """True when the question asks where to DO or FIND something, not what a sensor reads.

    Pure and building-agnostic: it reads the shape of the question, never a list
    of this estate's amenities.
    """
    q = query or ""
    if not _AMENITY_SEEKING_RE.search(q):
        return False
    # "Where can I find the room with the highest CO2?" is analytic despite the
    # shape, so an extremum word hands the question back.
    return not _EXTREMUM_RE.search(q)


def metered_quantity_question(query: str, building_id: Optional[str] = None) -> bool:
    """True when the query asks HOW MANY/MUCH of something this building meters.

    The gap this closes: ``is_data_query`` recognised a data question by sensor id,
    room id or a fixed phrase list, so any metered quantity outside that list was
    invisible to it. Measured live 2026-08-25 — "how many parking bays are free right
    now?" was not a data query, so it never reached the classifier, and the capability
    lane answered it with the building's CATERING amenities while a parking sensor sat
    in the graph with 5,090 rows behind it.

    Deliberately narrow. The quantity shape is REQUIRED, so the modality noun alone
    never claims a question: "where is the car park?" stays wayfinding and "is there
    parking?" stays an amenity question. Only "how many/much" plus a metered noun —
    which no other lane can answer with a number — is taken.
    """
    if not query or not query.strip():
        return False
    from orchestrator.services.grounding_guard import _ASKS_QUANTITY_RE

    if not _ASKS_QUANTITY_RE.search(query):
        return False
    words = set(re.findall(r"[a-z]+", query.lower()))
    return bool(words & metered_vocabulary(building_id))
