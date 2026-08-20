"""
Shared live-chat fixture for regression tests that hit the running orchestrator
on localhost:8000.

Used by the Phase 2 regression battery:
  - tests/test_capability_e2e.py
  - tests/test_non_regression_intents.py
  - tests/test_floor_n_protection.py
  - tests/test_capability_edge_cases.py
  - tests/test_capability_semantic_quality.py
  - tests/test_ontology_integrity.py
  - tests/perf/test_capability_performance.py

Provides:
  - LiveChatClient: thin wrapper around POST /chat with session auth + rate limiting
  - chat_client: pytest fixture that yields a LiveChatClient
  - skip_if_orchestrator_down: pytest marker that skips a test if /health 4xx/5xx
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
import requests

BASE = "http://localhost:8000"
DEFAULT_BUILDING = "bldg1"
DEFAULT_USER = "regtest"
DEFAULT_PASS = "regtestpass99"

# Server allows ~60 requests / 60s. Keep a comfortable margin.
REQUEST_DELAY_SECONDS = 1.1


@dataclass
class ChatResponse:
    """Normalised /chat response for assertions."""

    response_text: str
    intent: Optional[str]
    success: bool
    latency_s: float
    raw: Dict[str, Any] = field(default_factory=dict)

    def contains(self, *substrs: str, case_insensitive: bool = True) -> bool:
        """True if response_text contains ALL given substrings."""
        haystack = self.response_text.lower() if case_insensitive else self.response_text
        return all((s.lower() if case_insensitive else s) in haystack for s in substrs)

    def contains_any(self, *substrs: str, case_insensitive: bool = True) -> bool:
        """True if response_text contains AT LEAST ONE of the substrings."""
        haystack = self.response_text.lower() if case_insensitive else self.response_text
        return any((s.lower() if case_insensitive else s) in haystack for s in substrs)


class LiveChatClient:
    """Wrapper around POST /chat. Authenticates lazily, rate-limits, retries on 429."""

    def __init__(
        self,
        base: str = BASE,
        username: str = DEFAULT_USER,
        password: str = DEFAULT_PASS,
        building_id: str = DEFAULT_BUILDING,
    ):
        self.base = base
        self.username = username
        self.password = password
        self.building_id = building_id
        self._token: Optional[str] = None

    # ── auth ────────────────────────────────────────────────────────────────────

    def _login(self) -> str:
        """Returns a valid session token; auto-registers if user doesn't exist yet."""
        # Try login
        try:
            r = requests.post(
                f"{self.base}/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=10,
            )
            if r.status_code == 200 and r.json().get("success"):
                return r.json()["data"]["session_token"]
        except Exception:
            pass

        # Fallback: register + login
        requests.post(
            f"{self.base}/auth/register",
            json={
                "username": self.username,
                "password": self.password,
                "email": f"{self.username}@test.local",
            },
            timeout=10,
        )
        r = requests.post(
            f"{self.base}/auth/login",
            json={"username": self.username, "password": self.password},
            timeout=10,
        )
        return r.json()["data"]["session_token"]

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = self._login()
        return self._token

    # ── chat ────────────────────────────────────────────────────────────────────

    def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        building_id: Optional[str] = None,
        timeout: int = 90,
        rate_limit: bool = True,
    ) -> ChatResponse:
        """Send a single /chat request. Returns ChatResponse."""
        sid = session_id or f"regtest-{uuid.uuid4().hex[:10]}"
        bldg = building_id or self.building_id
        if rate_limit:
            time.sleep(REQUEST_DELAY_SECONDS)
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.token,
        }
        body = {"message": message, "session_id": sid, "building_id": bldg}

        t0 = time.time()
        for attempt in range(3):
            r = requests.post(f"{self.base}/chat", headers=headers, json=body, timeout=timeout)
            if r.status_code == 429:
                # Rate limited — back off then retry
                time.sleep(30 + attempt * 30)
                continue
            break
        latency = time.time() - t0

        if r.status_code >= 400:
            return ChatResponse(
                response_text=r.text,
                intent=None,
                success=False,
                latency_s=latency,
                raw={"status_code": r.status_code, "body": r.text},
            )

        data = r.json()
        # Response wire format: {"success": bool, "data": {"response": str, ...}, ...}
        payload = data.get("data") or {}
        return ChatResponse(
            response_text=payload.get("response", ""),
            intent=payload.get("intent"),
            success=bool(data.get("success", False)),
            latency_s=latency,
            raw=data,
        )

    # ── health ─────────────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        try:
            r = requests.get(f"{self.base}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False


# ── pytest fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def chat_client():
    """Session-scoped LiveChatClient. Skips suite if orchestrator unreachable."""
    client = LiveChatClient()
    if not client.is_alive():
        pytest.skip("orchestrator at localhost:8000 not reachable — skipping live tests")
    return client


@pytest.fixture
def fresh_session_id():
    """Returns a unique session_id per test (avoids cross-test Redis state)."""
    return f"regtest-{uuid.uuid4().hex[:10]}"
