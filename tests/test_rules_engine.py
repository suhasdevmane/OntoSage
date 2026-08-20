"""T20 — RulesEngine unit tests.

Covers:
  1. load() returns correct count from rules.yaml
  2. Rule disabled=false is skipped
  3. Breach condition fires notification
  4. No breach = no notification
  5. Cooldown prevents double-firing
  6. Duration window: fires only after sustained breach
  7. Concept-based trigger resolves via concept_resolver
  8. Unknown UUID (fetcher returns None) skips rule
  9. evaluate_all() returns correct fired count
  10. load() returns 0 when rules.yaml absent
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from orchestrator.services.rules_engine import EcaRule, RulesEngine

# ── helpers ────────────────────────────────────────────────────────────────────

_SAMPLE_RULES_YAML = """
rules:
  - id: co2_high
    name: CO2 high test rule
    enabled: true
    trigger:
      sensor_uuid: "test-uuid-1234"
      op: ">"
      threshold: 1000.0
      duration_min: 0
    action:
      type: notify
      message: "CO2 is {value:.0f} ppm"
      severity: warning

  - id: temp_cold
    name: Temperature too cold
    enabled: true
    trigger:
      sensor_uuid: "test-uuid-5678"
      op: "<"
      threshold: 18.0
      duration_min: 0
    action:
      type: notify
      message: "Temperature is {value:.1f}°C (below {threshold:.0f}°C)"
      severity: info

  - id: disabled_rule
    name: Disabled rule
    enabled: false
    trigger:
      sensor_uuid: "test-uuid-9999"
      op: ">"
      threshold: 50.0
      duration_min: 0
    action:
      type: notify
      message: "should never fire"
