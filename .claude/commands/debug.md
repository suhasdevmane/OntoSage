# OntoSage Pipeline Debugger

You are debugging an OntoSage pipeline failure. Symptom: $ARGUMENTS

## Step 1 — Classify the failure layer

Based on the symptom, identify which layer failed:

| Symptom | Layer | First file to read |
|---------|-------|-------------------|
| Answers wrong question / off-topic | Intent classification | `dialogue_agent.py:356-400` |
| Correct intent but routed wrong | Routing logic | `workflow.py:1079-1130` |
| "I don't have information" (data exists) | SPARQL agent | `sparql_agent.py:165-260` |
| SPARQL works but no time-series | SQL agent / adapter | `sql_agent.py` + `adapters/registry.py` |
| Analytics fails or returns error | Code executor | `analytics_agent.py` + check port 8002 |
| Response is raw JSON / malformed | Response node | `workflow.py:843-1079` |
| Service unreachable / 500 error | Infrastructure | `docker-compose ps` + `docker-compose logs -f orchestrator` |

## Step 2 — Read only the relevant slice

Use the Quick Navigation Index in CLAUDE.md to jump to the right file:line. Read ONLY that section — do not load entire files.

## Step 3 — Invoke systematic-debugging skill

Before proposing any fix, use the `systematic-debugging` skill:
- State the hypothesis
- Identify evidence that confirms or refutes it
- Propose ONE minimal fix
- Verify the fix resolves the symptom

## Step 4 — Check logs

```bash
docker-compose logs orchestrator 2>&1 | grep -E "ERROR|WARNING|intent=" | tail -30
docker-compose logs rag-service 2>&1 | grep ERROR | tail -10
```

## Step 5 — Run the relevant unit test

```bash
pytest -m unit -x -v 2>&1 | tail -30
```

If no test covers this failure, write one BEFORE fixing (TDD).

## Step 6 — Confirm fix and commit

```bash
git add <changed files>
git commit -m "fix: <what was broken and why>"
```
