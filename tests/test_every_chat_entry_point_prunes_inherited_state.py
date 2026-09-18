# -*- coding: utf-8 -*-
"""BUG-655: every conversational entry point applies the same inherited-state guard.

`prune_inherited` (V12-11) ran on `/v1/chat/completions` ONLY. `/chat`, `/chat/stream` and the
`/stream` websocket each restore the WHOLE `intermediate_results` from Redis and pruned
nothing — so on the endpoint the regression probe measures, a result about room A rode into a
question about room B.

These tests drive each ROUTE, not the helper alone: a guard that exists and is not called by
a route is the defect this row records. Each one restores a state carrying place-bound keys
about one room, asks about another, and inspects what the WORKFLOW was handed — the state at
the moment `execute` / `stream_execute` was called, snapshotted, so a prune that happened
only afterwards would still fail.

Negative cases sit beside every positive: a follow-up naming no place and a question about
the SAME place must keep what they inherited, or carry-forward ("now plot that") is broken
to fix a bug it does not have.

The second defect in the row — adjacent-turn comparison — is pinned too: room A, then a
follow-up naming no place, then room B, must prune on the third turn.

Nothing here reaches Redis, Postgres, GraphDB or a model: every manager is a fake.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

ROOM_A_Q = "What is the temperature in room 7.42?"
FOLLOW_UP_Q = "How has that changed over the last week?"
ROOM_B_Q = "And what is it in room 3.18?"
SAME_ROOM_Q = "What is the CO2 in room 7.42 now?"
NO_PLACE_Q = "Now plot that"

#: Place-bound keys a previous turn can leave behind, plus two that are not about a place.
INHERITED = {
    "forecast_result": {"about": "room 7.42", "success": True},
    "anomaly_result": {"about": "room 7.42"},
    "visualization_path": "/app/outputs/room_742.png",
    "unrelated_preference": {"units": "metric"},
    "fresh_session": False,
}
PLACE_BOUND_INHERITED = ("forecast_result", "anomaly_result", "visualization_path")


def _history(*user_texts: str) -> List[Any]:
    from shared.models import Message

    out: List[Any] = []
    for text in user_texts:
        out.append(Message(role="user", content=text, timestamp=datetime.now()))
        out.append(Message(role="assistant", content="(answer)", timestamp=datetime.now()))
    return out


def _saved_state(conversation_id: str, *user_texts: str):
    from shared.models import ConversationState

    return ConversationState(
        conversation_id=conversation_id,
        user_message=user_texts[-1] if user_texts else "",
        messages=_history(*user_texts),
        intermediate_results=copy.deepcopy(INHERITED),
    )


class _FakeRedis:
    """load_state returns the prepared state; every write is a no-op."""

    #: The rate-limit middleware reads this; None selects its in-process fallback.
    client = None

    def __init__(self, state):
        self._state = state

    async def load_state(self, conversation_id: str):
        return copy.deepcopy(self._state) if self._state is not None else None

    async def save_state(self, state) -> None:
        return None

    async def save_message(self, *args, **kwargs) -> None:
        return None

    async def add_conversation_to_user(self, *args, **kwargs) -> None:
        return None


class _FakeOrchestrator:
    """Records what the workflow was HANDED, then answers without running anything."""

    def __init__(self, intent: str = "sensor_data", answer: str = "It is 21.4 °C."):
        self.seen: Optional[Dict[str, Any]] = None
        self.seen_user_message: Optional[str] = None
        self.intent = intent
        self.answer = answer

    def _finish(self, state):
        from shared.models import Message

        self.seen = copy.deepcopy(state.intermediate_results)
        self.seen_user_message = state.user_message
        state.current_intent = self.intent
        state.messages.append(
            Message(role="assistant", content=self.answer, timestamp=datetime.now())
        )
        return state

    async def execute(self, state):
        return self._finish(state)

    async def stream_execute(self, state):
        yield {"dialogue": state}
        yield {"response": self._finish(state)}


@contextmanager
def _patched_main(saved_state, orch):
    import orchestrator.main as m

    with patch.object(m, "redis_manager", _FakeRedis(saved_state)), patch.object(
        m, "postgres_manager", None
    ), patch.object(m, "orchestrator", orch), patch.object(m, "job_queue", None):
        yield m


def _user_context():
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext

    return UserContext(
        user_id="tester",
        username="tester",
        role="admin",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS.get("admin", set()),
    )


async def _post(path: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import _oai_auth, app, get_user_context

    app.dependency_overrides[get_user_context] = _user_context
    app.dependency_overrides[_oai_auth] = lambda: None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=body, headers=headers or {})
    finally:
        app.dependency_overrides.pop(get_user_context, None)
        app.dependency_overrides.pop(_oai_auth, None)


# ── the four routes ─────────────────────────────────────────────────────────────


async def _ask_chat(history: List[str], question: str) -> _FakeOrchestrator:
    orch = _FakeOrchestrator()
    with _patched_main(_saved_state("conv_s:tester", *history), orch):
        resp = await _post("/chat", {"message": question, "session_id": "s"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True, resp.text
    return orch


async def _ask_chat_stream(history: List[str], question: str) -> _FakeOrchestrator:
    orch = _FakeOrchestrator()
    with _patched_main(_saved_state("c1:tester", *history), orch):
        resp = await _post("/chat/stream", {"message": question, "conversation_id": "c1:tester"})
    assert resp.status_code == 200, resp.text
    assert "[DONE]" in resp.text, resp.text
    return orch


def _ask_websocket(history: List[str], question: str) -> _FakeOrchestrator:
    from starlette.testclient import TestClient

    orch = _FakeOrchestrator()
    auth = {"mode": "session", "username": "tester", "role": "admin", "is_admin": True}
    with _patched_main(_saved_state("c1:tester", *history), orch) as m, patch.object(
        m, "_authenticate_websocket", AsyncMock(return_value=auth)
    ):
        client = TestClient(m.app)
        with client.websocket_connect("/stream") as ws:
            ws.send_text(json.dumps({"message": question, "conversation_id": "c1:tester"}))
            frames = []
            while True:
                frame = ws.receive_json()
                frames.append(frame)
                if frame.get("type") in ("done", "error"):
                    break
    assert frames[-1]["type"] == "done", frames
    return orch


async def _ask_v1(history: List[str], question: str) -> _FakeOrchestrator:
    """/v1 takes history from the request body, and carry-forward from Redis."""
    orch = _FakeOrchestrator()
    messages: List[Dict[str, str]] = []
    for text in history:
        messages += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": "(answer)"},
        ]
    messages.append({"role": "user", "content": question})
    import orchestrator.main as m

    with _patched_main(_saved_state("owui_c1:openwebui_user", *history), orch), patch.object(
        m, "resolve_forwarded_user", AsyncMock(return_value=("openwebui_user", "readonly"))
    ):
        resp = await _post(
            "/v1/chat/completions",
            {"model": "ontosage", "stream": False, "messages": messages},
            headers={"X-Chat-Id": "c1"},
        )
    assert resp.status_code == 200, resp.text
    return orch


async def _ask(route: str, history: List[str], question: str) -> _FakeOrchestrator:
    if route == "/stream":
        import asyncio

        # The websocket TestClient runs the app on its own loop in a thread; calling it
        # from inside this test's running loop would deadlock, so hand it to a worker.
        return await asyncio.to_thread(_ask_websocket, history, question)
    return await {"/chat": _ask_chat, "/chat/stream": _ask_chat_stream, "/v1": _ask_v1}[route](
        history, question
    )


ROUTES = ("/chat", "/chat/stream", "/stream", "/v1")

#: /v1 carries only these two forward from Redis, by design; the others never reach it.
_V1_CARRIED = ("forecast_result", "analytics_result")


def _place_bound_seen(route: str, orch: _FakeOrchestrator) -> List[str]:
    assert orch.seen is not None, f"{route}: the workflow never ran"
    return sorted(k for k in PLACE_BOUND_INHERITED if k in orch.seen)


def _expected_when_kept(route: str) -> List[str]:
    if route == "/v1":
        return sorted(k for k in PLACE_BOUND_INHERITED if k in _V1_CARRIED)
    return sorted(PLACE_BOUND_INHERITED)


@pytest.mark.parametrize("route", ROUTES)
async def test_a_new_room_drops_what_was_inherited_about_the_old_one(route):
    orch = await _ask(route, [ROOM_A_Q], ROOM_B_Q)
    assert (
        _place_bound_seen(route, orch) == []
    ), f"{route} handed the workflow results about room 7.42 under a question about 3.18"


@pytest.mark.parametrize("route", ROUTES)
async def test_the_look_back_skips_a_follow_up_that_named_no_place(route):
    """Second defect in BUG-655: A -> follow-up naming nothing -> B must still prune."""
    orch = await _ask(route, [ROOM_A_Q, FOLLOW_UP_Q], ROOM_B_Q)
    assert _place_bound_seen(route, orch) == []


@pytest.mark.parametrize("route", ROUTES)
async def test_a_follow_up_naming_no_place_keeps_what_it_inherited(route):
    """The case carry-forward exists for. Dropping here would break 'now plot that'."""
    orch = await _ask(route, [ROOM_A_Q], NO_PLACE_Q)
    assert _place_bound_seen(route, orch) == _expected_when_kept(route)


@pytest.mark.parametrize("route", ROUTES)
async def test_the_same_place_keeps_what_it_inherited(route):
    orch = await _ask(route, [ROOM_A_Q, FOLLOW_UP_Q], SAME_ROOM_Q)
    assert _place_bound_seen(route, orch) == _expected_when_kept(route)


@pytest.mark.parametrize("route", ("/chat", "/chat/stream", "/stream"))
async def test_keys_not_about_a_place_survive_a_switch(route):
    orch = await _ask(route, [ROOM_A_Q], ROOM_B_Q)
    assert orch.seen["unrelated_preference"] == {"units": "metric"}


@pytest.mark.parametrize("route", ("/chat", "/chat/stream", "/stream"))
async def test_a_first_turn_with_nothing_inherited_is_untouched(route):
    orch = _FakeOrchestrator()
    if route == "/stream":
        import asyncio

        def _run():
            from starlette.testclient import TestClient

            auth = {"mode": "session", "username": "tester", "role": "admin", "is_admin": True}
            with _patched_main(None, orch) as m, patch.object(
                m, "_authenticate_websocket", AsyncMock(return_value=auth)
            ):
                with TestClient(m.app).websocket_connect("/stream") as ws:
                    ws.send_text(json.dumps({"message": ROOM_B_Q}))
                    while ws.receive_json().get("type") not in ("done", "error"):
                        pass

        await asyncio.to_thread(_run)
    else:
        body = {"message": ROOM_B_Q}
        with _patched_main(None, orch):
            resp = await _post(route, body)
        assert resp.status_code == 200
    assert orch.seen is not None, f"{route}: a NEW conversation never reached the workflow"
    assert _place_bound_seen(route, orch) == []


async def test_the_websocket_runs_the_question_just_asked():
    """Found while wiring the guard: a resumed websocket conversation kept `user_message`
    from the PREVIOUS turn, and a new one omitted the required field altogether."""
    orch = await _ask("/stream", [ROOM_A_Q], ROOM_B_Q)
    assert orch.seen_user_message == ROOM_B_Q


# ── the helper itself ───────────────────────────────────────────────────────────


def test_the_helper_prunes_in_place_and_reports_what_it_dropped():
    from orchestrator.main import _prune_inherited_state

    inherited = copy.deepcopy(INHERITED)
    dropped = _prune_inherited_state(inherited, _history(ROOM_A_Q), ROOM_B_Q, "test")
    assert sorted(dropped) == sorted(PLACE_BOUND_INHERITED)
    assert not any(k in inherited for k in PLACE_BOUND_INHERITED)
    assert inherited["unrelated_preference"] == {"units": "metric"}


def test_the_helper_reads_openai_shaped_dicts_too():
    from orchestrator.main import _prune_inherited_state

    inherited = copy.deepcopy(INHERITED)
    history = [{"role": "user", "content": ROOM_A_Q}, {"role": "assistant", "content": "x"}]
    assert _prune_inherited_state(inherited, history, ROOM_B_Q, "test")


def test_an_assistant_message_naming_a_place_is_not_the_users_subject():
    """Only what the USER named is the subject. An answer mentioning a comparison room must
    not become the place the next question is compared against."""
    from orchestrator.main import _prune_inherited_state
    from shared.models import Message

    history = [
        Message(role="user", content=FOLLOW_UP_Q, timestamp=datetime.now()),
        Message(role="assistant", content="Room 3.18 is warmer.", timestamp=datetime.now()),
    ]
    inherited = copy.deepcopy(INHERITED)
    assert _prune_inherited_state(inherited, history, ROOM_B_Q, "test") == []
    assert "forecast_result" in inherited


def test_a_guard_that_fails_never_sinks_the_turn():
    from orchestrator.main import _prune_inherited_state

    inherited = copy.deepcopy(INHERITED)
    with patch(
        "orchestrator.services.context_switch.prune_inherited",
        side_effect=RuntimeError("boom"),
    ):
        assert _prune_inherited_state(inherited, _history(ROOM_A_Q), ROOM_B_Q, "test") == []
    assert inherited == INHERITED


def test_empty_or_missing_inherited_state_is_a_no_op():
    from orchestrator.main import _prune_inherited_state

    assert _prune_inherited_state({}, _history(ROOM_A_Q), ROOM_B_Q, "test") == []
    assert _prune_inherited_state(None, _history(ROOM_A_Q), ROOM_B_Q, "test") == []
