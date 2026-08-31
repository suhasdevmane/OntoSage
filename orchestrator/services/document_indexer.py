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
from typing import Any, Dict, List, Literal, Optional, Tuple

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
    #: Record-document lifting (V7-T18). Reported alongside the prose counts because a
    #: document that indexed fine as prose and failed to lift is NOT a healthy ingest —
    #: it silently loses the half a question actually needs to compute over.
    lifted_records: int = 0
    lift_failures: List[str] = field(default_factory=list)


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
    """Read a document file, tolerating the encoding it was actually saved in.

    Insisting on UTF-8 loses whole documents silently: a file saved from a Windows
    editor carries cp1252 bytes (an em-dash is 0x97), so the read raised, the
    warning scrolled past, and the document was never indexed — while the ontology
    still named it as the source for a topic. The question then had a document that
    did not exist as far as retrieval was concerned. Falling back keeps the content;
    the replacement pass is last-resort so a stray byte costs one character, not the
    entire file.
    """
    # utf-8-sig first: plain utf-8 does NOT fail on a byte-order mark, it decodes it
    # into a leading ﻿ that then rides along into the first chunk. utf-8-sig
    # reads BOM and non-BOM files alike, so trying it first costs nothing.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            if encoding != "utf-8-sig":
                logger.info(f"[document_indexer] {path.name}: decoded as {encoding}")
            return text
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"[document_indexer] could not read {path.name}: {e}")
            return None
    try:
        logger.warning(f"[document_indexer] {path.name}: undecodable bytes replaced")
        return path.read_text(encoding="utf-8", errors="replace")
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
            # A directory is only a building if a person named it one. Hidden and
            # bookkeeping directories are not: input/.trash holds documents the
            # admin console DELETED, and scanning it created a phantom building
            # whose 24 removed files were embedded into a documents_.trash
            # collection — deleted content, kept and searchable.
            if bldg_dir.name.startswith(".") or bldg_dir.name.startswith("_"):
                logger.debug(f"[document_indexer] skipping non-building directory {bldg_dir.name}")
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

    async def _lift_record_document(
        self, building_id: str, doc_path: Path
    ) -> Tuple[int, List[str]]:
        """Lift a record document into its own named graph (V7-T18).

        Returns (instances lifted, failures). Failures are REPORTED and nothing is
        written: half a permit register answers "how many are open" with a number that
        is confidently short, which is worse than declining. A document with no
        front-matter is not a record document and returns (0, []) — silently, because
        that is the normal case and not a fault.

        The graph is REPLACED rather than appended, so re-ingesting a corrected document
        supersedes it. Appending is how CAVEAT-039 grew reference fan-out to 68.9 and made
        a class listing return one sensor against a true 280.
        """
        try:
            from orchestrator.services.evidence.spatial_facts import active_namespace
            from orchestrator.services.ontology_manager import upload_ttl
            from orchestrator.services.record_documents import lift_document, to_turtle
        except ImportError as exc:  # pragma: no cover - import guard
            logger.debug(f"[document_indexer] record lifting unavailable: {exc}")
            return 0, []

        namespace = active_namespace()
        if not namespace:
            return 0, []

        mappings = Path(__file__).resolve().parents[2] / "ontology" / "record_documents"
        result = lift_document(doc_path, namespace, mappings)

        if result.errors:
            for why in result.errors[:5]:
                logger.warning(f"[document_indexer] {doc_path.name}: NOT lifted — {why}")
            return 0, [f"{doc_path.name}: {result.errors[0]}"]
        if not result.instances:
            return 0, []

        try:
            await upload_ttl(to_turtle(result), result.graph_iri, replace=True)
        except Exception as exc:
            logger.error(f"[document_indexer] {doc_path.name}: graph upload failed: {exc}")
            return 0, [f"{doc_path.name}: upload failed ({exc})"]

        logger.info(
            f"[document_indexer] {doc_path.name}: lifted {result.instances} "
            f"{result.record_type} records into {result.graph_iri}"
        )
        return result.instances, []

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

        # Check the stored vector width BEFORE reading the SHA cache: the cache
        # lives in the collection, so a stale-width collection would otherwise
        # report every file as unchanged and never rebuild.
        await self._ensure_dimension(collection_name)

        # ── Load existing SHA map from Qdrant ────────────────────────────────
        existing_shas = await self._load_existing_shas(collection_name)

        new_points: List[Any] = []
        indexed_files: List[str] = []
        skipped_files: List[str] = []

        lifted_records = 0
        lift_failures: List[str] = []

        for doc_path in doc_paths:
            file_sha = hashlib.sha256(doc_path.read_bytes()).hexdigest()
            if existing_shas.get(doc_path.name) == file_sha:
                logger.info(f"[document_indexer] {building_id}/{doc_path.name}: sha match — skip")
                skipped_files.append(doc_path.name)
                continue

            # A record document is ALSO lifted into triples (V7-T18). The prose path
            # below is untouched: a document that carries no front-matter is not a
            # record document and behaves exactly as it always did.
            n, why = await self._lift_record_document(building_id, doc_path)
            lifted_records += n
            lift_failures.extend(why)

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
            lifted_records=lifted_records,
            lift_failures=lift_failures,
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

    async def _ensure_dimension(self, collection_name: str) -> bool:
        """Drop the collection when it was built by a different embedding model.

        Vectors of different widths cannot be compared, so a collection written at
        384 dimensions is unusable the moment a 1024-dimension model loads. Nothing
        detected that: the SHA cache lives IN the collection, so unchanged documents
        skipped re-indexing, the collection kept its old width, and every search
        failed on a dimension mismatch — silently, since search failures return [].
        Dropping it here forces a rebuild at the new width on the next pass.

        Returns True when the collection was dropped.
        """
        try:
            if collection_name not in await self._list_collection_names():
                return False
            info = await self._qdrant.get_collection(collection_name)
            params = info.config.params.vectors
            current = getattr(params, "size", None)
            wanted = self._embedder.dimension
            if current is None or current == wanted:
                return False
            logger.warning(
                f"[document_indexer] {collection_name} was built at {current} dimensions but the "
                f"embedding model now produces {wanted} — dropping it so it rebuilds. Every "
                f"search against it would otherwise fail on the mismatch."
            )
            await self._qdrant.delete_collection(collection_name)
            return True
        except Exception as e:
            # Never block indexing on the check itself.
            logger.warning(f"[document_indexer] dimension check skipped for {collection_name}: {e}")
            return False

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
    only_document: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search documents collection for a query.  Returns list of {text, doc_name, score}.

    ``only_document`` restricts the search to one file, for when the ontology has
    already named the governing document (``ontosage:documentRef``). That turns
    retrieval from a guess into a lookup: similarity then only ORDERS chunks within
    a document known to be the right one, instead of deciding which document is
    relevant — a decision it makes against a floor calibrated on one corpus and one
    embedding model. The score threshold is dropped for a scoped search for the
    same reason: the question of relevance was already settled by the triple.
    """
    collection_name = f"{_COLLECTION_PREFIX}{building_id}"
    try:
        vec = await embedding_service.embed(query)
        _filter = None
        if only_document:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            _filter = Filter(
                must=[FieldCondition(key="doc_filename", match=MatchValue(value=only_document))]
            )
            score_threshold = None
        # Newer Qdrant client uses query_points; older uses search.
        if hasattr(qdrant_client, "query_points"):
            _res = await qdrant_client.query_points(
                collection_name=collection_name,
                query=vec,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
                query_filter=_filter,
            )
            results = _res.points if hasattr(_res, "points") else _res
        else:
            results = await qdrant_client.search(
                collection_name=collection_name,
                query_vector=vec,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
                query_filter=_filter,
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
