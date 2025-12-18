"""
OntoSage 2.0 Orchestrator - Main FastAPI Application
"""
import sys
sys.path.append('/app')

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, Cookie, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime
import json
import os

from shared.models import ConversationState, Message, APIResponse
from shared.utils import get_logger, generate_conversation_id
from shared.config import settings

from orchestrator.redis_manager import RedisManager
from orchestrator.postgres_manager import PostgresManager
from orchestrator.workflow import WorkflowOrchestrator
from orchestrator.auth_manager import AuthManager

logger = get_logger(__name__)

# Initialize components
redis_manager: RedisManager = None
postgres_manager: PostgresManager = None
orchestrator: WorkflowOrchestrator = None
auth_manager: AuthManager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown"""
    global redis_manager, postgres_manager, orchestrator, auth_manager
    
    # Startup
    logger.info("Starting OntoSage 2.0 Orchestrator...")
    
    # Initialize Redis
    redis_manager = RedisManager()
    await redis_manager.connect()
    logger.info("Redis connected")
    
    # Initialize Postgres
    postgres_manager = PostgresManager()
    await postgres_manager.connect()
    logger.info("Postgres connected")
    
    # Initialize authentication manager
    auth_manager = AuthManager(redis_manager, postgres_manager)
    logger.info("Auth manager initialized")
    
    # Initialize workflow with redis_manager reference
    orchestrator = WorkflowOrchestrator(redis_manager=redis_manager, postgres_manager=postgres_manager)
    logger.info("Workflow orchestrator initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down OntoSage 2.0 Orchestrator...")
    await redis_manager.close()
    await postgres_manager.close()

# Create FastAPI app
app = FastAPI(
    title="OntoSage 2.0 Orchestrator",
    description="Agentic AI orchestration for intelligent building queries",
    version="2.0.0",
    lifespan=lifespan
)

# Ensure outputs directory exists
os.makedirs("/app/outputs", exist_ok=True)

# Mount static files for serving plots and data
app.mount("/static", StaticFiles(directory="/app/outputs"), name="static")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_model=APIResponse)
async def root():
    """Root endpoint"""
    return APIResponse(
        success=True,
        data={
            "service": "OntoSage 2.0 Orchestrator",
            "version": "2.0.0",
            "status": "running"
        }
    )

@app.get("/health", response_model=APIResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Check Redis connection
        await redis_manager.connect()
        
        return APIResponse(
            success=True,
            data={
                "status": "healthy",
                "redis": "connected",
                "orchestrator": "ready"
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return APIResponse(
            success=False,
            error=str(e),
            data={
                "status": "unhealthy"
            }
        )

@app.get("/conversations/{user_id}", response_model=APIResponse)
async def get_conversations(user_id: str):
    """Get list of conversations for a user"""
    try:
        conversations = []
        
        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            conversations = await postgres_manager.get_user_conversations(user_id)
        
        # Fallback to Redis if empty or not available
        if not conversations and redis_manager:
            conversations = await redis_manager.get_user_conversations(user_id)
            
        return APIResponse(
            success=True,
            data={"conversations": conversations}
        )
    except Exception as e:
        logger.error(f"Failed to get conversations: {e}")
        return APIResponse(
            success=False,
            error=str(e)
        )

@app.get("/conversations/{conversation_id}/messages", response_model=APIResponse)
async def get_conversation_messages(conversation_id: str):
    """Get messages for a specific conversation"""
    try:
        messages = []
        
        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            messages = await postgres_manager.get_conversation_messages(conversation_id)
        
        # Fallback to Redis if empty or not available
        if not messages and redis_manager:
            messages = await redis_manager.get_messages(conversation_id)
            
        return APIResponse(
            success=True,
            data={"messages": messages}
        )
    except Exception as e:
        logger.error(f"Failed to get messages for {conversation_id}: {e}")
        return APIResponse(
            success=False,
            error=str(e)
        )

# Authentication helper
async def get_current_user(
    session_token: Optional[str] = Cookie(None, alias="session_token"),
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> Optional[str]:
    """
    Get current user from session token (cookie or header)
    
    Returns username or None
    """
    # Try cookie first
    if session_token:
        username = await auth_manager.validate_session(session_token)
        if username:
            return username
    
    # Try Authorization header
    if authorization:
        # Handle both "Bearer token" and raw token formats
        if isinstance(authorization, str) and authorization.startswith("Bearer "):
            token = authorization.replace("Bearer ", "").strip()
        elif isinstance(authorization, str):
            token = authorization.strip()
        else:
            token = str(authorization).strip()
        
        if token:
            username = await auth_manager.validate_session(token)
            if username:
                return username
    
    return None


# ==================== Authentication Endpoints ====================

@app.post("/auth/register", response_model=APIResponse)
async def register_user(request: Dict[str, Any]):
    """
    Register a new user
    
    Request:
        {
            "username": "user123",
            "password": "password",
            "email": "user@example.com" (optional)
        }
    """
    try:
        username = request.get("username")
        password = request.get("password")
        email = request.get("email")
        
        if not username or not password:
            return APIResponse(success=False, error="Username and password required")
        
        result = await auth_manager.register_user(username, password, email)
        
        if not result["success"]:
            return APIResponse(success=False, error=result["error"])
        
        return APIResponse(success=True, data=result)
        
    except Exception as e:
        logger.error(f"Registration endpoint error: {e}", exc_info=True)
        return APIResponse(success=False, error="Registration failed")


@app.post("/auth/login", response_model=APIResponse)
async def login_user(request: Dict[str, Any]):
    """
    Login user and create session
    
    Request:
        {
            "username": "user123",
            "password": "password"
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "username": "user123",
                "session_token": "...",
                "expires_in": 604800
            }
        }
    """
    try:
        username = request.get("username")
        password = request.get("password")
        
        if not username or not password:
            return APIResponse(success=False, error="Username and password required")
        
        result = await auth_manager.login_user(username, password)
        
        if not result["success"]:
            return APIResponse(success=False, error=result["error"])
        
        # Set session cookie
        response_data = APIResponse(success=True, data=result).dict()
        response = JSONResponse(content=response_data)
        response.set_cookie(
            key="session_token",
            value=result["session_token"],
            max_age=result["expires_in"],
            httponly=True,
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Login endpoint error: {e}", exc_info=True)
        return APIResponse(success=False, error="Login failed")


@app.post("/auth/logout", response_model=APIResponse)
async def logout_user(
    current_user: Optional[str] = Depends(get_current_user),
    session_token: str = Cookie(None, alias="session_token"),
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """Logout user and invalidate session"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")
        
        # Get the actual token from cookie or header
        token = session_token
        if not token and authorization:
            if isinstance(authorization, str) and authorization.startswith("Bearer "):
                token = authorization.replace("Bearer ", "").strip()
            elif isinstance(authorization, str):
                token = authorization.strip()
        
        if not token:
            return APIResponse(success=False, error="No active session")
        
        result = await auth_manager.logout_user(token)
        
        response_data = APIResponse(success=True, data=result).dict()
        response = JSONResponse(content=response_data)
        response.delete_cookie("session_token")
        
        return response
        
    except Exception as e:
        logger.error(f"Logout endpoint error: {e}")
        return APIResponse(success=False, error="Logout failed")
        raise HTTPException(status_code=500, detail="Logout failed")


