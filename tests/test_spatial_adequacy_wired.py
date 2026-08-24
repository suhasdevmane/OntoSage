# -*- coding: utf-8 -*-
"""The spatial-adequacy classifier has to be reachable, and it must not over-claim (V6-T13).

The tracker calls this "the single most important honesty gain in V6", and `classify()` was
written pure, unit-tested, and **called by nothing**. Every EvidenceSource therefore carried
the default grade NONE, and the gate — had it been wired — would have answered "no sensor
covers the space asked about" for every space in the building. The missing half was graph
access, not decision logic.

What this building actually declares, measured before any of it was written:

    hasLocation            3304     the containing space
    hasPart / isPartOf      637     siblings, through a shared parent
    feeds                    85     zone service
    environmentalBoundary     0     absent
    zoneValidated             0     absent

The two absent properties are the two that could *strengthen* a grade, so on this building the
classifier can reach IN_ROOM and PROXY and can never reach SERVED_ZONE. That is the
conservative direction and the correct one to be limited in: a building that has not validated
its zones has not earned the right to answer for a room from a zone. The test below pins it,
because a later change that starts awarding SERVED_ZONE without a validation triple would be
the exact substitution the non-substitution rule forbids.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus, SpatialAdequacy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
ROOM = "http://example.org/b#Room2.14"
CORRIDOR = "http://example.org/b#Corridor2"


def _rec(grades, **extra):
    return build_evidence_record(
        {
            "sql_result": {
                "results": {"data": [{"uuid": "u-1", "datetime": NOW.isoformat(), "value": 900}]}
            },
            "_prov_stores": [{"source_id": u, "kind": "sensor"} for u in grades],
            "_spatial_grades": grades,
            "_spatial_target": ROOM,
            **extra,
        },
        now=NOW,
    )


def test_an_in_room_sensor_raises_nothing():
    rec = _rec({"u-1": {"grade": "in_room", "reason": "the sensor is located in this space"}})
    assert not [g for g in rec.gates_advisory if "spatial" in g], rec.gates_advisory


def test_a_proxy_only_answer_is_flagged():
    """The case the supervisors test hardest and the one that actually occurs: the room
    exists, a sensor of the right kind exists, just not in that room."""
    rec = _rec(
        {
            "u-1": {
                "grade": "proxy",
                "reason": "the reading is from Corridor2, which is not the space asked about",
                "evidence_space": CORRIDOR,
            }
        }
    )
    hits = [g for g in rec.gates_advisory if "spatial" in g]
    assert hits, "a corridor reading answered a room question with no spatial verdict"
    assert "Corridor2" in hits[0], f"the verdict does not name the proxy: {hits[0]}"


def test_one_in_room_sensor_vindicates_a_crowd_of_proxies():
    """Judged on the STRONGEST grade, deliberately unlike freshness. One sensor genuinely in
    the room supports a room-level claim no matter how many corridor sensors were also
    returned; taking the weakest would refuse answers the building can properly make."""
    rec = _rec(
        {
            "u-1": {"grade": "proxy", "reason": "from Corridor2"},
            "u-2": {"grade": "proxy", "reason": "from Corridor3"},
            "u-3": {"grade": "in_room", "reason": "the sensor is located in this space"},
        }
    )
    assert not [g for g in rec.gates_advisory if "spatial" in g], rec.gates_advisory


def test_no_covering_sensor_at_all_is_flagged():
    rec = _rec({"u-1": {"grade": "none", "reason": "no sensor relates to this space"}})
    hits = [g for g in rec.gates_advisory if "spatial" in g]
    assert hits and "no sensor covers" in hits[0], hits


def test_the_grade_is_stamped_on_each_source():
    """A reader holding one source should not have to consult a record-level summary to learn
    whether THAT sensor covered the space."""
    rec = _rec(
        {
            "u-1": {"grade": "in_room", "reason": "x"},
            "u-2": {"grade": "proxy", "reason": "y"},
        }
    )
    by_id = {s.source_id: s.spatial_adequacy for s in rec.sources}
    assert by_id["u-1"] is SpatialAdequacy.IN_ROOM
    assert by_id["u-2"] is SpatialAdequacy.PROXY


def test_advisory_changes_no_answer():
    """Same contract as freshness: wiring a gate must not silently start refusing answers."""
    rec = _rec({"u-1": {"grade": "none", "reason": "no sensor relates to this space"}})
    assert rec.status == AnswerStatus.OBSERVED


def test_an_ungraded_answer_is_not_judged():
    """Most questions do not name a space. Grading them anyway would flag the whole corpus."""
    rec = build_evidence_record(
        {"sql_result": {"results": {"data": [{"datetime": NOW.isoformat(), "v": 1}]}}}, now=NOW
    )
    assert not [g for g in rec.gates_advisory if "spatial" in g]


# ── the fetcher: what it may and may not conclude ────────────────────────────


def test_zone_service_is_validated_only_by_an_explicit_triple():
    """`zoneValidated` is the only thing that turns zone service into coverage. The validated
    bucket is fed ONLY where the graph asserts `zoneValidated true` (T65's floor-5 pilot
    authored the first such triples); absent or false stays unvalidated — upgrading proximity
    to coverage on an assertion nobody made is the substitution this module exists to
    prevent."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/spatial_facts.py").read_text(encoding="utf-8")
    assert "zoneValidated" in src, "the fetcher no longer consults zoneValidated at all"
    body = src[src.index('zv = str(row.get("zv")') :][:400]
    assert '("true", "1")' in body, "validation must require an explicit true"
    assert (
        'e["vzone" if zv else "zone"]' in body
    ), "zone-reached spaces must split on the asserted flag, never default to validated"


def test_the_fetcher_has_no_notion_of_distance():
    """Proximity is not evidence of what a sensor measures — ductwork is. BUG-189 attributed
    one room's reading to a corridor the building did not have, and a distance term is how
    that class of error gets back in."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/spatial_facts.py").read_text(encoding="utf-8")
    for banned in ("distance", "nearest", "geo:", "wgs84", "ST_Distance"):
        assert banned.lower() not in src.lower().replace("no distance", "").replace(
            "nearest-neighbour", ""
        ), f"{banned!r} appears in the spatial fetcher"


def test_an_ambiguous_space_name_resolves_to_nothing():
    """Grading against an arbitrary one of several matches produces a confident verdict about
    the wrong room, which is worse than no verdict."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/spatial_facts.py").read_text(encoding="utf-8")
    body = src[src.index("async def resolve_space_iri") : src.index("async def facts_for_uuids")]
    assert "len(iris) != 1" in body, "resolution does not refuse an ambiguous match"


def test_the_namespace_is_never_a_literal():
    """Contract rule 3: core code carries no building literals."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/spatial_facts.py").read_text(encoding="utf-8")
    assert "abacws" not in src.lower()
    assert "BUILDING_NAMESPACE" in src
