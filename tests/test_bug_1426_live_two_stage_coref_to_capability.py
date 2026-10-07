# -*- coding: utf-8 -*-
"""BUG-1426, the LIVE failure: a follow-up asking "what time does it close?" after a
reply naming the cafe got the BUILDING's generic hours, not the cafe's.

Both unit-test files this bug already had passed throughout:
``tests/test_bug_1426_amenity_anaphor_survives_accents.py`` calls ``amenities_in_reply``
and ``resolve_sole_floor_or_amenity_anaphor`` DIRECTLY, and
``tests/test_f11_a_follow_up_can_point_at_a_floor_or_an_amenity.py``'s integration class
drives the real ``DialogueAgent.rewrite_to_standalone`` but only with lowercase,
unaccented fixtures ("cafe" in the reply, "cafe" as the lay term) -- never the accented
spelling a real rendered answer actually uses ("Café"). Neither file drove the rewrite's
OUTPUT into the capability lane: ``capability_agent.answer`` read the stale, un-rewritten
``state.user_message`` throughout, so even a perfect rewrite never reached it.

This file closes both gaps at once, end to end:

  1. the real `DialogueAgent.rewrite_to_standalone`, fed a reply that names the cafe with
     the accent a rendered answer actually uses ("Café"), against a graph label spelled
     without one ("Cafe") -- exactly BUG-1426's root cause for the dialogue_agent half;
  2. the glue the orchestrator's own coref block performs (`workflow/_orchestrator.py`,
     around the "Co-reference resolution" comment): replace `messages[-1]` and record
     `intermediate_results["coref_rewrite"]` -- copied here verbatim rather than invoking
     the whole node, which also runs unrelated guards (chart-affirmation, location-memory,
     "a reference to something I never said") this case does not need;
  3. the REAL `CapabilityAgent().answer()`, with only its data sources replaced (the same
     pattern as `test_amenity_and_room_answers_are_wired_into_their_lanes.py`), including a
     REAL `CapabilityGraphResolver` driven by a fake SPARQL executor -- so the mechanism
     under test is the actual lay-term scoring and `subject_facts` topic selection, not a
     mock that already knows the right answer.

`state.user_message` is asserted to stay stale throughout, the same as in production: the
fix must not depend on it being updated.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import orchestrator.agents.capability_agent as cap
import orchestrator.services.amenity_attribute_answer as amen_attr
import orchestrator.services.building_context as bctx
import orchestrator.services.capability_graph_resolver as cgr
import orchestrator.services.room_type_lookup as rtl
from orchestrator.agents.dialogue_agent import DialogueAgent
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

# The graph's OWN spelling for the amenity -- unaccented, as `tests/test_bug_1426_
# amenity_anaphor_survives_accents.py` establishes the live building actually declares it.
_AMENITY_CLASSES = [SimpleNamespace(label="Cafe", terms=("cafe", "canteen"))]

# A rendered reply using the accent a real answer uses ("Café"), naming the cafe's own
# floor in the same sentence -- BUG-1426's exact live shape (amenity-plus-floor).
_PREVIOUS_REPLY = "The Café is on Floor 0, open 08:00-16:30 on weekdays."

_LATEST_FOLLOW_UP = "What time does it close?"


def _conversation() -> ConversationState:
    return ConversationState(
        conversation_id="conv-bug-1426",
        user_id="tester",
        user_message=_LATEST_FOLLOW_UP,
        building_id="bldgX",
        current_intent="capability",
        messages=[
            Message(role="user", content="what is on the ground floor?"),
            Message(role="assistant", content=_PREVIOUS_REPLY),
            Message(role="user", content=_LATEST_FOLLOW_UP),
        ],
    )


async def _run_real_coref_rewrite(state: ConversationState) -> None:
    """Stage 1: the REAL rewrite, then the orchestrator's own glue -- not a hand-picked
    string. If the dialogue_agent accent-fold fix regresses, `rewritten` comes back None
    (the amenity label never matches the accented reply) and this coroutine is a no-op,
    which is exactly the live failure and makes stage 2's assertions fail honestly."""
    with patch(
        "orchestrator.services.record_registry.held_amenity_classes",
        new=AsyncMock(return_value=_AMENITY_CLASSES),
    ), patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(return_value=""),
    ) as gen:
        rewritten = await DialogueAgent().rewrite_to_standalone(state)
    assert rewritten is not None, (
        "the deterministic amenity resolver did not fire -- the accent-fold fix is "
        "not doing its job, or the model was asked (it must not be, for this case)"
    )
    gen.assert_not_called()
    # `workflow/_orchestrator.py`'s coref block, copied verbatim: replace messages[-1] and
    # record the rewrite for downstream lanes. It deliberately does NOT touch
    # `state.user_message` -- that is the other half of BUG-1426 under test here.
    original = state.messages[-1].content
    state.messages[-1] = Message(role=state.messages[-1].role, content=rewritten)
    state.intermediate_results["coref_rewrite"] = {"original": original, "rewritten": rewritten}


