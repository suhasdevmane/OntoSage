"""
Phase 4 tests — locked-capability gate + node.

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services.datasource_registry import DataSourceRegistry
from orchestrator.workflow import _orchestrator as _wo
from orchestrator.workflow._orchestrator import WorkflowOrchestrator
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

# Patch WHERE IT IS USED (lesson #159). `_orchestrator` captured `settings` at import time;
# `tests/test_strict_secrets.py` reloads `shared.config` and rebinds that module attribute,
# so a module-level `from shared.config import settings` here would be patching an object
# `_check_locked_capability` no longer reads. `_wo.settings` is that object by construction.
#
# The flag also has TWO real values depending on an untracked file: `shared/config.py`
# defaults DATASOURCE_TOGGLES_ENABLED to False (what CI and a fresh clone see) while a
# developer's `.env` sets it true. Measured both ways: with the patch neutered, the `True`
# tests fail on the default and the `False` test fails under `.env` — so in either state
# some of these pass for the ambient value rather than the patched one.


MANIFEST = textwrap.dedent(
    """
    datasources:
      - id: occupancy
        label: "Occupancy Sensing"
        modality: occupancy
        kind: timeseries
        provenance_system: "Occupancy Sensing System"
        color: "#3B82F6"
        ts_table: occupancy_data
        unlocks: [desk_availability, occupancy_peak_hours]
        match_keywords: ["free desk", "how busy", "occupancy"]
      - id: energy
        label: "Energy Metering"
        modality: energy
        kind: timeseries
        provenance_system: "Energy Metering System"
        color: "#F97316"
        ts_table: energy_data
        unlocks: [energy_peak_hours]
        match_keywords: ["peak hours", "energy consumption"]
    """
)


class _Mgr:
    def __init__(self, enabled):
        self._en = set(enabled)

    def is_enabled(self, sid):
        return sid in self._en


def _reg(tmp_path: Path) -> DataSourceRegistry:
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    r = DataSourceRegistry("bldg1", input_root=tmp_path)
    r.load()
    return r


def _state(query: str, intent: str = "sensor_data") -> ConversationState:
    # The gate now only fires for genuine live-data intents (CAVEAT-017 fix), so these
    # data-question tests carry a data intent; pass intent=... to exercise other cases.
    st = ConversationState(
        conversation_id="t",
        user_message=query,
        messages=[Message(role="user", content=query)],
    )
    st.current_intent = intent
    return st


def _fake_self(reg, mgr):
    return SimpleNamespace(datasource_registry=reg, datasource_manager=mgr)


# ── Gate ──────────────────────────────────────────────────────────────────────


def test_gate_fires_for_disabled_source(tmp_path, monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    src = WorkflowOrchestrator._check_locked_capability(fs, _state("where is a free desk?"))
    assert src == "occupancy"


def test_gate_silent_when_source_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=["occupancy"]))
    src = WorkflowOrchestrator._check_locked_capability(fs, _state("where is a free desk?"))
    assert src is None


def test_gate_silent_when_flag_off(tmp_path, monkeypatch):
    """The FLAG is what silences it — proved by flipping it, not by asserting None once.

    `assert src is None` against a flag that is already False (the `shared/config.py`
    default, which is what CI sees) passes without the gate ever being reached. The same
    fixture is therefore run both ways here: the only difference between the two calls is
    the flag, so a gate that stopped reading it cannot pass this.
    """
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    st = _state("where is a free desk?")

    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    assert WorkflowOrchestrator._check_locked_capability(fs, st) == "occupancy"

    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", False)
    assert WorkflowOrchestrator._check_locked_capability(fs, st) is None


def test_gate_silent_without_keyword(tmp_path, monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    src = WorkflowOrchestrator._check_locked_capability(fs, _state("what is the room temperature?"))
    assert src is None


def test_gate_silent_for_non_data_intent(tmp_path, monkeypatch):
    # CAVEAT-017 fix: a disabled-source keyword inside an informational / how-to / report
    # question (non-data intent) must NOT be intercepted — it passes through to the graph /
    # documents / report_intake, not the "enable X" decline.
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    st = _state("how do I report an occupancy complaint?", intent="capability")
    assert WorkflowOrchestrator._check_locked_capability(fs, st) is None


def test_gate_silent_without_registry(monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(None, None)
    assert WorkflowOrchestrator._check_locked_capability(fs, _state("free desk?")) is None


def test_gate_picks_matching_disabled_source(tmp_path, monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    src = WorkflowOrchestrator._check_locked_capability(fs, _state("what are the peak hours?"))
    assert src == "energy"


def test_gate_forbids_source_by_role(tmp_path, monkeypatch):
    # occupancy ENABLED, but the user's role is not allowed → forbidden decline
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    from orchestrator.services import admin_config

    monkeypatch.setattr(admin_config, "read_role_access", lambda: {"readonly": []})
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=["occupancy"]))
    st = _state("where is a free desk?")
    st.intermediate_results["user_role"] = "readonly"
    src = WorkflowOrchestrator._check_locked_capability(fs, st)
    assert src == "occupancy"
    assert st.intermediate_results["locked_reason"] == "forbidden"


def test_gate_allows_source_for_permitted_role(tmp_path, monkeypatch):
    monkeypatch.setattr(_wo.settings, "DATASOURCE_TOGGLES_ENABLED", True)
    from orchestrator.services import admin_config

    monkeypatch.setattr(admin_config, "read_role_access", lambda: {"readonly": ["occupancy"]})
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=["occupancy"]))
    st = _state("where is a free desk?")
    st.intermediate_results["user_role"] = "readonly"
    assert WorkflowOrchestrator._check_locked_capability(fs, st) is None


# ── Node ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_locked_node_builds_unlock_message(tmp_path):
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    st = _state("free desk?")
    st.intermediate_results["locked_source"] = "occupancy"
    out = await WorkflowOrchestrator._locked_capability_node(fs, st)
    msg = out.intermediate_results["dialogue_response"]
    assert "Occupancy Sensing System" in msg
    assert "switched" in msg and "off" in msg
    assert "desk availability" in msg  # unlock tag prettified
    # The unlock message used to end with a provenance caption. Every reading in this
    # deployment is placeholder data for the building's own feed, replaced wholesale at
    # connection time, so the caption described the STAGE and not the source (user
    # decision, 2026-09-16). What the message must still do is name the source that is
    # off and what enabling it unlocks — asserted above.
    assert "simulated" not in msg.lower()
    assert "synthetic" not in msg.lower()


@pytest.mark.asyncio
async def test_locked_node_unknown_source_graceful(tmp_path):
    fs = _fake_self(_reg(tmp_path), _Mgr(enabled=[]))
    st = _state("x")
    st.intermediate_results["locked_source"] = "nonexistent"
    out = await WorkflowOrchestrator._locked_capability_node(fs, st)
    assert "dialogue_response" in out.intermediate_results


# ── Graph wiring ────────────────────────────────────────────────────────────────


def test_locked_capability_node_registered_in_graph():
    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    graph = inst._build_graph()
    assert "locked_capability" in graph.nodes
