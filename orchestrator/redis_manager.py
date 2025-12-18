"""
Redis Manager for OntoSage 2.0
Handles conversation state persistence
"""
import sys
sys.path.append('/app')

import json
import redis.asyncio as redis
from typing import Optional, Dict, Any, List
from datetime import datetime

from shared.config import settings
from shared.models import ConversationState, Message
from shared.utils import get_logger, generate_conversation_id

logger = get_logger(__name__)

class RedisManager:
    """Manages conversation state in Redis"""
    
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self.client: Optional[redis.Redis] = None
        self.conversation_ttl = settings.CONVERSATION_TTL
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self.client.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def close(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            logger.info("Closed Redis connection")
    
    async def save_state(self, state: ConversationState) -> bool:
        """
        Save conversation state to Redis
        
        Args:
            state: ConversationState object
            
        Returns:
            Success boolean
        """
        if not self.client:
            await self.connect()
        
        try:
            key = f"conversation:{state.conversation_id}"
            
            # Convert to dict for storage
            state_dict = state.dict()
            
            # Log what we're saving
            logger.info(f"💾 REDIS SAVE: conversation_id={state.conversation_id}")
            logger.info(f"   ├─ Messages count: {len(state.messages)}")
            logger.info(f"   ├─ User: {state.user_id}")
            logger.info(f"   ├─ Intermediate results keys: {list(state.intermediate_results.keys()) if state.intermediate_results else 'None'}")
            logger.info(f"   └─ TTL: {self.conversation_ttl}s")
            
            # Store as JSON
            await self.client.setex(
                key,
                self.conversation_ttl,
                json.dumps(state_dict, default=str)
            )
            
            logger.info(f"✅ Successfully saved state for {state.conversation_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save state: {e}")
            return False
    
    async def load_state(self, conversation_id: str) -> Optional[ConversationState]:
        """
        Load conversation state from Redis
        
        Args:
            conversation_id: Conversation ID
            
        Returns:
            ConversationState or None if not found
        """
        if not self.client:
            await self.connect()
        
        try:
            key = f"conversation:{conversation_id}"
            logger.info(f"📂 REDIS LOAD: Attempting to load {conversation_id}")
            
            state_json = await self.client.get(key)
            
            if state_json:
                state_dict = json.loads(state_json)
                state = ConversationState(**state_dict)
                logger.info(f"✅ REDIS LOAD SUCCESS:")
                logger.info(f"   ├─ conversation_id: {conversation_id}")
                logger.info(f"   ├─ Messages count: {len(state.messages)}")
                logger.info(f"   ├─ User: {state.user_id}")
                if state.messages:
                    logger.info(f"   ├─ Last 3 messages:")
                    for i, msg in enumerate(state.messages[-3:]):
                        logger.info(f"   │   [{i+1}] {msg.role}: {msg.content[:60]}...")
                logger.info(f"   └─ Intermediate results: {list(state.intermediate_results.keys()) if state.intermediate_results else 'None'}")
                return state
            else:
                logger.info(f"🆕 REDIS LOAD: No state found for {conversation_id} (new conversation)")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to load state: {e}")
            return None
    
    async def delete_state(self, conversation_id: str) -> bool:
        """Delete conversation state"""
        if not self.client:
            await self.connect()
        
        try:
            key = f"conversation:{conversation_id}"
            await self.client.delete(key)
            logger.debug(f"Deleted state for {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete state: {e}")
            return False
    
    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Save a message to conversation history
        
        Args:
            conversation_id: Conversation ID
            role: Message role (user/assistant/system)
            content: Message content
            metadata: Optional metadata
        """
        if not self.client:
            await self.connect()
        
        try:
            key = f"messages:{conversation_id}"
            
            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": metadata or {}
            }
            
            # Add to list
            await self.client.rpush(key, json.dumps(message))
            
            # Set TTL
            await self.client.expire(key, self.conversation_ttl)
            
            # Trim to max history
            await self.client.ltrim(
                key,
                -settings.MAX_CONVERSATION_HISTORY,
                -1
            )
            
            logger.debug(f"Saved message to {conversation_id}")
            
        except Exception as e:
            logger.error(f"Failed to save message: {e}")
    
    async def get_messages(self, conversation_id: str) -> list:
        """
        Get conversation message history
        
        Args:
            conversation_id: Conversation ID
            
        Returns:
            List of Message objects
        """
        if not self.client:
            await self.connect()
        
        try:
            key = f"messages:{conversation_id}"
            messages_json = await self.client.lrange(key, 0, -1)
            
            messages = []
            for msg_json in messages_json:
                msg_dict = json.loads(msg_json)
                messages.append(Message(**msg_dict))
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []
    
    async def save_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any]
    ):
        """
        Save user preferences
        
        Args:
            user_id: User ID
            preferences: Preferences dict
        """
        if not self.client:
            await self.connect()
        
        try:
            key = f"user:prefs:{user_id}"
            await self.client.setex(
                key,
                86400 * 30,  # 30 days
                json.dumps(preferences)
            )
            logger.debug(f"Saved preferences for {user_id}")
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
    
    async def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences"""
        if not self.client:
            await self.connect()
        
        try:
            key = f"user:prefs:{user_id}"
            prefs_json = await self.client.get(key)
            
            if prefs_json:
                return json.loads(prefs_json)
            else:
                # Default preferences
                return {
                    "persona": "guest",
                    "language": "en",
                    "building_id": settings.BUILDING_ID
                }
        except Exception as e:
            logger.error(f"Failed to get preferences: {e}")
            return {}
    
    async def cache_sparql_result(
        self,
        query: str,
        result: Any,
        ttl: int = 3600
    ):
        """
        Cache SPARQL query result
        
        Args:
            query: SPARQL query string
            result: Query result
            ttl: Cache TTL in seconds
        """
        if not self.client:
            await self.connect()
        
        try:
            from shared.utils import generate_hash
            query_hash = generate_hash(query)
            key = f"cache:sparql:{query_hash}"
            
            await self.client.setex(
                key,
                ttl,
                json.dumps(result, default=str)
            )
            logger.debug(f"Cached SPARQL result: {query_hash}")
        except Exception as e:
            logger.error(f"Failed to cache result: {e}")
    
    async def get_cached_sparql_result(self, query: str) -> Optional[Any]:
        """Get cached SPARQL result"""
        if not self.client:
            await self.connect()
        
        try:
            from shared.utils import generate_hash
            query_hash = generate_hash(query)
            key = f"cache:sparql:{query_hash}"
            
            result_json = await self.client.get(key)
            if result_json:
                logger.debug(f"Cache hit: {query_hash}")
                return json.loads(result_json)
            else:
                logger.debug(f"Cache miss: {query_hash}")
                return None
        except Exception as e:
            logger.error(f"Failed to get cached result: {e}")
            return None

    async def get_cache(self, key: str) -> Optional[Any]:
        """
        Get value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        if not self.client:
            await self.connect()
            
        try:
            value = await self.client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Failed to get cache for key {key}: {e}")
            return None

    async def set_cache(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """
        Set value in cache
        
        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds
            
        Returns:
            Success boolean
        """
        if not self.client:
            await self.connect()
            
        try:
            await self.client.setex(
                key,
                ttl,
                json.dumps(value, default=str)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache for key {key}: {e}")
            return False

    async def add_conversation_to_user(self, user_id: str, conversation_id: str, title: str):
        """Add conversation to user's list"""
        if not self.client:
            await self.connect()
        
        try:
            # Add to user's set
            await self.client.sadd(f"user:{user_id}:conversations", conversation_id)
            
            # Store metadata
            meta = {
                "title": title,
                "updated_at": datetime.utcnow().isoformat()
            }
            await self.client.hset(f"conversation:{conversation_id}:meta", mapping=meta)
            
        except Exception as e:
            logger.error(f"Failed to add conversation to user list: {e}")

    async def get_user_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get list of conversations for user"""
        if not self.client:
            await self.connect()
            
        try:
            conv_ids = await self.client.smembers(f"user:{user_id}:conversations")
            conversations = []
            
            for cid in conv_ids:
                meta = await self.client.hgetall(f"conversation:{cid}:meta")
                if meta:
                    conversations.append({
                        "conversation_id": cid,
                        "title": meta.get("title", "Untitled"),
                        "updated_at": meta.get("updated_at")
                    })
                else:
                    # Fallback if meta missing
                    conversations.append({
                        "conversation_id": cid,
                        "title": "Untitled",
                        "updated_at": None
                    })
            
            # Sort by updated_at desc
            conversations.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
            return conversations
            
        except Exception as e:
            logger.error(f"Failed to get user conversations: {e}")
            return []

# Global instance
redis_manager = RedisManager()
