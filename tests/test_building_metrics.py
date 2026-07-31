"""Unit tests for live building metrics (services/building_metrics.py) and the
capability agent's live-grounding of count/area questions.

Everything runs offline: the SPARQL executor and the floor-area provider are injected,
so no GraphDB / DWG is needed. These lock in that count/area answers come from live
computation, never from frozen numbers.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.building_metrics import (
    BuildingMetrics,
    BuildingMetricsSnapshot,
    render_metrics_block,
)

pytestmark = pytest.mark.unit

_NS = "http://abacwsbuilding.cardiff.ac.uk/abacws#"


def _count_exec(mapping):
    """Async SPARQL exec that returns a count based on which class the query mentions."""

    async def _exec(query: str) -> dict:
        n = 0
        if "brick:Point" in query:
            n = mapping.get("points", 0)
        elif "brick:Sensor" in query and "GROUP BY" in query:
            # sensor-type breakdown
            return {
                "results": {
                    "bindings": [
                        {"t": {"value": _NS + "Temperature_Sensor"}, "n": {"value": "210"}},
                        {"t": {"value": _NS + "CO2_Sensor"}, "n": {"value": "120"}},
                    ]
                }
            }
        elif "brick:Sensor" in query:
            n = mapping.get("sensors", 0)
        elif "brick:Location" in query:
            n = mapping.get("zones", 0)
        return {"results": {"bindings": [{"n": {"value": str(n)}}]}}

    return _exec


def _areas(_bid):
    return [(0, 2765.7, 15), (5, 3616.3, 34)]


# ── BuildingMetrics.snapshot ─────────────────────────────────────────────────


async def test_snapshot_computes_live_counts_and_area():
    bm = BuildingMetrics(
        sparql_exec=_count_exec({"points": 1332, "sensors": 680, "zones": 96}),
        area_provider=_areas,
    )
    snap = await bm.snapshot("bldg1", namespace=_NS)
    assert snap.total_points == 1332
    assert snap.total_sensors == 680
    assert snap.zone_count == 96
    assert snap.total_area_m2 == pytest.approx(6382.0, abs=0.1)
    assert len(snap.per_floor_area) == 2
    assert snap.sensor_types and snap.sensor_types[0][0] == "Temperature Sensor"


async def test_snapshot_is_cached():
    calls = {"n": 0}

    async def _exec(query: str) -> dict:
        calls["n"] += 1
        return {"results": {"bindings": [{"n": {"value": "5"}}]}}

    bm = BuildingMetrics(sparql_exec=_exec, area_provider=lambda _b: [])
    await bm.snapshot("bldg1", namespace=_NS)
    first = calls["n"]
    await bm.snapshot("bldg1", namespace=_NS)  # within TTL → served from cache
    assert calls["n"] == first


async def test_snapshot_degrades_gracefully_on_sparql_error():
    async def _boom(_q):
        raise RuntimeError("GraphDB down")

    bm = BuildingMetrics(sparql_exec=_boom, area_provider=_areas)
    snap = await bm.snapshot("bldg1", namespace=_NS)
    # Counts unavailable, but area still computed — partial snapshot, no exception.
    assert snap.total_points is None
    assert snap.total_area_m2 == pytest.approx(6382.0, abs=0.1)


def test_render_block_uses_live_numbers():
    snap = BuildingMetricsSnapshot(
        total_points=1332,
        total_sensors=680,
        zone_count=96,
        total_area_m2=20370.0,
        per_floor_area=[(0, 1.0, 1)] * 6,
    )
    block = render_metrics_block(snap, "Abacws")
    assert "1,332" in block
    assert "20,370" in block
    assert "Abacws" in block


# ── capability agent: metrics questions answered live ────────────────────────


def test_is_metrics_question_detection():
    from orchestrator.agents.capability_agent import _is_metrics_question

    assert _is_metrics_question("How many sensors are there?")
    assert _is_metrics_question("what is the total floor area?")
    assert _is_metrics_question("how big is the building")
    # Not a metrics question — must fall through to normal KB handling.
    assert not _is_metrics_question("where is the prayer room?")
    assert not _is_metrics_question("how many people are on floor 3?")


def test_is_inventory_count_question_routing_detector():
    from orchestrator.services.building_metrics import is_inventory_count_question

    # Building-wide → must be stolen and answered from live metrics (FIX-003).
    assert is_inventory_count_question("How many sensors are there in the building?")
    assert is_inventory_count_question("what is the total floor area?")
    assert is_inventory_count_question("how big is the building?")
    assert is_inventory_count_question("what is the sensor count?")
    # Floor/zone/room-scoped or non-inventory → keep the normal SPARQL/spatial path.
    assert not is_inventory_count_question("how many sensors on floor 5?")
    assert not is_inventory_count_question("how many rooms on floor 3?")
    assert not is_inventory_count_question("how many people are on floor 3?")
    assert not is_inventory_count_question("what is the total area of floor 1?")
    assert not is_inventory_count_question("where is the prayer room?")


async def test_capability_answer_grounds_metrics_live(monkeypatch):
    import orchestrator.agents.capability_agent as cap
    import orchestrator.services.building_context as bctx
    import orchestrator.services.building_metrics as bmmod
    from shared.models import ConversationState, Message

    # Display name resolves from building config (TODO-012: no capability.yaml / KB).
    monkeypatch.setattr(
        bctx, "resolve_building_context", lambda _bid: SimpleNamespace(name="Abacws")
    )

    class _FakeBM:
        async def snapshot(self, _bid, namespace=None):
            return BuildingMetricsSnapshot(
                total_points=1332, total_sensors=680, total_area_m2=20370.0
            )

    monkeypatch.setattr(bmmod, "get_building_metrics", lambda: _FakeBM())

    state = ConversationState(
        conversation_id="c1",
        user_id="u",
        user_message="how many sensors are there?",
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content="how many sensors are there?")],
    )
    out = await cap.CapabilityAgent().answer(state)
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "live_metrics"
    assert "1,332" in res["response"]  # the live count, not the old frozen "~680" prose
    assert "computed live" in res["response"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# CAVEAT-007 — declared vs recently-reporting sensors
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_includes_reporting_coverage():
    async def _exec(q):
        return {"results": {"bindings": [{"n": {"value": "100"}}]}}

    async def _reporting(window_h):
        assert window_h == 24
        return 42

    bm = BuildingMetrics(
        sparql_exec=_exec, area_provider=lambda _b: [], reporting_provider=_reporting
    )
    snap = await bm.snapshot("anybldg")
    assert snap.reporting_sensors == 42
    assert snap.reporting_window_h == 24


@pytest.mark.asyncio
async def test_reporting_provider_failure_is_non_fatal():
    async def _exec(q):
        return {"results": {"bindings": [{"n": {"value": "7"}}]}}

    async def _boom(window_h):
        raise RuntimeError("db down")

    bm = BuildingMetrics(sparql_exec=_exec, area_provider=lambda _b: [], reporting_provider=_boom)
    snap = await bm.snapshot("anybldg")
    assert snap.reporting_sensors is None  # degraded, never raised
    assert snap.total_sensors == 7


def test_render_block_distinguishes_declared_vs_reporting():
    snap = BuildingMetricsSnapshot(total_sensors=1334, reporting_sensors=628, reporting_window_h=24)
    text = render_metrics_block(snap, "Any Building")
    assert "declared in the building model" in text
    assert "1,334" in text
    assert "reported data in the last 24 h" in text
    assert "628" in text


def test_render_block_omits_reporting_when_unknown():
    snap = BuildingMetricsSnapshot(total_sensors=300, reporting_sensors=None)
    text = render_metrics_block(snap, "Any Building")
    assert "declared in the building model" in text
    assert "reported data in the last" not in text
