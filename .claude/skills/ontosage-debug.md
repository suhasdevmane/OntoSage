---
name: ontosage-debug
description: Use when an OntoSage pipeline query returns wrong or empty results, an agent node fails, or a service is unreachable. Systematic root-cause methodology for the LangGraph multi-agent pipeline.
---

# OntoSage Pipeline Debug Runbook

Every pipeline failure lives in one layer. Find the layer first — then fix.

## The Pipeline Layers

```
User query (WebSocket / HTTP)
    ↓
[Layer 1] dialogue_agent — intent classification + entity extraction
          File: orchestrator/agents/dialogue_agent.py
    ↓
[Layer 2] workflow.py routing — _route_from_dialogue() conditional edges
          File: orchestrator/workflow.py:1079
    ↓
[Layer 3a] sparql_agent — SPARQL generation + GraphDB execution
           File: orchestrator/agents/sparql_agent.py:165
[Layer 3b] sql_agent — time-series fetch via storage adapter
           File: orchestrator/agents/sql_agent.py + services/adapters/
[Layer 3c] analytics_agent — code generation + code-executor (port 8002)
           File: orchestrator/agents/analytics_agent.py
    ↓
[Layer 4] _response_node — markdown assembly for all users
          File: orchestrator/workflow.py:843
    ↓
User response
```

## Universal First Steps

```bash
# 1. All services running?
docker-compose ps

# 2. Recent errors?
docker-compose logs orchestrator 2>&1 | grep -E "ERROR|WARNING" | tail -20

# 3. Orchestrator healthy?
curl -sf http://localhost:8000/health | python -m json.tool
```

## Layer 1 Diagnosis: Intent Wrong

**Symptom:** Response answers a different question / routes to wrong path / "I don't understand"

```bash
docker-compose logs orchestrator 2>&1 | grep "intent=\|Intent:" | tail -20
```

**Root cause:** Dialogue agent LLM misclassified the intent.

**Fix:** Edit `orchestrator/agents/dialogue_agent.py:_build_intent_detection_prompt()` at line ~362. Add clearer examples or sharpen the intent description. The LLM is given exactly these descriptions to classify.

## Layer 2 Diagnosis: Routed to Wrong Node

**Symptom:** Intent detected correctly but wrong data path executed (e.g. analytics when only discovery needed)

Read: `orchestrator/workflow.py:1079` — `_route_from_dialogue()`

Check: Does the `elif intent == "..."` branch for this intent return the correct node name?

**Fix:** Correct the return value. Verify return value EXACTLY matches `add_node()` name at line ~131.

## Layer 3a Diagnosis: SPARQL Empty

**Symptom:** "I don't have information about..." — but data IS in the ontology

```bash
# Test SPARQL directly (bypasses all application code)
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT ?s ?type WHERE { ?s a ?type } LIMIT 10"
```

- **Empty results:** Data not loaded → run `python scripts/onboard_building.py --building-id bldg1`
- **SPARQL syntax error:** Check prefixes in `sparql_agent.py:_generate_sparql()`
- **GraphDB unreachable:** `curl http://localhost:7200/rest/repositories`

## Layer 3b Diagnosis: SQL Empty

**Symptom:** SPARQL found entities/UUIDs but no time-series data returned

```bash
docker-compose logs orchestrator 2>&1 | grep "sql_agent\|UUID\|adapter" | tail -20
```

Check: `orchestrator/services/adapters/registry.py` — is the building ID registered? Is the correct DB adapter wired?

## Layer 3c Diagnosis: Analytics Failure

**Symptom:** Analytics returns error, empty, or hangs

```bash
curl -sf http://localhost:8002/health && echo "OK" || echo "code-executor DOWN"
docker-compose logs code-executor | tail -20
```

The code-executor sandbox (port 8002) must be running. Check it's healthy before debugging the analytics agent logic.

## Layer 4 Diagnosis: Response Malformed

**Symptom:** Raw JSON in response, code visible to user, or missing sections

Read: `orchestrator/workflow.py:843` — `_response_node()`

Check: Which keys are populated in `state.intermediate_results` at that point? The response node assembles from `sparql_results`, `sql_data`, `analytics_output`, etc.

## Using Skills

After identifying the layer, invoke the matching skill:
- Layer 1-2: `/skill langgraph` + use `pipeline-agent`
- Layer 3a: use `ontology-agent`
- Layer 3b: check `infra-agent` for adapter config
- Layer 3c: use `infra-agent` for code-executor
- All layers: `/skill systematic-debugging` for root-cause discipline

## Writing a Regression Test After Fixing

Always write a test that would have caught this failure before committing the fix:

```python
@pytest.mark.unit
def test_<describe_what_broke>():
    """Regression: <what was wrong and where>."""
    # Minimal reproduction that fails without the fix
    ...
```
