# -*- coding: utf-8 -*-
"""A resource watchdog that keeps reporting when the event loop has stopped running.

WHY THIS EXISTS (BUG-1194, 2026-09-30)
--------------------------------------
The orchestrator ran to **40.02 GiB of 46.64 GiB and 3210% CPU**, served nothing for an
hour, and `docker ps` said `Up 3 hours (healthy)` the whole time -- the healthcheck had
stopped completing, so the last PASS simply froze. The runaway had to be reconstructed
afterwards from `docker stats` taken by hand, because **nothing in the process had ever
written down its own size**. There was no line in an hour of logs saying how big it was.

Two properties follow from that, and they are the whole design:

1. **The sampler runs in a plain OS thread, not on the event loop.** The failure we are
   instrumenting is one where asyncio timers demonstrably did not fire -- a 180 s
   `LLM_TIMEOUT_S` and a 420 s `WORKFLOW_TIMEOUT_S`, both `asyncio.wait_for`, both silent
   on the same 3,412 s turn (BUG-1191). An `asyncio.sleep` loop would have gone quiet at
   exactly the moment it was needed. A `threading.Thread` doing `time.sleep` keeps its
   slot whenever the interpreter runs at all.

2. **It measures the loop as well as the memory.** A separate one-second heartbeat task
   stamps a monotonic clock; the thread reports how stale that stamp is. A large
   `loop_lag` is the direct, positive evidence that "the event loop never reached its
   timer callbacks" -- the cheapest explanation for BUG-1191 and, until now, an untested
   one. If it happens again the logs will say so rather than leaving it to inference.

WHAT THE NUMBERS MEAN
---------------------
`used` is computed the way ``docker stats`` computes it -- cgroup usage minus inactive
file cache -- so the figure in the log is directly comparable with the 1.69-2.01 GiB
steady state and the 40.02 GiB runaway already recorded on BUG-1194. `anon` is the
non-reclaimable half of it and is the better runaway signal: page cache is evicted under
pressure, anonymous memory is not.

This module never raises. An instrument that can break the thing it watches is worse than
no instrument.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_GIB = 1024.0**3

#: How often the sampler thread writes a line. 30 s costs three file reads and keeps an
#: hour of runaway to ~120 lines.
_DEFAULT_INTERVAL_S = 30.0

#: Report at WARNING above this share of the container's memory ceiling. Only used when a
#: finite cgroup limit exists -- an unlimited container falls back to the absolute default
#: below, because "60% of the host" is 28 GiB here and far too late to be a warning.
_LIMIT_WARN_FRACTION = 0.60

#: The absolute WARNING threshold, in GiB, when the container has no memory limit.
#: Steady state under a full 51-case gate load measured 1.69-2.01 GiB on 2026-09-30, so
#: 6 GiB is three times anything this process has legitimately needed and still leaves an
#: hour of headroom below the 40 GiB that actually wedged the machine.
_DEFAULT_MEM_WARN_GIB = 6.0

#: How stale the event-loop heartbeat may get before the sampler calls it out. A healthy
#: loop is a fraction of a second behind; 30 s means a coroutine has held the loop without
#: awaiting for half a minute, which is already a defect even when it recovers.
_DEFAULT_LOOP_LAG_WARN_S = 30.0

#: The heartbeat task's own period, and therefore the FLOOR on a meaningful reading.
#:
#: `loop_lag` is time since the last stamp, so on a perfectly healthy loop it reads
#: anywhere from 0 up to one full period depending on where in the cycle the sampler
#: landed. At 1.0 s the first live run printed `loop_lag=0.8s` while the loop was in
#: excellent health, which reads like a finding and is not one. 0.25 s keeps an idle
#: reading visibly small, so any figure above about half a second is real. The cost is
#: four `asyncio.sleep` wakeups a second, which is nothing next to the ECA engine's
#: existing 10 s MySQL poll.
#:
#: ANYTHING BELOW THIS NUMBER IS CADENCE, NOT LAG. Only the WARNING threshold means
#: something, and it is two orders of magnitude above it.
_HEARTBEAT_PERIOD_S = 0.25


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back loudly rather than raising."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"[watchdog] {name}={raw!r} is not a number; using {default}")
        return default


def _read_int_file(path: str) -> Optional[int]:
    """The integer in a one-line sysfs file, or None when it is absent or says 'max'."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        return None
    if not text or text == "max":
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def _read_stat_file(path: str) -> Dict[str, int]:
    """A cgroup ``*.stat`` file as a dict; empty when it cannot be read."""
    out: Dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        out[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        return {}
    return out


def _proc_rss_bytes() -> Optional[int]:
    """This process's resident set size, for hosts with no cgroup files."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_memory() -> Dict[str, Optional[float]]:
    """Container memory in bytes, using the same arithmetic as ``docker stats``.

    Returns ``used`` (cgroup usage minus inactive file cache), ``anon`` (non-reclaimable),
    ``limit`` (None when unlimited) and ``source``. Every value may be None: this runs on
    Windows and macOS developer machines too, where none of these files exist.
    """
    # cgroup v2 -- what Docker Desktop and every current Linux host present.
    current = _read_int_file("/sys/fs/cgroup/memory.current")
    if current is not None:
        stat = _read_stat_file("/sys/fs/cgroup/memory.stat")
        inactive = stat.get("inactive_file", 0)
        return {
            "used": float(max(current - inactive, 0)),
            "anon": float(stat["anon"]) if "anon" in stat else None,
            "limit": (lambda v: float(v) if v is not None else None)(
                _read_int_file("/sys/fs/cgroup/memory.max")
            ),
            "source": "cgroup-v2",
        }

    # cgroup v1.
    current = _read_int_file("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if current is not None:
        stat = _read_stat_file("/sys/fs/cgroup/memory/memory.stat")
        inactive = stat.get("total_inactive_file", stat.get("inactive_file", 0))
        limit = _read_int_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        # v1 spells "unlimited" as a number near 2**63, not as "max".
        if limit is not None and limit > (1 << 62):
            limit = None
        return {
            "used": float(max(current - inactive, 0)),
            "anon": float(stat["total_rss"]) if "total_rss" in stat else None,
            "limit": float(limit) if limit is not None else None,
            "source": "cgroup-v1",
        }

    rss = _proc_rss_bytes()
    if rss is not None:
        return {"used": float(rss), "anon": float(rss), "limit": None, "source": "proc-rss"}

    return {"used": None, "anon": None, "limit": None, "source": "unavailable"}


class _Heartbeat:
    """A monotonic stamp the event loop refreshes, so a thread can tell when it stopped."""

    def __init__(self) -> None:
        self._last = time.monotonic()
        self._task: Optional["asyncio.Task[None]"] = None

    def lag_s(self) -> float:
        """Seconds since the loop last ticked. Read from any thread; a float is atomic."""
        return max(time.monotonic() - self._last, 0.0)

    async def _run(self) -> None:
        while True:
            self._last = time.monotonic()
            await asyncio.sleep(_HEARTBEAT_PERIOD_S)

    def start(self) -> None:
        """Attach to the running loop. No loop (a sync test) is not an error."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is None or self._task.done():
            self._last = time.monotonic()
            self._task = loop.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None


class ProcessWatchdog:
    """Samples container memory and event-loop lag from a thread of its own."""

    def __init__(
        self,
        interval_s: Optional[float] = None,
        mem_warn_bytes: Optional[float] = None,
        loop_lag_warn_s: Optional[float] = None,
    ) -> None:
        self.interval_s = (
            interval_s
            if interval_s is not None
            else _env_float("WATCHDOG_INTERVAL_S", _DEFAULT_INTERVAL_S)
        )
        self.loop_lag_warn_s = (
            loop_lag_warn_s
            if loop_lag_warn_s is not None
            else _env_float("WATCHDOG_LOOP_LAG_WARN_S", _DEFAULT_LOOP_LAG_WARN_S)
        )
        self._explicit_mem_warn = mem_warn_bytes
        self.heartbeat = _Heartbeat()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._peak_used: float = 0.0
        self._prev_used: Optional[float] = None
        self._samples: int = 0

    # ── thresholds ────────────────────────────────────────────────────────────
    def mem_warn_bytes(self, limit: Optional[float]) -> float:
        """The WARNING threshold: a share of the ceiling when there is one, else absolute."""
        if self._explicit_mem_warn is not None:
            return self._explicit_mem_warn
        env = _env_float("WATCHDOG_MEM_WARN_GIB", 0.0)
        if env > 0:
            return env * _GIB
        if limit is not None and limit > 0:
            return limit * _LIMIT_WARN_FRACTION
        return _DEFAULT_MEM_WARN_GIB * _GIB

    # ── one sample ────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        """One reading, as the log line renders it. Safe to call from any thread."""
        mem = read_memory()
        used = mem.get("used")
        lag = self.heartbeat.lag_s()
        if used is not None:
            self._peak_used = max(self._peak_used, used)
        delta = None
        if used is not None and self._prev_used is not None:
            delta = used - self._prev_used
        out: Dict[str, Any] = {
            "used_bytes": used,
            "anon_bytes": mem.get("anon"),
            "limit_bytes": mem.get("limit"),
            "source": mem.get("source"),
            "peak_bytes": self._peak_used or None,
            "delta_bytes": delta,
            "loop_lag_s": lag,
            "threads": threading.active_count(),
        }
        self._prev_used = used
        self._samples += 1
        return out

    @staticmethod
    def _gib(value: Optional[float]) -> str:
        return "?" if value is None else f"{value / _GIB:.2f}GiB"

    def format(self, snap: Dict[str, Any]) -> str:
        """The one-line rendering. Kept short: this is written every interval, for ever."""
        parts = [
            f"mem={self._gib(snap['used_bytes'])}",
            f"anon={self._gib(snap['anon_bytes'])}",
            f"peak={self._gib(snap['peak_bytes'])}",
        ]
        if snap["limit_bytes"]:
            pct = 100.0 * (snap["used_bytes"] or 0.0) / snap["limit_bytes"]
            parts.append(f"limit={self._gib(snap['limit_bytes'])}({pct:.0f}%)")
        if snap["delta_bytes"] is not None:
            sign = "+" if snap["delta_bytes"] >= 0 else "-"
            parts.append(f"delta={sign}{abs(snap['delta_bytes']) / _GIB:.2f}GiB")
        parts.append(f"loop_lag={snap['loop_lag_s']:.1f}s")
        parts.append(f"threads={snap['threads']}")
        return "[watchdog] " + " ".join(parts)

    def _emit(self) -> None:
        snap = self.snapshot()
        line = self.format(snap)
        used = snap["used_bytes"]
        reasons = []
        if used is not None and used >= self.mem_warn_bytes(snap["limit_bytes"]):
            reasons.append(
                f"memory at or above {self._gib(self.mem_warn_bytes(snap['limit_bytes']))}"
            )
        if snap["loop_lag_s"] >= self.loop_lag_warn_s:
            reasons.append(f"event loop has not ticked for {snap['loop_lag_s']:.1f}s")
        if reasons:
            logger.warning(f"{line} -- {'; '.join(reasons)}")
        else:
            logger.info(line)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._emit()
            except Exception as e:  # never let the instrument kill the process
                logger.warning(f"[watchdog] sample failed: {e}")
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        """Start the heartbeat task and the sampler thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.heartbeat.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ontosage-watchdog", daemon=True)
        self._thread.start()
        logger.info(
            f"[watchdog] started: interval={self.interval_s:g}s "
            f"loop_lag_warn={self.loop_lag_warn_s:g}s source={read_memory()['source']}"
        )

    def stop(self) -> None:
        """Stop sampling. Safe to call when never started."""
        self._stop.set()
        self.heartbeat.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None


_instance: Optional[ProcessWatchdog] = None


def start_watchdog() -> Optional[ProcessWatchdog]:
    """Start the singleton watchdog. Returns None when disabled by WATCHDOG_ENABLED=false."""
    global _instance
    if (os.environ.get("WATCHDOG_ENABLED", "true") or "").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        logger.info("[watchdog] disabled by WATCHDOG_ENABLED")
        return None
    if _instance is None:
        _instance = ProcessWatchdog()
    _instance.start()
    return _instance


def stop_watchdog() -> None:
    """Stop the singleton watchdog if one is running."""
    global _instance
    if _instance is not None:
        _instance.stop()


def current_watchdog() -> Optional[ProcessWatchdog]:
    """The running singleton, for callers that want a snapshot on demand."""
    return _instance
