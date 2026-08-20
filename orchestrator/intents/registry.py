"""
Intent registry — Phase 6 single source of truth for intent metadata.

Loads `intent_definitions.yaml` at import time and exposes:

  - `IntentDefinition`     Pydantic model with one record per intent
  - `IntentRegistry`       lookup + grouping API
  - `get_intent_registry()` cached singleton

Consumers:
  - dialogue_agent._build_intent_detection_prompt → reads definitions/examples
  - multi_intent_detector.VALID_INTENTS          → reads `.names()`
  - planner_agent _DATA_PIPELINE_AGENTS          → reads `.in_group("data")`
  - planner_agent _STANDALONE_AGENTS             → reads `.in_group("standalone")`

When the YAML is missing or malformed the registry falls back to the
hardcoded `_DEFAULT_INTENTS` table so the orchestrator still boots.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────


class IntentDefinition(BaseModel):
    """Declarative metadata about a single intent.

    Read by the dialogue agent (to build its LLM prompt), the planner
    (to decide whether the intent needs data-pipeline prefix), and the
    multi-intent detector (to validate decomposed sub-intents).
    """

    name: str = Field(..., description="Canonical intent name, e.g. 'floor_plan'")
    description: str = Field(..., description="One-paragraph definition shown to the LLM")
    examples: List[str] = Field(default_factory=list, description="Example user queries")
    pipeline_group: str = Field(
        default="standalone",
        description="'data' (needs sparql/sql prefix), 'standalone' (self-contained), or 'meta' (clarification/greeting)",
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Legacy or synonymous names that also resolve here",
    )
    cacheable: bool = Field(
        default=True,
        description="Whether responses for this intent can be cached",
    )
    # Phase 6D — explicit workflow routing target.  When None, default rules
    # apply based on pipeline_group:
    #   data       → "sparql"  (needs UUID lookup first)
    #   standalone → intent name (e.g. floor_plan, capability — expects a node of the same name)
    #   meta       → "response"
    # Override examples: report → "planner", export → "export", visualization → "visualization"
    route_target: Optional[str] = Field(
        default=None,
        description="Workflow node to route to; None applies pipeline_group defaults",
    )
    # Phase 13B — explicit pointer to the WorkflowOrchestrator method that
    # implements this intent's node.  When set, `_build_graph` registers the
    # node automatically; otherwise the caller must hardcode it.  Pipeline
    # stages (sparql, sql, analytics, response, dialogue) deliberately leave
    # this empty because they are shared infrastructure, not 1:1 with intents.
    node_method: Optional[str] = Field(
        default=None,
        description=(
            "Name of the WorkflowOrchestrator method to register as this "
            "intent's graph node, e.g. '_floor_plan_node'.  When unset, the "
            "node is assumed to already exist (legacy / shared pipeline stage)."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Default data — used when YAML is missing.  Mirrors the existing hardcoded
# taxonomy in dialogue_agent.py / planner_agent.py / multi_intent_detector.py.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_INTENTS: List[IntentDefinition] = [
    IntentDefinition(
        name="general",
        description="General knowledge / greetings / non-building questions.",
        examples=['"Hello"', '"What can you do?"', '"What is HVAC?"'],
        pipeline_group="meta",
        cacheable=False,
    ),
    IntentDefinition(
        name="metadata",
        description="Static structure queries — list entities, look up types, describe a thing.",
        examples=[
            '"What sensors are in zone 5?"',
            '"What type of sensor is X?"',
            '"List all floors."',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="discovery",
        description="Explore available sensors, zones, data types, system capabilities.",
        examples=[
            '"What can I monitor?"',
            '"Show me all available data types."',
            '"How many sensors does the building have?"',
        ],
        pipeline_group="data",
        cacheable=False,
    ),
    IntentDefinition(
        name="analytics",
        description=(
            "ONLY for direct statistical computation on a single dataset — averages, "
            "min/max, sums, counts, histograms, distribution, current readings. "
            "NOT for comparisons, NOT for recommendations."
        ),
        examples=[
            '"What is the average CO2 last week?"',
            '"Show temperature history for zone 5."',
            '"Current humidity?"',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="compare",
        description=(
            "Side-by-side comparison of TWO OR MORE sensors, zones, floors, or time periods. "
            'ALWAYS use this when the user says "compare", "vs", "versus", "difference between", '
            '"higher/lower than", "which is better/worse", or names two distinct things.'
        ),
        examples=[
            '"Compare air quality between floor 1 and floor 5."',
            '"Is zone 3 hotter than zone 5?"',
            '"How does this week compare to last week?"',
        ],
        aliases=["comparison"],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="trend",
        description=(
            "How a single metric has CHANGED OVER TIME — increasing, decreasing, stable, "
            "rate of change."
        ),
        examples=[
            '"Is energy consumption trending up?"',
            '"How has CO2 changed since Monday?"',
            '"Is temperature rising?"',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="recommend",
        description=(
            "Request ACTIONABLE ADVICE — what to change, how to improve, what settings to use. "
            'ALWAYS use this when the user says "recommend", "suggest", "should I", "how can I improve", '
            '"what settings", "optimize", "what should I do", "tips", "advice".'
        ),
        examples=[
            '"What HVAC settings do you recommend?"',
            '"How can I improve air quality?"',
            '"Suggest energy saving measures."',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="anomaly",
        description="Detect out-of-range, spike, drop, or unusual sensor readings.",
        examples=[
            '"Any unusual readings today?"',
            '"Are there temperature spikes?"',
            '"Detect anomalies in CO2."',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="report",
        description="Generate a structured building report (daily/weekly summary, full energy report).",
        examples=[
            '"Generate a weekly energy report."',
            '"Create a building summary."',
            '"Daily occupancy report."',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="export",
        description="Export query results or report to a file (CSV, JSON, HTML, Markdown).",
        examples=[
            '"Export last week\'s data as CSV."',
            '"Download the report as JSON."',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="compliance",
        description=(
            "Check sensor readings against regulatory or comfort standards "
            "(ASHRAE, WELL, BREEAM, EN15251)."
        ),
        examples=[
            '"Is zone 5 within ASHRAE 55 limits?"',
            '"Check BREEAM compliance."',
            '"Is CO2 within safe limits?"',
        ],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="planner",
        description="Multi-step task requiring multiple agents or producing multiple outputs.",
        examples=[
            '"Generate CO2 report and export as CSV."',
            '"Analyse energy, then create a chart and export."',
        ],
        pipeline_group="meta",
    ),
    IntentDefinition(
        name="control",
        description=(
            "User issues a command to physically change a building system state. "
            "Entities: device (the system to control), action (set/on/off/lock/"
            'unlock/increase/decrease), target_value (e.g. "21°C", "50%"), zone/room.'
        ),
        examples=[
            '"Set HVAC zone 3 to 21°C"',
            '"Turn off the lights in room 2.04"',
            '"Lock down floor 4"',
            '"Increase ventilation in Lab 3.07"',
        ],
        pipeline_group="standalone",
        cacheable=False,
    ),
    IntentDefinition(
        name="maintenance",
        description=(
            "User reports a fault, raises a work order, checks ticket status, "
            'or updates a maintenance ticket. Trigger phrases: "broken", "not working", '
            '"report fault", "raise ticket", "fix the", "maintenance request", '
            '"check ticket", "status of MT-". Entities: device, location, '
            "fault_description, ticket_id (format MT-XXXX), assignee."
        ),
        examples=[],
        pipeline_group="standalone",
        cacheable=False,
    ),
    IntentDefinition(
        name="clarification",
        description="Query is too vague to proceed without more information.",
        examples=[
            '"Show me data." (no sensor/zone specified)',
            '"What happened?" (no context)',
        ],
        pipeline_group="meta",
        cacheable=False,
    ),
    IntentDefinition(
        name="floor_plan",
        description=(
            "User wants to see a floor plan, locate a room/zone/sensor on a floor, "
            "navigate the building layout, or get a building overview. "
            'ALWAYS use this when the user says: "floor plan", "show me floor", "layout", '
            '"where is [room/zone/facility]", "which floor is", "locate", "find my location", '
            '"building map", "navigate", "directions to", "how do I get to", '
            '"where can I find", "building directory", "building overview", "all floors", '
            '"which floor has", "find the office", "where is the lab", "server room location", '
            '"toilet", "meeting room location", "lift", "elevator", "staircase", '
            "or mentions a floor number with spatial/location intent."
        ),
        examples=[
            '"Show me floor 3 plan."',
            '"Where is zone 5.12?"',
            '"Which floor am I on?"',
            '"Where is the server room?"',
            '"Give me a building overview."',
        ],
        pipeline_group="standalone",
    ),
    IntentDefinition(
        name="spatial_query",
        description=(
            "User asks quantitative/analytical geometry questions about the building — "
            "room sizes, areas, adjacency relationships, counts, or MEP block locations. "
            "Use this when the user asks ABOUT DATA derived from the floor plan, not to SEE it. "
            'DISAMBIGUATION: "show me / where is / find" -> "floor_plan". '
            '"how many / area / size / adjacent" -> "spatial_query".'
        ),
        examples=[
            '"Which rooms are larger than 50 m²?"',
            '"What is the total area of floor 3?"',
            '"How many meeting rooms are on floor 4?"',
            '"Which rooms are adjacent to 3.01?"',
        ],
        pipeline_group="standalone",
    ),
    IntentDefinition(
        name="sensor_data",
        description="Current or historical sensor readings for a specific sensor.",
        examples=['"What is the current temperature in zone 5.28?"'],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="capability",
        description="Off-ontology / building capability queries (policies, amenities, contacts).",
        examples=['"Where is the prayer room?"', '"How do I report a fault?"'],
        pipeline_group="standalone",
    ),
    IntentDefinition(
        name="visualization",
        description="Plot or chart a metric.",
        examples=['"Plot temperature in zone 5.28 over the last 24h."'],
        pipeline_group="data",
    ),
    IntentDefinition(
        name="greeting",
        description="Friendly greeting; no information request.",
        examples=['"Hi"', '"Good morning"'],
        pipeline_group="meta",
        cacheable=False,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Loader
# ─────────────────────────────────────────────────────────────────────────────


# System-shipped defaults (lowest precedence).
_REGISTRY_SEARCH_PATHS = [
    Path("/app/orchestrator/intents/intent_definitions.yaml"),
    Path("orchestrator/intents/intent_definitions.yaml"),
]

# User overlay locations — searched in order, later wins.  Mirrors the
# `input/` convention used for buildings, personas, capability KBs, etc.


def _overlay_search_paths(building_id: Optional[str]) -> List[Path]:
    """Return user-overlay YAML paths, lowest precedence first.

    Search order (later wins):
      1. input/_defaults/intents.yaml  — operator-editable global defaults
      2. input/intents.yaml            — legacy global overlay (back-compat)
      3. input/<building_id>/intents.yaml — per-building override
    """
    paths: List[Path] = []
    # Phase 11C — operator-editable defaults under input/_defaults/ so the
    # entire mutable surface lives under input/.  Lowest user-overlay precedence;
    # shipped orchestrator/intents/intent_definitions.yaml is still the baseline.
    for base in (Path("/app/input"), Path("input")):
        paths.append(base / "_defaults" / "intents.yaml")
    # Global user overlay (back-compat)
    for base in (Path("/app/input"), Path("input")):
        paths.append(base / "intents.yaml")
    # Per-building overlay (wins over global)
    if building_id:
        for base in (Path("/app/input"), Path("input")):
            paths.append(base / building_id / "intents.yaml")
    return paths


def _load_yaml_file(path: Path) -> List[Dict]:
    """Return the raw `intents:` list from a YAML file, or [] on any error."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        items = raw.get("intents", [])
        if not isinstance(items, list):
            logger.warning(f"[intent_registry] {path} has non-list intents block; ignored")
            return []
        return items
    except Exception as e:
        logger.warning(f"[intent_registry] failed to load {path}: {e}")
        return []


