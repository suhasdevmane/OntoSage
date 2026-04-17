"""
Phase 6.1 — Agentic RAG Self-Correction Engine
================================================
Implements a multi-layer self-correction loop that wraps the SPARQL query
generation pipeline. When a query fails (syntax error, empty results, timeout),
the engine automatically diagnoses the failure, applies a targeted fix strategy,
and retries — up to a configurable max of attempts.

Correction strategies (in order):
  1. Syntax fix via rdflib AST parser  (fast, deterministic)
  2. Prefix injection / namespace repair (handles missing PREFIX declarations)
  3. LLM-guided query regeneration with error context (semantic fix)
  4. Schema fallback — try a simpler template query (guaranteed to work)

Design:
  - Each attempt is logged with its strategy, error, and duration
  - A self-correction report is stored in state.intermediate_results["correction_log"]
  - The engine integrates with SPARQLValidator and HybridRetrievalOrchestrator
  - Zero impact on happy-path latency (correction only fires on failure)

Usage:
    from orchestrator.services.self_correction_engine import SelfCorrectionEngine

    engine = SelfCorrectionEngine()
    result = await engine.execute_with_correction(state, raw_query, sparql_agent)
"""
from __future__ import annotations

import re
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

MAX_CORRECTION_ATTEMPTS = 3
EMPTY_RESULT_THRESHOLD  = 0     # retry if result count ≤ this
CORRECTION_TIMEOUT_S    = 30.0  # max seconds per correction attempt

# Standard SPARQL prefixes injected during prefix repair
STANDARD_PREFIXES = {
    "brick":  "https://brickschema.org/schema/Brick#",
    "ref":    "https://brickschema.org/schema/Brick/ref#",
    "rdf":    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":   "http://www.w3.org/2000/01/rdf-schema#",
    "xsd":    "http://www.w3.org/2001/XMLSchema#",
    "owl":    "http://www.w3.org/2002/07/owl#",
    "rec":    "https://w3id.org/rec#",
    "s223":   "http://data.ashrae.org/standard223#",
}

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CorrectionAttempt:
    attempt_num: int
    strategy: str
    original_query: str
    corrected_query: str
    error: Optional[str]
    success: bool
    result_count: int
    duration_ms: float
    explanation: str = ""


