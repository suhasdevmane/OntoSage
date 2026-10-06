# -*- coding: utf-8 -*-
"""ENABLE_SIGNUP gates POST /auth/register, and is off unless the env file turns it on."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from shared.config import Settings

pytestmark = pytest.mark.unit


def test_signup_is_off_by_default():
    assert Settings.model_fields["ENABLE_SIGNUP"].default is False


def _body():
    from orchestrator.main import RegisterRequest

    return RegisterRequest(username="tester_one", password="a-long-enough-password-1")


@pytest.mark.asyncio
async def test_register_is_refused_when_signup_is_disabled():
    import orchestrator.main as m

    register = AsyncMock(return_value={"success": True})
    with patch.object(m.settings, "ENABLE_SIGNUP", False), patch.object(
        m, "auth_manager", SimpleNamespace(register_user=register)
    ):
        result = await m.register_user(_body())
    register.assert_not_called()
    assert result.success is False
    assert "ENABLE_SIGNUP" in (result.error or "")


@pytest.mark.asyncio
async def test_register_creates_an_account_when_signup_is_enabled():
    import orchestrator.main as m

    register = AsyncMock(return_value={"success": True, "username": "tester_one"})
    with patch.object(m.settings, "ENABLE_SIGNUP", True), patch.object(
        m, "auth_manager", SimpleNamespace(register_user=register)
    ):
        result = await m.register_user(_body())
    register.assert_awaited_once()
    assert result.success is True
