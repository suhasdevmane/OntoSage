"""Service launcher catalog — the attached tools an admin can open from the console.

Each entry describes a web UI the admin can reach (GraphDB workbench, Grafana, Adminer,
etc.). The console renders a card per service with a live up/down status and an "Open"
button. Status is probed from INSIDE the docker network (``probe`` = internal service URL);
the browser opens the HOST-facing URL, which the frontend builds from the viewer's own
hostname + ``port`` + ``path`` (so it works via localhost or a remote IP).

Adding a tool = one entry here (data-driven; no per-building literals). ``probe: None``
marks an optional tool that isn't wired into the running stack yet — the card shows
"optional" with the ``note`` on how to enable it.
"""

from __future__ import annotations

import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
from urllib.parse import urlparse

from shared.utils import get_logger

logger = get_logger(__name__)

# Dedicated pool for reachability probes. The app's default executor is saturated by
# blocking work, so getaddrinfo/connect run here on their own threads (probing on the
# default executor stalled reachable hosts for the full timeout).
_PROBE_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="svc-probe")


# Ordered catalog. `port`/`path` = host-facing (browser). `probe` = internal URL the
# orchestrator hits to decide online/offline (None = optional / not in the running stack).
SERVICE_CATALOG: List[Dict[str, Any]] = [
    # ── Data & Graph ────────────────────────────────────────────────────────────
    {
        "id": "graphdb",
        "name": "GraphDB",
        "desc": "Graph database & SPARQL workbench (the building ontology)",
        "category": "Data & Graph",
        "icon": "🗄️",
        "port": 7200,
        "path": "/",
        "probe": "http://graphdb:7200/rest/repositories",
    },
    {
        "id": "qdrant",
        "name": "Qdrant",
        "desc": "Vector database dashboard (capability / document embeddings)",
        "category": "Data & Graph",
        "icon": "🧬",
        "port": 6333,
        "path": "/dashboard",
        "probe": "http://qdrant:6333/healthz",
    },
    {
        "id": "adminer",
        "name": "Adminer",
        "desc": "Browse MySQL & PostgreSQL data (sensor readings, users, reports)",
        "category": "Data & Graph",
        "icon": "🗃️",
        "port": 8093,
        "path": "/",
        "probe": "http://adminer:8080/",
    },
    {
        "id": "fileserver",
        "name": "File Server",
        "desc": "Generated artifacts — charts, exports, reports",
        "category": "Data & Graph",
        "icon": "📁",
        "port": 8081,
        "path": "/",
        "probe": "http://file-server:80/",
    },
    # ── Monitoring ──────────────────────────────────────────────────────────────
    {
        "id": "grafana",
        "name": "Grafana",
        "desc": "Dashboards & time-series graphs",
        "category": "Monitoring",
        "icon": "📊",
        "port": 3002,
        "path": "/",
        "probe": "http://grafana:3000/api/health",
    },
    {
        "id": "prometheus",
        "name": "Prometheus",
        "desc": "Metrics & scrape targets",
        "category": "Monitoring",
        "icon": "📈",
        "port": 9090,
        "path": "/",
        "probe": "http://prometheus:9090/-/healthy",
    },
    # ── Core APIs ───────────────────────────────────────────────────────────────
    {
        "id": "orchestrator",
        "name": "Orchestrator API",
        "desc": "REST API + interactive Swagger docs",
        "category": "Core APIs",
        "icon": "⚙️",
        "port": 8000,
        "path": "/docs",
        "probe": "http://orchestrator:8000/health",
    },
    {
        "id": "rag",
        "name": "RAG Service",
        "desc": "Semantic retrieval API (SPARQL fallback)",
        "category": "Core APIs",
        "icon": "🔎",
        "port": 8001,
        "path": "/docs",
        "probe": "http://graphdb-rag-service:8001/health",
    },
    {
        "id": "mcp",
        "name": "MCP Server",
        "desc": "Model Context Protocol endpoint",
        "category": "Core APIs",
        "icon": "🔌",
        "port": 8003,
        "path": "/",
        "probe": "http://mcp-server:8003/health",
    },
    # ── AI & Chat ───────────────────────────────────────────────────────────────
    {
        "id": "openwebui",
        "name": "Open WebUI",
        "desc": "Conversational interface for users & admins",
        "category": "AI & Chat",
        "icon": "💬",
        "port": 3000,
        "path": "/",
        "probe": "http://open-webui:8080/health",
    },
    {
        "id": "ollama",
        "name": "Ollama",
        "desc": "Local LLM server (embeddings / generation)",
        "category": "AI & Chat",
        "icon": "🦙",
        "port": 11434,
        "path": "/",
        "probe": "http://host.docker.internal:11434/api/tags",
    },
    # ── Optional (enable in docker-compose.yml) ─────────────────────────────────
    {
        "id": "pgadmin",
        "name": "pgAdmin",
        "desc": "PostgreSQL administration UI",
        "category": "Optional",
        "icon": "🐘",
        "port": 5050,
        "path": "/",
        "probe": None,
        "note": "Uncomment the `pgadmin` service in docker-compose.yml, then recreate.",
    },
    {
        "id": "thingsboard",
        "name": "ThingsBoard",
        "desc": "IoT device & telemetry platform",
        "category": "Optional",
        "icon": "🛰️",
        "port": 8082,
        "path": "/",
        "probe": None,
        "note": "Uncomment the `thingsboard` service in docker-compose.yml, then recreate.",
    },
    {
        # Named generically on purpose (BUG-214 family): this catalogue is shown for
        # WHICHEVER building is active, so a service labelled after one building told every
        # other building it ran that building's viewer. The compose service name stays as it
        # is because it is a literal docker-compose identifier, not a claim about the building.
        "id": "building3d",
        "name": "3D Building Visualiser",
        "desc": "3D building & sensor visualization",
        "category": "Optional",
        "icon": "🏢",
        "port": 8090,
        "path": "/",
        "probe": None,
        "note": "Uncomment the 3D visualiser service in docker-compose.yml, then recreate.",
    },
]


def _tcp_ok(url: str, timeout: float = 2.5) -> bool:
    """A service is 'online' if a blocking TCP connection to its host:port succeeds.
    Runs on the dedicated probe pool (never the app's default executor)."""
    p = urlparse(url)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


async def probe_services() -> List[Dict[str, Any]]:
    """Return the catalog with a live ``status`` per service:
    ``online`` (reachable) · ``offline`` (probed, unreachable) · ``optional`` (not probed)."""
    probes = [(i, s["probe"]) for i, s in enumerate(SERVICE_CATALOG) if s.get("probe")]
    results: Dict[int, bool] = {}
    if probes:
        loop = asyncio.get_event_loop()
        futs = [loop.run_in_executor(_PROBE_POOL, _tcp_ok, u) for _, u in probes]
        oks = await asyncio.gather(*futs)
        results = {probes[k][0]: oks[k] for k in range(len(probes))}

    out: List[Dict[str, Any]] = []
    for i, s in enumerate(SERVICE_CATALOG):
        item = {k: v for k, v in s.items() if k != "probe"}
        if s.get("probe") is None:
            item["status"] = "optional"
        else:
            item["status"] = "online" if results.get(i) else "offline"
        out.append(item)
    return out
