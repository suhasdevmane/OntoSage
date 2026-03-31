"""
PostgreSQL Manager for OntoSage 2.0
Handles user data and chat history persistence in PostgreSQL
"""
import sys
sys.path.append('/app')

import json
import asyncpg
from typing import Optional, Dict, Any, List
from datetime import datetime
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
        self.host = "postgres-user-data" # Service name in docker-compose
        self.port = 5432
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initialize database connection pool and schema"""
        try:
            dsn = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    salt VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """)
            
            # Conversations table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) REFERENCES users(username),
                    title VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """)
            
            # Messages table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(255) REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """)
            logger.info("PostgreSQL schema initialized")

    # ==================== User Operations ====================

    async def create_user(self, username: str, password_hash: str, salt: str, email: str = None, metadata: dict = None) -> bool:
        if not self.pool: return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (username, password_hash, salt, email, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, username, password_hash, salt, email, json.dumps(metadata or {}), datetime.now())
                return True
        except asyncpg.UniqueViolationError:
            logger.warning(f"User {username} already exists")
            return False
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        if not self.pool: return None
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
        if not self.pool: return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("UPDATE users SET last_login = $1 WHERE username = $2", datetime.now(), username)
        except Exception as e:
            logger.error(f"Error updating last login: {e}")

    # ==================== History Operations ====================

    async def create_conversation(self, conversation_id: str, username: str, title: str = "New Chat"):
        if not self.pool: return
        try:
            async with self.pool.acquire() as conn:
                # Check if user exists first (foreign key constraint)
                user = await self.get_user(username)
                if not user:
                    logger.warning(f"Cannot create conversation for non-existent user: {username}")
                    return

                await conn.execute("""
                    INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (id) DO NOTHING
                """, conversation_id, username, title, datetime.now(), datetime.now())
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")

    async def save_message(self, conversation_id: str, role: str, content: str, username: str = None):
        if not self.pool: return
        try:
            async with self.pool.acquire() as conn:
                # Ensure conversation exists
                if username:
                    await self.create_conversation(conversation_id, username)
                
                await conn.execute("""
                    INSERT INTO messages (conversation_id, role, content, timestamp)
                    VALUES ($1, $2, $3, $4)
                """, conversation_id, role, content, datetime.now())
                
                # Update conversation timestamp
                await conn.execute("""
                    UPDATE conversations SET updated_at = $1 WHERE id = $2
                """, datetime.now(), conversation_id)
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    async def get_user_conversations(self, username: str) -> List[Dict[str, Any]]:
        if not self.pool: return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM conversations 
                    WHERE user_id = $1 
                    ORDER BY updated_at DESC
                """, username)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting conversations: {e}")
            return []

    async def get_conversation_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        if not self.pool: return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM messages 
                    WHERE conversation_id = $1 
                    ORDER BY timestamp ASC
                """, conversation_id)
                
                # Convert to list of dicts and format timestamp
                messages = []
                for row in rows:
                    msg = dict(row)
                    msg['timestamp'] = msg['timestamp'].isoformat() if msg['timestamp'] else None
                    messages.append(msg)
                return messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    async def clear_user_history(self, username: str) -> bool:
        if not self.pool: return False
        try:
            async with self.pool.acquire() as conn:
                # Delete all conversations for user (messages will cascade delete)
                await conn.execute("DELETE FROM conversations WHERE user_id = $1", username)
                return True
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            return False
