"""V4-T16 tests — Building Capability Schema + admission gate (offline)."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.capability_schema import (
    ADMIT,
    CLARIFY,
    DECLINE,
    AmenityInstance,
    BuildingCapabilitySchema,
    validate,
)
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_MISSING,
    STATUS_PRESENT,
    SpaceCoverage,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    AmbiguitySignal,
    Constraint,
    DecisionKind,
    Direction,
    SpatialQualifier,
    SpatialRelation,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"


def _space(local, floor, noise=STATUS_PRESENT, co2=STATUS_PRESENT):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor=floor)
    sc.modalities = {
        "noise": {"status": noise, "sensor": "", "uuid": "u", "stored_at": "noise_data"},
        "co2": {"status": co2, "sensor": "", "uuid": "u", "stored_at": "co2_data"},
    }
    return sc


def _schema(amenities=None):
    spaces = [
        _space("RM001", "floor0"),
        _space("RM002", "floor0", co2=STATUS_MISSING),
        _space("RM101", "floor1"),
    ]
    return BuildingCapabilitySchema(
        building_id="anybldg",
        namespace=NS,
        spaces=spaces,
        amenities=(
            amenities
            if amenities is not None
            else [
                AmenityInstance(
                    iri=f"{NS}A1", kind="DrinkingWater", space_iri=f"{NS}RM001", floor="floor0"
                ),
            ]
        ),
    )


def _ir(constraints=None, spatial=None, signals=None):
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=(
            constraints
            if constraints is not None
            else [Constraint(modality="noise", direction=Direction.MINIMIZE)]
        ),
        spatial=spatial or [],
        signals=signals or [],
    )


def test_admit_clean_query_with_coverage():
    res = validate(_ir(), _schema())
    assert res.verdict == ADMIT
    assert res.coverage["noise"] == {"present": 3, "total": 3}


def test_partial_coverage_still_admits_with_ledger_numbers():
    res = validate(_ir([Constraint(modality="co2", direction=Direction.MINIMIZE)]), _schema())
    assert res.verdict == ADMIT
    assert res.coverage["co2"] == {"present": 2, "total": 3}


def test_zero_coverage_declines_never_fabricates():
    schema = _schema()
    for s in schema.spaces:
        s.modalities["co2"]["status"] = STATUS_MISSING
    res = validate(_ir([Constraint(modality="co2", direction=Direction.MINIMIZE)]), schema)
    assert res.verdict == DECLINE
    assert res.missing_modalities == ["co2"]


def test_compiler_signals_route_to_clarify():
    res = validate(
        _ir(signals=[AmbiguitySignal(kind="unmapped_term", phrase="radiation")]), _schema()
    )
    assert res.verdict == CLARIFY
    assert res.question.slot == "signals"


def test_floor_anchor_normalizes_or_clarifies():
    ok = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.ON_FLOOR, anchor="Floor 1")]),
        _schema(),
    )
    assert ok.verdict == ADMIT and ok.floor_anchor == "floor1"
    bad = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.ON_FLOOR, anchor="floor 9")]),
        _schema(),
    )
    assert bad.verdict == CLARIFY and bad.question.slot == "floor"
    assert bad.question.options == ["floor0", "floor1"]


def test_amenity_anchor_resolves_clarifies_or_declines():
    ok = validate(
        _ir(
            spatial=[
                SpatialQualifier(relation=SpatialRelation.NEAR_AMENITY, anchor="drinkingwater")
            ]
        ),
        _schema(),
    )
    assert ok.verdict == ADMIT and ok.amenity_anchor == "DrinkingWater"
    unk = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.NEAR_AMENITY, anchor="aquarium")]),
        _schema(),
    )
    assert unk.verdict == CLARIFY and "DrinkingWater" in unk.question.options
    none = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.NEAR_AMENITY, anchor="aquarium")]),
        _schema(amenities=[]),
    )
    assert none.verdict == DECLINE


def test_space_anchor_unique_ambiguous_missing():
    ok = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.IN_SPACE, anchor="RM101")]),
        _schema(),
    )
    assert ok.verdict == ADMIT and ok.space_anchor == f"{NS}RM101"
    amb = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.IN_SPACE, anchor="RM0")]), _schema()
    )
    assert amb.verdict == CLARIFY and len(amb.question.options) == 2
    gone = validate(
        _ir(spatial=[SpatialQualifier(relation=SpatialRelation.IN_SPACE, anchor="ZZZ")]), _schema()
    )
    assert gone.verdict == CLARIFY and gone.question.slot == "space"
