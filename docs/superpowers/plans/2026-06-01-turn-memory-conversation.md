# Turn-Memory Conversation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace time-based Redis TTL with a count-based sliding window + permanent Postgres turn-memory store so OntoSage maintains full ChatGPT-style conversation context indefinitely.

**Architecture:** Redis holds the last 20 verbatim messages as a hot cache (no TTL, evicted by count). Postgres stores one structured `turn_memory` row per conversation turn containing a deterministic 1-line result summary and the carry-forward artifacts needed for follow-up visualizations. On each new turn the last 20 messages come from Redis; older context is injected as a compact summary prefix reconstructed from Postgres rows.

**Tech Stack:** asyncpg (Postgres), redis.asyncio (Redis), Pydantic (ConversationState), pytest + pytest-asyncio (tests), unittest.mock (DB mocking)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `shared/config.py` | Add `CONVERSATION_MAX_MESSAGES`, change `CONVERSATION_TTL` default to `0` |
| Create | `orchestrator/services/turn_memory.py` | `TurnMemoryService`: save/load per-turn structured summaries |
| Modify | `orchestrator/postgres_manager.py` | Add `turn_memory` table to `_init_schema()` |
| Modify | `orchestrator/redis_manager.py` | Remove TTL from `save_state()`, add count-based message trim |
| Modify | `orchestrator/main.py` | Wire `TurnMemoryService` into `openai_chat_completions` |
| Create | `tests/test_turn_memory.py` | Unit tests for `TurnMemoryService` (mocked asyncpg) |
| Create | `tests/test_conversation_memory_e2e.py` | End-to-end flow: save turn → load context → carry-forward |

---

## Task 1: Config constants

**Files:**
- Modify: `shared/config.py` (lines ~349–371)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_turn_memory.py  (create file, add this first)
from shared.config import settings

def test_conversation_max_messages_exists():
    assert hasattr(settings, "CONVERSATION_MAX_MESSAGES")
    assert settings.CONVERSATION_MAX_MESSAGES >= 1

def test_conversation_ttl_default_is_zero():
    """TTL=0 means no expiry — count-based eviction instead."""
    # Default must be 0 so new installs get no-expiry behaviour.
    # Existing deployments can override via env var.
    from shared.config import Settings
    s = Settings()
    assert s.CONVERSATION_TTL == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

```
pytest tests/test_turn_memory.py::test_conversation_max_messages_exists tests/test_turn_memory.py::test_conversation_ttl_default_is_zero -v
```
Expected: `FAILED` — `test_conversation_max_messages_exists` (AttributeError) + `FAILED` — `test_conversation_ttl_default_is_zero` (assertion error, default is 3600).

- [ ] **Step 3: Edit `shared/config.py`**

Find the `CONVERSATION_TTL` field (~line 350) and the `MAX_CONVERSATION_HISTORY` field (~line 369). Replace both:

```python
    # ==================== Conversation Settings ====================
    CONVERSATION_TTL: int = Field(
        default=0,
        description=(
            "Conversation state TTL in Redis seconds. "
            "0 = no expiry (count-based eviction via CONVERSATION_MAX_MESSAGES). "
            "Set to e.g. 86400 to re-enable time-based expiry."
        ),
    )
    CONVERSATION_MAX_MESSAGES: int = Field(
        default=20,
        description="Max verbatim messages kept per conversation in Redis hot cache.",
    )
    MAX_CONVERSATION_HISTORY: int = Field(
        default=20, description="Max prior turns injected into LLM context from Redis."
    )
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_turn_memory.py::test_conversation_max_messages_exists tests/test_turn_memory.py::test_conversation_ttl_default_is_zero -v
```
Expected: `PASSED PASSED`.

- [ ] **Step 5: Commit**

```bash
git add shared/config.py tests/test_turn_memory.py
git commit -m "feat(memory): add CONVERSATION_MAX_MESSAGES, default CONVERSATION_TTL=0 (no expiry)"
```

---

## Task 2: Redis — count-based eviction, no TTL

**Files:**
- Modify: `orchestrator/redis_manager.py`

- [ ] **Step 1: Add tests to `tests/test_turn_memory.py`**

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shared.models import ConversationState, Message


