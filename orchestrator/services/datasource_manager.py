"""
datasource_manager.py — enable/disable engine for toggleable data sources.

Phase 1 of tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.

Enabling a source PUTs its UUID-keyed Brick point triples into a dedicated
GraphDB named graph (``urn:ontosage:ds:<id>``); disabling clears that graph. The
named graph IS the on/off switch — when absent, SPARQL cannot resolve the
source's UUIDs, so the downstream SQL step never runs and the capability is
gated with no special-casing in the query path.

Activation state is persisted to a small JSON file (mirrors the ttl_uploader
cache pattern) so it survives restarts and can be read on the router hot path.
GraphDB I/O is injectable (``client=``) so the engine is fully unit-testable
offline.

The point-triple TTL matches the canonical pattern used by the existing abacws
sensors and scripts/generate_timeseries_extension.py (dual
``ashrae:``/``ref:hasExternalReference`` → ``ref:TimeseriesReference`` with
``ref:hasTimeseriesId`` + ``ref:storedAt``), so the SPARQL agent resolves
synthetic UUIDs exactly as it does real ones.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _url_quote

from orchestrator.services.datasource_registry import DataSourceRegistry
from shared.models import DataSourceSpec
from shared.utils import get_logger

logger = get_logger(__name__)

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]

_STATE_SEARCH_PATHS = [
    Path("/app/volumes/artifacts/.datasource_state.json"),
    Path("volumes/artifacts/.datasource_state.json"),
]


def _resolve_state_path() -> Path:
    for p in _STATE_SEARCH_PATHS:
        if p.parent.exists():
            return p
    return _STATE_SEARCH_PATHS[-1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataSourceManager:
    """Loads sources, toggles them in GraphDB, and persists activation state."""

    def __init__(
        self,
        building_id: str,
        registry: DataSourceRegistry,
        *,
        graphdb_url: Optional[str] = None,
        repository: Optional[str] = None,
        building_namespace: Optional[str] = None,
        state_path: Optional[Path] = None,
        client: Optional[Any] = None,
        synthetic_service: Optional[Any] = None,
    ) -> None:
        self._building_id = building_id
        self._registry = registry
        self._graphdb_url = graphdb_url
        self._repository = repository
        self._bldg_ns = building_namespace
        self._state_path = state_path or _resolve_state_path()
        self._client = client  # injectable async HTTP client (httpx-compatible)
        self._state: Dict[str, Dict[str, Any]] = self._load_state()
        self._synth = synthetic_service  # lazily created SyntheticDataService

    def _synthetic(self) -> Any:
        if self._synth is None:
            from orchestrator.services.synthetic import SyntheticDataService

            self._synth = SyntheticDataService()
        return self._synth

    # ── Settings resolution (lazy) ────────────────────────────────────────────

    def _resolve_settings(self) -> None:
        if self._graphdb_url and self._repository and self._bldg_ns:
            return
        from shared.config import settings

        self._graphdb_url = self._graphdb_url or settings.GRAPHDB_URL
        self._repository = self._repository or settings.GRAPHDB_REPOSITORY
        self._bldg_ns = self._bldg_ns or settings.BUILDING_NAMESPACE

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if not self._state_path.exists():
            return {}
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[datasources] could not read state {self._state_path}: {e}")
            return {}

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[datasources] could not persist state {self._state_path}: {e}")

    def is_enabled(self, source_id: str) -> bool:
        """True if the source is enabled at runtime (state overrides manifest default)."""
        entry = self._state.get(source_id)
        if entry is not None:
            return bool(entry.get("enabled"))
        spec = self._registry.get(source_id)
        return bool(spec.enabled) if spec else False

    def enabled_ids(self) -> List[str]:
        return [s.id for s in self._registry.list() if self.is_enabled(s.id)]

    # ── TTL construction ──────────────────────────────────────────────────────

    def build_point_ttl(self, spec: DataSourceSpec) -> str:
        """Turtle registering the source's points as UUID-keyed Brick timeseries points.

        Delegates to the single canonical builder (brick_ttl) so the syntax is
        identical to the hand-authored bldg1 ontology.
        """
        self._resolve_settings()
        from orchestrator.services.brick_ttl import points_document

        table = spec.ts_table or "database1"
        pts = [
            {
                "local": p.local,
                "brick_class": p.brick_class,
                "location": p.location,
                "uuid": p.uuid,
                "stored_at": table,
                "unit": p.unit,
                "label": p.label,
            }
            for p in spec.points
        ]
        return points_document(
            self._bldg_ns,
            pts,
            header=f"Data source '{spec.id}' — auto-generated by DataSourceManager. Do not edit.",
        )

    # ── GraphDB I/O ────────────────────────────────────────────────────────────

    def _graph_endpoint(self, graph_uri: str) -> str:
        base = (self._graphdb_url or "").rstrip("/")
        return (
            f"{base}/repositories/{self._repository}"
            f"/rdf-graphs/service?graph={_url_quote(graph_uri, safe='')}"
        )

    async def _put_graph(self, graph_uri: str, ttl: str) -> bool:
        if _httpx is None:
            logger.warning("[datasources] httpx not installed — cannot reach GraphDB")
            return False
        endpoint = self._graph_endpoint(graph_uri)
        owns = self._client is None
        client = self._client or _httpx.AsyncClient(timeout=60.0)
        try:
            resp = await client.put(
                endpoint, content=ttl.encode("utf-8"), headers={"Content-Type": "text/turtle"}
            )
            if resp.status_code in (200, 204):
                return True
            logger.warning(
                f"[datasources] PUT <{graph_uri}> failed HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return False
        except Exception as e:  # pragma: no cover - network
            logger.warning(f"[datasources] PUT <{graph_uri}> error: {e}")
            return False
        finally:
            if owns:
                await client.aclose()

    async def _clear_graph(self, graph_uri: str) -> bool:
        if _httpx is None:
            logger.warning("[datasources] httpx not installed — cannot reach GraphDB")
            return False
        endpoint = self._graph_endpoint(graph_uri)
        owns = self._client is None
        client = self._client or _httpx.AsyncClient(timeout=60.0)
        try:
            resp = await client.delete(endpoint)
            # 200/204 = cleared; 404 = graph never existed (idempotent success)
            if resp.status_code in (200, 204, 404):
                return True
            logger.warning(
                f"[datasources] CLEAR <{graph_uri}> failed HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
            return False
        except Exception as e:  # pragma: no cover - network
            logger.warning(f"[datasources] CLEAR <{graph_uri}> error: {e}")
            return False
        finally:
            if owns:
                await client.aclose()

    # ── Public toggle API ──────────────────────────────────────────────────────

    async def enable(self, source_id: str) -> Dict[str, Any]:
        """Load the source's triples into its named graph and mark it enabled."""
        spec = self._registry.get(source_id)
        if spec is None:
            return {"ok": False, "source_id": source_id, "error": "unknown source"}

        self._resolve_settings()
        graph = spec.graph_uri()
        ttl = self.build_point_ttl(spec)
        # A source with no points (e.g. text_reports) still toggles on; there is
        # simply nothing to register in the graph.
        ok = True
        if spec.points:
            ok = await self._put_graph(graph, ttl)

        if ok:
            self._state[source_id] = {
                "enabled": True,
                "last_enabled_at": _now_iso(),
                "points": len(spec.points),
                "graph": graph,
            }
            self._save_state()
        return {
            "ok": ok,
            "source_id": source_id,
            "enabled": ok,
            "points": len(spec.points),
            "graph": graph,
        }

    async def disable(self, source_id: str) -> Dict[str, Any]:
        """Clear the source's named graph and mark it disabled."""
        spec = self._registry.get(source_id)
        if spec is None:
            return {"ok": False, "source_id": source_id, "error": "unknown source"}

        self._resolve_settings()
        graph = spec.graph_uri()
        ok = True
        if spec.points:
            ok = await self._clear_graph(graph)

        if ok:
            entry = self._state.get(source_id, {})
            entry.update({"enabled": False, "last_disabled_at": _now_iso()})
            self._state[source_id] = entry
            self._save_state()
        return {"ok": ok, "source_id": source_id, "enabled": False, "graph": graph}

    # ── Synthetic data generation ───────────────────────────────────────────────

    def preview(self, source_id: str, *, limit: int = 48) -> Dict[str, Any]:
        """Sample the generated series without writing to the DB."""
        spec = self._registry.get(source_id)
        if spec is None:
            return {"ok": False, "source_id": source_id, "error": "unknown source"}
        try:
            data = self._synthetic().preview(spec, limit=limit)
            data["ok"] = True
            return data
        except Exception as e:
            return {"ok": False, "source_id": source_id, "error": str(e)}

    def regenerate(self, source_id: str) -> Dict[str, Any]:
        """Generate + load the source's synthetic readings into its narrow table."""
        spec = self._registry.get(source_id)
        if spec is None:
            return {"ok": False, "source_id": source_id, "error": "unknown source"}
        try:
            result = self._synthetic().regenerate(spec)
        except Exception as e:
            return {"ok": False, "source_id": source_id, "error": str(e)}
        if result.get("ok"):
            entry = self._state.get(source_id, {})
            entry["last_generated_at"] = _now_iso()
            entry["row_count"] = result.get("rows", 0)
            self._state[source_id] = entry
            self._save_state()
        return result

    def create(self, spec_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new data source from the GUI (persists to the custom overlay)."""
        try:
            spec = self._registry.add_source(spec_dict)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "source_id": spec.id, "points": len(spec.points)}

    # ── Status view for the admin API ───────────────────────────────────────────

    def status(self) -> List[Dict[str, Any]]:
        """Serializable status of every source (for GET /api/v1/datasources)."""
        out: List[Dict[str, Any]] = []
        for spec in self._registry.list():
            st = self._state.get(spec.id, {})
            out.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "modality": spec.modality,
                    "kind": spec.kind,
                    "enabled": self.is_enabled(spec.id),
                    "synthetic": spec.synthetic,
                    "provenance_system": spec.provenance_system,
                    "color": spec.color,
                    "ts_table": spec.ts_table,
                    "unlocks": spec.unlocks,
                    "points": len(spec.points),
                    "row_count": st.get("row_count"),
                    "last_enabled_at": st.get("last_enabled_at"),
                    "last_generated_at": st.get("last_generated_at"),
                }
            )
        return out
