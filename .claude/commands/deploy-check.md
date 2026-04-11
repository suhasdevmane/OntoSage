# OntoSage Pre-Deployment Checklist

Running production readiness check for: $ARGUMENTS

Work through every gate. Do not mark the deployment ready until ALL pass.

## Gate 1 — Secrets & Git Safety

```bash
# .env must NOT be tracked by git
git ls-files .env && echo "FAIL: .env is tracked by git — add to .gitignore immediately" || echo "PASS: .env not tracked"

# No hardcoded secrets in source
grep -rn --include="*.py" "sk-\|openai.*key.*=.*['\"][a-zA-Z0-9]" orchestrator/ shared/ 2>/dev/null && echo "FAIL: hardcoded secret found" || echo "PASS: no hardcoded secrets"

# CORS check — should NOT be wildcard ["*"]
echo "=== CORS config ==="
grep -n "allow_origins" orchestrator/main.py
```

## Gate 2 — Service Health

```bash
echo "=== Docker services ==="
docker-compose ps

echo "=== Health endpoints ==="
curl -sf http://localhost:8000/health && echo " PASS: orchestrator" || echo " FAIL: orchestrator"
curl -sf http://localhost:8001/health && echo " PASS: rag-service" || echo " FAIL: rag-service"
curl -sf http://localhost:8002/health && echo " PASS: code-executor" || echo " FAIL: code-executor"

echo "=== Redis ==="
docker exec redis redis-cli ping
```

## Gate 3 — Data Integrity

```bash
echo "=== GraphDB triple count ==="
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" | python -m json.tool

echo "=== Building ID ==="
grep BUILDING_ID .env || echo "WARN: BUILDING_ID not set in .env"
```

## Gate 4 — Test Suite

```bash
pytest -m unit -x -q 2>&1 | tail -10
```

Must show: `N passed, 0 failed`

## Gate 5 — Auth Security

```bash
echo "=== Argon2id active ==="
python -c "
from orchestrator.auth_manager import _detect_hasher
h = _detect_hasher()
print(f'Hasher: {h.__class__.__name__}')
"
# Expected: NOT sha256 — should be Argon2id

echo "=== Session TTL (should be 604800 = 7 days) ==="
grep -n "604800\|7.*day\|session.*ttl\|TTL" orchestrator/auth_manager.py | head -5
```

## Gate 6 — Model Provider

```bash
echo "=== MODEL_PROVIDER ==="
grep MODEL_PROVIDER .env || echo "WARN: MODEL_PROVIDER not set"

echo "=== Ollama models (if local) ==="
docker exec ollama ollama list 2>/dev/null || echo "Ollama not running (OK if MODEL_PROVIDER=openai)"
```

## Manual Checklist

- [ ] Log level is `INFO` in production (not `DEBUG`) — check `shared/config.py`
- [ ] GraphDB backup taken before deploy
- [ ] `MODEL_PROVIDER` correct for this deployment (`local` or `openai`)
- [ ] OpenAI API key set if `MODEL_PROVIDER=openai`
- [ ] Stakeholders notified of maintenance window
- [ ] Rollback plan documented (previous Docker image tag saved)
- [ ] `depends_on` health conditions set in `docker-compose.yml` for all critical services

**If all gates pass:** Deployment approved. Run `docker-compose up -d` on target server.
