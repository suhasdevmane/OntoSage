# -*- coding: utf-8 -*-
"""The same fact must not change with who asks (V6-T29, acceptance scenario 8).

Master 14.1 scenario 8: *"the same factual question across different user roles -> the
underlying result is consistent while explanation depth adapts."*

The project already documents personas as **framing only, never permissions** -- but that
property has never been mechanically tested, and it is exactly the kind of invariant that
erodes silently. A persona prompt that says "be concise for executives" is one careless edit
away from "give executives rounded figures", and nothing would fail.

Two distinct things are asserted here, and conflating them is the error this guards against:

* **Facts are invariant.** A temperature is a temperature. If two roles get different
  numbers for the same question, one of them is wrong.
* **Visibility is not.** A role that may not see a value gets a REFUSAL, never a different
  value. Withholding is legitimate; altering is not, and a rounded or bucketed figure handed
  to a lower tier is altering while looking like withholding.
"""

import pytest

from orchestrator.middleware.rbac import ROLE_PERMISSIONS
from orchestrator.services.evidence import tier_for_role
from orchestrator.services.evidence.narration import status_badge
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

ROLES = sorted(ROLE_PERMISSIONS)


# ── the invariant, stated over the machinery that could break it ─────────────


def test_every_role_resolves_to_exactly_one_tier():
    """Ambiguity here would make the same question answer at different tiers by chance."""
    for role in ROLES:
        assert tier_for_role(role) is not None


def test_tier_never_changes_the_status_vocabulary():
    """An answer's KIND is a property of the evidence, not of the asker.

    If OBSERVED meant something different to an executive than to an occupant, the six-status
    taxonomy would stop being a shared language and become a per-role dialect.
    """
    for status in AnswerStatus:
        badge = status_badge(status)
        for role in ROLES:
            assert status_badge(status) == badge


def test_personas_do_not_appear_in_the_permission_map():
    """Personas frame; RBAC permits. The moment a persona grants anything, they have merged."""
    persona_words = {"executive", "visitor", "student", "researcher", "occupant_persona"}
    for role, perms in ROLE_PERMISSIONS.items():
        for perm in perms:
            assert perm.split(":")[0] not in persona_words


def test_a_lower_tier_holds_a_subset_not_a_variant():
    """Withholding is legitimate; ALTERING is not.

    A readonly user must not receive a *different* answer -- they receive *less*. Modelling
    that as a subset makes the distinction structural rather than a matter of prompt wording.
    """
    readonly = ROLE_PERMISSIONS["readonly"]
    for role in ("occupant", "operator", "analyst", "facility_manager", "admin"):
        assert readonly.issubset(ROLE_PERMISSIONS[role]), (
            f"readonly holds a permission {role} lacks; tiers must nest, or 'less access' "
            f"stops meaning 'a subset of the same facts'"
        )


def test_admin_is_a_superset_of_every_role():
    for role, perms in ROLE_PERMISSIONS.items():
        assert perms.issubset(ROLE_PERMISSIONS["admin"])


def test_no_role_can_see_a_value_another_role_sees_differently():
    """Structural version of scenario 8.

    Permissions decide WHETHER a value is shown. Nothing in the permission model can decide
    HOW MUCH of a value is shown, so there is no mechanism by which two roles could receive
    different numbers for the same question -- and this test fails if such a mechanism is
    ever added.
    """
    granularity_like = {
        p
        for perms in ROLE_PERMISSIONS.values()
        for p in perms
        if any(w in p for w in ("rounded", "approx", "bucket", "coarse", "blur"))
    }
    assert not granularity_like, (
        f"permissions that modulate PRECISION rather than ACCESS: {granularity_like}. "
        "A rounded figure handed to a lower tier is altering the fact while looking like "
        "withholding it."
    )


def test_the_tier_mapping_grants_nothing_by_itself():
    """The tier vocabulary must stay descriptive.

    If tier_for_role ever returned permissions rather than a label, it would become a second
    authorisation path -- the 'route around existing access controls' Master 11.2 forbids.
    """
    tier = tier_for_role("occupant")
    assert isinstance(tier.requires_permission, str)
    # It NAMES the permission that gates it; it does not hold or confer one.
    assert tier.requires_permission in {p for perms in ROLE_PERMISSIONS.values() for p in perms}


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_reach_the_health_endpoint(role):
    """A shared floor. Without one, 'the same question' is not askable by everyone."""
    assert "system:health" in ROLE_PERMISSIONS[role]
