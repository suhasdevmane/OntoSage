import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.config import settings
from shared.models import ConversationState, Message


def test_conversation_max_messages_exists():
    assert hasattr(settings, "CONVERSATION_MAX_MESSAGES")
    assert settings.CONVERSATION_MAX_MESSAGES >= 1


def test_conversation_ttl_default_is_zero():
    """TTL=0 means no expiry — count-based eviction instead."""
    from shared.config import Settings
    s = Settings()
    assert s.CONVERSATION_TTL == 0


def _make_state(n_messages: int = 5, conversation_id: str = "conv-1") -> ConversationState:
    msgs = [
        Message(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
        for i in range(n_messages)
    ]
    return ConversationState(
        conversation_id=conversation_id,
        user_id="alice",
        user_message="hi",
        building_id="bldg1",
        messages=msgs,
    )


@pytest.mark.asyncio
async def test_save_state_uses_set_not_setex_when_ttl_zero():
    """When CONVERSATION_TTL==0, save_state must call SET (no expiry)."""
    from pathlib import Path
    import importlib.util

    # Import directly from the module to bypass __init__ issues
    redis_manager_path = Path(__file__).parent.parent / "orchestrator" / "redis_manager.py"
    spec = importlib.util.spec_from_file_location(
        "redis_manager_direct",
        str(redis_manager_path)
    )
    redis_mgr_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redis_mgr_mod)
    RedisManager = redis_mgr_mod.RedisManager

    rm = RedisManager()
    rm.client = AsyncMock()
    rm.conversation_ttl = 0

    state = _make_state()
    await rm.save_state(state)

    rm.client.set.assert_called_once()
    rm.client.setex.assert_not_called()


@pytest.mark.asyncio
async def test_save_state_uses_setex_when_ttl_nonzero():
    """When CONVERSATION_TTL>0, legacy setex behaviour is preserved."""
    from pathlib import Path
    import importlib.util

    # Import directly from the module to bypass __init__ issues
    redis_manager_path = Path(__file__).parent.parent / "orchestrator" / "redis_manager.py"
    spec = importlib.util.spec_from_file_location(
        "redis_manager_direct_nonzero",
        str(redis_manager_path)
    )
    redis_mgr_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redis_mgr_mod)
    RedisManager = redis_mgr_mod.RedisManager

    rm = RedisManager()
    rm.client = AsyncMock()
    rm.conversation_ttl = 3600

    state = _make_state()
    await rm.save_state(state)

    rm.client.setex.assert_called_once()
    rm.client.set.assert_not_called()


@pytest.mark.asyncio
async def test_trim_messages_called_after_save():
    """After saving state, messages list must be trimmed to max_messages."""
    from pathlib import Path
    import importlib.util

    # Import directly from the module to bypass __init__ issues
    redis_manager_path = Path(__file__).parent.parent / "orchestrator" / "redis_manager.py"
    spec = importlib.util.spec_from_file_location(
        "redis_manager_direct_trim",
        str(redis_manager_path)
    )
    redis_mgr_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redis_mgr_mod)
    RedisManager = redis_mgr_mod.RedisManager

    rm = RedisManager()
    rm.client = AsyncMock()
    rm.conversation_ttl = 0
    rm.max_messages = 20

    state = _make_state(n_messages=30)
    await rm.save_state(state)

    # ltrim should have been called on the messages key
    ltrim_calls = [str(c) for c in rm.client.ltrim.call_args_list]
    assert any("messages:" in s for s in ltrim_calls)
