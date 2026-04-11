# Python Style Rules — OntoSage

These rules apply to ALL Python files in `orchestrator/`, `shared/`, `scripts/`, and `tests/`.

## Formatting

- **Line length:** 100 characters (`black --line-length 100`)
- **Formatter:** `black --line-length 100 <file>`
- **Import sorting:** `isort --profile black <file>`
- Run both before every commit

## Static Analysis

- `flake8 --max-line-length 110 --extend-ignore=E203,E501,W503`
- `bandit -ll` — no high or medium severity issues permitted
- `__init__.py` files may have unused imports (F401 suppressed by convention)

## Type Hints

- All new functions must have type hints on parameters and return values
- Use `Optional[X]` not `X | None` (Python 3.9 compatibility)
- Use `Dict`, `List`, `Tuple` from `typing` (not built-in generics `dict`, `list`)

## Async

- All LangGraph agent node functions must be `async def`
- Never block the event loop: no `time.sleep()`, no synchronous DB calls in async functions
- Use `await asyncio.sleep()` for delays
- Wrap blocking I/O: `await asyncio.get_event_loop().run_in_executor(None, blocking_fn)`

## Logging

```python
# CORRECT
from shared.utils import get_logger
logger = get_logger(__name__)
logger.info(f"[agent_name] Processing intent={intent}")
logger.error(f"[agent_name] Failed: {e}", exc_info=True)

# WRONG — never use print() in production code
print("something")
```

Log levels:
- `DEBUG` — detailed trace (disabled in production)
- `INFO` — state changes, node entry/exit
- `WARNING` — recoverable errors, fallbacks triggered
- `ERROR` — failures with `exc_info=True`

Never log: passwords, session tokens, API keys.

## Error Handling

```python
# CORRECT
try:
    result = await some_call()
except TimeoutError as e:
    logger.warning(f"[my_node] Timed out: {e}")
    return default_value
except Exception as e:
    logger.error(f"[my_node] Unexpected error: {e}", exc_info=True)
    raise

# WRONG — bare except swallows everything including KeyboardInterrupt
try:
    result = await some_call()
except:
    pass
```

## Docstrings

- One-line docstring for all public functions
- No docstrings required for private `_methods` unless logic is non-obvious

## Import Order (enforced by isort --profile black)

```python
# 1. Standard library
import asyncio
import json
from typing import Dict, List, Optional

# 2. Third-party
from fastapi import FastAPI
from langgraph.graph import StateGraph

# 3. Internal (shared/)
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

# 4. Local (orchestrator/)
from orchestrator.agents.sparql_agent import SPARQLAgent
```
