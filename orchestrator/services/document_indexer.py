"""
document_indexer.py — T08 of IMPLEMENTATION PLAN V3.

Indexes per-building policy and manual documents (input/<bldg>/documents/)
into Qdrant collection `documents_<bldg>`, chunked at ~500 tokens (~400 words).

Behaviour mirrors capability_indexer:
  - SHA-256 of each file: skip unchanged, rebuild on change
  - Chunk SHA stored in point payload for cross-restart idempotency
  - Degraded status → orchestrator startup not blocked
  - Respects EMBEDDING_PROVIDER (dimension auto-detected from embedder)

Supported formats: .md / .txt (plain text).  PDF support is planned via pdfminer.
Point payload: {text, doc_name, chunk_idx, file_sha, building_id, source_path}

Usage (FastAPI lifespan):
    indexer = DocumentIndexer(qdrant_client, embedding_service)
    results = await indexer.index_all_buildings()
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from shared.building_paths import resolve_building_dir
from shared.utils import get_logger

logger = get_logger(__name__)

_CHUNK_WORDS = 400
_COLLECTION_PREFIX = "documents_"
_SUPPORTED_EXTENSIONS = {".md", ".txt"}
_DOC_NAMESPACE = uuid.UUID("3a7c2e1b-4f5d-6e8a-9b0c-1d2e3f4a5b6c")


@dataclass
class DocIndexResult:
    """Result of indexing documents for a single building."""

    building_id: str
    status: Literal["indexed", "skipped", "degraded", "no_documents"]
    documents: int = 0
    chunks: int = 0
    duration_ms: float = 0.0
    reason: str = ""
    indexed_files: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)


def _chunk_text(text: str, chunk_words: int = _CHUNK_WORDS) -> List[str]:
    """Split text into overlapping chunks of approximately chunk_words words."""
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    step = max(1, int(chunk_words * 0.8))
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_words])
        if chunk.strip():
            chunks.append(chunk.strip())
        i += step
    return chunks


def _read_document(path: Path) -> Optional[str]:
    """Read a document file; returns None on error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"[document_indexer] could not read {path.name}: {e}")
        return None