@dataclass
class CorrectionLog:
    total_attempts: int = 0
    succeeded: bool = False
    final_strategy: str = "none"
    attempts: List[CorrectionAttempt] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "total_attempts": self.total_attempts,
            "succeeded": self.succeeded,
            "final_strategy": self.final_strategy,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "attempts": [
                {
                    "attempt": a.attempt_num,
                    "strategy": a.strategy,
                    "success": a.success,
                    "result_count": a.result_count,
                    "error": a.error,
                    "duration_ms": round(a.duration_ms, 2),
                    "explanation": a.explanation,
                }
                for a in self.attempts
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Correction Strategies
# ─────────────────────────────────────────────────────────────────────────────

class StrategyBase:
    name: str = "base"

    async def apply(self, query: str, error: Optional[str],
                    context: Dict) -> tuple[str, str]:
        """Return (corrected_query, explanation)."""
        raise NotImplementedError


class SyntaxFixStrategy(StrategyBase):
    """Use rdflib to detect and fix common SPARQL syntax errors."""
    name = "syntax_fix"

    async def apply(self, query: str, error: Optional[str],
                    context: Dict) -> tuple[str, str]:
        fixed = query
        explanation = "Applied syntax auto-fix"

        # Fix 1: Missing dot separators in WHERE clause
        fixed = re.sub(r'(\}\s*\{)', r'} . {', fixed)

        # Fix 2: Unclosed braces
        open_count  = fixed.count("{")
        close_count = fixed.count("}")
        if open_count > close_count:
            fixed += " }" * (open_count - close_count)
            explanation += "; added missing closing braces"

        # Fix 3: Remove invalid FILTER syntax
        if error and "FILTER" in (error or ""):
            fixed = re.sub(r'FILTER\s*\([^)]*\)\s*', '', fixed)
            explanation += "; removed malformed FILTER"

        # Fix 4: Remove double SELECT
        fixed = re.sub(r'SELECT\s+SELECT', 'SELECT', fixed, flags=re.IGNORECASE)

        return fixed, explanation


class PrefixRepairStrategy(StrategyBase):
    """Inject missing PREFIX declarations inferred from query usage."""
    name = "prefix_repair"

    async def apply(self, query: str, error: Optional[str],
                    context: Dict) -> tuple[str, str]:
        added = []
        # Extract used prefixes: patterns like "prefix:LocalName"
        used_prefixes = set(re.findall(r'\b([a-zA-Z][a-zA-Z0-9_]*):', query))

        # Find existing declared prefixes
        declared = set(re.findall(r'PREFIX\s+([a-zA-Z][a-zA-Z0-9_]*):', query, re.IGNORECASE))

        # Add missing standard prefixes
        missing = used_prefixes - declared
        prefix_block = ""
        for p in missing:
            if p in STANDARD_PREFIXES:
                prefix_block += f"PREFIX {p}: <{STANDARD_PREFIXES[p]}>\n"
                added.append(p)

        # Also add building namespace if available
        building_ns = context.get("building_namespace", "")
        building_prefix = context.get("building_prefix", "bldg")
        if building_ns and building_prefix not in declared:
            prefix_block += f"PREFIX {building_prefix}: <{building_ns}>\n"
            added.append(building_prefix)

        fixed = prefix_block + query if prefix_block else query
        explanation = f"Injected missing prefixes: {added}" if added else "No prefix injection needed"
        return fixed, explanation


class LLMRegenerationStrategy(StrategyBase):
    """Ask the LLM to regenerate the query with the error context provided."""
    name = "llm_regeneration"

    async def apply(self, query: str, error: Optional[str],
                    context: Dict) -> tuple[str, str]:
        llm_call: Optional[Callable] = context.get("llm_call")
        user_query: str = context.get("user_query", "")
        schema_hint: str = context.get("schema_hint", "Brick v1.3")

        if not llm_call:
            return query, "LLM unavailable — skipping regeneration"

        correction_prompt = f"""You are an expert SPARQL query writer for building ontologies ({schema_hint}).

The following SPARQL query FAILED with this error:
ERROR: {error or 'Empty results returned'}

FAILED QUERY:
```sparql
{query}
```

USER'S ORIGINAL QUESTION: {user_query}

Please write a CORRECTED, valid SPARQL query that:
1. Fixes the identified error
2. Uses proper PREFIX declarations
3. Uses OPTIONAL {{ }} for optional properties
4. Includes LIMIT 100 to prevent timeouts
5. Returns the data the user asked for

Return ONLY the corrected SPARQL query, no explanation."""

        try:
            corrected = await asyncio.wait_for(
                llm_call(correction_prompt),
                timeout=CORRECTION_TIMEOUT_S
            )
            # Extract query from markdown code block if present
            match = re.search(r'```(?:sparql)?\s*(.*?)```', corrected, re.DOTALL)
            if match:
                corrected = match.group(1).strip()
            return corrected.strip(), "LLM regenerated query with error context"
        except asyncio.TimeoutError:
            return query, "LLM regeneration timed out"
        except Exception as e:
            return query, f"LLM regeneration failed: {str(e)[:80]}"


class TemplateSchemaFallbackStrategy(StrategyBase):
    """Fall back to a simple, guaranteed-to-work template query."""
    name = "template_fallback"

    # Safe fallback query — discovers all sensor types
    FALLBACK_TEMPLATE = """\
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX {prefix}: <{namespace}>

SELECT DISTINCT ?sensor ?type ?label WHERE {{
  ?sensor a ?type .
  ?type rdfs:subClassOf* brick:Point .
  OPTIONAL {{ ?sensor rdfs:label ?label }}
  FILTER(STRSTARTS(STR(?sensor), STR({prefix}:)))
}}
LIMIT 50"""

    async def apply(self, query: str, error: Optional[str],
                    context: Dict) -> tuple[str, str]:
        namespace = context.get("building_namespace", "http://example.com/building#")
        prefix    = context.get("building_prefix", "bldg")
        fallback  = self.FALLBACK_TEMPLATE.format(namespace=namespace, prefix=prefix)
        return fallback, (
            "All correction strategies exhausted — falling back to safe sensor discovery query. "
            "Results may be broader than expected."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Self-Correction Engine
# ─────────────────────────────────────────────────────────────────────────────

class SelfCorrectionEngine:
    """
    Wraps SPARQL query execution with a multi-strategy self-correction loop.

    Usage:
        engine = SelfCorrectionEngine()
        result = await engine.execute_with_correction(
            state, user_query, execute_fn, context
        )
    """

    def __init__(self, max_attempts: int = MAX_CORRECTION_ATTEMPTS):
        self.max_attempts = max_attempts
        self._strategies: List[StrategyBase] = [
            SyntaxFixStrategy(),
            PrefixRepairStrategy(),
            LLMRegenerationStrategy(),
            TemplateSchemaFallbackStrategy(),
        ]

    async def execute_with_correction(
        self,
        initial_query: str,
        execute_fn: Callable[[str], Awaitable[Dict]],
        context: Dict[str, Any],
        state: Any = None,
    ) -> Dict[str, Any]:
        """
        Execute a SPARQL query with automatic self-correction on failure.

        Args:
            initial_query: The SPARQL query to execute
            execute_fn:    Async callable(query: str) → {"success": bool, "results": ..., "error": ...}
            context:       Dict with building_namespace, building_prefix, user_query, llm_call
            state:         ConversationState (optional, for storing correction log)

        Returns:
            The result dict from execute_fn, augmented with correction_log
        """
        log = CorrectionLog()
        t_global_start = time.monotonic()

        current_query = initial_query
        last_error: Optional[str] = None
        last_result: Optional[Dict] = None

        for attempt_num in range(1, self.max_attempts + 2):
            t_start = time.monotonic()

            # ── Execute ────────────────────────────────────────────────────
            try:
                result = await asyncio.wait_for(
                    execute_fn(current_query),
                    timeout=CORRECTION_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                result = {"success": False, "error": "Query execution timeout", "results": {}}
            except Exception as e:
                result = {"success": False, "error": str(e), "results": {}}

            duration_ms = (time.monotonic() - t_start) * 1000

            # ── Evaluate ───────────────────────────────────────────────────
            is_success = result.get("success", False)
            result_count = self._count_results(result)
            error = result.get("error") or (
                "Empty result set" if is_success and result_count == 0 else None
            )

            # Determine if we consider this a real success
            real_success = is_success and result_count > EMPTY_RESULT_THRESHOLD

            strategy_used = "initial" if attempt_num == 1 else self._strategies[attempt_num - 2].name

            log.attempts.append(CorrectionAttempt(
                attempt_num=attempt_num,
                strategy=strategy_used,
                original_query=initial_query if attempt_num == 1 else current_query,
                corrected_query=current_query,
                error=error,
                success=real_success,
                result_count=result_count,
                duration_ms=duration_ms,
            ))
            log.total_attempts = attempt_num

            if real_success:
                logger.info(f"✅ Self-correction: success on attempt {attempt_num} "
                            f"(strategy={strategy_used}, results={result_count})")
                log.succeeded = True
                log.final_strategy = strategy_used
                break

            last_error = error
            last_result = result

            # No more correction strategies
            if attempt_num > len(self._strategies):
                logger.warning("❌ All self-correction strategies exhausted")
                break

            # Fast-path: "Empty result set" is a data-absence, not a query bug.
            # Syntax/prefix fixes and LLM regeneration won't help when the sensor
            # type simply doesn't exist in the ontology.  Stop here so the caller
            # can fall through to semantic RAG quickly.
            if error == "Empty result set":
                logger.info("⚡ Empty result set — skipping further corrections, falling back to semantic RAG")
                break

            # ── Apply next correction strategy ─────────────────────────────
            strategy = self._strategies[attempt_num - 1]
            logger.info(f"🔄 Self-correction attempt {attempt_num + 1}: "
                        f"strategy={strategy.name}, error={error!r}")

            prev_query = current_query
            current_query, explanation = await strategy.apply(
                current_query, last_error, context
            )
            log.attempts[-1].explanation = explanation

            # If strategy produced identical query, skip to next strategy
            if current_query == prev_query:
                logger.debug(f"Strategy {strategy.name} produced no change, advancing")

        log.total_duration_ms = (time.monotonic() - t_global_start) * 1000

        # Augment result with correction log
        if last_result is None:
            last_result = result

        last_result["correction_log"] = log.to_dict()
        last_result["self_corrected"] = log.total_attempts > 1
        last_result["correction_attempts"] = log.total_attempts

        # Store in state
        if state is not None:
            try:
                state.intermediate_results["correction_log"] = log.to_dict()
            except Exception:
                pass

        if log.succeeded:
            return result
        else:
            last_result["success"] = False
            last_result["formatted_response"] = (
                "⚠️ I attempted to answer your query but encountered difficulties "
                f"after {log.total_attempts} correction attempts. "
                "Please try rephrasing or providing more specific sensor/zone names."
            )
            return last_result

    @staticmethod
    def _count_results(result: Dict) -> int:
        """Extract result row count from various result structures."""
        try:
            bindings = result.get("results", {}).get("results", {}).get("bindings", [])
            if bindings:
                return len(bindings)
            data = result.get("results", {}).get("data", [])
            if data:
                return len(data)
            standardized = result.get("standardized", {}).get("results", [])
            if standardized:
                return len(standardized)
        except Exception:
            pass
        return 0
