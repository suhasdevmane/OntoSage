# -*- coding: utf-8 -*-
"""Coverage and freshness must be reported together (CAVEAT-233).

"2,688 of 2,688 declared sensors resolve to rows" was exactly true of bldg1 while roughly
7.4% of those streams had produced a reading in the last day. Both statements describe the
same sensors; the first one alone invites the reader to believe the second. I published that
number in this project's own connectivity audit and had to qualify it afterwards, which is
why the fix is in the code rather than in a proofreading habit.

Two distinctions carry the whole fix, and both are easy to lose in a later refactor:

1. **Freshness is per UUID, never per table.** bldg1's ``noise_data`` has a table-level
   ``MAX(datetime)`` of "now" and exactly one current stream out of 236 — a single live sensor
   makes the store look live. A table-level check would restate the illusion in new words.

2. **Unmeasured is not zero.** A store with an unreachable adapter must not be rendered as a
   store where nothing is streaming; the first is a broken connection, the second is a dead
   building, and an operator would act differently on each.

A third property is deliberate rather than incidental: freshness does NOT change the verdict.
bldg1's wide ``sensor_data`` is a real archived snapshot the user loaded on purpose. It
answers historical questions correctly, and failing it for not streaming would be a false
alarm on data that is doing exactly what it should.
"""

import asyncio  # asyncio.run(), never get_event_loop(): under pytest-asyncio's auto mode
import re  # the ambient loop is closed by the time these sync tests run in a full suite
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
METRICS = (REPO / "orchestrator" / "services" / "building_metrics.py").read_text(encoding="utf-8")
MAIN = (REPO / "orchestrator" / "main.py").read_text(encoding="utf-8")
ONBOARD = (REPO / "orchestrator" / "services" / "onboarding_status.py").read_text(encoding="utf-8")


# ── the measurement itself ───────────────────────────────────────────────────


def _by_store(**stores):
    """Run reporting_uuids_by_store against fake adapters. `stores` maps a storage key to the
    rows its probe returns, or to None for an adapter that cannot be reached."""
    import json
    import tempfile

    from orchestrator.services import building_metrics as bm

    smap, adapters = {}, {}

    class _Res:
        def __init__(self, data):
            self.success, self.data = True, data

    class _Adapter:
        def __init__(self, rows):
            self.table = "readings"  # narrow shape

        async def execute_query(self, sql):
            return _Res(self._rows)

    for i, (key, rows) in enumerate(stores.items()):
        for u in {"u1", "u2", "u3"}:
            smap[f"{key}:{u}"] = {"uuid": u, "storage": key}
        if rows is None:
            adapters[key] = None
        else:
            a = _Adapter(rows)
            a._rows = [{"uuid": u} for u in rows]
            adapters[key] = a

    tmp = Path(tempfile.mkdtemp()) / "sensor_map.json"
    tmp.write_text(json.dumps(smap), encoding="utf-8")

    class _Registry:
        is_available = True

        def get(self, key):
            return adapters.get(key)

    import shared.config as cfg
    from orchestrator.services.adapters import registry as reg

    old_path, old_reg = cfg.settings.SENSOR_MAP_PATH, reg.adapter_registry
    cfg.settings.SENSOR_MAP_PATH = str(tmp)
    reg.adapter_registry = _Registry()
    try:
        return asyncio.run(bm.reporting_uuids_by_store(24))
    finally:
        cfg.settings.SENSOR_MAP_PATH, reg.adapter_registry = old_path, old_reg


def test_a_store_reports_only_the_uuids_that_actually_appeared():
    out = _by_store(alpha=["u1"])
    assert out == {"alpha": {"u1"}}, "freshness must be the per-uuid set, not the store"


def test_an_unreachable_store_is_absent_rather_than_empty():
    """The distinction the admin surfaces depend on: absent = unknown, empty = nothing fresh."""
    out = _by_store(alpha=["u1"], broken=None)
    assert "broken" not in out, (
        "an unreachable adapter was recorded as a store with zero reporting sensors — a "
        "broken connection then reads as a building that stopped streaming"
    )
    assert out["alpha"] == {"u1"}


def test_a_store_that_answered_with_nothing_fresh_is_present_and_empty():
    out = _by_store(alpha=[])
    assert out == {"alpha": set()}, "a successful probe finding nothing is a MEASURED zero"


def test_the_count_wrapper_still_returns_distinct_sensors():
    """The metrics snapshot's number is unchanged by the refactor, including de-duplication
    of a uuid that reports into two stores."""
    from orchestrator.services import building_metrics as bm

    async def _fake(_w=24):
        return {"a": {"u1", "u2"}, "b": {"u2"}}

    old = bm.reporting_uuids_by_store
    bm.reporting_uuids_by_store = _fake
    try:
        n = asyncio.run(bm._default_reporting_provider(24))
    finally:
        bm.reporting_uuids_by_store = old
    assert n == 2


# ── the surfaces that report coverage ────────────────────────────────────────


def test_every_coverage_surface_also_reports_freshness():
    """The three places that publish "N of M sensors have rows"."""
    assert '"total_reporting"' in MAIN, "the batch coverage badge omits freshness"
    assert '"reporting": reporting' in MAIN, "the per-datasource card omits freshness"
    assert "reporting in the last" in ONBOARD, "the onboarding readiness line omits freshness"


def test_the_unmeasured_case_survives_into_the_readout():
    """`.get(db_key, set())` would silently turn "not measured" back into zero."""
    body = MAIN[MAIN.index("async def _answerability_for(") :][:2200]
    assert "db_key in reporting" in body
    assert not re.search(
        r"reporting\.get\(db_key,\s*set\(\)\)", body
    ), "defaulting a missing store to an empty set reintroduces unmeasured-reads-as-zero"


def test_freshness_does_not_decide_the_verdict():
    """A historical-only store is a legitimate configuration — bldg1's wide `sensor_data` is a
    real snapshot the user loaded deliberately. `level` must stay a function of coverage."""
    body = MAIN[MAIN.index("async def _answerability_for(") :][:2200]
    chain = body[body.index("if not dec:") : body.index("fresh = None")]
    # The decision, not the prose around it: every branch that sets `level`, and the
    # conditions guarding them. A comment mentioning freshness is fine; a branch is not.
    decision = [
        ln.split("#", 1)[0].strip()
        for ln in chain.splitlines()
        if re.match(r"\s*(if|elif|else|level\s*=)", ln)
    ]
    assert decision, "level chain not found — this test is reading the wrong code"
    for ln in decision:
        assert "reporting" not in ln and "fresh" not in ln, (
            f"freshness reached the level computation ({ln!r}) — an archive that answers "
            "historical questions correctly would be flagged as a broken datasource"
        )


def test_the_onboarding_step_is_not_failed_by_staleness():
    step = ONBOARD[ONBOARD.index("async def _timeseries_step(") :][:2600]
    passed = step[
        step.index(
            'return _step(\n        "timeseries",\n        "Sensor data",\n        declared'
        ) :
    ][:200]
    assert "declared > 0 and with_data > 0" in passed
    assert "reporting" not in passed


def test_the_window_is_named_once():
    """A window that drifts between surfaces makes two honest numbers disagree."""
    assert "_FRESHNESS_WINDOW_H = 24" in MAIN
    assert MAIN.count("_FRESHNESS_WINDOW_H") >= 6