"""


def _engine_from_yaml(yaml_str: str, fetcher=None, notifier=None) -> RulesEngine:
    """Build a RulesEngine with patched file loading and injected fetcher/notifier."""
    engine = RulesEngine.__new__(RulesEngine)
    engine._building_id = "bldg_test"
    engine._rules = []
    engine._value_fetcher = fetcher or AsyncMock(return_value=None)
    engine._notifier = notifier or AsyncMock()

    data = yaml.safe_load(yaml_str) or {}
    for entry in data.get("rules", []):
        try:
            rule = EcaRule(**entry)
        except Exception:
            continue
        if rule.enabled:
            engine._rules.append(rule)
    return engine


def _engine_with_rules(rules: list, fetcher=None, notifier=None) -> RulesEngine:
    engine = RulesEngine.__new__(RulesEngine)
    engine._building_id = "bldg_test"
    engine._rules = [EcaRule(**r) for r in rules]
    engine._value_fetcher = fetcher or AsyncMock(return_value=None)
    engine._notifier = notifier or AsyncMock()
    return engine


# ── tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_returns_correct_count(tmp_path):
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(_SAMPLE_RULES_YAML, encoding="utf-8")

    engine = RulesEngine("test_bldg")
    with patch.object(engine, "_find_yaml", return_value=rules_yaml):
        count = engine.load()

    assert count == 2, f"Expected 2 enabled rules, got {count}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_rule_is_skipped(tmp_path):
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(_SAMPLE_RULES_YAML, encoding="utf-8")

    engine = RulesEngine("test_bldg")
    with patch.object(engine, "_find_yaml", return_value=rules_yaml):
        engine.load()

    rule_ids = [r.id for r in engine.rules]
    assert "disabled_rule" not in rule_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_breach_fires_notification():
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=1200.0)  # above 1000 threshold

    engine = _engine_from_yaml(_SAMPLE_RULES_YAML, fetcher=fetcher, notifier=notifier)

    # Patch Redis calls to no-ops
    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_mark_cooldown", AsyncMock()
    ), patch.object(engine, "_clear_breach", AsyncMock()):

        fired = await engine.evaluate_all()

    # co2_high fires (1200 > 1000), temp_cold does NOT (1200 > 18)
    assert fired >= 1
    notifier.assert_called()
    # First fired rule should be co2_high
    args = notifier.call_args_list[0].args
    assert args[0].id == "co2_high"
    assert abs(args[2] - 1200.0) < 0.01


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_breach_no_notification():
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=800.0)  # below 1000 threshold

    engine = _engine_from_yaml(_SAMPLE_RULES_YAML, fetcher=fetcher, notifier=notifier)

    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_clear_breach", AsyncMock()
    ):
        fired = await engine.evaluate_all()

    assert fired == 0
    notifier.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cooldown_prevents_double_fire():
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=1200.0)

    engine = _engine_from_yaml(_SAMPLE_RULES_YAML, fetcher=fetcher, notifier=notifier)

    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=True)), patch.object(
        engine, "_clear_breach", AsyncMock()
    ):
        fired = await engine.evaluate_all()

    assert fired == 0
    notifier.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duration_window_does_not_fire_on_first_detection():
    """Rule with duration_min > 0 must NOT fire on first breach detection."""
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=1200.0)

    rule_def = [
        {
            "id": "co2_sustained",
            "name": "CO2 sustained",
            "enabled": True,
            "trigger": {
                "sensor_uuid": "uuid-dur",
                "op": ">",
                "threshold": 1000.0,
                "duration_min": 10,
            },
            "action": {"type": "notify", "message": "CO2 high", "severity": "warning"},
        }
    ]
    engine = _engine_with_rules(rule_def, fetcher=fetcher, notifier=notifier)

    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_breach_sustained", AsyncMock(return_value=False)
    ), patch.object(engine, "_clear_breach", AsyncMock()):
        fired = await engine.evaluate_all()

    assert fired == 0
    notifier.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duration_window_fires_when_sustained():
    """Rule with duration_min > 0 MUST fire when breach is sustained."""
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=1200.0)

    rule_def = [
        {
            "id": "co2_sustained",
            "name": "CO2 sustained",
            "enabled": True,
            "trigger": {
                "sensor_uuid": "uuid-dur",
                "op": ">",
                "threshold": 1000.0,
                "duration_min": 10,
            },
            "action": {"type": "notify", "message": "CO2 high", "severity": "warning"},
        }
    ]
    engine = _engine_with_rules(rule_def, fetcher=fetcher, notifier=notifier)

    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_breach_sustained", AsyncMock(return_value=True)
    ), patch.object(engine, "_mark_cooldown", AsyncMock()), patch.object(
        engine, "_clear_breach", AsyncMock()
    ):
        fired = await engine.evaluate_all()

    assert fired == 1
    notifier.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_none_value_skips_rule():
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=None)  # no data

    engine = _engine_from_yaml(_SAMPLE_RULES_YAML, fetcher=fetcher, notifier=notifier)

    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)):
        fired = await engine.evaluate_all()

    assert fired == 0
    notifier.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_all_returns_correct_count():
    notifier = AsyncMock()

    # Value 1200 → co2_high fires (>1000), temp_cold does NOT (<18)
    fetcher = AsyncMock(return_value=1200.0)

    engine = _engine_from_yaml(_SAMPLE_RULES_YAML, fetcher=fetcher, notifier=notifier)
    with patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_mark_cooldown", AsyncMock()
    ), patch.object(engine, "_clear_breach", AsyncMock()):
        fired = await engine.evaluate_all()

    assert fired == 1  # only co2_high fires with value 1200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_returns_0_when_no_yaml():
    engine = RulesEngine("nonexistent_building")
    with patch.object(engine, "_find_yaml", return_value=None):
        count = engine.load()
    assert count == 0
    assert engine.rules == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concept_trigger_resolves_via_hbco():
    """Concept trigger: 'damp' → HBCO → brick class → uuid lookup."""
    notifier = AsyncMock()
    fetcher = AsyncMock(return_value=70.0)  # above 65 threshold

    from orchestrator.services.concept_resolver import ConceptMatch as _CM

    mock_match = _CM(
        concept_id="dampness",
        lay_term="damp",
        brick_classes=["brick:Zone_Air_Humidity_Sensor"],
        recipe_id="humidity_threshold",
        confidence="high",
    )

    rule_def = [
        {
            "id": "humidity_damp",
            "name": "High humidity",
            "enabled": True,
            "trigger": {"concept": "damp", "op": ">", "threshold": 65.0, "duration_min": 0},
            "action": {"type": "notify", "message": "Humidity high", "severity": "warning"},
        }
    ]
    engine = _engine_with_rules(rule_def, fetcher=fetcher, notifier=notifier)

    mock_cr = MagicMock()
    mock_cr.resolve = AsyncMock(return_value=[mock_match])
    with patch("orchestrator.services.concept_resolver.concept_resolver", mock_cr), patch.object(
        engine, "_uuid_for_class", AsyncMock(return_value="mock-humidity-uuid")
    ), patch.object(engine, "_in_cooldown", AsyncMock(return_value=False)), patch.object(
        engine, "_mark_cooldown", AsyncMock()
    ), patch.object(
        engine, "_clear_breach", AsyncMock()
    ):
        fired = await engine.evaluate_all()

    assert fired == 1
