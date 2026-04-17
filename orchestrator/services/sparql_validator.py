"""
SPARQLValidator — Phase 3.4 (SPARQL Validation & Self-Correction Loop)
=======================================================================
Validates SPARQL queries via rdflib before they are sent to GraphDB,
reducing round-trips for syntactically invalid queries.

Also maintains a Redis-based cache of (query_hash → results) so that
identical successful queries are answered without hitting GraphDB again.

Usage:
    from orchestrator.services.sparql_validator import sparql_validator

    # Pure syntax check (returns True if valid, error string if not)
    ok, err = sparql_validator.validate_syntax(query_string)

    # Validate + cache-aware execution
    result, from_cache = await sparql_validator.validate_and_cache(
        query_string, executor_fn
    )
"""

import sys

sys.path.append("/app")

import hashlib
import json
import re
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# rdflib sparqlalgebra parse (available without network)
try:
    from rdflib.plugins.sparql import prepareQuery

    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False
    logger.warning("rdflib not available — SPARQL syntax validation disabled")

# Patterns that are always invalid in SPARQL (quick pre-check)
_SYNTAX_BLACKLIST = [
    r"\bDROP\b",
    r"\bINSERT\b",
    r"\bDELETE\b",
    r"\bCREATE\b",
    r"\bLOAD\b",
    r"\bCLEAR\b",
    r"\bADD\b",
    r"\bCOPY\b",
    r"\bMOVE\b",
]

# Cache TTL in seconds (default 5 minutes)
CACHE_TTL = int(getattr(settings, "SPARQL_CACHE_TTL_SECONDS", 300))
CACHE_MAX_RESULTS_SIZE = 1024 * 50  # 50 KB max per cached result


