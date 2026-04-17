# MCP Server Fix & Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 bugs in the existing MCP server, add session continuity, and activate both stdio (Claude Desktop) and streamable-http (Cursor) transports with ready-to-paste config files.

**Architecture:** Thin proxy — `mcp-server/main.py` translates MCP tool calls into HTTP POST requests to the orchestrator `/chat` endpoint. Session IDs tracked in a module-level dict (`_sessions`). Transport selected by `MCP_TRANSPORT` env var (`stdio` | `streamable-http`).

**Tech Stack:** `mcp>=1.2.0` (FastMCP), `httpx`, Python 3.11

---

### Task 1: Write failing tests + bump requirements

**Files:**
- Create: `tests/test_mcp_server.py`
- Modify: `mcp-server/requirements.txt`

- [ ] **Step 1: Create the test file**

Create `tests/test_mcp_server.py` with this exact content:

```python
"""Tests for MCP server bug fixes and activation."""
from pathlib import Path


def test_mcp_version_bumped() -> None:
    """requirements.txt must require mcp>=1.2.0 (adds streamable-http transport)."""
    content = Path("mcp-server/requirements.txt").read_text(encoding="utf-8")
    assert "mcp>=1.2.0" in content, "Bump mcp to >=1.2.0 in mcp-server/requirements.txt"


def test_no_auth_token_endpoint() -> None:
    """main.py must not call /auth/token — that endpoint does not exist in the orchestrator."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "/auth/token" not in content, "Remove /auth/token call from _login() in main.py"


def test_no_login_function() -> None:
    """main.py must not define _login() — auth is now header-only."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "async def _login" not in content, "Remove _login() from main.py"


def test_no_documents_generate_endpoint() -> None:
    """main.py must not call /api/v1/documents/generate — endpoint does not exist."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "/api/v1/documents/generate" not in content, (
        "Remove secondary /api/v1/documents/generate call from generate_document tool"
    )


def test_session_dict_present() -> None:
    """main.py must define a module-level _sessions dict for session continuity."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "_sessions" in content and "= {}" in content


def test_get_or_create_session_present() -> None:
    """main.py must define _get_or_create_session() for reusing session IDs."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "def _get_or_create_session" in content


def test_session_id_passed_to_chat() -> None:
    """_chat() must accept and forward a session_id to the orchestrator."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "session_id" in content
    assert '"session_id"' in content or "'session_id'" in content


def test_streamable_http_transport_present() -> None:
    """main.py entry point must support streamable-http transport."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert "streamable-http" in content


def test_no_sse_transport() -> None:
    """main.py must not use the deprecated SSE transport."""
    content = Path("mcp-server/main.py").read_text(encoding="utf-8")
    assert 'transport="sse"' not in content and "transport='sse'" not in content


def test_dockerfile_expose_8003() -> None:
    """Dockerfile must EXPOSE 8003 (matches docker-compose port mapping)."""
    content = Path("mcp-server/Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 8003" in content


def test_claude_desktop_config_exists() -> None:
    """claude_desktop_config.json must exist for Claude Desktop users."""
    assert Path("mcp-server/claude_desktop_config.json").exists()


def test_cursor_mcp_config_exists() -> None:
    """cursor_mcp.json must exist for Cursor / VS Code users."""
    assert Path("mcp-server/cursor_mcp.json").exists()


def test_docker_compose_mcp_no_profile() -> None:
    """MCP server in docker-compose must not be gated behind 'mcp' profile."""
    content = Path("docker-compose.yml").read_text(encoding="utf-8")
    lines = content.splitlines()
    in_mcp_service = False
    for i, line in enumerate(lines):
        if "container_name: ontosage-mcp-server" in line:
            in_mcp_service = True
        if in_mcp_service and "profiles:" in line:
            block = "\n".join(lines[i : i + 5])
            assert "- mcp" not in block, (
                "Remove 'profiles:\\n  - mcp' from MCP server in docker-compose.yml"
            )
            break


def test_docker_compose_mcp_has_transport_env() -> None:
    """MCP server docker-compose service must set MCP_TRANSPORT=streamable-http."""
    content = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "MCP_TRANSPORT=streamable-http" in content
```

