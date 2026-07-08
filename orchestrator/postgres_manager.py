"""
PostgreSQL Manager for OntoSage 2.0
Handles user data and chat history persistence in PostgreSQL
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


class PostgresManager:
    """Manages user data and chat history in PostgreSQL"""

    def __init__(self):
        # Use the postgres-user-data service credentials
        self.user = settings.POSTGRES_USER_USER or "ontobot"
        self.password = settings.POSTGRES_USER_PASSWORD or "ontobot_secret"
        self.database = settings.POSTGRES_USER_DB or "ontobot"
        self.host = "postgres-user-data"  # Service name in docker-compose
        self.port = 5432
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initialize database connection pool and schema"""
        try:
            dsn = (
                f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            )
            self.pool = await asyncpg.create_pool(dsn)
            logger.info(f"Connected to PostgreSQL: {self.host}/{self.database}")

            await self._init_schema()

        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            # Don't raise here to allow app to start even if DB is down (optional)
            # raise e

    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Closed PostgreSQL connection")

    async def _init_schema(self):
        """Initialize database tables"""
        if not self.pool:
            return

        async with self.pool.acquire() as conn:
            # Users table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    salt VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    role VARCHAR(50) NOT NULL DEFAULT 'facility_manager',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """
            )
            # Migration: backfill role column on deployments created before RBAC
            # enforcement. Existing users default to facility_manager (broad
            # read/write, no system:admin) so authenticated flows keep working.
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS role "
                "VARCHAR(50) NOT NULL DEFAULT 'facility_manager';"
            )

            # Conversations table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) REFERENCES users(username),
                    title VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """
            )

            # Messages table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(255) REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """
            )

            # Turn memory table — one row per conversation turn.
            # Stores a structured summary (no raw sensor arrays) for long-term
            # context injection and cross-turn carry-forward artifacts.
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_memory (
                    id              SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(255) NOT NULL,
                    user_id         VARCHAR(255),
                    turn_index      INTEGER NOT NULL DEFAULT 0,
                    user_query      TEXT NOT NULL,
                    intent          VARCHAR(100),
                    entities        JSONB    DEFAULT '[]'::jsonb,
                    result_summary  TEXT,
                    carry_forward   JSONB    DEFAULT '{}'::jsonb,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_turn_memory_conv
                ON turn_memory(conversation_id, turn_index DESC);
            """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_turn_memory_user
                ON turn_memory(user_id);
            """
            )

            # Admin audit log — one row per mutating admin-console action (who did
            # what, when, and the outcome). Populated by the audit middleware.
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_log (
                    id        BIGSERIAL PRIMARY KEY,
                    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
                    username  VARCHAR(255),
                    role      VARCHAR(50),
                    method    VARCHAR(10) NOT NULL,
                    path      TEXT NOT NULL,
                    status    INTEGER,
                    trace_id  VARCHAR(64)
                );
            """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_audit_ts
                ON admin_audit_log(ts DESC);
            """
            )
            logger.info("PostgreSQL schema initialized")

    # ==================== User Operations ====================

    async def create_user(
        self,
        username: str,
        password_hash: str,
        salt: str,
        email: str = None,
        metadata: dict = None,
        role: str = "facility_manager",
    ) -> bool:
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, email, role, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    username,
                    password_hash,
                    salt,
                    email,
                    role,
                    json.dumps(metadata or {}),
                    datetime.now(),
                )
                return True
        except asyncpg.UniqueViolationError:
            logger.warning(f"User {username} already exists")
            return False
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    async def update_last_login(self, username: str):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET last_login = $1 WHERE username = $2", datetime.now(), username
                )
        except Exception as e:
            logger.error(f"Error updating last login: {e}")

    async def list_users(self) -> List[Dict[str, Any]]:
        """Return all users (no secrets) for the admin console."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT username, role, email, created_at, last_login "
                    "FROM users ORDER BY username"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []

    async def update_user_role(self, username: str, role: str) -> bool:
        """Change a user's role. Returns True if a row was updated."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE users SET role = $1 WHERE username = $2", role, username
                )
            return result.endswith("1")
        except Exception as e:
            logger.error(f"Error updating user role: {e}")
            return False

    async def update_user_metadata(self, username: str, metadata: Dict[str, Any]) -> bool:
        """Merge-update the metadata JSON column for a user. Returns True if a row was updated."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE users SET metadata = $1 WHERE username = $2",
                    json.dumps(metadata),
                    username,
                )
            return result.endswith("1")
        except Exception as e:
            logger.error(f"Error updating user metadata: {e}")
            return False

    async def delete_user(self, username: str) -> bool:
        """Delete a user and ALL their per-user data (turn_memory + conversations,
        which cascades to messages) in one transaction — GDPR right-to-be-forgotten.

        This also fixes a latent bug: ``conversations.user_id`` REFERENCES
        ``users(username)`` with NO ``ON DELETE CASCADE``, so deleting a user who
        ever had a conversation previously failed on the foreign key. Returns True
        if the user row was removed.
        """
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # turn_memory has no FK cascade from users — purge it explicitly.
                    await conn.execute("DELETE FROM turn_memory WHERE user_id = $1", username)
                    # conversations block the users delete (FK, no cascade); removing
                    # them cascades to messages via their own ON DELETE CASCADE.
                    await conn.execute("DELETE FROM conversations WHERE user_id = $1", username)
                    result = await conn.execute("DELETE FROM users WHERE username = $1", username)
            return result.endswith("1")
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False

    # ==================== History Operations ====================

    async def create_conversation(
        self, conversation_id: str, username: str, title: str = "New Chat"
    ):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                # Check if user exists first (foreign key constraint)
                user = await self.get_user(username)
                if not user:
                    logger.warning(f"Cannot create conversation for non-existent user: {username}")
                    return

                await conn.execute(
                    """
                    INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (id) DO NOTHING
                """,
                    conversation_id,
                    username,
                    title,
                    datetime.now(),
                    datetime.now(),
                )
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")

    async def save_message(
        self, conversation_id: str, role: str, content: str, username: str = None
    ):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                # Ensure conversation exists
                if username:
                    await self.create_conversation(conversation_id, username)

                await conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, timestamp)
                    VALUES ($1, $2, $3, $4)
                """,
                    conversation_id,
                    role,
                    content,
                    datetime.now(),
                )

                # Update conversation timestamp
                await conn.execute(
                    """
                    UPDATE conversations SET updated_at = $1 WHERE id = $2
                """,
                    datetime.now(),
                    conversation_id,
                )
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    async def get_user_conversations(self, username: str) -> List[Dict[str, Any]]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM conversations 
                    WHERE user_id = $1 
                    ORDER BY updated_at DESC
                """,
                    username,
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting conversations: {e}")
            return []

    async def get_conversation_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM messages 
                    WHERE conversation_id = $1 
                    ORDER BY timestamp ASC
                """,
                    conversation_id,
                )

                # Convert to list of dicts and format timestamp
                messages = []
                for row in rows:
                    msg = dict(row)
                    msg["timestamp"] = msg["timestamp"].isoformat() if msg["timestamp"] else None
                    messages.append(msg)
                return messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    async def clear_user_history(self, username: str) -> bool:
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                # Delete all conversations for user (messages will cascade delete)
                await conn.execute("DELETE FROM conversations WHERE user_id = $1", username)
                return True
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            return False

    # ==================== Admin Audit Log ====================

    async def record_admin_action(
        self,
        username: Optional[str],
        role: Optional[str],
        method: str,
        path: str,
        status: int,
        trace_id: Optional[str] = None,
    ) -> bool:
        """Append one admin-action audit row. Never raises (audit must not break a request)."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO admin_audit_log (username, role, method, path, status, trace_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    username,
                    role,
                    method,
                    path,
                    status,
                    trace_id,
                )
            return True
        except Exception as e:
            logger.error(f"Error recording admin audit action: {e}")
            return False

    async def get_admin_audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent admin-action audit rows (newest first)."""
        if not self.pool:
            return []
        limit = max(1, min(int(limit), 1000))
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ts, username, role, method, path, status, trace_id
                    FROM admin_audit_log ORDER BY ts DESC LIMIT $1
                    """,
                    limit,
                )
                out: List[Dict[str, Any]] = []
                for row in rows:
                    d = dict(row)
                    d["ts"] = d["ts"].isoformat() if d.get("ts") else None
                    out.append(d)
                return out
        except Exception as e:
            logger.error(f"Error reading admin audit log: {e}")
            return []
