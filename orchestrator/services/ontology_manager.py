"""
ontology_manager.py — Admin-facing CRUD operations on GraphDB named graphs.

Provides five public functions consumed by the admin console:

  list_named_graphs()     — list all named graphs with triple counts
  validate_ttl_text()     — parse Turtle in-process (sync, no network)
  upload_ttl()            — validate then PUT Turtle into a named graph
  drop_named_graph()      — DELETE a named graph
  run_sparql_select()     — safe read-only SELECT / ASK browser

All async functions accept an optional `client` parameter (injected
httpx.AsyncClient) so tests can mock without any live GraphDB.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

try:
    import rdflib

    _RDFLIB_AVAILABLE = True
except ImportError:
    _RDFLIB_AVAILABLE = False

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Default read/write timeout for GraphDB HTTP calls (seconds).
_TIMEOUT = 60.0

# SPARQL query used by list_named_graphs — one row per graph.
_LIST_GRAPHS_SPARQL = (
    "SELECT ?g (COUNT(*) AS ?n)"
    " WHERE { GRAPH ?g { ?s ?p ?o } }"
    " GROUP BY ?g"
    " ORDER BY DESC(?n)"
)

# Regex that finds the first SPARQL verb keyword in a query string,
# skipping over any leading PREFIX / BASE declarations.
_SPARQL_VERB_RE = re.compile(
    r"\b(SELECT|ASK|CONSTRUCT|DESCRIBE|INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY)\b",
    re.IGNORECASE,
)


def _graphdb_repo_url() -> str:
    """Return the base SPARQL endpoint URL for the configured repository."""
    base = settings.GRAPHDB_URL.rstrip("/")
    return f"{base}/repositories/{settings.GRAPHDB_REPOSITORY}"


def _rdf_graphs_url(graph_uri: str) -> str:
    """Return the named-graph management endpoint for *graph_uri*."""
    base = settings.GRAPHDB_URL.rstrip("/")
    encoded = quote_plus(graph_uri)
    return (
        f"{base}/repositories/{settings.GRAPHDB_REPOSITORY}"
        f"/rdf-graphs/service?graph={encoded}"
    )


async def list_named_graphs(
    client: Optional[Any] = None,
) -> Dict[str, int]:
    """Return all named graphs in GraphDB mapped to their triple counts.

    Returns {} (empty dict) if GraphDB is unreachable — never raises.
    """
    if not _HTTPX_AVAILABLE:
        logger.warning("[ontology_manager] httpx not installed — cannot list named graphs")
        return {}

    url = _graphdb_repo_url()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            resp = await client.post(
                url,
                content=_LIST_GRAPHS_SPARQL.encode("utf-8"),
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning(f"[ontology_manager] list_named_graphs: HTTP error — {exc}")
            return {}

        if resp.status_code != 200:
            logger.warning(
                f"[ontology_manager] list_named_graphs: HTTP {resp.status_code}"
                f" — {resp.text[:200]}"
            )
            return {}

        data = resp.json()
        result: Dict[str, int] = {}
        for binding in data.get("results", {}).get("bindings", []):
            g_uri = binding.get("g", {}).get("value", "")
            count_str = binding.get("n", {}).get("value", "0")
            if g_uri:
                try:
                    result[g_uri] = int(count_str)
                except ValueError:
                    result[g_uri] = 0
        return result
    finally:
        if owns:
            await client.aclose()


def validate_ttl_text(ttl_text: str) -> Dict[str, Any]:
    """Parse *ttl_text* as Turtle using rdflib and report validity (sync).

    Returns::

        {
            "ok": bool,
            "triple_count": int,
            "prefixes": dict,   # namespace prefix → URI
            "error": Optional[str],
        }
    """
    if not _RDFLIB_AVAILABLE:
        return {
            "ok": False,
            "triple_count": 0,
            "prefixes": {},
            "error": "rdflib not installed",
        }

    g = rdflib.Graph()
    try:
        g.parse(data=ttl_text, format="turtle")
    except Exception as exc:  # rdflib raises various parse exceptions
        return {
            "ok": False,
            "triple_count": 0,
            "prefixes": {},
            "error": f"parse error: {exc}",
        }

    prefixes = {str(prefix): str(ns) for prefix, ns in g.namespaces()}
    return {
        "ok": True,
        "triple_count": len(g),
        "prefixes": prefixes,
        "error": None,
    }


async def upload_ttl(
    ttl_text: str,
    graph_uri: str,
    client: Optional[Any] = None,
    *,
    replace: bool = False,
) -> Dict[str, Any]:
    """Validate then write Turtle content into a named graph in GraphDB.

    ``replace=False`` (default) POSTs the Turtle so triples are APPENDED to the
    named graph, preserving everything already there. ``replace=True`` PUTs,
    which REPLACES the whole named graph — every existing triple is deleted
    first. The additive default prevents silent data loss when an operator adds
    a handful of sensors to an already-populated graph; use replace only for a
    deliberate whole-graph overwrite (e.g. re-uploading a single-file graph).

    Validation happens locally first — invalid Turtle never reaches the network.

    Returns::

        {
            "ok": bool,
            "graph": str,
            "triple_count": int,
            "mode": "append" | "replace",
            "error": Optional[str],
        }
    """
    # Fast-fail: validate without touching the network.
    validation = validate_ttl_text(ttl_text)
    if not validation["ok"]:
        return {
            "ok": False,
            "graph": graph_uri,
            "triple_count": 0,
            "error": validation["error"],
        }

    if not _HTTPX_AVAILABLE:
        logger.warning("[ontology_manager] httpx not installed — cannot upload TTL")
        return {
            "ok": False,
            "graph": graph_uri,
            "triple_count": 0,
            "error": "httpx not available",
        }

    url = _rdf_graphs_url(graph_uri)
    mode = "replace" if replace else "append"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            # PUT replaces the whole named graph; POST appends to it.
            send = client.put if replace else client.post
            resp = await send(
                url,
                content=ttl_text.encode("utf-8"),
                headers={"Content-Type": "text/turtle"},
            )
        except httpx.HTTPError as exc:
            logger.warning(f"[ontology_manager] upload_ttl: HTTP error — {exc}")
            return {
                "ok": False,
                "graph": graph_uri,
                "triple_count": 0,
                "mode": mode,
                "error": str(exc),
            }

        # 201 Created is returned when POST creates a not-yet-existing graph.
        if resp.status_code in (200, 201, 204):
            logger.info(
                f"[ontology_manager] upload_ttl: {mode.upper()} {graph_uri!r}"
                f" HTTP {resp.status_code}, {validation['triple_count']} triples"
            )
            return {
                "ok": True,
                "graph": graph_uri,
                "triple_count": validation["triple_count"],
                "mode": mode,
                "error": None,
            }

        logger.warning(
            f"[ontology_manager] upload_ttl: {mode.upper()} {graph_uri!r}"
            f" HTTP {resp.status_code} — {resp.text[:200]}"
        )
        return {
            "ok": False,
            "graph": graph_uri,
            "triple_count": 0,
            "mode": mode,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    finally:
        if owns:
            await client.aclose()


async def drop_named_graph(
    graph_uri: str,
    client: Optional[Any] = None,
) -> bool:
    """DELETE a named graph from GraphDB.

    Returns True on 200 / 204 / 404 (graph already gone is success).
    Returns False on other HTTP errors or network failures.
    """
    if not _HTTPX_AVAILABLE:
        logger.warning("[ontology_manager] httpx not installed — cannot drop named graph")
        return False

    url = _rdf_graphs_url(graph_uri)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            resp = await client.delete(url)
        except httpx.HTTPError as exc:
            logger.warning(f"[ontology_manager] drop_named_graph: HTTP error — {exc}")
            return False

        if resp.status_code in (200, 204, 404):
            logger.info(
                f"[ontology_manager] drop_named_graph: {graph_uri!r}"
                f" HTTP {resp.status_code}"
            )
            return True

        logger.warning(
            f"[ontology_manager] drop_named_graph: {graph_uri!r}"
            f" HTTP {resp.status_code}"
        )
        return False
    finally:
        if owns:
            await client.aclose()


_EMPTY_SPARQL_RESULT: Dict[str, Any] = {
    "ok": False,
    "columns": [],
    "rows": [],
    "count": 0,
    "error": None,
}


def _first_sparql_verb(query: str) -> str:
    """Return the query's first operative SPARQL verb, or "" if none.

    A naive "first keyword match" is foolable by a verb-lookalike hidden inside a
    ``<URI>`` (Brick URIs legitimately contain ``#Sensor`` etc.), a string
    literal, or a ``PREFIX``/``BASE`` line. So neutralize those constructs FIRST
    — blanking ``<...>`` before stripping ``#`` comments, otherwise a URI's own
    ``#fragment`` would be mistaken for a comment — then scan the remaining body.
    This is defence-in-depth; the real backstop is that we POST to GraphDB's
    read-only query endpoint, which refuses updates regardless.
    """
    scrubbed = re.sub(r"<[^>]*>", "<>", query)  # URIs (incl. #fragments)
    scrubbed = re.sub(r'"[^"]*"', '""', scrubbed)  # double-quoted literals
    scrubbed = re.sub(r"'[^']*'", "''", scrubbed)  # single-quoted literals
    scrubbed = re.sub(r"#[^\n]*", "", scrubbed)  # line comments (URIs already blanked)
    scrubbed = re.sub(r"(?im)^\s*PREFIX\s+\S+\s*<>\s*", "", scrubbed)  # prefix decls
    scrubbed = re.sub(r"(?im)^\s*BASE\s*<>\s*", "", scrubbed)  # base decl
    match = _SPARQL_VERB_RE.search(scrubbed)
    return match.group(1).upper() if match else ""


async def run_sparql_select(
    query: str,
    limit: int = 100,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a SELECT or ASK SPARQL query against GraphDB (read-only browser).

    Non-SELECT / non-ASK queries are rejected immediately (no network call).
    If the query contains no LIMIT clause, ``LIMIT {limit}`` is appended.

    Returns::

        {
            "ok": bool,
            "columns": List[str],
            "rows": List[dict],
            "count": int,
            "error": Optional[str],
        }
    """
    # Detect the first operative SPARQL verb, ignoring keyword-lookalikes hidden
    # in URIs / literals / PREFIX lines (see _first_sparql_verb).
    first_verb = _first_sparql_verb(query)
    if first_verb not in ("SELECT", "ASK"):
        return {
            **_EMPTY_SPARQL_RESULT,
            "error": (
                "Only SELECT and ASK queries are permitted in the SPARQL browser."
                " Use the GraphDB workbench for data mutations."
            ),
        }

    # Auto-append LIMIT when absent (word-boundary match to avoid URI false positives).
    effective_query = query
    if not re.search(r"\bLIMIT\s+\d+", query, re.IGNORECASE):
        effective_query = f"{query.rstrip()}\nLIMIT {limit}"

    if not _HTTPX_AVAILABLE:
        logger.warning("[ontology_manager] httpx not installed — cannot run SPARQL")
        return {**_EMPTY_SPARQL_RESULT, "error": "httpx not available"}

    url = _graphdb_repo_url()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            resp = await client.post(
                url,
                content=effective_query.encode("utf-8"),
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning(f"[ontology_manager] run_sparql_select: HTTP error — {exc}")
            return {**_EMPTY_SPARQL_RESULT, "error": str(exc)}

        if resp.status_code != 200:
            return {
                **_EMPTY_SPARQL_RESULT,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()

        # ASK queries return {"head": {}, "boolean": true/false} — no bindings.
        if "boolean" in data:
            bool_val = data["boolean"]
            return {
                "ok": True,
                "columns": ["boolean"],
                "rows": [{"boolean": str(bool_val)}],
                "count": 1,
                "error": None,
            }

        vars_: List[str] = data.get("head", {}).get("vars", [])
        bindings = data.get("results", {}).get("bindings", [])

        rows: List[Dict[str, Any]] = []
        for binding in bindings:
            row = {
                var: binding[var]["value"] if var in binding else None
                for var in vars_
            }
            rows.append(row)

        return {
            "ok": True,
            "columns": vars_,
            "rows": rows,
            "count": len(rows),
            "error": None,
        }
    finally:
        if owns:
            await client.aclose()
