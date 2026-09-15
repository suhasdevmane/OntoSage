# -*- coding: utf-8 -*-
"""V12-20 — an ECA rule fires when its condition matched, and nothing moves (review B03).

    B03  "A positive fixture matches and a negative fixture does not, with NO actuation
          required or implied — a rule firing in a test should mean its condition matched,
          not that equipment moved. A rule either evaluates every matching point or must
          declare a scope."

THE DEFECT THIS ROW CLOSES (BUG-482)
-------------------------------------
A concept trigger resolves to a Brick CLASS, and a class has many points — 288 for
`Temperature_Sensor` on this building. The engine bound to the first point that was
reporting and evaluated ONLY that one, while the rule read as though it covered the class.
`humidity_damp_floor3` watched a single arbitrary humidity sensor.

The engine had been made to LOG which point it chose, which is honesty about the defect
rather than a fix for it. This row makes the rule say what it means: a concept rule now
declares `scope: all` or `scope: first_reporting`, and one that declares neither is loaded
DISABLED. No default — either default would silently pick a meaning the author did not,
and `first_reporting` as a default is exactly the behaviour that made this a defect.

WHY "NO ACTUATION" IS AN ASSERTION AND NOT A COMMENT
------------------------------------------------------
The review's point is that a fixture proving a rule "worked" must not be read as proving
equipment responded. This engine is notify-only for Gate A, and the tests below assert
that from the SOURCE — because the day someone adds an `actuate` action type, the fixtures
here would otherwise keep passing and keep meaning something different.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.rules_engine import (  # noqa: E402
    SCOPE_ALL,
    SCOPE_FIRST,
    EcaRule,
    RuleAction,
    RulesEngine,
    RuleTrigger,
)

REPO = Path(__file__).resolve().parent.parent


def _engine(values: Dict[str, float], fired: List[Tuple[str, str, float]]) -> RulesEngine:
    """An engine whose value fetcher and notifier are fixtures, not services."""

    async def _fetch(uuid: str) -> Optional[float]:
        return values.get(uuid)

    async def _notify(rule: EcaRule, uuid: str, value: float) -> None:
        fired.append((rule.id, uuid, value))

    eng = RulesEngine(building_id="bldgX", value_fetcher=_fetch, notifier=_notify)
    # Duration and cooldown live in Redis. These fixtures test the CONDITION, so both are
    # stubbed to "not sustained-blocked" and "not cooling down" — a rule that fires only
    # because Redis was unreachable would be a test of the wrong thing.
    eng._breach_sustained = _always(True)  # type: ignore[assignment]
    eng._in_cooldown = _always(False)  # type: ignore[assignment]
    eng._mark_cooldown = _noop()  # type: ignore[assignment]
    eng._clear_breach = _noop()  # type: ignore[assignment]
    return eng


def _always(value):
    async def _f(*_a, **_k):
        return value

    return _f


def _noop():
    async def _f(*_a, **_k):
        return None

    return _f


def _rule(uuid: str, op: str = ">", threshold: float = 1000.0) -> EcaRule:
    return EcaRule(
        id="co2_high",
        name="CO2 elevated",
        trigger=RuleTrigger(sensor_uuid=uuid, op=op, threshold=threshold),
        action=RuleAction(type="notify", message="CO2 is {value:.0f} ppm", severity="warning"),
    )


def _run(coro):
    return asyncio.run(coro)


# ── the positive and negative fixtures B03 asks for ──────────────────────────


def test_a_breaching_reading_fires_the_rule():
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"co2-1": 1240.0}, fired)
    assert _run(eng._evaluate_rule(_rule("co2-1"))) is True
    assert fired == [("co2_high", "co2-1", 1240.0)]


def test_a_reading_inside_the_threshold_does_not():
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"co2-1": 780.0}, fired)
    assert _run(eng._evaluate_rule(_rule("co2-1"))) is False
    assert fired == []


def test_a_reading_exactly_at_the_threshold_does_not_fire_a_strictly_greater_rule():
    """The boundary is where a threshold rule is most often wrong, and `>` means `>`."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"co2-1": 1000.0}, fired)
    assert _run(eng._evaluate_rule(_rule("co2-1", ">", 1000.0))) is False
    assert _run(eng._evaluate_rule(_rule("co2-1", ">=", 1000.0))) is True


