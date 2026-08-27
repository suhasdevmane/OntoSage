"""
semantic_router.py — deterministic query guards for intent routing.

Every function here is a PURE PREDICATE over the query string: given the same
text it returns the same verdict, with no embedding call, no vector search and
no per-building state. They answer the questions routing has to settle before
anything expensive runs — is this live data, a fault report, a control command,
a floor-plan or spatial question — and `routing_contract` composes them into the
ordered precedence rules that decide the lane.

Historically this module also held a stateful Qdrant router: it embedded the
query, searched a per-building ``capability_<bldg>`` collection built from
``capability.yaml``, and returned a routing verdict with matched KB entries.
That knowledge base was replaced by ``ontosage:Amenity`` /
``ontosage:KnowledgeTopic`` triples served by ``CapabilityGraphResolver``
(TODO-012), which left ``classify()`` and everything under it — the KB cache,
the routing-config loader, the collection searches — with no caller. It was
removed in TODO-081 along with ``capability_indexer`` and
``shared/capability_schema.py``.

Consequence worth knowing: routing no longer depends on Qdrant being reachable
or on an embedding model being loaded. A vector store outage can still cost a
document-grounded ANSWER, but it can no longer change which lane a question
takes.
"""

from __future__ import annotations

import re as _re
from typing import FrozenSet, Optional

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
#: Words asking for a MEASUREMENT of a space, paired below with the nouns that
#: name one. Kept as a two-part test rather than as more literal phrases in
#: _SPATIAL_BYPASS_PHRASES: that list already carried "how big is" but not "area
#: of room", so one phrasing of the same question reached the floor plan and
#: another was answered by the capability lane with "no information on record" --
#: about a room whose measured area the manifest was holding. Enumerating
#: phrasings loses that race indefinitely; enumerating the two ingredients does
#: not.
_SPACE_MEASURE_WORDS: FrozenSet[str] = frozenset(
    [
        "area",
        "how big",
        "how large",
        "size of",
        "square met",
        "square feet",
        "dimensions",
        "perimeter",
        "floor space",
    ]
)

#: Generic nouns only. A room identifier ("0.34", "RM001A") is the stronger
#: signal but its shape differs per building, and hard-coding one here would put
#: a building literal into shared routing code.
_SPACE_NOUNS: FrozenSet[str] = frozenset(
    [
        "room",
        "rooms",
        "space",
        "spaces",
        "office",
        "offices",
        "lab",
        "labs",
        "theatre",
        "theater",
    ]
)

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
        # V5-T27 — nearest-facility + accessible-route shapes reach the
        # route finder instead of the amenity-info capability probe. Facility-
        # specific on purpose: bare "nearest" would steal data questions.
        "nearest toilet",
        "closest toilet",
        "nearest lift",
        "closest lift",
        "nearest stair",
        "closest stair",
        "nearest kitchen",
        "closest kitchen",
        "nearest exit",
        "closest exit",
        "nearest meeting room",
        "closest meeting room",
        "nearest reception",
        "step-free route",
        "step free route",
        "wheelchair route",
        "wheelchair accessible route",
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

# BUG-157: "Fix the temperature in here." The verb-target rule above pairs actuation
# verbs with PLANT nouns (hvac, thermostat, damper) — the things an engineer names.
# Occupants name the QUANTITY instead ("the temperature", "the stuffiness"), and the
# verb they reach for is "fix"/"sort out", which was in neither list. So an actuation
# request fell through to analytics and was answered with real AHU temperatures:
# the system did nothing while sounding like it had acted.
_CONTROL_COMFORT_FIX_RE = _re.compile(
    r"\b(fix|sort(?:\s+out)?|do\s+something\s+about|deal\s+with|see\s+to|sort\s+me\s+out)\b"
    r".{0,30}?\b(temperature|temp|heating|heat|cooling|humidity|air|airflow|"
    r"ventilation|stuffiness|stuffy|draught|draft|noise|brightness|co2)\b",
    _re.IGNORECASE,
)

