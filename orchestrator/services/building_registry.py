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

from shared.floor_plan_config import ABACWS_CONFIG, BuildingConfig
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

    def scan(self) -> None:
        """Scan pdf_dir, register buildings and their floor PDFs."""
        if not self._pdf_dir.exists():
            logger.warning(f"[BuildingRegistry] PDF dir not found: {self._pdf_dir}")
            return

        # Always register Abacws as the default (it may not have a YAML file)
        self._register(ABACWS_CONFIG)

        for path in sorted(self._pdf_dir.glob("*.pdf")):
            m = _DEFAULT_PDF_PATTERN.match(path.name)
            if not m:
                continue
            building_slug = _slugify(m.group("building"))
            floor_num = int(m.group("floor"))

            if building_slug not in self._configs:
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
                        cfg = BuildingConfig(
                            building_id=building_slug,
                            building_name=m.group("building"),
                        )
                else:
                    cfg = BuildingConfig(
                        building_id=building_slug,
                        building_name=m.group("building"),
                    )
                self._register(cfg)

            if building_slug not in self._floor_map:
                self._floor_map[building_slug] = {}
            self._floor_map[building_slug][floor_num] = path

        logger.info(
            f"[BuildingRegistry] Registered buildings: {list(self._configs.keys())} "
            f"| floor counts: { {b: len(f) for b, f in self._floor_map.items()} }"
        )

    def _register(self, cfg: BuildingConfig) -> None:
        self._configs[cfg.building_id] = cfg

    def get(self, building_id: str) -> Optional[BuildingConfig]:
        """Return config for building_id, or None if unknown."""
        return self._configs.get(building_id)

    def get_or_default(self, building_id: Optional[str]) -> BuildingConfig:
        """Return config for building_id, falling back to Abacws default."""
        if building_id and building_id in self._configs:
            return self._configs[building_id]
        return ABACWS_CONFIG

    def building_ids(self) -> List[str]:
        return sorted(self._configs.keys())

    def floors_for(self, building_id: str) -> Dict[int, Path]:
        """Return {floor_num: pdf_path} for a building."""
        return dict(self._floor_map.get(building_id, {}))

    def pdf_path(self, building_id: str, floor: int) -> Optional[Path]:
        return self._floor_map.get(building_id, {}).get(floor)

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
                    self._register(BuildingConfig(building_id=building_id))
            else:
                self._register(BuildingConfig(building_id=building_id))


def _slugify(name: str) -> str:
    """Convert a building display name to a lowercase slug (e.g. 'Abacws' → 'abacws')."""
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
