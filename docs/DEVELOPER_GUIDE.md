# Developer Guide

## Local Development
- Python 3.11; create a venv and install per-service `requirements.txt`.
- Orchestrator and shared modules are bind-mounted for hot reload in Docker.

## Codebase Layout
- `orchestrator/`: FastAPI app, LangGraph workflow, agents, managers
    - `agents/`: Individual agent logic (Dialogue, SPARQL, SQL, Analytics)
    - `services/`: Helper services (ContextManager)
    - `redis_manager.py`: Caching and state persistence
    - `postgres_manager.py`: Long-term storage
- `rag-service/`: GraphDB/Qdrant RAG components
- `code-executor/`: Sandbox runtime and API
- `frontend/`: React 19 + TypeScript UI
- `shared/`: Settings (`shared/config.py`) and common utilities (`shared/models.py`)

## Adding an Agent
1. Create file in `orchestrator/agents/` (e.g., `my_agent.py`).
2. Define tool functions and state IO.
3. Register in `orchestrator/workflow.py` and routing logic.
4. Expose any needed config via `shared/config.py`.

## API Standardization
All API endpoints must return the `APIResponse` model defined in `shared/models.py`.
```python
return APIResponse(
    success=True,
    data={"key": "value"},
    error=None
)
```
Refer to `orchestrator/main.py` for examples.

## Caching Strategy
- **Conversation State**: Automatically saved to Redis after every turn.
- **Semantic Caching**: SPARQL and SQL agents check `redis_manager` for cached results before executing queries. Use `generate_hash(query)` for keys.

## Testing
```bash
pytest -q
```
End-to-end smoke tests can be run with:
```bash
python smoke_test.py
```

## Debugging
- Tail orchestrator logs: `docker-compose -f docker-compose.agentic.yml logs -f orchestrator`
- Attach VSCode debugger to Python inside the container if needed.

## Style
- Follow PEP8; type hints encouraged
- Keep agents small and single-responsibility

## API
- FastAPI docs at `http://localhost:8000/docs`
- OpenAI-compatible endpoints under `/v1` if enabled
