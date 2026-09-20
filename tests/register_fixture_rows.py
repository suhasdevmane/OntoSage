# -*- coding: utf-8 -*-
"""The register rows the register lane sees, built offline from the real documents.

The lane reads rows out of GraphDB as one binding per record, every predicate a column and a
repeated predicate comma-joined (``SparqlAgent._pivot_by_subject``). The documents under
``input/documents`` are lifted into exactly those triples by ``record_documents.lift_document``
and the mappings under ``ontology/record_documents``, so running the lifter and pivoting its
triples the same way gives the rows the live lane holds — with no graph, no network and no
invented data. Tests built on this are checking the building's own registers.

``ground_truth`` reads the SAME document a second way — the markdown table, cell by cell, with
the mapping's own status vocabulary applied — so an expectation never comes from the code under
test.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.services import record_documents

REPO = Path(__file__).resolve().parent.parent


def _documents_dir() -> Path:
    """The record documents of the active building, else of a PARKED one.

    The committed tree has NO active building (`input/` is absent; Workflow rule 8), and a fresh
    clone and CI see exactly that. These fixtures test the register lane against the building's own
    documents, which a parked building keeps under `bldg<N>/documents`, so the parked copy is read
    when nothing is active. 2026-09-20: 117 tests failed and 24 errored parked for want of this.
    """
    active = REPO / "input" / "documents"
    if active.is_dir():
        return active
    for parked in sorted(REPO.glob("bldg*/documents")):
        if any(parked.glob("*.md")):
            return parked
    return active


DOCUMENTS = _documents_dir()
MAPPINGS = REPO / "ontology" / "record_documents"
NAMESPACE = "http://example.org/bldg/"
_RETRIEVED = datetime(2026, 9, 16, 17, 21, 36)


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _front(document: str) -> Dict[str, Any]:
    front, _body = record_documents.parse_front_matter(
        (DOCUMENTS / document).read_text(encoding="utf-8")
    )
    return front


def document_names() -> List[str]:
    """Every document under input/documents that carries record front-matter and a mapping."""
    out = []
    for path in sorted(DOCUMENTS.glob("*.md")):
        front = _front(path.name)
        if front.get("record_type") and (MAPPINGS / f"{front['record_type']}.yaml").is_file():
            out.append(path.name)
    return out


@lru_cache(maxsize=None)
def _lift(document: str) -> Tuple[Tuple[Dict[str, Dict[str, str]], ...], str]:
    path = DOCUMENTS / document
    result = record_documents.lift_document(path, NAMESPACE, MAPPINGS, _RETRIEVED)
    assert result.ok, f"{document} did not lift: {result.errors}"
    by_subject: Dict[str, Dict[str, Dict[str, str]]] = {}
    seen = set()  # a graph is a SET of triples: the same fact lifted twice is stored once
    for subject, predicate, value in result.triples:
        if predicate == record_documents.RDF_TYPE or (subject, predicate, _text(value)) in seen:
            continue
        seen.add((subject, predicate, _text(value)))
        column = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        row = by_subject.setdefault(subject, {"record": {"type": "uri", "value": subject}})
        if column in row:
            row[column]["value"] = f"{row[column]['value']}, {_text(value)}"
        else:
            row[column] = {"type": "literal", "value": _text(value)}
    columns: List[str] = []
    for row in by_subject.values():
        for column in row:
            if column not in columns:
                columns.append(column)
    rows = list(by_subject.values())
    for row in rows:
        for column in columns:
            row.setdefault(column, {"type": "literal", "value": ""})
    label = str((_front(document).get("tables") or [{}])[0].get("name", ""))
    return tuple(rows), label


def lifted_rows(document: str) -> Tuple[List[Dict[str, Dict[str, str]]], str]:
    """(rows, register label) for one document, in the shape the register lane reads them.

    Returned as fresh copies: the lane never mutates its rows, but a test might.
    """
    rows, label = _lift(document)
    return [{k: dict(v) for k, v in r.items()} for r in rows], label


def ground_truth(document: str) -> List[Dict[str, str]]:
    """The document's own table, cell by cell, with ``_id``, ``_status`` and the register's owner.

    ``_status`` is the mapping's canonical status for the row's status cell, computed by the
    lifter's own value-list rule; ``_owner`` is the row's owner cell when the mapping has an
    owner-like column, else the front-matter owner.
    """
    path = DOCUMENTS / document
    front, body = record_documents.parse_front_matter(path.read_text(encoding="utf-8"))
    mapping = record_documents.load_mapping(str(front["record_type"]), MAPPINGS)
    assert mapping is not None
    declared = {str(t.get("name", "")).strip().lower() for t in front.get("tables") or []}
    table = next(
        rows
        for heading, rows in record_documents.parse_tables(body)
        if heading.strip().lower() in declared
    )

    def _column(suffix: str) -> Optional[str]:
        return next(
            (c for c, spec in mapping.columns.items() if spec.predicate.endswith(suffix)), None
        )

    id_col, status_col = _column("recordId"), _column("recordStatus")
    owner_col = _column("recordOwner") or _column("responsibleRole") or _column("accountableRole")
    out = []
    for row in table:
        item = dict(row)
        item["_id"] = row[id_col]
        item["_status"] = ""
        if status_col and row.get(status_col):
            value, _why = record_documents._coerce(
                row[status_col], "xsd:string", mapping.columns[status_col]
            )
            item["_status"] = str(value or "")
        item["_owner"] = row.get(owner_col, "") if owner_col else str(front["owner"])
        out.append(item)
    return out


def owner_column(document: str) -> Optional[str]:
    """The table column that holds a record's own owner, when the mapping has one."""
    front = _front(document)
    mapping = record_documents.load_mapping(str(front["record_type"]), MAPPINGS)
    assert mapping is not None
    for suffix in ("recordOwner", "responsibleRole", "accountableRole"):
        for col, spec in mapping.columns.items():
            if spec.predicate.endswith(suffix):
                return col
    return None


def due_column(document: str) -> Optional[str]:
    """The table column mapped to a next-due / review-due date, when there is one."""
    front = _front(document)
    mapping = record_documents.load_mapping(str(front["record_type"]), MAPPINGS)
    assert mapping is not None
    for col, spec in mapping.columns.items():
        local = spec.predicate.rsplit(":", 1)[-1].lower()
        if spec.datatype.endswith("date") and ("due" in local or "expir" in local):
            return col
    return None
