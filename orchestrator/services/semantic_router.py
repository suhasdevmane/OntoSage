"""
SemanticRouter — query-time semantic classifier for intent routing.

Embeds the user query once, searches one or more registered Qdrant collections,
groups raw points by entry_id with max-pool scoring, and returns a
SemanticRouteResult that the dialogue agent uses to decide whether to:
  - SKIP the LLM intent call entirely (score >= override_min)
  - SOFT-override an LLM non-data intent (threshold <= score < override_min)
  - DO NOTHING and let the LLM classify (score < threshold)

Intent-agnostic by design: `register_intent("capability", "capability_")` today;
future `register_intent("floor_plan", "spatial_")` requires no further changes.

Failure modes (all non-raising):
  - Qdrant unreachable     → source="fallback", score=0.0, matches=[]
  - Per-building disabled  → source="disabled", score=0.0, matches=[]
  - Empty/whitespace query → source="semantic", score=0.0 (no embed call attempted)
"""

from __future__ import annotations

import os
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Literal, Optional

import yaml

from shared.building_paths import resolve_building_file
from shared.capability_schema import (
    CapabilityEntry,
    CapabilityKB,
    CapabilityRoutingConfig,
    IntentRouteConfig,
)
from shared.utils import get_logger

logger = get_logger(__name__)

# ── Data-query bypass ─────────────────────────────────────────────────────────
# Queries that match any of these patterns are LIVE-DATA requests (SPARQL /
# analytics pipeline).  They must never be captured by the KB capability router,
# even when KB entries happen to score high because they mention sensor counts or
# zone names in their content text.
#
# The check is pure regex + frozenset substring — no embedding call needed.

# Sensor ID patterns: Air_Temperature_Sensor_5.28, CO2_Sensor_5.08, etc.
_SENSOR_ID_RE = _re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*_)+Sensor_[\d.]+\b",
    _re.IGNORECASE,
)
# Zone ID patterns: Zone_5.28, zone 5.28
_ZONE_ID_RE = _re.compile(
    r"\bzone[_\s][\d]+\.[\d]+\b",
    _re.IGNORECASE,
)
# Room/floor locators: room 5.01, rm 3.2, floor 3 — combined with a measurement
# keyword these are live-data questions ("latest CO2 in room 5.01"), which the
# phrase list above cannot enumerate. Added 2026-06-12 after a live data question
# was hijacked by a high-confidence capability override (score 0.684 on OpenAI
# embeddings vs thresholds calibrated for local MiniLM).
_ROOM_ID_RE = _re.compile(r"\b(room|rm)[_\s]?\d+(\.\d+)?\b", _re.IGNORECASE)
_FLOOR_ID_RE = _re.compile(r"\bfloor[_\s]?\d+\b", _re.IGNORECASE)

# ── Data-keyword exclusion for floor-plan bypass ──────────────────────────────
# When a query mentions "floor N" AND data/analytics keywords, it is a data
# request, not a floor plan visualisation request.  Queries like
# "Show average temperature trend for floor 2 last week" must NOT be routed
# to floor_plan even though they contain "show" and "floor 2".
_DATA_ANALYTIC_WORDS: FrozenSet[str] = frozenset(
    [
        "temperature",
        "co2",
        "humidity",
        # "air quality" was missing (TODO-133): "what is the air quality on floor 1?"
        # therefore failed is_data_query, the capability probe was NOT bypassed, a
        # lay-term matched a capability topic, and a plainly answerable data question
        # was routed to capability and honestly declined — on a building whose
        # LARGEST sensor class is Air_Quality_Sensor. These are generic measurand
        # words (domain English, no building's vocabulary).
        "air quality",
        "aqi",
        "iaq",
        "noise",
        "occupancy",
        "pressure",
        "sensor",
        "reading",
        "level",
        "value",
        "measurement",
        "trend",
        "average",
        "mean",
        "analytics",
        "analysis",
        "statistics",
        "energy",
        "consumption",
        "usage",
        "power",
        "kw",
        "kwh",
        "report",
        "compare",
        "comparison",
        "forecast",
        "predict",
        "last week",
        "last month",
        "last hour",
        "yesterday",
        "today",
        "over time",
        "time series",
        "historical",
        "current reading",
        "highest",
        "lowest",
        "maximum",
        "minimum",
        "variance",
        "std",
        "anomaly",
        "spike",
        "alert",
        "threshold",
        "exceed",
        # Modalities standardized out of input/data — measurable QUANTITIES only
        # (not equipment names like "AHU", so "is the AHU broken?" still routes to
        # capability). Combined with a floor/room locator → data-query bypass.
        "water",
        "flow",
        "illuminance",
        "lux",
        "vibration",
        "runtime",
        "run-time",
        "run time",
        "pm2.5",
        "pm25",
        "particulate",
        "voc",
        "tvoc",
        "watt",
    ]
)

