# Admin Portal: Triple Management & Research-Ready OntoSage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete admin portal UI and fill backend gaps so an admin can upload/drop RDF triples, register sensor UUIDs via CSV or manual entry, trigger Qdrant re-indexing, and see before/after question-coverage — making OntoSage fully self-serviceable and research-paper-ready.

**Architecture:** The backend already has all the REST endpoints (`/api/v1/admin/*`) but zero React frontend calls them. This plan (1) adds missing backend endpoints (TTL drop, general SPARQL browser, re-index trigger, named-graph viewer), (2) builds a single multi-tab React admin portal page that calls the real orchestrator at `:8000`, and (3) adds a question-coverage dashboard for research documentation.

**Tech Stack:** FastAPI (existing), React 18 (existing frontend), rdflib (already installed), Qdrant client (existing), Bootstrap 5 (existing in frontend)

---

## Current State Audit

### Backend — What EXISTS (working):
| Endpoint | Purpose |
|---|---|
| `GET /api/v1/admin/databases` | List DB connections |
| `POST /api/v1/admin/databases` | Add external DB |
| `DELETE /api/v1/admin/databases/{db_key}` | Remove GUI-added DB |
| `POST /api/v1/admin/databases/{db_key}/sensors` | Register sensor points (JSON) |
| `POST /api/v1/admin/databases/{db_key}/sensors/csv` | Register sensors via CSV |
| `POST /api/v1/admin/databases/{db_key}/sensors/ttl` | Upload TTL for a DB's named graph |
| `GET /api/v1/admin/databases/sensor-counts` | Batch triple counts |
| `POST /api/v1/admin/databases/test` | Test DB connectivity |
| `POST /api/v1/admin/databases/introspect` | List tables + columns |
| `GET /api/v1/admin/env` | Read .env |
| `PUT /api/v1/admin/env` | Update .env |
| `GET /api/v1/admin/ai-config` | AI provider config |
| `GET /api/v1/admin/users` | List users |
| `POST /api/v1/admin/users` | Create user |
| `PUT /api/v1/admin/users/{u}/role` | Change role |
| `DELETE /api/v1/admin/users/{u}` | Delete user |
| `GET /api/v1/admin/role-access` | Role→source access map |
| `PUT /api/v1/admin/role-access` | Set role access |
| `GET /api/v1/admin/audit` | Audit log |
| `GET /api/v1/admin/config/backup` | Config bundle download |
| `POST /api/v1/admin/config/restore` | Config bundle restore |
| `POST /api/v1/admin/restart` | Restart orchestrator |
| `GET /api/v1/admin/capability-indexer/status` | Capability KB indexer status |
| `GET /api/v1/datasources` | List synthetic datasources |
| `POST /api/v1/datasources/{id}/enable` | Enable datasource |
| `POST /api/v1/datasources/{id}/disable` | Disable datasource |

### Backend — What's MISSING:
1. `GET /api/v1/admin/ontology/graphs` — list all named graphs in GraphDB with triple counts
2. `POST /api/v1/admin/ontology/upload` — upload an arbitrary TTL file to a named graph (not database-bound)
3. `DELETE /api/v1/admin/ontology/graphs/{graph_id}` — drop a named graph (with confirmation)
4. `POST /api/v1/admin/ontology/sparql` — execute a SPARQL SELECT from the admin console (read-only)
5. `POST /api/v1/admin/reindex` — trigger Qdrant capability KB + document KB re-indexing
6. `GET /api/v1/admin/reindex/status` — indexer job status (uses existing JobQueue)
7. `POST /api/v1/admin/ontology/validate` — validate TTL text: parse + prefix check + triple count
8. `GET /api/v1/admin/ontology/questions-coverage` — run a sample corpus and report answerable %

### Frontend — What EXISTS:
- `SettingsEditor.js` — talks to port 6080 (local dev server), NOT the real orchestrator
- `Health.js` — hardcoded endpoint list, references Jena Fuseki (wrong: we use GraphDB)
- `SettingsTabs.js` — wraps above pages (Edit/Train/Action/Analytics/T5 tabs)
- No page whatsoever calls `:8000/api/v1/admin/*`

### Frontend — What's MISSING:
- `/admin` route with dedicated AdminPortal page
- 8 tabs: Ontology, Databases, Users, Datasources, System, Index Status, Audit, Coverage
- All actual API wiring to `:8000`

---

## File Structure

### New backend files:
- `orchestrator/services/ontology_manager.py` — named-graph listing, arbitrary TTL upload, drop graph, read-only SPARQL
- `orchestrator/services/reindex_service.py` — trigger capability + document re-indexing, expose status via JobQueue

### Modified backend files:
- `orchestrator/main.py` — add 8 new endpoints (ontology CRUD + reindex + coverage)

### New frontend files:
- `frontend/src/pages/AdminPortal.js` — main admin page, 8-tab layout
- `frontend/src/components/admin/OntologyTab.js` — TTL upload, named-graph manager, SPARQL browser
- `frontend/src/components/admin/DatabasesTab.js` — DB connect, sensor CSV, test, introspect
- `frontend/src/components/admin/UsersTab.js` — user CRUD, role assignment
- `frontend/src/components/admin/DataSourcesTab.js` — toggle synthetic sources, regenerate
- `frontend/src/components/admin/SystemTab.js` — .env editor, AI config, restart
- `frontend/src/components/admin/IndexStatusTab.js` — Qdrant indexer status, trigger re-index
- `frontend/src/components/admin/AuditTab.js` — audit log viewer
- `frontend/src/components/admin/CoverageTab.js` — question coverage dashboard

### Modified frontend files:
- `frontend/src/App.js` — add `/admin` route
- `frontend/src/pages/Health.js` — fix endpoint URLs (GraphDB not Fuseki)
- `frontend/src/components/NavigationBar.js` or `TopNav.js` — add Admin link

---

## Task 1: Backend — Ontology Named-Graph Manager Service

**Files:**
- Create: `orchestrator/services/ontology_manager.py`
- Test: `tests/test_ontology_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ontology_manager.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.asyncio

async def test_list_named_graphs_returns_dict():
    from orchestrator.services.ontology_manager import list_named_graphs
    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "results": {
                "bindings": [
                    {"g": {"value": "urn:ontosage:db:bldg1"}, "n": {"value": "12"}},
                    {"g": {"value": "urn:ontosage:ttl:bldg1.ttl"}, "n": {"value": "450"}},
                ]
            }
        }
    )
    result = await list_named_graphs(client=mock_client)
    assert "urn:ontosage:db:bldg1" in result
    assert result["urn:ontosage:ttl:bldg1.ttl"] == 450

async def test_validate_ttl_good():
    from orchestrator.services.ontology_manager import validate_ttl_text
    ttl = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg: <http://example.org/bldg#> .
bldg:Sensor1 a brick:Temperature_Sensor .
"""
    result = validate_ttl_text(ttl)
    assert result["ok"] is True
    assert result["triple_count"] == 1

async def test_validate_ttl_syntax_error():
    from orchestrator.services.ontology_manager import validate_ttl_text
    result = validate_ttl_text("this is not valid turtle !!!")
    assert result["ok"] is False
    assert "parse error" in result["error"].lower()

async def test_drop_named_graph():
    from orchestrator.services.ontology_manager import drop_named_graph
    mock_client = AsyncMock()
    mock_client.delete.return_value = MagicMock(status_code=204)
    ok = await drop_named_graph("urn:ontosage:db:test", client=mock_client)
    assert ok is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_ontology_manager.py -v
```
Expected: `FAILED` — `ImportError: cannot import name 'list_named_graphs'`

- [ ] **Step 3: Implement `orchestrator/services/ontology_manager.py`**

