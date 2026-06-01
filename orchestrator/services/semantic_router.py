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

import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Literal, Optional

import yaml

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

# ── Data-keyword exclusion for floor-plan bypass ──────────────────────────────
# When a query mentions "floor N" AND data/analytics keywords, it is a data
# request, not a floor plan visualisation request.  Queries like
# "Show average temperature trend for floor 2 last week" must NOT be routed
# to floor_plan even though they contain "show" and "floor 2".
_DATA_ANALYTIC_WORDS: FrozenSet[str] = frozenset([
    "temperature", "co2", "humidity", "noise", "occupancy", "pressure",
    "sensor", "reading", "level", "value", "measurement",
    "trend", "average", "mean", "analytics", "analysis", "statistics",
    "energy", "consumption", "usage", "power", "kw", "kwh",
    "report", "compare", "comparison", "forecast", "predict",
    "last week", "last month", "last hour", "yesterday", "today",
    "over time", "time series", "historical", "current reading",
    "highest", "lowest", "maximum", "minimum", "variance", "std",
    "anomaly", "spike", "alert", "threshold", "exceed",
])

# Phrase-level signals: any of these substrings in the lowercased query → bypass.
_DATA_BYPASS_PHRASES: FrozenSet[str] = frozenset([
    # Enumeration / listing queries
    "list all sensors",   "list all temperature sensors", "list all co2 sensors",
    "list all humidity sensors", "list all noise sensors", "list all occupancy sensors",
    "list all zones",     "list all floors",  "list all hvac",
    "list the sensors",   "list the zones",   "show all sensors",
    "show me all sensors",
    # Counting queries
    "how many zones",     "how many sensors",  "how many floors",
    "how many rooms",     "how many co2 sensors", "how many temperature sensors",
    "how many humidity sensors", "how many noise sensors",
    "number of sensors",  "number of zones",   "number of floors",
    # Lookup / membership queries
    "which sensors are in", "which sensors are on",
    "what sensors are in",  "what sensors are on",
    "sensors in zone",      "sensors on floor",
    # Sensor-type discovery (asking SPARQL, not KB description)
    "what sensor types",  "sensor types installed", "types of sensors installed",
    "what types of sensors", "sensor types available",
    # HVAC equipment listing via SPARQL
    "what hvac equipment", "list all hvac equipment", "hvac equipment installed",
    "hvac equipment in the building",
    # UUID / metadata lookup
    "uuid for", "what is the uuid", "get the uuid",
    # Report / analytics pipeline queries — these go to SPARQL+SQL+report, not KB
    "maintenance report", "energy report", "generate report", "generate a report",
    "create a report", "show me a report", "build a report",
    "weekly report", "monthly report", "daily report", "annual report",
    "temperature report", "co2 report", "sensor report", "hvac report",
    "trend report", "analytics report", "compliance report",
    "show me a maintenance", "maintenance summary", "maintenance schedule",
    "show trend", "show average", "show analysis", "statistical analysis",
    "sensor variance", "sensor readings for", "historical data",
    "energy consumption", "energy usage trend", "power consumption",
    # Anomaly / alert pipeline queries
    "anomaly detection", "detect anomaly", "temperature spike",
    "alert me if", "notify me when", "warn me if", "set an alert",
    "if co2 exceeds", "if temperature goes above", "if humidity drops",
    "threshold exceeded", "out of range", "unusual reading",
    # Maintenance schedule / ticket queries — go to maintenance intent, not KB
    "maintenance schedule", "scheduled maintenance", "planned maintenance",
    "maintenance this week", "maintenance this month", "maintenance next",
    "open maintenance tickets", "outstanding maintenance", "maintenance tasks",
    "maintenance work scheduled", "what maintenance", "maintenance is scheduled",
    "scheduled for", "is scheduled for building maintenance",
])

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

