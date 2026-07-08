"""T12 — Generic feed adapter framework unit tests.

Covers:
  1. FeedSpec validation (required fields, pattern, env expansion)
  2. FeedSpec.auth_header() reads from env-var (never from literal)
  3. RestPollAdapter.poll() fetches JSON and maps fields
  4. RestPollAdapter handles HTTP errors gracefully (returns [])
  5. CsvDropAdapter.poll() reads rows from CSV
  6. CsvDropAdapter tracks offset (only new rows on repeated poll)
  7. CsvDropAdapter handles missing file gracefully
  8. FeedRegistry.load() returns 0 when feeds.yaml absent (no-op)
  9. FeedRegistry.load() loads and instantiates adapters from YAML
  10. FeedRegistry.run_all_once() calls poll() and routes writes via adapter registry
  11. _derive_uuid is deterministic and different per building+feed
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.feeds.base import FeedRecord, FeedSpec
from orchestrator.services.feeds.csv_drop import CsvDropAdapter, _parse_ts
from orchestrator.services.feeds.registry import FeedRegistry, _derive_uuid
from orchestrator.services.feeds.rest_poll import RestPollAdapter, _extract_by_dotpath


# ─── FeedSpec validation ──────────────────────────────────────────────────────


def test_feedspec_valid():
    s = FeedSpec(id="temp_sensor", type="rest_poll", url="http://api.example.com/data")
    assert s.id == "temp_sensor"
    assert s.interval_s == 60


def test_feedspec_invalid_type():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FeedSpec(id="bad", type="mqtt")  # mqtt not in allowed pattern yet


def test_feedspec_auth_header_reads_env(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "secret123")
    s = FeedSpec(id="x", type="rest_poll", auth_env="MY_API_TOKEN")
    assert s.auth_header() == "secret123"


def test_feedspec_auth_header_missing_env(monkeypatch):
    monkeypatch.delenv("NO_SUCH_VAR", raising=False)
    s = FeedSpec(id="x", type="rest_poll", auth_env="NO_SUCH_VAR")
    assert s.auth_header() is None


def test_feedspec_auth_header_no_auth_env():
    s = FeedSpec(id="x", type="rest_poll")
    assert s.auth_header() is None


# ─── _extract_by_dotpath ─────────────────────────────────────────────────────


def test_extract_top_level():
    assert _extract_by_dotpath({"temperature": 21.5}, "temperature") == 21.5


def test_extract_nested():
    data = {"current_weather": {"temperature": -2.3}}
    assert _extract_by_dotpath(data, "current_weather.temperature") == -2.3


def test_extract_list_index():
    data = {"sensors": [{"val": 10}, {"val": 20}]}
    assert _extract_by_dotpath(data, "sensors.1.val") == 20.0


def test_extract_missing_path():
    assert _extract_by_dotpath({"a": 1}, "b.c") is None


def test_extract_non_numeric():
    assert _extract_by_dotpath({"status": "ok"}, "status") is None


# ─── RestPollAdapter ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rest_poll_extracts_field_map():
    spec = FeedSpec(
        id="outside_temp",
        type="rest_poll",
        url="http://api.test/weather",
        field_map={"current.temp": "temperature"},
        unit="degC",
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"current": {"temp": 18.7}})
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("orchestrator.services.feeds.rest_poll._httpx.AsyncClient", return_value=mock_client):
        adapter = RestPollAdapter(spec)
        records = await adapter.poll()

    assert len(records) == 1
    assert records[0].value == 18.7
    assert records[0].metric == "temperature"
    assert records[0].unit == "degC"


@pytest.mark.asyncio
async def test_rest_poll_http_error_returns_empty():
    import httpx

    spec = FeedSpec(id="x", type="rest_poll", url="http://api.test/bad")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("orchestrator.services.feeds.rest_poll._httpx.AsyncClient", return_value=mock_client):
        adapter = RestPollAdapter(spec)
        records = await adapter.poll()

    assert records == []


@pytest.mark.asyncio
async def test_rest_poll_no_url_returns_empty():
    spec = FeedSpec(id="x", type="rest_poll")
    adapter = RestPollAdapter(spec)
    records = await adapter.poll()
    assert records == []


# ─── CsvDropAdapter ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_drop_reads_rows(tmp_path):
    csv_file = tmp_path / "sensors.csv"
    csv_file.write_text("timestamp,temperature\n2026-01-01T00:00:00Z,21.5\n2026-01-01T00:01:00Z,22.0\n")

    spec = FeedSpec(
        id="room_temp",
        type="csv_drop",
        path=str(csv_file),
        field_map={"temperature": "value"},
        unit="degC",
    )
    adapter = CsvDropAdapter(spec, input_root=str(tmp_path))
    records = await adapter.poll()

    assert len(records) == 2
    assert records[0].value == 21.5
    assert records[1].value == 22.0


@pytest.mark.asyncio
async def test_csv_drop_offset_only_new_rows(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("value\n10\n20\n")

    spec = FeedSpec(id="x", type="csv_drop", path=str(csv_file))
    adapter = CsvDropAdapter(spec, input_root=str(tmp_path))

    records1 = await adapter.poll()
    assert len(records1) == 2  # first poll: both rows

    # Append a new row
    with csv_file.open("a") as f:
        f.write("30\n")

    records2 = await adapter.poll()
    assert len(records2) == 1  # only the new row
    assert records2[0].value == 30.0


@pytest.mark.asyncio
async def test_csv_drop_missing_file_returns_empty(tmp_path):
    spec = FeedSpec(id="x", type="csv_drop", path="nonexistent.csv")
    adapter = CsvDropAdapter(spec, input_root=str(tmp_path))
    records = await adapter.poll()
    assert records == []


def test_parse_ts_iso_with_z():
    from datetime import timezone
    dt = _parse_ts("2026-01-01T10:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_ts_invalid():
    assert _parse_ts("not-a-date") is None


# ─── FeedRegistry ─────────────────────────────────────────────────────────────


def test_feed_registry_load_no_yaml(tmp_path):
    reg = FeedRegistry("bldg99", input_root=str(tmp_path))
    count = reg.load()
    assert count == 0
    assert reg.adapter_ids() == []


def test_feed_registry_load_from_yaml(tmp_path):
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: outside_temp
    type: rest_poll
    url: http://api.test/weather
    interval_s: 300
    field_map:
      current.temp: value
    brick_class: brick:Outside_Air_Temperature_Sensor
    unit: degC
    storage: bldg:database1
  - id: room_sensor
    type: csv_drop
    path: input/data/sensors.csv
    field_map:
      temperature: value
    storage: bldg:database1
"""
    )
    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    count = reg.load()
    assert count == 2
    assert "outside_temp" in reg.adapter_ids()
    assert "room_sensor" in reg.adapter_ids()


