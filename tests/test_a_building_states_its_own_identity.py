# -*- coding: utf-8 -*-
"""A building's identity must come from the building, not from a default (CAVEAT-446).

WHAT WENT WRONG
---------------
`shared/building_context.py` resolved the SPARQL prefix label from `building_prefix` and
the timezone from `building_timezone`.

No `building.yaml` in this repository writes either key. bldg2, bldg3 and bldg4 write
`ontology_prefix`; bldg1 wrote neither, and no timezone at all. So every building silently
ran on the environment defaults.

The shape is what matters. Not a crash, not a warning: a wrong value that happens to be
right for the building the defaults were set from. A fourth building with a different
prefix label would have been misread with nothing anywhere saying so -- and the symptom
would have appeared far from the cause, as a query that returns no rows.

These tests are over whatever buildings the tree contains, so a building added next month is
covered without being named here.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _building_yamls() -> List[Path]:
    out = [
        p / "building.yaml"
        for p in REPO.glob("bldg*")
        if p.is_dir() and (p / "building.yaml").exists()
    ]
    active = REPO / "input" / "building.yaml"
    if active.exists():
        out.append(active)
    return out


def test_there_is_a_building_to_check():
    assert _building_yamls(), "no building.yaml found; the discovery is wrong"


@pytest.mark.parametrize("path", _building_yamls(), ids=lambda p: p.parent.name)
def test_every_building_declares_its_prefix_and_timezone(path: Path):
    """Stated, not inherited.

    A default that is right for one building is a trap for the next one: nothing reports
    that the value came from the environment rather than from the building.
    """
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prefix = data.get("ontology_prefix") or data.get("building_prefix")
    tz = data.get("timezone") or data.get("building_timezone")
    assert prefix, (
        f"{path.parent.name}/building.yaml declares no prefix label, so it inherits one "
        f"from the environment and cannot be told apart from a building that shares it"
    )
    assert tz, f"{path.parent.name}/building.yaml declares no timezone"


@pytest.mark.parametrize("path", _building_yamls(), ids=lambda p: p.parent.name)
def test_the_declared_prefix_is_the_one_its_ttl_uses(path: Path):
    """The declaration has to be TRUE, not merely present.

    A prefix label that disagrees with the building's own TTL is worse than an absent one:
    it silences the fallback while still being wrong.
    """
    import re

    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declared = data.get("ontology_prefix") or data.get("building_prefix")
    if not declared:
        pytest.skip("no prefix declared; covered by the test above")
    ns = str(data.get("ontology_namespace") or "")
    if not ns:
        pytest.skip("no namespace declared")

    pattern = re.compile(rf"@prefix\s+{re.escape(str(declared))}:\s*<{re.escape(ns)}>")
    ttls = [
        p
        for p in path.parent.glob("*.ttl")
        if not p.name.lower().startswith("brick") and pattern.search(
            p.read_text(encoding="utf-8", errors="replace")
        )
    ]
    assert ttls, (
        f"{path.parent.name}: building.yaml declares prefix {declared!r} for namespace "
        f"{ns!r}, and no TTL in the folder binds that pair"
    )


def test_the_reader_accepts_the_key_the_buildings_actually_write():
    from orchestrator.services import building_context as bc

    src = inspect.getsource(bc)
    assert "ontology_prefix" in src, (
        "the resolver no longer reads `ontology_prefix`, which is the key every "
        "building.yaml in this repo writes"
    )
    assert 'yaml_data.get("timezone")' in src, (
        "the resolver no longer reads `timezone`, only the `building_timezone` spelling "
        "that no building writes"
    )


def test_the_older_spelling_still_works():
    """A file written before the rename must keep working."""
    from orchestrator.services import building_context as bc

    src = inspect.getsource(bc)
    assert "building_prefix" in src and "building_timezone" in src, (
        "dropping the legacy keys would break any building.yaml written against them"
    )
