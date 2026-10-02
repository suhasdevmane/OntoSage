# -*- coding: utf-8 -*-
"""The intent-decision cache key must change when the routing contract's SOURCE changes.

CAVEAT-1413, 2026-10-02. `decision_cache_key` already carried a contract fingerprint -- of the
rules' NAMES and ORDER. A rule's body and the keyword list it read changed, no rule was added or
reordered, and every cached decision stayed valid for its hour across two restarts: a routing
fix that `apply_contract` provably applied offline was never seen live ("Cache hit for intent
detection"). The fingerprint now covers the module's source, so editing a rule retires the
decisions it produced the moment the process restarts.
"""

import pytest

from orchestrator.agents import dialogue_agent as da

pytestmark = pytest.mark.unit


def test_the_fingerprint_reads_the_contracts_source(monkeypatch):
    import inspect

    src = inspect.getsource(da._routing_contract_fingerprint)
    assert "getsource(_rc)" in src, "the fingerprint must hash the contract's SOURCE, not names"


def test_a_changed_rule_body_changes_the_key(monkeypatch):
    import inspect

    from orchestrator.services import routing_contract as rc

    monkeypatch.setattr(da, "_CONTRACT_FP", None)
    before = da.decision_cache_key("what is the function of your building?", "b", "general")
    real = inspect.getsource

    def _patched(obj):
        text = real(obj)
        return text + "\n# a rule body changed\n" if obj is rc else text

    monkeypatch.setattr(da, "_CONTRACT_FP", None)
    monkeypatch.setattr(inspect, "getsource", _patched)
    after = da.decision_cache_key("what is the function of your building?", "b", "general")
    assert before != after


def test_the_same_contract_gives_the_same_key(monkeypatch):
    monkeypatch.setattr(da, "_CONTRACT_FP", None)
    a = da.decision_cache_key("Is the lift working?", "b", "general")
    monkeypatch.setattr(da, "_CONTRACT_FP", None)
    b = da.decision_cache_key("Is the lift working?", "b", "general")
    assert a == b
