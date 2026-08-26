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


def _r_correlation(c: _Ctx) -> Optional[str]:
    if c.intent == "clarification" and _any(c.ql, CORRELATION_KWS):
        return "analytics"
    return None


def _r_floor_plan(c: _Ctx) -> Optional[str]:
    if c.intent in ("floor_plan", "spatial_query"):
        return None
    return "floor_plan" if _any(c.ql, FLOOR_PLAN_KWS) else None


def _is_countable_meta(ql: str) -> bool:
    """Device/structure COUNT or building-identity question shape (BUG-045)."""
    count_q = _any(ql, COUNT_TRIGGER_KWS)
    devices = _any(ql, COUNTABLE_DEVICE_KWS)
    structure = _any(ql, STRUCTURE_COUNT_KWS)
    geometry = _any(ql, ROOM_GEOMETRY_KWS)
    info = _any(ql, BUILDING_INFO_KWS)
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

    return "discovery" if is_inventory_question(c.query) else None


def _r_forecast(c: _Ctx) -> Optional[str]:
    if c.intent in ("trend", "analytics"):
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
    if c.intent not in ("general", "general_knowledge", "clarification", "greeting", "metadata"):
        return None
    from orchestrator.services.building_profile import detect_facet

    return "capability" if detect_facet(c.query) else None


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


def _r_standing_alert(c: _Ctx) -> Optional[str]:
    """'notify me when X' / 'alert me if X' → alert (standing personal alert)."""
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    return "alert" if STANDING_ALERT_RE.search(c.query) else None


def _r_automation_question(c: _Ctx) -> Optional[str]:
    """'can the system automatically …?' → automation_capability (honest answer)."""
    if c.intent not in _WEAK_INTENTS:
        return None
    if c.sr.is_control_command(c.query) or c.sr.report_intake_intent(c.query):
        return None
    return "automation_capability" if AUTOMATION_Q_RE.search(c.query) else None


# V4 ARBITER — constraint-recommendation shapes: choose/rank spaces under
# comfort constraints. Conservative from-set: weak intents + 'recommend' (which
# has no dedicated logic and collapses to generic analytics today); analytics/
# spatial_query classifications keep their proven routes.
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
    r"(?:\bis\s+(?!there\b)(?:\S{2,}\s+){1,3}(?:free|booked|available|in use|reserved|occupied|taken)\b"
    # "step-free" is an ACCESSIBILITY term, not an availability one. Without the
    # lookbehind, "which rooms are step-free accessible?" matched here and was answered
    # with "69 of 233 rooms have no booking today" — a booking answer to an
    # accessibility question (measured 2026-08-25). Any hyphen-prefixed "free"
    # (step-free, barrier-free) is excluded: nobody asks whether a room is "X-free"
    # meaning unoccupied.
    r"|\b(?:which|what|any|list)\b.{0,40}\brooms?\b.{0,30}\b(?:(?<!-)free|available)\b"
    r"|\b(?:a|any)\s+rooms?\s+(?:(?<!-)free|available)\b"
    r"|\bbookings?\b|\breservations?\b"
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
    r"|\bhow busy was\b.{0,30}\b(?:entrance|building)\b)",
    re.IGNORECASE,
)


_INTERROGATIVE_RE = re.compile(
    r"^\s*(?:how many|how much|any|are there|is there|what|which|when|show|list|count|do we have)\b"
    r"|\?\s*$",
    re.IGNORECASE,
)


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
    return "events" if EVENTS_RE.search(c.query) else None


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
    # "How much <resource>" asks for a QUANTITY of a mass noun and can never be a device
    # census, so it settles the question before the inventory guard is consulted. That guard
    # returns True for "How much electricity does the lab on floor 5 use?" — a false positive
    # that would otherwise route a consumption question to the inventory lane. Narrowing the
    # shared guard itself would risk the counting behaviour it owns; this states the one case
    # where counting is impossible instead.
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
    from orchestrator.services.observability import is_observability_question

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
    return "spatial_query" if WAYFIND_RE.search(c.query) else None


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


def _r_superlative_room_takeover(c: _Ctx) -> Optional[str]:
    """Room-superlative shape classified analytics/sensor_data → deliberate (BUG-163).

    Post-saturation the deliberative path holds full per-room coverage on every
    modality; generic analytics demonstrably cannot rank rooms (it aggregated a
    hardware-scale column into '0.00 ppm' answers). Lowest precedence: it fires
    only when no earlier rule (comfort question, compare, data promotion) did.
    """
    if c.intent not in ("analytics", "sensor_data"):
        return None
    return "deliberate" if DELIBERATE_RE.search(c.query) else None


def _r_data_query_promotion(c: _Ctx) -> Optional[str]:
    """A value/reading question naming a place + measurable → sensor_data (post stage).

    Guard: a countable/structure/building-identity question is metadata, never
    demoted to a per-sensor reading.
    """
    if c.intent not in ("metadata", "general", "capability", "general_knowledge"):
        return None
    if not c.sr.is_data_query(c.query):
        return None
    if _is_countable_meta(c.ql):
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


PARSE_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "inference_privacy_denial",
        "individual presence/pattern/private-content/override shapes → refusal (V5-T42)",
        _r_inference_privacy,
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
        "inventory_to_discovery",
        "'what/which X does this building have' → discovery (one census handler), "
        "after countable_metadata so COUNT questions keep their route",
        _r_inventory_to_discovery,
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
        "event_store_query",
        "bookings / work orders / footfall → events lane (V5-T24)",
        _r_event_store_query,
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
        "wayfinding_spatial",
        "route / nearest-facility questions → spatial route finder (V5-T27)",
        _r_wayfinding_spatial,
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
)

POST_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "data_query_promotion",
        "place + measurable reading question → sensor_data (guarded against counts)",
        _r_data_query_promotion,
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
