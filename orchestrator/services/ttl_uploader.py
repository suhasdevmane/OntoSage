"""
ttl_uploader.py — Idempotent TTL ingestion at orchestrator startup.

Phase 3 (production hardening): when the orchestrator boots, scan `input/`
for TTL files belonging to the active buildings and POST them to GraphDB.

Design properties
-----------------
1. **Idempotent** — SHA-256 fingerprint cached in
   `volumes/artifacts/.ttl_uploads.json`.  Unchanged files are skipped (no
   network call).  This mirrors the floor-plan pipeline pattern.

2. **Non-fatal** — any upload failure logs a warning but never blocks
   startup.  Operators can fix GraphDB connectivity later without taking
   the orchestrator down.

3. **Layout-flexible** — finds TTLs under both new (`input/<bldg>/*.ttl`)
   and legacy (`input/<bldg>_*.ttl`) layouts.

4. **Schema-aware** — TTLs prefixed `Brick`, `brick`, `rec`, `s223`, or
   matching `*_schema.ttl` are uploaded once into the shared `<repo>`
   repository.  Per-building TTLs go into the same repo (current
   single-repo deployment) but the design keeps room for future per-bldg
   repos.

Usage:
    from orchestrator.services.ttl_uploader import run_idempotent_uploads
    await run_idempotent_uploads(building_ids=["bldg1"])
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Paths / constants
# ─────────────────────────────────────────────────────────────────────────────

# Where the orchestrator looks for input TTLs (mirrors floor plan layout).
_INPUT_SEARCH_PATHS = [Path("/app/input"), Path("input")]

# Additional directories scanned for building-independent ontology TTLs
# (e.g. ontology/hbco_core.ttl).  These are treated as schema files.
_ONTOLOGY_SEARCH_PATHS = [Path("/app/ontology"), Path("ontology")]

# Where the SHA-256 cache lives.  Same volume as artifacts so it survives
# container restarts.
_CACHE_SEARCH_PATHS = [
    Path("/app/volumes/artifacts/.ttl_uploads.json"),
    Path("volumes/artifacts/.ttl_uploads.json"),
]

# Filenames containing any of these tokens are treated as shared schema
# (uploaded once even if multiple buildings reference them).
_SHARED_SCHEMA_TOKENS = ("brick", "rec", "s223", "schema")


# ─────────────────────────────────────────────────────────────────────────────
# Filesystem helpers
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_input_dir() -> Optional[Path]:
    """Return the first existing path from _INPUT_SEARCH_PATHS, or None."""
    for p in _INPUT_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _resolve_cache_path() -> Path:
    """Pick a cache path that lives under a writable parent dir.

    Falls back to the first candidate even if the parent does not exist so
    the caller can create it on save.
    """
    for p in _CACHE_SEARCH_PATHS:
        if p.parent.exists():
            return p
    return _CACHE_SEARCH_PATHS[0]


def compute_sha(path: Path) -> str:
    """Return SHA-256 hex digest of a file's content."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache() -> Dict[str, str]:
    """Read the SHA cache from disk.  Returns {} if missing or unreadable."""
    cache_path = _resolve_cache_path()
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        logger.warning(f"[ttl_uploader] cache at {cache_path} is not a dict — ignoring")
    except Exception as e:
        logger.warning(f"[ttl_uploader] failed to read cache {cache_path}: {e}")
    return {}


