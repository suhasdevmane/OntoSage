"""Read the actuation audit trail back (2026-08-27).

``SimDriver.set_point()`` writes a row to ``actuation_log`` for every approved
setpoint change: who asked, which point, what value, why, and when. bldg1 ships
with ``actuation.driver: sim`` and three writable points, so the path is live on
the shipped building — and until now nothing in the system ever read a single row
back. "What did you change today?" and "who approved that?" were unanswerable
about actions this system had itself recorded.

Sixth instance of the same pattern in this codebase: a capability that is
present, correct, tested, and has no invoker (lessons.md #87). Found by
``scripts/audit_unread_stores.py``, which asks the mechanical question — for
every kind of data stored, where is the code that reads it back — of the
relational stores the way the earlier audit asked it of the graph.

Read-only by construction. Nothing here writes, deletes, or amends an audit row;
an audit trail that its own reader can edit is not an audit trail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: Newest first, and always bounded — an audit trail grows without limit.
_SELECT_SQL = """
SELECT audit_id, building_id, user_id, point_uri, value, reason, status, created_at
FROM actuation_log
WHERE building_id = $1
ORDER BY created_at DESC
LIMIT $2
"""

_SELECT_SINCE_SQL = """
SELECT audit_id, building_id, user_id, point_uri, value, reason, status, created_at
FROM actuation_log
WHERE building_id = $1 AND created_at >= NOW() - ($2 || ' hours')::interval
ORDER BY created_at DESC
LIMIT $3
"""

_MAX_LIMIT = 500


async def read_actuation_log(
    building_id: str,
    *,
    postgres_manager: Any = None,
    limit: int = 50,
    since_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Return recent actuation audit rows for a building.

    Args:
        building_id: the building whose trail to read — never cross-building.
        postgres_manager: object with a ``.pool`` attribute (asyncpg pool).
        limit: maximum rows, capped at 500.
        since_hours: restrict to the last N hours, if given.

    Returns a dict with ``ok``, ``actions`` and ``count``. A missing table means
    nothing has ever been actuated, which is not an error: it reports zero
    actions and says so, rather than raising at a caller that only wanted to
    know whether anything happened.
    """
    n = max(1, min(int(limit or 50), _MAX_LIMIT))
    out: Dict[str, Any] = {
        "ok": True,
        "building_id": building_id,
        "actions": [],
        "count": 0,
        "window_hours": since_hours,
    }

    pool = getattr(postgres_manager, "pool", None) if postgres_manager is not None else None
    if pool is None:
        out["ok"] = False
        out["error"] = "no database connection — the actuation trail cannot be read"
        return out

    try:
        async with pool.acquire() as conn:
            if since_hours is not None:
                rows = await conn.fetch(_SELECT_SINCE_SQL, building_id, str(since_hours), n)
            else:
                rows = await conn.fetch(_SELECT_SQL, building_id, n)
    except Exception as exc:
        # An absent table is the ordinary state of a building that has never
        # actuated anything; anything else is worth surfacing.
        if "actuation_log" in str(exc) and "exist" in str(exc).lower():
            logger.info("[actuation_audit] no actuation_log table yet — nothing recorded")
            return out
        logger.warning(f"[actuation_audit] read failed: {exc}")
        out["ok"] = False
        out["error"] = str(exc)
        return out

    out["actions"] = [_as_action(r) for r in rows]
    out["count"] = len(out["actions"])
    return out


def _as_action(row: Any) -> Dict[str, Any]:
    """One audit row as a plain dict, with the timestamp made printable."""
    d = dict(row)
    created = d.get("created_at")
    d["created_at"] = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
    return d


def format_actions(result: Dict[str, Any], *, max_lines: int = 10) -> str:
    """A human-readable rendering of :func:`read_actuation_log`'s result.

    Says what it truncated. A list that silently stops reads as the whole answer,
    which for an audit trail is the worst possible way to be wrong.
    """
    if not result.get("ok"):
        return f"The record of control actions could not be read: {result.get('error', 'unknown')}."

    actions: List[Dict[str, Any]] = result.get("actions") or []
    if not actions:
        window = result.get("window_hours")
        when = f" in the last {window:g} hours" if window else ""
        return f"No control actions have been recorded for this building{when}."

    lines = []
    for a in actions[:max_lines]:
        reason = f" — {a['reason']}" if a.get("reason") else ""
        lines.append(
            f"- {a.get('created_at', '')}: {a.get('point_uri')} set to "
            f"{a.get('value')} by {a.get('user_id')} [{a.get('status')}]{reason}"
        )
    if len(actions) > max_lines:
        lines.append(f"- …and {len(actions) - max_lines} more")
    return f"**{len(actions)} control action(s) recorded:**\n" + "\n".join(lines)
