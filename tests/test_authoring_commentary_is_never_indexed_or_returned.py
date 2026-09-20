# -*- coding: utf-8 -*-
"""A register's design rationale is developer prose, never an answer (2D-16, defect class C10).

Every register document opens with a section written for the person who BUILT it ("Three duty
columns, not one ...", "Why every row carries a survey date"). Indexed beside the table, it was
retrieved for "what design choices were made?" and returned as though the building had said it.
Measured on the 2026-09-18 held-out reads.

Two fixes are locked here: the section is left out of what the indexer embeds (and the document
is re-embedded once, through a revision-tagged SHA), and passages already in an index built before
that are dropped at answer time by fingerprint, so the fix does not wait for a re-embed.
"""

from __future__ import annotations

import hashlib

import pytest

from orchestrator.services import document_indexer as di
from orchestrator.services import passage_relevance as pr

pytestmark = pytest.mark.unit

REGISTER = """---
record_type: asset_engineering
owner: "M and E Maintenance Supervisor"
simulated: true
tables:
  - name: "Asset engineering profile register"
    maps_to: asset_engineering_profiles
---

# Asset Engineering Profile Register - Example Building

## What this register records, and what the building recorded before it

The building already recorded that an air handling unit exists. Three design decisions carry the
register:

- **Three duty columns, not one.** design_duty is the claim on the drawing, commissioned_duty is
  what was witnessed, observed_duty is what is measured now. Collapsing them would make the only
  interesting question unaskable.

## Asset engineering profile register

| code | name | design_duty | observed_duty |
|---|---|---|---|
| AEP-001 | Air Handling Unit - Floor 0 | 2.4 m3/s | 2.1 m3/s |
"""


def test_the_design_rationale_section_is_found_by_its_heading():
    found = [s.heading for s in pr.authoring_sections(REGISTER)]
    assert found == ["What this register records, and what the building recorded before it"]


@pytest.mark.parametrize(
    "heading",
    [
        "Why every row carries a survey date",
        "Why this register exists",
        "What this register is for",
        "What this register records, and what it deliberately does not",
        "What this is, and the two corrections made to the source",
        "What changed, and why",
        "What a handover record is for",
        "How the register is used",
        "How a target is read",
        "Design choices",
    ],
)
def test_headings_that_talk_about_the_document_itself_are_authoring(heading):
    assert pr.is_authoring_heading(heading)


@pytest.mark.parametrize(
    "heading",
    [
        "Grades",  # a legend the building's own data is read through
        "How to read the fail state",  # a legend for a field, not a note on design
        "How cost is computed",  # the method behind a figure a stakeholder asks about
        "What a visitor needs to know",  # written for the visitor
        "Exceptions at the date of this version",
        "Circuits",
        "Scented products",
    ],
)
def test_legends_and_visitor_guidance_are_kept(heading):
    assert not pr.is_authoring_heading(heading)


def test_the_indexed_text_has_no_front_matter_and_no_rationale():
    text = pr.indexable_text(REGISTER)
    assert "Three duty columns" not in text
    assert "simulated" not in text, "front matter must never be embedded or quoted"
    assert "maps_to" not in text
    assert "AEP-001" in text, "the table is the register; it must survive"


def test_a_document_with_nothing_to_strip_is_returned_unchanged():
    plain = "# Policies\n\n## Scented products\n\nPlease avoid them.\n"
    assert pr.indexable_text(plain) == plain
    assert pr.strip_authoring_commentary(plain) == (plain, [])


def test_a_nested_section_goes_with_its_commentary_parent_and_not_beyond_it():
    text = (
        "# T\n\n## Why this register exists\n\nBecause.\n\n### A sub-point\n\nMore.\n\n"
        "## Real content\n\nThe lift is out of service.\n"
    )
    stripped, removed = pr.strip_authoring_commentary(text)
    assert removed == ["Why this register exists"]
    assert "sub-point" not in stripped and "Because" not in stripped
    assert "The lift is out of service." in stripped


def test_a_heading_inside_a_code_fence_is_not_a_section():
    text = "# T\n\n```\n## Why this register exists\n```\n\n## Content\n\nFact.\n"
    assert pr.authoring_sections(text) == []


# ── the indexer ──────────────────────────────────────────────────────────────


def test_the_index_hash_only_changes_for_a_document_whose_embedded_text_changes(tmp_path):
    plain = tmp_path / "plain.md"
    plain.write_text("# Policy\n\nBe kind.\n", encoding="utf-8")
    register = tmp_path / "register.md"
    register.write_text(REGISTER, encoding="utf-8")

    plain_sha = hashlib.sha256(plain.read_bytes()).hexdigest()
    register_sha = hashlib.sha256(register.read_bytes()).hexdigest()

    assert di._index_revision_sha(plain, plain_sha) == plain_sha, "nothing to rebuild"
    tagged = di._index_revision_sha(register, register_sha)
    assert tagged != register_sha, "the register must re-embed once, without its rationale"
    assert di._index_revision_sha(register, register_sha) == tagged, "and be stable after that"


# ── an index built before the fix ────────────────────────────────────────────


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "asset_engineering_register.md").write_text(REGISTER, encoding="utf-8")
    return tmp_path


def _flat(text: str) -> str:
    """What the indexer stored: the whole file as single-spaced words."""
    return " ".join(text.split())


def test_a_stale_passage_that_is_the_rationale_is_dropped_at_answer_time(docs):
    stale = {"doc_name": "asset_engineering_register", "text": _flat(REGISTER), "score": 0.9}
    rationale_only = {
        "doc_name": "asset_engineering_register",
        "text": "Three duty columns, not one. design_duty is the claim on the drawing, "
        "commissioned_duty is what was witnessed, observed_duty is what is measured now. "
        "Collapsing them would make the only interesting question unaskable.",
        "score": 0.9,
    }
    table = {
        "doc_name": "asset_engineering_register",
        "text": "| AEP-001 | Air Handling Unit - Floor 0 | 2.4 m3/s | 2.1 m3/s | " * 3,
        "score": 0.8,
    }
    kept = pr.drop_commentary_hits([rationale_only, table], "bx", docs_dir=docs)
    assert kept == [table]
    # A chunk that is mostly TABLE and merely begins with front matter is not commentary.
    assert pr.drop_commentary_hits([stale], "bx", docs_dir=docs)[0]["text"].startswith("#")


def test_flattened_front_matter_never_reaches_a_reader():
    chunk = (
        '--- record_type: asset_engineering owner: "M and E" simulated: true tables: - name: '
        '"Register" maps_to: asset_engineering_profiles --- # Register - Example Building '
        "AEP-001 Air Handling Unit"
    )
    cleaned = pr.strip_flat_front_matter(chunk)
    assert "simulated" not in cleaned and "maps_to" not in cleaned
    assert cleaned.startswith("# Register")


def test_no_commentary_and_no_documents_dir_means_nothing_is_dropped(tmp_path):
    hit = {"doc_name": "x", "text": "Anything at all about a lift.", "score": 0.7}
    assert pr.drop_commentary_hits([hit], "bx", docs_dir=tmp_path) == [hit]
    assert pr.commentary_shingles("bx", docs_dir=tmp_path / "missing") == set()
