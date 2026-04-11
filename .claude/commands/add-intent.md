# Add New Intent to OntoSage

Adding intent: $ARGUMENTS

Follow these steps in order. All are required for a complete, testable intent.

## Step 0 — Define the intent

Before touching code, decide:
- **Intent name** (snake_case, e.g. `maintenance_request`)
- **Trigger phrases** (e.g. "report broken light", "book meeting room")
- **Required nodes** (sparql only? sparql + sql? new node?)
- **Response shape** (text? data table? confirmation?)

## Step 1 — Write the workflow wiring test first (TDD)

File: `tests/test_workflow_wiring.py`

```python
def test_workflow_routes_<intent_name>():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert 'elif intent == "<intent_name>"' in content
```

Run: `pytest tests/test_workflow_wiring.py::test_workflow_routes_<intent_name> -v`
Expected: **FAIL** (intent not yet added)

## Step 2 — Add intent to dialogue agent prompt

File: `orchestrator/agents/dialogue_agent.py`
Location: `_build_intent_detection_prompt()` at line ~362 (the 14-intent list)

Add one line inside the intent taxonomy string:
```
   - "<intent_name>": <one-sentence description of what triggers it>.
```

## Step 3 — Add routing branch

File: `orchestrator/workflow.py`
Function: `_route_from_dialogue()` at line 1079

Add an `elif` branch (before the final `else`/`return "response"`):
```python
elif intent == "<intent_name>":
    return "response"   # change to node name if new node needed
```

## Step 4 — Register new node (only if new processing node needed)

File: `orchestrator/workflow.py` at line ~131

```python
workflow.add_node("<intent_name>", self._safe_node(self._<intent_name>_node, "<intent_name>"))
workflow.add_edge("<intent_name>", "response")
```

Update routing in Step 3 to return `"<intent_name>"` instead of `"response"`.

## Step 5 — Implement node function (only if new node added)

Add to `WorkflowOrchestrator` class in `workflow.py`:

```python
async def _<intent_name>_node(self, state: ConversationState) -> ConversationState:
    """Handle <intent_name> intent."""
    logger.info(f"[<intent_name>] Processing for entities: {state.intermediate_results.get('entities')}")
    try:
        # Your logic here
        state.intermediate_results["<intent_name>_result"] = {
            "acknowledged": True,
            "message": "Request processed."
        }
    except Exception as e:
        logger.error(f"[<intent_name>] Failed: {e}", exc_info=True)
        state.intermediate_results["error"] = f"<intent_name>: {str(e)}"
    return state
```

## Step 6 — Run the wiring test again

```bash
pytest tests/test_workflow_wiring.py::test_workflow_routes_<intent_name> -v
```

Expected: **PASS**

## Step 7 — Run full unit suite

```bash
pytest -m unit -x -q 2>&1 | tail -10
```

Expected: All pass.

## Step 8 — Commit

```bash
git add orchestrator/agents/dialogue_agent.py orchestrator/workflow.py tests/
git commit -m "feat: add <intent_name> intent end-to-end (dialogue → routing → node → test)"
```
