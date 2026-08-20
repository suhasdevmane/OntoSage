# -*- coding: utf-8 -*-
"""V5-T32: the unlock report names exactly what is missing, per shape."""

from __future__ import annotations

import pytest

from orchestrator.services.onboarding_report import (
    LOCKED,
    PARTIAL,
    UNLOCKED,
    build_unlock_report,
    render_report,
)

pytestmark = pytest.mark.unit


def _facts(**over):
    base = {
        "backed_points": 0,
        "spaces": 0,
        "history_days": 0.0,
        "modalities_with_data": [],
        "events_source_registered": False,
        "events_rows": 0,
        "event_types": [],
        "compliance_checks": 0,
        "adjacency_edges": 0,
        "access_policies": 0,
    }
    base.update(over)
    return base


def _by_name(statuses):
    return {s.name: s for s in statuses}


def test_empty_building_locks_everything_with_reasons():
    st = _by_name(build_unlock_report(_facts()))
    assert all(s.state == LOCKED for s in st.values())
    assert "ref:hasTimeseriesId" in st["readings"].missing[0]
    assert "events_data" in st["bookings"].missing[0]
    assert "ComplianceCheck" in st["compliance_register"].missing[0]
    assert "adjacency" in st["wayfinding"].missing[0]
    assert "AccessPolicy" in st["privacy_policies"].missing[0]
    # every locked capability must say what to do, never just "not configured"
    assert all(s.missing for s in st.values())


def test_s1_only_building_unlocks_readings_but_not_predict_or_detect():
    st = _by_name(
        build_unlock_report(
            _facts(
                backed_points=40,
                spaces=20,
                history_days=0.5,
                modalities_with_data=["temperature", "co2"],
            )
        )
    )
    assert st["readings"].state == UNLOCKED
    assert st["ranking"].state == UNLOCKED
    assert st["predict"].state == LOCKED and "days of readings" in st["predict"].missing[0]
    assert st["detect"].state == LOCKED
    assert st["bookings"].state == LOCKED


def test_history_thresholds_are_graded_not_binary():
    partial = _by_name(build_unlock_report(_facts(backed_points=10, spaces=5, history_days=3)))
    assert partial["predict"].state == PARTIAL
    assert "seasonal" in partial["predict"].why
    mature = _by_name(
        build_unlock_report(
            _facts(
                backed_points=10,
                spaces=5,
                history_days=40,
                events_source_registered=True,
                events_rows=5,
                event_types=["booking"],
            )
        )
    )
    assert mature["predict"].state == UNLOCKED
    assert mature["detect"].state == UNLOCKED


def test_detect_without_events_store_is_partial_not_unlocked():
    st = _by_name(build_unlock_report(_facts(backed_points=10, spaces=5, history_days=10)))
    assert st["detect"].state == PARTIAL
    assert "events_data" in st["detect"].missing[0]


def test_events_store_granularity_per_event_type():
    st = _by_name(
        build_unlock_report(
            _facts(
                events_source_registered=True, events_rows=100, event_types=["booking", "access"]
            )
        )
    )
    assert st["bookings"].state == UNLOCKED
    assert st["access_counts"].state == UNLOCKED
    assert st["workorders"].state == PARTIAL
    assert "workorder" in st["workorders"].missing[0]


def test_registered_but_empty_events_store_is_partial():
    st = _by_name(build_unlock_report(_facts(events_source_registered=True, events_rows=0)))
    assert st["bookings"].state == PARTIAL
    assert "rows in the events table" in st["bookings"].missing[0]


def test_fully_connected_building_unlocks_everything():
    st = _by_name(
        build_unlock_report(
            _facts(
                backed_points=418,
                spaces=52,
                history_days=40,
                modalities_with_data=["temperature", "co2", "noise"],
                events_source_registered=True,
                events_rows=3000,
                event_types=["booking", "workorder", "access", "anomaly"],
                compliance_checks=82,
                adjacency_edges=120,
                access_policies=12,
            )
        )
    )
    assert all(s.state == UNLOCKED for s in st.values()), {
        k: (v.state, v.missing) for k, v in st.items() if v.state != UNLOCKED
    }


def test_report_renders_counts_and_actions():
    facts = _facts(backed_points=5, spaces=3, history_days=1)
    text = render_report("tb", facts, build_unlock_report(facts))
    assert "Onboarding report — tb" in text
    assert "capabilities unlocked" in text
    assert "⛔" in text and "|" in text
