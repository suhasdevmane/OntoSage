#!/usr/bin/env python3
"""Create (or promote) an OntoSage admin user for the admin console.

There is no seeded admin account and /auth/register only creates
``facility_manager`` users — which can toggle data sources but cannot use the
Settings (.env) or Databases tabs (those need the ``admin`` role / system:admin).
This helper creates an ``admin``-role user, or promotes an existing user to admin.

Run inside the orchestrator container (it has Redis/Postgres on the network):

    docker exec ontosage-orchestrator \
        python /app/orchestrator/create_admin.py <username> <password> [email]

Then sign in at http://127.0.0.1:3001 with those credentials.
"""

from __future__ import annotations

import asyncio
import sys

from orchestrator.auth_manager import AuthManager
from orchestrator.postgres_manager import PostgresManager
from orchestrator.redis_manager import RedisManager


async def _promote_existing(pg: PostgresManager, username: str) -> bool:
    """Set an existing user's role to admin. Returns True on success."""
    pool = getattr(pg, "pool", None)
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET role = 'admin' WHERE username = $1", username
            )
        # asyncpg returns e.g. "UPDATE 1"
        return result.endswith("1")
    except Exception as e:  # pragma: no cover - operational helper
        print(f"  promote failed: {e}")
        return False


async def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python -m orchestrator.create_admin <username> <password> [email]")
        return 2
    username, password = sys.argv[1], sys.argv[2]
    email = sys.argv[3] if len(sys.argv) > 3 else None

    redis = RedisManager()
    await redis.connect()
    pg = PostgresManager()
    await pg.connect()
    auth = AuthManager(redis, pg)

    try:
        result = await auth.register_user(username, password, email, role="admin")
        if result.get("success"):
            print(f"✓ created admin user '{username}' (role=admin)")
            return 0
        # register said no — most likely the username already exists → promote it
        print(f"register: {result.get('error')} — attempting to promote to admin…")
        if await _promote_existing(pg, username):
            print(f"✓ promoted existing user '{username}' to role=admin")
            return 0
        print(f"✗ could not create or promote '{username}'")
        return 1
    except ValueError as e:
        # register_user raises on duplicate / invalid input
        print(f"register raised: {e} — attempting to promote to admin…")
        if await _promote_existing(pg, username):
            print(f"✓ promoted existing user '{username}' to role=admin")
            return 0
        return 1
    finally:
        try:
            await redis.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
