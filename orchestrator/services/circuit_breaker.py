"""
Circuit Breaker Pattern for External Dependencies
===================================================
Prevents cascading failures when external services (LLM, MySQL, GraphDB, RAG)
are down.  Instead of timing out every request, the breaker trips after
`failure_threshold` consecutive failures and fast-fails for `recovery_timeout`
seconds, then allows a single probe request through (HALF_OPEN).

Usage:
    from orchestrator.services.circuit_breaker import circuit_breaker_for

    breaker = circuit_breaker_for("mysql")

    if not breaker.allow_request():
        return {"error": "database_unavailable"}

    try:
        result = await adapter.execute_query(sql)
        breaker.record_success()
    except Exception as e:
        breaker.record_failure()
        raise
"""

import time
import threading
from enum import Enum
from typing import Dict
from shared.utils import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"          # Normal operation — requests pass through
    OPEN = "open"              # Breaker tripped — fast-fail all requests
    HALF_OPEN = "half_open"    # Recovery probe — one request allowed


class CircuitBreaker:
    """
    Thread-safe circuit breaker for a single dependency.

    Parameters:
        name:              Human-readable label (e.g. "mysql", "llm")
        failure_threshold:  Consecutive failures before opening (default 5)
        recovery_timeout:   Seconds to wait before probing (default 30)
        success_threshold:  Consecutive successes in HALF_OPEN to close (default 2)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info(f"CircuitBreaker[{self.name}]: OPEN -> HALF_OPEN (probing)")
            return self._state

    def allow_request(self) -> bool:
        """Return True if a request should be allowed through."""
        current = self.state
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return True  # allow probe
        # OPEN
        return False

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info(f"CircuitBreaker[{self.name}]: HALF_OPEN -> CLOSED (recovered)")
            else:
                # Any success in CLOSED resets consecutive failure count
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — re-open
                self._state = CircuitState.OPEN
                logger.warning(f"CircuitBreaker[{self.name}]: HALF_OPEN -> OPEN (probe failed)")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}]: CLOSED -> OPEN "
                    f"(failures={self._failure_count})"
                )

    def reset(self) -> None:
        """Force-reset to CLOSED (e.g. after manual intervention)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info(f"CircuitBreaker[{self.name}]: manually reset to CLOSED")

    def status(self) -> Dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ── Global breaker registry ──────────────────────────────────────────────────

_breakers: Dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def circuit_breaker_for(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """
    Get or create a named circuit breaker.
    Same name always returns the same instance (singleton per dependency).
    """
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _breakers[name]


def all_breaker_statuses() -> list:
    """Return status dicts for every registered breaker (for health endpoint)."""
    with _registry_lock:
        return [b.status() for b in _breakers.values()]
