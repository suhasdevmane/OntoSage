# LangGraph Agent Node Patterns — OntoSage

These patterns MUST be followed for every new agent node in `orchestrator/workflow.py`.

## 1. Always Use the _safe_node Wrapper

```python
# CORRECT — always wrap
workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))

# WRONG — never register bare
workflow.add_node("my_node", self._my_node_fn)
```

The `_safe_node` wrapper at `workflow.py:191` catches exceptions, logs them with context, and returns the state with an `"error"` key so the pipeline continues gracefully instead of crashing the entire session.

## 2. Node Function Signature

```python
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description of what this node does."""
    logger.info(f"[my_node] intent={state.intent}, entities={state.intermediate_results.get('entities', [])}")
    # ... do work ...
    state.intermediate_results["my_result"] = result
    return state
```

Rules:
- Always `async def`
- Always returns the same `ConversationState` object (mutated in place)
- Always log entry with intent for debuggability
- One-line docstring required

## 3. State Mutation Rules

```python
# CORRECT — write to your own key
state.intermediate_results["my_node_result"] = {"data": ..., "success": True}

# CORRECT — read previous results with default
sparql_data = state.intermediate_results.get("sparql_results", [])
uuids = state.intermediate_results.get("uuids", [])

# WRONG — overwrite another node's key
state.intermediate_results["sparql_results"] = []  # breaks SPARQL→SQL data handoff

# WRONG — add new top-level state fields without updating shared/models.py
state.my_new_field = "something"
```

Reserved keys (do not overwrite):
- `intent`, `entities`, `time_range` — set by dialogue node
- `sparql_results`, `uuids` — set by sparql node
- `sql_data` — set by sql node
- `analytics_output` — set by analytics node
- `visualization_path` — set by visualization node
- `error` — set by _safe_node on failure

## 4. Error Handling Inside Nodes

```python
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """Handle my_node intent."""
    try:
        result = await some_service_call(timeout=30)
        state.intermediate_results["my_result"] = result
    except asyncio.TimeoutError:
        logger.warning("[my_node] Service timed out — returning empty result")
        state.intermediate_results["my_result"] = {}
        state.intermediate_results["error"] = "my_node: timeout after 30s"
    except Exception as e:
        logger.error(f"[my_node] Unexpected error: {e}", exc_info=True)
        state.intermediate_results["error"] = f"my_node: {str(e)}"
    return state
```

Do NOT raise from inside a node — always catch, log, set error key, and return state.

## 5. Adding a New Node — Complete Checklist (Phase 13B — 2026-05-29)

Adding a new pipeline intent is now **two steps**, not five.  The previous
manual `_build_graph` / `_route_from_dialogue` edits are obsolete.

```yaml
# Step 1: Append to orchestrator/intents/intent_definitions.yaml
#         (or input/<BUILDING_ID>/intents.yaml for per-building overlays)
- name: my_intent
  description: |-
    Tell the LLM what this intent handles.  Include trigger phrases.
  examples:
    - '"example user query 1"'
    - '"example user query 2"'
  pipeline_group: standalone           # data | standalone | meta
  route_target: my_node                # graph node name (defaults to intent name)
  node_method: _my_node_fn             # method on WorkflowOrchestrator
```

```python
# Step 2: Implement the handler on WorkflowOrchestrator
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description."""
    # ... agent logic ...
    state.intermediate_results["my_result"] = result
    return state
```

Outgoing edges, routing dispatch, and graph wiring are all auto-generated.
Restart the orchestrator and your intent is live.

Tests:

```python
# tests/test_routing_accuracy.py — add a canonical case
("trigger query phrasing", "my_intent", "my_node"),

# tests/test_intent_graph_autowire.py runs on every build and asserts:
#   - the intent's node_method exists on WorkflowOrchestrator
#   - the resulting node was registered into the LangGraph state machine
```

Only modify `_build_graph` directly when adding a **shared pipeline stage**
(sparql, sql, analytics, response) — those are not 1:1 with any intent and
remain hardcoded.

### Legacy 5-step checklist (pre-Phase-13, kept for context only)

```python
# Step 1: Implement node function in WorkflowOrchestrator class
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    ...

# Step 2: Register in _build_graph() at line ~131
workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))

# Step 3: Add outgoing edge at line ~186
workflow.add_edge("my_node", "response")

# Step 4: Add routing in _route_from_dialogue() at line ~1079
elif intent == "my_intent":
    return "my_node"   # must EXACTLY match the add_node() name

# Step 5: Write test in tests/test_workflow_wiring.py
def test_workflow_routes_my_intent():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert 'elif intent == "my_intent"' in content
    assert 'workflow.add_node("my_node"' in content
```

## 6. Routing Function Pattern

```python
def _route_from_dialogue(self, state: ConversationState) -> str:
    """Route to appropriate node based on classified intent."""
    intent = state.intermediate_results.get("intent", "general")

    if intent == "sensor_data":
        return "sparql"
    elif intent == "my_intent":
        return "my_node"   # exact match to add_node() name
    # ... other branches ...
    else:
        return "response"  # safe default fallback
```

**Critical:** Return values MUST exactly match registered node names — a typo silently routes to a non-existent node with no error.
