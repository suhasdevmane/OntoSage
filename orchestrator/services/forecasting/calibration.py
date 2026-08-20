# -*- coding: utf-8 -*-
"""
calibration.py — registry-driven confidence-interval calibration (V5-T14).

The T17 time-travel grader measured the raw model bands at **CI80 ≈ 0.48 /
CI95 ≈ 0.59 actual coverage** — roughly 2× over-confident. This module closes
the loop: the measured coverage per (modality × horizon) lives in the
building's own skill registry (``volumes/<id>/artifacts/forecast_skill.json``,
written by ``scripts/grade_forecasts.py``), and bands are widened by the
normal-quantile ratio needed to reach nominal coverage:

    factor = z(nominal) / z(observed),   z(p) = Φ⁻¹((1+p)/2)

capped to [1, 4] (never narrow a band; never explode one). A modality or
horizon with no registry entry gets factor 1.0 — uncalibrated bands are
served as-is rather than guessed. Everything is per-building: a fresh
building starts uncalibrated and earns factors by running the grader.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import NormalDist
from typing import Dict, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_MAX_FACTOR = 4.0
_registry_cache: Dict[str, dict] = {}


def _z(p: float) -> float:
    p = min(max(p, 0.02), 0.998)  # keep inv_cdf away from the tails
    return NormalDist().inv_cdf((1.0 + p) / 2.0)


def load_registry(building_id: str, repo_root: Optional[Path] = None) -> dict:
    """The building's skill registry, cached per process; {} when absent."""
    if building_id in _registry_cache:
        return _registry_cache[building_id]
    root = repo_root or Path("/app")
    candidates = [
        root / "volumes" / building_id / "artifacts" / "forecast_skill.json",
        Path("volumes") / building_id / "artifacts" / "forecast_skill.json",
    ]
    if repo_root is None:
        # In the container the ACTIVE building's artifacts dir is mounted
        # flat at /app/volumes/artifacts (compose maps
        # ./volumes/<id>/artifacts -> /app/volumes/artifacts), so the
        # building-segmented paths above never exist there. Without this the
        # calibration layer silently no-ops live — caught in T32 shakedown.
        try:
            from shared.config import settings

            if building_id == settings.BUILDING_ID:
                candidates.append(root / "volumes" / "artifacts" / "forecast_skill.json")
        except Exception:  # settings unavailable in odd contexts — skip
            pass
    registry: dict = {}
    for path in candidates:
        try:
            if path.exists():
                registry = json.loads(path.read_text(encoding="utf-8"))
                break
        except (OSError, ValueError) as exc:
            logger.warning(f"[calibration] registry unreadable at {path}: {exc}")
    _registry_cache[building_id] = registry
    if registry:
        logger.info(
            f"[calibration] skill registry loaded for {building_id}: "
            f"{sum(len(v) for v in registry.values())} cells"
        )
    return registry


def _nearest_horizon(entries: dict, horizon_h: float) -> Optional[dict]:
    best = None
    for key, entry in entries.items():
        try:
            h = float(str(key).rstrip("h"))
        except ValueError:
            continue
        d = abs(h - horizon_h)
        if best is None or d < best[0]:
            best = (d, entry)
    return best[1] if best else None


def band_factors(
    building_id: str, modality: str, horizon_h: float, repo_root: Optional[Path] = None
) -> Tuple[float, float]:
    """(factor80, factor95) for this modality/horizon; (1, 1) when unknown."""
    registry = load_registry(building_id, repo_root)
    entries = registry.get(modality) or {}
    entry = _nearest_horizon(entries, horizon_h)
    if not entry:
        return 1.0, 1.0

    def _factor(nominal: float, observed) -> float:
        if observed is None or observed <= 0:
            return 1.0
        if observed >= nominal:
            return 1.0  # already covering — never narrow
        return min(_MAX_FACTOR, _z(nominal) / _z(float(observed)))

    return (
        round(_factor(0.80, entry.get("ci80_coverage")), 3),
        round(_factor(0.95, entry.get("ci95_coverage")), 3),
    )


def calibrate_band(
    band: Optional[Tuple[float, float]], value: float, factor: float
) -> Optional[Tuple[float, float]]:
    """Widen a (lo, hi) band around the forecast value by ``factor``."""
    if band is None or factor <= 1.0:
        return band
    lo, hi = band
    return (
        round(value - (value - lo) * factor, 3),
        round(value + (hi - value) * factor, 3),
    )


def reset_cache_for_tests() -> None:
    _registry_cache.clear()
