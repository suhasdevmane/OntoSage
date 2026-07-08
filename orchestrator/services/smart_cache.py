"""
Phase 6.3 — Smart Cache Invalidation Service
=============================================
Extends the Redis-based caching layer with intelligent, event-driven
invalidation strategies instead of time-based TTL expiry only.

Strategies:
  1. Event-based — Invalidate when ontology file changes (inotify/polling)
  2. Data-staleness — Invalidate sensor result caches after N new readings
  3. Dependency-graph — Invalidate downstream caches when upstream data changes
  4. Selective — Target only the affected sensor/zone prefix, not the whole cache
  5. TTL + freshness hybrid — Keep TTL as a safety net but allow early invalidation

Key classes:
  CacheKeyRegistry   — Tracks which cache keys exist and their dependencies
  SmartCacheManager  — Orchestrates invalidation strategies
  OntologyChangeWatcher — Polls TTL files and fires invalidation on change

Usage:
    from orchestrator.services.smart_cache import SmartCacheManager

    cache = SmartCacheManager(redis_client)
    await cache.invalidate_on_data_change(sensor_uuid="uuid-temp-101")
    await cache.invalidate_on_ontology_change()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TTL = 300  # seconds (default cache lifetime)
SENSOR_CACHE_TTL = 60  # sensor result caches (more volatile)
METADATA_CACHE_TTL = 3600  # ontology/metadata caches (very stable)
STALENESS_THRESHOLD = 100  # new readings before sensor cache invalidated

# Redis key namespaces
NS_SPARQL = "sparql_cache:"
NS_SQL = "sql_cache:"
NS_SENSOR = "sensor_map:"
NS_COMMUNITY = "community_rag:"
NS_ALL = [NS_SPARQL, NS_SQL, NS_SENSOR, NS_COMMUNITY]

# ─────────────────────────────────────────────────────────────────────────────
# Dependency graph (which keys depend on which facts)
# ─────────────────────────────────────────────────────────────────────────────


class CacheKeyRegistry:
    """Tracks active cache keys and their dependency relationships."""

    def __init__(self):
        self._key_deps: Dict[str, Set[str]] = {}  # cache_key → set of fact_keys
        self._fact_keys: Dict[str, Set[str]] = {}  # fact_key  → set of cache_keys

    def register(self, cache_key: str, depends_on: List[str]):
        """Register a cache key and the fact-keys it depends on."""
        self._key_deps[cache_key] = set(depends_on)
        for fact in depends_on:
            self._fact_keys.setdefault(fact, set()).add(cache_key)

    def get_dependent_caches(self, fact_key: str) -> Set[str]:
        """Return cache keys that must be invalidated when fact_key changes."""
        return self._fact_keys.get(fact_key, set()).copy()

    def remove(self, cache_key: str):
        """Remove a cache key from the registry."""
        deps = self._key_deps.pop(cache_key, set())
        for fact in deps:
            self._fact_keys.get(fact, set()).discard(cache_key)

    def __len__(self):
        return len(self._key_deps)


# ─────────────────────────────────────────────────────────────────────────────
# Ontology change watcher
# ─────────────────────────────────────────────────────────────────────────────


class OntologyChangeWatcher:
    """Poll TTL files for changes and fire callbacks on modification."""

    def __init__(self, watch_paths: List[str], poll_interval_s: float = 30.0):
        self._paths = [Path(p) for p in watch_paths if os.path.exists(p)]
        self._poll_s = poll_interval_s
        self._mtimes: Dict[str, float] = {}
        self._hashes: Dict[str, str] = {}
        self._callbacks: List[Callable[[str], Any]] = []
        self._running = False

    def on_change(self, callback: Callable[[str], Any]):
        """Register a callback invoked with the changed file path."""
        self._callbacks.append(callback)

    def _file_hash(self, path: Path) -> str:
        try:
            return hashlib.md5(  # non-security: file content fingerprint for cache
                path.read_bytes(), usedforsecurity=False
            ).hexdigest()
        except Exception:
            return ""

    async def start(self):
        """Start polling in background."""
        self._running = True
        # Initialise baselines
        for p in self._paths:
            self._mtimes[str(p)] = p.stat().st_mtime if p.exists() else 0
            self._hashes[str(p)] = self._file_hash(p)
        logger.info(f"OntologyChangeWatcher: monitoring {len(self._paths)} file(s)")
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        while self._running:
            await asyncio.sleep(self._poll_s)
            for p in self._paths:
                key = str(p)
                if not p.exists():
                    continue
                new_mtime = p.stat().st_mtime
                if new_mtime != self._mtimes.get(key, 0):
                    new_hash = self._file_hash(p)
                    if new_hash != self._hashes.get(key, ""):
                        self._mtimes[key] = new_mtime
                        self._hashes[key] = new_hash
                        logger.info(f"Ontology change detected: {p}")
                        for cb in self._callbacks:
                            try:
                                result = cb(key)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                logger.error(f"Ontology change callback error: {e}")

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
# Smart Cache Manager
# ─────────────────────────────────────────────────────────────────────────────


class SmartCacheManager:
    """
    Orchestrates intelligent cache invalidation on top of Redis.

    Supports:
      - Whole-namespace flush (flush all SPARQL / sensor-map caches)
      - Selective sensor invalidation (only keys containing a UUID)
      - Ontology-change invalidation (TTL file hash changed)
      - Data-staleness tracking (N new rows → invalidate that sensor's cache)
      - Dependency-graph invalidation
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._registry = CacheKeyRegistry()
        self._staleness_counters: Dict[str, int] = {}  # uuid → new row count
        self._invalidation_log: List[Dict] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Core helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _delete_keys(self, keys: List[str], reason: str):
        """Delete keys from Redis and log the event."""
        if not keys:
            return
        if self._redis:
            try:
                await self._redis.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")
        event = {
            "timestamp": time.time(),
            "reason": reason,
            "keys_invalidated": len(keys),
            "sample": keys[:3],
        }
        self._invalidation_log.append(event)
        logger.info(f"Cache invalidation ({reason}): {len(keys)} keys removed")

    async def _scan_keys(self, pattern: str) -> List[str]:
        """Scan Redis for keys matching pattern."""
        if not self._redis:
            return []
        try:
            keys = []
            cursor = 0
            while True:
                cursor, batch = await self._redis.scan(cursor, match=pattern, count=100)
                keys.extend([k.decode() if isinstance(k, bytes) else k for k in batch])
                if cursor == 0:
                    break
            return keys
        except Exception as e:
            logger.warning(f"Redis scan failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 1: Namespace flush
    # ─────────────────────────────────────────────────────────────────────────

    async def invalidate_namespace(self, namespace: str, reason: str = "namespace_flush"):
        """Flush all keys under a cache namespace (e.g. 'sparql_cache:')."""
        keys = await self._scan_keys(f"{namespace}*")
        await self._delete_keys(keys, reason)
        return len(keys)

    async def invalidate_all_sparql(self):
        """Invalidate all SPARQL query caches."""
        return await self.invalidate_namespace(NS_SPARQL, "sparql_full_flush")

    async def invalidate_sensor_map(self):
        """Invalidate sensor map cache (triggers full re-discovery)."""
        return await self.invalidate_namespace(NS_SENSOR, "sensor_map_flush")

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 2: Selective sensor invalidation
    # ─────────────────────────────────────────────────────────────────────────

    async def invalidate_for_sensor(self, sensor_uuid: str):
        """
        Invalidate only cache keys that contain a specific sensor UUID.
        Avoids flushing the entire cache on a single-sensor change.
        """
        affected = []
        for ns in [NS_SPARQL, NS_SQL]:
            keys = await self._scan_keys(f"{ns}*{sensor_uuid}*")
            affected.extend(keys)
        await self._delete_keys(affected, f"sensor_selective:{sensor_uuid[:8]}")
        return len(affected)

    async def invalidate_for_zone(self, zone_label: str):
        """Invalidate caches containing a zone or floor name."""
        pattern_key = zone_label.lower().replace(" ", "_")
        affected = []
        for ns in NS_ALL:
            keys = await self._scan_keys(f"{ns}*{pattern_key}*")
            affected.extend(keys)
        await self._delete_keys(affected, f"zone_selective:{zone_label}")
        return len(affected)

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 3: Ontology change invalidation
    # ─────────────────────────────────────────────────────────────────────────

    async def invalidate_on_ontology_change(self, changed_file: str = ""):
        """
        Called when an ontology TTL file changes.
        Flushes SPARQL + sensor map caches (metadata is now stale).
        SQL/analytics caches are unaffected (time-series data unchanged).
        """
        logger.info(f"Ontology change trigger: {changed_file}")
        sparql_count = await self.invalidate_namespace(NS_SPARQL, "ontology_change")
        sensor_count = await self.invalidate_namespace(NS_SENSOR, "ontology_change")
        return {"sparql_flushed": sparql_count, "sensor_map_flushed": sensor_count}

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 4: Data staleness tracking
    # ─────────────────────────────────────────────────────────────────────────

    async def on_new_readings(self, sensor_uuid: str, n_new_rows: int):
        """
        Called by the ingestion pipeline when new sensor readings arrive.
        If cumulative new rows exceed STALENESS_THRESHOLD, the sensor's
        SQL cache is considered stale and is invalidated.
        """
        self._staleness_counters[sensor_uuid] = (
            self._staleness_counters.get(sensor_uuid, 0) + n_new_rows
        )

        if self._staleness_counters[sensor_uuid] >= STALENESS_THRESHOLD:
            logger.info(f"Staleness threshold reached for {sensor_uuid} — invalidating")
            count = await self.invalidate_for_sensor(sensor_uuid)
            self._staleness_counters[sensor_uuid] = 0
            return count
        return 0

    # ─────────────────────────────────────────────────────────────────────────
    # Strategy 5: Dependency-graph invalidation
    # ─────────────────────────────────────────────────────────────────────────

    def register_dependency(self, cache_key: str, depends_on: List[str]):
        """Register that cache_key should be invalidated when any fact in depends_on changes."""
        self._registry.register(cache_key, depends_on)

    async def invalidate_dependents(self, fact_key: str):
        """Invalidate all cache keys that depend on fact_key."""
        dependent_keys = list(self._registry.get_dependent_caches(fact_key))
        await self._delete_keys(dependent_keys, f"dependency:{fact_key}")
        for k in dependent_keys:
            self._registry.remove(k)
        return len(dependent_keys)

    # ─────────────────────────────────────────────────────────────────────────
    # Cache set/get helpers (with auto-registration)
    # ─────────────────────────────────────────────────────────────────────────

    async def set(
        self, key: str, value: str, ttl: int = DEFAULT_TTL, depends_on: Optional[List[str]] = None
    ):
        """Set a value in Redis with smart TTL and optional dependency registration."""
        if self._redis:
            try:
                await self._redis.setex(key, ttl, value)
            except Exception as e:
                logger.warning(f"Cache set failed: {e}")
        if depends_on:
            self.register_dependency(key, depends_on)

    async def get(self, key: str) -> Optional[str]:
        """Get a value from Redis."""
        if not self._redis:
            return None
        try:
            val = await self._redis.get(key)
            return val.decode() if isinstance(val, bytes) else val
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Observability
    # ─────────────────────────────────────────────────────────────────────────

    def get_invalidation_log(self) -> List[Dict]:
        return list(self._invalidation_log)

    def get_staleness_status(self) -> Dict[str, int]:
        return dict(self._staleness_counters)

    async def cache_stats(self) -> Dict:
        """Return current cache statistics."""
        stats: Dict[str, int] = {}
        for ns in NS_ALL:
            keys = await self._scan_keys(f"{ns}*")
            stats[ns.rstrip(":")] = len(keys)
        stats["registered_dependencies"] = len(self._registry)
        stats["invalidation_events"] = len(self._invalidation_log)
        return stats
