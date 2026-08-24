# -*- coding: utf-8 -*-
"""Evidence policy loading, overlays and fail-safe behaviour (V6-T04).

Three properties matter more than the numbers themselves:

* no threshold is a code constant - a "5 minutes" in Python is a building literal wearing a
  number, and a building archiving at 15-minute resolution would be permanently stale
  against it;
* absence fails SAFE, not open - a missing or broken overlay leaves defaults in force,
  because a building must never end up with no gate because of a typo;
* gates start advisory - a gate that arrives enforcing changes answers on the commit that
  introduces it, entangled with everything else in that run, which is exactly what makes a
  regression indistinguishable from an intended tightening.
"""

from pathlib import Path

import pytest
import yaml

from orchestrator.services.evidence import GateMode, load_policy
from orchestrator.services.evidence.policy import _deep_merge

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
DEFAULT = REPO / "config" / "evidence_policy.yaml"


# ── the shipped default ──────────────────────────────────────────────────────


def test_default_policy_exists_and_loads():
    p = load_policy("any")
    assert p.raw.get("version")
    assert "config" in p.sources[0]


def test_thresholds_come_from_config_not_code():
    """Change the file, change the behaviour - that is the whole point."""
    p = load_policy("any", input_dir=REPO / "does" / "not" / "exist")
    cfg = yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))
    assert p.max_age_minutes("co2") == float(
        cfg["freshness"]["by_modality"]["co2"]["max_age_minutes"]
    )


def test_every_threshold_group_carries_a_citation():
    """A number without a source is indistinguishable from one tuned to flatter a score."""
    cfg = yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))
    assert cfg["freshness"]["default_citation"].strip()
    assert cfg["completeness"]["citation"].strip()
    assert cfg["agreement"]["citation"].strip()
    assert cfg["spatial_adequacy"]["citation"].strip()
    assert cfg["consequence"]["citation"].strip()
    for modality, spec in cfg["freshness"]["by_modality"].items():
        assert spec.get("citation", "").strip(), f"freshness.{modality} has no citation"


def test_unknown_modality_falls_back_to_the_default():
    p = load_policy("any")
    assert p.max_age_minutes("unobtanium") == p.raw["freshness"]["default_max_age_minutes"]


def test_absent_agreement_tolerance_is_none_not_infinite():
    """None means 'do not judge', NOT 'any spread is acceptable'."""
    assert load_policy("any").agreement_tolerance("unobtanium") is None


# ── consequence scaling ──────────────────────────────────────────────────────


def test_safety_shapes_demand_more_than_informational_ones():
    p = load_policy("any")
    assert p.min_completeness("safety_or_compliance") > p.min_completeness("informational")
    assert p.requires_calibration("safety_or_compliance") is True
    assert p.requires_calibration("informational") is False


def test_unknown_shape_defaults_to_informational():
    """A NEW shape must not silently acquire a safety threshold it was not designed for.

    The permissive default is the deliberate choice: the safety set is enumerated
    explicitly, which also makes it auditable at a glance.
    """
    assert load_policy("any").consequence_class("some_new_shape_nobody_listed") == "informational"


def test_standards_verdicts_forbid_unknown_calibration():
    """Acceptance scenario 7: no standards verdict from an uncalibrated sensor."""
    p = load_policy("any")
    assert p.forbids_unknown_calibration("safety_or_compliance") is True
    assert p.forbids_unknown_calibration("informational") is False


# ── spatial adequacy ─────────────────────────────────────────────────────────


def test_a_room_level_answer_may_not_rest_on_a_proxy():
    """The non-substitution rule, expressed as policy rather than as code."""
    p = load_policy("any")
    assert "proxy" not in p.allowed_adequacy("space")
    assert "in_room" in p.allowed_adequacy("space")
    # A building-wide question may legitimately use proxy evidence.
    assert "proxy" in p.allowed_adequacy("building")


# ── overlays ─────────────────────────────────────────────────────────────────


def test_overlay_narrows_one_modality_without_deleting_the_others(tmp_path):
    """A wholesale replace would silently drop twelve modalities; merge must be key-wise."""
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump({"freshness": {"by_modality": {"co2": {"max_age_minutes": 2}}}}),
        encoding="utf-8",
    )
    p = load_policy("bldgX", input_dir=tmp_path)
    assert p.max_age_minutes("co2") == 2.0
    assert p.max_age_minutes("temperature") == 15.0  # untouched
    assert len(p.sources) == 2


def test_missing_overlay_leaves_defaults_in_force(tmp_path):
    p = load_policy("bldgX", input_dir=tmp_path)
    assert p.max_age_minutes("co2") == 5.0
    assert len(p.sources) == 1


def test_malformed_overlay_is_ignored_rather_than_fatal(tmp_path):
    """A typo in an optional file must not take the building's evidence policy down."""
    (tmp_path / "evidence_policy.yaml").write_text("this: [is: not: valid: yaml", encoding="utf-8")
    p = load_policy("bldgX", input_dir=tmp_path)
    assert p.max_age_minutes("co2") == 5.0  # defaults survived


def test_overlay_that_is_not_a_mapping_is_ignored(tmp_path):
    (tmp_path / "evidence_policy.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    assert load_policy("bldgX", input_dir=tmp_path).max_age_minutes("co2") == 5.0


def test_deep_merge_replaces_scalars_and_merges_dicts():
    base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 3}
    over = {"a": {"y": 9}, "b": [7], "c": 4}
    out = _deep_merge(base, over)
    assert out["a"] == {"x": 1, "y": 9}  # merged, x survived
    assert out["b"] == [7]  # lists replace
    assert out["c"] == 4


# ── gate mode ────────────────────────────────────────────────────────────────


def test_every_gate_ships_advisory():
    """V6-T55: no gate may change an answer until its impact report has been reviewed."""
    p = load_policy("any")
    for gate in ("freshness", "completeness", "agreement", "spatial_adequacy", "calibration"):
        assert p.gate_mode(gate) is GateMode.ADVISORY, f"{gate} must ship advisory"
        assert p.is_enforcing(gate) is False


def test_a_gate_with_no_config_entry_is_advisory():
    """A gate added without config records but does not act - the safe direction."""
    assert load_policy("any").gate_mode("a_gate_nobody_configured") is GateMode.ADVISORY


def test_a_gate_with_a_nonsense_mode_is_advisory(tmp_path):
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump({"gates": {"freshness": {"mode": "banana"}}}), encoding="utf-8"
    )
    assert load_policy("bldgX", input_dir=tmp_path).gate_mode("freshness") is GateMode.ADVISORY


def test_a_building_can_switch_one_gate_to_enforcing(tmp_path):
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump({"gates": {"freshness": {"mode": "enforcing"}}}), encoding="utf-8"
    )
    p = load_policy("bldgX", input_dir=tmp_path)
    assert p.is_enforcing("freshness") is True
    assert p.is_enforcing("completeness") is False  # others unaffected
