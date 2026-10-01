# -*- coding: utf-8 -*-
"""CAVEAT-656: Open WebUI streams, so the streaming branch of /v1/chat/completions is the
code path real users run — and every quality number this project has (the 51-case gate, the
unseen tails, the demo rehearsals) was measured through `"stream": false` or `/chat`.

These tests pin the two paths to each other. What matters is not that the stream is
well-formed — `test_v1_reports_the_lane.py` already covers the framing — but that a client
reassembling `delta.content` gets THE SAME ANSWER, under the same guards, with the same
honesty metadata, and that a failure reaches the reader as a failure.

The honesty guards (publication gate, answer-relevance gate, grounding guard, claim binder)
all live in `_response_node`, INSIDE the LangGraph state machine, and both branches take
their answer text from the last assistant message of the state the graph returned. So they
apply on both paths by construction — and `test_no_branch_re_derives_the_answer` plus
`test_main_py_applies_no_gate_of_its_own` are what keep that true.

Every manager is a fake; nothing reaches Redis, Postgres or a model.
"""

from __future__ import annotations

import ast
import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

QUESTION = "What is the temperature in room 7.42?"
ANSWER = "Room 7.42 averaged 21.4 °C over the last 24 hours, from 1 sensor. " * 8
EVIDENCE = {"sources": [{"uuid": "abc"}], "verified": True}


# ── fakes ───────────────────────────────────────────────────────────────────────


class _FakeRedis:
    client = None  # read by the rate-limit middleware; None selects its fallback

    async def load_state(self, conversation_id: str):
        return None

    async def save_state(self, state) -> None:
        return None

    async def save_message(self, *args, **kwargs) -> None:
        return None


class _Orchestrator:
    """Finishes the turn the way `_response_node` does: an assistant Message, appended
    after the guards have had their say."""

    def __init__(self, answer: str = ANSWER, intent: str = "sensor_data", evidence=EVIDENCE):
        self.answer = answer
        self.intent = intent
        self.evidence = evidence

    def _finish(self, state):
        from shared.models import Message

        state.current_intent = self.intent
        if self.evidence is not None:
            state.intermediate_results["evidence_record"] = self.evidence
        state.messages.append(
            Message(role="assistant", content=self.answer, timestamp=datetime.now())
        )
        return state

    async def execute(self, state):
        return self._finish(state)

    async def stream_execute(self, state):
        yield {"dialogue": state}
        yield {"sql": state}
        yield {"response": self._finish(state)}


class _FailingOrchestrator:
    """A workflow that raises. Reproduces what the REAL methods hand back:

    * `execute()` catches and appends an assistant message (`_user_friendly_error`);
    * `stream_execute()` catches and yields `{"error": <str>, "state": state}` — a step
      whose only ConversationState is the PRE-graph one, whose last message is the user's
      own question.

    Verified against the real `WorkflowOrchestrator` on a graph that raises.
    """

    FRIENDLY = "I wasn't able to process your request. Could you try rephrasing your question?"

    async def execute(self, state):
        from shared.models import Message

        state.messages.append(
            Message(role="assistant", content=self.FRIENDLY, timestamp=datetime.now())
        )
        return state

    async def stream_execute(self, state):
        yield {"dialogue": state}
        yield {"error": "RuntimeError: node blew up", "state": state}


class _ExplodingOrchestrator:
    """The async generator itself raises, with no error step — e.g. a `GeneratorExit`-class
    fault or a bug in `stream_execute`'s own handler."""

    async def execute(self, state):
        raise RuntimeError("boom")

    async def stream_execute(self, state):
        yield {"dialogue": state}
        raise RuntimeError("boom")


class _AngryPostgres:
    """Reaches the persistence block that sits BETWEEN the assembled answer and the first
    content chunk. Anything raising there loses the whole answer."""

    class _Pool:
        pass

    pool = _Pool()

    async def create_user(self, *a, **k):
        return None

    async def save_message(self, *a, **k):
        raise RuntimeError("postgres is down")


@contextmanager
def _patched(orch, postgres=None):
    import orchestrator.main as m

    with patch.object(m, "redis_manager", _FakeRedis()), patch.object(
        m, "postgres_manager", postgres
    ), patch.object(m, "orchestrator", orch), patch.object(
        m, "resolve_forwarded_user", AsyncMock(return_value=("openwebui_user", "readonly"))
    ):
        yield m


# ── transport ───────────────────────────────────────────────────────────────────


async def _post(body: Dict[str, Any]):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import _oai_auth, app

    app.dependency_overrides[_oai_auth] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.post(
                "/v1/chat/completions", json=body, headers={"X-Chat-Id": "caveat656"}
            )
    finally:
        app.dependency_overrides.pop(_oai_auth, None)


