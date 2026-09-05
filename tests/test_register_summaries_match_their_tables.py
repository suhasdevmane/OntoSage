# -*- coding: utf-8 -*-
"""A register that miscounts itself teaches the system a false fact.

Registers close with a bold summary sentence, and that sentence is prose the document lane
can quote verbatim. The department directory shipped claiming *"twelve have no out-of-hours
route at all"* when the true figure in its own table was **eight** — written by hand, never
checked against the rows underneath it.

That is worse than an ordinary error. The table is right, so every computed answer is right,
and the one sentence most likely to be quoted as a headline is wrong. A reader has no way to
tell them apart.

WHAT THIS CHECKS, AND WHAT IT DOES NOT
--------------------------------------
It checks the **leading count claim** — "**82 groups", "**20 functions" — against the number
of data rows actually in the table. That is the claim every register makes and the one that
drifts whenever rows are added.

It does NOT verify the rest of the sentence. "Eight have no out-of-hours route" is a claim
about a column's contents and would need a claim language to express. Guarding the count is
the part that can be guarded cheaply and is worth having; the rest stays a review
responsibility, and saying so here is more honest than implying the whole summary is
verified.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _registers():
    """Every register document in whichever building folder this checkout holds."""
    docs = sorted(REPO.glob("*/documents/*.md"))
    return [d for d in docs if d.read_text(encoding="utf-8").startswith("---")]


def _data_rows(text: str) -> int:
    """Rows under a header separator, across every table in the document."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    seps = {
        i
        for i, ln in enumerate(lines)
        if set(ln.replace("|", "").replace(" ", "")) <= set("-:") and "-" in ln
    }
    return len(lines) - 2 * len(seps)


def test_there_are_registers_to_check():
    """Guards the discovery itself: a glob that matches nothing passes everything below."""
    assert _registers(), "no register documents found; the glob or the layout has changed"


@pytest.mark.parametrize("doc", _registers(), ids=lambda p: p.name)
def test_the_leading_count_claim_matches_the_rows(doc):
    text = doc.read_text(encoding="utf-8")
    rows = _data_rows(text)
    # The summary is the bold sentence at the end: "**82 groups: ..." / "**20 functions."
    claims = re.findall(r"\*\*(\d{1,4})\s+(?:groups|functions|records|rows|entries)\b", text)
    if not claims:
        pytest.skip(f"{doc.name} makes no leading count claim")
    for claimed in claims:
        assert int(claimed) == rows, (
            f"{doc.name} claims {claimed} but its tables hold {rows} data rows. The table is "
            f"the fact; the sentence is what gets quoted."
        )


def test_the_two_registers_that_carried_a_false_count_are_right_now():
    """The specific regression, pinned by name because it was found in production."""
    for name, expected in (("department_directory.md", 8), ("stakeholder_group_register.md", 8)):
        hits = [d for d in _registers() if d.name == name]
        if not hits:
            continue
        text = hits[0].read_text(encoding="utf-8").lower()
        m = re.search(r"(\w+)\s+(?:have|of the twenty[\w\s]*have)\s+no out-of-hours route", text)
        assert m, f"{name} no longer states an out-of-hours claim; update this test with it"
        stated = WORDS.get(m.group(1), None) or int(m.group(1)) if m.group(1).isdigit() else WORDS.get(m.group(1))
        assert stated == expected, (
            f"{name} claims '{m.group(1)}' departments have no out-of-hours route; the "
            f"directory table says {expected}"
        )
