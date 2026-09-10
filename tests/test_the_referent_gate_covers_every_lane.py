# -*- coding: utf-8 -*-
"""An existence check that runs in two lanes of eighteen protects two lanes (BUG-445, W1-4).

WHAT WENT WRONG
---------------
`apply_referent_gate` was written to be shared. Its own docstring says why:

    "Copying the block into each lane would have made the third copy the one that drifts;
     a shared function is the reason a fourth lane can be covered by a single call."

It had TWO callers. The sparql node ran an inline copy, and the events lane called the
helper -- added only after that lane was measured answering *"are there any vibration
anomalies on floor 9"* with 500 episodes from floors 3, 4 and 5, in a six-storey building
(BUG-399).

Register, asset_state, observability, readiness, diagnosis, deliberate, capability, spatial,
floor_plan, alert, report and export answered questions naming a room or a floor and never
checked that the building has one. Being shared is not the same as being called.

THE FIX IS NOT A THIRD CALL SITE
--------------------------------
The gate runs ONCE per turn, at the end of the dialogue node, before routing. Every turn
passes through that node, so a lane added next month is covered without being told the gate
exists -- and the check costs one SPARQL round trip per turn rather than one per lane.

A refusal short-circuits routing to `response`, and is collected immediately after the
privacy refusal: the building does not contain the thing the question named, so there is
nothing any lane could truthfully say about it.

Still FAILS OPEN. Refusing a legitimate question because GraphDB blinked is a worse trade
than letting one through, and every lane's own guards still apply downstream.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.workflow import _orchestrator as wf  # noqa: E402


def test_the_gate_runs_once_per_turn_before_routing():
    src = inspect.getsource(wf.WorkflowOrchestrator._dialogue_node)
    assert "await self._gate_referent_once(state)" in src, (
        "the turn-level referent gate is no longer called from the dialogue node, so every "
        "lane except sparql and events is unguarded again"
    )


def test_a_refusal_short_circuits_routing_to_the_response_node():
    src = inspect.getsource(wf.WorkflowOrchestrator._route_from_dialogue_impl)
    assert 'state.intermediate_results.get("referent_refusal_result")' in src
    assert '"referent_not_found"' in src, (
        "the routing override no longer records why it fired, so a route_decision audit "
        "cannot tell this apart from an ordinary response route"
    )


def test_the_response_node_collects_the_refusal_above_every_lane():
    """Ordering is the fix. A lane's draft answer would be about something else."""
    src = inspect.getsource(wf)
    refusal = src.index('_referent_refusal.get("formatted_response")')
    for later in (
        'elif dialogue_response:',
        '_register_result.get("formatted_response")',
        '_asset_state_result["formatted_response"]',
    ):
        assert src.index(later) > refusal, (
            f"{later!r} is now checked before the referent refusal, so a lane can answer "
            f"about a referent the building does not have"
        )


def test_the_gate_covers_the_standalone_place_lanes():
    """The lanes the review found unguarded, pinned by name.

    Listed by INTENT rather than by node so the set reads as "questions about somewhere",
    and nothing in it is specific to any building.
    """
    src = inspect.getsource(wf.WorkflowOrchestrator._gate_referent_once)
    for lane in (
        "register",
        "asset_state",
        "observability",
        "readiness_check",
        "diagnosis",
        "deliberate",
        "capability",
        "spatial_query",
        "floor_plan",
    ):
        assert f'"{lane}"' in src, f"the {lane} lane is no longer covered by the gate"


def test_the_data_intents_are_not_re_listed_but_inherited():
    """GATED_INTENTS is the shared set; restating it here would be the second copy."""
    src = inspect.getsource(wf.WorkflowOrchestrator._gate_referent_once)
    assert "GATED_INTENTS" in src
    assert '"sensor_data"' not in src, (
        "the data intents have been copied out of GATED_INTENTS into this method; the two "
        "lists will diverge and only one of them is the documented contract"
    )


def test_the_gate_fails_open_and_says_so():
    src = inspect.getsource(wf.WorkflowOrchestrator._gate_referent_once)
    assert "except Exception" in src
    assert "logger.warning" in src, (
        "the gate swallows its own failures silently; a guard that fails open without "
        "logging is indistinguishable from a guard that found nothing"
    )


def test_an_unscoped_question_is_not_gated():
    """A question naming no referent must not pay for the check twice or be refused."""
    src = inspect.getsource(wf.WorkflowOrchestrator._gate_referent_once)
    assert "if intent not in GATED_INTENTS and intent not in place_lanes" in src


def test_the_refusal_is_cleared_between_turns():
    """A refusal is as stale as an answer.

    Turn 1's "Room 9.99 does not exist" must not answer turn 2's question about a room
    that does. The suite's own staleness guard caught this key missing.
    """
    assert "referent_refusal_result" in wf._PER_TURN_LANE_KEYS
