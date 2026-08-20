# -*- coding: utf-8 -*-
"""V5-T29: one allowed-numbers builder guards every template lane."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from orchestrator.services.numeric_guard import (
    SUPPRESSION_TEXT,
    collect,
    find_unbacked,
    guard_payload,
)

pytestmark = pytest.mark.unit


def test_clean_payload_passes_untouched():
    p = {
        "success": True,
        "count": 452,
        "formatted_response": "**About 452 arrivals** this morning.",
    }
    out = guard_payload(p, "events")
    assert out is p or out == p
    assert "452 arrivals" in out["formatted_response"]


def test_unbacked_number_is_suppressed_with_standard_text():
    p = {
        "success": True,
        "count": 452,
        "formatted_response": "**About 999 arrivals** this morning.",
    }
    out = guard_payload(p, "events")
    assert out["formatted_response"] == SUPPRESSION_TEXT
    assert out["guard_violations"] == ["999"]
    assert out["count"] == 452  # structured fields stay intact


def test_datetime_fields_back_their_clock_fragments():
    p = {
        "success": True,
        "window": [datetime(2026, 8, 12, 18, 20), datetime(2026, 8, 12, 19, 20)],
        "formatted_response": "Booked 18:20–19:20 on 2026-08-12.",
    }
    assert guard_payload(p, "events")["formatted_response"].startswith("Booked")


def test_decimal_fragments_and_thousands_are_backed():
    allowed, blobs = set(), []
    collect({"value": 32.117, "total": 1316}, allowed, blobs)
    assert find_unbacked("noise 32.117 dB across 1,316 bookings (32 avg)", allowed, blobs) == []


def test_real_register_payload_survives():
    from tests.test_compliance_register_service import _FakeSparql, _row, _svc

    fake = _FakeSparql(
        rows=[
            _row("check_fire_door_1", "2026-07-01T00:00:00", label="Fire door inspection"),
            _row("check_pat_1", "2026-06-15T00:00:00", label="PAT testing"),
        ],
        count=82,
    )
    r = asyncio.run(
        _svc(fake).answer("Which compliance checks are overdue?", now=datetime(2026, 8, 17))
    )
    out = guard_payload(r, "register")
    assert out["formatted_response"] != SUPPRESSION_TEXT
    assert "2 compliance item(s) overdue" in out["formatted_response"]


def test_real_events_payload_survives():
    from orchestrator.services.event_query_service import EventQueryService
    from tests.test_event_query_service import NOW, ROOMS, _FakeAdapter

    svc = EventQueryService("tb", _FakeAdapter([]), ROOMS)
    r = asyncio.run(svc.answer("Which rooms are free today?", now=NOW))
    out = guard_payload(r, "events")
    assert out["formatted_response"] != SUPPRESSION_TEXT


def test_real_diagnosis_decline_survives():
    from orchestrator.services.anomaly.diagnosis import DiagnosisService

    svc = DiagnosisService("tb", "ns#", sparql_exec=lambda q: None)
    r = asyncio.run(svc.diagnose("what is the temperature?"))
    out = guard_payload(r, "diagnosis")
    assert out.get("formatted_response", "") == ""  # empty stays empty, no crash


def test_zero_padded_clock_fragments_are_backed():
    """'at 14:00' must not trip the guard when hour=14 is a payload field —
    the '00' is the same number as an innocuous 0 (V5-T15 shakedown)."""
    p = {
        "hour": 14,
        "value": 21.5,
        "formatted_response": "At 14:00 the reading was 21.5.",
    }
    assert guard_payload(p, "test")["formatted_response"].startswith("At 14:00")
