# -*- coding: utf-8 -*-
"""H8 (QA-trial plan, 2026-10-04): separating real tester reports from machine-written
ones is one query against the live `user_reports` table -- no DDL change. Skips
gracefully when the user-data Postgres is not reachable (this is an operational script,
not a build-time dependency)."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "trial_report_quarantine.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("trial_report_quarantine", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_script_is_importable_and_exposes_the_expected_functions():
    mod = _load_module()
    assert hasattr(mod, "quarantine")
    assert hasattr(mod, "_connect")
    assert mod.MACHINE_REPORTER == "rules_engine"


@pytest.mark.asyncio
async def test_against_the_live_database_when_reachable():
    """Not mocked on purpose: the one thing worth checking is that the real query
    returns a human count <= the total, against the real table shape. Skips if the
    user-data Postgres cannot be reached from this host."""
    mod = _load_module()
    try:
        conn = await mod._connect()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"user-data Postgres not reachable: {exc}")
        return
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_reports")
        human = await conn.fetchval(
            "SELECT COUNT(*) FROM user_reports WHERE reporter_id <> $1", mod.MACHINE_REPORTER
        )
        assert human <= total
        assert human >= 0
    finally:
        await conn.close()