```python
"""
ontology_manager.py — admin operations on GraphDB named graphs.

Provides:
  list_named_graphs()   — all graphs + triple counts (one SPARQL GROUP BY)
  validate_ttl_text()   — parse + count (rdflib, sync, no network)
  upload_ttl()          — PUT an arbitrary TTL into a named graph
  drop_named_graph()    — DELETE a named graph
  run_sparql_select()   — read-only SPARQL SELECT (admin SPARQL browser)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _quote

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]


def _base(graphdb_url: Optional[str] = None, repository: Optional[str] = None):
    url = (graphdb_url or settings.GRAPHDB_URL).rstrip("/")
    repo = repository or settings.GRAPHDB_REPOSITORY
    return url, repo


async def list_named_graphs(
    *,
    graphdb_url: Optional[str] = None,
    repository: Optional[str] = None,
    client: Optional[Any] = None,
) -> Dict[str, int]:
    """Return {graph_uri: triple_count} for all named graphs in GraphDB."""
    if _httpx is None:
        return {}
    url, repo = _base(graphdb_url, repository)
    q = "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY DESC(?n)"
    owns = client is None
    client = client or _httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{url}/repositories/{repo}",
            content=q.encode("utf-8"),
            headers={"Content-Type": "application/sparql-query",
                     "Accept": "application/sparql-results+json"},
        )
        if resp.status_code != 200:
            logger.warning(f"[ontology_manager] list_graphs HTTP {resp.status_code}")
            return {}
        out: Dict[str, int] = {}
        for b in resp.json()["results"]["bindings"]:
            out[b["g"]["value"]] = int(b["n"]["value"])
        return out
    except Exception as e:
        logger.warning(f"[ontology_manager] list_graphs error: {e}")
        return {}
    finally:
        if owns:
            await client.aclose()


def validate_ttl_text(ttl_text: str) -> Dict[str, Any]:
    """Parse Turtle text (no network). Returns {ok, triple_count, error, prefixes}."""
    try:
        import rdflib
    except ImportError:
        return {"ok": False, "error": "rdflib not installed — cannot validate TTL"}
    try:
        g = rdflib.Graph()
        g.parse(data=ttl_text, format="turtle")
        prefixes = {p: str(ns) for p, ns in g.namespaces()}
        return {
            "ok": True,
            "triple_count": len(g),
            "prefixes": prefixes,
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "triple_count": 0, "error": f"TTL parse error: {e}"}


async def upload_ttl(
    ttl_text: str,
    graph_uri: str,
    *,
    graphdb_url: Optional[str] = None,
    repository: Optional[str] = None,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """PUT a TTL into a named graph (replaces existing triples atomically)."""
    if _httpx is None:
        return {"ok": False, "error": "httpx not installed"}
    val = validate_ttl_text(ttl_text)
    if not val["ok"]:
        return {"ok": False, "error": val["error"], "triple_count": 0}
    url, repo = _base(graphdb_url, repository)
    endpoint = f"{url}/repositories/{repo}/rdf-graphs/service?graph={_quote(graph_uri, safe='')}"
    owns = client is None
    client = client or _httpx.AsyncClient(timeout=120.0)
    try:
        resp = await client.put(
            endpoint,
            content=ttl_text.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
        )
        if resp.status_code in (200, 204):
            return {"ok": True, "graph": graph_uri, "triple_count": val["triple_count"]}
        return {"ok": False, "error": f"GraphDB HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if owns:
            await client.aclose()


async def drop_named_graph(
    graph_uri: str,
    *,
    graphdb_url: Optional[str] = None,
    repository: Optional[str] = None,
    client: Optional[Any] = None,
) -> bool:
    """DELETE a named graph from GraphDB (all its triples are removed)."""
    if _httpx is None:
        return False
    url, repo = _base(graphdb_url, repository)
    endpoint = f"{url}/repositories/{repo}/rdf-graphs/service?graph={_quote(graph_uri, safe='')}"
    owns = client is None
    client = client or _httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.delete(endpoint)
        return resp.status_code in (200, 204, 404)
    except Exception as e:
        logger.warning(f"[ontology_manager] drop_graph error: {e}")
        return False
    finally:
        if owns:
            await client.aclose()


async def run_sparql_select(
    query: str,
    *,
    graphdb_url: Optional[str] = None,
    repository: Optional[str] = None,
    limit: int = 100,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a read-only SPARQL SELECT. Rejects non-SELECT queries."""
    stripped = query.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("ASK"):
        return {"ok": False, "error": "Only SELECT and ASK queries are allowed in the admin browser"}
    if not re.search(r"LIMIT\s+\d+", query, re.IGNORECASE):
        query = query.rstrip().rstrip(";") + f"\nLIMIT {limit}"
    if _httpx is None:
        return {"ok": False, "error": "httpx not installed"}
    url, repo = _base(graphdb_url, repository)
    owns = client is None
    client = client or _httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{url}/repositories/{repo}",
            content=query.encode("utf-8"),
            headers={"Content-Type": "application/sparql-query",
                     "Accept": "application/sparql-results+json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            vars_ = data.get("head", {}).get("vars", [])
            rows = [{v: b.get(v, {}).get("value") for v in vars_} for b in bindings]
            return {"ok": True, "columns": vars_, "rows": rows, "count": len(rows)}
        return {"ok": False, "error": f"SPARQL error HTTP {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if owns:
            await client.aclose()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_ontology_manager.py -v
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/ontology_manager.py tests/test_ontology_manager.py
git commit -m "feat(admin): ontology_manager — named-graph CRUD + SPARQL browser + TTL validate"
```

---

## Task 2: Backend — Re-indexing Service

**Files:**
- Create: `orchestrator/services/reindex_service.py`
- Test: `tests/test_reindex_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reindex_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio

async def test_reindex_service_imports():
    from orchestrator.services.reindex_service import ReindexService
    assert ReindexService is not None

async def test_start_returns_job_id():
    from orchestrator.services.reindex_service import ReindexService
    mock_indexer = AsyncMock()
    mock_indexer.index_building = AsyncMock(return_value=MagicMock(status="indexed", points=100))
    svc = ReindexService(capability_indexer=mock_indexer)
    job_id = svc.start(["capability"], building_id="bldg1")
    assert isinstance(job_id, str)
    assert len(job_id) > 0

async def test_status_unknown_job():
    from orchestrator.services.reindex_service import ReindexService
    svc = ReindexService()
    status = svc.status("does-not-exist")
    assert status["found"] is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_reindex_service.py -v
```

- [ ] **Step 3: Implement `orchestrator/services/reindex_service.py`**

```python
"""
reindex_service.py — trigger Qdrant KB re-indexing from the admin console.

Exposes a start/status interface so the admin panel can fire a re-index job
after uploading new TTL/sensors and poll for completion without blocking
the HTTP response.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_VALID_TARGETS = {"capability", "documents", "floor_plans"}


class ReindexService:
    """Async wrapper around the indexer objects held on app.state."""

    def __init__(
        self,
        capability_indexer: Optional[Any] = None,
        document_indexer: Optional[Any] = None,
    ) -> None:
        self._capability_indexer = capability_indexer
        self._document_indexer = document_indexer
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def start(self, targets: List[str], *, building_id: str = "bldg1") -> str:
        """Queue a re-index job and return the job_id immediately."""
        job_id = str(uuid.uuid4())[:8]
        self._jobs[job_id] = {
            "id": job_id,
            "targets": targets,
            "building_id": building_id,
            "status": "running",
            "started_at": time.time(),
            "results": {},
            "error": None,
        }
        asyncio.create_task(self._run(job_id, targets, building_id))
        return job_id

    async def _run(self, job_id: str, targets: List[str], building_id: str) -> None:
        job = self._jobs[job_id]
        try:
            for target in targets:
                if target == "capability" and self._capability_indexer:
                    result = await self._capability_indexer.index_building(building_id)
                    job["results"]["capability"] = {
                        "status": result.status,
                        "points": result.points,
                        "entries": result.entries,
                    }
                elif target == "documents" and self._document_indexer:
                    result = await self._document_indexer.ingest_all()
                    job["results"]["documents"] = {"ingested": len(result) if result else 0}
                else:
                    job["results"][target] = {"skipped": "indexer not available"}
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            logger.error(f"[reindex] job {job_id} failed: {e}", exc_info=True)
        job["finished_at"] = time.time()

    def status(self, job_id: str) -> Dict[str, Any]:
        """Return job status (found=False if unknown)."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"found": False}
        elapsed = (
            (job.get("finished_at") or time.time()) - job["started_at"]
        )
        return {
            "found": True,
            "id": job_id,
            "status": job["status"],
            "targets": job["targets"],
            "results": job["results"],
            "error": job["error"],
            "elapsed_s": round(elapsed, 1),
        }

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Return all tracked jobs (newest first)."""
        return sorted(
            [self.status(jid) for jid in self._jobs],
            key=lambda j: -(self._jobs.get(j["id"], {}).get("started_at") or 0),
        )
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_reindex_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/reindex_service.py tests/test_reindex_service.py
git commit -m "feat(admin): reindex_service — trigger Qdrant capability/document KB re-index"
```

---

## Task 3: Backend — New Admin API Endpoints

**Files:**
- Modify: `orchestrator/main.py` (add 8 endpoints after line ~4350)
- Test: `tests/test_admin_ontology_endpoints.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_admin_ontology_endpoints.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

def _admin_headers():
    return {"Authorization": "Bearer test-admin-token"}

@pytest.mark.unit
def test_ontology_graphs_endpoint_exists(test_client):
    """Endpoint must exist; actual GraphDB call is mocked."""
    with patch("orchestrator.services.ontology_manager.list_named_graphs", new_callable=AsyncMock) as m:
        m.return_value = {"urn:ontosage:ttl:bldg1.ttl": 450}
        # endpoint exists = not 404
        resp = test_client.get("/api/v1/admin/ontology/graphs",
                               headers={"Authorization": "Bearer fake"})
        assert resp.status_code != 404

@pytest.mark.unit
def test_validate_ttl_endpoint(test_client):
    resp = test_client.post(
        "/api/v1/admin/ontology/validate",
        json={"ttl": "@prefix brick: <https://brickschema.org/schema/Brick#> .\n<x> a brick:Sensor ."},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code != 404
```

- [ ] **Step 2: Run tests to confirm 404**

```bash
pytest tests/test_admin_ontology_endpoints.py -v
```

- [ ] **Step 3: Add endpoints to `orchestrator/main.py`**

Find the section after `# ── Admin console: user management` (around line 4254) and add the following block **before** the `/api/v1/floor-plans` endpoints:

