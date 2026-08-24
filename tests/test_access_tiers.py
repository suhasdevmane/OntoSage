# -*- coding: utf-8 -*-
"""Master Report access tiers mapped onto OntoSage RBAC (V6-T28).

The point of the mapping is that the supervisors' specification and the implementation can be
checked against each other. These tests are that check, and the load-bearing one is
`test_every_role_listed_in_a_tier_actually_holds_its_permission`: a mapping that claims a role
answers at a tier it cannot reach would make every EvidenceRecord's access_tier a lie.

The mapping must never become an authorisation path. `require_permission()` stays the only
gate; Master 11.2 requires the conversational layer to enforce the SAME permissions as the
underlying systems, and a second path is precisely the "route around existing access controls"
it warns about.
"""

from pathlib import Path

import pytest
import yaml

from orchestrator.middleware.rbac import ALL_PERMISSIONS, ROLE_PERMISSIONS
from orchestrator.services.evidence.access_tiers import (
    all_tiers,
    permission_for_tier,
    tier_for_role,
    tier_for_shape,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CFG = REPO / "config" / "access_tiers.yaml"


def test_all_six_master_report_tiers_are_present():
    names = set(all_tiers())
    assert names == {
        "public",
        "occupant",
        "operational",
        "security_safety",
        "research",
        "strategic",
    }


def test_tiers_are_ranked_uniquely():
    """Rank makes 'at least tier X' answerable; duplicates make it ambiguous."""
    ranks = [t.rank for t in all_tiers().values()]
    assert sorted(ranks) == list(range(len(ranks)))


def test_every_role_listed_in_a_tier_actually_holds_its_permission():
    """The load-bearing consistency check.

    A tier claiming a role can answer at it, when that role lacks the permission, would make
    every EvidenceRecord.access_tier a claim the authorisation system does not support.
    """
    mismatches = [
        (tier.name, role, tier.requires_permission)
        for tier in all_tiers().values()
        for role in tier.roles
        if tier.requires_permission not in ROLE_PERMISSIONS.get(role, set())
    ]
    assert not mismatches, f"tier/role permission mismatches: {mismatches}"


def test_every_tier_permission_is_a_real_permission():
    """A typo here silently maps a tier to a permission nothing grants."""
    for tier in all_tiers().values():
        assert tier.requires_permission in ALL_PERMISSIONS, tier.requires_permission


def test_every_role_maps_to_some_tier():
    for role in ROLE_PERMISSIONS:
        assert tier_for_role(role) is not None


def test_an_unknown_role_falls_back_to_public_not_upward():
    """The floor, never a guess upward - an unmapped role must not gain scope."""
    assert tier_for_role("some_role_that_does_not_exist").name == "public"


def test_a_role_in_several_tiers_resolves_to_the_broadest():
    """Documented behaviour: a role that can answer at several tiers records the widest."""
    assert tier_for_role("admin").rank == max(t.rank for t in all_tiers().values())


def test_shape_can_fix_a_tier_regardless_of_asker():
    """An access-event query is a security-tier question no matter who asks it."""
    assert tier_for_shape("access_events").name == "security_safety"
    assert tier_for_shape("wayfinding").name == "public"


def test_shape_that_does_not_fix_a_tier_returns_none():
    """None means 'the asker's role decides', not 'public'."""
    assert tier_for_shape("sensor_data") is None
    assert tier_for_shape("") is None


def test_strategic_does_not_imply_security_access():
    """Breadth of view is not a reason to read door records.

    The rank ladder is about scope, not trust. If strategic ever came to imply
    security_safety, an executive dashboard would inherit access-event visibility.
    """
    tiers = all_tiers()
    assert tiers["strategic"].rank > tiers["security_safety"].rank
    # ...and they are gated by different permissions, so rank alone grants nothing.
    assert tiers["strategic"].requires_permission != tiers["security_safety"].requires_permission


def test_config_documents_that_it_maps_rather_than_grants():
    text = CFG.read_text(encoding="utf-8")
    assert "DOES NOT GRANT" in text or "does not grant" in text
    assert "require_permission" in text


def test_every_tier_carries_a_description():
    for tier in all_tiers().values():
        assert len(tier.description) > 40, f"{tier.name} needs a usable description"


def test_config_cites_its_source():
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    assert "Table 15" in cfg["citation"]


def test_permission_for_unknown_tier_is_the_narrowest():
    assert permission_for_tier("no_such_tier") == "metadata:read"