- [ ] **Step 2: Run tests — confirm all fail**

```bash
pytest tests/test_mcp_server.py -v
```

Expected: All 14 tests FAIL (nothing has been changed yet).

- [ ] **Step 3: Bump mcp version in requirements.txt**

Replace `mcp-server/requirements.txt` with:

```
mcp>=1.2.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

- [ ] **Step 4: Verify version test passes**

```bash
pytest tests/test_mcp_server.py::test_mcp_version_bumped -v
```

Expected: PASS

---

### Task 2: Fix auth, headers, and session continuity in main.py

**Files:**
- Modify: `mcp-server/main.py`

This task rewrites the auth/session infrastructure (lines 51–107 in the original file).

- [ ] **Step 1: Replace env vars + helpers block**

Find this block in `mcp-server/main.py` (around lines 51–107):

```python
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" | "sse"
MCP_SSE_PORT = int(os.environ.get("MCP_SSE_PORT", "8080"))
MCP_SSE_HOST = os.environ.get("MCP_SSE_HOST", "0.0.0.0")
```

And further down, the entire `_session_token`, `_login()`, `_headers()`, and `_chat()` block.

Replace those sections so they read exactly:

```python
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" | "streamable-http"
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8003"))
```

Then, replacing the `_session_token = None` through the end of `_chat()`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Session registry — maps a client key → orchestrator session_id
# Key is "stdio" for Claude Desktop, or the caller-provided value for HTTP.
# ─────────────────────────────────────────────────────────────────────────────

import uuid
from typing import Any, Dict, List, Optional

_sessions: Dict[str, str] = {}


def _get_or_create_session(key: str = "default") -> str:
    """Return the existing session_id for key, or create and store a new UUID."""
    if key not in _sessions:
        _sessions[key] = str(uuid.uuid4())
    return _sessions[key]


def _headers() -> dict:
    """Build request headers. Sends X-API-Key if MCP_AUTH_TOKEN is configured."""
    h = {"Content-Type": "application/json"}
    if MCP_AUTH_TOKEN:
        h["X-API-Key"] = MCP_AUTH_TOKEN
    return h


async def _chat(
    message: str,
    persona: str = MCP_DEFAULT_PERSONA,
    building_id: Optional[str] = None,
    session_id: str = "",
) -> dict:
    """Send a chat message to the OntoSage orchestrator and return the response dict."""
    if not session_id:
        session_id = _get_or_create_session(
            "stdio" if MCP_TRANSPORT == "stdio" else "http"
        )
    payload: Dict[str, Any] = {
        "message": message,
        "persona": persona,
        "session_id": session_id,
    }
    if building_id:
        payload["building_id"] = building_id
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=120) as client:
        resp = await client.post("/chat", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 2: Run auth + session tests**

```bash
pytest tests/test_mcp_server.py::test_no_auth_token_endpoint \
       tests/test_mcp_server.py::test_no_login_function \
       tests/test_mcp_server.py::test_session_dict_present \
       tests/test_mcp_server.py::test_get_or_create_session_present \
       tests/test_mcp_server.py::test_session_id_passed_to_chat -v
```

Expected: All 5 PASS

---

### Task 3: Add session_id to all tools + fix generate_document

**Files:**
- Modify: `mcp-server/main.py`

Add `session_id: str = ""` as the last parameter to 8 tools, and remove the broken secondary HTTP call from `generate_document`. Replace each tool body exactly as shown below.

- [ ] **Step 1: Replace query_building**

```python
@mcp.tool()
async def query_building(
    question: str,
    persona: str = "general",
    building_id: str = "",
    session_id: str = "",
) -> str:
    """Ask any natural-language question about the smart building.

    Examples:
      - "How many sensors are in zone 5.01?"
      - "What is the average CO2 level?"
      - "Show me temperature trends for this week"

    Args:
        question: The question to ask about the building
        persona: Response style — general, facility_manager, executive, researcher,
                 student, occupant, energy_manager, safety_officer,
                 sustainability_officer, it_admin
        building_id: Optional building ID for multi-building deployments
        session_id: Optional session ID for conversation continuity
    """
    try:
        result = await _chat(
            question,
            persona=persona,
            building_id=building_id or None,
            session_id=session_id,
        )
        return result.get("response") or result.get("message") or json.dumps(result)
    except Exception as e:
        return f"Error querying building: {e}"