@app.get("/auth/me", response_model=APIResponse)
async def get_current_user_info(
    current_user: Optional[str] = Depends(get_current_user)
):
    """Get current authenticated user info"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")
        
        user_info = await auth_manager.get_user_info(current_user)
        
        if not user_info:
            return APIResponse(success=False, error="User not found")
        
        return APIResponse(success=True, data=user_info)
        
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        return APIResponse(success=False, error="Failed to get user info")


# ==================== Chat History Endpoints ====================

@app.get("/history/{username}", response_model=APIResponse)
async def get_user_history(
    username: str,
    current_user: Optional[str] = Depends(get_current_user)
):
    """
    Get chat history for a specific user
    
    Returns user's conversation history
    """
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")
        
        # Users can only access their own history
        if current_user != username:
            return APIResponse(success=False, error="Access denied")
        
        conversations = []
        
        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            pg_convs = await postgres_manager.get_user_conversations(username)
            for conv in pg_convs:
                conv_id = conv['id']
                messages = await postgres_manager.get_conversation_messages(conv_id)
                
                if messages:
                    conversations.append({
                        "conversation_id": conv_id,
                        "messages": messages,
                        "message_count": len(messages),
                        "last_message": messages[-1] if messages else None,
                        "created_at": conv['created_at'].isoformat() if conv['created_at'] else None
                    })
        
        # Fallback to Redis if Postgres is empty or not available (and we want to support migration/hybrid)
        # For now, let's just use Postgres if available, otherwise Redis
        if not conversations and redis_manager:
            # Get all conversation IDs for this user
            pattern = f"conversation:*:{username}"
            keys = await redis_manager.client.keys(pattern)
            
            for key in keys:
                # Redis keys are already strings in newer versions
                key_str = key if isinstance(key, str) else key.decode('utf-8')
                # Extract conversation_id by removing only the "conversation:" prefix
                conv_id = key_str.replace("conversation:", "", 1)
                
                # Get messages
                messages = await redis_manager.get_messages(conv_id)
                
                if messages:
                    conversations.append({
                        "conversation_id": conv_id,
                        "messages": messages,
                        "message_count": len(messages),
                        "last_message": messages[-1] if messages else None
                    })
        
        return APIResponse(
            success=True,
            data={
                "username": username,
                "conversations": conversations,
                "total_conversations": len(conversations)
            }
        )
        
    except Exception as e:
        logger.error(f"Get history error: {e}", exc_info=True)
        return APIResponse(success=False, error="Failed to get history")


@app.post("/history/{username}", response_model=APIResponse)
async def save_user_history(
    username: str,
    request: Dict[str, Any],
    current_user: Optional[str] = Depends(get_current_user)
):
    """
    Save chat history for a user
    
    Request:
        {
            "messages": [...]
        }
    """
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")
        
        if current_user != username:
            return APIResponse(success=False, error="Access denied")
        
        messages = request.get("messages", [])
        
        # Generate conversation ID
        conv_id = generate_conversation_id()
        
        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            # Create conversation first
            await postgres_manager.create_conversation(conv_id, username, title="Imported Chat")
            
            for msg in messages:
                await postgres_manager.save_message(
                    conv_id,
                    msg.get("sender", "user"), # Map 'sender' to 'role'
                    msg.get("text", ""),
                    username
                )
        
        # Also save to Redis for session continuity if needed, or just as fallback
        if redis_manager:
            for msg in messages:
                await redis_manager.save_message(
                    conv_id,
                    msg.get("sender", "user"),
                    msg.get("text", "")
                )
        
        return APIResponse(
            success=True,
            data={
                "conversation_id": conv_id,
                "message_count": len(messages)
            }
        )
        
    except Exception as e:
        logger.error(f"Save history error: {e}")
        return APIResponse(success=False, error="Failed to save history")


@app.delete("/history/{username}", response_model=APIResponse)
async def clear_user_history(
    username: str,
    current_user: Optional[str] = Depends(get_current_user)
):
    """Clear all chat history for a user"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")
        
        if current_user != username:
            return APIResponse(success=False, error="Access denied")
        
        deleted_count = 0
        
        # Clear from Postgres
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.clear_user_history(username)
            # We don't get a count back easily, but assume success
        
        # Clear from Redis
        if redis_manager:
            # Delete all conversations for this user
            pattern = f"conversation:*:{username}"
            keys = await redis_manager.client.keys(pattern)
            
            for key in keys:
                await redis_manager.client.delete(key)
                deleted_count += 1
            
            # Delete messages
            msg_pattern = f"messages:*:{username}"
            msg_keys = await redis_manager.client.keys(msg_pattern)
            
            for key in msg_keys:
                await redis_manager.client.delete(key)
        
        return APIResponse(
            success=True,
            data={
                "deleted_conversations": deleted_count, # This might be just Redis count
                "message": "History cleared successfully"
            }
        )
        
    except Exception as e:
        logger.error(f"Clear history error: {e}")
        return APIResponse(success=False, error="Failed to clear history")


