# -*- coding: utf-8 -*-
"""BUG-884 — naming a floor bound what was NAMED for it, not what was ON it.

Measured live 2026-09-23. "Will floor 3 be warmer than floor 4 tomorrow?" resolved to:

    ['Access_Reader_F3_Entrance', 'Entry_Count_Sensor_F3', 'Door_Sensor_Server_F3',
     'HVAC_Meter_F3', 'Lighting_Meter_F3', 'PlugLoad_Meter_F3', 'FireExit_Door_Sensor_F3',
     'RH_Sensor_F3']

Eight floor-3 METERS, nothing whatever from floor 4, and not one temperature sensor. The same
shape produced "No readings were found for Floor_2" for evidence pack #27, of a floor with 42
instrumented spaces.

The graph held the answer the whole time: floor → spaces → points, through the two location
idioms `coverage_audit` has always covered. Asked structurally, floor 3 yields 48 temperature
sensors and floor 4 yields 56.

TWO WAYS THIS WENT WRONG WHILE BEING FIXED, both pinned below, because both produced a
confident wrong answer rather than an error:

1. Narrowing the floor's points by the QUESTION's words re-created the original bug one layer
   down — every candidate is already on that floor, so "floor 3" is noise that scored
   `Floor3_General_Waste_Bin_Fill` above forty-eight temperature sensors. The answer then
   compared floor 3's waste bins with floor 4's temperatures as though both were degrees.
2. The default limit of 8 truncated 104 points to 8, all from floor 3 — so a comparison whose
   answer quoted floor-4 numbers had no floor-4 sensor bound at all.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


# ── recognising a floor ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,digits",
    [
        ("Floor_3", "3"),
        ("floor 3", "3"),
        ("Level 2", "2"),
        ("storey 4", "4"),
        ("Floor_10", "10"),
        ("  floor-5 ", "5"),
    ],
)
def test_a_floor_entity_is_recognised_however_it_is_written(name, digits):
    m = SPARQLAgent._FLOOR_ENTITY_RE.match(name)
    assert m and m.group(1) == digits


@pytest.mark.parametrize(
    "name",
    [
        "Room_2.01",  # a dotted number is a SPACE, not a floor
        "2.01",
        "the atrium",
        "Floor",  # no number: which floor?
        "AHU01N",
        "Zone_5",  # a zone is not a floor
    ],
)
def test_anything_that_is_not_a_floor_falls_through_to_the_label_path(name):
    assert SPARQLAgent._FLOOR_ENTITY_RE.match(name) is None


# ── the quantity must be known, or this must not act ─────────────────────────────────


@pytest.mark.asyncio
async def test_without_a_resolved_class_it_declines_to_act():
    """Binding eight arbitrary points off a floor is WORSE than the behaviour it replaces.

    With no class resolved there is nothing to narrow 400 points by except the question's own
    words, and those words name the floor — which is how waste bins won a temperature question.
    """
    agent = SPARQLAgent.__new__(SPARQLAgent)
    got = await SPARQLAgent._resolve_floor_structurally(
        agent, "Floor_3", "will floor 3 be warmer", "http://x#", 8, class_hints=None
    )
    assert got == []
    got_empty = await SPARQLAgent._resolve_floor_structurally(
        agent, "Floor_3", "will floor 3 be warmer", "http://x#", 8, class_hints=[]
    )
    assert got_empty == []


@pytest.mark.asyncio
async def test_a_non_floor_entity_is_never_touched_even_with_a_class():
    agent = SPARQLAgent.__new__(SPARQLAgent)
    got = await SPARQLAgent._resolve_floor_structurally(
        agent, "Room_2.01", "co2 in room 2.01", "http://x#", 8, ["brick:CO2_Level_Sensor"]
    )
    assert got == []


@pytest.mark.asyncio
async def test_the_query_filters_by_class_and_covers_both_location_idioms():
    """A building modelling only `isPointOf` must not come back empty."""
    seen = {}
    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _capture(query, ns, pfx):
        seen["q"] = query
        return ["bldg:Air_Temperature_Sensor_3.01"]

    agent._select_subjects = _capture
    agent._prefix_block = lambda: "PREFIX brick: <b#>\nPREFIX ref: <r#>\nPREFIX rdfs: <s#>"
    got = await SPARQLAgent._resolve_floor_structurally(
        agent, "Floor_3", "warmer", "http://x#", 200, ["brick:Temperature_Sensor"]
    )
    assert got == ["bldg:Air_Temperature_Sensor_3.01"]
    q = seen["q"]
    assert "brick:hasLocation" in q and "brick:isPointOf" in q, "both idioms are required"
    assert "VALUES ?cls" in q and "brick:Temperature_Sensor" in q
    assert "ref:hasExternalReference" in q, "a point with no readings cannot answer"
    assert "brick:isPartOf" in q


@pytest.mark.asyncio
async def test_a_failing_query_returns_nothing_rather_than_raising():
    """The label path still answers; a structural miss must never cost the turn."""
    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _boom(query, ns, pfx):
        raise RuntimeError("graphdb down")

    agent._select_subjects = _boom
    agent._prefix_block = lambda: ""
    got = await SPARQLAgent._resolve_floor_structurally(
        agent, "Floor_3", "warmer", "http://x#", 8, ["brick:Temperature_Sensor"]
    )
    assert got == []


# ── a floor's mean is not eight of its rooms ─────────────────────────────────────────


def test_the_floor_cap_is_large_enough_for_a_whole_floor():
    """48 and 56 sensors per modality on this building's floors; 8 was a sixth of one floor."""
    assert SPARQLAgent._FLOOR_POINT_CAP >= 100


def test_the_resolver_does_not_truncate_a_floor_scoped_result_to_the_default_limit():
    """Two floors resolved 104 points and `resolved[:8]` returned eight, all from floor 3.

    The answer still quoted floor-4 numbers, so a comparison was narrated over a set containing
    none of one side.
    """
    src = inspect.getsource(SPARQLAgent._resolve_entities_by_label)
    assert "structural_found" in src
    assert "_FLOOR_POINT_CAP" in src
    assert "return resolved[:limit]" not in src, "the default limit must not cap a floor result"


def test_the_resolution_carries_no_building_literal():
    import ast
    from pathlib import Path

    # Parsed from the MODULE, not from `inspect.getsource` + dedent: the method embeds a
    # multi-line SPARQL f-string whose lines start at column 0, so there is no common indent
    # to remove and dedent leaves it unparseable.
    module = ast.parse(
        Path("orchestrator/agents/sparql_agent.py").read_text(encoding="utf-8")
    )
    fn = next(
        n
        for n in ast.walk(module)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_resolve_floor_structurally"
    )
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant):
        fn.body = fn.body[1:]
    code = ast.unparse(ast.fix_missing_locations(fn))
    for literal in ("bldg1", "abacws", "cardiff", "temperature_sensor"):
        assert literal not in code.lower(), literal