```

- [ ] **Step 2: Replace get_sensor_list**

```python
@mcp.tool()
async def get_sensor_list(filter: str = "", session_id: str = "") -> str:
    """Discover available sensors in the building.

    Args:
        filter: Optional filter keyword (e.g., "temperature", "CO2", "zone 5.01")
        session_id: Optional session ID for conversation continuity
    """
    query = f"List all {filter} sensors" if filter else "What sensors are available in the building?"
    try:
        result = await _chat(query, persona="it_admin", session_id=session_id)
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error listing sensors: {e}"
```

- [ ] **Step 3: Replace get_sensor_data**

```python
@mcp.tool()
async def get_sensor_data(
    sensor_name: str,
    time_range: str = "last 24 hours",
    session_id: str = "",
) -> str:
    """Fetch time-series data for a specific sensor.

    Args:
        sensor_name: Name or type of sensor (e.g., "Air_Temperature_Sensor_5.04",
                     "CO2 in zone 5.01")
        time_range: Time range (e.g., "last 24 hours", "this week",
                    "2024-01-01 to 2024-01-31")
        session_id: Optional session ID for conversation continuity
    """
    query = f"Show me {sensor_name} data for {time_range}"
    try:
        result = await _chat(query, persona="researcher", session_id=session_id)
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error fetching sensor data: {e}"
```

- [ ] **Step 4: Replace generate_report**

```python
@mcp.tool()
async def generate_report(
    report_type: str = "summary",
    format: str = "markdown",
    topic: str = "",
    session_id: str = "",
) -> str:
    """Generate a building report.

    Args:
        report_type: Type of report — summary, anomaly, compliance, trend, full
        format: Output format — markdown, html, pdf, csv
        topic: Optional topic focus (e.g., "air quality", "energy", "zone 5.01")
        session_id: Optional session ID for conversation continuity
    """
    query = f"Generate a {report_type} report"
    if topic:
        query += f" on {topic}"
    if format and format != "markdown":
        query += f" as {format}"
    try:
        result = await _chat(query, persona="facility_manager", session_id=session_id)
        response = result.get("response") or ""
        download_url = result.get("download_url") or ""
        if download_url:
            response += f"\n\nDownload: {download_url}"
        return response or json.dumps(result)
    except Exception as e:
        return f"Error generating report: {e}"
```

- [ ] **Step 5: Replace check_compliance**

```python
@mcp.tool()
async def check_compliance(
    standard: str = "ashrae55",
    zone: str = "",
    session_id: str = "",
) -> str:
    """Check building compliance against a standard.

    Args:
        standard: Standard to check — ashrae55, well, en15251, breeam, iso50001
        zone: Optional zone to check (e.g., "zone 5.01"). If empty, checks whole building.
        session_id: Optional session ID for conversation continuity
    """
    query = f"Check {standard} compliance"
    if zone:
        query += f" for {zone}"
    try:
        result = await _chat(query, persona="sustainability_officer", session_id=session_id)
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error checking compliance: {e}"
```

- [ ] **Step 6: Replace check_standards_batch**

```python
@mcp.tool()
async def check_standards_batch(
    zone: str = "",
    standards: str = "all",
    session_id: str = "",
) -> str:
    """Check compliance against ALL applicable standards at once.

    Args:
        zone: Optional zone to check. If empty, checks whole building.
        standards: Comma-separated IDs, or 'all' for BREEAM+WELL+ASHRAE+EN15251+ISO50001.
        session_id: Optional session ID for conversation continuity
    """
    standard_list = ["breeam", "well_v2", "ashrae55", "en15251", "iso50001"]
    if standards and standards != "all":
        standard_list = [s.strip() for s in standards.split(",")]
    results = {}
    for std in standard_list:
        try:
            result = await _chat(
                f"Check {std} compliance" + (f" for {zone}" if zone else ""),
                persona="sustainability_officer",
                session_id=session_id,
            )
            results[std] = result.get("response") or "No result"
        except Exception as e:
            results[std] = f"Error: {e}"
    return json.dumps(results, indent=2)
