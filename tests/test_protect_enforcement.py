# -*- coding: utf-8 -*-
"""V5-T39: PROTECT enforcement — shadow/on modes, chokepoint block, provenance."""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services.privacy import enforcement
from orchestrator.services.privacy.policy_engine import (
    Policy,
    PolicyEngine,
    _parse_tiers,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/tb#"


def _inject_engine(monkeypatch):
    """Install a loaded engine as the process singleton (no graph, no settings)."""
    eng = PolicyEngine("tb", NS, sparql_exec=None)
    eng.set_policies(
        [
            Policy(iri=f"{NS}p_inf", role="*", inference_class="individual_presence:deny"),
            Policy(iri=f"{NS}p_admin", role="admin", tiers=[(0.0, 1.0)]),
            Policy(
                iri=f"{NS}p_occ",
                role="occupant",
                scope_spaces="any",
                min_sensors=14,
                min_spaces=7,
                tiers=_parse_tiers("60:300,10080:3600"),
            ),
        ]
    )
    monkeypatch.setattr(enforcement, "_engine", eng)
    from shared.config import settings

    monkeypatch.setattr(enforcement, "_engine_building", settings.BUILDING_ID)
    return eng


def _mode(monkeypatch, mode: str):
    from shared.config import settings

    monkeypatch.setattr(settings, "PROTECT_ENFORCE", mode, raising=False)


def test_mode_parsing(monkeypatch):
    for raw, expected in (("off", "off"), ("SHADOW", "shadow"), ("on", "on"), ("bogus", "shadow")):
        _mode(monkeypatch, raw)
        assert enforcement.enforcement_mode() == expected


def test_off_mode_never_consults(monkeypatch):
    _inject_engine(monkeypatch)
    _mode(monkeypatch, "off")
    v = asyncio.run(enforcement.consult("sql", "occupant", modality="occupancy", n_sensors=1))
    assert v is None


def test_shadow_logs_but_never_blocks(monkeypatch):
    _inject_engine(monkeypatch)
    _mode(monkeypatch, "shadow")
    v = asyncio.run(enforcement.consult("sql", "nobody_role", modality="occupancy", n_sensors=1))
    assert v is not None and v.decision == "deny"
    assert enforcement.should_block(v) is False  # shadow NEVER blocks


def test_on_mode_blocks_denials(monkeypatch):
    _inject_engine(monkeypatch)
    _mode(monkeypatch, "on")
    v = asyncio.run(enforcement.consult("sql", "nobody_role"))
    assert enforcement.should_block(v) is True
    payload = enforcement.refusal_payload(v, "sql", "occupancy per office right now")
    assert payload["success"] is False and payload["results"]["data"] == []
    text = payload["formatted_response"]
    assert "can't answer" in text  # states the refusal plainly
    assert "You can instead:" in text  # V5-T41: offers reformulations
    assert text.count("- ") >= 1


def test_k_floor_applies_only_to_presence_adjacent_modalities(monkeypatch):
    _inject_engine(monkeypatch)
    _mode(monkeypatch, "shadow")
    # occupancy with 1 sensor → the k-floor bites
    v_occ = asyncio.run(enforcement.consult("sql", "occupant", modality="occupancy", n_sensors=1))
    assert v_occ.decision == "restrict" and "≥14 sensors" in v_occ.reason
    # temperature with 1 sensor → no k-floor (identifies nobody)
    v_temp = asyncio.run(
        enforcement.consult("sql", "occupant", modality="temperature", n_sensors=1)
    )
    assert "≥14 sensors" not in (v_temp.reason or "")


def test_inference_denial_flows_through_consult(monkeypatch):
    _inject_engine(monkeypatch)
    _mode(monkeypatch, "on")
    v = asyncio.run(
        enforcement.consult(
            "sql", "admin", inference_class="individual_presence", modality="occupancy"
        )
    )
    assert v.decision == "deny" and enforcement.should_block(v)


# ── the chokepoint invariant: a denied query NEVER touches the database ──────


class _RecordingSQLAgent:
    def __init__(self):
        self.calls = []

    async def fetch_data_for_uuids(self, *a, **k):
        self.calls.append(a)
        return {"success": True, "results": {"data": []}}


def test_denied_sql_fetch_never_reaches_the_adapter(monkeypatch):
    """Enforce=on + deny → the SQL node returns the refusal with ZERO fetches."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator
    from shared.models import ConversationState, Message

    _inject_engine(monkeypatch)
    _mode(monkeypatch, "on")

    class _Stub:
        sql_agent = _RecordingSQLAgent()

        def _build_sensor_metadata_from_bindings(self, bindings):
            return {}

        def _infer_query_kind(self, message):
            return "occupancy"

    state = ConversationState(
        conversation_id="t39",
        user_message="occupancy in RM001?",
        messages=[Message(role="user", content="occupancy in RM001?")],
    )
    state.analytics_required = True
    state.intermediate_results = {
        "user_role": "nobody_role",  # no policy → deny
        "sparql_result": {
            "success": True,
            "results": {
                "results": {
                    "bindings": [{"uuid": {"value": "11111111-2222-4333-8444-555555555555"}}]
                }
            },
        },
    }
    stub = _Stub()
    out = asyncio.run(WorkflowOrchestrator._sql_node(stub, state))
    assert stub.sql_agent.calls == [], "denied query must never touch the adapter"
    sql_result = out.intermediate_results["sql_result"]
    assert sql_result["success"] is False and sql_result["denied_by_policy"] == ""
    assert "can't answer" in sql_result["formatted_response"]
    assert "You can instead:" in sql_result["formatted_response"]
    assert out.intermediate_results["applied_policies"]


def test_shadow_sql_fetch_proceeds_unchanged(monkeypatch):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator
    from shared.models import ConversationState, Message

    _inject_engine(monkeypatch)
    _mode(monkeypatch, "shadow")

    class _Stub:
        sql_agent = _RecordingSQLAgent()
        smart_cache = None

        def _build_sensor_metadata_from_bindings(self, bindings):
            return {}

        def _infer_query_kind(self, message):
            return "occupancy"

    state = ConversationState(
        conversation_id="t39b",
        user_message="occupancy in RM001?",
        messages=[Message(role="user", content="occupancy in RM001?")],
    )
    state.analytics_required = True
    state.intermediate_results = {
        "user_role": "nobody_role",
        "sparql_result": {
            "success": True,
            "results": {
                "results": {
                    "bindings": [{"uuid": {"value": "11111111-2222-4333-8444-555555555555"}}]
                }
            },
        },
    }
    stub = _Stub()
    asyncio.run(WorkflowOrchestrator._sql_node(stub, state))
    assert len(stub.sql_agent.calls) == 1, "shadow mode must not change behaviour"


def test_dossier_carries_applied_policies_and_survives_guard():
    from orchestrator.services.deliberation.candidates import CoverageLedger
    from orchestrator.services.deliberation.clarify_policy import ClarifyDecision
    from orchestrator.services.deliberation.cqir import (
        CQIR,
        Constraint,
        DecisionKind,
        Direction,
    )
    from orchestrator.services.deliberation.dossier import (
        build_dossier,
        numeric_guard,
        render_answer,
    )
    from orchestrator.services.deliberation.plan_executor import ExecutionOutcome
    from orchestrator.services.deliberation.scorer import ScoreResult

    ir = CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
    )
    from orchestrator.services.deliberation.scorer import ScoredCandidate

    ranked = [ScoredCandidate(space_iri="s#A", label="A", floor="f0", total=1.0, rank=1)]
    outcome = ExecutionOutcome(
        score=ScoreResult(ranked=ranked, excluded=[], tie_break_rule=""),
        ledger=CoverageLedger(),
        candidates=[],
    )
    dossier = build_dossier(
        ir,
        ClarifyDecision(action="proceed"),
        outcome,
        "tb",
        applied_policies=["p_occ (restrict: resolution clamped to 300s for data 30 min old)"],
    )
    prose = render_answer(dossier)
    assert "Privacy:" in prose and "clamped to 300s" in prose
    assert numeric_guard(prose, dossier) == []