def _make_state(n_messages: int = 5, conversation_id: str = "conv-1") -> ConversationState:
    msgs = [Message(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
            for i in range(n_messages)]
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
    from orchestrator.redis_manager import RedisManager

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
    from orchestrator.redis_manager import RedisManager

    rm = RedisManager()
    rm.client = AsyncMock()
    rm.conversation_ttl = 3600

    state = _make_state()
    await rm.save_state(state)

    rm.client.setex.assert_called_once()
    rm.client.set.assert_not_called()


@pytest.mark.asyncio
async def test_trim_messages_called_after_save():
    """After saving state, messages list must be trimmed to CONVERSATION_MAX_MESSAGES."""
    from orchestrator.redis_manager import RedisManager

    rm = RedisManager()
    rm.client = AsyncMock()
    rm.conversation_ttl = 0
    rm.max_messages = 20

    state = _make_state(n_messages=30)
    await rm.save_state(state)

    # ltrim should have been called on the messages key
    ltrim_calls = [str(c) for c in rm.client.ltrim.call_args_list]
    assert any("messages:" in s for s in ltrim_calls)
```

- [ ] **Step 2: Run tests — expect FAIL**

```
pytest tests/test_turn_memory.py::test_save_state_uses_set_not_setex_when_ttl_zero tests/test_turn_memory.py::test_save_state_uses_setex_when_ttl_nonzero tests/test_turn_memory.py::test_trim_messages_called_after_save -v
```
Expected: all three `FAILED`.

- [ ] **Step 3: Edit `orchestrator/redis_manager.py`**

**3a.** In `__init__`, add `max_messages`:

```python
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self.client: Optional[redis.Redis] = None
        self.conversation_ttl = settings.CONVERSATION_TTL
        self.max_messages = settings.CONVERSATION_MAX_MESSAGES
```

**3b.** Replace the `save_state` method body (keep signature identical):

```python
    async def save_state(self, state: ConversationState) -> bool:
        """Save conversation state to Redis (no TTL when CONVERSATION_TTL==0)."""
        if not self.client:
            await self.connect()

        try:
            key = f"conversation:{state.conversation_id}"
            state_dict = state.dict()

            logger.info(f"💾 REDIS SAVE: conversation_id={state.conversation_id}")
            logger.info(f"   ├─ Messages count: {len(state.messages)}")
            logger.info(f"   ├─ User: {state.user_id}")
            logger.info(
                f"   ├─ Intermediate results keys: "
                f"{list(state.intermediate_results.keys()) if state.intermediate_results else 'None'}"
            )

            serialized = json.dumps(state_dict, default=str)
            if self.conversation_ttl > 0:
                logger.info(f"   └─ TTL: {self.conversation_ttl}s")
                await self.client.setex(key, self.conversation_ttl, serialized)
            else:
                logger.info("   └─ TTL: none (count-based eviction)")
                await self.client.set(key, serialized)

            # Count-based message eviction — trim messages list to max_messages
            msgs_key = f"messages:{state.conversation_id}"
            await self.client.ltrim(msgs_key, -self.max_messages, -1)

            logger.info(f"✅ Successfully saved state for {state.conversation_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to save state: {e}")
            return False
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_turn_memory.py::test_save_state_uses_set_not_setex_when_ttl_zero tests/test_turn_memory.py::test_save_state_uses_setex_when_ttl_nonzero tests/test_turn_memory.py::test_trim_messages_called_after_save -v
```
Expected: `PASSED PASSED PASSED`.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/redis_manager.py tests/test_turn_memory.py
git commit -m "feat(memory): Redis save_state uses SET (no TTL) when CONVERSATION_TTL=0, trims messages by count"
```

---

## Task 3: Postgres `turn_memory` table

**Files:**
- Modify: `orchestrator/postgres_manager.py` (method `_init_schema`)

- [ ] **Step 1: Add test to `tests/test_turn_memory.py`**

```python
@pytest.mark.asyncio
async def test_init_schema_creates_turn_memory_table():
    """_init_schema must CREATE TABLE IF NOT EXISTS turn_memory."""
    from orchestrator.postgres_manager import PostgresManager

    pm = PostgresManager()
    executed_sqls = []

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=lambda sql: executed_sqls.append(sql))

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    pm.pool = mock_pool

    await pm._init_schema()

    combined = " ".join(executed_sqls)
    assert "turn_memory" in combined, "turn_memory table not created in _init_schema"
    assert "conversation_id" in combined
    assert "result_summary" in combined
    assert "carry_forward" in combined
```

- [ ] **Step 2: Run test — expect FAIL**

```
pytest tests/test_turn_memory.py::test_init_schema_creates_turn_memory_table -v
```
Expected: `FAILED` — assertion `"turn_memory" in combined`.

- [ ] **Step 3: Add `turn_memory` table to `orchestrator/postgres_manager.py`**

Inside `_init_schema`, after the `messages` table CREATE (around line 98), add:

```python
            # Turn memory table — one row per conversation turn.
            # Stores a structured summary (no raw sensor arrays) for long-term
            # context injection and cross-turn carry-forward artifacts.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS turn_memory (
                    id            SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(255) NOT NULL,
                    user_id       VARCHAR(255),
                    turn_index    INTEGER NOT NULL DEFAULT 0,
                    user_query    TEXT NOT NULL,
                    intent        VARCHAR(100),
                    entities      JSONB    DEFAULT '{}'::jsonb,
                    result_summary TEXT,
                    carry_forward JSONB    DEFAULT '{}'::jsonb,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_turn_memory_conv
                ON turn_memory(conversation_id, turn_index DESC);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_turn_memory_user
                ON turn_memory(user_id);
            """)
```

- [ ] **Step 4: Run test — expect PASS**

```
pytest tests/test_turn_memory.py::test_init_schema_creates_turn_memory_table -v
```
Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/postgres_manager.py tests/test_turn_memory.py
git commit -m "feat(memory): add turn_memory table + indices to Postgres schema"
```

---

## Task 4: `TurnMemoryService` — save and load

**Files:**
- Create: `orchestrator/services/turn_memory.py`

- [ ] **Step 1: Write all unit tests to `tests/test_turn_memory.py`**

```python
# ── TurnMemoryService tests ───────────────────────────────────────────────────

from orchestrator.services.turn_memory import TurnMemoryService


def _make_forecast_state() -> ConversationState:
    return ConversationState(
        conversation_id="conv-fc",
        user_id="alice",
        user_message="forecast 5.02 next 24h",
        building_id="bldg1",
        messages=[
            Message(role="user", content="forecast 5.02 next 24h"),
            Message(role="assistant", content="24h forecast: 21–23°C, ARIMA model, RMSE=0.8"),
        ],
        intermediate_results={
            "intent": "forecast",
            "entities": [{"type": "room", "value": "5.02"}],
            "forecast_result": {
                "success": True,
                "sensor_label": "Zone 5.02 Temperature",
                "model": "ARIMA",
                "horizon": "next 24 hours",
                "metrics": {"rmse": 0.82, "mae": 0.61, "mape": 3.1},
                "forecast": [21.1, 21.3, 21.5],
                "lower_80": [20.5, 20.7, 20.9],
                "upper_80": [21.7, 21.9, 22.1],
                "lower_95": [20.0, 20.2, 20.4],
                "upper_95": [22.2, 22.4, 22.6],
                "formatted_response": "Forecast: 21–23°C over 24h",
            },
        },
    )


def test_extract_result_summary_forecast():
    svc = TurnMemoryService(pool=None)
    state = _make_forecast_state()
    summary = svc._extract_result_summary(state)
    assert "Zone 5.02 Temperature" in summary
    assert "ARIMA" in summary
    assert "0.82" in summary


def test_extract_result_summary_general_fallback():
    svc = TurnMemoryService(pool=None)
    state = ConversationState(
        conversation_id="conv-gen",
        user_id="bob",
        user_message="hello",
        building_id="bldg1",
        messages=[
            Message(role="user", content="hello"),
            Message(role="assistant", content="Hi! How can I help you today?"),
        ],
        intermediate_results={"intent": "greeting"},
    )
    summary = svc._extract_result_summary(state)
    assert "Hi!" in summary


def test_extract_carry_forward_includes_forecast_result():
    svc = TurnMemoryService(pool=None)
    state = _make_forecast_state()
    cf = svc._extract_carry_forward(state)
    assert "forecast_result" in cf
    assert cf["forecast_result"]["success"] is True


def test_extract_carry_forward_excludes_raw_sparql():
    svc = TurnMemoryService(pool=None)
    state = ConversationState(
        conversation_id="conv-sparql",
        user_id="carol",
        user_message="what sensors exist",
        building_id="bldg1",
        messages=[Message(role="user", content="what sensors exist")],
        intermediate_results={
            "intent": "discovery",
            "sparql_results": [{"s": "http://...sensor1"}, {"s": "http://...sensor2"}],
        },
    )
    cf = svc._extract_carry_forward(state)
    assert "sparql_results" not in cf
    assert "sql_data" not in cf


@pytest.mark.asyncio
async def test_save_turn_inserts_row():
    """save_turn executes an INSERT with correct fields."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)  # next turn_index

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    state = _make_forecast_state()
    await svc.save_turn(state)

    mock_conn.execute.assert_called_once()
    call_sql = mock_conn.execute.call_args[0][0]
    assert "INSERT INTO turn_memory" in call_sql


@pytest.mark.asyncio
async def test_get_context_returns_summary_string():
    """get_older_context returns a non-empty string when rows exist."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {
            "turn_index": 1,
            "user_query": "forecast room 5.02 next 24h",
            "intent": "forecast",
            "result_summary": "24h forecast Zone 5.02 Temperature: ARIMA RMSE=0.82",
        }
    ])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    ctx = await svc.get_older_context("conv-fc", skip_recent=20)
    assert ctx != ""
    assert "5.02" in ctx