```

- [ ] **Step 7: Replace generate_document (removes broken secondary HTTP call)**

```python
@mcp.tool()
async def generate_document(
    document_type: str = "summary",
    output_format: str = "pdf",
    title: str = "",
    time_range: str = "last 7 days",
    persona: str = "facility_manager",
    session_id: str = "",
) -> str:
    """Generate a formal building document (PDF / Word / HTML).

    Args:
        document_type: summary, executive_kpi, anomaly_digest, compliance_report,
                       energy_report, iaq_report, research_export
        output_format: pdf, docx, or html
        title: Optional custom document title
        time_range: e.g. 'last 7 days', 'last month'
        persona: facility_manager, executive, researcher, etc.
        session_id: Optional session ID for conversation continuity
    """
    query = (
        f"Generate a {document_type} report as {output_format}"
        + (f" titled '{title}'" if title else "")
        + f" for {time_range}"
    )
    try:
        result = await _chat(query, persona=persona, session_id=session_id)
        response_text = result.get("response") or json.dumps(result)
        download_url = result.get("download_url") or ""
        if download_url:
            return f"{response_text}\n\nDownload: {download_url}"
        return response_text
    except Exception as e:
        return f"Error generating document: {e}"
```

- [ ] **Step 8: Replace multi_hop_query**

```python
@mcp.tool()
async def multi_hop_query(
    question: str,
    persona: str = "researcher",
    session_id: str = "",
) -> str:
    """Ask a complex cross-entity question requiring multi-step reasoning.

    Best for: 'Which floor has highest CO2?', 'Compare energy per zone', etc.

    Args:
        question: Complex natural-language question
        persona: researcher, energy_manager, facility_manager, etc.
        session_id: Optional session ID for conversation continuity
    """
    try:
        result = await _chat(question, persona=persona, session_id=session_id)
        return result.get("response") or result.get("formatted_response") or json.dumps(result)
    except Exception as e:
        return f"Error in multi-hop query: {e}"
```

Note: `get_building_info` does NOT get `session_id` — it calls `/health` directly, not `/chat`.

- [ ] **Step 9: Run the document fix test**

```bash
pytest tests/test_mcp_server.py::test_no_documents_generate_endpoint -v
```

Expected: PASS

---

### Task 4: Fix entry point — replace SSE with streamable-http

**Files:**
- Modify: `mcp-server/main.py` (entry point block, currently lines ~369–397)

- [ ] **Step 1: Replace the entire `if __name__ == "__main__":` block**

Find and replace the existing `if __name__ == "__main__":` block at the bottom of `mcp-server/main.py` with:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Entry point — stdio (Claude Desktop) or streamable-http (Cursor / Docker)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(
        f"OntoSage MCP Server starting "
        f"(orchestrator={ORCHESTRATOR_URL}, transport={MCP_TRANSPORT}, "
        f"port={MCP_HTTP_PORT})"
    )

    if MCP_TRANSPORT == "streamable-http":
        logger.info(f"streamable-http mode: listening on 0.0.0.0:{MCP_HTTP_PORT}")
        try:
            mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_HTTP_PORT)
        except TypeError:
            # Older FastMCP versions read port from env var instead of kwargs
            os.environ.setdefault("MCP_HTTP_PORT", str(MCP_HTTP_PORT))
            mcp.run(transport="streamable-http")
    else:
        # Default: stdio for Claude Desktop / local clients
        mcp.run(transport="stdio")
```

- [ ] **Step 2: Run the transport tests**

```bash
pytest tests/test_mcp_server.py::test_streamable_http_transport_present \
       tests/test_mcp_server.py::test_no_sse_transport -v
```

Expected: Both PASS

---

### Task 5: Fix Dockerfile + create client config files

