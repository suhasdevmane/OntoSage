# -*- coding: utf-8 -*-
"""V5-T43: policies are authored through the GUI, but guarantees are not weakened by accident.

The 0-leak certification rests on these triples. A form that lets an operator drop
a k-anonymity floor with one keystroke, or delete "never identify individuals",
would turn a certified property into a configuration accident. These tests pin
the two refusals and the TTL that gets written.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services.policy_admin import (
    build_policy_ttl,
    create_policy,
    delete_policy,
    diff_weakening,
    known_roles,
    validate_policy_fields,
)

pytestmark = pytest.mark.unit


def _fields(**over):
    base = {
        "id": "policy_occupant_full",
        "role": "occupant",
        "scope_spaces": "any",
        "min_sensors": 3,
        "min_spaces": 2,
        "tiers": "0:900,60:60",
        "rate_max": 20,
        "rate_window_min": 5,
        "comment": "Occupants get coarse aggregates only.",
    }
    base.update(over)
    return base


# ── validation ───────────────────────────────────────────────────────────────


def test_roles_come_from_rbac_not_a_hardcoded_list():
    roles = known_roles()
    assert "*" in roles and "occupant" in roles and "admin" in roles


@pytest.mark.parametrize(
    "over, fragment",
    [
        ({"id": "9bad"}, "invalid policy id"),
        ({"id": "has space"}, "invalid policy id"),
        ({"role": "wizard"}, "unknown role"),
        ({"min_sensors": 0}, "at least 1"),
        ({"min_spaces": -3}, "at least 1"),
        ({"min_sensors": "abc"}, "whole number"),
        ({"tiers": "nonsense"}, "minutes:seconds"),
        ({"rate_max": -1}, "0 or more"),
    ],
)
def test_incoherent_forms_are_refused_with_a_reason(over, fragment):
    assert fragment in (validate_policy_fields(_fields(**over)) or "")


def test_a_coherent_form_passes():
    assert validate_policy_fields(_fields()) is None


# ── the individual-privacy line ──────────────────────────────────────────────


def test_an_inference_class_may_only_be_authored_as_deny():
    err = validate_policy_fields(
        {"id": "p_inf", "role": "*", "inference_class": "individual_presence:allow"}
    )
    assert "only be authored as ':deny'" in err
    assert "never tracks individuals" in err


def test_a_deny_inference_class_is_accepted():
    assert (
        validate_policy_fields(
            {"id": "p_inf", "role": "*", "inference_class": "individual_presence:deny"}
        )
        is None
    )


def test_a_malformed_inference_class_is_refused():
    err = validate_policy_fields({"id": "p_inf", "role": "*", "inference_class": "garbage"})
    assert "individual_presence:deny" in err


# ── weakening detection ──────────────────────────────────────────────────────


def test_no_previous_policy_means_nothing_is_being_weakened():
    assert diff_weakening(None, _fields()) == []


def test_tightening_is_not_flagged():
    old = {"min_sensors": 2, "min_spaces": 1, "rate_max": 100, "tiers": "0:60"}
    new = {"min_sensors": 5, "min_spaces": 3, "rate_max": 10, "tiers": "0:900"}
    assert diff_weakening(old, new) == []


def test_lowering_a_k_floor_is_flagged_with_both_values():
    out = diff_weakening({"min_sensors": 5}, {"min_sensors": 2})
    assert out == ["sensor k-anonymity floor lowered 5 -> 2"]


def test_removing_a_rate_limit_is_flagged_as_unlimited():
    out = diff_weakening({"min_sensors": 1, "rate_max": 10}, {"min_sensors": 1, "rate_max": 0})
    assert any("unlimited" in o for o in out)


def test_sharpening_a_resolution_tier_is_flagged_as_finer_data():
    out = diff_weakening(
        {"min_sensors": 1, "tiers": "0:900,60:60"}, {"min_sensors": 1, "tiers": "0:60,60:60"}
    )
    assert any("finer data released" in o for o in out)


def test_every_weakening_is_listed_not_just_the_first():
    out = diff_weakening(
        {"min_sensors": 5, "min_spaces": 4, "rate_max": 10, "tiers": "0:900"},
        {"min_sensors": 2, "min_spaces": 1, "rate_max": 0, "tiers": "0:30"},
    )
    assert len(out) == 4


# ── rendered TTL ─────────────────────────────────────────────────────────────


def test_rendered_ttl_carries_the_floors_and_parses():
    from rdflib import Graph

    built = build_policy_ttl("tb", _fields(), actor="alice")
    assert built["ok"]
    g = Graph()
    g.parse(data=built["ttl"], format="turtle")
    assert len(g) >= 6
    body = built["ttl"]
    assert "ontosage:AccessPolicy" in body
    assert "ontosage:minAggregationSensors 3" in body
    assert "ontosage:minAggregationSpaces 2" in body
    assert '"20:5"' in body  # rate limit serialization


def test_the_ttl_records_who_authored_it():
    built = build_policy_ttl("tb", _fields(), actor="alice")
    assert "authored in the admin policy editor by alice" in built["ttl"]


def test_a_quote_in_the_comment_cannot_break_the_turtle():
    from rdflib import Graph

    built = build_policy_ttl("tb", _fields(comment='he said "hi"\nand left'), actor="bob")
    assert built["ok"]
    Graph().parse(data=built["ttl"], format="turtle")  # must not raise


def test_an_inference_policy_omits_floors_it_does_not_use():
    built = build_policy_ttl(
        "tb", {"id": "p_inf", "role": "*", "inference_class": "individual_presence:deny"}
    )
    assert built["ok"]
    assert "inferenceClass" in built["ttl"]
    assert "minAggregationSensors" not in built["ttl"]


# ── the create/delete guards (no graph needed: list_policies is stubbed) ──────


def _stub_existing(monkeypatch, rows):
    async def _fake_list(building_id, client=None):
        return rows

    monkeypatch.setattr("orchestrator.services.policy_admin.list_policies", _fake_list)


def test_creating_a_weaker_policy_is_refused_until_acknowledged(monkeypatch):
    _stub_existing(
        monkeypatch,
        [{"id": "policy_occupant_full", "inference_class": "", "min_sensors": 5, "min_spaces": 2}],
    )
    res = asyncio.run(create_policy("tb", _fields(min_sensors=2), actor="alice"))
    assert res["ok"] is False
    assert "weakens a privacy guarantee" in res["error"]
    assert res["weakened"] == ["sensor k-anonymity floor lowered 5 -> 2"]


def test_an_inference_policy_cannot_be_edited_through_the_gui(monkeypatch):
    _stub_existing(
        monkeypatch,
        [
            {
                "id": "policy_inference_individual_presence",
                "inference_class": "individual_presence:deny",
            }
        ],
    )
    res = asyncio.run(
        create_policy("tb", _fields(id="policy_inference_individual_presence"), actor="alice")
    )
    assert res["ok"] is False
    assert "cannot be edited here" in res["error"]


def test_an_inference_policy_cannot_be_deleted_through_the_gui(monkeypatch):
    _stub_existing(
        monkeypatch,
        [{"id": "policy_inf", "inference_class": "individual_presence:deny"}],
    )
    res = asyncio.run(delete_policy("tb", "policy_inf", actor="alice"))
    assert res["ok"] is False
    assert "answer questions about individuals" in res["error"]


def test_delete_rejects_a_malformed_id():
    res = asyncio.run(delete_policy("tb", "../../etc/passwd"))
    assert res["ok"] is False and "invalid policy id" in res["error"]
