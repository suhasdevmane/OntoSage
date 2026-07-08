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

        # Per-building override
        if building_id:
            for template in _PER_BUILDING_PATHS:
                override_path = Path(template.format(building_id=building_id))
                if override_path.exists():
                    overrides = _load_yaml(override_path)
                    if overrides:
                        recipes.update(overrides)
                        logger.info(
                            f"[recipes] applied {len(overrides)} override(s) "
                            f"from {override_path}"
                        )
                    break

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
