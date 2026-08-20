"""V4-T17 tests — candidate enumeration + coverage ledger (offline)."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.candidates import (
    FLOOR_CHANGE_PENALTY_M,
    CoverageLedger,
    GeometryInfo,
    enumerate_candidates,
)
from orchestrator.services.deliberation.capability_schema import (
    AdmissionResult,
    AmenityInstance,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_MISSING,
    STATUS_PRESENT,
    SpaceCoverage,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"


def _space(local, floor, noise=STATUS_PRESENT):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor=floor)
    sc.modalities = {
        "noise": {"status": noise, "sensor": "", "uuid": f"u-{local}", "stored_at": "noise_data"},
    }
    return sc


def _schema(spaces, amenities=None):
    return BuildingCapabilitySchema(
        building_id="anybldg", namespace=NS, spaces=spaces, amenities=amenities or []
    )


def _ir(hardness=Hardness.SOFT):
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE, hardness=hardness)],
    )


def test_floor_scope_and_sensor_handles():
    schema = _schema([_space("RM001", "floor0"), _space("RM101", "floor1")])
    cands, ledger = enumerate_candidates(
        _ir(), AdmissionResult(verdict="admit", floor_anchor="floor1"), schema
    )
    assert [c.label for c in cands] == ["RM101"]
    assert cands[0].sensors["noise"]["uuid"] == "u-RM101"
    assert ledger.in_scope == 1 and ledger.considered == 1
    assert ledger.instrumented["noise"] == 1


def test_hard_constraint_excludes_with_ledger_reason():
    schema = _schema([_space("RM001", "floor0"), _space("RM002", "floor0", noise=STATUS_MISSING)])
    cands, ledger = enumerate_candidates(
        _ir(Hardness.HARD), AdmissionResult(verdict="admit"), schema
    )
    assert [c.label for c in cands] == ["RM001"]
    assert len(ledger.excluded) == 1
    assert "hard requirement" in ledger.excluded[0].reason
    assert ledger.in_scope == 2 and ledger.considered == 1


def test_soft_constraint_keeps_uninstrumented_spaces():
    schema = _schema([_space("RM001", "floor0"), _space("RM002", "floor0", noise=STATUS_MISSING)])
    cands, ledger = enumerate_candidates(
        _ir(Hardness.SOFT), AdmissionResult(verdict="admit"), schema
    )
    assert len(cands) == 2  # soft: kept, scorer handles insufficient data honestly
    assert ledger.instrumented["noise"] == 1


def test_duplicate_iris_dedupe():
    schema = _schema([_space("RM001", "floor0"), _space("RM001", "floor0")])
    cands, _ = enumerate_candidates(_ir(), AdmissionResult(verdict="admit"), schema)
    assert len(cands) == 1


def test_amenity_distance_same_and_cross_floor():
    spaces = [_space("RM001", "floor0"), _space("RM101", "floor1"), _space("WATER", "floor0")]
    schema = _schema(
        spaces,
        amenities=[
            AmenityInstance(
                iri=f"{NS}A", kind="DrinkingWater", space_iri=f"{NS}WATER", floor="floor0"
            )
        ],
    )
    geometry = {
        f"{NS}RM001": GeometryInfo(centroid_m=(0.0, 0.0), floor_index=0),
        f"{NS}RM101": GeometryInfo(centroid_m=(3.0, 4.0), floor_index=1),
        f"{NS}WATER": GeometryInfo(centroid_m=(3.0, 4.0), floor_index=0),
    }
    cands, ledger = enumerate_candidates(
        _ir(), AdmissionResult(verdict="admit", amenity_anchor="DrinkingWater"), schema, geometry
    )
    by_label = {c.label: c for c in cands}
    assert by_label["RM001"].distance_to_anchor_m == pytest.approx(5.0)  # 3-4-5 triangle
    assert by_label["RM101"].distance_to_anchor_m == pytest.approx(FLOOR_CHANGE_PENALTY_M)
    assert by_label["WATER"].distance_to_anchor_m == 0.0  # amenity in the room itself


def test_no_geometry_with_amenity_anchor_excludes_and_records():
    spaces = [_space("RM001", "floor0"), _space("WATER", "floor0")]
    schema = _schema(
        spaces,
        amenities=[
            AmenityInstance(
                iri=f"{NS}A", kind="DrinkingWater", space_iri=f"{NS}WATER", floor="floor0"
            )
        ],
    )
    cands, ledger = enumerate_candidates(
        _ir(),
        AdmissionResult(verdict="admit", amenity_anchor="DrinkingWater"),
        schema,
        geometry={f"{NS}WATER": GeometryInfo(centroid_m=(0, 0), floor_index=0)},
    )
    assert [c.label for c in cands] == ["WATER"]
    assert any("no geometry" in e.reason for e in ledger.excluded)


def test_ledger_summary_reads_like_a_coverage_statement():
    ledger = CoverageLedger(in_scope=5, considered=4, instrumented={"noise": 3})
    s = ledger.summary()
    assert "4 of 5 spaces considered" in s and "noise: 3/4" in s
