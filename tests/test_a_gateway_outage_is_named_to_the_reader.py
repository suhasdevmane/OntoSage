"""CAVEAT-1459: a hosted-gateway outage must reach the reader as what it is.

During the compound-question captures the gateway stopped answering for seconds at a time and
the orchestrator logged "[hosted] gateway unreachable (ReadTimeout); refusing without queueing".
Turns in flight became "I wasn't able to generate an answer just now" and "I found N records ...
but I couldn't summarise them ... just now" -- true, and indistinguishable from a building that
cannot answer. CAVEAT-1409 already words the outage plainly when ``model_is_unavailable()`` is
True, but that read only the circuit breaker, and the gateway's own refusal never tripped it.
"""

import sys

import httpx
import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent
from orchestrator.llm_manager import GatewayUnreachable, LLMManager
from orchestrator.services import circuit_breaker as cb

pytestmark = pytest.mark.unit

V1_FALLBACK_ONE_ROW = (
    "I found **1 records** that bear on this, but I couldn't summarise them against your "
    "question just now, so I haven't drawn a conclusion from them. The records are:\n"
    "- Handover A\n\nAsk about one of them, or narrow the question, and I can answer from its "
    "detail."
)
ONE_ROW = [{"label": {"type": "literal", "value": "Handover A"}}]


@pytest.fixture(autouse=True)
def _model_reachable_after():
    cb.note_model_reachable()
    yield
    cb.note_model_reachable()


def test_a_reported_outage_makes_the_model_unavailable_until_it_is_cleared():
    assert not cb.model_is_unavailable()
    cb.note_model_unreachable(30)
    assert cb.model_is_unavailable()
    cb.note_model_reachable()
    assert not cb.model_is_unavailable()


def test_an_outage_window_expires_on_its_own(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cb.time, "monotonic", lambda: now[0])
    cb.note_model_unreachable(20)
    now[0] += 19.9
    assert cb.model_is_unavailable()
    now[0] += 0.2
    assert not cb.model_is_unavailable()


async def test_a_failed_gateway_probe_reports_the_outage(monkeypatch):
    class _TimesOut:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            raise httpx.ReadTimeout("")

    monkeypatch.setattr(httpx, "AsyncClient", _TimesOut)
    mgr = LLMManager.__new__(LLMManager)
    mgr.config = {"base_url": "http://gateway.invalid/v1", "api_key": ""}
    with pytest.raises(GatewayUnreachable):
        await mgr._probe_hosted_gateway()
    assert cb.model_is_unavailable()


def test_the_register_fallback_is_unchanged_when_the_model_is_up():
    # Word for word what v1 said: the evaluation's provider-failure marker matches this text.
    assert SPARQLAgent._register_fallback(ONE_ROW) == V1_FALLBACK_ONE_ROW


def test_the_register_fallback_says_why_when_the_model_is_down():
    cb.note_model_unreachable(30)
    out = SPARQLAgent._register_fallback(ONE_ROW)
    assert "couldn't summarise them against your question just now" in out
    assert "language model that writes the summary is not responding" in out
    assert "not a gap in the building's records" in out


async def test_a_call_in_a_fresh_outage_waits_the_window_out_once_and_proceeds(monkeypatch):
    """Live, 2026-10-08: a compile made in the second of a gateway blip failed at once and the
    asker was told to rephrase. One refusal window is now waited out before giving up."""
    lm_mod = sys.modules[LLMManager.__module__]  # the module, not the instance it re-exports

    mgr = LLMManager.__new__(LLMManager)
    calls = {"probe": 0}
    slept = []

    async def probe():
        calls["probe"] += 1
        if calls["probe"] == 1:
            mgr._gateway_down_since = mgr._gateway_down_since or lm_mod.time.monotonic()
            mgr._gateway_down_until = lm_mod.time.monotonic() + 5.0
            raise GatewayUnreachable("ReadTimeout")

    async def no_sleep(seconds):
        slept.append(seconds)

    mgr._gateway_down_since = None
    monkeypatch.setattr(mgr, "_probe_hosted_gateway", probe)
    monkeypatch.setattr(lm_mod.asyncio, "sleep", no_sleep)
    await mgr._await_hosted_gateway()
    assert calls["probe"] == 2 and len(slept) == 1 and 5.0 <= slept[0] <= 6.5


async def test_a_sustained_outage_still_fails_fast(monkeypatch):
    lm_mod = sys.modules[LLMManager.__module__]  # the module, not the instance it re-exports

    mgr = LLMManager.__new__(LLMManager)
    mgr._gateway_down_since = lm_mod.time.monotonic() - (lm_mod.HOSTED_BLIP_S + 5)
    slept = []

    async def probe():
        raise GatewayUnreachable("ReadTimeout")

    async def no_sleep(seconds):  # pragma: no cover - must not be called
        slept.append(seconds)

    monkeypatch.setattr(mgr, "_probe_hosted_gateway", probe)
    monkeypatch.setattr(lm_mod.asyncio, "sleep", no_sleep)
    with pytest.raises(GatewayUnreachable):
        await mgr._await_hosted_gateway()
    assert slept == []
