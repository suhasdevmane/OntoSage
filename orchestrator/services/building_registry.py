"""
building_registry.py — Discovers and caches per-building configurations.

At startup the registry scans /app/input/ for:
  - Files matching the PDF filename pattern   → registers a building
  - /app/input/<building_id>/building.yaml    → overrides defaults for that building

Buildings are keyed by building_id (e.g. "abacws", "cardiff_eng").

Usage:
    registry = BuildingRegistry(pdf_dir=Path("/app/input"))
    registry.scan()
    cfg = registry.get("abacws")   # → BuildingConfig
    all_ids = registry.building_ids()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from shared.floor_plan_config import BuildingConfig, default_config
from shared.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_PDF_PATTERN = re.compile(
    r"^(?P<building>.+?)\s+floor\s+(?P<floor>\d+)\.pdf$",
    re.IGNORECASE,
)


class BuildingRegistry:
    """
    Discovers buildings from PDF filenames and building.yaml overrides.
    Thread-safe reads after initial scan().
    """

    def __init__(self, pdf_dir: Optional[Path] = None) -> None:
        self._pdf_dir = pdf_dir or Path("/app/input")
        self._configs: Dict[str, BuildingConfig] = {}
        self._floor_map: Dict[str, Dict[int, Path]] = {}
        # Phase 4 — alias → primary building_id table.  Populated from each
        # registered BuildingConfig.floor_plan_aliases.  Look-up methods
        # (get / get_or_default / floors_for / pdf_path) consult this map
        # before reporting "unknown building".
        self._aliases: Dict[str, str] = {}

    def scan(self) -> None:
        """Scan pdf_dir, register buildings and their floor PDFs."""
        if not self._pdf_dir.exists():
            logger.warning(f"[BuildingRegistry] PDF dir not found: {self._pdf_dir}")
            return

        # Phase 4 — pre-scan input/*/building.yaml FIRST so:
        #   (a) buildings without PDFs at the top level (e.g. logical "bldg1"
        #       whose floor plans live under "Abacws floor N.pdf") are
        #       registered with their aliases;
        #   (b) aliases are known before the PDF slug discovery so the slug
        #       can be matched to a primary building_id.
        pre_scanned_aliases: set = set()
        # Candidate building.yaml locations, in priority order:
        #   1. FLAT layout — input/building.yaml (the active single-building
        #      layout; bldg1's config + floor_plan_aliases live here after the
        #      nested input/<id>/building.yaml was removed).
        #   2. NESTED layout — input/<id>/building.yaml (staging / multi-building).
        # Underscore-prefixed dirs (e.g. _templates/) are onboarding scaffolding
        # and are skipped so their placeholder building.yaml never gates scan.
        yaml_candidates = []
        flat_yaml = self._pdf_dir / "building.yaml"
        if flat_yaml.exists():
            yaml_candidates.append(flat_yaml)
        for sub in sorted(self._pdf_dir.iterdir()):
            if not sub.is_dir() or sub.name.startswith("_"):
                continue
            yaml_path = sub / "building.yaml"
            if yaml_path.exists():
                yaml_candidates.append(yaml_path)

        for yaml_path in yaml_candidates:
            try:
                cfg = BuildingConfig.from_yaml(yaml_path)
                if cfg.building_id not in self._configs:
                    self._register(cfg)
                    pre_scanned_aliases.update(cfg.floor_plan_aliases or [])
                    logger.info(
                        f"[BuildingRegistry] Pre-registered {cfg.building_id} from "
                        f"{yaml_path} (aliases={cfg.floor_plan_aliases or []})"
                    )
            except Exception as e:
                logger.warning(f"[BuildingRegistry] Failed to load {yaml_path}: {e}")

        # (A hardcoded 'abacws' default used to be registered here. It was
        # redundant — the PDF scan below registers a config for whatever slug it
        # finds, for any building — and actively wrong on a site that has no
        # such building: CAVEAT-094.)

        for path in sorted(self._pdf_dir.glob("*.pdf")):
            m = _DEFAULT_PDF_PATTERN.match(path.name)
            if not m:
                continue
            building_slug = _slugify(m.group("building"))
            floor_num = int(m.group("floor"))

            # Phase 4 — when the PDF slug already resolves via an alias to a
            # pre-scanned building, do NOT register a duplicate config under
            # the slug.  The alias subsumes it.
            if building_slug not in self._configs and self.resolve_id(building_slug) is None:
                # Try to load a building.yaml from <pdf_dir>/<building_id>/
                yaml_path = self._pdf_dir / building_slug / "building.yaml"
                if yaml_path.exists():
                    try:
                        cfg = BuildingConfig.from_yaml(yaml_path)
                        logger.info(
                            f"[BuildingRegistry] Loaded config from {yaml_path}: "
                            f"building_id={cfg.building_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[BuildingRegistry] Failed to load {yaml_path}: {e}. "
                            "Using defaults."
                        )
                        cfg = default_config(building_slug, m.group("building"))
                else:
                    cfg = default_config(building_slug, m.group("building"))
                self._register(cfg)

            # Phase 4 — if the PDF's slug is an alias for a pre-scanned
            # building, store the floor under the PRIMARY building_id so
            # floors_for(primary) returns the PDF.  Otherwise key by slug.
            primary = self.resolve_id(building_slug) or building_slug
            if primary not in self._floor_map:
                self._floor_map[primary] = {}
            self._floor_map[primary][floor_num] = path

        logger.info(
            f"[BuildingRegistry] Registered buildings: {list(self._configs.keys())} "
            f"| floor counts: { {b: len(f) for b, f in self._floor_map.items()} }"
        )

    def _register(self, cfg: BuildingConfig) -> None:
        self._configs[cfg.building_id] = cfg
        # Phase 4 — record any declared aliases so look-ups via either ID
        # land on the same data.
        for alias in cfg.floor_plan_aliases:
            if alias and alias != cfg.building_id:
                self._aliases[alias] = cfg.building_id

    def resolve_id(self, building_id: Optional[str]) -> Optional[str]:
        """Translate a building ID through the alias map.

        Returns the primary building_id, or None if completely unknown.  Use
        this when callers may reference a building under either its logical
        ID (e.g. 'bldg1') or its floor-plan slug (e.g. 'abacws').
        """
        if not building_id:
            return None
        if building_id in self._configs:
            return building_id
        return self._aliases.get(building_id)

    def get(self, building_id: str) -> Optional[BuildingConfig]:
        """Return config for building_id (alias-aware), or None if unknown."""
        primary = self.resolve_id(building_id)
        return self._configs.get(primary) if primary else None

    def get_or_default(self, building_id: Optional[str]) -> BuildingConfig:
        """Return config for building_id (alias-aware).

        Fallback order is building-agnostic: the requested id → the ACTIVE building
        (settings.BUILDING_ID) → any registered building → the shipped sample config
        (only if the registry is completely empty). Never silently returns Abacws
        geometry for a different active building.
        """
        primary = self.resolve_id(building_id)
        if primary:
            return self._configs[primary]
        # Fall back to the active building, not a hardcoded one.
        try:
            from shared.config import settings

            active = self.resolve_id(settings.BUILDING_ID)
            if active:
                return self._configs[active]
        except Exception:
            pass
        if self._configs:
            return next(iter(self._configs.values()))
        # Absolute last resort: an empty registry. Describe the configured
        # building generically rather than naming a building that may not exist
        # at this site.
        try:
            from shared.config import settings as _s

            return default_config(_s.BUILDING_ID)
        except Exception:
            return default_config("")

    def building_ids(self) -> List[str]:
        return sorted(self._configs.keys())

    def aliases(self) -> Dict[str, str]:
        """Return a copy of the alias → primary_id mapping (debug / introspection)."""
        return dict(self._aliases)

    def floors_for(self, building_id: str) -> Dict[int, Path]:
        """Return {floor_num: pdf_path} for a building (alias-aware)."""
        primary = self.resolve_id(building_id) or building_id
        return dict(self._floor_map.get(primary, {}))

    def pdf_path(self, building_id: str, floor: int) -> Optional[Path]:
        primary = self.resolve_id(building_id) or building_id
        return self._floor_map.get(primary, {}).get(floor)

    def all_floors(self) -> List[tuple]:
        """Return [(building_id, floor_num)] for every discovered PDF."""
        result = []
        for bid, floors in self._floor_map.items():
            for floor in sorted(floors.keys()):
                result.append((bid, floor))
        return result

    def register_floor(self, building_id: str, floor: int, path: Path) -> None:
        """Register a new PDF discovered at runtime (used by file watcher)."""
        if building_id not in self._floor_map:
            self._floor_map[building_id] = {}
        self._floor_map[building_id][floor] = path
        if building_id not in self._configs:
            yaml_path = self._pdf_dir / building_id / "building.yaml"
            if yaml_path.exists():
                try:
                    self._register(BuildingConfig.from_yaml(yaml_path))
                except Exception:
                    self._register(default_config(building_id))
            else:
                self._register(default_config(building_id))


def _slugify(name: str) -> str:
    """Convert a building display name to a lowercase slug (e.g. 'North Wing' -> 'north_wing')."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ── Module-level singleton ─────────────────────────────────────────────────────
_registry: Optional[BuildingRegistry] = None


def get_building_registry(pdf_dir: Optional[Path] = None) -> BuildingRegistry:
    """Return the module-level registry singleton, scanning on first call."""
    global _registry
    if _registry is None:
        _registry = BuildingRegistry(pdf_dir)
        _registry.scan()
    return _registry
