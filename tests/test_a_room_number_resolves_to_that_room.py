# -*- coding: utf-8 -*-
"""WB-10: 'room 2.01' must never resolve to room 5.01 (the floor digit was dropped)."""

import asyncio

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def test_a_dotted_room_id_is_searched_whole():
    agent = SPARQLAgent.__new__(SPARQLAgent)
    seen = []

    async def _select(q, ns, pfx):
        seen.append(q)
        return []

    agent._select_subjects = _select
    agent._prefix_block = lambda: ""
    import orchestrator.agents.sparql_agent as sa

    sa_ns, sa_pf = sa._active_namespace, sa._active_prefix
    sa._active_namespace, sa._active_prefix = (lambda: "http://x#"), (lambda: "bldg")
    try:
        asyncio.run(agent._resolve_entities_by_label(["Room_2.01"], user_query="co2 in room 2.01"))
    finally:
        sa._active_namespace, sa._active_prefix = sa_ns, sa_pf
    assert seen and 'CONTAINS(?hay, "2.01")' in seen[0]
    assert 'CONTAINS(?hay, "room")' not in seen[0]  # identifier present: kind-word optional
    assert 'CONTAINS(?hay, "01")' not in seen[0]
