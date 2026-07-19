"""
Unit tests for the admin building-identity config (ontology namespace / prefix in building.yaml).

Writes to a temp input dir (monkeypatched) — never the real input/building.yaml.
"""

from __future__ import annotations

import pytest

from orchestrator.services import admin_config as ac

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_input(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_input_dir", lambda: tmp_path)
    return tmp_path


def test_set_yaml_scalar_replaces_and_preserves_comments():
    text = "building_id: bldg1\n# keep this comment\nontology_namespace: http://old#\nfloors: 5\n"
    out = ac._set_yaml_scalar(text, "ontology_namespace", "http://new#")
    assert "ontology_namespace: http://new#" in out
    assert "http://old#" not in out
    assert "# keep this comment" in out  # comment survives
    assert "building_id: bldg1" in out and "floors: 5" in out  # other keys untouched


def test_set_yaml_scalar_appends_when_missing():
    out = ac._set_yaml_scalar("building_id: bldg2\n", "ontology_prefix", "b2")
    assert out.endswith("ontology_prefix: b2\n")
    assert "building_id: bldg2" in out


def test_read_building_config_falls_back_to_settings(tmp_input):
    # No building.yaml → values come from live settings.
    cfg = ac.read_building_config()
    assert cfg["exists"] is False
    assert cfg["ontology_namespace"]  # settings default is non-empty
    assert cfg["ontology_prefix"]


def test_write_rejects_namespace_without_terminator(tmp_input):
    res = ac.write_building_config("http://example.org/abacws", "bldg")
    assert res["ok"] is False and "#" in res["error"]


def test_write_rejects_non_uri_namespace(tmp_input):
    res = ac.write_building_config("abacws#", "bldg")
    assert res["ok"] is False and "absolute" in res["error"]


def test_write_rejects_bad_prefix(tmp_input):
    res = ac.write_building_config("http://example.org/b2#", "2bad")
    assert res["ok"] is False and "prefix" in res["error"]


def test_write_persists_and_reads_back(tmp_input):
    res = ac.write_building_config("http://example.org/bldg2#", "b2", building_name="Building 2")
    assert res["ok"] is True
    # File written + round-trips through read_building_config.
    cfg = ac.read_building_config()
    assert cfg["ontology_namespace"] == "http://example.org/bldg2#"
    assert cfg["ontology_prefix"] == "b2"
    assert cfg["building_name"] == "Building 2"
    assert cfg["exists"] is True


def test_write_updates_existing_file_in_place(tmp_input):
    (tmp_input / "building.yaml").write_text(
        "building_id: bldg2\n# important note\nontology_namespace: http://old#\nfloors: 3\n",
        encoding="utf-8",
    )
    ac.write_building_config("http://example.org/new#", "bn")
    text = (tmp_input / "building.yaml").read_text(encoding="utf-8")
    assert "http://example.org/new#" in text and "http://old#" not in text
    assert "# important note" in text and "floors: 3" in text  # unrelated content preserved
