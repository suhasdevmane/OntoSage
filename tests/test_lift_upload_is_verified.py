# -*- coding: utf-8 -*-
"""A lift is only lifted when the upload SUCCEEDED (BUG-382).

Found on the second building, which is what the portability test is for. Nine record
documents logged "lifted N records"; three of the nine were missing from the graph.
GraphDB had rejected them with HTTP 500 "Couldn't precommit transaction" — a transient
precommit conflict while another writer held the repository — and `upload_ttl` reported
that by RETURNING {"ok": False}, not by raising. The caller only caught exceptions, so a
rejected upload was announced as a successful lift.

Claiming an upload happened when it did not is the failure this project guards against
everywhere else, and it is worse here than an outright error: the register looks present,
the question looks answerable, and the answer is silently computed over nothing.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.document_indexer import DocumentIndexer

pytestmark = pytest.mark.unit

SOURCE = inspect.getsource(DocumentIndexer._lift_record_document)


def test_the_upload_result_is_checked_not_just_the_absence_of_an_exception():
    assert 'outcome.get("ok")' in SOURCE, (
        "upload_ttl returns {'ok': bool, ...} and does not raise on a non-2xx; only the "
        "result can say whether the graph landed"
    )


def test_success_is_reported_only_inside_the_ok_branch():
    ok_at = SOURCE.index('outcome.get("ok")')
    lifted_at = SOURCE.index("lifted {result.instances}")
    assert ok_at < lifted_at, "the success log must sit inside the ok branch"


def test_a_rejected_upload_returns_zero_and_a_failure():
    tail = SOURCE[SOURCE.index("NOT lifted") :]
    assert "return 0, [" in tail, "a rejected upload must lift nothing and say so"


def test_a_transient_rejection_is_retried():
    """ "Couldn't precommit transaction" is contention, not a bad document."""
    assert "for attempt in range(3)" in SOURCE
    assert "asyncio.sleep" in SOURCE


def test_the_failure_is_surfaced_to_the_caller():
    """An ingest that lifted nothing must not report a healthy status."""
    from orchestrator.services.document_indexer import DocIndexResult

    assert "lift_failures" in DocIndexResult.__dataclass_fields__
    assert "lifted_records" in DocIndexResult.__dataclass_fields__


# ── the SHA cache must not suppress a lift that never happened ────────────────


def test_a_sha_skip_still_retries_a_missing_graph():
    """The SHA records that the PROSE was indexed, and nothing about the lift.

    A document whose prose indexed and whose graph upload was rejected would otherwise be
    skipped for ever, because the file never changes. Measured on the second building:
    three registers were rejected with HTTP 500, and the next boot skipped all three on a
    SHA match. This is the trap CLAUDE.md documents for TTL uploads, in a new place.
    """
    source = inspect.getsource(DocumentIndexer.index_building)
    skip_at = source.index("sha match")
    tail = source[skip_at : skip_at + 1400]
    assert "_lift_record_document" in tail
    assert "if_missing=True" in tail


def test_the_missing_graph_check_errs_towards_leaving_it_alone():
    """Wrongly believing a graph is empty would rewrite every register on every boot."""
    source = inspect.getsource(DocumentIndexer._graph_has_triples)
    assert source.count("return True") >= 2, "every failure path must assume it is present"
