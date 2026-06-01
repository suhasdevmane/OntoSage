"""
floor_plan_config.py — Building-specific floor plan configuration.

Each building can override defaults via an optional `building.yaml` file
placed in /app/input/<building_id>/building.yaml.  Without the file the
system uses the Abacws defaults so existing behaviour is unchanged.

building.yaml example for a second building:
--------------------------------------------
building_id: cardiff_eng
building_name: Cardiff School of Engineering
zone_id_pattern: "R{floor}{nn}"      # e.g. R301, R415
ontology_namespace: "https://cardiff.ac.uk/zones/"
default_dpi: 200
display_name: Cardiff Engineering Building
floors_label_override:
  0: "Ground Floor"
  1: "First Floor"
--------------------------------------------

``zone_id_pattern`` tokens:
  {floor}  — the floor number (one or more digits)
  {nn}     — two-digit room/zone suffix
  {nnn}    — three-digit room/zone suffix
  Omit to use the raw regex; or provide a full Python regex string.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

# Default regex that matches Abacws-style zone IDs: "3.01", "5.28"
_DEFAULT_ZONE_PATTERN = r"\b(\d+)\.(\d{2})\b"

# AIA/NCS layer naming conventions → semantic role
_DEFAULT_LAYER_MAP: Dict[str, str] = {
    r"(?i)A[_-]?AREA": "room_boundary",
    r"(?i)A[_-]?ROOM": "room_boundary",
    r"(?i)A[_-]?SPAC": "room_boundary",
    r"(?i)A[_-]?FLOR[_-]?AREA": "room_boundary",
    r"(?i)A[_-]?WALL": "wall",
    r"(?i)A[_-]?DOOR": "door",
    r"(?i)A[_-]?GLAZ": "window",
    r"(?i)A[_-]?WIND": "window",
    r"(?i)A[_-]?FURN": "furniture",
    r"(?i)A[_-]?EQPM": "equipment",
    r"(?i)A[_-]?ANNO": "annotation",
    r"(?i)A[_-]?TEXT": "annotation",
    r"(?i)A[_-]?NPLT": "annotation",
    r"(?i)A[_-]?ROOM[_-]?NPLT": "room_label",
    r"(?i)M[_-]?HVAC": "hvac",
    r"(?i)M[_-]?MECH": "mechanical",
    r"(?i)E[_-]?LITE": "lighting",
    r"(?i)E[_-]?POWR": "power",
    r"(?i)F[_-]": "fire_protection",
    r"(?i)P[_-]": "plumbing",
    r"(?i)STAIR": "staircase",
    r"(?i)LIFT|ELEV": "lift",
    r"(?i)DEFPOINT|DIMS|DIM": "dimension",
    r"(?i)^0$": "default",
}


class StorageRoute(BaseModel):
    """A single UUID-pattern → backend routing rule.

    Allows per-building heterogeneous time-series setups (e.g. temp sensors on
    MySQL, energy meters on InfluxDB).  When a sensor UUID matches `pattern`,
    queries are routed to the named `backend` key (resolved against
    database_registry.yaml).

    Patterns use shell-glob syntax (`*` matches anything).  Patterns are
    evaluated in declaration order, first match wins.
    """

    pattern: str = Field(..., description="UUID glob pattern, e.g. 'temp-*'")
    backend: str = Field(..., description="Backend key from database_registry.yaml")


class StorageConfig(BaseModel):
    """Per-building storage backend selection.

    When omitted from building.yaml, the AdapterRegistry initialises EVERY
    backend declared in database_registry.yaml (legacy behaviour).  When
    present, only the listed backends are initialised, dramatically reducing
    startup time and noise from failed connection attempts.

    Example:
        storage:
          databases:                # subset of database_registry.yaml keys
            - database1
            - database8
          primary: database1        # default backend when SPARQL result has no
                                    # ref:storedAt hint
          routes:                   # optional UUID-pattern routing
            - pattern: "temp-*"
              backend: database1
            - pattern: "power-*"
              backend: influxdb1
          fallback: database1       # used if no route matches
    """

    databases: List[str] = Field(
        default_factory=list,
        description=(
            "Keys from database_registry.yaml that this building needs. "
            "Empty list = initialise every available adapter (legacy)."
        ),
    )
    primary: Optional[str] = Field(
        default=None,
        description="Default backend key when storage URI lookup fails.",
    )
    routes: List[StorageRoute] = Field(
        default_factory=list,
        description="UUID-pattern → backend routing rules (first match wins).",
    )
    fallback: Optional[str] = Field(
        default=None,
        description="Used by the registry when no route matches.",
    )


class BuildingConfig(BaseModel):
    """
    Per-building configuration loaded from building.yaml (or defaults).

    All fields have sensible defaults so the Abacws building works
    without any YAML file.
    """

    building_id: str = "abacws"
    building_name: str = "Abacws"
    display_name: Optional[str] = None
    zone_id_pattern: str = _DEFAULT_ZONE_PATTERN
    ontology_namespace: str = "https://abacws.example/zones/"
    default_dpi: int = Field(default=200, ge=72, le=600)
    thumbnail_width_px: int = Field(default=400, ge=100, le=1200)
    floors_label_override: Dict[int, str] = Field(default_factory=dict)
    pdf_filename_pattern: str = r"(?P<building>.+?)\s+floor\s+(?P<floor>\d+)\.pdf"
    llm_extract_enabled: bool = True
    # DW1 — per-building layer overrides (merged on top of _DEFAULT_LAYER_MAP)
    layer_map: Dict[str, str] = Field(default_factory=dict)
    min_room_area_m2: float = Field(default=2.0, ge=0.1)
    max_room_area_m2: float = Field(default=10_000.0)
    # Phase 2 — per-building storage adapter binding
    storage: Optional[StorageConfig] = Field(
        default=None,
        description="Storage backend selection; omit for legacy 'init all' behaviour.",
    )
    # Phase 4 — alias names this building also answers to.
    # Resolves the historical mismatch where logical BUILDING_ID (e.g. "bldg1")
    # differs from the floor-plan registry slug (e.g. "abacws" derived from
    # filename "Abacws floor N.pdf").  Callers using the alias get the same
    # config / floor-plan data as callers using the primary building_id.
    floor_plan_aliases: List[str] = Field(
        default_factory=list,
        description="Additional IDs that resolve to this building (e.g. floor-plan PDF slugs).",
    )

    @property
    def effective_display_name(self) -> str:
        return self.display_name or self.building_name

    def floor_label(self, floor: int) -> str:
        """Return a human-readable label for a floor number."""
        if floor in self.floors_label_override:
            return self.floors_label_override[floor]
        if floor == 0:
            return "Ground Floor"
        return f"Floor {floor}"

    def zone_id_regex(self) -> re.Pattern:
        """Compile and return the zone-ID regex for this building."""
        pattern = self.zone_id_pattern
        # Expand template tokens to regex groups if the user used the
        # shorthand template syntax (contains {floor} / {nn} / {nnn}).
        if "{floor}" in pattern:
            pattern = pattern.replace("{floor}", r"(?P<floor>\d+)")
        if "{nnn}" in pattern:
            pattern = pattern.replace("{nnn}", r"(?P<zone>\d{3})")
        elif "{nn}" in pattern:
            pattern = pattern.replace("{nn}", r"(?P<zone>\d{2})")
        return re.compile(pattern)

    def merged_layer_map(self) -> Dict[str, str]:
        """Return the combined AIA/NCS defaults + any building-specific overrides."""
        combined = dict(_DEFAULT_LAYER_MAP)
        combined.update(self.layer_map)
        return combined

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "BuildingConfig":
        """Load a BuildingConfig from a building.yaml file."""
        with open(yaml_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(**raw)

    @classmethod
    def default(cls) -> "BuildingConfig":
        """Return the Abacws default configuration."""
        return cls()


# ── Module-level default singleton ────────────────────────────────────────────
DEFAULT_BUILDING_CONFIG: BuildingConfig = BuildingConfig.default()

# Abacws-specific floor label map (ground floor is floor 0)
_ABACWS_FLOOR_LABELS: Dict[int, str] = {
    0: "Ground Floor",
    1: "First Floor",
    2: "Second Floor",
    3: "Third Floor",
    4: "Fourth Floor",
    5: "Fifth Floor",
}

ABACWS_CONFIG = BuildingConfig(
    building_id="abacws",
    building_name="Abacws",
    display_name="Abacws Building",
    zone_id_pattern=_DEFAULT_ZONE_PATTERN,
    ontology_namespace="https://abacws.example/zones/",
    default_dpi=200,
    thumbnail_width_px=400,
    floors_label_override=_ABACWS_FLOOR_LABELS,
)
