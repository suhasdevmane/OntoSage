# -*- coding: utf-8 -*-
"""I3 (QA-trial plan, 2026-10-04): the derived-open-set script runs and reports
structurally, against the real trackers -- not a fixture, since the whole point is
that it reads the trackers THEMSELVES rather than a copy of them.
"""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "trial_coverage_audit.py"


def test_the_script_exists_and_is_importable_as_a_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("trial_coverage_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")


def test_it_runs_against_the_real_trackers_and_exits_zero():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "TRIAL_TRACKER.csv:" in result.stdout
    assert "FIX_TRACKER.csv:" in result.stdout
    assert "Blocked on an owner decision" in result.stdout


def test_every_not_done_row_from_the_real_tracker_is_listed():
    """The report's own count must match a fresh, independent read of the CSV --
    not trust the script's arithmetic against itself."""
    with open(REPO / "tasks" / "TRIAL_TRACKER.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    not_done = [r for r in rows if r["Status"] != "DONE"]

    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=30
    )
    for r in not_done:
        assert r["ID"] in result.stdout, f"{r['ID']} (status={r['Status']}) missing from report"