# Phrase-level signals: any of these substrings in the lowercased query → bypass.
_DATA_BYPASS_PHRASES: FrozenSet[str] = frozenset(
    [
        # Enumeration / listing queries
        "list all sensors",
        "list all temperature sensors",
        "list all co2 sensors",
        "list all humidity sensors",
        "list all noise sensors",
        "list all occupancy sensors",
        "list all zones",
        "list all floors",
        "list all hvac",
        "list the sensors",
        "list the zones",
        "show all sensors",
        "show me all sensors",
        # Counting queries
        "how many zones",
        "how many sensors",
        "how many floors",
        "how many rooms",
        "how many co2 sensors",
        "how many temperature sensors",
        "how many humidity sensors",
        "how many noise sensors",
        "number of sensors",
        "number of zones",
        "number of floors",
        # Lookup / membership queries
        "which sensors are in",
        "which sensors are on",
        "what sensors are in",
        "what sensors are on",
        "sensors in zone",
        "sensors on floor",
        # Sensor-type discovery (asking SPARQL, not KB description)
        "what sensor types",
        "sensor types installed",
        "types of sensors installed",
        "what types of sensors",
        "sensor types available",
        # HVAC equipment listing via SPARQL
        "what hvac equipment",
        "list all hvac equipment",
        "hvac equipment installed",
        "hvac equipment in the building",
        # UUID / metadata lookup
        "uuid for",
        "what is the uuid",
        "get the uuid",
        # Report / analytics pipeline queries — these go to SPARQL+SQL+report, not KB
        "maintenance report",
        "energy report",
        "generate report",
        "generate a report",
        "create a report",
        "show me a report",
        "build a report",
        "weekly report",
        "monthly report",
        "daily report",
        "annual report",
        "temperature report",
        "co2 report",
        "sensor report",
        "hvac report",
        "trend report",
        "analytics report",
        "compliance report",
        "show me a maintenance",
        "maintenance summary",
        "maintenance schedule",
        "show trend",
        "show average",
        "show analysis",
        "statistical analysis",
        "sensor variance",
        "sensor readings for",
        "historical data",
        "energy consumption",
        "energy usage trend",
        "power consumption",
        # Anomaly / alert pipeline queries
        "anomaly detection",
        "detect anomaly",
        "temperature spike",
        "alert me if",
        "notify me when",
        "warn me if",
        "set an alert",
        "if co2 exceeds",
        "if temperature goes above",
        "if humidity drops",
        "threshold exceeded",
        "out of range",
        "unusual reading",
        # Maintenance schedule / ticket queries — go to maintenance intent, not KB
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
        "what maintenance",
        "maintenance is scheduled",
    ]
)

# ── Floor-plan bypass ────────────────────────────────────────────────────────
# Queries with explicit floor-plan/spatial signals must skip the KB router and
# go to the floor_plan agent.  The KB has entries about facilities/rooms that
# score high for "see the rooms" but that's NOT what these queries want —
# they want the actual floor plan PDF/image.

# Matches "floor N", "Nth floor", "fifth floor", "top floor"
_FLOOR_NUMBER_RE = _re.compile(
    r"\b(?:floor|level|storey|story)\s*\d+\b"
    r"|\b\d+(?:st|nd|rd|th)\s+floor\b"
    r"|\b(?:ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|top|highest|uppermost)\s+floor\b",
    _re.IGNORECASE,
)

_FLOOR_PLAN_BYPASS_PHRASES: FrozenSet[str] = frozenset(
    [
        "floor plan",
        "floorplan",
        "floor map",
        "building map",
        "building layout",
        "show me floor",
        "see floor",
        "see the floor",
        "view floor",
        "show me the layout",
        "show me the plan",
        "room layout",
        "open the plan",
        "actual rooms",
        "actual layout",
        "see the rooms",
        "see the actual rooms",
        "where is room",
        "where is the room",
        "where is zone",
        "where is the zone",
        "locate the room",
        "locate the zone",
        "find the room",
        "find the zone",
        "show me where",
        "navigate to",
        "directions to",
        "building overview",
        "building directory",
    ]
)

# ── Spatial-query bypass ─────────────────────────────────────────────────────
# Quantitative geometry queries (area, count, adjacency) must reach the
# spatial_query agent which reads the DWG manifest, not the KB router.
_SPATIAL_BYPASS_PHRASES: FrozenSet[str] = frozenset(
    [
        "area of floor",
        "total area of",
        "how big is",
        "adjacent to",
        "next to room",
        "rooms adjacent",
        "largest room",
        "smallest room",
        "biggest room",
        "room sizes",
        "room areas",
        "room dimensions",
        "square meters",
        "square metres",
        "square feet",
    ]
)

