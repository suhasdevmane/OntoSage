# -*- coding: utf-8 -*-
"""One Point measures one quantity (CAVEAT-286, 2026-08-27).

bldg1 asserted two contradictions in its source TTL:

* 34 ``TVOC_Level_Sensor_5.xx`` individuals also carried
  ``brick:Particulate_Matter_Sensor`` — a volatile organic compound typed as
  particulate matter.
* ``NO2_Sensor_Parking`` carried ``brick:CO_Level_Sensor`` — nitrogen dioxide
  typed as carbon monoxide, whose exposure limit is a different number entirely.

Either lets a question about one gas be answered with a reading of another. The
pm25 modality had an exclusion list that neutralised the first case for that one
consumer, which is precisely why the wrong type survived: the graph still
asserted it, and every other consumer still believed it.

Retyping bldg1 alone would leave the next building free to repeat it, so the
check lives in the input validator and runs on every swap.
"""

from pathlib import Path

import pytest

from orchestrator.services.input_validators import (
    _measurand_conflicts,
    validate_building_input,
    validate_measurand_typing,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _building_dir(building: str) -> Path:
    """A building's TTL directory, whether it is ACTIVE (input/) or parked.

    Without this the bldg1 cases SKIP whenever bldg1 is the live building, and a
    skip reads as "checked and fine".
    """
    active = _REPO / "input"
    if (active / "building.yaml").is_file():
        try:
            if building in (active / "building.yaml").read_text(encoding="utf-8"):
                return active
        except OSError:  # pragma: no cover
            pass
    return _REPO / building


def _input_root() -> Path:
    """The root to hand validate_building_input, for whichever layout is in use.

    Both are normal: the committed tree has every building parked (bldg1/), and a
    live session has one active (input/). A test that only knows one of them fails
    in the other, which reads as a regression in the thing being tested.
    """
    return _REPO / "input" if (_REPO / "input" / "building.yaml").is_file() else _REPO


# ── the check catches the two defects that were actually shipped ─────────────
def test_the_tvoc_pair_is_redundant_not_contradictory():
    """This test used to assert the OPPOSITE, and the correction is the point.

    Verbatim from bldg1_expanded_protege_clean.ttl before the retype. It was
    recorded as "a volatile organic compound typed as particulate matter" — a
    defect in the building's data. It is not: Brick 1.4 itself declares
    ``brick:TVOC_Sensor rdfs:subClassOf brick:Particulate_Matter_Sensor``
    (Brick_v1.4.ttl:31248), so asserting both is REDUNDANT, not contradictory, and
    a reasoner derives it whatever the file says.

    Flagging it would report Brick-conformant data as broken, which is how a
    conformance check gets switched off. The real harm — a count of particulate
    sensors including 35 gas sensors — is disclosed at answer time instead
    (CAVEAT-286, tests/test_measurand_kinds.py).
    """
    text = """bldg:TVOC_Level_Sensor_5.01 rdf:type owl:NamedIndividual ,
                                     brick:Air_Quality_Sensor ,
                                     brick:Particulate_Matter_Sensor ,
                                     brick:Point ,
                                     brick:TVOC_Level_Sensor ;
                            brick:hasLocation bldg:Zone_5.01 .
"""
    assert _measurand_conflicts(text) == []


def test_the_no2_defect_as_it_was_written_is_caught():
    """Verbatim from bldg1_enhancements.ttl before the fix — note the label said
    NO2 all along, so only the machine-readable type was wrong."""
    text = """bldg:NO2_Sensor_Parking
    rdf:type owl:NamedIndividual , brick:CO_Level_Sensor , brick:NO2_Level_Sensor ;
    rdfs:label "NO2/Exhaust Gas Sensor - Parking Level" .
"""
    conflicts = _measurand_conflicts(text)
    assert [f for _s, fams in conflicts for f in fams] == ["carbon monoxide", "nitrogen dioxide"]


# ── and does not fire on correct typing ──────────────────────────────────────
def test_a_class_hierarchy_within_one_family_is_not_a_conflict():
    """PM2.5 is particulate matter; asserting both is a hierarchy, not a clash."""
    text = """bldg:PM25 a brick:Particulate_Matter_Sensor , brick:PM2_5_Level_Sensor ,
        brick:Air_Quality_Sensor , brick:Sensor .
"""
    assert _measurand_conflicts(text) == []


def test_co2_is_not_read_as_co():
    """The two class names differ by one character and mean different gases."""
    text = "bldg:S a brick:CO2_Level_Sensor , brick:CO2_Sensor , brick:Air_Quality_Sensor .\n"
    assert _measurand_conflicts(text) == []


def test_an_untyped_or_unrelated_instance_is_ignored():
    text = 'bldg:Room1 a brick:Room ; rdfs:label "Room 1" .\n'
    assert _measurand_conflicts(text) == []


# ── every shipped building is clean, and stays clean ─────────────────────────
@pytest.mark.parametrize("building", ["bldg1", "bldg2", "bldg3"])
def test_shipped_buildings_have_no_contradictory_sensor_typing(building):
    d = _building_dir(building)
    if not d.is_dir():
        pytest.skip(f"{building} is not present in this checkout")
    ok, issues = validate_measurand_typing(d)
    assert ok, "\n".join(issues)


def test_the_vendored_brick_tbox_is_skipped():
    """Brick's own class hierarchy legitimately puts a class under several parents;
    scanning it would report the schema as a defect."""
    d = _building_dir("bldg1")
    if not (d / "Brick_v1.4.ttl").is_file():
        pytest.skip("Brick TBox not present")
    ok, _ = validate_measurand_typing(d)
    assert ok


def test_a_missing_directory_is_not_an_error():
    assert validate_measurand_typing(_REPO / "no_such_building") == (True, [])


# ── wired into the swap-time report, not just available ──────────────────────
def test_the_check_runs_as_part_of_building_validation():
    """A validator nothing calls is the recurring defect in this codebase
    (lessons.md #87): five capabilities shipped with no invoker."""
    ok, report = validate_building_input("bldg1", _input_root())
    assert "sensor typing" in report["files"], sorted(report["files"])
    assert report["files"]["sensor typing"]["ok"], report["files"]["sensor typing"]["issues"]


# ── a second defect the check surfaced on its way in ────────────────────────
def test_a_declared_timetable_feed_validates():
    """feeds.yaml declared `type: timetable`, which the feed REGISTRY dispatches
    (institutional.py handles it) — but the validator kept its own list of feed
    types and had never been told, so it reported the working feed as an unknown
    type missing brick_class and storage. An institutional source produces events,
    not a Brick point: it has neither key by design."""
    import yaml

    from orchestrator.services.input_validators import validate_feeds_yaml

    path = _building_dir("bldg1") / "feeds.yaml"
    if not path.is_file():
        pytest.skip("bldg1/feeds.yaml not present")
    declared = {f.get("type") for f in yaml.safe_load(path.read_text(encoding="utf-8"))["feeds"]}
    assert "timetable" in declared, "the feed this test is about is no longer declared"
    ok, issues = validate_feeds_yaml(path)
    assert ok, issues


def test_the_accepted_feed_types_come_from_the_registry():
    """Two copies of one list is how they drifted in the first place."""
    from orchestrator.services.feeds.registry import _ADAPTER_CLASSES
    from orchestrator.services.input_validators import _known_feed_types

    known, institutional = _known_feed_types()
    assert known == set(_ADAPTER_CLASSES)
    assert institutional <= known


def test_a_telemetry_feed_still_must_name_its_class_and_store(tmp_path):
    """Relaxing the keys for institutional sources must not relax them for the
    rest_poll feeds that do become points with rows."""
    from orchestrator.services.input_validators import validate_feeds_yaml

    p = tmp_path / "feeds.yaml"
    p.write_text("feeds:\n  - id: x\n    type: rest_poll\n    url: http://h/\n", encoding="utf-8")
    ok, issues = validate_feeds_yaml(p)
    assert not ok
    assert any("brick_class" in i and "storage" in i for i in issues), issues


def test_an_unknown_feed_type_is_still_rejected(tmp_path):
    from orchestrator.services.input_validators import validate_feeds_yaml

    p = tmp_path / "feeds.yaml"
    p.write_text("feeds:\n  - id: x\n    type: carrier_pigeon\n    path: a.csv\n", encoding="utf-8")
    ok, issues = validate_feeds_yaml(p)
    assert not ok
    assert any("carrier_pigeon" in i for i in issues), issues
