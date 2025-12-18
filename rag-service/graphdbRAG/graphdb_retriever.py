"""
GraphDB RAG Retriever - Implements Ontotext 2-step retrieval pattern
Step 1: Entity retrieval via vector similarity (GraphDB built-in)
Step 2: Bounded context retrieval via SPARQL (triples around entities)
"""
import sys
sys.path.append('/app')

import httpx
from typing import Dict, Any, List, Optional, Tuple
import json
import re
from urllib.parse import quote
from shared.utils import get_logger
from shared.config import settings

logger = get_logger(__name__)


class GraphDBRetriever:
    """
    GraphDB-based RAG retriever following Ontotext technique:
    1. Vector similarity search returns entity IRIs (not text chunks)
    2. SPARQL fetches "bounded context" - triples within N hops of entities
    3. Returns structured graph data with prefixes for SPARQL generation
    """
    
    def __init__(
        self,
        graphdb_url: str = None,
        repository: str = None,
        similarity_index: str = None,
        username: str = None,
        password: str = None
    ):
        self.graphdb_url = graphdb_url or settings.GRAPHDB_URL
        self.repository = repository or settings.GRAPHDB_REPOSITORY
        self.similarity_index = similarity_index or settings.GRAPHDB_SIMILARITY_INDEX
        self.username = username or settings.GRAPHDB_USER
        self.password = password or settings.GRAPHDB_PASSWORD
        
        # Endpoints
        self.sparql_endpoint = f"{self.graphdb_url}/repositories/{self.repository}"
        self.update_endpoint = f"{self.graphdb_url}/repositories/{self.repository}/statements"
        
        # Standard prefixes used in the ontology
        self.prefixes = {
            'brick': 'https://brickschema.org/schema/Brick#',
            'bldg': 'http://abacwsbuilding.cardiff.ac.uk/abacws#',
            'rec': 'https://w3id.org/rec#',
            'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
            'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
            'owl': 'http://www.w3.org/2002/07/owl#',
            'skos': 'http://www.w3.org/2004/02/skos/core#',
            'sosa': 'http://www.w3.org/ns/sosa/',
            'xsd': 'http://www.w3.org/2001/XMLSchema#',
            'tag': 'https://brickschema.org/schema/BrickTag#',
            'ashrae': 'http://data.ashrae.org/standard223#',
            'bacnet': 'http://data.ashrae.org/bacnet/2020#',
            'schema': 'http://schema.org/',
            'dcterms': 'http://purl.org/dc/terms/',
            'ref': 'https://brickschema.org/schema/Brick/ref#',
            'qudt': 'http://qudt.org/schema/qudt/',
            'unit': 'http://qudt.org/vocab/unit/',
            'quantitykind': 'http://qudt.org/vocab/quantitykind/'
        }
        
        logger.info(f"GraphDB Retriever initialized: {self.graphdb_url}/{self.repository}")
    
    def _get_auth(self) -> Optional[Tuple[str, str]]:
        """Get HTTP basic auth tuple"""
        if self.username and self.password:
            return (self.username, self.password)
        return None
    
    async def _retrieve_by_identifiers(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Fallback: Search for entities containing identifiers (words with digits) from the query.
        Useful when vector similarity fails for specific IDs like '5.11'.
        """
        # Improved tokenization: Split by whitespace, strip punctuation, but keep dots/underscores inside
        # This preserves "5.12" or "Sensor_1" as single tokens
        raw_tokens = query.split()
        identifiers = []
        for token in raw_tokens:
            # Strip trailing/leading punctuation
            clean_token = token.strip(".,:;?!()[]{}'\"")
            # Check if it has digits (e.g. "5.12", "Sensor_1")
            if any(c.isdigit() for c in clean_token) and len(clean_token) > 1:
                identifiers.append(clean_token)
        
        if not identifiers:
            return []
            
        logger.info(f"🔍 Detected identifiers in query: {identifiers}")
        
        try:
            # Build SPARQL filters
            # We want to match either the label OR the URI string (local name)
            filters = []
            for ident in identifiers:
                # Escape single quotes
                safe_ident = ident.replace("'", "\\'")
                # Match label (contains) OR URI (contains)
                # This ensures we find "Zone_Air_Humidity_Sensor_5.12" even if label is different
                filters.append(f"(CONTAINS(LCASE(?label), '{safe_ident.lower()}') || CONTAINS(LCASE(STR(?entity)), '{safe_ident.lower()}'))")
            
            filter_clause = " || ".join(filters)
            
            sparql_query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?entity ?label WHERE {{
    ?entity rdfs:label ?label .
    FILTER({filter_clause})
}}
LIMIT {top_k}
"""
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.sparql_endpoint,
                    auth=self._get_auth(),
                    headers={'Accept': 'application/sparql-results+json'},
                    data={'query': sparql_query}
                )
                response.raise_for_status()
                results = response.json()
                
            entities = []
            for binding in results.get('results', {}).get('bindings', []):
                entity = {
                    'iri': binding['entity']['value'],
                    'score': 1.0,  # High score for exact identifier match
                    'label': binding.get('label', {}).get('value', '')
                }
                entities.append(entity)
                
            logger.info(f"✅ Retrieved {len(entities)} entities via identifier search")
            return entities
            
        except Exception as e:
            logger.error(f"Identifier retrieval failed: {e}")
            return []

    async def retrieve_entities(
        self,
        query: str,
        top_k: int = 20,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Step 1: Entity Retrieval via GraphDB Similarity Index + Identifier Search
        
        Args:
            query: User's natural language query
            top_k: Number of entities to retrieve (default increased to 20)
            min_score: Minimum similarity score threshold
            
        Returns:
            List of entity dicts with 'iri', 'score', 'label'
        """
        entities = []
        
        # 1. Run Identifier Search (Fallback/Priority)
        identifier_entities = await self._retrieve_by_identifiers(query, top_k=5)
        entities.extend(identifier_entities)
        
        try:
            # GraphDB similarity search SPARQL query
            # Note: We clean the query of newlines for the similarity index
            clean_query = query.replace('\n', ' ').replace('\r', ' ').strip()
            
            similarity_query = f"""
PREFIX : <http://www.ontotext.com/graphdb/similarity/>
PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?entity ?score ?label WHERE {{
    ?search a similarity:{self.similarity_index} ;
           :searchTerm "{clean_query}" ;
           :documentResult ?result .
    ?result :value ?entity ;
           :score ?score .
    OPTIONAL {{ ?entity rdfs:label ?label }}
    FILTER(?score >= {min_score})
}}
ORDER BY DESC(?score)
LIMIT {top_k}
"""
            
            logger.info(f"🔍 Entity retrieval query: {clean_query[:100]}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.sparql_endpoint,
                    auth=self._get_auth(),
                    headers={'Accept': 'application/sparql-results+json'},
                    data={'query': similarity_query}
                )
                response.raise_for_status()
                results = response.json()
            
            # Parse results
            sim_entities = []
            for binding in results.get('results', {}).get('bindings', []):
                entity = {
                    'iri': binding['entity']['value'],
                    'score': float(binding['score']['value']),
                    'label': binding.get('label', {}).get('value', '')
                }
                sim_entities.append(entity)
            
            # Merge results (deduplicate)
            existing_iris = {e['iri'] for e in entities}
            for ent in sim_entities:
                if ent['iri'] not in existing_iris:
                    entities.append(ent)
                    existing_iris.add(ent['iri'])
            
            # Sort by score (identifier matches have 1.0)
            entities.sort(key=lambda x: x['score'], reverse=True)
            entities = entities[:top_k + 5] # Allow a bit more
            
            logger.info(f"✅ Retrieved {len(entities)} entities (scores: {[e['score'] for e in entities[:3]]})")
            logger.info(f"🔗 Entity IRIs: {[e['iri'] for e in entities[:5]]}")
            return entities
            
        except Exception as e:
            logger.error(f"Entity retrieval failed: {e}", exc_info=True)
            return entities
    
    async def get_bounded_context(
        self,
        entity_iris: List[str],
        hops: int = 2,
        max_triples_per_entity: int = 500
    ) -> Dict[str, Any]:
        """
        Step 2: Bounded Context Retrieval via SPARQL
        
        Fetches triples within N hops of the given entities.
        
        Args:
            entity_iris: List of entity IRIs from step 1
            hops: Number of graph hops (1 or 2 recommended)
            max_triples_per_entity: Limit triples to prevent explosion
            
        Returns:
            Dict with 'triples', 'prefixes', 'entities', 'summary'
        """
        if not entity_iris:
            return {'triples': [], 'prefixes': {}, 'entities': [], 'summary': ''}
        
        try:
            # Build VALUES clause for multiple entities
            values_clause = " ".join([f"<{iri}>" for iri in entity_iris])
            
            # SPARQL query to get bounded context
            if hops == 1:
                # 1-hop: Direct properties of entities
                context_query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rec: <https://w3id.org/rec#>

SELECT DISTINCT ?s ?p ?o WHERE {{
    VALUES ?entity {{ {values_clause} }}
    
    {{
        # Entity as subject
        ?entity ?p ?o .
        BIND(?entity AS ?s)
    }} UNION {{
        # Entity as object
        ?s ?p ?entity .
        BIND(?entity AS ?o)
    }}
}}
LIMIT {max_triples_per_entity * len(entity_iris)}
"""
            else:
                # 2-hop: Extended neighborhood
                context_query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rec: <https://w3id.org/rec#>

SELECT DISTINCT ?s ?p ?o WHERE {{
    VALUES ?entity {{ {values_clause} }}
    
    {{
        # 1-hop from entity
        ?entity ?p1 ?o1 .
        BIND(?entity AS ?s)
        BIND(?p1 AS ?p)
        BIND(?o1 AS ?o)
    }} UNION {{
        ?s1 ?p1 ?entity .
        BIND(?s1 AS ?s)
        BIND(?p1 AS ?p)
        BIND(?entity AS ?o)
    }} UNION {{
        # 2-hop from entity (limited)
        ?entity ?p1 ?intermediate .
        FILTER(?p1 != rdf:type)
        ?intermediate ?p2 ?o2 .
        # Removed FILTER(isIRI(?intermediate)) to allow traversal through Blank Nodes
        BIND(?intermediate AS ?s)
        BIND(?p2 AS ?p)
        BIND(?o2 AS ?o)
    }}
}}
LIMIT {max_triples_per_entity * len(entity_iris)}
"""
            
            logger.info(f"🔗 Fetching {hops}-hop context for {len(entity_iris)} entities")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.sparql_endpoint,
                    auth=self._get_auth(),
                    headers={'Accept': 'application/sparql-results+json'},
                    data={'query': context_query}
                )
                response.raise_for_status()
                results = response.json()
            
            # Parse triples
            triples = []
            used_prefixes = set()
            
            for binding in results.get('results', {}).get('bindings', []):
                s_val = binding['s']['value']
                p_val = binding['p']['value']
                o_binding = binding['o']
                
                # Track which prefixes are used
                for prefix, namespace in self.prefixes.items():
                    if namespace in s_val or namespace in p_val:
                        used_prefixes.add(prefix)
                    if o_binding['type'] == 'uri' and namespace in o_binding['value']:
                        used_prefixes.add(prefix)
                
                # Format triple for readability
                s = self._shorten_iri(s_val)
                p = self._shorten_iri(p_val)
                
                if o_binding['type'] == 'uri':
                    o = self._shorten_iri(o_binding['value'])
                elif o_binding['type'] == 'literal':
                    o_val = o_binding['value']
                    # Handle datatype
                    if 'datatype' in o_binding:
                        dt = self._shorten_iri(o_binding['datatype'])
                        o = f'"{o_val}"^^{dt}'
                    elif 'xml:lang' in o_binding:
                        lang = o_binding['xml:lang']
                        o = f'"{o_val}"@{lang}'
                    else:
                        o = f'"{o_val}"'
                else:
                    o = o_binding['value']
                
                triples.append({'subject': s, 'predicate': p, 'object': o})
            
            # Build prefix declarations
            prefix_declarations = {
                prefix: namespace 
                for prefix, namespace in self.prefixes.items() 
                if prefix in used_prefixes
            }
            
            # Create summary text for LLM
            summary = self._create_context_summary(triples, entity_iris)
            
            logger.info(f"✅ Retrieved {len(triples)} triples with {len(prefix_declarations)} prefixes")
            
            return {
                'triples': triples,
                'prefixes': prefix_declarations,
                'entities': entity_iris,
                'summary': summary,
                'triple_count': len(triples)
            }
            
        except Exception as e:
            logger.error(f"Bounded context retrieval failed: {e}", exc_info=True)
            return {'triples': [], 'prefixes': {}, 'entities': entity_iris, 'summary': ''}
    
    def _shorten_iri(self, iri: str) -> str:
        """Convert full IRI to prefixed form"""
        for prefix, namespace in self.prefixes.items():
            if iri.startswith(namespace):
                local_name = iri[len(namespace):]
                return f"{prefix}:{local_name}"
        return f"<{iri}>"
    
    def _create_context_summary(self, triples: List[Dict], entity_iris: List[str]) -> str:
        """Create human-readable summary of retrieved context"""
        if not triples:
            return "No context found."
        
        summary_lines = [
            f"Retrieved {len(triples)} triples about {len(entity_iris)} entities:",
            ""
        ]
        
        # Group by subject
        by_subject = {}
        for triple in triples:
            s = triple['subject']
            if s not in by_subject:
                by_subject[s] = []
            by_subject[s].append(triple)
        
        # Ignored types to save space (generic classes)
        ignored_types = {
            'rdfs:Resource', 'brick:Class', 'brick:Entity', 
            'owl:NamedIndividual'
        }

        # Format (limit to first 15 entities to avoid token explosion)
        for i, (subject, subject_triples) in enumerate(list(by_subject.items())[:15]):
            summary_lines.append(f"{subject}:")
            
            # Filter and Sort
            formatted_props = []
            for t in subject_triples:
                p = t['predicate']
                o = t['object']
                
                # Skip generic types
                if p == 'rdf:type' and any(ignored in o for ignored in ignored_types):
                    continue
                    
                formatted_props.append((p, o))
            
            # Sort: Labels first, then types, then others
            def sort_key(item):
                p, o = item
                if 'label' in p.lower():
                    return 0
                if 'type' in p.lower():
                    return 1
                return 2
                
            formatted_props.sort(key=sort_key)
            
            # Add to summary (limit 20 properties per entity)
            for p, o in formatted_props[:20]:
                summary_lines.append(f"  {p} {o}")
                
            summary_lines.append("")
        
        if len(by_subject) > 15:
            summary_lines.append(f"... and {len(by_subject) - 15} more entities")
        
        return "\n".join(summary_lines)
    
    async def retrieve_for_sparql(
        self,
        query: str,
        top_k: int = 10,
        hops: int = 2,
        min_score: float = 0.3
    ) -> Dict[str, Any]:
        """
        Complete 2-step retrieval for SPARQL generation
        
        Returns context optimized for LLM SPARQL generation:
        - Prefixes (for SPARQL header)
        - Triples (showing actual property names and structure)
        - Entity IRIs (for precise query construction)
        - Summary (human-readable context)
        
        Args:
            query: User's natural language query
            top_k: Number of entities to retrieve
            hops: Graph traversal depth (1 or 2)
            min_score: Similarity threshold
            
        Returns:
            Dict with 'prefixes', 'triples', 'entities', 'summary', 'prefix_declarations'
        """
        # Step 1: Entity retrieval
        entities = await self.retrieve_entities(query, top_k, min_score)
        
        if not entities:
            logger.warning("No entities found in similarity search")
            return {
                'prefixes': {},
                'prefix_declarations': '',
                'triples': [],
                'entities': [],
                'summary': 'No relevant entities found in the knowledge graph.',
                'entity_labels': [],
                'retrieved_entity_count': 0,
                'triple_count': 0
            }
        
        # Extract IRIs
        entity_iris = [e['iri'] for e in entities]
        entity_labels = [e['label'] for e in entities if e['label']]
        
        # Step 2: Bounded context
        context = await self.get_bounded_context(entity_iris, hops=hops)
        
        # Format prefix declarations for SPARQL
        prefix_declarations = "\n".join([
            f"PREFIX {prefix}: <{namespace}>"
            for prefix, namespace in context['prefixes'].items()
        ])
        
        # Add entity metadata to summary
        entity_summary = "Relevant entities:\n" + "\n".join([
            f"  - {e['label'] or e['iri']} (score: {e['score']:.3f})"
            for e in entities[:5]
        ])
        
        full_summary = f"{entity_summary}\n\n{context['summary']}"
        
        return {
            'prefixes': context['prefixes'],
            'prefix_declarations': prefix_declarations,
            'triples': context['triples'],
            'entities': entity_iris,
            'entity_labels': entity_labels,
            'summary': full_summary,
            'retrieved_entity_count': len(entities),
            'triple_count': len(context['triples'])
        }
    
    async def health_check(self) -> bool:
        """Check GraphDB connection"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.graphdb_url}/rest/repositories/{self.repository}",
                    auth=self._get_auth()
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"GraphDB health check failed: {e}")
            return False
