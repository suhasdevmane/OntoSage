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


def _norm_label(label: str) -> str:
    """Collapse a room label to a comparison key.

    Case and separators differ freely between a CAD label and a PDF caption for
    the same room ("RM001A_room" / "RM001A Room"), and neither difference makes
    them different rooms.
    """
    return "".join(ch for ch in (label or "").lower() if ch.isalnum())


def _drop_duplicated_cad_copies(pdf_spaces: List[Space]) -> List[Space]:
    """Undo an earlier bad merge that left both copies of a room (BUG-198).

    The merged manifest is written to the same path the PDF pipeline writes to,
    so a re-ingestion can hand the merge its OWN previous output as the "PDF"
    side. When that output came from the era before rooms were paired, it holds
    both halves of every room; every label is then ambiguous, the label pairing
    below refuses to act, and the duplicates survive another round.

    Only a CAD-sourced space whose label is ALSO claimed by another space in the
    same list is dropped, because only then is it a leftover copy. A correctly
    merged record is CAD-sourced too but owns its label alone, so it passes
    through and re-pairs by zone_id — which is what makes merging a merged
    manifest a no-op instead of a slow loss of identity.
    """
    counts: Dict[str, int] = {}
    for s in pdf_spaces:
        key = _norm_label(s.label)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return [
        s for s in pdf_spaces if not (s.source == "dwg" and counts.get(_norm_label(s.label), 0) > 1)
    ]