# ...but a fix VERB alone does not make a command. These shapes contain one and are
# not requests to act: instruction-seeking ("how do I fix the temperature myself?")
# and maintenance history ("when was the thermostat last fixed?"). Checked first.
_COMFORT_FIX_NOT_COMMAND_RE = _re.compile(
    r"^\s*(?:how|when|who|why|what|where)\b"
    r"|\b(?:was|were|has\s+been|had\s+been|got)\s+(?:\w+\s+){0,2}?fixed\b",
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


class SemanticRouter:
    """Deterministic, stateless query guards used by intent routing.

    This class was once a stateful Qdrant router: it embedded a query, searched
    a per-building ``capability_<bldg>`` collection built from ``capability.yaml``
    and returned a routing verdict. That knowledge base was replaced by
    ``ontosage:Amenity`` / ``ontosage:KnowledgeTopic`` triples answered by
    ``CapabilityGraphResolver`` (TODO-012), which left ``classify()`` — and the
    search, config-loading and KB-caching machinery beneath it — with no caller
    at all. All of it is gone (TODO-081).

    What remains, and what was always the load-bearing part, are the ``is_*``
    predicates below: pure functions over the query string that decide whether a
    question is live-data, a report, a control command, floor-plan or spatial.
    ``routing_contract`` and ``dialogue_agent`` call them ON THE CLASS, never on
    an instance, so nothing needs constructing, wiring at boot, or a Qdrant
    connection to make a routing decision.
    """

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
            # ...unless the question asks WHERE something can be done or found.
            # "Where can I fill my water bottle on floor 3?" names a floor and
            # contains "water", so it was promoted to sensor_data and answered with
            # the floor plan, while the building's twelve refill points sat in a
            # lane the question never reached (BUG-337, measured live). The shape
            # decides, not the noun -- one owner, in the routing contract.
            from orchestrator.services.routing_contract import (  # local: avoids a cycle
                amenity_seeking_question,
            )

            if not amenity_seeking_question(query):
                return True
        if any(phrase in q for phrase in _DATA_BYPASS_PHRASES):
            return True
        # 5. A quantity question about something this building METERS. Checks 1-4
        #    recognise a data question by sensor id, room id or a fixed phrase
        #    list, so a metered quantity phrased without any of those was
        #    invisible here — and this function is the FIRST condition of the
        #    capability short-circuit bypass, so being invisible meant the
        #    capability lane answered before the classifier ever ran. Measured
        #    2026-08-25: "how many parking bays are free right now?" was answered
        #    with the building's catering amenities while a parking sensor sat in
        #    the graph with 5,090 rows behind it. The vocabulary comes from the
        #    building's own modality config, not another literal list here.
        from orchestrator.services.routing_contract import (  # local: avoids a cycle
            metered_quantity_question,
        )

        return metered_quantity_question(query)

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
        if any(phrase in q for phrase in _SPATIAL_BYPASS_PHRASES):
            return True
        return SemanticRouter.is_space_geometry_question(query)

    @staticmethod
    def is_space_geometry_question(query: str) -> bool:
        """True for "how big is room X" / "the area of office Y".

        A measurement OF a space, not a reading taken inside one: "how warm is
        room 3.01" asks a sensor question and must not match. Shared with the
        routing contract so the capability bypass and the intent override cannot
        disagree about what counts as a geometry question -- they did, and the
        result was that one phrasing answered with the room's area while another
        told the user no such information existed.
        """
        if not query or not query.strip():
            return False
        q = query.lower()
        if not any(w in q for w in _SPACE_MEASURE_WORDS):
            return False
        return any(_re.search(rf"\b{n}\b", q) for n in _SPACE_NOUNS)

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
        # BUG-157: comfort-quantity fix requests ("fix the temperature in here"),
        # excluding the question shapes that merely contain a fix verb.
        if _CONTROL_COMFORT_FIX_RE.search(query) and not _COMFORT_FIX_NOT_COMMAND_RE.search(query):
            return True
        return False
