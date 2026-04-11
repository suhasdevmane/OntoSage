# OntoSage Test Runner

Running tests for: $ARGUMENTS

## Step 1 — Quick unit tests (always first)

```bash
pytest -m unit -x -v 2>&1 | tail -40
```

If any fail — stop and fix before proceeding. Unit tests must always be green.

## Step 2 — Coverage report

```bash
pytest -m unit --cov=orchestrator --cov-report=term-missing 2>&1 | grep -E "FAIL|ERROR|orchestrator/" | tail -40
```

Look for lines with `< 70%` coverage. Priority gaps to fill:

| File | Why it matters |
|------|---------------|
| `orchestrator/workflow.py` | Routing functions critical for correctness |
| `orchestrator/services/disambiguation_service.py` | New file, zero coverage |
| `orchestrator/services/circuit_breaker.py` | State transitions must be tested |
| `orchestrator/auth_manager.py` | SHA-256→Argon2id migration path |
| `orchestrator/agents/anomaly_agent.py` | Spike detection edge cases |

## Step 3 — Integration tests (only if services running)

```bash
docker-compose ps    # confirm all services healthy first
pytest -m integration -v 2>&1 | tail -40
```

## Step 4 — Specific file or test

```bash
# Run specific file
pytest tests/$ARGUMENTS -v 2>&1 | tail -40

# Run specific test
pytest tests/test_phase3_4_services.py::test_ontology_validator -v
```

## Step 5 — Fix failing tests protocol

1. Read the full error traceback — identify the exact failing assertion
2. Check if it's a stale mock (mock returns wrong type/value after a model change)
3. Check if a field was renamed in `shared/models.py`
4. Fix the test OR the implementation — never comment out a failing test
5. Re-run to confirm green

## Common Test Markers Reference

```bash
pytest -m unit              # No external services — fast, always in CI
pytest -m integration       # Requires docker-compose up
pytest -m slow              # Tests >5 seconds
pytest -m live              # Requires live GraphDB + real ontology
pytest -m "not live"        # Everything except live DB tests
pytest -m "unit or integration"  # Combined
```
