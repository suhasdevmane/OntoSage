# -*- coding: utf-8 -*-
"""BUG-147 / CAVEAT-154: one record per room, not two half-records.

The DWG and PDF passes describe the same rooms and each holds half of what a
room needs — geometry on one side, ontology identity on the other. They were
paired on ``zone_id``, but the DWG mints positional CAD ids ("0Z001") while the
PDF slugs the room name ("fp.bldg2.0.rm001a_room"), so the two id spaces never
intersect and every room was emitted twice. Half of every manifest was
unlinkable by construction, which is why the live join rate was exactly 50.0%
on every floor of every building rather than some noisy fraction.
"""

from __future__ import annotations

import pytest

from orchestrator.services.floor_plan_registry import (
    FloorPlanRegistry,
    _norm_label,
    _unique_by_label,
)
from shared.models import Space

pytestmark = pytest.mark.unit


def dwg_space(zone_id, label, area=20.0):
    """A CAD space: geometry and adjacency, but no identity."""
    return Space(
        id=f"bldg2.{zone_id}",
        zone_id=zone_id,
        label=label,
        type="zone",
        centroid={"x": 0.1, "y": 0.2},
        polygon=[{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        area_m2=area,
        perimeter_m=18.0,
        layer="A-AREA-ROOM",
        adjacent_spaces=["0Z002"],
        source="dwg",
        confidence=0.98,
    )


def pdf_space(zone_id, label, iri="http://buildsys.org/ontologies/bldg2#RM001A_room"):
    """A PDF/LLM space: identity, but no geometry whatsoever."""
    return Space(
        id=f"bldg2.{zone_id}",
        zone_id=zone_id,
        label=label,
        type="unknown",
        ontology_iri=iri,
        source="llm",
        confidence=0.75,
    )


@pytest.fixture
def registry():
    return FloorPlanRegistry.__new__(FloorPlanRegistry)


class TestTheDuplicationItself:
    def test_disjoint_id_schemes_still_produce_one_room(self, registry):
        """The exact live shape: 0Z001 vs fp.bldg2.0.rm001a_room, same label."""
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room")],
            [pdf_space("fp.bldg2.0.rm001a_room", "RM001A_room")],
        )
        assert len(merged) == 1, f"expected one room, got {[s.zone_id for s in merged]}"

    def test_the_surviving_record_has_BOTH_halves(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room", area=20.0)],
            [pdf_space("fp.bldg2.0.rm001a_room", "RM001A_room")],
        )
        s = merged[0]
        assert s.area_m2 == 20.0, "lost the DWG geometry"
        assert s.polygon and s.centroid, "lost the DWG polygon/centroid"
        assert s.ontology_iri, "lost the PDF ontology identity"

    def test_a_whole_floor_reaches_a_100_percent_join_rate(self, registry):
        """The join rate BUG-147 is actually about, pinned."""
        dwg = [dwg_space(f"0Z{i:03d}", f"RM{i:03d}_room") for i in range(1, 17)]
        pdf = [pdf_space(f"fp.bldg2.0.rm{i:03d}_room", f"RM{i:03d}_room") for i in range(1, 17)]
        merged = registry._merge_spaces(dwg, pdf)
        assert len(merged) == 16, "duplicates survived the merge"
        linked = [s for s in merged if s.ontology_iri]
        assert len(linked) == 16, f"join rate {len(linked)}/16, not 100%"
        assert all(s.area_m2 for s in merged), "some room lost its geometry"


class TestIdentityIsPreserved:
    def test_the_dwg_zone_id_survives_because_adjacency_references_it(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room")],
            [pdf_space("fp.bldg2.0.rm001a_room", "RM001A_room")],
        )
        assert merged[0].zone_id == "0Z001"
        assert merged[0].adjacent_spaces == ["0Z002"]

    def test_the_pdf_id_is_kept_as_an_alias_so_old_lookups_resolve(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room")],
            [pdf_space("fp.bldg2.0.rm001a_room", "RM001A_room")],
        )
        assert "fp.bldg2.0.rm001a_room" in merged[0].aliases

    def test_a_space_is_never_its_own_alias(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room")],
            [pdf_space("0Z001", "RM001A_room")],
        )
        assert "0Z001" not in merged[0].aliases


class TestWhatMustNotBeMerged:
    def test_an_ambiguous_label_merges_nothing(self, registry):
        """Two PDF rooms share a label: fusing either would corrupt both."""
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "Office")],
            [pdf_space("fp.a", "Office"), pdf_space("fp.b", "Office")],
        )
        assert len(merged) == 3, "an unresolvable label must not be guessed at"

    def test_one_pdf_space_cannot_be_claimed_twice(self, registry):
        """Two identically-labelled CAD zones, one PDF room."""
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "Lab"), dwg_space("0Z002", "Lab")],
            [pdf_space("fp.lab", "Lab")],
        )
        assert sum(1 for s in merged if s.ontology_iri) == 1, "identity was duplicated"

    def test_genuinely_different_rooms_stay_separate(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "RM001_room")],
            [pdf_space("fp.rm999", "RM999_room")],
        )
        assert len(merged) == 2

    def test_an_unlabelled_cad_space_matches_nothing(self, registry):
        merged = registry._merge_spaces(
            [dwg_space("0Z001", "")],
            [pdf_space("fp.rm001", "RM001_room")],
        )
        assert len(merged) == 2