def test_feed_registry_disabled_feed_not_loaded(tmp_path):
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: disabled_feed
    type: rest_poll
    url: http://api.test/data
    enabled: false
"""
    )
    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    count = reg.load()
    assert count == 0
    assert "disabled_feed" not in reg.adapter_ids()


def test_feed_registry_invalid_type_skipped(tmp_path):
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: bad_feed
    type: mqtt
  - id: good_feed
    type: rest_poll
    url: http://api.test/data
"""
    )
    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    # bad_feed fails pydantic validation → skipped; good_feed loads
    count = reg.load()
    assert count == 1
    assert "good_feed" in reg.adapter_ids()


def test_feed_registry_uuid_derivation_deterministic():
    u1 = _derive_uuid("bldg1", "outside_temp")
    u2 = _derive_uuid("bldg1", "outside_temp")
    assert u1 == u2
    assert u1 != _derive_uuid("bldg1", "inside_temp")
    assert u1 != _derive_uuid("bldg2", "outside_temp")


@pytest.mark.asyncio
async def test_feed_registry_run_all_once_routes_via_writer(tmp_path):
    """run_all_once() must route writes through the adapter registry (injected writer)."""
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    csv_file = tmp_path / "bldg1" / "data.csv"
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    csv_file.write_text("value\n99.0\n")

    (bldg_dir / "feeds.yaml").write_text(
        f"""
feeds:
  - id: test_feed
    type: csv_drop
    path: {csv_file}
    field_map:
      value: value
    storage: bldg:database1
"""
    )

    written_records = []

    async def mock_writer(records):
        written_records.extend(records)
        return len(records)

    reg = FeedRegistry("bldg1", input_root=str(tmp_path), writer=mock_writer)
    reg.load()

    results = await reg.run_all_once()

    assert results.get("test_feed", 0) == 1
    assert len(written_records) == 1
    assert written_records[0].value == 99.0
    assert written_records[0].feed_id == "test_feed"


