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

import json
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field


class DecisionKind(str, Enum):
    SELECT_ONE = "select_one"  # "where should I sit" -> best candidate
    RANK_ALL = "rank_all"  # "rank the rooms by ..." -> ordered list
    SUPERLATIVE = "superlative"  # "quietest room" / "minimum occupancy zone"
    LIST_MATCHING = "list_matching"  # "which rooms are below 800ppm"
    # v2 operations. Only the facet compiler emits these; the v1 compiler's closed vocabulary
    # (compiler._DECISIONS) is the four above, so a v1 compile can never produce one.
    AGGREGATE_RANK = "aggregate_rank"  # "which floor has the fewest people" -> group, reduce, rank
    COMPARE_FACETS = "compare_facets"  # "occupancy versus capacity in each room"
    PERIOD_COMPARE = "period_compare"  # "this week against last week", "weekdays vs weekends"
    RELATE = "relate"  # "is CO2 higher during timetabled sessions", "does CO2 rise with occupancy"


#: The decision kinds only the v2 facet compiler may emit. Kept apart so the v1 compile
#: vocabulary -- and the v1 JSON schema built from it -- stays exactly what it was.
V2_DECISIONS = frozenset(
    {
        DecisionKind.AGGREGATE_RANK,
        DecisionKind.COMPARE_FACETS,
        DecisionKind.PERIOD_COMPARE,
        DecisionKind.RELATE,
    }
)


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
    # V12-08 — a DURATION and an INTERVAL are different requests, and this spec used to be
    # able to express only the first. "yesterday" and "today" both compiled to
    # window_hours=24.0, so the two commonest time words in the corpus named the same
    # interval, and `fetch.py` turned either into `utcnow() - 24h` with no upper bound: a
    # rolling day ending NOW, half of it today, in the wrong zone. When the question names
    # a calendar day these carry its absolute local bounds, resolved ONCE by
    # services/requested_interval.py, and every consumer uses them verbatim.
    resolved_start: Optional[str] = Field(
        None, description="Absolute local start 'YYYY-MM-DD HH:MM:SS' when a day was named"
    )
    resolved_end: Optional[str] = Field(
        None, description="Absolute local end, INCLUSIVE — the builders emit `<=`"
    )
    unparseable: bool = Field(
        False,
        description="True when the phrase had a time anchor we could not parse — a clarify signal, never a silent default",
    )
    source_phrase: str = ""

    @property
    def is_resolved_interval(self) -> bool:
        """True when this spec names an absolute interval rather than a duration."""
        return bool(self.resolved_start and self.resolved_end)


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


class FacetOperator(str, Enum):
    """How a criterion compares a FACET's value (v2). Which ones fit is decided by the
    facet's value type, in code (``compiler._OPERATORS_BY_VALUE_TYPE``), never by the model."""

    BELOW = "below"  # number: strictly less than the stated value
    ABOVE = "above"  # number: strictly more than the stated value
    AT_LEAST = "at_least"  # number: >= the stated value ("at least 12 seats")
    AT_MOST = "at_most"  # number: <= the stated value
    MINIMIZE = "minimize"  # number: lower is better, scored across the candidates
    MAXIMIZE = "maximize"  # number: higher is better, scored across the candidates
    NEAR = "near"  # number: closest to the stated value
    EQUALS = "equals"  # enum: one value from the facet's value set
    ONE_OF = "one_of"  # enum: any of several values from the set
    IS_TRUE = "is_true"  # boolean
    IS_FALSE = "is_false"  # boolean
    FREE_FOR = "free_for"  # event: no booking overlaps the next <value> hours
    CONTAINS = "contains"  # text: the value appears in the recorded text


#: Operators that RANK rather than filter: a value only has to be present to count, and the
#: scorer places it relative to the other candidates.
SCORING_OPERATORS = frozenset({FacetOperator.MINIMIZE, FacetOperator.MAXIMIZE, FacetOperator.NEAR})


class FacetCriterion(BaseModel):
    """One requirement on a FACET of the building (v2): a record field, a TTL property of a
    space, the authoritative capacity, a booking check. ``facet`` is a catalogue key
    (``facets.Facet.key``) and nothing else -- the compiler rejects any other string.

    ``record_group`` ties criteria that must hold for ONE record: "a projector that is ready"
    is AVReadiness kind = Projector AND status = ready on the same component, never a room
    whose projector is broken and whose display is ready. Criteria on facets that are not
    read from records carry no group.
    """

    facet: str = Field(..., description="A facet catalogue key, e.g. record:<Class>.<predicate>")
    operator: FacetOperator
    value: Optional[Union[bool, float, str, List[str]]] = Field(
        None, description="Stated by the user (number, enum value(s), text) or None"
    )
    hardness: Hardness = Hardness.SOFT
    weight: float = Field(1.0, ge=0.0, le=10.0)
    threshold_source: ThresholdSource = ThresholdSource.USER
    source_phrase: str = Field("", description="The user's words this criterion came from")
    record_group: Optional[str] = Field(
        None, description="Criteria with the same group must hold for one record"
    )


