# -*- coding: utf-8 -*-
"""V5-T25: ARBITER event-derived criteria — fold, filter, ledger, dossier."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.deliberation.capability_schema import (
    AdmissionResult,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.compiler import _fold_event_criteria
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    SpaceCoverage,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    EventCriterion,
    TimeSpec,
)
from orchestrator.services.deliberation.plan_executor import execute

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"


def test_fold_detects_free_window_and_pressure():
    crits = _fold_event_criteria("find me a quiet room free for the next 2 hours near water")
    assert [c.kind for c in crits] == ["free_window"] and crits[0].hours == 2.0
    crits = _fold_event_criteria("which rooms are available now?")
    assert crits and crits[0].hours == 1.0
    crits = _fold_event_criteria("a study space that's rarely booked")
    assert [c.kind for c in crits] == ["low_booking_pressure"]
    assert _fold_event_criteria("what is the CO2 in RM101?") == []


def test_fingerprint_changes_with_event_criteria():
    base = CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
    )
    with_events = base.model_copy(
        update={"event_criteria": [EventCriterion(kind="free_window", hours=2.0)]}
    )
    assert base.plan_fingerprint() != with_events.plan_fingerprint()


# ── executor filter ──────────────────────────────────────────────────────────


@dataclass
class FakeResult:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class FakeEventsAdapter:
    """Returns one booking for RM-Busy overlapping any requested window."""

    def __init__(self, busy_subject: str):
        self.busy_subject = busy_subject

    def build_overlap_window(self, event_type, start, end, subject_uuids=None, limit=1000):
        self._window = (start, end)
        return "SELECT ..."

    async def execute_query(self, sql):
        s = datetime.utcnow()
        return FakeResult(
            data=[
                {
                    "event_id": "b1",
                    "event_type": "booking",
                    "subject_uuid": self.busy_subject,
                    "start_dt": s,
                    "end_dt": s + timedelta(hours=3),
                    "status": "done",
                }
            ]
        )


class FakeSeriesAdapter:
    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        return "SELECT ..."

    async def execute_query(self, sql):
        rows = []
        now = datetime.utcnow()
        for uid, level in (("u-Busy", 30.0), ("u-Free", 40.0)):
            for i in range(12):
                rows.append(
                    {
                        "timestamp": (now - timedelta(hours=12 - i)).strftime("%Y-%m-%d %H:%M:%S"),
                        "uuid": uid,
                        "value": level,
                    }
                )
        return FakeResult(data=rows)


def _schema():
    spaces = []
    for local in ("Busy", "Free"):
        sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor="floor0")
        sc.modalities = {
            "noise": {
                "status": STATUS_PRESENT,
                "sensor": "",
                "uuid": f"u-{local}",
                "stored_at": "noise_data",
            }
        }
        spaces.append(sc)
    return BuildingCapabilitySchema(building_id="tb", namespace=NS, spaces=spaces, amenities=[])


def _adapters(busy_subject):
    events = FakeEventsAdapter(busy_subject)
    series = FakeSeriesAdapter()
    return lambda key: events if key == "bldg:events_data" else series


def _ir_with_events():
    return CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        time=TimeSpec(),
        event_criteria=[EventCriterion(kind="free_window", hours=2.0)],
    )


def test_booked_candidate_is_excluded_with_ledger_reason():
    busy_subject = derive_point_uuid("tb", "evt_subject", "Busy")
    out = asyncio.run(
        execute(
            _ir_with_events(),
            AdmissionResult(verdict="admit"),
            _schema(),
            adapter_getter=_adapters(busy_subject),
        )
    )
    # Busy is quieter (30 dB) but BOOKED — Free must win, Busy must be excluded
    assert [s.label for s in out.score.ranked] == ["Free"]
    assert any("not free for the requested 2h window" in e.reason for e in out.ledger.excluded)
    checks = {ec.space_iri.split("#")[-1]: ec for ec in out.event_checks}
    assert checks["Busy"].free is False and checks["Free"].free is True
    assert "booked" in checks["Busy"].detail


def test_missing_events_store_is_declared_not_silent():
    out = asyncio.run(
        execute(
            _ir_with_events(),
            AdmissionResult(verdict="admit"),
            _schema(),
            adapter_getter=lambda key: None if key == "bldg:events_data" else FakeSeriesAdapter(),
        )
    )
    # nothing filtered, and the dossier will carry the honesty note
    assert {s.label for s in out.score.ranked} == {"Busy", "Free"}
    assert out.event_notes and "no booking/event store" in out.event_notes[0]


def test_dossier_renders_availability_and_survives_the_guard():
    from orchestrator.services.deliberation.clarify_policy import ClarifyDecision
    from orchestrator.services.deliberation.dossier import (
        build_dossier,
        numeric_guard,
        render_answer,
    )

    busy_subject = derive_point_uuid("tb", "evt_subject", "Busy")
    ir = _ir_with_events()
    out = asyncio.run(
        execute(
            ir,
            AdmissionResult(verdict="admit"),
            _schema(),
            adapter_getter=_adapters(busy_subject),
        )
    )
    dossier = build_dossier(ir, ClarifyDecision(action="proceed"), out, "tb")
    prose = render_answer(dossier)
    assert "Availability: 1 of 2 candidate(s) free for the next 2h" in prose
    assert numeric_guard(prose, dossier) == []
