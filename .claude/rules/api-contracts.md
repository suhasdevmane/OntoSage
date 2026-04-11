# FastAPI Endpoint Patterns — OntoSage

These patterns MUST be followed for all new endpoints in `orchestrator/main.py`.

## Response Envelope

All endpoints return this structure:

```python
from fastapi.responses import JSONResponse

# Success response
return JSONResponse({
    "status": "success",
    "data": {...},
    "trace_id": request.state.trace_id,
})

# Error response
return JSONResponse({
    "status": "error",
    "message": "Human-readable description of what went wrong",
    "trace_id": request.state.trace_id,
}, status_code=400)
```

## RBAC Protection (required on every data endpoint)

```python
from orchestrator.middleware.rbac import create_rbac_dependency, UserContext
from fastapi import Depends

@app.get("/api/v1/sensors")
async def get_sensors(
    request: Request,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read")),
):
    # user.role, user.tenant_id, user.allowed_buildings are all available
    ...
```

Available permissions:
- **Data read:** `sensor:read`, `analytics:read`, `metadata:read`, `report:read`, `export:read`, `anomaly:read`, `trend:read`, `compliance:read`, `comparison:read`
- **Config:** `config:read`, `config:write`
- **User mgmt:** `user:read`, `user:write`, `user:delete`
- **Building:** `building:read`, `building:write`, `building:delete`
- **System:** `system:admin`, `system:health`

Guest users default to `readonly` role — they only have `metadata:read` and `system:health`.

## Input Validation (always use Pydantic — never raw dict)

```python
from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000,
                         description="User's natural language question")
    session_id: str = Field(..., min_length=1,
                             description="UUID identifying the conversation")
    building_id: Optional[str] = Field(None,
                                        description="Override building context")

@app.post("/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read")),
):
    ...
```

Never use `await request.json()` directly — always use a typed Pydantic model.

## WebSocket Pattern

```python
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # Validate input
            if "message" not in data or not isinstance(data["message"], str):
                await websocket.send_json({"type": "error", "message": "Invalid message format"})
                continue
            # Process and respond
            result = await process_message(data["message"], session_id)
            await websocket.send_json({"type": "response", "data": result})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: session={session_id} error={e}", exc_info=True)
        await websocket.close(code=1011)
```

## Trace ID (inject in all logs)

Every request gets a `trace_id` injected by middleware. Use it in all logs and responses:

```python
@app.post("/api/v1/my-endpoint")
async def my_endpoint(request: Request, ...):
    trace_id = request.state.trace_id
    logger.info(f"[{trace_id}] Processing request: session={session_id}")
    return JSONResponse({"status": "success", "trace_id": trace_id, "data": ...})
```

## Health Endpoint Pattern

```python
@app.get("/health")
async def health():
    """Health check — no auth required."""
    return {
        "status": "healthy",
        "services": {
            "graphdb": await check_graphdb(),
            "redis": await check_redis(),
            "ollama": await check_ollama() if settings.MODEL_PROVIDER == "local" else "skipped",
        }
    }
```

Health endpoint must NOT require authentication — used by Docker health checks and monitoring.