def save_cache(cache: Dict[str, str]) -> None:
    """Persist the SHA cache to disk.  Failures log a warning and continue."""
    cache_path = _resolve_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, sort_keys=True)
    except Exception as e:
        logger.warning(f"[ttl_uploader] failed to persist cache {cache_path}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TTL discovery
# ─────────────────────────────────────────────────────────────────────────────


def _looks_like_schema(name: str) -> bool:
    """Heuristic: is this TTL a shared schema (Brick / REC / s223 / *_schema)?"""
    lower = name.lower()
    return any(tok in lower for tok in _SHARED_SCHEMA_TOKENS)


def discover_ttls(building_id: str) -> List[Path]:
    """Return TTL files belonging to a building.

    Search rules:
      - New/nested layout: **every** ``input/<building_id>/*.ttl``.
      - Flat layout (canonical, one active building): **every** top-level
        ``input/*.ttl`` that is not a shared schema — regardless of filename.

    The flat rule is deliberately name-agnostic: the documented invariant is
    that the active building's files sit directly under ``input/`` (see
    CLAUDE.md), so any TTL an operator drops there is loaded — you do NOT have
    to prefix it ``<building_id>_``. This makes "use the input folder as-is,
    all TTL files considered" true even for arbitrarily-named files (e.g.
    ``equipment_linkage.ttl``). Shared schema TTLs (``Brick*.ttl``,
    ``*_schema.ttl``, REC / s223) are handled once by
    :func:`discover_schema_ttls` and excluded here to avoid a double-add.
    """
    input_dir = _resolve_input_dir()
    if input_dir is None:
        logger.debug("[ttl_uploader] no input/ directory found")
        return []

    results: List[Path] = []
    # New layout: input/<bldg>/*.ttl — load all TTLs in the building's own dir.
    bldg_dir = input_dir / building_id
    if bldg_dir.is_dir():
        results.extend(sorted(bldg_dir.glob("*.ttl")))

    # Flat layout: load every top-level input/*.ttl that is not a shared schema.
    # NB single-building invariant (CLAUDE.md contract #1): v1 serves ONE active building,
    # which owns every flat input/*.ttl regardless of filename (FIX-019). The building_id
    # arg is therefore not a filename filter here — do NOT add one, or arbitrarily-named
    # building TTLs (e.g. equipment_linkage.ttl) get silently skipped on a clean load again.
    # A SECOND building's TTLs must NOT be staged in the flat root (they would cross-load
    # into the single repo); use the nested layout input/<other_id>/*.ttl for that.
    for path in sorted(input_dir.glob("*.ttl")):
        if not _looks_like_schema(path.name):
            results.append(path)

    return results


def discover_schema_ttls() -> List[Path]:
    """Return shared schema TTLs (Brick, REC, etc.) from input/ and ontology/."""
    results: List[Path] = []
    input_dir = _resolve_input_dir()
    if input_dir is not None:
        results.extend(p for p in sorted(input_dir.glob("*.ttl")) if _looks_like_schema(p.name))
    # Include all TTLs under ontology/ directories (all are schema-level)
    for onto_dir in _ONTOLOGY_SEARCH_PATHS:
        if onto_dir.is_dir():
            results.extend(sorted(onto_dir.glob("*.ttl")))
            break
    return results


# ─────────────────────────────────────────────────────────────────────────────
# GraphDB upload
# ─────────────────────────────────────────────────────────────────────────────


def _graph_uri_for_path(ttl_path: Path) -> str:
    """Deterministic named-graph URI for a TTL file.

    Using the file name as the key means the same file always lands in the
    same named graph, so a PUT replaces previous triples rather than appending
    them.  This eliminates blank-node duplication on repeated uploads.
    """
    safe = ttl_path.name.replace(" ", "_")
    return f"urn:ontosage:ttl:{safe}"


async def upload_to_graphdb(
    ttl_path: Path,
    *,
    repository: Optional[str] = None,
    graphdb_url: Optional[str] = None,
    timeout: float = 120.0,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """PUT a TTL file into a per-file named graph in GraphDB.

    Using PUT with ``?context=<graph>`` instead of a bare POST replaces all
    triples in the named graph atomically — preventing blank-node duplication
    on repeated startups even when the SHA cache is cold (e.g. after a volume
    reset).  Returns True on HTTP 200/204.
    """
    repo = repository or settings.GRAPHDB_REPOSITORY
    base = (graphdb_url or settings.GRAPHDB_URL).rstrip("/")
    graph_uri = _graph_uri_for_path(ttl_path)
    # Percent-encode the whole <graph> token: a literal '+' in a filename would
    # otherwise be decoded as a space by GraphDB → "Invalid IRI value" (HTTP 500).
    encoded_graph = quote(f"<{graph_uri}>", safe="")
    url = f"{base}/repositories/{repo}/statements?context={encoded_graph}"
    ttl_bytes = ttl_path.read_bytes()

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        try:
            resp = await client.put(
                url,
                content=ttl_bytes,
                headers={"Content-Type": "application/x-turtle"},
            )
        except httpx.HTTPError as e:
            logger.warning(f"[ttl_uploader] {ttl_path.name}: HTTP error talking to GraphDB — {e}")
            return False
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code in (200, 204):
        return True
    logger.warning(
        f"[ttl_uploader] {ttl_path.name}: upload failed HTTP {resp.status_code} "
        f"— {resp.text[:300]}"
    )
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────


async def audit_undeclared_types(sample: int = 5) -> Dict[str, Any]:
    """Report instances typed with a class NOTHING declares (TODO-181/BUG-203).

    Two failure modes meet here, and neither announces itself.

    A TTL can mint a type into a namespace that does not define it —
    ``brick:Sound_Level_Sensor``, where Brick 1.4 has no acoustic class at all.
    Queries still work, because matching is on the LOCAL name, so a
    non-conformant graph behaves exactly like a correct one and nothing
    complains. And separately, a triple that reached the DEFAULT graph is immune
    to every later correction: each TTL is published with
    ``PUT ?context=<named graph>``, which replaces that graph and cannot touch
    anything outside it, so the file gets fixed, the upload reports success, and
    the graph keeps answering from the old copy (BUG-194 was a policy shadowed
    this way; TODO-181 left 52 subjects carrying BOTH the old and the new type).

    An undeclared type is the symptom both produce, and unlike a raw
    default-graph count it does not drown in inference: reasoning materialises
    superclass types like ``brick:Sensor`` and Brick's own SHACL vocabulary
    outside every named graph by the million, none of which is a defect. Asking
    "is anything typed with a class that has no definition?" returned exactly
    the 56 real instances and nothing else.

    Read-only and non-fatal — a failed audit must never block startup.
    """
    from shared.config import settings as _s

    # Scope: the namespaces THIS system mints into. Third-party vocabulary is
    # out of scope by design — SHACL terms (sh:TripleRule and friends) are not
    # declared as owl:Class in this repository and would otherwise contribute
    # over a million "findings", burying the handful that mean something. A
    # guard nobody can act on is worse than no guard (lessons.md #20).
    owned = [
        "https://brickschema.org/schema/Brick#",
        "http://ontosage.org/capabilities#",
    ]
    building_ns = (getattr(_s, "BUILDING_NAMESPACE", "") or "").strip()
    if building_ns:
        owned.append(building_ns)
    ns_filter = " || ".join(f'STRSTARTS(STR(?t), "{ns}")' for ns in owned)
    query = (
        "PREFIX owl: <http://www.w3.org/2002/07/owl#> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?t (COUNT(?s) AS ?n) WHERE { "
        "  ?s a ?t . "
        "  FILTER(isIRI(?t)) "
        f"  FILTER({ns_filter}) "
        "  FILTER NOT EXISTS { ?t a owl:Class } "
        "  FILTER NOT EXISTS { ?t a rdfs:Class } "
        "  FILTER NOT EXISTS { ?t rdfs:subClassOf ?parent } "
        "} GROUP BY ?t ORDER BY DESC(?n)"
    )
    result: Dict[str, Any] = {"undeclared_types": 0, "instances": 0, "top": []}
    try:
        base = _s.GRAPHDB_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/repositories/{_s.GRAPHDB_REPOSITORY}",
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
                content=query,
            )
        if resp.status_code != 200:
            logger.warning(f"[ttl_uploader] type audit skipped: HTTP {resp.status_code}")
            return result
        bindings = resp.json().get("results", {}).get("bindings", [])
    except Exception as exc:
        logger.warning(f"[ttl_uploader] type audit skipped: {exc}")
        return result

    rows = []
    for item in bindings:
        try:
            rows.append((item["t"]["value"], int(item["n"]["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    result["undeclared_types"] = len(rows)
    result["instances"] = sum(n for _, n in rows)
    result["top"] = [{"type": ty, "count": n} for ty, n in rows[:sample]]

    if rows:
        preview = ", ".join(f"{ty.rsplit('#')[-1]} x{n}" for ty, n in rows[:sample])
        logger.warning(
            f"[ttl_uploader] type audit: {result['instances']} instance(s) carry "
            f"{len(rows)} type(s) that NOTHING declares — queries still work "
            f"(local-name matching) but the graph is non-conformant. If a TTL fix "
            f"did not clear it, the triples are in the DEFAULT graph and need a "
            f"scoped SPARQL DELETE (BUG-203). Top: {preview}"
        )
    else:
        logger.info("[ttl_uploader] type audit clean — every instance carries a declared class")
    return result


async def run_idempotent_uploads(
    building_ids: Iterable[str],
    *,
    include_schemas: bool = True,
    cache: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Scan input/ for TTLs and upload any that changed since last boot.

    Parameters
    ----------
    building_ids
        Buildings to ingest (typically `building_registry.building_ids()`).
    include_schemas
        When True, also (re)upload shared schemas if their SHA changed.
    cache
        Inject a custom cache for testing.  Defaults to the persisted on-disk
        cache.

    Returns a summary dict suitable for structured logging:
        {
            "uploaded": [path, ...],
            "skipped":  [path, ...],
            "failed":   [path, ...],
        }
    """
    summary: Dict[str, Any] = {"uploaded": [], "skipped": [], "failed": []}

    own_cache = cache is None
    if own_cache:
        cache = load_cache()

    # Build the work list (de-duped).
    paths: List[Path] = []
    seen: set = set()
    if include_schemas:
        for p in discover_schema_ttls():
            if p not in seen:
                paths.append(p)
                seen.add(p)
    for bid in building_ids:
        for p in discover_ttls(bid):
            if p not in seen:
                paths.append(p)
                seen.add(p)

    if not paths:
        logger.info("[ttl_uploader] no TTL files discovered — nothing to do")
        return summary

    logger.info(f"[ttl_uploader] discovered {len(paths)} TTL file(s) to evaluate")

    async with httpx.AsyncClient(timeout=120.0) as client:
        for path in paths:
            try:
                sha = compute_sha(path)
            except OSError as e:
                logger.warning(f"[ttl_uploader] could not hash {path}: {e}")
                summary["failed"].append(str(path))
                continue

            key = str(path)
            if cache.get(key) == sha:
                logger.info(f"[ttl_uploader] {path.name} unchanged — skipping")
                summary["skipped"].append(key)
                continue

            ok = await upload_to_graphdb(path, client=client)
            if ok:
                cache[key] = sha
                logger.info(f"[ttl_uploader] {path.name} uploaded (sha={sha[:12]}...)")
                summary["uploaded"].append(key)
            else:
                summary["failed"].append(key)

    if own_cache:
        save_cache(cache)

    logger.info(
        f"[ttl_uploader] done — uploaded={len(summary['uploaded'])} "
        f"skipped={len(summary['skipped'])} failed={len(summary['failed'])}"
    )
    # State the position on what this upload could NOT have fixed.
    summary["type_audit"] = await audit_undeclared_types()
    return summary
