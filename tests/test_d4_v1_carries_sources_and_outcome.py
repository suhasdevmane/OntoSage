# -*- coding: utf-8 -*-
"""D4 (QA-trial plan, 2026-10-04): sources, turn_outcome and retrieval_outcome on /v1.

The structured sources array was in the `/chat` envelope and the websocket and in NEITHER
`/v1` branch, while Open WebUI posts to `/v1/chat/completions` — the endpoint real testers
hit. `turn_outcome` and `retrieval_outcome` reached neither endpoint at all, so nothing the
server returned said whether a turn declined (CAVEAT-887).

What these tests pin:

* non-streamed and streamed `/v1` both carry `ontosage_sources`, `ontosage_turn_outcome` and
  `ontosage_retrieval_outcome`, on the SAME extension-field convention as `ontosage_intent`;
* a turn that never classified (the timeout branch, the stream-abort guard) reports the
  fields as null/empty rather than omitting them, so "no outcome" is distinguishable from
  "an older server that never reported one" — the same contract `test_v1_reports_the_lane.py`
  already pins for `ontosage_intent`;
* `retrieval_outcome.from_state` reads the lane that classified a typed absence, even though
  that lane is EXACTLY the one `evidence.assemble.infer_lane` would skip (a typed absence is
  a lane that produced no evidence, by infer_lane's own definition) — the reason this reader
  could not simply reuse that matcher.

Every manager is a fake; nothing reaches Redis, Postgres or a model.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

ANSWER = "No air-pressure sensor is recorded for this room. " * 5


class _FakeRedis:
    client = None

    async def load_state(self, conversation_id: str):
        return None

    async def save_state(self, state) -> None:
        return None

    async def save_message(self, *args, **kwargs) -> None:
        return None


class _FakeOrchestrator:
    def __init__(self, bus: Dict[str, Any]):
        self.bus = bus

    def _finish(self, state):
        from shared.models import Message

        state.current_intent = "sensor_data"
        state.intermediate_results.update(self.bus)
        state.messages.append(Message(role="assistant", content=ANSWER, timestamp=datetime.now()))
        return state

    async def execute(self, state):
        return self._finish(state)

    async def stream_execute(self, state):
        yield {"dialogue": state}
        yield {"response": self._finish(state)}


@contextmanager
def _patched(bus: Dict[str, Any]):
    import orchestrator.main as m

    with patch.object(m, "redis_manager", _FakeRedis()), patch.object(
        m, "postgres_manager", None
    ), patch.object(m, "orchestrator", _FakeOrchestrator(bus)), patch.object(
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
        "messages": [{"role": "user", "content": "Is there an air-pressure sensor in 2.01?"}],
    }


def _frames(text: str) -> List[str]:
    return [line[6:] for line in text.split("\n") if line.startswith("data: ")]


_SOURCES = [{"owner": "sensordb", "kind": "sensor"}]
_TURN_OUTCOME = {"outcome": "ok", "first_pass_ok": True, "retried": [], "lanes": []}
# A typed absence: sparql_result carries retrieval_outcome, and its OWN "results" is empty
# -- exactly the dict evidence.assemble.lane_produced_evidence calls not-evidence, which is
# why infer_lane (used to pick the winning lane for the evidence record) cannot be reused
# here: it would skip the one lane that has something to say.
_RETRIEVAL_OUTCOME = {"outcome": "not_declared", "subject": "an air-pressure sensor in 2.01"}
_BUS = {
    "sources": _SOURCES,
    "turn_outcome": _TURN_OUTCOME,
    "sparql_result": {"success": True, "results": [], "retrieval_outcome": _RETRIEVAL_OUTCOME},
}


async def test_the_non_streamed_body_carries_all_three_fields():
    with _patched(_BUS):
        payload = (await _post(_body(stream=False))).json()
    assert payload["ontosage_sources"] == _SOURCES
    assert payload["ontosage_turn_outcome"] == _TURN_OUTCOME
    assert payload["ontosage_retrieval_outcome"] == _RETRIEVAL_OUTCOME


async def test_a_turn_with_no_typed_absence_reports_no_retrieval_outcome():
    bus = {"sources": [], "turn_outcome": _TURN_OUTCOME, "sql_result": {"success": True}}
    with _patched(bus):
        payload = (await _post(_body(stream=False))).json()
    assert payload["ontosage_retrieval_outcome"] is None


async def test_the_final_streamed_chunk_carries_all_three_fields():
    with _patched(_BUS):
        resp = await _post(_body(stream=True))
    frames = _frames(resp.text)
    chunks = [json.loads(f) for f in frames if f != "[DONE]"]
    final = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert len(final) == 1
    assert final[0]["ontosage_sources"] == _SOURCES
    assert final[0]["ontosage_turn_outcome"] == _TURN_OUTCOME
    assert final[0]["ontosage_retrieval_outcome"] == _RETRIEVAL_OUTCOME


def test_the_timeout_body_carries_the_fields_as_null_not_omitted():
    """Source-pinned, like test_v1_reports_the_lane.py's equivalent for ontosage_intent."""
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    timeout_body = src[src.index('"causes": ["pipeline_timeout"]') :][:900]
    assert '"ontosage_sources": []' in timeout_body
    assert '"ontosage_turn_outcome": None' in timeout_body
    assert '"ontosage_retrieval_outcome": None' in timeout_body


