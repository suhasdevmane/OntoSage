"""
JobQueue — lightweight Redis-backed async job store for long-running requests.

Jobs live at key ``job:{job_id}`` with a 1-hour TTL.
Background coroutines call update_job() on completion.
Clients poll GET /jobs/{job_id}.
"""

import json
import secrets
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_JOB_TTL_S = 3600  # 1 hour


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobQueue:
    """Thin wrapper around a Redis client for job lifecycle management."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def create_job(
        self,
        conversation_id: str,
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        """Create a new queued job and return its job_id."""
        job_id = secrets.token_urlsafe(12)
        payload = {
            "job_id": job_id,
            "conversation_id": conversation_id,
            "user_message": user_message[:200],
            "intent": intent,
            "status": JobStatus.QUEUED.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "result": None,
            "error": None,
        }
        await self._redis.set(f"job:{job_id}", json.dumps(payload), ex=_JOB_TTL_S)
        logger.info(f"[job_queue] created job_id={job_id} intent={intent}")
        return job_id

    async def update_job(
        self,
        job_id: str,
        status: "JobStatus",
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update job status and optionally set result/error. Resets TTL."""
        raw = await self._redis.get(f"job:{job_id}")
        if not raw:
            logger.warning(f"[job_queue] update_job: job_id={job_id} not found")
            return
        payload = json.loads(raw)
        payload["status"] = status.value
        payload["updated_at"] = datetime.utcnow().isoformat()
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        await self._redis.set(f"job:{job_id}", json.dumps(payload), ex=_JOB_TTL_S)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the job payload dict, or None if not found or expired."""
        raw = await self._redis.get(f"job:{job_id}")
        if not raw:
            return None
        return json.loads(raw)
