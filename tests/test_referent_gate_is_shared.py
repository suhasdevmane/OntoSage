# -*- coding: utf-8 -*-
"""The existence check is ONE implementation, callable from any lane (BUG-399).

It lived inline inside the sparql node, so every lane that does not pass through sparql had
no existence check at all. Measured on the events lane: "are there any vibration anomalies on
floor 9" was answered with 500 episodes from floors 3, 4 and 5 — a floor this building does
not have.

Copying the block into each lane would make the third copy the one that drifts. A shared
function is the reason the next lane can be covered by a single call rather than by new
logic, and these tests pin that property rather than the events lane specifically.

It FAILS OPEN. A check that could not run — GraphDB down, resolver raising — passes the
question through, because refusing a legitimate question on an infrastructure fault is the
worse trade: the lane's own guards still apply downstream.
"""

import inspect

import pytest

from orchestrator.workflow._orchestrator import apply_referent_gate

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, **results):
        self.intermediate_results = results


class _Resolution:
    def __init__(self, status, referent="floor 9", message="no"):
        self.status, self.referent, self.message = status, referent, message


def _patch_resolver(monkeypatch, resolution=None, raises=None):
    from orchestrator.services import referent_resolver as rr

    class _Fake:
        def __init__(self, _exec):
            pass

        async def resolve(self, **_kw):
            if raises:
                raise raises
            return resolution

    monkeypatch.setattr(rr, "ReferentResolver", _Fake)


@pytest.mark.asyncio
async def test_a_missing_referent_is_refused(monkeypatch):
    from orchestrator.services.referent_resolver import NOT_FOUND

    _patch_resolver(monkeypatch, _Resolution(NOT_FOUND))
    state = _State(entities=[])
    assert await apply_referent_gate(state, "anomalies on floor 9", None, lane="events") is True


@pytest.mark.asyncio
async def test_the_refusal_names_the_gate_so_it_is_attributable(monkeypatch):
    """Without this the regression gate reads a deliberate refusal as silent breakage."""
    from orchestrator.services.referent_resolver import NOT_FOUND

    _patch_resolver(monkeypatch, _Resolution(NOT_FOUND))
    state = _State(entities=[])
    await apply_referent_gate(state, "anomalies on floor 9", None, lane="events")
    evidence = state.intermediate_results["evidence"]
    assert evidence["status"] == "not_assessable"
    assert "referent_existence" in evidence["gates_applied"]
    assert "floor 9" in evidence["not_assessable_reason"]


@pytest.mark.asyncio
async def test_a_resolvable_referent_passes_through(monkeypatch):
    from orchestrator.services.referent_resolver import RESOLVED

    _patch_resolver(monkeypatch, _Resolution(RESOLVED, referent="floor 4"))
    state = _State(entities=[])
    assert await apply_referent_gate(state, "anomalies on floor 4", None, lane="events") is False
    assert "evidence" not in state.intermediate_results


@pytest.mark.asyncio
async def test_a_question_naming_nothing_passes_through(monkeypatch):
    from orchestrator.services.referent_resolver import NO_REFERENT

    _patch_resolver(monkeypatch, _Resolution(NO_REFERENT, referent=""))
    state = _State(entities=[])
    assert await apply_referent_gate(state, "any anomalies this week", None, lane="events") is False


@pytest.mark.asyncio
async def test_a_check_that_could_not_run_fails_open(monkeypatch):
    """SKIPPED means GraphDB was unreachable, not that the referent is absent."""
    from orchestrator.services.referent_resolver import SKIPPED

    _patch_resolver(monkeypatch, _Resolution(SKIPPED))
    state = _State(entities=[])
    assert await apply_referent_gate(state, "anomalies on floor 9", None, lane="events") is False


@pytest.mark.asyncio
async def test_a_resolver_that_raises_fails_open(monkeypatch):
    """An existence check that errors must not take the lane down with it."""
    _patch_resolver(monkeypatch, raises=RuntimeError("graphdb unreachable"))
    state = _State(entities=[])
    assert await apply_referent_gate(state, "anomalies on floor 9", None, lane="events") is False


def test_the_events_lane_calls_the_shared_gate():
    """Pinned against the source: this lane demonstrably needed it."""
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator.WorkflowOrchestrator._events_node)
    assert "apply_referent_gate" in src


def test_no_lane_reimplements_the_gate():
    """One implementation. A second copy is the one that drifts.

    ReferentResolver(...).resolve is called in exactly two places: the shared helper, and
    the sparql node whose long-standing behaviour is deliberately left alone. A third call
    site means a lane grew its own copy instead of calling this one.
    """
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert src.count("ReferentResolver(") <= 2, (
        "a lane is constructing its own ReferentResolver rather than calling "
        "apply_referent_gate — that is how the copies drift apart"
    )
