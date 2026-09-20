# -*- coding: utf-8 -*-
"""A field that is present can still say the thing is absent (probe regression, 2026-09-19).

"Which departments have no out-of-hours route?" answered "**None of the 20 records in the Department
register lacks a recorded out-of-hours route** — every one of them has it." The field is never empty:
eight departments record the VALUE "No cover, next working day", and the register's own closing
sentence says "Eight have no out-of-hours route at all".

The cause was YAML, not logic. `absent_values` began with a bare `no`, which YAML reads as the
boolean false, so the compiled pattern was `false` and matched nothing. Both readings of "no Y" —
an empty cell, and a value that says none — must work, and neither may swallow an ordinary value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator.services.register_vocabulary import get_vocabulary

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "register_vocabulary.yaml"


@pytest.mark.parametrize(
    "value",
    [
        "No cover, next working day",  # the exact value behind the regression
        "None",
        "none recorded",
        "n/a",
        "not provided",
        "-",
        "—",
    ],
)
def test_a_value_that_says_none_is_read_as_none(value):
    assert get_vocabulary().value_says_none(value) is True, value


@pytest.mark.parametrize(
    "value",
    [
        "Normal hours",  # starts with "no" only as a prefix of a longer word
        "Notified weekly",
        "Security control room",
        "Nominated deputy",
        "24/7",
        "",  # an EMPTY cell is the other reading; the caller keeps them apart
    ],
)
def test_an_ordinary_value_is_not_read_as_none(value):
    assert get_vocabulary().value_says_none(value) is False, value


def test_no_vocabulary_word_was_eaten_by_yaml():
    """A bare no/yes/on/off in a YAML list becomes a boolean and silently stops matching."""
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    offenders = {
        key: [v for v in values if isinstance(v, bool)]
        for key, values in raw.items()
        if isinstance(values, list)
    }
    assert not {k: v for k, v in offenders.items() if v}, offenders


def test_the_department_register_really_holds_the_shape_this_protects():
    """Read from the building's own file, so the test fails if the data stops exercising it."""
    doc = REPO / "input" / "documents" / "department_directory.md"
    if not doc.is_file():
        pytest.skip("no active building")
    rows = [l for l in doc.read_text(encoding="utf-8").splitlines() if l.strip().startswith("|")]
    header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    column = header.index("out_of_hours")
    vocab = get_vocabulary()
    values = [
        [c.strip() for c in r.strip().strip("|").split("|")][column]
        for r in rows[2:]
        if len([c for c in r.strip().strip("|").split("|")]) == len(header)
    ]
    says_none = [v for v in values if vocab.value_says_none(v)]
    assert len(says_none) == 8, f"expected the eight with no cover, got {len(says_none)}"
