# -*- coding: utf-8 -*-
"""A certification run is bracketed by health checks (2026-08-27).

The project wrote this rule down after being burned by it: *grading a run is only
valid if the stack was healthy for all of it.* Nothing enforced it anywhere.

Three artifacts had to be thrown away for exactly that reason:

* CAVEAT-173 / BUG-176 - a container recreated mid-run produced a 9.2%-coverage
  figure that meant nothing.
* BUG-177 - the LLM went down mid-run and its fallback text reads like an answer.
  One such fallback was a row dump that would have graded as a PASS.

Both were caught afterwards, by someone reading the rows behind a number that
looked wrong. This makes the check happen before a single question is asked, and
again at the end, and writes the verdict INTO the artifact rather than into a log
nobody re-reads.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cert():
    path = _REPO / "scripts" / "certify_building.py"
    spec = importlib.util.spec_from_file_location("_certify", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- preflight refuses rather than explains afterwards ------------------------
def test_a_dead_stack_fails_preflight(cert, monkeypatch):
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (0, ""))
    monkeypatch.setattr(cert, "_container_snapshot", dict)
    ok, checks, _ = cert.preflight(None)
    assert ok is False
    assert any("FAIL" in c and "/health" in c for c in checks)


def test_the_wrong_building_fails_preflight(cert, monkeypatch):
    """Certifying bldg2 against a stack serving bldg1 produces a scorecard labelled
    with the wrong building - which is worse than no scorecard."""
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {}}'))
    monkeypatch.setattr(cert, "_container_snapshot", dict)
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    ok, checks, _ = cert.preflight("bldg2")
    assert ok is False
    assert any("expected 'bldg2'" in c for c in checks)


def test_an_unhealthy_container_fails_preflight(cert, monkeypatch):
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    monkeypatch.setattr(
        cert, "_container_snapshot", lambda: {"a": "Up 3 minutes (healthy)", "b": "Up (unhealthy)"}
    )
    ok, checks, _ = cert.preflight("bldg1")
    assert ok is False
    assert any("unhealthy: ['b']" in c for c in checks)


def test_a_dead_provider_behind_a_healthy_container_fails(cert, monkeypatch):
    """BUG-177's exact blind spot: /health is 200 while the model is gone, and the
    fallback text grades as an answer."""
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "down"}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    monkeypatch.setattr(cert, "_container_snapshot", dict)
    ok, checks, _ = cert.preflight("bldg1")
    assert ok is False
    assert any("ollama" in c and "FAIL" in c for c in checks)


def test_a_healthy_stack_passes(cert, monkeypatch):
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "ok"}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    monkeypatch.setattr(cert, "_container_snapshot", lambda: {"a": "Up 5 minutes (healthy)"})
    ok, _checks, before = cert.preflight("bldg1")
    assert ok is True
    assert before["building"] == "bldg1"


# -- postflight catches what changed DURING the run ---------------------------
def test_a_container_restart_mid_run_invalidates_the_run(cert, monkeypatch):
    """CAVEAT-173 exactly: a recreate mid-run, and a number that meant nothing."""
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "ok"}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    before = {"containers": {"orch": "Up 20 minutes (healthy)"}, "building": "bldg1"}
    monkeypatch.setattr(cert, "_container_snapshot", lambda: {"orch": "Up 2 minutes (healthy)"})
    ok, checks = cert.postflight(before, "bldg1")
    assert ok is False
    assert any("restarted" in c and "orch" in c for c in checks)


def test_a_vanished_container_invalidates_the_run(cert, monkeypatch):
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "ok"}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    before = {"containers": {"orch": "Up 20 minutes", "gone": "Up 20 minutes"}, "building": "bldg1"}
    monkeypatch.setattr(cert, "_container_snapshot", lambda: {"orch": "Up 20 minutes"})
    ok, checks = cert.postflight(before, "bldg1")
    assert ok is False
    assert any("vanished" in c and "gone" in c for c in checks)


def test_a_building_swap_mid_run_invalidates_the_run(cert, monkeypatch):
    """A scorecard that spans two buildings describes neither."""
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "ok"}}'))
    monkeypatch.setattr(cert, "_container_snapshot", lambda: {"orch": "Up 20 minutes"})
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg2")
    before = {"containers": {"orch": "Up 20 minutes"}, "building": "bldg1"}
    ok, checks = cert.postflight(before, None)
    assert ok is False
    assert any("ACTIVE BUILDING changed" in c for c in checks)


def test_an_unchanged_stack_stays_valid(cert, monkeypatch):
    monkeypatch.setattr(cert, "_get", lambda *a, **k: (200, '{"services": {"ollama": "ok"}}'))
    monkeypatch.setattr(cert, "_active_building", lambda: "bldg1")
    snap = {"orch": "Up 20 minutes (healthy)"}
    monkeypatch.setattr(cert, "_container_snapshot", lambda: dict(snap))
    ok, _ = cert.postflight({"containers": dict(snap), "building": "bldg1"}, "bldg1")
    assert ok is True


# -- and the verdict is written where it will be read -------------------------
def test_the_verdict_is_stamped_into_the_artifact():
    """A log nobody re-reads is not a warning. The scorecard has to carry it."""
    src = (_REPO / "scripts" / "certify_building.py").read_text(encoding="utf-8")
    assert "## Run validity:" in src
    assert "Do not publish these numbers" in src
    assert "card.write_text" in src
