# -*- coding: utf-8 -*-
"""V5-T38: deterministic PDP — table-driven verdict matrix (30+ cases)."""

from __future__ import annotations

import pytest

from orchestrator.services.privacy.policy_engine import (
    ALLOW,
    DENY,
    RESTRICT,
    Policy,
    PolicyEngine,
    PolicyVerdict,
    _parse_tiers,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/tb#"

_TIERS = "15:5,60:60,10080:3600"


def _policies():
    inf = [
        Policy(iri=f"{NS}p_inf_{c}", role="*", inference_class=f"{c}:deny")
        for c in ("individual_presence", "individual_pattern", "private_content")
    ]
    return inf + [
        Policy(iri=f"{NS}p_admin", role="admin", tiers=[(0.0, 1.0)]),
        Policy(iri=f"{NS}p_analyst", role="analyst", tiers=[(0.0, 1.0)]),
        Policy(
            iri=f"{NS}p_fm",
            role="facility_manager",
            tiers=_parse_tiers(_TIERS),
            rate_max=3,
            rate_window_min=1,
        ),
        # the real occupant model is THREE scoped policies (T37 template):
        Policy(iri=f"{NS}p_occ_own", role="occupant", scope_spaces="own", tiers=[(0.0, 1.0)]),
        Policy(
            iri=f"{NS}p_occ_public",
            role="occupant",
            scope_spaces="public",
            tiers=_parse_tiers(_TIERS),
        ),
        Policy(
            iri=f"{NS}p_occupant",
            role="occupant",
            scope_spaces="any",
            min_sensors=14,
            min_spaces=7,
            tiers=_parse_tiers("60:300,10080:3600"),
            rate_max=60,
            rate_window_min=60,
        ),
    ]


def _engine(clock=None):
    eng = PolicyEngine("tb", NS, sparql_exec=None, clock=clock or (lambda: 1000.0))
    eng.set_policies(_policies())
    return eng


# ── the matrix ───────────────────────────────────────────────────────────────

MATRIX = [
    # (case_id, role, kwargs, expected_decision, expected_fragment)
    # inference-class denials bind EVERY role — including admin (user decision #2)
    (
        "inf-presence-admin",
        "admin",
        {"inference_class": "individual_presence"},
        DENY,
        "never individuals",
    ),
    (
        "inf-presence-occ",
        "occupant",
        {"inference_class": "individual_presence"},
        DENY,
        "never individuals",
    ),
    (
        "inf-pattern-admin",
        "admin",
        {"inference_class": "individual_pattern"},
        DENY,
        "never individuals",
    ),
    (
        "inf-pattern-fm",
        "facility_manager",
        {"inference_class": "individual_pattern"},
        DENY,
        "never individuals",
    ),
    (
        "inf-content-analyst",
        "analyst",
        {"inference_class": "private_content"},
        DENY,
        "never individuals",
    ),
    (
        "inf-content-occ",
        "occupant",
        {"inference_class": "private_content"},
        DENY,
        "never individuals",
    ),
    # a NON-denied inference class passes through to the role policy
    ("inf-unknown-class", "admin", {"inference_class": "room_conditions"}, ALLOW, "allowed"),
    # unknown role → deny, never a silent default
    ("unknown-role", "visitor_x", {}, DENY, "no access policy"),
    ("empty-role-readonly", "", {}, DENY, "no access policy"),
    # admin/analyst: unrestricted tiers ("0:1")
    (
        "admin-raw-recent",
        "admin",
        {"data_age_minutes": 1, "requested_resolution_s": 1},
        ALLOW,
        "allowed",
    ),
    (
        "admin-raw-old",
        "admin",
        {"data_age_minutes": 99999, "requested_resolution_s": 1},
        ALLOW,
        "allowed",
    ),
    (
        "analyst-raw",
        "analyst",
        {"data_age_minutes": 500, "requested_resolution_s": 5},
        ALLOW,
        "allowed",
    ),
    # facility_manager tier boundaries
    (
        "fm-recent-at-tier",
        "facility_manager",
        {"data_age_minutes": 10, "requested_resolution_s": 5},
        ALLOW,
        "allowed",
    ),
    (
        "fm-recent-too-fine",
        "facility_manager",
        {"data_age_minutes": 10, "requested_resolution_s": 1},
        RESTRICT,
        "clamped to 5s",
    ),
    (
        "fm-boundary-15min",
        "facility_manager",
        {"data_age_minutes": 15, "requested_resolution_s": 5},
        ALLOW,
        "allowed",
    ),
    (
        "fm-hour-old",
        "facility_manager",
        {"data_age_minutes": 30, "requested_resolution_s": 5},
        RESTRICT,
        "clamped to 60s",
    ),
    (
        "fm-hour-at-tier",
        "facility_manager",
        {"data_age_minutes": 30, "requested_resolution_s": 60},
        ALLOW,
        "allowed",
    ),
    (
        "fm-week-old",
        "facility_manager",
        {"data_age_minutes": 2000, "requested_resolution_s": 60},
        RESTRICT,
        "clamped to 3600s",
    ),
    (
        "fm-beyond-tiers",
        "facility_manager",
        {"data_age_minutes": 20000, "requested_resolution_s": 60},
        RESTRICT,
        "clamped to 3600s",
    ),
    ("fm-raw-unspecified", "facility_manager", {"data_age_minutes": 5}, RESTRICT, "clamped to 5s"),
    (
        "fm-coarse-ok",
        "facility_manager",
        {"data_age_minutes": 20000, "requested_resolution_s": 3600},
        ALLOW,
        "allowed",
    ),
    # occupant DEFAULT scope is 'any' — the cross-space k-floors (≥14/≥7)
    ("occ-below-sensor-floor", "occupant", {"n_sensors": 3}, RESTRICT, "≥14 sensors"),
    ("occ-below-space-floor", "occupant", {"n_spaces": 2}, RESTRICT, "≥7 spaces"),
    ("occ-both-floors-met", "occupant", {"n_sensors": 20, "n_spaces": 10}, ALLOW, "allowed"),
    (
        "occ-floor-and-tier",
        "occupant",
        {"n_sensors": 3, "data_age_minutes": 30, "requested_resolution_s": 1},
        RESTRICT,
        "aggregation floor",
    ),
    (
        "occ-cross-coarse",
        "occupant",
        {"n_sensors": 20, "n_spaces": 10, "data_age_minutes": 30, "requested_resolution_s": 300},
        ALLOW,
        "allowed",
    ),
    (
        "occ-cross-too-fine",
        "occupant",
        {"n_sensors": 20, "n_spaces": 10, "data_age_minutes": 30, "requested_resolution_s": 60},
        RESTRICT,
        "clamped to 300s",
    ),
    # occupant OWN scope: your data is yours — raw, single sensor
    (
        "occ-own-raw",
        "occupant",
        {"scope": "own", "n_sensors": 1, "data_age_minutes": 1, "requested_resolution_s": 1},
        ALLOW,
        "allowed",
    ),
    # occupant PUBLIC scope: tiered but no k-floor
    (
        "occ-public-tier",
        "occupant",
        {"scope": "public", "n_sensors": 1, "data_age_minutes": 30, "requested_resolution_s": 5},
        RESTRICT,
        "clamped to 60s",
    ),
    (
        "occ-public-at-tier",
        "occupant",
        {"scope": "public", "data_age_minutes": 10, "requested_resolution_s": 5},
        ALLOW,
        "allowed",
    ),
    # an unknown scope falls back to the conservative 'any' policy
    ("occ-weird-scope", "occupant", {"scope": "basement", "n_sensors": 3}, RESTRICT, "≥14 sensors"),
    # admins have no k-floors
    ("admin-single-sensor", "admin", {"n_sensors": 1, "n_spaces": 1}, ALLOW, "allowed"),
]


@pytest.mark.parametrize(
    "case_id,role,kwargs,decision,fragment", MATRIX, ids=[m[0] for m in MATRIX]
)
def test_verdict_matrix(case_id, role, kwargs, decision, fragment):
    v = _engine().evaluate(role, **kwargs)
    assert v.decision == decision, f"{case_id}: {v.reason}"
    assert fragment.lower() in (v.reason or "").lower()
    if decision != DENY or "no access policy" not in v.reason:
        assert v.policy_iri or decision == DENY
    if decision == DENY:
        assert v.alternative, f"{case_id}: every deny must offer a nearest-allowed alternative"


def test_verdicts_are_deterministic():
    eng = _engine()
    a = eng.evaluate("facility_manager", data_age_minutes=30, requested_resolution_s=5)
    b = eng.evaluate("facility_manager", data_age_minutes=30, requested_resolution_s=5)
    assert (a.decision, a.reason, a.policy_iri, a.resolution_s) == (
        b.decision,
        b.reason,
        b.policy_iri,
        b.resolution_s,
    )


def test_verdict_carries_provenance():
    v = _engine().evaluate("occupant", n_sensors=3)
    assert v.policy_iri.endswith("p_occupant")
    assert v.parameters["role"] == "occupant"
    assert v.min_sensors == 14 and v.min_spaces == 7


def test_rate_limit_sliding_window():
    t = {"now": 1000.0}
    eng = _engine(clock=lambda: t["now"])
    for i in range(3):
        assert eng.evaluate("facility_manager", user_id="u1").decision == ALLOW
    v = eng.evaluate("facility_manager", user_id="u1")
    assert v.decision == DENY and "rate limit" in v.reason and "retry" in v.alternative
    # another user is unaffected
    assert eng.evaluate("facility_manager", user_id="u2").decision == ALLOW
    # window slides — allowed again
    t["now"] += 61.0
    assert eng.evaluate("facility_manager", user_id="u1").decision == ALLOW


def test_rate_limit_ignored_without_user_id():
    eng = _engine()
    for _ in range(5):
        assert eng.evaluate("facility_manager").decision == ALLOW


def test_tier_parser():
    assert _parse_tiers("15:5,60:60,10080:3600") == [(15.0, 5.0), (60.0, 60.0), (10080.0, 3600.0)]
    assert _parse_tiers("0:1") == [(0.0, 1.0)]
    assert _parse_tiers("garbage") == []
