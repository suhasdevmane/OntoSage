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
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Paths / constants
# ─────────────────────────────────────────────────────────────────────────────

# Where the orchestrator looks for input TTLs (mirrors floor plan layout).
_INPUT_SEARCH_PATHS = [Path("/app/input"), Path("input")]

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

    Search rules (both honoured to support new + legacy layouts):
      - `input/<building_id>/*.ttl`        (new layout)
      - `input/<building_id>_*.ttl`         (legacy flat layout)
    Shared schema TTLs (`Brick*.ttl`, `*_schema.ttl`, etc.) at the top of
    `input/` are returned separately via `discover_schema_ttls()`.
    """
    input_dir = _resolve_input_dir()
    if input_dir is None:
        logger.debug("[ttl_uploader] no input/ directory found")
        return []

    results: List[Path] = []
    # New layout: input/<bldg>/*.ttl
    bldg_dir = input_dir / building_id
    if bldg_dir.is_dir():
        results.extend(sorted(bldg_dir.glob("*.ttl")))

    # Legacy flat layout: input/<bldg>_*.ttl
    pattern = re.compile(rf"^{re.escape(building_id)}_.*\.ttl$", re.IGNORECASE)
    for path in sorted(input_dir.glob("*.ttl")):
        if pattern.match(path.name) and not _looks_like_schema(path.name):
            results.append(path)

    return results


def discover_schema_ttls() -> List[Path]:
    """Return shared schema TTLs (Brick, REC, etc.) from the top of input/."""
    input_dir = _resolve_input_dir()
    if input_dir is None:
        return []
    return [p for p in sorted(input_dir.glob("*.ttl")) if _looks_like_schema(p.name)]


# ─────────────────────────────────────────────────────────────────────────────
# GraphDB upload
# ─────────────────────────────────────────────────────────────────────────────


async def upload_to_graphdb(
    ttl_path: Path,
    *,
    repository: Optional[str] = None,
    graphdb_url: Optional[str] = None,
    timeout: float = 120.0,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """POST a TTL file to GraphDB.  Returns True on HTTP 200/204."""
    repo = repository or settings.GRAPHDB_REPOSITORY
    base = (graphdb_url or settings.GRAPHDB_URL).rstrip("/")
    url = f"{base}/repositories/{repo}/statements"
    ttl_bytes = ttl_path.read_bytes()

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        try:
            resp = await client.post(
                url,
                content=ttl_bytes,
                headers={"Content-Type": "application/x-turtle"},
            )
        except httpx.HTTPError as e:
            logger.warning(
                f"[ttl_uploader] {ttl_path.name}: HTTP error talking to GraphDB — {e}"
            )
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
                logger.info(
                    f"[ttl_uploader] {path.name} uploaded (sha={sha[:12]}...)"
                )
                summary["uploaded"].append(key)
            else:
                summary["failed"].append(key)

    if own_cache:
        save_cache(cache)

    logger.info(
        f"[ttl_uploader] done — uploaded={len(summary['uploaded'])} "
        f"skipped={len(summary['skipped'])} failed={len(summary['failed'])}"
    )
    return summary