def _load_yaml(building_id: Optional[str] = None) -> List[IntentDefinition]:
    """Merge system defaults + user overlays.  Last writer of each `name:` wins.

    Search order (later overrides earlier):
      0. hardcoded `_DEFAULT_INTENTS`                    (always — baseline)
      1. orchestrator/intents/intent_definitions.yaml    (shipped defaults — REPLACE the baseline)
      2. input/intents.yaml                               (global user overlay — MERGE)
      3. input/<building_id>/intents.yaml                 (per-building overlay — MERGE)

    The shipped YAML, when present, replaces the hardcoded baseline.  The
    overlays then merge on top.  If neither shipped YAML nor overlays produce
    any intents, the hardcoded baseline is returned unchanged.
    """
    merged: Dict[str, Dict] = {}

    # 1. Shipped defaults (REPLACE the baseline when present)
    shipped_loaded = False
    for path in _REGISTRY_SEARCH_PATHS:
        items = _load_yaml_file(path)
        if items:
            for item in items:
                name = item.get("name")
                if name:
                    merged[name] = item
            shipped_loaded = True
            break  # first shipped path that loads wins

    # 0. Hardcoded fallback baseline when no shipped YAML loaded
    if not shipped_loaded:
        for it in _DEFAULT_INTENTS:
            merged[it.name] = it.model_dump()

    # 2 + 3. User overlays (MERGE)
    for path in _overlay_search_paths(building_id):
        for item in _load_yaml_file(path):
            name = item.get("name")
            if name:
                merged[name] = item
                logger.info(f"[intent_registry] overlay applied: '{name}' from {path}")

    out: List[IntentDefinition] = []
    for data in merged.values():
        try:
            out.append(IntentDefinition(**data))
        except Exception as e:
            logger.warning(f"[intent_registry] rejected definition for '{data.get('name')}': {e}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Registry class
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class IntentRegistry:
    """Read-only registry of all intents declared in YAML (or defaults)."""

    intents: List[IntentDefinition] = field(default_factory=list)
    _by_name: Dict[str, IntentDefinition] = field(default_factory=dict, init=False)
    _by_alias: Dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for it in self.intents:
            self._by_name[it.name] = it
            for alias in it.aliases or []:
                self._by_alias[alias.lower().strip()] = it.name

    # ── Lookup ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[IntentDefinition]:
        """Return the IntentDefinition for `name` (alias-aware)."""
        if not name:
            return None
        key = name.lower().strip()
        if key in self._by_name:
            return self._by_name[key]
        resolved = self._by_alias.get(key)
        return self._by_name.get(resolved) if resolved else None

    def resolve_name(self, name: str) -> Optional[str]:
        """Return the canonical name for `name` (translates aliases)."""
        d = self.get(name)
        return d.name if d else None

    def names(self) -> FrozenSet[str]:
        """All canonical intent names (no aliases)."""
        return frozenset(self._by_name.keys())

    def in_group(self, group: str) -> FrozenSet[str]:
        """All intents in the given pipeline group ('data', 'standalone', 'meta')."""
        return frozenset(it.name for it in self.intents if it.pipeline_group == group)

    def with_node_method(self) -> List[IntentDefinition]:
        """Phase 13B — every intent that declared a `node_method`.

        Each returned definition has both `route_target` (graph node label)
        and `node_method` (python method name on WorkflowOrchestrator) set;
        `_build_graph` iterates this list to auto-register the corresponding
        graph nodes without touching workflow.py.
        """
        return [it for it in self.intents if it.node_method]

    def route_targets(self) -> FrozenSet[str]:
        """Union of every resolved `route_target` across the registry.

        Phase 13B uses this to derive the conditional-edges target dict for
        the dialogue node, eliminating the previously-hardcoded 15-entry
        mapping in workflow.py.  Targets that are pipeline stages
        (sparql / sql / etc.) are merged with the result by the caller.
        """
        targets: set[str] = set()
        for it in self.intents:
            tgt = self.route_target_for(it.name)
            if tgt:
                targets.add(tgt)
        return frozenset(targets)

    def route_target_for(self, intent_name: str) -> Optional[str]:
        """Phase 6D — return the workflow node this intent should route to.

        Resolution order:
          1. The intent's explicit `route_target` field (highest precedence)
          2. Default by pipeline_group:
               - data       → "sparql"   (first stage of the data pipeline)
               - standalone → intent.name (expects a same-named workflow node)
               - meta       → "response"
          3. None (caller falls back to its own logic, e.g. "response")
        """
        d = self.get(intent_name)
        if d is None:
            return None
        if d.route_target:
            return d.route_target
        if d.pipeline_group == "data":
            return "sparql"
        if d.pipeline_group == "standalone":
            return d.name
        if d.pipeline_group == "meta":
            return "response"
        return None

    def descriptions_markdown(self) -> str:
        """Render the intent block for embedding in an LLM prompt.

        Output matches the format used by the legacy hardcoded prompt in
        dialogue_agent.py so behaviour is byte-equivalent.
        """
        lines: List[str] = []
        for it in self.intents:
            head = f'   - "{it.name}"'
            pad = " " * max(1, 18 - len(head))
            lines.append(f"{head}{pad}: {it.description}")
            if it.examples:
                indent = " " * 24
                example_text = ", ".join(it.examples)
                lines.append(f"{indent}e.g. {example_text}")
            lines.append("")
        return "\n".join(lines).rstrip()


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def get_intent_registry(building_id: Optional[str] = None) -> IntentRegistry:
    """Build (per building_id) and return the runtime registry.

    Resolution order:
      1. orchestrator/intents/intent_definitions.yaml   (shipped defaults)
      2. input/intents.yaml                              (global overlay)
      3. input/<building_id>/intents.yaml                (per-building overlay)
      4. hardcoded `_DEFAULT_INTENTS` (only used if every YAML fails to load)

    Phase 11A: when `building_id` is None, falls back to `settings.BUILDING_ID`
    for backward compatibility with call sites that have no request context.
    Multi-tenant call sites (workflow, dialogue agent) MUST pass the per-request
    `state.building_id` so per-building overlays apply.

    The cache is keyed by `building_id`, so different buildings get distinct
    registries and overlays don't leak across tenants.
    """
    if not building_id:
        try:
            from shared.config import settings as _settings

            building_id = _settings.BUILDING_ID
        except Exception:
            building_id = None

    defs = _load_yaml(building_id=building_id)
    if not defs:
        # Belt-and-braces — `_load_yaml` already includes the hardcoded
        # fallback, but if validation rejected every entry we still want a
        # working registry.
        logger.info(
            "[intent_registry] every definition rejected — falling back to " "hardcoded defaults"
        )
        defs = list(_DEFAULT_INTENTS)
    else:
        logger.info(
            f"[intent_registry] loaded {len(defs)} intents (building_id={building_id}): "
            f"{[d.name for d in defs]}"
        )
    return IntentRegistry(intents=defs)
