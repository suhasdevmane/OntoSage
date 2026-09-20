# -*- coding: utf-8 -*-
"""Wave 2 (2D-06): the lane runs the grouping for a register too large to hand over.

"Which rooms have teaching sessions this week?" selects the timetable register (675 sessions),
names no room to scope by, and so was declined — a generated query then answered "the building's
records do not contain any information about teaching sessions ... you'll need to consult the
timetable or scheduling system", sourced from the building model rather than from the register
that holds the answer.

The register lane now asks the graph to COUNT per value before it declines. This drives
``SPARQLAgent._whole_register`` itself with the graph replaced by a stub that answers the GROUP BY,
so what is checked is the lane's own decision: that it groups, what it asks the graph for, and
what it does when the grouping cannot be trusted.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent
from orchestrator.services import record_registry

pytestmark = pytest.mark.unit

QUESTION = "Which rooms have teaching sessions this week?"
SESSIONS = 675
ONTO = "http://ontosage.org/capabilities#"

#: what a GROUP BY over 675 sessions returns, one row per room
ROOMS = [("Room 2.15 - Seminar Room", 24), ("Room 1.06 - Computer Laboratory", 23)]


def _group_rows(predicate: str, pairs=ROOMS) -> Dict[str, Any]:
    return {
        "head": {"vars": ["p", "v", "n"]},
        "results": {
            "bindings": [
                {
                    "p": {"type": "uri", "value": ONTO + predicate},
                    "v": {"type": "literal", "value": value},
                    "n": {"type": "literal", "value": str(count)},
                }
                for value, count in pairs
            ]
        },
    }


def _lane(
    monkeypatch,
    answer: Optional[Dict[str, Any]],
    instances: int = SESSIONS,
    narration: str = "",
):
    """The register lane with one stubbed graph answer.

    ``narration`` is what the model would write; leaving it empty fails the test if the model is
    asked at all, which is how the grouping path is told apart from the ordinary one.
    """
    asked: List[str] = []

    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _execute(query: str, *a, **k):
        asked.append(query)
        if answer is None:
            raise RuntimeError("graph unavailable")
        return answer

    async def _format(*a, **k):
        if not narration:
            raise AssertionError("the model was asked, and the graph had already counted")
        return narration

    agent._execute_query = _execute
    agent._format_results = _format

    cls = record_registry.RecordClass(
        "TimetabledSession",
        "Timetabled session",
        instances,
        record_registry._terms_for(
            "TimetabledSession", "Timetabled session", "teaching session|teaching sessions"
        ),
    )

    async def _classes(namespace: str = ""):
        return [cls]

    monkeypatch.setattr(record_registry, "record_classes", _classes)
    return agent, asked


def _ask(agent: SPARQLAgent, question: str = QUESTION):
    state = SimpleNamespace(building_id=None, intermediate_results={})
    return asyncio.run(agent._whole_register(state, question))


def test_the_lane_groups_an_oversized_register_instead_of_declining(monkeypatch):
    agent, asked = _lane(monkeypatch, _group_rows("locationText"))
    result = _ask(agent)
    assert result is not None, "the lane declined a register it can group"
    text = result["formatted_response"]
    assert text.startswith(
        "**2 rooms** appear on the 675 records in the Timetabled session register"
    )
    assert "- **Room 2.15 - Seminar Room** — 24" in text
    assert "this week" in text  # the period it was NOT narrowed by is stated
    assert result["method"] == "whole_register" and result["success"] is True


def test_it_asks_the_graph_to_count_rather_than_fetching_675_records(monkeypatch):
    agent, asked = _lane(monkeypatch, _group_rows("locationText"))
    _ask(agent)
    assert len(asked) == 1, asked
    query = asked[0]
    assert "COUNT(DISTINCT ?record)" in query and "GROUP BY ?p ?v" in query
    assert 'CONTAINS(LCASE(STR(?p)), "room")' in query
    assert "ontosage:TimetabledSession" in query


def _not_grouped(result) -> bool:
    """The lane took its ordinary path: it declined, or the model wrote the answer."""
    return result is None or not result["formatted_response"].startswith("**")


def test_two_candidate_predicates_are_left_to_the_ordinary_path(monkeypatch):
    """Grouping by the wrong column files every record under a heading it does not belong to."""
    rows = _group_rows("locationText")
    rows["results"]["bindings"] += _group_rows("roomBandCode", [("A", 400)])["results"]["bindings"]
    agent, _asked = _lane(monkeypatch, rows, narration="narrated")
    assert _not_grouped(_ask(agent))


def test_a_graph_that_cannot_answer_the_grouping_falls_back_rather_than_inventing(monkeypatch):
    agent, _asked = _lane(monkeypatch, None, narration="narrated")
    assert _not_grouped(_ask(agent))


def test_a_question_that_is_not_a_grouping_is_unaffected(monkeypatch):
    agent, _asked = _lane(monkeypatch, _group_rows("locationText"), narration="narrated")
    assert _not_grouped(_ask(agent, "Which teaching sessions are overdue?"))


def test_the_total_is_the_registers_own_size_not_the_sum_of_the_groups(monkeypatch):
    """A record carrying the field twice would be counted twice, and the total would overstate
    the register. 24 + 23 is 47; the register holds 675."""
    agent, _asked = _lane(monkeypatch, _group_rows("locationText"))
    text = _ask(agent)["formatted_response"]
    assert "675 records" in text and "47 records" not in text
