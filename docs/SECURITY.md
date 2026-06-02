# Security Guide

This guide covers authentication, role-based access control, the analytics code sandbox, secrets management, network security, and security best practices for OntoSage deployments.

---

## Authentication

### Password Hashing

OntoSage uses **Argon2id** for all password hashing — the current winner of the Password Hashing Competition and the recommendation of OWASP for new applications.

Key properties of the implementation (`orchestrator/auth_manager.py`):

- **Algorithm:** Argon2id (hybrid of Argon2i and Argon2d)
- **Memory cost:** 64 MB (configurable)
- **Time cost:** 3 iterations
- **Parallelism:** 4 threads
- **Output length:** 32 bytes

**Legacy SHA-256 migration:** If a deployment was originally using the old SHA-256 password scheme, OntoSage detects this on first login and transparently re-hashes the password to Argon2id. No user action is required.

### Session Tokens

- Sessions are 32-byte cryptographically random tokens generated via `os.urandom(32)`
- Stored in Redis with a **7-day TTL**
- Transmitted in the `Authorization: Bearer <token>` header
- Invalidated on logout or when the TTL expires
- Never logged, never included in error messages

### Brute Force Protection

- Failed login attempts are rate-limited at the application level
- After 5 consecutive failures, the account is temporarily locked for 15 minutes
- All authentication events (success, failure, lockout) are logged with trace IDs

---

## Role-Based Access Control (RBAC)

OntoSage enforces a **6-role, 20-permission** RBAC model. Every API endpoint is protected by a permission check using FastAPI's dependency injection.

### Roles

| Role | Description | Typical User |
|------|-------------|-------------|
| `admin` | Full system access + user management | IT administrator |
| `facility_manager` | All data + configuration read access | Building manager |
| `analyst` | Data read, analytics, exports | Data scientist, sustainability team |
| `operator` | Sensor data and anomaly monitoring | BMS operator, HVAC technician |
| `occupant` | Current conditions for accessible zones | Building tenant |
| `readonly` | Discovery and metadata only | Auditor, visitor |

### Permissions

| Permission | Roles that have it | Description |
|------------|-------------------|-------------|
| `sensor:read` | admin, facility_manager, analyst, operator, occupant | Read sensor readings |
| `analytics:read` | admin, facility_manager, analyst | Run analytics and statistics |
| `metadata:read` | all roles | Query ontology structure |
| `report:read` | admin, facility_manager, analyst, operator | Generate reports |
| `export:read` | admin, facility_manager, analyst | Download data files |
| `anomaly:read` | admin, facility_manager, analyst, operator | View anomaly alerts |
| `trend:read` | admin, facility_manager, analyst | View historical trends |
| `comparison:read` | admin, facility_manager, analyst | Compare zones/periods |
| `compliance:read` | admin, facility_manager, analyst | Compliance reports |
| `config:read` | admin, facility_manager | Read system configuration |
| `config:write` | admin | Modify system configuration |
| `user:read` | admin | View user accounts |
| `user:write` | admin | Create or modify users |
| `user:delete` | admin | Delete user accounts |
| `building:read` | admin, facility_manager | Read building metadata |
| `building:write` | admin | Modify building configuration |
| `building:delete` | admin | Remove buildings |
| `system:admin` | admin | System administration tasks |
| `system:health` | all roles | Check service health |
| `forecast:read` | admin, facility_manager, analyst | View forecasts |

### Enforcing Permissions on Endpoints

Use the `create_rbac_dependency` factory in every data endpoint:

```python
from orchestrator.middleware.rbac import create_rbac_dependency, UserContext
from fastapi import Depends

@app.get("/api/v1/analytics")
async def run_analytics(
    request: Request,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "analytics:read")),
):
    # user.role, user.tenant_id, user.allowed_buildings available
    ...
```

Health endpoints explicitly skip RBAC (Docker health checks require unauthenticated access):

```python
@app.get("/health")
async def health():
    """No authentication required — used by Docker health checks."""
    ...
```

### Tenant Isolation

Each user account is associated with a `tenant_id`. Queries are automatically scoped to the user's tenant, preventing cross-tenant data access even when users share the same OntoSage instance.

---

## Code Execution Sandbox

The analytics agent generates Python code and submits it to the `code-executor` service for sandboxed execution. This is the most security-sensitive part of the system.

### Isolation Layers

**Docker container isolation:**
- Runs as a non-root user inside the container
- No network access to external services (internal network only)
- Read-only filesystem except for `/tmp`
- No access to host filesystem

**Resource limits (configured in `docker-compose.yml`):**
- CPU: 1 core maximum
- Memory: 512 MB (default), configurable via `CODE_EXECUTOR_MEMORY_LIMIT`
- Execution timeout: 30 seconds (configurable via `CODE_EXECUTOR_TIMEOUT`)

