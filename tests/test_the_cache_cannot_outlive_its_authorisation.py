# -*- coding: utf-8 -*-
"""A cached answer cannot bypass the authorisation or the code that produced it.

V12-16, review case B12 — *"If a cache exists, change permissions or building scope before
reusing an answer. The cache cannot bypass the current authorisation and provenance
policy."* B12 applies here precisely because a cache exists: `resp_cache` holds an answer
for an hour, and if it can be served to an identity whose permitted scope differs from the
one that filled it, the permission check is decorative.

TWO SEPARATE FAILURES, ONE KEY
------------------------------
**Who.** Measured before this session: with role absent from the key, an occupant asked a
room-level temperature question and was correctly refused above the k-anonymity floor; a
facility manager then asked the same words and was served the occupant's refusal. With the
order reversed, the occupant received the facility manager's room-level reading verbatim —
the very figure the PDP had just denied them. The leak traps never caught it because they
run as a single user.

**Under what code.** Measured 2026-09-10 (BUG-498): a dishonest answer came back in 0.9 s —
a cache hit — from a revision whose guard had since been fixed and redeployed. The running
code would not have produced it. The cache did.

WHY A KEY COMPONENT AND NOT A FLUSH
-----------------------------------
`policy_admin.invalidate_policy_caches` already flushes on a policy edit, and that is
useful. But it is wrapped in try/except and logs a warning when the cache object is
missing, so it fails OPEN — stale answers stay servable and nothing says so. A key
component fails CLOSED: a changed signature is simply a miss, with nothing for anyone to
remember to do.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import response_cache as rc  # noqa: E402

R = rc.ResponseCacheService


# ── who is asking ────────────────────────────────────────────────────────────


def test_two_people_in_an_individually_scoped_role_do_not_share_a_partition():
    """"What is the temperature in my office" is one question and two rooms."""
    assert R._partition("bldg1", "occupant", "alice") != R._partition(
        "bldg1", "occupant", "bob"
    )


def test_a_narrower_identity_misses_rather_than_hits():
    """B12's explicit requirement. An occupant must not read a facility manager's entry."""
    manager = R._partition("bldg1", "facility_manager", "alice")
    occupant = R._partition("bldg1", "occupant", "alice")
    assert manager != occupant, (
        "the same person under a narrower role would hit the wider role's cached answer"
    )


def test_a_different_building_never_shares_a_partition():
    assert R._partition("bldg1", "occupant", "alice") != R._partition(
        "bldg2", "occupant", "alice"
    )


def test_roles_with_estate_wide_scope_may_share():
    """Not every distinction is worth a cache miss: two facility managers are owed the
    same answer, and splitting them would cost hit rate for nothing."""
    assert R._partition("bldg1", "facility_manager", "alice") == R._partition(
        "bldg1", "facility_manager", "bob"
    )


# ── under what code (BUG-498) ────────────────────────────────────────────────


def test_the_partition_carries_the_revision():
    assert R._partition("bldg1", "occupant", "alice").endswith(f"|r{rc.REVISION}")


def test_an_answer_from_another_revision_is_unreachable():
    """The BUG-498 scenario, as a key comparison: fix the code, redeploy, and the old
    entry can no longer be found — without anyone remembering to flush."""
    before = R._partition("bldg1", "occupant", "alice", revision="deadbeef0001")
    after = R._partition("bldg1", "occupant", "alice", revision="deadbeef0002")
    assert before != after


def test_the_revision_is_derived_not_hardcoded():
    """It must change when the deployment changes. BUILD_SHA when the image carries one;
    process boot otherwise, because /app/orchestrator is bind-mounted here and a restart
    IS a deployment."""
    assert rc.REVISION, "an empty revision would silently disable this protection"
    assert rc.REVISION != "unknown", (
        "BUILD_SHA is literally 'unknown' in this deployment; using it verbatim would "
        "pin every build to one partition and restore BUG-498"
    )


# ── the thing that must keep working ─────────────────────────────────────────


def test_partition_blind_invalidation_still_matches_every_partition():
    """`invalidate` deliberately sweeps `{building_id}|*` while lookup is partition-bound.
    Putting the revision anywhere but LAST would break that, and a policy edit would stop
    clearing anything."""
    import inspect

    src = inspect.getsource(R.invalidate)
    assert '{building_id}|' in src or "building_id}|" in src

    for role, user in [("occupant", "alice"), ("facility_manager", ""), ("", "bob")]:
        part = R._partition("bldg1", role, user)
        assert part.startswith("bldg1|"), f"{part} would escape a building-wide flush"


def test_the_key_is_still_a_single_flat_string():
    """Redis keys are strings; a partition containing a newline or a wildcard would break
    both lookup and the sweep."""
    part = R._partition("bldg1", "occupant", "alice")
    for bad in ("\n", "\r", " ", "*", "?"):
        assert bad not in part, f"partition contains {bad!r}: {part!r}"


def test_a_policy_edit_still_flushes_as_well_as_keying():
    """Belt and braces on purpose. The key protects against a MISSED flush; the flush
    protects against a policy change that does not alter the revision — which is every
    policy change, since editing a policy does not redeploy the code."""
    import inspect

    from orchestrator.services import policy_admin

    src = inspect.getsource(policy_admin.invalidate_policy_caches)
    assert "response_cache" in src and "flush_all=True" in src, (
        "a policy edit no longer clears the response cache, and the revision in the key "
        "will not catch it — editing a policy does not change the code revision"
    )
