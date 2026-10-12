"""'The quietest study area' scopes the ranking to the rooms that host one.

The compiler emits IN_SPACE 'StudyArea' for it. Looked up as a room name, the anchor matched no
space and the reader was asked "I can't find 'StudyArea'. Did you mean one of: Room0.01, ...?".
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.candidates import enumerate_candidates
from orchestrator.services.deliberation.capability_schema import (
    ADMIT,
    CLARIFY,
    AmenityInstance,
    BuildingCapabilitySchema,
    validate,
)
from orchestrator.services.deliberation.coverage_audit import STATUS_PRESENT, SpaceCoverage
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    SpatialQualifier,
    SpatialRelation,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/anybldg#"


def _space(local, floor):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor=floor)
    sc.modalities = {
        "noise": {"status": STATUS_PRESENT, "sensor": "", "uuid": local, "stored_at": "t"}
    }
    return sc


def _schema():
    return BuildingCapabilitySchema(
        building_id="anybldg",
        namespace=NS,
        spaces=[_space("RM001", "floor0"), _space("RM101", "floor1"), _space("RM102", "floor1")],
        amenities=[
            AmenityInstance(
                iri=f"{NS}S1", kind="StudyArea", space_iri=f"{NS}RM101", floor="floor1"
            ),
            AmenityInstance(
                iri=f"{NS}S2", kind="StudyArea", space_iri=f"{NS}RM102", floor="floor1"
            ),
            AmenityInstance(
                iri=f"{NS}W1", kind="DrinkingWater", space_iri=f"{NS}RM001", floor="floor0"
            ),
        ],
    )


def _ir(anchor, relation=SpatialRelation.IN_SPACE):
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        spatial=[SpatialQualifier(relation=relation, anchor=anchor)],
        signals=[],
    )


@pytest.mark.parametrize("anchor", ["StudyArea", "study area", "study areas", "study_area"])
def test_an_amenity_kind_is_admitted_as_a_scope(anchor):
    res = validate(_ir(anchor), _schema())
    assert res.verdict == ADMIT
    assert res.host_kind_anchor == "StudyArea"
    assert res.space_anchor is None


def test_the_ranking_considers_only_the_spaces_hosting_it():
    schema = _schema()
    ir = _ir("StudyArea")
    cands, _ledger = enumerate_candidates(ir, validate(ir, schema), schema)
    assert sorted(c.space_iri for c in cands) == [f"{NS}RM101", f"{NS}RM102"]


def test_a_room_name_still_resolves_as_a_room():
    res = validate(_ir("RM001"), _schema())
    assert res.space_anchor == f"{NS}RM001"
    assert res.host_kind_anchor is None


def test_an_unknown_name_still_asks():
    assert validate(_ir("Ballroom"), _schema()).verdict == CLARIFY
