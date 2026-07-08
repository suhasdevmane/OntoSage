"""
concept_resolver.py — HBCO lay-term resolution for the dialogue/SPARQL pipeline.

Translates lay-language terms in a user query into structured concept metadata
(brick classes + recipe IDs) from the Human-Building Conversation Ontology (HBCO).

Integration points:
  - dialogue_agent: calls resolve() after LLM entity extraction; stores results
    in state.intermediate_results["concepts"] (NEW reserved key).
  - sparql_agent._infer_class: checks concepts FIRST, falls back to static map.
  - analytics node: if concepts carry a recipe_id, fetches recipe thresholds to
    enrich the analytics prompt with numeric context.

Caching: concept map loaded from GraphDB once and cached in Redis (key
  cache:concept:hbco_all, 24h TTL). Cache is shared across requests.

Routing-precedence safety: this module ONLY affects class inference and recipe
  selection.  It does NOT affect intent routing — routing-precedence rules in
  CLAUDE.md (report-intake > capability, actuation → control-decline, etc.)
  must continue to run unchanged in dialogue_agent and _route_from_dialogue.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_HBCO = "http://ontosage.org/hbco#"
_CONCEPT_CACHE_KEY = "cache:concept:hbco_all"
_CONCEPT_CACHE_TTL = 86400  # 24 hours

_SPARQL_LOAD_CONCEPTS = """\
PREFIX hbco: <http://ontosage.org/hbco#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?concept ?layTerm ?brickClass ?recipe ?confidence WHERE {
  ?concept a hbco:Concept ;
           hbco:layTerm ?layTerm .
  OPTIONAL { ?concept hbco:mapsToBrickClass ?brickClass }
  OPTIONAL { ?concept hbco:requiresRecipe   ?recipe }
  OPTIONAL { ?concept hbco:confidence       ?confidence }
}"""


@dataclass
class ConceptMatch:
    concept_id: str
    lay_term: str
    brick_classes: List[str] = field(default_factory=list)
    recipe_id: Optional[str] = None
    confidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "lay_term": self.lay_term,
            "brick_classes": self.brick_classes,
            "recipe_id": self.recipe_id,
            "confidence": self.confidence,
        }


def _concept_id_from_uri(uri: str) -> str:
    """e.g. 'http://ontosage.org/hbco#stuffiness' -> 'stuffiness'"""
    return uri.split("#")[-1].split("/")[-1]


def _brick_local(uri: str) -> str:
    """e.g. 'https://brickschema.org/schema/Brick#CO2_Level_Sensor' -> 'brick:CO2_Level_Sensor'"""
    if "brickschema.org/schema/Brick#" in uri:
        return "brick:" + uri.split("#")[-1]
    return uri


def _parse_bindings(bindings: list) -> Dict[str, ConceptMatch]:
    """Group SPARQL result rows by concept URI -> ConceptMatch."""
    by_concept: Dict[str, Dict[str, Any]] = {}
    for row in bindings:
        curi = row.get("concept", {}).get("value", "")
        if not curi:
            continue
        if curi not in by_concept:
            by_concept[curi] = {
                "concept_id": _concept_id_from_uri(curi),
                "lay_terms": set(),
                "brick_classes": set(),
                "recipe_id": None,
                "confidence": "",
            }
        entry = by_concept[curi]
        lt = row.get("layTerm", {}).get("value", "")
        if lt:
            entry["lay_terms"].add(lt.lower())
        bc = row.get("brickClass", {}).get("value", "")
        if bc:
            entry["brick_classes"].add(_brick_local(bc))
        recipe = row.get("recipe", {}).get("value", "")
        if recipe and not entry["recipe_id"]:
            entry["recipe_id"] = recipe
        conf = row.get("confidence", {}).get("value", "")
        if conf:
            entry["confidence"] = conf

    # Convert to list-of-dicts for JSON serialisation
    result: Dict[str, Dict[str, Any]] = {}
    for curi, entry in by_concept.items():
        result[curi] = {
            "concept_id": entry["concept_id"],
            "lay_terms": sorted(entry["lay_terms"]),
            "brick_classes": sorted(entry["brick_classes"]),
            "recipe_id": entry["recipe_id"],
            "confidence": entry["confidence"],
        }
    return result


class ConceptResolver:
    """Resolve lay-language terms in a query to HBCO concept metadata."""

    async def _load_concept_map(self) -> Dict[str, Dict[str, Any]]:
        """Fetch full concept map from Redis cache or GraphDB. Returns {concept_uri: entry}."""
        try:
            from orchestrator.redis_manager import redis_manager

            cached = await redis_manager.get_cache(_CONCEPT_CACHE_KEY)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as e:
            logger.debug(f"[concept_resolver] Redis unavailable: {e}")

        data = await self._fetch_from_graphdb()
        if data:
            try:
                from orchestrator.redis_manager import redis_manager

                await redis_manager.set_cache(_CONCEPT_CACHE_KEY, data, ttl=_CONCEPT_CACHE_TTL)
            except Exception as e:
                logger.debug(f"[concept_resolver] Redis cache write skipped: {e}")
        return data

    async def _fetch_from_graphdb(self) -> Dict[str, Dict[str, Any]]:
        """Run SPARQL against GraphDB to load all HBCO concepts + lay terms."""
        endpoint = (
            f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
            f"/repositories/{settings.GRAPHDB_REPOSITORY}"
        )
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    endpoint,
                    content=_SPARQL_LOAD_CONCEPTS.encode(),
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[concept_resolver] GraphDB returned {resp.status_code}"
                    )
                    return {}
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
        except Exception as e:
            logger.warning(f"[concept_resolver] failed to fetch concepts from GraphDB: {e}")
            return {}

        result = _parse_bindings(bindings)
        logger.info(f"[concept_resolver] loaded {len(result)} concept(s) from GraphDB")
        return result

    async def resolve(self, text: str) -> List[ConceptMatch]:
        """Find all HBCO concepts whose lay terms appear in the query text.

        Returns a list of ConceptMatch objects ordered by lay_term length
        (longer, more specific matches first).
        """
        if not text:
            return []

        normalized = text.lower()
        concept_map = await self._load_concept_map()
        if not concept_map:
            return []

        matches: List[ConceptMatch] = []
        for entry in concept_map.values():
            for lay_term in entry.get("lay_terms", []):
                if not lay_term:
                    continue
                # Whole-word boundary check to avoid 'hot' matching 'shot'
                pattern = r"(?<![a-z])" + re.escape(lay_term) + r"(?![a-z])"
                if re.search(pattern, normalized):
                    matches.append(
                        ConceptMatch(
                            concept_id=entry["concept_id"],
                            lay_term=lay_term,
                            brick_classes=list(entry.get("brick_classes", [])),
                            recipe_id=entry.get("recipe_id"),
                            confidence=entry.get("confidence", ""),
                        )
                    )
                    break  # one match per concept is enough

        # Sort: longer lay term first (more specific), then by confidence
        _conf_order = {"high": 0, "medium": 1, "low": 2, "": 3}
        matches.sort(
            key=lambda m: (-len(m.lay_term), _conf_order.get(m.confidence, 3))
        )
        return matches

    async def invalidate_cache(self) -> None:
        """Clear the Redis concept map cache (call after HBCO TTL is re-uploaded)."""
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.delete_cache(_CONCEPT_CACHE_KEY)
            logger.info("[concept_resolver] concept cache cleared")
        except Exception as e:
            logger.debug(f"[concept_resolver] cache clear skipped: {e}")


# Module-level singleton
concept_resolver = ConceptResolver()
