"""
MultiIntentDetector — Post-classification compound query decomposition.

Runs AFTER the dialogue agent classifies a single primary intent.  When the
user's query contains multiple distinct sub-tasks spanning different intent
domains, this module decomposes it into a list of SubIntent objects that the
enhanced PlannerAgent can execute sequentially.

Two-stage gate ensures single-intent queries (95%+ of traffic) pay only a
<1ms heuristic check — no LLM call, no additional I/O.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestrator.llm_manager import llm_manager
from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Phase 6 — populated from the intent registry (orchestrator/intents) so adding
# a new intent in YAML automatically extends the multi-intent detector.  The
# legacy hardcoded set is preserved as a fallback when the registry can't load.
_LEGACY_VALID_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "anomaly",
        "compare",
        "trend",
        "recommend",
        "compliance",
        "report",
        "export",
        "planner",
        "floor_plan",
        "spatial_query",
        "capability",
        "control",
        "maintenance",
        "discovery",
        "metadata",
        "general",
        "clarification",
    }
)


def _load_valid_intents() -> frozenset:
    try:
        from orchestrator.intents import get_intent_registry

        names = get_intent_registry().names()
        if names:
            return names
    except Exception:
        pass
    return _LEGACY_VALID_INTENTS


VALID_INTENTS = _load_valid_intents()

INTENT_DOMAINS: Dict[str, frozenset] = {
    "data": frozenset(
        {
            "temperature",
            "co2",
            "humidity",
            "sensor",
            "reading",
            "energy",
            "consumption",
            "occupancy",
            "current",
            "latest",
            "average",
            "level",
            "noise",
            "light",
            "power",
            "watt",
            "kwh",
        }
    ),
    "anomaly": frozenset(
        {
            "unusual",
            "anomaly",
            "anomalies",
            "spike",
            "fault",
            "flagged",
            "alert",
            "abnormal",
            "out of range",
        }
    ),
    "capability": frozenset(
        {
            "contact",
            "book",
            "booking",
            "who should",
            "who do i",
            "how do i",
            "policy",
            "opening hours",
            "lift",
            "elevator",
            "accessible",
            "facilities",
            "wifi",
            "parking",
            "reception",
            "report maintenance",
            "how to report",
        }
    ),
    "floor_plan": frozenset(
        {
            "floor plan",
            "layout",
            "show me floor",
            "where is",
            "locate",
            "navigate",
            "map",
            "building overview",
        }
    ),
    "spatial": frozenset(
        {
            "area",
            "size",
            "how many rooms",
            "adjacent",
            "square",
            "how big",
            "largest",
            "smallest",
            "room count",
        }
    ),
    "report": frozenset(
        {
            "generate report",
            "create report",
            "building report",
            "weekly report",
            "daily report",
            "monthly report",
            "summary report",
            "energy report",
            "summarise",
            "summarize",
            "give me a summary",
        }
    ),
    "recommend": frozenset(
        {
            "recommend",
            "suggest",
            "should i",
            "advice",
            "optimize",
            "improve",
            "what should",
            "best room",
            "most comfortable",
        }
    ),
    "compare": frozenset(
        {
            "compare",
            "comparison",
            "vs",
            "versus",
            "difference between",
            "higher than",
            "lower than",
            "better",
            "worse",
        }
    ),
}

_CONNECTIVE_PHRASES = [
    "and also",
    "as well as",
    "plus ",
    "additionally",
    "in addition",
    "can you also",
    "also tell",
    "also let",
    "also check",
    "also show",
    "tell me",
    "let me know",
    "and let me",
    "and tell me",
    "and remind me",
    "and show me",
    "and check",
    "first ",
    "then ",
    "finally ",
    "first,",
    "then,",
    "finally,",
    "1)",
    "2)",
    "3)",
    "1.",
    "2.",
    "3.",
    ", and how",
    ", how do",
    ", how big",
    ", how many",
    ", and do",
    ", and can",
    ", and what",
    ", and which",
    "? and ",
    "? how ",
    "? what ",
    "? which ",
]


@dataclass
class SubIntent:
    """A single decomposed sub-task."""

    sub_query: str
    intent: str
    entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sub_query": self.sub_query,
            "intent": self.intent,
            "entities": self.entities,
        }


class MultiIntentDetector:
    """Detects and decomposes compound queries into sub-intents."""

    async def detect(
        self,
        query: str,
        primary_intent: str,
        entities: Optional[List[str]] = None,
    ) -> Optional[List[SubIntent]]:
        """Return a list of SubIntents if the query is compound, else None."""
        if not settings.MULTI_INTENT_ENABLED:
            return None

        if not self._passes_heuristic(query):
            return None

        return await self._decompose(query, primary_intent, entities or [])

    def _passes_heuristic(self, query: str) -> bool:
        """Fast string-matching gate — rejects obviously single-intent queries."""
        if len(query) < settings.MULTI_INTENT_MIN_LENGTH:
            return False

        q_lower = query.lower()

        has_connective = any(phrase in q_lower for phrase in _CONNECTIVE_PHRASES)
        if not has_connective:
            return False

        matched_domains = set()
        for domain, keywords in INTENT_DOMAINS.items():
            for kw in keywords:
                if kw in q_lower:
                    matched_domains.add(domain)
                    break
        if len(matched_domains) < 2:
            return False

        return True

    async def _decompose(
        self,
        query: str,
        primary_intent: str,
        entities: List[str],
    ) -> Optional[List[SubIntent]]:
        """LLM call to decompose a compound query into sub-intents."""
        prompt = f"""You are a query decomposition module for a smart building assistant.

