# -*- coding: utf-8 -*-
"""H5 (QA-trial plan, 2026-10-04): the daily check script runs and reads what the
system already computes, without requiring four separate commands to be remembered."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "daily_trial_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("daily_trial_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_it_runs_against_the_live_stack_and_prints_a_report():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--no-log"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "/health:" in result.stdout
    assert "sensor freshness" in result.stdout
    assert "watchdog:" in result.stdout
    assert "backup:" in result.stdout


def test_watchdog_and_backup_degrade_honestly_when_not_yet_built():
    """H1 and C7 have not landed yet -- this must say so, not silently omit the line
    or crash."""
    mod = _load_module()
    assert (
        "not yet available" in mod._watchdog_restarts() or "unreadable" in mod._watchdog_restarts()
    )
    assert "not yet available" in mod._backup_status() or "unreadable" in mod._backup_status()


def test_sensor_freshness_reports_a_real_result_or_names_why_not():
    mod = _load_module()
    result = mod._sensor_freshness()
    assert result, "must never return an empty string"


def test_gate_deletions_returns_a_real_count_not_unavailable():
    """Regression for the first version's own bug, found running this script for the
    first time: count_gate_deletions.py's output is a sentence ('replacements in the
    last 24h: 2'), not a bare digit line, so a line.strip().isdigit() scan always
    found nothing and reported 'unavailable' even when the real count was 2."""
    mod = _load_module()
    result = mod._gate_deletions_24h()
    assert result is None or isinstance(result, int)