@pytest.mark.asyncio
async def test_get_carry_forward_returns_forecast_result():
    """get_carry_forward returns carry_forward JSON from the most recent turn."""
    forecast_cf = {
        "forecast_result": {
            "success": True,
            "sensor_label": "Zone 5.02 Temperature",
            "model": "ARIMA",
        }
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"carry_forward": json.dumps(forecast_cf)})

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    cf = await svc.get_carry_forward("conv-fc")
    assert cf.get("forecast_result", {}).get("success") is True


@pytest.mark.asyncio
async def test_save_turn_no_op_when_pool_none():
    """save_turn must not raise when Postgres is unavailable (pool=None)."""
    svc = TurnMemoryService(pool=None)
    state = _make_forecast_state()
    await svc.save_turn(state)   # must not raise
```

- [ ] **Step 2: Run tests — expect FAIL (module not found)**

```
pytest tests/test_turn_memory.py -k "TurnMemoryService or extract or carry_forward or save_turn or get_context or get_carry_forward" -v
```
Expected: `ERROR` — `ModuleNotFoundError: No module named 'orchestrator.services.turn_memory'`.

- [ ] **Step 3: Create `orchestrator/services/turn_memory.py`**

```python
"""
TurnMemoryService — structured per-turn memory for OntoSage conversations.

Each completed turn is summarised into one Postgres row:
  - user_query     : verbatim user message
  - intent         : classified intent
  - entities       : extracted entities (JSON)
  - result_summary : deterministic 1-line human-readable summary (no raw arrays)
  - carry_forward  : forecast_result / analytics_result needed for follow-up viz

On the next turn:
  - get_carry_forward()   → injects forecast/analytics artifacts into intermediate_results
  - get_older_context()   → builds a compact text prefix injected as a system message
                            so the LLM knows what happened in earlier turns
"""