@app.get("/health/aggregate", response_model=APIResponse)
async def aggregate_health():
    """Aggregated health including Redis and Ollama readiness (via sidecar or direct)."""
    status: Dict[str, Any] = {
        "service": "orchestrator",
        "version": "2.0.0",
    }
    # Redis status
    try:
        # redis_manager.connect() populates internal client; some implementations keep .redis attribute, else provide method
        # Fallback: attempt a lightweight state fetch to validate connectivity
        if hasattr(redis_manager, "redis") and redis_manager.redis:
            pong = await redis_manager.redis.ping()
            status["redis"] = "ok" if pong else "no-pong"
        else:
            await redis_manager.connect()
            # After reconnect attempt ping again if attribute now exists
            if hasattr(redis_manager, "redis") and redis_manager.redis:
                pong = await redis_manager.redis.ping()
                status["redis"] = "ok" if pong else "no-pong"
            else:
                status["redis"] = "connected"  # minimal confirmation
    except Exception as re:
        status["redis"] = f"error: {re}" 

    import httpx
    ollama_base = settings.OLLAMA_BASE_URL
    sidecar_candidates = ["http://ollama-health:8005", "http://localhost:8005"]
    ollama_info = {"reachable": False}
    async with httpx.AsyncClient(timeout=5) as client:
        for c in sidecar_candidates:
            try:
                r = await client.get(f"{c}/status")
                if r.status_code == 200:
                    d = r.json()
                    ollama_info.update({
                        "reachable": True,
                        "models": d.get("available_models", []),
                        "configured_model": d.get("configured_model"),
                        "generate_ready": d.get("generate_ready", False),
                        "source": "sidecar"
                    })
                    break
            except Exception:
                continue
        if not ollama_info["reachable"]:
            try:
                tags = await client.get(f"{ollama_base}/api/tags")
                if tags.status_code == 200:
                    tjson = tags.json()
                    names = [m.get("name") for m in tjson.get("models", [])]
                    ollama_info.update({
                        "reachable": True,
                        "models": names,
                        "configured_model": settings.OLLAMA_MODEL,
                        "generate_ready": settings.OLLAMA_MODEL in names,
                        "source": "direct"
                    })
            except Exception as oe:
                ollama_info["error"] = str(oe)

    status["ollama"] = ollama_info
    # Normalize Redis health: treat 'ok', 'no-pong', or 'connected' as acceptable
    redis_healthy = status.get("redis") in ["ok", "no-pong", "connected"]
    status["status"] = "healthy" if redis_healthy and ollama_info.get("reachable") else "degraded"
    return APIResponse(success=True, data=status)

