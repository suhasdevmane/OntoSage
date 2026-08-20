"""
Capture §17.1 pre-flight baseline artefacts for the capability semantic routing
migration.

Snapshots taken (all read-only, no orchestrator interaction):
  - Qdrant /collections — proves existing collections (floor_plans, agent_memory)
    are present and intact BEFORE the indexer creates capability_<bldg>
  - GraphDB /rest/repositories — proves the ontology repository state pre-migration
  - docker-compose ps — service health snapshot
  - The directory layout of orchestrator/ and shared/ (file sha-256 fingerprints)
    so any silent file change is detectable after the refactor lands

Writes to:  tests/baselines/phase1_pre_flag_<YYYYMMDD_HHMM>/

Usage:
    python scripts/capture_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import urllib.request
import urllib.error


ROOT = Path(__file__).resolve().parent.parent
QDRANT_URL = "http://localhost:6333"
GRAPHDB_URL = "http://localhost:7200"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M")
OUT_DIR = ROOT / "tests" / "baselines" / f"phase1_pre_flag_{TIMESTAMP}"


def _fetch(url: str, timeout: int = 10):
    """GET a URL, return (status, body_text)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return None, f"ERROR: {e}"


def _save(name: str, content: str):
    path = OUT_DIR / name
    path.write_text(content, encoding="utf-8")
    print(f"  [saved] {path.relative_to(ROOT)}")


def capture_qdrant():
    print("[qdrant] snapshotting collections...")
    status, body = _fetch(f"{QDRANT_URL}/collections")
    if status == 200:
        # Pretty-print
        try:
            data = json.loads(body)
            _save("qdrant_collections.json", json.dumps(data, indent=2))
            # Per-collection detail
            for col in data.get("result", {}).get("collections", []):
                name = col["name"]
                s, b = _fetch(f"{QDRANT_URL}/collections/{name}")
                if s == 200:
                    _save(f"qdrant_collection_{name}.json", json.dumps(json.loads(b), indent=2))
        except json.JSONDecodeError:
            _save("qdrant_collections.json", body)
    else:
        _save("qdrant_collections.json", f"# fetch failed: status={status}\n{body}")


def capture_graphdb():
    print("[graphdb] snapshotting repositories...")
    status, body = _fetch(f"{GRAPHDB_URL}/rest/repositories")
    if status == 200:
        _save("graphdb_repositories.json", body)
    else:
        _save("graphdb_repositories.json", f"# fetch failed: status={status}\n{body}")


def capture_docker():
    print("[docker] snapshotting container state...")
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            _save("docker_compose_ps.json", result.stdout)
        else:
            _save("docker_compose_ps.json", f"# command failed: {result.stderr}")
    except Exception as e:
        _save("docker_compose_ps.json", f"# error: {e}")


def capture_file_fingerprints():
    """SHA-256 of every .py file in orchestrator/ and shared/ as a structural snapshot.
    Any silent change to a code file after this point can be diffed against this baseline.
    """
    print("[code] fingerprinting orchestrator/ and shared/ ...")
    targets = sorted(
        list((ROOT / "orchestrator").rglob("*.py")) + list((ROOT / "shared").rglob("*.py"))
    )
    fingerprints = {}
    for path in targets:
        rel = path.relative_to(ROOT).as_posix()
        try:
            h = hashlib.sha256(path.read_bytes()).hexdigest()
            fingerprints[rel] = h
        except Exception as e:
            fingerprints[rel] = f"ERROR: {e}"
    _save("code_fingerprints.json", json.dumps(fingerprints, indent=2, sort_keys=True))


def capture_settings():
    """Snapshot the currently-loaded settings (provider, flag, etc.) so we know
    the EXACT runtime config at the time the baseline was captured."""
    print("[settings] snapshotting active configuration...")
    try:
        from shared.config import settings

        snap = {
            "MODEL_PROVIDER": settings.MODEL_PROVIDER,
            "EMBEDDING_PROVIDER": settings.EMBEDDING_PROVIDER,
            "EMBEDDING_MODEL_OPENAI": settings.EMBEDDING_MODEL_OPENAI,
            "EMBEDDING_MODEL_LOCAL": settings.EMBEDDING_MODEL_LOCAL,
            "EMBEDDING_DIMENSION_OPENAI": settings.EMBEDDING_DIMENSION_OPENAI,
            "EMBEDDING_DIMENSION_LOCAL": settings.EMBEDDING_DIMENSION_LOCAL,
            "CAPABILITY_SEMANTIC_ROUTING_ENABLED": settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED,
            "EMBEDDING_CACHE_TTL_SECONDS": settings.EMBEDDING_CACHE_TTL_SECONDS,
            "RBAC_ENABLED": settings.RBAC_ENABLED,
            "RESPONSE_CACHE_ENABLED": settings.RESPONSE_CACHE_ENABLED,
            "captured_at": datetime.now().isoformat(),
        }
        _save("settings_snapshot.json", json.dumps(snap, indent=2))
    except Exception as e:
        _save("settings_snapshot.json", f"# import failed: {e}")


def write_manifest():
    """Index of what's in this baseline directory."""
    manifest = {
        "timestamp": TIMESTAMP,
        "captured_at": datetime.now().isoformat(),
        "purpose": "Phase 1 pre-flag baseline for capability semantic routing migration",
        "spec_section": "17.1 (pre-flight)",
        "files": sorted(p.name for p in OUT_DIR.glob("*")),
    }
    _save("MANIFEST.json", json.dumps(manifest, indent=2))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Capturing pre-flight baseline -> {OUT_DIR}")
    print("-" * 70)
    capture_qdrant()
    capture_graphdb()
    capture_docker()
    capture_file_fingerprints()
    capture_settings()
    write_manifest()
    print("-" * 70)
    print(f"Done. Files in {OUT_DIR.relative_to(ROOT)}/")
    for p in sorted(OUT_DIR.glob("*")):
        size_kb = p.stat().st_size / 1024
        print(f"  {p.name:<35s} {size_kb:>8.1f} KB")


if __name__ == "__main__":
    main()
