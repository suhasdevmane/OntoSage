# MCP Server Fix & Activation Design

**Goal:** Fix 3 bugs in the existing `mcp-server/main.py`, add session continuity, activate both stdio (Claude Desktop) and streamable-http (Cursor) transports with ready-to-paste config files.

**Architecture:** Thin proxy pattern — MCP tools translate to orchestrator `/chat` calls. Session continuity via module-level `_sessions` dict. Transport selected by `MCP_TRANSPORT` env var.

**Tech Stack:** `mcp>=1.2.0` (FastMCP), `httpx`, Python 3.11

---

## Bug Fixes (3)

### Bug 1: Auth endpoint mismatch
Current `_login()` calls `/auth/token` which does not exist in the orchestrator.
Fix: Remove the login step entirely. Auth is handled by passing `X-API-Key: {MCP_AUTH_TOKEN}` in every request header. If `MCP_AUTH_TOKEN` is empty, requests are unauthenticated (fine for local deployments).

### Bug 2: Port / transport mismatch
Current: Dockerfile `EXPOSE 8003`, docker-compose maps `8003:8003`, but `MCP_SSE_PORT` defaults to `8080` — the container listens on 8080 but only 8003 is reachable from outside.
Fix: Switch to `streamable-http` transport (replaces SSE in MCP spec ≥1.2). FastMCP's `streamable-http` respects `MCP_HTTP_PORT` env var, defaulting to `8003`. Dockerfile updated to `EXPOSE 8003`.

### Bug 3: Broken secondary endpoint in `generate_document`
Current: calls `/api/v1/documents/generate` after the `/chat` call. This endpoint does not exist in the orchestrator.
Fix: Remove the secondary HTTP call. Return the chat response only. If a download URL is present in the chat response, it is included as-is.

---

## Session Continuity

```python
# Module-level session registry
_sessions: Dict[str, str] = {}

def _get_or_create_session(key: str) -> str:
    """Return existing session_id for key, or create and store a new UUID."""
    if key not in _sessions:
        _sessions[key] = str(uuid.uuid4())
    return _sessions[key]
```

**stdio mode:** `key = "stdio"` — one session for the entire Claude Desktop process lifetime.

**streamable-http mode:** `key = client_ip` extracted from the FastMCP request context — one session per editor/client connection.

Every tool gains an optional `session_id: str = ""` parameter. If provided, it is used directly (caller override). If empty, `_get_or_create_session(key)` is called.

The `session_id` is passed as the `session_id` field in every `/chat` POST body. The orchestrator stores conversation state in Redis with a 1-hour TTL — no Redis dependency is added to the MCP server.

---

## Transport Split

| Mode | Transport | How it starts | Client config |
|------|-----------|---------------|---------------|
| stdio | `stdio` | Claude Desktop spawns `python main.py` as child process | `claude_desktop_config.json` |
| HTTP | `streamable-http` | Docker container `ontosage-mcp-server` on port 8003 | `cursor_mcp.json` |

Both modes share one `main.py`. `MCP_TRANSPORT` env var selects the mode.

**Entry point logic:**
```python
if MCP_TRANSPORT == "streamable-http":
    mcp.run(transport="streamable-http", port=MCP_HTTP_PORT)
else:
    mcp.run(transport="stdio")
```

---

## Config Files

### `mcp-server/claude_desktop_config.json`
Paste the `mcpServers` block into `~/.config/claude/claude_desktop_config.json` (Mac/Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):
```json
{
  "mcpServers": {
    "ontosage": {
      "command": "python",
      "args": ["C:/path/to/OntoSage/mcp-server/main.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "ORCHESTRATOR_URL": "http://localhost:8000",
        "MCP_AUTH_TOKEN": ""
      }
    }
  }
}
```

### `mcp-server/cursor_mcp.json`
Paste into Cursor → Settings → MCP (or `.cursor/mcp.json` in the project root):
```json
{
  "mcpServers": {
    "ontosage": {
      "url": "http://localhost:8003/mcp"
    }
  }
}
```

---

## Docker Compose Changes

```yaml
# BEFORE (broken)
ontosage-mcp-server:
  ...
  profiles:
    - mcp          # ← required --profile mcp flag to start

# AFTER (fixed)
ontosage-mcp-server:
  ...
  environment:
    - MCP_TRANSPORT=streamable-http
    - MCP_HTTP_PORT=8003
    - ORCHESTRATOR_URL=http://orchestrator:8000
    - MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN:-}
  # profiles removed — starts with regular docker compose up
```

The `depends_on: orchestrator: condition: service_healthy` is retained so the MCP server only starts after the orchestrator is ready.

---

## File Map

| File | Action | Notes |
|------|--------|-------|
| `mcp-server/main.py` | Modify | Fix auth, fix document tool, add session dict, add streamable-http |
| `mcp-server/requirements.txt` | Modify | `mcp>=1.2.0` |
| `mcp-server/Dockerfile` | Modify | `EXPOSE 8003`, `ENV MCP_TRANSPORT=streamable-http` |
| `docker-compose.yml` | Modify | Remove `profiles`, add transport env vars |
| `mcp-server/claude_desktop_config.json` | Create | Claude Desktop paste-in |
| `mcp-server/cursor_mcp.json` | Create | Cursor paste-in |

---

## Error Handling

- Tool calls that fail HTTP → return `"Error: {message}"` string (existing pattern, retained)
- If orchestrator is not reachable → `httpx.ConnectError` caught, returns actionable message
- If `MCP_AUTH_TOKEN` is set but invalid → orchestrator returns 401, tool returns `"Auth error: check MCP_AUTH_TOKEN"`
- Session registry is never persisted — a restart clears all sessions (acceptable: Redis TTL handles graceful degradation on the orchestrator side)

---

## Out of Scope

- Direct SPARQL/SQL tools bypassing the orchestrator (Sub-project #3 territory)
- Multi-building MCP support (building_id parameter already exists on tools, no changes needed)
- MCP prompts / prompt templates
- MCP sampling
