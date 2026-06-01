from shared.config import settings


def test_conversation_max_messages_exists():
    assert hasattr(settings, "CONVERSATION_MAX_MESSAGES")
    assert settings.CONVERSATION_MAX_MESSAGES >= 1


def test_conversation_ttl_default_is_zero():
    """TTL=0 means no expiry — count-based eviction instead."""
    from shared.config import Settings
    s = Settings()
    assert s.CONVERSATION_TTL == 0
