# -*- coding: utf-8 -*-
"""A dead hosted gateway refuses in seconds, not after a queue wait.

The VPN dropped in the middle of a real run and one answer stalled for 45 minutes. The probe
below runs before any queued request is sent, so an unreachable gateway is named at once.
Offline: the probe targets a closed loopback port, which refuses immediately.
"""

import time

import pytest

pytestmark = pytest.mark.unit


def _manager(base_url):
    from orchestrator.llm_manager import LLMManager

    m = LLMManager.__new__(LLMManager)
    m.provider = "hosted"
    m.config = {"base_url": base_url, "api_key": "not-a-real-key"}
    return m


async def test_a_closed_gateway_is_named_in_seconds():
    from orchestrator.llm_manager import GatewayUnreachable

    m = _manager("http://127.0.0.1:9/v1")
    t0 = time.monotonic()
    with pytest.raises(GatewayUnreachable) as exc:
        await m._probe_hosted_gateway()
    assert time.monotonic() - t0 < 5.0
    assert "NameError" not in str(exc.value)
    assert "ConnectError" in str(exc.value) or "Connect" in str(exc.value)


async def test_a_failed_probe_is_cached_so_the_next_call_refuses_without_probing():
    from orchestrator.llm_manager import GatewayUnreachable

    m = _manager("http://127.0.0.1:9/v1")
    with pytest.raises(GatewayUnreachable):
        await m._probe_hosted_gateway()
    t0 = time.monotonic()
    with pytest.raises(GatewayUnreachable):
        await m._probe_hosted_gateway()
    assert time.monotonic() - t0 < 0.5


def test_gateway_unreachable_is_never_retried():
    from orchestrator.llm_manager import GatewayUnreachable, LLMManager

    m = LLMManager.__new__(LLMManager)
    assert m._is_retryable(GatewayUnreachable("down")) is False


def test_hosted_calls_get_two_attempts_not_three():
    from orchestrator.llm_manager import HOSTED_MAX_ATTEMPTS

    assert HOSTED_MAX_ATTEMPTS == 2


def test_the_user_sees_a_named_cause_not_a_generic_connection_message():
    from orchestrator.llm_manager import GatewayUnreachable
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    text = WorkflowOrchestrator._user_friendly_error(GatewayUnreachable("refused"))
    assert "not reachable" in text
    assert "VPN" in text
    assert "backend services" not in text


def test_the_gate_counts_a_deadline_apology_as_no_answer():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "regression_answerability",
        Path(__file__).resolve().parents[1] / "scripts" / "regression_answerability.py",
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert gate.classify("Your request took too long to process. Please try a simpler question.") == "timeout"
    assert gate.classify("Floor 3 averaged 21.4 °C over the last hour.") == "answered"
