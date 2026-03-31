# Workflow Deep Dive: From Intent to Action

This document details the "under-the-hood" mechanics of **OntoSage**, explaining how it achieves **Zero-Knowledge Interaction** and **Persona-Agnostic Adaptation**.

## 1. The Cognitive Lifecycle

The journey of a user request follows a sophisticated path designed to abstract complexity:

1.  **Input**: User speaks or types a query into **Open WebUI** (e.g., "It's too hot in the conference room").
2.  **Orchestrator (FastAPI)**:
    *   Receives the request and loads the `ConversationState` from Redis.
    *   **Memory Retrieval**: Queries **Qdrant** to fetch relevant past conversation history (e.g., user previously mentioned "Building 1").
    *   **Persona Inference**: Based on the user's history and query complexity, the system infers a persona (e.g., "Occupant" vs. "Facility Manager").
3.  **LangGraph Execution**:
    *   The `WorkflowOrchestrator` initializes the state graph.
    *   **Intent Classification**: The **Dialogue Agent** determines the goal.
        *   *Example*: "It's too hot" -> `Intent: Comfort_Complaint` -> `Action: Check_Temperature_Sensor`.
4.  **Zero-Knowledge Translation**:
    *   **SPARQL Agent**: Maps "Conference Room" to `bldg:Room-101` using **GraphDB Similarity Indexing**. It does not use external vector stores for this mapping.
    *   **SQL Agent**: Maps "Temperature" to the specific sensor UUID `sensor_123` and generates a SQL query.
5.  **Multi-Objective Reasoning**:
    *   If the user asks "Optimize energy for this room," the **Analytics Agent** balances conflicting goals (Comfort vs. Energy) using a Python-based optimization script.
6.  **Response Generation**:
    *   The LLM synthesizes the technical data (24.5°C) into a natural response ("The temperature is 24.5°C, which is 2 degrees above the setpoint.").
    *   **Visualization Agent**: Generates a Plotly chart if a trend was detected.

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
    1.  **Memory Lookup**: Queries Qdrant for similar past user queries.
    2.  **Context Retrieval**: Calls RAG Service (`_retrieve_ontology_context`) which uses **GraphDB Similarity** to find relevant ontology concepts.
    3.  **Prompt Construction**: Constructs a prompt with conversation history, memory context, and retrieved ontology context.
    4.  **Classification**: Asks the LLM to classify the intent into: `sparql`, `sql`, `analytics`, `visualization`, or `general`.
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
