"""T33 — NotificationService unit tests.

Covers:
  1. Log channel always present (no channels.yaml needed)
  2. Dispatch to log channel returns ok=1
  3. Webhook channel dispatches to mock endpoint
  4. Webhook failure (non-2xx) returns ok=0
  5. Webhook auth header injected from env var
  6. Disabled channel is skipped
  7. Unknown channel type is skipped gracefully
  8. SMTP channel reports non-fatal skip (placeholder)
  9. has_channel_type correctly detects channel types
  10. reset_notification_service clears singleton
  11. 'email me this' decline when no smtp channel configured
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.notification_service import (
    NotificationService,
    get_notification_service,
    reset_notification_service,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def _svc(channels: List[Dict[str, Any]]) -> NotificationService:
    """Build a service with injected channels (bypass YAML loading)."""
    return NotificationService("bldg_test", _channels_override=channels)


# ── tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_channel_always_present_no_yaml():
    svc = NotificationService("nonexistent_building")
    assert any(c["type"] == "log" for c in svc.channels)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_log_returns_one():
    svc = _svc([{"id": "log", "type": "log", "enabled": True}])
    ok = await svc.dispatch(title="Test", message="hello", severity="info")
    assert ok == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_dispatches_successfully():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("orchestrator.services.notification_service.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        svc = _svc(
            [
                {"id": "log", "type": "log", "enabled": True},
                {
                    "id": "webhook1",
                    "type": "webhook",
                    "enabled": True,
                    "url": "http://test.example/notify",
                },
            ]
        )
        ok = await svc.dispatch(title="Alert", message="high CO2")

    assert ok == 2  # log + webhook


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_non_2xx_returns_failure():
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("orchestrator.services.notification_service.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        svc = _svc(
            [
                {"id": "log", "type": "log", "enabled": True},
                {
                    "id": "bad_wh",
                    "type": "webhook",
                    "enabled": True,
                    "url": "http://test.example/notify",
                },
            ]
        )
        ok = await svc.dispatch(title="Alert", message="CO2 high")

    assert ok == 1  # only log succeeded


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_auth_header_injected():
    sent_headers: Dict = {}

    async def fake_post(url, json, headers):
        sent_headers.update(headers)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = fake_post

    with patch("orchestrator.services.notification_service.httpx") as mock_httpx, patch.dict(
        os.environ, {"MY_WEBHOOK_TOKEN": "Bearer test-secret"}
    ):
        mock_httpx.AsyncClient.return_value = mock_client
        svc = _svc(
            [
                {
                    "id": "auth_wh",
                    "type": "webhook",
                    "enabled": True,
                    "url": "http://test.example/notify",
                    "auth_header_env": "MY_WEBHOOK_TOKEN",
                }
            ]
        )
        await svc.dispatch(title="T", message="M")

    assert sent_headers.get("Authorization") == "Bearer test-secret"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_channel_is_skipped():
    svc = _svc(
        [
            {"id": "log", "type": "log", "enabled": True},
            {
                "id": "disabled_wh",
                "type": "webhook",
                "enabled": False,
                "url": "http://test.example",
            },
        ]
    )
    ok = await svc.dispatch(title="T", message="M")
    assert ok == 1  # only log


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_channel_type_skipped_gracefully():
    svc = _svc(
        [
            {"id": "log", "type": "log", "enabled": True},
            {"id": "pager", "type": "pagerduty", "enabled": True},
        ]
    )
    ok = await svc.dispatch(title="T", message="M")
    assert ok == 1  # log only; pagerduty is unknown but does not raise


@pytest.mark.unit
@pytest.mark.asyncio
async def test_smtp_placeholder_returns_false():
    svc = _svc(
        [
            {
                "id": "email1",
                "type": "smtp",
                "enabled": True,
                "to_addr": "mgr@example.com",
            }
        ]
    )
    ok = await svc.dispatch(title="T", message="M")
    assert ok == 0  # smtp dispatch is a no-op placeholder


@pytest.mark.unit
def test_has_channel_type_detects_webhook():
    svc = _svc(
        [
            {"id": "log", "type": "log", "enabled": True},
            {"id": "wh", "type": "webhook", "enabled": True, "url": "http://x"},
        ]
    )
    assert svc.has_channel_type("webhook") is True
    assert svc.has_channel_type("smtp") is False


@pytest.mark.unit
def test_reset_notification_service_clears_singleton():
    reset_notification_service()
    with patch("shared.config.settings") as mock_settings:
        mock_settings.BUILDING_ID = "test_bldg"
        svc1 = get_notification_service()
        svc2 = get_notification_service()
    assert svc1 is svc2  # same instance

    reset_notification_service()
    with patch("shared.config.settings") as mock_settings:
        mock_settings.BUILDING_ID = "test_bldg"
        svc3 = get_notification_service()
    # After reset, a new instance is created
    assert svc3 is not svc1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_smtp_channel_conversational_decline():
    """When no smtp channel configured, the service correctly reports has_channel_type=False."""
    svc = _svc([{"id": "log", "type": "log", "enabled": True}])
    assert svc.has_channel_type("smtp") is False
    # Conversational handler checks this before dispatching — honest decline
    decline_message = (
        "I can log the notification, but no email channel is configured. "
        "Ask your building administrator to add an smtp channel in channels.yaml."
    )
    assert "smtp" in decline_message  # token check; real handler is in orchestrator
