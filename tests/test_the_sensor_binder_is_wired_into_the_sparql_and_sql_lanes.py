# -*- coding: utf-8 -*-
"""2D-05 wiring: the binder runs where retrieval yields the wrong (or no) series, and only there.

A binder that is correct in isolation and not called is the failure this project has measured
before (the referent gate had two callers across eighteen lanes). These pin the five seams:

1. the sparql lane asks the binder BEFORE the CAVEAT-148 repair, so a bound result is not
   "repaired" into a building-wide one;
2. the repair itself steps aside for a bound result;
3. the "no UUIDs" clarification for trend/compare/compliance does not overwrite the binder's
   own typed absence (which has no UUIDs by construction);
4. the sql lane clears a forecast window that lies in the future;
5. the spatial-adequacy grade uses the space the binder resolved, so a zone-basis answer
   carries its "Spatial basis" line even when the dialogue stage extracted no entity.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from orchestrator.workflow import _orchestrator
from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def test_the_sparql_lane_binds_before_it_repairs():
    src = inspect.getsource(WorkflowOrchestrator._sparql_node)
    assert "_sensor_binder.apply_to_result(state, result, _sparql_query)" in src
    assert src.index("apply_to_result") < src.index("_repair_retrieved_modality")


async def test_a_bound_result_is_not_repaired_into_a_wider_one(monkeypatch):
    """Without the guard a modality miss would swap the room's sensor for the whole building's."""
    called = []

    async def spy(query):
        called.append(query)
        return {"results": {"bindings": []}}

    monkeypatch.setattr("orchestrator.services.deliberation.live.sparql_exec", spy)
    state = SimpleNamespace(intermediate_results={"concepts": []})
    result = {
        "method": "sensor_binder",
        "results": {"results": {"bindings": []}},
    }
    stub = SimpleNamespace(_infer_query_kind=lambda text: "co2")
    await WorkflowOrchestrator._repair_retrieved_modality(stub, state, result, "co2 in room 1.06")

    assert called == []
    assert "modality_repair" not in state.intermediate_results
    assert result["method"] == "sensor_binder"


def test_the_no_uuid_fallback_does_not_overwrite_the_binders_own_absence():
    """A trend/compare/compliance turn with no UUIDs is replaced by a generic "specify the zone"
    message. The binder's typed absence has no UUIDs by construction and is the honest answer."""
    src = inspect.getsource(WorkflowOrchestrator._sparql_node)
    guard = '_binder_absence = _is_typed_absence(result) and bool(result.get("binder"))'
    assert guard in src
    assert src.index(guard) < src.index("_original_intent in _contextual_intents")
    assert "and not _binder_absence" in src


def test_the_sql_lane_reads_history_for_a_forecast():
    src = inspect.getsource(WorkflowOrchestrator._sql_node)
    assert "_history_window(" in src
    assert src.index("_history_window(") < src.index("fetch_data_for_uuids(")


def test_the_spatial_grade_uses_the_space_the_binder_resolved():
    src = inspect.getsource(WorkflowOrchestrator._grade_spatial_adequacy)
    assert 'results.get("binder_scope")' in src
    assert "target = binder_target" in src


def test_only_a_space_is_graded_against_the_binder_scope():
    """A heat pump's point is not 'in' a room; grading it as one would print a false caveat."""
    from orchestrator.services import sensor_binder as sb

    binding = sb.Binding(
        status=sb.STATUS_BOUND,
        basis=sb.BASIS_EQUIPMENT,
        scope_kind=sb.SCOPE_EQUIPMENT,
        scope_iri="http://example.org/b#Heat_Pump_1",
        scope_label="Heat Pump 1",
        quantity_label="temperature",
        sensors=[sb.BoundSensor(iri="x", label="x", uuid="1" * 8 + "-1111-4111-8111-" + "1" * 12)],
    )
    state = SimpleNamespace(intermediate_results={})
    sb._replace(state, {}, binding, "q")
    assert "binder_scope" not in state.intermediate_results

    binding.scope_kind, binding.basis = sb.SCOPE_SPACE, sb.BASIS_ZONE
    sb._replace(state, {}, binding, "q")
    assert state.intermediate_results["binder_scope"]["iri"].endswith("Heat_Pump_1")


def test_the_orchestrator_module_imports_the_binder_lazily():
    """The module is imported at the call, so a fault in it cannot stop the orchestrator booting."""
    assert (
        "sensor_binder"
        not in inspect.getsource(_orchestrator).split("class WorkflowOrchestrator")[0]
    )