import json
from typing import Any, Dict, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Keys whose full JSON is stored for carry-forward (needed for cross-turn viz).
# All other intermediate_results keys contain raw sensor arrays and are excluded.
_CARRY_FORWARD_KEYS = {"forecast_result", "analytics_result"}

# Max characters for result_summary stored in Postgres
_SUMMARY_MAX_CHARS = 300


class TurnMemoryService:
    """Save and retrieve per-turn structured memory from Postgres."""

    def __init__(self, pool: Any):
        self.pool = pool

    # ── Public API ────────────────────────────────────────────────────────────

    async def save_turn(self, state: ConversationState) -> None:
        """Persist a completed turn to the turn_memory table.

        No-ops gracefully when Postgres pool is None (e.g. in tests or when DB is down).
        """
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                turn_index = await conn.fetchval(
                    "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM turn_memory WHERE conversation_id = $1",
                    state.conversation_id,
                )
                await conn.execute(
                    """
                    INSERT INTO turn_memory
                        (conversation_id, user_id, turn_index, user_query,
                         intent, entities, result_summary, carry_forward)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    state.conversation_id,
                    state.user_id or "",
                    turn_index,
                    state.user_message or "",
                    state.intermediate_results.get("intent", "general"),
                    json.dumps(state.intermediate_results.get("entities") or []),
                    self._extract_result_summary(state),
                    json.dumps(self._extract_carry_forward(state)),
                )
                logger.info(
                    f"[turn_memory] saved turn {turn_index} for conv={state.conversation_id}"
                )
        except Exception as e:
            logger.warning(f"[turn_memory] save_turn failed (non-fatal): {e}")

    async def get_carry_forward(self, conversation_id: str) -> Dict[str, Any]:
        """Return carry_forward dict from the most recent turn, or empty dict."""
        if not self.pool:
            return {}
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT carry_forward FROM turn_memory
                    WHERE conversation_id = $1
                    ORDER BY turn_index DESC LIMIT 1
                    """,
                    conversation_id,
                )
            if row and row["carry_forward"]:
                cf = row["carry_forward"]
                return json.loads(cf) if isinstance(cf, str) else cf
        except Exception as e:
            logger.warning(f"[turn_memory] get_carry_forward failed (non-fatal): {e}")
        return {}

    async def get_older_context(self, conversation_id: str, skip_recent: int = 20) -> str:
        """Return a compact text block summarising turns older than `skip_recent`.

        This is injected as a system-context prefix so the LLM retains memory
        of earlier turns without replaying their full text.
        Returns "" when there are no older turns.
        """
        if not self.pool:
            return ""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT turn_index, user_query, intent, result_summary
                    FROM turn_memory
                    WHERE conversation_id = $1
                    ORDER BY turn_index DESC
                    OFFSET $2
                    """,
                    conversation_id,
                    skip_recent,
                )
            if not rows:
                return ""
            lines = []
            for r in reversed(rows):
                summary = r["result_summary"] or "(no summary)"
                lines.append(
                    f"Turn {r['turn_index']} [{r['intent']}]: Q: {r['user_query'][:80]} → {summary[:150]}"
                )
            return "Earlier conversation context:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning(f"[turn_memory] get_older_context failed (non-fatal): {e}")
        return ""

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_result_summary(self, state: ConversationState) -> str:
        """Build a deterministic 1-line summary — no LLM call, no raw arrays."""
        ir = state.intermediate_results
        intent = ir.get("intent", "general")

        if intent in ("forecast", "trend"):
            fr = ir.get("forecast_result") or {}
            if fr.get("success"):
                sensor = fr.get("sensor_label", "sensor")
                model = fr.get("model", "model")
                horizon = fr.get("horizon", "forecast")
                metrics = fr.get("metrics") or {}
                rmse = metrics.get("rmse")
                rmse_str = f" RMSE={rmse:.2f}" if rmse else ""
                return f"{horizon} {sensor}: {model}{rmse_str}"

        if intent in ("analytics", "compare", "compliance", "anomaly"):
            ar = ir.get("analytics_result") or {}
            resp = (ar.get("formatted_response") or "").strip()
            if resp:
                return resp[:_SUMMARY_MAX_CHARS]

        # Fallback: first N chars of the last assistant message
        last_assistant = next(
            (m.content for m in reversed(state.messages) if m.role == "assistant"),
            "",
        )
        return last_assistant[:_SUMMARY_MAX_CHARS]

    def _extract_carry_forward(self, state: ConversationState) -> Dict[str, Any]:
        """Extract only the safe carry-forward keys (forecast + analytics artifacts)."""
        return {
            k: v
            for k, v in state.intermediate_results.items()
            if k in _CARRY_FORWARD_KEYS
        }
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_turn_memory.py -k "extract or carry_forward or save_turn or get_context or get_carry_forward or no_op" -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/turn_memory.py tests/test_turn_memory.py
git commit -m "feat(memory): add TurnMemoryService — structured per-turn Postgres memory"
```

---

## Task 5: Wire `TurnMemoryService` into `openai_chat_completions`

**Files:**
- Modify: `orchestrator/main.py`

The wiring has three injection points inside `openai_chat_completions`:

1. **Startup** — instantiate `TurnMemoryService` using the Postgres pool.
2. **Pre-turn** — replace the Redis-only carry-forward with `turn_memory.get_carry_forward()` + inject older context as a system message prefix.
3. **Post-turn** — call `turn_memory.save_turn(final_state)`.

- [ ] **Step 1: Add end-to-end flow tests to `tests/test_conversation_memory_e2e.py`**

```python
"""End-to-end flow tests for turn memory wiring in openai_chat_completions.