The user sent a compound query that contains multiple distinct sub-tasks.
Break it into separate sub-tasks, each with its own intent.

User query: "{query}"

Primary intent already detected: "{primary_intent}"

Available intents (pick the most specific for each sub-task):
- "analytics"      : Statistical data query (temperature, CO2, humidity readings, averages)
- "anomaly"        : Detect unusual readings, spikes, faults
- "compare"        : Side-by-side comparison of sensors, zones, or time periods
- "trend"          : How a metric changed over time
- "recommend"      : Actionable advice, suggestions, best options
- "compliance"     : Check against standards (ASHRAE, WELL, etc.)
- "report"         : Generate a structured summary report
- "export"         : Export data to file (CSV, JSON)
- "floor_plan"     : Show floor layout, locate a room
- "spatial_query"  : Room sizes, counts, areas, adjacency
- "capability"     : Building policies, contacts, booking, facilities info
- "maintenance"    : Report a fault, raise a ticket
- "discovery"      : Explore available sensors and building structure
- "sensor_data"    : Current or historical sensor readings

Rules:
- Each sub-task must be a DISTINCT action — don't split one task into artificial steps
- The primary intent "{primary_intent}" should be one of the sub-tasks
- Minimum 2 sub-tasks, maximum 5
- Each sub-task needs a concise natural language query that could stand alone

Return ONLY a JSON array:
[
  {{"sub_query": "...", "intent": "...", "entities": [...]}},
  {{"sub_query": "...", "intent": "...", "entities": [...]}}
]"""

        try:
            response = await llm_manager.generate(prompt, temperature=0.0)
            match = re.search(r"\[[\s\S]*\]", response)
            if not match:
                logger.warning("[multi-intent] LLM returned no JSON array")
                return None

            items = json.loads(match.group(0))
            if not isinstance(items, list) or len(items) < 2:
                return None

            sub_intents = []
            for item in items[:5]:
                intent = item.get("intent", "").strip().lower()
                if intent not in VALID_INTENTS:
                    logger.debug(f"[multi-intent] Dropping invalid intent: {intent}")
                    continue
                sub_intents.append(
                    SubIntent(
                        sub_query=item.get("sub_query", ""),
                        intent=intent,
                        entities=item.get("entities", []),
                    )
                )

            if len(sub_intents) < 2:
                return None

            logger.info(
                f"[multi-intent] Decomposed into {len(sub_intents)} sub-intents: "
                f"{[s.intent for s in sub_intents]}"
            )
            return sub_intents

        except json.JSONDecodeError as e:
            logger.warning(f"[multi-intent] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"[multi-intent] Decomposition failed (non-fatal): {e}")
            return None
