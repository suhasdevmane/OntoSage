# -*- coding: utf-8 -*-
"""'How many kitchens?' is answered from the room records, never from points (BUG-1410).

MEASURED 2026-10-01, occupant01 on /v1, a minute apart:

    'Where is the kitchen?'                 -> three (2.66, 3.18, 5.26), from the room records
    'How many kitchens are in the building?' -> "two kitchens", indicated by the sensors
                                                WasteBin_Fill_F2_Kitchen / _F3_Kitchen

The log: `[sparql] resolved ['Kitchen'] -> 2 point(s)`. The metadata lane resolved the entity
to the two POINTS whose names carry the word and counted them (BUG-877B's shape: a count of
instruments narrated as a count of the things they stand in). Room 5.26 has no waste bin and
so did not exist as far as that answer was concerned.

`room_type_lookup` already answers the shape from the graph's own room records; the lane now
asks it first. Measured over the 4,060-question bank before landing: the lookup claims none
of them, so this acts only on the plain "which rooms / how many <kind>" shape.
"""

import inspect

import pytest

from orchestrator.agents import sparql_agent

pytestmark = pytest.mark.unit


def test_the_room_records_are_asked_before_the_register_and_before_any_query():
    src = inspect.getsource(sparql_agent.SPARQLAgent.generate_query)
    i_rooms = src.index("await self._rooms_of_kind(user_query)")
    i_register = src.index("await self._whole_register(state, user_query)")
    assert i_rooms < i_register


def test_the_lookup_is_restricted_to_the_rooms_shape():
    """'Which floor is the server room on?' belongs to the floor-plan lane, not here."""
    src = inspect.getsource(sparql_agent.SPARQLAgent._rooms_of_kind)
    assert 'answer_live(user_query, only="rooms")' in src


async def test_a_question_naming_no_room_kind_leaves_the_path_untouched(monkeypatch):
    from orchestrator.services import room_type_lookup

    async def _none(q, only=None):
        return None

    monkeypatch.setattr(room_type_lookup, "answer_live", _none)
    agent = sparql_agent.SPARQLAgent.__new__(sparql_agent.SPARQLAgent)
    assert await agent._rooms_of_kind("How many sensors are in the building?") is None


async def test_a_room_records_answer_is_returned_as_the_lane_result(monkeypatch):
    from orchestrator.services import room_type_lookup

    async def _three(q, only=None):
        return "**3 rooms are recorded as Kitchen**\n\n_From the building's own room records._"

    monkeypatch.setattr(room_type_lookup, "answer_live", _three)
    agent = sparql_agent.SPARQLAgent.__new__(sparql_agent.SPARQLAgent)
    out = await agent._rooms_of_kind("How many kitchens are in the building?")
    assert out["success"] is True
    assert out["method"] == "room_records"
    assert out["analytics_required"] is False
    assert "3 rooms are recorded as Kitchen" in out["formatted_response"]


async def test_a_lookup_failure_never_blocks_the_lane(monkeypatch):
    from orchestrator.services import room_type_lookup

    async def _boom(q, only=None):
        raise RuntimeError("graph down")

    monkeypatch.setattr(room_type_lookup, "answer_live", _boom)
    agent = sparql_agent.SPARQLAgent.__new__(sparql_agent.SPARQLAgent)
    assert await agent._rooms_of_kind("How many kitchens?") is None
