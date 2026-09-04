# -*- coding: utf-8 -*-
"""No script may filter the corpus on a Source label the corpus does not contain.

The six occupant catalogues carried `supervisor_catalogue_2026-08` because they arrived from
the supervisor before the other 31 were generated. That was a **delivery batch, not a
different corpus** — all 37 are the same Talking Abacws catalogues, 80 questions each, and
the six files are byte-identical to their copies in the 37-catalogue folder. Merged under one
source on 2026-09-04: **2,960 questions across 37 roles**, plus the 1,100 synthetic bank.

A Source filter is a silent failure mode. `--source supervisor_catalogue_2026-08` after the
merge selects **zero** rows and reports a clean run over nothing, which is the same shape as
BUG-359 (grading one building against another's labels) and CAVEAT-393 (recall over whichever
detectors survived an offset): the harness reporting a completeness it never achieved.

Five scripts held the retired label as a constant when the merge landed.
"""

import csv
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
BANK = REPO / "tasks" / "smart_building_questions.csv"
TRACKED = REPO / "docs" / "smart_building_questions.csv"


def _sources(path: Path) -> set:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {(r.get("Source") or "").strip() for r in csv.DictReader(fh)}


def _rows(path: Path) -> list:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.skipif(not BANK.is_file(), reason="corpus is gitignored; present only locally")
def test_the_corpus_holds_exactly_two_sources():
    assert _sources(BANK) == {"stakeholder_catalogue_37", "v5_synthetic_bank"}


@pytest.mark.skipif(not BANK.is_file(), reason="corpus is gitignored")
def test_every_catalogue_role_has_eighty_questions():
    import collections

    rows = [r for r in _rows(BANK) if r["Source"] == "stakeholder_catalogue_37"]
    per_role = collections.Counter(r["Stakeholder_Role"] for r in rows)
    assert len(per_role) == 37, f"expected 37 roles, found {len(per_role)}"
    assert set(per_role.values()) == {80}, f"uneven role sizes: {sorted(set(per_role.values()))}"
    assert len(rows) == 2960


def test_the_tracked_copy_matches_the_live_one():
    """`tasks/` is gitignored, so `docs/smart_building_questions.csv` is the only corpus a
    clone sees. It drifted once already (CAVEAT-409, the V7 tracker) and must not again."""
    assert TRACKED.is_file(), "the tracked corpus copy is missing"
    tracked = _rows(TRACKED)
    assert len(tracked) == 4060
    assert {r["Source"] for r in tracked} == {"stakeholder_catalogue_37", "v5_synthetic_bank"}
    if BANK.is_file():
        live = _rows(BANK)
        assert len(live) == len(tracked)
        assert {r["ID"] for r in live} == {r["ID"] for r in tracked}


def test_every_role_names_a_catalogue_file():
    """A role with no catalogue behind it is a question set nobody can trace."""
    folder = REPO / "QuestionBank" / "Talking_Abacws_37_Stakeholder_Catalogues"
    if not folder.is_dir():
        pytest.skip("catalogue PDFs are not present in this checkout")

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    files = {
        norm(p.stem)
        for p in folder.glob("*.pdf")
        if "master_technical_report" not in p.stem.lower()
    }
    roles = {
        norm(r["Stakeholder_Role"])
        for r in _rows(TRACKED)
        if r["Source"] == "stakeholder_catalogue_37"
    }
    assert roles <= files, f"roles with no catalogue file: {sorted(roles - files)}"
    assert files <= roles, f"catalogue files with no role: {sorted(files - roles)}"


def test_no_script_filters_on_a_source_the_corpus_lacks():
    """The durable guard: five scripts held the retired label when the merge landed, and a
    filter that matches nothing reports a clean run over an empty set."""
    valid = _sources(TRACKED)
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            for literal in re.findall(r"""["']([a-z0-9_]*catalogue[a-z0-9_-]*)["']""", code):
                if literal not in valid and "catalogue" in literal:
                    offenders.append(f"{path.name}:{line_no} -> {literal!r}")
    assert not offenders, (
        "these filter the corpus on a Source that does not exist, so they select nothing "
        "and say nothing:\n  " + "\n  ".join(offenders)
    )
