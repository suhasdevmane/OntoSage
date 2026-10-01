# -*- coding: utf-8 -*-
"""A healthcheck that cannot fail is worse than none, because it misdirects triage (BUG-1194).

2026-09-30: the orchestrator ran to 40.02 GiB of 46.64 GiB at 3210% CPU and served nothing
for an hour, while `docker ps` said `Up 3 hours (healthy)` the whole time. The status was
frozen -- `docker inspect` showed `FailingStreak: 2` beside `healthy` with a last check an
hour old, because the probe had stopped completing and a stale PASS renders identically to
a fresh one. Anyone triaging from `docker ps` would have ruled the orchestrator out first,
and that is exactly what happened.

Three properties are pinned here, each for a reason the incident supplies:

* **The probe bounds itself** (`curl --max-time`). Docker's `timeout:` only helps when the
  daemon can reap a hung exec; on the day it could not. curl exiting 28 on its own is a
  failure the health monitor records.
* **A low retry count and a short interval**, so an unresponsive process is `unhealthy`
  within about a minute rather than two and a half.
* **A memory ceiling with swap disabled**, which is the only control that confines a
  runaway to its own container instead of starving the host that runs the probe.

The numbers are asserted as BOUNDS, not equalities: tightening them further is an
improvement and must not fail this test. Loosening them undoes the fix and must.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: `docker-compose.yml` is whichever building is ACTIVE and is absent from the committed
#: tree by Workflow rule 8, so it is checked when present and never required.
COMPOSE_FILES = sorted(REPO.glob("docker-compose*.yml"))

SERVICE_RE = re.compile(r"^  ([a-z0-9_.-]+):\s*$")

#: Seconds. Interval x retries must reach `unhealthy` inside this, or a wedged process
#: sits green long enough for someone to look elsewhere first.
MAX_SECONDS_TO_UNHEALTHY = 120


def _orchestrator_block(text: str):
    """The `orchestrator:` service block, or None when this file has no such service."""
    lines = text.splitlines(keepends=True)
    marks = [(m.group(1), i) for i, ln in enumerate(lines) if (m := SERVICE_RE.match(ln))]
    for idx, (name, start) in enumerate(marks):
        if name != "orchestrator":
            continue
        end = marks[idx + 1][1] if idx + 1 < len(marks) else len(lines)
        return "".join(lines[start:end])
    return None


def _orchestrator_files():
    out = []
    for path in COMPOSE_FILES:
        # The timeseries-backends file declares databases only.
        if "timeseries-backends" in path.name:
            continue
        block = _orchestrator_block(path.read_text(encoding="utf-8"))
        if block:
            out.append((path.name, block))
    return out


def _seconds(block: str, key: str):
    m = re.search(rf"^\s*{key}:\s*(\d+)([smh])\s*$", block, re.M)
    if not m:
        return None
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def test_there_is_an_orchestrator_to_check():
    """Guards the guard: an empty list would pass everything below."""
    assert _orchestrator_files(), "no compose file declares an orchestrator service"


@pytest.mark.parametrize("name,block", _orchestrator_files(), ids=lambda v: str(v)[:40])
def test_the_probe_bounds_itself(name, block):
    """curl must carry --max-time: the daemon's own timeout did not save us."""
    test_line = re.search(r"^\s*test:\s*(\[.*\])\s*$", block, re.M)
    assert test_line, f"{name}: orchestrator has no healthcheck test line"
    assert "--max-time" in test_line.group(1), (
        f"{name}: the healthcheck probe has no --max-time, so it relies entirely on the "
        "daemon reaping a hung exec — which is what froze at `healthy` on 2026-09-30"
    )


@pytest.mark.parametrize("name,block", _orchestrator_files(), ids=lambda v: str(v)[:40])
def test_unhealthy_is_reached_within_two_minutes(name, block):
    interval = _seconds(block, "interval")
    retries = re.search(r"^\s*retries:\s*(\d+)\s*$", block, re.M)
    assert interval is not None, f"{name}: no healthcheck interval"
    assert retries, f"{name}: no healthcheck retries"
    worst = interval * int(retries.group(1))
    assert worst <= MAX_SECONDS_TO_UNHEALTHY, (
        f"{name}: interval {interval}s x retries {retries.group(1)} = {worst}s to reach "
        f"unhealthy, over the {MAX_SECONDS_TO_UNHEALTHY}s budget"
    )
    assert int(retries.group(1)) <= 3, f"{name}: retries {retries.group(1)} is not a low count"


@pytest.mark.parametrize("name,block", _orchestrator_files(), ids=lambda v: str(v)[:40])
def test_the_daemon_timeout_outlasts_the_probes_own(name, block):
    """curl must lose the race to itself, not be killed: a killed exec is the freeze."""
    daemon = _seconds(block, "timeout")
    probe = re.search(r'"--max-time",\s*"(\d+)"', block)
    assert daemon is not None, f"{name}: no healthcheck timeout"
    assert probe, f"{name}: --max-time has no value"
    assert int(probe.group(1)) < daemon, (
        f"{name}: curl --max-time {probe.group(1)}s is not shorter than the daemon's "
        f"timeout {daemon}s, so docker kills the probe instead of letting it exit"
    )


@pytest.mark.parametrize("name,block", _orchestrator_files(), ids=lambda v: str(v)[:40])
def test_the_container_has_a_memory_ceiling_and_no_swap(name, block):
    mem = re.search(r"^\s*mem_limit:\s*(\S+)\s*$", block, re.M)
    swap = re.search(r"^\s*memswap_limit:\s*(\S+)\s*$", block, re.M)
    assert mem, (
        f"{name}: the orchestrator has no mem_limit. Without one a runaway takes the whole "
        "host with it, which is how the healthcheck's own exec stopped completing"
    )
    assert swap, f"{name}: mem_limit without memswap_limit lets the runaway swap instead of dying"
    assert mem.group(1) == swap.group(1), (
        f"{name}: memswap_limit {swap.group(1)} != mem_limit {mem.group(1)}; swap must be "
        "disabled or the container thrashes for an hour instead of failing in a second"
    )


@pytest.mark.parametrize("name,block", _orchestrator_files(), ids=lambda v: str(v)[:40])
def test_the_start_period_still_covers_the_measured_cold_start(name, block):
    """Shortening the interval must not re-open BUG-246's false unhealthy on every boot."""
    start = _seconds(block, "start_period")
    assert start is not None and start >= 300, (
        f"{name}: start_period {start}s is under the ~4m15s cold start measured for "
        "lifespan, which makes every boot report a false (unhealthy) — BUG-246"
    )