# ── Report-intake bypass ─────────────────────────────────────────────────────
# Fault/complaint/suggestion/safety/feedback STATEMENTS must reach the
# report_intake handler, NOT the capability KB router. The KB router otherwise
# steals them because phrases like "toilet"/"bike racks" score high against the
# amenities KB. These are classified by `report_intake_intent()` which also
# guards against QUESTIONS ("is it too warm?" is analytics, not a complaint).
_REPORT_QUESTION_STARTS = (
    "is ",
    "are ",
    "what",
    "how",
    "why",
    "can ",
    "could ",
    "does ",
    "do ",
    "where",
    "when",
    "which",
    "should ",
    "will ",
    "would ",
    "who ",
    "whose",
    "tell me",
    "show me",
    "list ",
    "give me",
)
_REPORT_SAFETY_PHRASES: FrozenSet[str] = frozenset(
    [
        "gas smell",
        "smell of gas",
        "smell gas",
        "smells of gas",
        "smoke",
        "is on fire",
        "fire hazard",
        "fire exit",
        "emergency exit",
        "exit is blocked",
        "blocked fire exit",
        "blocked exit",
        "safety hazard",
        "trip hazard",
        "exposed wire",
        "exposed wires",
        "unsafe",
        "electrical hazard",
        "spillage",
        "wet floor",
        "broken glass",
    ]
)
_REPORT_FAULT_PHRASES: FrozenSet[str] = frozenset(
    [
        "is broken",
        "are broken",
        "is leaking",
        "leaking",
        "is dripping",
        "dripping",
        "is not working",
        "isn't working",
        "are not working",
        "not working",
        "doesn't work",
        "does not work",
        "won't turn",
        "wont turn",
        "is faulty",
        "is damaged",
        "is clogged",
        "is blocked",
        "out of order",
        "needs fixing",
        "needs repair",
        "needs to be fixed",
        "is flickering",
        "flickering",
        "is stuck",
        "is jammed",
        "no hot water",
        "broken light",
        "light is out",
        "report a fault",
        "report a problem",
        "report an issue",
        "file a ticket",
        "file a maintenance",
        "log a ticket",
        "raise a ticket",
        "maintenance ticket",
    ]
)
_REPORT_SUGGESTION_PHRASES: FrozenSet[str] = frozenset(
    [
        "suggestion:",
        "i suggest",
        "i'd suggest",
        "id suggest",
        "i would suggest",
        "it would be great",
        "it would be nice",
        "it'd be great",
        "would be good to have",
        "you should add",
        "please add",
        "can you add",
        "could you add",
        "we need more",
        "we could use",
        "it would help to have",
    ]
)
_REPORT_FEEDBACK_PHRASES: FrozenSet[str] = frozenset(
    [
        "great job",
        "well done",
        "good work",
        "thank you for fixing",
        "thanks for fixing",
        "really appreciate",
        "much appreciated",
        "great service",
        "love the",
        "fantastic job",
    ]
)
_REPORT_COMPLAINT_PHRASES: FrozenSet[str] = frozenset(
    [
        "too cold",
        "too warm",
        "too hot",
        "too stuffy",
        "too noisy",
        "too loud",
        "too dark",
        "too bright",
        "always cold",
        "always warm",
        "always too",
        "it's freezing",
        "its freezing",
        "freezing in",
        "boiling in",
        "stuffy in",
        "smells bad",
        "bad smell",
        "uncomfortable",
        "not comfortable",
    ]
)

# ── Control / actuation commands ─────────────────────────────────────────────
# Physical actuation of building systems must route to the control intent (which
# DECLINES — OntoSage is read-only/advisory) — NOT floor_plan just because a
# "floor N" is mentioned, NOT maintenance, and NOT the capability KB.
#
# Detection has three layers (see `is_control_command`):
#   1. _CONTROL_COMMAND_PHRASES — strong literal commands (substring match).
#   2. _CONTROL_VERB_TARGET_RE  — actuation VERB followed by a controllable TARGET
#      ("open the windows", "unlock all the doors", "turn off the HVAC").
#   3. _CONTROL_ENSURE_RE       — indirect / polite / interrogative requests
#      ("can you ensure every door is unlocked", "keep the windows open").
# Status QUESTIONS ("is the door locked?", "are the windows open?") deliberately
# do NOT match — only verb-first commands and explicit ensure/keep requests do.
_CONTROL_COMMAND_PHRASES: FrozenSet[str] = frozenset(
    [
        # windows / blinds / curtains / doors / gates / shutters
        "open the window",
        "close the window",
        "open the windows",
        "close the windows",
        "open windows",
        "close windows",
        "open all the window",
        "close all the window",
        "open the blind",
        "close the blind",
        "open the blinds",
        "close the blinds",
        "open the curtain",
        "close the curtain",
        "open the shutter",
        "close the shutter",
        "open the door",
        "close the door",
        "open the doors",
        "close the doors",
        "open all the door",
        "open every door",
        "unlock all the door",
        "unlock every door",
        "unlock the door",
        "lock the door",
        "unlock the doors",
        "lock the doors",
        "unlock all door",
        "unlock everything",
        "open everything",
        "open the gate",
        "close the gate",
        "release the door",
        "release the lock",
        "release the maglock",
        "let people out",
        "let everyone out",
        "lock down",
        "lockdown",
        "go into lockdown",
        # hvac / heating / cooling / ventilation / fans
        "turn on",
        "turn off",
        "switch on",
        "switch off",
        "power on",
        "power off",
        "set the thermostat",
        "set the temperature",
        "set temperature to",
        "adjust the temperature",
        "increase the temperature",
        "decrease the temperature",
        "turn up the heat",
        "turn down the heat",
        "turn on the heating",
        "turn off the heating",
        "turn on the ac",
        "turn off the ac",
        "turn on the cooling",
        "turn off the cooling",
        "start the hvac",
        "stop the hvac",
        "start the ventilation",
        "stop the ventilation",
        "turn on the fan",
        "turn off the fan",
        "set the setpoint",
        "change the setpoint",
        "override the setpoint",
        "override the hvac",
        "override the system",
        # lights
        "dim the light",
        "brighten the light",
        "turn on the light",
        "turn off the light",
        "switch on the light",
        "switch off the light",
        "turn on the lights",
        "turn off the lights",
        # blinds positioning
        "lower the blind",
        "raise the blind",
        "lower the blinds",
        "raise the blinds",
        # alarms / systems / power
        "silence the alarm",
        "disable the alarm",
        "arm the alarm",
        "disarm the alarm",
        "trigger the alarm",
        "reset the system",
        "restart the system",
        "reboot the system",
        "shut down the system",
        "cut the power",
        "turn off the power",
        "turn on the power",
        "lock the",
        "unlock the",
    ]
)