class SPARQLValidator:
    """
    Phase 3.4: Two-layer SPARQL protection:
      Layer 1 — Syntax validation via rdflib (before network call)
      Layer 2 — Redis query cache (successful results reused)
    """

    # Known common prefix declarations to inject for rdflib parse
    _PREFIX_INJECT = (
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "PREFIX ashrae: <http://data.ashrae.org/standard223#>\n"
    )

    # Max results safety cap for SPARQL queries without explicit LIMIT
    _MAX_RESULTS_LIMIT = 1000

    @classmethod
    def enforce_limit(cls, query: str) -> str:
        """Append LIMIT if the query is a SELECT without one (safety cap)."""
        q_upper = query.upper()
        # Only apply to SELECT queries that don't already have LIMIT
        if "SELECT" in q_upper and "LIMIT" not in q_upper:
            query = query.rstrip().rstrip(";") + f"\nLIMIT {cls._MAX_RESULTS_LIMIT}"
        return query

    # ------------------------------------------------------------------
    # Layer 1: Syntax Validation
    # ------------------------------------------------------------------

    def validate_syntax(self, query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate SPARQL syntax without executing.
        Returns (True, None) if valid, (False, error_message) if invalid.
        """
        if not query or not query.strip():
            return False, "Empty query"

        # Quick blacklist check
        q_upper = query.upper()
        for pattern in _SYNTAX_BLACKLIST:
            if re.search(pattern, q_upper):
                return False, f"Forbidden SPARQL operation: {pattern}"

        # Must be a SELECT, ASK, DESCRIBE, or CONSTRUCT query
        first_kw = q_upper.lstrip().split()[0] if q_upper.strip() else ""
        # Skip PREFIX/BASE preamble
        non_prefix = re.sub(r"(PREFIX|BASE)\s+\S+\s+<[^>]+>", "", q_upper).strip()
        first_meaningful = non_prefix.split()[0] if non_prefix.split() else ""
        if first_meaningful not in ("SELECT", "ASK", "DESCRIBE", "CONSTRUCT", "WITH"):
            return (
                False,
                f"Query must start with SELECT/ASK/DESCRIBE/CONSTRUCT, got: '{first_meaningful}'",
            )

        if not RDFLIB_AVAILABLE:
            return True, None  # Can't do deeper check without rdflib

        # Inject common prefixes so rdflib can parse without unknown prefix errors
        augmented = (
            self._PREFIX_INJECT
            + f"PREFIX {settings.BUILDING_PREFIX}: <{settings.BUILDING_NAMESPACE}>\n"
            + query
        )
        try:
            prepareQuery(augmented)
            return True, None
        except Exception as e:
            error_msg = str(e)
            # Attempt graceful fix for common issues
            fixed = self._attempt_auto_fix(query, error_msg)
            if fixed and fixed != query:
                try:
                    prepareQuery(self._PREFIX_INJECT + fixed)
                    logger.info(f"SPARQLValidator: auto-fixed query (len {len(fixed)})")
                    return True, f"AUTO_FIXED:{fixed}"
                except Exception:
                    pass
            return False, f"SPARQL parse error: {error_msg[:200]}"

    def _attempt_auto_fix(self, query: str, error: str) -> Optional[str]:
        """Apply simple auto-corrections for known common syntax errors."""
        fixed = query

        # Fix: missing closing brace
        open_braces = query.count("{")
        close_braces = query.count("}")
        if open_braces > close_braces:
            fixed += " }" * (open_braces - close_braces)
            logger.debug(f"Auto-fix: added {open_braces - close_braces} closing braces")

        # Fix: double WHERE WHERE
        fixed = re.sub(r"\bWHERE\s+WHERE\b", "WHERE", fixed, flags=re.IGNORECASE)

        # Fix: SELECT * (sometimes not allowed without explicit variables)
        # Leave as-is — GraphDB generally supports SELECT *

        return fixed if fixed != query else None

    # ------------------------------------------------------------------
    # Layer 2: Redis Query Cache
    # ------------------------------------------------------------------

    def _make_cache_key(self, query: str) -> str:
        """Generate a deterministic cache key from a normalized SPARQL string."""
        normalized = re.sub(r"\s+", " ", query.strip().lower())
        h = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"sparql_cache:{h}"

    async def get_cached(self, query: str) -> Optional[Dict]:
        """Return cached result if available, else None."""
        try:
            from orchestrator.redis_manager import redis_manager

            if not redis_manager or not redis_manager.redis:
                return None
            key = self._make_cache_key(query)
            cached = await redis_manager.redis.get(key)
            if cached:
                logger.info(f"SPARQLValidator cache HIT: {key}")
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Cache get failed: {e}")
        return None

    async def set_cached(self, query: str, result: Dict) -> None:
        """Store query result in Redis cache with TTL."""
        try:
            from orchestrator.redis_manager import redis_manager

            if not redis_manager or not redis_manager.redis:
                return
            # Don't cache large result sets
            serialized = json.dumps(result)
            if len(serialized) > CACHE_MAX_RESULTS_SIZE:
                logger.debug("SPARQLValidator: result too large to cache, skipping")
                return
            key = self._make_cache_key(query)
            await redis_manager.redis.setex(key, CACHE_TTL, serialized)
            logger.info(f"SPARQLValidator cache SET: {key} (TTL={CACHE_TTL}s)")
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")

    async def invalidate(self, pattern: str = "sparql_cache:*") -> int:
        """Invalidate cached queries matching a pattern."""
        try:
            from orchestrator.redis_manager import redis_manager

            if not redis_manager or not redis_manager.redis:
                return 0
            keys = await redis_manager.redis.keys(pattern)
            if keys:
                await redis_manager.redis.delete(*keys)
            logger.info(f"SPARQLValidator: invalidated {len(keys)} cache entries")
            return len(keys)
        except Exception as e:
            logger.debug(f"Cache invalidate failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Combined validate + cache-aware execution
    # ------------------------------------------------------------------

    async def validate_and_execute(
        self,
        query: str,
        executor: Callable[[str], Coroutine[Any, Any, Dict]],
        use_cache: bool = True,
    ) -> Tuple[Dict, bool]:
        """
        Validate syntax → check cache → execute → store in cache.
        Returns (result_dict, from_cache_bool).

        Raises ValueError if query is invalid and no auto-fix is possible.
        """
        # Layer 1: syntax check
        valid, error = self.validate_syntax(query)
        if not valid:
            raise ValueError(f"Invalid SPARQL: {error}")

        # Handle auto-fix
        actual_query = query
        if error and error.startswith("AUTO_FIXED:"):
            actual_query = error[len("AUTO_FIXED:") :]
            logger.info("SPARQLValidator: using auto-fixed query")

        # Layer 2: cache check
        if use_cache:
            cached = await self.get_cached(actual_query)
            if cached is not None:
                return cached, True

        # Execute
        result = await executor(actual_query)

        # Cache successful results
        if use_cache and isinstance(result, dict) and result:
            await self.set_cached(actual_query, result)

        return result, False


# Module-level singleton
sparql_validator = SPARQLValidator()