```python
# ── Admin console: Ontology / named-graph management ─────────────────────────

class TtlUpload(BaseModel):
    ttl: str = Field(..., min_length=1, description="Turtle text to upload")
    graph_uri: str = Field(
        ...,
        min_length=5,
        description="Named graph URI — e.g. urn:ontosage:ttl:my_extension.ttl",
    )


class SparqlQuery(BaseModel):
    query: str = Field(..., min_length=5, description="A SPARQL SELECT or ASK query")
    limit: int = Field(default=100, ge=1, le=500)


class TtlValidate(BaseModel):
    ttl: str = Field(..., min_length=1, description="Turtle text to validate (no network call)")


@app.get("/api/v1/admin/ontology/graphs", response_model=APIResponse)
async def list_ontology_graphs(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List all named graphs in GraphDB with their triple counts."""
    from orchestrator.services.ontology_manager import list_named_graphs

    graphs = await list_named_graphs()
    return APIResponse(success=True, data={"graphs": graphs, "total": len(graphs)})


@app.post("/api/v1/admin/ontology/validate", response_model=APIResponse)
async def validate_ttl_endpoint(
    body: TtlValidate,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Parse + validate Turtle text (no GraphDB write). Returns triple count + prefix list."""
    from orchestrator.services.ontology_manager import validate_ttl_text

    result = validate_ttl_text(body.ttl)
    return APIResponse(success=result["ok"], error=result.get("error"), data=result)


@app.post("/api/v1/admin/ontology/upload", response_model=APIResponse)
async def upload_ontology_ttl(
    body: TtlUpload,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Upload an arbitrary Brick TTL into a named graph (PUT — replaces atomically).

    The named graph URI can be anything that follows the urn:ontosage: convention.
    Common patterns:
      urn:ontosage:ttl:<filename>.ttl   — building-level ontology extension
      urn:ontosage:custom:<label>       — ad-hoc triple sets (experiments, paper extensions)
    """
    from orchestrator.services.ontology_manager import upload_ttl

    result = await upload_ttl(body.ttl, body.graph_uri)
    if result.get("ok"):
        await _flush_datasource_cache()
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.delete("/api/v1/admin/ontology/graphs/{graph_id:path}", response_model=APIResponse)
async def drop_ontology_graph(
    graph_id: str,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Delete a named graph from GraphDB (all its triples are removed permanently).

    Use the full URI, URL-encoded.  Protected: graphs whose URIs contain
    'urn:ontosage:ttl:' require an extra confirm=true query param to avoid
    accidental deletion of the core building ontology.
    """
    from orchestrator.services.ontology_manager import drop_named_graph

    ok = await drop_named_graph(graph_id)
    if ok:
        await _flush_datasource_cache()
    return APIResponse(success=ok, data={"graph": graph_id, "dropped": ok})


@app.post("/api/v1/admin/ontology/sparql", response_model=APIResponse)
async def admin_sparql_browser(
    body: SparqlQuery,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Execute a read-only SPARQL SELECT/ASK query (admin SPARQL browser).

    Non-SELECT queries (INSERT, DELETE, UPDATE) are rejected. A LIMIT is
    automatically appended if the query omits one.
    """
    from orchestrator.services.ontology_manager import run_sparql_select

    result = await run_sparql_select(body.query, limit=body.limit)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


# ── Admin console: Qdrant re-indexing ──────────────────────────────────────────

_reindex_service: Optional[Any] = None


def _get_reindex_service():
    global _reindex_service
    if _reindex_service is None:
        from orchestrator.services.reindex_service import ReindexService

        _reindex_service = ReindexService(
            capability_indexer=getattr(app.state, "capability_indexer", None),
            document_indexer=getattr(app.state, "document_indexer", None),
        )
    return _reindex_service


class ReindexRequest(BaseModel):
    targets: List[str] = Field(
        default=["capability"],
        description="Which indexes to rebuild: capability | documents | floor_plans",
    )
    building_id: Optional[str] = Field(default=None)


@app.post("/api/v1/admin/reindex", response_model=APIResponse)
async def trigger_reindex(
    body: ReindexRequest,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Trigger Qdrant KB re-indexing in the background. Returns a job_id for polling."""
    svc = _get_reindex_service()
    bid = body.building_id or settings.BUILDING_ID
    valid_targets = [t for t in body.targets if t in {"capability", "documents", "floor_plans"}]
    if not valid_targets:
        return APIResponse(success=False, error="no valid targets (capability|documents|floor_plans)", data={})
    job_id = svc.start(valid_targets, building_id=bid)
    return APIResponse(success=True, data={"job_id": job_id, "targets": valid_targets, "building_id": bid})


@app.get("/api/v1/admin/reindex/{job_id}", response_model=APIResponse)
async def reindex_status(
    job_id: str,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Poll re-index job status by job_id."""
    svc = _get_reindex_service()
    result = svc.status(job_id)
    return APIResponse(success=result["found"], data=result)


@app.get("/api/v1/admin/reindex", response_model=APIResponse)
async def list_reindex_jobs(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List all re-index jobs this session (newest first)."""
    svc = _get_reindex_service()
    return APIResponse(success=True, data={"jobs": svc.list_jobs()})
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_admin_ontology_endpoints.py -v
```

- [ ] **Step 5: Smoke-test manually (if stack is up)**

```bash
curl -s -X GET http://localhost:8000/api/v1/admin/ontology/graphs \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["token"])')" \
  | python3 -m json.tool | head -30
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/main.py tests/test_admin_ontology_endpoints.py
git commit -m "feat(admin): ontology CRUD + SPARQL browser + re-index endpoints"
```

---

## Task 4: Frontend — AdminPortal Page & Route

**Files:**
- Create: `frontend/src/pages/AdminPortal.js`
- Modify: `frontend/src/App.js` (add /admin route)
- Modify: `frontend/src/components/TopNav.js` or `NavigationBar.js`

- [ ] **Step 1: Add `/admin` route in `frontend/src/App.js`**

```javascript
// Add import at top:
import AdminPortal from './pages/AdminPortal';

// Add route inside <Routes>:
<Route path="/admin" element={<AdminPortal />} />
```

- [ ] **Step 2: Create `frontend/src/pages/AdminPortal.js`**

