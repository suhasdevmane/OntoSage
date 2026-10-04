# -*- coding: utf-8 -*-
"""Calibration-gated standards claims (V6-T34) and independent backups (V6-T36).

Two rules whose failure modes are the most consequential in V6:

  R-12 / scenario 7 — a standards verdict from an uncalibrated instrument carries the
                      authority of the standard with none of its rigour. It gets quoted; the
                      caveat attached to it does not.
  R-10            — a backup sharing the primary's failure mode is not a backup. Offering the
                      top two ranked options is exactly what the catalogues warn against,
                      because ranking is by quality and the two best rooms are usually the two
                      best rooms off the same air handler.

**The consequence map was the real defect here.** `by_shape` was keyed on invented shape names
(`compliance_verdict`, `standards_check`, `control_command`) that the router never emits, so
`consequence_class()` returned `informational` for every question in the system and the whole
of T32's scaling was inert — no claim ever required calibration or an authoritative source.
The first test below is the one that would have caught it.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services.evidence.independence import Candidate, choose
from orchestrator.services.evidence.policy import load_policy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


# ── T32/T34: the consequence map must speak the router's language ────────────


@pytest.mark.parametrize(
    "intent,expected",
    [
        ("compliance", "safety_or_compliance"),
        ("safety_report", "safety_or_compliance"),
        ("control", "safety_or_compliance"),
        ("recommend", "operational"),
        ("events", "operational"),
        ("sensor_data", "informational"),
        ("analytics", "informational"),
    ],
)
def test_the_consequence_map_uses_real_intent_names(intent, expected):
    """The defect this parametrisation exists for: the map was keyed on shape names the
    router never emits, so every question resolved to informational and nothing escalated."""
    assert load_policy().consequence_class(intent) == expected


def test_every_mapped_shape_is_a_real_intent_or_a_declared_alias():
    """A key nobody emits is dead config that looks like policy."""
    import re
    from pathlib import Path

    import yaml

    # Base registry PLUS any per-building overlay: `lab_booking` is declared in bldg1's
    # input/intents.yaml, so a check reading only the base file would call a real intent
    # dead config. Overlays are globbed rather than named, so this holds in the parked state
    # and for a building that declares intents this repo has never seen.
    txt = Path("orchestrator/intents/intent_definitions.yaml").read_text(encoding="utf-8")
    for overlay in list(Path(".").glob("input/intents.yaml")) + list(
        Path(".").glob("bldg*/intents.yaml")
    ):
        txt += overlay.read_text(encoding="utf-8")
    real = set(re.findall(r"^\s*-\s*name:\s*(\w+)", txt, re.M))
    aliases = {
        "compliance_verdict",
        "standards_check",
        "control_command",
        "accessibility_route",
        "booking_query",
        "wayfinding",
    }
    mapped = set(
        yaml.safe_load(Path("config/evidence_policy.yaml").read_text(encoding="utf-8"))[
            "consequence"
        ]["by_shape"]
    )
    unknown = mapped - real - aliases
    assert not unknown, f"consequence classes keyed on shapes nothing emits: {sorted(unknown)}"


def test_an_unlisted_shape_defaults_to_the_permissive_end():
    """A NEW shape must not silently acquire a safety threshold it was not designed for —
    nor silently bypass one, which is why safety shapes are listed explicitly."""
    assert load_policy().consequence_class("some_brand_new_intent") == "informational"


def test_only_safety_claims_require_calibration():
    p = load_policy()
    assert p.requires_calibration("safety_or_compliance")
    assert not p.requires_calibration("informational")
    assert p.forbids_unknown_calibration("safety_or_compliance")


# ── T34: the three calibration states ────────────────────────────────────────


@pytest.mark.parametrize(
    "entry,expected",
    [
        (None, "unknown"),
        ({}, "unknown"),
        ({"calibrated_on": "2026-05-01"}, "calibrated"),
        ({"calibrated_on": "2026-05-01", "due_on": "2027-05-01"}, "calibrated"),
        ({"calibrated_on": "2025-01-01", "due_on": "2026-04-11"}, "expired"),
    ],
)
def test_calibration_state_is_derived_conservatively(entry, expected):
    """Unknown is the DEFAULT and is never upgraded by silence — an undeclared calibration is
    not a passing one, and defaulting it to `calibrated` would be the most dangerous default
    in the system."""
    from orchestrator.services.evidence.assemble import _calibration_state

    assert _calibration_state(entry, NOW) == expected


def test_a_date_without_a_due_date_still_counts_as_calibrated():
    """A building that records the date but not the interval has still calibrated the
    instrument; demanding both would refuse every building that does the common thing."""
    from orchestrator.services.evidence.assemble import _calibration_state

    assert _calibration_state({"calibrated_on": "2026-05-01"}, NOW) == "calibrated"


# ── T36: an independent backup, or an honest absence ─────────────────────────


def test_the_backup_must_not_share_a_dependency_with_the_primary():
    """The naive implementation — offer the top two — is the thing R-10 forbids."""
    v = choose(
        [
            Candidate("r1", "Room 5.01", 0.9, {"ahu#A", "circuit#1"}),
            Candidate("r2", "Room 5.02", 0.8, {"ahu#A", "circuit#1"}),  # same AHU: not a backup
            Candidate("r3", "Room 2.10", 0.6, {"ahu#B", "circuit#2"}),
        ]
    )
    assert v.primary.identifier == "r1"
    assert v.backup is not None and v.backup.identifier == "r3", (
        "the runner-up shares the primary's air handler; a single failure takes both"
    )


def test_no_independent_option_is_stated_not_faked():
    v = choose(
        [
            Candidate("r1", "Room 5.01", 0.9, {"ahu#A"}),
            Candidate("r2", "Room 5.02", 0.8, {"ahu#A"}),
        ]
    )
    assert not v.has_independent_backup
    text = v.describe()
    assert "No independent backup exists" in text
    assert "ahu#A".rsplit("#", 1)[-1] in text, (
        "the shared dependency must be named — it is the actionable fact, the single point "
        "of failure the estate can fix"
    )


def test_a_single_candidate_says_there_is_nothing_to_fall_back_to():
    v = choose([Candidate("r1", "Room 5.01", 0.9, {"ahu#A"})])
    assert not v.has_independent_backup
    assert "nothing to fall back to" in v.reason


def test_the_ranking_is_never_reordered():
    """This module knows nothing about what makes an option good and must not silently
    re-sort a ranking it did not compute."""
    v = choose(
        [
            Candidate("r1", "A", 0.5, {"x"}),
            Candidate("r2", "B", 0.9, {"y"}),  # higher score, but second in the given order
        ]
    )
    assert v.primary.identifier == "r1"


def test_independence_never_uses_distance_or_floor():
    """Two rooms on different floors can share a riser; two adjacent rooms can be on separate
    circuits. Only the declared dependency graph knows, which is why proximity appears
    nowhere — the same reason spatial_facts has no distance term (BUG-189)."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/independence.py").read_text(encoding="utf-8")
    body = src[src.index("def choose(") :]
    # CODE only. The first version scanned comments too and tripped on the sentence
    # "deliberately not distance" — flagging the very statement that documents the rule as a
    # violation of it. A prose ban is not an implementation detail; the executable lines are.
    code = "; ".join(
        ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("#", '"""'))
    )
    for banned in ("distance", "proximity", "floor_number", "nearest"):
        assert banned not in code.lower(), f"{banned!r} influences the backup choice"
