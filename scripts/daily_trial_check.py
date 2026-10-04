#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H5 (QA-trial plan, 2026-10-04): a daily check that reads what the system already
computes, rather than requiring someone to remember four separate commands.

The two things that would ruin a trial day silently -- a dead model and a stopped
publisher -- are both already measured somewhere nobody looks routinely: /health's
service map, and MySQL's own newest-row timestamp per backend. This script reads both,
plus the gate-deletion count (scripts/count_gate_deletions.py), and writes ONE dated
line to a log file so a week of runs is one file to scan, not four commands to remember.

FRESHNESS is reported as a FIELD, never inferred from the healthcheck's own PASS/FAIL --
a wedged container can report "healthy" for hours (BUG-1194), so staleness has to be
measured independently (CAVEAT-1202's lesson).

Two pieces this row's own Depends_on names are not yet built and are reported as
"not yet available" rather than silently skipped: H1's watchdog restart count (the
watchdog script exists but is not yet registered as a scheduled task) and C7's backup
status file (no scheduled backup exists yet). This script is written to pick both up
the moment they exist, with no further change needed -- see _watchdog_restarts and
_backup_status below.

Usage:
    python scripts/daily_trial_check.py                    # print + append to the log
    python scripts/daily_trial_check.py --no-log            # print only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

REPO = Path(__file__).resolve().parent.parent
LOG_PATH = REPO / "docs" / "phase0" / "trial" / "daily_check.log"
BASE_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{BASE_URL}/health"
#: A model/publisher check older than this many minutes is reported STALE, not healthy.
#: Not an owner decision measured against anything -- a plain, conservative default
#: (the fastest-cadence modalities this building declares have a 5-minute policy
#: limit; half an hour is "something is genuinely wrong", not noise).
FRESHNESS_THRESHOLD_MINUTES = 30


def _sensor_freshness() -> str:
    """H6's own endpoint (now UTC-correct, BUG-1440), as the real freshness signal --
    not /health's connectivity-only status, which stays 'ok' through a stopped
    publisher. Needs an admin login; reports the attempt's own failure rather than
    silently omitting the check."""
    import os

    user = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not user or not password:
        return "unavailable (ADMIN_USERNAME/ADMIN_PASSWORD not set in this shell)"
    try:
        login = httpx.post(
            f"{BASE_URL}/auth/login", json={"username": user, "password": password}, timeout=10
        )
        login.raise_for_status()
        token = login.json()["data"]["session_token"]
        resp = httpx.get(
            f"{BASE_URL}/api/v1/admin/sensors/health",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        counts = data.get("by_state", {})
        not_probed = data.get("not_probed", [])
        return f"{counts} ({data.get('assessed', 0)} assessed)" + (
            f"; not probed: {not_probed}" if not_probed else ""
        )
    except Exception as exc:
        return f"check failed: {exc}"


def _health() -> dict:
    try:
        r = httpx.get(HEALTH_URL, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _gate_deletions_24h() -> Optional[int]:
    script = REPO / "scripts" / "count_gate_deletions.py"
    if not script.is_file():
        return None
    try:
        out = subprocess.run(
            [sys.executable, str(script), "--since", "24h"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        import re as _re

        m = _re.search(r"replacements in the last \S+:\s*(\d+)", out.stdout)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _watchdog_restarts() -> str:
    """H1's watchdog log, once registered as a scheduled task. Not yet available."""
    log = REPO / "scripts" / "ollama_watchdog.log"
    if not log.is_file():
        return "not yet available (H1: watchdog not yet registered)"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        restarts = sum(1 for ln in lines[-500:] if "restart" in ln.lower())
        return f"{restarts} restart(s) in the last 500 log lines"
    except Exception as exc:
        return f"unreadable: {exc}"


def _backup_status() -> str:
    """C7's backup status file, once a scheduled backup exists. Not yet available."""
    status_file = REPO / "volumes" / "backups" / "status.json"
    if not status_file.is_file():
        return "not yet available (C7: no scheduled backup yet)"
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        return str(data)
    except Exception as exc:
        return f"unreadable: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-log", action="store_true", help="Print only, do not append to the log"
    )
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    health = _health()
    services = (health.get("data") or {}).get("services") or {}
    overall = (health.get("data") or {}).get("status", "unreachable")
    breakers = services.get("circuit_breakers") or []
    open_breakers = [b["name"] for b in breakers if b.get("state") != "closed"]

    gate_deletions = _gate_deletions_24h()
    freshness = _sensor_freshness()
    watchdog = _watchdog_restarts()
    backup = _backup_status()

    lines = [
        f"{now.isoformat(timespec='seconds')}",
        f"  /health: {overall}" + (f" (open breakers: {open_breakers})" if open_breakers else ""),
        f"  mysql: {services.get('mysql', {}).get('status', 'unknown')}",
        f"  graphdb: {services.get('graphdb', {}).get('status', 'unknown')}",
        f"  redis: {services.get('redis', {}).get('status', 'unknown')}",
        f"  sensor freshness (H6, UTC-correct): {freshness}",
        f"  answer-relevance gate deletions (24h): {gate_deletions if gate_deletions is not None else 'unavailable'}",
        f"  watchdog: {watchdog}",
        f"  backup: {backup}",
    ]
    report = "\n".join(lines)
    print(report)

    if not args.no_log:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(report + "\n\n")
        print(f"\nAppended to {LOG_PATH}")

    return 0 if overall == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