class DocumentIndexer:
    """Indexes per-building documents into Qdrant `documents_<bldg>` collections.

    Usage:
        indexer = DocumentIndexer(qdrant_client, embedding_service)
        results = await indexer.index_all_buildings()
    """

    def __init__(
        self,
        qdrant_client: Any,
        embedding_service: Any,
        input_root: str = "/app/input",
        collection_prefix: str = _COLLECTION_PREFIX,
    ):
        self._qdrant = qdrant_client
        self._embedder = embedding_service
        self._input_root = Path(input_root)
        self._collection_prefix = collection_prefix

    # ── public API ──────────────────────────────────────────────────────────────

    async def index_all_buildings(self) -> Dict[str, DocIndexResult]:
        """Scan input_root for per-building documents/ folders and index each."""
        results: Dict[str, DocIndexResult] = {}
        if not self._input_root.exists():
            logger.warning(f"[document_indexer] input_root not found: {self._input_root}")
            return results

        # Nested layout: input/<id>/documents/
        for bldg_dir in sorted(self._input_root.iterdir()):
            if not bldg_dir.is_dir():
                continue
            docs_dir = bldg_dir / "documents"
            if not docs_dir.is_dir():
                continue
            building_id = bldg_dir.name
            results[building_id] = await self.index_building(building_id)

        # Flat layout: input/documents/ → index under the active building id.
        from shared.config import settings as _settings

        _active = _settings.BUILDING_ID
        if _active not in results and resolve_building_dir(_active, "documents", self._input_root):
            results[_active] = await self.index_building(_active)

        return results

    async def index_building(self, building_id: str) -> DocIndexResult:
        """Index documents for a single building.  Idempotent; safe to call repeatedly."""
        t0 = time.monotonic()
        docs_dir = resolve_building_dir(building_id, "documents", self._input_root)
        collection_name = f"{self._collection_prefix}{building_id}"

        if docs_dir is None:
            return DocIndexResult(
                building_id=building_id,
                status="no_documents",
                reason=f"no documents/ found for {building_id} (input/<id>/documents or input/documents)",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        doc_paths = [
            p
            for p in sorted(docs_dir.iterdir())
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
        ]
        if not doc_paths:
            return DocIndexResult(
                building_id=building_id,
                status="no_documents",
                reason="documents/ dir exists but contains no .md/.txt files",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Load existing SHA map from Qdrant ────────────────────────────────
        existing_shas = await self._load_existing_shas(collection_name)

        new_points: List[Any] = []
        indexed_files: List[str] = []
        skipped_files: List[str] = []

        for doc_path in doc_paths:
            file_sha = hashlib.sha256(doc_path.read_bytes()).hexdigest()
            if existing_shas.get(doc_path.name) == file_sha:
                logger.info(f"[document_indexer] {building_id}/{doc_path.name}: sha match — skip")
                skipped_files.append(doc_path.name)
                continue

            text = _read_document(doc_path)
            if text is None:
                continue

            chunks = _chunk_text(text)
            if not chunks:
                continue

            try:
                vectors = await self._embedder.embed_batch(chunks)
            except Exception as e:
                logger.error(
                    f"[document_indexer] {building_id}/{doc_path.name}: embedding failed: {e}"
                )
                continue

            from qdrant_client.models import PointStruct

            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                point_id = str(
                    uuid.uuid5(
                        _DOC_NAMESPACE,
                        f"{building_id}:{doc_path.name}:{i}:{file_sha}",
                    )
                )
                new_points.append(
                    PointStruct(
                        id=point_id,
                        vector=vec,
                        payload={
                            "text": chunk,
                            "doc_name": doc_path.stem,
                            "doc_filename": doc_path.name,
                            "chunk_idx": i,
                            "file_sha": file_sha,
                            "building_id": building_id,
                            "source_path": str(doc_path),
                        },
                    )
                )
            indexed_files.append(doc_path.name)

        if not new_points and not indexed_files:
            # All files were skipped (sha match)
            return DocIndexResult(
                building_id=building_id,
                status="skipped",
                documents=len(skipped_files),
                reason="all files sha-match — no rebuild needed",
                skipped_files=skipped_files,
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Rebuild collection when new_points exist ─────────────────────────
        try:
            if new_points:
                # If there are skipped (existing) files too, do partial update:
                # delete stale doc's points, then upsert new ones (simpler to just
                # recreate when any doc changed, since collections are small).
                if skipped_files:
                    await self._delete_docs(collection_name, indexed_files, building_id)
                else:
                    # All files changed or this is first run: full recreate
                    await self._recreate_collection(collection_name)

                await self._upsert_points(collection_name, new_points)
        except Exception as e:
            logger.error(f"[document_indexer] {building_id}: Qdrant write failed: {e}")
            return DocIndexResult(
                building_id=building_id,
                status="degraded",
                reason=f"Qdrant write failed: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        duration_ms = (time.monotonic() - t0) * 1000
        total_docs = len(indexed_files) + len(skipped_files)
        logger.info(
            f"[document_indexer] {building_id}: status=indexed "
            f"docs={len(indexed_files)} chunks={len(new_points)} "
            f"skipped={len(skipped_files)} ({duration_ms:.0f}ms)"
        )
        return DocIndexResult(
            building_id=building_id,
            status="indexed",
            documents=total_docs,
            chunks=len(new_points),
            indexed_files=indexed_files,
            skipped_files=skipped_files,
            duration_ms=duration_ms,
        )

    # ── internal helpers ─────────────────────────────────────────────────────

    async def _load_existing_shas(self, collection_name: str) -> Dict[str, str]:
        """Return {doc_filename: file_sha} for points already in the collection."""
        try:
            existing_names = await self._list_collection_names()
            if collection_name not in existing_names:
                return {}
            shas: Dict[str, str] = {}
            offset = None
            while True:
                result = await self._qdrant.scroll(
                    collection_name=collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                records = result[0] if isinstance(result, tuple) else result.points
                next_offset = result[1] if isinstance(result, tuple) else result.next_page_offset
                for rec in records:
                    payload = rec.payload or {}
                    fname = payload.get("doc_filename")
                    sha = payload.get("file_sha")
                    if fname and sha:
                        shas[fname] = sha
                if not next_offset:
                    break
                offset = next_offset
            return shas
        except Exception as e:
            logger.warning(f"[document_indexer] could not load existing SHAs: {e}")
            return {}

    async def _list_collection_names(self) -> List[str]:
        result = await self._qdrant.get_collections()
        return [c.name for c in result.collections]

    async def _recreate_collection(self, collection_name: str) -> None:
        from qdrant_client.models import Distance, VectorParams

        existing = await self._list_collection_names()
        if collection_name in existing:
            await self._qdrant.delete_collection(collection_name)
        await self._qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=self._embedder.dimension, distance=Distance.COSINE),
        )

    async def _delete_docs(
        self, collection_name: str, doc_filenames: List[str], building_id: str
    ) -> None:
        """Delete all points belonging to specific doc_filenames."""
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        try:
            await self._qdrant.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_filename",
                            match=MatchAny(any=doc_filenames),
                        ),
                        FieldCondition(key="building_id", match={"value": building_id}),
                    ]
                ),
            )
        except Exception as e:
            logger.warning(f"[document_indexer] delete_docs failed: {e}")

    async def _upsert_points(self, collection_name: str, points: List[Any]) -> None:
        if not points:
            return
        # Ensure collection exists (may have been deleted by _delete_docs but not recreated)
        existing = await self._list_collection_names()
        if collection_name not in existing:
            await self._recreate_collection(collection_name)

        batch_size = 100
        for i in range(0, len(points), batch_size):
            await self._qdrant.upsert(
                collection_name=collection_name, points=points[i : i + batch_size]
            )


async def search_documents(
    qdrant_client: Any,
    embedding_service: Any,
    query: str,
    building_id: str,
    top_k: int = 3,
    score_threshold: float = 0.35,
) -> List[Dict[str, Any]]:
    """Search documents collection for a query.  Returns list of {text, doc_name, score}."""
    collection_name = f"{_COLLECTION_PREFIX}{building_id}"
    try:
        vec = await embedding_service.embed(query)
        # Newer Qdrant client uses query_points; older uses search.
        if hasattr(qdrant_client, "query_points"):
            _res = await qdrant_client.query_points(
                collection_name=collection_name,
                query=vec,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
            results = _res.points if hasattr(_res, "points") else _res
        else:
            results = await qdrant_client.search(
                collection_name=collection_name,
                query_vector=vec,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
        return [
            {
                "text": r.payload.get("text", ""),
                "doc_name": r.payload.get("doc_name", ""),
                "doc_filename": r.payload.get("doc_filename", ""),
                "score": r.score,
            }
            for r in results
        ]
    except Exception as e:
        logger.warning(f"[document_indexer] search failed for {building_id}: {e}")
        return []
