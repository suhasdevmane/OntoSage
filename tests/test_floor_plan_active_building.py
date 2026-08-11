# -*- coding: utf-8 -*-
"""Floor-plan manifests are served only for the building that is running.

The manifest directory is a mounted volume. A manifest written by an earlier
occupant of that volume survives a building swap, so listing the directory
unfiltered served another building's floors as if they belonged to the running
one — the same contamination class as BUG-105 (TTL upload).

Aliases must still resolve: a building onboarded under a legacy slug writes its
manifests under that slug, and those are genuinely its own.
"""

import pytest

from orchestrator.services.floor_plan_registry import FloorPlanRegistry

pytestmark = pytest.mark.unit


class _StubPdfPipeline:
    def __init__(self, manifests):
        self._manifests = manifests

    def list_manifests(self):
        return list(self._manifests)


def _registry(monkeypatch, on_disk, active, aliases=()):
    reg = FloorPlanRegistry.__new__(FloorPlanRegistry)
    reg._pdf_pipeline = _StubPdfPipeline(on_disk)
    monkeypatch.setattr(
        FloorPlanRegistry,
        "_identity_candidates",
        staticmethod(lambda bid: [bid, *aliases]),
    )
    import shared.config as cfg

    monkeypatch.setattr(cfg.settings, "BUILDING_ID", active, raising=False)
    return reg


def test_another_buildings_manifests_are_not_served(monkeypatch):
    on_disk = [("abacws", 0), ("abacws", 1), ("bldg3", 0), ("bldg3", 1)]
    reg = _registry(monkeypatch, on_disk, active="bldg3")

    assert reg.list_manifests() == [("bldg3", 0), ("bldg3", 1)]


def test_a_legacy_alias_still_counts_as_the_active_building(monkeypatch):
    on_disk = [("abacws", 0), ("abacws", 5), ("bldg3", 0)]
    reg = _registry(monkeypatch, on_disk, active="bldg1", aliases=("abacws",))

    assert reg.list_manifests() == [("abacws", 0), ("abacws", 5)]


def test_identity_match_ignores_case(monkeypatch):
    reg = _registry(monkeypatch, [("BLDG3", 2)], active="bldg3")
    assert reg.list_manifests() == [("BLDG3", 2)]


def test_nothing_on_disk_is_not_an_error(monkeypatch):
    assert _registry(monkeypatch, [], active="bldg3").list_manifests() == []


def test_foreign_manifests_are_reported_not_silently_dropped(monkeypatch, caplog):
    reg = _registry(monkeypatch, [("abacws", 0), ("bldg3", 0)], active="bldg3")
    with caplog.at_level("WARNING"):
        reg.list_manifests()
    assert any("abacws" in r.message for r in caplog.records)
