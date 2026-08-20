"""
T37 — Tests for orchestrator/services/input_validators.py

Each per-file validator is tested with:
  - a valid/complete fixture  →  (True, [])
  - an absent file            →  (True, [])   (optional = absence ok)
  - a malformed YAML/CSV/TTL  →  (False, [msg])
  - a schema violation        →  (False, [msg])
"""

from __future__ import annotations

import csv
import textwrap
from pathlib import Path

import pytest
import yaml

from orchestrator.services.input_validators import (
    _BENCHMARKS_REQUIRED_COLS,
    _DOCS_ALLOWED_EXTENSIONS,
    format_validation_report,
    validate_benchmarks_csv,
    validate_building_input,
    validate_channels_yaml,
    validate_concepts_ttl,
    validate_documents_dir,
    validate_feeds_yaml,
    validate_recipes_yaml,
    validate_rules_yaml,
)

# ── fixtures ──────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ── feeds.yaml ────────────────────────────────────────────────────────────────


class TestFeedsYaml:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_feeds_yaml(tmp_path / "no_such_file.yaml")
        assert ok is True
        assert issues == []

    def test_valid_feed(self, tmp_path):
        p = _write(
            tmp_path / "feeds.yaml",
            """
            feeds:
              - id: temp_floor3
                type: csv_drop
                brick_class: brick:Temperature_Sensor
                storage: mysql
                field_map:
                  temperature: value
            """,
        )
        ok, issues = validate_feeds_yaml(p)
        assert ok is True, issues

    def test_malformed_yaml(self, tmp_path):
        p = tmp_path / "feeds.yaml"
        p.write_text("feeds: [bad: yaml: :\n", encoding="utf-8")
        ok, issues = validate_feeds_yaml(p)
        assert ok is False
        assert any("YAML parse error" in i for i in issues)

    def test_unknown_type(self, tmp_path):
        p = _write(
            tmp_path / "feeds.yaml",
            """
            feeds:
              - id: bad_feed
                type: kafka_stream
                brick_class: brick:Temperature_Sensor
                storage: mysql
            """,
        )
        ok, issues = validate_feeds_yaml(p)
        assert ok is False
        assert any("kafka_stream" in i for i in issues)

    def test_missing_required_key(self, tmp_path):
        p = _write(
            tmp_path / "feeds.yaml",
            """
            feeds:
              - id: incomplete
                type: rest_poll
            """,
        )
        ok, issues = validate_feeds_yaml(p)
        assert ok is False
        assert any("missing required keys" in i for i in issues)

    def test_duplicate_id(self, tmp_path):
        p = _write(
            tmp_path / "feeds.yaml",
            """
            feeds:
              - id: dup
                type: csv_drop
                brick_class: brick:CO2_Sensor
                storage: mysql
              - id: dup
                type: csv_drop
                brick_class: brick:CO2_Sensor
                storage: mysql
            """,
        )
        ok, issues = validate_feeds_yaml(p)
        assert ok is False
        assert any("duplicate" in i for i in issues)

    def test_field_map_missing_value_mapping(self, tmp_path):
        p = _write(
            tmp_path / "feeds.yaml",
            """
            feeds:
              - id: no_value
                type: csv_drop
                brick_class: brick:CO2_Sensor
                storage: mysql
                field_map:
                  col_a: timestamp
            """,
        )
        ok, issues = validate_feeds_yaml(p)
        assert ok is False
        assert any("field_map" in i for i in issues)


# ── recipes.yaml ──────────────────────────────────────────────────────────────


class TestRecipesYaml:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_recipes_yaml(tmp_path / "no_recipes.yaml")
        assert ok is True

    def test_valid_recipe(self, tmp_path):
        p = _write(
            tmp_path / "recipes.yaml",
            """
            co2_comfort:
              kind: threshold
              params:
                threshold_max: 1000
                unit: ppm
            """,
        )
        ok, issues = validate_recipes_yaml(p)
        assert ok is True, issues

    def test_bad_recipe_kind(self, tmp_path):
        p = _write(
            tmp_path / "recipes.yaml",
            """
            bad_recipe:
              kind: magic_kind
              params: {}
            """,
        )
        ok, issues = validate_recipes_yaml(p)
        assert ok is False
        assert any("magic_kind" in i for i in issues)

    def test_missing_params(self, tmp_path):
        p = _write(
            tmp_path / "recipes.yaml",
            """
            no_params:
              kind: threshold
            """,
        )
        ok, issues = validate_recipes_yaml(p)
        assert ok is False
        assert any("params" in i for i in issues)