@app.post("/chat", response_model=APIResponse)
async def chat(
    request: Dict[str, Any],
    current_user: Optional[str] = Depends(get_current_user)
):
    """
    Synchronous chat endpoint (requires authentication)
    
    Request:
        {
            "message": "user message",
            "conversation_id": "optional-id",
            "persona": "student|researcher|facility_manager|general",
            "language": "en",
            "building": "building1"
        }
    
    Response:
        {
            "success": true,
            "data": {
                "conversation_id": "...",
                "response": "...",
                "intent": "...",
                "username": "...",
                "analytics": boolean
            }
        }
    """
    try:
        # Validate authentication
        if not current_user:
            return APIResponse(success=False, error="Authentication required")
        
        username = current_user
        
        # Extract request data
        user_message = request.get("message")
        if not user_message:
            return APIResponse(success=False, error="Message is required")
        
        # Use session_id if provided, otherwise conversation_id, otherwise generate new one
        # This ensures all queries in same session share the same conversation_id
        session_id = request.get("session_id")
        conversation_id = request.get("conversation_id")
        
        if session_id:
            # Use session_id as conversation_id for continuity
            conversation_id = f"conv_{session_id}:{username}"
            logger.info(f"Using session_id for conversation: {conversation_id}")
        elif not conversation_id:
            # Generate new conversation_id only if neither session_id nor conversation_id provided
            conversation_id = f"{generate_conversation_id()}:{username}"
            logger.info(f"Generated new conversation_id: {conversation_id}")
        else:
            logger.info(f"Using provided conversation_id: {conversation_id}")
        
        persona = request.get("persona", "general")
        language = request.get("language", "en")
        building = request.get("building", "building1")
        
        # Load or create conversation state
        state = await redis_manager.load_state(conversation_id)
        
        if not state:
            # New conversation
            state = ConversationState(
                conversation_id=conversation_id,
                user_message=user_message,  # Add current message
                messages=[],
                building_id=building,
                persona=persona if persona in ["stakeholder", "guest", "officer", "facility_manager"] else "guest"
            )
            # Store user association
            state.user_id = username
        else:
            # Update existing conversation with new message
            state.user_message = user_message
        
        # Add user message
        from datetime import datetime
        state.messages.append(Message(
            role="user",
            content=user_message,
            timestamp=datetime.now()
        ))
        
        # Save message
        await redis_manager.save_message(
            conversation_id,
            "user",
            user_message
        )
        
        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.save_message(
                conversation_id,
                "user",
                user_message,
                username
            )
        
        # Execute workflow
        logger.info("="*100)
        logger.info("🚀 FRONTEND REQUEST - Starting Workflow Execution")
        logger.info("="*100)
        logger.info(f"📝 Conversation ID: {conversation_id}")
        logger.info(f"👤 User: {username}")
        logger.info(f"💬 Message: {user_message}")
        logger.info(f"🏢 Building: {state.building_id}")
        logger.info(f"🎭 Persona: {state.persona}")
        logger.info("="*100)
        
        updated_state = await orchestrator.execute(state)
        
        # Log intermediate results
        logger.info("\n" + "="*100)
        logger.info("📊 WORKFLOW RESULTS SUMMARY")
        logger.info("="*100)
        logger.info(f"🎯 Intent: {updated_state.current_intent}")
        
        if updated_state.intermediate_results:
            logger.info("\n📋 Intermediate Results:")
            
            # SPARQL Results
            sparql_result = updated_state.intermediate_results.get("sparql_result", {})
            if sparql_result:
                logger.info("\n1️⃣ SPARQL Agent Results:")
                sparql_output = sparql_result.get("output", {})
                if isinstance(sparql_output, dict):
                    results = sparql_output.get("results", {}).get("bindings", [])
                    logger.info(f"   📊 Found {len(results)} results")
                    if results:
                        logger.info(f"   🔍 Sample result: {results[0]}")
            
            # SQL Results
            sql_result = updated_state.intermediate_results.get("sql_result", {})
            if sql_result:
                logger.info("\n2️⃣ SQL Agent Results:")
                sql_output = sql_result.get("output", {})
                if isinstance(sql_output, dict):
                    data = sql_output.get("data", [])
                    logger.info(f"   📊 Found {len(data)} data rows")
                    if data:
                        logger.info(f"   🔍 Sample row: {data[0]}")
            
            # Analytics Results
            analytics_result = updated_state.intermediate_results.get("analytics_result", {})
            if analytics_result:
                logger.info("\n3️⃣ Analytics Agent Results:")
                analytics_output = analytics_result.get("output")
                if analytics_output:
                    logger.info(f"   📈 Output: {str(analytics_output)[:200]}...")
                analytics_code = analytics_result.get("code")
                if analytics_code:
                    logger.info(f"   💻 Code executed: {len(analytics_code)} chars")
        
        logger.info("="*100 + "\n")
        
        # Save updated state
        await redis_manager.save_state(updated_state)
        
        # Get assistant response
        assistant_entry = updated_state.messages[-1] if updated_state.messages else None
        assistant_message = assistant_entry.content if assistant_entry else "No response generated"
        assistant_metadata = assistant_entry.metadata if assistant_entry else None
        logger.info(f"✅ Assistant Response: {assistant_message[:200]}...")
        
        # Save assistant message
        await redis_manager.save_message(
            conversation_id,
            "assistant",
            assistant_message,
            metadata=assistant_metadata
        )
        
        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.save_message(
                conversation_id,
                "assistant",
                assistant_message,
                username
            )
        
        # Get analytics flag from state (set by SPARQL/SQL agents)
        analytics_flag = getattr(updated_state, 'analytics_required', False)
        
        return APIResponse(
            success=True,
            data={
                "conversation_id": conversation_id,
                "response": assistant_message,
                "intent": updated_state.current_intent,
                "username": username,
                "analytics": analytics_flag,
                "media": assistant_metadata.get("media") if assistant_metadata else None
            }
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e))