# Actuation VERB ... (within ~40 chars) ... controllable TARGET. Verb-first so it
# matches commands ("open the door") but not status questions ("is the door open").
_CONTROL_VERB_TARGET_RE = _re.compile(
    r"\b(unlock|lock|open|close|shut|turn\s+on|turn\s+off|switch\s+on|switch\s+off|"
    r"power\s+on|power\s+off|adjust|increase|decrease|dim|brighten|raise|lower|"
    r"start|stop|enable|disable|activate|deactivate|restart|reboot|override|"
    r"release|arm|disarm|engage|disengage|silence)\b.{0,40}?\b("
    r"door|doors|lock|locks|window|windows|blind|blinds|shade|shades|curtain|curtains|"
    r"gate|gates|barrier|barriers|shutter|shutters|turnstile|hvac|thermostat|thermostats|"
    r"heating|cooling|air\s+conditioning|ventilation|fan|fans|light|lights|lighting|lamp|"
    r"alarm|alarms|sprinkler|sprinklers|boiler|chiller|pump|valve|damper|ahu|vav|"
    r"power|electricity|mains|socket|sockets|plug|lift|lifts|elevator|elevators|"
    r"setpoint|set\s+point|access\s+control|maglock|mag\s+lock)\b",
    _re.IGNORECASE,
)

# Indirect / polite / interrogative actuation requests directed at the assistant:
# "can you ensure every door is unlocked", "make sure the windows are open",
# "keep the doors unlocked", "please open ...". These are commands phrased as asks.
# Automation-capability QUESTION: modal + building/system subject + autonomy cue.
# "Can the building automatically X?", "Could the system detect Y by itself?" —
# these are T22 capability questions, never actuation commands (guard 2026-06-12).
# "Can YOU open the door" keeps subject 'you' and is still a command.
_AUTOMATION_CAPABILITY_Q_RE = _re.compile(
    r"\b(can|could|will|would|does|should|is)\s+(the\s+)?(building|system|it|ontosage)\b"
    r".{0,40}\b(automatically|auto-|by itself|on its own|without (me|us|anyone|manual))",
    _re.IGNORECASE,
)

# Advice QUESTION about a user action: "Should I open the windows to improve air
# quality?" asks for a recommendation (analytics + recipe guidance, e.g. the T14
# window_opening_guidance recipe) — it is not a command to actuate anything
# (guard 2026-06-12, QA case WF04).
_ADVICE_QUESTION_RE = _re.compile(
    r"\b(should (i|we)|is it (worth|a good idea|better)|would it (help|be better)|"
    r"do you (recommend|suggest|advise)|what do you recommend)\b",
    _re.IGNORECASE,
)

_CONTROL_ENSURE_RE = _re.compile(
    r"\b(ensure|make\s+sure|makesure|please\s+(?:un)?lock|please\s+open|please\s+close|"
    r"please\s+turn|keep\s+(?:all\s+)?(?:the\s+)?(?:doors?|windows?|gates?|blinds?)|"
    r"have\s+(?:all\s+)?(?:the\s+)?(?:doors?|windows?|gates?)|"
    r"can\s+you\s+(?:please\s+)?(?:un)?lock|can\s+you\s+(?:please\s+)?open|"
    r"could\s+you\s+(?:un)?lock|could\s+you\s+open|i\s+(?:need|want)\s+you\s+to\s+"
    r"(?:un)?lock|i\s+(?:need|want)\s+you\s+to\s+open|let\s+people|allow\s+everyone)\b"
    r".{0,80}?\b(unlock|unlocked|lock|locked|open|opened|close|closed|shut|"
    r"turned\s+on|turned\s+off|switched\s+on|switched\s+off|released|disabled|enabled|out)\b",
    _re.IGNORECASE,
)


@dataclass
class CapabilityMatch:
    """Single grouped match returned by the semantic router.

    entry_id  → the YAML capability id (e.g. 'lift_accessibility_detail')
    score     → max similarity score across all vectors for this entry
    entry     → the loaded CapabilityEntry (content used by CapabilityAgent)
    """

    entry_id: str
    score: float
    entry: Optional[CapabilityEntry] = None


