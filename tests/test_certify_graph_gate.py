# -*- coding: utf-8 -*-
"""Refuse to grade a duplicated graph (BUG-343, 2026-08-27).

Booting bldg3 for the first time since the context-less writer was stopped found it
duplicating again: 1,246,228 triples for 2,747 IRI subjects, and a single restart took
timeseries references 4,337 -> 5,268. The source fix was correct, committed, and green
under 3,583 tests. It had simply never reached that building, because docker compose
builds a project-tagged image per building and bldg3's was four weeks old. `restart`
does not rebuild, and neither does a plain `up -d` when the image already exists.

**No unit test can see which image is running.** So this gate does not check the fix; it
checks the SYMPTOM, which is visible from outside whatever caused it. One sensor has one
timeseries reference, so references divided by distinct UUIDs is 1 in a healthy graph.
It was 2.84 on bldg3, 27.4 on bldg1 and 95.2 on bldg2 before their rebuilds.

Placed in the certification preflight because a duplicated graph does not fail loudly --
it answers, and the numbers mean nothing. That is the same class as CAVEAT-173 and
BUG-177, which is what the preflight already exists for.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _mod():
    path = _REPO / "scripts" / "certify_building.py"
    spec = importlib.util.spec_from_file_location("_certify", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _with_rows(monkeypatch, csv_text):
    """Stand in for GraphDB, returning the CSV a fan-out query would."""
    mod = _mod()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return csv_text.encode()

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: _Resp())
    return mod


# ── the measurements that were actually taken ────────────────────────────────
@pytest.mark.parametrize(
    "refs,uuids,building",
    [(4337, 1528, "bldg3"), (78_800, 2876, "bldg1"), (273_000, 2868, "bldg2")],
)
def test_the_fan_out_each_building_actually_had_is_refused(monkeypatch, refs, uuids, building):
    mod = _with_rows(monkeypatch, f"refs,uuids\n{refs},{uuids}\n")
    ok, why = mod._graph_is_not_duplicated()
    assert not ok, f"{building} at {refs / uuids:.1f} copies/UUID should be refused"
    assert "rebuild" in why


def test_a_clean_graph_passes(monkeypatch):
    """bldg3 after the rebuild: 1528 references for 1528 UUIDs."""
    mod = _with_rows(monkeypatch, "refs,uuids\n1528,1528\n")
    ok, why = mod._graph_is_not_duplicated()
    assert ok, why
    assert "1.00" in why


def test_a_few_legitimate_second_references_are_not_a_defect(monkeypatch):
    """A building may declare a second reference on some points. The gate is set to
    catch duplication, not to forbid that -- a check that fires on correct data is a
    check somebody switches off."""
    mod = _with_rows(monkeypatch, "refs,uuids\n1600,1528\n")
    assert mod._graph_is_not_duplicated()[0] is True


# ── unknown is not failure ───────────────────────────────────────────────────
def test_an_unreachable_graphdb_does_not_fail_the_preflight(monkeypatch):
    """Refusing to certify because this script cannot see GraphDB would make the gate
    the reason runs stop happening."""
    mod = _mod()

    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(mod.urllib.request, "urlopen", _boom)
    ok, why = mod._graph_is_not_duplicated()
    assert ok
    assert "unknown" in why


def test_a_graph_with_no_timeseries_references_passes(monkeypatch):
    """Dividing by zero would crash the preflight on a building that has no linked
    sensors yet -- which is every building mid-onboarding."""
    mod = _with_rows(monkeypatch, "refs,uuids\n0,0\n")
    assert mod._graph_is_not_duplicated()[0] is True


def test_unparseable_output_does_not_crash(monkeypatch):
    mod = _with_rows(monkeypatch, "refs,uuids\nnot,numbers\n")
    assert mod._graph_is_not_duplicated()[0] is True


# ── and it is wired in, not merely available ─────────────────────────────────
def test_the_gate_runs_as_part_of_preflight():
    """The recurring defect in this codebase is a capability that is present, correct,
    tested, and that nothing calls (lessons.md #87, six instances)."""
    import inspect

    src = inspect.getsource(_mod().preflight)
    assert "_graph_is_not_duplicated()" in src
    assert "ok &= graph_ok" in src, "the result must be able to fail the preflight"


def test_the_repository_name_is_not_hardcoded():
    """Core scripts carry zero building literals; the repo name comes from the env."""
    import inspect

    src = inspect.getsource(_mod())
    assert 'os.getenv("GRAPHDB_REPOSITORY"' in src
