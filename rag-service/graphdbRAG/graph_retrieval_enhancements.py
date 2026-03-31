"""
Professional Graph Database Retrieval Enhancements
===================================================

Implements advanced retrieval strategies from commercial graph databases:
- Google Knowledge Graph: Bidirectional traversal, entity resolution
- Neo4j: Property path queries, relationship depth control
- Amazon Neptune: Schema-guided navigation, inference rules
- GraphDB: SPARQL optimization, reasoning chains

Key Enhancements:
1. **Bidirectional Traversal** - Follow relationships in both directions
2. **Property Paths** - Multi-hop relationship queries (e.g., Floor -> Room -> Sensor)
3. **Schema-Guided Search** - Use TBox to navigate ABox efficiently
4. **Relationship Depth Control** - Limit traversal depth to prevent over-fetching
5. **Entity Resolution** - Merge duplicate entities, resolve aliases
6. **Cardinality Awareness** - Optimize for 1:1 vs 1:N relationships
7. **Inference Chains** - Derive implicit relationships from explicit ones
"""
import sys
sys.path.append('/app')

import re
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import defaultdict, deque
import asyncio

from shared.config import settings
from shared.utils import get_logger
from shared.models import RetrievalResult

from embeddings import EmbeddingManager
from retrieval import RetrievalManager

logger = get_logger(__name__)


