"""
floor_plan_pipeline.py — 10-step floor plan ingestion pipeline.

Converts a raw PDF into a canonical FloorPlanManifest (JSON), a rendered
PNG, and a thumbnail.  All steps run sequentially; failures populate
manifest.warnings[] instead of crashing so partial results are still useful.

Steps:
  1.  discover        — find PDFs in /app/input/ matching building pattern
  2.  fingerprint     — SHA-256; skip if manifest already up to date
  3.  render_pages    — PyMuPDF → PNG @ configured DPI
  4.  extract_text    — pdfplumber + coordinate-aware text blocks
  5.  detect_spaces   — regex layer → LLM layer (if enabled)
  6.  classify_types  — rule-based → LLM fallback per ambiguous label
  7.  normalise_ids   — consistent zone_id format per building config
  8.  link_ontology   — match zone IDs to GraphDB IRIs via SPARQL
  9.  embed_and_index — Qdrant upsert, one point per space
  10. write_manifest  — JSON to disk + Redis cache

Public API:
    pipeline = FloorPlanPipeline()
    await pipeline.ingest_all()                   # startup: all buildings
    await pipeline.ingest_file(Path("...pdf"))    # watcher: single file
    manifest = pipeline.load_manifest("abacws", 3)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.floor_plan_config import ABACWS_CONFIG, BuildingConfig
from shared.models import (
    FloorPlanManifest,
    NormalisedBBox,
    NormalisedPoint,
    RenderedImage,
    Space,
)
from shared.utils import get_logger

logger = get_logger(__name__)

GENERATOR_VERSION = "1.0.0"
_DEFAULT_PDF_DIR = Path("/app/input")
_DEFAULT_MANIFEST_DIR = Path("/app/floor_plans")  # separate writable volume
_RENDER_DPI = 200
_THUMB_WIDTH = 400

# ── Prometheus metrics (§15) — graceful degradation if unavailable ─────────────
try:
    from prometheus_client import Counter, Histogram

    _FP_INGESTION_TOTAL = Counter(
        "floor_plan_ingestion_total",
        "Total floor plan ingestion runs",
        ["building", "floor", "outcome"],  # outcome: success | skipped | failed
    )
    _FP_INGESTION_DURATION = Histogram(
        "floor_plan_ingestion_duration_seconds",
        "Floor plan ingestion duration per step",
        ["building", "floor", "step"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
    )
    _FP_MANIFEST_WARNINGS = Counter(
        "floor_plan_manifest_warnings",
        "Number of warnings recorded in floor plan manifests",
        ["building", "floor"],
    )
    _FP_API_REQUESTS = Counter(
        "floor_plan_api_requests_total",
        "Total floor plan API requests",
        ["endpoint", "status"],
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False


def _prom_observe(histogram, labels: dict, value: float) -> None:  # noqa: ANN001
    """Safely record a histogram observation."""
    if _PROM_AVAILABLE:
        try:
            histogram.labels(**labels).observe(value)
        except Exception:  # pragma: no cover
            pass


def _prom_inc(counter, labels: dict, amount: float = 1.0) -> None:  # noqa: ANN001
    """Safely increment a counter."""
    if _PROM_AVAILABLE:
        try:
            counter.labels(**labels).inc(amount)
        except Exception:  # pragma: no cover
            pass

# Facility-type keyword map (used in rule-based classification, step 6)
_FACILITY_KEYWORDS: Dict[str, List[str]] = {
    "toilet": ["toilet", "wc", "w.c.", "bathroom", "restroom", "lavatory", "male", "female"],
    "meeting_room": ["meeting", "conference", "boardroom", "seminar", "breakout"],
    "lab": ["lab", "laboratory", "workshop", "studio", "makers"],
    "classroom": ["classroom", "teaching", "tutorial"],
    "lecture": ["lecture", "auditorium", "theatre", "theater"],
    "kitchen": ["kitchen", "kitchenette", "break room", "breakroom", "coffee"],
    "server_room": ["server", "data centre", "data center", "it room", "comms", "network"],
    "staircase": ["stair", "staircase", "stairwell", "fire escape"],
    "lift": ["lift", "elevator"],
    "storage": ["storage", "store room", "store", "cupboard", "plant room", "plant"],
    "reception": ["reception", "lobby", "entrance", "foyer"],
    "corridor": ["corridor", "hallway", "circulation", "walkway"],
    "office": ["office", "workspace", "workstation", "open plan", "open-plan"],
    "utility": ["utility", "electrical", "mechanical", "maintenance", "riser"],
}


class FloorPlanPipeline:
    """
    Idempotent pipeline that converts PDF floor plans → FloorPlanManifest.
    One instance is shared across the application lifecycle.
    """

    def __init__(
        self,
        pdf_dir: Optional[Path] = None,
        manifest_dir: Optional[Path] = None,
        graphdb_url: Optional[str] = None,
        qdrant_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        llm_extract_enabled: bool = True,
    ) -> None:
        from shared.config import settings

        self._pdf_dir = pdf_dir or _DEFAULT_PDF_DIR
        self._manifest_dir = manifest_dir or _DEFAULT_MANIFEST_DIR
        self._graphdb_url = graphdb_url or getattr(settings, "GRAPHDB_URL", "http://graphdb:7200")
        self._qdrant_url = qdrant_url or getattr(settings, "QDRANT_URL", "http://qdrant:6333")
        self._openai_key = openai_api_key or getattr(settings, "OPENAI_API_KEY", "")
        self._llm_extract_enabled = llm_extract_enabled
        self._redis = None
        self._qdrant_client = None
        self._pdf_pattern = re.compile(
            r"^(?P<building>.+?)\s+floor\s+(?P<floor>\d+)\.pdf$",
            re.IGNORECASE,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def ingest_all(self) -> List[FloorPlanManifest]:
        """Ingest all PDFs found in pdf_dir.  Idempotent."""
        if not self._pdf_dir.exists():
            logger.warning(f"[pipeline] PDF dir not found: {self._pdf_dir}")
            return []
        results: List[FloorPlanManifest] = []
        for pdf_path in sorted(self._pdf_dir.glob("*.pdf")):
            try:
                manifest = await self.ingest_file(pdf_path)
                if manifest:
                    results.append(manifest)
            except Exception as e:
                logger.error(f"[pipeline] Failed to ingest {pdf_path.name}: {e}", exc_info=True)
        return results

    async def ingest_file(self, pdf_path: Path) -> Optional[FloorPlanManifest]:
        """Ingest one PDF through all 10 steps."""
        import time as _time

        t_start = _time.monotonic()

        # Step 1: discover
        m = self._pdf_pattern.match(pdf_path.name)
        if not m:
            logger.debug(f"[pipeline] Skipping non-floor-plan PDF: {pdf_path.name}")
            return None

        building_name = m.group("building")
        building_id = _slugify(building_name)
        floor = int(m.group("floor"))

        cfg = self._load_config(building_id)
        manifest_path = self._manifest_path(building_id, floor)
        warnings: List[str] = []

        _labels = {"building": building_id, "floor": str(floor)}

        logger.info(f"[pipeline] Ingesting {pdf_path.name} → building={building_id}, floor={floor}")

        # Step 2: fingerprint — skip if unchanged
        sha = _sha256_file(pdf_path)
        if manifest_path.exists():
            try:
                existing = FloorPlanManifest.model_validate_json(manifest_path.read_text("utf-8"))
                if existing.source_sha256 == sha:
                    logger.info(f"[pipeline] {pdf_path.name} unchanged — skipping.")
                    _prom_inc(_FP_INGESTION_TOTAL, {**_labels, "outcome": "skipped"})
                    return existing
            except Exception:
                pass  # Corrupt manifest — regenerate

        # Step 3: render pages → PNG + thumbnail
        _t3 = _time.monotonic()
        image_info, render_warnings = await _run_in_executor(
            _render_pdf, pdf_path, self._manifest_dir, building_id, floor, cfg.default_dpi
        )
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "render"}, _time.monotonic() - _t3)
        warnings.extend(render_warnings)
        if image_info is None:
            logger.error(f"[pipeline] Render failed for {pdf_path.name} — aborting.")
            _prom_inc(_FP_INGESTION_TOTAL, {**_labels, "outcome": "failed"})
            return None

        # Step 4: extract text layer
        _t4 = _time.monotonic()
        text_blocks, extract_warnings = await _run_in_executor(
            _extract_text_blocks, pdf_path
        )
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "extract"}, _time.monotonic() - _t4)
        warnings.extend(extract_warnings)

        # Step 5: detect spaces (regex then LLM)
        _t5 = _time.monotonic()
        raw_spaces, detect_warnings = _detect_spaces_regex(text_blocks, building_id, floor, cfg)
        warnings.extend(detect_warnings)

        if self._llm_extract_enabled and cfg.llm_extract_enabled:
            llm_spaces, llm_warnings = await self._detect_spaces_llm(
                text_blocks, building_id, floor, existing_ids={s.zone_id for s in raw_spaces}
            )
            raw_spaces.extend(llm_spaces)
            warnings.extend(llm_warnings)
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "detect_spaces"}, _time.monotonic() - _t5)

        # Step 6: classify types
        raw_spaces = _classify_types(raw_spaces)

        # Step 7: normalise IDs
        raw_spaces = _normalise_ids(raw_spaces, building_id, floor)

        # Step 8: link ontology
        _t8 = _time.monotonic()
        link_warnings = await self._link_ontology(raw_spaces, building_id, floor)
        warnings.extend(link_warnings)
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "link_ontology"}, _time.monotonic() - _t8)

        # Build facilities map
        facilities: Dict[str, List[str]] = {}
        for space in raw_spaces:
            if space.type not in ("unknown", "zone", "corridor"):
                facilities.setdefault(space.type, []).append(space.zone_id)

        # Build ontology_links map
        ontology_links = {
            s.zone_id: s.ontology_iri
            for s in raw_spaces
            if s.ontology_iri
        }

        # Step 3 metadata → RenderedImage model
        png_url = f"/floor-plans/renders/{building_id}/floor_{floor}.png"
        thumb_url = f"/floor-plans/renders/{building_id}/floor_{floor}_thumb.png"
        rendered_image = RenderedImage(
            png_url=png_url,
            thumbnail_url=thumb_url,
            width_px=image_info["width_px"],
            height_px=image_info["height_px"],
            dpi=cfg.default_dpi,
        )

        import urllib.parse

        pdf_url = f"/floor-plans/{urllib.parse.quote(pdf_path.name)}"

        manifest = FloorPlanManifest(
            schema_version="1.0",
            building_id=building_id,
            building_name=building_name,
            floor=floor,
            floor_label=cfg.floor_label(floor),
            source_pdf=pdf_path.name,
            source_sha256=sha,
            generated_at=datetime.utcnow(),
            generator_version=GENERATOR_VERSION,
            page_count=image_info.get("page_count", 1),
            rendered_image=rendered_image,
            pdf_url=pdf_url,
            bounding_box=image_info.get("bounding_box", {}),
            spaces=raw_spaces,
            facilities=facilities,
            ontology_links=ontology_links,
            warnings=warnings,
        )

        # Step 9: embed + index into Qdrant
        _t9 = _time.monotonic()
        await self._embed_and_index(manifest)
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "embed_index"}, _time.monotonic() - _t9)

        # Step 10: write manifest to disk + Redis
        await self._write_manifest(manifest)

        # Emit success metrics
        _prom_inc(_FP_INGESTION_TOTAL, {**_labels, "outcome": "success"})
        _prom_observe(_FP_INGESTION_DURATION, {**_labels, "step": "total"}, _time.monotonic() - t_start)
        if warnings:
            _prom_inc(_FP_MANIFEST_WARNINGS, _labels, amount=len(warnings))

        logger.info(
            f"[floor_plan_pipeline] building={building_id} floor={floor} step=total "
            f"duration_ms={round((_time.monotonic() - t_start) * 1000)} ok=true "
            f"spaces={len(raw_spaces)} warnings={len(warnings)}"
        )
        return manifest


    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def _manifest_path(self, building_id: str, floor: int) -> Path:
        d = self._manifest_dir / building_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"floor_{floor}.manifest.json"

    def load_manifest(self, building_id: str, floor: int) -> Optional[FloorPlanManifest]:
        """Load a manifest from disk (synchronous, hot-path)."""
        p = self._manifest_path(building_id, floor)
        if not p.exists():
            return None
        try:
            return FloorPlanManifest.model_validate_json(p.read_text("utf-8"))
        except Exception as e:
            logger.warning(f"[pipeline] Could not load manifest {p}: {e}")
            return None

    def list_manifests(self) -> List[Tuple[str, int]]:
        """Return [(building_id, floor)] for every manifest on disk."""
        results = []
        if not self._manifest_dir.exists():
            return results
        for bdir in self._manifest_dir.iterdir():
            if bdir.is_dir():
                for mf in bdir.glob("floor_*.manifest.json"):
                    try:
                        floor = int(mf.stem.replace("floor_", "").replace(".manifest", ""))
                        results.append((bdir.name, floor))
                    except ValueError:
                        pass
        return sorted(results)

    async def _write_manifest(self, manifest: FloorPlanManifest) -> None:
        path = self._manifest_path(manifest.building_id, manifest.floor)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        logger.debug(f"[pipeline] Manifest written: {path}")

        # Cache in Redis (best-effort)
        try:
            redis = await self._get_redis()
            if redis:
                key = f"floor_plan:manifest:{manifest.building_id}:{manifest.floor}"
                await redis.set(key, manifest.model_dump_json(), ex=3600)
        except Exception as e:
            logger.debug(f"[pipeline] Redis cache skipped: {e}")

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self, building_id: str) -> BuildingConfig:
        yaml_path = self._pdf_dir / building_id / "building.yaml"
        if yaml_path.exists():
            try:
                return BuildingConfig.from_yaml(yaml_path)
            except Exception as e:
                logger.warning(f"[pipeline] Could not load {yaml_path}: {e}")
        if building_id == "abacws":
            return ABACWS_CONFIG
        return BuildingConfig(building_id=building_id)

    # ── Step 5 LLM space detection ─────────────────────────────────────────────

    async def _detect_spaces_llm(
        self,
        text_blocks: List[Dict[str, Any]],
        building_id: str,
        floor: int,
        existing_ids: set,
    ) -> Tuple[List[Space], List[str]]:
        """Use LLM to extract space labels not captured by regex."""
        warnings: List[str] = []
        if not self._openai_key:
            return [], ["LLM extraction skipped: no OpenAI API key"]

        # Collect text lines not already matched as zone IDs
        lines = [
            b["text"].strip()
            for b in text_blocks
            if b.get("text", "").strip() and len(b["text"].strip()) > 2
        ]
        if not lines:
            return [], []

        # De-duplicate and limit to avoid excessive tokens
        unique_lines = list(dict.fromkeys(lines))[:80]
        prompt = (
            f"You are analysing floor plan text from floor {floor} of the {building_id} building.\n"
            "Below is a list of text labels extracted from the floor plan PDF.\n"
            "For each label that appears to be a room or space name (NOT a zone number, NOT a "
            "page number, NOT a generic word like 'the' or 'of'), output a JSON object with:\n"
            '  {"label": "<original text>", "type": "<space type from: office/lab/meeting_room/'
            'classroom/lecture/toilet/kitchen/server_room/storage/staircase/lift/reception/'
            'corridor/utility/unknown>"}\n'
            "Return ONLY a JSON array. If nothing qualifies, return [].\n\n"
            "Labels:\n" + "\n".join(f"- {l}" for l in unique_lines)
        )
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._openai_key)
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=1200,
                ),
                timeout=20,
            )
            raw_json = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json, flags=re.DOTALL).strip()
            items = json.loads(raw_json)

            spaces: List[Space] = []
            for item in items:
                label = str(item.get("label", "")).strip()
                space_type = str(item.get("type", "unknown"))
                if not label or label.lower() in existing_ids:
                    continue
                zone_id = f"fp.{building_id}.{floor}.{_slugify(label)[:20]}"
                spaces.append(
                    Space(
                        id=f"{building_id}.{zone_id}",
                        zone_id=zone_id,
                        label=label,
                        type=space_type,  # type: ignore[arg-type]
                        source="llm",
                        confidence=0.75,
                    )
                )
            logger.info(f"[pipeline] LLM extracted {len(spaces)} additional spaces on floor {floor}")
            return spaces, []
        except asyncio.TimeoutError:
            warnings.append("LLM space extraction timed out")
            return [], warnings
        except Exception as e:
            warnings.append(f"LLM space extraction failed: {e}")
            return [], warnings

    # ── Step 8 Ontology linking ────────────────────────────────────────────────

    async def _link_ontology(
        self, spaces: List[Space], building_id: str, floor: int
    ) -> List[str]:
        """Query GraphDB to populate ontology_iri on each space."""
        warnings: List[str] = []
        try:
            import httpx

            zone_ids = [s.zone_id for s in spaces if "." in s.zone_id]
            if not zone_ids:
                return []

            sparql = _build_zone_sparql(zone_ids[:30])
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._graphdb_url}/repositories/ontosage/sparql",
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                    content=sparql,
                )
            if resp.status_code != 200:
                warnings.append(f"Ontology linking: GraphDB returned {resp.status_code}")
                return warnings

            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            iri_map: Dict[str, str] = {}
            for b in bindings:
                label = b.get("label", {}).get("value", "")
                iri = b.get("zone", {}).get("value", "")
                if label and iri:
                    iri_map[label] = iri

            linked = 0
            for space in spaces:
                iri = iri_map.get(space.zone_id) or iri_map.get(f"Zone {space.zone_id}")
                if iri:
                    space.ontology_iri = iri
                    linked += 1

            logger.info(
                f"[pipeline] Ontology linking floor {floor}: {linked}/{len(spaces)} spaces linked"
            )
            if linked == 0:
                warnings.append(
                    f"No ontology links found for floor {floor} zones. "
                    "Check GraphDB or run onboard_building.py."
                )
        except Exception as e:
            warnings.append(f"Ontology linking failed: {e}")
        return warnings

    # ── Step 9 Qdrant indexing ─────────────────────────────────────────────────

    async def _embed_and_index(self, manifest: FloorPlanManifest) -> None:
        """Embed each space and upsert into Qdrant floor_plans collection."""
        try:
            client = await self._get_qdrant_client()
            if not client:
                return

            from qdrant_client.models import PointStruct

            texts = [
                f"{s.label} {s.type} floor {manifest.floor} {manifest.building_name}"
                for s in manifest.spaces
            ]
            if not texts:
                return

            embeddings = await self._batch_embed(texts)
            points = []
            for space, emb in zip(manifest.spaces, embeddings):
                pid = int(
                    hashlib.md5(f"{manifest.building_id}.{manifest.floor}.{space.zone_id}".encode()).hexdigest(),
                    16,
                ) % (2**63)
                points.append(
                    PointStruct(
                        id=pid,
                        vector=emb,
                        payload={
                            "building_id": manifest.building_id,
                            "floor": manifest.floor,
                            "floor_label": manifest.floor_label,
                            "space_id": space.id,
                            "zone_id": space.zone_id,
                            "label": space.label,
                            "type": space.type,
                            "tags": space.tags,
                            "ontology_iri": space.ontology_iri,
                            "pdf_url": manifest.pdf_url,
                            "image_url": manifest.rendered_image.png_url,
                            "source": "floor_plan_space",
                        },
                    )
                )

            COLL = "floor_plans"
            await client.upsert(collection_name=COLL, points=points)
            logger.info(
                f"[pipeline] Indexed {len(points)} spaces for "
                f"building={manifest.building_id}, floor={manifest.floor}"
            )
        except Exception as e:
            logger.warning(f"[pipeline] Qdrant indexing failed (non-fatal): {e}")

    # ── Embedding helpers ──────────────────────────────────────────────────────

    async def _batch_embed(self, texts: List[str]) -> List[List[float]]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._openai_key)
            resp = await client.embeddings.create(
                model="text-embedding-3-large",
                input=[t[:512] for t in texts],
            )
            return [item.embedding for item in resp.data]
        except Exception:
            return [_hash_embed(t) for t in texts]

    # ── Redis / Qdrant helpers ─────────────────────────────────────────────────

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from shared.config import settings
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}"
            )
            return self._redis
        except Exception:
            return None

    async def _get_qdrant_client(self):
        if self._qdrant_client is not None:
            return self._qdrant_client
        try:
            from qdrant_client import AsyncQdrantClient, models

            client = AsyncQdrantClient(url=self._qdrant_url)
            existing = await client.get_collections()
            names = {c.name for c in existing.collections}
            if "floor_plans" not in names:
                await client.create_collection(
                    collection_name="floor_plans",
                    vectors_config=models.VectorParams(size=3072, distance=models.Distance.COSINE),
                )
            self._qdrant_client = client
            return client
        except Exception as e:
            logger.debug(f"[pipeline] Qdrant unavailable: {e}")
            return None


# ── Pure helper functions (run in executor so they don't block event loop) ─────


def _render_pdf(
    pdf_path: Path,
    manifest_dir: Path,
    building_id: str,
    floor: int,
    dpi: int,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Render the first page of a PDF to PNG + thumbnail using PyMuPDF."""
    warnings: List[str] = []
    try:
        import fitz  # PyMuPDF

        out_dir = manifest_dir / building_id
        out_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_dir / f"floor_{floor}.png"
        thumb_path = out_dir / f"floor_{floor}_thumb.png"

        doc = fitz.open(str(pdf_path))
        page = doc[0]

        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(png_path))

        # Thumbnail: scale to 400 px wide preserving aspect ratio
        scale = _THUMB_WIDTH / pix.width
        mat_thumb = fitz.Matrix(scale * dpi / 72, scale * dpi / 72)
        pix_thumb = page.get_pixmap(matrix=mat_thumb, alpha=False)
        pix_thumb.save(str(thumb_path))

        rect = page.rect
        info = {
            "width_px": pix.width,
            "height_px": pix.height,
            "page_count": len(doc),
            "bounding_box": {
                "width_pt": rect.width,
                "height_pt": rect.height,
            },
        }
        doc.close()
        logger.info(f"[pipeline] Rendered floor {floor} → {pix.width}×{pix.height}px")
        return info, warnings
    except ImportError:
        warnings.append("PyMuPDF (fitz) not installed — PNG rendering skipped")
        return {"width_px": 0, "height_px": 0, "page_count": 1, "bounding_box": {}}, warnings
    except Exception as e:
        warnings.append(f"PDF rendering failed: {e}")
        return None, warnings


