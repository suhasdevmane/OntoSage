"""similarity_reindex.py — debounced, self-coalescing rebuild of the GraphDB similarity index.

Adding sensors / TTL triples triggers a rebuild of the (Lucene text) similarity index the sensor
RAG retriever queries. A naive rebuild-per-change is wasteful: a burst of N registrations would
queue N full-graph rebuilds (minutes each). This debouncer instead:

  * **collapses a burst** into ONE eventual rebuild — every request during the quiet window is
    folded into a single run;
  * **waits out** any rebuild already running (via the rebuild trigger's own retry) and then, once
    it starts a rebuild, **polls GraphDB's real status** until it reports built — so "done" is
    honest, not guessed;
  * **re-runs once more** if new triples arrive WHILE a rebuild is in progress (a rebuild snapshots
    the repo at its start, so mid-rebuild additions would otherwise be missed).

The single async worker guarantees only one rebuild is ever in flight from our side. Exposes a
status the admin console polls to know when newly-added data is actually searchable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_StatusFn = Callable[[], Awaitable[Dict[str, Any]]]
_RebuildFn = Callable[[], Awaitable[Dict[str, Any]]]


class SimilarityRebuildDebouncer:
    """Coalesces similarity-index rebuild requests into one eventual, status-tracked rebuild."""

    # Max times one worker pass will (re-)fire a rebuild while waiting out a pre-existing one,
    # before giving up — guards against a wedged GraphDB index that never leaves REBUILDING.
    _MAX_FIRES = 3

    def __init__(
        self,
        rebuild_fn: _RebuildFn,
        status_fn: _StatusFn,
        *,
        delay: float = 3.0,
        poll_interval: float = 5.0,
        poll_max_s: float = 900.0,
    ) -> None:
        self._rebuild_fn = rebuild_fn
        self._status_fn = status_fn
        self._delay = delay
        self._poll_interval = poll_interval
        self._poll_max_s = poll_max_s

        self._task: Optional["asyncio.Task[Any]"] = None
        self._dirty = False
        self._state = "idle"  # idle | pending | rebuilding
        self._last_requested_at: Optional[float] = None
        self._last_triggered_at: Optional[float] = None
        self._last_completed_at: Optional[float] = None
        self._completed_count = 0
        self._graphdb_status: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request(self) -> Dict[str, Any]:
        """Mark the index dirty and ensure a debounced rebuild is scheduled. Non-blocking."""
        self._dirty = True
        self._last_requested_at = time.time()
        if self._task is None or self._task.done():
            try:
                self._task = asyncio.create_task(self._worker())
            except RuntimeError:
                # No running loop (sync / unit-test context) — status still reflects the request.
                logger.debug("[similarity_reindex] no running event loop; rebuild deferred")
        return self.status()

    def status(self) -> Dict[str, Any]:
        """Snapshot of the debouncer + last-known GraphDB index status."""
        return {
            "state": self._state,
            "pending": self._dirty,
            "ready": self._state == "idle" and not self._dirty,
            "last_requested_at": self._last_requested_at,
            "last_triggered_at": self._last_triggered_at,
            "last_completed_at": self._last_completed_at,
            "completed_count": self._completed_count,
            "graphdb_status": self._graphdb_status,
        }

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        try:
            while True:
                # Debounce: wait for a quiet window; any request during the wait restarts it,
                # so a whole burst of registrations collapses into the single rebuild below.
                self._state = "pending"
                self._dirty = False
                await asyncio.sleep(self._delay)
                if self._dirty:
                    continue

                # Fire a rebuild covering everything requested so far. We are the sole coordinator:
                # if a pre-existing rebuild is already running ("already_rebuilding"), it may predate
                # our request, so we wait it out and fire a FRESH one that includes our triples —
                # bounded by _MAX_FIRES so a wedged GraphDB index can't spin forever.
                self._state = "rebuilding"
                self._last_triggered_at = time.time()
                self._dirty = False  # additions AFTER this must cause a follow-up rebuild
                try:
                    for fire in range(self._MAX_FIRES):
                        res = await self._rebuild_fn()
                        if not res.get("ok"):
                            logger.warning(
                                f"[similarity_reindex] rebuild trigger failed: {res.get('error')}"
                            )
                            break
                        await self._await_graphdb_done()
                        # If we started a fresh rebuild (204), the just-added triples are covered.
                        if res.get("status") == "rebuilding":
                            break
                        # Otherwise a pre-existing rebuild just finished — loop to start our own.
                        logger.info(
                            "[similarity_reindex] pre-existing rebuild finished; "
                            f"firing a fresh one ({fire + 1}/{self._MAX_FIRES})"
                        )
                except Exception as e:  # pragma: no cover - defensive; worker must not die
                    logger.error(f"[similarity_reindex] rebuild error: {e}", exc_info=True)

                self._last_completed_at = time.time()
                self._completed_count += 1
                logger.info(
                    f"[similarity_reindex] rebuild #{self._completed_count} settled "
                    f"(graphdb_status={self._graphdb_status})"
                )
                # Triples added while rebuilding? Do one more pass to include them.
                if self._dirty:
                    continue
                break
        finally:
            self._state = "idle"
            self._task = None

    async def _await_graphdb_done(self) -> None:
        """Poll the real GraphDB index status until it is no longer (re)building (bounded)."""
        waited = 0.0
        # Give GraphDB a beat to register the rebuild before the first poll.
        await asyncio.sleep(min(self._poll_interval, 3.0))
        while waited < self._poll_max_s:
            try:
                st = await self._status_fn()
                self._graphdb_status = st.get("status")
                if not st.get("building"):
                    return
            except Exception as e:  # pragma: no cover - status is best-effort
                logger.debug(f"[similarity_reindex] status poll error: {e}")
            await asyncio.sleep(self._poll_interval)
            waited += self._poll_interval
        logger.warning(
            "[similarity_reindex] stopped waiting for GraphDB rebuild after "
            f"{self._poll_max_s:.0f}s (last status={self._graphdb_status})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Module singleton — the one similarity-rebuild gateway
# ─────────────────────────────────────────────────────────────────────────────

_debouncer: Optional[SimilarityRebuildDebouncer] = None


def get_similarity_debouncer() -> SimilarityRebuildDebouncer:
    """Return the process-wide similarity-rebuild debouncer (created on first use)."""
    global _debouncer
    if _debouncer is None:
        from orchestrator.services.ontology_manager import (
            get_similarity_index_status,
            rebuild_similarity_index,
        )

        _debouncer = SimilarityRebuildDebouncer(
            rebuild_similarity_index, get_similarity_index_status
        )
    return _debouncer
