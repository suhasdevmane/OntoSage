"""
Shared configuration for OntoSage 2.0
Supports both local (Ollama) and cloud (OpenAI) model providers
"""
import os
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    """
    Central configuration for all OntoSage services
    """
    
    # ==================== Model Provider ====================
    MODEL_PROVIDER: Literal["local", "cloud", "openai"] = Field(
        default="local",
        description="Choose 'local' for local Ollama, 'cloud' for cloud Ollama, or 'openai' for OpenAI API"
    )
    
    # ==================== LLM Configuration ====================
    # Local (Ollama)
    OLLAMA_BASE_URL: str = Field(default="http://ollama:11434", description="Ollama API endpoint")
    OLLAMA_MODEL: str = Field(default="deepseek-r1:32b", description="Ollama model name")
    
    # Cloud (Ollama Cloud)
    OLLAMA_CLOUD_API_KEY: str = Field(default="", description="Ollama Cloud API key")
    OLLAMA_CLOUD_BASE_URL: str = Field(default="https://api.ollama.ai/v1", description="Ollama Cloud API endpoint")
    OLLAMA_CLOUD_MODEL: str = Field(default="gpt-oss:120b-cloud", description="Ollama Cloud model name")
    
    # Cloud (OpenAI)
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (required if MODEL_PROVIDER=openai)")
    OPENAI_MODEL: str = Field(default="o3-mini", description="OpenAI model name")
    OPENAI_TEMPERATURE: float = Field(default=0.1, description="LLM temperature for generation")
    
    # ==================== Embedding Configuration ====================
    EMBEDDING_PROVIDER: Literal["local", "openai"] = Field(
        default="local",
        description="Choose 'local' for sentence-transformers or 'openai' for OpenAI embeddings"
    )
    
    # Local embeddings
    EMBEDDING_MODEL_LOCAL: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model for local embeddings (384 dims)"
    )
    EMBEDDING_DIMENSION_LOCAL: int = Field(default=384, description="Embedding dimensions for local model")
    
    # OpenAI embeddings
    EMBEDDING_MODEL_OPENAI: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model (1536 dims)"
    )
    EMBEDDING_DIMENSION_OPENAI: int = Field(default=1536, description="Embedding dimensions for OpenAI")
    
    @property
    def embedding_dimension(self) -> int:
        """Get current embedding dimension based on provider"""
        return self.EMBEDDING_DIMENSION_OPENAI if self.EMBEDDING_PROVIDER == "openai" else self.EMBEDDING_DIMENSION_LOCAL
    
    @property
    def embedding_model(self) -> str:
        """Get current embedding model based on provider"""
        return self.EMBEDDING_MODEL_OPENAI if self.EMBEDDING_PROVIDER == "openai" else self.EMBEDDING_MODEL_LOCAL
    
    # ==================== STT Configuration ====================
    STT_PROVIDER: Literal["local", "openai"] = Field(
        default="openai",  # default switched due to PyAV/FFmpeg build incompatibility
        description="Choose 'local' for faster-whisper or 'openai' for Whisper API"
    )
    
    WHISPER_MODEL_LOCAL: str = Field(
        default="base",
        description="Local Whisper model size: tiny, base, small, medium, large"
    )
    
    # ==================== Service URLs ====================
    QDRANT_URL: str = Field(default="http://qdrant:6333", description="Qdrant vector DB URL")
    REDIS_URL: str = Field(default="redis://redis:6379/0", description="Redis URL for state management")
    
    # Service hosts/ports (for constructing URLs in services)
    REDIS_HOST: str = Field(default="redis", description="Redis hostname")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    
    FUSEKI_HOST: str = Field(default="jena-fuseki", description="Fuseki hostname")
    FUSEKI_PORT: int = Field(default=3030, description="Fuseki port")
    FUSEKI_URL: str = Field(
        default="http://fuseki:3030/abacws",
        description="Jena Fuseki SPARQL endpoint for Building 1"
    )
    
    # GraphDB Configuration (new architecture)
    GRAPHDB_URL: str = Field(default="http://graphdb:7200", description="GraphDB REST API URL")
    GRAPHDB_HOST: str = Field(default="graphdb", description="GraphDB hostname")
    GRAPHDB_PORT: int = Field(default=7200, description="GraphDB port")
    GRAPHDB_REPOSITORY: str = Field(default="bldg", description="GraphDB repository name")
    GRAPHDB_USER: str = Field(default="admin", description="GraphDB username")
    GRAPHDB_PASSWORD: str = Field(default="Admin@GraphDB2024", description="GraphDB password")
    GRAPHDB_SIMILARITY_INDEX: str = Field(default="bldg_index", description="GraphDB similarity index name")
    GRAPHDB_USE_SIMILARITY: bool = Field(default=True, description="Use GraphDB similarity indexing for entity retrieval")
    
    # ==================== Postgres User Data Configuration ====================
    POSTGRES_USER_USER: str = Field(default="ontobot", description="Postgres username for user data")
    POSTGRES_USER_PASSWORD: str = Field(default="ontobot_secret", description="Postgres password for user data")
    POSTGRES_USER_DB: str = Field(default="ontobot", description="Postgres database name for user data")
    POSTGRES_USER_HOST: str = Field(default="postgres-user-data", description="Postgres hostname for user data")
    POSTGRES_USER_PORT: int = Field(default=5432, description="Postgres port for user data")
    
    MYSQL_HOST: str = Field(default="mysql", description="MySQL host (Building 1)")
    MYSQL_PORT: int = Field(default=3306, description="MySQL port")
    MYSQL_USER: str = Field(default="root", description="MySQL username")
    MYSQL_PASSWORD: str = Field(default="mysql", description="MySQL password")
    MYSQL_DATABASE: str = Field(default="abacws", description="MySQL database name")
    
    RAG_SERVICE_URL: str = Field(default="http://rag-service:8001", description="RAG service URL")
    CODE_EXECUTOR_URL: str = Field(default="http://code-executor:8002", description="Code executor URL")
    WHISPER_STT_URL: str = Field(default="http://whisper-stt:8003", description="Whisper STT service URL")
    
    RAG_SERVICE_HOST: str = Field(default="rag-service", description="RAG service hostname")
    RAG_SERVICE_PORT: int = Field(default=8001, description="RAG service port")
    
    CODE_EXECUTOR_HOST: str = Field(default="code-executor", description="Code executor hostname")
    CODE_EXECUTOR_PORT: int = Field(default=8002, description="Code executor port")

    # ==================== Public URLs ====================
    STATIC_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL (including protocol) for serving static artifacts such as plots"
    )
    
    # ==================== Building Configuration ====================
    BUILDING_ID: str = Field(default="bldg1", description="Building identifier (bldg1, bldg2, bldg3)")
    BUILDING_NAME: str = Field(default="Abacws Building", description="Human-readable building name")
    
    # Ontology Files
    BRICK_TBOX_FILE: str = Field(
        default="trial/dataset/Brick.ttl",
        description="Brick Schema TBox file (vocabulary definitions)"
    )
    BLDG1_ABOX_FILE: str = Field(
        default="trial/dataset/bldg1_protege.ttl",
        description="Building 1 ABox file (instances)"
    )
    
    # RAG Collections
    TBOX_COLLECTION: str = Field(default="brick_schema", description="Qdrant collection for TBox")
    ABOX_COLLECTION: str = Field(default="building_instances", description="Qdrant collection for ABox")
    ONTOLOGY_COLLECTION: str = Field(default="ontology", description="Legacy collection name")
    
    # ==================== Security & Limits ====================
    CODE_EXECUTOR_TIMEOUT: int = Field(default=30, description="Code execution timeout in seconds")
    CODE_EXECUTOR_MEMORY_LIMIT: str = Field(default="1g", description="Memory limit for code execution")
    CODE_EXECUTOR_CPU_LIMIT: float = Field(default=1.0, description="CPU limit for code execution")
    
    MAX_RETRY_ATTEMPTS: int = Field(default=3, description="Max retry attempts for error recovery")
    
    # ==================== Conversation Settings ====================
    CONVERSATION_TTL: int = Field(default=3600, description="Conversation state TTL in Redis (seconds)")
    
    # ==================== RAG System Selection ====================
    RAG_SYSTEM: Literal["graphdbRAG", "GraphRAG", "RAG_system", "RAG_system_advance"] = Field(
        default="graphdbRAG",
        description="Select RAG system: 'graphdbRAG' (GraphDB similarity), 'GraphRAG' (Microsoft), 'RAG_system', 'RAG_system_advance'"
    )
    
    # ==================== Ontology Query Mode ====================
    ONTOLOGY_QUERY_MODE: Literal["semantic", "sparql", "hybrid"] = Field(
        default="semantic",
        description="Ontology query strategy: 'semantic' (RAG+LLM only), 'sparql' (traditional), 'hybrid' (semantic with SPARQL fallback)"
    )
    USE_SEMANTIC_ONTOLOGY: bool = Field(
        default=True,
        description="Enable semantic RAG-based ontology querying (bypasses SPARQL generation)"
    )
    MAX_CONVERSATION_HISTORY: int = Field(default=20, description="Max messages to keep in conversation history")
    
    # ==================== Logging ====================
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load OpenAI credentials from orchestrator/agents/.env if available
        agents_env_path = Path("/app/agents/.env")
        if agents_env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(agents_env_path, override=True)  # Override existing env vars
            # Override with values from agents/.env if present
            if os.getenv("OPENAI_API_KEY"):
                self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
            if os.getenv("OPENAI_MODEL"):
                self.OPENAI_MODEL = os.getenv("OPENAI_MODEL")

