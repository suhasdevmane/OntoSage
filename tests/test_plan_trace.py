# -*- coding: utf-8 -*-
"""V4-T33: unified plan trace — reflex and deliberative answers share one formalism."""

from pathlib import Path

import pytest

from orchestrator.workflow._orchestrator import build_plan_trace

pytestmark = pytest.mark.unit


def test_reflex_trace_wraps_route_decision_and_executed_stages():
    """BUG-510 — this fixture used `sparql_results` and `sql_data`.

    Neither key exists. The lanes write `sparql_result` and `sql_result`. So this test
    passed against a `_TRACE_STAGE_MARKERS` tuple that named the same non-existent keys,
    and certified a trace the real pipeline could never produce: on an actual turn the
    fallback found nothing and the three principal data stages were absent from every
    trace it built.

    The test was written from the same wrong list as the code it tested, which is why
    neither caught the other. `.claude/rules/agent-patterns.md` already recorded those two
    strings as "names that appear nowhere in the pipeline" on 2026-08-22; this fixture and
    `_TRACE_STAGE_MARKERS` both kept them for another three weeks.
    """
    results = {
        "route_decision": {
            "intent_from_dialogue": "sensor_data",
            "intent_after_overrides": "sensor_data",
            "final_node": "sparql",
            "decision_source": "registry",
            "overrides_applied": [],
        },
        "sparql_result": [{"uuid": "u1"}],
        "sql_result": {"rows": 12},
    }
    trace = build_plan_trace(results)
    assert trace["kind"] == "reflex"
    assert trace["intent"] == "sensor_data"
    assert trace["steps"] == ["sparql", "sql"]  # execution order, from state keys
    assert trace["decision_source"] == "registry"


def test_a_trace_cannot_be_built_from_keys_the_pipeline_never_writes():
    """The counter-test, so this fixture cannot drift back to invented names.

    If `sparql_results`/`sql_data` ever produce steps again, either the markers have been
    reverted or someone has started writing those keys — both worth failing on.
    """
    results = {
        "route_decision": {
            "intent_from_dialogue": "sensor_data",
            "final_node": "sparql",
            "decision_source": "registry",
        },
        "sparql_results": [{"uuid": "u1"}],  # not a bus key
        "sql_data": {"rows": 12},  # not a bus key
        "analytics_output": {"x": 1},  # not a bus key
    }
    trace = build_plan_trace(results)
    assert trace["steps"] == ["sparql"], (
        "steps should fall back to the final node, because none of those keys exists; "
        "if they produced stages, BUG-510 has come back"
    )


def test_reflex_trace_falls_back_to_final_node_for_standalone_lanes():
    results = {
        "route_decision": {
            "intent_from_dialogue": "floor_plan",
            "final_node": "floor_plan",
            "decision_source": "override",
            "overrides_applied": ["floor_plan_navigation"],
        }
    }
    trace = build_plan_trace(results)
    assert trace["kind"] == "reflex"
    assert trace["steps"] == ["floor_plan"]
    assert trace["overrides_applied"] == ["floor_plan_navigation"]


def test_deliberative_trace_carries_plan_hash_and_stage_list():
    results = {
        "route_decision": {
            "intent_from_dialogue": "recommend",
            "intent_after_overrides": "deliberate",
            "final_node": "deliberate",
            "decision_source": "override",
            "overrides_applied": ["constraint_recommendation"],
        },
        "evidence_dossier": {"plan_hash": "abc123", "ranked": []},
    }
    trace = build_plan_trace(results)
    assert trace["kind"] == "deliberative"
    assert trace["plan_hash"] == "abc123"
    assert trace["steps"][0] == "compile_cqir" and trace["steps"][-1] == "dossier_guard"


def test_empty_state_still_yields_a_trace_never_raises():
    trace = build_plan_trace({})
    assert trace["kind"] == "reflex" and trace["steps"] == []


def test_chat_payload_carries_plan_trace():
    """The /chat and WS payloads must expose plan_trace next to evidence."""
    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    assert src.count('"plan_trace": ') >= 2