def test_the_stream_abort_guard_carries_the_fields_as_null_not_omitted():
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    guard_body = src[src.index("ontosage_stream_error") - 400 : src.index("ontosage_stream_error")]
    assert '"ontosage_sources": []' in guard_body
    assert '"ontosage_turn_outcome": None' in guard_body
    assert '"ontosage_retrieval_outcome": None' in guard_body


def test_chat_and_websocket_envelopes_also_carry_turn_outcome_and_retrieval_outcome():
    """/chat and the websocket already carried `sources` and `evidence_record`; this pins
    that both now ALSO carry the two new fields, on the unprefixed convention those two
    envelopes already use (no `ontosage_` prefix -- that is a /v1-only convention, since
    `/chat` and the websocket are this project's own endpoints, not an OpenAI-compatible
    surface a client's own fields could collide with)."""
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "main.py").read_text(
        encoding="utf-8"
    )
    assert src.count('"turn_outcome": updated_state.intermediate_results.get("turn_outcome")') == 1
    assert src.count('"turn_outcome": final_state.intermediate_results.get("turn_outcome")') == 1
    # The definition, plus one call per envelope that has a finished state to read: /chat,
    # the websocket, and both /v1 branches -- 1 def + 4 call sites.
    assert src.count("_retrieval_outcome_from_state(") == 5
    assert src.count("def _retrieval_outcome_from_state(") == 1


# ── retrieval_outcome.from_state, directly ──────────────────────────────────────────


def test_from_state_finds_the_outcome_infer_lane_would_skip():
    from orchestrator.services.evidence.assemble import infer_lane
    from orchestrator.services.retrieval_outcome import from_state

    results = {
        "sparql_result": {"success": True, "results": [], "retrieval_outcome": _RETRIEVAL_OUTCOME}
    }
    # The premise this test exists to prove: infer_lane finds NOTHING for this bus (the
    # lane produced no evidence by its own rule), which is exactly why a naive re-use of
    # infer_lane here would never surface the outcome it is asked to report.
    assert infer_lane(results) is None
    assert from_state(results) == _RETRIEVAL_OUTCOME


def test_from_state_is_none_when_nothing_was_classified():
    from orchestrator.services.retrieval_outcome import from_state

    assert from_state({"sql_result": {"success": True, "results": [1, 2]}}) is None
    assert from_state({}) is None
    assert from_state(None) is None


def test_from_state_prefers_the_earlier_lane_in_t02_order():
    from orchestrator.services.evidence.assemble import T02_LANES
    from orchestrator.services.retrieval_outcome import from_state

    later = {"outcome": "no_observations", "subject": "later"}
    results = {
        T02_LANES[0]: {"retrieval_outcome": _RETRIEVAL_OUTCOME},
        T02_LANES[1]: {"retrieval_outcome": later},
    }
    assert from_state(results) == _RETRIEVAL_OUTCOME
