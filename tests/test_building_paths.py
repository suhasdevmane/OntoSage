"""Unit tests for shared.building_paths — flat/nested layout resolution.

Canonical layout is FLAT (input/<file>); nested (input/<id>/<file>) is a
fallback that takes precedence when present.
"""

import pytest

from shared.building_paths import resolve_building_dir, resolve_building_file

pytestmark = pytest.mark.unit


def test_flat_file(tmp_path):
    (tmp_path / "capability.yaml").write_text("x", encoding="utf-8")
    p = resolve_building_file("bldg1", "capability.yaml", input_root=tmp_path)
    assert p == tmp_path / "capability.yaml"


def test_nested_file(tmp_path):
    (tmp_path / "bldg1").mkdir()
    (tmp_path / "bldg1" / "capability.yaml").write_text("x", encoding="utf-8")
    p = resolve_building_file("bldg1", "capability.yaml", input_root=tmp_path)
    assert p == tmp_path / "bldg1" / "capability.yaml"


def test_nested_takes_precedence_over_flat(tmp_path):
    (tmp_path / "bldg1").mkdir()
    (tmp_path / "bldg1" / "building.yaml").write_text("nested", encoding="utf-8")
    (tmp_path / "building.yaml").write_text("flat", encoding="utf-8")
    p = resolve_building_file("bldg1", "building.yaml", input_root=tmp_path)
    assert p == tmp_path / "bldg1" / "building.yaml"


def test_missing_file_returns_none(tmp_path):
    assert resolve_building_file("bldg1", "nope.yaml", input_root=tmp_path) is None


def test_flat_dir(tmp_path):
    (tmp_path / "documents").mkdir()
    p = resolve_building_dir("bldg1", "documents", input_root=tmp_path)
    assert p == tmp_path / "documents"


def test_nested_dir_precedence(tmp_path):
    (tmp_path / "bldg1" / "documents").mkdir(parents=True)
    (tmp_path / "documents").mkdir()
    p = resolve_building_dir("bldg1", "documents", input_root=tmp_path)
    assert p == tmp_path / "bldg1" / "documents"


def test_missing_dir_returns_none(tmp_path):
    assert resolve_building_dir("bldg1", "documents", input_root=tmp_path) is None
