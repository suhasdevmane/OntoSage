"""
GraphRAG Service Models
Pydantic models for request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class IndexRequest(BaseModel):
    """Request to create GraphRAG index"""
    input_path: Optional[str] = Field(None, description="Override default input path")
    config_override: Optional[Dict[str, Any]] = Field(None, description="Override config settings")
    
class IndexResponse(BaseModel):
    """Response from index creation"""
    task_id: str
    status: str
    message: str
    estimated_time: Optional[str] = None

class QueryRequest(BaseModel):
    """Request for GraphRAG query"""
    query: str = Field(..., description="User question")
    community_level: int = Field(2, description="Community detection level (0-3)")
    response_type: str = Field("multiple paragraphs", description="Response format")
    
class QueryResponse(BaseModel):
    """Response from GraphRAG query"""
    query: str
    answer: str
    context: List[str] = []
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    communities: List[Dict[str, Any]] = []
    query_type: str  # "local" or "global"
    
class GraphStatsResponse(BaseModel):
    """Statistics about the knowledge graph"""
    entities: int = 0
    relationships: int = 0
    communities: int = 0
    text_units: int = 0
    total_tokens: int = 0
    last_updated: Optional[str] = None
    
class TaskStatus(BaseModel):
    """Status of background indexing task"""
    task_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float = 0.0
    current_step: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
