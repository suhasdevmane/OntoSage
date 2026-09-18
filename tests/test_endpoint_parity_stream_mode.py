# -*- coding: utf-8 -*-
"""CAVEAT-656: the streamed /v1 path Open WebUI uses is compared with the unstreamed one.

Offline throughout. The streaming CLIENT is `scripts/ask_questions.py`'s `_ask_v1_stream`,
reused by the parity harness rather than rewritten, so these tests feed that client RECORDED
chunk streams through a fake `requests.post` and check what it reassembles:

* a hand-recorded fixture in the exact framing `/v1/chat/completions` emits — role chunk, a
  pipeline-steps `<details>` panel, 200-character content chunks, a `finish_reason: "stop"`
  chunk carrying `ontosage_intent`, then `data: [DONE]`;
* a stream PRODUCED BY THE REAL ENDPOINT (fake workflow, real `main.py` framing), so a change
  to the server's framing that the client cannot reassemble fails here, not on demo day;
* the degenerate streams: empty, HTTP error, a malformed chunk mid-stream.

Then the harness's own logic: the streamed/unstreamed verdict, the rule that a lane is only
compared when both sides report one, `ontosage_intent` read from the unstreamed body, the
cache flush before every ask, and the refusal to run with a forwarded header the reused client
does not send.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load("_parity_stream_tests", "scripts/endpoint_parity_probe.py")
MATCHES = _load("_probe_for_stream_tests", "scripts/regression_probe.py")._matches

ANSWER = (
    "Room 7.42 is at 21.4 °C and CO₂ is 612 ppm. "
    "Both are within the comfort band for an occupied teaching room. " * 6
).strip()


def _chunk(delta: Dict[str, Any], finish=None, **top) -> str:
    payload = {
        "id": "chatcmpl-owui_x:u",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "ontosage",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    payload.update(top)
    return "data: " + json.dumps(payload)


def _recorded_stream(answer: str = ANSWER, intent: str = "sensor_data") -> List[str]:
    """The framing main.py emits, as iter_lines() yields it (blank separators included)."""
    lines = [_chunk({"role": "assistant"}), ""]
    for part in (
        "<details>\n<summary>Pipeline steps</summary>\n\n",
        "- Analyzing your question…\n",
        "- Querying building ontology\n",
        "\n</details>\n\n",
    ):
        lines += [_chunk({"content": part}), ""]
    for i in range(0, len(answer), 200):
        lines += [_chunk({"content": answer[i : i + 200]}), ""]
    lines += [_chunk({}, finish="stop", ontosage_intent=intent), "", "data: [DONE]", ""]
    return lines


class _Resp:
    def __init__(self, lines: List[str], status: int = 200):
        self.status_code = status
        self._lines = lines
        self.text = "\n".join(lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, decode_unicode=False):
        yield from self._lines


def _client_over(lines: List[str], status: int = 200):
    """ask_questions' real client, with `requests.post` answering from recorded lines."""
    import requests

    seen: Dict[str, Any] = {}

    def fake_post(url, json=None, headers=None, timeout=None, stream=False):
        seen.update(url=url, body=json, headers=headers, stream=stream)
        return _Resp(lines, status)

    return fake_post, seen, requests


def _ask_streamed(lines: List[str], status: int = 200, forwarded: str = "a@b.c"):
    fake_post, seen, requests = _client_over(lines, status)
    with patch.object(requests, "post", fake_post):
        res = H.ask_v1_stream(
            [{"role": "user", "content": "q"}], "http://x", "key", "chat1", forwarded, 5
        )
    return res, seen


# ── chunk reassembly, through the REUSED client ─────────────────────────────────


def test_the_harness_reuses_ask_questions_client_rather_than_its_own():
    client = H._stream_client()
    assert client.__name__ == "_ask_v1_stream"
    assert Path(client.__code__.co_filename).name == "ask_questions.py"


def test_a_recorded_stream_reassembles_to_the_answer_without_the_steps_panel():
    res, seen = _ask_streamed(_recorded_stream())
    assert res["status"] == "OK"
    assert res["answer"] == ANSWER
    assert "Pipeline steps" not in res["answer"]
    assert seen["body"]["stream"] is True and seen["stream"] is True
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["headers"]["X-Chat-Id"] == "chat1"
    assert seen["headers"][H.STREAM_CLIENT_HEADER] == "a@b.c"


def test_multibyte_characters_survive_chunk_boundaries():
    answer = "°C₂" * 150  # 450 chars: every 200-char boundary lands inside the run
    res, _ = _ask_streamed(_recorded_stream(answer))
    assert res["answer"] == answer


def test_a_stream_without_the_panel_reassembles_too():
    """show_status=false streams no <details> block."""
    lines = [l for l in _recorded_stream() if "Pipeline steps" not in l]
    lines = [l for l in lines if "Analyzing" not in l and "Querying" not in l]
    lines = [l for l in lines if "</details>" not in l]
    res, _ = _ask_streamed(lines)
    assert res["answer"] == ANSWER