def _row(**fields) -> dict:
    return {k: {"value": v} for k, v in fields.items()}


_CAFE_ROW = _row(
    a="urn:x#cafe",
    label="Cafe",
    loc="Ground floor, by the atrium",
    note="Open 08:00-16:30 on weekdays.",
    cat="Catering",
    lay="cafe, canteen",
)
_HOURS_ROW = _row(
    a="urn:x#hours",
    label="Working Hours",
    answer="The building's general opening hours are 07:00-19:00, Monday to Friday.",
    cat="General",
    lay="opening hours, open, close, what time, hours",
)


async def _fake_sparql_exec(query: str) -> dict:
    if "subClassOf" in query:  # the kind-terms query; no inherited vocabulary needed here
        return {"results": {"bindings": []}}
    return {"results": {"bindings": [_CAFE_ROW, _HOURS_ROW]}}


def _wire_capability_lane(monkeypatch) -> None:
    """Isolate the capability lane's data sources, the same way
    `test_amenity_and_room_answers_are_wired_into_their_lanes.py` does -- a REAL
    `CapabilityGraphResolver` over a fake SPARQL executor, everything upstream of it
    stood down so the mechanism under test (lay-term scoring + `subject_facts`) decides
    the answer, not an earlier short-circuit."""
    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Test"))
    monkeypatch.setattr(
        cgr, "get_capability_graph_resolver", lambda: cgr.CapabilityGraphResolver(_fake_sparql_exec)
    )

    async def _no_rooms(_q, only=None):
        return None

    monkeypatch.setattr(rtl, "answer_live", _no_rooms)

    async def _no_attr(_q, _building_name):
        # The "hours" attribute pattern matches both the stale and the rewritten question
        # ("what time ... close"); stood down so the mechanism under test -- the graph
        # resolver's lay-term scoring and subject_facts -- is what decides the answer.
        return None

    monkeypatch.setattr(amen_attr, "answer_live", _no_attr)


@pytest.mark.asyncio
async def test_the_rewrite_reaches_the_capability_lane_and_the_cafe_answers_for_itself(
    monkeypatch,
):
    """The fixed path, end to end: coref rewrite -> capability lane."""
    state = _conversation()
    await _run_real_coref_rewrite(state)

    # Sanity on stage 1 (and the accent-fold fix): the rewrite names the graph's own
    # spelling, not the accented one from the reply.
    assert state.messages[-1].content == "What time does the Cafe close?"
    # The other half of the bug: user_message is NEVER updated by the coref block, in
    # this test exactly as in production. The fix must not depend on it changing.
    assert state.user_message == _LATEST_FOLLOW_UP

    _wire_capability_lane(monkeypatch)
    out = await cap.CapabilityAgent().answer(state)
    result = out.intermediate_results["capability_result"]

    assert result["provenance"] == "capability_graph"
    assert "Open 08:00-16:30" in result["response"], result["response"]
    assert "07:00-19:00" not in result["response"], (
        "the building's generic hours answered instead of the cafe's own — "
        "state.user_message was read instead of the coref rewrite"
    )


@pytest.mark.asyncio
async def test_without_the_rewrite_the_building_s_generic_hours_answer_instead(monkeypatch):
    """Contrast case, demonstrating WHY the fix matters: with no coref rewrite recorded
    (as for a turn-one question, or if `_effective_query` fell back silently), the stale
    text carries no amenity word at all, so the graph resolver never even matches the
    cafe -- this is the live defect, reproduced by the same real resolver."""
    state = _conversation()
    # No rewrite recorded: state.intermediate_results has no "coref_rewrite" key, and
    # state.user_message is the same stale text the orchestrator leaves it as.
    assert "coref_rewrite" not in state.intermediate_results

    _wire_capability_lane(monkeypatch)
    out = await cap.CapabilityAgent().answer(state)
    result = out.intermediate_results["capability_result"]

    assert result["provenance"] == "capability_graph"
    assert "07:00-19:00" in result["response"], result["response"]
    assert "Open 08:00-16:30" not in result["response"]
