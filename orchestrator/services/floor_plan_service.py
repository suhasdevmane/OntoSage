"""
FloorPlanService — Abacws Building Floor Plan Integration
==========================================================
Discovers PDF floor plan files in /app/input/, extracts their text content
with pdfplumber, indexes them into the Qdrant `floor_plans` collection, and
provides helpers for detecting floor references in user queries and building
contextual floor plan links for the chat response.

Architecture:
  1. On startup → index_all() extracts text from each PDF and upserts into Qdrant
  2. Per-query → detect_floor_from_query() → get_floor_context() / get_pdf_url()
  3. The floor_plan_node in workflow.py uses this service

Qdrant collection : floor_plans
Vector size       : settings.embedding_dimension (provider-dependent — 3072 for
                     OpenAI text-embedding-3-large, 384 for local MiniLM)
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
COLLECTION_NAME = "floor_plans"
CHUNK_SIZE = 400  # words per chunk for Qdrant indexing
CHUNK_OVERLAP = 40

_FLOOR_RE = re.compile(
    r"\b(?:floor|level|storey|story)\s*(\d+)\b",
    re.IGNORECASE,
)
_ZONE_RE = re.compile(
    r"\b(?:zone|room|space)\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_PDF_DIR = Path("/app/input")
_BUILDING_NAME = "Abacws"  # filename prefix for the PDFs

# Base URL for serving floor plan PDFs.
# In production this is the file-server nginx (port 8080).
# Override via STATIC_BASE_URL env var.
_STATIC_BASE_URL = getattr(settings, "STATIC_BASE_URL", "http://localhost:8080")
_FLOOR_PLAN_URL_PREFIX = "/floor-plans"  # served at <STATIC_BASE_URL>/floor-plans/<filename>


class FloorPlanService:
    """
    Manages the lifecycle of floor plan PDFs:
    - discovery    : scans /app/input/ for matching PDF files
    - extraction   : reads text via pdfplumber
    - indexing     : embeds + upserts into Qdrant
    - serving      : provides the HTTP URL for each floor's PDF
    - detection    : regex helpers to find floor/zone references in user queries
    """

    def __init__(self, pdf_dir: Optional[Path] = None) -> None:
        self._pdf_dir = pdf_dir or _PDF_DIR
        self._floor_map: Dict[int, Path] = {}
        self._text_cache: Dict[int, str] = {}
        self._qdrant_client = None
        self._embed_client = None
        self._discover()

    # ── Discovery ─────────────────────────────────────────────────────────

    def _discover(self) -> None:
        """Scan /app/input/ for files matching '<building> floor <N>.pdf'."""
        if not self._pdf_dir.exists():
            logger.warning(f"[FloorPlanService] PDF dir not found: {self._pdf_dir}")
            return
        pattern = re.compile(
            rf"{re.escape(_BUILDING_NAME)}\s+floor\s+(\d+)\.pdf$",
            re.IGNORECASE,
        )
        for path in self._pdf_dir.glob("*.pdf"):
            m = pattern.match(path.name)
            if m:
                floor_num = int(m.group(1))
                self._floor_map[floor_num] = path
        if self._floor_map:
            logger.info(
                f"[FloorPlanService] Discovered floors: {sorted(self._floor_map.keys())}"
            )
        else:
            logger.warning(
                f"[FloorPlanService] No floor plan PDFs found in {self._pdf_dir}"
            )

    # ── Text extraction ────────────────────────────────────────────────────

    def get_available_floors(self) -> List[int]:
        return sorted(self._floor_map.keys())

    def get_pdf_path(self, floor: int) -> Optional[Path]:
        return self._floor_map.get(floor)

    def get_pdf_text(self, floor: int) -> str:
        """Extract and cache the full text from a floor plan PDF."""
        if floor in self._text_cache:
            return self._text_cache[floor]
        path = self.get_pdf_path(floor)
        if path is None:
            return ""
        try:
            import pdfplumber

            text_parts: List[str] = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
            full_text = "\n".join(text_parts).strip()
            self._text_cache[floor] = full_text
            logger.info(
                f"[FloorPlanService] Extracted {len(full_text)} chars from Floor {floor} PDF"
            )
            return full_text
        except Exception as e:
            logger.error(
                f"[FloorPlanService] Failed to extract text from Floor {floor}: {e}"
            )
            return ""

    def get_pdf_url(self, floor: int, absolute: bool = False) -> str:
        """Return the HTTP URL for the floor's PDF file.

        By default returns a relative path (``/floor-plans/<filename>``)
        that the frontend resolves.  Pass ``absolute=True`` to get a
        fully-qualified URL using ``STATIC_BASE_URL`` (suitable for chat
        markdown links).
        """
        path = self._floor_map.get(floor)
        if path:
            # URL-encode the filename so spaces in "Abacws floor 1.pdf" work
            encoded_name = urllib.parse.quote(path.name)
        else:
            encoded_name = f"floor-{floor}.pdf"

        rel = f"{_FLOOR_PLAN_URL_PREFIX}/{encoded_name}"
        if absolute:
            base = _STATIC_BASE_URL.rstrip("/")
            return f"{base}{rel}"
        return rel

    def get_floor_summary(self, floor: int, max_chars: int = 1500) -> str:
        """Return a truncated excerpt of floor plan text suitable for LLM context."""
        text = self.get_pdf_text(floor)
        if not text:
            return f"Floor plan text for Floor {floor} is not available."
        return text[:max_chars].strip() + ("…" if len(text) > max_chars else "")

    # ── Query helpers ──────────────────────────────────────────────────────

    def detect_floor_from_query(self, query: str) -> Optional[int]:
        """Return the first floor number mentioned in *query*, or None."""
        m = _FLOOR_RE.search(query)
        if m:
            floor = int(m.group(1))
            if floor in self._floor_map:
                return floor
            # Floor not in our map — still return it (may be valid)
            return floor if 1 <= floor <= 10 else None
        return None

    def detect_zone_from_query(self, query: str) -> Optional[str]:
        """Return the first zone/room identifier mentioned in *query*, or None."""
        m = _ZONE_RE.search(query)
        return m.group(0).strip() if m else None

    def detect_all_floors_from_query(self, query: str) -> List[int]:
        """Return all floor numbers mentioned in *query* that we have PDFs for."""
        found: List[int] = []
        for m in _FLOOR_RE.finditer(query):
            floor = int(m.group(1))
            if floor in self._floor_map and floor not in found:
                found.append(floor)
        return found

    def is_floor_plan_query(self, query: str) -> bool:
        """Heuristic: is this query likely asking for a floor plan?"""
        keywords = (
            "floor plan",
            "layout",
            "map",
            "floorplan",
            "where is",
            "locate",
            "where am i",
            "show me floor",
            "see floor",
            "floor map",
            "room layout",
            "building map",
        )
        q_lower = query.lower()
        return any(kw in q_lower for kw in keywords) or bool(_FLOOR_RE.search(query))

    def get_zones_for_floor(self, floor: int) -> List[str]:
        """
        Return a sorted list of zone identifiers known to be on *floor*.

        Zone IDs in the Abacws ontology follow the pattern ``<floor>.<nn>``
        (e.g. zones on floor 5 are ``5.01``, ``5.02`` … ``5.28``).

        This method derives zone numbers purely from the floor number
        (no live SPARQL needed) by checking which well-known zone IDs
        are consistent with the floor.  If Qdrant has indexed floor plan
        text, we also mine it for room/zone numbers.
        """
        # Derive from indexed text first (if available)
        zones: List[str] = []
        text = self.get_pdf_text(floor)
        if text:
            # Match patterns like 5.01, 5.12, 5.28 in the PDF text
            zone_pattern = re.compile(rf"\b{floor}\.(\d{{2}})\b")
            found = set(zone_pattern.findall(text))
            zones = sorted(f"{floor}.{n}" for n in found)

        # Fallback: return a safe generic set (zones typically go up to ~28 per floor)
        if not zones:
            zones = [f"{floor}.{n:02d}" for n in range(1, 15)]

        return zones

    def build_disambiguation_prompt(
        self, floor: int, zones: Optional[List[str]] = None
    ) -> str:
        """
        Build a markdown response that shows the floor plan PDF link and
        asks the user to specify which zone they want data for.

        Uses absolute PDF URL so the link works in Open WebUI / any chat client.
        """
        pdf_url = self.get_pdf_url(floor, absolute=True)
        if zones is None:
            zones = self.get_zones_for_floor(floor)

        lines = [
            f"## \U0001f3e2 Floor {floor} \u2014 {_BUILDING_NAME} Building",
            "",
            f"\U0001f4c4 **[Open Floor {floor} Plan (PDF)]({pdf_url})**",
            "",
            "I've pulled up the floor plan for you. "
            "Use the PDF to locate the room or zone you're interested in.",
            "",
        ]

        if zones:
            zone_list = ", ".join(f"**{z}**" for z in zones[:20])
            lines += [
                f"**Known zones on Floor {floor}:** {zone_list}",
                "",
                "\U0001f4ac Which zone or room would you like sensor data for?  "
                "(e.g. *\"zone 5.12\"* or just *\"5.12\"*)",
            ]
        else:
            lines.append(
                "\U0001f4ac Which room or zone on Floor "
                f"{floor} are you interested in?"
            )

        return "\n".join(lines)

    # ── Qdrant indexing ────────────────────────────────────────────────────

    async def _get_qdrant_client(self):
        if self._qdrant_client is not None:
            return self._qdrant_client
        try:
            from qdrant_client import AsyncQdrantClient, models

            embed_dim = settings.embedding_dimension
            client = AsyncQdrantClient(url=settings.QDRANT_URL)
            existing = await client.get_collections()
            names = {c.name for c in existing.collections}
            if COLLECTION_NAME not in names:
                await client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=embed_dim,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(
                    f"[FloorPlanService] Created Qdrant collection: {COLLECTION_NAME}"
                )
            else:
                # A prior run under a different EMBEDDING_PROVIDER may have sized
                # this collection differently (e.g. 3072 for OpenAI vs. 384 for
                # local MiniLM) — recreate rather than silently upserting
                # mismatched-dimension vectors, which Qdrant would reject.
                info = await client.get_collection(COLLECTION_NAME)
                existing_size = info.config.params.vectors.size
                if existing_size != embed_dim:
                    logger.warning(
                        f"[FloorPlanService] '{COLLECTION_NAME}' collection has dim "
                        f"{existing_size}, expected {embed_dim} (EMBEDDING_PROVIDER "
                        "changed) — recreating"
                    )
                    await client.delete_collection(COLLECTION_NAME)
                    await client.create_collection(
                        collection_name=COLLECTION_NAME,
                        vectors_config=models.VectorParams(
                            size=embed_dim, distance=models.Distance.COSINE
                        ),
                    )
            self._qdrant_client = client
            return client
        except Exception as e:
            logger.error(f"[FloorPlanService] Qdrant init failed: {e}")
            return None

    async def _embed(self, texts: List[str]) -> List[List[float]]:
        """Embed via the configured provider (settings.EMBEDDING_PROVIDER — local
        sentence-transformers or OpenAI), falling back to a deterministic
        pseudo-embedding if the provider call fails."""
        try:
            if self._embed_client is None:
                from orchestrator.services.embedding_service import EmbeddingService

                self._embed_client = EmbeddingService()
            return await self._embed_client.embed_batch(texts)
        except Exception as e:
            logger.warning(
                f"[FloorPlanService] Embedding failed ({e}), using hash fallback"
            )
            import struct

            dim = settings.embedding_dimension
            result = []
            for text in texts:
                h = hashlib.sha256(text.encode()).digest()
                raw = (h * ((dim * 4 // len(h)) + 1))[: dim * 4]
                floats = list(struct.unpack(f"{dim}f", raw))
                # Normalise to [-1, 1]
                max_v = max(abs(v) for v in floats) or 1.0
                result.append([v / max_v for v in floats])
            return result

    @staticmethod
    def _chunk_text(
        text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
    ) -> List[str]:
        words = text.split()
        chunks: List[str] = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i : i + chunk_size])
            chunks.append(chunk)
            i += chunk_size - overlap
        return chunks

    async def _floor_already_indexed(self, client, floor: int) -> bool:
        """Return True if Qdrant already holds at least one point for this floor."""
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            result = await client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[FieldCondition(key="floor", match=MatchValue(value=floor))]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
            return bool(result[0])
        except Exception:
            return False

    async def index_all(self) -> None:
        """Extract, embed, and upsert all floor plan PDFs into Qdrant. Idempotent.

        PDF text extraction (pdfplumber) is CPU/IO-bound; it runs in a thread-pool
        executor so the asyncio event loop stays responsive during indexing.
        """
        import asyncio

        if not self._floor_map:
            logger.info("[FloorPlanService] No floor plans to index.")
            return

        client = await self._get_qdrant_client()
        if client is None:
            logger.warning("[FloorPlanService] Qdrant unavailable — skipping indexing.")
            return

        from qdrant_client.models import PointStruct

        for floor, path in sorted(self._floor_map.items()):
            try:
                # Skip floors that are already in Qdrant (e.g. after container restart)
                if await self._floor_already_indexed(client, floor):
                    logger.debug(
                        f"[FloorPlanService] Floor {floor} already indexed — skipping."
                    )
                    continue

                # Run blocking pdfplumber extraction in a thread so we don't stall the loop
                text = await asyncio.to_thread(self.get_pdf_text, floor)
                if not text:
                    continue
                chunks = self._chunk_text(text)
                embeddings = await self._embed(chunks)
                points = []
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                    point_id = int(
                        hashlib.md5(  # non-security: deterministic Qdrant point ID
                            f"floor-{floor}-chunk-{i}".encode(), usedforsecurity=False
                        ).hexdigest(),
                        16,
                    ) % (2**63)
                    points.append(
                        PointStruct(
                            id=point_id,
                            vector=emb,
                            payload={
                                "floor": floor,
                                "chunk_index": i,
                                "text": chunk,
                                "source": "floor_plan",
                                "building": _BUILDING_NAME,
                                "pdf_url": self.get_pdf_url(floor),
                            },
                        )
                    )
                await client.upsert(collection_name=COLLECTION_NAME, points=points)
                logger.info(
                    f"[FloorPlanService] Indexed Floor {floor}: {len(points)} chunks → Qdrant"
                )
            except Exception as e:
                logger.error(f"[FloorPlanService] Indexing floor {floor} failed: {e}")

    async def search_floor_context(
        self, query: str, floor: Optional[int] = None, top_k: int = 3
    ) -> str:
        """
        Semantic search over indexed floor plan text.
        Returns the top matching chunks as a single string for LLM context.
        """
        client = await self._get_qdrant_client()
        if client is None:
            return ""
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            embeddings = await self._embed([query])
            query_vector = embeddings[0]
            search_filter = None
            if floor is not None:
                search_filter = Filter(
                    must=[FieldCondition(key="floor", match=MatchValue(value=floor))]
                )
            results = await client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=top_k,
            )
            if not results:
                return ""
            return "\n---\n".join(r.payload.get("text", "") for r in results)
        except Exception as e:
            logger.warning(f"[FloorPlanService] Qdrant search failed: {e}")
            return ""

    def build_floor_plan_response(
        self, floor: int, zone: Optional[str] = None, base_url: str = ""
    ) -> str:
        """
        Build a formatted markdown response block including the floor plan link.
        Used by _floor_plan_node in workflow.py when the zone is already known.
        """
        pdf_url = self.get_pdf_url(floor, absolute=True)

        lines = [
            f"## \U0001f3e2 Floor {floor} \u2014 {_BUILDING_NAME} Building",
            "",
            f"\U0001f4c4 **[Open Floor {floor} Plan (PDF)]({pdf_url})**",
            "",
        ]
        if zone:
            lines += [
                f"You mentioned **{zone}**.",
                f"Use the floor plan above to locate it on Floor {floor}.",
                "",
            ]
        summary = self.get_floor_summary(floor, max_chars=800)
        if summary:
            lines += [
                "**Floor plan text extract:**",
                "```",
                summary,
                "```",
                "",
            ]
        lines += [
            "\U0001f4ac *Would you like to:*",
            "- See **live sensor data** for a specific zone on this floor?",
            "- Get an **air quality or temperature report** for this floor?",
            "- Compare floors? Just ask!",
        ]
        return "\n".join(lines)


    # ── Manifest-aware methods (Phase 9) ─────────────────────────────────────

    def get_manifest(
        self, floor: int, building_id: str
    ) -> Optional[Any]:
        """
        Return the FloorPlanManifest for a floor, or None if not yet generated.
        Delegates to the pipeline's disk-based manifest store.
        """
        try:
            from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

            return get_floor_plan_pipeline().load_manifest(building_id, floor)
        except Exception as e:
            logger.warning(f"[FloorPlanService] get_manifest failed: {e}")
            return None

    def get_all_manifests(
        self, building_id: str
    ) -> Dict[int, Any]:
        """Return {floor: manifest} for all available manifests of a building."""
        try:
            from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

            pipeline = get_floor_plan_pipeline()
            return {
                fl: pipeline.load_manifest(bid, fl)
                for bid, fl in pipeline.list_manifests()
                if bid == building_id
            }
        except Exception as e:
            logger.warning(f"[FloorPlanService] get_all_manifests failed: {e}")
            return {}

    def search_spaces(
        self,
        query: str,
        building_id: str,
        floor: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for spaces by label / type across all floors (or one floor).
        Returns a list of dicts: {floor, floor_label, space_id, zone_id, label,
        type, pdf_url, image_url, score}.
        """
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        manifests = self.get_all_manifests(building_id)
        for fl, manifest in manifests.items():
            if manifest is None:
                continue
            if floor is not None and fl != floor:
                continue
            for space in manifest.spaces:
                score = 0
                if query_lower in space.label.lower():
                    score += 3
                if query_lower in space.type.lower():
                    score += 2
                if any(query_lower in tag.lower() for tag in space.tags):
                    score += 1
                # Also match zone_id exactly
                if query_lower == space.zone_id.lower():
                    score += 5
                if score > 0:
                    results.append(
                        {
                            "floor": fl,
                            "floor_label": manifest.floor_label,
                            "space_id": space.id,
                            "zone_id": space.zone_id,
                            "label": space.label,
                            "type": space.type,
                            "tags": space.tags,
                            "ontology_iri": space.ontology_iri,
                            "pdf_url": self.get_pdf_url(fl, absolute=True),
                            "image_url": getattr(manifest.rendered_image, "png_url", ""),
                            "score": score,
                        }
                    )

        results.sort(key=lambda r: (-r["score"], r["floor"]))
        return results

    def get_facilities_by_type(
        self, facility_type: str, building_id: str
    ) -> List[Dict[str, Any]]:
        """Return all spaces of a given type across all floors."""
        return self.search_spaces(facility_type, building_id=building_id)

    def get_building_overview_markdown(
        self, building_id: str
    ) -> str:
        """Return a markdown building overview card per floor (manifest-based)."""
        manifests = self.get_all_manifests(building_id)
        if not manifests:
            # Fall back to PDF-based overview
            floors = self.get_available_floors()
            if not floors:
                return "No floor plans available."
            lines = [f"## 🏢 {_BUILDING_NAME} Building — Floor Overview", ""]
            for fl in floors:
                lines.append(f"📄 [Floor {fl}]({self.get_pdf_url(fl, absolute=True)})")
            return "\n".join(lines)

        lines = [f"## 🏢 {_BUILDING_NAME} Building — Floor Overview", ""]
        for fl in sorted(manifests.keys()):
            manifest = manifests[fl]
            if not manifest:
                continue
            pdf_url = self.get_pdf_url(fl, absolute=True)
            floor_label = manifest.floor_label

            type_counts: Dict[str, int] = {}
            for space in manifest.spaces:
                type_counts[space.type] = type_counts.get(space.type, 0) + 1

            zone_count = type_counts.pop("zone", 0)
            summary = ", ".join(
                f"{cnt} {t.replace('_', ' ')}"
                for t, cnt in sorted(type_counts.items())
                if cnt > 0
            )
            lines.append(f"### [{floor_label} 📄]({pdf_url})")
            if summary:
                lines.append(f"**Spaces:** {summary}")
            if zone_count:
                lines.append(f"**Sensor zones:** {zone_count}")
            lines.append("")
        return "\n".join(lines)

    def suggest_floor_plan_link(
        self, zone_id: str, building_id: str
    ) -> str:
        """
        Given a zone_id like '5.12', return a small markdown footer linking
        to the floor plan.  Used to append a floor plan hint to SPARQL / SQL
        responses that resolve to a known zone.
        """
        try:
            floor = int(zone_id.split(".")[0])
        except (ValueError, IndexError):
            return ""

        manifest = self.get_manifest(floor, building_id)
        if manifest:
            image_url = manifest.rendered_image.png_url
            floor_label = manifest.floor_label
            pdf_url = self.get_pdf_url(floor, absolute=True)
        elif floor in self._floor_map:
            floor_label = "Ground Floor" if floor == 0 else f"Floor {floor}"
            pdf_url = self.get_pdf_url(floor, absolute=True)
            image_url = None
        else:
            return ""

        img_part = f" — [🖼 View image]({image_url})" if image_url else ""
        return (
            f"\n\n---\n"
            f"📍 *Zone `{zone_id}` is on **{floor_label}**. "
            f"[📄 View Floor Plan]({pdf_url}){img_part}*"
        )


# ── Module-level singleton ─────────────────────────────────────────────────
floor_plan_service = FloorPlanService()
