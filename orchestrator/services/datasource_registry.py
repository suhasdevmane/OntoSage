"""
datasource_registry.py — load & index toggleable synthetic data sources.

Phase 0 of tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.

Reads ``input/datasources.yaml`` (flat canonical) or ``input/<id>/datasources.yaml``
(nested fallback) via ``shared/building_paths.py`` and exposes the specs, the
``unlocks`` reverse index, and deterministic point-UUID derivation.

This module is *read-only*: it does not touch GraphDB or MySQL. The enable/disable
engine (Phase 1) and the generator (Phase 2) build on top of it.

Built-in always-on provenance labels for the real stores (ontology, live MySQL,
analytics) live here too, so provenance tagging works even with every synthetic
source switched off.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from shared.building_paths import resolve_building_file
from shared.models import DataSourceSpec, ProvenanceTag
from shared.utils import get_logger

logger = get_logger(__name__)

_PathLike = Union[str, Path]

# Deterministic namespace for point UUIDs (uuid5). Fixed constant -> re-running
# the generator yields the same UUID per (building, source, point).
_UUID_NS = uuid.UUID("6f4c2e1a-9b3d-5f7a-8c21-0d1e2f3a4b5c")

# ── Built-in provenance labels for always-on real stores ───────────────────────
# source_id -> (label, color, synthetic). Referenced by the provenance tagging in
# Phase 3 so the ontology / live-data / compute stores get consistent chips.
BUILTIN_PROVENANCE: Dict[str, ProvenanceTag] = {
    "ontology": ProvenanceTag(
        source_id="ontology",
        label="Building Ontology",
        color="#6B7280",
        synthetic=False,
        store="graphdb",
    ),
    "live_sensors": ProvenanceTag(
        source_id="live_sensors",
        label="Live Sensor Data",
        color="#10B981",
        synthetic=False,
        store="mysql",
    ),
    "analytics": ProvenanceTag(
        source_id="analytics",
        label="Analytics Engine",
        color="#8B5CF6",
        synthetic=False,
        store="compute",
    ),
    "capability_kb": ProvenanceTag(
        source_id="capability_kb",
        label="Capability Knowledge Base",
        color="#F59E0B",
        synthetic=False,
        store="qdrant",
    ),
    "documents": ProvenanceTag(
        source_id="documents",
        label="Document Knowledge Base",
        color="#0EA5E9",
        synthetic=False,
        store="qdrant",
    ),
}


def derive_point_uuid(building_id: str, source_id: str, local: str) -> str:
    """Deterministic UUID for a synthesized point (stable across regenerations)."""
    return str(uuid.uuid5(_UUID_NS, f"{building_id}:{source_id}:{local}"))


class DataSourceRegistry:
    """Loads datasources.yaml and indexes specs for lookup and capability gating."""

    def __init__(self, building_id: str, *, input_root: Optional[_PathLike] = None) -> None:
        self._building_id = building_id
        self._input_root = input_root
        self._specs: Dict[str, DataSourceSpec] = {}

    # ── Loading ─────────────────────────────────────────────────────────────

    def load(self) -> int:
        """Load the curated manifest + the GUI-added overlay. Returns count loaded.

        Reads ``datasources.yaml`` (curated, hand-authored) first, then merges
        ``datasources.custom.yaml`` (GUI-created sources). The curated file wins
        on an id clash so a GUI add can never clobber a curated source.
        """
        self._specs.clear()
        primary = self._find_yaml()
        custom = self._custom_yaml_path()
        loaded_from = []
        for path in (primary, custom):
            if path is None or not Path(path).is_file():
                continue
            n_before = len(self._specs)
            self._merge_file(Path(path))
            loaded_from.append(f"{Path(path).name}(+{len(self._specs) - n_before})")

        if not loaded_from:
            logger.info(
                f"[datasources] no datasources.yaml for building '{self._building_id}' — idle"
            )
            return 0
        logger.info(
            f"[datasources] building='{self._building_id}' loaded {len(self._specs)} source(s) "
            f"from {', '.join(loaded_from)}"
        )
        return len(self._specs)

    def _merge_file(self, path: Path) -> None:
        """Parse one manifest file and merge its sources (existing id wins)."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[datasources] could not parse {path}: {e}")
            return
        entries = data.get("datasources", [])
        if not isinstance(entries, list):
            logger.warning(f"[datasources] {path.name}: top-level 'datasources' must be a list")
            return
        for entry in entries:
            try:
                spec = DataSourceSpec(**entry)
            except Exception as e:
                logger.warning(
                    f"[datasources] invalid source '{(entry or {}).get('id', '?')}': {e}"
                )
                continue
            for pt in spec.points:
                if not pt.uuid:
                    pt.uuid = derive_point_uuid(self._building_id, spec.id, pt.local)
            if spec.id in self._specs:
                logger.warning(f"[datasources] duplicate source id '{spec.id}' — keeping first")
                continue
            self._specs[spec.id] = spec

    # ── Accessors ───────────────────────────────────────────────────────────

    def list(self) -> List[DataSourceSpec]:
        """All loaded sources, in manifest order."""
        return list(self._specs.values())

    def get(self, source_id: str) -> Optional[DataSourceSpec]:
        return self._specs.get(source_id)

    def enabled_ids(self) -> List[str]:
        """Source ids marked enabled in the manifest (runtime state is Phase 1)."""
        return [s.id for s in self._specs.values() if s.enabled]

    def unlocks_index(self) -> Dict[str, str]:
        """Reverse index: capability_tag -> source_id (first source wins on clash)."""
        index: Dict[str, str] = {}
        for spec in self._specs.values():
            for tag in spec.unlocks:
                index.setdefault(tag, spec.id)
        return index

    def provenance_for(self, source_id: str) -> Optional[ProvenanceTag]:
        """Provenance tag for a source (synthetic source or built-in real store)."""
        if source_id in BUILTIN_PROVENANCE:
            return BUILTIN_PROVENANCE[source_id]
        spec = self._specs.get(source_id)
        if spec is None:
            return None
        store = f"mysql:{spec.ts_table}" if spec.ts_table else "reports"
        return ProvenanceTag(
            source_id=spec.id,
            label=spec.provenance_system,
            color=spec.color,
            synthetic=spec.synthetic,
            store=store,
        )

    def provenance_for_table(self, ts_table: str) -> Optional[ProvenanceTag]:
        """Provenance tag for a narrow MySQL table (used by the SQL node in Phase 3)."""
        for spec in self._specs.values():
            if spec.ts_table and spec.ts_table == ts_table:
                return self.provenance_for(spec.id)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_yaml(self) -> Optional[Path]:
        # When an explicit input_root is injected (tests / non-standard mounts),
        # search ONLY there — never fall back to the default input/ dir, or a test
        # against an empty tmp dir would pick up the real seed manifest.
        if self._input_root is not None:
            return resolve_building_file(
                self._building_id, "datasources.yaml", input_root=self._input_root
            )
        return resolve_building_file(self._building_id, "datasources.yaml")

    def _input_dir(self) -> Path:
        """Directory that GUI-added sources are persisted under."""
        if self._input_root is not None:
            return Path(self._input_root)
        for p in (Path("/app/input"), Path("input")):
            if p.exists():
                return p
        return Path("input")

    def _custom_yaml_path(self) -> Path:
        """Overlay file for GUI-created sources (keeps the curated seed pristine)."""
        return self._input_dir() / "datasources.custom.yaml"

    # ── Mutation (GUI create) ─────────────────────────────────────────────────

    def add_source(self, spec_dict: Dict) -> DataSourceSpec:
        """Validate + persist a new source to the custom overlay, then index it.

        Raises ValueError on a validation error or a duplicate id. The new source
        starts disabled; the caller enables/regenerates it via the manager.
        """
        try:
            spec = DataSourceSpec(**spec_dict)
        except Exception as e:
            raise ValueError(f"invalid data source: {e}") from e
        if spec.id in self._specs:
            raise ValueError(f"data source id '{spec.id}' already exists")
        # Deterministic UUIDs so the persisted file, TTL, and MySQL agree.
        for pt in spec.points:
            if not pt.uuid:
                pt.uuid = derive_point_uuid(self._building_id, spec.id, pt.local)

        path = self._custom_yaml_path()
        doc: Dict = {"version": 1, "datasources": []}
        if path.is_file():
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or doc
            except Exception as e:  # pragma: no cover - defensive
                raise ValueError(f"custom manifest unreadable: {e}") from e
        if not isinstance(doc.get("datasources"), list):
            doc["datasources"] = []
        payload = spec.model_dump() if hasattr(spec, "model_dump") else spec.dict()
        doc["datasources"].append(payload)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
        except OSError as e:
            # Most common cause: input/ is mounted read-only. Surface an actionable
            # message instead of a raw 500 so the GUI can tell the operator.
            raise ValueError(
                f"could not persist to {path} ({e}). Is ./input mounted read-write? "
                "Remove ':ro' from the orchestrator's input mount in docker-compose.yml."
            ) from e

        self._specs[spec.id] = spec
        logger.info(f"[datasources] added source '{spec.id}' → {path.name}")
        return spec
