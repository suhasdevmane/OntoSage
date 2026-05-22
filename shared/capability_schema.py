"""
Capability KB schema — validates input/<bldg>/capability.yaml.
Loaded once at startup; answers are served by CapabilityAgent.

Also defines CapabilityRoutingConfig: the per-building tuning block that lives
in input/<bldg>/building.yaml under `capability_routing:`.  Read by
SemanticRouter at query time.
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


class CapabilityRoutingConfig(BaseModel):
    """Per-building config for the capability semantic router.

    Lives under `capability_routing:` in input/<bldg>/building.yaml.
    All fields have sensible defaults so the block can be omitted entirely
    on existing buildings.
    """

    enabled: bool = True
    embedding_model: Literal["auto", "openai", "local"] = "auto"
    threshold: float = Field(
        default=0.65, ge=0.0, le=1.0,
        description=(
            "Min similarity score (cosine) at which the router considers the "
            "match strong enough to *softly* override a non-data LLM intent."
        ),
    )
    override_min: float = Field(
        default=0.85, ge=0.0, le=1.0,
        description=(
            "Min similarity score at which the router *unconditionally* sets "
            "intent=capability and skips the LLM intent call entirely."
        ),
    )
    top_k: int = Field(default=5, ge=1, le=50)
    fallback_on_qdrant_failure: Literal["skip"] = Field(
        default="skip",
        description=(
            "What to do when Qdrant is unreachable. "
            "'skip' → SemanticRouter returns source=fallback; dialogue agent "
            "uses LLM-only intent. "
            "'keyword' → use legacy keyword matcher (only valid during the "
            "migration phase; removed after Phase 3 cleanup)."
        ),
    )

    @model_validator(mode="after")
    def _check_override_above_threshold(self) -> "CapabilityRoutingConfig":
        if self.override_min < self.threshold:
            raise ValueError(
                f"override_min ({self.override_min}) must be >= threshold "
                f"({self.threshold}) — semantic-first routing requires a hard "
                f"override band above the soft threshold."
            )
        return self


class IntentRouteConfig(BaseModel):
    """Per-intent config for additional semantic intents beyond capability.

    Used by the multi-intent extension (spec: 2026-05-22-multi-intent-semantic-routing.md).
    Opt-in only — when the parent `intent_routing` block is absent, no additional
    intents are registered with SemanticRouter and behavior is identical to
    capability-only routing.
    """

    enabled: bool = Field(
        default=False,
        description="Opt-in safety: disabled by default. Set true to register this intent.",
    )
    descriptors: List[str] = Field(
        default_factory=list,
        description=(
            "Phrases that describe queries that should route to this intent. "
            "Each descriptor is embedded into a per-intent Qdrant collection at "
            "startup; user queries are matched against them at runtime."
        ),
    )
    threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    override_min: float = Field(default=0.70, ge=0.0, le=1.0)
    top_k: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def _check_consistency(self) -> "IntentRouteConfig":
        if self.override_min < self.threshold:
            raise ValueError(
                f"override_min ({self.override_min}) must be >= threshold ({self.threshold})"
            )
        if self.enabled and not self.descriptors:
            raise ValueError(
                "enabled=true requires at least one descriptor; otherwise leave enabled=false"
            )
        return self


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

