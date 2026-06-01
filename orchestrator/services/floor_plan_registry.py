"""
floor_plan_registry.py — Orchestrates DWG + PDF pipelines and merges results.

Runs DWGPipeline and FloorPlanPipeline in parallel, then merges per-floor:
  - DWG wins for geometry (polygon, area_m2, perimeter_m, adjacency, blocks)
  - PDF wins for rendered_image (PNG + thumbnail URL)
  - If only PDF: schema_version="1.0", unchanged
  - If only DWG: schema_version="2.0", no PNG
  - If both:     schema_version="2.0", full enrichment

Public API:
    registry = get_floor_plan_registry()
    manifests = await registry.ingest_all()
    manifest  = registry.load_manifest("abacws", 3)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shared.models import FloorPlanManifest, Space
from shared.utils import get_logger

logger = get_logger(__name__)


class FloorPlanRegistry:
    """
    Merge orchestrator that combines DWG geometry with PDF renders.
    One instance is shared across the application lifecycle.
    """

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        manifest_dir: Optional[Path] = None,
        graphdb_url: Optional[str] = None,
        qdrant_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        llm_extract_enabled: bool = True,
    ) -> None:
        from orchestrator.services.dwg_pipeline import DWGPipeline
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        self._dwg_pipeline = DWGPipeline(
            input_dir=input_dir,
            manifest_dir=manifest_dir,
            graphdb_url=graphdb_url,
        )
        self._pdf_pipeline = FloorPlanPipeline(
            pdf_dir=input_dir,
            manifest_dir=manifest_dir,
            graphdb_url=graphdb_url,
            qdrant_url=qdrant_url,
            openai_api_key=openai_api_key,
            llm_extract_enabled=llm_extract_enabled,
        )
        self._manifest_dir = manifest_dir or Path("/app/floor_plans")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def ingest_all(self) -> List[FloorPlanManifest]:
        """Run DWG and PDF pipelines in parallel, then merge per floor."""
        dwg_results, pdf_results = await asyncio.gather(
            self._dwg_pipeline.ingest_all(),
            self._pdf_pipeline.ingest_all(),
            return_exceptions=True,
        )

        # Tolerate one pipeline failing — treat as empty list
        if isinstance(dwg_results, Exception):
            logger.warning(f"[registry] DWG pipeline failed: {dwg_results}")
            dwg_results = []
        if isinstance(pdf_results, Exception):
            logger.warning(f"[registry] PDF pipeline failed: {pdf_results}")
            pdf_results = []

        # Index by (building_id, floor)
        dwg_map: Dict[Tuple[str, int], FloorPlanManifest] = {
            (m.building_id, m.floor): m for m in dwg_results  # type: ignore[union-attr]
        }
        pdf_map: Dict[Tuple[str, int], FloorPlanManifest] = {
            (m.building_id, m.floor): m for m in pdf_results  # type: ignore[union-attr]
        }

        all_keys = set(dwg_map) | set(pdf_map)
        merged: List[FloorPlanManifest] = []

        for key in sorted(all_keys):
            dwg_m = dwg_map.get(key)
            pdf_m = pdf_map.get(key)
            result = self._merge(dwg_m, pdf_m)
            if result:
                await self._write_manifest(result)
                merged.append(result)

        dwg_count = sum(1 for m in merged if "dwg" in m.data_sources)
        logger.info(
            f"[registry] Ingestion complete — {len(merged)} manifests "
            f"({dwg_count} DWG-enriched)"
        )
        return merged

    def load_manifest(self, building_id: str, floor: int) -> Optional[FloorPlanManifest]:
        """Load the final merged manifest from disk (Phase 4 — alias-aware)."""
        # Phase 4 — try the requested ID first, then each alias declared in the
        # BuildingRegistry.  This keeps manifests written under legacy slugs
        # (e.g. "abacws") accessible to callers using the logical ID ("bldg1").
        candidates = [building_id]
        try:
            from orchestrator.services.building_registry import get_building_registry
            reg = get_building_registry()
            primary = reg.resolve_id(building_id)
            if primary and primary not in candidates:
                candidates.append(primary)
            cfg = reg.get(primary or building_id)
            if cfg is not None:
                for alias in cfg.floor_plan_aliases or []:
                    if alias not in candidates:
                        candidates.append(alias)
        except Exception:
            pass

        for bid in candidates:
            p = self._manifest_dir / bid / f"floor_{floor}.manifest.json"
            if not p.exists():
                continue
            try:
                return FloorPlanManifest.model_validate_json(p.read_text("utf-8"))
            except Exception as e:
                logger.warning(f"[registry] Could not load manifest {p}: {e}")
        return None

    # ── Merge logic ───────────────────────────────────────────────────────────

    def _merge(
        self,
        dwg: Optional[FloorPlanManifest],
        pdf: Optional[FloorPlanManifest],
    ) -> Optional[FloorPlanManifest]:
        """Merge DWG geometry + PDF render into one canonical manifest."""
        if pdf is None and dwg is None:
            return None

        if pdf is None:
            # DWG only — no PNG yet
            logger.debug(
                f"[registry] floor={dwg.floor} building={dwg.building_id}: DWG-only manifest"
            )
            return dwg

        if dwg is None:
            # PDF only — schema 1.0 unchanged
            logger.debug(
                f"[registry] floor={pdf.floor} building={pdf.building_id}: PDF-only manifest"
            )
            return pdf

        # Both available — produce v2.0 merged manifest
        logger.info(
            f"[registry] Merging DWG + PDF for {pdf.building_id} floor {pdf.floor}"
        )
        merged_spaces = self._merge_spaces(dwg.spaces, pdf.spaces)

        return FloorPlanManifest(
            schema_version="2.0",
            building_id=pdf.building_id,
            building_name=pdf.building_name,
            floor=pdf.floor,
            floor_label=pdf.floor_label,
            # PDF provides source tracking
            source_pdf=pdf.source_pdf,
            source_sha256=pdf.source_sha256,
            # DWG source tracking
            source_dwg=dwg.source_dwg,
            source_dwg_sha256=dwg.source_dwg_sha256,
            dwg_units=dwg.dwg_units,
            data_sources=["pdf", "dwg"],
            generated_at=datetime.utcnow(),
            generator_version="2.0.0",
            page_count=pdf.page_count,
            # PDF wins for rendered image
            rendered_image=pdf.rendered_image,
            pdf_url=pdf.pdf_url,
            bounding_box=dwg.bounding_box or pdf.bounding_box,
            # Merged spaces
            spaces=merged_spaces,
            facilities=pdf.facilities or dwg.facilities,
            ontology_links=pdf.ontology_links,
            warnings=pdf.warnings + dwg.warnings,
            # DWG-specific geometry
            total_area_m2=dwg.total_area_m2,
            blocks=dwg.blocks,
            layers=dwg.layers,
            adjacency=dwg.adjacency,
        )

    def _merge_spaces(
        self,
        dwg_spaces: List[Space],
        pdf_spaces: List[Space],
    ) -> List[Space]:
        """
        Merge DWG and PDF space lists.

        Strategy:
        - DWG spaces have polygon/area geometry — they are the primary entries.
        - For each DWG space with a generic label ("Zone X.XX"), try to find a
          richer label from the PDF spaces by matching zone_id.
        - PDF-only spaces (no matching DWG zone_id) are appended at the end.
        """
        dwg_by_zone: Dict[str, Space] = {s.zone_id: s for s in dwg_spaces}
        pdf_by_zone: Dict[str, Space] = {s.zone_id: s for s in pdf_spaces}

        merged: List[Space] = []
        pdf_zone_ids_used = set()

        for zone_id, dwg_space in dwg_by_zone.items():
            pdf_space = pdf_by_zone.get(zone_id)
            if pdf_space:
                pdf_zone_ids_used.add(zone_id)
                # DWG wins for geometry; PDF wins for label if DWG label is generic
                label = dwg_space.label
                if label.startswith("Zone ") and pdf_space.label and not pdf_space.label.startswith("Zone "):
                    label = pdf_space.label

                merged.append(
                    Space(
                        id=dwg_space.id,
                        zone_id=zone_id,
                        label=label,
                        aliases=list({*dwg_space.aliases, *pdf_space.aliases}),
                        type=pdf_space.type if pdf_space.type != "unknown" else dwg_space.type,
                        tags=list({*dwg_space.tags, *pdf_space.tags}),
                        centroid=dwg_space.centroid or pdf_space.centroid,
                        bbox=pdf_space.bbox or dwg_space.bbox,
                        polygon=dwg_space.polygon,
                        sensor_uuids=list({*dwg_space.sensor_uuids, *pdf_space.sensor_uuids}),
                        ontology_iri=pdf_space.ontology_iri or dwg_space.ontology_iri,
                        source="dwg",
                        confidence=max(dwg_space.confidence, pdf_space.confidence),
                        area_m2=dwg_space.area_m2,
                        perimeter_m=dwg_space.perimeter_m,
                        layer=dwg_space.layer,
                        adjacent_spaces=dwg_space.adjacent_spaces,
                    )
                )
            else:
                merged.append(dwg_space)

        # Append PDF-only spaces not in DWG
        for zone_id, pdf_space in pdf_by_zone.items():
            if zone_id not in pdf_zone_ids_used and zone_id not in dwg_by_zone:
                merged.append(pdf_space)

        return merged

    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def list_manifests(self) -> List[Tuple[str, int]]:
        """Return [(building_id, floor)] for every merged manifest on disk."""
        return self._pdf_pipeline.list_manifests()

    async def _write_manifest(self, manifest: FloorPlanManifest) -> None:
        d = self._manifest_dir / manifest.building_id
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"floor_{manifest.floor}.manifest.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        logger.debug(f"[registry] Manifest written: {path}")

        # Re-index spaces in Qdrant with full merged payload (incl. DWG geometry)
        await self._reindex_merged_spaces(manifest)

        # Cache in Redis (best-effort)
        try:
            from shared.config import settings
            import redis.asyncio as aioredis

            redis = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}"
            )
            key = f"floor_plan:manifest:{manifest.building_id}:{manifest.floor}"
            await redis.set(key, manifest.model_dump_json(), ex=3600)
            await redis.aclose()
        except Exception as e:
            logger.debug(f"[registry] Redis cache skipped: {e}")

    async def _reindex_merged_spaces(self, manifest: FloorPlanManifest) -> None:
        """Re-upsert all spaces to Qdrant with full merged payload (DWG geometry included)."""
        try:
            await self._pdf_pipeline._embed_and_index(manifest)
            with_geom = sum(1 for s in manifest.spaces if s.area_m2 is not None)
            logger.info(
                f"[registry] Re-indexed {len(manifest.spaces)} spaces "
                f"({with_geom} with geometry) "
                f"for {manifest.building_id}/floor {manifest.floor}"
            )
        except Exception as e:
            logger.warning(f"[registry] Qdrant re-indexing skipped (non-fatal): {e}")


# ── Module-level singleton ─────────────────────────────────────────────────────
_registry: Optional[FloorPlanRegistry] = None


def get_floor_plan_registry() -> FloorPlanRegistry:
    global _registry
    if _registry is None:
        _registry = FloorPlanRegistry()
    return _registry
