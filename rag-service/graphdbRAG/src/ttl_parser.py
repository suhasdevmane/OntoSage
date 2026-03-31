"""
TTL (Turtle) Parser for GraphRAG
Extracts RDF triples from Turtle ontology files while preserving prefixes and namespaces
"""
import re
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass
import logging
from rdflib import Graph, Namespace, URIRef, BNode, Literal, RDF
from rdflib.namespace import RDF, RDFS, OWL

logger = logging.getLogger(__name__)


@dataclass
class RDFTriple:
    """Represents an RDF triple with prefix information"""
    subject: str
    predicate: str
    object: str
    subject_prefix: Optional[str] = None
    predicate_prefix: Optional[str] = None
    object_prefix: Optional[str] = None
    
    def to_text(self) -> str:
        """Convert triple to natural language text for GraphRAG processing"""
        return f"{self.subject} {self.predicate} {self.object}"
    
    def to_sparql_format(self) -> str:
        """Convert triple to SPARQL-compatible format"""
        return f"{self.subject} {self.predicate} {self.object} ."


class TTLParser:
    """Parser for Turtle (TTL) ontology files"""
    
    def __init__(self, ttl_file_path: str, skip_blank_nodes: bool = False, skip_shacl: bool = True):
        """
        Initialize TTL parser
        
        Args:
            ttl_file_path: Path to the TTL file
            skip_blank_nodes: If True, exclude ALL blank nodes (NOT RECOMMENDED - removes sensor metadata!)
                             Default False - keeps ExternalReference, TimeseriesReference, etc.
            skip_shacl: If True, exclude SHACL schema validation shapes (RECOMMENDED)
                       Default True - removes sh:PropertyShape, sh:NodeShape, sh:path, etc.
        
        Recommendation for GraphRAG:
            - skip_blank_nodes=False (keep sensor metadata and timeseries links)
            - skip_shacl=True (remove schema validation noise)
        """
        self.ttl_file_path = Path(ttl_file_path)
        self.prefixes: Dict[str, str] = {}
        self.triples: List[RDFTriple] = []
        self.raw_content: str = ""
        self.skip_blank_nodes = skip_blank_nodes
        self.skip_shacl = skip_shacl
        
    def parse(self) -> Dict[str, any]:
        """
        Parse TTL file and extract prefixes and triples
        
        Returns:
            Dictionary containing prefixes, triples, and statistics
        """
        logger.info(f"Parsing TTL file: {self.ttl_file_path}")
        
        with open(self.ttl_file_path, 'r', encoding='utf-8') as f:
            self.raw_content = f.read()
        
        # Extract prefixes
        self._extract_prefixes()
        
        # Extract triples
        self._extract_triples()
        
        return {
            'prefixes': self.prefixes,
            'triples': self.triples,
            'triple_count': len(self.triples),
            'prefix_count': len(self.prefixes)
        }
    
    def _extract_prefixes(self):
        """Extract @prefix declarations from TTL file"""
        prefix_pattern = r'@prefix\s+([^:]+):\s+<([^>]+)>\s*\.'
        
        for match in re.finditer(prefix_pattern, self.raw_content):
            prefix_name = match.group(1).strip()
            namespace_uri = match.group(2).strip()
            self.prefixes[prefix_name] = namespace_uri
            logger.debug(f"Found prefix: {prefix_name} -> {namespace_uri}")
    
    def _extract_triples(self):
        """Extract RDF triples from TTL file using rdflib"""
        try:
            # Parse TTL file with rdflib
            graph = Graph()
            graph.parse(str(self.ttl_file_path), format='turtle')
            
            logger.info(f"Parsed {len(graph)} triples with rdflib")
            
            # SHACL and OWL namespaces for schema filtering
            SHACL_NS = "http://www.w3.org/ns/shacl#"
            OWL_NS = "http://www.w3.org/2002/07/owl#"
            
            # Schema types to skip (these are validation rules, not building data)
            SCHEMA_TYPES = {
                f"{SHACL_NS}NodeShape",
                f"{SHACL_NS}PropertyShape",
            }
            
            # Collect blank nodes that are SHACL shapes
            shacl_blank_nodes = set()
            if self.skip_shacl:
                for subj in graph.subjects(RDF.type, None):
                    if isinstance(subj, BNode):
                        for obj in graph.objects(subj, RDF.type):
                            if str(obj) in SCHEMA_TYPES:
                                shacl_blank_nodes.add(subj)
                                break
            
            skipped_blank = 0
            skipped_shacl = 0
            
            # Extract all triples
            for subj, pred, obj in graph:
                try:
                    # Skip SHACL schema triples if requested
                    if self.skip_shacl:
                        # Skip if predicate is SHACL property (sh:path, sh:class, etc.)
                        if str(pred).startswith(SHACL_NS):
                            skipped_shacl += 1
                            continue
                        
                        # Skip if object is SHACL type (NodeShape, PropertyShape)
                        if isinstance(obj, URIRef) and str(obj) in SCHEMA_TYPES:
                            skipped_shacl += 1
                            continue
                        
                        # Skip if subject is a known SHACL blank node
                        if isinstance(subj, BNode) and subj in shacl_blank_nodes:
                            skipped_shacl += 1
                            continue
                    
                    # Skip non-SHACL blank nodes ONLY if user explicitly requests it
                    # (Generally NOT recommended for building data!)
                    if self.skip_blank_nodes and isinstance(subj, BNode):
                        # Only skip if NOT a SHACL shape (those are already handled above)
                        if subj not in shacl_blank_nodes:
                            skipped_blank += 1
                            continue
                    
                    # Convert URIRef/BNode/Literal to string with prefix
                    subject_str, subj_prefix = self._uri_to_prefixed_name(subj, graph)
                    predicate_str, pred_prefix = self._uri_to_prefixed_name(pred, graph)
                    object_str, obj_prefix = self._uri_to_prefixed_name(obj, graph)
                    
                    triple = RDFTriple(
                        subject=subject_str,
                        predicate=predicate_str,
                        object=object_str,
                        subject_prefix=subj_prefix,
                        predicate_prefix=pred_prefix,
                        object_prefix=obj_prefix
                    )
                    
                    self.triples.append(triple)
                    
                except Exception as e:
                    logger.warning(f"Failed to convert triple: {e}")
                    continue
            
            logger.info(f"Extracted {len(self.triples)} triples (skipped {skipped_blank} data blank nodes, {skipped_shacl} SHACL schema)")
                    
        except Exception as e:
            logger.error(f"Failed to parse TTL file with rdflib: {e}")
            # Fallback to regex-based parsing
            self._extract_triples_fallback()
    
    def _uri_to_prefixed_name(self, term, graph: Graph) -> Tuple[str, Optional[str]]:
        """
        Convert rdflib term (URIRef/BNode/Literal) to prefixed name string
        
        Returns:
            Tuple of (prefixed_name, prefix)
        """
        # Handle literals
        if isinstance(term, Literal):
            return (str(term), None)
        
        # Handle blank nodes
        if isinstance(term, BNode):
            return (f"_:{term}", None)
        
        # Handle URIRefs - try to use namespace prefix
        if isinstance(term, URIRef):
            term_str = str(term)
            
            # Try each prefix to find a match
            for prefix, namespace in self.prefixes.items():
                if term_str.startswith(namespace):
                    local_name = term_str[len(namespace):]
                    return (f"{prefix}:{local_name}", prefix)
            
            # No prefix found, return full URI
            return (f"<{term_str}>", None)
        
        return (str(term), None)
    
    def _extract_triples_fallback(self):
        """Fallback regex-based triple extraction (original method)"""
        # Remove comments
        content = re.sub(r'#.*$', '', self.raw_content, flags=re.MULTILINE)
        
        # Remove prefix declarations
        content = re.sub(r'@prefix[^.]+\.', '', content)
        content = re.sub(r'@base[^.]+\.', '', content)
        
        # Simple triple extraction (handles basic Turtle syntax)
        # Format: subject predicate object .
        triple_pattern = r'([^\s]+)\s+([^\s]+)\s+([^.;]+)\s*[.;]'
        
        for match in re.finditer(triple_pattern, content):
            try:
                subject_raw = match.group(1).strip()
                predicate_raw = match.group(2).strip()
                object_raw = match.group(3).strip()
                
                # Skip empty matches
                if not subject_raw or not predicate_raw or not object_raw:
                    continue
                
                # Skip RDF type definitions that are too generic
                if subject_raw.startswith('@') or predicate_raw.startswith('@'):
                    continue
                
                # Extract prefix information
                subject, subj_prefix = self._parse_prefixed_name(subject_raw)
                predicate, pred_prefix = self._parse_prefixed_name(predicate_raw)
                obj, obj_prefix = self._parse_prefixed_name(object_raw)
                
                triple = RDFTriple(
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    subject_prefix=subj_prefix,
                    predicate_prefix=pred_prefix,
                    object_prefix=obj_prefix
                )
                
                self.triples.append(triple)
                
            except Exception as e:
                logger.warning(f"Failed to parse triple: {e}")
                continue
    
    def _parse_prefixed_name(self, name: str) -> Tuple[str, Optional[str]]:
        """
        Parse a prefixed name (e.g., brick:TemperatureSensor)
        
        Returns:
            Tuple of (full_name, prefix)
        """
        name = name.strip()
        
        # Handle URIs in angle brackets
        if name.startswith('<') and name.endswith('>'):
            return (name[1:-1], None)
        
        # Handle literals
        if name.startswith('"'):
            return (name, None)
        
        # Handle prefixed names
        if ':' in name:
            prefix, local_name = name.split(':', 1)
            if prefix in self.prefixes:
                return (name, prefix)
        
        return (name, None)
    
    def get_triples_as_text_chunks(self, chunk_size: int = 50) -> List[str]:
        """
        Convert triples to text chunks for GraphRAG processing
        
        Args:
            chunk_size: Number of triples per chunk
        
        Returns:
            List of text chunks
        """
        chunks = []
        
        for i in range(0, len(self.triples), chunk_size):
            chunk_triples = self.triples[i:i + chunk_size]
            
            # Create natural language description of triples
            chunk_text = "RDF Triples:\n"
            chunk_text += "\n".join([
                f"- {triple.to_text()}"
                for triple in chunk_triples
            ])
            
            chunks.append(chunk_text)
        
        return chunks
    
    def get_entity_types_from_ontology(self) -> List[str]:
        """
        Extract entity types from the ontology
        Looks for rdf:type, rdfs:Class, and common building ontology classes
        
        Returns:
            List of unique entity types found in the ontology
        """
        entity_types = set()
        
        # Common building ontology prefixes
        building_prefixes = ['brick', 'bot', 'saref', 'sosa', 'bldg']
        
        for triple in self.triples:
            # Look for class definitions
            if 'type' in triple.predicate.lower() or 'Class' in triple.object:
                if triple.subject_prefix in building_prefixes:
                    entity_types.add(triple.subject.split(':')[-1])
                if triple.object_prefix in building_prefixes:
                    entity_types.add(triple.object.split(':')[-1])
            
            # Extract from common predicates
            if triple.subject_prefix in building_prefixes:
                entity_types.add(triple.subject.split(':')[-1])
            if triple.object_prefix in building_prefixes and not triple.object.startswith('"'):
                entity_types.add(triple.object.split(':')[-1])
        
        # Add common building entity types
        default_types = [
            'Building', 'Floor', 'Zone', 'Room', 'Space',
            'Sensor', 'TemperatureSensor', 'HumiditySensor', 'OccupancySensor',
            'Equipment', 'HVAC', 'AHU', 'VAV', 'Damper', 'Fan',
            'Point', 'SetPoint', 'Command', 'Status',
            'Location', 'System', 'Component', 'Device'
        ]
        
        entity_types.update(default_types)
        
        return sorted(list(entity_types))
    
    def get_prefixes_as_sparql(self) -> str:
        """
        Generate SPARQL PREFIX declarations
        
        Returns:
            String of SPARQL PREFIX statements
        """
        prefix_lines = []
        for prefix, namespace in self.prefixes.items():
            prefix_lines.append(f"PREFIX {prefix}: <{namespace}>")
        return "\n".join(prefix_lines)
    
    def export_for_graphrag(self, output_dir: Path) -> Dict[str, Path]:
        """
        Export parsed TTL data in format suitable for GraphRAG ingestion
        
        Args:
            output_dir: Directory to write output files
        
        Returns:
            Dictionary of output file paths
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_files = {}
        
        # 1. Export triples as text chunks
        chunks_file = output_dir / "ttl_chunks.txt"
        chunks = self.get_triples_as_text_chunks(chunk_size=100)
        with open(chunks_file, 'w', encoding='utf-8') as f:
            f.write("\n\n---CHUNK_SEPARATOR---\n\n".join(chunks))
        output_files['chunks'] = chunks_file
        
        # 2. Export prefixes
        prefixes_file = output_dir / "prefixes.txt"
        with open(prefixes_file, 'w', encoding='utf-8') as f:
            f.write(self.get_prefixes_as_sparql())
        output_files['prefixes'] = prefixes_file
        
        # 3. Export entity types
        entity_types_file = output_dir / "entity_types.txt"
        entity_types = self.get_entity_types_from_ontology()
        with open(entity_types_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(entity_types))
        output_files['entity_types'] = entity_types_file
        
        # 4. Export raw triples for reference
        triples_file = output_dir / "raw_triples.txt"
        with open(triples_file, 'w', encoding='utf-8') as f:
            for triple in self.triples:
                f.write(f"{triple.to_sparql_format()}\n")
        output_files['triples'] = triples_file
        
        logger.info(f"Exported {len(self.triples)} triples to {output_dir}")
        
        return output_files


def parse_ttl_for_graphrag(ttl_file_path: str, output_dir: Optional[str] = None) -> Dict:
    """
    Convenience function to parse TTL file and prepare for GraphRAG
    
    Args:
        ttl_file_path: Path to TTL ontology file
        output_dir: Optional directory to export processed files
    
    Returns:
        Dictionary containing parsed data and statistics
    """
    parser = TTLParser(ttl_file_path)
    parse_result = parser.parse()
    
    if output_dir:
        output_files = parser.export_for_graphrag(Path(output_dir))
        parse_result['output_files'] = output_files
    
    return parse_result


if __name__ == "__main__":
    # Example usage
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        ttl_file = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else "./ttl_export"
        
        result = parse_ttl_for_graphrag(ttl_file, output_dir)
        
        print(f"\n✅ Parsed TTL file successfully!")
        print(f"   - Prefixes: {result['prefix_count']}")
        print(f"   - Triples: {result['triple_count']}")
        print(f"   - Output directory: {output_dir}")
    else:
        print("Usage: python ttl_parser.py <ttl_file> [output_dir]")
