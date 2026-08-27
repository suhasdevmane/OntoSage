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
from pathlib import Path
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
        f"{base}/repositories/{settings.GRAPHDB_REPOSITORY}" f"/rdf-graphs/service?graph={encoded}"
    )


#: Where the repository's own configuration lives. ONE definition of what an
#: OntoSage repository is, shared with scripts/ensure_graphdb_repo.py -- two copies of
#: a repository config is how two buildings end up with different inference profiles
#: and nobody notices until a query returns different answers on each.
_REPO_CONFIG_PATHS = (
    Path("/app/config/graphdb_repo_bldg.ttl"),
    Path("config/graphdb_repo_bldg.ttl"),
)


def _repo_config_bytes() -> Optional[bytes]:
    for candidate in _REPO_CONFIG_PATHS:
        try:
            if candidate.is_file():
                return candidate.read_bytes()
        except OSError:  # pragma: no cover - unreadable path
            continue
    return None


async def ensure_repository_exists(client: Optional[Any] = None) -> bool:
    """Create the configured repository if GraphDB has none. Returns True if created.

    BUG-348: a building booted for the first time has an empty GraphDB volume, and an
    empty volume has no repository. The TTL uploader then has nowhere to put the
    ontology and ontology init retries "GraphDB is not reachable" indefinitely, while
    the orchestrator serves a building that can answer nothing. Measured on bldg4's
    first boot -- the exact path GUI onboarding puts a new building through.

    Idempotent by design: an existing repository is left untouched, so this is a no-op
    on every boot after the first, and it must never be a way to reset one.
    """
    base = settings.GRAPHDB_URL.rstrip("/")
    repo = settings.GRAPHDB_REPOSITORY
    close = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.get(f"{base}/rest/repositories")
        if resp.status_code != 200:
            raise RuntimeError(f"GraphDB listed repositories with HTTP {resp.status_code}")
        body = resp.text
        if f'"{repo}"' in body or f"/repositories/{repo}" in body:
            return False

        cfg = _repo_config_bytes()
        if cfg is None:
            raise RuntimeError("repository config not found; cannot create %r" % repo)

        created = await client.post(
            f"{base}/rest/repositories",
            files={"config": ("config.ttl", cfg, "text/turtle")},
        )
        if created.status_code not in (200, 201, 204):
            raise RuntimeError(f"create returned HTTP {created.status_code}: {created.text[:200]}")
        logger.info("[ontology_manager] created GraphDB repository %r", repo)
        return True
    finally:
        if close:
            await client.aclose()


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
                f"[ontology_manager] drop_named_graph: {graph_uri!r}" f" HTTP {resp.status_code}"
            )
            return True

        logger.warning(
            f"[ontology_manager] drop_named_graph: {graph_uri!r}" f" HTTP {resp.status_code}"
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
            row = {var: binding[var]["value"] if var in binding else None for var in vars_}
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


async def rebuild_similarity_index(client: Optional[Any] = None) -> Dict[str, Any]:
    """Rebuild the GraphDB similarity index used by the sensor RAG retriever.

    Triggers a rebuild via the SPARQL ``similarity:rebuildIndex`` predicate (a SPARQL UPDATE on the
    repository's ``/statements`` endpoint). This is deliberately NOT the ``/rest/similarity`` REST
    API — that API is disabled in this deployment (returns HTTP 405), whereas the SPARQL trigger is
    portable across GraphDB editions and verified working here.

    The index (``GRAPHDB_SIMILARITY_INDEX``) is what ``rag-service`` queries for semantic entity
    retrieval and does NOT auto-update when triples change, so newly-registered sensors only surface
    in fuzzy/semantic search after a rebuild. The index itself persists in the GraphDB data volume
    across restarts — only a rebuild (not a re-create) is needed to pick up new triples. No-op
    (``ok=True``, ``status="disabled"``) when similarity is turned off.

    Returns ``{ok, index, status, error}`` and never raises.
    """
    index = settings.GRAPHDB_SIMILARITY_INDEX
    if not getattr(settings, "GRAPHDB_USE_SIMILARITY", True):
        return {"ok": True, "index": index, "status": "disabled", "error": None}
    if not _HTTPX_AVAILABLE:
        return {"ok": False, "index": index, "status": None, "error": "httpx not available"}

    # index comes from config (not user input); guard anyway against a broken value breaking the
    # SPARQL literal — a real index name is a bare identifier.
    if any(c in index for c in ('"', "\\", "<", ">", "{", "}", " ", "\n")):
        return {"ok": False, "index": index, "status": None, "error": "invalid index name"}

    # Rebuild = DELETE + CREATE, not the in-place SPARQL ``rebuildIndex`` trigger. On this GraphDB
    # (10.7.4) the in-place trigger was observed to hang the index in REBUILDING indefinitely,
    # whereas dropping and recreating a (Lucene) text index rebuilds it cleanly in seconds over the
    # current data — which is exactly what we need to pick up newly-added triples. The brief window
    # between delete and create (a few seconds) is the only time semantic search is unavailable;
    # exact SPARQL retrieval is unaffected throughout.
    base, auth = _sim_rest_ctx()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        await _delete_similarity_index(index, base, auth, client)  # best-effort (ok if absent)
        created = await _create_similarity_index(index, base, auth, client)
        if created["ok"]:
            logger.info(f"[ontology_manager] rebuild_similarity_index: {index!r} recreated")
            return {"ok": True, "index": index, "status": "rebuilding", "error": None}
        return {"ok": False, "index": index, "status": None, "error": created["error"]}
    finally:
        if owns:
            await client.aclose()


# GraphDB similarity-plugin status values that mean a (re)build is in progress.
_SIM_IN_PROGRESS = {"BUILDING", "REBUILDING", "CREATING", "INDEXING"}

# Data query for the text similarity index: index EVERY typed IRI with rich text (label + type
# name + local name). Building-agnostic — it indexes whatever ontology is loaded, so a new
# building's sensors are covered with no edits. Mirrors rag-service/graphdbRAG/create_graphdb_index.
_SIM_DATA_QUERY = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
    "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
    "SELECT ?documentID ?documentText {\n"
    "    ?documentID rdf:type ?type .\n"
    "    FILTER(ISIRI(?documentID))\n"
    "    OPTIONAL { ?documentID rdfs:label ?label }\n"
    # Enrich the indexed text with the ontology's natural-language description so a plain-English
    # question matches the right term. Critically this makes the OCBV schema retrievable: an OCBV
    # class/property carries rdfs:comment + skos:definition/example + layTerms + competencyQuestion,
    # so a question like "the toilet is leaking, who do I tell" now matches ontosage:MaintenanceIssue
    # — and the retriever's bounded-context step then surfaces that term's example SPARQL to the LLM.
    "    OPTIONAL { ?documentID rdfs:comment ?comment }\n"
    "    OPTIONAL { ?documentID skos:definition ?definition }\n"
    "    OPTIONAL { ?documentID skos:example ?example }\n"
    "    OPTIONAL { ?documentID ontosage:layTerms ?layterms }\n"
    "    OPTIONAL { ?documentID ontosage:competencyQuestion ?cq }\n"
    '    BIND(REPLACE(STR(?type), "^.*[#/]([^#/]+)$", "$1") as ?typeName)\n'
    '    BIND(REPLACE(STR(?documentID), "^.*[#/]([^#/]+)$", "$1") as ?entityName)\n'
    '    BIND(CONCAT(COALESCE(?label, ""), " ", COALESCE(?typeName, ""), " ",\n'
    '        COALESCE(?entityName, ""), " ", COALESCE(STR(?comment), ""), " ",\n'
    '        COALESCE(STR(?definition), ""), " ", COALESCE(STR(?example), ""), " ",\n'
    '        COALESCE(STR(?layterms), ""), " ", COALESCE(STR(?cq), "")) as ?documentText)\n'
    "}"
)
_SIM_SEARCH_QUERY = "SELECT ?documentID ?documentText { ?documentID ?p ?documentText . }"