# ── rules.yaml ────────────────────────────────────────────────────────────────


class TestRulesYaml:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_rules_yaml(tmp_path / "rules.yaml")
        assert ok is True

    def test_valid_rule(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: co2_high
                trigger:
                  concept: co2_level
                  op: ">"
                  threshold: 1000
                action:
                  type: notify
                  message: "CO2 high"
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is True, issues

    def test_valid_rule_with_sensor_uuid(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: temp_high
                trigger:
                  sensor_uuid: "abc123"
                  op: ">"
                  threshold: 27.0
                action:
                  type: notify
                  message: "Temperature high"
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is True, issues

    def test_bad_operator(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: bad_op
                trigger:
                  concept: co2_level
                  op: "GREATER"
                  threshold: 1000
                action:
                  type: notify
                  message: "test"
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is False
        assert any("GREATER" in i for i in issues)

    def test_missing_concept_and_uuid(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: no_concept
                trigger:
                  op: ">"
                  threshold: 50
                action:
                  type: notify
                  message: "test"
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is False
        assert any("concept" in i for i in issues)

    def test_unsupported_action_type(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: actuate_rule
                trigger:
                  concept: temp
                  op: ">"
                  threshold: 25
                action:
                  type: actuate
                  target: thermostat
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is False
        assert any("actuate" in i for i in issues)

    def test_duplicate_rule_id(self, tmp_path):
        p = _write(
            tmp_path / "rules.yaml",
            """
            rules:
              - id: same
                trigger:
                  concept: co2
                  op: ">"
                  threshold: 1000
                action:
                  type: notify
                  message: a
              - id: same
                trigger:
                  concept: co2
                  op: ">"
                  threshold: 1000
                action:
                  type: notify
                  message: b
            """,
        )
        ok, issues = validate_rules_yaml(p)
        assert ok is False
        assert any("duplicate" in i for i in issues)


# ── channels.yaml ─────────────────────────────────────────────────────────────


class TestChannelsYaml:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_channels_yaml(tmp_path / "channels.yaml")
        assert ok is True

    def test_valid_channel(self, tmp_path):
        p = _write(
            tmp_path / "channels.yaml",
            """
            channels:
              - type: log
                name: default_log
              - type: webhook
                url: https://hooks.example.com/notify
            """,
        )
        ok, issues = validate_channels_yaml(p)
        assert ok is True, issues

    def test_bad_channel_type(self, tmp_path):
        p = _write(
            tmp_path / "channels.yaml",
            """
            channels:
              - type: telegram
                chat_id: 123456
            """,
        )
        ok, issues = validate_channels_yaml(p)
        assert ok is False
        assert any("telegram" in i for i in issues)


# ── benchmarks.csv ────────────────────────────────────────────────────────────


class TestBenchmarksCsv:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_benchmarks_csv(tmp_path / "benchmarks.csv")
        assert ok is True

    def test_valid_csv(self, tmp_path):
        p = tmp_path / "benchmarks.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "p25", "p50", "p75", "unit", "source"])
            w.writerow(["co2_ppm", "400", "600", "900", "ppm", "ASHRAE"])
        ok, issues = validate_benchmarks_csv(p)
        assert ok is True, issues

    def test_missing_column(self, tmp_path):
        p = tmp_path / "benchmarks.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "p50", "unit"])  # missing p25, p75, source
        ok, issues = validate_benchmarks_csv(p)
        assert ok is False
        assert any("missing required columns" in i for i in issues)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "benchmarks.csv"
        p.write_text("", encoding="utf-8")
        ok, issues = validate_benchmarks_csv(p)
        assert ok is False
        assert any("empty" in i for i in issues)


# ── documents/ ────────────────────────────────────────────────────────────────


class TestDocumentsDir:
    def test_absent_is_ok(self, tmp_path):
        ok, issues = validate_documents_dir(tmp_path / "no_documents")
        assert ok is True

    def test_allowed_extensions(self, tmp_path):
        d = tmp_path / "documents"
        d.mkdir()
        (d / "maintenance.md").write_text("# log", encoding="utf-8")
        (d / "policy.pdf").write_bytes(b"%PDF-1.4 fake")
        ok, issues = validate_documents_dir(d)
        assert ok is True, issues

    def test_disallowed_extension(self, tmp_path):
        d = tmp_path / "documents"
        d.mkdir()
        (d / "report.docx").write_bytes(b"PK fake docx")
        ok, issues = validate_documents_dir(d)
        assert ok is False
        assert any(".docx" in i for i in issues)


# ── aggregate validator ───────────────────────────────────────────────────────


class TestValidateBuildingInput:
    def test_all_absent_ok(self, tmp_path):
        """A building directory with only building.yaml passes vacuously."""
        bldg_dir = tmp_path / "bldg99"
        bldg_dir.mkdir()
        all_ok, report = validate_building_input("bldg99", tmp_path)
        assert all_ok is True
        assert report["building_id"] == "bldg99"
        for fname, result in report["files"].items():
            assert result["ok"] is True, f"{fname} should pass when absent"

    def test_missing_building_dir_fails_loudly(self, tmp_path):
        """A non-existent building directory must FAIL with an actionable message,
        not pass vacuously (files-only onboarding contract: fail loudly)."""
        all_ok, report = validate_building_input("ghost_bldg", tmp_path)
        assert all_ok is False
        assert "<building dir>" in report["files"]
        issues = report["files"]["<building dir>"]["issues"]
        assert any("input/ghost_bldg/" in i for i in issues)
        assert any("scaffold" in i for i in issues)
        text = format_validation_report(report)
        assert "FAIL" in text

    def test_bad_feeds_propagates(self, tmp_path):
        bldg_dir = tmp_path / "bldgX"
        bldg_dir.mkdir()
        _write(
            bldg_dir / "feeds.yaml",
            """
            feeds:
              - id: bad
                type: mqtt
                brick_class: brick:CO2_Sensor
                storage: mysql
            """,
        )
        all_ok, report = validate_building_input("bldgX", tmp_path)
        assert all_ok is False
        assert report["files"]["feeds.yaml"]["ok"] is False

    def test_format_report_returns_text(self, tmp_path):
        bldg_dir = tmp_path / "bldgZ"
        bldg_dir.mkdir()
        all_ok, report = validate_building_input("bldgZ", tmp_path)
        text = format_validation_report(report)
        assert "bldgZ" in text
        assert "PASS" in text or "FAIL" in text


# ── scaffold smoke test ───────────────────────────────────────────────────────


class TestScaffold:
    def test_scaffold_copies_templates(self, tmp_path, monkeypatch):
        """run_scaffold copies _templates and substitutes BUILDING_ID."""
        import sys

        # Write a minimal template file
        templates = tmp_path / "_templates"
        templates.mkdir()
        (templates / "feeds.yaml").write_text(
            "# building: {BUILDING_ID}\nfeeds: []\n", encoding="utf-8"
        )

        # Import and call directly
        repo_root = Path(__file__).resolve().parent.parent
        monkeypatch.syspath_prepend(str(repo_root))

        from scripts.onboard_building import run_scaffold

        run_scaffold("newbldg", tmp_path)

        dest = tmp_path / "newbldg" / "feeds.yaml"
        assert dest.exists()
        assert "newbldg" in dest.read_text()
        assert "{BUILDING_ID}" not in dest.read_text()

    def test_real_templates_scaffold_to_a_valid_building(self, tmp_path, monkeypatch):
        """The SHIPPED input/_templates must scaffold into a building that
        passes every validator out of the box. Regression for 2026-06-13:
        the rules.yaml template used the pre-T29 field names (value/point_uuid
        instead of threshold/sensor_uuid), so every freshly scaffolded
        building failed validation on first contact.

        Also asserts the building.yaml template's namespace contract:
        id substituted, unique ontosage.org fallback URI ending in '#',
        standardized 'bldg' prefix label.
        """
        import shutil
        import sys

        import yaml

        repo_root = Path(__file__).resolve().parent.parent
        real_templates = repo_root / "input" / "_templates"
        if not real_templates.is_dir():
            pytest.skip("input/_templates not present")

        monkeypatch.syspath_prepend(str(repo_root))
        from scripts.onboard_building import run_scaffold

        shutil.copytree(real_templates, tmp_path / "_templates")
        run_scaffold("newbldg", tmp_path)

        cfg = yaml.safe_load((tmp_path / "newbldg" / "building.yaml").read_text(encoding="utf-8"))
        assert cfg["building_id"] == "newbldg"
        assert cfg["ontology_namespace"] == "http://ontosage.org/buildings/newbldg#"
        assert cfg["ontology_namespace"].endswith("#")
        assert cfg["building_prefix"] == "bldg"

        all_ok, report = validate_building_input("newbldg", tmp_path)
        assert all_ok, format_validation_report(report)
