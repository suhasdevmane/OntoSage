# -*- coding: utf-8 -*-
"""The publish map must be built from the field ``ref:storedAt`` actually holds (CAVEAT-402).

``ref:storedAt`` names the REGISTRY KEY of a store. ``build_map`` compared it against the
store's TABLE NAME, and got away with it because most stores are registered under a key
identical to their table. The two where they differ were dropped in silence — and were
rescued only because a second, hand-written map happened to cover them. A building that
names its keys and tables differently throughout would have produced an EMPTY map, an empty
console line, and a stack where nothing at all was fed.

That is also how CAVEAT-402 came to be filed as a data gap. Reconciling by reading map files
found 605 "unfed" watched points; measuring per-uuid freshness through the adapters found
zero. The map files were never the authority — they were three files, none aware of the
others, and the answer depended on which one you opened.
"""

import json

import pytest

from scripts.generate_publisher_map import (
    _value_col,
    build_map,
    narrow_tables,
    sibling_uuids,
)

pytestmark = pytest.mark.unit


def _graph(rows):
    """Stand in for the SPARQL CSV the generator reads."""
    return lambda _endpoint, _query: rows


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "database_registry.yaml"
    path.write_text(
        "databases:\n"
        "  noise_data:\n"
        "    type: mysql_narrow\n"
        "    table: noise_data\n"
        "  database1_floors04:\n"  # key != table — the case that was dropped
        "    type: mysql_narrow\n"
        "    table: sensor_data_floors04\n"
        "  database1:\n"
        "    type: mysql\n",  # wide: not a narrow store, not publishable here
        encoding="utf-8",
    )
    return path


def test_a_store_whose_key_differs_from_its_table_is_not_dropped(registry, monkeypatch):
    tables = narrow_tables(registry)
    assert tables["database1_floors04"] == "sensor_data_floors04"

    import scripts.generate_publisher_map as mod

    monkeypatch.setattr(
        mod,
        "_sparql",
        _graph(
            [
                {"sensor": "s:A", "uuid": "u-a", "stored": "database1_floors04", "label": "A"},
                {"sensor": "s:B", "uuid": "u-b", "stored": "noise_data", "label": "B"},
            ]
        ),
    )
    out = build_map("http://x", tables)
    assert set(out) == {"u-a", "u-b"}, "the key-named store was dropped again"


def test_the_write_target_is_the_table_not_the_key(registry, monkeypatch):
    """The publisher INSERTs into entry['table']; a registry key there is not a table."""
    import scripts.generate_publisher_map as mod

    monkeypatch.setattr(
        mod,
        "_sparql",
        _graph([{"sensor": "s:A", "uuid": "u-a", "stored": "database1_floors04", "label": "A"}]),
    )
    out = build_map("http://x", narrow_tables(registry))
    assert out["u-a"]["table"] == "sensor_data_floors04"


def test_a_wide_store_is_not_published_here(registry, monkeypatch):
    """Its columns are written by the wide path; publishing them again would double them."""
    import scripts.generate_publisher_map as mod

    monkeypatch.setattr(
        mod,
        "_sparql",
        _graph([{"sensor": "s:W", "uuid": "u-w", "stored": "database1", "label": "W"}]),
    )
    assert build_map("http://x", narrow_tables(registry)) == {}


def test_the_value_range_follows_the_table_not_the_key(registry, monkeypatch):
    """`database1_floors04` carries no modality; `sensor_data_floors04` is what to read."""
    assert _value_col("temperature_data") == "temp_c"
    assert _value_col("database1_floors04") == "generic"


# ── sibling maps ───────────────────────────────────────────────────────────────────────


def test_a_point_another_loaded_map_feeds_is_left_to_it(tmp_path):
    (tmp_path / "b_extended_narrow_uuids.json").write_text(
        json.dumps({"u-a": {"uuid": "u-a", "table": "sensor_data_floors04"}}), encoding="utf-8"
    )
    claimed = sibling_uuids("b", tmp_path / "b_narrow_publish_map.json")
    assert claimed == {"u-a": "b_extended_narrow_uuids.json"}


def test_the_superseded_legacy_map_is_not_treated_as_a_sibling(tmp_path):
    """It is loaded only INSTEAD of the generated map, never alongside it.

    Deferring to it would leave its points fed by nobody — the same accident this function
    exists to prevent, one file further along. It was live for the length of one dry-run.
    """
    (tmp_path / "b_timeseries_extension_uuids.json").write_text(
        json.dumps({"u-legacy": {"uuid": "u-legacy", "table": "energy_data"}}), encoding="utf-8"
    )
    claimed = sibling_uuids("b", tmp_path / "b_narrow_publish_map.json")
    assert claimed == {}, "the generated map supersedes the legacy one; it is not a sibling"


def test_the_map_being_written_never_claims_against_itself(tmp_path):
    target = tmp_path / "b_narrow_publish_map.json"
    target.write_text(json.dumps({"u-a": {"uuid": "u-a", "table": "noise_data"}}), encoding="utf-8")
    assert sibling_uuids("b", target) == {}


def test_an_unreadable_sibling_does_not_stop_the_generator(tmp_path):
    """Half a map is worse than none: a parse error must not silently claim zero points."""
    (tmp_path / "b_extended_narrow_uuids.json").write_text("{ not json", encoding="utf-8")
    assert sibling_uuids("b", tmp_path / "b_narrow_publish_map.json") == {}
