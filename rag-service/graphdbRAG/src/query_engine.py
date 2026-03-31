"""
GraphRAG Query Engine
Handles local and global search queries
"""
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd

from shared.utils import get_logger

logger = get_logger(__name__)

class GraphRAGQueryEngine:
    """Manages GraphRAG query operations"""
    
    def __init__(self):
        self.output_dir = Path("/app/graphrag-service/outputs")
        self.cache_dir = Path("/app/graphrag-service/cache")
        
        logger.info("Query engine initialized")
    
    async def local_search(
        self,
        query: str,
        community_level: int = 2,
        response_type: str = "multiple paragraphs"
    ) -> Dict[str, Any]:
        """
        Perform local search
        Fast, focused search within specific communities
        """
        try:
            # Import graphrag query engine
            from graphrag.query.local_search import LocalSearch
            from graphrag.query.context_builder.entity_extraction import EntityVectorStoreKey
            from graphrag.query.llm.oai.chat_openai import ChatOpenAI
            from graphrag.query.llm.oai.embedding import OpenAIEmbedding
            from graphrag.query.input.loaders.dfs import store_entity_semantic_embeddings
            
            # Load graph data
            entities_df = pd.read_parquet(self.output_dir / "create_final_entities.parquet")
            relationships_df = pd.read_parquet(self.output_dir / "create_final_relationships.parquet")
            text_units_df = pd.read_parquet(self.output_dir / "create_final_text_units.parquet")
            
            # Initialize search engine
            llm = ChatOpenAI()
            text_embedder = OpenAIEmbedding()
            
            # Create local search instance
            local_search_engine = LocalSearch(
                llm=llm,
                context_builder=None,  # Will be configured below
                token_encoder=None,
                llm_params={
                    "max_tokens": 2000,
                    "temperature": 0.0
                },
                context_builder_params={
                    "text_unit_prop": 0.5,
                    "community_prop": 0.1,
                    "conversation_history_max_turns": 5,
                    "conversation_history_user_turns_only": True,
                    "top_k_mapped_entities": 10,
                    "top_k_relationships": 10,
                    "include_entity_rank": True,
                    "include_relationship_weight": True,
                    "include_community_rank": False,
                    "return_candidate_context": False,
                    "embedding_vectorstore_key": EntityVectorStoreKey.ID,
                    "max_tokens": 12_000
                },
                response_type=response_type
            )
            
            # Execute search
            result = await local_search_engine.asearch(query)
            
            return {
                "answer": result.response,
                "context": result.context_data.get("sources", []),
                "entities": result.context_data.get("entities", []),
                "relationships": result.context_data.get("relationships", []),
                "communities": []
            }
            
        except Exception as e:
            logger.error(f"Local search failed: {e}")
            # Return fallback response
            return {
                "answer": f"Error performing local search: {str(e)}",
                "context": [],
                "entities": [],
                "relationships": [],
                "communities": []
            }
    
    async def global_search(
        self,
        query: str,
        community_level: int = 2,
        response_type: str = "multiple paragraphs"
    ) -> Dict[str, Any]:
        """
        Perform global search
        Comprehensive search across entire knowledge graph
        """
        try:
            # Import graphrag query engine
            from graphrag.query.global_search import GlobalSearch
            from graphrag.query.llm.oai.chat_openai import ChatOpenAI
            
            # Load graph data
            entities_df = pd.read_parquet(self.output_dir / "create_final_entities.parquet")
            relationships_df = pd.read_parquet(self.output_dir / "create_final_relationships.parquet")
            communities_df = pd.read_parquet(self.output_dir / "create_final_communities.parquet")
            community_reports_df = pd.read_parquet(self.output_dir / "create_final_community_reports.parquet")
            
            # Initialize search engine
            llm = ChatOpenAI()
            
            # Create global search instance
            global_search_engine = GlobalSearch(
                llm=llm,
                context_builder=None,  # Will be configured below
                token_encoder=None,
                max_data_tokens=12_000,
                map_llm_params={
                    "max_tokens": 1000,
                    "temperature": 0.0
                },
                reduce_llm_params={
                    "max_tokens": 2000,
                    "temperature": 0.0
                },
                allow_general_knowledge=False,
                json_mode=False,
                context_builder_params={
                    "use_community_summary": False,
                    "shuffle_data": True,
                    "include_community_rank": True,
                    "min_community_rank": 0,
                    "community_rank_name": "rank",
                    "include_community_weight": True,
                    "community_weight_name": "occurrence weight",
                    "normalize_community_weight": True,
                    "max_tokens": 12_000,
                    "context_name": "Reports"
                },
                concurrent_coroutines=32,
                response_type=response_type
            )
            
            # Execute search
            result = await global_search_engine.asearch(query)
            
            return {
                "answer": result.response,
                "context": result.context_data.get("sources", []),
                "entities": [],
                "relationships": [],
                "communities": result.context_data.get("communities", [])
            }
            
        except Exception as e:
            logger.error(f"Global search failed: {e}")
            # Return fallback response
            return {
                "answer": f"Error performing global search: {str(e)}",
                "context": [],
                "entities": [],
                "relationships": [],
                "communities": []
            }
