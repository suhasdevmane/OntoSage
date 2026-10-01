# -*- coding: utf-8 -*-
"""The process must write down its own size, in a thread the event loop cannot starve.

BUG-1194: an hour of orchestrator logs during a 40 GiB runaway contained not one line
saying how big the process was, so the whole incident had to be reconstructed afterwards
from `docker stats` typed by hand. BUG-1191: two nested `asyncio.wait_for` deadlines --
180 s and 420 s -- were both silent on the same 3,412 s turn, which is the signature of a
loop that is not running its timer callbacks.

So the two things asserted here are the two things that make the next occurrence
diagnosable from the log alone:

* the sampler is an OS thread, not a coroutine, because an `asyncio.sleep` loop would go
  quiet at exactly the moment it was needed;
* it reports **event-loop lag**, which is the direct evidence for "the timers never
  fired" that nobody had.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

import orchestrator.services.process_watchdog as pw
from orchestrator.services.process_watchdog import (
    ProcessWatchdog,
    _Heartbeat,
    read_memory,
    start_watchdog,
    stop_watchdog,
)

pytestmark = pytest.mark.unit

_GIB = 1024.0**3


def test_read_memory_never_raises_and_always_names_its_source():
    mem = read_memory()
    assert set(mem) == {"used", "anon", "limit", "source"}
    assert mem["source"] in {"cgroup-v2", "cgroup-v1", "proc-rss", "unavailable"}
    if mem["used"] is not None:
        assert mem["used"] >= 0


def test_a_snapshot_carries_the_fields_the_log_line_needs():
    wd = ProcessWatchdog(interval_s=0.01)
    snap = wd.snapshot()
    for key in ("used_bytes", "anon_bytes", "limit_bytes", "peak_bytes", "loop_lag_s", "threads"):
        assert key in snap
    assert snap["loop_lag_s"] >= 0
    assert snap["threads"] >= 1


def test_the_first_snapshot_has_no_delta_and_the_second_does(monkeypatch):
    """A growth figure needs two readings; inventing one from a single sample is worse."""
    readings = iter([2.0 * _GIB, 5.0 * _GIB])
    monkeypatch.setattr(
        pw,
        "read_memory",
        lambda: {"used": next(readings), "anon": None, "limit": None, "source": "test"},
    )
    wd = ProcessWatchdog(interval_s=0.01)
    assert wd.snapshot()["delta_bytes"] is None
    assert wd.snapshot()["delta_bytes"] == pytest.approx(3.0 * _GIB)


def test_peak_is_a_high_water_mark_not_the_latest_value():
    wd = ProcessWatchdog(interval_s=0.01)
    wd._peak_used = 40.0 * _GIB  # the measured runaway
    snap = wd.snapshot()
    assert snap["peak_bytes"] == pytest.approx(40.0 * _GIB)


def test_the_warning_threshold_follows_the_container_limit_when_there_is_one():
    wd = ProcessWatchdog(interval_s=0.01)
    assert wd.mem_warn_bytes(8.0 * _GIB) == pytest.approx(4.8 * _GIB)  # 60% of 8 GiB


def test_the_warning_threshold_is_absolute_when_the_container_is_unlimited():
    """60% of an unlimited host is 28 GiB here, which is far too late to be a warning."""
    wd = ProcessWatchdog(interval_s=0.01)
    assert wd.mem_warn_bytes(None) == pytest.approx(6.0 * _GIB)


def test_an_explicit_threshold_wins_over_both():
    wd = ProcessWatchdog(interval_s=0.01, mem_warn_bytes=3.0 * _GIB)
    assert wd.mem_warn_bytes(8.0 * _GIB) == pytest.approx(3.0 * _GIB)


def test_memory_above_the_threshold_is_a_warning_not_an_info(caplog, monkeypatch):
    # Injected rather than read: this test must say the same thing on the Windows dev
    # host (no cgroup, no /proc — the watchdog correctly reports `mem=?` there) as in the
    # Linux container it is actually for.
    monkeypatch.setattr(
        pw,
        "read_memory",
        lambda: {"used": 40.02 * _GIB, "anon": 39.0 * _GIB, "limit": None, "source": "test"},
    )
    wd = ProcessWatchdog(interval_s=0.01, mem_warn_bytes=6.0 * _GIB)
    with caplog.at_level("INFO"):
        wd._emit()
    assert any(r.levelname == "WARNING" for r in caplog.records), caplog.text
    assert "mem=40.02GiB" in caplog.text
    assert "at or above" in caplog.text


def test_an_ordinary_sample_is_info(caplog):
    wd = ProcessWatchdog(interval_s=0.01, mem_warn_bytes=10_000.0 * _GIB, loop_lag_warn_s=1e9)
    with caplog.at_level("INFO"):
        wd._emit()
    assert caplog.records, "the watchdog emitted nothing at all"
    assert all(r.levelname != "WARNING" for r in caplog.records), caplog.text


def test_a_stalled_event_loop_is_reported_as_a_warning(caplog):
    """The evidence BUG-1191 needed and nobody had."""
    wd = ProcessWatchdog(interval_s=0.01, mem_warn_bytes=10_000.0 * _GIB, loop_lag_warn_s=0.0)
    with caplog.at_level("INFO"):
        wd._emit()
    assert any("has not ticked" in r.message for r in caplog.records), caplog.text


def test_the_line_renders_every_number_even_when_memory_is_unreadable():
    """A developer machine with no cgroup must still get a line, not a traceback."""
    wd = ProcessWatchdog(interval_s=0.01)
    line = wd.format(
        {
            "used_bytes": None,
            "anon_bytes": None,
            "limit_bytes": None,
            "peak_bytes": None,
            "delta_bytes": None,
            "loop_lag_s": 0.2,
            "threads": 4,
        }
    )
    assert line.startswith("[watchdog] ")
    assert "mem=?" in line and "loop_lag=0.2s" in line


def test_a_failing_sample_does_not_kill_the_thread(caplog, monkeypatch):
    """An instrument that can break the thing it watches is worse than no instrument."""
    wd = ProcessWatchdog(interval_s=0.01)

    def boom():
        wd._stop.set()  # one iteration, then let the loop exit
        raise RuntimeError("sysfs went away")

    monkeypatch.setattr(wd, "snapshot", boom)
    with caplog.at_level("WARNING"):
        wd._run()
    assert "sample failed" in caplog.text


def test_the_sampler_is_a_thread_so_a_blocked_loop_cannot_silence_it():
    """The whole point: it must keep reporting when the event loop does not run."""

    async def main():
        wd = ProcessWatchdog(interval_s=0.05, mem_warn_bytes=10_000.0 * _GIB)
        wd.start()
        try:
            names = [t.name for t in threading.enumerate()]
            assert "ontosage-watchdog" in names
            # Block the loop the way a synchronous lane does — no await at all.
            time.sleep(0.3)
            # The thread kept sampling while the loop was held.
            assert wd._samples >= 2, f"only {wd._samples} samples while the loop was blocked"
            # And it noticed the loop was not ticking.
            assert wd.heartbeat.lag_s() >= 0.25
        finally:
            wd.stop()

    asyncio.run(main())


def test_stop_is_safe_when_never_started():
    ProcessWatchdog(interval_s=0.01).stop()  # must not raise


def test_the_singleton_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("WATCHDOG_ENABLED", "false")
    assert start_watchdog() is None
    stop_watchdog()  # must not raise


def test_the_heartbeat_is_a_no_op_without_a_running_loop():
    hb = _Heartbeat()
    hb.start()  # no loop: must not raise
    assert hb.lag_s() >= 0
    hb.stop()