def _body(stream: bool, show_status: Optional[bool] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": "ontosage",
        "stream": stream,
        "messages": [{"role": "user", "content": QUESTION}],
    }
    if show_status is not None:
        body["show_status"] = show_status
    return body


def _frames(text: str) -> List[str]:
    """The `data:` payloads of an SSE body, in order."""
    return [line[6:] for line in text.split("\n") if line.startswith("data: ")]


def _chunks(frames: List[str]) -> List[dict]:
    return [json.loads(f) for f in frames if f != "[DONE]"]


def _assemble(frames: List[str]) -> str:
    """Exactly what an OpenAI client renders: every `delta.content`, concatenated."""
    out = []
    for c in _chunks(frames):
        piece = c["choices"][0]["delta"].get("content")
        if piece:
            out.append(piece)
    return "".join(out)


def _strip_panel(text: str) -> str:
    return re.sub(r"<details>.*?</details>\s*", "", text, count=1, flags=re.S)


# ── 1. the stream is well-formed SSE ────────────────────────────────────────────


async def test_the_stream_is_well_formed_sse():
    with _patched(_Orchestrator()):
        resp = await _post(_body(stream=True))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp.text)
    assert frames, "no data: frames at all"
    assert frames[-1] == "[DONE]", "a stream that never says [DONE] leaves a client hanging"
    chunks = _chunks(frames)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    for c in chunks:
        assert c["object"] == "chat.completion.chunk"
        assert set(c["choices"][0]["delta"]) <= {"role", "content"}, c
    stops = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert len(stops) == 1 and stops[-1] is chunks[-1], "finish_reason must land once, last"


# ── 2. the two paths deliver the same answer ────────────────────────────────────


async def test_the_assembled_stream_equals_the_unstreamed_answer():
    """The claim every quality number in this project rests on."""
    with _patched(_Orchestrator()):
        streamed = _assemble(_frames((await _post(_body(stream=True))).text))
        unstreamed = (await _post(_body(stream=False))).json()["choices"][0]["message"]["content"]
    assert _strip_panel(streamed) == unstreamed


async def test_with_the_panel_off_the_stream_is_byte_identical():
    """`show_status: false` removes the <details> panel, so no surgery is needed and the
    equality is exact — no regex is standing between the two answers."""
    with _patched(_Orchestrator()):
        streamed = _assemble(_frames((await _post(_body(True, show_status=False))).text))
        unstreamed = (await _post(_body(False))).json()["choices"][0]["message"]["content"]
    assert streamed == unstreamed
    assert "<details>" not in streamed


async def test_the_answer_survives_chunking_at_any_length():
    """The answer is emitted in 200-char slices; a boundary must not eat a character."""
    answer = "".join(chr(ord("a") + (i % 26)) for i in range(1234))
    with _patched(_Orchestrator(answer=answer)):
        streamed = _assemble(_frames((await _post(_body(True, show_status=False))).text))
    assert streamed == answer


# ── 3. the honesty metadata is on both paths ────────────────────────────────────


async def test_the_streamed_final_chunk_carries_the_same_ontosage_fields_as_the_body():
    """`ontosage_llm_degraded` is how a grader learns not to score an outage's apology, and
    `ontosage_evidence_record` is the turn's statement of what it rests on. A field that
    rides only the non-streamed body is a field real users' turns never carry."""
    with _patched(_Orchestrator()):
        body = (await _post(_body(False))).json()
        frames = _frames((await _post(_body(True))).text)
    final = _chunks(frames)[-1]
    body_fields = {k for k in body if k.startswith("ontosage_")}
    stream_fields = {k for k in final if k.startswith("ontosage_")}
    assert (
        body_fields <= stream_fields
    ), f"only on the non-streamed body: {body_fields - stream_fields}"


async def test_the_streamed_evidence_record_is_the_same_record():
    with _patched(_Orchestrator()):
        body = (await _post(_body(False))).json()
        frames = _frames((await _post(_body(True))).text)
    assert _chunks(frames)[-1]["ontosage_evidence_record"] == body["ontosage_evidence_record"]
    assert body["ontosage_evidence_record"] == EVIDENCE


# ── 4. a failure reaches the reader as a failure ────────────────────────────────


