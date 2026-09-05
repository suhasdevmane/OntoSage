# -*- coding: utf-8 -*-
"""A suggestion offered instead of a missing thing must be the same kind of thing.

When the referent gate refuses, it adds "What this building does have: ...". That sentence
is offered IN PLACE OF the space or asset the user asked about, so a suggestion of the wrong
kind is not a smaller answer — it is a different one, delivered in exactly the moment the
system is being careful.

Measured live before this fix:

    "verified corridor" -> "CCTV Corridor F1, CCTV Corridor F2, ..."   (cameras)
    "lift lobby"        -> "CHK-301, CHK-302, CHK-303"                 (patrol checkpoints)
    "room"              -> "Alcohol Vapor MQ3 Gas Sensor 5.01, ..."    (gas sensors)

Every one matched only because its NAME contains the word. `_suggest_terms` searched every
typed entity in the namespace and never asked what kind of thing the question was about,
although the resolver knew — `TypedReferent.kind` was sitting in the caller.

After: a space referent suggests only entities beneath `brick:Location`, an equipment
referent only entities beneath `brick:Equipment`. Verified live: "is chiller 7 running?"
now suggests "Chiller 1" and "PUMP-CH1" rather than anything merely named after a chiller.

HONEST RESIDUAL: for a FLOOR referent the suggestions are Locations, but include fire exits
whose LABELS carry "Floor 1 North". They are at least locations now; narrowing further would
need a floor-specific class test, which is not done and is not claimed here.
"""

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import referent_resolver as rr  # noqa: E402


def test_a_root_is_declared_for_each_physical_kind():
    for kind in (rr.KIND_SPACE, rr.KIND_FLOOR, rr.KIND_EQUIPMENT):
        assert kind in rr.ReferentResolver._SUGGEST_ROOT, (
            f"{kind} has no suggestion root, so its suggestions are unfiltered again"
        )


def test_space_and_equipment_do_not_share_a_root():
    roots = rr.ReferentResolver._SUGGEST_ROOT
    assert roots[rr.KIND_SPACE] != roots[rr.KIND_EQUIPMENT], (
        "a space referent and an equipment referent must not draw from the same pool, or "
        "a missing corridor can be answered with a chiller"
    )
    assert roots[rr.KIND_SPACE].endswith("Location")
    assert roots[rr.KIND_EQUIPMENT].endswith("Equipment")


def test_the_query_constrains_the_class_when_a_kind_is_known():
    import inspect

    src = inspect.getsource(rr.ReferentResolver._suggest_terms)
    assert "rdfs:subClassOf*" in src, (
        "the suggestion query no longer constrains the class; it will match any entity "
        "whose name happens to contain the word"
    )
    assert "_SUGGEST_ROOT" in src


def test_an_unknown_kind_still_returns_suggestions():
    """Degrade to the old behaviour rather than to silence.

    A measurand referent has no physical root, and returning nothing for it would remove a
    working hint to fix a different problem.
    """
    import inspect

    src = inspect.getsource(rr.ReferentResolver._suggest_terms)
    assert 'if root else ""' in src, (
        "an unknown kind must drop the filter, not the suggestions"
    )


def test_the_caller_passes_the_kind():
    """The kind was already known one frame up; the bug was never a missing signal."""
    import inspect

    src = inspect.getsource(rr.ReferentResolver._resolve_typed)
    assert "typed.kind" in src, (
        "_resolve_typed no longer passes the referent kind, so the filter cannot apply"
    )
