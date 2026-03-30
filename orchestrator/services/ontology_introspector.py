"""
OntologyIntrospector — Phase 1.4
=================================
Dynamically discovers entity types, namespaces, and sensor classes from a
live GraphDB repository.  Removes the need for hardcoded class lists in
prompts and query templates.

Usage:
    from orchestrator.services.ontology_introspector import OntologyIntrospector
    intro = OntologyIntrospector()
    await intro.initialize()               # called once at startup
    classes  = intro.sensor_classes        # list of Brick class IRIs
    ns_map   = intro.namespace_map         # dict {prefix: uri}
"""
import sys
sys.path.append('/app')

import httpx
from typing import Dict, List, Optional
from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

GRAPHDB_QUERY_ENDPOINT = (
    f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
    f"/repositories/{settings.GRAPHDB_REPOSITORY}"
)


class OntologyIntrospector:
    """
    Queries the live GraphDB repository to discover:
      - All distinct rdf:type classes used in the ABox.
      - All namespaces / prefixes referenced.
      - Brick / S223 / custom sensor-like classes.
    Results are cached in instance variables after the first call to
    `initialize()`.
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self.entity_types: List[str] = []       # all distinct rdf:type IRIs
        self.sensor_classes: List[str] = []     # subsets matching Sensor pattern
        self.namespace_map: Dict[str, str] = {} # prefix → base URI
        self.building_namespace: str = settings.BUILDING_NAMESPACE
        self.building_prefix: str = settings.BUILDING_PREFIX

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Run discovery queries.  Safe to call multiple times (idempotent)."""
        if self._initialized:
            return
        logger.info("🔍 OntologyIntrospector: starting discovery …")
        await self._discover_entity_types()
        await self._discover_namespaces()
        self._extract_sensor_classes()
        self._initialized = True
        logger.info(
            f"✅ OntologyIntrospector ready: "
            f"{len(self.entity_types)} types, "
            f"{len(self.sensor_classes)} sensor classes, "
            f"{len(self.namespace_map)} namespaces"
        )

    async def refresh(self) -> None:
        """Force re-discovery (e.g. after ontology reload)."""
        self._initialized = False
        await self.initialize()

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    async def _discover_entity_types(self) -> None:
        """
        Fetch all distinct rdf:type values used in the building namespace.
        Only needs to run at startup or after ontology updates.
        """
        query = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT DISTINCT ?type WHERE {{
  ?s rdf:type ?type .
  FILTER(STRSTARTS(STR(?s), '{self.building_namespace}'))
}}
ORDER BY STR(?type)
LIMIT 200
"""
        results = await self._sparql_select(query)
        self.entity_types = [
            row["type"]["value"]
            for row in results
            if "type" in row
        ]
        logger.info(f"  discovered {len(self.entity_types)} entity types")

    async def _discover_namespaces(self) -> None:
        """
        Infer namespaces from the distinct IRIs used as predicates and types.
        Builds a prefix→base-URI map (best-effort, without GraphDB's namespace API).
        """
        known_ns = {
            "brick": "https://brickschema.org/schema/Brick#",
            "rdf":   "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs":  "http://www.w3.org/2000/01/rdf-schema#",
            "owl":   "http://www.w3.org/2002/07/owl#",
            "xsd":   "http://www.w3.org/2001/XMLSchema#",
            "skos":  "http://www.w3.org/2004/02/skos/core#",
            "sosa":  "http://www.w3.org/ns/sosa/",
            "rec":   "https://w3id.org/rec#",
            "ref":   "https://brickschema.org/schema/Brick/ref#",
            "s223":  "http://data.ashrae.org/standard223#",
            "qudt":  "http://qudt.org/schema/qudt/",
            "unit":  "http://qudt.org/vocab/unit/",
        }
        # Add the building-specific namespace
        known_ns[self.building_prefix] = self.building_namespace
        self.namespace_map = known_ns

        # Try to discover any extra namespaces used by predicates
        query = """
SELECT DISTINCT ?p WHERE { ?s ?p ?o . } LIMIT 300
"""
        try:
            rows = await self._sparql_select(query)
            for row in rows:
                iri = row.get("p", {}).get("value", "")
                if not iri:
                    continue
                # Split on last '#' or '/'
                if "#" in iri:
                    base = iri.rsplit("#", 1)[0] + "#"
                elif "/" in iri:
                    base = iri.rsplit("/", 1)[0] + "/"
                else:
                    continue
                # Only add if we don't already know this base
                if base not in self.namespace_map.values():
                    short = iri.split("/")[-1].split("#")[-1]
                    # Use a sanitized prefix candidate
                    candidate = "ns_" + short[:8].lower().replace("-", "_")
                    if candidate not in self.namespace_map:
                        self.namespace_map[candidate] = base
        except Exception as e:
            logger.warning(f"OntologyIntrospector: namespace auto-discovery partial: {e}")

    def _extract_sensor_classes(self) -> None:
        """
        Filter entity_types to those that look like sensor / point classes
        based on IRI token matching.
        """
        sensor_keywords = ["sensor", "setpoint", "alarm", "command", "status", "meter", "point"]
        self.sensor_classes = [
            t for t in self.entity_types
            if any(kw in t.lower() for kw in sensor_keywords)
        ]
        logger.info(f"  identified {len(self.sensor_classes)} sensor-like classes")

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    async def _sparql_select(self, query: str) -> List[Dict]:
        """Execute a SPARQL SELECT against GraphDB and return bindings list."""
        try:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": query},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("results", {}).get("bindings", [])
        except Exception as e:
            logger.error(f"OntologyIntrospector SPARQL error: {e}")
            return []

    # ------------------------------------------------------------------
    # Convenience helpers for other services
    # ------------------------------------------------------------------

    def get_sensor_class_labels(self) -> List[str]:
        """Return local names of sensor classes (e.g. 'Air_Temperature_Sensor')."""
        labels = []
        for iri in self.sensor_classes:
            local = iri.split("#")[-1] if "#" in iri else iri.split("/")[-1]
            if local:
                labels.append(local)
        return labels

    def build_sparql_prefix_block(self) -> str:
        """Return a SPARQL PREFIX block from the discovered namespace map."""
        lines = [f"PREFIX {pfx}: <{uri}>" for pfx, uri in self.namespace_map.items()]
        return "\n".join(lines)

    def is_ready(self) -> bool:
        return self._initialized


# Module-level singleton (lazy initialised)
ontology_introspector = OntologyIntrospector()
