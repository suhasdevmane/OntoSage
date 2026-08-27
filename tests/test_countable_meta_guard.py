# -*- coding: utf-8 -*-
"""A quantity of a metered resource is not a census of devices (BUG-266, 2026-08-27).

``_is_countable_meta`` returned True for *"How much electricity does the lab on
floor 5 use?"*. The question contains "how much" (a count trigger) and "floor" (a
structure word), which was enough for the guard to call it a device count. Any
rule deferring to that guard would drop a straightforward consumption question.

It was WORKED AROUND rather than fixed: ``consumption_question`` stated the rule
itself and pre-empted the guard, on the reasoning that narrowing the shared guard
would risk the counting behaviour it owns. That left one decision with two
owners, which is the drift this contract exists to prevent — so the rule now
lives in the guard and the caller agrees with it.

The counting behaviour is pinned FIRST here, because that is what the narrowing
could plausibly have broken.
"""

import pytest

from orchestrator.services.routing_contract import _is_countable_meta, consumption_question

pytestmark = pytest.mark.unit


def _meta(q: str) -> bool:
    return _is_countable_meta(q.lower())


# ── the counting behaviour the guard owns, unchanged ─────────────────────────
@pytest.mark.parametrize(
    "question",
    [
        "How many sensors are on floor 5?",
        "How many temperature sensors does this building have?",
        "How many floors does this building have?",
        "How many energy meters are there?",
        "How many zones are on level 3?",
        "What building is this?",
        "Tell me about this building",
        "Number of devices in the building",
    ],
)
def test_a_census_is_still_a_census(question):
    assert _meta(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "How many rooms are on floor 2?",  # geometry keeps it on spatial_query
        "How big is room 5.01?",
    ],
)
def test_geometry_questions_are_still_excluded(question):
    assert _meta(question) is False


# ── and the quantity questions it used to claim ──────────────────────────────
@pytest.mark.parametrize(
    "question",
    [
        "How much electricity does the lab on floor 5 use?",
        "How much water was used on floor 3 last week?",
        "How much gas did the building use in June?",
        "How much energy did level 2 consume yesterday?",
        "How much power is floor 0 drawing?",
    ],
)
def test_a_quantity_of_a_metered_resource_is_not_a_census(question):
    assert _meta(question) is False


def test_a_resource_question_that_names_a_device_keeps_counting():
    """ "How much energy do the meters use?" names a countable device, so the
    counting behaviour this guard owns still applies. Suppressing it there would
    trade one false positive for another."""
    assert _meta("How much energy do the meters use?") is True


def test_building_identity_still_wins_inside_a_resource_question():
    """The identity shape is unconditional; a resource word must not suppress it."""
    assert _meta("How much energy does it use — and what building is this?") is True


# ── the caller now agrees with the guard rather than pre-empting it ──────────
@pytest.mark.parametrize(
    "question",
    [
        "How much electricity does the lab on floor 5 use?",
        "How much water was used on floor 3 last week?",
    ],
)
def test_consumption_and_the_guard_no_longer_disagree(question):
    """They gave opposite answers about the same sentence, and only the order of
    the checks decided which one the router believed."""
    assert consumption_question(question) is True
    assert _meta(question) is False


def test_a_census_is_not_a_consumption_question():
    assert consumption_question("How many energy meters are there?") is False


def test_the_rule_is_stated_once():
    """Two copies of one rule is how they drifted. The guard owns it; the caller
    may agree with it, but the guard must be where it is decided."""
    import inspect

    from orchestrator.services import routing_contract as rc

    src = inspect.getsource(rc._is_countable_meta)
    assert "_QUANTITY_NOT_CENSUS_RE" in src, "the guard must make this decision itself"
