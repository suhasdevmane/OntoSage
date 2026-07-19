"""
ReindexService — lightweight async job queue for Qdrant re-indexing.

The admin console calls start() after uploading a new TTL or registering new
sensors.  start() returns immediately with a job_id; the actual work runs as
an asyncio background task.  Callers poll status(job_id) until finished_at is
set and status is "done" or "error".

Supported targets: 'capability' | 'documents' | 'floor_plans' | 'ontology_similarity'

'ontology_similarity' rebuilds the GraphDB similarity index (NOT a Qdrant collection) that the
sensor RAG retriever queries — the reindex that surfaces newly-registered sensors in semantic
search. It needs no indexer instance, so it works even in a bare ReindexService.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)


class ReindexService:
    """Manages background Qdrant re-index jobs."""

    # Cap retained job history so a long-lived process can't leak the dict.
    _MAX_JOBS = 100

    def __init__(
        self,
        capability_indexer: Optional[Any] = None,
        document_indexer: Optional[Any] = None,
    ) -> None:
        self._capability_indexer = capability_indexer
        self._document_indexer = document_indexer
        self._jobs: Dict[str, Dict[str, Any]] = {}
        # Retain a strong reference to each background task. asyncio keeps only a
        # WEAK reference, so a task whose handle we drop can be garbage-collected
        # mid-run and silently cancelled — the "job stuck in pending" symptom.
        self._tasks: Dict[str, "asyncio.Task[Any]"] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_indexers(
        self,
        capability_indexer: Optional[Any] = None,
        document_indexer: Optional[Any] = None,
    ) -> None:
        """Refresh the indexer references (called by the single reindex gateway each request).

        Resolving indexers late — rather than binding them once at construction — lets one shared
        service be created early in startup (before the indexers exist) yet still run capability /
        document reindexes correctly once they are attached to app.state.
        """
        self._capability_indexer = capability_indexer
        self._document_indexer = document_indexer

    def start(self, targets: List[str], *, building_id: str = "bldg1") -> str:
        """Queue a re-index job and return the job_id (8-char UUID prefix) immediately."""
        job_id = uuid.uuid4().hex[:8]
        job: Dict[str, Any] = {
            "id": job_id,
            "targets": list(targets),
            "building_id": building_id,
            # "pending" until the background task actually starts; _run flips it
            # to "running". If there is no event loop the task never runs and the
            # status honestly stays "pending" (not a misleading "running").
            "status": "pending",
            "started_at": time.time(),
            "finished_at": None,
            "results": {},
            "error": None,
        }
        self._jobs[job_id] = job
        self._evict_old_jobs()
        try:
            task = asyncio.create_task(self._run(job_id, targets, building_id))
            self._tasks[job_id] = task
            task.add_done_callback(lambda t, jid=job_id: self._tasks.pop(jid, None))
        except RuntimeError:
            # No running event loop — sync / unit-test context; task is recorded but not scheduled.
            logger.debug(
                f"[reindex_service] job={job_id} no running event loop; background task deferred"
            )
        logger.info(
            f"[reindex_service] started job={job_id} targets={targets} building={building_id}"
        )
        return job_id

    def _evict_old_jobs(self) -> None:
        """Bound ``_jobs`` to ``_MAX_JOBS``, dropping the oldest FINISHED jobs
        first so an in-flight job is never evicted."""
        excess = len(self._jobs) - self._MAX_JOBS
        if excess <= 0:
            return
        # Finished jobs (finished_at set) sort before running ones; oldest first.
        candidates = sorted(
            self._jobs.values(),
            key=lambda j: (j["finished_at"] is None, j["started_at"]),
        )
        for job in candidates[:excess]:
            self._jobs.pop(job["id"], None)

    def status(self, job_id: str) -> Dict[str, Any]:
        """Return job status dict. Returns {'found': False} for unknown job_id."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"found": False}

        now = time.time()
        finished = job["finished_at"]
        elapsed = (finished if finished is not None else now) - job["started_at"]

        return {
            "found": True,
            "id": job["id"],
            "status": job["status"],
            "targets": job["targets"],
            "results": dict(job["results"]),
            "error": job["error"],
            "elapsed_s": round(elapsed, 4),
        }

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Return all jobs via status(), newest first (by started_at descending)."""
        sorted_jobs = sorted(
            self._jobs.values(),
            key=lambda j: j["started_at"],
            reverse=True,
        )
        return [self.status(j["id"]) for j in sorted_jobs]

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    async def _run(self, job_id: str, targets: List[str], building_id: str) -> None:
        """Execute each target sequentially; update job dict on completion."""
        job = self._jobs[job_id]
        job["status"] = "running"
        try:
            had_error = False
            for target in targets:
                try:
                    result = await self._run_target(target, building_id)
                    job["results"][target] = result
                except Exception as exc:
                    logger.error(
                        f"[reindex] {job_id} target={target} error: {exc}",
                        exc_info=True,
                    )
                    had_error = True
                    job["error"] = str(exc)  # last error wins for top-level error field
                    job["results"][target] = {"error": str(exc)}

            job["status"] = "error" if had_error else "done"
        finally:
            job["finished_at"] = time.time()
            logger.info(f"[reindex_service] job={job_id} finished status={job['status']}")

    async def _run_target(self, target: str, building_id: str) -> Dict[str, Any]:
        """Dispatch a single target; return a result dict."""
        if target == "capability":
            if self._capability_indexer is None:
                return {"skipped": "indexer not available"}
            result = await self._capability_indexer.index_building(building_id)
            return {
                "status": result.status,
                "points": result.points,
                "entries": result.entries,
            }

        if target == "documents":
            if self._document_indexer is None:
                return {"skipped": "indexer not available"}
            result = await self._document_indexer.ingest_all()
            n = result if isinstance(result, int) else (len(result) if result else 0)
            return {"ingested": n}

        if target == "floor_plans":
            return {"skipped": "not implemented"}

        if target == "ontology_similarity":
            # Route through the debounced similarity gateway (the one similarity-rebuild path) so a
            # burst of jobs still collapses into a single eventual, status-tracked rebuild.
            from orchestrator.services.similarity_reindex import (
                get_similarity_debouncer,
            )

            return get_similarity_debouncer().request()

        return {"skipped": "unknown target"}
