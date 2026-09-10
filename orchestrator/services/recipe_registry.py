"""
recipe_registry.py — Load and serve analytic recipes for HBCO concept evaluation.

Recipes define the evaluation logic (threshold, range, aggregate, trend, correlate)
and parameters for assessing building conditions expressed as lay-language concepts.

Loading order (later layers override earlier):
  1. config/recipes.yaml  (base recipes, version-controlled)
  2. input/<BUILDING_ID>/recipes.yaml  (per-building override, optional)

Usage:
    from orchestrator.services.recipe_registry import recipe_registry
    recipe = recipe_registry.get("co2_threshold")
    if recipe:
        print(recipe["params"]["co2_ppm_alert"])
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

_BASE_CONFIG_PATHS = [Path("/app/config/recipes.yaml"), Path("config/recipes.yaml")]
_PER_BUILDING_PATHS = [
    "/app/input/{building_id}/recipes.yaml",
    "input/{building_id}/recipes.yaml",
]


def _resolve_path(candidates: List[str]) -> Optional[Path]:
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


def _resolve_building_overlay(building_id: str) -> Optional[Path]:
    """This building's recipes.yaml, in EITHER input layout.

    `_PER_BUILDING_PATHS` names the nested form only, and the canonical layout is FLAT:
    under swap-by-rename the active building's files sit directly in ``input/``. So a
    per-building recipe overlay could never be found for any building this repo ships
    (CAVEAT-448). ``shared/building_paths`` is the one implementation; the templates remain
    as a fallback for a caller with neither layout under a standard root.
    """
    from shared.building_paths import resolve_building_file

    resolved = resolve_building_file(building_id, "recipes.yaml")
    if resolved is not None:
        return resolved
    return _resolve_path([c.format(building_id=building_id) for c in _PER_BUILDING_PATHS])


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning(f"[recipes] {path}: expected dict, got {type(data).__name__}")
            return {}
        return data.get("recipes", data)  # handle both root and nested `recipes:` key
    except Exception as e:
        logger.warning(f"[recipes] failed to load {path}: {e}")
        return {}


class RecipeRegistry:
    """Singleton registry: base recipes + optional per-building overrides."""

    def __init__(self) -> None:
        self._recipes: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _ensure_loaded(self, building_id: Optional[str] = None) -> None:
        if self._loaded:
            return
        self.load(building_id=building_id)

    def load(self, *, building_id: Optional[str] = None) -> int:
        """Load base recipes + optional per-building overlay.  Returns total recipe count."""
        recipes: Dict[str, Dict[str, Any]] = {}

        # Base config
        base_path = _resolve_path([str(p) for p in _BASE_CONFIG_PATHS])
        if base_path:
            recipes.update(_load_yaml(base_path))
            logger.info(f"[recipes] loaded {len(recipes)} base recipe(s) from {base_path}")
        else:
            logger.warning("[recipes] config/recipes.yaml not found — recipe registry empty")

        # Per-building override, resolved in EITHER layout (CAVEAT-448). This walked
        # _PER_BUILDING_PATHS directly, which names the nested form only, so under the
        # canonical flat layout no building's overrides were ever applied.
        if building_id:
            override_path = _resolve_building_overlay(building_id)
            if override_path is not None:
                overrides = _load_yaml(override_path)
                if overrides:
                    recipes.update(overrides)
                    logger.info(
                        f"[recipes] applied {len(overrides)} override(s) from {override_path}"
                    )

        self._recipes = recipes
        self._loaded = True
        return len(recipes)

    def get(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        """Return the recipe dict for the given id, or None if not found."""
        self._ensure_loaded()
        return self._recipes.get(recipe_id)

    def all_ids(self) -> List[str]:
        """Return sorted list of all recipe IDs."""
        self._ensure_loaded()
        return sorted(self._recipes.keys())

    def all_recipes(self) -> Dict[str, Dict[str, Any]]:
        """Return a deep copy of the full recipe dict."""
        self._ensure_loaded()
        return copy.deepcopy(self._recipes)

    def reload(self, building_id: Optional[str] = None) -> int:
        """Force reload — useful after hot-swap."""
        self._loaded = False
        return self.load(building_id=building_id)


# Module-level singleton
recipe_registry = RecipeRegistry()
