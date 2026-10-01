# -*- coding: utf-8 -*-
"""W5-02 — the session summary is carried on EVERY chat entry point, and something reads it.

WHAT WAS MEASURED, AND WHY THIS FILE EXISTS
-------------------------------------------
Read from `orchestrator/main.py` on 2026-09-29, before any change:

* ``TurnMemoryService`` was constructed in exactly ONE function, ``openai_chat_completions``;
* ``save_turn`` was called from two places, both inside that same function;
* ``get_older_context`` was called from one place, likewise.

So ``/chat``, ``/chat/stream`` and the ``/stream`` websocket wrote no turn and read no
memory. Open WebUI uses ``/v1/chat/completions`` and the regression probe uses ``/chat``, so
the feature was live on the endpoint that is demonstrated and absent from the endpoint that
is measured — and every offline test passed, because every offline test exercised ``/v1`` or
the service in isolation. That asymmetry IS the row.

It is the same shape as BUG-655 one section earlier in the same file: ``prune_inherited``
ran on ``/v1`` only, and three routes carried a result about room A into a question about
room B. The fix there was one helper called by four routes. The fix here is the same, so the
guard against it recurring has to be the same too: this file reads
``main.CHAT_ENTRY_POINTS`` and fails when a chat route exists that the set does not name.

A NOTE ON WHERE THE SUMMARY GOES
--------------------------------
``/v1`` prepended its block as a ``system`` message at index 0. Nothing in ``orchestrator/``
matches on ``role == "system"``, and both readers of ``state.messages`` take the LAST five or
six entries (``ContextManager.prune_messages(max_messages=5)``,
``format_conversation_history(msgs, max_messages=6)``). A block at index 0 is therefore
dropped by every reader as soon as the conversation is longer than three turns — which is
exactly when long-term memory is the point. The last two tests here pin the replacement: the
summary goes on the bus and reaches the co-reference rewrite's prompt.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Set
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

MAIN = Path(__file__).resolve().parent.parent / "orchestrator" / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8", errors="replace")
TREE = ast.parse(SOURCE)

#: The two halves. A route with only the read half reports success by returning "" forever.
REQUIRED = ("_inject_session_summary", "_save_turn_memory")


def _declared_entry_points() -> Dict[str, str]:
    """``main.CHAT_ENTRY_POINTS`` read from the SOURCE, so importing main is not needed."""
    for node in ast.walk(TREE):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "CHAT_ENTRY_POINTS"
        ):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", "") == "CHAT_ENTRY_POINTS":
                    return ast.literal_eval(node.value)
    raise AssertionError("main.CHAT_ENTRY_POINTS is gone — W5-02's contract has no definition")


ENTRY_POINTS = _declared_entry_points()


def _functions() -> Dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls_within(node: ast.AST) -> Set[str]:
    """Every function name called anywhere inside ``node``, nested defs included.

    Nested defs matter: two of the four routes do their work inside an ``event_generator``
    closure, so a search restricted to the top-level body would find nothing and pass.
    """
    names: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _routed_paths() -> Set[str]:
    """Every path registered with ``@app.post`` / ``@app.websocket`` in this module."""
    paths: Set[str] = set()
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                continue
            if deco.func.attr not in ("post", "websocket"):
                continue
            if deco.args and isinstance(deco.args[0], ast.Constant):
                paths.add(str(deco.args[0].value))
    return paths


# ── the set is explicit, and it is the real set ─────────────────────────────────────────


def test_the_declared_entry_point_set_is_the_four_chat_routes():
    assert ENTRY_POINTS == {
        "/chat": "chat",
        "/chat/stream": "chat_stream",
        "/stream": "websocket_stream",
        "/v1/chat/completions": "openai_chat_completions",
    }


def test_no_chat_route_exists_that_the_set_does_not_name():
    """A fifth entry point cannot be added without deciding about memory.

    This is the assertion that would have caught the original defect: a route that takes a
    user message and runs the workflow, with no session memory and no test saying so.
    """
    conversational = {p for p in _routed_paths() if "chat" in p or p == "/stream"}
    assert conversational - set(ENTRY_POINTS) == set()


def test_every_named_function_exists():
    missing = sorted(set(ENTRY_POINTS.values()) - set(_functions()))
    assert not missing, f"CHAT_ENTRY_POINTS names functions that are gone: {missing}"


# ── both halves, on every one of them ───────────────────────────────────────────────────


@pytest.mark.parametrize("path,function", sorted(ENTRY_POINTS.items()))
def test_the_route_reads_and_writes_the_session_memory(path, function):
    calls = _calls_within(_functions()[function])
    missing = [name for name in REQUIRED if name not in calls]
    assert not missing, f"{path} ({function}) never calls {missing}"


def test_the_offloaded_report_job_saves_its_turn_too():
    """``/chat`` returns before its own save when it offloads a report to the job queue, so
    the answer the user eventually reads would otherwise be the one hole left in the
    memory."""
    assert "_save_turn_memory" in _calls_within(_functions()["_run_workflow_as_job"])


def test_no_route_builds_its_own_copy_of_the_memory_helpers():
    """One helper, four callers. A copy per route is how three of them came to be missing it.

    ``TurnMemoryService`` may be constructed only by the shared factory; ``save_turn`` and
    the session readers may be called only from the two helpers.
    """
    # ENTRY_POINTS is DERIVED, not written out, so a change to the derivation empties it and
    # "one helper, four callers" becomes a statement about no caller (CAVEAT-1115). Three of
    # the four were missing the helper once; that is the state this must be able to see.
    assert (
        len(ENTRY_POINTS) >= 4
    ), f"only {len(ENTRY_POINTS)} chat entry points were derived: {sorted(ENTRY_POINTS)}"
    for function in ENTRY_POINTS.values():
        calls = _calls_within(_functions()[function])
        assert "TurnMemoryService" not in calls, f"{function} builds its own memory service"
        assert "save_turn" not in calls, f"{function} calls save_turn directly"
        assert "get_session_summary" not in calls, f"{function} reads the store directly"
        assert "get_session_context" not in calls, f"{function} reads the store directly"


def test_the_helpers_are_the_only_place_the_store_is_touched():
    body = SOURCE
    assert body.count(".save_turn(") == 1
    # ONE read per turn, and it is the two-key one: `get_session_context` returns the
    # rendered block AND the structured turns from a single query (BUG-941 needs the turns;
    # the prompts need the block). Both names are pinned so that neither a second reader nor
    # a silent return to the summary-only call can be added without this failing.
    assert body.count(".get_session_context(") == 1
    assert body.count(".get_session_summary(") == 0


# ── it is not injected where nothing would read it ──────────────────────────────────────


def test_the_summary_is_not_prepended_as_a_system_message_any_more():
    """Every reader of ``state.messages`` takes the LAST five or six entries, so a block at
    index 0 is dropped once the conversation is longer than three turns — which is exactly
    when it is needed. The old ``/v1`` injection did that and could not have worked."""
    assert 'Message(role="system"' not in SOURCE


def test_nothing_in_the_orchestrator_reads_a_system_message_out_of_the_state():
    """The premise of the test above, checked rather than assumed."""
    root = MAIN.parent
    pattern = re.compile(r"""role\s*==\s*["']system["']""")
    offenders = [
        p.as_posix()
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
        and pattern.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == []


def test_the_bus_key_the_helper_writes_is_the_one_the_rewrite_reads():
    inject = _functions()["_inject_session_summary"]
    written = {
        node.slice.value
        for node in ast.walk(inject)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
    }
    assert "session_summary" in written

    dialogue = (MAIN.parent / "agents" / "dialogue_agent.py").read_text(encoding="utf-8")
    assert 'intermediate_results.get("session_summary")' in dialogue


# ── and something actually reads it ─────────────────────────────────────────────────────


def _state_with(summary: str):
    from shared.models import ConversationState, Message

    contents = [
        "where is the nearest defibrillator on floor 2",
        "It is by the north stair.",
        "what is the co2 in room 5.01",
        "That is answered above.",
        "and humidity there",
    ]
    state = ConversationState(
        conversation_id="conv-w5",
        user_id="tester",
        user_message=contents[-1],
        building_id="bldg1",
        messages=[
            Message(role="user" if i % 2 == 0 else "assistant", content=c)
            for i, c in enumerate(contents)
        ],
    )
    if summary:
        state.intermediate_results["session_summary"] = summary
    return state


@pytest.mark.asyncio
async def test_the_rewrite_prompt_carries_the_summary_when_there_is_one():
    """The delivery step. A lane that runs and is read by nobody is this repo's most
    expensive recurring defect (agent-patterns rule 5, step 3)."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    summary = "Turns 1-30 covered: defibrillator; floor 2 (30 answered, 0 declined)."
    gen = AsyncMock(return_value="what is the humidity in room 5.01")
    with patch("orchestrator.agents.dialogue_agent.llm_manager.generate", new=gen):
        await DialogueAgent().rewrite_to_standalone(_state_with(summary))
    prompt = gen.await_args.args[0]
    assert summary in prompt
    assert "never use them to state a value" in prompt


@pytest.mark.asyncio
async def test_no_summary_leaves_the_rewrite_prompt_exactly_as_it_was():
    from orchestrator.agents.dialogue_agent import DialogueAgent

    gen = AsyncMock(return_value="what is the humidity in room 5.01")
    with patch("orchestrator.agents.dialogue_agent.llm_manager.generate", new=gen):
        await DialogueAgent().rewrite_to_standalone(_state_with(""))
    assert "Subjects from earlier in this session" not in gen.await_args.args[0]


# ── through the real routes, not through the source ─────────────────────────────────────
#
# The tests above read `main.py`. These drive each route through the ASGI app and inspect
# what the WORKFLOW WAS HANDED — because a helper that exists and is not reached is the
# defect this row records, and the source can satisfy an AST check while the call sits on a
# branch nothing takes. The harness is BUG-655's, reused rather than rebuilt: it already
# drives all four routes with every manager faked (lesson #136 — grep by purpose first).


def _load_harness():
    """BUG-655's route harness, loaded BY PATH.

    `tests/` is not an importable package here and pytest's import mode does not put it on
    `sys.path`, so a plain `import test_...` raises ModuleNotFoundError at collection.
    """
    import importlib.util

    path = Path(__file__).with_name("test_every_chat_entry_point_prunes_inherited_state.py")
    spec = importlib.util.spec_from_file_location("w5_route_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _load_harness()

SUMMARY = "Turns 1-30 covered: defibrillator; floor 2 (30 answered, 0 declined)."


class _StubMemory:
    """A TurnMemoryService double that records what each route asked it to do."""

    def __init__(self, summary: str):
        self._summary = summary
        self.read_for: list = []
        self.saved_for: list = []

    async def get_session_summary(self, conversation_id: str, skip_recent: int = 20) -> str:
        self.read_for.append(conversation_id)
        return self._summary

    async def get_session_context(self, conversation_id: str, skip_recent: int = 20):
        """The two-key read every route now uses (BUG-941): block plus structured turns."""
        from orchestrator.services.session_summary import TurnNote

        self.read_for.append(conversation_id)
        notes = [
            TurnNote(
                turn_index=1,
                question="where is the defibrillator?",
                intent="metadata",
                outcome="answered",
            )
        ]
        return self._summary, notes

    async def get_carry_forward(self, conversation_id: str) -> dict:
        return {}

    async def save_turn(self, state) -> None:
        self.saved_for.append(state.conversation_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", harness.ROUTES)
async def test_every_route_hands_the_workflow_the_session_summary(route):
    import orchestrator.main as m

    stub = _StubMemory(SUMMARY)
    with patch.object(m, "_turn_memory_service", lambda: stub):
        orch = await harness._ask(route, [harness.ROOM_A_Q], harness.FOLLOW_UP_Q)
    assert orch.seen is not None, f"{route}: the workflow never ran"
    assert orch.seen.get("session_summary") == SUMMARY, f"{route}: no summary on the bus"
    assert stub.read_for, f"{route}: the store was never read"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", harness.ROUTES)
async def test_every_route_writes_the_turn_it_just_answered(route):
    """The half that is easy to forget: without it the read half returns "" forever."""
    import orchestrator.main as m

    stub = _StubMemory("")
    with patch.object(m, "_turn_memory_service", lambda: stub):
        await harness._ask(route, [harness.ROOM_A_Q], harness.FOLLOW_UP_Q)
    assert stub.saved_for, f"{route}: the completed turn was never stored"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", harness.ROUTES)
async def test_an_empty_store_leaves_no_key_on_the_bus(route):
    """Absent memory must be absent, not an empty string a prompt would still render."""
    import orchestrator.main as m

    with patch.object(m, "_turn_memory_service", lambda: _StubMemory("")):
        orch = await harness._ask(route, [harness.ROOM_A_Q], harness.FOLLOW_UP_Q)
    assert "session_summary" not in (orch.seen or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("route", harness.ROUTES)
async def test_a_broken_store_costs_the_memory_and_not_the_answer(route):
    """A memory failure must never sink a turn — the answer still goes out."""
    import orchestrator.main as m

    class _Broken(_StubMemory):
        async def get_session_summary(self, conversation_id, skip_recent=20):
            raise RuntimeError("pool exhausted")

        async def save_turn(self, state):
            raise RuntimeError("pool exhausted")

    with patch.object(m, "_turn_memory_service", lambda: _Broken("")):
        orch = await harness._ask(route, [harness.ROOM_A_Q], harness.FOLLOW_UP_Q)
    assert orch.seen is not None, f"{route}: a memory failure stopped the workflow"
