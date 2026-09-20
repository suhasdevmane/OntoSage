# -*- coding: utf-8 -*-
"""A concept-resolved class repairs a retrieval when the catalogue has no key for the inferred name.

Live, unscripted, 2026-09-18: "How much electricity did the building use yesterday?" resolved the
concept `energy_consumption` -> `brick:Energy_Sensor` (six floor meters, all with readings) and then
fetched eight AIR QUALITY sensors; the analytics ran over "low/medium/high" strings and reported "No
valid data". The wanted modality is inferred from the query text ("energy"); the catalogue's key is
`energy_submeter`, so `needs_repair` took its "unknown modality: never guess" exit. The guess it
refused to make had already been made by the concept resolver.

The safety argument is one-sided and these tests pin both halves: the catalogue still wins whenever
it knows the name (nothing that repairs today changes), and a resolved class only opens the case
that used to do nothing.
"""

from __future__ import annotations

import pytest

from orchestrator.services import modality_repair as mr

pytestmark = pytest.mark.unit

NS = "http://example.org/building#"


def _air_quality_rows(n: int = 8):
    return [
        {
            "sensor": {"value": f"{NS}Air_Quality_Level_Sensor_5.0{i}"},
            "label": {"value": f"Air Quality Level Sensor installed-node 5.0{i}"},
            "type": {"value": "https://brickschema.org/schema/Brick#Air_Quality_Sensor"},
        }
        for i in range(n)
    ]


@pytest.fixture
def no_energy_key(monkeypatch):
    """The building's catalogue has no modality named 'energy' (its key is energy_submeter)."""
    real = mr.modality_classes

    def fake(modality, building_id=None):
        return () if modality == "energy" else real(modality, building_id)

    monkeypatch.setattr(mr, "modality_classes", fake)


def test_the_case_that_used_to_do_nothing_now_repairs(no_energy_key):
    rows = _air_quality_rows()
    assert mr.needs_repair(rows, "energy") is False, "without a resolved class: unchanged, no guess"
    assert mr.needs_repair(rows, "energy", extra_classes=["brick:Energy_Sensor"]) is True


def test_a_retrieval_that_already_holds_the_resolved_class_is_left_alone(no_energy_key):
    rows = _air_quality_rows(2) + [
        {
            "sensor": {"value": f"{NS}Energy_Meter_Floor3"},
            "label": {"value": "Electrical Energy Meter - Floor 3"},
        }
    ]
    assert mr.needs_repair(rows, "energy", extra_classes=["brick:Energy_Sensor"]) is False


def test_the_query_is_built_from_the_resolved_class(no_energy_key):
    assert mr.build_modality_query("energy", NS) is None, "no catalogue key and no resolved class"
    q = mr.build_modality_query("energy", NS, extra_classes=["brick:Energy_Sensor"])
    assert q and '"Energy_Sensor"' in q
    assert f'STRSTARTS(STR(?sensor), "{NS}")' in q
    assert "ref:hasTimeseriesId" in q, "a sensor with no series cannot answer a data question"


def test_the_question_s_floor_scope_is_still_kept(no_energy_key):
    q = mr.build_modality_query("energy", NS, floors=["3"], extra_classes=["brick:Energy_Sensor"])
    assert 'FILTER(?floorNum IN ("3"))' in q


def test_the_catalogue_wins_whenever_it_knows_the_name(monkeypatch):
    """Nothing that repairs today may change: a resolved class never overrides the catalogue."""
    monkeypatch.setattr(mr, "modality_classes", lambda m, b=None: ("Air_Temperature_Sensor",))
    assert mr.classes_for("temperature", None, ["brick:Something_Else"]) == ("Air_Temperature_Sensor",)
    q = mr.build_modality_query("temperature", NS, extra_classes=["brick:Something_Else"])
    assert '"Air_Temperature_Sensor"' in q and "Something_Else" not in q


def test_no_modality_and_no_class_never_guesses(monkeypatch):
    monkeypatch.setattr(mr, "modality_classes", lambda m, b=None: ())
    assert mr.needs_repair(_air_quality_rows(), None) is False
    assert mr.needs_repair(_air_quality_rows(), "energy") is False
    assert mr.needs_repair(_air_quality_rows(), "energy", extra_classes=[]) is False
    assert mr.needs_repair(_air_quality_rows(), "energy", extra_classes=[""]) is False


def test_the_prefix_of_a_resolved_class_is_dropped():
    assert mr.classes_for("zzz-not-a-modality", None, ["brick:Energy_Sensor", "Bare_Class"]) == (
        "Energy_Sensor",
        "Bare_Class",
    )


def test_the_orchestrator_passes_the_resolved_classes_to_the_query():
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator.WorkflowOrchestrator._repair_retrieved_modality)
    assert "extra_classes=_resolved_classes" in src
