"""
live.py — shared helpers for running deliberation tooling against the LIVE stack.

Used by host-side scripts (scripts/audit_coverage.py, scripts/saturate_building.py)
and safe inside the orchestrator container too:

  * ``active_identity()`` — the ACTIVE building's id/namespace/prefix. Host-side,
    ``shared.config.settings`` only sees real environment variables (it does not
    read the repo ``.env``), so the identity file ``input/env.building`` is the
    source of truth; settings is the in-container fallback.
  * ``sparql_exec`` — async SPARQL-JSON executor with a localhost fallback for
    host-side runs (the configured GraphDB host is the docker-network hostname).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import httpx

from shared.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[3]

_IDENTITY_KEYS = ("BUILDING_ID", "BUILDING_NAMESPACE", "BUILDING_PREFIX")


def active_identity() -> Dict[str, str]:
    """Active building identity: input/env.building first, settings fallback."""
    identity = {
        "BUILDING_ID": settings.BUILDING_ID,
        "BUILDING_NAMESPACE": settings.BUILDING_NAMESPACE,
        "BUILDING_PREFIX": settings.BUILDING_PREFIX,
    }
    env_building = _REPO_ROOT / "input" / "env.building"
    if env_building.exists():
        for line in env_building.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                key, value = s.split("=", 1)
                if key.strip() in _IDENTITY_KEYS:
                    identity[key.strip()] = value.strip()
    return identity


def endpoint_candidates() -> List[str]:
    """Configured GraphDB endpoint first; localhost fallback for host-side runs."""
    configured = (
        f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
        f"/repositories/{settings.GRAPHDB_REPOSITORY}"
    )
    local = f"http://localhost:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"
    return [configured] if configured == local else [configured, local]


_resolved_endpoint: str = ""


async def sparql_exec(query: str) -> Dict[str, Any]:
    """POST a SPARQL query, returning SPARQL-JSON; remembers the working endpoint."""
    global _resolved_endpoint
    last_exc: Exception = RuntimeError("no GraphDB endpoint candidates")
    for endpoint in [_resolved_endpoint] if _resolved_endpoint else endpoint_candidates():
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    endpoint,
                    content=query.encode("utf-8"),
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                )
                resp.raise_for_status()
                _resolved_endpoint = endpoint
                return resp.json()
        except httpx.ConnectError as exc:
            last_exc = exc
            continue
    raise last_exc
