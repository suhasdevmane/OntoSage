# -*- coding: utf-8 -*-
"""The class-listing query's variable NAMES are a contract with its reader (BUG-236).

`_orchestrator` extracts bindings by name, not by position:

    if "uuid" in var.lower() or "id" in var.lower():   -> the timeseries id
    if "storage" in var.lower():                        -> the storedAt reference

The TODO-223 fix added `GROUP BY` + `SAMPLE` to stop a one-to-many join exhausting the LIMIT.
SPARQL forbids `(SAMPLE(?x) AS ?x)`, so the projections had to be aliased, and `?storage`
became `?store`. That alias does not contain "storage", so **every class-listing query
returned an empty storage map** from that moment. `sql_agent` then had no per-uuid `storedAt`,
logged "Storage: N/A" for every sensor, and validated them all against a fallback adapter --
which is why the water question still reported no data after BUG-234 had supposedly fixed
exactly that. Two correct fixes, defeated by a rename between them.

The coupling is fragile by nature, so it is asserted here rather than left to be noticed.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ORCH = Path(__file__).resolve().parent.parent / "orchestrator"
AGENT = (ORCH / "agents" / "sparql_agent.py").read_text(encoding="utf-8")
READER = (ORCH / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")


def _class_listing_projection() -> str:
    """The SELECT list of the class-listing template."""
    i = AGENT.index("SAMPLE(?location)")
    return AGENT[i - 120 : i + 700]


def test_the_reader_still_matches_by_name():
    """If this changes, the rest of this file is testing the wrong contract."""
    assert '"uuid" in var.lower() or "id" in var.lower()' in READER
    assert '"storage" in var.lower()' in READER


def test_the_storage_alias_contains_the_substring_the_reader_looks_for():
    """The regression, directly. `?store` does not contain "storage"."""
    proj = _class_listing_projection()
    aliases = re.findall(r"AS \?(\w+)", proj)
    assert any("storage" in a.lower() for a in aliases), (
        f"no projection alias contains 'storage': {aliases} — the storage map will be empty "
        "for every class-listing query and every sensor will be validated against a fallback "
        "adapter"
    )


def test_the_uuid_alias_contains_the_substring_the_reader_looks_for():
    proj = _class_listing_projection()
    aliases = re.findall(r"AS \?(\w+)", proj)
    assert any(("uuid" in a.lower() or "id" in a.lower()) for a in aliases), aliases


def test_no_alias_collides_with_its_own_source_variable():
    """SPARQL rejects `(SAMPLE(?x) AS ?x)`. This is WHY the aliases exist, and re-introducing
    the collision to satisfy the reader would break the query instead."""
    proj = _class_listing_projection()
    for source, alias in re.findall(r"SAMPLE\(\?(\w+)\) AS \?(\w+)", proj):
        assert source != alias, f"(SAMPLE(?{source}) AS ?{alias}) is not valid SPARQL"


def test_the_listing_still_groups_and_bounds():
    """The TODO-223 properties must survive any future rename: one row per sensor, and a
    limit that can express a real population."""
    proj = _class_listing_projection()
    assert "GROUP BY ?sensor" in proj
    assert "_CLASS_LISTING_LIMIT" in proj
