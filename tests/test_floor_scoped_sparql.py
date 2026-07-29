"""Unit tests for the portable floor-scoped SPARQL resolver.

"Compare temperature between floor 1 and floor 5" previously deflected because
RAG queried floors (no sensor UUIDs). _floor_scoped_sparql resolves the metric's
sensors per floor through the Brick spatial hierarchy
(sensor → hasLocation → isPartOf* → brick:Floor) — building-portable, no
abacws-specific label parsing — so the pipeline gets data and compares.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

_agent = SPARQLAgent()


def test_builds_query_for_metric_plus_floors():
    q = _agent._floor_scoped_sparql("Compare the temperature between floor 1 and floor 5.", None)
    assert q is not None
    # Portable building blocks: broad temp class via TBOX rollup (matches whatever
    # subclass the building types its sensors as), floor hierarchy, UUID link.
    assert "brick:Temperature_Sensor" in q
    assert "rdfs:subClassOf*" in q
    assert "brick:Floor" in q
    assert "brick:hasLocation" in q
    assert "ref:hasTimeseriesId" in q
    # Both requested floors are scoped.
    assert '"1"' in q and '"5"' in q
    # Declares the ref: prefix it needs (absent from the standard block).
    assert "PREFIX ref:" in q


def test_none_without_floor():
    # Zone-scoped query — must not trigger floor resolution.
    assert _agent._floor_scoped_sparql("What is the temperature in zone 5.28?", None) is None


def test_none_without_inferrable_metric():
    # No metric keyword AND no salient label terms → None (don't hijack generic
    # floor queries). "compare"/"floor" are structure words, not metric nouns.
    assert _agent._floor_scoped_sparql("compare floor 1 and floor 5", None) is None


def test_label_fallback_for_unmapped_metric():
    # No Brick class maps the hyphenated "run-time", so the label-match tier
    # resolves it by rdfs:label — naming-agnostic (works for any URI scheme).
    q = _agent._floor_scoped_sparql("What is the AHU run-time on floor 5?", None)
    assert q is not None
    assert 'CONTAINS(LCASE(STR(?label)), "ahu")' in q
    assert 'CONTAINS(LCASE(STR(?label)), "run")' in q
    assert "ref:hasTimeseriesId" in q
    assert '"5"' in q
    assert "?sensor a brick:" not in q  # label tier has no hard-coded class triple


def test_salient_terms():
    assert _agent._salient_terms("compare floor 1 and floor 5") == []
    assert _agent._salient_terms("What is the AHU run-time on floor 5?") == ["ahu", "run", "time"]


def test_prefers_indoor_over_outside_class_target():
    # An HBCO class_target pointing at the weather feed must not win — the keyword
    # class (Temperature_Sensor) inferred from "temperature" is used instead, so
    # the outside-only target never reaches the query string.
    q = _agent._floor_scoped_sparql(
        "temperature on floor 3", "brick:Outside_Air_Temperature_Sensor"
    )
    assert q is not None
    assert "brick:Temperature_Sensor" in q
    assert "Outside_Air_Temperature_Sensor" not in q
    assert '"3"' in q


def test_level_synonym_and_multi_floor():
    q = _agent._floor_scoped_sparql("compare CO2 on level 2 and level 4", None)
    assert q is not None
    assert '"2"' in q and '"4"' in q
