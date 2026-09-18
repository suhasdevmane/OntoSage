# -*- coding: utf-8 -*-
"""The empty-window fallback reads the store the points live in, through its adapter (BUG-660).

When a question naming no period finds nothing in its default window, the SQL lane answers
from the most recent rows on record instead (and says so, BUG-658). That fallback used to be
built by hand as `SELECT ... FROM <wide table> ... LIMIT 200` and run through `_execute_query`,
which asks the registry for the DEFAULT adapter. Two defects followed:

* for a point held in a narrow table or on any non-default backend it asked the wrong store,
  in the wrong shape — a uuid read as a column name; and
* `_execute_query` RAISES on adapter failure, so a failed fallback escaped the lane and turned
  the whole turn into `{"success": False}` rather than an honest "no data".

These tests pin the contract instead of the SQL text: the fallback is built by the group's
own adapter and executed on it, it is still bounded to the most recent rows, it still records
the real span of what it returned, and when it fails the lane answers "no rows", not an error.
"""

import logging
from typing import Any, Dict, List, Optional

import pytest

import orchestrator.agents.sql_agent as sql_mod
from orchestrator.agents.sql_agent import SQLAgent

pytestmark = pytest.mark.unit

# Opaque identifiers standing in for whatever the graph returns — not building literals.
POINT = "00000000-0000-4000-8000-00000000000a"
OTHER_POINT = "00000000-0000-4000-8000-00000000000b"
QUESTION = "What is the CO2 in that space?"  # names no period, so the fallback may run

OLD_ROWS = [
    {"timestamp": "2025-01-01 00:00:00", "uuid": POINT, "value": 412.0},
    {"timestamp": "2025-03-09 23:55:00", "uuid": POINT, "value": 508.0},
]
LATER_ROWS = [{"timestamp": "2025-04-02 08:00:00", "uuid": OTHER_POINT, "value": 21.5}]


class _Result:
    def __init__(self, data: List[Dict[str, Any]], success: bool = True, error: str = ""):
        self.success = success
        self.data = list(data)
        self.error = error or None
        self.row_count = len(data)


class _AdapterType:
    def __init__(self, name: str):
        self.value = name


class _Store:
    """A store with its OWN query shape. Answers the first query with `in_window`, then
    `latest` — so the primary read finds nothing and the fallback finds the old rows."""

    def __init__(
        self,
        name: str,
        in_window: Optional[List[Dict[str, Any]]] = None,
        latest: Optional[List[Dict[str, Any]]] = None,
        fail_fallback: str = "",
        build_fallback: bool = True,
    ):
        self.name = name
        self.adapter_type = _AdapterType(name)
        self._in_window = list(in_window or [])
        self._latest = list(latest or [])
        self._fail_fallback = fail_fallback
        self._build_fallback = build_fallback
        self.builds: List[Dict[str, Any]] = []
        self.executed: List[str] = []

    def get_dialect_hints(self) -> str:
        return ""

    def build_timeseries_query(self, **kwargs) -> Optional[str]:
        self.builds.append(dict(kwargs))
        if len(self.builds) > 1 and not self._build_fallback:
            return None
        return f"{self.name.upper()}-NATIVE {sorted(kwargs['uuids'])} #{len(self.builds)}"

    async def execute_query(self, query: str) -> _Result:
        self.executed.append(query)
        if len(self.executed) == 1:
            return _Result(self._in_window)
        if self._fail_fallback == "raise":
            raise RuntimeError("connection reset by peer")
        if self._fail_fallback == "unsuccessful":
            return _Result([], success=False, error="Table 'x' doesn't exist")
        return _Result(self._latest)


class _Registry:
    """Routes by storage key. The DEFAULT adapter is a separate wide store that must never be
    touched for a group that lives elsewhere — reaching it is the defect under test."""

    is_available = True

    def __init__(self, stores: Dict[str, Optional[_Store]], default: _Store):
        self._stores = stores
        self.default = default

    async def get_valid_uuids(self, uuids, primary=None, storage_map=None):
        return list(uuids)

    @staticmethod
    def _resolve_storage_key(storage: str) -> str:
        return str(storage or "").split(":")[-1].split("#")[-1]

    def get(self, key=None):
        if not key:
            return self.default
        return self._stores.get(self._resolve_storage_key(key), None)

    def get_schema_text(self, key=None, keep_columns=None) -> str:
        return ""

    def get_timestamp_column(self, key=None) -> str:
        return "datetime"


def _agent(monkeypatch, stores: Dict[str, Optional[_Store]]) -> SQLAgent:
    default = _Store("default_wide", in_window=OLD_ROWS, latest=OLD_ROWS)
    registry = _Registry(stores, default)
    monkeypatch.setattr(sql_mod, "adapter_registry", registry, raising=True)
    agent = SQLAgent()

    async def _format(rows, query, label, metadata=None):
        return f"{len(rows)} reading(s)."

    monkeypatch.setattr(agent, "_format_results", _format, raising=True)
    agent._test_registry = registry  # type: ignore[attr-defined]
    return agent


