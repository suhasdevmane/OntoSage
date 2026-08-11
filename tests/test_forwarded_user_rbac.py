"""Per-user RBAC through a shared-key proxy (Open WebUI → OntoSage).

Open WebUI authenticates with ONE pipeline key, so without forwarding, every chat user
reaches OntoSage as the same least-privilege identity and role-aware answers are
impossible. These tests pin the security properties of the opt-in forwarding path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


def _request(headers: dict):
    return SimpleNamespace(headers=headers)


async def _resolve(headers, *, trust=True, user_row=None, header="X-OpenWebUI-User-Email"):
    import orchestrator.main as m

    pg = SimpleNamespace(get_user=AsyncMock(return_value=user_row))
    with patch.object(m.settings, "TRUST_FORWARDED_USER", trust), patch.object(
        m.settings, "FORWARDED_USER_HEADER", header
    ), patch.object(m, "postgres_manager", pg):
        return await m.resolve_forwarded_user(_request(headers))


@pytest.mark.asyncio
async def test_known_user_gets_their_own_role():
    got = await _resolve(
        {"X-OpenWebUI-User-Email": "analyst01@example.com"},
        user_row={"username": "analyst01", "role": "analyst"},
    )
    assert got == ("analyst01", "analyst")


@pytest.mark.asyncio
async def test_disabled_flag_ignores_the_header_entirely():
    """The header must do NOTHING unless trust is explicitly enabled — otherwise anyone
    holding the shared key could impersonate any user by setting one header."""
    got = await _resolve(
        {"X-OpenWebUI-User-Email": "admin01@example.com"},
        trust=False,
        user_row={"username": "admin01", "role": "admin"},
    )
    assert got == ("openwebui_user", "readonly")


@pytest.mark.asyncio
async def test_unknown_user_falls_back_to_least_privilege():
    got = await _resolve({"X-OpenWebUI-User-Email": "stranger@example.com"}, user_row=None)
    assert got[1] == "readonly"


@pytest.mark.asyncio
async def test_missing_header_falls_back_to_least_privilege():
    assert await _resolve({}) == ("openwebui_user", "readonly")


@pytest.mark.asyncio
async def test_lookup_failure_never_breaks_the_turn():
    import orchestrator.main as m

    pg = SimpleNamespace(get_user=AsyncMock(side_effect=RuntimeError("db down")))
    with patch.object(m.settings, "TRUST_FORWARDED_USER", True), patch.object(
        m, "postgres_manager", pg
    ):
        got = await m.resolve_forwarded_user(_request({"X-OpenWebUI-User-Email": "a@b.com"}))
    assert got == ("openwebui_user", "readonly")


@pytest.mark.asyncio
async def test_email_local_part_matches_an_ontosage_username():
    """Open WebUI forwards an email; OntoSage accounts are keyed by username."""
    import orchestrator.main as m

    calls = []

    async def _get_user(name):
        calls.append(name)
        return (
            {"username": "facility01", "role": "facility_manager"} if name == "facility01" else None
        )

    pg = SimpleNamespace(get_user=_get_user)
    with patch.object(m.settings, "TRUST_FORWARDED_USER", True), patch.object(
        m, "postgres_manager", pg
    ):
        got = await m.resolve_forwarded_user(
            _request({"X-OpenWebUI-User-Email": "facility01@example.com"})
        )
    assert got == ("facility01", "facility_manager")
    assert calls == ["facility01@example.com", "facility01"]  # full email tried first


@pytest.mark.asyncio
async def test_placeholder_stub_never_shadows_a_real_account():
    """Chatting before being provisioned must not permanently pin someone to readonly.

    `/v1` auto-creates a conversation-owner stub keyed by whatever identity it saw
    (an email), always readonly. If that stub were treated as an account it would be
    found first and outrank the real account an admin creates afterwards.
    """
    import orchestrator.main as m

    rows = {
        "s1@example.com": {  # the auto-created stub
            "username": "s1@example.com",
            "role": "readonly",
            "metadata": {"source": "open_webui"},
        },
        "s1": {"username": "s1", "role": "analyst", "metadata": {}},  # the real account
    }

    async def _get_user(name):
        return rows.get(name)

    pg = SimpleNamespace(get_user=_get_user)
    with patch.object(m.settings, "TRUST_FORWARDED_USER", True), patch.object(
        m, "postgres_manager", pg
    ):
        got = await m.resolve_forwarded_user(_request({"X-OpenWebUI-User-Email": "s1@example.com"}))
    assert got == ("s1", "analyst")


@pytest.mark.asyncio
async def test_placeholder_marker_survives_json_string_metadata():
    import orchestrator.main as m

    assert m._is_placeholder_account({"metadata": '{"source": "open_webui"}'}) is True
    assert m._is_placeholder_account({"metadata": {"source": "open_webui"}}) is True
    assert m._is_placeholder_account({"metadata": {}}) is False
    assert m._is_placeholder_account({"metadata": None}) is False