def test_a_point_with_no_value_does_not_fire_and_is_not_read_as_compliant():
    """"No reading" is not "within threshold". Treating a silent instrument as a healthy
    one is the same error as narrating an empty fetch as sensor absence."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({}, fired)
    assert _run(eng._evaluate_rule(_rule("co2-1"))) is False
    assert fired == []


@pytest.mark.parametrize(
    "op, value, threshold, expected",
    [
        ("<", 12.0, 18.0, True),
        ("<", 21.0, 18.0, False),
        ("<=", 18.0, 18.0, True),
        ("!=", 5.0, 5.0, False),
        ("==", 5.0, 5.0, True),
    ],
)
def test_every_operator_means_what_it_says(op, value, threshold, expected):
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"s": value}, fired)
    assert _run(eng._evaluate_rule(_rule("s", op, threshold))) is expected


# ── the scope contract: every matching point, or say so ──────────────────────


def _concept_engine(values, fired, candidates):
    eng = _engine(values, fired)

    class _M:
        brick_classes = ["brick:Humidity_Sensor"]

    async def _resolve(_c):
        return [_M()]

    async def _uuids(_cls):
        return list(candidates)

    import orchestrator.services.concept_resolver as cr

    cr.concept_resolver.resolve = _resolve  # type: ignore[assignment]
    eng._uuids_for_class = _uuids  # type: ignore[assignment]
    return eng


def _concept_rule(scope: Optional[str]) -> EcaRule:
    return EcaRule(
        id="damp",
        name="Damp",
        trigger=RuleTrigger(concept="damp", op=">", threshold=65.0, scope=scope),
        action=RuleAction(type="notify", message="Humidity {value:.0f}%"),
    )


def test_scope_all_evaluates_every_matching_point():
    """The defect, inverted. Two of three points breach; both must be reported."""
    fired: List[Tuple[str, str, float]] = []
    eng = _concept_engine({"h1": 72.0, "h2": 40.0, "h3": 80.0}, fired, ["h1", "h2", "h3"])
    assert _run(eng._evaluate_rule(_concept_rule(SCOPE_ALL))) is True
    assert sorted(u for _, u, _ in fired) == ["h1", "h3"]


def test_scope_first_reporting_watches_exactly_one():
    fired: List[Tuple[str, str, float]] = []
    eng = _concept_engine({"h1": 72.0, "h2": 40.0, "h3": 80.0}, fired, ["h1", "h2", "h3"])
    assert _run(eng._evaluate_rule(_concept_rule(SCOPE_FIRST))) is True
    assert len(fired) == 1, "a first_reporting rule reported more than the point it watches"


def test_scope_all_skips_a_point_that_is_not_reporting():
    """A point with no value is excluded, not counted as non-breaching."""
    fired: List[Tuple[str, str, float]] = []
    eng = _concept_engine({"h1": 72.0, "h3": 80.0}, fired, ["h1", "h2", "h3"])
    assert _run(eng._evaluate_rule(_concept_rule(SCOPE_ALL))) is True
    assert sorted(u for _, u, _ in fired) == ["h1", "h3"]


def test_a_concept_rule_with_no_scope_does_not_load():
    """No default. Either default would pick a meaning the author did not."""
    assert RulesEngine._scope_is_declared(_concept_rule(None)) is False
    assert RulesEngine._scope_is_declared(_concept_rule(SCOPE_ALL)) is True
    assert RulesEngine._scope_is_declared(_concept_rule(SCOPE_FIRST)) is True


def test_a_direct_uuid_rule_needs_no_scope():
    """It watches exactly the point it names; there is nothing to declare."""
    assert RulesEngine._scope_is_declared(_rule("co2-1")) is True


def test_an_undeclared_scope_is_rejected_by_the_model_not_silently_accepted():
    with pytest.raises(Exception):
        RuleTrigger(concept="damp", scope="whatever")


def test_the_shipped_concept_rule_declares_its_scope():
    """The rule that made this a defect must not still be the undeclared one."""
    import yaml

    path = REPO / "input" / "rules.yaml"
    if not path.is_file():  # pragma: no cover - parked tree
        pytest.skip("no active building")
    for entry in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("rules", []):
        trig = entry.get("trigger", {}) or {}
        if trig.get("concept") and not trig.get("sensor_uuid"):
            assert trig.get("scope") in (SCOPE_ALL, SCOPE_FIRST), (
                f"rule {entry.get('id')!r} triggers on a concept and declares no scope, so "
                "it would be loaded disabled"
            )


# ── a rule firing means its condition matched. Nothing moved. ────────────────


def test_the_engine_is_notify_only():
    """B03's point, asserted from the source rather than left as a comment: the day an
    `actuate` action type appears, every fixture above would keep passing and would quietly
    start meaning something else."""
    src = (REPO / "orchestrator" / "services" / "rules_engine.py").read_text(encoding="utf-8")
    for forbidden in ("actuation_registry", "ActuationRegistry", "actuate(", "write_point"):
        assert forbidden not in src, (
            f"the rules engine references {forbidden} — a fired rule may now move equipment, "
            "and the fixtures in this file no longer mean what they say"
        )


def test_the_only_shipped_action_type_is_notify():
    import yaml

    path = REPO / "input" / "rules.yaml"
    if not path.is_file():  # pragma: no cover - parked tree
        pytest.skip("no active building")
    for entry in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("rules", []):
        assert (entry.get("action") or {}).get("type", "notify") == "notify"


def test_firing_calls_the_notifier_and_nothing_else():
    """The whole observable effect of a fired rule, enumerated."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"co2-1": 1240.0}, fired)
    _run(eng._evaluate_rule(_rule("co2-1")))
    assert len(fired) == 1

    notifier_src = inspect.getsource(RulesEngine._default_notifier)
    assert "notification_service" in notifier_src or "dispatch" in notifier_src
    assert "actuat" not in notifier_src.lower()