@dataclass
class SemanticRouteResult:
    """Result of one classification call.

    intent  → "capability" if score >= override_min; None otherwise
              (caller decides what to do with medium-score matches)
    score   → max grouped entry score
    matches → top-k grouped CapabilityMatches (may be populated even when intent=None,
              so caller can apply soft-override logic)
    source  → "semantic" | "fallback" | "disabled"
    """

    intent: Optional[str]
    score: float
    matches: List[CapabilityMatch] = field(default_factory=list)
    source: Literal["semantic", "fallback", "disabled"] = "semantic"


@dataclass
class _IntentBinding:
    """One registered intent → its Qdrant collection prefix."""

    intent: str
    collection_prefix: str  # e.g. "capability_" → real collection is "capability_<bldg>"


# Document-KB rescue (route policy/governance/privacy questions to the capability
# node so its doc-search fallback can ground them from documents_<bldg>). Gated +
# tunable: behavior-changing, so it can be disabled / re-calibrated per deployment.
_DOC_KB_ROUTING_ENABLED = os.environ.get("DOC_KB_ROUTING_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_DOC_KB_ROUTE_THRESHOLD = float(os.environ.get("DOC_KB_ROUTE_THRESHOLD", "0.38"))


class SemanticRouter:
    """Query-time semantic router. See module docstring.

    Args:
        qdrant_client: AsyncQdrantClient instance
        embedding_service: EmbeddingService instance
        input_root: where to read per-building config + KB (defaults to /app/input)
    """

    def __init__(
        self,
        qdrant_client,
        embedding_service,
        input_root: str = "/app/input",
    ):
        self._qdrant = qdrant_client
        self._embedder = embedding_service
        self._input_root = Path(input_root)
        self._intents: Dict[str, _IntentBinding] = {}
        # Per-building cache: KB + routing config — loaded once, reused
        self._kb_cache: Dict[str, CapabilityKB] = {}
        self._config_cache: Dict[str, CapabilityRoutingConfig] = {}

    # ── public API ──────────────────────────────────────────────────────────────

    @staticmethod
    def is_data_query(query: str) -> bool:
        """Return True when the query is clearly a live-data / SPARQL request.

        Such queries should bypass the KB capability router entirely, even when
        KB content happens to mention sensor counts or zone names.

        Checks (in order, short-circuits on first match):
          1. Explicit sensor ID pattern (Air_Temperature_Sensor_5.28, etc.)
          2. Explicit zone ID pattern (Zone_5.28, zone 5.28)
          3. Room/floor locator + measurement keyword ("latest CO2 in room 5.01")
          4. Known data-query phrases (enumeration, counting, lookup)
        """
        if not query or not query.strip():
            return False
        q = query.lower()
        if _SENSOR_ID_RE.search(query):
            return True
        if _ZONE_ID_RE.search(query):
            return True
        if (_ROOM_ID_RE.search(query) or _FLOOR_ID_RE.search(query)) and any(
            word in q for word in _DATA_ANALYTIC_WORDS
        ):
            return True
        return any(phrase in q for phrase in _DATA_BYPASS_PHRASES)

    @staticmethod
    def is_floor_plan_query(query: str) -> bool:
        """Return True when query clearly asks for the floor plan / spatial map.

        These must bypass the KB router so the floor_plan agent can return
        the actual PDF/image, not a generic facilities description.

        Guard: if the query contains data/analytics keywords alongside floor
        mentions (e.g. "temperature trend for floor 2"), it is a data request
        and must NOT be classified as a floor plan query.
        """
        if not query or not query.strip():
            return False
        q = query.lower()
        # Data/analytics exclusion: "show temperature trend for floor 2" is NOT
        # a floor plan request even though it contains "show" and "floor N".
        if any(word in q for word in _DATA_ANALYTIC_WORDS):
            return False
        # Control exclusion: "open the windows on floor 3" is an actuation command
        # (-> control -> decline), NOT a request to open the floor plan.
        if SemanticRouter.is_control_command(query):
            return False
        # Phrase matches
        if any(phrase in q for phrase in _FLOOR_PLAN_BYPASS_PHRASES):
            return True
        # Floor number + visual verb (only when no data keywords present — checked above)
        # "show me floor 5", "open floor 3", "view the 2nd floor"
        if _FLOOR_NUMBER_RE.search(query) and any(
            v in q
            for v in (
                "show",
                "open",
                "view",
                "see",
                "display",
                "give me",
                "pull up",
                "bring up",
                "draw",
                "plan",
                "layout",
                "map",
            )
        ):
            return True
        return False

    @staticmethod
    def is_spatial_query(query: str) -> bool:
        """Return True when query is a quantitative geometry question."""
        if not query or not query.strip():
            return False
        q = query.lower()
        return any(phrase in q for phrase in _SPATIAL_BYPASS_PHRASES)

    @staticmethod
    def report_intake_intent(query: str) -> Optional[str]:
        """Classify a fault/complaint/suggestion/safety/feedback REPORT.

        Returns the report-intake intent name
        ('safety_report' | 'maintenance' | 'complaint' | 'suggestion' |
        'feedback') for STATEMENTS that should be logged, or None otherwise.

        Questions ("is it too warm?", "is the lift broken?") return None — they
        are data/discovery queries, not reports. Used both to (a) bypass the KB
        router and (b) deterministically override the LLM intent downstream.
        """
        if not query or not query.strip():
            return None
        q = query.lower().strip()
        is_question = q.endswith("?") or q.startswith(_REPORT_QUESTION_STARTS)

        # Suggestions / feedback read as statements even when phrased politely.
        if any(p in q for p in _REPORT_SUGGESTION_PHRASES):
            return "suggestion"
        if any(p in q for p in _REPORT_FEEDBACK_PHRASES):
            return "feedback"
        # Fault / complaint / safety only when NOT a question.
        if not is_question:
            if any(p in q for p in _REPORT_SAFETY_PHRASES):
                return "safety_report"
            if any(p in q for p in _REPORT_FAULT_PHRASES):
                return "maintenance"
            if any(p in q for p in _REPORT_COMPLAINT_PHRASES):
                return "complaint"
        return None

    @staticmethod
    def is_report_intake_query(query: str) -> bool:
        """True when the query is a fault/complaint/suggestion/etc. report."""
        return SemanticRouter.report_intake_intent(query) is not None

    @staticmethod
    def is_control_command(query: str) -> bool:
        """True when the query is a physical actuation command (-> control).

        Three layers: literal command phrases, verb->target adjacency
        ("open the door"), and indirect/polite/ensure requests ("can you ensure
        every door is unlocked", "keep the windows open"). Status questions
        ("is the door locked?") are deliberately NOT matched.

        Automation-capability QUESTIONS ("can the building automatically close
        the blinds when it gets sunny?") are NOT commands — they must reach the
        T22 honest-capability path, not the control decline (fix 2026-06-12).
        """
        if not query or not query.strip():
            return False
        if _AUTOMATION_CAPABILITY_Q_RE.search(query):
            return False
        if _ADVICE_QUESTION_RE.search(query):
            return False
        if any(p in query.lower() for p in _CONTROL_COMMAND_PHRASES):
            return True
        if _CONTROL_VERB_TARGET_RE.search(query) or _CONTROL_ENSURE_RE.search(query):
            return True
        return False

    def register_intent(self, intent: str, collection_prefix: str) -> None:
        """Extension hook for adding new intent bindings (e.g. floor_plan later)."""
        self._intents[intent] = _IntentBinding(intent=intent, collection_prefix=collection_prefix)
        logger.info(f"[semantic_router] registered intent={intent} prefix={collection_prefix}")

    async def classify(self, query: str, building_id: str) -> SemanticRouteResult:
        """Classify a user query for a given building.  Intent-agnostic.

        Loops over all registered intents, searches each one's collection, and
        returns the WINNING intent (highest grouped score) — provided its score
        crosses the per-intent threshold band.

        Returns SemanticRouteResult. Never raises.
        """
        # Empty/whitespace queries — no embedding call needed
        if not query or not query.strip():
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source="semantic")

        # Too-short queries are vague/clarification requests; skip KB routing entirely.
        # A 1-3 word query like "It" or "that" has no semantic signal for KB matching
        # and will produce spurious high-score matches on short KB entry keywords.
        if len(query.split()) <= 3:
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source="semantic")

        # Data-query bypass: sensor/zone/discovery queries must go to SPARQL, not KB.
        # Check this BEFORE embedding so we pay zero cost on the fast path.
        if self.is_data_query(query):
            logger.debug(f"[semantic_router] data-query bypass (no KB lookup): '{query[:70]}'")
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source="semantic")

        # Floor-plan bypass: explicit floor plan / room visualisation requests
        # must reach the floor_plan agent which returns the actual PDF/image,
        # not a generic KB capability description.  Return intent directly so
        # downstream routing is deterministic, not heuristic.
        if self.is_floor_plan_query(query):
            logger.info(f"[semantic_router] floor-plan bypass: '{query[:70]}'")
            return SemanticRouteResult(intent="floor_plan", score=1.0, matches=[], source="bypass")

        # Spatial-query bypass: quantitative geometry (area, count, adjacency)
        # must reach the spatial_query agent which reads the DWG manifest.
        if self.is_spatial_query(query):
            logger.info(f"[semantic_router] spatial-query bypass: '{query[:70]}'")
            return SemanticRouteResult(
                intent="spatial_query", score=1.0, matches=[], source="bypass"
            )

        if not self._intents:
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source="disabled")

        # Embed query once — reused across all intent searches
        try:
            query_vec = await self._embedder.embed(query)
        except Exception as e:
            logger.warning(f"[semantic_router] embedding failed (fallback): {e}")
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source="fallback")

        # Search each registered intent's collection.
        # Track per-intent results to pick the highest-scoring intent.
        candidates: list = []  # [(intent_name, cfg, matches), ...]
        any_disabled = False
        any_fallback = False

        for intent_name, binding in self._intents.items():
            cfg = self._get_config_for_intent(building_id, intent_name)
            if cfg is None or not getattr(cfg, "enabled", False):
                any_disabled = True
                continue

            collection = f"{binding.collection_prefix}{building_id}"
            try:
                if intent_name == "capability":
                    # Capability uses the KB-backed multi-vector search (group-by entry_id)
                    matches = await self._search_capability(
                        query_vec=query_vec,
                        collection=collection,
                        building_id=building_id,
                        cfg=cfg,
                    )
                else:
                    # Generic intent search — descriptors → points, no entry lookup
                    matches = await self._search_generic_intent(
                        query_vec=query_vec,
                        collection=collection,
                        top_k=getattr(cfg, "top_k", 3),
                    )
            except Exception as e:
                logger.warning(
                    f"[semantic_router] search failed for intent={intent_name} "
                    f"collection={collection} (continuing): {e}"
                )
                any_fallback = True
                continue

            if matches:
                candidates.append((intent_name, cfg, matches))

        # Build the base decision (the documents rescue may override it below).
        if not candidates:
            source = (
                "fallback"
                if any_fallback
                else ("disabled" if any_disabled and len(self._intents) == 1 else "semantic")
            )
            base = SemanticRouteResult(intent=None, score=0.0, matches=[], source=source)
        else:
            # Pick the WINNING intent: highest top-score across all candidates
            winner_intent, winner_cfg, winner_matches = max(candidates, key=lambda c: c[2][0].score)
            top_score = winner_matches[0].score
            if top_score >= winner_cfg.override_min:
                base = SemanticRouteResult(
                    intent=winner_intent, score=top_score, matches=winner_matches, source="semantic"
                )
            elif top_score >= winner_cfg.threshold:
                base = SemanticRouteResult(
                    intent=None, score=top_score, matches=winner_matches, source="semantic"
                )
            else:
                base = SemanticRouteResult(
                    intent=None, score=top_score, matches=[], source="semantic"
                )

        # Document-KB rescue: when the query did NOT route to capability but a
        # building document strongly matches, route to capability so its
        # doc-search fallback grounds the answer. Policy / governance / privacy
        # questions live in documents_<bldg>, not capability.yaml, so without this
        # they fall through to a generic general-knowledge answer. (Data/spatial
        # queries already bypassed above, so this only affects info questions.)
        if base.intent != "capability" and _DOC_KB_ROUTING_ENABLED:
            doc_score = await self._documents_route_signal(query_vec, building_id)
            if doc_score >= _DOC_KB_ROUTE_THRESHOLD:
                logger.info(
                    f"[semantic_router] documents rescue (score={doc_score:.3f}) → capability"
                )
                return SemanticRouteResult(
                    intent="capability", score=doc_score, matches=[], source="documents"
                )

        return base

    async def _documents_route_signal(self, query_vec: List[float], building_id: str) -> float:
        """Top similarity score from the per-building documents collection (0.0 on miss).

        Pure routing signal: when the structured capability KB did not win but a
        policy/manual/governance document matches well, route the query to the
        capability node so its doc-search fallback can ground the answer. Never
        raises (a missing collection or outage degrades to 0.0 = no rescue).
        """
        collection = f"documents_{building_id}"
        try:
            if hasattr(self._qdrant, "query_points"):
                res = await self._qdrant.query_points(
                    collection_name=collection, query=query_vec, limit=1, with_payload=False
                )
                pts = res.points if hasattr(res, "points") else res
            else:
                pts = await self._qdrant.search(
                    collection_name=collection, query_vector=query_vec, limit=1, with_payload=False
                )
            return float(getattr(pts[0], "score", 0.0)) if pts else 0.0
        except Exception as e:
            logger.debug(f"[semantic_router] documents probe skipped: {e}")
            return 0.0

    def _get_config_for_intent(self, building_id: str, intent_name: str):
        """Returns per-intent config object (CapabilityRoutingConfig for capability,
        IntentRouteConfig for additional intents)."""
        if intent_name == "capability":
            return self._get_routing_config(building_id)

        # Other intents: read from intent_routing.<intent_name> block
        bldg_yaml = resolve_building_file(building_id, "building.yaml", self._input_root)
        if bldg_yaml is None:
            return None
        try:
            with open(bldg_yaml, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            block = (data.get("intent_routing") or {}).get(intent_name)
            if not block:
                return None
            return IntentRouteConfig(**block)
        except Exception as e:
            logger.warning(
                f"[semantic_router] intent config invalid for {building_id}/{intent_name}: {e}"
            )
            return None

    async def _search_generic_intent(
        self, query_vec, collection: str, top_k: int
    ) -> List[CapabilityMatch]:
        """Search a non-capability intent collection. Each point is a descriptor.

        Returns CapabilityMatch (reused as a generic container) with entry=None.
        The caller uses entry_id (which holds the descriptor index) only for logging.
        """
        if hasattr(self._qdrant, "query_points"):
            result = await self._qdrant.query_points(
                collection_name=collection,
                query=query_vec,
                limit=top_k,
                with_payload=True,
            )
            raw_points = result.points if hasattr(result, "points") else result
        else:
            raw_points = await self._qdrant.search(
                collection_name=collection,
                query_vector=query_vec,
                limit=top_k,
                with_payload=True,
            )
        matches = []
        for point in raw_points:
            payload = point.payload or {}
            matches.append(
                CapabilityMatch(
                    entry_id=str(payload.get("descriptor_idx", "?")),
                    score=float(getattr(point, "score", 0.0)),
                    entry=None,
                )
            )
        return matches

    # ── internal: routing config + KB loaders ──────────────────────────────────

    def _get_routing_config(self, building_id: str) -> CapabilityRoutingConfig:
        if building_id in self._config_cache:
            return self._config_cache[building_id]

        bldg_yaml = resolve_building_file(building_id, "building.yaml", self._input_root)
        if bldg_yaml is None:
            cfg = CapabilityRoutingConfig()
        else:
            try:
                with open(bldg_yaml, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                cfg = CapabilityRoutingConfig(**(data.get("capability_routing") or {}))
            except Exception as e:
                logger.warning(
                    f"[semantic_router] routing config invalid for {building_id}: "
                    f"{e} — falling back to defaults"
                )
                cfg = CapabilityRoutingConfig()
        self._config_cache[building_id] = cfg
        return cfg

    def _get_kb(self, building_id: str) -> Optional[CapabilityKB]:
        if building_id in self._kb_cache:
            return self._kb_cache[building_id]
        # Nested layout (input/<id>/capability.yaml) then FLAT layout
        # (input/capability.yaml — the active single-building layout). Mirrors
        # the capability agent's loader; without the flat fallback the router
        # could not resolve entry_id → CapabilityEntry, so every match came back
        # with entry=None and was filtered out (capability answers never grounded).
        for cap_yaml in (
            self._input_root / building_id / "capability.yaml",
            self._input_root / "capability.yaml",
        ):
            if not cap_yaml.exists():
                continue
            try:
                kb = CapabilityKB.from_yaml(cap_yaml)
                self._kb_cache[building_id] = kb
                return kb
            except Exception as e:
                logger.error(
                    f"[semantic_router] failed to load KB for {building_id} at {cap_yaml}: {e}"
                )
        return None

    # ── internal: Qdrant search + max-pool group-by ─────────────────────────────

    async def _search_capability(
        self,
        query_vec: List[float],
        collection: str,
        building_id: str,
        cfg: CapabilityRoutingConfig,
    ) -> List[CapabilityMatch]:
        """Return up to top_k distinct entries ranked by max-pool of point scores."""
        # Fetch raw points — pull more than top_k because we'll collapse to entries
        raw_top_k = max(cfg.top_k * 5, 20)
        # Newer Qdrant client uses query_points; older uses search.
        if hasattr(self._qdrant, "query_points"):
            result = await self._qdrant.query_points(
                collection_name=collection,
                query=query_vec,
                limit=raw_top_k,
                with_payload=True,
            )
            raw_points = result.points if hasattr(result, "points") else result
        else:
            raw_points = await self._qdrant.search(
                collection_name=collection,
                query_vector=query_vec,
                limit=raw_top_k,
                with_payload=True,
            )

        # Group by entry_id, max-pool the score
        per_entry: Dict[str, float] = {}
        for point in raw_points:
            payload = point.payload or {}
            entry_id = payload.get("entry_id")
            if not entry_id:
                continue
            score = float(getattr(point, "score", 0.0))
            if entry_id not in per_entry or score > per_entry[entry_id]:
                per_entry[entry_id] = score

        # Sort by score desc, take top_k
        ranked = sorted(per_entry.items(), key=lambda x: x[1], reverse=True)[: cfg.top_k]

        # Resolve entry_id → CapabilityEntry (for content lookup by caller)
        kb = self._get_kb(building_id)
        kb_index = {e.id: e for e in (kb.capabilities if kb else [])}

        return [
            CapabilityMatch(entry_id=eid, score=sc, entry=kb_index.get(eid)) for eid, sc in ranked
        ]

    async def search_capability_entries(
        self, query: str, building_id: str, min_score: float = 0.0
    ) -> List[CapabilityMatch]:
        """Threshold-free capability KB search for the agent answer fallback.

        Routing intentionally discards capability matches below the routing
        threshold (to avoid false-positive *routing*). But once the LLM has
        independently routed a query to the capability node, the agent still
        wants the best KB entries even when they sat just under that bar. This
        embeds `query`, searches the per-building capability collection, and
        returns resolved matches with ``score >= min_score``. Never raises.
        """
        binding = self._intents.get("capability")
        cfg = self._get_config_for_intent(building_id, "capability")
        if binding is None or cfg is None:
            return []
        try:
            query_vec = await self._embedder.embed(query)
            collection = f"{binding.collection_prefix}{building_id}"
            matches = await self._search_capability(query_vec, collection, building_id, cfg)
            return [m for m in matches if m.score >= min_score and m.entry is not None]
        except Exception as e:
            logger.warning(f"[semantic_router] capability fallback search failed: {e}")
            return []
