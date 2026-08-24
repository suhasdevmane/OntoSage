# -*- coding: utf-8 -*-
"""The Question-to-Observability Matrix (V6-T09).

Master 13.1's central artefact: for every question shape, what answering it requires and
whether this building has it. The plan calls it the thing that *"prevents the project from
claiming capabilities that the physical deployment cannot support"*.

Two properties carry the whole value and are easy to lose:

1. **Every unsatisfied row names the SPECIFIC missing element.** "62% observable" tells an
   estate manager nothing. "occupancy: no sensor in 41 of 52 spaces" and "availability: no
   booking system connected" are two different jobs for two different people, and separating
   them is what turns the readiness split from an embarrassment into a work list.
2. **Causes are never summed into one score.** Installing a sensor, declaring a cadence,
   connecting a booking system and commissioning a calibration are four different jobs; a
   single percentage hides which one is blocking.
"""

import pytest

from orchestrator.services.evidence.matrix import (
    AUTHORITATIVE_SYSTEM_BY_SHAPE,
    ShapeRequirement,
    assess_shape,
    summarise,
)

pytestmark = pytest.mark.unit


def _req(**kw):
    base = dict(shape="sensor_data", modalities=("temperature",), spatial_resolution="space")
    base.update(kw)
    return ShapeRequirement(**base)


def test_a_fully_covered_shape_is_satisfied():
    r = assess_shape(
        _req(),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 1.0},
    )
    assert r.satisfied and r.verdict == "satisfied"


def test_an_absent_modality_says_the_variable_cannot_be_read_at_all():
    """Distinct from partial coverage: no sensor anywhere is a procurement job, while partial
    coverage is a list of rooms. Collapsing them would merge two different remedies."""
    r = assess_shape(_req(), instrumented_modalities=[])
    assert not r.satisfied
    assert "cannot be read at all" in r.missing[0]


def test_partial_coverage_is_reported_with_its_number():
    r = assess_shape(
        _req(),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 0.62},
    )
    assert not r.satisfied
    assert "62%" in r.missing[0], f"the share must be stated: {r.missing}"


def test_a_building_scope_shape_is_not_penalised_for_partial_room_coverage():
    """ "How many temperature sensors does this building have?" needs no sensor in every room.
    Judging a building-level question by room-level coverage would report a gap that does not
    affect it."""
    r = assess_shape(
        _req(spatial_resolution="building"),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 0.62},
    )
    assert r.satisfied, r.missing


def test_a_missing_cadence_is_its_own_finding():
    r = assess_shape(
        _req(min_completeness=0.9),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 1.0},
        cadence_declared={"temperature": False},
    )
    assert any("archival cadence" in m for m in r.missing)


def test_calibration_is_judged_as_a_SHARE_not_as_any_of():
    """One commissioned instrument must not vouch for a whole building's standards claims — a
    safety verdict needs every contributing sensor calibrated. The any-of form of this check
    hid six real gaps on the live building until it was made share-based."""
    partial = assess_shape(
        _req(requires_calibration=True, consequence_class="safety_or_compliance"),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 1.0},
        calibration_declared={"temperature": 0.4},
    )
    assert any("40%" in m for m in partial.missing), partial.missing

    full = assess_shape(
        _req(requires_calibration=True, consequence_class="safety_or_compliance"),
        instrumented_modalities=["temperature"],
        space_coverage={"temperature": 1.0},
        calibration_declared={"temperature": 1.0},
    )
    assert full.satisfied, full.missing


def test_an_unconnected_authoritative_system_is_named():
    r = assess_shape(
        _req(
            shape="events",
            modalities=(),
            requires_authoritative_source=True,
            authoritative_system="booking system",
        ),
        instrumented_modalities=["temperature"],
    )
    assert not r.satisfied
    assert "booking system" in r.missing[0]
    assert "R-8" in r.missing[0], (
        "the row must say WHY a sensor cannot substitute, or the reader assumes it is an "
        "arbitrary restriction"
    )


def test_a_connected_system_satisfies_the_requirement():
    r = assess_shape(
        _req(
            shape="events",
            modalities=(),
            requires_authoritative_source=True,
            authoritative_system="booking system",
        ),
        instrumented_modalities=[],
        connected_systems=["booking system"],
    )
    assert r.satisfied


def test_the_summary_separates_causes_and_never_scores_them():
    rows = [
        assess_shape(_req(), instrumented_modalities=[]),
        assess_shape(
            _req(), instrumented_modalities=["temperature"], space_coverage={"temperature": 0.5}
        ),
        assess_shape(
            _req(min_completeness=0.9),
            instrumented_modalities=["temperature"],
            space_coverage={"temperature": 1.0},
            cadence_declared={"temperature": False},
        ),
    ]
    s = summarise(rows)
    assert s["no sensor"] == 1 and s["partial coverage"] == 1 and s["no cadence"] == 1
    assert (
        "score" not in s and "percent" not in s
    ), "a single figure would hide which of four different jobs is blocking each shape"


def test_entitlement_shapes_map_to_a_system_of_record():
    """The same mapping permission_guard enforces at answer time — one definition, not two."""
    assert AUTHORITATIVE_SYSTEM_BY_SHAPE["events"] == "booking system"
    assert "compliance" in AUTHORITATIVE_SYSTEM_BY_SHAPE


def test_the_generator_carries_no_building_literal():
    from pathlib import Path

    for f in ("scripts/build_observability_matrix.py", "orchestrator/services/evidence/matrix.py"):
        src = Path(f).read_text(encoding="utf-8").lower()
        for literal in ("abacws", "bldg1", "buildsys"):
            assert literal not in src, f"building literal {literal!r} in {f}"
