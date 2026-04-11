# OntoSage Security + Code Quality Audit

Auditing: $ARGUMENTS

## Phase 1 — Automated Scans

```bash
echo "=== Security scan (bandit) ==="
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests 2>&1 | tail -30

echo "=== Dependency vulnerabilities ==="
pip-audit --requirement orchestrator/requirements.txt 2>&1 | tail -20

echo "=== Format compliance (black) ==="
black --check --line-length 100 orchestrator/ shared/ 2>&1 | tail -20

echo "=== Import order (isort) ==="
isort --check-only --profile black orchestrator/ tests/ 2>&1 | tail -10

echo "=== Static analysis (flake8) ==="
flake8 orchestrator/ shared/ --max-line-length 110 --extend-ignore=E203,E501,W503 2>&1 | tail -20
```

## Phase 2 — Auth & Session Audit

Review these manually:

```bash
# Is Argon2id the active hasher?
grep -n "_detect_hasher\|Argon2\|sha256" orchestrator/auth_manager.py | head -10

# Session token generation — must be secrets.token_hex(32), not UUID
grep -n "session_token\|token_hex\|uuid" orchestrator/auth_manager.py | head -10

# Session TTL — must be 604800 (7 days) max
grep -n "604800\|TTL\|expire" orchestrator/auth_manager.py | head -10

# validate_session checks expiry?
grep -n "expire\|ttl\|check" orchestrator/auth_manager.py | grep -i "validate\|session" | head -10
```

## Phase 3 — RBAC Coverage

```bash
# All data endpoints must use require_permission()
echo "=== Endpoints WITHOUT require_permission ==="
grep -n "@app\.\(get\|post\|put\|delete\)" orchestrator/main.py | head -30

echo "=== require_permission usage ==="
grep -n "require_permission\|Depends.*rbac" orchestrator/main.py | head -20
```

Verify every data endpoint (`/chat`, `/api/v1/*`) has `Depends(create_rbac_dependency(...))`.

## Phase 4 — Input Validation

```bash
# Find raw request.json() usage (dangerous — must use Pydantic instead)
grep -rn "request\.json()\|request\.body()" orchestrator/ 2>/dev/null

# Confirm Pydantic models on POST bodies
grep -n "class.*Request\|class.*Body\|BaseModel" orchestrator/main.py | head -20
```

## Phase 5 — Network Exposure

```bash
# Which ports are exposed externally in docker-compose?
grep -A2 "ports:" docker-compose.yml | grep -v "^--$" | head -30
```

Internal services (GraphDB 7200, Redis 6379, MySQL 3306) should NOT be exposed to public internet — only the orchestrator (8000) should be.

## Phase 6 — Invoke Security Auditor Agent

Use the `security-auditor` agent (`.claude/security-auditor.md`) for comprehensive DevSecOps review covering:
- OWASP Top 10 for the API surface
- WebSocket security
- Code execution sandbox (port 8002) isolation
- Secrets chain from `.env` to runtime

## Phase 7 — Code Quality Review

Invoke the `superpowers:requesting-code-review` skill for a final review against:
- State immutability in LangGraph nodes
- `_safe_node` wrapper usage on all nodes
- Error isolation (no bare `except:`)
- Test coverage for all changed files