def test_an_empty_stream_is_a_failure_not_an_empty_answer():
    lines = [_chunk({"role": "assistant"}), _chunk({}, finish="stop"), "data: [DONE]"]
    res, _ = _ask_streamed(lines)
    assert res["status"] != "OK" and res["answer"] == ""


def test_an_http_error_is_reported_as_transport():
    res, _ = _ask_streamed(["Internal Server Error"], status=500)
    assert res["status"] == "HTTP 500"


def test_a_malformed_chunk_mid_stream_does_not_lose_the_rest():
    lines = _recorded_stream()
    lines.insert(len(lines) // 2, "data: {not json")
    res, _ = _ask_streamed(lines)
    assert res["answer"] == ANSWER


def test_the_streamed_side_reports_no_lane_to_this_client():
    """The client reads delta.content only. Pinned so that the day it learns to read the final
    chunk's `ontosage_intent`, this fails and lane comparison can be switched on."""
    res, _ = _ask_streamed(_recorded_stream(intent="register"))
    assert res["intent"] is None


# ── the REAL endpoint's framing, reassembled by the client ──────────────────────


async def _server_stream(answer: str, intent: str) -> List[str]:
    """What /v1/chat/completions actually emits, with the workflow faked."""
    from httpx import ASGITransport, AsyncClient

    import orchestrator.main as m
    from shared.models import Message

    class _Redis:
        client = None

        async def load_state(self, cid):
            return None

        async def save_state(self, s):
            return None

    class _Orch:
        async def stream_execute(self, state):
            yield {"dialogue": state}
            state.current_intent = intent
            state.messages.append(
                Message(role="assistant", content=answer, timestamp=datetime.now())
            )
            yield {"response": state}

    m.app.dependency_overrides[m._oai_auth] = lambda: None
    try:
        with patch.object(m, "redis_manager", _Redis()), patch.object(
            m, "postgres_manager", None
        ), patch.object(m, "orchestrator", _Orch()), patch.object(
            m, "resolve_forwarded_user", AsyncMock(return_value=("openwebui_user", "readonly"))
        ):
            async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://t") as c:
                resp = await c.post(
                    "/v1/chat/completions",
                    json={
                        "model": "ontosage",
                        "stream": True,
                        "messages": [{"role": "user", "content": "q"}],
                    },
                )
    finally:
        m.app.dependency_overrides.pop(m._oai_auth, None)
    assert resp.status_code == 200
    return resp.text.split("\n")


async def test_the_client_reassembles_what_the_real_endpoint_frames():
    lines = await _server_stream(ANSWER, "sensor_data")
    res, _ = _ask_streamed(lines)
    assert res["status"] == "OK"
    assert res["answer"] == ANSWER


async def test_the_real_final_chunk_carries_the_lane():
    lines = await _server_stream(ANSWER, "register")
    payloads = [json.loads(l[6:]) for l in lines if l.startswith("data: {")]
    assert H.v1_intent(payloads[-1]) == "register"


# ── the harness's comparison ────────────────────────────────────────────────────


def _res(answer, status="OK", intent=None):
    return {"answer": answer, "status": status, "intent": intent, "seconds": 1.0}


def test_stream_verdict_names_all_four_outcomes():
    assert H.stream_verdict(True, True) == H.STREAM_BOTH_PASS
    assert H.stream_verdict(False, False) == H.STREAM_BOTH_FAIL
    assert H.stream_verdict(True, False) == H.UNSTREAMED_ONLY
    assert H.stream_verdict(False, True) == H.STREAMED_ONLY


def test_a_streamed_answer_that_loses_a_figure_is_divergent():
    case = {"group": "g", "question": "q", "expect": ["612"]}
    row = H.compare_streamed(case, _res("CO2 is 612 ppm"), _res("CO2 is fine"), [], MATCHES)
    assert row["verdict"] == H.UNSTREAMED_ONLY
    assert row["numbers"]["only_chat"] == ["612"]


def test_reworded_but_equally_correct_answers_agree():
    case = {"group": "g", "question": "q", "expect": ["612"]}
    row = H.compare_streamed(
        case, _res("CO2 is 612 ppm."), _res("It reads 612 ppm of CO2."), [], MATCHES
    )
    assert row["verdict"] == H.STREAM_BOTH_PASS and row["same_text"] is False


def test_an_empty_stream_fails_the_streamed_side_on_transport():
    case = {"group": "g", "question": "q", "expect": []}
    row = H.compare_streamed(case, _res("fine"), _res("", status="EMPTY"), [], MATCHES)
    assert row["verdict"] == H.UNSTREAMED_ONLY
    assert row["streamed_why"] == "transport EMPTY"


def test_a_lane_is_not_checked_when_only_one_side_reports_it():
    """Otherwise the unstreamed side is graded on MORE evidence and a wrong lane there reads
    as a stream divergence."""
    case = {"group": "g", "question": "q", "expect": [], "expect_intent": "register"}
    row = H.compare_streamed(case, _res("x", intent="document"), _res("x"), [], MATCHES)
    assert row["verdict"] == H.STREAM_BOTH_PASS
    assert row["lane_checked"] is False and row["unstreamed_intent"] == "document"


def test_a_lane_is_checked_when_both_sides_report_one():
    case = {"group": "g", "question": "q", "expect": [], "expect_intent": "register"}
    row = H.compare_streamed(
        case, _res("x", intent="register"), _res("x", intent="document"), [], MATCHES
    )
    assert row["verdict"] == H.UNSTREAMED_ONLY and row["lane_checked"] is True


def test_the_unstreamed_body_lane_is_read_from_ontosage_intent():
    assert H.v1_intent({"ontosage_intent": "sensor_data"}) == "sensor_data"
    assert H.v1_intent({"ontosage_intent": None}) is None
    assert H.v1_intent({"ontosage_intent": ""}) is None
    assert H.v1_intent({}) is None


def test_the_stream_report_leads_with_divergence_and_the_cache_status():
    case = {"group": "g", "question": "q1", "expect": ["612"], "expect_intent": "x"}
    rows = [
        H.compare_streamed({**case, "question": "agree"}, _res("612"), _res("612"), [], MATCHES),
        H.compare_streamed(case, _res("612"), _res("nothing"), [], MATCHES),
    ]
    text = "\n".join(
        H.stream_report_lines(rows, {"cache_lines": ["> ## WARNING — 1 of 4 FLUSHES FAILED\n"]})
    )
    assert text.index("WARNING") < text.index("| verdict |")
    assert text.index(H.UNSTREAMED_ONLY) < text.index(H.STREAM_BOTH_PASS)
    assert "2 case(s) assert a lane" in text


# ── the cache flush, and the header refusal ─────────────────────────────────────


def test_the_flusher_reports_failures_at_the_top():
    calls: List[str] = []

    def flush(container):
        calls.append(container)
        return {"ok": len(calls) != 2, "error": "no redis" if len(calls) == 2 else ""}

    fresh = H.CacheFlusher(flush, "redis-memory-store")
    for _ in range(3):
        fresh()
    assert calls == ["redis-memory-store"] * 3
    text = "\n".join(fresh.report_lines())
    assert "WARNING" in text and "1 of 3" in text and "no redis" in text


def test_a_disabled_flusher_never_flushes_and_says_so():
    fresh = H.CacheFlusher(lambda c: pytest.fail("flushed"), "r", enabled=False)
    fresh()
    assert "--no-flush" in "\n".join(fresh.report_lines())


def _fake_main_env(monkeypatch, forwarded_header="X-OpenWebUI-User-Email"):
    events: List[str] = []
    probe = SimpleNamespace(
        _matches=MATCHES,
        _active_building=lambda url: "",
        _scalar_from_graph=lambda q, u, r: "0",
        flush_response_cache=lambda c: events.append("flush") or {"ok": True},
        REDIS_CONTAINER="redis-memory-store",
    )
    cap = SimpleNamespace(_login=lambda url: "tok", _active_model=lambda u, t: ("local", "m"))
    replay = SimpleNamespace(
        _env_or_dotenv=lambda k, d: forwarded_header if k == "FORWARDED_USER_HEADER" else d
    )
    mods = {"_regression_probe": probe, "_cap": cap, "_replay": replay}
    monkeypatch.setattr(H, "_load", lambda name, rel: mods[name])
    monkeypatch.setattr(H, "resolve_vocabulary", lambda u, r: None)

    def fake_v1(messages, *a, **k):
        events.append("v1")
        return _res("612", intent="register")

    def fake_stream(messages, *a, **k):
        events.append("stream")
        return _res("612")

    monkeypatch.setattr(H, "ask_v1", fake_v1)
    monkeypatch.setattr(H, "ask_v1_stream", fake_stream)
    monkeypatch.setattr(H, "ask_chat", lambda *a, **k: pytest.fail("/chat asked in --stream"))
    return events


def test_stream_mode_flushes_before_each_of_the_two_asks(tmp_path, monkeypatch):
    events = _fake_main_env(monkeypatch)
    out = tmp_path / "s.md"
    rc = H.main(["--stream", "--sample", "2", "--out", str(out)])
    assert rc == 0
    assert events[:4] == ["flush", "v1", "flush", "stream"]
    assert events.count("flush") == events.count("v1") + events.count("stream")
    assert "Streamed versus unstreamed" in out.read_text(encoding="utf-8")


def test_stream_mode_refuses_a_header_the_reused_client_does_not_send(tmp_path, monkeypatch):
    events = _fake_main_env(monkeypatch, forwarded_header="X-Forwarded-Email")
    assert H.main(["--stream", "--out", str(tmp_path / "s.md")]) == 2
    assert events == []
