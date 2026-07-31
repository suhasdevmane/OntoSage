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


def _r_forecast(c: _Ctx) -> Optional[str]:
    if c.intent in ("trend", "analytics", "sensor_data"):
        return None
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
    if c.intent not in (
        "capability",
        "general",
        "greeting",
        "metadata",
        "clarification",
        "discovery",
        None,
    ):
        return None
    return c.sr.report_intake_intent(c.query)


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


# Precedence order is the contract. Historical rules keep their historical order;
# the two automation-shape rules (2026-07-30) slot after the report-intake pair so
# genuine reports and comfort questions still win.
PARSE_STAGE_RULES: Tuple[Rule, ...] = (
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
)

POST_STAGE_RULES: Tuple[Rule, ...] = (
    Rule(
        "data_query_promotion",
        "place + measurable reading question → sensor_data (guarded against counts)",
        _r_data_query_promotion,
        preserve_analytics=True,
    ),
)

_STAGES: Dict[str, Tuple[Rule, ...]] = {
    "parse": PARSE_STAGE_RULES,
    "post": POST_STAGE_RULES,
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
    return applied
