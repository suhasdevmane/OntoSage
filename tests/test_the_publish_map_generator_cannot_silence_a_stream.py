# -*- coding: utf-8 -*-
"""`scripts/generate_publish_map.py` rewrites a publish map from scratch (BUG-1142).

WHAT WAS WRONG, MEASURED ON THE LIVE GRAPH 2026-09-30
-----------------------------------------------------
A `--dry-run` said the generator would write 32 entries and remove all 1,086 on disk. The
1,086 attribute exactly, and only one third of the story is harmful:

* **1,050 were inert.** They are also in the sibling narrow publish map, and the publisher
  drops every collision at load: its log reads `1050 sensor(s) appear in BOTH publish maps`
  and then `Loaded 36 extended narrow sensors`. Removing them restores the disjointness
  this generator exists to maintain.
* **36 were the whole of the live map**, and were invisible because both queries traversed
  `?sensor ref:hasExternalReference ?r` while those points are linked with the `ashrae:`
  spelling. Same cause as BUG-1141, BUG-531 and BUG-481.
* **All 32 it WOULD have written were duplicates too.** `_already_published` walked only
  the top level of each `*_publish_map.json`, so it collected 0 of the plant map's 44 uuids
  (nested under `groups[*].roles[*]`) and 0 of the waste map's 24 (under `bins[*].roles[*]`).
  Those 32 are AHU points the plant lane writes into the same table on every tick.

WHAT THESE TESTS PIN
--------------------
1. The traversal binds a predicate variable instead of naming a spelling.
2. The claim walk reaches a uuid at any depth, and survives a map whose top-level values
   are not entry dicts -- the shape that makes the sibling generator raise.
3. A removal is classified by whether anything else still publishes the point, which is the
   only distinction between dropping a duplicate and silencing a stream.
4. Against whatever maps are on disk: every point a sibling map publishes is claimed.

Offline: JSON and source text only. No graph, no model, no container.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Set

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "generate_publish_map.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("generate_publish_map", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. the traversal ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["_QUERY", "_UNMAPPED"])
def test_the_traversal_binds_a_predicate_rather_than_naming_one(gen, name):
    """Naming two spellings only waits for a third (BUG-1142 (a), BUG-531, BUG-481)."""
    q = getattr(gen, name)
    assert "?anyRefPred" in q, f"{name} names a reference predicate instead of binding one"
    assert "hasExternalReference" not in q, (
        f"{name} still names a spelling of the reference relation. This building uses three; "
        f"a query that names one of them cannot see the points linked with the others."
    )


def test_the_mapped_query_deduplicates(gen):
    """A sensor carrying two spellings matches twice: 4,895 rows became 9,849 without this."""
    assert "SELECT DISTINCT" in gen._QUERY


# ── 2. the claim walk ─────────────────────────────────────────────────────────


def _plant_shaped() -> dict:
    """The real plant map's shape: a scalar and a list at the top level."""
    return {
        "table": "plant_data",
        "groups": [
            {
                "group": "AHU_A",
                "roles": {
                    "fan_status": {"uuid": "u-fan", "point": "AHU_A_Fan_Status"},
                    "supply_air_temp": {"uuid": "u-sat", "point": "AHU_A_Supply_Air_Temperature"},
                },
            }
        ],
    }


def _waste_shaped() -> dict:
    return {
        "fill_table": "wastefill_data",
        "capacity_kg": {"General": 55.0},
        "bins": [{"bin": "B1", "roles": {"fill": {"uuid": "u-fill"}, "weight": {"uuid": "u-wt"}}}],
    }


def test_a_nested_uuid_is_reached(gen):
    found: Set[str] = gen._uuids_anywhere(_plant_shaped(), set())
    assert found == {"u-fan", "u-sat"}


def test_a_uuid_under_a_list_of_dicts_is_reached(gen):
    assert gen._uuids_anywhere(_waste_shaped(), set()) == {"u-fill", "u-wt"}


def test_a_scalar_at_the_top_level_does_not_stop_the_walk(gen, tmp_path):
    """The sibling generator raises AttributeError on exactly this shape; this one must not."""
    (tmp_path / "b_plant_publish_map.json").write_text(
        json.dumps(_plant_shaped()), encoding="utf-8"
    )
    claimed = gen._already_published(tmp_path)
    assert claimed == {
        "u-fan": "b_plant_publish_map.json",
        "u-sat": "b_plant_publish_map.json",
    }


def test_a_flat_map_still_works(gen, tmp_path):
    (tmp_path / "b_narrow_publish_map.json").write_text(
        json.dumps({"u-a": {"uuid": "u-a", "table": "noise_data"}}), encoding="utf-8"
    )
    assert gen._already_published(tmp_path) == {"u-a": "b_narrow_publish_map.json"}


