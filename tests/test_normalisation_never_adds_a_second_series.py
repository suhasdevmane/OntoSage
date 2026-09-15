# -*- coding: utf-8 -*-
"""BUG-531 — normalising a vocabulary must never give a sensor a second series.

`scripts/normalise_timeseries_links.py` exists to make `s223:hasExternalReference` links
reachable by the `ref:` predicate the code queries. Its guard was checked per REFERENCE:

    FILTER NOT EXISTS { ?s ref:hasExternalReference ?r }

so a sensor already linked by its building file to its real narrow table, and ALSO carrying
a SATURATE-era `s223:` link to a synthetic series, had the synthetic one promoted as a second
canonical reference. Measured on bldg1 2026-09-15: 89 of 126 promoted links landed on sensors
that were already linked, and 70 sensors had populated series in BOTH stores — which the SQL
lane fetched and merged into one answer's statistics. The documented fan-out metric read
1.00 throughout, because each reference carried its own uuid.

The fix that made 106 invisible sensors reachable is what created the defect. These tests
pin the guard at the level of the SENSOR, and they parse the source's SPARQL rather than
matching prose (lessons.md #102: the old guard's text is quoted in the new comment).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "normalise_timeseries_links.py"


def _module():
    return ast.parse(SCRIPT.read_text(encoding="utf-8"))


def _only_unlinked_value() -> str:
    for node in _module().body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_ONLY_UNLINKED" for t in node.targets
        ):
            return ast.get_source_segment(SCRIPT.read_text(encoding="utf-8"), node.value) or ""
    return ""


def test_the_guard_is_per_sensor_not_per_reference():
    """`?anyRef`, an unbound variable, means "any canonical link at all". Binding it to the
    alias's own reference `?r` is the defect."""
    guard = _only_unlinked_value()
    assert guard, "_ONLY_UNLINKED is gone — the per-sensor guard was removed"
    assert "?anyRef" in guard
    assert "?r }" not in guard, "the guard is bound to the alias reference again"


def test_both_the_count_and_the_insert_use_the_same_guard():
    """If the dry-run counts with one rule and the insert writes with another, the dry-run
    stops predicting what the run will do — which is its only job."""
    code_only = "\n".join(
        line.split("#", 1)[0]
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
    )
    assert code_only.count("_ONLY_UNLINKED") >= 3, "definition plus BOTH query sites"
    # The FILTER form only. `?s <{_REF}> ?r` also appears in the INSERT template, where it is
    # exactly what should be written — the first version of this assertion matched that.
    assert "FILTER NOT EXISTS {{ ?s <{_REF}> ?r" not in code_only, (
        "a per-reference filter survives in a query"
    )


def test_the_script_says_re_running_does_not_remove_existing_duplicates():
    """Once the derived graph exists, every affected sensor already has a canonical link, so
    the fixed guard skips it. Without this said, someone re-runs the script and believes the
    77 duplicates are gone."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Drop the derived graph first" in text
