"""
cqir.py — the Constraint-Query IR: ARBITER's typed, closed-vocabulary core (V4-T15).

The LLM's ONLY generative role in deliberation is compiling a natural-language
constraint query into this IR. Everything after — admission, candidate
enumeration, execution, scoring — is deterministic code that trusts these types.
Unmappable input never becomes a guess: it becomes an ambiguity signal for the
clarify-or-proceed policy.

Pure types + validation here; the LLM call lives in the compiler (compiler.py)
so these models stay import-light and offline-testable.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DecisionKind(str, Enum):
    SELECT_ONE = "select_one"  # "where should I sit" -> best candidate
    RANK_ALL = "rank_all"  # "rank the rooms by ..." -> ordered list
    SUPERLATIVE = "superlative"  # "quietest room" / "minimum occupancy zone"
    LIST_MATCHING = "list_matching"  # "which rooms are below 800ppm"


class Hardness(str, Enum):
    HARD = "hard"  # filter: candidates failing it are excluded
    SOFT = "soft"  # preference: weighted into the score


class Direction(str, Enum):
    MINIMIZE = "minimize"  # quiet -> minimize noise
    MAXIMIZE = "maximize"  # bright -> maximize illuminance
    BELOW = "below"  # threshold constraints
    ABOVE = "above"
    NEAR_VALUE = "near_value"  # comfort band around a target


class ThresholdSource(str, Enum):
    RECIPE = "recipe"  # standards-anchored default (cited in the dossier)
    USER = "user"  # the user stated a number
    DEFAULT = "default"  # equal-weight fallback, declared as assumption


class SpatialRelation(str, Enum):
    ON_FLOOR = "on_floor"
    NEAR_AMENITY = "near_amenity"  # anchor = amenity kind or label
    IN_SPACE = "in_space"  # scoped to one named space
    ADJACENT_TO = "adjacent_to"


class TimeBasis(str, Enum):
    NOW = "now"  # latest readings
    WINDOW = "window"  # aggregate over a past window
    FORECAST = "forecast"  # future horizon -> forecaster


class Constraint(BaseModel):
    """One environmental criterion, mapped to a known modality — never invented."""

    modality: str = Field(..., description="A saturation_modalities.yaml modality name")
    direction: Direction
    hardness: Hardness = Hardness.SOFT
    threshold: Optional[float] = Field(
        None, description="Numeric bound when direction is below/above/near_value"
    )
    threshold_source: ThresholdSource = ThresholdSource.RECIPE
    recipe_id: Optional[str] = Field(
        None, description="RecipeRegistry id anchoring the threshold/utility"
    )
    weight: float = Field(1.0, ge=0.0, le=10.0)
    source_phrase: str = Field(
        "", description="The user's words this constraint came from (dossier)"
    )


class SpatialQualifier(BaseModel):
    relation: SpatialRelation
    anchor: str = Field(
        ..., description="floor label, amenity kind (e.g. DrinkingWater), or space name"
    )
    source_phrase: str = ""


class TimeSpec(BaseModel):
    basis: TimeBasis = TimeBasis.NOW
    horizon_hours: Optional[float] = Field(None, description="For FORECAST: hours ahead")
    window_hours: Optional[float] = Field(None, description="For WINDOW: hours of history")
    unparseable: bool = Field(
        False,
        description="True when the phrase had a time anchor we could not parse — a clarify signal, never a silent default",
    )
    source_phrase: str = ""


class AmbiguitySignal(BaseModel):
    """Anything the compiler could not map — input to the clarify-or-proceed policy."""

    kind: str = Field(
        ...,
        description="unmapped_term | unresolved_anchor | unparseable_time | conflicting | vague",
    )
    phrase: str
    note: str = ""


class EventCriterion(BaseModel):
    """Event-store-derived requirement (V5-T25): availability / booking pressure.

    kind 'free_window'  — the space must have no booking overlapping
                          [now, now + hours] (hard filter, ledger-visible).
    kind 'low_booking_pressure' — prefer rarely-booked spaces; surfaced as
                          dossier evidence (scored weighting deferred).
    """

    kind: str = Field(..., description="free_window | low_booking_pressure")
    hours: float = Field(2.0, description="Window length for free_window")


class CQIR(BaseModel):
    """The compiled constraint program. `signals` non-empty means NOT ready to run."""

    decision: DecisionKind
    target_kind: str = Field("space", description="What we choose between (v1: space)")
    constraints: List[Constraint] = Field(default_factory=list)
    spatial: List[SpatialQualifier] = Field(default_factory=list)
    time: TimeSpec = Field(default_factory=TimeSpec)
    signals: List[AmbiguitySignal] = Field(default_factory=list)
    event_criteria: List[EventCriterion] = Field(default_factory=list)
    raw_query: str = ""

    def is_executable(self) -> bool:
        """Ready for admission: has criteria, no blocking ambiguity."""
        return bool(self.constraints) and not self.signals

    def plan_fingerprint(self) -> str:
        """Deterministic hash of the BEHAVIORAL core — the determinism anchor.

        Hashes exactly what execution consumes: constraints (modality,
        direction, hardness, threshold+source, recipe, weight), spatial
        (relation, anchor), time (basis, horizons) and target_kind. Presentation
        styling (decision kind: select_one vs list_matching ranks identically)
        and provenance text (raw_query, source_phrase) are excluded — measured
        live, temp-0 local models wobble on exactly those non-behavioral
        fields while emitting byte-identical constraint programs.
        """
        import hashlib
        import json

        core = {
            "target": self.target_kind,
            "constraints": sorted(
                (
                    c.modality,
                    c.direction.value,
                    c.hardness.value,
                    c.threshold,
                    c.threshold_source.value,
                    c.recipe_id,
                    c.weight,
                )
                for c in self.constraints
            ),
            "spatial": sorted((q.relation.value, q.anchor) for q in self.spatial),
            "time": (self.time.basis.value, self.time.horizon_hours, self.time.window_hours),
            "events": sorted((e.kind, e.hours) for e in self.event_criteria),
        }
        canon = json.dumps(core, sort_keys=True, default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
