"""
CapabilityIndexer — startup-time pipeline that embeds capability KB entries
into Qdrant, one collection per building.

Behaviour:
  - Iterates /app/input/<bldg>/capability.yaml (and building.yaml for config)
  - Computes SHA-256 of capability.yaml content
  - Compares against existing collection's payload.yaml_sha:
      match     → SKIP (idempotent, no embedding API calls)
      mismatch  → DELETE collection, rebuild
      dim mismatch (provider switched) → DELETE collection, rebuild
      missing   → CREATE collection, populate
  - Multi-vector embedding: per entry → one point per keyword + one for content[:500]
  - Point ID: uuid5(NAMESPACE_OID, f"{building_id}:{entry_id}:{vector_source}:{text_hash}")
  - Failures (Qdrant or embedding API) are logged and return IndexResult(status="degraded")
    — orchestrator startup MUST NOT be blocked by capability indexing failure.

Returns IndexResult per building with: status, entries, points, duration_ms, reason.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal

import yaml

from shared.capability_schema import (
    CapabilityKB,
    CapabilityRoutingConfig,
)
from shared.utils import get_logger

logger = get_logger(__name__)


# Stable namespace for deterministic UUID v5 generation — chosen once, never changed.
# Changing this constant would invalidate every point ID in production.
_CAPABILITY_NAMESPACE = uuid.UUID("8f1a3b9e-7c4d-5e2f-9a8b-1c2d3e4f5a6b")

_CONTENT_EMBED_MAX_CHARS = 500


@dataclass
class IndexResult:
    """Result of indexing a single building.

    status:
      indexed  → collection was (re)built from scratch
      skipped  → existing collection's yaml_sha matched; no embedding API calls
      degraded → indexing failed (Qdrant or embedding error); router will use fallback
      disabled → capability_routing.enabled = false in building.yaml
    """

    building_id: str
    status: Literal["indexed", "skipped", "degraded", "disabled"]
    entries: int = 0
    points: int = 0
    duration_ms: float = 0.0
    yaml_sha: str = ""
    reason: str = ""


class CapabilityIndexer:
    """See module docstring.

    Usage in FastAPI lifespan:
        indexer = CapabilityIndexer(qdrant_client, embedding_service)
        results = await indexer.index_all_buildings()
        for bldg, result in results.items():
            logger.info(f"[capability_indexer] {bldg}: {result}")
    """

    def __init__(
        self,
        qdrant_client,
        embedding_service,
        input_root: str = "/app/input",
        collection_prefix: str = "capability_",
    ):
        self._qdrant = qdrant_client
        self._embedder = embedding_service
        self._input_root = Path(input_root)
        self._collection_prefix = collection_prefix

    # ── public API ──────────────────────────────────────────────────────────────

    async def index_all_buildings(self) -> Dict[str, IndexResult]:
        """Scan input_root, index each building. Returns {building_id: IndexResult}."""
        results: Dict[str, IndexResult] = {}
        if not self._input_root.exists():
            logger.warning(f"[capability_indexer] input_root not found: {self._input_root}")
            return results

        for bldg_dir in sorted(self._input_root.iterdir()):
            if not bldg_dir.is_dir():
                continue
            cap_yaml = bldg_dir / "capability.yaml"
            if not cap_yaml.exists():
                continue
            building_id = bldg_dir.name
            results[building_id] = await self.index_building(building_id)
            # Additionally index any opt-in extra intents (floor_plan, spatial_query, ...)
            # defined in input/<bldg>/building.yaml under `intent_routing:`.
            # Failures here are non-fatal — they don't affect capability indexing.
            try:
                await self.index_extra_intents(building_id)
            except Exception as e:
                logger.warning(
                    f"[capability_indexer] extra-intent indexing failed for "
                    f"{building_id} (non-fatal): {e}"
                )
        return results

    async def index_building(self, building_id: str) -> IndexResult:
        """Index a single building. Idempotent; safe to call repeatedly."""
        t0 = time.monotonic()
        cap_yaml_path = self._input_root / building_id / "capability.yaml"
        bldg_yaml_path = self._input_root / building_id / "building.yaml"
        collection_name = f"{self._collection_prefix}{building_id}"

        if not cap_yaml_path.exists():
            return IndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"capability.yaml not found at {cap_yaml_path}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── 1. Load + validate capability KB ────────────────────────────────────
        try:
            yaml_bytes = cap_yaml_path.read_bytes()
            yaml_sha = hashlib.sha256(yaml_bytes).hexdigest()
            kb = CapabilityKB.from_yaml(cap_yaml_path)
        except Exception as e:
            logger.error(f"[capability_indexer] {building_id}: failed to load YAML: {e}")
            return IndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"yaml load/validation failed: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── 2. Load routing config (optional) ───────────────────────────────────
        routing_cfg = self._load_routing_config(bldg_yaml_path)
        if not routing_cfg.enabled:
            return IndexResult(
                building_id=building_id,
                status="disabled",
                entries=len(kb.capabilities),
                yaml_sha=yaml_sha,
                reason="capability_routing.enabled = false",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── 3. Check existing collection state ──────────────────────────────────
        try:
            should_rebuild, existing_msg = await self._check_collection_state(
                collection_name, yaml_sha, expected_dim=self._embedder.dimension
            )
        except Exception as e:
            logger.error(f"[capability_indexer] {building_id}: Qdrant probe failed: {e}")
            return IndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"Qdrant probe failed: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        if not should_rebuild:
            logger.info(
                f"[capability_indexer] {building_id}: skipped — {existing_msg}"
            )
            return IndexResult(
                building_id=building_id,
                status="skipped",
                entries=len(kb.capabilities),
                yaml_sha=yaml_sha,
                reason=existing_msg,
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── 4. Build points (embed) ─────────────────────────────────────────────
        try:
            points = await self._build_points(building_id, kb, yaml_sha)
        except Exception as e:
            logger.error(f"[capability_indexer] {building_id}: embedding failed: {e}")
            return IndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"embedding failed: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── 5. (Re)create collection + upsert ───────────────────────────────────
        try:
            await self._recreate_collection(collection_name)
            await self._upsert_points(collection_name, points)
        except Exception as e:
            logger.error(f"[capability_indexer] {building_id}: Qdrant write failed: {e}")
            return IndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"Qdrant write failed: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            f"[capability_indexer] {building_id}: indexed entries={len(kb.capabilities)} "
            f"points={len(points)} sha={yaml_sha[:8]} ({duration_ms:.0f}ms)"
        )
        return IndexResult(
            building_id=building_id,
            status="indexed",
            entries=len(kb.capabilities),
            points=len(points),
            yaml_sha=yaml_sha,
            duration_ms=duration_ms,
        )

    async def index_extra_intents(self, building_id: str) -> Dict[str, IndexResult]:
        """Index opt-in extra intents (e.g. floor_plan, spatial_query) from
        building.yaml's `intent_routing:` block. Each intent gets its own
        Qdrant collection: intent_<intent_name>_<building_id>.

        Returns {intent_name: IndexResult}. Empty dict if no extra intents configured.
        Skips intents with enabled=false.
        """
        import yaml as _yaml
        from shared.capability_schema import IntentRouteConfig

        bldg_yaml_path = self._input_root / building_id / "building.yaml"
        results: Dict[str, IndexResult] = {}
        if not bldg_yaml_path.exists():
            return results

        try:
            with open(bldg_yaml_path, "r", encoding="utf-8") as fh:
                data = _yaml.safe_load(fh) or {}
        except Exception as e:
            logger.warning(
                f"[capability_indexer] {building_id}: building.yaml unreadable for "
                f"extra intents: {e}"
            )
            return results

        intent_routing_block = data.get("intent_routing") or {}
        if not intent_routing_block:
            return results  # no extra intents — that's the default

        # SHA-256 of the intent_routing block alone — keeps capability vs extras independent
        block_bytes = _yaml.safe_dump(intent_routing_block, sort_keys=True).encode("utf-8")
        block_sha = hashlib.sha256(block_bytes).hexdigest()

        for intent_name, raw_cfg in intent_routing_block.items():
            try:
                cfg = IntentRouteConfig(**(raw_cfg or {}))
            except Exception as e:
                logger.warning(
                    f"[capability_indexer] {building_id}/{intent_name}: invalid config "
                    f"({e}) — skipping intent"
                )
                continue

            collection_name = f"intent_{intent_name}_{building_id}"

            if not cfg.enabled:
                logger.info(
                    f"[capability_indexer] {building_id}/{intent_name}: status=disabled "
                    f"(enabled=false)"
                )
                results[intent_name] = IndexResult(
                    building_id=f"{building_id}/{intent_name}",
                    status="disabled",
                    reason="enabled=false",
                )
                continue

            # Idempotency check — same as capability flow
            t0 = time.monotonic()
            try:
                should_rebuild, msg = await self._check_collection_state(
                    collection_name, block_sha, expected_dim=self._embedder.dimension
                )
            except Exception as e:
                logger.warning(
                    f"[capability_indexer] {building_id}/{intent_name}: Qdrant probe "
                    f"failed: {e}"
                )
                results[intent_name] = IndexResult(
                    building_id=f"{building_id}/{intent_name}",
                    status="degraded", reason=f"Qdrant probe failed: {e}",
                )
                continue

            if not should_rebuild:
                results[intent_name] = IndexResult(
                    building_id=f"{building_id}/{intent_name}",
                    status="skipped",
                    entries=len(cfg.descriptors),
                    yaml_sha=block_sha,
                    reason=msg,
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
                logger.info(
                    f"[capability_indexer] {building_id}/{intent_name}: skipped — {msg}"
                )
                continue

            # Build points: one per descriptor
            try:
                vectors = await self._embedder.embed_batch(cfg.descriptors)
            except Exception as e:
                logger.warning(
                    f"[capability_indexer] {building_id}/{intent_name}: embedding "
                    f"failed: {e}"
                )
                results[intent_name] = IndexResult(
                    building_id=f"{building_id}/{intent_name}",
                    status="degraded", reason=f"embedding failed: {e}",
                )
                continue

            from qdrant_client.models import PointStruct
            points = []
            for i, (descriptor, vec) in enumerate(zip(cfg.descriptors, vectors)):
                pid = str(uuid.uuid5(
                    _CAPABILITY_NAMESPACE,
                    f"{building_id}:intent:{intent_name}:{i}:{descriptor}",
                ))
                points.append(PointStruct(
                    id=pid, vector=vec,
                    payload={
                        "intent_name": intent_name,
                        "descriptor_idx": i,
                        "text": descriptor,
                        "yaml_sha": block_sha,
                        "building_id": building_id,
                    },
                ))

            try:
                await self._recreate_collection(collection_name)
                await self._upsert_points(collection_name, points)
            except Exception as e:
                logger.warning(
                    f"[capability_indexer] {building_id}/{intent_name}: Qdrant write "
                    f"failed: {e}"
                )
                results[intent_name] = IndexResult(
                    building_id=f"{building_id}/{intent_name}",
                    status="degraded", reason=f"Qdrant write failed: {e}",
                )
                continue

            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                f"[capability_indexer] {building_id}/{intent_name}: indexed "
                f"descriptors={len(cfg.descriptors)} points={len(points)} "
                f"sha={block_sha[:8]} ({duration_ms:.0f}ms)"
            )
            results[intent_name] = IndexResult(
                building_id=f"{building_id}/{intent_name}",
                status="indexed",
                entries=len(cfg.descriptors),
                points=len(points),
                yaml_sha=block_sha,
                duration_ms=duration_ms,
            )

        return results

    # ── internal: routing config loader ─────────────────────────────────────────

    def _load_routing_config(self, bldg_yaml_path: Path) -> CapabilityRoutingConfig:
        """Read capability_routing from building.yaml; defaults if absent."""
        if not bldg_yaml_path.exists():
            return CapabilityRoutingConfig()
        try:
            with open(bldg_yaml_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            block = data.get("capability_routing") or {}
            return CapabilityRoutingConfig(**block)
        except Exception as e:
            logger.warning(
                f"[capability_indexer] building.yaml routing config invalid "
                f"({bldg_yaml_path}): {e} — falling back to defaults"
            )
            return CapabilityRoutingConfig()

    # ── internal: collection state check ────────────────────────────────────────

    async def _check_collection_state(
        self, collection_name: str, expected_sha: str, expected_dim: int
    ) -> tuple[bool, str]:
        """Return (should_rebuild, message).

        Logic:
          - Collection missing → rebuild (msg: "missing")
          - Dim mismatch → rebuild (msg: "dim mismatch")
          - Existing point's yaml_sha differs → rebuild (msg: "sha mismatch")
          - Existing point's yaml_sha matches → skip (msg: "sha match")
          - Collection exists but empty → rebuild (msg: "empty")
        """
        existing_names = await self._list_collection_names()
        if collection_name not in existing_names:
            return True, "missing"

        info = await self._qdrant.get_collection(collection_name)
        existing_dim = self._extract_dim(info)
        if existing_dim != expected_dim:
            return True, f"dim mismatch (existing={existing_dim} expected={expected_dim})"

        # Scroll one point to check its yaml_sha
        scroll = await self._qdrant.scroll(
            collection_name=collection_name, limit=1, with_payload=True
        )
        records = scroll[0] if isinstance(scroll, tuple) else scroll.points
        if not records:
            return True, "empty"

        first = records[0]
        existing_sha = (first.payload or {}).get("yaml_sha")
        if existing_sha == expected_sha:
            return False, f"sha match ({existing_sha[:8]})"
        return True, f"sha mismatch (existing={(existing_sha or '?')[:8]} new={expected_sha[:8]})"

    async def _list_collection_names(self) -> List[str]:
        result = await self._qdrant.get_collections()
        return [c.name for c in result.collections]

    @staticmethod
    def _extract_dim(collection_info: Any) -> int:
        """Pull vector dim out of a Qdrant collection info object.

        Qdrant client returns nested config; structure has been stable but defensive.
        """
        try:
            return int(collection_info.config.params.vectors.size)
        except AttributeError:
            # Newer client versions may have vectors as a dict
            vectors = collection_info.config.params.vectors
            if isinstance(vectors, dict):
                # Single unnamed vector → {'': VectorParams(size=...)}
                first = next(iter(vectors.values()))
                return int(first.size)
            raise

    # ── internal: embedding (build points) ──────────────────────────────────────

    async def _build_points(
        self, building_id: str, kb: CapabilityKB, yaml_sha: str
    ) -> List[Any]:
        """Per entry: one embedding per keyword + one for content[:500].
        All points for the same entry share entry_id in payload for group-by at query time.
        """
        from qdrant_client.models import PointStruct

        # Collect all texts to embed in one batch (efficient for OpenAI / local)
        embed_specs: List[tuple[str, str, str]] = []  # (entry_id, vector_source, text)
        for entry in kb.capabilities:
            # One vector per keyword
            for kw in entry.keywords:
                if kw and kw.strip():
                    embed_specs.append((entry.id, "keyword", kw.strip()))
            # One vector for content (truncated)
            content = (entry.content or "").strip()[:_CONTENT_EMBED_MAX_CHARS]
            if content:
                embed_specs.append((entry.id, "content", content))

        if not embed_specs:
            return []

        texts = [spec[2] for spec in embed_specs]
        vectors = await self._embedder.embed_batch(texts)

        # Build PointStructs with deterministic UUID v5 IDs
        points: List[Any] = []
        for (entry_id, vector_source, text), vector in zip(embed_specs, vectors):
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            point_id = str(
                uuid.uuid5(
                    _CAPABILITY_NAMESPACE,
                    f"{building_id}:{entry_id}:{vector_source}:{text_hash}",
                )
            )
            # Find the source entry for category/source payload
            entry = next((e for e in kb.capabilities if e.id == entry_id), None)
            payload = {
                "entry_id": entry_id,
                "category": entry.category if entry else "",
                "source": entry.source if entry else "",
                "vector_source": vector_source,
                "text": text,
                "yaml_sha": yaml_sha,
                "building_id": building_id,
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        return points

    # ── internal: Qdrant write ──────────────────────────────────────────────────

    async def _recreate_collection(self, collection_name: str) -> None:
        from qdrant_client.models import Distance, VectorParams

        existing = await self._list_collection_names()
        if collection_name in existing:
            await self._qdrant.delete_collection(collection_name)

        await self._qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=self._embedder.dimension, distance=Distance.COSINE
            ),
        )

    async def _upsert_points(self, collection_name: str, points: List[Any]) -> None:
        if not points:
            return
        # Batch upsert in chunks of 100 to avoid huge single payloads
        batch_size = 100
        for i in range(0, len(points), batch_size):
            chunk = points[i : i + batch_size]
            await self._qdrant.upsert(collection_name=collection_name, points=chunk)
