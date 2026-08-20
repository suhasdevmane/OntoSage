"""
persona_loader.py — Phase 5 YAML-driven persona configuration.

Loads persona definitions from YAML files instead of (or in addition to) the
hardcoded `_REGISTRY` dict in `persona_registry.py`.  The hardcoded defaults
remain as a safety net so the system still boots with no YAML present.

Lookup precedence (later overrides earlier):
  1. Hardcoded `_REGISTRY` (safety default — always present)
  2. Global personas:       `input/personas/<name>.yaml`
  3. Per-building overrides: `input/<BUILDING_ID>/personas/<name>.yaml`

Each YAML file has the shape:

```yaml
name: facility_manager
description: Responsible for building operations and maintenance
aliases:
  - facilities
  - facility manager
top_domains:
  - ENERGY
  - THERMAL
  - OCCUPANCY
lookup_share: 0.62
default_complexity: MODERATE
clarification_threshold: 0.5
borda_topics:
  - Energy
  - Temperature
  - Occupancy
```

Adding a new persona = drop a YAML file.  No Python edits required.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Conventional locations honoured by the loader (both new + dev layouts).
# Phase 11C — input/_defaults/personas/ is the operator-editable home for the
# shipped persona defaults; legacy input/personas/ is still consulted for
# back-compat.  Later dirs win on conflicting persona names.
_GLOBAL_PERSONA_DIRS: List[Path] = [
    Path("/app/input/_defaults/personas"),
    Path("input/_defaults/personas"),
    Path("/app/input/personas"),
    Path("input/personas"),
]


def _per_building_persona_dirs(building_id: Optional[str]) -> List[Path]:
    if not building_id:
        return []
    return [
        Path(f"/app/input/{building_id}/personas"),
        Path(f"input/{building_id}/personas"),
    ]


def _load_yaml_files(dirs: List[Path]) -> Dict[str, Dict]:
    """Read every *.yaml in each dir; later files for the same name win."""
    out: Dict[str, Dict] = {}
    for d in dirs:
        if not d.exists() or not d.is_dir():
            continue
        for path in sorted(d.glob("*.yaml")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                if not isinstance(data, dict):
                    logger.warning(f"[persona_loader] {path} did not produce a mapping; ignored")
                    continue
                name = data.get("name") or path.stem
                out[name] = data
                logger.debug(f"[persona_loader] loaded persona '{name}' from {path}")
            except Exception as e:
                logger.warning(f"[persona_loader] failed to read {path}: {e}")
    return out


def load_persona_overlays(building_id: Optional[str] = None) -> Tuple[Dict, Dict[str, str]]:
    """Return (persona_data_by_name, alias_map) merged from disk.

    Returns
    -------
    persona_data_by_name : Dict[str, dict]
        Raw dicts ready to pass into PersonaPriors(**data).  Empty when no
        YAML files exist.
    alias_map : Dict[str, str]
        Maps each declared alias to the persona name it should resolve to.
    """
    merged: Dict[str, Dict] = {}
    merged.update(_load_yaml_files(_GLOBAL_PERSONA_DIRS))
    merged.update(_load_yaml_files(_per_building_persona_dirs(building_id)))

    # Strip the alias list out of the per-persona dicts so the PersonaPriors
    # constructor (which doesn't accept an `aliases` field) can be called.
    aliases: Dict[str, str] = {}
    cleaned: Dict[str, Dict] = {}
    for name, data in merged.items():
        data = dict(data)
        for alias in data.pop("aliases", []) or []:
            alias_key = str(alias).lower().strip()
            if alias_key:
                aliases[alias_key] = name
        # Ensure name field matches the registry key.
        data["name"] = name
        cleaned[name] = data

    if cleaned:
        logger.info(
            f"[persona_loader] merged personas from disk: {sorted(cleaned.keys())} "
            f"(+ {len(aliases)} aliases)"
        )
    return cleaned, aliases