_FLOOR_PLAN_BYPASS_PHRASES: FrozenSet[str] = frozenset([
    "floor plan", "floorplan", "floor map", "building map", "building layout",
    "show me floor", "see floor", "see the floor", "view floor",
    "show me the layout", "show me the plan", "room layout", "open the plan",
    "actual rooms", "actual layout", "see the rooms", "see the actual rooms",
    "where is room", "where is the room", "where is zone", "where is the zone",
    "locate the room", "locate the zone", "find the room", "find the zone",
    "show me where", "navigate to", "directions to",
    "building overview", "building directory",
])

# ── Spatial-query bypass ─────────────────────────────────────────────────────
# Quantitative geometry queries (area, count, adjacency) must reach the
# spatial_query agent which reads the DWG manifest, not the KB router.
_SPATIAL_BYPASS_PHRASES: FrozenSet[str] = frozenset([
    "area of floor", "total area of", "how big is",
    "adjacent to", "next to room", "rooms adjacent",
    "largest room", "smallest room", "biggest room",
    "room sizes", "room areas", "room dimensions",
    "square meters", "square metres", "square feet",
])


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
          3. Known data-query phrases (enumeration, counting, lookup)
        """
        if not query or not query.strip():
            return False
        q = query.lower()
        if _SENSOR_ID_RE.search(query):
            return True
        if _ZONE_ID_RE.search(query):
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
        # Phrase matches
        if any(phrase in q for phrase in _FLOOR_PLAN_BYPASS_PHRASES):
            return True
        # Floor number + visual verb (only when no data keywords present — checked above)
        # "show me floor 5", "open floor 3", "view the 2nd floor"
        if _FLOOR_NUMBER_RE.search(query) and any(
            v in q for v in (
                "show", "open", "view", "see", "display", "give me", "pull up",
                "bring up", "draw", "plan", "layout", "map",
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
            return SemanticRouteResult(
                intent="floor_plan", score=1.0, matches=[], source="bypass"
            )

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

        # No registered intent's collection returned matches
        if not candidates:
            source = "fallback" if any_fallback else (
                "disabled" if any_disabled and len(self._intents) == 1 else "semantic"
            )
            return SemanticRouteResult(intent=None, score=0.0, matches=[], source=source)

        # Pick the WINNING intent: highest top-score across all candidates
        winner_intent, winner_cfg, winner_matches = max(
            candidates, key=lambda c: c[2][0].score
        )
        top_score = winner_matches[0].score

        # Decision based on winning intent's per-intent thresholds
        if top_score >= winner_cfg.override_min:
            return SemanticRouteResult(
                intent=winner_intent, score=top_score,
                matches=winner_matches, source="semantic",
            )
        elif top_score >= winner_cfg.threshold:
            return SemanticRouteResult(
                intent=None, score=top_score,
                matches=winner_matches, source="semantic",
            )
        else:
            return SemanticRouteResult(
                intent=None, score=top_score, matches=[], source="semantic",
            )

    def _get_config_for_intent(self, building_id: str, intent_name: str):
        """Returns per-intent config object (CapabilityRoutingConfig for capability,
        IntentRouteConfig for additional intents)."""
        if intent_name == "capability":
            return self._get_routing_config(building_id)

        # Other intents: read from intent_routing.<intent_name> block
        bldg_yaml = self._input_root / building_id / "building.yaml"
        if not bldg_yaml.exists():
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
                collection_name=collection, query=query_vec,
                limit=top_k, with_payload=True,
            )
            raw_points = result.points if hasattr(result, "points") else result
        else:
            raw_points = await self._qdrant.search(
                collection_name=collection, query_vector=query_vec,
                limit=top_k, with_payload=True,
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

        bldg_yaml = self._input_root / building_id / "building.yaml"
        if not bldg_yaml.exists():
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
        cap_yaml = self._input_root / building_id / "capability.yaml"
        if not cap_yaml.exists():
            return None
        try:
            kb = CapabilityKB.from_yaml(cap_yaml)
            self._kb_cache[building_id] = kb
            return kb
        except Exception as e:
            logger.error(f"[semantic_router] failed to load KB for {building_id}: {e}")
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
            CapabilityMatch(entry_id=eid, score=sc, entry=kb_index.get(eid))
            for eid, sc in ranked
        ]
