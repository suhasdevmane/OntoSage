# -*- coding: utf-8 -*-
"""The rag-service ontology importer was the graph bloat (CAVEAT-287, 2026-08-26).

It scanned the SAME ``/app/input/*.ttl`` the orchestrator's ttl_uploader already ingests,
but POSTed each file to ``/statements`` with the context header commented out. POST
appends, so every restart of that service added another full copy of every ontology file —
Brick_v1.4 and Brick+extensions included — into the DEFAULT graph, each time with fresh
blank nodes that nothing can deduplicate.

Measured before it was disabled: 20.3M triples for a building with 10,969 IRI subjects;
15.4M of them SHACL machinery, 4.19M blank-node subjects, and 55,706 timeseries references
for 2,872 distinct UUIDs — 19.4 copies of each, up from 13.4 the previous day purely from
development restarts. Named graphs held 422,892 triples; the rest was in the default graph.

Two guarantees are pinned here: the importer does not run by default, and if someone turns
it back on it names a context so a re-import replaces instead of appending.
"""

import inspect
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_RAG = Path(__file__).resolve().parents[1] / "rag-service" / "graphdbRAG"


def _read(name: str) -> str:
    return (_RAG / name).read_text(encoding="utf-8")


def test_the_importer_does_not_run_by_default():
    """An unconditional create_task here is what made every restart grow the graph."""
    src = _read("main.py")
    assert "import_ontology()" in src, "the importer should still exist, just be gated"
    assert "RAG_IMPORT_ONTOLOGY" in src

    # The call must sit INSIDE the env guard. Indentation alone cannot tell a guarded
    # call from a bare one, so check the structure: the guard appears first, and the
    # call is indented deeper than it.
    lines = src.split("\n")
    guard = next(
        (
            i
            for i, ln in enumerate(lines)
            if "RAG_IMPORT_ONTOLOGY" in ln and ln.lstrip().startswith("if ")
        ),
        None,
    )
    assert guard is not None, "no `if` guard on the RAG_IMPORT_ONTOLOGY flag"
    call = next(
        (i for i, ln in enumerate(lines) if "asyncio.create_task(import_ontology())" in ln),
        None,
    )
    assert call is not None and call > guard, "the import runs before/outside the guard"
    indent = lambda ln: len(ln) - len(ln.lstrip())  # noqa: E731
    assert indent(lines[call]) > indent(lines[guard]), "the call is not inside the guard block"


def test_the_env_flag_defaults_to_off():
    src = _read("main.py")
    m = re.search(r'getenv\(\s*"RAG_IMPORT_ONTOLOGY"\s*,\s*"([^"]*)"', src)
    assert m is not None, "the flag must have an explicit default"
    assert m.group(1).lower() in ("false", "0", "no"), m.group(1)


def test_a_context_is_named_when_importing():
    """Without a context every file lands in the default graph and POST appends."""
    src = _read("import_ontology.py")
    assert "X-GraphDB-Context" in src
    commented = re.search(r"^\s*#\s*\"X-GraphDB-Context\"", src, re.MULTILINE)
    assert commented is None, "the context header is commented out again"
    assert re.search(
        r"^\s*context = f", src, re.MULTILINE
    ), "context must be assigned, not commented"


def test_the_orchestrator_uploader_still_owns_ingestion():
    """ttl_uploader uploads each file into its own named graph with a SHA skip, which is
    why the rag-service copy was redundant as well as harmful."""
    from orchestrator.services import ttl_uploader

    src = inspect.getsource(ttl_uploader)
    assert "context" in src.lower()
