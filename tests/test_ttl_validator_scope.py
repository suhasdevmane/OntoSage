# -*- coding: utf-8 -*-
"""The TTL boot gate must gate exactly what the uploader loads — no more.

A stray TTL in a subdirectory of the input tree is never uploaded to GraphDB, so
it cannot corrupt the graph; halting startup over it is a false positive that
takes the whole stack down. That is not hypothetical: a downloaded sample at
``input/floors/examples/synthetic_building.ttl`` — correctly declaring a
different building's prefix, because it describes a different building — put the
orchestrator into a 16-restart loop.
"""

from pathlib import Path

import pytest

from orchestrator.services.ttl_uploader import discover_ttls
from orchestrator.services.ttl_validator import validate_building_ttls

pytestmark = pytest.mark.unit

NS = "http://example.org/demo#"
GOOD = f"@prefix bldg: <{NS}> .\n@prefix brick: <https://brickschema.org/schema/Brick#> .\nbldg:R1 a brick:Room .\n"
WRONG = "@prefix other: <http://elsewhere.example/x#> .\nother:R1 a other:Thing .\n"


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _validate(root: Path):
    return validate_building_ttls("bldg9", NS, "bldg", root)


def test_subdirectory_ttl_does_not_halt_startup(tmp_path):
    """The exact shape of the incident: a sample TTL nested in the input tree."""
    _write(tmp_path, "building.yaml", "building_id: bldg9\n")
    _write(tmp_path, "bldg9_rooms.ttl", GOOD)
    _write(tmp_path, "floors/examples/synthetic_building.ttl", WRONG)

    report = _validate(tmp_path)

    assert report.ok, [str(i) for i in report.hard_failures]
    assert report.ttl_files_checked == 1, "only the top-level TTL should be gated"
    assert not any("synthetic_building" in i.ttl_path for i in report.issues)


def test_a_wrong_ttl_at_the_top_level_still_halts_startup(tmp_path):
    """Relaxing the scope must not blunt the gate where it actually matters."""
    _write(tmp_path, "building.yaml", "building_id: bldg9\n")
    _write(tmp_path, "bldg9_rooms.ttl", WRONG)

    assert not _validate(tmp_path).ok


def test_validator_scope_equals_uploader_scope(tmp_path, monkeypatch):
    """Pin the invariant itself, so the two cannot drift apart again."""
    _write(tmp_path, "building.yaml", "building_id: bldg9\n")
    _write(tmp_path, "bldg9_rooms.ttl", GOOD)
    _write(tmp_path, "extra_equipment.ttl", GOOD)
    _write(tmp_path, "floors/examples/synthetic_building.ttl", WRONG)
    _write(tmp_path, "documents/manual.ttl", WRONG)

    monkeypatch.setattr("orchestrator.services.ttl_uploader._resolve_input_dir", lambda: tmp_path)
    uploaded = {p.name for p in discover_ttls("bldg9")}
    report = _validate(tmp_path)

    assert uploaded == {"bldg9_rooms.ttl", "extra_equipment.ttl"}
    assert report.ttl_files_checked == len(uploaded), (
        "the gate must consider exactly the files the uploader loads — "
        f"uploader={sorted(uploaded)}, validator checked {report.ttl_files_checked}"
    )
    assert report.ok
