"""
Phase 7.7 — Ontology Schema Auto-Detector
==========================================
Automatically detects which ontology schema(s) is used in a loaded TTL
file by sampling RDF types and scoring against Brick, RealEstateCore,
and ASHRAE 223P signature patterns — eliminating the need for operators
to manually set `schema: brick` in building_config.yaml.

Detection algorithm:
  1. Sample up to 500 subjects from the TTL using rdflib
  2. For each subject, collect its rdf:type URIs
  3. Score each schema by counting matches to known type URIs / namespaces
  4. Normalise scores. If top schema score ≥ 90% threshold → auto-set
  5. If mixed (e.g., Brick + ASHRAE 223P co-exist) → list both

Usage:
    from orchestrator.services.ontology_detector import OntologySchemaDetector

    detector = OntologySchemaDetector()
    result = await detector.detect("input/building.ttl")

    print(result.schemas)        # ["brick"]
    print(result.confidence)     # 0.96
    print(result.prefix_block)   # "PREFIX brick: <https://brickschema.org/schema/Brick#>\\n..."
    print(result.building_ns)    # "http://example.com/mybldg#"
    print(result.sensor_count)   # 142
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Schema fingerprints
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_NAMESPACES = {
    "brick": [
        "https://brickschema.org/schema/Brick#",
        "https://brickschema.org/schema/1.1/Brick#",
        "https://brickschema.org/schema/1.2/Brick#",
        "https://brickschema.org/schema/1.3/Brick#",
    ],
    "rec": [
        "https://w3id.org/rec/core/",
        "https://w3id.org/rec/",
        "https://w3id.org/realestatecore/",
    ],
    "ashrae223": [
        "http://data.ashrae.org/standard223#",
        "https://data.ashrae.org/standard223#",
    ],
    "saref": [
        "https://saref.etsi.org/core/",
        "https://saref.etsi.org/",
    ],
    "sosa": [
        "http://www.w3.org/ns/sosa/",
        "https://www.w3.org/ns/sosa/",
    ],
}

# Canonical prefixes emitted per detected schema
SCHEMA_PREFIXES = {
    "brick": (
        "PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl:   <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>\n"
        "PREFIX unit:  <http://qudt.org/vocab/unit/>\n"
        "PREFIX qudt:  <http://qudt.org/schema/qudt/>\n"
        "PREFIX sosa:  <http://www.w3.org/ns/sosa/>\n"
        "PREFIX ssn:   <http://www.w3.org/ns/ssn/>\n"
        "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
        "PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>\n"
    ),
    "rec": (
        "PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl:   <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX rec:   <https://w3id.org/rec/core/>\n"
        "PREFIX bot:   <https://w3id.org/bot#>\n"
        "PREFIX sosa:  <http://www.w3.org/ns/sosa/>\n"
        "PREFIX ssn:   <http://www.w3.org/ns/ssn/>\n"
        "PREFIX geom:  <https://w3id.org/omg#>\n"
        "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
    ),
    "ashrae223": (
        "PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl:   <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX s223:  <http://data.ashrae.org/standard223#>\n"
        "PREFIX qudt:  <http://qudt.org/schema/qudt/>\n"
        "PREFIX unit:  <http://qudt.org/vocab/unit/>\n"
    ),
}

# Brick sensor type indicators
SENSOR_CLASS_PATTERNS = [
    "Sensor",
    "Meter",
    "Setpoint",
    "Command",
    "Parameter",
    "Status",
    "Alarm",
    "Point",
    "Actuator",
]

CONFIDENCE_THRESHOLD = float(os.environ.get("ONTOLOGY_DETECT_THRESHOLD", "0.75"))


@dataclass
class DetectionResult:
    """Result from OntologySchemaDetector.detect()."""

    schemas: List[str] = field(default_factory=list)
    confidence: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    prefix_block: str = ""
    building_ns: str = ""
    building_prefix: str = "bldg"
    sensor_count: int = 0
    class_count: int = 0
    detected: bool = False
    notes: List[str] = field(default_factory=list)

    def to_config_yaml(self) -> str:
        """Returns a building_config.yaml `schema` section for auto-population."""
        schema_str = ", ".join(self.schemas) if self.schemas else "brick"
        return (
            f"# Auto-detected by OntologySchemaDetector (confidence={self.confidence:.0%})\n"
            f"building:\n"
            f'  namespace: "{self.building_ns}"\n'
            f'  prefix: "{self.building_prefix}"\n'
            f'  schema: "{schema_str}"\n'
        )

    def to_dict(self) -> Dict:
        return {
            "schemas": self.schemas,
            "confidence": round(self.confidence, 3),
            "score_breakdown": {k: round(v, 3) for k, v in self.score_breakdown.items()},
            "prefix_block": self.prefix_block,
            "building_ns": self.building_ns,
            "building_prefix": self.building_prefix,
            "sensor_count": self.sensor_count,
            "class_count": self.class_count,
            "detected": self.detected,
            "notes": self.notes,
        }


class OntologySchemaDetector:
    """
    Detects which ontology schema is used in a TTL file without manual configuration.

    Works with rdflib (always available in the OntoSage environment via rag-service).
    Also supports detection from a running GraphDB instance by sampling the SPARQL endpoint.
    """

    def __init__(self, sample_limit: int = 500, confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self._sample = sample_limit
        self._threshold = confidence_threshold

    # ─────────────────────────────────────────────────────────────────────────
    # Entry points
    # ─────────────────────────────────────────────────────────────────────────

    async def detect_from_file(self, ttl_path: str) -> DetectionResult:
        """Detect schema from a local .ttl file."""
        try:
            import rdflib

            g = rdflib.Graph()
            g.parse(ttl_path, format="turtle")
            return self._analyse_graph(g)
        except ImportError:
            return DetectionResult(notes=["rdflib not available"])
        except Exception as e:
            logger.error(f"Ontology detection error: {e}")
            return DetectionResult(notes=[f"Parse error: {e}"])

    async def detect_from_graphdb(
        self, graphdb_url: str, repository: str = "bldg"
    ) -> DetectionResult:
        """Detect schema by sampling types from a live GraphDB instance."""
        try:
            import httpx

            sparql = "SELECT DISTINCT ?type WHERE { " "  ?s a ?type . " f"}} LIMIT {self._sample}"
            url = f"{graphdb_url}/repositories/{repository}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url,
                    params={
                        "query": sparql,
                        "format": "application/sparql-results+json",
                    },
                )
                resp.raise_for_status()
                bindings = resp.json()["results"]["bindings"]
                type_uris = [b["type"]["value"] for b in bindings if b["type"]["type"] == "uri"]
            return self._analyse_type_uris(type_uris, graphdb_url)
        except Exception as e:
            logger.error(f"GraphDB detection error: {e}")
            return DetectionResult(notes=[f"GraphDB error: {e}"])

    def detect_from_string(self, ttl_content: str) -> DetectionResult:
        """Detect schema from a TTL string (for testing)."""
        try:
            import rdflib

            g = rdflib.Graph()
            g.parse(data=ttl_content, format="turtle")
            return self._analyse_graph(g)
        except Exception as e:
            return DetectionResult(notes=[f"Parse error: {e}"])

    # ─────────────────────────────────────────────────────────────────────────
    # Analysis
    # ─────────────────────────────────────────────────────────────────────────

    def _analyse_graph(self, g) -> DetectionResult:
        """Analyse an rdflib Graph to detect schema."""
        import rdflib

        RDF = rdflib.RDF
        RDFS = rdflib.RDFS

        type_uris: List[str] = []
        subject_ns: Dict[str, int] = {}
        sensor_count = 0
        class_count = 0

        for s, p, o in g.triples((None, RDF.type, None)):
            type_uri = str(o)
            type_uris.append(type_uri)
            # Count sensor types
            class_name = type_uri.split("#")[-1].split("/")[-1]
            if any(pat in class_name for pat in SENSOR_CLASS_PATTERNS):
                sensor_count += 1
            class_count += 1
            # Record subject namespace
            s_uri = str(s)
            if "#" in s_uri:
                ns = s_uri.rsplit("#", 1)[0] + "#"
            elif "/" in s_uri:
                ns = s_uri.rsplit("/", 1)[0] + "/"
            else:
                ns = s_uri
            subject_ns[ns] = subject_ns.get(ns, 0) + 1

        building_ns, building_prefix = self._infer_building_ns(subject_ns, type_uris)
        return self._analyse_type_uris(
            type_uris,
            building_ns,
            sensor_count=sensor_count,
            class_count=class_count,
            building_prefix=building_prefix,
        )

    def _analyse_type_uris(
        self,
        type_uris: List[str],
        building_ns: str = "",
        sensor_count: int = 0,
        class_count: int = 0,
        building_prefix: str = "bldg",
    ) -> DetectionResult:
        """Score schemas from a list of type URI strings."""
        if not type_uris:
            return DetectionResult(notes=["No rdf:type triples found"])

        total = len(type_uris)
        scores: Dict[str, int] = {schema: 0 for schema in SCHEMA_NAMESPACES}

        for uri in type_uris:
            for schema, namespaces in SCHEMA_NAMESPACES.items():
                if any(uri.startswith(ns) for ns in namespaces):
                    scores[schema] += 1

        norm_scores = {s: (c / total) for s, c in scores.items()}
        sorted_schemas = sorted(norm_scores.items(), key=lambda x: x[1], reverse=True)

        detected_schemas = [s for s, score in sorted_schemas if score >= self._threshold]
        top_schema, top_score = sorted_schemas[0] if sorted_schemas else ("brick", 0.0)

        if not detected_schemas and top_score > 0.3:
            detected_schemas = [top_schema]
            notes = [f"Low confidence auto-detect: {top_schema} ({top_score:.0%})"]
        elif not detected_schemas:
            detected_schemas = ["brick"]
            notes = ["Could not detect schema, defaulting to Brick"]
        else:
            notes = []

        # Build combined prefix block
        prefix_block = ""
        for schema in detected_schemas:
            if schema in SCHEMA_PREFIXES:
                prefix_block += SCHEMA_PREFIXES[schema]
        if building_ns:
            prefix_block += f"PREFIX bldg: <{building_ns}>\n"

        return DetectionResult(
            schemas=detected_schemas,
            confidence=top_score,
            score_breakdown={s: round(v, 3) for s, v in norm_scores.items() if v > 0},
            prefix_block=prefix_block,
            building_ns=building_ns,
            building_prefix=building_prefix,
            sensor_count=sensor_count,
            class_count=class_count,
            detected=top_score >= self._threshold,
            notes=notes,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Building namespace inference
    # ─────────────────────────────────────────────────────────────────────────

    def _infer_building_ns(
        self, subject_ns: Dict[str, int], type_uris: List[str]
    ) -> Tuple[str, str]:
        """
        Infer the building-specific namespace (the most frequent
        non-schema subject namespace).
        """
        schema_ns_prefixes = set()
        for nss in SCHEMA_NAMESPACES.values():
            schema_ns_prefixes.update(nss)

        # Also exclude common standard namespaces
        STANDARD_NS = {
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "http://www.w3.org/2000/01/rdf-schema#",
            "http://www.w3.org/2002/07/owl#",
            "http://www.w3.org/2001/XMLSchema#",
            "http://www.w3.org/ns/sosa/",
            "http://www.w3.org/ns/ssn/",
            "http://purl.org/dc/terms/",
            "http://qudt.org/",
            "https://qudt.org/",
        }

        candidates = {
            ns: count
            for ns, count in subject_ns.items()
            if not any(ns.startswith(p) for p in schema_ns_prefixes | STANDARD_NS) and count > 1
        }

        if not candidates:
            return "", "bldg"

        building_ns = max(candidates, key=candidates.get)
        # Infer a short prefix from the namespace
        building_prefix = self._ns_to_prefix(building_ns)
        return building_ns, building_prefix

    @staticmethod
    def _ns_to_prefix(ns: str) -> str:
        """Derive a short, clean prefix from a namespace URI."""
        ns_clean = ns.rstrip("#/")
        segment = ns_clean.split("/")[-1] or ns_clean.split("/")[-2]
        segment = re.sub(r"[^a-zA-Z0-9]", "", segment).lower()
        return segment[:8] if segment else "bldg"
