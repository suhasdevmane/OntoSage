# -*- coding: utf-8 -*-
"""The record-document lifter: a document becomes countable data (V7-T18).

703 of the 2,960 catalogue questions are capped by a system this building holds only as
prose. The retrieval lane can quote a permit register; it cannot count it. These tests
pin the contract that turns one into the other, and the guards that stop it turning a
document into a wrong answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.services.record_documents import (
    ONTOSAGE,
    lift_document,
    parse_front_matter,
    parse_tables,
    to_turtle,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/bldgX#"
MAPPINGS = Path(__file__).resolve().parents[1] / "ontology" / "record_documents"

GOOD = """---
record_type: permit_to_work
owner: "Estates Compliance Team"
authority: "Example University"
source_system: "Permit Register"
effective_from: 2026-01-01
version: "2.0"
simulated: true
tables:
  - name: "Permit register"
    maps_to: permits
---

# Permits

Some prose that must be left alone.

## Permit register

| permit | type | date | area | status |
|---|---|---|---|---|
| P-1 | Hot works | 2026-08-23 | Level 3 riser | Closed, fire watch completed |
| P-2 | Roof access | 2026-08-30 | Roof plant | Open |
"""


def _write(tmp_path: Path, text: str, name: str = "reg.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_document_with_no_front_matter_is_not_a_record_document(tmp_path):
    """The prose path must be completely unaffected by adding the lifter."""
    result = lift_document(_write(tmp_path, "# Just a policy\n\nSome text."), NS, MAPPINGS)
    assert result.instances == 0
    assert result.errors == []  # not a fault — this is the normal case


def test_a_register_becomes_countable_instances(tmp_path):
    result = lift_document(_write(tmp_path, GOOD), NS, MAPPINGS)
    assert result.errors == []
    assert result.instances == 2
    statuses = {o for _, p, o in result.triples if p.endswith("recordStatus")}
    assert statuses == {"closed", "open"}


def test_a_declared_value_list_is_a_lookup_not_a_judgement(tmp_path):
    """'Closed, fire watch completed' is closed because the MAPPING says so."""
    result = lift_document(_write(tmp_path, GOOD), NS, MAPPINGS)
    closed = [s for s, p, o in result.triples if p.endswith("recordStatus") and o == "closed"]
    assert len(closed) == 1


def test_a_value_matching_nothing_is_an_error_never_a_guess(tmp_path):
    text = GOOD.replace("| Open |", "| Bananas |")
    result = lift_document(_write(tmp_path, text), NS, MAPPINGS)
    assert result.errors, "an undeclared status must fail, not be guessed at"
    assert "bananas" in result.errors[0].lower()


def test_a_failure_lifts_NOTHING_rather_than_half(tmp_path):
    """Half a register answers 'how many are open' with a confidently short number."""
    text = GOOD.replace("| Open |", "| Bananas |")
    result = lift_document(_write(tmp_path, text), NS, MAPPINGS)
    assert result.instances == 0
    assert result.triples == []


def test_missing_required_front_matter_is_reported_by_name(tmp_path):
    text = GOOD.replace('owner: "Estates Compliance Team"\n', "")
    result = lift_document(_write(tmp_path, text), NS, MAPPINGS)
    assert result.errors and "owner" in result.errors[0]
    assert result.instances == 0


def test_every_lifted_fact_carries_its_provenance(tmp_path):
    """Without derivedFromDocument a stale table silently outranks a live register."""
    result = lift_document(_write(tmp_path, GOOD), NS, MAPPINGS)
    predicates = {p for _, p, _ in result.triples}
    for required in (
        "derivedFromDocument",
        "liftedByMapping",
        "recordOwner",
        "owningAuthority",
        "recordVersion",
        "retrievedAt",
        "isSimulated",
    ):
        assert ONTOSAGE + required in predicates, f"{required} missing from lifted facts"


def test_a_synthetic_document_stays_declared_synthetic(tmp_path):
    result = lift_document(_write(tmp_path, GOOD), NS, MAPPINGS)
    assert any(p.endswith("isSimulated") and o is True for _, p, o in result.triples)


def test_one_named_graph_per_document(tmp_path):
    """Replaced on re-ingest, not appended — CAVEAT-039 was accumulation."""
    result = lift_document(_write(tmp_path, GOOD, "permits.md"), NS, MAPPINGS)
    assert result.graph_iri == f"{NS}documents/permits"


def test_a_duplicate_record_id_is_refused(tmp_path):
    """Two rows sharing an id would merge into one instance and silently lose a record."""
    text = GOOD.replace("| P-2 |", "| P-1 |")
    result = lift_document(_write(tmp_path, text), NS, MAPPINGS)
    assert result.errors and "duplicate" in result.errors[0].lower()


def test_an_undeclared_table_is_not_lifted(tmp_path):
    """Only tables the front-matter names are lifted — a document may carry others."""
    text = GOOD.replace('- name: "Permit register"', '- name: "Some other table"')
    assert "Some other table" in text, "the fixture edit must actually apply"
    result = lift_document(_write(tmp_path, text), NS, MAPPINGS)
    assert result.instances == 0
    assert result.errors


def test_front_matter_and_body_split_cleanly():
    front, body = parse_front_matter(GOOD)
    assert front["record_type"] == "permit_to_work"
    assert body.lstrip().startswith("# Permits")
    assert "record_type" not in body


def test_tables_are_paired_with_their_heading():
    _, body = parse_front_matter(GOOD)
    tables = parse_tables(body)
    assert [h for h, _ in tables] == ["Permit register"]
    assert len(tables[0][1]) == 2


def test_turtle_serialises_to_something_parseable(tmp_path):
    rdflib = pytest.importorskip("rdflib")
    result = lift_document(_write(tmp_path, GOOD), NS, MAPPINGS)
    graph = rdflib.Graph()
    graph.parse(data=to_turtle(result), format="turtle")
    assert len(graph) == len(result.triples)
