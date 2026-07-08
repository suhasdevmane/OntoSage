"""
TurnMemoryService — structured per-turn memory for OntoSage conversations.

Each completed turn is summarised into one Postgres row:
  - user_query     : verbatim user message
  - intent         : classified intent
  - entities       : extracted entities (JSON)
  - result_summary : deterministic 1-line human-readable summary (no raw arrays)
  - carry_forward  : forecast_result / analytics_result for follow-up viz

On the next turn:
  - get_carry_forward()  -> injects forecast/analytics artifacts into intermediate_results
  - get_older_context()  -> builds compact text prefix for LLM long-term memory
"""

import json
from typing import Any, Dict, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

_CARRY_FORWARD_KEYS = {"forecast_result", "analytics_result"}
_SUMMARY_MAX_CHARS = 300
# Per-conversation retention cap: keep only the newest N turns; older rows are
# pruned on each save so a long-lived conversation can't grow the table without
# bound. This is the Postgres ROW cap — distinct from CONVERSATION_MAX_MESSAGES
# (the Redis working-context trim, ~20, which stays small to bound the LLM prompt).
_MAX_TURNS_PER_CONVERSATION = 500


class TurnMemoryService:
    """Save and retrieve per-turn structured memory from Postgres."""

    def __init__(self, pool: Any):
        self.pool = pool

    async def save_turn(self, state: ConversationState) -> None:
        """Persist a completed turn to turn_memory. No-ops when pool=None."""
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                turn_index = await conn.fetchval(
                    "SELECT COALESCE(MAX(turn_index), 0) + 1 "
                    "FROM turn_memory WHERE conversation_id = $1",
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
                    json.dumps(state.intermediate_results.get("entities") or [], default=str),
                    self._extract_result_summary(state),
                    # default=str coerces numpy/datetime/Decimal in the forecast/
                    # analytics carry_forward so the whole turn-save can't fail on
                    # them (the Redis save_state path already does this). Without it,
                    # a forecast follow-up ("now plot that") silently loses its state.
                    json.dumps(self._extract_carry_forward(state), default=str),
                )
                logger.info(
                    f"[turn_memory] saved turn {turn_index} "
                    f"for conv={state.conversation_id}"
                )
                # Retention: prune everything older than the newest N turns so a
                # long conversation can't grow the table unbounded. turn_index is
                # monotonic, so this keeps rows with turn_index > (MAX - N).
                await conn.execute(
                    """
                    DELETE FROM turn_memory
                    WHERE conversation_id = $1
                      AND turn_index <= (
                          SELECT MAX(turn_index) - $2
                          FROM turn_memory WHERE conversation_id = $1
                      )
                    """,
                    state.conversation_id,
                    _MAX_TURNS_PER_CONVERSATION,
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
            logger.warning(
                f"[turn_memory] get_carry_forward failed (non-fatal): {e}"
            )
        return {}

    async def get_older_context(
        self, conversation_id: str, skip_recent: int = 20, max_older: int = 30
    ) -> str:
        """Return compact text block summarising turns older than skip_recent.

        Capped at ``max_older`` turns (the most-recent among the older set) so a
        long conversation can't inject an ever-growing block into every LLM prompt
        — token blow-up / context-window overflow / an unbounded row scan. Returns
        "" when there are no older turns.
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
                    OFFSET $2 LIMIT $3
                    """,
                    conversation_id,
                    skip_recent,
                    max_older,
                )
            if not rows:
                return ""
            lines = []
            for r in reversed(rows):
                summary = r["result_summary"] or "(no summary)"
                lines.append(
                    f"Turn {r['turn_index']} [{r['intent']}]: "
                    f"Q: {r['user_query'][:80]} -> {summary[:150]}"
                )
            return "Earlier conversation context:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning(
                f"[turn_memory] get_older_context failed (non-fatal): {e}"
            )
        return ""

    async def delete_conversation(self, conversation_id: str) -> int:
        """Delete all turn_memory rows for a conversation (e.g. user clears a chat).
        Returns the number of rows removed."""
        return await self._delete_where("conversation_id", conversation_id)

    async def delete_user_turns(self, user_id: str) -> int:
        """Delete all turn_memory rows for a user — GDPR / right-to-be-forgotten
        erasure. Call on account deletion so per-turn history never outlives the
        account. Returns the number of rows removed."""
        return await self._delete_where("user_id", user_id)

    async def _delete_where(self, column: str, value: str) -> int:
        """DELETE by a WHITELISTED column ('conversation_id' | 'user_id'); the
        value is always parameterized. Returns the deleted row count (0 on error)."""
        if not self.pool or column not in ("conversation_id", "user_id"):
            return 0
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    f"DELETE FROM turn_memory WHERE {column} = $1", value
                )
            deleted = int(result.split()[-1]) if result else 0  # asyncpg -> "DELETE <n>"
            logger.info(f"[turn_memory] deleted {deleted} rows where {column}={value!r}")
            return deleted
        except Exception as e:
            logger.warning(f"[turn_memory] delete by {column} failed (non-fatal): {e}")
            return 0

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
                rmse_str = f" RMSE={rmse:.2f}" if rmse is not None else ""
                return f"{horizon} {sensor}: {model}{rmse_str}"

        if intent in ("analytics", "compare", "compliance", "anomaly"):
            ar = ir.get("analytics_result") or {}
            resp = (ar.get("formatted_response") or "").strip()
            if resp:
                return resp[:_SUMMARY_MAX_CHARS]

        last_assistant = next(
            (m.content for m in reversed(state.messages) if m.role == "assistant"),
            "",
        )
        return last_assistant[:_SUMMARY_MAX_CHARS]

    def _extract_carry_forward(self, state: ConversationState) -> Dict[str, Any]:
        """Extract only the safe carry-forward keys (forecast + analytics)."""
        return {
            k: v
            for k, v in state.intermediate_results.items()
            if k in _CARRY_FORWARD_KEYS
        }