def _sim_rest_ctx() -> tuple:
    """(base_url, auth) for GraphDB REST/SPARQL similarity calls."""
    base = settings.GRAPHDB_URL.rstrip("/")
    auth = None
    if settings.GRAPHDB_USER and settings.GRAPHDB_PASSWORD:
        auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
    return base, auth


async def _delete_similarity_index(index: str, base: str, auth, client: Any) -> bool:
    """Best-effort delete of the similarity index via SPARQL ``deleteIndex`` (ok if it's absent)."""
    update = (
        "PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>\n"
        "PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>\n"
        f'INSERT DATA {{ similarity-index:{index} similarity:deleteIndex "" . }}'
    )
    url = f"{base}/repositories/{settings.GRAPHDB_REPOSITORY}/statements"
    try:
        resp = await client.post(
            url,
            content=update.encode("utf-8"),
            headers={"Content-Type": "application/sparql-update"},
            auth=auth,
        )
        return resp.status_code in (200, 204)
    except httpx.HTTPError as exc:  # pragma: no cover - network
        logger.debug(f"[ontology_manager] delete similarity index (best-effort) failed: {exc}")
        return False


async def _create_similarity_index(index: str, base: str, auth, client: Any) -> Dict[str, Any]:
    """Create the text similarity index via ``POST /rest/similarity`` (also builds it).

    Returns ``{ok, created, error}``. The correct GraphDB 10.x path is ``/rest/similarity`` — NOT
    ``/rest/similarity/indexes`` (that 405s).
    """
    body = {
        "name": index,
        "type": "text",
        "selectQuery": _SIM_DATA_QUERY,
        "searchQuery": _SIM_SEARCH_QUERY,
        "stopList": "",
        "analyzerClass": "org.apache.lucene.analysis.en.EnglishAnalyzer",
        "infer": True,
        "sameAs": True,
        "parameters": ["-termweight", "idf"],
    }
    headers = {
        "X-GraphDB-Repository": settings.GRAPHDB_REPOSITORY,
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(f"{base}/rest/similarity", json=body, headers=headers, auth=auth)
    except httpx.HTTPError as exc:
        return {"ok": False, "created": False, "error": f"create error: {exc}"}
    if resp.status_code in (200, 201):
        logger.info(f"[ontology_manager] _create_similarity_index: created {index!r}")
        return {"ok": True, "created": True, "error": None}
    return {"ok": False, "created": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


async def ensure_similarity_index(client: Optional[Any] = None) -> Dict[str, Any]:
    """Create the GraphDB text similarity index if it does not exist (idempotent).

    Uses the Workbench REST API ``POST /rest/similarity`` (NB: the ``/rest/similarity/indexes``
    path used by the old create script is wrong for GraphDB 10.x → 405). Creating the index also
    builds it. This is what makes the semantic index self-heal on a fresh GraphDB volume — no manual
    Workbench step. Returns ``{ok, index, exists, created, error}``; no-op when similarity is off.
    """
    index = settings.GRAPHDB_SIMILARITY_INDEX
    if not getattr(settings, "GRAPHDB_USE_SIMILARITY", True):
        return {"ok": True, "index": index, "exists": False, "created": False, "error": None}
    if not _HTTPX_AVAILABLE:
        return {
            "ok": False,
            "index": index,
            "exists": False,
            "created": False,
            "error": "httpx not available",
        }

    base = settings.GRAPHDB_URL.rstrip("/")
    auth = None
    if settings.GRAPHDB_USER and settings.GRAPHDB_PASSWORD:
        auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
    headers = {"X-GraphDB-Repository": settings.GRAPHDB_REPOSITORY}

    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        # List existing indexes — GET /rest/similarity returns [{"name": ...}, ...].
        try:
            listing = await client.get(
                f"{base}/rest/similarity",
                headers={**headers, "Accept": "application/json"},
                auth=auth,
            )
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "index": index,
                "exists": False,
                "created": False,
                "error": f"list error: {exc}",
            }
        if listing.status_code == 200:
            try:
                names = {i.get("name") for i in listing.json() if isinstance(i, dict)}
            except Exception:
                names = set()
            if index in names:
                return {"ok": True, "index": index, "exists": True, "created": False, "error": None}

        # Not present — create it (this also triggers the initial build).
        created = await _create_similarity_index(index, base, auth, client)
        return {
            "ok": created["ok"],
            "index": index,
            "exists": False,
            "created": created["created"],
            "error": created["error"],
        }
    finally:
        if owns:
            await client.aclose()


async def get_similarity_index_status(client: Optional[Any] = None) -> Dict[str, Any]:
    """Read the GraphDB similarity index's current status via SPARQL (read-only, non-mutating).

    GraphDB exposes it as ``<index> similarity:status ?status`` — e.g. ``REBUILDING`` while a build
    is running, ``BUILT`` when ready. Lets the admin be told, honestly, when newly-added data is
    actually searchable. Returns ``{ok, index, status, building, error}``; ``building`` is True
    while a (re)build is in progress. Never raises.
    """
    index = settings.GRAPHDB_SIMILARITY_INDEX
    if not _HTTPX_AVAILABLE:
        return {
            "ok": False,
            "index": index,
            "status": None,
            "building": False,
            "error": "httpx not available",
        }

    query = (
        "PREFIX : <http://www.ontotext.com/graphdb/similarity/>\n"
        "SELECT ?status WHERE { ?index :status ?status . "
        f'FILTER(STRENDS(STR(?index), "/{index}")) }} LIMIT 1'
    )
    url = _graphdb_repo_url()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            resp = await client.post(
                url,
                content=query.encode("utf-8"),
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
            )
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "index": index,
                "status": None,
                "building": False,
                "error": str(exc),
            }

        if resp.status_code != 200:
            return {
                "ok": False,
                "index": index,
                "status": None,
                "building": False,
                "error": f"HTTP {resp.status_code}",
            }

        bindings = resp.json().get("results", {}).get("bindings", [])
        status = bindings[0].get("status", {}).get("value") if bindings else None
        building = bool(status) and status.upper() in _SIM_IN_PROGRESS
        return {"ok": True, "index": index, "status": status, "building": building, "error": None}
    finally:
        if owns:
            await client.aclose()