@pytest.mark.asyncio
async def test_feed_registry_empty_feeds_yaml_is_noop(tmp_path):
    """A feeds.yaml with no feeds list boots silently."""
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text("{}\n")

    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    count = reg.load()
    assert count == 0
    results = await reg.run_all_once()
    assert results == {}


# ─── T13: Feed point auto-registration in GraphDB ─────────────────────────────


@pytest.mark.asyncio
async def test_register_in_graphdb_puts_turtle(tmp_path):
    """register_in_graphdb() PUT to GraphDB with generated Turtle content."""
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: outside_temp
    type: rest_poll
    url: http://api.test/weather
    brick_class: brick:Outside_Air_Temperature_Sensor
    location: bldg:building_exterior
    storage: bldg:database1
    unit: degC
"""
    )

    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    reg.load()

    put_calls = []

    class FakeResp:
        status_code = 204
        text = ""

    class FakePutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def put(self, url, *, content, headers):
            put_calls.append({"url": url, "body": content.decode(), "headers": headers})
            return FakeResp()

    with patch("orchestrator.services.feeds.registry._httpx_for_reg") as mock_cls:
        mock_cls.AsyncClient.return_value = FakePutClient()
        result = await reg.register_in_graphdb(
            graphdb_url="http://graphdb:7200",
            repository="bldg",
            building_namespace="http://abacwsbuilding.cardiff.ac.uk/abacws#",
        )

    from urllib.parse import unquote

    assert result is True
    assert len(put_calls) == 1
    url = unquote(put_calls[0]["url"])
    assert "feeds/bldg1" in url
    body = put_calls[0]["body"]
    assert "outside_temp" in body
    assert "brick:Outside_Air_Temperature_Sensor" in body
    assert "hasTimeseriesId" in body
    assert "database1" in body


@pytest.mark.asyncio
async def test_register_in_graphdb_no_feeds_skips(tmp_path):
    """No feeds loaded → register returns True without making HTTP calls."""
    reg = FeedRegistry("bldg_empty", input_root=str(tmp_path))
    # load() not called — no adapters

    with patch("orchestrator.services.feeds.registry._httpx_for_reg") as mock_cls:
        result = await reg.register_in_graphdb(
            graphdb_url="http://graphdb:7200",
            repository="bldg",
            building_namespace="http://test.example/#",
        )

    mock_cls.assert_not_called()
    assert result is True


@pytest.mark.asyncio
async def test_register_in_graphdb_http_error_returns_false(tmp_path):
    """GraphDB returning non-2xx → returns False, does not raise."""
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: temp
    type: rest_poll
    url: http://api.test/t
    brick_class: brick:Temperature_Sensor
"""
    )

    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    reg.load()

    class FakeBadResp:
        status_code = 500
        text = "Internal Server Error"

    class FakeBadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def put(self, url, *, content, headers):
            return FakeBadResp()

    with patch("orchestrator.services.feeds.registry._httpx_for_reg") as mock_cls:
        mock_cls.AsyncClient.return_value = FakeBadClient()
        result = await reg.register_in_graphdb(
            graphdb_url="http://graphdb:7200",
            repository="bldg",
            building_namespace="http://test.example/#",
        )

    assert result is False


def test_build_registration_ttl_structure(tmp_path):
    """_build_registration_ttl() generates valid Turtle with required predicates."""
    bldg_dir = tmp_path / "bldg1"
    bldg_dir.mkdir()
    (bldg_dir / "feeds.yaml").write_text(
        """
feeds:
  - id: co2_lobby
    type: rest_poll
    url: http://api.test/co2
    brick_class: brick:CO2_Level_Sensor
    location: bldg:lobby
    storage: bldg:database1
    unit: ppm
"""
    )
    reg = FeedRegistry("bldg1", input_root=str(tmp_path))
    reg.load()

    ttl = reg._build_registration_ttl(
        "http://abacwsbuilding.cardiff.ac.uk/abacws#",
        "http://abacwsbuilding.cardiff.ac.uk/abacws/feeds/bldg1",
    )

    assert "bldg:feed_co2_lobby" in ttl
    assert "brick:CO2_Level_Sensor" in ttl
    assert "brick:hasLocation" in ttl
    assert "bldg:lobby" in ttl
    assert "hasTimeseriesId" in ttl
    assert "ref:storedAt" in ttl
    assert "feed-auto-registered" in ttl
