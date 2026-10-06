# -*- coding: utf-8 -*-
"""A floor-wide count reads each sensor from the store its ref:storedAt names (BUG-1442).

The live question "How complete is the CO2 data for floor 3 this month" bound 50 sensors. 48
of them are stored in `sensor_data_floors04` (ref:storedAt database1_floors04); the answer
cited `Co2 Data` as a source as well, because the provenance step recorded EVERY store in the
bound map once any row came back, not the stores that actually returned rows.

The routing itself was already correct when measured (48 uuids grouped under floors04, the
co2_data group held one sensor's rows and no others). These tests pin that contract with
in-memory adapters that hold rows only for the uuids they own, so a regression that sent a
floors04 uuid to co2_data would show up as a count of zero rather than as a plausible number.
"""

from typing import Any, Dict, List, Optional

import pytest

import orchestrator.agents.sql_agent as sql_mod
from orchestrator.agents.sql_agent import SQLAgent
from orchestrator.services import provenance as prov

pytestmark = pytest.mark.unit

# Opaque identifiers standing in for graph-returned ids. Not building literals.
F1 = "00000000-0000-4000-8000-0000000000a1"
F2 = "00000000-0000-4000-8000-0000000000a2"
F3 = "00000000-0000-4000-8000-0000000000a3"
LONE = "00000000-0000-4000-8000-0000000000b1"  # bound to a store that holds none of its rows
QUESTION = "How complete is the CO2 data for the floor?"  # names no period

FLOOR_STORE = "database1_floors04"
EMPTY_STORE = "co2_data"


def _rows(uuid: str, n: int) -> List[Dict[str, Any]]:
    return [
        {"timestamp": f"2026-10-01 {i // 60:02d}:{i % 60:02d}:00", "uuid": uuid, "value": 500.0}
        for i in range(n)
    ]


class _Result:
    def __init__(self, data: List[Dict[str, Any]]):
        self.success = True
        self.data = list(data)
        self.error = None
        self.row_count = len(data)


class _AdapterType:
    def __init__(self, name: str):
        self.value = name


class _Store:
    """An in-memory store. It answers ONLY for the uuids it holds; anything else is no rows."""

    def __init__(self, name: str, holds: Dict[str, List[Dict[str, Any]]]):
        self.name = name
        self.adapter_type = _AdapterType(name)
        self._holds = holds
        self._asked: List[str] = []
        self.queries: List[List[str]] = []

    def get_dialect_hints(self) -> str:
        return ""

    def build_timeseries_query(self, **kwargs) -> Optional[str]:
        self._asked = list(kwargs["uuids"])
        self.queries.append(list(kwargs["uuids"]))
        return f"{self.name}-query {len(self._asked)}"

    async def execute_query(self, query: str) -> _Result:
        out: List[Dict[str, Any]] = []
        for u in self._asked:
            out.extend(self._holds.get(u, []))
        return _Result(out)


class _Registry:
    is_available = True

    def __init__(self, stores: Dict[str, _Store], default: _Store):
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
        return self._stores.get(self._resolve_storage_key(key))

    def get_schema_text(self, key=None, keep_columns=None) -> str:
        return ""

    def get_timestamp_column(self, key=None) -> str:
        return "datetime"


@pytest.fixture
def stores(monkeypatch):
    """Two real stores and a default that must never be touched for these sensors."""
    floors = _Store(
        FLOOR_STORE,
        {F1: _rows(F1, 3), F2: _rows(F2, 2), F3: _rows(F3, 4)},
    )
    empty = _Store(EMPTY_STORE, {})  # holds none of the bound LONE sensor's rows
    default = _Store("default_wide", {F1: _rows(F1, 99)})  # would inflate a count if reached
    registry = _Registry({FLOOR_STORE: floors, EMPTY_STORE: empty}, default)
    monkeypatch.setattr(sql_mod, "adapter_registry", registry, raising=True)

    agent = SQLAgent()

    async def _no_aggregate(*args, **kwargs):
        return None  # the aggregate lane is a separate path; this pins the per-sensor read

    async def _format(rows, query, label, metadata=None):
        return f"{len(rows)} reading(s)."

    monkeypatch.setattr(agent, "_try_aggregate_lane", _no_aggregate, raising=True)
    monkeypatch.setattr(agent, "_format_results", _format, raising=True)
    return {"agent": agent, "floors": floors, "empty": empty, "default": default}


async def _count(agent: SQLAgent, storage_map: Dict[str, str]):
    return await agent.fetch_data_for_uuids(list(storage_map), QUESTION, storage_map, None, None)


async def test_each_sensor_is_counted_from_the_store_its_storedat_names(stores):
    storage_map = {F1: f"bldg:{FLOOR_STORE}", F2: f"bldg:{FLOOR_STORE}", F3: f"bldg:{FLOOR_STORE}"}

    result = await _count(stores["agent"], storage_map)

    assert len(result["results"]["data"]) == 3 + 2 + 4
    assert stores["floors"].queries and set(stores["floors"].queries[0]) == {F1, F2, F3}
    assert stores["default"].queries == [], "the default store was reached for named sensors"


async def test_a_sensor_in_a_second_store_is_read_there_and_not_in_the_first(stores):
    storage_map = {
        F1: f"bldg:{FLOOR_STORE}",
        F2: f"bldg:{FLOOR_STORE}",
        LONE: f"bldg:{EMPTY_STORE}",
    }

    result = await _count(stores["agent"], storage_map)

    # The floors store was asked only for its own uuids, and the empty store only for its own.
    assert set(stores["floors"].queries[0]) == {F1, F2}
    assert stores["empty"].queries[0] == [LONE]
    # Five rows from the floors store; the empty store contributed nothing.
    assert len(result["results"]["data"]) == 3 + 2


def test_a_store_with_no_rows_for_the_bound_uuids_is_not_cited(stores):
    """The citation half of BUG-1442: co2_data held no rows for the bound sensor, so it must
    not appear among the stores the answer names."""
    state = type("S", (), {})()
    state.intermediate_results = {}
    storage_map = {
        F1: f"bldg:{FLOOR_STORE}",
        F2: f"bldg:{FLOOR_STORE}",
        LONE: f"bldg:{EMPTY_STORE}",
    }
    rows = [r for u in (F1, F2) for r in _rows(u, 1)]

    prov.record_sql_stores(state, storage_map, prov.uuids_holding_rows(rows))

    cited = state.intermediate_results["_prov_stores"]
    assert cited == [f"store:{FLOOR_STORE}"]
    assert f"store:{EMPTY_STORE}" not in cited


def test_without_a_uuid_column_every_bound_store_is_still_cited(stores):
    """Aggregate-shaped results carry no uuid column. The map is then all the lane knows, and
    the old behaviour (cite every bound store) is kept rather than guessing a subset."""
    state = type("S", (), {})()
    state.intermediate_results = {}
    storage_map = {F1: f"bldg:{FLOOR_STORE}", LONE: f"bldg:{EMPTY_STORE}"}

    prov.record_sql_stores(state, storage_map, prov.uuids_holding_rows([{"n": 4}]))

    assert set(state.intermediate_results["_prov_stores"]) == {
        f"store:{FLOOR_STORE}",
        f"store:{EMPTY_STORE}",
    }


def test_uuids_holding_rows_is_none_for_rows_without_uuid():
    assert prov.uuids_holding_rows([{"value": 1}]) is None
    assert prov.uuids_holding_rows([{"uuid": F1, "value": 1}]) == {F1}
    assert prov.uuids_holding_rows([]) == set()