**Python-level restrictions (`code-executor/sandbox.py`):**

The sandbox uses `RestrictedPython` to evaluate code with a whitelist:

```python
# Allowed imports (data science only)
SAFE_MODULES = {
    "pandas", "numpy", "matplotlib", "plotly",
    "datetime", "math", "statistics", "json",
    "collections", "itertools", "functools",
}

# Blocked at import time
BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "requests",
    "urllib", "http", "ftplib", "smtplib", "pickle",
    "ctypes", "threading", "multiprocessing",
}
```

**What the LLM can generate:**
- Data manipulation with pandas/numpy
- Statistical computations
- Matplotlib/plotly chart generation
- Datetime arithmetic

**What is explicitly blocked:**
- File system access (`open()`, `os.path`, etc.)
- Network calls (`requests`, `urllib`, `socket`)
- Process execution (`subprocess`, `os.system`)
- Module imports not in the whitelist
- Infinite loops (terminated by timeout)

### Example Safe Analytics Code

```python
import pandas as pd
import numpy as np

# sensor_data is injected by the orchestrator
df = pd.DataFrame(sensor_data)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df.sort_values("timestamp")

result = {
    "mean": float(df["value"].mean()),
    "max": float(df["value"].max()),
    "min": float(df["value"].min()),
    "std": float(df["value"].std()),
    "count": int(len(df)),
}
```

### What Happens on Policy Violation

If generated code attempts a blocked operation, the sandbox returns a `403 Forbidden` response. The analytics agent catches this, logs the violation with the trace ID, and returns an error message to the user.

---

## SQL Injection Prevention

All SPARQL and SQL queries are LLM-generated — user input is never directly interpolated into query strings. The flow is:

1. User provides natural language (e.g., "temperature in Zone 5")
2. Dialogue agent extracts structured entities (zone name, sensor type)
3. SPARQL/SQL agent passes structured entities to the LLM as context
4. LLM generates the query — user text never enters the query template
5. SPARQL validator checks syntax before execution
6. SQL adapter uses parameterised queries when binding values

This architecture makes SQL injection structurally impossible because user input is never in the query path.

Additionally, the SQL agent blocks these keywords in generated queries:
```python
BLOCKED_SQL_KEYWORDS = ["DROP", "DELETE", "INSERT", "UPDATE", "CREATE",
                        "ALTER", "TRUNCATE", "EXEC", "EXECUTE", "GRANT",
                        "REVOKE", "MERGE"]
```

---

## Network Security

### Docker Network Architecture

OntoSage uses two Docker networks:

| Network | Purpose | Exposed to Host |
|---------|---------|-----------------|
| `ontobot-agentic` | Internal service-to-service communication | No |
| `ontobot-network` | External integration (Open WebUI ↔ Orchestrator) | Via mapped ports |

Services communicate using Docker DNS names (`redis`, `graphdb`, `mysql`, etc.). No service is accessible from outside Docker except through explicitly mapped host ports.

### Exposed Ports (Default)

| Port | Service | Exposure |
|------|---------|---------|
| 3000 | Open WebUI (chat interface) | Public |
| 8000 | Orchestrator API | Public (for API clients) |
| 8001 | RAG Service | Internal only (no host mapping) |
| 8002 | Code Executor | Internal only |
| 7200 | GraphDB Workbench | Admin only — restrict in production |
| 6379 | Redis | Internal only |
| 3306/3307 | MySQL | Internal only |
| 5433 | PostgreSQL | Internal only |
| 6333 | Qdrant | Internal only |
| 27017 | MongoDB | Internal only |

### Production Network Hardening

For production deployments:

