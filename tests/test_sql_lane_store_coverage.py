# -*- coding: utf-8 -*-
"""The SQL lane must not read a store that provably predates the question (BUG-378).

Room 5.04 on bldg1 is served by two temperature points: the real sensor in the wide store,
holding 1,045 readings on the date asked about, and a synthetic `_sat_` overlay point on a
narrow table frozen five days earlier. The lane read the frozen one and answered "No data
found" while the live sensor sat there with the answer. 665 of the 728 points on the eight
frozen stores are that same overlay shadowing a live sensor, so this is broad.

Three safety properties are pinned here, and they matter more than the happy path:

* **unknown is never stale** — a store that cannot be probed is still read;
* **all-or-nothing** — if every point would be dropped, none is, because a stale reading is
  still evidence about the recent past and the freshness gate exists to label it as such;
* **the omission is named** — dropping a point the question asked about and then answering
  from the rest changes the question without saying so.
"""

from datetime import datetime

import pytest

from orchestrator.agents.sql_agent import SQLAgent, _parse_window_start
from orchestrator.services import store_coverage

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 31, 17, 0)
FROZEN = datetime(2026, 8, 26, 13, 36)

LIVE_UUID = "aa1c2b1f-c59d-44bf-af24-08ced2ff7ffb"
SAT_UUID = "0000sat0-0000-0000-0000-000000000000"
STORAGE = {LIVE_UUID: "bldg:database1", SAT_UUID: "bldg:temperature_data"}


class _Adapter:
    def __init__(self, latest):
        self._latest = latest

    async def latest_timestamp(self, store_key: str = ""):
        return self._latest


@pytest.fixture(autouse=True)
def _clear():
    store_coverage.reset_cache()
    yield
    store_coverage.reset_cache()


def _agent(monkeypatch, latest_by_store):
    from orchestrator.services.adapters import registry as reg

    monkeypatch.setattr(
        reg.adapter_registry,
        "get",
        lambda key=None: (_Adapter(latest_by_store[key]) if key in latest_by_store else None),
        raising=False,
    )
    return SQLAgent()


# ── window parsing ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-08-29", datetime(2026, 8, 29)),
        ("2026-08-29 10:30:00", datetime(2026, 8, 29, 10, 30)),
        ("2026-08-29T10:30:00", datetime(2026, 8, 29, 10, 30)),
    ],
)
def test_a_window_start_is_parsed(raw, expected):
    assert _parse_window_start(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "last tuesday", "not-a-date"])
def test_an_unparseable_window_is_none_so_nothing_is_dropped(raw):
    assert _parse_window_start(raw) is None


# ── selection ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_frozen_point_is_dropped_and_the_live_one_kept(monkeypatch):
    agent = _agent(monkeypatch, {"database1": NOW, "temperature_data": FROZEN})
    kept, reasons = await agent._drop_uncoverable_uuids(
        [SAT_UUID, LIVE_UUID], STORAGE, "2026-08-29"
    )
    assert kept == [LIVE_UUID]
    assert SAT_UUID in reasons


@pytest.mark.asyncio
async def test_nothing_is_dropped_when_every_point_would_be(monkeypatch):
    """A stale reading is still evidence; dropping it all yields 'nothing' instead of 'old'."""
    agent = _agent(monkeypatch, {"temperature_data": FROZEN, "co2_data": FROZEN})
    uuids = [SAT_UUID, "second-frozen"]
    storage = {SAT_UUID: "bldg:temperature_data", "second-frozen": "bldg:co2_data"}
    kept, reasons = await agent._drop_uncoverable_uuids(uuids, storage, "2026-08-29")
    assert kept == uuids
    assert reasons == {}


@pytest.mark.asyncio
async def test_an_unprobeable_store_is_kept(monkeypatch):
    """Unknown is not stale: a probe failure must never silence a sensor."""
    agent = _agent(monkeypatch, {"database1": NOW})  # temperature_data has no adapter
    kept, reasons = await agent._drop_uncoverable_uuids(
        [SAT_UUID, LIVE_UUID], STORAGE, "2026-08-29"
    )
    assert set(kept) == {SAT_UUID, LIVE_UUID}
    assert reasons == {}


@pytest.mark.asyncio
async def test_a_current_store_is_never_dropped(monkeypatch):
    agent = _agent(monkeypatch, {"database1": NOW, "temperature_data": NOW})
    kept, reasons = await agent._drop_uncoverable_uuids(
        [SAT_UUID, LIVE_UUID], STORAGE, "2026-08-29"
    )
    assert set(kept) == {SAT_UUID, LIVE_UUID}
    assert reasons == {}


# ── disclosure ─────────────────────────────────────────────────────────────────────────


def test_a_dropped_point_is_named_with_its_store_and_label():
    text = store_coverage.describe_skipped(
        {SAT_UUID: "temperature_data holds nothing after 2026-08-26 13:36"},
        {SAT_UUID: {"label": "Room5.04_sat_temperature"}},
    )
    assert "Room5.04_sat_temperature" in text and "temperature_data" in text


def test_the_lane_discloses_omissions_in_its_response():
    """Pinned against the source: the note must reach formatted_response, not just a log."""
    import inspect

    from orchestrator.agents import sql_agent

    src = inspect.getsource(sql_agent)
    assert "describe_skipped" in src, "omissions computed but never disclosed to the user"
    assert '"points_omitted"' in src, "omissions not carried for the evidence record"
