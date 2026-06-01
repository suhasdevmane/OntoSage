"""
BuildingContextResolver — Phase 10 foundation for per-request multi-tenant.

Today most agents read `settings.BUILDING_NAME`, `settings.BUILDING_NAMESPACE`,
`settings.BUILDING_PREFIX` directly.  Those are PROCESS-global, set from the
single active `BUILDING_ID` at startup.

For one orchestrator to serve multiple buildings concurrently (the explicit
goal stated by the user), every agent must look up these strings per request,
using the `state.building_id` carried with each ConversationState.

This module provides the lookup.  It is purely additive — no agent uses it
yet.  Future sessions migrate callers incrementally:

    # Before (process-global):
    namespace = settings.BUILDING_NAMESPACE

    # After (per-request):
    from orchestrator.services.building_context import resolve_building_context
    bctx = resolve_building_context(state.building_id)
    namespace = bctx.namespace

The resolver caches per-building-id to amortize YAML reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class BuildingContext:
    """Per-building config that callers actually need at request time.

    Fields are the ones currently read from `settings.*` by SPARQL, document,
    report, and dialogue agents.  Adding fields here is forward-compatible —
    legacy callers ignore new ones.
    """

    building_id: str           # canonical id (e.g. "bldg1")
    name: str                  # human-readable (e.g. "Abacws Building")
    namespace: str             # SPARQL ABox namespace (must end in '#' or '/')
    prefix: str                # short SPARQL prefix (e.g. "bldg")
    timezone: str              # IANA tz name for time-range parsing


# ─────────────────────────────────────────────────────────────────────────────
# Loader — searches input/<bldg>/building.yaml, then falls back to settings
# ─────────────────────────────────────────────────────────────────────────────


def _load_building_yaml(building_id: str) -> Optional[dict]:
    """Try to read input/<building_id>/building.yaml.  Returns None if absent."""
    for base in (Path("/app/input"), Path("input")):
        p = base / building_id / "building.yaml"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    return yaml.safe_load(fh) or {}
            except Exception as e:
                logger.warning(f"[building_context] failed to load {p}: {e}")
                return None
    return None


def _settings_fallback() -> dict:
    """Read the active building's identity from settings as a fallback."""
    from shared.config import settings
    return {
        "building_id": settings.BUILDING_ID,
        "building_name": settings.BUILDING_NAME,
        "ontology_namespace": settings.BUILDING_NAMESPACE,
        "building_prefix": settings.BUILDING_PREFIX,
        "building_timezone": settings.BUILDING_TIMEZONE,
    }


@lru_cache(maxsize=32)
def resolve_building_context(building_id: Optional[str]) -> BuildingContext:
    """Return a BuildingContext for the given building_id.

    Resolution order:
      1. `input/<building_id>/building.yaml` — per-building YAML
      2. `settings.*` — process-global fallback (the active building)

    Lookup is cached so repeated calls for the same building_id are free.
    """
    from shared.config import settings

    bid = building_id or settings.BUILDING_ID

    yaml_data = _load_building_yaml(bid)

    # The canonical building_id is what the CALLER asked for — even if no
    # YAML exists for it.  Per-request multi-tenant means we don't silently
    # rewrite the id to the active settings building.
    if yaml_data and yaml_data.get("building_id"):
        canonical_id = yaml_data["building_id"]
    else:
        canonical_id = bid

    # For the other fields, prefer YAML, then fall back to settings.  This
    # gives sensible defaults (active building's name) when the requested
    # building has only a partial YAML or none at all.
    yaml_data = yaml_data or {}
    return BuildingContext(
        building_id=canonical_id,
        name=yaml_data.get("building_name") or settings.BUILDING_NAME,
        namespace=(
            yaml_data.get("ontology_namespace")
            or yaml_data.get("namespace")
            or settings.BUILDING_NAMESPACE
        ),
        prefix=yaml_data.get("building_prefix") or settings.BUILDING_PREFIX,
        timezone=yaml_data.get("building_timezone") or settings.BUILDING_TIMEZONE,
    )


def clear_cache() -> None:
    """Drop the cached resolutions (e.g. after live config edit)."""
    resolve_building_context.cache_clear()
