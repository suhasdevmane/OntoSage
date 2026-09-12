# -*- coding: utf-8 -*-
"""Provenance is judged per observation, and silence is never measurement.

V12-04 parts 1 and 2, review risk R4 and case B06.

THE FIXTURES ARE THE LIVE BUILDING, NOT AN INVENTION
-----------------------------------------------------
Measured on bldg1, 2026-09-11:

    graph      1,408 points declare isSimulated true, 0 declared false, 1,356 silent
               of the silent, 685 reference `database1` (real instruments) and the rest
               reference stores the registry already declares synthetic
    store      sensor_data: 697,329 rows, 2025-01-01 -> 2026-09-11
                 <= 2025-03-09   576,557  the owner's real snapshot
                 >  2025-03-09   120,772  generated, PUBLISH_WIDE=true

The real data stops eighteen months ago. So every question about current conditions reads
generated rows from points that are correctly declared measured — which is precisely why
a per-POINT or per-TABLE flag cannot answer the question and a per-observation rule must.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.observation_provenance import (  # noqa: E402
    Origin,
    observation_origin,
    store_boundary,
)

BOUNDARY = "2025-03-09T23:59:59"


# ── the case a per-table flag gets wrong ─────────────────────────────────────


def test_a_recent_reading_from_the_mixed_table_is_generated():
    """The live case: a "right now" question on bldg1 reads generated rows."""
    v = observation_origin(
        point_simulated=False, measured_through=BOUNDARY, observed_at="2026-09-11 16:39:23"
    )
    assert v.origin is Origin.SIMULATED
    assert v.basis == "observation"
    assert not v.admissible_for_operational_claim


def test_a_snapshot_era_reading_from_the_same_point_is_measured():
    """Same point, same table, different row — and the opposite verdict. No per-table or
    per-point flag can produce both."""
    v = observation_origin(
        point_simulated=False, measured_through=BOUNDARY, observed_at="2025-02-14 09:00:00"
    )
    assert v.origin is Origin.MEASURED
    assert v.basis == "observation"
    assert v.admissible_for_operational_claim


def test_the_boundary_instant_itself_counts_as_measured():
    v = observation_origin(
        point_simulated=False, measured_through=BOUNDARY, observed_at="2025-03-09 23:59:59"
    )
    assert v.origin is Origin.MEASURED


# ── silence is not measurement ───────────────────────────────────────────────


def test_an_undeclared_point_with_an_undeclared_store_is_unknown():
    """1,356 points said nothing, and every consumer read that as real. This is the defect
    V12-04 part 1 exists to remove."""
    v = observation_origin(point_simulated=None, store_synthetic=None)
    assert v.origin is Origin.UNKNOWN
    assert not v.admissible_for_operational_claim
    assert "silence is not evidence" in v.reason


def test_unknown_is_inadmissible_for_an_operational_claim():
    """The review's whole point: an attractive candidate of unestablished origin must not
    win a recommendation about the real building."""
    assert not observation_origin(point_simulated=None).admissible_for_operational_claim


def test_a_missing_timestamp_against_a_mixed_store_is_unknown_not_measured():
    """A reading that cannot be placed on either side of the boundary is not given the
    benefit of the doubt."""
    v = observation_origin(point_simulated=False, measured_through=BOUNDARY, observed_at=None)
    assert v.origin is Origin.UNKNOWN
    assert "not established" in v.reason


def test_an_unreadable_boundary_does_not_silently_pass_everything():
    v = observation_origin(
        point_simulated=False, measured_through="whenever", observed_at="2026-01-01"
    )
    assert v.origin is Origin.UNKNOWN


# ── precedence ───────────────────────────────────────────────────────────────


def test_a_saturate_point_is_simulated_whatever_the_date():
    """A provisioned point has no real readings at all — the boundary cannot rescue it."""
    v = observation_origin(
        point_simulated=True, measured_through=BOUNDARY, observed_at="2025-01-02 00:00:00"
    )
    assert v.origin is Origin.SIMULATED
    assert v.basis == "point"


def test_a_synthetic_store_beats_an_undeclared_point():
    v = observation_origin(point_simulated=None, store_synthetic=True)
    assert v.origin is Origin.SIMULATED and v.basis == "store"


def test_a_measured_point_with_no_boundary_is_measured():
    v = observation_origin(point_simulated=False)
    assert v.origin is Origin.MEASURED and v.basis == "point"


# ── it must not crash on real-world input ────────────────────────────────────


@pytest.mark.parametrize(
    "ts",
    [
        "2026-09-11 16:39:23",
        "2026-09-11T16:39:23",
        "2026-09-11T16:39:23Z",
        "2026-09-11T16:39:23+01:00",
        datetime(2026, 9, 11, 16, 39, 23),
        "2026-09-11",
    ],
)
def test_every_timestamp_shape_the_stores_actually_emit(ts):
    """An offset-aware row against a naive boundary must not raise — that would turn a
    provenance question into a crash, and the lane would lose the answer entirely."""
    v = observation_origin(point_simulated=False, measured_through=BOUNDARY, observed_at=ts)
    assert v.origin is Origin.SIMULATED, "all of these are after the boundary"


# ── the boundary is declared, not hardcoded ──────────────────────────────────


def test_the_boundary_is_read_from_the_registry():
    reg = {"databases": {"database1": {"nature": "real", "measured_through": BOUNDARY}}}
    assert store_boundary(reg, "database1") == BOUNDARY
    assert store_boundary(reg, "nope") is None
    assert store_boundary({}, "database1") is None


def test_bldg1_declares_no_boundary_and_that_is_deliberate():
    """Owner decision, 2026-09-11: treat everything in `database1` as real.

    An earlier pass added `measured_through: 2025-03-09T23:59:59` after measuring that the
    wide table holds a real snapshot plus generated top-up rows. That read the DATA
    correctly and the INTENT wrongly. The owner's position is that this database stands in
    for the real one and will be repointed at real credentials; the 680 `bldg:`-prefixed
    sensors stored here are real instruments and their readings are real throughout. The
    loaded/generated split is a development artefact, not something an answer should
    reason about.

    So the assertion is inverted: bldg1 must declare NO boundary. The mechanism stays in
    `observation_provenance.py` because another building may genuinely need it — a store
    that really does change character on a date — and the module is building-agnostic.

    This does not weaken R4. The 1,408 SATURATE-provisioned points are still simulated and
    still excluded from an operational ranking; that is the protection that matters, and
    it keys off the point, not the date.
    """
    import yaml
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "input" / "database_registry.yaml"
    if not path.is_file():
        pytest.skip("no active building")
    reg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert store_boundary(reg, "database1") is None, (
        "database1 declares a measured_through boundary again. The owner decided on "
        "2026-09-11 that everything in this store is to be treated as real; a boundary "
        "here would start reporting this building's own sensors as simulated."
    )


def test_the_boundary_mechanism_still_works_for_a_building_that_needs_one():
    """Removing bldg1's boundary must not remove the capability — another building may
    have a store that genuinely changed character on a date."""
    reg = {"databases": {"other": {"measured_through": "2024-06-30T23:59:59"}}}
    assert store_boundary(reg, "other") == "2024-06-30T23:59:59"
    v = observation_origin(
        point_simulated=False,
        measured_through=store_boundary(reg, "other"),
        observed_at="2025-01-01 00:00:00",
    )
    assert v.origin is Origin.SIMULATED
