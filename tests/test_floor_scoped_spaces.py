# -*- coding: utf-8 -*-
"""Counting the spaces on a floor must not assume how a building names floors.

The template used to build the floor's IRI by string ("bldg:Floor2"). That
matches one convention and silently returns nothing for any building that
spells it differently ("floor2", "Floor_2", label "Level 2") — the question
came back as "no rooms found" while the graph held 41.

Two further defects in the same template: it traversed only brick:hasPart, so a
graph that asserts brick:isPartOf on the room found nothing; and it matched only
zone types, so "how many rooms" was answered with rooms plus zones.
"""

import re

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def _sparql(query: str):
    return SPARQLAgent._template_sparql(SPARQLAgent.__new__(SPARQLAgent), query, [], set())


def test_floor_is_matched_by_number_not_by_a_constructed_iri():
    sql = _sparql("how many rooms are on floor 2?")
    assert sql is not None
    assert "bldg:Floor2" not in sql, "must not hardcode one building's floor naming"
    assert "REGEX" in sql and "floor|storey|level" in sql


@pytest.mark.parametrize("n", ["0", "2", "11"])
def test_the_requested_floor_number_reaches_the_filter(n):
    sql = _sparql(f"how many rooms are on floor {n}?")
    assert re.search(rf"0\*{n}\(\[\^0-9\]", sql), f"floor {n} not in the filter"


def test_both_part_of_directions_are_traversed():
    sql = _sparql("how many rooms are on floor 2?")
    assert "brick:hasPart ?zone" in sql
    assert "?zone brick:isPartOf ?floor" in sql


def test_counting_rooms_counts_only_rooms():
    sql = _sparql("how many rooms are on floor 2?")
    assert "?zone a brick:Room" in sql
    assert "brick:HVAC_Zone" not in sql, "a room is usually also a zone — do not double count"
    assert "COUNT(DISTINCT ?zone)" in sql


def test_counting_zones_counts_zones():
    sql = _sparql("how many zones are on floor 2?")
    assert "brick:HVAC_Zone" in sql
    assert "?zone a brick:Room" not in sql


def test_a_listing_question_returns_rows_not_a_count():
    sql = _sparql("what rooms are on floor 2?")
    assert "COUNT(" not in sql
    assert "SELECT DISTINCT ?zone ?label" in sql


@pytest.mark.parametrize("phrasing", ["storey 2", "level 2", "floor 2"])
def test_alternate_words_for_a_floor_are_understood(phrasing):
    assert _sparql(f"how many rooms are on {phrasing}?") is not None