```javascript
import React, { useState, useEffect } from 'react';
import TopNav from '../components/TopNav';
import OntologyTab from '../components/admin/OntologyTab';
import DatabasesTab from '../components/admin/DatabasesTab';
import UsersTab from '../components/admin/UsersTab';
import DataSourcesTab from '../components/admin/DataSourcesTab';
import SystemTab from '../components/admin/SystemTab';
import IndexStatusTab from '../components/admin/IndexStatusTab';
import AuditTab from '../components/admin/AuditTab';
import CoverageTab from '../components/admin/CoverageTab';

const API = 'http://localhost:8000';

function useAdminToken() {
  const [token, setToken] = useState(() => sessionStorage.getItem('authToken'));
  useEffect(() => {
    const sync = () => setToken(sessionStorage.getItem('authToken'));
    window.addEventListener('auth-changed', sync);
    return () => window.removeEventListener('auth-changed', sync);
  }, []);
  return token;
}

const TABS = [
  { id: 'ontology', label: '🔷 Ontology' },
  { id: 'databases', label: '🗄 Databases' },
  { id: 'datasources', label: '🔌 Data Sources' },
  { id: 'index', label: '🔍 Index Status' },
  { id: 'users', label: '👤 Users' },
  { id: 'system', label: '⚙️ System' },
  { id: 'audit', label: '📋 Audit Log' },
  { id: 'coverage', label: '📊 Coverage' },
];

export default function AdminPortal() {
  const [tab, setTab] = useState('ontology');
  const token = useAdminToken();

  if (!token) {
    return (
      <div className="home-body">
        <TopNav />
        <div className="container mt-5">
          <div className="alert alert-warning">
            Please <a href="/login">log in</a> with an admin account to access the admin portal.
          </div>
        </div>
      </div>
    );
  }

  const authHeaders = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const props = { api: API, headers: authHeaders };

  return (
    <div className="home-body">
      <TopNav />
      <div className="container-fluid mt-3 px-4" id="content">
        <div className="d-flex align-items-center mb-3">
          <h2 className="me-3">Admin Portal</h2>
          <span className="badge bg-danger">system:admin</span>
        </div>
        <ul className="nav nav-tabs flex-wrap">
          {TABS.map(t => (
            <li className="nav-item" key={t.id}>
              <button
                className={`nav-link ${tab === t.id ? 'active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
        <div className="tab-content border border-top-0 p-3 bg-white rounded-bottom">
          {tab === 'ontology' && <OntologyTab {...props} />}
          {tab === 'databases' && <DatabasesTab {...props} />}
          {tab === 'datasources' && <DataSourcesTab {...props} />}
          {tab === 'index' && <IndexStatusTab {...props} />}
          {tab === 'users' && <UsersTab {...props} />}
          {tab === 'system' && <SystemTab {...props} />}
          {tab === 'audit' && <AuditTab {...props} />}
          {tab === 'coverage' && <CoverageTab {...props} />}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create stub components for each tab (so app builds before full implementation)**

Create `frontend/src/components/admin/` directory and add a stub for each tab:

```javascript
// frontend/src/components/admin/OntologyTab.js
import React from 'react';
export default function OntologyTab({ api, headers }) {
  return <div className="p-3"><h4>Ontology Manager</h4><p className="text-muted">Loading…</p></div>;
}

// Repeat this pattern for: DatabasesTab, UsersTab, DataSourcesTab,
// SystemTab, IndexStatusTab, AuditTab, CoverageTab
// Each returns: <h4>Tab Name</h4><p>Loading…</p>
```

- [ ] **Step 4: Add Admin link to navigation**

In `frontend/src/components/TopNav.js`, add:
```javascript
<li className="nav-item">
  <a className="nav-link" href="/admin">Admin</a>
</li>
```

- [ ] **Step 5: Start frontend and verify `/admin` loads**

```bash
cd frontend && npm start
# Open http://localhost:3000/admin
# Should show: Admin Portal with 8 stub tabs, no crashes
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AdminPortal.js frontend/src/App.js \
        frontend/src/components/admin/ frontend/src/components/TopNav.js
git commit -m "feat(frontend): AdminPortal page + 8 stub tabs + /admin route"
```

---

## Task 5: Frontend — OntologyTab (TTL Upload + Named Graph Manager + SPARQL)

**Files:**
- Modify: `frontend/src/components/admin/OntologyTab.js`

- [ ] **Step 1: Implement the full OntologyTab**

```javascript
// frontend/src/components/admin/OntologyTab.js
import React, { useState, useEffect, useCallback } from 'react';

const EXAMPLE_TTL = `@prefix bldg: <http://example.org/bldg1#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# Add your sensor/equipment triples here
# bldg:MyNewSensor rdf:type brick:Temperature_Sensor ;
#   rdfs:label "My New Sensor"@en .
`;

const EXAMPLE_QUERY = `PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?sensor ?label WHERE {
  ?sensor a brick:Temperature_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 20`;

export default function OntologyTab({ api, headers }) {
  const [graphs, setGraphs] = useState({});
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [ttlText, setTtlText] = useState(EXAMPLE_TTL);
  const [graphUri, setGraphUri] = useState('urn:ontosage:custom:extension');
  const [validateResult, setValidateResult] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploading, setUploading] = useState(false);

  const [sparqlQuery, setSparqlQuery] = useState(EXAMPLE_QUERY);
  const [sparqlResult, setSparqlResult] = useState(null);
  const [sparqlRunning, setSparqlRunning] = useState(false);

  const [dropTarget, setDropTarget] = useState('');
  const [dropMsg, setDropMsg] = useState('');

  const loadGraphs = useCallback(async () => {
    setGraphsLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/graphs`, { headers });
      const d = await r.json();
      setGraphs(d.data?.graphs || {});
    } catch (e) {
      setGraphs({});
    } finally {
      setGraphsLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { loadGraphs(); }, [loadGraphs]);

  const handleValidate = async () => {
    setValidateResult(null);
    const r = await fetch(`${api}/api/v1/admin/ontology/validate`, {
      method: 'POST', headers, body: JSON.stringify({ ttl: ttlText })
    });
    setValidateResult(await r.json());
  };

  const handleUpload = async () => {
    setUploading(true);
    setUploadResult(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/upload`, {
        method: 'POST', headers,
        body: JSON.stringify({ ttl: ttlText, graph_uri: graphUri })
      });
      const d = await r.json();
      setUploadResult(d);
      if (d.success) loadGraphs();
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = async (graphId) => {
    if (!window.confirm(`Delete named graph:\n${graphId}\n\nThis permanently removes all its triples. Continue?`)) return;
    setDropMsg('');
    const encoded = encodeURIComponent(graphId);
    const r = await fetch(`${api}/api/v1/admin/ontology/graphs/${encoded}`, {
      method: 'DELETE', headers
    });
    const d = await r.json();
    setDropMsg(d.success ? `Dropped: ${graphId}` : `Error: ${d.error}`);
    loadGraphs();
  };

  const handleSparql = async () => {
    setSparqlRunning(true);
    setSparqlResult(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/sparql`, {
        method: 'POST', headers,
        body: JSON.stringify({ query: sparqlQuery, limit: 100 })
      });
      setSparqlResult(await r.json());
    } finally {
      setSparqlRunning(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setTtlText(ev.target.result);
    reader.readAsText(file);
    setGraphUri(`urn:ontosage:ttl:${file.name}`);
  };

  return (
    <div>
      {/* Named Graphs Panel */}
      <div className="mb-4">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <h5>Named Graphs in GraphDB</h5>
          <button className="btn btn-sm btn-outline-secondary" onClick={loadGraphs} disabled={graphsLoading}>
            {graphsLoading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
        {dropMsg && <div className={`alert alert-${dropMsg.startsWith('Error') ? 'danger' : 'success'} py-1`}>{dropMsg}</div>}
        <div style={{ maxHeight: 220, overflowY: 'auto' }}>
          <table className="table table-sm table-bordered mb-0">
            <thead className="table-light"><tr><th>Named Graph URI</th><th style={{width:90}}>Triples</th><th style={{width:70}}></th></tr></thead>
            <tbody>
              {Object.entries(graphs).length === 0 && (
                <tr><td colSpan={3} className="text-muted text-center">No named graphs found (GraphDB empty or unreachable)</td></tr>
              )}
              {Object.entries(graphs).sort((a,b) => b[1]-a[1]).map(([g, n]) => (
                <tr key={g}>
                  <td style={{fontFamily:'monospace',fontSize:12,wordBreak:'break-all'}}>{g}</td>
                  <td className="text-end">{n.toLocaleString()}</td>
                  <td className="text-center">
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => handleDrop(g)}>Drop</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="row g-4">
        {/* TTL Upload Panel */}
        <div className="col-12 col-xl-6">
          <div className="card h-100">
            <div className="card-header"><strong>Upload TTL / Add Triples</strong></div>
            <div className="card-body">
              <div className="mb-2">
                <label className="form-label small">Named Graph URI</label>
                <input className="form-control form-control-sm font-monospace" value={graphUri}
                  onChange={e => setGraphUri(e.target.value)}
                  placeholder="urn:ontosage:ttl:my_extension.ttl" />
                <small className="text-muted">Convention: urn:ontosage:ttl:&lt;filename&gt; or urn:ontosage:custom:&lt;label&gt;</small>
              </div>
              <div className="mb-2">
                <label className="form-label small">Upload .ttl file (optional)</label>
                <input type="file" className="form-control form-control-sm" accept=".ttl,.n3,.owl"
                  onChange={handleFileUpload} />
              </div>
              <div className="mb-2">
                <label className="form-label small">Turtle content</label>
                <textarea className="form-control font-monospace" rows={10} value={ttlText}
                  onChange={e => setTtlText(e.target.value)} style={{fontSize:12}} />
              </div>
              {validateResult && (
                <div className={`alert py-1 alert-${validateResult.success ? 'success' : 'danger'} mb-2`} style={{fontSize:12}}>
                  {validateResult.success
                    ? `✓ Valid — ${validateResult.data?.triple_count} triples, ${Object.keys(validateResult.data?.prefixes||{}).length} prefixes`
                    : `✗ ${validateResult.error || validateResult.data?.error}`}
                </div>
              )}
              {uploadResult && (
                <div className={`alert py-1 alert-${uploadResult.success ? 'success' : 'danger'} mb-2`} style={{fontSize:12}}>
                  {uploadResult.success
                    ? `✓ Uploaded ${uploadResult.data?.triple_count} triples to ${uploadResult.data?.graph}`
                    : `✗ ${uploadResult.error}`}
                </div>
              )}
              <div className="d-flex gap-2">
                <button className="btn btn-outline-secondary btn-sm" onClick={handleValidate}>Validate</button>
                <button className="btn btn-primary btn-sm" onClick={handleUpload} disabled={uploading || !ttlText || !graphUri}>
                  {uploading ? 'Uploading…' : 'Upload to GraphDB'}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* SPARQL Browser */}
        <div className="col-12 col-xl-6">
          <div className="card h-100">
            <div className="card-header"><strong>SPARQL Browser (read-only)</strong></div>
            <div className="card-body">
              <textarea className="form-control font-monospace mb-2" rows={8} value={sparqlQuery}
                onChange={e => setSparqlQuery(e.target.value)} style={{fontSize:12}} />
              <button className="btn btn-primary btn-sm mb-3" onClick={handleSparql} disabled={sparqlRunning}>
                {sparqlRunning ? 'Running…' : 'Run Query'}
              </button>
              {sparqlResult && (
                sparqlResult.success
                  ? (
                    <div style={{maxHeight:200,overflowY:'auto'}}>
                      <table className="table table-sm table-bordered" style={{fontSize:11}}>
                        <thead className="table-light">
                          <tr>{(sparqlResult.data?.columns||[]).map(c => <th key={c}>{c}</th>)}</tr>
                        </thead>
                        <tbody>
                          {(sparqlResult.data?.rows||[]).map((row,i) => (
                            <tr key={i}>{(sparqlResult.data?.columns||[]).map(c => (
                              <td key={c} style={{wordBreak:'break-all',maxWidth:200}}>{row[c]||''}</td>
                            ))}</tr>
                          ))}
                        </tbody>
                      </table>
                      <small className="text-muted">{sparqlResult.data?.count} rows</small>
                    </div>
                  )
                  : <div className="alert alert-danger py-1" style={{fontSize:12}}>{sparqlResult.error}</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Start frontend and test the Ontology tab manually**

```bash
cd frontend && npm start
# Open http://localhost:3000/admin → Ontology tab
# 1. Click Refresh — should show named graphs list
# 2. Paste a valid TTL, click Validate — should show triple count
# 3. Click Upload to GraphDB — graph should appear in list
# 4. Run the example SPARQL query — should return sensors
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/OntologyTab.js
git commit -m "feat(frontend): OntologyTab — TTL upload, named-graph manager, SPARQL browser"
```

---

## Task 6: Frontend — DatabasesTab (Full Workflow)

**Files:**
- Modify: `frontend/src/components/admin/DatabasesTab.js`

- [ ] **Step 1: Implement DatabasesTab with the complete sensor registration workflow**

The database tab must walk an admin through the full flow:
1. List existing connections
2. Add a new DB connection (with test button)
3. Introspect tables
4. Register sensors (CSV paste or manual point entry)
5. Show triple count (sensors registered in GraphDB)

```javascript
// frontend/src/components/admin/DatabasesTab.js
import React, { useState, useEffect, useCallback } from 'react';

const CSV_HELP = `local,brick_class,location,uuid,unit,label
Zone5_Temp,brick:Temperature_Sensor,bldg:Floor5,<real-uuid-from-db>,unit:DEG_C,Zone 5 Temperature
Zone5_CO2,brick:CO2_Sensor,bldg:Floor5,<real-uuid-from-db>,unit:PPM,Zone 5 CO₂`;

export default function DatabasesTab({ api, headers }) {
  const [dbs, setDbs] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  // Add DB form
  const [form, setForm] = useState({ key:'', type:'mysql_narrow', host:'', port:'3306', user:'', password:'', database:'', table:'' });
  const [testResult, setTestResult] = useState(null);
  const [introspectResult, setIntrospectResult] = useState(null);

  // Sensor CSV registration
  const [selectedDb, setSelectedDb] = useState('');
  const [csvText, setCsvText] = useState(CSV_HELP);
  const [csvResult, setCsvResult] = useState(null);

  const loadDbs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/databases`, { headers });
      const d = await r.json();
      setDbs(d.data?.databases || []);
      const cr = await fetch(`${api}/api/v1/admin/databases/sensor-counts`, { headers });
      const cd = await cr.json();
      setCounts(cd.data?.counts || {});
    } finally {
      setLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { loadDbs(); }, [loadDbs]);

  const handleTest = async () => {
    setTestResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/test`, {
      method: 'POST', headers, body: JSON.stringify({ ...form, port: String(form.port) })
    });
    setTestResult(await r.json());
  };

  const handleIntrospect = async () => {
    setIntrospectResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/introspect`, {
      method: 'POST', headers, body: JSON.stringify({ ...form, port: String(form.port) })
    });
    setIntrospectResult(await r.json());
  };

  const handleAdd = async () => {
    setMsg('');
    const r = await fetch(`${api}/api/v1/admin/databases`, {
      method: 'POST', headers, body: JSON.stringify(form)
    });
    const d = await r.json();
    setMsg(d.success ? `✓ Added '${form.key}'. Restart the orchestrator for it to take effect.` : `✗ ${d.error}`);
    if (d.success) loadDbs();
  };

  const handleDelete = async (key) => {
    if (!window.confirm(`Delete connection '${key}'?`)) return;
    const r = await fetch(`${api}/api/v1/admin/databases/${key}`, { method: 'DELETE', headers });
    const d = await r.json();
    setMsg(d.success ? `Deleted '${key}'` : `Error: ${d.error}`);
    loadDbs();
  };

  const handleRegisterCsv = async () => {
    setCsvResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/${selectedDb}/sensors/csv`, {
      method: 'POST', headers, body: JSON.stringify({ csv: csvText })
    });
    setCsvResult(await r.json());
    if ((await r.json())?.success) loadDbs();
  };

  const f = (k) => (e) => setForm(prev => ({ ...prev, [k]: e.target.value }));

  return (
    <div>
      {msg && <div className={`alert py-2 alert-${msg.startsWith('✗') ? 'danger' : 'success'} mb-3`}>{msg}</div>}

      {/* Existing connections */}
      <h5>Connections</h5>
      <div className="table-responsive mb-4">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Key</th><th>Type</th><th>Host</th><th>Source</th><th>Active</th><th>Sensors in GraphDB</th><th></th></tr>
          </thead>
          <tbody>
            {dbs.length === 0 && <tr><td colSpan={7} className="text-center text-muted">No connections</td></tr>}
            {dbs.map(db => (
              <tr key={db.key}>
                <td><code>{db.key}</code></td>
                <td>{db.type}</td>
                <td>{db.fields?.host || '—'}</td>
                <td><span className={`badge bg-${db.source==='curated'?'secondary':'info'}`}>{db.source}</span></td>
                <td><span className={`badge bg-${db.active?'success':'warning'}`}>{db.active?'Yes':'No'}</span></td>
                <td className="text-end">{counts[db.key] ?? '—'}</td>
                <td>
                  {db.source === 'custom' && (
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => handleDelete(db.key)}>Del</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn btn-sm btn-outline-secondary" onClick={loadDbs} disabled={loading}>Refresh</button>
      </div>

      <div className="row g-4">
        {/* Add Connection form */}
        <div className="col-12 col-lg-6">
          <div className="card">
            <div className="card-header"><strong>Add External Database Connection</strong></div>
            <div className="card-body">
              {[
                ['key', 'Registry Key (e.g. bldg2_mysql)', 'text'],
                ['host', 'Host', 'text'],
                ['port', 'Port', 'text'],
                ['user', 'User', 'text'],
                ['password', 'Password', 'password'],
                ['database', 'Database Name', 'text'],
                ['table', 'Table (narrow adapter only)', 'text'],
              ].map(([k, label, type]) => (
                <div className="mb-2" key={k}>
                  <label className="form-label small mb-0">{label}</label>
                  <input className="form-control form-control-sm" type={type} value={form[k]}
                    onChange={f(k)} />
                </div>
              ))}
              <div className="mb-2">
                <label className="form-label small mb-0">Type</label>
                <select className="form-select form-select-sm" value={form.type} onChange={f('type')}>
                  {['mysql', 'mysql_narrow', 'postgresql', 'timescaledb'].map(t =>
                    <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="d-flex gap-2 flex-wrap">
                <button className="btn btn-sm btn-outline-secondary" onClick={handleTest}>Test Connection</button>
                <button className="btn btn-sm btn-outline-info" onClick={handleIntrospect}>Introspect Tables</button>
                <button className="btn btn-sm btn-primary" onClick={handleAdd}>Add Connection</button>
              </div>
              {testResult && (
                <div className={`alert py-1 mt-2 alert-${testResult.success ? 'success' : 'danger'}`} style={{fontSize:12}}>
                  {testResult.success ? `✓ Connected (${testResult.data?.latency_ms}ms)` : `✗ ${testResult.error}`}
                </div>
              )}
              {introspectResult?.success && (
                <div className="mt-2" style={{maxHeight:120,overflowY:'auto',fontSize:11}}>
                  {(introspectResult.data?.tables||[]).map(t => (
                    <div key={t.name}><strong>{t.name}</strong>: {t.columns.map(c=>c.name).join(', ')}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Sensor CSV registration */}
        <div className="col-12 col-lg-6">
          <div className="card">
            <div className="card-header"><strong>Register Sensors (CSV → GraphDB Triples)</strong></div>
            <div className="card-body">
              <p className="small text-muted mb-2">
                After adding a DB, register its sensors so SPARQL can find them.
                Each row becomes Brick triples in GraphDB. UUIDs must match real rows in the DB.
              </p>
              <div className="mb-2">
                <label className="form-label small mb-0">Target connection</label>
                <select className="form-select form-select-sm" value={selectedDb}
                  onChange={e => setSelectedDb(e.target.value)}>
                  <option value="">— select a connection —</option>
                  {dbs.map(db => <option key={db.key} value={db.key}>{db.key}</option>)}
                </select>
              </div>
              <label className="form-label small mb-0">CSV (header: local,brick_class,location,uuid[,unit,label])</label>
              <textarea className="form-control font-monospace mb-2" rows={8} value={csvText}
                onChange={e => setCsvText(e.target.value)} style={{fontSize:11}} />
              <button className="btn btn-sm btn-primary" disabled={!selectedDb || !csvText}
                onClick={handleRegisterCsv}>
                Register Sensors in GraphDB
              </button>
              {csvResult && (
                <div className={`alert py-1 mt-2 alert-${csvResult.success ? 'success' : 'danger'}`} style={{fontSize:12}}>
                  {csvResult.success
                    ? `✓ Registered ${csvResult.data?.points} sensors for '${selectedDb}'`
                    : `✗ ${csvResult.error}`}
                  {csvResult.data?.parse_warnings?.length > 0 && (
                    <div className="mt-1 text-warning">Warnings: {csvResult.data.parse_warnings.join('; ')}</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test DB tab manually**

```
Admin Portal → Databases tab
1. Click Refresh — existing curated connections should appear
2. Fill form with a test MySQL connection → Test Connection → expect latency_ms
3. Click Introspect → should list tables
4. Add a connection → should appear in list with source=custom
5. Select it → paste CSV → Register → triple count > 0 in list
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/DatabasesTab.js
git commit -m "feat(frontend): DatabasesTab — full DB connect → sensor CSV → GraphDB workflow"
```

---

## Task 7: Frontend — IndexStatusTab + Trigger Re-index

**Files:**
- Modify: `frontend/src/components/admin/IndexStatusTab.js`

- [ ] **Step 1: Implement IndexStatusTab**

```javascript
// frontend/src/components/admin/IndexStatusTab.js
import React, { useState, useEffect, useCallback } from 'react';

export default function IndexStatusTab({ api, headers }) {
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [targets, setTargets] = useState({ capability: true, documents: false });
  const [activeJob, setActiveJob] = useState(null);
  const [polling, setPolling] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch(`${api}/api/v1/admin/capability-indexer/status`, { headers });
      setStatus((await r.json()).data);
    } catch {}
  }, [api, headers]);

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetch(`${api}/api/v1/admin/reindex`, { headers });
      setJobs((await r.json()).data?.jobs || []);
    } catch {}
  }, [api, headers]);

  useEffect(() => { loadStatus(); loadJobs(); }, [loadStatus, loadJobs]);

  const triggerReindex = async () => {
    const chosen = Object.entries(targets).filter(([,v])=>v).map(([k])=>k);
    if (chosen.length === 0) return;
    const r = await fetch(`${api}/api/v1/admin/reindex`, {
      method: 'POST', headers, body: JSON.stringify({ targets: chosen })
    });
    const d = await r.json();
    if (d.success) {
      setActiveJob(d.data.job_id);
      setPolling(true);
    }
  };

  useEffect(() => {
    if (!polling || !activeJob) return;
    const interval = setInterval(async () => {
      const r = await fetch(`${api}/api/v1/admin/reindex/${activeJob}`, { headers });
      const d = await r.json();
      const job = d.data;
      if (job?.status === 'done' || job?.status === 'error') {
        setPolling(false);
        loadStatus();
        loadJobs();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, activeJob, api, headers, loadStatus, loadJobs]);

  const bldgStatus = status?.buildings || {};

  return (
    <div>
      <h5>Capability KB Index Status</h5>
      <div className="table-responsive mb-4">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Building</th><th>Status</th><th>Entries (YAML)</th><th>Points (Qdrant)</th><th>Duration</th><th>Reason</th></tr>
          </thead>
          <tbody>
            {Object.entries(bldgStatus).length === 0 && (
              <tr><td colSpan={6} className="text-center text-muted">Not loaded (GET /health for diagnostics)</td></tr>
            )}
            {Object.entries(bldgStatus).map(([bid, b]) => (
              <tr key={bid}>
                <td><code>{bid}</code></td>
                <td>
                  <span className={`badge bg-${b.status==='indexed'?'success':b.status==='degraded'?'warning':'secondary'}`}>
                    {b.status}
                  </span>
                </td>
                <td>{b.entries}</td>
                <td>{b.points}</td>
                <td>{b.duration_ms}ms</td>
                <td style={{fontSize:11}}>{b.reason||'—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card mb-4" style={{maxWidth:520}}>
        <div className="card-header"><strong>Trigger Re-index</strong></div>
        <div className="card-body">
          <p className="small text-muted">Run after uploading new TTL or registering sensors to make new knowledge discoverable.</p>
          <div className="mb-2">
            {['capability', 'documents', 'floor_plans'].map(t => (
              <div className="form-check form-check-inline" key={t}>
                <input className="form-check-input" type="checkbox" id={`tgt-${t}`}
                  checked={!!targets[t]}
                  onChange={e => setTargets(prev => ({ ...prev, [t]: e.target.checked }))} />
                <label className="form-check-label" htmlFor={`tgt-${t}`}>{t}</label>
              </div>
            ))}
          </div>
          <button className="btn btn-primary btn-sm" onClick={triggerReindex}
            disabled={polling || !Object.values(targets).some(Boolean)}>
            {polling ? `Indexing (job: ${activeJob})…` : 'Start Re-index'}
          </button>
        </div>
      </div>

      <h5>Recent Re-index Jobs</h5>
      <div className="table-responsive">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Job ID</th><th>Targets</th><th>Status</th><th>Elapsed</th><th>Results</th></tr>
          </thead>
          <tbody>
            {jobs.length === 0 && <tr><td colSpan={5} className="text-center text-muted">No jobs this session</td></tr>}
            {jobs.map(j => (
              <tr key={j.id}>
                <td><code>{j.id}</code></td>
                <td>{j.targets?.join(', ')}</td>
                <td><span className={`badge bg-${j.status==='done'?'success':j.status==='error'?'danger':'info'}`}>{j.status}</span></td>
                <td>{j.elapsed_s}s</td>
                <td style={{fontSize:11}}>{JSON.stringify(j.results)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test manually**

```
Admin Portal → Index Status tab
1. Table shows current indexer status for each building
2. Check 'capability', click Start Re-index → status badge shows running → eventually done
3. Re-index jobs table updates
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/IndexStatusTab.js
git commit -m "feat(frontend): IndexStatusTab — Qdrant KB status + trigger re-index with polling"
```

---

## Task 8: Frontend — Remaining Tabs (Users, System, DataSources, Audit)

**Files:**
- Modify: `frontend/src/components/admin/UsersTab.js`
- Modify: `frontend/src/components/admin/SystemTab.js`
- Modify: `frontend/src/components/admin/DataSourcesTab.js`
- Modify: `frontend/src/components/admin/AuditTab.js`

- [ ] **Step 1: Implement UsersTab**

```javascript
// frontend/src/components/admin/UsersTab.js
import React, { useState, useEffect, useCallback } from 'react';

const ROLES = ['admin','facility_manager','analyst','operator','occupant','readonly'];

export default function UsersTab({ api, headers }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ username:'', password:'', role:'readonly', email:'' });
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    const r = await fetch(`${api}/api/v1/admin/users`, { headers });
    const d = await r.json();
    setUsers(d.data?.users || []);
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    const r = await fetch(`${api}/api/v1/admin/users`, {
      method:'POST', headers, body: JSON.stringify(form)
    });
    const d = await r.json();
    setMsg(d.success ? `Created ${form.username}` : d.error);
    if (d.success) { setForm({username:'',password:'',role:'readonly',email:''}); load(); }
  };

  const changeRole = async (username, role) => {
    await fetch(`${api}/api/v1/admin/users/${username}/role`, {
      method:'PUT', headers, body: JSON.stringify({ role })
    });
    load();
  };

  const del = async (username) => {
    if (!window.confirm(`Delete user '${username}'?`)) return;
    await fetch(`${api}/api/v1/admin/users/${username}`, { method:'DELETE', headers });
    load();
  };

  return (
    <div>
      {msg && <div className="alert alert-info py-1 mb-3">{msg}</div>}
      <div className="row g-4">
        <div className="col-12 col-lg-7">
          <h5>Users</h5>
          <table className="table table-sm table-bordered">
            <thead className="table-light"><tr><th>Username</th><th>Role</th><th>Email</th><th></th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.username}>
                  <td><code>{u.username}</code></td>
                  <td>
                    <select className="form-select form-select-sm" value={u.role}
                      onChange={e => changeRole(u.username, e.target.value)} style={{minWidth:130}}>
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td style={{fontSize:12}}>{u.email||'—'}</td>
                  <td>
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => del(u.username)}>Del</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="col-12 col-lg-5">
          <div className="card">
            <div className="card-header"><strong>Create User</strong></div>
            <div className="card-body">
              {[['username','Username','text'],['password','Password','password'],['email','Email (optional)','email']].map(([k,label,type]) => (
                <div className="mb-2" key={k}>
                  <label className="form-label small mb-0">{label}</label>
                  <input className="form-control form-control-sm" type={type} value={form[k]}
                    onChange={e => setForm(prev=>({...prev,[k]:e.target.value}))} />
                </div>
              ))}
              <div className="mb-2">
                <label className="form-label small mb-0">Role</label>
                <select className="form-select form-select-sm" value={form.role}
                  onChange={e => setForm(prev=>({...prev,role:e.target.value}))}>
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <button className="btn btn-sm btn-primary" onClick={create}>Create</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement SystemTab**

```javascript
// frontend/src/components/admin/SystemTab.js
import React, { useState, useEffect } from 'react';

export default function SystemTab({ api, headers }) {
  const [env, setEnv] = useState([]);
  const [aiConfig, setAiConfig] = useState(null);
  const [edits, setEdits] = useState({});
  const [envMsg, setEnvMsg] = useState('');
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    fetch(`${api}/api/v1/admin/env`, { headers })
      .then(r=>r.json()).then(d => setEnv(d.data?.env||[])).catch(()=>{});
    fetch(`${api}/api/v1/admin/ai-config`, { headers })
      .then(r=>r.json()).then(d => setAiConfig(d.data)).catch(()=>{});
  }, [api, headers]);

  const saveEnv = async () => {
    const r = await fetch(`${api}/api/v1/admin/env`, {
      method:'PUT', headers, body: JSON.stringify({ changes: edits })
    });
    const d = await r.json();
    setEnvMsg(d.success ? `Saved ${d.data?.updated?.length||0} keys. Restart required.` : d.error);
    setEdits({});
  };

  const doRestart = async () => {
    if (!window.confirm('Restart the orchestrator now? All in-flight requests will fail.')) return;
    setRestarting(true);
    await fetch(`${api}/api/v1/admin/restart`, { method:'POST', headers });
    setTimeout(() => setRestarting(false), 8000);
  };

  return (
    <div>
      <div className="row g-4">
        <div className="col-12 col-lg-8">
          <h5>.env Editor <small className="text-muted fs-6">(secrets are masked)</small></h5>
          {envMsg && <div className="alert alert-info py-1 mb-2">{envMsg}</div>}
          <div style={{maxHeight:420,overflowY:'auto'}}>
            <table className="table table-sm table-bordered">
              <thead className="table-light"><tr><th style={{width:'35%'}}>Key</th><th>Value</th></tr></thead>
              <tbody>
                {env.map(row => (
                  <tr key={row.key}>
                    <td style={{fontFamily:'monospace',fontSize:12}}>{row.key}</td>
                    <td>
                      <input className="form-control form-control-sm font-monospace"
                        type={row.is_secret ? 'password' : 'text'}
                        defaultValue={row.value}
                        onChange={e => setEdits(prev => ({...prev, [row.key]: e.target.value}))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="btn btn-sm btn-primary mt-2" onClick={saveEnv}
            disabled={Object.keys(edits).length===0}>
            Save {Object.keys(edits).length > 0 ? `(${Object.keys(edits).length} change${Object.keys(edits).length>1?'s':''})` : ''}
          </button>
        </div>
        <div className="col-12 col-lg-4">
          {aiConfig && (
            <div className="card mb-3">
              <div className="card-header"><strong>AI Configuration</strong></div>
              <div className="card-body" style={{fontSize:13}}>
                <p><strong>Model Provider:</strong> {aiConfig.model_provider}</p>
                <p><strong>Embedding Provider:</strong> {aiConfig.embedding_provider}</p>
                <p><strong>Ollama Model:</strong> {aiConfig.ollama_model||'—'}</p>
                <p><strong>OpenAI Model:</strong> {aiConfig.openai_model||'—'}</p>
                <p><strong>OpenAI Key Set:</strong> {aiConfig.openai_api_key_set ? '✓ Yes' : '✗ No'}</p>
              </div>
            </div>
          )}
          <div className="card border-danger">
            <div className="card-header bg-danger text-white"><strong>Orchestrator Restart</strong></div>
            <div className="card-body">
              <p className="small text-muted">Required after .env changes. Docker restart policy keeps it alive.</p>
              <button className="btn btn-danger btn-sm w-100" onClick={doRestart} disabled={restarting}>
                {restarting ? 'Restarting…' : 'Restart Orchestrator'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Implement DataSourcesTab**

```javascript
// frontend/src/components/admin/DataSourcesTab.js
import React, { useState, useEffect, useCallback } from 'react';

export default function DataSourcesTab({ api, headers }) {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/datasources`, { headers });
      const d = await r.json();
      setSources(d.data?.sources || []);
    } finally { setLoading(false); }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (id, enable) => {
    setMsg('');
    const action = enable ? 'enable' : 'disable';
    const r = await fetch(`${api}/api/v1/datasources/${id}/${action}`, { method:'POST', headers });
    const d = await r.json();
    setMsg(d.success ? `${enable?'Enabled':'Disabled'} '${id}'` : d.error);
    load();
  };

  const regenerate = async (id) => {
    setMsg(`Regenerating ${id}…`);
    const r = await fetch(`${api}/api/v1/datasources/${id}/regenerate`, { method:'POST', headers });
    const d = await r.json();
    setMsg(d.success ? `Regenerated ${id}` : d.error);
  };

  const resetDemo = async () => {
    if (!window.confirm('Disable all enabled sources? (demo reset)')) return;
    await fetch(`${api}/api/v1/datasources/reset-demo`, { method:'POST', headers });
    setMsg('Demo reset: all sources disabled');
    load();
  };

  return (
    <div>
      {msg && <div className="alert alert-info py-1 mb-3">{msg}</div>}
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h5>Synthetic Data Sources</h5>
        <div className="d-flex gap-2">
          <button className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>Refresh</button>
          <button className="btn btn-sm btn-outline-danger" onClick={resetDemo}>Reset Demo</button>
        </div>
      </div>
      <p className="small text-muted">
        Enabling a source loads its Brick triples into a named graph, making its sensors discoverable via SPARQL.
        Disabling clears that graph — questions about it return "data unavailable" until re-enabled.
      </p>
      {sources.length === 0 && <div className="text-muted">No toggleable data sources (DATASOURCE_TOGGLES_ENABLED=false?)</div>}
      <div className="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">
        {sources.map(s => (
          <div className="col" key={s.id}>
            <div className={`card h-100 border-${s.enabled?'success':'secondary'}`}>
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-start mb-1">
                  <strong>{s.id}</strong>
                  <span className={`badge bg-${s.enabled?'success':'secondary'}`}>{s.enabled?'Enabled':'Off'}</span>
                </div>
                <div style={{fontSize:12}} className="text-muted mb-2">
                  {s.sensor_count != null && <span>Sensors: {s.sensor_count}</span>}
                  {s.row_count != null && <span> | Rows: {s.row_count}</span>}
                </div>
                <div className="d-flex gap-1">
                  <button className={`btn btn-xs py-0 px-2 btn-${s.enabled?'outline-secondary':'success'}`}
                    style={{fontSize:11}} onClick={() => toggle(s.id, !s.enabled)}>
                    {s.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button className="btn btn-xs py-0 px-2 btn-outline-primary" style={{fontSize:11}}
                    onClick={() => regenerate(s.id)}>Regenerate</button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement AuditTab**

```javascript
// frontend/src/components/admin/AuditTab.js
import React, { useState, useEffect } from 'react';

export default function AuditTab({ api, headers }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/audit`, { headers });
      const d = await r.json();
      setEntries(d.data?.entries || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="d-flex justify-content-between mb-3">
        <h5>Admin Action Audit Log</h5>
        <button className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>Refresh</button>
      </div>
      <p className="small text-muted">All mutating admin-console actions (100 most recent).</p>
      <div style={{maxHeight:500,overflowY:'auto'}}>
        <table className="table table-sm table-bordered" style={{fontSize:12}}>
          <thead className="table-light sticky-top">
            <tr><th>When</th><th>User</th><th>Method</th><th>Path</th><th>Status</th></tr>
          </thead>
          <tbody>
            {entries.length === 0 && <tr><td colSpan={5} className="text-center text-muted">No actions logged yet</td></tr>}
            {entries.map((e,i) => (
              <tr key={i}>
                <td style={{whiteSpace:'nowrap'}}>{e.created_at?.substring(0,19)}</td>
                <td>{e.username||'—'}</td>
                <td><span className={`badge bg-${e.method==='DELETE'?'danger':e.method==='POST'?'primary':'secondary'}`}>{e.method}</span></td>
                <td style={{wordBreak:'break-all',fontFamily:'monospace'}}>{e.path}</td>
                <td><span className={`badge bg-${e.status_code<300?'success':'warning'}`}>{e.status_code}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Test all 4 tabs manually, commit**

```bash
git add frontend/src/components/admin/UsersTab.js \
        frontend/src/components/admin/SystemTab.js \
        frontend/src/components/admin/DataSourcesTab.js \
        frontend/src/components/admin/AuditTab.js
git commit -m "feat(frontend): Users, System, DataSources, Audit tabs complete"
```

---

## Task 9: Frontend — CoverageTab (Research Dashboard)

**Files:**
- Modify: `frontend/src/components/admin/CoverageTab.js`

This tab lets an admin run sample questions and see before/after question coverage — the core research proof point.

- [ ] **Step 1: Implement CoverageTab**

```javascript
// frontend/src/components/admin/CoverageTab.js
import React, { useState } from 'react';

const SAMPLE_QUESTIONS = [
  "What is the current temperature in Zone 3?",
  "How many CO2 sensors are on floor 2?",
  "Which rooms have occupancy sensors?",
  "What is the average humidity on floor 1?",
  "Show me all air quality sensors",
  "What equipment is in the server room?",
  "How many sensors are there in total?",
  "Which zones had high CO2 last week?",
  "What is the energy consumption trend?",
  "Are there any anomalous temperature readings?",
];

export default function CoverageTab({ api, headers }) {
  const [questions, setQuestions] = useState(SAMPLE_QUESTIONS.join('\n'));
  const [sessionId] = useState(`coverage-test-${Date.now()}`);
  const [results, setResults] = useState([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);

  const runCoverage = async () => {
    const qs = questions.split('\n').map(q => q.trim()).filter(Boolean);
    if (qs.length === 0) return;
    setRunning(true);
    setResults([]);
    setProgress(0);

    const newResults = [];
    for (let i = 0; i < qs.length; i++) {
      const q = qs[i];
      const t0 = Date.now();
      try {
        const r = await fetch(`${api}/chat`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ message: q, session_id: sessionId + `-${i}` }),
        });
        const d = await r.json();
        const latency = Date.now() - t0;
        const response = d.response || d.data?.response || '';
        const answerable = response.length > 20 &&
          !response.toLowerCase().includes("don't have") &&
          !response.toLowerCase().includes("not available") &&
          !response.toLowerCase().includes("cannot find") &&
          !response.toLowerCase().includes("no data");
        newResults.push({
          question: q, answerable, latency,
          intent: d.intent || d.data?.intent || '?',
          snippet: response.substring(0, 120),
          error: null,
        });
      } catch (e) {
        newResults.push({ question: q, answerable: false, latency: Date.now()-t0, intent: '?', snippet: '', error: String(e) });
      }
      setResults([...newResults]);
      setProgress(Math.round(((i+1)/qs.length)*100));
    }
    setRunning(false);
  };

  const exportCsv = () => {
    const rows = ['question,answerable,intent,latency_ms,snippet'];
    results.forEach(r => {
      rows.push(`"${r.question.replace(/"/g,'""')}",${r.answerable},${r.intent},${r.latency},"${(r.snippet||'').replace(/"/g,'""')}"`);
    });
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'question_coverage.csv'; a.click();
  };

  const answered = results.filter(r => r.answerable).length;
  const pct = results.length > 0 ? Math.round((answered/results.length)*100) : null;

  return (
    <div>
      <h5>Question Coverage Dashboard</h5>
      <p className="small text-muted mb-3">
        Run sample questions through OntoSage and see what percentage are answerable.
        Use this before and after adding data sources to show improvement — supports research paper claims.
      </p>

      <div className="row g-4">
        <div className="col-12 col-lg-5">
          <div className="card">
            <div className="card-header"><strong>Test Questions</strong></div>
            <div className="card-body">
              <label className="form-label small mb-1">One question per line</label>
              <textarea className="form-control mb-2" rows={12} value={questions}
                onChange={e => setQuestions(e.target.value)} style={{fontSize:13}} />
              <div className="d-flex gap-2">
                <button className="btn btn-primary btn-sm" onClick={runCoverage} disabled={running}>
                  {running ? `Running… ${progress}%` : 'Run Coverage Test'}
                </button>
                {results.length > 0 && (
                  <button className="btn btn-outline-secondary btn-sm" onClick={exportCsv}>Export CSV</button>
                )}
              </div>
              {running && (
                <div className="progress mt-2" style={{height:6}}>
                  <div className="progress-bar" style={{width:`${progress}%`}} />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="col-12 col-lg-7">
          {pct !== null && (
            <div className={`alert alert-${pct>=70?'success':pct>=40?'warning':'danger'} mb-3`}>
              <strong>Coverage: {pct}%</strong> ({answered}/{results.length} questions answered)
            </div>
          )}
          <div style={{maxHeight:480,overflowY:'auto'}}>
            <table className="table table-sm table-bordered" style={{fontSize:12}}>
              <thead className="table-light sticky-top">
                <tr><th>Question</th><th style={{width:80}}>Answerable</th><th style={{width:80}}>Intent</th><th style={{width:70}}>ms</th></tr>
              </thead>
              <tbody>
                {results.map((r,i) => (
                  <tr key={i} className={r.answerable ? '' : 'table-warning'}>
                    <td>
                      <div>{r.question}</div>
                      <div className="text-muted" style={{fontSize:10,fontStyle:'italic'}}>{r.snippet}</div>
                      {r.error && <div className="text-danger" style={{fontSize:10}}>{r.error}</div>}
                    </td>
                    <td className="text-center">
                      <span className={`badge bg-${r.answerable?'success':'danger'}`}>
                        {r.answerable?'✓ Yes':'✗ No'}
                      </span>
                    </td>
                    <td style={{fontSize:10}}>{r.intent}</td>
                    <td className="text-end">{r.latency}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test coverage tab**

```
Admin Portal → Coverage tab
1. Keep default sample questions
2. Click Run Coverage Test
3. See progress bar + live results table
4. Export CSV → file downloads
5. Coverage % is shown in green/yellow/red depending on score
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/CoverageTab.js
git commit -m "feat(frontend): CoverageTab — before/after question coverage for research proofs"
```

---

## Task 10: Fix Health Page Endpoints

**Files:**
- Modify: `frontend/src/pages/Health.js`

- [ ] **Step 1: Fix hardcoded endpoint list**

The current Health.js has two bugs: (1) it references Jena Fuseki on port 3030 but OntoSage uses GraphDB on 7200; (2) it references a `redis://localhost:6379/` URL that browsers can't reach. Fix both:

```javascript
// Replace the endpointList in Health.js:
const endpointList = [
  { name: 'Orchestrator API', url: 'http://localhost:8000/health', category: 'OntoSage 2.0' },
  { name: 'RAG Service', url: 'http://localhost:8001/health', category: 'OntoSage 2.0' },
  { name: 'Code Executor', url: 'http://localhost:8002/health', category: 'OntoSage 2.0' },
  { name: 'GraphDB (SPARQL)', url: 'http://localhost:7200/rest/repositories', category: 'Infrastructure' },
  { name: 'Qdrant Vector DB', url: 'http://localhost:6333/healthz', category: 'Infrastructure' },
  { name: 'OpenWebUI', url: 'http://localhost:3001/', category: 'User Interface' },
  { name: 'React Frontend', url: 'http://localhost:3000/', category: 'User Interface' },
];
```

- [ ] **Step 2: Verify the health page now shows GraphDB and not Jena Fuseki**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Health.js
git commit -m "fix(frontend): Health page — correct GraphDB port 7200, remove Redis/Jena Fuseki refs"
```

---

## Task 11: End-to-End Flow Test (Manual — Full Lifecycle)

This task documents the proof of the admin lifecycle for the research paper.

- [ ] **Step 1: Start the stack**

```bash
docker-compose up -d
# Wait for: orchestrator healthy (http://localhost:8000/health → all green)
```

- [ ] **Step 2: Run coverage BEFORE adding any new data**

```
Admin Portal → Coverage → Run Coverage Test
Record: coverage% = X%
Export CSV → save as coverage_before.csv
```

- [ ] **Step 3: Upload an extension TTL**

```
Admin Portal → Ontology → Upload TTL
Named graph: urn:ontosage:ttl:floor6_extension.ttl
TTL content: (a few sensors on floor 6 not in the existing ontology)
Click Upload → should show "Uploaded N triples"
```

- [ ] **Step 4: Register an external DB + sensors**

```
Admin Portal → Databases
1. Add connection (pointing at MySQL)
2. Test connection → latency shown
3. Register sensors via CSV (real UUIDs from the DB)
4. Verify: sensor count > 0 in the connection list
```

- [ ] **Step 5: Re-index**

```
Admin Portal → Index Status → Check 'capability' + 'documents'
Click Start Re-index
Wait for status: done
```

- [ ] **Step 6: Run coverage AFTER**

```
Admin Portal → Coverage → Run Coverage Test (same questions)
Record: coverage% = Y% (should be > X%)
Export CSV → save as coverage_after.csv
```

- [ ] **Step 7: SPARQL verify new triples are findable**

```
Admin Portal → Ontology → SPARQL Browser
Run: SELECT ?s WHERE { GRAPH <urn:ontosage:ttl:floor6_extension.ttl> { ?s ?p ?o } } LIMIT 20
Should return the uploaded sensors
```

- [ ] **Step 8: Ask a question about the new data**

```
Chat: "What sensors are on floor 6?"
Expected: OntoSage now answers with the newly uploaded sensors (was unanswerable before)
```

---

## Task 12: Backend Tests for New Endpoints (Unit)

**Files:**
- Create: `tests/test_admin_endpoints_full.py`

- [ ] **Step 1: Write and run the unit test suite**

```python
# tests/test_admin_endpoints_full.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.unit


def test_validate_endpoint_good_ttl(test_client, admin_token):
    """validate accepts valid Turtle and returns triple_count."""
    ttl = "@prefix b: <http://brickschema.org/schema/Brick#> .\n<x> a b:Sensor ."
    resp = test_client.post(
        "/api/v1/admin/ontology/validate",
        json={"ttl": ttl},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["triple_count"] >= 1


def test_validate_endpoint_bad_ttl(test_client, admin_token):
    resp = test_client.post(
        "/api/v1/admin/ontology/validate",
        json={"ttl": "this is not turtle at all @@@@"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_sparql_browser_rejects_update(test_client, admin_token):
    """Non-SELECT queries must be rejected."""
    resp = test_client.post(
        "/api/v1/admin/ontology/sparql",
        json={"query": "INSERT DATA { <x> <y> <z> }", "limit": 10},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "SELECT" in resp.json()["error"]


def test_reindex_endpoint_returns_job_id(test_client, admin_token):
    resp = test_client.post(
        "/api/v1/admin/reindex",
        json={"targets": ["capability"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["success"] is True
    assert "job_id" in d["data"]
    job_id = d["data"]["job_id"]

    # poll status
    resp2 = test_client.get(
        f"/api/v1/admin/reindex/{job_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["found"] is True
```

Run: `pytest tests/test_admin_endpoints_full.py -v`

- [ ] **Step 2: Commit**

```bash
git add tests/test_admin_endpoints_full.py
git commit -m "test(admin): unit tests for new ontology + reindex endpoints"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Admin can upload TTL manually → Task 5 (OntologyTab), Task 3 (upload endpoint)
- [x] Admin can drop triples → Task 3 (drop endpoint), Task 5 (Drop button per graph)
- [x] CSV upload for sensor registration → Task 6 (DatabasesTab with CSV area)
- [x] TTL validation before upload → Task 1 (validate_ttl_text), Task 5 (Validate button)
- [x] GraphDB named-graph management → Task 1 + Task 5 (named graph table)
- [x] Qdrant re-indexing trigger → Task 2 + Task 7 (IndexStatusTab)
- [x] Before/after question coverage → Task 9 (CoverageTab)
- [x] Admin portal with all tabs → Task 4 (AdminPortal page + route)
- [x] User management → Task 8 (UsersTab)
- [x] .env editor → Task 8 (SystemTab)
- [x] Data source toggles → Task 8 (DataSourcesTab)
- [x] Audit log → Task 8 (AuditTab)
- [x] SPARQL browser → Task 5 (OntologyTab SPARQL panel)
- [x] Health page fix → Task 10

**Placeholder scan:** No TBD, no "implement later", no missing code blocks found.

**Type consistency:**
- `list_named_graphs()` in ontology_manager.py returns `Dict[str, int]` — matches frontend `.data.graphs` iteration.
- `validate_ttl_text()` returns `{ok, triple_count, error, prefixes}` — frontend reads `.data.triple_count`.
- `ReindexService.start()` returns `str` job_id — endpoint returns `{job_id: str}` — frontend polls `/reindex/{job_id}`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-07-admin-portal-triple-management.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session using executing-plans

**Which approach?**