class TestLabelNormalisation:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("RM001A_room", "RM001A Room"),
            ("rm001a room", "RM001A_ROOM"),
            ("Zone 1.01", "zone-1.01"),
        ],
    )
    def test_separators_and_case_do_not_make_a_different_room(self, a, b):
        assert _norm_label(a) == _norm_label(b)

    def test_different_rooms_do_not_collide(self):
        assert _norm_label("RM001_room") != _norm_label("RM002_room")

    def test_a_repeated_label_is_dropped_from_the_index(self):
        idx = _unique_by_label([pdf_space("a", "Office"), pdf_space("b", "Office")])
        assert _norm_label("Office") not in idx

    def test_an_empty_label_is_never_indexed(self):
        assert _unique_by_label([pdf_space("a", "")]) == {}


class TestZoneIdMatchStillWins:
    def test_a_shared_zone_id_pairs_without_needing_the_label(self, registry):
        """The original path must keep working even when labels disagree."""
        merged = registry._merge_spaces(
            [dwg_space("5.28", "Zone 5.28")],
            [pdf_space("5.28", "Seminar Room")],
        )
        assert len(merged) == 1
        assert merged[0].label == "Seminar Room", "a richer PDF label should win over 'Zone X'"
        assert merged[0].ontology_iri


class TestIdempotenceUnderReingestion(TestTheDuplicationItself):
    """BUG-198: the merged manifest is written to the path the PDF pipeline
    also writes to, so a re-ingestion can hand _merge_spaces its own previous
    output as the "PDF" side. That output already carries the DWG copies, which
    makes every label ambiguous and re-emits the duplicates forever — the reason
    the live floors stayed at 32 spaces across repeated re-ingestions."""

    def test_merging_a_merged_result_again_changes_nothing(self, registry):
        dwg = [dwg_space("0Z001", "RM001A_room"), dwg_space("0Z002", "RM001B_room")]
        pdf = [
            pdf_space("fp.bldg2.0.rm001a_room", "RM001A_room"),
            pdf_space("fp.bldg2.0.rm001b_room", "RM001B_room"),
        ]
        once = registry._merge_spaces(dwg, pdf)
        twice = registry._merge_spaces(dwg, once)
        assert len(once) == 2
        assert len(twice) == len(once), "re-ingestion re-inflated the space list"
        assert {s.zone_id for s in twice} == {s.zone_id for s in once}
        assert all(s.ontology_iri and s.area_m2 for s in twice), "a round trip lost half a room"

    def test_a_leftover_copy_is_dropped_but_a_merged_record_is_not(self, registry):
        """Both are CAD-sourced; only the one whose label is contested is stale."""
        stale = registry._merge_spaces(
            [dwg_space("0Z001", "RM001A_room")],
            [
                dwg_space("0Z001", "RM001A_room"),  # leftover CAD copy
                pdf_space("fp.rm001a", "RM001A_room"),  # its PDF twin
            ],
        )
        assert len(stale) == 1 and stale[0].ontology_iri, "the wrong copy was kept"

        lone = registry._merge_spaces([], [dwg_space("0Z001", "RM001A_room")])
        assert len(lone) == 1, "a record that owns its label must survive"

    def test_a_legacy_unpaired_manifest_collapses_on_the_next_merge(self, registry):
        """The live shape before the fix: 32 records for 16 rooms."""
        dwg = [dwg_space(f"0Z{i:03d}", f"RM{i:03d}_room") for i in range(1, 17)]
        legacy = dwg + [
            pdf_space(f"fp.bldg2.0.rm{i:03d}_room", f"RM{i:03d}_room") for i in range(1, 17)
        ]
        assert len(legacy) == 32
        merged = registry._merge_spaces(dwg, legacy)
        assert len(merged) == 16, f"legacy duplicates survived: {len(merged)}"
        assert all(s.ontology_iri and s.area_m2 for s in merged)