async def _ask(agent: SQLAgent, storage_map: Dict[str, str], question: str = QUESTION):
    return await agent.fetch_data_for_uuids(list(storage_map), question, storage_map, None, None)


def _all_text(store: _Store) -> str:
    return " ".join(store.executed)


def _warned_about_fallback(caplog, store_key: str) -> bool:
    """A WARNING that names both the fallback and the store — not the primary path's own log."""
    return any(
        rec.levelno == logging.WARNING
        and store_key in rec.getMessage()
        and "fallback" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ── the store and the shape ─────────────────────────────────────────────────────────────


async def test_a_narrow_store_fallback_goes_through_the_narrow_adapter(monkeypatch):
    """The core defect: the fallback for a narrow-table point asked the DEFAULT wide store."""
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    result = await _ask(agent, {POINT: "bldg:co2_store"})

    # Built by the group's own adapter, for the group's own uuids — twice: primary, fallback.
    assert len(narrow.builds) == 2
    assert narrow.builds[1]["uuids"] == [POINT]
    assert len(narrow.executed) == 2
    # The default store was never asked, and no hand-built wide-table SQL went anywhere.
    assert agent._test_registry.default.executed == []
    assert "sensor_data" not in _all_text(narrow)
    assert "FROM" not in _all_text(narrow)
    assert result["success"] is True
    assert result["results"]["data"] == OLD_ROWS


async def test_the_fallback_asks_a_different_question_from_the_empty_one(monkeypatch):
    """Re-running the builder with the SAME bounds would re-apply the adapter's default
    lookback and find nothing again. The fallback must lift that bound."""
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    await _ask(agent, {POINT: "bldg:co2_store"})

    primary, fallback = narrow.builds
    assert (primary["start_date"], primary["end_date"]) == (None, None)
    assert (fallback["start_date"], fallback["end_date"]) != (None, None)


async def test_a_wide_store_group_still_substitutes(monkeypatch):
    """The ordinary wide-table case must keep working, now through its own builder."""
    wide = _Store("wide", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"database1": wide})

    result = await _ask(agent, {POINT: "bldg:database1"})

    assert len(wide.builds) == 2
    assert len(wide.executed) == 2
    assert agent._test_registry.default.executed == []
    assert result["results"]["data"] == OLD_ROWS
    marker = result["window_substituted"]
    assert marker is not None
    assert marker["stores"] == ["database1"]


# ── still bounded, still disclosed ──────────────────────────────────────────────────────


async def test_the_fallback_is_bounded_to_the_most_recent_rows(monkeypatch):
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    await _ask(agent, {POINT: "bldg:co2_store"})

    limit = narrow.builds[1]["limit"]
    assert 1 <= limit <= 200, "the fallback reads a recent sample, never a whole history"


async def test_the_marker_carries_the_real_span_of_the_rows_returned(monkeypatch):
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    result = await _ask(agent, {POINT: "bldg:co2_store"})

    marker = result["window_substituted"]
    assert marker is not None and marker["substituted"] is True
    assert marker["actual_earliest"] == "2025-01-01 00:00:00"
    assert marker["actual_latest"] == "2025-03-09 23:55:00"
    assert marker["rows"] == len(OLD_ROWS)
    assert marker["stores"] == ["co2_store"]
    assert "2025-03-09 23:55:00" in result["formatted_response"]


async def test_two_stores_each_read_through_their_own_adapter_widen_one_span(monkeypatch):
    first = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    second = _Store("plant_narrow", in_window=[], latest=LATER_ROWS)
    agent = _agent(monkeypatch, {"storeA": first, "storeB": second})

    result = await _ask(agent, {POINT: "bldg:storeA", OTHER_POINT: "bldg:storeB"})

    assert first.builds[1]["uuids"] == [POINT]
    assert second.builds[1]["uuids"] == [OTHER_POINT]
    assert agent._test_registry.default.executed == []
    marker = result["window_substituted"]
    assert marker["actual_earliest"] == "2025-01-01 00:00:00"
    assert marker["actual_latest"] == "2025-04-02 08:00:00"
    assert marker["rows"] == len(OLD_ROWS) + len(LATER_ROWS)
    assert sorted(marker["stores"]) == ["storeA", "storeB"]


async def test_a_full_fallback_sample_is_marked_as_capped(monkeypatch):
    """A fallback that came back exactly full is a sample, and its size is not a count."""
    narrow = _Store("co2_narrow", in_window=[], latest=[])
    agent = _agent(monkeypatch, {"co2_store": narrow})
    captured: Dict[str, int] = {}
    original = narrow.build_timeseries_query

    def _build(**kwargs):
        if len(narrow.builds) == 1:
            captured["limit"] = kwargs["limit"]
            narrow._latest = [
                {
                    "timestamp": f"2025-03-09 {i // 60:02d}:{i % 60:02d}:00",
                    "uuid": POINT,
                    "value": 1,
                }
                for i in range(kwargs["limit"])
            ]
        return original(**kwargs)

    monkeypatch.setattr(narrow, "build_timeseries_query", _build, raising=False)

    result = await _ask(agent, {POINT: "bldg:co2_store"})

    assert len(result["results"]["data"]) == captured["limit"]
    assert result["rows_capped"] is True


