# -*- coding: utf-8 -*-
"""The response cache must never serve one requester's answer to another (BUG-368).

Measured live on bldg1, 2026-08-31, before the fix: an occupant asked for a room-level
temperature and was correctly refused above the k-anonymity floor; a facility_manager
then asked the same words and was served the occupant's refusal; and with the order
reversed the occupant received the facility manager's room-level reading verbatim — the
very figure the PDP had just denied them.

The PROTECT traps never caught it because they run as a single user, so nothing in the
suite ever put two roles behind one question. These tests do exactly that, at the level
where the defect lived: the cache key.
"""

from __future__ import annotations

import pytest

from orchestrator.services.response_cache import ResponseCacheService

pytestmark = pytest.mark.unit


def _partition(role: str, user: str = "", building: str = "bldg1") -> str:
    return ResponseCacheService._partition(building, role, user)


def test_two_roles_never_share_a_partition():
    """A facility manager and an occupant must not read each other's answers."""
    assert _partition("facility_manager", "alice") != _partition("occupant", "bob")


def test_the_leak_direction_that_was_measured():
    """occupant -> facility_manager and back: neither may reach the other's entry."""
    occupant = _partition("occupant", "replaytest")
    manager = _partition("facility_manager", "v7fmtest")
    assert occupant != manager
    # and neither is a prefix of the other, so a pattern flush of one cannot
    # silently match the other's keys
    assert not occupant.startswith(manager)
    assert not manager.startswith(occupant)


def test_individually_scoped_roles_are_partitioned_per_person():
    """Two occupants asking 'my office' mean two different rooms.

    The occupant policy is scoped to `own` spaces, so identical words are owed
    different answers. Role alone would let one occupant read the other's.
    """
    assert _partition("occupant", "alice") != _partition("occupant", "bob")


def test_building_wide_roles_share_across_people():
    """Roles whose policy is scoped to `any` space get one partition, not one each.

    This is the whole hit rate: two facility managers asking the same question are
    owed the same answer, and partitioning them apart would buy no safety.
    """
    assert _partition("facility_manager", "alice") == _partition("facility_manager", "bob")


def test_an_absent_role_is_treated_as_individually_scoped():
    """No role is the least privilege, not the most.

    An unauthenticated or unresolved caller must not land in a shared partition where
    it could read a privileged answer — the failure mode is silent, so the default has
    to be the safe one.
    """
    assert _partition("", "alice") != _partition("", "bob")
    assert _partition("", "alice") != _partition("facility_manager", "alice")


def test_role_is_case_and_space_insensitive():
    """'Facility_Manager' and 'facility_manager' are one role, not two partitions."""
    assert _partition("  Facility_Manager ", "x") == _partition("facility_manager", "x")


def test_partitions_stay_inside_their_building():
    """Two buildings never share a partition, whatever the role."""
    assert _partition("facility_manager", "a", "bldg1") != _partition(
        "facility_manager", "a", "bldg2"
    )