def _canonical_facet_value(value) -> str:
    """A facet value as the fingerprint sees it: behaviour, not spelling.

    Comparisons on enum and text values are case-insensitive and a one_of is a set, so
    neither case nor list order may separate two plans that execute identically.
    """
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return json.dumps(float(value))
    if isinstance(value, (list, tuple)):
        return json.dumps(sorted(str(v).strip().lower() for v in value))
    return json.dumps(str(value).strip().lower())


def _facet_core(criteria: List[FacetCriterion]) -> List[Tuple]:
    """The behavioural core of the facet criteria, independent of how groups were LABELLED.

    A record group is identified by its MEMBERS, never by the label the model happened to
    give it: "g1" and "projector" naming the same partition are the same plan.
    """
    signature = {
        id(c): (
            c.facet,
            c.operator.value,
            _canonical_facet_value(c.value),
            c.hardness.value,
            c.weight,
            c.threshold_source.value,
        )
        for c in criteria
    }
    members: Dict[str, List[Tuple]] = {}
    for c in criteria:
        if c.record_group:
            members.setdefault(c.record_group, []).append(signature[id(c)])
    rows = []
    for c in criteria:
        group = json.dumps(sorted(members[c.record_group])) if c.record_group else ""
        rows.append(signature[id(c)] + (group,))
    return sorted(rows)


# ── v2 operations: aggregate -> rank (C3) and compare two facets (C2) ─────────────────────


class GroupBy(str, Enum):
    """What an aggregate groups the spaces by."""

    FLOOR = "floor"  # the floor a space is part of (brick:isPartOf a brick:Floor)
    BUILDING = "building"  # one group: every space in scope
    SPACE_KIND = "space_kind"  # the space's own room class ("Laboratory", "Conference_Room")


class Statistic(str, Enum):
    """How one group's per-space values are reduced to the figure it is ranked on."""

    MEAN = "mean"
    SUM = "sum"  # only for a facet whose values ADD UP (people, seats) -- decided in code
    MIN = "min"
    MAX = "max"
    RANGE = "range"  # highest minus lowest space in the group: "the largest gap"
    STDEV = "stdev"  # population standard deviation across the group's spaces: "how evenly"
    COUNT = "count"  # spaces with a value (a yes/no facet: spaces where it is yes)
    COUNT_ABOVE = "count_above"  # spaces strictly above a threshold the question states
    COUNT_BELOW = "count_below"  # spaces strictly below a threshold the question states


class SortOrder(str, Enum):
    ASC = "asc"  # fewest / lowest / smallest first
    DESC = "desc"  # most / highest / largest first


class CompareRelation(str, Enum):
    RATIO = "ratio"  # facet_a / facet_b
    DIFFERENCE = "difference"  # facet_a - facet_b
    EXCEEDS = "exceeds"  # facet_a > facet_b


class AggregateSpec(BaseModel):
    """Group the spaces in scope, reduce one facet per group, rank the groups (shape C3).

    ``facet`` is a catalogue key (a sensor facet as ``sensor:<modality>``); it is None only for
    ``count``, which then counts the spaces that pass the plan's filters. Every other criterion
    of an aggregate plan NARROWS which spaces are counted -- it never ranks them.
    """

    facet: Optional[str] = Field(None, description="A facet catalogue key, or None for count")
    group_by: GroupBy = GroupBy.FLOOR
    statistic: Statistic
    threshold: Optional[float] = Field(
        None, description="Only for count_above / count_below, and only a number the user stated"
    )
    order: SortOrder = SortOrder.DESC
    top_k: Optional[int] = Field(None, ge=1, description="Groups shown; presentation only")
    source_phrase: str = ""

    def core(self) -> Tuple:
        """The behavioural core the fingerprint hashes (``top_k`` and the phrase are not)."""
        return (
            self.facet or "",
            self.group_by.value,
            self.statistic.value,
            None if self.threshold is None else float(self.threshold),
            self.order.value,
        )


