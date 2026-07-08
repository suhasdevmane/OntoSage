"""
T23 — Tests for the actuation gateway: SimDriver + ActuationRegistry.

All DB calls are mocked so these are pure unit tests (no Postgres needed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from orchestrator.services.actuation.base import ActuationDriver, ActuationResult
from orchestrator.services.actuation.registry import ActuationRegistry, _NullDriver
from orchestrator.services.actuation.sim_driver import SimDriver


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_postgres_manager(audit_id: str = "fake-audit-id"):
    """Return a mock postgres_manager whose pool returns an audit_id row."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"audit_id": audit_id})
    conn.execute = AsyncMock(return_value=None)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    pm = MagicMock()
    pm.pool = pool
    return pm


# ── SimDriver — basic contract ────────────────────────────────────────────────


class TestSimDriverCapabilities:
    def test_empty_writable_list(self):
        driver = SimDriver("bldg1", [])
        assert driver._writable == set()

    @pytest.mark.asyncio
    async def test_capabilities_returns_sorted_list(self):
        driver = SimDriver("bldg1", ["urn:bldg1:B", "urn:bldg1:A"])
        caps = await driver.capabilities()
        assert caps == ["urn:bldg1:A", "urn:bldg1:B"]

    @pytest.mark.asyncio
    async def test_set_point_unknown_point_returns_failure(self):
        driver = SimDriver("bldg1", ["urn:bldg1:VAV-501-SP"])
        result = await driver.set_point("urn:bldg1:UNKNOWN-SP", 22.5)
        assert result.success is False
        assert "not in the writable points list" in result.error

    @pytest.mark.asyncio
    async def test_set_point_known_point_returns_success(self):
        pm = _make_postgres_manager("audit-xyz")
        driver = SimDriver("bldg1", ["urn:bldg1:VAV-501-SP"], postgres_manager=pm)
        driver._table_ensured = True  # skip table creation in unit test

        result = await driver.set_point("urn:bldg1:VAV-501-SP", 22.5, user_id="alice")

        assert result.success is True
        assert result.point_uri == "urn:bldg1:VAV-501-SP"
        assert result.value == 22.5
        assert result.audit_id == "audit-xyz"
        assert "[SIM]" in result.message

    @pytest.mark.asyncio
    async def test_set_point_db_failure_still_succeeds(self):
        """Sim driver is resilient — a DB error should NOT block the result."""
        pm = MagicMock()
        pm.pool = MagicMock()
        pm.pool.acquire = MagicMock(side_effect=ConnectionError("DB down"))
        driver = SimDriver("bldg1", ["urn:bldg1:VAV-501-SP"], postgres_manager=pm)
        driver._table_ensured = True

        result = await driver.set_point("urn:bldg1:VAV-501-SP", 21.0)
        assert result.success is True  # sim is resilient

    @pytest.mark.asyncio
    async def test_set_point_no_postgres_still_succeeds(self):
        """Without postgres_manager, driver skips DB and still returns success."""
        driver = SimDriver("bldg1", ["urn:bldg1:VAV-501-SP"], postgres_manager=None)
        result = await driver.set_point("urn:bldg1:VAV-501-SP", 21.0)
        assert result.success is True
        assert result.audit_id is not None  # UUID generated locally

    @pytest.mark.asyncio
    async def test_audit_id_present_on_success(self):
        pm = _make_postgres_manager("audit-abc123")
        driver = SimDriver("bldg1", ["urn:bldg1:LIGHTING-3F-SP"], postgres_manager=pm)
        driver._table_ensured = True

        result = await driver.set_point("urn:bldg1:LIGHTING-3F-SP", 3)
        assert result.audit_id is not None

    @pytest.mark.asyncio
    async def test_set_point_with_reason(self):
        pm = _make_postgres_manager("audit-reason")
        driver = SimDriver("bldg1", ["urn:bldg1:AHU-F5-SP"], postgres_manager=pm)
        driver._table_ensured = True

        result = await driver.set_point(
            "urn:bldg1:AHU-F5-SP", 18.0, reason="energy saving policy"
        )
        assert result.success is True


# ── NullDriver ────────────────────────────────────────────────────────────────


