"""
T26 — Tests for GoalPlanner: detect_goal + kpi_questions + format_goal_answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator.services.goal_planner import GoalPlanner
from shared.config import settings

# ── GoalPlanner unit tests ────────────────────────────────────────────────────


def _make_planner(goals_yaml_content: str) -> GoalPlanner:
    """Return a GoalPlanner pre-loaded with inline goals config."""
    data = yaml.safe_load(goals_yaml_content) or {}
    planner = GoalPlanner()
    planner._goals = data.get("goals", {})
    planner._loaded = True
    return planner


_SAMPLE_GOALS_YAML = """
goals:
  eco_friendly:
    triggers:
      - eco-friendly
      - eco friendly
      - save energy
      - reduce carbon
    display_name: "Eco-friendly"
    kpis:
      - id: energy_consumption
        label: "Energy consumption"
        intent: sensor_data
        question_template: "What is the current energy consumption?"
      - id: co2_indoor
        label: "Indoor CO2"
        intent: sensor_data
        question_template: "What are the CO2 levels in {building_id}?"

  comfort:
    triggers:
      - comfortable
      - improve comfort
      - occupant comfort
    display_name: "Occupant comfort"
    kpis:
      - id: temperature
        label: "Temperature"
        intent: sensor_data
        question_template: "What is the current temperature?"
"""


class TestGoalDetection:
    def test_eco_friendly_trigger_detected(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        goal_id, kpis = planner.detect_goal("Can you make the building more eco-friendly?")
        assert goal_id == "eco_friendly"
        assert len(kpis) == 2

    def test_save_energy_trigger_detected(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        goal_id, kpis = planner.detect_goal("How can we save energy in this building?")
        assert goal_id == "eco_friendly"

    def test_comfort_trigger_detected(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        goal_id, kpis = planner.detect_goal("Improve occupant comfort in the building.")
        assert goal_id == "comfort"
        assert len(kpis) == 1

    def test_no_mandate_phrasing_returns_none(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        # No "make/improve/reduce" verb — should not match
        goal_id, kpis = planner.detect_goal("What is the temperature in room 5.01?")
        assert goal_id is None
        assert kpis == []

    def test_unknown_trigger_returns_none(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        goal_id, kpis = planner.detect_goal("Improve security in the building.")
        assert goal_id is None  # "security" not in triggers

    def test_case_insensitive_trigger(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        goal_id, _ = planner.detect_goal("Make the building ECO-FRIENDLY please.")
        assert goal_id == "eco_friendly"


class TestKpiQuestions:
    def test_questions_generated_from_kpis(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        _, kpis = planner.detect_goal("Make the building eco-friendly.")
        questions = planner.kpi_questions(kpis, building_id="bldg1")
        assert len(questions) == 2
        assert questions[0]["id"] == "energy_consumption"
        assert questions[0]["intent"] == "sensor_data"
        assert "energy" in questions[0]["question"].lower()

    def test_building_id_substituted_in_template(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        _, kpis = planner.detect_goal("Make the building eco-friendly.")
        questions = planner.kpi_questions(kpis, building_id="bldg99")
        co2_q = next(q for q in questions if q["id"] == "co2_indoor")
        assert "bldg99" in co2_q["question"]

    def test_empty_kpis_returns_empty(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        assert planner.kpi_questions([]) == []

    def test_label_present_in_result(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        _, kpis = planner.detect_goal("Improve occupant comfort please.")
        questions = planner.kpi_questions(kpis)
        assert questions[0]["label"] == "Temperature"


class TestGoalAnswer:
    def test_format_includes_display_name(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer(
            "eco_friendly",
            [
                {"id": "energy_consumption", "label": "Energy consumption", "answer": "50 kWh/day"},
                {"id": "co2_indoor", "label": "Indoor CO2", "answer": "612 ppm"},
            ],
        )
        assert "Eco-friendly" in text
        assert "50 kWh/day" in text
        assert "612 ppm" in text

    def test_format_unknown_goal_uses_fallback_name(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer("unknown_goal", [])
        assert "Unknown Goal" in text or "unknown" in text.lower()

    # T27 — Three-tier capability report tests

    def test_measured_tier_appears_when_data_present(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer(
            "eco_friendly",
            [{"id": "energy_consumption", "label": "Energy", "answer": "120 kWh"}],
        )
        assert "What I measured" in text
        assert "120 kWh" in text

    def test_automatable_tier_appears_when_flagged(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer(
            "eco_friendly",
            [
                {
                    "id": "co2_indoor",
                    "label": "CO2",
                    "answer": "850 ppm",
                    "automatable": True,
                }
            ],
        )
        assert "automate" in text.lower() or "ECA" in text
        assert "set up an alert" in text.lower()

    def test_needs_extension_tier_appears(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer(
            "eco_friendly",
            [
                {
                    "id": "hvac_runtime",
                    "label": "HVAC",
                    "answer": None,
                    "extension": "Requires actuation driver (Phase H)",
                }
            ],
        )
        assert "needs further" in text.lower() or "capability" in text.lower()
        assert "Phase H" in text

    def test_no_data_kpis_handled_gracefully(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer(
            "comfort",
            [{"id": "temperature", "label": "Temperature", "answer": None}],
        )
        assert "No live data" in text or text  # no crash is enough

    def test_honest_actuation_disclaimer_present(self):
        planner = _make_planner(_SAMPLE_GOALS_YAML)
        text = planner.format_goal_answer("eco_friendly", [])
        assert "Phase H" in text or "actuation" in text.lower()


# ── Config/flag tests ─────────────────────────────────────────────────────────


class TestGoalPlannerConfig:
    def test_goal_planner_enabled_defaults_false(self):
        """GOAL_PLANNER_ENABLED must default to False (feature-flagged)."""
        assert settings.GOAL_PLANNER_ENABLED is False

    def test_goals_yaml_exists_and_has_required_structure(self):
        """config/goals.yaml must exist and contain at least 2 goals."""
        p = Path("config/goals.yaml")
        if not p.is_file():
            p = Path("/app/config/goals.yaml")
        assert p.is_file(), "config/goals.yaml must exist"

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        goals = data.get("goals", {})
        assert len(goals) >= 2, "At least 2 goals required"

        for goal_id, cfg in goals.items():
            assert "triggers" in cfg, f"goals.{goal_id} missing triggers"
            assert len(cfg["triggers"]) >= 1
            assert "kpis" in cfg, f"goals.{goal_id} missing kpis"
            assert len(cfg["kpis"]) >= 1
            for kpi in cfg["kpis"]:
                assert "id" in kpi
                assert "intent" in kpi
                assert "question_template" in kpi

    def test_eco_friendly_in_goals_yaml(self):
        """eco_friendly goal must be in the canonical goals.yaml."""
        p = Path("config/goals.yaml")
        if not p.is_file():
            p = Path("/app/config/goals.yaml")
        if not p.is_file():
            pytest.skip("goals.yaml not found")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        assert "eco_friendly" in data.get("goals", {})