class CompareSpec(BaseModel):
    """Two numeric facts about the SAME spaces, side by side (shape C2).

    ``relation`` is the one the compiler ACCEPTED for the two facets' units; when it differs
    from what the question asked (a ratio between two figures that share no unit is not
    meaningful), ``requested_relation`` keeps the asked one so the answer can say why.
    """

    facet_a: str
    facet_b: str
    relation: CompareRelation = CompareRelation.DIFFERENCE
    requested_relation: Optional[CompareRelation] = None
    #: The question is about the whole (the building, a floor), not about each space: add a
    #: total -- only when both facets' values ADD UP, which code decides from their units.
    total: bool = False
    source_phrase: str = ""

    def core(self) -> Tuple:
        """The behavioural core the fingerprint hashes. The order of a and b is behaviour."""
        return (self.facet_a, self.facet_b, self.relation.value, bool(self.total))


class PeriodRef(BaseModel):
    """One period of a period comparison, RESOLVED by ``requested_interval.compared_periods``
    from the question's own words -- never a date the model wrote."""

    label: str  # "last week", "today", "weekdays (the last 14 days)"
    start: str  # store-clock (UTC) bounds, inclusive
    end: str
    #: "weekday" | "weekend": only those local days inside [start, end] belong to the period.
    day_type: Optional[str] = None
    #: The period is still in progress, so it holds only the readings that exist so far.
    partial: bool = False


class PeriodSpec(BaseModel):
    """One sensed facet over TWO periods, reduced per period and compared (shape C4).

    Per space and period the value is the store's reduction of every reading in the period
    (``aggregate_lane.run_aggregates``); ``statistic`` reduces the spaces: the mean or the sum of
    their period means, or the lowest minimum / highest maximum reading.
    """

    facet: str
    statistic: Statistic = Statistic.MEAN
    group_by: Optional[GroupBy] = None
    #: Exactly two, earlier first (weekdays before weekends).
    periods: List[PeriodRef] = Field(default_factory=list)
    source_phrase: str = ""

    def core(self) -> Tuple:
        """The behavioural core: the facet, the reduction, the grouping and the resolved bounds
        (the labels are presentation)."""
        return (
            self.facet,
            self.statistic.value,
            self.group_by.value if self.group_by is not None else "",
            tuple((p.start, p.end, p.day_type or "") for p in self.periods),
        )


class RelationKind(str, Enum):
    """How a measured series is related to what it is set against (shape C5)."""

    DURING = "during"  # its level during recorded events (or while a yes/no reading is on) vs not
    AFTER = "after"  # its level within a lag after each recorded event vs the same spaces' baseline
    CO_MOVEMENT = (
        "co_movement"  # two measured series in the same spaces: aligned-bucket correlation
    )


class RelateSpec(BaseModel):
    """How one measured series relates to events the building records, or to a second measured
    series, in the SAME spaces (shape C5). What it computes is co-occurrence -- the series' level
    during and outside the events, or how two series move together -- never a cause.

    ``series`` is a sensor facet key. ``events`` is an event-source facet key (the catalogue's
    ``event:<RecordClass>`` facets, discovered from the graph); ``other_series`` is a second sensor
    facet key -- a co-movement partner, or a yes/no reading whose ON periods stand in for events
    ("while the window is open"). The window and the lag are RESOLVED IN CODE from the question's
    own words (``compiler._relation_window`` / ``_stated_lag_minutes``), never written by a model.
    """

    series: str
    relation: RelationKind
    events: Optional[str] = None
    other_series: Optional[str] = None
    #: AFTER only: how long after each event's end counts as "after".
    lag_minutes: Optional[float] = None
    #: USER when the question states the lag, DEFAULT when the code supplied it (declared).
    lag_source: ThresholdSource = ThresholdSource.DEFAULT
    group_by: Optional[GroupBy] = None
    #: Store-clock (UTC) bounds, inclusive, when the question names a calendar day or period.
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    #: A trailing duration the question names ("over the last 3 days"), resolved against now.
    window_hours: Optional[float] = None
    #: The question's own words for the window ("last week"); presentation only.
    window_label: str = ""
    source_phrase: str = ""

    def core(self) -> Tuple:
        """The behavioural core the fingerprint hashes: what is related to what, how, over which
        window. Labels, phrases and whether a lag was stated or defaulted are presentation -- the
        same lag computes the same figures either way."""
        return (
            self.series,
            self.relation.value,
            self.events or "",
            self.other_series or "",
            None if self.lag_minutes is None else float(self.lag_minutes),
            self.group_by.value if self.group_by is not None else "",
            self.window_start or "",
            self.window_end or "",
            None if self.window_hours is None else float(self.window_hours),
        )


