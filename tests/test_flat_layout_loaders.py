"""FA-series regression tests: loaders honor the FLAT input layout.

Canonical layout keeps a single building's files directly under input/
(input/building.yaml, input/capability.yaml, input/documents/ …). These tests
pin the flat behavior for the loaders refactored onto shared.building_paths so
a future change can't silently regress to nested-only.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


# ── input_validators: accept the flat layout ────────────────────────────────


def test_validate_building_input_flat_layout(tmp_path):
    from orchestrator.services.input_validators import validate_building_input

    (tmp_path / "building.yaml").write_text("building_id: bldg1\n", encoding="utf-8")
    ok, report = validate_building_input("bldg1", tmp_path)
    # The <building dir> hard-fail must NOT trigger on a valid flat layout.
    assert "<building dir>" not in report["files"]
    assert ok is True


def test_validate_building_input_flat_wrong_building_rejected(tmp_path):
    from orchestrator.services.input_validators import validate_building_input

    (tmp_path / "building.yaml").write_text("building_id: bldg1\n", encoding="utf-8")
    ok, report = validate_building_input("bldg2", tmp_path)
    assert ok is False
    assert "<building dir>" in report["files"]


def test_validate_building_input_no_layout_rejected(tmp_path):
    from orchestrator.services.input_validators import validate_building_input

    ok, report = validate_building_input("bldg1", tmp_path)
    assert ok is False
    assert report["files"]["<building dir>"]["exists"] is False


# ── document_indexer: index the active building's flat documents/ ───────────


def test_document_index_all_buildings_flat(tmp_path, monkeypatch):
    from orchestrator.services import document_indexer as di
    from shared.config import settings

    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "policy.md").write_text("hello", encoding="utf-8")

    idx = di.DocumentIndexer(qdrant_client=None, embedding_service=None, input_root=str(tmp_path))
    idx.index_building = AsyncMock(return_value="indexed")
    monkeypatch.setattr(settings, "BUILDING_ID", "bldg1")

    res = asyncio.run(idx.index_all_buildings())
    idx.index_building.assert_awaited_once_with("bldg1")
    assert "bldg1" in res


# ── capability_indexer: index the active building's flat capability.yaml ────


def test_capability_index_all_buildings_flat(tmp_path, monkeypatch):
    from orchestrator.services import capability_indexer as ci
    from shared.config import settings

    (tmp_path / "capability.yaml").write_text("capabilities: []\n", encoding="utf-8")

    idx = ci.CapabilityIndexer(qdrant_client=None, embedding_service=None, input_root=str(tmp_path))
    idx.index_building = AsyncMock(return_value="indexed")
    idx.index_extra_intents = AsyncMock(return_value={})
    monkeypatch.setattr(settings, "BUILDING_ID", "bldg1")

    res = asyncio.run(idx.index_all_buildings())
    idx.index_building.assert_awaited_once_with("bldg1")
    assert "bldg1" in res


# ── building_context: read building.yaml from flat input/ ───────────────────


def test_building_context_loads_flat(tmp_path, monkeypatch):
    from orchestrator.services import building_context as bc

    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "building.yaml").write_text(
        "building_id: bldg1\nbuilding_name: Test Tower\n", encoding="utf-8"
    )
    data = bc._load_building_yaml("bldg1")
    assert data is not None
    assert data.get("building_name") == "Test Tower"
