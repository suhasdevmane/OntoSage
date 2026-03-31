"""
GraphRAG Indexer
Handles entity extraction, relationship mapping, and community detection
"""
import asyncio
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import pandas as pd

from shared.utils import get_logger

logger = get_logger(__name__)

class GraphRAGIndexer:
    """Manages GraphRAG indexing pipeline"""
    
    def __init__(self):
        self.input_dir = Path("/app/graphrag-service/inputs")
        self.output_dir = Path("/app/graphrag-service/outputs")
        self.cache_dir = Path("/app/graphrag-service/cache")
        self.tasks = {}  # Track background tasks
        
        # Ensure directories exist
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Indexer initialized")
        logger.info(f"  Input: {self.input_dir}")
        logger.info(f"  Output: {self.output_dir}")
        
    def has_existing_index(self) -> bool:
        """Check if index exists"""
        try:
            # Check for graphrag output artifacts
            entities_file = self.output_dir / "create_final_entities.parquet"
            relationships_file = self.output_dir / "create_final_relationships.parquet"
            
            return entities_file.exists() and relationships_file.exists()
        except Exception as e:
            logger.error(f"Error checking index: {e}")
            return False
    
    async def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about current index"""
        try:
            stats = {
                "entities": 0,
                "relationships": 0,
                "communities": 0,
                "text_units": 0,
                "total_tokens": 0,
                "last_updated": None
            }
            
            # Read entities
            entities_file = self.output_dir / "create_final_entities.parquet"
            if entities_file.exists():
                df = pd.read_parquet(entities_file)
                stats["entities"] = len(df)
                stats["last_updated"] = datetime.fromtimestamp(
                    entities_file.stat().st_mtime
                ).isoformat()
            
            # Read relationships
            relationships_file = self.output_dir / "create_final_relationships.parquet"
            if relationships_file.exists():
                df = pd.read_parquet(relationships_file)
                stats["relationships"] = len(df)
            
            # Read communities
            communities_file = self.output_dir / "create_final_communities.parquet"
            if communities_file.exists():
                df = pd.read_parquet(communities_file)
                stats["communities"] = len(df)
            
            # Read text units
            text_units_file = self.output_dir / "create_final_text_units.parquet"
            if text_units_file.exists():
                df = pd.read_parquet(text_units_file)
                stats["text_units"] = len(df)
                if "n_tokens" in df.columns:
                    stats["total_tokens"] = int(df["n_tokens"].sum())
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "entities": 0,
                "relationships": 0,
                "communities": 0,
                "text_units": 0,
                "total_tokens": 0,
                "last_updated": None,
                "error": str(e)
            }
    
    async def start_indexing(
        self,
        input_path: Optional[str] = None,
        config_override: Optional[Dict[str, Any]] = None
    ) -> str:
        """Start indexing process in background"""
        task_id = str(uuid.uuid4())
        
        # Store task info
        self.tasks[task_id] = {
            "status": "pending",
            "progress": 0.0,
            "started_at": datetime.now(),
            "current_step": "Initializing"
        }
        
        # Start indexing in background
        asyncio.create_task(self._run_indexing(task_id, input_path, config_override))
        
        return task_id
    
    async def _run_indexing(
        self,
        task_id: str,
        input_path: Optional[str],
        config_override: Optional[Dict[str, Any]]
    ):
        """Execute indexing pipeline"""
        try:
            self.tasks[task_id]["status"] = "running"
            self.tasks[task_id]["current_step"] = "Loading documents"
            self.tasks[task_id]["progress"] = 0.1
            
            # Import graphrag here to avoid startup delays
            from graphrag.index import run_pipeline_with_config
            from graphrag.index.config import PipelineConfig
            
            # Update progress
            self.tasks[task_id]["current_step"] = "Extracting entities"
            self.tasks[task_id]["progress"] = 0.3
            
            # Run GraphRAG indexing pipeline
            # This will create entities, relationships, and communities
            logger.info(f"Starting GraphRAG pipeline for task {task_id}")
            
            # Configure pipeline
            config = self._build_config(input_path, config_override)
            
            # Run pipeline
            await run_pipeline_with_config(config)
            
            # Update progress
            self.tasks[task_id]["current_step"] = "Detecting communities"
            self.tasks[task_id]["progress"] = 0.7
            
            # Finalize
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["progress"] = 1.0
            self.tasks[task_id]["current_step"] = "Completed"
            self.tasks[task_id]["completed_at"] = datetime.now()
            
            logger.info(f"Indexing completed for task {task_id}")
            
        except Exception as e:
            logger.error(f"Indexing failed for task {task_id}: {e}")
            self.tasks[task_id]["status"] = "failed"
            self.tasks[task_id]["error"] = str(e)
            self.tasks[task_id]["completed_at"] = datetime.now()
    
    def _build_config(
        self,
        input_path: Optional[str],
        config_override: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build GraphRAG pipeline configuration"""
        # Base configuration
        config = {
            "input": {
                "base_dir": str(input_path) if input_path else str(self.input_dir),
                "file_type": "text"
            },
            "output": {
                "base_dir": str(self.output_dir)
            },
            "cache": {
                "base_dir": str(self.cache_dir)
            },
            "llm": {
                "provider": "openai",  # Can be configured from env
                "model": "gpt-4-turbo-preview"
            },
            "embeddings": {
                "provider": "openai",
                "model": "text-embedding-3-small"
            }
        }
        
        # Apply overrides
        if config_override:
            config.update(config_override)
        
        return config
    
    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of indexing task"""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        
        return self.tasks[task_id]
    
    async def get_sample_entities(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get sample entities from index"""
        try:
            entities_file = self.output_dir / "create_final_entities.parquet"
            if not entities_file.exists():
                return []
            
            df = pd.read_parquet(entities_file)
            sample = df.head(limit)
            
            return sample.to_dict('records')
            
        except Exception as e:
            logger.error(f"Error getting entities: {e}")
            return []
    
    async def get_sample_relationships(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get sample relationships from index"""
        try:
            relationships_file = self.output_dir / "create_final_relationships.parquet"
            if not relationships_file.exists():
                return []
            
            df = pd.read_parquet(relationships_file)
            sample = df.head(limit)
            
            return sample.to_dict('records')
            
        except Exception as e:
            logger.error(f"Error getting relationships: {e}")
            return []
