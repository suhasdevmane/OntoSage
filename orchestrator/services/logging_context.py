"""
Structured Logging with Trace IDs
===================================
Provides a contextvars-based trace_id that propagates through async call chains.
Middleware sets it from incoming X-Trace-Id header or generates a fresh one.

Usage in any module:
    from orchestrator.services.logging_context import get_trace_id, set_trace_id

    trace_id = get_trace_id()       # returns current trace_id (never None)
    set_trace_id("abc123")          # override for the current async context

Usage as middleware:
    app.add_middleware(TraceIdMiddleware)
"""

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ContextVar that travels through async await chains
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Return the current trace_id, or generate one if not set."""
    tid = _trace_id_var.get()
    if not tid:
        tid = uuid.uuid4().hex[:12]
        _trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


class TraceIdMiddleware(BaseHTTPMiddleware):
    """
    Reads X-Trace-Id from incoming request headers (or generates one),
    stores it in contextvars, and returns it in the response header.
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:12]
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
