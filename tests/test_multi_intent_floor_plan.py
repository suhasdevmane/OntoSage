"""
Integration test for opt-in floor_plan semantic intent (multi-intent extension).

Spec: docs/superpowers/specs/2026-05-22-multi-intent-semantic-routing.md

This test validates the NON-REGRESSION contract: with floor_plan semantic routing
OFF (which is the default and current bldg1 state), all the 2026-05-20 floor-N
hijack protections still hold.

When/if floor_plan descriptors are enabled in input/<bldg>/building.yaml later,
a separate test will verify the opt-in path. That's a Phase B of the multi-intent
rollout — see spec §"Phased rollout".
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.live


def test_floor_plan_intent_not_registered_by_default(chat_client):
    """In the current bldg1 state, intent_routing.floor_plan is NOT configured.
    The admin endpoint should report only 'capability' in router_intents.

    This is the non-regression contract: extending the router schema must not
    silently enable extra intents.
    """
    r = requests.get(f"{chat_client.base}/api/v1/admin/capability-indexer/status", timeout=10)
    assert r.status_code == 200
    intents = r.json()["data"].get("router_intents", [])
    assert "capability" in intents, "capability must remain registered"
    # Default state: no extra intents
    extras = [i for i in intents if i != "capability"]
    assert extras == [], (
        f"Unexpected extra intents registered without opt-in: {extras}. "
        "If you enabled intent_routing in building.yaml, this is expected; "
        "otherwise the lifespan logic has a bug (auto-registering disabled intents)."
    )


def test_floor_n_protection_still_holds_with_multi_intent_code(chat_client, fresh_session_id):
    """Sanity: the floor-N hijack protections must continue working with the
    intent-agnostic SemanticRouter refactor in place (even with no extra intents
    enabled)."""
    resp = chat_client.chat("What is the temperature on floor 3?", session_id=fresh_session_id)
    assert resp.success
    assert not resp.contains(
        "I have floor plans for"
    ), "Floor-N hijack regression — multi-intent refactor must not break §15.2"


def test_capability_still_wins_with_no_extras(chat_client, fresh_session_id):
    """The intent-agnostic refactor must not break the existing capability path
    when no extra intents are registered."""
    resp = chat_client.chat(
        "What are the lift dimensions and weight limit?", session_id=fresh_session_id
    )
    assert resp.success
    assert resp.contains_any("1000 kg", "1000kg", "106 cm", "lift", "dimensions")
    assert not resp.contains("ontology data does not provide")
