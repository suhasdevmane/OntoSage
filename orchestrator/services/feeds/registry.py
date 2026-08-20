"""
feeds/registry.py — FeedRegistry: loads feeds.yaml, schedules polling.

Usage (FastAPI lifespan — follow floor_plan_watcher pattern):

    feed_registry = FeedRegistry(building_id=settings.BUILDING_ID)
    feed_registry.load()
    asyncio.create_task(feed_registry.run_forever())

feeds.yaml schema (per-building, under input/<building_id>/feeds.yaml):

    feeds:
      - id: weather_temp
        type: rest_poll
        url: https://api.open-meteo.com/v1/forecast?...
        interval_s: 300
        field_map:
          current_weather.temperature: value
        brick_class: brick:Outside_Air_Temperature_Sensor
        location: bldg:building_exterior
        unit: degC
        storage: bldg:database1

STRICT_SECRETS compliance:
  - auth values MUST be env-var NAMES in auth_env (never literal tokens in YAML)
  - YAML is version-controlled; never put credentials there
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote as _url_quote

import yaml

from orchestrator.services.feeds.base import FeedAdapter, FeedRecord, FeedSpec
from orchestrator.services.feeds.csv_drop import CsvDropAdapter
from orchestrator.services.feeds.rest_poll import RestPollAdapter
from shared.utils import get_logger

logger = get_logger(__name__)

try:
    import httpx as _httpx_for_reg
except ImportError:
    _httpx_for_reg = None  # type: ignore[assignment]

# Paths searched for the feeds.yaml (Docker vs local dev)
_YAML_SEARCH_PATHS = [
    "/app/input/{building_id}/feeds.yaml",
    "input/{building_id}/feeds.yaml",
]

_ADAPTER_CLASSES = {
    "rest_poll": RestPollAdapter,
    "csv_drop": CsvDropAdapter,
}


def _derive_uuid(building_id: str, feed_id: str) -> str:
    """Deterministic UUID for a feed's time-series point (stable across restarts)."""
    digest = hashlib.md5(  # noqa: S324 — non-security: deterministic point ID
        f"{building_id}:{feed_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:]}"


class FeedRegistry:
    """Manages all feeds for a building: loading, polling, and writing.

    The write path delegates to services/adapters/registry.py so the framework
    never writes SQL directly — storage is routed by the storedAt URI.
    """

    def __init__(
        self,
        building_id: str,
        *,
        input_root: str = "/app/input",
        writer: Optional[Callable] = None,
    ) -> None:
        self._building_id = building_id
        self._input_root = Path(input_root)
        self._adapters: Dict[str, FeedAdapter] = {}
        self._specs: Dict[str, FeedSpec] = {}
        # writer is a callable: async (records: List[FeedRecord]) -> int
        # injected for testing; defaults to _adapter_registry_writer()
        self._writer = writer or self._adapter_registry_writer

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self) -> int:
        """Load feeds.yaml for the building.  Returns number of enabled feeds loaded."""
        yaml_path = self._find_yaml()
        if yaml_path is None:
            logger.info(
                f"[feeds] no feeds.yaml for building '{self._building_id}' — feed framework idle"
            )
            return 0

        try:
            raw = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
        except Exception as e:
            logger.warning(f"[feeds] could not parse {yaml_path}: {e}")
            return 0

        feed_defs = data.get("feeds", [])
        if not isinstance(feed_defs, list):
            logger.warning(f"[feeds] feeds.yaml must have a top-level 'feeds' list")
            return 0

        loaded = 0
        for entry in feed_defs:
            try:
                spec = FeedSpec(**entry)
            except Exception as e:
                logger.warning(f"[feeds] invalid feed spec {entry.get('id', '?')}: {e}")
                continue

            if not spec.enabled:
                logger.debug(f"[feeds] {spec.id}: disabled — skipping")
                continue

            # Assign deterministic UUID if not provided in YAML
            if not spec.uuid:
                spec = spec.model_copy(update={"uuid": _derive_uuid(self._building_id, spec.id)})

            adapter_cls = _ADAPTER_CLASSES.get(spec.type)
            if adapter_cls is None:
                logger.warning(f"[feeds] unknown feed type '{spec.type}' for {spec.id}")
                continue

            if spec.type == "csv_drop":
                adapter = adapter_cls(spec, input_root=str(self._input_root))
            else:
                adapter = adapter_cls(spec)

            self._adapters[spec.id] = adapter
            self._specs[spec.id] = spec
            loaded += 1

        logger.info(
            f"[feeds] building='{self._building_id}' loaded {loaded} feed(s) " f"from {yaml_path}"
        )
        return loaded

    # ── Polling ───────────────────────────────────────────────────────────────

    async def poll_once(self, feed_id: str) -> List[FeedRecord]:
        """Poll a single feed adapter once.  Returns records (may be empty)."""
        adapter = self._adapters.get(feed_id)
        if adapter is None:
            return []
        return await adapter.poll_safe()

    async def run_all_once(self) -> Dict[str, int]:
        """Poll all feeds and write results.  Returns {feed_id: records_written}."""
        results: Dict[str, int] = {}
        for feed_id in list(self._adapters.keys()):
            records = await self.poll_once(feed_id)
            written = await self._write(records)
            results[feed_id] = written
        return results

    async def run_forever(self) -> None:
        """Asyncio background task: poll each feed on its own interval."""
        if not self._adapters:
            logger.debug("[feeds] no adapters loaded — run_forever exits immediately")
            return

        # Track next-fire time per feed
        import time

        next_fire: Dict[str, float] = {fid: time.monotonic() for fid in self._adapters}

        logger.info(f"[feeds] polling loop started for {len(self._adapters)} feed(s)")
        while True:
            now = time.monotonic()
            for feed_id, adapter in list(self._adapters.items()):
                if now >= next_fire[feed_id]:
                    records = await adapter.poll_safe()
                    if records:
                        written = await self._write(records)
                        logger.debug(
                            f"[feeds] {feed_id}: polled {len(records)} record(s), "
                            f"wrote {written}"
                        )
                    next_fire[feed_id] = now + adapter.spec.interval_s
            await asyncio.sleep(1)

    # ── Internal write path ───────────────────────────────────────────────────

    async def _write(self, records: List[FeedRecord]) -> int:
        if not records:
            return 0
        try:
            return await self._writer(records)
        except Exception as e:
            logger.error(f"[feeds] write failed: {e}", exc_info=True)
            return 0

    async def _adapter_registry_writer(self, records: List[FeedRecord]) -> int:
        """Default writer: routes writes through the adapter registry by storedAt URI."""
        written = 0
        # Group records by storage URI for batching
        by_storage: Dict[str, List[FeedRecord]] = {}
        for rec in records:
            spec = self._specs.get(rec.feed_id)
            storage = spec.storage if spec else ""
            by_storage.setdefault(storage, []).append(rec)

        for storage_uri, recs in by_storage.items():
            if not storage_uri:
                logger.debug(f"[feeds] {recs[0].feed_id}: no storage URI — records not persisted")
                continue
            try:
                from orchestrator.services.adapters.registry import adapter_registry

                adapter = adapter_registry.get(storage_uri)
                if adapter is None:
                    logger.warning(f"[feeds] no adapter for storage='{storage_uri}'")
                    continue
                if hasattr(adapter, "write_records"):
                    written += await adapter.write_records(recs)
                else:
                    logger.debug(
                        f"[feeds] adapter {type(adapter).__name__} has no write_records "
                        f"— {len(recs)} record(s) queued but not persisted (T13 wires this)"
                    )
            except Exception as e:
                logger.error(f"[feeds] write to '{storage_uri}' failed: {e}")

        return written

    # ── Ontology registration (T13) ───────────────────────────────────────────

    async def register_in_graphdb(
        self,
        *,
        graphdb_url: Optional[str] = None,
        repository: Optional[str] = None,
        building_namespace: Optional[str] = None,
    ) -> bool:
        """PUT Brick point triples for all loaded feeds into a dedicated GraphDB named graph.

        Idempotent: repeated calls replace the same named graph.
        Feeds removed from feeds.yaml are automatically removed on next boot.
        Non-fatal: logs warning and returns False if GraphDB is unreachable.
        """
        if _httpx_for_reg is None:
            logger.warning("[feeds/register] httpx not installed — skipping GraphDB registration")
            return False

        if not self._specs:
            logger.debug("[feeds/register] no feeds to register — skipping")
            return True

        # Resolve settings lazily to avoid import cost when feeds not configured
        try:
            from shared.config import settings as _settings

            _graphdb_url = graphdb_url or _settings.GRAPHDB_URL
            _repository = repository or _settings.GRAPHDB_REPOSITORY
            _bldg_ns = building_namespace or _settings.BUILDING_NAMESPACE
        except Exception as e:
            logger.warning(f"[feeds/register] could not load settings: {e}")
            return False

        # Named graph: <namespace_base>/feeds/<building_id>  (strip trailing # or /)
        ns_base = _bldg_ns.rstrip("#/")
        named_graph = f"{ns_base}/feeds/{self._building_id}"
        endpoint = (
            f"{_graphdb_url}/repositories/{_repository}"
            f"/rdf-graphs/service?graph={_url_quote(named_graph, safe='')}"
        )

        ttl = self._build_registration_ttl(_bldg_ns, named_graph)

        try:
            async with _httpx_for_reg.AsyncClient(timeout=30.0) as client:
                resp = await client.put(
                    endpoint,
                    content=ttl.encode("utf-8"),
                    headers={"Content-Type": "text/turtle"},
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        f"[feeds/register] registered {len(self._specs)} feed point(s) "
                        f"in graph <{named_graph}>"
                    )
                    return True
                else:
                    logger.warning(
                        f"[feeds/register] GraphDB returned {resp.status_code}: {resp.text[:200]}"
                    )
                    return False
        except Exception as e:
            logger.warning(f"[feeds/register] could not reach GraphDB: {e}")
            return False

    def _build_registration_ttl(self, bldg_ns: str, named_graph: str) -> str:
        """Build Turtle content registering all loaded feeds as Brick points."""
        ns_prefix = bldg_ns.rstrip("#/") + "#"
        lines = [
            f"# Feed point registrations for building {self._building_id}",
            f"# Named graph: <{named_graph}>",
            f"# Auto-generated by FeedRegistry.register_in_graphdb() — do not edit manually.",
            "",
            f"@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            f"@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .",
            f"@prefix owl:    <http://www.w3.org/2002/07/owl#> .",
            f"@prefix brick:  <https://brickschema.org/schema/Brick#> .",
            f"@prefix ref:    <https://brickschema.org/schema/Brick/ref#> .",
            f"@prefix ashrae: <http://data.ashrae.org/standard223#> .",
            f"@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .",
            f"@prefix bldg:   <{ns_prefix}> .",
            "",
        ]

        for feed_id, spec in self._specs.items():
            safe_id = feed_id.replace("-", "_").replace(".", "_")
            point_uri = f"bldg:feed_{safe_id}"
            bnode = f"_:ref_{safe_id}"

            # Build rdf:type list
            type_list = ["owl:NamedIndividual"]
            if spec.brick_class:
                # brick_class may be prefixed ("brick:Outside_Air_Temperature_Sensor")
                # or a full URI — use as-is if it already has a colon
                bc = spec.brick_class if ":" in spec.brick_class else f"brick:{spec.brick_class}"
                type_list.append(bc)

            type_str = " ,\n".join(f"                    {t}" for t in type_list)
            lines.append(f"{point_uri} rdf:type {type_str} ;")

            if spec.location:
                loc = spec.location if ":" in spec.location else f"bldg:{spec.location}"
                lines.append(f"                 brick:hasLocation {loc} ;")

            lines.append(f"                 ashrae:hasExternalReference {bnode} ;")
            lines.append(f"                 ref:hasExternalReference {bnode} ;")
            lines.append(f'                 rdfs:comment "feed-auto-registered"^^xsd:string ;')
            label = (
                spec.brick_class.split(":")[-1].replace("_", " ") if spec.brick_class else feed_id
            )
            lines.append(f'                 rdfs:label "{label} feed {feed_id}"@en .')
            lines.append("")

            lines.append(f"{bnode} rdf:type ashrae:ExternalReference ,")
            lines.append(f"             ref:ExternalReference ,")
            lines.append(f"             ref:TimeseriesReference ;")
            lines.append(f'        ref:hasTimeseriesId "{spec.uuid}" ;')
            storage = spec.storage if spec.storage else "bldg:database1"
            stor = storage if ":" in storage else f"bldg:{storage}"
            lines.append(f"        ref:storedAt {stor} .")
            lines.append("")

        return "\n".join(lines)

    # ── Accessors ─────────────────────────────────────────────────────────────

    def adapter_ids(self) -> List[str]:
        return list(self._adapters.keys())

    def spec(self, feed_id: str) -> Optional[FeedSpec]:
        return self._specs.get(feed_id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_yaml(self) -> Optional[Path]:
        # Check injected input_root first (supports tests and non-standard
        # mounts), then the well-known roots — both via the shared resolver,
        # which supports the nested (input/<id>/) AND flat (input/) layouts.
        from shared.config import resolve_building_file

        candidate = resolve_building_file(
            self._building_id, "feeds.yaml", input_root=self._input_root
        )
        if candidate is not None:
            return candidate
        return resolve_building_file(self._building_id, "feeds.yaml")
