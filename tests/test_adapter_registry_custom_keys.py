"""Regression: GUI-added (custom-overlay) DB keys must stay active despite the
building.yaml `storage.databases` filter, and must be routable without a restart.

Pre-existing bug: `_initialize_from_yaml` skipped any key not in the storage filter,
so a connection added via the admin console was merged into the config but never built
into an adapter — on reload *or* restart. See registry.reload()/_merge_custom_databases.
"""

from __future__ import annotations

import yaml

import pytest

from orchestrator.services.adapters.registry import AdapterRegistry

pytestmark = pytest.mark.unit


def _write_custom(tmp_path, keys):
    (tmp_path / "database_registry.custom.yaml").write_text(
        yaml.safe_dump({"databases": {k: {"type": "mysql_narrow", "table": k} for k in keys}}),
        encoding="utf-8",
    )
    return tmp_path / "database_registry.yaml"  # primary path (need not exist)


def test_merge_records_custom_keys(tmp_path):
    primary = _write_custom(tmp_path, ["warehouse1", "warehouse2"])
    reg = AdapterRegistry()
    data = {"databases": {"database1": {"type": "mysql"}}}

    reg._merge_custom_databases(primary, data, yaml)

    # custom keys are tracked (so the storage filter can't drop them) …
    assert reg._custom_keys == {"warehouse1", "warehouse2"}
    # … and merged into the config for adapter construction
    assert set(data["databases"]) == {"database1", "warehouse1", "warehouse2"}


def test_merge_no_overlay_clears_custom_keys(tmp_path):
    reg = AdapterRegistry()
    reg._custom_keys = {"stale"}  # simulate a previous load
    primary = tmp_path / "database_registry.yaml"  # no sibling custom file

    reg._merge_custom_databases(primary, {"databases": {}}, yaml)

    # a deleted overlay must clear the tracked keys (not leak the stale set)
    assert reg._custom_keys == set()


def test_curated_key_wins_but_still_not_treated_as_custom(tmp_path):
    # a custom entry that clashes with a curated key must not override it,
    # and the clash key is still listed as custom (it exists in the overlay).
    primary = _write_custom(tmp_path, ["database1"])
    reg = AdapterRegistry()
    data = {"databases": {"database1": {"type": "mysql", "table": "curated"}}}

    reg._merge_custom_databases(primary, data, yaml)

    assert data["databases"]["database1"]["table"] == "curated"  # curated wins
    assert reg._custom_keys == {"database1"}
