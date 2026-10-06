"""One pipeline turn at a time, per process (H2, TRIAL_TRACKER, 2026-10-06).

The host runs Ollama with OLLAMA_NUM_PARALLEL=1, so a second question that reaches the
model while one is generating queues INSIDE Ollama, where nothing reports it. The tester
sees silence until the client gives up. The owner's decision is to serialise on the host:
one turn runs, the next waits here, and the wait is logged and shown to a streaming client.

Two rules this module keeps:

* The queue wait does NOT count against REQUEST_TIMEOUT_SECS. ``run(..., timeout=...)``
  applies the timeout only once the lock is held, so a question that waited 40 s still gets
  its full budget to run.
* The lock is per process. The orchestrator runs as one uvicorn worker (orchestrator/Dockerfile),
  so per process is global. Background report jobs are NOT gated (they are not on a request
  path), so a long report can still hold the model while chat waits behind the model.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Optional, TypeVar

from shared.utils import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Shown to a client that is waiting, in plain words, rather than a silent timeout.
WAITING_MESSAGE = (
    "Another question is being answered right now. " "You are next, and your answer will follow."
)

_gate: Optional[asyncio.Lock] = None
_waiting = 0


def _lock() -> asyncio.Lock:
    """The process lock, created on first use so it binds to the running event loop."""
    global _gate
    if _gate is None:
        _gate = asyncio.Lock()
    return _gate


def busy() -> bool:
    """True while another turn holds the pipeline."""
    return _lock().locked()


def waiting() -> int:
    """How many turns are queued behind the one running."""
    return _waiting


@asynccontextmanager
async def turn(label: str) -> AsyncIterator[None]:
    """Hold the pipeline for one turn; log how long this turn queued."""
    global _waiting
    lock = _lock()
    if not lock.locked():
        await lock.acquire()
        waited = 0.0
    else:
        _waiting += 1
        logger.info(f"[pipeline_gate] {label}: another question is being answered; queued")
        started = time.monotonic()
        try:
            await lock.acquire()
        finally:
            _waiting -= 1
        waited = time.monotonic() - started
        logger.info(f"[pipeline_gate] {label}: started after {waited:.1f}s in the queue")
    try:
        yield
    finally:
        lock.release()


async def run(awaitable: Awaitable[T], label: str, timeout: Optional[float] = None) -> T:
    """Await one pipeline call under the gate; ``timeout`` starts only once the gate is held."""
    async with turn(label):
        if timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout)


async def stream(agen: AsyncIterator[Any], label: str) -> AsyncIterator[Any]:
    """Yield a pipeline's stream under the gate, releasing it when the stream ends or closes."""
    async with turn(label):
        async for item in agen:
            yield item
