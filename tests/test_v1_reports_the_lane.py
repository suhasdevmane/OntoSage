# -*- coding: utf-8 -*-
"""TODO-657: /v1/chat/completions says which lane answered, without disturbing a client.

The demo runs through Open WebUI, which posts to `/v1/chat/completions`. That body carried
no intent, so every lane assertion in the regression corpus was unevaluable on the demo
endpoint — and BUG-631's shape, a plausible answer from the WRONG lane, was invisible there.

The field is `ontosage_intent`, following the `ontosage_evidence_record` /
`ontosage_llm_degraded` convention already on this body. What these tests pin:

* non-streamed: the field is present, equals the finished state's `current_intent` (the
  value /chat returns as `intent`), and every standard OpenAI field is unchanged;
* streamed: the lane rides ONLY on the final `finish_reason: "stop"` chunk, at the TOP level
  of the chunk, never inside `delta` — so a client that reassembles `delta.content` gets
  exactly the answer it got before, and the lane is read from the same final state the
  answer text came from;
* the stream framing is untouched: role chunk first, `data: [DONE]` last.

Every manager is a fake; nothing reaches Redis, Postgres or a model.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

ANSWER = "Room 7.42 is at 21.4 °C. " * 30  # long enough to be split across content chunks


class _FakeRedis:
    client = None  # read by the rate-limit middleware; None selects its fallback

    async def load_state(self, conversation_id: str):
        return None

    async def save_state(self, state) -> None:
        return None

    async def save_message(self, *args, **kwargs) -> None:
        return None


class _FakeOrchestrator:
    def __init__(self, intent):
        self.intent = intent

    def _finish(self, state):
        from shared.models import Message

        state.current_intent = self.intent
        state.messages.append(Message(role="assistant", content=ANSWER, timestamp=datetime.now()))
        return state

    async def execute(self, state):
        return self._finish(state)

    async def stream_execute(self, state):
        yield {"dialogue": state}
        yield {"sparql": state}
        yield {"response": self._finish(state)}


@contextmanager
def _patched(intent):
    import orchestrator.main as m

    with patch.object(m, "redis_manager", _FakeRedis()), patch.object(
        m, "postgres_manager", None
    ), patch.object(m, "orchestrator", _FakeOrchestrator(intent)), patch.object(
        m, "resolve_forwarded_user", AsyncMock(return_value=("openwebui_user", "readonly"))
    ):
        yield m


async def _post(body: Dict[str, Any]):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import _oai_auth, app

    app.dependency_overrides[_oai_auth] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.post("/v1/chat/completions", json=body, headers={"X-Chat-Id": "t"})
    finally:
        app.dependency_overrides.pop(_oai_auth, None)


def _body(stream: bool) -> Dict[str, Any]:
    return {
        "model": "ontosage",
        "stream": stream,
        "messages": [{"role": "user", "content": "What is the temperature in room 7.42?"}],
    }


def _frames(text: str) -> List[str]:
    """The `data:` payloads of an SSE body, in order."""
    return [line[6:] for line in text.split("\n") if line.startswith("data: ")]


# ── non-streamed ────────────────────────────────────────────────────────────────


async def test_the_body_names_the_lane():
    with _patched("sensor_data"):
        resp = await _post(_body(stream=False))
    assert resp.status_code == 200
    assert resp.json()["ontosage_intent"] == "sensor_data"


async def test_the_openai_fields_are_unchanged():
    with _patched("sensor_data"):
        payload = (await _post(_body(stream=False))).json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"] == {"role": "assistant", "content": ANSWER}
    assert payload["choices"][0]["finish_reason"] == "stop"
    # Additive only: no standard field renamed, and the lane is not smuggled into `message`.
    assert set(payload) >= {"id", "object", "created", "model", "choices", "usage"}
    assert "intent" not in payload["choices"][0]["message"]


async def test_a_turn_that_never_classified_reports_no_lane_rather_than_a_guess():
    with _patched(None):
        payload = (await _post(_body(stream=False))).json()
    assert "ontosage_intent" in payload
    assert payload["ontosage_intent"] is None


def test_the_timeout_body_carries_the_field_too():
    """A timed-out turn has no lane. The key is still present, so a reader can tell 'no
    lane' from 'an older server that never reported one'."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    timeout_body = src[src.index('"causes": ["pipeline_timeout"]') :][:600]
    assert '"ontosage_intent": None' in timeout_body


# ── streamed ────────────────────────────────────────────────────────────────────


async def _stream(intent) -> List[str]:
    with _patched(intent):
        resp = await _post(_body(stream=True))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return _frames(resp.text)


async def test_the_final_chunk_names_the_lane():
    frames = await _stream("register")
    chunks = [json.loads(f) for f in frames if f != "[DONE]"]
    final = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert len(final) == 1
    assert final[0]["ontosage_intent"] == "register"


async def test_only_the_final_chunk_carries_it_and_never_inside_delta():
    frames = await _stream("register")
    chunks = [json.loads(f) for f in frames if f != "[DONE]"]
    carrying = [c for c in chunks if "ontosage_intent" in c]
    assert len(carrying) == 1 and carrying[0]["choices"][0]["finish_reason"] == "stop"
    for c in chunks:
        assert set(c["choices"][0]["delta"]) <= {"role", "content"}, c
        assert c["object"] == "chat.completion.chunk"


async def test_the_stream_framing_is_unchanged():
    frames = await _stream("register")
    assert frames[-1] == "[DONE]"
    first = json.loads(frames[0])
    assert first["choices"][0]["delta"] == {"role": "assistant"}


async def test_the_reassembled_answer_is_exactly_what_it_was():
    """What an OpenAI client renders: every delta.content, concatenated, minus the
    pipeline-steps panel. The lane must add nothing to it."""
    import re

    frames = await _stream("register")
    text = "".join(
        json.loads(f)["choices"][0]["delta"].get("content") or "" for f in frames if f != "[DONE]"
    )
    text = re.sub(r"<details>.*?</details>\s*", "", text, count=1, flags=re.S)
    assert text == ANSWER
    assert "register" not in text


async def test_the_streamed_lane_matches_the_unstreamed_one():
    frames = await _stream("sensor_data")
    streamed = [json.loads(f) for f in frames if f != "[DONE]"][-1]["ontosage_intent"]
    with _patched("sensor_data"):
        unstreamed = (await _post(_body(stream=False))).json()["ontosage_intent"]
    assert streamed == unstreamed == "sensor_data"