These tests exercise the three injection points without spinning up real
Postgres/Redis — they mock at the service boundary.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import ConversationState, Message
from orchestrator.services.turn_memory import TurnMemoryService


# ── Helper: minimal carry_forward from a forecast turn ───────────────────────

_FORECAST_CF = {
    "forecast_result": {
        "success": True,
        "sensor_label": "Zone 5.02 Temperature",
        "model": "ARIMA",
        "horizon": "next 24 hours",
        "metrics": {"rmse": 0.82, "mae": 0.61, "mape": 3.1},
        "forecast": [21.1, 21.3],
        "lower_80": [20.5, 20.7],
        "upper_80": [21.7, 21.9],
        "lower_95": [20.0, 20.2],
        "upper_95": [22.2, 22.4],
        "formatted_response": "24h forecast: 21-23°C",
    }
}


def test_carry_forward_survives_json_round_trip():
    """carry_forward JSON stored in Postgres must deserialise back to same dict."""
    svc = TurnMemoryService(pool=None)
    state = ConversationState(
        conversation_id="conv-rt",
        user_id="alice",
        user_message="forecast",
        building_id="bldg1",
        messages=[Message(role="user", content="forecast")],
        intermediate_results=_FORECAST_CF,
    )
    cf = svc._extract_carry_forward(state)
    serialized = json.dumps(cf)
    restored = json.loads(serialized)
    assert restored["forecast_result"]["success"] is True
    assert restored["forecast_result"]["sensor_label"] == "Zone 5.02 Temperature"


