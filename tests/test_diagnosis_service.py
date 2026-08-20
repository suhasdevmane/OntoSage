# -*- coding: utf-8 -*-
"""V5-T20: diagnosis lens — question parsing, referents, windows, language."""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.anomaly.diagnosis import (
    DiagnosisService,
    is_why_question,
    parse_day_window,
)
from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 17, 15, 0, 0)  # a Monday


def test_why_question_detection_requires_why_and_a_comfort_word():
    assert is_why_question("Why was floor 2 freezing on Tuesday?") == ("temperature", "low")
    assert is_why_question("why is it so stuffy in RM125?") == ("co2", "high")
    assert is_why_question("Why was the library so loud yesterday?") == ("noise", "high")
    assert is_why_question("Why is the sky blue?") is None
    assert is_why_question("What is the temperature?") is None


def test_day_window_parsing_is_deterministic():
    s, e, label = parse_day_window("why was it cold on tuesday?", NOW)
    assert label == "last Tuesday" and s.weekday() == 1 and (e - s).days == 1
    assert s < NOW  # always the most recent PAST Tuesday
    s, e, label = parse_day_window("why was it cold yesterday?", NOW)
    assert label == "yesterday" and s.day == 16
    s, e, label = parse_day_window("why is it cold?", NOW)
    assert label == "the last 24 hours" and (e - s).total_seconds() == 86400
    # a weekday named today still resolves to LAST week, never a zero-length window
    s, e, label = parse_day_window("why was it cold on monday?", NOW)
    assert (NOW - s).days == 7


def _spaces():
    a = SpaceCoverage(space_iri="ns#RM125_room", label="RM125_room", floor="floor1")
    b = SpaceCoverage(space_iri="ns#RM201_room", label="RM201_room", floor="floor2")
    c = SpaceCoverage(space_iri="ns#RM202_room", label="RM202_room", floor="floor2")
    return [a, b, c]


def test_referent_resolution_room_floor_building():
    kind, hits = DiagnosisService.resolve_referent("why is RM125 so cold?", _spaces())
    assert kind == "room" and hits[0].label == "RM125_room"
    kind, hits = DiagnosisService.resolve_referent("why was floor 2 freezing?", _spaces())
    assert kind == "floor" and {h.label for h in hits} == {"RM201_room", "RM202_room"}
    kind, hits = DiagnosisService.resolve_referent("why is it so cold in here?", _spaces())
    assert kind == "building" and len(hits) == 3


def test_window_mean_only_uses_the_window():
    series = [
        ("2026-08-16 10:00:00", 10.0),
        ("2026-08-17 10:00:00", 20.0),
        ("2026-08-17 11:00:00", 30.0),
    ]
    m = DiagnosisService._window_mean(
        series, datetime(2026, 8, 17, 0, 0), datetime(2026, 8, 18, 0, 0)
    )
    assert m == pytest.approx(25.0)
    assert (
        DiagnosisService._window_mean(
            series, datetime(2026, 8, 10, 0, 0), datetime(2026, 8, 11, 0, 0)
        )
        is None
    )


def test_non_why_question_returns_empty():
    import asyncio

    svc = DiagnosisService("tb", "ns#", sparql_exec=lambda q: None)
    r = asyncio.run(svc.diagnose("what is the temperature?"))
    assert not r["success"] and r["formatted_response"] == ""