# ── a failed fallback is "no rows", never a failed turn ─────────────────────────────────


@pytest.mark.parametrize("failure", ["raise", "unsuccessful"])
async def test_a_failing_fallback_degrades_to_no_rows(monkeypatch, caplog, failure):
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS, fail_fallback=failure)
    agent = _agent(monkeypatch, {"co2_store": narrow})
    # Make the OLD path fail the same way, so this test cannot pass on the default adapter.
    agent._test_registry.default._fail_fallback = "raise"
    agent._test_registry.default._in_window = []
    agent._test_registry.default.executed.append("primed")

    with caplog.at_level(logging.WARNING, logger=sql_mod.logger.name):
        result = await _ask(agent, {POINT: "bldg:co2_store"})

    assert result["success"] is True
    assert result["results"]["data"] == []
    assert result["window_substituted"] is None
    assert _warned_about_fallback(caplog, "co2_store"), "the warning must name the store"


async def test_a_store_with_no_adapter_degrades_to_no_rows(monkeypatch, caplog):
    """An unknown store must not be answered from whichever adapter happens to be default."""
    agent = _agent(monkeypatch, {"ghost_store": None})
    agent._test_registry.default._fail_fallback = "raise"
    agent._test_registry.default.executed.append("primed")

    with caplog.at_level(logging.WARNING, logger=sql_mod.logger.name):
        result = await _ask(agent, {POINT: "bldg:ghost_store"})

    assert result["success"] is True
    assert result["results"]["data"] == []
    assert result["window_substituted"] is None
    assert agent._test_registry.default.executed == ["primed"]
    assert _warned_about_fallback(caplog, "ghost_store")


async def test_an_adapter_that_cannot_build_the_fallback_degrades_to_no_rows(monkeypatch, caplog):
    """No hand-written wide SQL as a last resort: a store that declines is 'no rows'."""
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS, build_fallback=False)
    agent = _agent(monkeypatch, {"co2_store": narrow})
    agent._test_registry.default._fail_fallback = "raise"
    agent._test_registry.default.executed.append("primed")

    with caplog.at_level(logging.WARNING, logger=sql_mod.logger.name):
        result = await _ask(agent, {POINT: "bldg:co2_store"})

    assert result["success"] is True
    assert result["results"]["data"] == []
    assert result["window_substituted"] is None
    assert len(narrow.executed) == 1, "only the primary query ran on the store"
    assert agent._test_registry.default.executed == ["primed"]
    assert _warned_about_fallback(caplog, "co2_store")


# ── the real builders: the lifted lookback actually reaches the SQL ─────────────────────


def _real_adapters():
    from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
    from orchestrator.services.adapters.mysql_narrow_adapter import MySQLNarrowAdapter

    # No connection is opened: only the query builders are exercised.
    return [MySQLAdapter(), MySQLNarrowAdapter(table="narrow_points")]


@pytest.mark.parametrize("adapter", _real_adapters(), ids=["mysql_wide", "mysql_narrow"])
async def test_real_builders_get_a_newest_first_query_with_no_default_lookback(adapter):
    """The fake adapters above prove routing; this proves the bound. A builder handed no
    bounds applies its own 30-day lookback, which is the window that just came back empty."""
    executed: List[str] = []

    async def _record(query: str):
        executed.append(query)
        return _Result(OLD_ROWS)

    adapter.execute_query = _record  # type: ignore[method-assign]

    rows = await SQLAgent()._latest_rows_from_store(adapter, "a_store", [POINT], "datetime", 200)

    assert rows == OLD_ROWS
    assert len(executed) == 1
    sql = executed[0]
    assert "INTERVAL" not in sql.upper()
    assert POINT in sql
    assert "DESC LIMIT 200" in sql.replace("`", "")


# ── negatives: the fallback does not run when it should not ─────────────────────────────


async def test_data_in_the_window_means_no_fallback_build(monkeypatch):
    narrow = _Store("co2_narrow", in_window=OLD_ROWS, latest=LATER_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    result = await _ask(agent, {POINT: "bldg:co2_store"})

    assert len(narrow.builds) == 1
    assert result["window_substituted"] is None
    assert result["results"]["data"] == OLD_ROWS


async def test_a_present_tense_question_does_not_reach_the_fallback(monkeypatch):
    narrow = _Store("co2_narrow", in_window=[], latest=OLD_ROWS)
    agent = _agent(monkeypatch, {"co2_store": narrow})

    result = await _ask(agent, {POINT: "bldg:co2_store"}, "What is the CO2 there right now?")

    assert len(narrow.builds) == 1
    assert result["results"]["data"] == []
    assert result["window_substituted"] is None