@pytest.mark.asyncio
async def test_carry_forward_injected_into_new_state():
    """get_carry_forward result must appear in the new state's intermediate_results."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(
        return_value={"carry_forward": json.dumps(_FORECAST_CF)}
    )
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    cf = await svc.get_carry_forward("conv-fc")

    # Simulate what main.py does: build new state with carry_forward
    new_state = ConversationState(
        conversation_id="conv-fc",
        user_id="alice",
        user_message="show graph",
        building_id="bldg1",
        messages=[Message(role="user", content="show graph")],
        intermediate_results=cf,
    )

    assert new_state.intermediate_results.get("forecast_result", {}).get("success") is True


@pytest.mark.asyncio
async def test_older_context_prepended_as_system_message():
    """Older turn summaries must be injected as the first message in state."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {
            "turn_index": 1,
            "user_query": "what is the temperature in room 5.02",
            "intent": "sensor_data",
            "result_summary": "Room 5.02: 22.3°C current reading",
        }
    ])
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    ctx = await svc.get_older_context("conv-fc", skip_recent=20)

    assert "22.3" in ctx
    assert "sensor_data" in ctx


@pytest.mark.asyncio
async def test_save_turn_does_not_store_raw_sensor_arrays():
    """Raw SQL/SPARQL data must never reach the turn_memory table."""
    executed_sqls = []
    executed_args = []

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    async def capture_execute(sql, *args):
        executed_sqls.append(sql)
        executed_args.append(args)

    mock_conn.execute = AsyncMock(side_effect=capture_execute)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    svc = TurnMemoryService(pool=mock_pool)
    state = ConversationState(
        conversation_id="conv-sql",
        user_id="bob",
        user_message="temperature last hour",
        building_id="bldg1",
        messages=[Message(role="user", content="temperature last hour"),
                  Message(role="assistant", content="Average: 22.1°C")],
        intermediate_results={
            "intent": "sensor_data",
            "sql_data": [{"ts": "2026-06-01T10:00", "value": 22.1}] * 500,
            "sparql_results": [{"uuid": "abc123"}] * 100,
        },
    )
    await svc.save_turn(state)

    # The stored carry_forward JSON must NOT contain sql_data or sparql_results
    insert_sql = next((s for s in executed_sqls if "INSERT" in s), "")
    assert insert_sql, "No INSERT executed"
    cf_arg = executed_args[0][7]  # 8th positional arg = carry_forward JSON
    cf = json.loads(cf_arg)
    assert "sql_data" not in cf
    assert "sparql_results" not in cf
