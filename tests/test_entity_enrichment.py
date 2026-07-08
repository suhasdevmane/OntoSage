"""Unit tests for shared.entity_enrichment (Part D — naming-agnostic inference)."""

from pathlib import Path

import pytest

from shared.entity_enrichment import (
    EnrichmentConfig,
    enrich_entity,
    infer_point_class,
    infer_relationships,
    local_name,
    normalize_tokens,
)

pytestmark = pytest.mark.unit

_CFG = EnrichmentConfig.load(
    Path(__file__).resolve().parents[1] / "config" / "entity_enrichment.yaml"
)


def test_local_name_forms():
    assert local_name("bldg:Energy_Meter_Floor5") == "Energy_Meter_Floor5"
    assert local_name("<http://x/bldg#bldgx.AHU01.ZAT>") == "bldgx.AHU01.ZAT"
    assert local_name("http://abacws#Zone_5.28") == "Zone_5.28"


def test_normalize_tokens_delims_and_camel():
    assert normalize_tokens("bldgx.ZONE.AHU01.RM123.Zone_Air_Temp") == [
        "bldgx",
        "zone",
        "ahu01",
        "rm123",
        "zone",
        "air",
        "temp",
    ]
    assert normalize_tokens("ZoneAirTemp") == ["zone", "air", "temp"]


def test_infer_point_class_longest_match():
    # 'zone_air_temp' (3 tokens) must beat 'temp' (1) and 'air_temp' (2).
    assert (
        infer_point_class("bldgx.ZONE.AHU01.RM123.Zone_Air_Temp", _CFG.point_classes)
        == "brick:Zone_Air_Temperature_Sensor"
    )
    assert (
        infer_point_class("AHU01.SAT", _CFG.point_classes) == "brick:Supply_Air_Temperature_Sensor"
    )
    assert infer_point_class("RM12.CO2", _CFG.point_classes) == "brick:CO2_Level_Sensor"
    assert infer_point_class("AHU3.Runtime", _CFG.point_classes) == "brick:Run_Time_Sensor"


def test_infer_point_class_unmapped():
    assert infer_point_class("bldgx.WIDGET.FROBNICATOR", _CFG.point_classes) is None


def test_infer_relationships_equipment_and_room():
    rels, stubs = infer_relationships("bldgx.ZONE.AHU01.RM123.Zone_Air_Temp", _CFG)
    assert ("brick:isPointOf", "AHU01") in rels
    assert ("brick:hasLocation", "RM123") in rels
    assert ("AHU01", "brick:AHU") in stubs
    assert ("RM123", "brick:Room") in stubs


def test_enrich_entity_end_to_end_bms_example():
    r = enrich_entity("bldg:bldgx.ZONE.AHU01.RM123.Zone_Air_Temp", _CFG)
    assert r.brick_class == "brick:Zone_Air_Temperature_Sensor"
    assert r.is_mapped
    assert "AHU01" in r.label and "RM123" in r.label
    assert r.label.startswith("Zone Air Temperature")
    preds = {p for p, _ in r.relationships}
    assert preds == {"brick:isPointOf", "brick:hasLocation"}


def test_enrich_entity_unmapped_still_labels():
    # No class inferred → still produces a readable label (drops 'bldgx'/'zone').
    r = enrich_entity("bldg:bldgx.ZONE.WIDGET99", _CFG)
    assert r.brick_class is None
    assert "Bldgx" not in r.label  # ignore_tokens dropped
    assert "Widget99" in r.label or "WIDGET99" in r.label.upper()