@app.post("/chat/stream")
async def chat_stream(
    request: Dict[str, Any],
    current_user: Optional[str] = Depends(get_current_user)
):
    """
    Streaming chat endpoint (Server-Sent Events)
    """
    try:
        # Validate authentication
        # Allow unauthenticated for demo/testing if needed, but prefer authenticated
        username = current_user or "guest"
        
        user_message = request.get("message")
        if not user_message:
            raise HTTPException(status_code=400, detail="Message is required")
            
        conversation_id = request.get("conversation_id")
        if not conversation_id:
            conversation_id = f"{generate_conversation_id()}:{username}"
            
        persona = request.get("persona", "general")
        # Map 'general' to 'guest' or validate against allowed values
        valid_personas = ["stakeholder", "guest", "officer", "facility_manager"]
        if persona not in valid_personas:
            persona = "guest"

        language = request.get("language", "en")
        building = request.get("building", "building1")
        
        async def event_generator():
            try:
                # Send conversation ID first
                yield f"data: {json.dumps({'type': 'conversation_id', 'id': conversation_id})}\n\n"
                
                # Load or create state
                state = await redis_manager.load_state(conversation_id)
                if not state:
                    state = ConversationState(
                        conversation_id=conversation_id,
                        user_message=user_message,
                        messages=[],
                        building_id=building,
                        persona=persona,
                        user_id=username
                    )
                else:
                    state.user_message = user_message
                
                # Add user message
                from datetime import datetime
                state.messages.append(Message(
                    role="user",
                    content=user_message,
                    timestamp=datetime.now()
                ))
                await redis_manager.save_message(conversation_id, "user", user_message)
                
                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.save_message(
                        conversation_id,
                        "user",
                        user_message,
                        username
                    )
                
                # Add to user's conversation list if new
                await redis_manager.add_conversation_to_user(username, conversation_id, user_message[:30] + "...")

                # Execute workflow (Synchronous for now to ensure full context)
                # We simulate streaming by sending the full response
                updated_state = await orchestrator.execute(state)
                
                assistant_entry = updated_state.messages[-1] if updated_state.messages else None
                full_response = assistant_entry.content if assistant_entry else "No response generated"
                assistant_metadata = assistant_entry.metadata if assistant_entry else None
                
                # Save assistant message
                await redis_manager.save_message(conversation_id, "assistant", full_response, metadata=assistant_metadata)
                
                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.save_message(
                        conversation_id,
                        "assistant",
                        full_response,
                        username
                    )
                
                # Save updated state
                await redis_manager.save_state(updated_state)
                
                # Stream the response (simulate chunks or send all at once)
                # Frontend expects {"type": "token", "content": "..."}
                yield f"data: {json.dumps({'type': 'token', 'content': full_response})}\n\n"
                if assistant_metadata and assistant_metadata.get('media'):
                    yield f"data: {json.dumps({'type': 'metadata', 'media': assistant_metadata['media']})}\n\n"
                yield f"data: [DONE]\n\n"
                
                yield f"data: [DONE]\n\n"
                
            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Chat stream setup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for streaming responses
    
    Client sends:
        {
            "message": "user message",
            "conversation_id": "optional-id",
            "persona": "student|researcher|facility_manager|general"
        }
    
    Server streams:
        {"type": "intent", "data": "sparql"}
        {"type": "progress", "data": "Querying ontology..."}
        {"type": "result", "data": {...}}
        {"type": "response", "data": "Final response"}
        {"type": "done"}
    """
    await websocket.accept()
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            request = json.loads(data)
            
            user_message = request.get("message")
            if not user_message:
                await websocket.send_json({
                    "type": "error",
                    "data": "Message is required"
                })
                continue
            
            conversation_id = request.get("conversation_id") or generate_conversation_id()
            persona = request.get("persona", "general")
            language = request.get("language", "en")
            building = request.get("building", "building1")
            
            # Load or create state
            state = await redis_manager.load_state(conversation_id)
            
            if not state:
                state = ConversationState(
                    conversation_id=conversation_id,
                    messages=[],
                    current_intent="unknown",
                    query_results={},
                    intermediate_results={},
                    user_preferences={
                        "persona": persona,
                        "language": language,
                        "building": building
                    }
                )
            
            # Add user message
            state.messages.append(Message(
                role="user",
                content=user_message,
                timestamp=None
            ))
            
            await redis_manager.save_message(conversation_id, "user", user_message)
            
            # Stream workflow execution
            async for step in orchestrator.stream_execute(state):
                # Send progress updates
                if "dialogue" in step:
                    await websocket.send_json({
                        "type": "progress",
                        "data": "Analyzing intent..."
                    })
                elif "sparql" in step:
                    await websocket.send_json({
                        "type": "progress",
                        "data": "Querying building ontology..."
                    })
                elif "sql" in step:
                    await websocket.send_json({
                        "type": "progress",
                        "data": "Fetching sensor data..."
                    })
                elif "analytics" in step:
                    await websocket.send_json({
                        "type": "progress",
                        "data": "Performing analysis..."
                    })
                elif "visualization" in step:
                    await websocket.send_json({
                        "type": "progress",
                        "data": "Creating visualization..."
                    })
            
            # Get final state
            final_state = await orchestrator.execute(state)
            
            # Save state
            await redis_manager.save_state(final_state)
            
            # Get response
            assistant_message = final_state.messages[-1].content if final_state.messages else "No response"
            
            await redis_manager.save_message(conversation_id, "assistant", assistant_message)
            
            # Send final response
            await websocket.send_json({
                "type": "response",
                "data": assistant_message,
                "conversation_id": conversation_id,
                "intent": final_state.current_intent
            })
            
            await websocket.send_json({"type": "done"})
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "data": str(e)
            })
        except:
            pass

@app.get("/conversation/{conversation_id}", response_model=APIResponse)
async def get_conversation(conversation_id: str):
    """Get conversation history"""
    try:
        messages = await redis_manager.get_messages(conversation_id)
        
        return APIResponse(
            success=True,
            data={
                "conversation_id": conversation_id,
                "messages": messages,
                "count": len(messages)
            }
        )
        
    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        return APIResponse(success=False, error=str(e))

@app.delete("/conversation/{conversation_id}", response_model=APIResponse)
async def delete_conversation(conversation_id: str):
    """Delete conversation"""
    try:
        # Delete state and messages
        await redis_manager.redis.delete(f"conversation:{conversation_id}")
        await redis_manager.redis.delete(f"messages:{conversation_id}")
        
        return APIResponse(
            success=True,
            data={"message": f"Conversation {conversation_id} deleted"}
        )
        
    except Exception as e:
        logger.error(f"Delete conversation error: {e}")
        return APIResponse(success=False, error=str(e))

@app.post("/preferences", response_model=APIResponse)
async def update_preferences(request: Dict[str, Any]):
    """Update user preferences"""
    try:
        conversation_id = request.get("conversation_id")
        if not conversation_id:
            return APIResponse(success=False, error="conversation_id required")
        
        preferences = {
            "persona": request.get("persona"),
            "language": request.get("language"),
            "building": request.get("building")
        }
        
        # Remove None values
        preferences = {k: v for k, v in preferences.items() if v is not None}
        
        await redis_manager.save_user_preferences(conversation_id, preferences)
        
        return APIResponse(
            success=True,
            data={"preferences": preferences}
        )
        
    except Exception as e:
        logger.error(f"Update preferences error: {e}")
        return APIResponse(success=False, error=str(e))

# ==================== OpenAI Compatibility Layer ====================

@app.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    OpenAI-compatible endpoint for Open WebUI integration.
    Allows Open WebUI to use the OntoSage pipeline as a backend.
    """
    try:
        # Basic auth check (accept any token for now)
        # username = "openwebui_user" # Moved below to support 'user' field
        
        data = await request.json()
        messages = data.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        # Determine username from request or default
        # Open WebUI and other clients may send a 'user' field
        username = data.get("user") or "openwebui_user"
            
        # Extract last user message
        last_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not last_user_msg:
             raise HTTPException(status_code=400, detail="No user message found")
             
        user_message = last_user_msg["content"]
        
        # Generate conversation ID
        conversation_id = f"owui_{generate_conversation_id()}:{username}"
        
        # Create state
        state = ConversationState(
            conversation_id=conversation_id,
            user_message=user_message,
            messages=[], 
            building_id="building1", # Default
            persona="guest",
            user_id=username
        )
        
        # Add the current message to the history so the agent can see it
        state.messages.append(Message(
            role="user",
            content=user_message,
            timestamp=datetime.now()
        ))
        
        # Execute workflow
        updated_state = await orchestrator.execute(state)
        
        # Get response
        assistant_message = updated_state.messages[-1].content if updated_state.messages else "No response generated"
        
        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            # Ensure user exists (idempotent)
            await postgres_manager.create_user(username, "placeholder_hash", "placeholder_salt", metadata={"source": "open_webui"})
            
            # Save user message
            await postgres_manager.save_message(
                conversation_id,
                "user",
                user_message,
                username
            )
            
            # Save assistant message
            await postgres_manager.save_message(
                conversation_id,
                "assistant",
                assistant_message,
                username
            )

        # Format response as OpenAI ChatCompletion
        return {
            "id": f"chatcmpl-{conversation_id}",
            "object": "chat.completion",
            "created": int(datetime.now().timestamp()),
            "model": data.get("model", "ontobot-pipeline"),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": assistant_message
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }

    except Exception as e:
        logger.error(f"OpenAI endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/models")
async def openai_models():
    """List available models for Open WebUI"""
    return {
        "object": "list",
        "data": [
            {
                "id": "ontobot-pipeline",
                "object": "model",
                "created": 1677610602,
                "owned_by": "ontosage"
            }
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