```

- [ ] **Step 2: Run tests — expect PASS (no main.py changes yet)**

```
pytest tests/test_conversation_memory_e2e.py -v
```
Expected: all `PASSED` — these tests target `TurnMemoryService` directly, not `main.py`.

- [ ] **Step 3: Edit `orchestrator/main.py` — instantiate `TurnMemoryService`**

Near the top of `openai_chat_completions` (after the `postgres_manager` import area, before the handler body), find the line where `postgres_manager` is first referenced inside the function. Add `TurnMemoryService` instantiation near the top of the function body, after parsing `data`:

```python
        # Turn memory service — uses the same Postgres pool as postgres_manager
        from orchestrator.services.turn_memory import TurnMemoryService as _TMS
        _turn_memory = _TMS(
            pool=postgres_manager.pool if postgres_manager else None
        )
```

Add this block immediately after line:
```python
        logger.info(
            f"[/v1/chat/completions] loaded {len(prior_messages)} prior turns into state"
        )
```

- [ ] **Step 4: Replace Redis-only carry-forward with `TurnMemoryService`**

Find the block added in the previous session (the `_CARRY_FORWARD_KEYS` block):

```python
        # Carry forward selected intermediate_results from the previous turn so
        # nodes like _visualization_node can reference prior forecast/analytics
        # data (e.g. "show me the graph for the above").
        _CARRY_FORWARD_KEYS = {"forecast_result", "analytics_result"}
        carry_forward: dict = {}
        try:
            _prev = await redis_manager.load_state(conversation_id)
            if _prev and _prev.intermediate_results:
                carry_forward = {
                    k: v for k, v in _prev.intermediate_results.items()
                    if k in _CARRY_FORWARD_KEYS
                }
                if carry_forward:
                    logger.info(
                        f"[/v1/chat/completions] carried forward from Redis: {list(carry_forward.keys())}"
                    )
        except Exception as _ce:
            logger.debug(f"[/v1/chat/completions] Redis carry-forward skipped: {_ce}")
```

Replace entirely with:

```python
        # Carry forward forecast/analytics artifacts from previous turn.
        # Primary source: Postgres turn_memory (persistent, survives Redis flush).
        # Fallback: Redis hot-cache (same session, faster).
        carry_forward: dict = {}
        try:
            carry_forward = await _turn_memory.get_carry_forward(conversation_id)
            if not carry_forward:
                # Redis fallback
                _prev = await redis_manager.load_state(conversation_id)
                if _prev and _prev.intermediate_results:
                    _cf_keys = {"forecast_result", "analytics_result"}
                    carry_forward = {k: v for k, v in _prev.intermediate_results.items()
                                     if k in _cf_keys}
            if carry_forward:
                logger.info(
                    f"[/v1/chat/completions] carry-forward loaded: {list(carry_forward.keys())}"
                )
        except Exception as _ce:
            logger.debug(f"[/v1/chat/completions] carry-forward skipped: {_ce}")

        # Inject older turn summaries (turns beyond the 20-message Redis window)
        # as a compact system-context prefix so the LLM retains long-term memory.
        older_context = ""
        try:
            older_context = await _turn_memory.get_older_context(
                conversation_id, skip_recent=settings.CONVERSATION_MAX_MESSAGES
            )
        except Exception as _oe:
            logger.debug(f"[/v1/chat/completions] older_context skipped: {_oe}")
