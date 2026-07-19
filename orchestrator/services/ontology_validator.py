"""
OntologyValidator — Phase 1.5
================================
Validates the GraphDB connection and repository configuration at startup,
exposing validation results for the /health endpoint.

Usage:
    from orchestrator.services.ontology_validator import ontology_validator
    result = await ontology_validator.validate()
    print(result.ok, result.details)
"""

import sys

sys.path.append("/app")

from dataclasses import dataclass, field
from typing import Any, Dict

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

GRAPHDB_QUERY_ENDPOINT = (
    f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
    f"/repositories/{settings.GRAPHDB_REPOSITORY}"
)


@dataclass
class ValidationResult:
    ok: bool
    details: Dict[str, Any] = field(default_factory=dict)
    errors: list = field(default_factory=list)


class OntologyValidator:
    """
    Validates at startup that:
      1. GraphDB is reachable.
      2. The configured repository exists.
      3. The repository contains at least one entity in the building namespace.
    """

    def __init__(self) -> None:
        self._last_result: ValidationResult = ValidationResult(ok=False)
        self._last_attempt: float = 0.0

    async def revalidate_if_needed(self, cooldown: float = 30.0) -> ValidationResult:
        """Re-run validation if the last result was NOT ok and the cooldown elapsed.

        The startup check (lifespan) can run before GraphDB accepts connections on a cold
        `docker-compose up`, caching a false negative that never self-heals. Calling this from
        /health lets the flag correct itself once GraphDB is ready, without hammering it.
        """
        import time as _t

        if not self._last_result.ok and (_t.monotonic() - self._last_attempt) >= cooldown:
            return await self.validate()
        return self._last_result

    async def validate(self) -> ValidationResult:
        """Run all validation checks and cache the result."""
        import time as _t

        self._last_attempt = _t.monotonic()
        errors = []
        details: Dict[str, Any] = {
            "graphdb_host": settings.GRAPHDB_HOST,
            "graphdb_port": settings.GRAPHDB_PORT,
            "repository": settings.GRAPHDB_REPOSITORY,
            "building_namespace": settings.BUILDING_NAMESPACE,
            "building_prefix": settings.BUILDING_PREFIX,
            "building_timezone": settings.BUILDING_TIMEZONE,
        }

        # Check 1: GraphDB reachable
        reachable = await self._check_reachability()
        details["graphdb_reachable"] = reachable
        if not reachable:
            errors.append("GraphDB is not reachable")

        # Check 2: Repository exists and has entities
        entity_count = 0
        if reachable:
            entity_count = await self._count_building_entities()
            details["entity_count"] = entity_count
            if entity_count == 0:
                errors.append(
                    f"No entities found in namespace '{settings.BUILDING_NAMESPACE}'. "
                    "Verify the ABox has been loaded into GraphDB."
                )
            else:
                logger.info(f"✅ OntologyValidator: {entity_count} building entities found")

        ok = len(errors) == 0
        details["valid"] = ok
        result = ValidationResult(ok=ok, details=details, errors=errors)
        self._last_result = result

        if ok:
            logger.info("✅ OntologyValidator: all checks passed")
        else:
            for err in errors:
                logger.warning(f"⚠️  OntologyValidator: {err}")

        return result

    @property
    def last_result(self) -> ValidationResult:
        """Return the last cached validation result."""
        return self._last_result

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    async def _check_reachability(self) -> bool:
        try:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                # A trivial ASK query to verify endpoint is reachable
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": "ASK { ?s ?p ?o }"},
                    headers={"Accept": "application/sparql-results+json"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"OntologyValidator reachability check failed: {e}")
            return False

    async def _count_building_entities(self) -> int:
        """Count distinct subjects in the building namespace."""
        query = f"""
SELECT (COUNT(DISTINCT ?s) AS ?cnt) WHERE {{
  ?s ?p ?o .
  FILTER(STRSTARTS(STR(?s), '{settings.BUILDING_NAMESPACE}'))
}}
"""
        try:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": query},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
                if bindings:
                    return int(bindings[0].get("cnt", {}).get("value", 0))
        except Exception as e:
            logger.error(f"OntologyValidator entity count failed: {e}")
        return 0


# Module-level singleton
ontology_validator = OntologyValidator()
