# -*- coding: utf-8 -*-
"""Two ways an uploaded document silently stops existing.

Both found live on bldg1, and both matter more now that the ontology NAMES its
documents (ontosage:documentRef): a topic can point at a document that retrieval
cannot see, so the question looks answerable and returns nothing.

  * a document saved from a Windows editor is cp1252, the UTF-8 read raised, the
    warning scrolled past, and the file was never indexed
  * input/.trash — where the admin console puts DELETED documents — looked like a
    building, so 24 removed files were embedded into a documents_.trash collection
"""

from pathlib import Path

import pytest

from orchestrator.services.document_indexer import DocumentIndexer, _read_document

pytestmark = pytest.mark.unit


# ── encoding ─────────────────────────────────────────────────────────────────


def test_a_cp1252_document_is_read_not_dropped(tmp_path):
    """An em-dash saved by a Windows editor is byte 0x97 — not valid UTF-8."""
    # 0x97 is the raw byte a Windows editor writes for an em-dash; it cannot be
    # produced by encoding U+0097, so the file is written byte-for-byte.
    p = tmp_path / "maintenance_log.md"
    p.write_bytes(b"# Maintenance Log \x97 Abacws Building")

    text = _read_document(p)

    assert text is not None, "the document must not be lost to its encoding"
    assert "Maintenance Log" in text


def test_utf8_is_still_preferred(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("Assemble at the north car park — promptly.", encoding="utf-8")
    assert "north car park" in _read_document(p)


def test_a_bom_does_not_leak_into_the_text(tmp_path):
    p = tmp_path / "doc.md"
    p.write_bytes(b"\xef\xbb\xbf# Fire Safety")
    assert _read_document(p).startswith("# Fire Safety")


def test_undecodable_bytes_cost_a_character_not_the_file(tmp_path):
    p = tmp_path / "doc.md"
    p.write_bytes(b"Fire assembly \xff\xfe point is the car park")
    text = _read_document(p)
    assert text is not None
    assert "car park" in text, "the rest of the document must survive"


def test_a_missing_file_still_returns_none(tmp_path):
    assert _read_document(tmp_path / "nope.md") is None


# ── which directories count as a building ────────────────────────────────────


def _building_dirs_scanned(root: Path) -> list:
    """The directories index_all_buildings would treat as buildings."""
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith(".") or d.name.startswith("_"):
            continue
        if (d / "documents").is_dir():
            out.append(d.name)
    return out


def test_deleted_documents_are_not_treated_as_a_building(tmp_path):
    """input/.trash is where the admin console puts DELETED documents. Indexing it
    kept removed content alive and searchable under its own collection."""
    for name in ("bldg1", ".trash", "_backup"):
        (tmp_path / name / "documents").mkdir(parents=True)
        (tmp_path / name / "documents" / "d.md").write_text("x", encoding="utf-8")

    assert _building_dirs_scanned(tmp_path) == ["bldg1"]


def test_the_scan_rule_is_implemented_not_just_asserted():
    """Guard the real code, so the rule cannot be dropped without this failing."""
    import inspect

    src = inspect.getsource(DocumentIndexer.index_all_buildings)
    assert 'startswith(".")' in src and 'startswith("_")' in src