async def delete_subject(
    subject_uri: str,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Delete every triple whose subject is *subject_uri* (SPARQL UPDATE via /statements).

    Scoped to a single subject — the safe primitive for removing one capability instance
    without touching any other subject. Clears the subject from BOTH the default graph and
    every named graph: the uploader loads all TTL into named graphs (``urn:ontosage:ttl:*``),
    so a bare no-GRAPH ``DELETE WHERE`` can miss them depending on GraphDB's update
    default-graph config; the ``GRAPH ?g`` form removes them deterministically regardless.
    Returns ``{"ok": bool, "subject": str, "error": Optional[str]}`` and never raises.
    """
    if not _HTTPX_AVAILABLE:
        return {"ok": False, "subject": subject_uri, "error": "httpx not available"}
    # Injection guard — a real URI has no whitespace, '>' or control chars.
    if not subject_uri or any(c in subject_uri for c in (">", "<", " ", "\n", "\r", "\t")):
        return {"ok": False, "subject": subject_uri, "error": "invalid subject URI"}

    update = (
        f"DELETE WHERE {{ <{subject_uri}> ?p ?o }};\n"
        f"DELETE WHERE {{ GRAPH ?g {{ <{subject_uri}> ?p ?o }} }}"
    )
    base = settings.GRAPHDB_URL.rstrip("/")
    url = f"{base}/repositories/{settings.GRAPHDB_REPOSITORY}/statements"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            resp = await client.post(
                url,
                content=update.encode("utf-8"),
                headers={"Content-Type": "application/sparql-update"},
            )
        except httpx.HTTPError as exc:
            logger.warning(f"[ontology_manager] delete_subject: HTTP error — {exc}")
            return {"ok": False, "subject": subject_uri, "error": str(exc)}

        if resp.status_code in (200, 204):
            logger.info(
                f"[ontology_manager] delete_subject: {subject_uri!r} HTTP {resp.status_code}"
            )
            return {"ok": True, "subject": subject_uri, "error": None}

        logger.warning(
            f"[ontology_manager] delete_subject: {subject_uri!r} HTTP {resp.status_code}"
            f" — {resp.text[:200]}"
        )
        return {"ok": False, "subject": subject_uri, "error": f"HTTP {resp.status_code}"}
    finally:
        if owns:
            await client.aclose()
