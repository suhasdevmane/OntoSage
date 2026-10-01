"""
TurnMemoryService — structured per-turn memory for OntoSage conversations.

Each completed turn is summarised into one Postgres row:
  - user_query     : verbatim user message
  - intent         : classified intent
  - entities       : extracted entities (JSON)
  - result_summary : deterministic 1-line human-readable summary (no raw arrays)
  - carry_forward  : forecast_result / analytics_result for follow-up viz

On the next turn:
  - get_carry_forward()    -> injects forecast/analytics artifacts into intermediate_results
  - get_session_summary()  -> the rolling, bounded, figure-free account of the session so
                              far (W5-01). Replaced get_older_context(), which dropped the
                              oldest turns outright and carried past ANSWERS — measurements
                              included — back into the prompt.
"""

import json
from typing import Any, Dict, List, Tuple

from orchestrator.services import session_summary
from orchestrator.services.session_summary import TurnNote
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

_CARRY_FORWARD_KEYS = {"forecast_result", "analytics_result"}
_SUMMARY_MAX_CHARS = 300
# How many older rows the rolling summary may scan in one turn. Above the Postgres
# retention cap below, so the scan sees every turn that still exists — the summary
# COMPRESSES what it cannot show in detail, and can only do that for rows it read.
_MAX_OLDER_SCAN = 500
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
                    f"[turn_memory] saved turn {turn_index} " f"for conv={state.conversation_id}"
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
            logger.warning(f"[turn_memory] get_carry_forward failed (non-fatal): {e}")
        return {}

    async def get_session_summary(
        self, conversation_id: str, skip_recent: int = session_summary.RECENT_TURNS_KEPT_RAW
    ) -> str:
        """Return the rolling session summary for turns older than ``skip_recent``.

        Replaces ``get_older_context``, which did two things wrong (W5-01):

        * it read ``OFFSET skip_recent LIMIT 30``, so at turn 60 turns 1-10 were dropped
          with no trace — the window was a cliff;
        * it carried ``result_summary[:150]``, the ANSWER verbatim, so a measurement from
          twenty turns ago was fed back into the prompt with no time basis.

        ``session_summary.build`` compresses rather than truncates, and carries no text
        derived from an answer at all. The scan is bounded at :data:`_MAX_OLDER_SCAN` rows
        and every text column is truncated BY THE DATABASE, so a conversation full of
        10,000-character questions cannot pull megabytes across the wire once per turn.
        Returns "" when there are no older turns.
        """
        return (await self.get_session_context(conversation_id, skip_recent))[0]

    async def get_session_context(
        self, conversation_id: str, skip_recent: int = session_summary.RECENT_TURNS_KEPT_RAW
    ) -> Tuple[str, List[TurnNote]]:
        """The rendered session summary AND the structured turns it was built from.

        Two readers, ONE database round trip. They need different slices of the same rows:

        * the SUMMARY skips the newest ``skip_recent`` turns, because the raw message window
          still shows them, and compresses everything older than its detail window into a
          single line naming subjects — which is right for a prompt and lossy for recall,
          since the compressed line keeps no question text.
        * the RECALL lane (BUG-941) needs every turn, in full, including the newest ones:
          "what did I just ask?" is a recall question too, and a user who declared their
          subject three turns ago is exactly the case the summary hands to the era line.

        So the fetch takes everything and the SLICING happens here. Doing it with two
        queries would double the per-turn cost of a feature that runs on every turn of every
        route, and doing it in the caller would put the offset arithmetic back in four
        places — which is how ``skip_recent`` came to be a MESSAGE count used as a TURN
        offset and left a seventeen-turn hole (BUG-908).

        Returns ``("", [])`` when there is nothing stored or Postgres is unavailable.
        """
        if not self.pool:
            return "", []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT turn_index,
                           LEFT(user_query, 160)     AS user_query,
                           LEFT(intent, 40)          AS intent,
                           LEFT(result_summary, 300) AS result_summary
                    FROM turn_memory
                    WHERE conversation_id = $1
                    ORDER BY turn_index DESC
                    LIMIT $2
                    """,
                    conversation_id,
                    _MAX_OLDER_SCAN,
                )
            if not rows:
                return "", []
            # Oldest-first, which is what `session_summary.build` documents it requires.
            notes = [session_summary.note_from_row(r) for r in reversed(rows)]
            # The summary's own window. `LIMIT` above is the retention cap, so this slice
            # can never drop a row the old `OFFSET skip_recent` would have kept.
            skip = max(0, int(skip_recent))
            older = notes[: len(notes) - skip] if skip else notes
            return (session_summary.build(older) if older else ""), notes
        except Exception as e:
            logger.warning(f"[turn_memory] get_session_context failed (non-fatal): {e}")
        return "", []

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
                result = await conn.execute(f"DELETE FROM turn_memory WHERE {column} = $1", value)
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
        return {k: v for k, v in state.intermediate_results.items() if k in _CARRY_FORWARD_KEYS}