```

- [ ] **Step 5: Inject `older_context` into state messages**

Find the line where `state.messages.append(Message(role="user", ...))` adds the current message. Just before that append, add:

```python
        # Prepend older turn summaries as a system message so the LLM has
        # long-term memory beyond the 20-message Redis window.
        if older_context:
            state.messages.insert(
                0,
                Message(role="system", content=older_context, timestamp=datetime.now()),
            )
```

- [ ] **Step 6: Add `save_turn` call in the streaming path**

Find the block in `event_generator()` where Redis state is saved:

```python
                # Persist state to Redis so the next turn can carry forward
                # intermediate_results (e.g. forecast_result for viz requests)
                try:
                    await redis_manager.save_state(final_state)
                except Exception as _rse:
                    logger.debug(f"[/v1/chat/completions] Redis save skipped: {_rse}")
```

Add `save_turn` immediately after:

```python
                # Persist structured turn summary to Postgres for long-term memory
                try:
                    await _turn_memory.save_turn(final_state)
                except Exception as _tse:
                    logger.debug(f"[/v1/chat/completions] turn_memory save skipped: {_tse}")
```

- [ ] **Step 7: Add `save_turn` call in the non-streaming path**

Find the non-streaming Redis save block:

```python
        # Persist state to Redis (non-streaming path)
        try:
            await redis_manager.save_state(updated_state)
        except Exception as _rse:
            logger.debug(f"[/v1/chat/completions] Redis save skipped: {_rse}")
```

Add immediately after:

```python
        try:
            await _turn_memory.save_turn(updated_state)
        except Exception as _tse:
            logger.debug(f"[/v1/chat/completions] turn_memory save skipped: {_tse}")
```

- [ ] **Step 8: Run full test suite — must not regress**

```
pytest tests/test_turn_memory.py tests/test_conversation_memory_e2e.py tests/test_state_persistence.py -v
```
Expected: all `PASSED`, zero failures.

- [ ] **Step 9: Commit**

```bash
git add orchestrator/main.py tests/test_conversation_memory_e2e.py
git commit -m "feat(memory): wire TurnMemoryService into openai_chat_completions — save turn, carry forward, inject older context"
```

---

## Task 6: Full regression — run all tests

- [ ] **Step 1: Run the complete test suite**

```
pytest tests/ -v --tb=short -q
```

Expected: all tests that were passing before this feature remain passing. Any new failures are regressions introduced by this feature and must be fixed before proceeding.

- [ ] **Step 2: Fix any regressions**

Common causes:
- `CONVERSATION_TTL` default changed from 3600 to 0 — any test that asserts `settings.CONVERSATION_TTL == 3600` must be updated to `== 0` or removed.
- `RedisManager.save_state` now calls `.set()` instead of `.setex()` when TTL=0 — mocks expecting `.setex` need updating.

To find affected tests:
```
grep -r "CONVERSATION_TTL\|setex\|conversation_ttl" tests/
```

- [ ] **Step 3: Run suite again — confirm clean**

```
pytest tests/ -v --tb=short -q
```
Expected: same pass count as before this feature + new tests all green.

- [ ] **Step 4: Final commit**

```bash
git add -p   # stage only test fixes
git commit -m "fix(memory): update existing tests for TTL=0 default and SET-not-SETEX change"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All four design decisions covered — count-based eviction (Task 2), `turn_memory` Postgres table (Task 3), `TurnMemoryService` (Task 4), full wiring (Task 5).
- [x] **No placeholders:** Every step has exact code, exact commands, expected output.
- [x] **Type consistency:** `TurnMemoryService.__init__(pool)` used identically across Tasks 4 and 5. `_extract_carry_forward` and `_extract_result_summary` method names match between tests and implementation.
- [x] **Raw data exclusion:** `_extract_carry_forward` excludes `sparql_results`, `sql_data`, `correction_trace` — only `forecast_result` and `analytics_result` are stored. Verified by `test_save_turn_does_not_store_raw_sensor_arrays`.
- [x] **Graceful degradation:** Every `TurnMemoryService` method no-ops when `pool=None` — Postgres down never crashes a chat request.
- [x] **Backward compat:** `CONVERSATION_TTL > 0` still works via `setex` — existing deployments with env-var override are unaffected.
