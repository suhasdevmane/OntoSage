# -*- coding: utf-8 -*-
"""W01: the purge removes harness residue and can never match a person's conversation.

On 2026-09-18 Redis sat at 99.77% of its cap because ~16,000 harness conversations were never
deleted. The remedy deletes keys, so the property that matters is what it can NOT delete.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "redis_hygiene.py"


def _load():
    spec = importlib.util.spec_from_file_location("redis_hygiene", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["redis_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


rh = _load()

#: Ids that came from real Open WebUI chats and sessions (observed shapes, 2026-09-18).
REAL = [
    "owui_f89723ea7b605165:openwebui_user",
    "owui_606290a81b292d80:openwebui_user:meta",
    "owui_070acaa1c2bffd36:openwebui_user",
]
HARNESS = [
    "conv_baseline-cf5d1940:admin@ontosage",
    "owui_rehearsal-5b8b40ad:openwebui_user",
    "owui_replay-1a2b3c4d:openwebui_user",
    "owui_diag-9f8e7d6c:openwebui_user",
]


def _matches(key_id: str) -> bool:
    return any(key_id.startswith(p) for p in rh.HARNESS_PREFIXES)


@pytest.mark.parametrize("key_id", REAL)
def test_a_real_chat_never_matches_a_harness_prefix(key_id):
    assert not _matches(key_id), key_id


@pytest.mark.parametrize("key_id", HARNESS)
def test_every_harness_shape_is_matched(key_id):
    assert _matches(key_id), key_id


def test_only_conversation_families_are_scanned():
    """Sessions, users, caches and the compiled-query cache are never in a purge pattern."""
    assert set(rh.KEY_FAMILIES) == {"conversation", "messages"}
    for protected in ("session", "user", "user_sessions", "cache", "resp_cache", "cqir_compile"):
        assert protected not in rh.KEY_FAMILIES


def test_the_scan_patterns_are_prefix_scoped_not_family_wide(monkeypatch):
    seen = []
    monkeypatch.setattr(rh, "_scan", lambda c, pattern: seen.append(pattern) or [])
    rh.harness_keys("redis-memory-store")
    assert seen, "nothing was scanned"
    for pattern in seen:
        family, _, rest = pattern.partition(":")
        assert family in rh.KEY_FAMILIES
        assert rest != "*", "a family-wide pattern would delete real chats"
        assert any(rest.startswith(p) for p in rh.HARNESS_PREFIXES), pattern


def test_memory_parses_used_cap_and_fraction(monkeypatch):
    info = "used_memory:1073741824\nmaxmemory:2147483648\nmaxmemory_policy:allkeys-lru\n"
    monkeypatch.setattr(rh, "_cli", lambda *a, **k: info)
    m = rh.memory("x")
    assert m["fraction"] == pytest.approx(0.5)
    assert m["policy"] == "allkeys-lru"


def test_check_fails_over_the_limit_and_passes_under_it(monkeypatch, capsys):
    monkeypatch.setattr(rh, "harness_keys", lambda c: [])
    monkeypatch.setattr(
        rh, "memory", lambda c: {"used": 2, "cap": 2, "fraction": 0.997, "policy": "allkeys-lru"}
    )
    assert rh.main(["--check"]) == 1
    monkeypatch.setattr(
        rh, "memory", lambda c: {"used": 1, "cap": 100, "fraction": 0.01, "policy": "allkeys-lru"}
    )
    assert rh.main(["--check"]) == 0


def test_dry_run_deletes_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(rh, "harness_keys", lambda c: ["conversation:conv_x"])
    monkeypatch.setattr(rh, "purge", lambda c, k: called.append(k) or 0)
    monkeypatch.setattr(
        rh, "memory", lambda c: {"used": 1, "cap": 100, "fraction": 0.01, "policy": "allkeys-lru"}
    )
    assert rh.main(["--purge", "--dry-run"]) == 0
    assert called == []
