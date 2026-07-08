"""goal_planner.py — Goal → KPI decomposition service (T26).

Decomposes open-ended goal mandates ('make the building eco-friendly') into
a list of measurable KPI sub-questions that route through existing pipeline
nodes (sensor_data, analytics, anomaly, trend).

The planner is configuration-driven: config/goals.yaml defines the goal
taxonomy.  Per-building overlays via input/<building_id>/goals.yaml.
The GOAL_PLANNER_ENABLED flag gates this feature (default False).

Usage:
    from orchestrator.services.goal_planner import GoalPlanner
    planner = GoalPlanner()
    goal, kpis = planner.detect_goal("Can you make the building more eco-friendly?")
    if goal:
        sub_questions = planner.kpi_questions(kpis, building_id="bldg1")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_CONFIG_SEARCH_PATHS = [
    "config/goals.yaml",
    "/app/config/goals.yaml",
]
_BUILDING_OVERLAY_PATHS = [
    "input/{building_id}/goals.yaml",
    "/app/input/{building_id}/goals.yaml",
]

_GOAL_TRIGGER_RE_CACHE: Dict[str, re.Pattern] = {}

_MANDATE_PHRASING_RE = re.compile(
    r"\b(make|improve|enhance|optimise|optimize|reduce|increase|maximise|maximize|ensure|"
    r"achieve|get|become|be more|save|lower|cut|decrease|boost)\b",
    re.IGNORECASE,
)


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(f"[GoalPlanner] Could not load {path}: {exc}")
        return {}


def _find_config() -> Optional[Path]:
    for template in _CONFIG_SEARCH_PATHS:
        p = Path(template)
        if p.is_file():
            return p
    return None


def _find_building_overlay(building_id: str) -> Optional[Path]:
    for template in _BUILDING_OVERLAY_PATHS:
        p = Path(template.format(building_id=building_id))
        if p.is_file():
            return p
    return None


class GoalPlanner:
    """Detect goal mandates and decompose them into KPI sub-questions."""

    def __init__(self) -> None:
        self._goals: Dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self, building_id: str = "") -> None:
        if self._loaded:
            return
        base = _find_config()
        if base:
            data = _load_yaml(base)
            self._goals = data.get("goals", {})

        if building_id:
            overlay = _find_building_overlay(building_id)
            if overlay:
                overlay_data = _load_yaml(overlay)
                for goal_id, goal_cfg in overlay_data.get("goals", {}).items():
                    if goal_id in self._goals:
                        # Deep-merge KPIs: per-building can ADD KPIs, not replace
                        existing = self._goals[goal_id].get("kpis", [])
                        extra = goal_cfg.get("kpis", [])
                        self._goals[goal_id]["kpis"] = existing + extra
                    else:
                        self._goals[goal_id] = goal_cfg

        self._loaded = True

    def detect_goal(self, query: str) -> Tuple[Optional[str], List[Dict]]:
        """Return (goal_id, kpi_list) if query matches a goal mandate.

        Returns (None, []) if no goal mandate is detected.
        """
        self._ensure_loaded()
        q_lower = query.lower()

        # Quick filter: must contain mandate phrasing
        if not _MANDATE_PHRASING_RE.search(q_lower):
            return None, []

        for goal_id, goal_cfg in self._goals.items():
            triggers = goal_cfg.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in q_lower:
                    kpis = goal_cfg.get("kpis", [])
                    logger.info(
                        f"[GoalPlanner] Goal detected: {goal_id} "
                        f"(trigger='{trigger}', {len(kpis)} KPIs)"
                    )
                    return goal_id, kpis

        return None, []

    def kpi_questions(self, kpis: List[Dict], building_id: str = "") -> List[Dict]:
        """Expand KPIs into sub-question dicts with question + intent.

        Returns list of {'id', 'label', 'intent', 'question'} dicts.
        """
        result = []
        for kpi in kpis:
            template = kpi.get("question_template", "")
            question = template.replace("{building_id}", building_id)
            result.append({
                "id": kpi.get("id"),
                "label": kpi.get("label", kpi.get("id", "")),
                "intent": kpi.get("intent", "sensor_data"),
                "question": question,
            })
        return result

    def format_goal_answer(
        self, goal_id: str, kpi_results: List[Dict]
    ) -> str:
        """Format a structured multi-KPI answer from KPI results.

        T27 — Three-tier structure per the master-table answerability model:
          1. Measured: what we read from live sensors (answer with data)
          2. Automatable-now: what the ECA rule engine can already do (notify path)
          3. Needs-extension: what requires actuation or additional hardware

        Each KPI result may optionally include:
          answer      (str) — live data answer; absent means sensor not available
          automatable (bool) — True if an ECA rule can handle this KPI today
          extension   (str) — description of what would be needed to close the gap
        """
        self._ensure_loaded()
        goal_cfg = self._goals.get(goal_id, {})
        display_name = goal_cfg.get("display_name", goal_id.replace("_", " ").title())

        measured = [k for k in kpi_results if k.get("answer") and k["answer"] != "No data available"]
        no_data = [k for k in kpi_results if not k.get("answer") or k["answer"] == "No data available"]
        automatable = [k for k in kpi_results if k.get("automatable") is True]
        needs_ext = [k for k in kpi_results if k.get("extension")]

        lines = [f"## Goal Assessment: {display_name}\n"]

        if measured:
            lines.append("### What I measured\n")
            for kpi in measured:
                label = kpi.get("label", kpi.get("id", ""))
                lines.append(f"- **{label}**: {kpi['answer']}")

        if automatable:
            lines.append("\n### What I can automate now (ECA alerts)\n")
            for kpi in automatable:
                label = kpi.get("label", kpi.get("id", ""))
                lines.append(f"- **{label}**: I can watch this and notify you when it falls outside range.")
            lines.append(
                "\nWant me to set up an alert for any of these? Just say which ones."
            )

        if needs_ext:
            lines.append("\n### What needs further capability\n")
            for kpi in needs_ext:
                label = kpi.get("label", kpi.get("id", ""))
                ext = kpi.get("extension", "")
                lines.append(f"- **{label}**: {ext}")

        if no_data and not measured:
            lines.append("\n*No live data available for these KPIs — check sensor connectivity.*")

        lines.append(
            "\n---\n*Assessed from live sensor data and analytics. "
            "Physical actuation (e.g., automatic setpoint adjustment) requires "
            "Phase H hardware integration.*"
        )
        return "\n".join(lines)


_planner: Optional[GoalPlanner] = None


def get_goal_planner() -> GoalPlanner:
    global _planner
    if _planner is None:
        _planner = GoalPlanner()
    return _planner