class TestNullDriver:
    @pytest.mark.asyncio
    async def test_capabilities_empty(self):
        driver = _NullDriver()
        assert await driver.capabilities() == []

    @pytest.mark.asyncio
    async def test_set_point_always_fails(self):
        driver = _NullDriver()
        result = await driver.set_point("urn:bldg1:ANY", 1)
        assert result.success is False
        assert "driver=none" in result.error


# ── ActuationRegistry ─────────────────────────────────────────────────────────


class TestActuationRegistry:
    def _write_building_yaml(self, tmp_path: Path, building_id: str, cfg: dict) -> Path:
        d = tmp_path / building_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / "building.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        return tmp_path

    def test_driver_sim_from_yaml(self, tmp_path):
        input_root = self._write_building_yaml(
            tmp_path,
            "bldg1",
            {
                "building_id": "bldg1",
                "actuation": {
                    "driver": "sim",
                    "points_writable": ["urn:bldg1:VAV-501-SP"],
                },
            },
        )
        reg = ActuationRegistry()
        reg._YAML_SEARCH_PATHS = [str(input_root / "{building_id}" / "building.yaml")]

        # Monkeypatch _find_yaml
        yaml_path = input_root / "bldg1" / "building.yaml"
        reg._find_yaml = lambda bid: yaml_path if bid == "bldg1" else None

        driver = reg.driver_for("bldg1")
        assert isinstance(driver, SimDriver)
        assert "urn:bldg1:VAV-501-SP" in driver._writable

    def test_driver_none_from_yaml(self, tmp_path):
        input_root = self._write_building_yaml(
            tmp_path,
            "bldg2",
            {
                "building_id": "bldg2",
                "actuation": {"driver": "none"},
            },
        )
        reg = ActuationRegistry()
        yaml_path = input_root / "bldg2" / "building.yaml"
        reg._find_yaml = lambda bid: yaml_path if bid == "bldg2" else None

        driver = reg.driver_for("bldg2")
        assert isinstance(driver, _NullDriver)

    def test_no_actuation_block_returns_null(self, tmp_path):
        input_root = self._write_building_yaml(
            tmp_path, "bldg3", {"building_id": "bldg3"}
        )
        reg = ActuationRegistry()
        yaml_path = input_root / "bldg3" / "building.yaml"
        reg._find_yaml = lambda bid: yaml_path if bid == "bldg3" else None

        driver = reg.driver_for("bldg3")
        assert isinstance(driver, _NullDriver)

    def test_driver_cached_on_second_call(self, tmp_path):
        input_root = self._write_building_yaml(
            tmp_path,
            "bldg4",
            {
                "building_id": "bldg4",
                "actuation": {"driver": "sim", "points_writable": []},
            },
        )
        reg = ActuationRegistry()
        yaml_path = input_root / "bldg4" / "building.yaml"
        reg._find_yaml = lambda bid: yaml_path if bid == "bldg4" else None

        d1 = reg.driver_for("bldg4")
        d2 = reg.driver_for("bldg4")
        assert d1 is d2  # same instance from cache

    def test_invalidate_clears_cache(self, tmp_path):
        input_root = self._write_building_yaml(
            tmp_path,
            "bldg5",
            {
                "building_id": "bldg5",
                "actuation": {"driver": "sim", "points_writable": []},
            },
        )
        reg = ActuationRegistry()
        yaml_path = input_root / "bldg5" / "building.yaml"
        reg._find_yaml = lambda bid: yaml_path if bid == "bldg5" else None

        d1 = reg.driver_for("bldg5")
        reg.invalidate("bldg5")
        d2 = reg.driver_for("bldg5")
        assert d1 is not d2  # different instances after invalidation

    def test_bldg1_building_yaml_has_actuation_block(self):
        """Smoke test: the real building.yaml (flat layout) declares actuation."""
        for template in ["/app/input/building.yaml", "input/building.yaml"]:
            p = Path(template)
            if p.is_file():
                import yaml as _yaml
                data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                assert "actuation" in data, "building.yaml must have actuation block"
                assert data["actuation"]["driver"] == "sim"
                assert len(data["actuation"].get("points_writable", [])) >= 1
                return
        pytest.skip("building.yaml not found in this environment")
