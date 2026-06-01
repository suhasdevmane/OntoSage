"""
Tests for the async job queue (Task 5).
"""
import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_job_queue_module_importable():
    """JobQueue module must expose the required API."""
    from orchestrator.services.job_queue import JobQueue, JobStatus

    assert hasattr(JobQueue, "create_job")
    assert hasattr(JobQueue, "update_job")
    assert hasattr(JobQueue, "get_job")
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.DONE.value == "done"
    assert JobStatus.FAILED.value == "failed"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_job_lifecycle():
    """A job goes queued → running → done and result is retrievable."""
    from orchestrator.services.job_queue import JobQueue, JobStatus

    store = {}

    async def fake_set(key, value, ex=None):
        store[key] = value

    async def fake_get(key):
        return store.get(key)

    mock_redis = MagicMock()
    mock_redis.set = fake_set
    mock_redis.get = fake_get

    jq = JobQueue(mock_redis)
    job_id = await jq.create_job("conv-123", "Generate energy report")
    assert job_id is not None

    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.QUEUED.value

    await jq.update_job(job_id, JobStatus.RUNNING)
    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.RUNNING.value

    await jq.update_job(job_id, JobStatus.DONE, result={"response": "Report complete"})
    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.DONE.value
    assert job["result"]["response"] == "Report complete"


@pytest.mark.unit
def test_jobs_endpoint_registered():
    """GET /jobs/{job_id} must be registered in the FastAPI app."""
    from orchestrator.main import app

    routes = [getattr(r, "path", "") for r in app.routes]
    assert "/jobs/{job_id}" in routes, f"Route missing. Registered routes: {routes}"