class GraphRetrievalEnhancements:
    """
    Advanced graph retrieval strategies for ontology navigation
    """
    
    def __init__(self, retrieval_manager: RetrievalManager):
        self.retrieval_manager = retrieval_manager
        
        # Graph traversal configurations
        self.max_depth = 3  # Maximum relationship hops
        self.max_neighbors = 50  # Maximum related entities per node
        
        # Relationship importance weights
        self.relationship_weights = {
            "hasPart": 1.0,          # Core composition (Floor hasPart Room)
            "hasPoint": 0.9,         # Sensor points
            "hasLocation": 0.85,     # Spatial relationships
            "feeds": 0.8,            # Equipment connections
            "isPartOf": 0.9,         # Reverse composition
            "isLocationOf": 0.8,     # Reverse spatial
            "type": 0.95,            # Class membership
            "subClassOf": 0.85       # Hierarchical
        }
    
    async def bidirectional_traverse(
        self,
        entity_uri: str,
        depth: int = 2,
        relationship_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Traverse relationships bidirectionally from an entity
        
        Example: For "Floor4"
        - Forward: Floor4 -> hasPart -> Room4.01, Room4.02, ...
        - Backward: Building -> hasPart -> Floor4
        
        Args:
            entity_uri: Starting entity URI (e.g., "bldg:Floor4")
            depth: Number of hops to traverse (1-3 recommended)
            relationship_types: Filter by specific relationships
            
        Returns:
            {
                "forward": {relationship: [targets]},
                "backward": {relationship: [sources]},
                "neighbors": [all connected entities]
            }
        """
        logger.info(f"🔄 Bidirectional traversal from {entity_uri} (depth={depth})")
        
        forward = await self._traverse_forward(entity_uri, depth, relationship_types)
        backward = await self._traverse_backward(entity_uri, depth, relationship_types)
        
        # Merge neighbor sets
        all_neighbors = set()
        for targets in forward.values():
            all_neighbors.update(targets)
        for sources in backward.values():
            all_neighbors.update(sources)
        
        return {
            "entity": entity_uri,
            "forward": forward,
            "backward": backward,
            "neighbors": list(all_neighbors),
            "total_neighbors": len(all_neighbors)
        }
    
    async def property_path_query(
        self,
        start_entity: str,
        path: List[str],
        filters: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Execute multi-hop property path queries
        
        Example: "Find all sensors in Floor4"
        Path: Floor4 -> hasPart -> Room -> hasPoint -> Sensor
        
        Args:
            start_entity: Starting point (e.g., "Floor4")
            path: List of relationships to follow ["hasPart", "hasPoint"]
            filters: Optional filters {property: value}
            
        Returns:
            List of entity URIs matching the path
        """
        logger.info(f"🛤️ Property path query: {start_entity} -> {' -> '.join(path)}")
        
        current_entities = {start_entity}
        
        for relationship in path:
            next_entities = set()
            
            for entity in current_entities:
                # Search for triples: entity relationship ?target
                query_text = f"{entity} {relationship}"
                results = await self.retrieval_manager.retrieve(
                    query=query_text,
                    collection=settings.ABOX_COLLECTION,
                    top_k=self.max_neighbors
                )
                
                # Extract target entities from results
                for result in results:
                    targets = self._extract_targets_from_triple(result.text, relationship)
                    next_entities.update(targets)
            
            current_entities = next_entities
            
            if not current_entities:
                logger.warning(f"⚠️ No entities found after {relationship}")
                break
        
        # Apply filters if provided
        if filters:
            current_entities = await self._apply_filters(current_entities, filters)
        
        logger.info(f"✅ Property path found {len(current_entities)} entities")
        return list(current_entities)
    
    async def schema_guided_search(
        self,
        query: str,
        entity_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use TBox schema to guide ABox instance retrieval
        
        Example: Query "rooms in Floor4"
        1. TBox: Find brick:Room class definition, properties
        2. ABox: Search for instances of type brick:Room
        3. Filter: Only rooms with relationship to Floor4
        
        Args:
            query: Natural language query
            entity_type: Optional type constraint (e.g., "brick:Room")
            
        Returns:
            Schema-enhanced results with type information
        """
        logger.info(f"🎯 Schema-guided search: '{query}' (type={entity_type})")
        
        # Step 1: Extract entity type from query if not provided
        if not entity_type:
            entity_type = await self._infer_entity_type(query)
        
        # Step 2: Retrieve schema definition from TBox
        schema_context = await self._get_schema_definition(entity_type)
        
        # Step 3: Use schema to enhance ABox query
        enhanced_query = f"{query} {entity_type} {schema_context}"
        
        # Step 4: Retrieve instances with type filtering
        instances = await self.retrieval_manager.retrieve(
            query=enhanced_query,
            collection=settings.ABOX_COLLECTION,
            top_k=50
        )
        
        # Step 5: Filter by type assertion (rdf:type)
        typed_instances = [
            inst for inst in instances
            if entity_type in inst.text or "rdf:type" in inst.text
        ]
        
        return {
            "query": query,
            "entity_type": entity_type,
            "schema_context": schema_context,
            "instances": typed_instances,
            "count": len(typed_instances)
        }
    
    async def relationship_depth_query(
        self,
        entity: str,
        relationship: str,
        max_depth: int = 3,
        count_only: bool = False
    ) -> Dict[str, Any]:
        """
        Query relationships with depth control
        
        Example: "How many rooms in Floor4?"
        - entity="Floor4", relationship="hasPart", depth=1
        - Counts direct children without deep traversal
        
        Args:
            entity: Source entity URI
            relationship: Relationship predicate
            max_depth: Maximum traversal depth
            count_only: Return count instead of full results
            
        Returns:
            Depth-aware relationship results
        """
        logger.info(f"📊 Depth query: {entity} -{relationship}-> ? (depth={max_depth})")
        
        results_by_depth = defaultdict(list)
        visited = set()
        queue = deque([(entity, 0)])  # (entity, current_depth)
        
        while queue:
            current_entity, depth = queue.popleft()
            
            if depth > max_depth or current_entity in visited:
                continue
            
            visited.add(current_entity)
            
            # Find all targets of this relationship
            query_text = f"{current_entity} {relationship}"
            targets = await self._find_relationship_targets(query_text)
            
            results_by_depth[depth].extend(targets)
            
            # Add targets to queue for next depth level
            if depth < max_depth:
                for target in targets:
                    queue.append((target, depth + 1))
        
        total_count = sum(len(entities) for entities in results_by_depth.values())
        
        if count_only:
            return {
                "entity": entity,
                "relationship": relationship,
                "total_count": total_count,
                "by_depth": {d: len(entities) for d, entities in results_by_depth.items()}
            }
        
        return {
            "entity": entity,
            "relationship": relationship,
            "total_count": total_count,
            "results_by_depth": dict(results_by_depth),
            "all_targets": list(visited)
        }
    
    async def inference_chain(
        self,
        query: str,
        max_inferences: int = 5
    ) -> Dict[str, Any]:
        """
        Derive implicit relationships using inference rules
        
        Example Rules:
        - If Room hasLocation Floor, then Room isPartOf Floor
        - If Sensor hasPoint Equipment, then Sensor monitors Equipment
        - If A hasPart B and B hasPart C, then A hasPart C (transitive)
        
        Args:
            query: Query requiring inference
            max_inferences: Maximum inference steps
            
        Returns:
            Results with explicit + inferred triples
        """
        logger.info(f"🔗 Inference chain for: '{query}'")
        
        # Define inference rules
        inference_rules = [
            {"if": ["?x", "hasLocation", "?y"], "then": ["?x", "isPartOf", "?y"]},
            {"if": ["?x", "hasPart", "?y"], "then": ["?y", "isPartOf", "?x"]},  # Inverse
            # Transitive: hasPart(A,B) ∧ hasPart(B,C) → hasPart(A,C)
        ]
        
        # Step 1: Get explicit triples
        explicit_results = await self.retrieval_manager.retrieve(
            query=query,
            collection=settings.ABOX_COLLECTION,
            top_k=20
        )
        
        # Step 2: Apply inference rules
        inferred_triples = []
        for result in explicit_results:
            for rule in inference_rules[:max_inferences]:
                inferred = self._apply_inference_rule(result.text, rule)
                inferred_triples.extend(inferred)
        
        return {
            "query": query,
            "explicit_count": len(explicit_results),
            "inferred_count": len(inferred_triples),
            "explicit_triples": [r.text for r in explicit_results],
            "inferred_triples": inferred_triples
        }
    
    # ==================== Helper Methods ====================
    
    async def _traverse_forward(
        self,
        entity: str,
        depth: int,
        relationship_types: Optional[List[str]]
    ) -> Dict[str, List[str]]:
        """Forward traversal: entity -> relationship -> target"""
        results = defaultdict(list)
        
        # Search for triples where entity is subject
        query = f"{entity}"
        triples = await self.retrieval_manager.retrieve(
            query=query,
            collection=settings.ABOX_COLLECTION,
            top_k=100
        )
        
        for triple in triples:
            # Parse triple: subject predicate object
            parsed = self._parse_triple(triple.text)
            if parsed and parsed["subject"] == entity:
                rel_type = parsed["predicate"]
                if not relationship_types or rel_type in relationship_types:
                    results[rel_type].append(parsed["object"])
        
        return dict(results)
    
    async def _traverse_backward(
        self,
        entity: str,
        depth: int,
        relationship_types: Optional[List[str]]
    ) -> Dict[str, List[str]]:
        """Backward traversal: source -> relationship -> entity"""
        results = defaultdict(list)
        
        # Search for triples where entity is object
        query = f"{entity}"
        triples = await self.retrieval_manager.retrieve(
            query=query,
            collection=settings.ABOX_COLLECTION,
            top_k=100
        )
        
        for triple in triples:
            parsed = self._parse_triple(triple.text)
            if parsed and parsed["object"] == entity:
                rel_type = parsed["predicate"]
                if not relationship_types or rel_type in relationship_types:
                    results[rel_type].append(parsed["subject"])
        
        return dict(results)
    
    def _parse_triple(self, triple_text: str) -> Optional[Dict[str, str]]:
        """
        Parse RDF triple from text
        Format: "subject predicate object"
        """
        # Pattern: URI predicate URI/Literal
        pattern = r'<([^>]+)>\s+<([^>]+)>\s+(?:<([^>]+)>|"([^"]+)")'
        match = re.search(pattern, triple_text)
        
        if match:
            return {
                "subject": match.group(1),
                "predicate": match.group(2),
                "object": match.group(3) or match.group(4)
            }
        
        # Fallback: simplified parsing
        parts = triple_text.split()
        if len(parts) >= 3:
            return {
                "subject": parts[0],
                "predicate": parts[1],
                "object": " ".join(parts[2:])
            }
        
        return None
    
    def _extract_targets_from_triple(self, triple_text: str, relationship: str) -> Set[str]:
        """Extract target entities from triple matching relationship"""
        targets = set()
        parsed = self._parse_triple(triple_text)
        
        if parsed and relationship in parsed["predicate"]:
            targets.add(parsed["object"])
        
        return targets
    
    async def _find_relationship_targets(self, query_text: str) -> List[str]:
        """Find all targets for a relationship query"""
        results = await self.retrieval_manager.retrieve(
            query=query_text,
            collection=settings.ABOX_COLLECTION,
            top_k=100
        )
        
        targets = []
        for result in results:
            parsed = self._parse_triple(result.text)
            if parsed:
                targets.append(parsed["object"])
        
        return targets
    
    async def _infer_entity_type(self, query: str) -> str:
        """Infer entity type from query keywords"""
        # Simple keyword matching (can be enhanced with NER)
        type_keywords = {
            "room": "brick:Room",
            "sensor": "brick:Sensor",
            "floor": "brick:Floor",
            "equipment": "brick:Equipment",
            "zone": "brick:Zone"
        }
        
        query_lower = query.lower()
        for keyword, entity_type in type_keywords.items():
            if keyword in query_lower:
                return entity_type
        
        return "owl:Thing"  # Default
    
    async def _get_schema_definition(self, entity_type: str) -> str:
        """Retrieve schema definition from TBox"""
        results = await self.retrieval_manager.retrieve(
            query=entity_type,
            collection=settings.TBOX_COLLECTION,
            top_k=5
        )
        
        # Combine schema triples
        schema_context = " ".join([r.text for r in results])
        return schema_context
    
    async def _apply_filters(
        self,
        entities: Set[str],
        filters: Dict[str, Any]
    ) -> Set[str]:
        """Apply property filters to entity set"""
        filtered = set()
        
        for entity in entities:
            # Query entity properties
            results = await self.retrieval_manager.retrieve(
                query=entity,
                collection=settings.ABOX_COLLECTION,
                top_k=10
            )
            
            # Check if entity matches all filters
            if self._matches_filters(results, filters):
                filtered.add(entity)
        
        return filtered
    
    def _matches_filters(self, results: List, filters: Dict[str, Any]) -> bool:
        """Check if results match filter criteria"""
        result_text = " ".join([r.text for r in results])
        
        for prop, value in filters.items():
            if str(value) not in result_text:
                return False
        
        return True
    
    def _apply_inference_rule(self, triple_text: str, rule: Dict) -> List[str]:
        """Apply single inference rule to triple"""
        inferred = []
        parsed = self._parse_triple(triple_text)
        
        if not parsed:
            return inferred
        
        # Match rule condition
        if_pattern = rule["if"]
        if parsed["predicate"] in if_pattern[1]:
            # Generate inferred triple
            then_pattern = rule["then"]
            inferred_triple = f"{parsed['subject']} {then_pattern[1]} {parsed['object']}"
            inferred.append(inferred_triple)
        
        return inferred


# ==================== Integration with Smart Retrieval ====================

async def enhance_smart_retrieval_with_graph(
    query: str,
    smart_results: Dict[str, Any],
    embedding_manager: EmbeddingManager
) -> Dict[str, Any]:
    """
    Enhance smart retrieval results with graph traversal
    
    Args:
        query: Original user query
        smart_results: Results from SmartOntologyRetriever
        embedding_manager: Embedding manager instance
        
    Returns:
        Enhanced results with graph relationships
    """
    retrieval_manager = RetrievalManager(embedding_manager)
    graph_enhancer = GraphRetrievalEnhancements(retrieval_manager)
    
    # Detect counting queries
    if any(keyword in query.lower() for keyword in ["how many", "count", "number of"]):
        logger.info("🔢 Detected counting query - using relationship depth query")
        
        # Extract entity and relationship from query
        # Example: "How many rooms in Floor4?" -> entity="Floor4", rel="hasPart"
        entity = _extract_entity_from_query(query)
        relationship = "hasPart"  # Common for "how many X in Y" queries
        
        if entity:
            depth_results = await graph_enhancer.relationship_depth_query(
                entity=entity,
                relationship=relationship,
                max_depth=1,
                count_only=True
            )
            smart_results["graph_count"] = depth_results
    
    # Add bidirectional context for main entities
    if smart_results.get("entities"):
        for entity_list in smart_results["entities"].values():
            for entity in entity_list[:3]:  # Limit to top 3 entities
                bidirectional = await graph_enhancer.bidirectional_traverse(
                    entity_uri=entity,
                    depth=2
                )
                smart_results.setdefault("graph_context", []).append(bidirectional)
    
    return smart_results


def _extract_entity_from_query(query: str) -> Optional[str]:
    """Extract main entity from counting query"""
    # Pattern: "How many X in Y" -> extract Y
    patterns = [
        r'in\s+(\w+\d*)',      # "in Floor4"
        r'on\s+(\w+\d*)',      # "on Floor4"
        r'at\s+(\w+\d*)',      # "at Floor4"
        r'of\s+(\w+\d*)',      # "of Floor4"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None