async def test_a_workflow_error_is_not_streamed_as_the_users_own_question():
    """THE defect this file was written for.

    `stream_execute` catches a workflow exception and yields `{"error": ..., "state": ...}`.
    The state is the PRE-graph one, whose last message is the user's own question, appended
    by main.py before the graph ran. Reading `messages[-1]` therefore streams the question
    back as the assistant's answer, at 200, with `finish_reason: "stop"`.
    """
    with _patched(_FailingOrchestrator()):
        streamed = _strip_panel(_assemble(_frames((await _post(_body(True))).text)))
    assert (
        QUESTION not in streamed
    ), "the streaming branch echoed the user's own question back as the answer: " + repr(streamed)


async def test_a_workflow_error_reads_the_same_on_both_paths():
    with _patched(_FailingOrchestrator()):
        streamed = _strip_panel(_assemble(_frames((await _post(_body(True))).text)))
        unstreamed = (await _post(_body(False))).json()["choices"][0]["message"]["content"]
    assert streamed == unstreamed


async def test_a_generator_level_exception_is_surfaced_not_truncated():
    """If the generator raises, an SSE body simply stops: no error, no `[DONE]`, and the
    client renders whatever arrived as a complete answer."""
    with _patched(_ExplodingOrchestrator()):
        resp = await _post(_body(True))
    frames = _frames(resp.text)
    assert frames, "the stream produced nothing at all"
    assert frames[-1] == "[DONE]", "the stream was truncated with no terminator"
    assert any(
        c["choices"][0]["finish_reason"] == "stop" for c in _chunks(frames)
    ), "no finish_reason: a client cannot tell this apart from a dropped connection"


async def test_a_persistence_failure_does_not_swallow_the_answer():
    """The Postgres write sits between the assembled answer and the first content chunk.
    An exception there costs the reader the whole answer, not just the transcript."""
    with _patched(_Orchestrator(), postgres=_AngryPostgres()):
        frames = _frames((await _post(_body(True, show_status=False))).text)
    assert _assemble(frames) == ANSWER
    assert frames[-1] == "[DONE]"


# ── 5. neither branch may grow a guard the other lacks ──────────────────────────


async def test_no_branch_re_derives_the_answer():
    """Both branches must read the answer out of the state the graph returned, so whatever
    `_response_node` decided — including a publication-gate withholding — is what ships.
    A branch that rebuilt the text from `intermediate_results` would bypass every guard."""
    withheld = "I can't give you that figure: it did not pass verification."
    with _patched(_Orchestrator(answer=withheld)):
        streamed = _strip_panel(_assemble(_frames((await _post(_body(True))).text)))
        unstreamed = (await _post(_body(False))).json()["choices"][0]["message"]["content"]
    assert streamed == unstreamed == withheld


def test_main_py_applies_no_gate_of_its_own():
    """The honesty guards live in `_response_node`, inside the graph, so both branches get
    them. This fails the moment one is added to `main.py`, where it could only be wired into
    one branch — which is how a guard becomes something users never get."""
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    for module in (
        "publication_gate",
        "answer_relevance_gate",
        "claim_binder",
    ):
        assert module not in src, (
            f"{module} is referenced in main.py. If it now gates an answer there, wire it "
            "into BOTH the streaming and non-streaming branches and update this test."
        )


def test_every_streaming_endpoint_reads_the_last_ASSISTANT_message():
    """BUG-1211 is a SHAPE, not one endpoint, and it survived its own fix in a sibling.

    The defect: `main.py` appends the user turn to `state.messages` BEFORE the graph, and
    `stream_execute` reports failure as ``{"error": ..., "state": <pre-graph state>}``. So any
    endpoint that both (a) drives `stream_execute` and (b) ships `messages[-1]` will hand the
    user their own question back as the assistant's answer — HTTP 200, `finish_reason: "stop"`,
    nothing saying it failed.

    `/v1/chat/completions` was found and fixed. `/chat/stream` does exactly the same two things
    and was not, because the defect had been pinned on the endpoint where it was noticed rather
    than on the condition that produces it. This test pins the CONDITION: every site that ships
    an answer after a `stream_execute` must go through `_assistant_answer`.

    `/chat` is deliberately not covered — it calls `execute()`, which appends an assistant
    message on failure, so `messages[-1]` there IS the assistant's answer.
    """
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if not seg.replace(" ", "").endswith("messages[-1]"):
            continue
        # only the ones whose value is assigned to something that ships as an answer
        parent_src = seg
        line = node.lineno
        context = "\n".join(src.splitlines()[max(0, line - 3) : line + 2])
        if "assistant_message" in context:
            offenders.append((line, parent_src))

    assert not offenders, (
        "these ship `messages[-1]` as the answer; after a stream_execute failure that is the "
        f"USER'S OWN QUESTION (BUG-1211). Use `_assistant_answer`: {offenders}"
    )