def operation_facet_keys(
    aggregate: Optional[AggregateSpec] = None,
    compare: Optional[CompareSpec] = None,
    period: Optional[PeriodSpec] = None,
    relate: Optional[RelateSpec] = None,
) -> List[str]:
    """The facet keys an operation reads, in order: the aggregated facet (none when spaces are
    counted), a and b of a comparison, the reading compared across two periods, or the series a
    relation reads and what it is set against (an event source or a second series)."""
    if aggregate is not None:
        return [aggregate.facet] if aggregate.facet else []
    if compare is not None:
        return [compare.facet_a, compare.facet_b]
    if period is not None:
        return [period.facet]
    if relate is not None:
        return [relate.series] + [k for k in (relate.events, relate.other_series) if k]
    return []


class CQIR(BaseModel):
    """The compiled constraint program. `signals` non-empty means NOT ready to run."""

    decision: DecisionKind
    target_kind: str = Field("space", description="What we choose between (v1: space)")
    constraints: List[Constraint] = Field(default_factory=list)
    spatial: List[SpatialQualifier] = Field(default_factory=list)
    time: TimeSpec = Field(default_factory=TimeSpec)
    signals: List[AmbiguitySignal] = Field(default_factory=list)
    event_criteria: List[EventCriterion] = Field(default_factory=list)
    #: v2 — criteria on facets of the graph (records, TTL properties, capacity, bookings).
    #: Empty for every plan the v1 compiler can produce, and then invisible to the fingerprint.
    facet_criteria: List[FacetCriterion] = Field(default_factory=list)
    #: v2 — group -> reduce -> rank (C3). None for every v1 plan, and then invisible.
    aggregate: Optional[AggregateSpec] = None
    #: v2 — two facets of the same spaces side by side (C2). None for every v1 plan.
    compare: Optional[CompareSpec] = None
    #: v2 — one reading over two periods (C4). None for every v1 plan.
    period: Optional[PeriodSpec] = None
    #: v2 — a series related to recorded events or to a second series (C5). None for every v1 plan.
    relate: Optional[RelateSpec] = None
    raw_query: str = ""

    @property
    def operation(self) -> Optional[str]:
        """The v2 operation this plan runs instead of a ranking of spaces, or None."""
        if self.aggregate is not None:
            return DecisionKind.AGGREGATE_RANK.value
        if self.compare is not None:
            return DecisionKind.COMPARE_FACETS.value
        if self.period is not None:
            return DecisionKind.PERIOD_COMPARE.value
        if self.relate is not None:
            return DecisionKind.RELATE.value
        return None

    def operation_facets(self) -> List[str]:
        """The facet keys this plan's operation reads (``operation_facet_keys``)."""
        return operation_facet_keys(self.aggregate, self.compare, self.period, self.relate)

    def is_executable(self) -> bool:
        """Ready for admission: has criteria (or an operation), no blocking ambiguity."""
        has_work = bool(
            self.constraints
            or self.facet_criteria
            or self.aggregate
            or self.compare
            or self.period
            or self.relate
        )
        return has_work and not self.signals

    def plan_fingerprint(self) -> str:
        """Deterministic hash of the BEHAVIORAL core — the determinism anchor.

        Hashes exactly what execution consumes: constraints (modality,
        direction, hardness, threshold+source, recipe, weight), spatial
        (relation, anchor), time (basis, horizons) and target_kind. Presentation
        styling (decision kind: select_one vs list_matching ranks identically)
        and provenance text (raw_query, source_phrase) are excluded — measured
        live, temp-0 local models wobble on exactly those non-behavioral
        fields while emitting byte-identical constraint programs.

        v2: facet criteria enter the core ONLY when there are some, and an operation
        (``aggregate`` / ``compare`` / ``period`` / ``relate``) ONLY when the plan has one. A plan without
        them hashes to exactly the bytes the v1 code produced, so every fingerprint recorded
        before facets existed still identifies the same plan (pinned by a test against a value
        computed on the unmodified v1 code).
        """
        import hashlib

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
            # The resolved interval belongs in the fingerprint: two questions that named
            # different days reasoned over different evidence, and a fingerprint that
            # cannot tell them apart would certify them identical. It is stable across
            # repeats of the same question on the same day, which is what the invariance
            # benchmark compares.
            "time": (
                self.time.basis.value,
                self.time.horizon_hours,
                self.time.window_hours,
                self.time.resolved_start,
                self.time.resolved_end,
            ),
            "events": sorted((e.kind, e.hours) for e in self.event_criteria),
        }
        if self.facet_criteria:
            core["facets"] = _facet_core(self.facet_criteria)
        if self.aggregate is not None:
            core["aggregate"] = self.aggregate.core()
        if self.compare is not None:
            core["compare"] = self.compare.core()
        if self.period is not None:
            core["period"] = self.period.core()
        if self.relate is not None:
            core["relate"] = self.relate.core()
        canon = json.dumps(core, sort_keys=True, default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
