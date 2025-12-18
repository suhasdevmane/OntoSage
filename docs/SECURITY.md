# Security & Isolation

## Code Execution
- Executed in dedicated container with limited CPU/RAM
- No network access (recommended); only whitelisted paths
- Timeouts enforced via config (`CODE_EXECUTOR_TIMEOUT`)

## Secrets
- Never commit `.env` with real keys
- Use environment variables and Docker secrets where possible

## Network
- Prefer internal networks; restrict external binds to localhost
- GraphDB ports are bound to 127.0.0.1 by default in compose

## Authentication
- API keys for Abacws API
- Optional auth for orchestrator endpoints (planned)

## Supply Chain
- Pin base images when possible
- Rebuild regularly and keep images updated
