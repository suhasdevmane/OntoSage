"""Regression test: capability KB loads from the FLAT input layout.

The active deployment keeps capability.yaml at input/capability.yaml (flat),
not input/<id>/capability.yaml. _load_kb previously only checked the nested
path, so the capability agent reported "no capability profile" for bldg1 even
though the KB existed and was indexed. (Same flat-vs-nested class as the
BuildingRegistry / TTL-validator fixes.)
"""

import shutil
from pathlib import Path

import pytest

import orchestrator.agents.capability_agent as cap

pytestmark = pytest.mark.unit

_REAL = Path(__file__).resolve().parents[1] / "input" / "capability.yaml"
_skip = pytest.mark.skipif(not _REAL.exists(), reason="input/capability.yaml not present")


def _point_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(cap, "_INPUT_ROOT", tmp_path)
    monkeypatch.setattr(cap, "_LOCAL_INPUT_ROOT", tmp_path)
    cap._KB_CACHE.clear()


@_skip
def test_load_kb_from_flat_layout(tmp_path, monkeypatch):
    # FLAT: input/capability.yaml (no input/<id>/ subdir).
    shutil.copy(_REAL, tmp_path / "capability.yaml")
    _point_roots(monkeypatch, tmp_path)
    kb = cap._load_kb("bldg1")
    assert kb is not None, "flat-layout capability.yaml should be found"
    assert len(kb.capabilities) > 0
    cap._KB_CACHE.clear()


@_skip
def test_nested_layout_still_loads(tmp_path, monkeypatch):
    # NESTED: input/<id>/capability.yaml must keep working (tried first).
    (tmp_path / "bldg1").mkdir()
    shutil.copy(_REAL, tmp_path / "bldg1" / "capability.yaml")
    _point_roots(monkeypatch, tmp_path)
    kb = cap._load_kb("bldg1")
    assert kb is not None
    cap._KB_CACHE.clear()


def test_missing_capability_yaml_returns_none(tmp_path, monkeypatch):
    _point_roots(monkeypatch, tmp_path)  # empty dir, neither layout present
    assert cap._load_kb("bldg1") is None
    cap._KB_CACHE.clear()
