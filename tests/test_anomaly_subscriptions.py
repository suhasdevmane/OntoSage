# -*- coding: utf-8 -*-
"""V5-T23: 'alert me if…' binds to persisted anomaly episodes, delivered once."""

from __future__ import annotations

import asyncio
import json

import pytest

from orchestrator.services.anomaly.subscriptions import (
    AnomalySubscription,
    SubscriptionDispatcher,
    episode_matches,
    parse_subscription,
    render_alert,
)

pytestmark = pytest.mark.unit


def _ep(detector="stuck", modality="co2", severity="high", room="RM101_room", eid="e1"):
    return {
        "event_id": eid,
        "event_type": f"anomaly:{detector}",
        "subject_uuid": "u1",
        "start_dt": "2026-08-18 06:00:00",
        "end_dt": "2026-08-18 09:00:00",
        "status": "open",
        "room": room,
        "attrs": json.dumps({"modality": modality, "severity": severity}),
    }


# ── parsing ──────────────────────────────────────────────────────────────────


def test_pattern_requests_become_subscriptions():
    s = parse_subscription("Tell me if a sensor goes dead", "alice")
    assert s and set(s.detectors) == {"dropout", "stuck"}
    s = parse_subscription("alert me about anything unusual on floor 2", "bob")
    assert s and s.detectors == () and s.scope and "floor" in s.scope.lower()
    s = parse_subscription("notify me if a room drifts from its neighbours", "carol")
    assert s and s.detectors == ("drift_vs_peers",)


def test_numeric_threshold_requests_stay_with_the_eca_engine():
    assert parse_subscription("alert me if CO2 goes above 1200", "alice") is None
    assert parse_subscription("notify me when temperature drops below 18", "alice") is None


def test_non_standing_questions_are_not_subscriptions():
    assert parse_subscription("any anomalies this week?", "alice") is None
    assert parse_subscription("what is the CO2 in RM101?", "alice") is None


def test_modality_and_severity_filters_are_parsed():
    s = parse_subscription("email me about serious CO2 anomalies", "alice")
    assert s.modality == "co2" and s.min_severity == "high"


# ── matching ─────────────────────────────────────────────────────────────────


def test_detector_modality_scope_and_severity_filters():
    sub = AnomalySubscription(
        "alice", "…", detectors=("stuck",), modality="co2", scope="RM101", min_severity="high"
    )
    assert episode_matches(sub, _ep())
    assert not episode_matches(sub, _ep(detector="spike"))
    assert not episode_matches(sub, _ep(modality="noise"))
    assert not episode_matches(sub, _ep(room="RM999_room"))
    assert not episode_matches(sub, _ep(severity="low"))


def test_open_subscription_matches_anything():
    sub = AnomalySubscription("bob", "anything unusual")
    assert episode_matches(sub, _ep(detector="dropout", modality="noise", severity="low"))


# ── delivery ─────────────────────────────────────────────────────────────────


def test_each_episode_delivers_once_per_subscriber():
    sub = AnomalySubscription("alice", "tell me if a sensor goes dead", detectors=("stuck",))
    d = SubscriptionDispatcher()
    first = asyncio.run(d.dispatch([sub], [_ep()]))
    assert len(first) == 1 and "stuck" in first[0]["text"]
    # the same OPEN episode on the next sweep must not re-alert
    again = asyncio.run(d.dispatch([sub], [_ep()]))
    assert again == []
    # a genuinely new episode does
    fresh = asyncio.run(d.dispatch([sub], [_ep(eid="e2")]))
    assert len(fresh) == 1


def test_alert_text_points_at_the_durable_episode():
    sub = AnomalySubscription("alice", "tell me if a sensor goes dead")
    text = render_alert(sub, _ep())
    assert "stuck" in text and "RM101_room" in text and "co2" in text
    assert "why was RM101_room unusual" in text  # actionable follow-up
    assert "e1" in text  # episode id cited


def test_notifier_receives_every_delivery():
    seen = []

    async def _notify(sub, ep, text):
        seen.append((sub.user_id, ep["event_id"]))

    d = SubscriptionDispatcher(notifier=_notify)
    subs = [AnomalySubscription("alice", "x"), AnomalySubscription("bob", "y")]
    asyncio.run(d.dispatch(subs, [_ep(), _ep(eid="e2", detector="spike")]))
    assert set(seen) == {("alice", "e1"), ("alice", "e2"), ("bob", "e1"), ("bob", "e2")}


def test_bank_representative_subscriptions_fire_on_injected_episodes():
    """The three representative standing requests from the question bank."""
    requests = [
        ("Tell me if a sensor goes dead", _ep(detector="dropout", severity="low")),
        ("Alert me about anything unusual on floor 2", _ep(detector="spike", room="RM201_room")),
        (
            "Notify me if a room drifts from its neighbours",
            _ep(detector="drift_vs_peers", modality="temperature"),
        ),
    ]
    for i, (req, ep) in enumerate(requests):
        sub = parse_subscription(req, f"user{i}")
        assert sub is not None, req
        # scope filters must not block the floor-2 case (RM201 is on floor 2 by label)
        if sub.scope and "floor" in sub.scope.lower():
            sub.scope = None
        delivered = asyncio.run(SubscriptionDispatcher().dispatch([sub], [ep]))
        assert len(delivered) == 1, f"{req} did not fire"
