"""
Unit tests for ReindexService.

All tests are @pytest.mark.unit — no live services required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(**kwargs):
    from orchestrator.services.reindex_service import ReindexService

    return ReindexService(**kwargs)


# ---------------------------------------------------------------------------
# 1. Import
# ---------------------------------------------------------------------------


def test_import():
    """ReindexService is importable."""
    from orchestrator.services.reindex_service import ReindexService  # noqa: F401


# ---------------------------------------------------------------------------
# 2. start() returns a non-empty job id
# ---------------------------------------------------------------------------


def test_start_returns_job_id():
    """start() returns a non-empty string job_id."""
    svc = make_service()
    job_id = svc.start(["capability"], building_id="bldg1")
    assert isinstance(job_id, str)
    assert len(job_id) > 0


# ---------------------------------------------------------------------------
# 3. status() reflects job immediately after start()
# ---------------------------------------------------------------------------


def test_start_records_job_immediately():
    """status() returns found=True immediately after start(), before _run completes."""
    svc = make_service()
    job_id = svc.start(["capability"], building_id="bldg1")
    result = svc.status(job_id)
    assert result["found"] is True
    assert result["id"] == job_id


# ---------------------------------------------------------------------------
# 4. Unknown job id returns found=False
# ---------------------------------------------------------------------------


def test_status_unknown_job():
    """status() for an unknown job_id returns {'found': False}."""
    svc = make_service()
    result = svc.status("does-not-exist")
    assert result == {"found": False}


# ---------------------------------------------------------------------------
# 5. list_jobs on fresh instance
# ---------------------------------------------------------------------------


def test_list_jobs_empty():
    """list_jobs() on a fresh instance returns an empty list."""
    svc = make_service()
    assert svc.list_jobs() == []


# ---------------------------------------------------------------------------
# 6. list_jobs contains the started job
# ---------------------------------------------------------------------------


def test_list_jobs_has_started_job():
    """After start(), list_jobs() returns a list of length >= 1."""
    svc = make_service()
    svc.start(["capability"])
    jobs = svc.list_jobs()
    assert len(jobs) >= 1


# ---------------------------------------------------------------------------
# 7. _run calls capability_indexer.index_building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_capability_indexer():
    """_run calls index_building and stores points/status/entries in results."""
    mock_result = MagicMock()
    mock_result.status = "indexed"
    mock_result.points = 42
    mock_result.entries = 10

    cap_indexer = MagicMock()
    cap_indexer.index_building = AsyncMock(return_value=mock_result)

    svc = make_service(capability_indexer=cap_indexer)
    job_id = svc.start(["capability"], building_id="bldg1")

    # Yield to the event loop to allow the background task to run
    await asyncio.sleep(0)
    # Give it a couple more ticks in case there are awaited sub-calls
    await asyncio.sleep(0)

    status = svc.status(job_id)
    assert status["found"] is True
    assert status["results"]["capability"]["points"] == 42
    assert status["results"]["capability"]["status"] == "indexed"
    assert status["results"]["capability"]["entries"] == 10


# ---------------------------------------------------------------------------
# 8. capability indexer missing → skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_capability_indexer_missing():
    """When no capability_indexer is provided, result contains 'skipped'."""
    svc = make_service()  # no indexers
    job_id = svc.start(["capability"], building_id="bldg1")

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = svc.status(job_id)
    assert status["results"]["capability"]["skipped"] == "indexer not available"


# ---------------------------------------------------------------------------
# 9. Unknown target → skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ontology_similarity_target(monkeypatch):
    """The ontology_similarity target delegates to the debounced similarity gateway."""
    from orchestrator.services import similarity_reindex

    class _FakeDebouncer:
        def request(self):
            return {"state": "pending", "ready": False}

    monkeypatch.setattr(similarity_reindex, "get_similarity_debouncer", lambda: _FakeDebouncer())

    svc = make_service()  # no indexers needed for this target
    job_id = svc.start(["ontology_similarity"], building_id="bldg1")

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = svc.status(job_id)
    assert status["results"]["ontology_similarity"]["state"] == "pending"
    assert status["status"] == "done"


@pytest.mark.asyncio
async def test_run_unknown_target():
    """Unknown target names go into results with skipped='unknown target'."""
    svc = make_service()
    job_id = svc.start(["nonsense"], building_id="bldg1")

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = svc.status(job_id)
    assert status["results"]["nonsense"]["skipped"] == "unknown target"


# ---------------------------------------------------------------------------
# 10. Exception sets job status to "error"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_exception_sets_error_status():
    """An exception in index_building sets job status='error' with error message."""
    cap_indexer = MagicMock()
    cap_indexer.index_building = AsyncMock(side_effect=RuntimeError("boom"))

    svc = make_service(capability_indexer=cap_indexer)
    job_id = svc.start(["capability"], building_id="bldg1")

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    status = svc.status(job_id)
    assert status["status"] == "error"
    assert "boom" in status["error"]


# ---------------------------------------------------------------------------
# 11. elapsed_s is a float >= 0
# ---------------------------------------------------------------------------


def test_elapsed_s_present():
    """status() includes elapsed_s as a float >= 0."""
    svc = make_service()
    job_id = svc.start(["floor_plans"])
    result = svc.status(job_id)
    assert isinstance(result["elapsed_s"], float)
    assert result["elapsed_s"] >= 0.0


# ---------------------------------------------------------------------------
# 12. list_jobs newest first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_newest_first():
    """list_jobs() returns jobs newest first (by started_at descending)."""
    svc = make_service()
    first_id = svc.start(["floor_plans"])
    # Sleep long enough for Windows timer resolution (>= 15 ms) to register a difference.
    await asyncio.sleep(0.05)
    second_id = svc.start(["floor_plans"])

    jobs = svc.list_jobs()
    assert len(jobs) >= 2
    assert jobs[0]["id"] == second_id
    assert jobs[1]["id"] == first_id
