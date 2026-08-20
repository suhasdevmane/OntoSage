"""sim_driver.py — Simulation actuation driver (T23).

Logs every set_point() call to Postgres actuation_log and returns success.
Never touches any physical BMS endpoint — safe for demo and testing.

Table schema (auto-created on first use):
    actuation_log (
        id          SERIAL PRIMARY KEY,
        audit_id    UUID NOT NULL DEFAULT gen_random_uuid(),
        building_id TEXT NOT NULL,
        user_id     TEXT NOT NULL DEFAULT 'system',
        point_uri   TEXT NOT NULL,
        value       TEXT NOT NULL,
        reason      TEXT,
        status      TEXT NOT NULL DEFAULT 'sim_ok',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
"""

from __future__ import annotations

import uuid as _uuid_mod
from typing import Any, List, Optional

from orchestrator.services.actuation.base import ActuationDriver, ActuationResult
from shared.utils import get_logger

logger = get_logger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS actuation_log (
    id          SERIAL PRIMARY KEY,
    audit_id    TEXT NOT NULL,
    building_id TEXT NOT NULL,
    user_id     TEXT NOT NULL DEFAULT 'system',
    point_uri   TEXT NOT NULL,
    value       TEXT NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'sim_ok',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_actlog_building ON actuation_log (building_id, created_at DESC);
"""

_INSERT_SQL = """
INSERT INTO actuation_log
    (audit_id, building_id, user_id, point_uri, value, reason, status)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING audit_id;
"""


class SimDriver(ActuationDriver):
    """Simulation driver — logs to Postgres, never actuates physically.

    Writable points are declared in building.yaml under actuation.points_writable.
    Any point NOT in that list is rejected with success=False.

    Args:
        postgres_manager: Optional object with a .pool attribute (asyncpg pool).
            Injected by the orchestrator at runtime; tests can pass a mock directly.
            When None the driver still succeeds but skips DB persistence.
    """

    def __init__(
        self,
        building_id: str,
        writable_points: List[str],
        postgres_manager: Optional[Any] = None,
    ) -> None:
        self._building_id = building_id
        self._writable: set = set(writable_points)
        self._postgres = postgres_manager
        self._table_ensured = False

    async def _ensure_table(self) -> None:
        if self._table_ensured or self._postgres is None:
            return
        try:
            pool = self._postgres.pool
            if pool is None:
                return
            async with pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
            self._table_ensured = True
        except Exception as exc:
            logger.warning(f"[SimDriver] Could not ensure actuation_log table: {exc}")

    async def capabilities(self) -> List[str]:
        return sorted(self._writable)

    async def set_point(
        self,
        point_uri: str,
        value: Any,
        *,
        user_id: str = "system",
        reason: str = "",
    ) -> ActuationResult:
        """Log the would-be actuation to Postgres and return success."""
        if point_uri not in self._writable:
            logger.warning(
                f"[SimDriver] Rejected set_point on unknown/non-writable point: {point_uri}"
            )
            return ActuationResult(
                success=False,
                point_uri=point_uri,
                value=value,
                error=(
                    f"Point '{point_uri}' is not in the writable points list "
                    f"for {self._building_id}"
                ),
            )

        audit_id = str(_uuid_mod.uuid4())
        recorded_audit_id = audit_id
        await self._ensure_table()

        if self._postgres is not None:
            try:
                pool = self._postgres.pool
                if pool is not None:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            _INSERT_SQL,
                            audit_id,
                            self._building_id,
                            user_id,
                            point_uri,
                            str(value),
                            reason or None,
                            "sim_ok",
                        )
                    if row:
                        recorded_audit_id = row["audit_id"]
            except Exception as exc:
                logger.warning(f"[SimDriver] DB write failed, continuing: {exc}")
                # Sim mode is resilient — DB failure does NOT block success

        logger.info(
            f"[SimDriver] SIM set_point: building={self._building_id} "
            f"point={point_uri} value={value} user={user_id} audit={recorded_audit_id}"
        )
        return ActuationResult(
            success=True,
            point_uri=point_uri,
            value=value,
            audit_id=recorded_audit_id,
            message=f"[SIM] Would set {point_uri} = {value}. Audit id: {recorded_audit_id}",
        )
