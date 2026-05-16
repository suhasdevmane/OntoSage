"""Tests for AlertMonitor — proactive sensor threshold alert service."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.services.alert_monitor import AlertMonitor, _eval_threshold


class TestThresholdEvaluation:
    def test_greater_than_breached(self):
        assert _eval_threshold(1100, ">", 1000) is True

    def test_greater_than_not_breached(self):
        assert _eval_threshold(900, ">", 1000) is False

    def test_less_than_breached(self):
        assert _eval_threshold(14, "<", 15) is True

    def test_less_than_not_breached(self):
        assert _eval_threshold(16, "<", 15) is False

    def test_gte_breached_equal(self):
        assert _eval_threshold(1000, ">=", 1000) is True

    def test_gte_not_breached(self):
        assert _eval_threshold(999, ">=", 1000) is False


class TestAlertDeduplication:
    @pytest.mark.asyncio
    async def test_dedup_suppresses_second_fire(self):
        """Second call within TTL window must NOT broadcast."""
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[None, b"1"])  # first: miss, second: hit
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {
            "sensor_type": "CO2_Sensor",
            "threshold": 1000,
            "comparator": ">",
            "severity": "warning",
            "message": "CO₂ in {zone} is {value} ppm.",
        }
        await monitor._maybe_fire("sensor-1", 1100, "Lab 3.07", rule)
        await monitor._maybe_fire("sensor-1", 1100, "Lab 3.07", rule)
        assert conn_mgr.broadcast_alert.call_count == 1

    @pytest.mark.asyncio
    async def test_dedup_key_format(self):
        """Dedup key must be 'alert:{sensor_id}:{threshold}'."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {"sensor_type": "CO2_Sensor", "threshold": 1000, "comparator": ">",
                "severity": "warning", "message": "CO₂ in {zone} is {value} ppm."}
        await monitor._maybe_fire("sensor-42", 1200, "Zone A", rule)
        redis.get.assert_called_once_with("alert:sensor-42:1000")
        redis.setex.assert_called_once_with("alert:sensor-42:1000", 600, "1")

    @pytest.mark.asyncio
    async def test_broadcast_called_with_correct_severity(self):
        """broadcast_alert must receive the severity and formatted message."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {"sensor_type": "CO2_Sensor", "threshold": 1000, "comparator": ">",
                "severity": "critical", "message": "CO₂ in {zone} is {value} ppm."}
        await monitor._maybe_fire("sensor-1", 1250, "Lab 3", rule)
        conn_mgr.broadcast_alert.assert_called_once()
        call_kwargs = conn_mgr.broadcast_alert.call_args
        assert call_kwargs.kwargs["severity"] == "critical"
        assert "Lab 3" in call_kwargs.kwargs["message"]
        assert "1250" in call_kwargs.kwargs["message"]