# Global settings instance
settings = Settings()

def get_llm_config() -> dict:
    """
    Get LLM configuration based on provider
    Returns dict with model params for LangChain
    """
    if settings.MODEL_PROVIDER == "openai":
        return {
            "provider": "openai",
            "model": settings.OPENAI_MODEL,
            "api_key": settings.OPENAI_API_KEY,
            "temperature": settings.OPENAI_TEMPERATURE,
        }
    elif settings.MODEL_PROVIDER == "cloud":
        return {
            "provider": "ollama_cloud",
            "base_url": settings.OLLAMA_CLOUD_BASE_URL,
            "model": settings.OLLAMA_CLOUD_MODEL,
            "api_key": settings.OLLAMA_CLOUD_API_KEY,
            "temperature": settings.OPENAI_TEMPERATURE,
        }
    else:  # local (Ollama)
        return {
            "provider": "ollama",
            "base_url": settings.OLLAMA_BASE_URL,
            "model": settings.OLLAMA_MODEL,
            "temperature": settings.OPENAI_TEMPERATURE,
        }

def get_embedding_config() -> dict:
    """
    Get embedding configuration based on provider
    """
    if settings.EMBEDDING_PROVIDER == "openai":
        return {
            "provider": "openai",
            "model": settings.EMBEDDING_MODEL_OPENAI,
            "api_key": settings.OPENAI_API_KEY,
            "dimensions": settings.EMBEDDING_DIMENSION_OPENAI,
        }
    else:  # local
        return {
            "provider": "local",
            "model": settings.EMBEDDING_MODEL_LOCAL,
            "dimensions": settings.EMBEDDING_DIMENSION_LOCAL,
        }

def validate_config():
    """
    Validate configuration based on chosen providers
    Raises ValueError if required settings are missing
    """
    if settings.MODEL_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai")
    
    if settings.MODEL_PROVIDER == "cloud" and not settings.OLLAMA_CLOUD_API_KEY:
        raise ValueError("OLLAMA_CLOUD_API_KEY is required when MODEL_PROVIDER=cloud")
    
    if settings.EMBEDDING_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
    
    if settings.STT_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when STT_PROVIDER=openai")
    
    return True