def test_an_unreadable_map_does_not_claim_zero_silently_for_the_others(gen, tmp_path):
    (tmp_path / "b_narrow_publish_map.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "b_waste_publish_map.json").write_text(json.dumps(_waste_shaped()), "utf-8")
    claimed = gen._already_published(tmp_path)
    assert set(claimed) == {"u-fill", "u-wt"}


# ── 3. the rail ───────────────────────────────────────────────────────────────


def test_a_removal_something_else_publishes_is_not_a_silencing(gen):
    current = {"u-a": {"uuid": "u-a"}, "u-b": {"uuid": "u-b"}}
    fresh: dict = {}
    claimed = {"u-a": "b_narrow_publish_map.json", "u-b": "b_narrow_publish_map.json"}
    removed, silenced, by_file = gen._removal_report(current, fresh, claimed)
    assert removed == {"u-a", "u-b"}
    assert silenced == set(), "a duplicate being dropped is not a stream going silent"
    assert by_file["b_narrow_publish_map.json"] == 2


def test_a_removal_nothing_else_publishes_is_a_silencing(gen):
    """The 36 synth streams, in miniature."""
    current = {"u-a": {"uuid": "u-a"}, "u-live": {"uuid": "u-live"}}
    removed, silenced, _ = gen._removal_report(current, {}, {"u-a": "b_narrow_publish_map.json"})
    assert removed == {"u-a", "u-live"}
    assert silenced == {"u-live"}


def test_a_kept_entry_is_not_a_removal(gen):
    current = {"u-a": {"uuid": "u-a"}}
    removed, silenced, _ = gen._removal_report(current, {"u-a": {"uuid": "u-a"}}, {})
    assert removed == set() and silenced == set()


def test_the_rail_has_a_default_below_a_full_rewrite(gen):
    """A script that can silently replace a whole map is a footgun whatever the reason."""
    assert 0 < gen.DEFAULT_MAX_DELETE_PCT < 100


def _staged(gen, tmp_path, monkeypatch, fresh, on_disk, claimed):
    """A sandboxed `main()`: no graph, no real building, writes only into tmp_path."""
    monkeypatch.setattr(gen, "_env", lambda *a, **k: "b")
    monkeypatch.setattr(gen, "REPO", tmp_path)
    monkeypatch.setattr(
        gen,
        "build",
        lambda *a, **k: (fresh, __import__("collections").Counter(), [], 0, claimed),
    )
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "b_extended_narrow_uuids.json").write_text(json.dumps(on_disk), encoding="utf-8")
    return out


def test_a_run_that_would_silence_a_stream_refuses_and_writes_nothing(
    gen, tmp_path, monkeypatch, capsys
):
    """BUG-1142 in miniature: the map's only live entry is not in the fresh build."""
    on_disk = {"u-live": {"uuid": "u-live", "table": "t", "class": "C", "lo": 0, "hi": 1, "dec": 0}}
    out = _staged(
        gen, tmp_path, monkeypatch, {"u-new": {"uuid": "u-new", "class": "C"}}, on_disk, {}
    )
    rc = gen.main(["--out", "out"])
    assert rc == 2
    assert json.loads((out / "b_extended_narrow_uuids.json").read_text(encoding="utf-8")) == on_disk
    assert "REFUSED" in capsys.readouterr().out


def test_a_bulk_removal_refuses_even_when_every_removal_is_claimed(
    gen, tmp_path, monkeypatch, capsys
):
    """Today's correct run removes 96.7% and silences nothing. It still stops to be looked at."""
    on_disk = {f"u{i}": {"uuid": f"u{i}", "class": "C"} for i in range(10)}
    claimed = {f"u{i}": "b_narrow_publish_map.json" for i in range(1, 10)}
    out = _staged(gen, tmp_path, monkeypatch, {"u0": on_disk["u0"]}, on_disk, claimed)
    rc = gen.main(["--out", "out"])
    assert rc == 2
    assert len(json.loads((out / "b_extended_narrow_uuids.json").read_text(encoding="utf-8"))) == 10
    text = capsys.readouterr().out
    assert "REFUSED" in text and "--max-delete-pct" in text


def test_force_writes_and_says_what_it_overrode(gen, tmp_path, monkeypatch, capsys):
    on_disk = {f"u{i}": {"uuid": f"u{i}", "class": "C"} for i in range(10)}
    fresh = {"u-new": {"uuid": "u-new", "class": "C", "lo": 0, "hi": 1, "dec": 0, "table": "t"}}
    out = _staged(gen, tmp_path, monkeypatch, fresh, on_disk, {})
    rc = gen.main(["--out", "out", "--force"])
    assert rc == 0
    assert json.loads((out / "b_extended_narrow_uuids.json").read_text(encoding="utf-8")) == fresh
    assert "overriding" in capsys.readouterr().out


def test_dry_run_never_writes_and_still_announces_the_refusal(gen, tmp_path, monkeypatch, capsys):
    on_disk = {f"u{i}": {"uuid": f"u{i}", "class": "C"} for i in range(10)}
    out = _staged(
        gen, tmp_path, monkeypatch, {"u-new": {"uuid": "u-new", "class": "C"}}, on_disk, {}
    )
    rc = gen.main(["--out", "out", "--dry-run"])
    assert rc == 0
    assert len(json.loads((out / "b_extended_narrow_uuids.json").read_text(encoding="utf-8"))) == 10
    assert "would REFUSE" in capsys.readouterr().out


# ── 4. against whatever is on disk ────────────────────────────────────────────


def _building_dirs():
    dirs = [p for p in REPO.glob("bldg*") if p.is_dir() and (p / "building.yaml").exists()]
    active = REPO / "input"
    if (active / "building.yaml").exists():
        dirs.append(active)
    return [d for d in dirs if list(d.glob("*_publish_map.json"))]


@pytest.mark.parametrize("folder", _building_dirs(), ids=lambda p: p.name)
def test_every_point_a_sibling_map_publishes_is_claimed(gen, folder):
    """The regression, against the real files: 68 points were claimed by nobody."""
    claimed = set(gen._already_published(folder))
    missed = {}
    for p in sorted(folder.glob("*_publish_map.json")):
        deep = gen._uuids_anywhere(json.loads(p.read_text(encoding="utf-8")), set())
        gap = deep - claimed
        if gap:
            missed[p.name] = len(gap)
    assert not missed, (
        f"the claim walk cannot see these points, so the generator would write them a "
        f"second time into the same table: {missed}"
    )


# ── building agnosticism ──────────────────────────────────────────────────────


def test_the_script_carries_no_building_literal():
    from scripts.check_building_literals import _prose_lines

    src = SCRIPT.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff"):
        assert literal not in code, f"the generator hardcodes {literal}"
