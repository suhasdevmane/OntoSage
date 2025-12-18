"""
Shared utility functions for OntoSage 2.0
"""
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance"""
    return logging.getLogger(name)

def generate_conversation_id() -> str:
    """Generate a unique conversation ID"""
    return f"conv_{uuid.uuid4().hex[:12]}"

def generate_hash(text: str) -> str:
    """Generate SHA256 hash of text"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]

def truncate_text(text: str, max_length: int = 1000) -> str:
    """Truncate text to max length"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def format_sparql_results(results: List[Dict[str, Any]]) -> str:
    """Format SPARQL results as readable text"""
    if not results:
        return "No results found."
    
    # Get all unique keys
    keys = set()
    for result in results:
        keys.update(result.keys())
    keys = sorted(keys)
    
    # Format as table
    lines = []
    lines.append(" | ".join(keys))
    lines.append("-" * (len(keys) * 15))
    
    for result in results[:10]:  # Show first 10
        values = [str(result.get(k, ""))[:20] for k in keys]
        lines.append(" | ".join(values))
    
    if len(results) > 10:
        lines.append(f"\n... and {len(results) - 10} more results")
    
    return "\n".join(lines)

def format_sql_results(results: List[Dict[str, Any]]) -> str:
    """Format SQL results as readable text"""
    return format_sparql_results(results)  # Same format

def extract_code_from_llm_response(response: str) -> str:
    """
    Extract Python code from LLM response
    Handles markdown code blocks
    """
    # Try to find code in ```python ... ``` blocks
    if "```python" in response:
        parts = response.split("```python")
        if len(parts) > 1:
            code_part = parts[1].split("```")[0]
            return code_part.strip()
    
    # Try generic ``` blocks
    if "```" in response:
        parts = response.split("```")
        if len(parts) > 1:
            code_part = parts[1]
            return code_part.strip()
    
    # Return as-is if no code blocks found
    return response.strip()

def extract_sparql_from_llm_response(response: str) -> str:
    """
    Extract SPARQL query from LLM response
    Handles markdown code blocks
    """
    # Try to find SPARQL in ```sparql ... ``` blocks
    if "```sparql" in response.lower():
        parts = response.lower().split("```sparql")
        if len(parts) > 1:
            code_part = parts[1].split("```")[0]
            return code_part.strip()
    
    # Try generic ``` blocks
    if "```" in response:
        parts = response.split("```")
        if len(parts) > 1:
            code_part = parts[1]
            return code_part.strip()
    
    # Look for SELECT or CONSTRUCT keywords
    lines = response.split("\n")
    sparql_lines = []
    in_query = False
    
    for line in lines:
        if any(keyword in line.upper() for keyword in ["SELECT", "CONSTRUCT", "ASK", "DESCRIBE"]):
            in_query = True
        
        if in_query:
            sparql_lines.append(line)
            
            # End when we hit a line that looks like closing brace
            if "}" in line and not "{" in line:
                break
    
    if sparql_lines:
        return "\n".join(sparql_lines).strip()
    
    # Return as-is if no query found
    return response.strip()

def validate_sparql_syntax(query: str) -> tuple[bool, Optional[str]]:
    """
    Basic SPARQL syntax validation
    Returns (is_valid, error_message)
    """
    query_upper = query.upper()
    
    # Check for required keywords
    if not any(kw in query_upper for kw in ["SELECT", "CONSTRUCT", "ASK", "DESCRIBE"]):
        return False, "Missing query type (SELECT, CONSTRUCT, ASK, or DESCRIBE)"
    
    # Check for WHERE clause if SELECT
    if "SELECT" in query_upper and "WHERE" not in query_upper:
        return False, "SELECT queries require WHERE clause"
    
    # Check balanced braces
    if query.count("{") != query.count("}"):
        return False, "Unbalanced braces in query"
    
    # Check for common PREFIX issues
    if "PREFIX" in query_upper and ":" not in query:
        return False, "PREFIX declaration seems malformed"
    
    return True, None

def safe_json_loads(text: str, default: Any = None) -> Any:
    """Safely parse JSON, return default if fails"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default

def safe_json_dumps(obj: Any, default: str = "{}") -> str:
    """Safely dump to JSON, return default if fails"""
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError):
        return default

def calculate_embedding_cost(num_tokens: int, provider: str = "openai") -> float:
    """
    Calculate embedding API cost
    OpenAI: $0.00002 per 1K tokens (text-embedding-3-small)
    """
    if provider == "openai":
        return (num_tokens / 1000) * 0.00002
    return 0.0  # Local is free

def calculate_llm_cost(
    input_tokens: int,
    output_tokens: int,
    provider: str = "openai",
    model: str = "gpt-4-turbo-preview"
) -> float:
    """
    Calculate LLM API cost
    GPT-4 Turbo: $0.01/1K input, $0.03/1K output
    """
    if provider == "openai":
        if "gpt-4" in model.lower():
            input_cost = (input_tokens / 1000) * 0.01
            output_cost = (output_tokens / 1000) * 0.03
            return input_cost + output_cost
        elif "gpt-3.5" in model.lower():
            input_cost = (input_tokens / 1000) * 0.0005
            output_cost = (output_tokens / 1000) * 0.0015
            return input_cost + output_cost
    return 0.0  # Local is free

def estimate_tokens(text: str) -> int:
    """
    Rough token estimation
    ~1 token per 4 characters for English
    """
    return len(text) // 4

class Timer:
    """Simple context manager for timing operations"""
    
    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
        self.end_time = None
        self.logger = get_logger(__name__)
    
    def __enter__(self):
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, *args):
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()
        self.logger.info(f"{self.name} took {duration:.2f}s")
    
    @property
    def duration(self) -> float:
        """Get duration in seconds"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
