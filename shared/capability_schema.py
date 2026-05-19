"""
Capability KB schema — validates input/<bldg>/capability.yaml.
Loaded once at startup; answers are served by CapabilityAgent.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


class CapabilityEntry(BaseModel):
    id: str
    category: str
    keywords: List[str]
    content: str
    source: str = ""


class BuildingInfo(BaseModel):
    id: str
    name: str
    institution: str = ""
    location: str = ""
    year_built: Optional[Any] = None
    floors: Optional[Any] = None
    floor_range: str = ""
    total_area_m2: Optional[Any] = None
    occupancy_type: str = ""
    smart_building: bool = False
    sensor_count: Optional[Any] = None
    description: str = ""


class CapabilityKB(BaseModel):
    building_info: BuildingInfo
    capabilities: List[CapabilityEntry] = Field(default_factory=list)

    @property
    def building(self) -> BuildingInfo:
        return self.building_info

    @classmethod
    def from_yaml(cls, path: Path) -> "CapabilityKB":
        if not _YAML_OK:
            raise ImportError("PyYAML is required to load capability KB")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(**data)

    def search(self, query: str, max_results: int = 3) -> List[CapabilityEntry]:
        """Return entries whose keywords overlap with the query (case-insensitive)."""
        q = query.lower()
        scored: List[tuple] = []
        for entry in self.capabilities:
            hits = sum(1 for kw in entry.keywords if kw.lower() in q)
            if hits > 0:
                scored.append((hits, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:max_results]]
