"""V4-T19 tests — deterministic plan executor (offline, fake adapters + forecaster)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from orchestrator.services.deliberation.capability_schema import (
    AdmissionResult,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    SpaceCoverage,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    TimeBasis,
    TimeSpec,
)
from orchestrator.services.deliberation.plan_executor import execute

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"


@dataclass
class FakeResult:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class FakeAdapter:
    """Serves canned per-uuid series regardless of the SQL text."""

    def __init__(self, rows):
        self._rows = rows

    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        return "SELECT ..."

    async def execute_query(self, sql):
        return FakeResult(data=self._rows)


def _space(local, floor="floor0"):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor=floor)
    sc.modalities = {
        "noise": {
            "status": STATUS_PRESENT,
            "sensor": "",
            "uuid": f"u-{local}",
            "stored_at": "noise_data",
        },
    }
    return sc


def _schema(locals_):
    return BuildingCapabilitySchema(
        building_id="anybldg", namespace=NS, spaces=[_space(x) for x in locals_], amenities=[]
    )


def _rows(uuid_, values):
    return [
        {"timestamp": f"2026-08-13 {10 + i:02d}:00:00", "uuid": uuid_, "value": v}
        for i, v in enumerate(values)
    ]


def _ir(basis=TimeBasis.NOW, horizon=None):
    return CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        time=TimeSpec(basis=basis, horizon_hours=horizon),
    )


def _run(coro):
    return asyncio.run(coro)


def test_now_basis_ranks_on_recent_mean_with_evidence():
    rows = _rows("u-Quiet", [40, 40, 40, 40, 40, 32]) + _rows("u-Loud", [40, 40, 40, 40, 40, 60])
    adapter = FakeAdapter(rows)
    out = _run(
        execute(
            _ir(),
            AdmissionResult(verdict="admit"),
            _schema(["Quiet", "Loud"]),
            adapter_getter=lambda t: adapter,
        )
    )
    assert [s.label for s in out.score.ranked] == ["Quiet", "Loud"]
    cell = [e for e in out.evidence if e.space_iri.endswith("Quiet")][0]
    assert cell.uuid == "u-Quiet" and cell.stored_at == "noise_data" and cell.n_points >= 1
    assert out.plan_hash and out.timings_ms["fetch_ms"] >= 0


def test_forecast_basis_uses_injected_forecaster_and_records_model():
    rows = _rows("u-A", [40] * 12) + _rows("u-B", [50] * 12)
    adapter = FakeAdapter(rows)

    async def fake_forecaster(series, horizon):
        return series[-1][1] - 20.0, "fake-model"  # B forecasts quieter than A

    out = _run(
        execute(
            _ir(TimeBasis.FORECAST, 24),
            AdmissionResult(verdict="admit"),
            _schema(["A", "B"]),
            adapter_getter=lambda t: adapter,
            forecaster=fake_forecaster,
        )
    )
    assert {f.model for f in out.forecasts} == {"fake-model"}
    assert all(f.horizon_hours == 24 for f in out.forecasts)
    by = {s.label: s for s in out.score.ranked}
    # forecast values (20, 30) rank A above B still — but both came from the forecaster
    assert by["A"].criteria[0].value == pytest.approx(20.0)
    assert by["B"].criteria[0].value == pytest.approx(30.0)


def test_missing_series_becomes_data_gap_not_a_value():
    rows = _rows("u-Has", [40] * 6)  # 'None' candidate has no rows at all
    adapter = FakeAdapter(rows)
    out = _run(
        execute(
            _ir(),
            AdmissionResult(verdict="admit"),
            _schema(["Has", "None"]),
            adapter_getter=lambda t: adapter,
        )
    )
    assert [s.label for s in out.score.ranked] == ["Has"]
    assert any(s.label == "None" for s in out.score.excluded)
    assert all(e.space_iri.endswith("Has") for e in out.evidence)


def test_plan_hash_deterministic_and_basis_sensitive():
    rows = _rows("u-A", [40] * 6)
    adapter = FakeAdapter(rows)
    a1 = _run(
        execute(
            _ir(),
            AdmissionResult(verdict="admit"),
            _schema(["A"]),
            adapter_getter=lambda t: adapter,
        )
    )
    a2 = _run(
        execute(
            _ir(),
            AdmissionResult(verdict="admit"),
            _schema(["A"]),
            adapter_getter=lambda t: adapter,
        )
    )
    b = _run(
        execute(
            _ir(TimeBasis.WINDOW),
            AdmissionResult(verdict="admit"),
            _schema(["A"]),
            adapter_getter=lambda t: adapter,
        )
    )
    assert a1.plan_hash == a2.plan_hash
    assert a1.plan_hash != b.plan_hash


# ── V5-T12/T13: two-tier forecasting ─────────────────────────────────────────


def _cyclic_rows(uuid_, start, hours, day_val, night_val):
    from datetime import datetime, timedelta

    t0 = datetime.fromisoformat(start)
    rows = []
    for i in range(hours):
        ts = t0 + timedelta(hours=i)
        v = day_val if 12 <= ts.hour <= 23 else night_val
        rows.append({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "uuid": uuid_, "value": v})
    return rows


def test_tier1_shortlist_ranks_on_predicted_values_not_history_means(monkeypatch):
    """RoomB's history MEAN (40) beats RoomA's (45), but the coming 12 h are
    B's loud phase (60): the tier-1 seasonal profile must hand the single
    shortlist slot to A. The old history-mean prelim would have picked B."""
    import orchestrator.services.deliberation.plan_executor as pe

    monkeypatch.setattr(pe, "FORECAST_TOP_K", 1)
    # 3 days of history ending 11:00 (the quiet phase, about to turn loud)
    hours = 3 * 24 - 12
    rows = [
        {"timestamp": r["timestamp"], "uuid": "u-A", "value": 45.0}
        for r in _cyclic_rows("u-A", "2026-08-03 00:00:00", hours, 45, 45)
    ] + _cyclic_rows("u-B", "2026-08-03 00:00:00", hours, 60, 20)
    adapter = FakeAdapter(rows)

    async def fake_forecaster(series, horizon):
        return series[-1][1], "fake-tier2"

    out = _run(
        execute(
            _ir(TimeBasis.FORECAST, 12),
            AdmissionResult(verdict="admit"),
            _schema(["A", "B"]),
            adapter_getter=lambda t: adapter,
            forecaster=fake_forecaster,
        )
    )
    assert {f.space_iri.split("#")[-1] for f in out.forecasts} == {"A"}
    assert [c.space_iri.split("#")[-1] for c in out.candidates] == ["A"]


def test_default_forecaster_produces_rich_records():
    """No injected forecaster: the ModelSelector adapter path fills model,
    backtest MAE and n_train on the ForecastRecord (V5-T12 acceptance)."""
    pytest.importorskip("pandas")
    rows = _cyclic_rows("u-A", "2026-08-03 00:00:00", 28, 60, 20)
    adapter = FakeAdapter(rows)
    out = _run(
        execute(
            _ir(TimeBasis.FORECAST, 12),
            AdmissionResult(verdict="admit"),
            _schema(["A"]),
            adapter_getter=lambda t: adapter,
        )
    )
    assert out.forecasts, "expected a forecast record for the only candidate"
    rec = out.forecasts[0]
    assert rec.model and rec.model != "linear trend"
    assert rec.backtest_mae is not None and rec.n_train > 0


def test_injected_tuple_forecasters_still_work():
    rows = _rows("u-A", [40] * 12)
    adapter = FakeAdapter(rows)

    async def tuple_forecaster(series, horizon):
        return 7.5, "legacy-tuple"

    out = _run(
        execute(
            _ir(TimeBasis.FORECAST, 24),
            AdmissionResult(verdict="admit"),
            _schema(["A"]),
            adapter_getter=lambda t: adapter,
            forecaster=tuple_forecaster,
        )
    )
    assert out.forecasts[0].model == "legacy-tuple"
    assert out.forecasts[0].ci95 is None and out.forecasts[0].n_train == 0
