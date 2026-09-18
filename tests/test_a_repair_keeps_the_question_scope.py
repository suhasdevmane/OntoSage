"""A repair may widen the CLASS it looks for, never the PLACE it looks in (BUG-632).

"What is the air quality on floor 3?" was answered from sensors labelled 5.27 and 5.32. The
floor-scoped query was right — 107 rows, every one on floor 3 — and the modality repair then
decided those rows held "no air_quality sensors" and replaced them with 400 from a
building-wide query:

    [modality_repair] want=air_quality rows=107 miss=True under_populated=False
    [modality_repair] no air_quality sensors from retrieval (107 rows); replaced with 400

Two faults in one line. The miss was false — CO2, PM2.5 and TVOC readings ARE air quality, and
the catalogue knew only `Air_Quality_Sensor`. And the replacement silently changed the scope:
a repair that answers about the building when it was asked about a floor is not a repair.
"""

import pytest

from orchestrator.services import modality_repair as mr

pytestmark = pytest.mark.unit

_IAQ = ["brick:CO2_Level_Sensor", "brick:PM2.5_Level_Sensor", "brick:TVOC_Sensor", "brick:Air_Quality_Sensor"]
_NS = "http://example.org/bldg#"


def test_a_repair_for_a_floor_question_is_scoped_to_that_floor():
    query = mr.build_modality_query("air_quality", _NS, floors=["3"])
    assert query is not None
    assert "?floorNum" in query
    assert 'IN ("3")' in query
    assert "brick:Floor" in query


def test_a_repair_with_no_floor_named_stays_building_wide():
    """Most questions name no floor, and those must keep the behaviour they had."""
    query = mr.build_modality_query("air_quality", _NS)
    assert query is not None
    assert "?floorNum" not in query


def test_several_floors_are_all_kept():
    query = mr.build_modality_query("air_quality", _NS, floors=["1", "5"])
    assert 'IN ("1", "5")' in query


def test_the_scoped_repair_is_valid_sparql():
    """A malformed repair fails silently and the fallback answers instead (BUG-631)."""
    from rdflib.plugins.sparql import prepareQuery

    prepareQuery(mr.build_modality_query("air_quality", _NS, floors=["3"]))
    prepareQuery(mr.build_modality_query("air_quality", _NS))


def test_a_constituent_of_the_concept_is_not_a_total_miss():
    """CO2 IS air quality. The catalogue names one class; the concept names four."""
    rows = [{"label": {"value": "CO2 Level Sensor installed-node 3.10"}}]
    assert mr.needs_repair(rows, "air_quality", extra_classes=_IAQ) is False


def test_without_the_resolved_concept_the_old_judgement_stands():
    """The generosity is scoped to what a resolver deliberately chose, not to everything."""
    rows = [{"label": {"value": "CO2 Level Sensor installed-node 3.10"}}]
    assert mr.needs_repair(rows, "air_quality") is True


def test_an_unrelated_modality_still_triggers_a_repair():
    """The guard must not become 'never repair' — a temperature sensor is not air quality."""
    rows = [{"label": {"value": "Air Temperature Sensor installed-node 3.10"}}]
    assert mr.needs_repair(rows, "air_quality", extra_classes=_IAQ) is True


def test_an_empty_result_still_triggers_a_repair():
    assert mr.needs_repair([], "air_quality", extra_classes=_IAQ) is True


def test_the_caller_passes_the_floors_and_the_resolved_classes():
    """Both fixes are worthless if the caller passes neither — the shape of the defect."""
    from pathlib import Path

    source = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    block = source[source.index("[modality_repair] want=") - 2000 : source.index("[modality_repair] want=") + 1500]
    assert "extra_classes=_resolved_classes" in block
    assert "floors=_asked_floors" in block
