"""
Unit tests for SimilarityRebuildDebouncer — collapses a burst of rebuild requests into one
eventual rebuild, and re-runs once if triples arrive mid-rebuild. Uses tiny delays + fake
rebuild/status callables so the tests are fast and deterministic (no GraphDB).
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services.similarity_reindex import SimilarityRebuildDebouncer

pytestmark = pytest.mark.unit


async def _built_status():
    return {"status": "BUILT", "building": False}


async def _settle(d, timeout=3.0):
    """Wait until the debouncer is idle and not pending."""
    waited = 0.0
    while waited < timeout:
        s = d.status()
        if s["state"] == "idle" and not s["pending"]:
            return
        await asyncio.sleep(0.02)
        waited += 0.02
    raise AssertionError(f"debouncer did not settle; status={d.status()}")


@pytest.mark.asyncio
async def test_collapses_burst_into_one_rebuild():
    calls = {"n": 0}

    async def rebuild():
        calls["n"] += 1
        return {"ok": True, "status": "rebuilding"}

    d = SimilarityRebuildDebouncer(
        rebuild, _built_status, delay=0.05, poll_interval=0.01, poll_max_s=1.0
    )
    for _ in range(5):  # burst within the debounce window
        d.request()
        await asyncio.sleep(0.005)

    await _settle(d)
    assert calls["n"] == 1  # five requests collapsed into ONE rebuild
    assert d.status()["completed_count"] == 1
    assert d.status()["ready"] is True
    assert d.status()["graphdb_status"] == "BUILT"


@pytest.mark.asyncio
async def test_reruns_when_dirtied_during_rebuild():
    calls = {"n": 0}
    inside_first = asyncio.Event()

    async def rebuild():
        calls["n"] += 1
        if calls["n"] == 1:
            inside_first.set()
            await asyncio.sleep(0.05)  # stay "in rebuild" long enough to be dirtied
        return {"ok": True, "status": "rebuilding"}

    d = SimilarityRebuildDebouncer(
        rebuild, _built_status, delay=0.02, poll_interval=0.01, poll_max_s=1.0
    )
    d.request()
    await asyncio.wait_for(inside_first.wait(), timeout=1.0)
    d.request()  # arrives WHILE the first rebuild runs → must trigger a second

    await _settle(d)
    assert calls["n"] == 2  # mid-rebuild addition forced a follow-up rebuild


@pytest.mark.asyncio
async def test_request_returns_status_and_no_loop_is_safe():
    async def rebuild():
        return {"ok": True, "status": "rebuilding"}

    d = SimilarityRebuildDebouncer(rebuild, _built_status, delay=0.02)
    st = d.request()
    assert set(st) >= {"state", "pending", "ready", "completed_count"}
    assert st["pending"] is True
    await _settle(d)
    assert d.status()["completed_count"] == 1


@pytest.mark.asyncio
async def test_refires_after_preexisting_rebuild_finishes():
    """If a pre-existing rebuild is running ('already_rebuilding'), the worker waits it out and
    fires a fresh one so the just-added triples are covered."""
    seq = ["already_rebuilding", "rebuilding"]
    fired = {"n": 0}

    async def rebuild():
        i = min(fired["n"], len(seq) - 1)
        fired["n"] += 1
        return {"ok": True, "status": seq[i]}

    d = SimilarityRebuildDebouncer(
        rebuild, _built_status, delay=0.02, poll_interval=0.01, poll_max_s=1.0
    )
    d.request()
    await _settle(d)
    assert fired["n"] == 2  # one wait-out + one fresh rebuild
    assert d.status()["completed_count"] == 1