1. **Place a reverse proxy (nginx or Caddy) in front of the exposed services.** See the [Deployment Guide](DEPLOYMENT.md#production-deployment-considerations).

2. **Remove GraphDB's host port mapping** unless you need remote admin access:
   ```yaml
   # docker-compose.yml — remove or comment out the ports: section for graphdb
   graphdb:
     # ports:
     #   - "7200:7200"
   ```

3. **Restrict the Orchestrator API to localhost** if you are only using it via Open WebUI:
   ```yaml
   orchestrator:
     ports:
       - "127.0.0.1:8000:8000"   # localhost only
   ```

4. **Enable TLS** for all externally exposed services via your reverse proxy.

---

## Secrets Management

### Development

Use `.env` for local development. The `.env` file is in `.gitignore` and must never be committed.

```bash
cp .env.example .env
# Edit .env — add real credentials
```

### Secret Hygiene Built In

OntoSage hardens secret handling in two ways:

- **Masked configuration.** Secret-bearing settings (`OPENAI_API_KEY`, `OLLAMA_CLOUD_API_KEY`, `GRAPHDB_PASSWORD`, `POSTGRES_USER_PASSWORD`, `MYSQL_PASSWORD`, `SECRET_KEY`) are excluded from the application's config representation, so they are never echoed into logs, error traces, or test output.
- **`STRICT_SECRETS` boot guard.** Set `STRICT_SECRETS=true` in production and the orchestrator **refuses to start** if any password is still its built-in default (e.g. the shipped GraphDB/Postgres/MySQL placeholders). This fails closed — a misconfigured deployment never silently runs on default credentials.

```bash
# Production .env
STRICT_SECRETS=true
GRAPHDB_PASSWORD=<your-strong-password>
POSTGRES_USER_PASSWORD=<your-strong-password>
MYSQL_PASSWORD=<your-strong-password>
SECRET_KEY=<openssl rand -hex 32>
```

### Production: Docker Secrets

For production, use Docker Secrets to avoid storing credentials in environment variables (which appear in `docker inspect`):

```yaml
# docker-compose.prod.yml
services:
  orchestrator:
    secrets:
      - openai_api_key
      - mysql_password
      - postgres_password

secrets:
  openai_api_key:
    external: true
  mysql_password:
    external: true
  postgres_password:
    external: true
```

Create the secrets:

```bash
echo "sk-your-openai-key" | docker secret create openai_api_key -
echo "your-mysql-password" | docker secret create mysql_password -
echo "your-postgres-password" | docker secret create postgres_password -
```

### Rotating Secrets

To rotate a secret:

```bash
# Remove old secret (after updating containers to use new value)
docker secret rm openai_api_key

# Create new secret
echo "sk-new-key" | docker secret create openai_api_key -

# Restart services that use it
docker compose restart orchestrator
```

### What to Never Log

The application is instrumented to never log:
- Passwords or password hashes
- Session tokens
- API keys
- Database connection strings with credentials

If you add new functionality, ensure `logger.debug()` calls do not include any of the above.

---

## Data Privacy

### Local Mode (Ollama)

When `MODEL_PROVIDER=local`, all LLM inference happens inside your Docker environment. No data leaves the server. This mode is suitable for:
- Air-gapped networks
- High-security facilities (government, defence, R&D, hospitals)
- GDPR-restricted deployments where sensor data cannot leave the EU
- Organisations with policies prohibiting cloud AI services

### Cloud Mode (OpenAI)

When `MODEL_PROVIDER=openai`, the following data is sent to OpenAI's API:
- The user's natural language question
- Context extracted from the ontology (entity names, zone names)
- Analytics task descriptions

**Sensor readings are never sent to OpenAI.** The SQL queries return raw numbers that are processed locally; only the task specification (e.g., "compute mean and std of these values") goes to the API.

Refer to [OpenAI's data privacy policy](https://openai.com/policies/privacy-policy) for information on data retention and processing.

### Conversation History

- **Redis:** Recent conversation state is count-bounded to `CONVERSATION_MAX_MESSAGES` with no time-expiry by default (set `CONVERSATION_TTL` > 0 to enforce time-based expiry)
- **PostgreSQL:** Per-turn summaries in `turn_memory` (no raw sensor arrays)
- **MongoDB:** Full message history is persisted for audit and conversation continuity
- **Retention policy:** Set your MongoDB TTL index according to your organisation's data retention requirements

---

## Security Checklist for Production

Before deploying OntoSage to production:

- [ ] Changed all default passwords in `.env` (`MYSQL_PASSWORD`, `POSTGRES_USER_PASSWORD`, `API_KEY`)
- [ ] Generated a strong `SECRET_KEY` (`openssl rand -hex 32`)
- [ ] Moved secrets to Docker Secrets (not environment variables)
- [ ] Removed host port mappings for internal-only services (Redis, GraphDB, MySQL, PostgreSQL)
- [ ] Placed nginx or Caddy reverse proxy in front of Open WebUI and Orchestrator API
- [ ] Enabled TLS on the reverse proxy with a valid certificate
- [ ] Restricted GraphDB Workbench to admin network or removed host port
- [ ] Confirmed `.env` file is in `.gitignore` and not committed
- [ ] Set `LOG_LEVEL=INFO` (not DEBUG) in production
- [ ] Reviewed RBAC role assignments — principle of least privilege
- [ ] Enabled Docker resource limits for the code executor container
- [ ] Scheduled regular base image updates (`docker compose pull`)
- [ ] Configured MongoDB TTL index for conversation history retention

---

## Reporting Security Vulnerabilities

If you discover a security vulnerability in OntoSage, please report it privately:

1. Do **not** open a public GitHub issue
2. Email the maintainers at the address in the repository's `SECURITY.md` (repo root)
3. Include a description of the vulnerability, steps to reproduce, and potential impact
4. Allow up to 14 days for a response before any public disclosure

We follow coordinated disclosure practices and will credit researchers in the changelog.
