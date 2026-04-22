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
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, Field

# Default regex that matches Abacws-style zone IDs: "3.01", "5.28"
_DEFAULT_ZONE_PATTERN = r"\b(\d+)\.(\d{2})\b"


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