**Files:**
- Modify: `mcp-server/Dockerfile`
- Create: `mcp-server/claude_desktop_config.json`
- Create: `mcp-server/cursor_mcp.json`

- [ ] **Step 1: Replace mcp-server/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MCP_TRANSPORT=streamable-http
ENV MCP_HTTP_PORT=8003

EXPOSE 8003
CMD ["python", "main.py"]
```

- [ ] **Step 2: Create mcp-server/claude_desktop_config.json**

```json
{
  "_instructions": [
    "Paste the 'mcpServers' object into your Claude Desktop config file.",
    "Mac/Linux: ~/.config/claude/claude_desktop_config.json",
    "Windows:   %APPDATA%\\Claude\\claude_desktop_config.json",
    "Update the path in 'args' to your actual OntoSage checkout location.",
    "The orchestrator must be running locally (docker compose up)."
  ],
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

- [ ] **Step 3: Create mcp-server/cursor_mcp.json**

```json
{
  "_instructions": [
    "Option 1: Paste the 'mcpServers' object into Cursor Settings > MCP.",
    "Option 2: Save this file as .cursor/mcp.json in your project root.",
    "The ontosage-mcp-server Docker container must be running (docker compose up).",
    "Cursor connects to the streamable-http endpoint at http://localhost:8003/mcp"
  ],
  "mcpServers": {
    "ontosage": {
      "url": "http://localhost:8003/mcp"
    }
  }
}
```

- [ ] **Step 4: Run Dockerfile and config tests**

```bash
pytest tests/test_mcp_server.py::test_dockerfile_expose_8003 \
       tests/test_mcp_server.py::test_claude_desktop_config_exists \
       tests/test_mcp_server.py::test_cursor_mcp_config_exists -v
```

Expected: All 3 PASS

---

### Task 6: Fix docker-compose.yml — remove mcp profile, add transport env

**Files:**
- Modify: `docker-compose.yml` (lines 838–856)

- [ ] **Step 1: Replace the mcp-server service environment + remove profiles**

Find this block (around line 838):

```yaml
  mcp-server:
    build:
      context: ./mcp-server
      dockerfile: Dockerfile
    container_name: ontosage-mcp-server
    ports:
      - "8003:8003"
    environment:
      - ORCHESTRATOR_URL=http://orchestrator:8000
      - MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN:-}
      - MCP_DEFAULT_PERSONA=${MCP_DEFAULT_PERSONA:-general}
    depends_on:
      orchestrator:
        condition: service_healthy
    networks:
      - ontobot-agentic
    profiles:
      - mcp
    restart: unless-stopped
```

Replace it with:

```yaml
  mcp-server:
    build:
      context: ./mcp-server
      dockerfile: Dockerfile
    container_name: ontosage-mcp-server
    ports:
      - "8003:8003"
    environment:
      - ORCHESTRATOR_URL=http://orchestrator:8000
      - MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN:-}
      - MCP_DEFAULT_PERSONA=${MCP_DEFAULT_PERSONA:-general}
      - MCP_TRANSPORT=streamable-http
      - MCP_HTTP_PORT=8003
    depends_on:
      orchestrator:
        condition: service_healthy
    networks:
      - ontobot-agentic
    restart: unless-stopped
```

(The `profiles: - mcp` block is removed entirely.)

- [ ] **Step 2: Run docker-compose tests**

```bash
pytest tests/test_mcp_server.py::test_docker_compose_mcp_no_profile \
       tests/test_mcp_server.py::test_docker_compose_mcp_has_transport_env -v
```

Expected: Both PASS

---

### Task 7: Full verification

- [ ] **Step 1: Run all MCP server tests**

```bash
pytest tests/test_mcp_server.py -v
```

Expected: All 14 tests PASS

- [ ] **Step 2: Syntax check main.py**

```bash
python -m py_compile mcp-server/main.py && echo "Syntax OK"
```

Expected: `Syntax OK`

- [ ] **Step 3: Confirm no regression in existing tests**

```bash
pytest tests/test_bootstrap.py tests/test_phase3_4_services.py -q
```

Expected: 52 passed, 1 skipped (unchanged from before)
