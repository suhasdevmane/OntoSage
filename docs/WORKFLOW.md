# System Workflow Deep Dive

This document provides a comprehensive, "under-the-hood" explanation of the OntoSage 2.0 workflow. It details how requests are processed, how agents interact, and the specific code paths involved in generating answers.

## 1. Request Lifecycle

The journey of a user request follows this path:

1.  **Frontend**: User sends a message via the React UI (`/chat` endpoint).
2.  **Orchestrator (FastAPI)**:
    *   Receives the request in `orchestrator/main.py`.
    *   Validates authentication (`auth_manager.py`).
    *   Loads/Creates `ConversationState` from Redis.
    *   Passes the state to `WorkflowOrchestrator`.
3.  **LangGraph Execution**:
    *   The `WorkflowOrchestrator` (`orchestrator/workflow.py`) initializes the state graph.
    *   Execution starts at the **Dialogue Node**.
4.  **Agent Routing**:
    *   **Dialogue Agent** analyzes the intent (e.g., `sparql`, `sql`, `analytics`, `general`).
    *   The graph routes the state to the appropriate specialized agent.
5.  **Task Execution**:
    *   The specialized agent performs its task (querying DB, running code, etc.).
    *   Results are stored in `state.intermediate_results`.
6.  **Response Generation**:
    *   The flow returns to the **Response Node** (often back to Dialogue Agent or a dedicated response generator).
    *   The LLM synthesizes a final natural language answer using the intermediate results.
7.  **Delivery**:
    *   The final response is saved to Redis/Postgres.
    *   The Orchestrator returns a standardized `APIResponse` JSON to the frontend.

---

## 2. LangGraph Orchestration

The core logic is defined in `orchestrator/workflow.py`. We use **LangGraph** to define a state machine where nodes are agents and edges are routing logic.

### The Graph Structure

```python
# orchestrator/workflow.py

def _build_graph(self) -> StateGraph:
    workflow = StateGraph(ConversationState)
    
    # Nodes
    workflow.add_node("dialogue", self._dialogue_node)
    workflow.add_node("sparql", self._sparql_node)
    workflow.add_node("sql", self._sql_node)
    workflow.add_node("analytics", self._analytics_node)
    workflow.add_node("visualization", self._visualization_node)
    workflow.add_node("response", self._response_node)
    
    # Entry Point
    workflow.set_entry_point("dialogue")
    
    # Conditional Edges (Routing)
    workflow.add_conditional_edges(
        "dialogue",
        self._route_from_dialogue,
        {
            "sparql": "sparql",
            "sql": "sql",
            "analytics": "analytics",
            "visualization": "visualization",
            "response": "response",
            "end": END
        }
    )
    # ... (other edges)
```

### Conversation State

The state passed between agents is defined in `shared/models.py`:

```python
class ConversationState(BaseModel):
    conversation_id: str
    user_message: str
    messages: List[Message]
    current_intent: Optional[str]
    intermediate_results: Dict[str, Any]  # Stores output from SPARQL/SQL agents
    analytics_required: bool
    # ...
```

---

## 3. Agent Internals

### A. Dialogue Agent (`orchestrator/agents/dialogue_agent.py`)
*   **Role**: The "Front Desk". It classifies intent and handles general chit-chat.
*   **Mechanism**:
    1.  Retrieves context from RAG Service (`_retrieve_ontology_context`).
    2.  Constructs a prompt with conversation history and retrieved context.
    3.  Asks the LLM to classify the intent into: `sparql`, `sql`, `analytics`, `visualization`, or `general`.
*   **Code Highlight**:
    ```python
    # Intent Classification Prompt
    prompt = f"""
    Analyze the user's request: "{state.user_message}"
    Determine the best tool to use:
    - SPARQL: For questions about building structure, sensors, rooms, or metadata.
    - SQL: For questions about historical sensor data, temperature readings, energy usage.
    - ANALYTICS: For statistical analysis, correlations, or complex data processing.
    - GENERAL: For greetings, clarifications, or general knowledge.
    """
    ```

### B. SPARQL Agent (`orchestrator/agents/sparql_agent.py`)
*   **Role**: Queries the Ontology (GraphDB).
*   **Workflow**:
    1.  **Schema Retrieval**: Fetches relevant schema parts (classes, properties) from RAG.
    2.  **Query Generation**: Uses LLM to generate a SPARQL query based on the user question and schema.
    3.  **Execution**: Sends the query to GraphDB via HTTP.
    4.  **Caching**: Checks Redis for cached results of identical semantic queries.
*   **Key File**: `orchestrator/agents/sparql_agent.py`

### C. SQL Agent (`orchestrator/agents/sql_agent.py`)
*   **Role**: Queries Time-Series Data (MySQL).
*   **Security**: Implements **Strict SQL Validation** to prevent injection.
    ```python
    def validate_sql(self, query: str) -> bool:
        # Only allow SELECT
        if not re.match(r"^\s*SELECT", query, re.IGNORECASE):
            return False
        # Block DML/DDL
        if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b", query, re.IGNORECASE):
            return False
        return True
    ```
*   **Workflow**: Similar to SPARQL Agent but targets MySQL tables (`sensor_data`, `devices`).

### D. Analytics Agent (`orchestrator/agents/analytics_agent.py`)
*   **Role**: Performs data analysis.
*   **Mechanism**:
    1.  **Template Matching**: Checks if the request matches a pre-defined template (e.g., "correlation between X and Y").
    2.  **Code Generation**: If matched, uses a deterministic Python template. If not, uses LLM to generate Python code.
    3.  **Execution**: Sends the code to the **Code Executor** service (Docker sandbox).
    4.  **Result**: Returns text output or a path to a generated plot image.

---

## 4. RAG Service Workflow

The **RAG Service** (`rag-service/`) bridges the gap between unstructured text and structured knowledge.

1.  **Ingestion**:
    *   Ontology files (`.ttl`) and documents (`.md`, `.pdf`) are chunked.
    *   Embeddings are generated using `sentence-transformers/all-MiniLM-L6-v2`.
    *   Vectors are stored in **Qdrant**.
2.  **Retrieval**:
    *   User query is embedded.
    *   Qdrant performs a vector similarity search.
    *   Top-k results (text chunks + entity URIs) are returned to the Orchestrator.

---

## 5. Data & State Management

### Redis Caching (`orchestrator/redis_manager.py`)
*   **Conversation State**: Persisted after every turn.
*   **Semantic Caching**:
    *   Key: `hash(intent + canonical_query)`
    *   Value: JSON result from DB.
    *   TTL: 1 hour.
    *   Benefit: drastically reduces latency for repeated questions like "What is the temperature?".

### Postgres Persistence (`orchestrator/postgres_manager.py`)
*   Used for long-term storage of user accounts, conversation history, and audit logs.
*   Acts as the "Source of Truth" if Redis is flushed.

---

## 6. API Standardization

All endpoints in `orchestrator/main.py` follow this response format:

```json
{
  "success": true,  // or false
  "data": {         // The actual payload
    "conversation_id": "...",
    "response": "...",
    "intent": "sql"
  },
  "error": null,    // Error message if success is false
  "meta": {         // Debug info, timing, etc.
    "cached": true
  }
}
```

This ensures the frontend can consistently handle success and error states.
