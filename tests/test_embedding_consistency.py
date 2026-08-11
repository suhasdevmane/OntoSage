# -*- coding: utf-8 -*-
"""One boot-time answer to "do all the vector stores match the model?"

Every indexer checks the collection IT owns, but only when that indexer runs. A
building that is parked, documents that are unchanged, floor plans already
ingested — none of those get looked at, so a mismatch introduced by swapping the
embedding model sits there until a user gets an empty answer. Comparing vectors of
different widths returns no rows rather than raising, so the symptom is silence.

The sweep enumerates whatever collections EXIST rather than a list of expected
names, which is what makes it work for a building onboarded tomorrow.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services.embedding_consistency import check_embedding_consistency

pytestmark = pytest.mark.unit


def _qdrant(collections: dict, fail_on=()):
    """collections: {name: width or None}."""
    dropped = []

    class _Q:
        async def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in collections])

        async def get_collection(self, name):
            if name in fail_on:
                raise RuntimeError("unreadable")
            width = collections[name]
            return SimpleNamespace(
                config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=width)))
            )

        async def delete_collection(self, name):
            dropped.append(name)

    return _Q(), dropped


async def test_a_consistent_instance_changes_nothing():
    q, dropped = _qdrant({"documents_bldg1": 1024, "floor_plans": 1024, "user_memory": 1024})
    report = await check_embedding_consistency(q, 1024, "bge-large")

    assert report.mismatched == []
    assert dropped == [], "a matching collection must never be destroyed"
    assert "matching" in report.summary()


async def test_a_stale_derived_collection_is_dropped_so_it_rebuilds():
    q, dropped = _qdrant({"documents_bldg2": 384, "documents_bldg1": 1024})
    report = await check_embedding_consistency(q, 1024, "bge-large")

    assert dropped == ["documents_bldg2"]
    assert [c.name for c in report.mismatched] == ["documents_bldg2"]
    assert report.mismatched[0].action == "dropped"


async def test_irreplaceable_data_is_reported_never_deleted():
    """user_memory holds what people told the assistant. An unusable collection is
    bad; deleting the only copy of something is worse, and that call belongs to its
    owner rather than to a boot sweep."""
    q, dropped = _qdrant({"user_memory": 384})
    report = await check_embedding_consistency(q, 1024, "bge-large")

    assert dropped == [], "user memory must not be silently destroyed"
    assert report.mismatched[0].action == "reported"


@pytest.mark.parametrize(
    "name,rebuildable",
    [
        ("documents_bldg7", True),
        ("capability_bldg7", True),
        ("floor_plans", True),
        ("brick_schema", True),
        ("user_memory", False),
        ("something_someone_added", False),
    ],
)
async def test_only_regenerable_stores_are_dropped(name, rebuildable):
    q, dropped = _qdrant({name: 384})
    await check_embedding_consistency(q, 1024, "bge-large")
    assert (dropped == [name]) is rebuildable


async def test_a_building_nobody_has_seen_yet_is_covered():
    """Collections are enumerated, not looked up against expected names — so a
    building onboarded tomorrow is checked the moment it creates one."""
    q, dropped = _qdrant({"documents_a_brand_new_site": 384})
    await check_embedding_consistency(q, 1024, "bge-large")
    assert dropped == ["documents_a_brand_new_site"]


async def test_an_empty_instance_is_not_an_error():
    q, dropped = _qdrant({})
    report = await check_embedding_consistency(q, 1024, "bge-large")
    assert report.collections == [] and dropped == []
    assert "no vector collections" in report.summary()


async def test_an_unreadable_collection_does_not_stop_the_sweep():
    q, dropped = _qdrant(
        {"documents_bldg1": 1024, "documents_bldg2": 384}, fail_on=("documents_bldg1",)
    )
    await check_embedding_consistency(q, 1024, "bge-large")
    assert dropped == ["documents_bldg2"], "the rest of the sweep must still run"


async def test_qdrant_being_down_is_survivable():
    """Boot must not fail because the check could not run."""

    class _Dead:
        async def get_collections(self):
            raise RuntimeError("qdrant unreachable")

    report = await check_embedding_consistency(_Dead(), 1024, "bge-large")
    assert report.collections == []


def test_the_sweep_names_no_building():
    import inspect

    from orchestrator.services import embedding_consistency as ec

    src = inspect.getsource(ec).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys"):
        assert literal not in src, f"the sweep must not name a building: {literal}"