def _unique_by_label(spaces: List[Space]) -> Dict[str, Space]:
    """Index spaces by normalised label, keeping only UNAMBIGUOUS labels.

    A label shared by two spaces cannot identify either of them, so it is
    dropped rather than resolved arbitrarily — merging the wrong pair would fuse
    one room's geometry onto another room's identity, and nothing downstream
    could detect that.
    """
    counts: Dict[str, int] = {}
    for s in spaces:
        key = _norm_label(s.label)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {_norm_label(s.label): s for s in spaces if counts.get(_norm_label(s.label)) == 1}


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
                await self.link_unlinked_spaces(result)
                await self._write_manifest(result)
                merged.append(result)

        dwg_count = sum(1 for m in merged if "dwg" in m.data_sources)
        logger.info(
            f"[registry] Ingestion complete — {len(merged)} manifests "
            f"({dwg_count} DWG-enriched)"
        )
        return merged

    async def link_unlinked_spaces(self, manifest: FloorPlanManifest) -> None:
        """Resolve ontology IRIs for the MERGED space set.

        Linking used to happen only inside the PDF pipeline, over PDF spaces, and
        a DWG space could acquire an IRI solely by being merged with a PDF space
        that already had one. A floor whose PDF carries no text layer therefore
        linked nothing at all, however well its CAD named the rooms -- and that
        is not an edge case: it is exactly what a scanned or image-only floor
        plan looks like, and what hand-drawn room boundaries produce.

        This also closes a split between the two ways ingestion can be triggered.
        The /reingest endpoint linked the merged set; boot-time ingest did not, so
        the SAME inputs yielded a fully-linked floor or an unlinked one depending
        on which path ran. Owning the step here makes the merge the single place
        it happens, and both callers inherit it.
        """
        unlinked = [s for s in manifest.spaces if not s.ontology_iri]
        if not unlinked:
            return
        try:
            await self._pdf_pipeline._link_ontology(unlinked, manifest.building_id, manifest.floor)
        except Exception as e:
            logger.warning(
                f"[registry] ontology linking failed for "
                f"{manifest.building_id}/floor {manifest.floor}: {e}"
            )
            return
        # Rebuilt, not patched: the map was assembled at merge time from the
        # spaces that had IRIs then, so newly-linked spaces are missing from it.
        manifest.ontology_links = {
            s.zone_id: s.ontology_iri for s in manifest.spaces if s.ontology_iri
        }

    @staticmethod
    def _identity_candidates(building_id: str) -> List[str]:
        """Every on-disk name that legitimately belongs to one building.

        Manifests are written under whichever slug the pipeline saw, which for a
        building onboarded under a legacy name is not its logical id — so a
        building owns its id, the id that resolves from it, and every declared
        floor-plan alias.
        """
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
        return candidates

    def load_manifest(self, building_id: str, floor: int) -> Optional[FloorPlanManifest]:
        """Load the final merged manifest from disk (Phase 4 — alias-aware)."""
        # Phase 4 — try the requested ID first, then each alias declared in the
        # BuildingRegistry.  This keeps manifests written under legacy slugs
        # (e.g. "abacws") accessible to callers using the logical ID ("bldg1").
        candidates = self._identity_candidates(building_id)

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
        logger.info(f"[registry] Merging DWG + PDF for {pdf.building_id} floor {pdf.floor}")
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
            # Rebuilt from the MERGED spaces, not copied from the PDF manifest:
            # a merged space keeps the DWG zone_id, so PDF-keyed links would
            # point at ids no space in this manifest carries any more.
            ontology_links={s.zone_id: s.ontology_iri for s in merged_spaces if s.ontology_iri},
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
        Merge DWG and PDF space lists into ONE record per real room.

        The two sources describe the same rooms and each holds half of what a
        room needs: the DWG carries polygon, area, centroid and adjacency but no
        identity, while the PDF/LLM pass carries the ontology IRI but no
        geometry at all.

        Pairing them on ``zone_id`` alone silently failed (BUG-147, CAVEAT-154),
        because the two sides mint ids from different things: the DWG uses the
        positional CAD id ("0Z001") and the PDF uses a slug of the room name
        ("fp.bldg2.0.rm001a_room"). Those id spaces never intersect, so every
        space fell through to an "unmatched" branch and each room was emitted
        TWICE — once with geometry and no IRI, once with an IRI and no geometry.
        Half of every manifest was therefore unlinkable BY CONSTRUCTION, which
        is why the measured join rate sat at exactly 50.0% on every floor of
        every building rather than at some noisy fraction.

        Both halves do agree on ``label`` ("RM001A_room"), so that is the
        fallback key. It is applied only when the normalised label identifies
        exactly ONE space on each side: an ambiguous label merges nothing, since
        fusing two genuinely different rooms would corrupt geometry and identity
        together, which is far worse than leaving a duplicate visible.

        The surviving record keeps the DWG ``zone_id`` because the manifest's
        ``adjacency`` block and every ``adjacent_spaces`` list reference it; the
        PDF id is preserved as an alias so lookups by the old id still resolve.
        """
        pdf_spaces = _drop_duplicated_cad_copies(pdf_spaces)

        dwg_by_zone: Dict[str, Space] = {s.zone_id: s for s in dwg_spaces}
        pdf_by_zone: Dict[str, Space] = {s.zone_id: s for s in pdf_spaces}
        pdf_by_label = _unique_by_label(pdf_spaces)

        merged: List[Space] = []
        pdf_zone_ids_used = set()

        for zone_id, dwg_space in dwg_by_zone.items():
            pdf_space = pdf_by_zone.get(zone_id)
            if pdf_space is None:
                pdf_space = pdf_by_label.get(_norm_label(dwg_space.label))
                if pdf_space is not None and pdf_space.zone_id in pdf_zone_ids_used:
                    pdf_space = None  # already claimed by an earlier DWG space
            if pdf_space:
                pdf_zone_ids_used.add(pdf_space.zone_id)
                # DWG wins for geometry; PDF wins for label if DWG label is generic
                label = dwg_space.label
                if (
                    label.startswith("Zone ")
                    and pdf_space.label
                    and not pdf_space.label.startswith("Zone ")
                ):
                    label = pdf_space.label

                merged.append(
                    Space(
                        id=dwg_space.id,
                        zone_id=zone_id,
                        label=label,
                        aliases=sorted(
                            {*dwg_space.aliases, *pdf_space.aliases, pdf_space.zone_id} - {zone_id}
                        ),
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

        # Append PDF-only spaces — those no DWG space claimed by id OR by label
        for zone_id, pdf_space in pdf_by_zone.items():
            if zone_id not in pdf_zone_ids_used and zone_id not in dwg_by_zone:
                merged.append(pdf_space)

        return merged

    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def list_manifests(self) -> List[Tuple[str, int]]:
        """Return [(building_id, floor)] for the ACTIVE building's manifests.

        The manifest directory is a mounted volume, so a manifest written by an
        earlier occupant of that volume survives a building swap. Listing the
        directory unfiltered served those foreign floors as if they belonged to
        the running building. Only the active building's own identities are
        returned; foreign directories are reported once so the leftovers are
        visible rather than silently ignored.
        """
        found = self._pdf_pipeline.list_manifests()
        try:
            from shared.config import settings

            owned = {c.lower() for c in self._identity_candidates(settings.BUILDING_ID)}
        except Exception:
            return found

        mine = [(bid, floor) for bid, floor in found if str(bid).lower() in owned]
        foreign = {bid for bid, _ in found if str(bid).lower() not in owned}
        if foreign:
            logger.warning(
                f"[registry] ignoring {len(found) - len(mine)} floor-plan manifests from "
                f"{sorted(foreign)} — not owned by the active building "
                f"{settings.BUILDING_ID}; delete them from the mounted volume"
            )
        return mine

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
            import redis.asyncio as aioredis

            from shared.config import settings

            redis = aioredis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}")
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
