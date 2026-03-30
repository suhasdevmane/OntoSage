"""
PromptBuilder — C.2 Dynamic Prompt Templates
=============================================
Generates SPARQL and SQL prompts dynamically from live building metadata,
eliminating hard-coded Abacws/Brick examples that mislead other buildings.

The builder consults three sources at call time:
  1. OntologyIntrospector  — discovered entity classes and namespaces
  2. Adapter dialect hints — correct SQL syntax for MySQL vs. PostgreSQL
  3. settings              — building namespace, prefix, timezone

Usage:
    from orchestrator.services.prompt_builder import PromptBuilder

    builder = PromptBuilder()

    sparql_hints = builder.sparql_system_hints()   # inject into SPARQL prompt
    sql_hints    = builder.sql_dialect_hints()      # inject into SQL prompt
    intent_hints = builder.intent_context_hints(sensor_types, building_id)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from shared.config import settings

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Builds context-aware prompt fragments from live building metadata.

    All methods return *strings* ready for f-string injection into existing
    LLM prompts.  They are pure (no await) so they can be called from sync
    and async contexts alike; heavy discovery is done at startup by
    OntologyIntrospector, not here.
    """

    # ------------------------------------------------------------------
    # SPARQL helpers
    # ------------------------------------------------------------------

    def sparql_system_hints(
        self,
        sensor_classes: Optional[List[str]] = None,
        namespace_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Return a text block describing this building's ontology to inject
        near the top of a SPARQL generation prompt.

        Args:
            sensor_classes: IRI list from OntologyIntrospector.sensor_classes
            namespace_map:  {prefix: uri} from OntologyIntrospector.namespace_map
        """
        ns = settings.BUILDING_NAMESPACE
        prefix = settings.BUILDING_PREFIX
        building_name = settings.BUILDING_NAME
        schema = self._detect_schema_label(namespace_map or {}, ns)

        lines = [
            f"=== BUILDING ONTOLOGY PROFILE ===",
            f"Building: {building_name}",
            f"Ontology schema: {schema}",
            f"Building namespace: {ns}",
            f"Building prefix:    {prefix}:",
        ]

        if sensor_classes:
            compact = self._compact_iris(sensor_classes, namespace_map or {})
            lines.append(f"Known sensor/point classes ({len(compact)}): "
                         + ", ".join(compact[:15])
                         + (" …" if len(compact) > 15 else ""))
        else:
            lines.append("Known sensor/point classes: (discovery pending — use generic Brick/REC patterns)")

        if namespace_map:
            ns_lines = [f"  PREFIX {p}: <{u}>" for p, u in list(namespace_map.items())[:10]]
            lines.append("Active namespaces:\n" + "\n".join(ns_lines))

        lines.append(
            f"\nUSE PREFIX '{prefix}:' for all building-specific instances. "
            f"Do NOT use hardcoded example URIs from other buildings."
        )
        return "\n".join(lines)

    def sparql_prefix_block(
        self, namespace_map: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Return a SPARQL PREFIX block covering the building namespace plus
        any additional namespaces discovered by OntologyIntrospector.
        """
        declared: Dict[str, str] = {}

        # Always include building namespace
        declared[settings.BUILDING_PREFIX] = settings.BUILDING_NAMESPACE

        # Add discovered namespaces (up to 20)
        if namespace_map:
            for p, u in list(namespace_map.items())[:20]:
                if p not in declared:
                    declared[p] = u

        return "\n".join(f"PREFIX {p}: <{u}>" for p, u in declared.items())

    # ------------------------------------------------------------------
    # SQL helpers
    # ------------------------------------------------------------------

    def sql_dialect_hints(self, adapter=None) -> str:
        """
        Return SQL dialect hints for the active storage adapter.

        Args:
            adapter: An adapter instance exposing .get_dialect_hints() (optional).
                     Falls back to MySQL hints if not supplied.
        """
        if adapter and hasattr(adapter, "get_dialect_hints"):
            try:
                return adapter.get_dialect_hints()
            except Exception as e:
                logger.debug(f"PromptBuilder: adapter.get_dialect_hints() failed: {e}")

        # Fallback: MySQL (the default Building 1 backend)
        return (
            "MySQL dialect rules:\n"
            "- Use backtick-quoted identifiers for UUID column names: `uuid-here`\n"
            "- Current time: NOW()   Current date: CURDATE()\n"
            "- Date arithmetic: CURDATE() - INTERVAL N DAY  /  NOW() - INTERVAL N HOUR\n"
            "- String functions: CONCAT(), LOWER(), UPPER(), TRIM()\n"
            "- Avoid ILIKE (MySQL only has LIKE, case-insensitive by default on utf8)"
        )

    def sql_schema_hints(self, schema_text: str = "") -> str:
        """
        Augment a schema text with building-specific context (timezone, units).
        """
        tz = settings.BUILDING_TIMEZONE
        lines = [schema_text] if schema_text else []
        lines.append(
            f"\nBuilding timezone: {tz}  "
            f"(convert Datetime to local time using CONVERT_TZ or AT TIME ZONE if needed)"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Intent / dialogue helpers
    # ------------------------------------------------------------------

    def intent_context_hints(
        self,
        sensor_types: Optional[List[str]] = None,
        building_id: str = "",
    ) -> str:
        """
        Return a short text block for the intent-detection prompt listing
        available sensor types for this building.
        """
        bname = settings.BUILDING_NAME
        bid = building_id or settings.BUILDING_ID
        lines = [f"Building: {bname} (id={bid})"]
        if sensor_types:
            lines.append("Available sensor types: " + ", ".join(sensor_types[:20]))
        else:
            lines.append("Available sensor types: (not yet discovered — use general sensor terms)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_schema_label(namespace_map: Dict[str, str], building_ns: str) -> str:
        """Guess the primary ontology schema from namespace map content."""
        for uri in namespace_map.values():
            if "brickschema" in uri:
                return "Brick Schema"
            if "w3id.org/rec" in uri:
                return "RealEstateCore (REC)"
            if "data.ashrae.org/standard223" in uri:
                return "ASHRAE 223P"
        return "Brick Schema"  # safe default

    @staticmethod
    def _compact_iris(iris: List[str], namespace_map: Dict[str, str]) -> List[str]:
        """Replace known namespace URIs with their prefixes for readability."""
        # Build reverse map: uri → prefix
        reverse = {v: k for k, v in namespace_map.items()}
        result = []
        for iri in iris:
            for base_uri, pref in reverse.items():
                if iri.startswith(base_uri):
                    result.append(f"{pref}:{iri[len(base_uri):]}")
                    break
            else:
                result.append(iri)
        return result


# Module-level singleton — cheap to construct; do not initialize at import time
_prompt_builder: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    """Return the module-level PromptBuilder singleton."""
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = PromptBuilder()
    return _prompt_builder