def _extract_text_blocks(
    pdf_path: Path,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Extract text blocks with bounding boxes using PyMuPDF for accuracy."""
    warnings: List[str] = []
    blocks: List[Dict[str, Any]] = []
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        page = doc[0]
        page_w = page.rect.width or 1
        page_h = page.rect.height or 1

        raw_blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
        for b in raw_blocks:
            if b[6] != 0:  # skip image blocks
                continue
            text = b[4].strip().replace("\n", " ")
            if not text:
                continue
            x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
            cx = ((x0 + x1) / 2) / page_w
            cy = ((y0 + y1) / 2) / page_h
            blocks.append(
                {
                    "text": text,
                    "centroid": {"x": min(cx, 1.0), "y": min(cy, 1.0)},
                    "bbox": {
                        "x": x0 / page_w,
                        "y": y0 / page_h,
                        "w": (x1 - x0) / page_w,
                        "h": (y1 - y0) / page_h,
                    },
                }
            )
        doc.close()
        logger.debug(f"[pipeline] Extracted {len(blocks)} text blocks from {pdf_path.name}")
    except ImportError:
        # Fallback: pdfplumber (no coordinates)
        warnings.append("PyMuPDF unavailable — using pdfplumber (no coordinates)")
        try:
            import pdfplumber

            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            blocks.append({"text": line, "centroid": None, "bbox": None})
        except Exception as e2:
            warnings.append(f"Text extraction completely failed: {e2}")
    except Exception as e:
        warnings.append(f"Text extraction failed: {e}")
    return blocks, warnings


def _detect_spaces_regex(
    text_blocks: List[Dict[str, Any]],
    building_id: str,
    floor: int,
    cfg: BuildingConfig,
) -> Tuple[List[Space], List[str]]:
    """Extract zone IDs and facility labels using regex and keyword matching."""
    warnings: List[str] = []
    spaces: List[Space] = []
    seen_ids: set = set()

    zone_re = cfg.zone_id_regex()

    for block in text_blocks:
        text = block.get("text", "").strip()
        if not text:
            continue
        centroid_raw = block.get("centroid")
        bbox_raw = block.get("bbox")

        centroid = (
            NormalisedPoint(x=centroid_raw["x"], y=centroid_raw["y"])
            if centroid_raw
            else None
        )
        bbox = (
            NormalisedBBox(
                x=bbox_raw["x"], y=bbox_raw["y"],
                w=bbox_raw["w"], h=bbox_raw["h"],
            )
            if bbox_raw
            else None
        )

        # Match zone IDs
        for match in zone_re.finditer(text):
            zone_id = match.group(0).strip()
            if zone_id in seen_ids:
                continue
            seen_ids.add(zone_id)
            spaces.append(
                Space(
                    id=f"{building_id}.{zone_id}",
                    zone_id=zone_id,
                    label=f"Zone {zone_id}",
                    type="zone",
                    centroid=centroid,
                    bbox=bbox,
                    source="text_extraction",
                    confidence=0.95,
                )
            )

        # Keyword-based facility detection
        text_lower = text.lower()
        for facility_type, keywords in _FACILITY_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    label = text[:80]
                    if label in seen_ids:
                        break
                    seen_ids.add(label)
                    spaces.append(
                        Space(
                            id=f"{building_id}.fp.{floor}.{_slugify(label)[:20]}",
                            zone_id=f"fp.{floor}.{_slugify(label)[:20]}",
                            label=label,
                            type=facility_type,  # type: ignore[arg-type]
                            centroid=centroid,
                            bbox=bbox,
                            source="text_extraction",
                            confidence=0.80,
                        )
                    )
                    break

    return spaces, warnings


def _classify_types(spaces: List[Space]) -> List[Space]:
    """Rule-based type classification pass for any spaces still typed 'unknown'."""
    for space in spaces:
        if space.type != "unknown":
            continue
        label_lower = space.label.lower()
        for facility_type, keywords in _FACILITY_KEYWORDS.items():
            if any(kw in label_lower for kw in keywords):
                space.type = facility_type  # type: ignore[assignment]
                break
    return spaces


def _normalise_ids(spaces: List[Space], building_id: str, floor: int) -> List[Space]:
    """Ensure every space has a globally unique id using building_id prefix."""
    for space in spaces:
        if not space.id.startswith(building_id):
            space.id = f"{building_id}.{space.zone_id}"
    return spaces


def _build_zone_sparql(zone_ids: List[str]) -> str:
    values = " ".join(f'"{z}"' for z in zone_ids)
    return f"""
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?zone ?label WHERE {{
    ?zone a ?type .
    ?type rdfs:subClassOf* brick:Zone .
    ?zone rdfs:label ?label .
    FILTER(?label IN ({values}))
}} LIMIT 100
"""


# ── Utility functions ──────────────────────────────────────────────────────────


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _hash_embed(text: str, size: int = 3072) -> List[float]:
    h = hashlib.sha256(text.encode()).digest()
    raw = (h * ((size * 4 // len(h)) + 1))[: size * 4]
    floats = list(struct.unpack(f"{size}f", raw))
    max_v = max(abs(v) for v in floats) or 1.0
    return [v / max_v for v in floats]


async def _run_in_executor(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


# ── Module-level singleton ─────────────────────────────────────────────────────
_pipeline: Optional[FloorPlanPipeline] = None


def get_floor_plan_pipeline() -> FloorPlanPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = FloorPlanPipeline()
    return _pipeline
