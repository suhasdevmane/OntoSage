"""registry.py — ActuationRegistry (T23).

Reads actuation config from input/<building_id>/building.yaml and returns
the appropriate driver instance.

building.yaml actuation block:
    actuation:
      driver: sim          # sim | none (physical drivers: Phase H+)
      points_writable:
        - urn:bldg1:VAV-501-SP       # VAV setpoint room 5.01
        - urn:bldg1:LIGHTING-3F-SP   # lighting setpoint floor 3
        - urn:bldg1:AHU-F5-SP        # AHU supply-air setpoint

If the block is absent or driver=none, capabilities() returns [].
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from orchestrator.services.actuation.base import ActuationDriver, ActuationResult
from orchestrator.services.actuation.sim_driver import SimDriver
from shared.utils import get_logger

logger = get_logger(__name__)

_YAML_SEARCH_PATHS = [
    "/app/input/{building_id}/building.yaml",
    "input/{building_id}/building.yaml",
]


class _NullDriver(ActuationDriver):
    """Driver returned when actuation is disabled (driver=none)."""

    async def capabilities(self):
        return []

    async def set_point(self, point_uri, value, *, user_id="system", reason=""):
        return ActuationResult(
            success=False,
            point_uri=point_uri,
            value=value,
            error="Actuation is not enabled for this building (driver=none).",
        )


class ActuationRegistry:
    """Resolves and caches the actuation driver for each building."""

    def __init__(self) -> None:
        self._cache: dict = {}

    def driver_for(self, building_id: str) -> ActuationDriver:
        """Return the driver for building_id (cached after first load)."""
        if building_id not in self._cache:
            self._cache[building_id] = self._load(building_id)
        return self._cache[building_id]

    def _load(self, building_id: str) -> ActuationDriver:
        yaml_path = self._find_yaml(building_id)
        if yaml_path is None:
            logger.info(f"[ActuationRegistry] No building.yaml for {building_id} — null driver")
            return _NullDriver()

        try:
            import yaml

            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning(f"[ActuationRegistry] Could not read {yaml_path}: {exc}")
            return _NullDriver()

        act_cfg = data.get("actuation", {})
        driver_name = act_cfg.get("driver", "none")

        if driver_name == "sim":
            points = act_cfg.get("points_writable", [])
            logger.info(
                f"[ActuationRegistry] SimDriver for {building_id}: "
                f"{len(points)} writable point(s)"
            )
            return SimDriver(building_id=building_id, writable_points=points)
        else:
            logger.info(
                f"[ActuationRegistry] Null driver for {building_id} (driver={driver_name!r})"
            )
            return _NullDriver()

    def _find_yaml(self, building_id: str) -> Optional[Path]:
        # Shared resolver — supports nested (input/<id>/) and flat (input/) layouts.
        from shared.config import resolve_building_file

        found = resolve_building_file(building_id, "building.yaml")
        if found is not None:
            return found
        # Legacy fallback for non-standard mounts.
        for template in _YAML_SEARCH_PATHS:
            p = Path(template.format(building_id=building_id))
            if p.is_file():
                return p
        return None

    def invalidate(self, building_id: str) -> None:
        """Remove cached driver — call after building.yaml changes."""
        self._cache.pop(building_id, None)


# Module-level singleton
_registry: Optional[ActuationRegistry] = None


def get_actuation_registry() -> ActuationRegistry:
    global _registry
    if _registry is None:
        _registry = ActuationRegistry()
    return _registry
