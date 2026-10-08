# -*- coding: utf-8 -*-
"""operations.py — what a v2 plan computes when the answer is not a ranking of spaces (C3, C2, C4).

WHY THIS EXISTS
---------------
ARBITER answered one shape of question: rank the spaces. "Which floor has the fewest people
right now?" is not that shape -- it ranks FLOORS, by a figure each floor is reduced to from its
spaces. "What is the occupancy versus the capacity in each room?" ranks nothing at all -- it puts
two facts about the same spaces side by side. "Was it warmer this week than last week?" compares
one reading over two periods. Each compiled to a ranking of rooms, or to nothing, and the
arithmetic that answers them was left to whoever narrated the result.

This module is that arithmetic, and nothing else: given one value per space (already read by the
executor -- a sensor's windowed mean, or a facet value read through ``facet_resolvers``), it
groups, reduces, ranks, compares and reports coverage. It does no I/O and names no building, so
every figure it produces can be checked offline against the values it was handed.

THE RULES IT ENFORCES, each decided here in code and never by a prompt
---------------------------------------------------------------------
* A SUM is only formed for a quantity whose values ADD UP -- a count of people, of seats, an
  amount of energy. A temperature, a concentration or a sound level is a LEVEL: adding two rooms'
  readings produces a number that describes nothing. Decided from the facet's unit and kind
  (``additive``), never from the question's wording.
* A RATIO or an "exceeds" between two facets is only computed when they are counts of the same
  thing or share a unit (``compare_fit``). Two known units of different quantities are refused;
  a missing unit downgrades the relation to a difference with each figure's unit shown.
* EVERY GROUP FIGURE CARRIES ITS n: how many spaces contributed, and which spaces in the group had
  no usable value (never imputed, never silently dropped). A range or a standard deviation needs
  two spaces; one space is reported as one space, not as a spread of zero.
* An entity missing either side of a comparison is listed as NOT COMPARABLE, with the reason.
  Two periods are compared over the spaces with readings in BOTH, for the same reason.
* Ties are ties: the order between equal figures is the group's own sort key (a floor's number,
  then its name), and the answer says when the top is shared.

WHY aggregate_lane's GROUPING IS NOT REUSED HERE
------------------------------------------------
``aggregate_lane.combine_windowed`` / ``combine_latest`` reduce per-SENSOR store aggregates
(``SensorAgg`` / ``SensorLatest`` rows from a SQL GROUP BY) and carry sensor-level rules that are
right there and wrong here: a floor-level meter replaces the rooms it already counts, one reading
per room, a peak sensor in the direction asked. ARBITER has already reduced each SPACE to one
value (``plan_executor.EvidenceCell``), its groups can be room kinds as well as floors, and the
statistics C3 needs -- a range with BOTH extreme spaces, a population standard deviation, a count
above a threshold the user stated, dispersion across groups and across spaces -- are not in
``GroupStat``. Feeding spaces through it as fake sensors would inherit its rules without its
premises. What IS shared is the unit contract both lanes stand on: ``units.normalise`` and
``units.quantity_kind`` decide what a unit measures, exactly as ``aggregate_lane._kind_of`` does.

For C4 aggregate_lane IS reused, at the layer where it fits: ``plan_executor._run_period`` has the
store reduce every reading of each period per sensor (``aggregate_lane.run_aggregates`` and its
readiness check), so a week is read whole, never cut to its newest rows by a row fetch; this
module then combines those per-space period means exactly as C3 combines per-space values.

C5 (a series related to recorded events or to a second series) works the same way one level
finer: the store reduces each series into fixed time BUCKETS (``aggregate_lane.run_buckets``), and
this module classifies the buckets against the events and computes the co-occurrence statistics.
What it reports is co-occurrence -- a level during and outside events, a correlation of aligned
buckets -- and never a cause; every figure carries how many spaces, events, buckets and readings
it rests on, and a space missing either side is named, never imputed.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from orchestrator.services.deliberation.cqir import (
    AggregateSpec,
    CompareRelation,
    CompareSpec,
    RelationKind,
    SortOrder,
    Statistic,
)

if TYPE_CHECKING:  # pragma: no cover - facets imports the compiler, which imports this module
    from orchestrator.services.deliberation.facets import Facet

#: Figures are kept to this many decimals: enough to show what the evidence supports, and the
#: same rounding everywhere, so the answer and the dossier print the same digits.
DECIMALS = 2

#: Unit words that count DISCRETE things. Generic English; the unit contract (units.py) does not
#: list them because no sensor reports "people" as a physical unit -- but a count of people, of
#: seats or of bays is the commonest thing a building adds up.
_COUNT_UNITS = frozenset(
    {"people", "person", "persons", "occupants", "count", "seats", "desks", "bays", "items"}
)

#: Quantity kinds (units._KIND) whose values add up across spaces: amounts, not levels.
_ADDITIVE_KINDS = frozenset({"count", "energy", "volume", "mass", "power"})

#: How many spaces a "missing" or "not comparable" list names before it says "and N more".
MAX_NAMED = 8


def _r(value: Optional[float]) -> Optional[float]:
    """A figure rounded the one way every figure here is rounded."""
    if value is None:
        return None
    rounded = round(float(value), DECIMALS)
    return 0.0 if rounded == 0 else rounded  # never "-0"


def rounded(value: Optional[float]) -> Optional[float]:
    """A figure rounded as every figure an operation reports is rounded."""
    return _r(value)


def fmt(value: Optional[float]) -> str:
    """A figure as the answer prints it (no trailing zeros)."""
    return "" if value is None else f"{_r(value):g}"


def with_unit(value: Optional[float], unit: str) -> str:
    """A figure with its unit, as the answer prints it: "3 people", "1 person", "21.5 °C"."""
    text = fmt(value)
    if not text or not unit:
        return text
    if unit == "people" and text == "1":
        return "1 person"
    return f"{text} {unit}"


# ── what a facet's values mean ───────────────────────────────────────────────────────────


def facet_unit(facet: Optional["Facet"]) -> str:
    """The facet's unit as a reader sees it ("°C", "people", "ppm"), or "" when it has none."""
    raw = str(getattr(facet, "unit", None) or "").strip()
    if not raw:
        return ""
    from orchestrator.services import units

    return units.normalise(raw)


def _names_a_count(facet: "Facet") -> bool:
    """True when an integer facet's own name says it COUNTS something: "seatCount", "number of
    lockers". A "floorNumber" is an ordinal, not a count, so only these two shapes qualify."""
    from orchestrator.services.deliberation.coverage_audit import _local

    name = _local(str(getattr(facet, "predicate", None) or getattr(facet, "key", "") or ""))
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").lower().split()
    if not words:
        return False
    return words[-1] in ("count", "counts") or words[:2] == ["number", "of"]


def is_count(facet: Optional["Facet"]) -> bool:
    """True when the facet's values are counts of discrete things (people, seats, lockers)."""
    if facet is None or getattr(facet, "value_type", "") not in ("number", "integer"):
        return False
    unit = facet_unit(facet).lower()
    if unit in _COUNT_UNITS:
        return True
    from orchestrator.services import units

    if unit and units.quantity_kind(unit) == "count":
        return True
    return not unit and getattr(facet, "value_type", "") == "integer" and _names_a_count(facet)


def additive(facet: Optional["Facet"]) -> Tuple[bool, str]:
    """(may this facet's values be ADDED across spaces, the reason when not).

    Decided from the facet's unit and kind, never from the question: a count of people or seats
    and an amount of energy add up; a temperature, a concentration or a sound level is a level,
    and their total describes nothing.
    """
    if facet is None:
        return False, "nothing was named to add up"
    label = str(getattr(facet, "label", "") or getattr(facet, "key", ""))
    if getattr(facet, "value_type", "") not in ("number", "integer"):
        return False, f"{label} is not a number"
    if is_count(facet):
        return True, ""
    unit = facet_unit(facet)
    from orchestrator.services import units

    kind = units.quantity_kind(unit) if unit else None
    if kind in _ADDITIVE_KINDS:
        return True, ""
    if unit:
        return False, (
            f"{label} is a level measured in {unit}, not an amount — adding up spaces' "
            "levels produces a number that describes nothing"
        )
    return False, f"{label} has no recorded unit that says its values add up"


@dataclass(frozen=True)
class CompareFit:
    """What comparing two facets is allowed to compute."""

    relation: Optional[CompareRelation] = None
    #: (multiply, add) turning facet_b's values into facet_a's unit; None when no conversion.
    convert_b: Optional[Tuple[float, float]] = None
    #: A sentence the answer carries: a conversion applied, or why the relation was changed.
    note: str = ""
    #: Why the two cannot be compared at all (the compiler turns it into a signal).
    refusal: str = ""


def compare_fit(a: "Facet", b: "Facet", relation: CompareRelation) -> CompareFit:
    """Whether ``relation`` between two facets means anything, from their units alone.

    * Both must be numbers.
    * The same unit, or two counts of the same thing (people against people): any relation.
    * Two known units of one quantity with an approved conversion: any relation, b converted.
    * Two counts of DIFFERENT things (people against seats), or a figure with no recorded unit:
      a difference with each figure's unit named -- a ratio or "exceeds" would claim the two
      measure one thing, which nothing recorded says.
    * Two known units of different quantities (ppm against °C): refused -- no relation between
      them means anything, a difference included.
    """
    label_a = str(getattr(a, "label", "") or getattr(a, "key", ""))
    label_b = str(getattr(b, "label", "") or getattr(b, "key", ""))
    for facet, label in ((a, label_a), (b, label_b)):
        if getattr(facet, "value_type", "") not in ("number", "integer"):
            kind = getattr(facet, "value_type", "") or "not a number"
            return CompareFit(refusal=f"{label} is {_article(kind)} {kind} value, not a figure")
    ua, ub = facet_unit(a), facet_unit(b)
    count_a, count_b = is_count(a), is_count(b)
    if ua and ub and ua == ub:
        return CompareFit(relation=relation)
    from orchestrator.services import units

    if ua and ub:
        conversion = units.convert(1.0, ub, ua)
        offset = units.convert(0.0, ub, ua)
        if conversion.ok and offset.ok:
            add = float(offset.value or 0.0)
            mul = float(conversion.value or 0.0) - add
            return CompareFit(
                relation=relation,
                convert_b=(mul, add),
                note=f"{label_b} converted from {ub} to {ua} ({conversion.factor})",
            )
        if not (count_a and count_b):
            return CompareFit(
                refusal=(
                    f"{label_a} is measured in {ua} and {label_b} in {ub} — different "
                    "quantities, so no comparison between them means anything"
                )
            )
    # Two counts of different things, or a side with no recorded unit: the two figures are
    # shown with their own units, as a difference, and nothing claims they measure one thing.
    if relation == CompareRelation.DIFFERENCE:
        return CompareFit(relation=relation, note=_units_shown(label_a, ua, label_b, ub))
    return CompareFit(
        relation=CompareRelation.DIFFERENCE,
        note=(
            f"a {relation.value.replace('_', ' ')} needs two figures of one kind; "
            + _units_shown(label_a, ua, label_b, ub)
            + ", so the difference is shown instead"
        ),
    )


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _units_shown(label_a: str, ua: str, label_b: str, ub: str) -> str:
    def one(label: str, unit: str) -> str:
        return f"{label} in {unit}" if unit else f"{label} with no recorded unit"

    return f"{one(label_a, ua)} and {one(label_b, ub)}"


# ── the values handed in, and the results handed out ─────────────────────────────────────


class SpaceValue(BaseModel):
    """One space's value for the facet an operation reads, with where it came from."""

    space_iri: str
    label: str
    #: The groups the space belongs to (one floor; possibly several room kinds).
    groups: List[str] = Field(default_factory=list)
    value: Optional[float] = None
    #: A yes/no facet's value.
    flag: Optional[bool] = None
    #: True when the space has a usable value (for a count of spaces: always).
    present: bool = False
    display: str = ""
    provenance: str = ""
    #: Why the space has no usable value ("no reading", "records disagree: ...").
    reason: str = ""


class GroupResult(BaseModel):
    """One group (a floor, the building, a room kind) reduced to the figure it is ranked on."""

    key: str
    label: str
    #: Position among the groups that HAVE a figure, 1-based; None for a group without one.
    rank: Optional[int] = None
    #: The statistic asked for.
    value: Optional[float] = None
    #: Spaces that contributed a value.
    n: int = 0
    mean: Optional[float] = None
    stdev: Optional[float] = None
    low: Optional[float] = None
    low_space: str = ""
    high: Optional[float] = None
    high_space: str = ""
    #: Highest minus lowest, with two or more spaces.
    spread: Optional[float] = None
    #: The group's values added up -- only when they ADD UP.
    total: Optional[float] = None
    #: Spaces in the group with no usable value ("Room 2.04 (no reading)"), named up to
    #: MAX_NAMED; ``n_missing`` is how many there are.
    missing: List[str] = Field(default_factory=list)
    n_missing: int = 0
    #: Spaces in the group whose filter could not be checked: not counted, named.
    unverified: List[str] = Field(default_factory=list)
    n_unverified: int = 0
    #: Why the group has no figure.
    note: str = ""


class Dispersion(BaseModel):
    """How evenly a quantity is spread: across the groups' means, and across the spaces."""

    groups_n: int = 0
    groups_stdev: Optional[float] = None
    groups_low: Optional[float] = None
    groups_low_label: str = ""
    groups_high: Optional[float] = None
    groups_high_label: str = ""
    spaces_n: int = 0
    spaces_stdev: Optional[float] = None
    spaces_low: Optional[float] = None
    spaces_low_label: str = ""
    spaces_high: Optional[float] = None
    spaces_high_label: str = ""


class AggregateResult(BaseModel):
    """The whole result of an AGGREGATE_RANK plan."""

    facet: str = ""
    label: str = ""
    unit: str = ""
    statistic: str
    group_by: str
    order: str
    threshold: Optional[float] = None
    top_k: Optional[int] = None
    #: How each space's value was obtained ("recent mean (last readings)", "recorded value").
    basis: str = ""
    #: True when the facet is a yes/no fact, so a count is of the spaces where it is yes.
    yes_no: bool = False
    #: Ranked groups first (by figure, then the group's sort key), then those without one.
    groups: List[GroupResult] = Field(default_factory=list)
    #: Labels of the groups sharing the top figure (more than one means a tie).
    tied_top: List[str] = Field(default_factory=list)
    #: Spaces with no group (no floor, no room kind recorded): not counted, named.
    unplaced: List[str] = Field(default_factory=list)
    n_unplaced: int = 0
    #: Spaces counted in more than one group (a space of several room kinds).
    overlapping: int = 0
    dispersion: Optional[Dispersion] = None
    #: Every per-space value the result rests on -- the evidence.
    spaces: List[SpaceValue] = Field(default_factory=list)
    #: Distinct spaces that contributed to any group.
    n_spaces: int = 0
    notes: List[str] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    """One space with both facets side by side, or why it cannot be compared."""

    space_iri: str
    label: str
    a: Optional[float] = None
    b: Optional[float] = None
    a_display: str = ""
    b_display: str = ""
    a_provenance: str = ""
    b_provenance: str = ""
    ratio: Optional[float] = None
    #: The ratio as a percentage, when a ratio is meaningful.
    percent: Optional[float] = None
    difference: Optional[float] = None
    exceeds: Optional[bool] = None
    comparable: bool = False
    #: Why it is not comparable ("no capacity recorded").
    reason: str = ""


class ComparisonTotal(BaseModel):
    """Both facets added up over the spaces that have both -- only when both add up."""

    n: int = 0
    a: float = 0.0
    b: float = 0.0
    ratio: Optional[float] = None
    percent: Optional[float] = None
    difference: Optional[float] = None
    exceeds: Optional[bool] = None
    #: Spaces with only facet_a (or only facet_b), and what that side adds up to there.
    a_only_n: int = 0
    a_only_sum: Optional[float] = None
    b_only_n: int = 0
    b_only_sum: Optional[float] = None


class CompareResult(BaseModel):
    """The whole result of a COMPARE_FACETS plan."""

    facet_a: str
    facet_b: str
    label_a: str = ""
    label_b: str = ""
    unit_a: str = ""
    unit_b: str = ""
    relation: str
    requested_relation: Optional[str] = None
    basis: str = ""
    #: Comparable spaces, sorted by the relation (largest first; exceeding first).
    rows: List[ComparisonRow] = Field(default_factory=list)
    not_comparable: List[ComparisonRow] = Field(default_factory=list)
    n_comparable: int = 0
    n_exceeding: int = 0
    total: Optional[ComparisonTotal] = None
    notes: List[str] = Field(default_factory=list)


# ── grouping ─────────────────────────────────────────────────────────────────────────────

_DIGITS_RE = re.compile(r"-?\d+")


def group_sort_key(key: str, label: str = "") -> Tuple[int, int, str]:
    """The order of groups with equal figures: a floor's number first, then its name."""
    text = f"{label} {key}"
    match = _DIGITS_RE.search(text)
    if match:
        return (0, int(match.group(0)), (label or key).lower())
    return (1, 0, (label or key).lower())


def _pstdev(values: Sequence[float]) -> Optional[float]:
    """Population standard deviation: the spread of THESE spaces, not an estimate of others."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _extremes(
    members: Sequence[SpaceValue],
) -> Tuple[Optional[SpaceValue], Optional[SpaceValue]]:
    """(lowest, highest) member by value; ties go to the space named first alphabetically."""
    valued = [m for m in members if m.value is not None]
    if not valued:
        return None, None
    lo = sorted(valued, key=lambda m: (float(m.value), m.label.lower(), m.space_iri))[0]
    hi = sorted(valued, key=lambda m: (-float(m.value), m.label.lower(), m.space_iri))[0]
    return lo, hi


def _named(spaces: Sequence[str]) -> List[str]:
    names = sorted(dict.fromkeys(s for s in spaces if s), key=str.lower)
    if len(names) <= MAX_NAMED:
        return names
    return names[:MAX_NAMED] + [f"and {len(names) - MAX_NAMED} more"]


def _reduce(
    group: GroupResult,
    members: Sequence[SpaceValue],
    spec: AggregateSpec,
    is_boolean: bool,
    adds_up: bool,
) -> None:
    """Fill one group's figures from its members. In place."""
    present = [m for m in members if m.present]
    group.n = len(present)
    absent = [f"{m.label} ({m.reason})" if m.reason else m.label for m in members if not m.present]
    group.missing = _named(absent)
    group.n_missing = len(absent)
    nums = [float(m.value) for m in present if m.value is not None]
    if nums:
        group.mean = _r(sum(nums) / len(nums))
        group.stdev = _r(_pstdev(nums))
        lo, hi = _extremes([m for m in present if m.value is not None])
        group.low, group.low_space = _r(lo.value), lo.label
        group.high, group.high_space = _r(hi.value), hi.label
        if len(nums) >= 2:
            group.spread = _r(hi.value - lo.value)
        if adds_up:
            group.total = _r(sum(nums))
    stat = spec.statistic
    if stat == Statistic.COUNT:
        if is_boolean:
            group.value = float(sum(1 for m in present if m.flag is True))
        else:
            group.value = float(group.n)
        return
    if stat in (Statistic.COUNT_ABOVE, Statistic.COUNT_BELOW):
        if not nums:
            group.note = "no space in it has a value"
            return
        threshold = float(spec.threshold or 0.0)
        if stat == Statistic.COUNT_ABOVE:
            group.value = float(sum(1 for v in nums if v > threshold))
        else:
            group.value = float(sum(1 for v in nums if v < threshold))
        return
    if not nums:
        group.note = "no space in it has a value"
        return
    if stat == Statistic.MEAN:
        group.value = group.mean
    elif stat == Statistic.SUM:
        group.value = group.total
        if not adds_up:
            group.note = "its values do not add up"
    elif stat == Statistic.MIN:
        group.value = group.low
    elif stat == Statistic.MAX:
        group.value = group.high
    elif stat == Statistic.RANGE:
        group.value = group.spread
        if group.spread is None:
            group.note = "only one space in it has a value, so it has no spread"
    elif stat == Statistic.STDEV:
        group.value = group.stdev
        if group.stdev is None:
            group.note = "only one space in it has a value, so it has no spread"


def _dispersion(groups: Sequence[GroupResult], spaces: Sequence[SpaceValue]) -> Dispersion:
    """Spread across the groups' means AND across the individual spaces, each with its n."""
    out = Dispersion()
    means = [g for g in groups if g.mean is not None and g.n > 0]
    out.groups_n = len(means)
    if means:
        out.groups_stdev = _r(_pstdev([float(g.mean) for g in means]))
        lo = sorted(means, key=lambda g: (float(g.mean), group_sort_key(g.key, g.label)))[0]
        hi = sorted(means, key=lambda g: (-float(g.mean), group_sort_key(g.key, g.label)))[0]
        out.groups_low, out.groups_low_label = lo.mean, lo.label
        out.groups_high, out.groups_high_label = hi.mean, hi.label
    unique: Dict[str, SpaceValue] = {}
    for s in spaces:
        if s.present and s.value is not None:
            unique.setdefault(s.space_iri, s)
    values = list(unique.values())
    out.spaces_n = len(values)
    if values:
        out.spaces_stdev = _r(_pstdev([float(s.value) for s in values]))
        lo_s, hi_s = _extremes(values)
        out.spaces_low, out.spaces_low_label = _r(lo_s.value), lo_s.label
        out.spaces_high, out.spaces_high_label = _r(hi_s.value), hi_s.label
    return out


def aggregate(
    spec: AggregateSpec,
    spaces: Sequence[SpaceValue],
    *,
    label: str,
    unit: str = "",
    adds_up: bool = False,
    is_boolean: bool = False,
    basis: str = "",
    group_labels: Optional[Dict[str, str]] = None,
    unverified: Optional[Dict[str, List[str]]] = None,
    notes: Iterable[str] = (),
) -> AggregateResult:
    """Group the spaces, reduce each group, rank the groups. Deterministic, no I/O.

    ``spaces`` carries one entry per space in the population (after every filter), each with
    the groups it belongs to; a space with no group is reported as unplaced. ``unverified`` maps
    a group key to the spaces in it whose filter could not be checked -- named, never counted.
    """
    labels = dict(group_labels or {})
    by_group: Dict[str, List[SpaceValue]] = {}
    unplaced: List[str] = []
    memberships: Dict[str, int] = {}
    for s in spaces:
        if not s.groups:
            unplaced.append(s.label)
            continue
        for key in s.groups:
            by_group.setdefault(key, []).append(s)
        memberships[s.space_iri] = len(s.groups)
    for key in unverified or {}:
        by_group.setdefault(key, [])
    groups: List[GroupResult] = []
    for key, members in by_group.items():
        group = GroupResult(key=key, label=labels.get(key) or key)
        _reduce(group, members, spec, is_boolean, adds_up)
        held_back = list((unverified or {}).get(key, []))
        group.unverified = _named(held_back)
        group.n_unverified = len(held_back)
        if not members and group.unverified:
            group.note = "no space in it could be verified on what you asked for"
        groups.append(group)
    ranked = [g for g in groups if g.value is not None]
    others = [g for g in groups if g.value is None]
    descending = spec.order == SortOrder.DESC
    ranked.sort(
        key=lambda g: (
            -float(g.value) if descending else float(g.value),
            group_sort_key(g.key, g.label),
        )
    )
    for position, group in enumerate(ranked, 1):
        group.rank = position
    others.sort(key=lambda g: group_sort_key(g.key, g.label))
    tied = [g.label for g in ranked if g.value == ranked[0].value] if ranked else []
    result = AggregateResult(
        facet=spec.facet or "",
        label=label,
        unit=unit,
        statistic=spec.statistic.value,
        group_by=spec.group_by.value,
        order=spec.order.value,
        threshold=spec.threshold,
        top_k=spec.top_k,
        basis=basis,
        yes_no=is_boolean,
        groups=ranked + others,
        tied_top=tied,
        unplaced=_named(unplaced),
        n_unplaced=len(unplaced),
        overlapping=sum(1 for n in memberships.values() if n > 1),
        spaces=sorted(spaces, key=lambda s: (s.label.lower(), s.space_iri)),
        n_spaces=len({s.space_iri for s in spaces if s.present and s.groups}),
        notes=[n for n in notes if n],
    )
    if spec.statistic in (Statistic.STDEV, Statistic.RANGE):
        result.dispersion = _dispersion(ranked + others, [s for s in spaces if s.groups])
    return result


# ── comparing two facets of the same spaces ──────────────────────────────────────────────


def compare(
    spec: CompareSpec,
    rows: Sequence[ComparisonRow],
    *,
    label_a: str,
    label_b: str,
    unit_a: str = "",
    unit_b: str = "",
    adds_up: bool = False,
    basis: str = "",
    convert_b: Optional[Tuple[float, float]] = None,
    notes: Iterable[str] = (),
) -> CompareResult:
    """Per space: a, b, and the relation; a total over the spaces with both, when both add up.

    ``rows`` arrive with ``a`` / ``b`` filled where the space has a usable value and ``reason``
    naming what is missing otherwise. Nothing is imputed: a space without both is listed as not
    comparable, and the total is formed ONLY over the spaces that have both -- the spaces with one
    side are counted and summed separately, so the reader sees what was left out of it.
    """
    relation = spec.relation
    comparable: List[ComparisonRow] = []
    apart: List[ComparisonRow] = []
    for row in rows:
        row = row.model_copy()
        if row.b is not None and convert_b is not None:
            row.b = _r(row.b * convert_b[0] + convert_b[1])
        if row.a is None or row.b is None:
            row.comparable = False
            if not row.reason:
                missing = [lbl for lbl, v in ((label_a, row.a), (label_b, row.b)) if v is None]
                row.reason = "no " + " and no ".join(missing) + " recorded"
            apart.append(row)
            continue
        row.comparable = True
        row.difference = _r(row.a - row.b)
        row.exceeds = row.a > row.b
        if relation == CompareRelation.RATIO or relation == CompareRelation.EXCEEDS:
            if row.b:
                row.ratio = _r(row.a / row.b)
                row.percent = _r(row.a / row.b * 100.0)
        comparable.append(row)

    def order(row: ComparisonRow):
        if relation == CompareRelation.EXCEEDS:
            return (not row.exceeds, -(row.difference or 0.0), row.label.lower())
        if relation == CompareRelation.RATIO:
            missing_ratio = row.ratio is None
            return (missing_ratio, -(row.ratio or 0.0), row.label.lower())
        return (-(row.difference or 0.0), row.label.lower())

    comparable.sort(key=order)
    apart.sort(key=lambda r: r.label.lower())
    result = CompareResult(
        facet_a=spec.facet_a,
        facet_b=spec.facet_b,
        label_a=label_a,
        label_b=label_b,
        unit_a=unit_a,
        unit_b=unit_a if convert_b is not None else unit_b,
        relation=relation.value,
        requested_relation=(
            spec.requested_relation.value if spec.requested_relation is not None else None
        ),
        basis=basis,
        rows=comparable,
        not_comparable=apart,
        n_comparable=len(comparable),
        n_exceeding=sum(1 for r in comparable if r.exceeds),
        notes=[n for n in notes if n],
    )
    if spec.total and adds_up and comparable:
        total_a = sum(float(r.a) for r in comparable)
        total_b = sum(float(r.b) for r in comparable)
        only_a = [r for r in apart if r.a is not None and r.b is None]
        only_b = [r for r in apart if r.b is not None and r.a is None]
        # A ratio of the totals only where a ratio of the spaces' figures means something.
        proportional = relation in (CompareRelation.RATIO, CompareRelation.EXCEEDS) and total_b
        result.total = ComparisonTotal(
            n=len(comparable),
            a=_r(total_a),
            b=_r(total_b),
            ratio=_r(total_a / total_b) if proportional else None,
            percent=_r(total_a / total_b * 100.0) if proportional else None,
            difference=_r(total_a - total_b),
            exceeds=total_a > total_b,
            a_only_n=len(only_a),
            a_only_sum=_r(sum(float(r.a) for r in only_a)) if only_a else None,
            b_only_n=len(only_b),
            b_only_sum=_r(sum(float(r.b) for r in only_b)) if only_b else None,
        )
    return result


# ── one reading over two periods (C4) ────────────────────────────────────────────────────


class PeriodSpace(BaseModel):
    """One space's reading in each of the two periods, as the store reduced it."""

    space_iri: str
    label: str
    groups: List[str] = Field(default_factory=list)
    #: Per period: the mean of every reading, the lowest and highest reading, how many.
    a_mean: Optional[float] = None
    a_low: Optional[float] = None
    a_high: Optional[float] = None
    a_n: int = 0
    b_mean: Optional[float] = None
    b_low: Optional[float] = None
    b_high: Optional[float] = None
    b_n: int = 0
    #: Why the space is not compared ("no readings last week").
    reason: str = ""

    @property
    def paired(self) -> bool:
        """True when the space has readings in BOTH periods -- the only spaces compared."""
        return self.a_n > 0 and self.b_n > 0


class PeriodWindow(BaseModel):
    """One period as the answer states it."""

    label: str
    start: str
    end: str
    #: The bounds in building time, for the reader.
    shown: str = ""
    day_type: Optional[str] = None
    partial: bool = False
    #: For a weekday/weekend period: how many local days of that type the window holds.
    days: int = 0


class PeriodFigure(BaseModel):
    """Both periods' figures for one group of spaces (or for all of them), and the change."""

    key: str
    label: str
    #: Spaces with readings in both periods.
    n: int = 0
    a: Optional[float] = None
    b: Optional[float] = None
    #: For the lowest / highest reading: the space that holds it in each period.
    a_space: str = ""
    b_space: str = ""
    #: b minus a: the later period against the earlier (weekends against weekdays).
    change: Optional[float] = None
    #: The change as a percentage of a's figure; None when a is zero.
    percent: Optional[float] = None
    direction: str = ""  # higher | lower | the same
    readings_a: int = 0
    readings_b: int = 0


class PeriodResult(BaseModel):
    """The whole result of a PERIOD_COMPARE plan."""

    facet: str
    label: str = ""
    unit: str = ""
    statistic: str
    group_by: str = ""
    periods: List[PeriodWindow] = Field(default_factory=list)
    overall: Optional[PeriodFigure] = None
    groups: List[PeriodFigure] = Field(default_factory=list)
    spaces: List[PeriodSpace] = Field(default_factory=list)
    #: Spaces not compared, with the reason, named up to MAX_NAMED; how many in all.
    not_compared: List[str] = Field(default_factory=list)
    n_not_compared: int = 0
    notes: List[str] = Field(default_factory=list)


def _period_reduce(
    statistic: str, members: Sequence[PeriodSpace], side: str
) -> Tuple[Optional[float], str]:
    """(one period's figure over the paired spaces, the space holding it for a min / max)."""
    if statistic in (Statistic.MIN.value, Statistic.MAX.value):
        field_name = f"{side}_low" if statistic == Statistic.MIN.value else f"{side}_high"
        sign = 1.0 if statistic == Statistic.MIN.value else -1.0
        held = [m for m in members if getattr(m, field_name) is not None]
        if not held:
            return None, ""
        extreme = sorted(
            held, key=lambda m: (sign * float(getattr(m, field_name)), m.label.lower())
        )[0]
        return _r(getattr(extreme, field_name)), extreme.label
    means = [float(getattr(m, f"{side}_mean")) for m in members]
    if not means:
        return None, ""
    if statistic == Statistic.SUM.value:
        return _r(sum(means)), ""
    return _r(sum(means) / len(means)), ""


def _period_figure(
    key: str, label: str, statistic: str, members: Sequence[PeriodSpace]
) -> PeriodFigure:
    paired = [m for m in members if m.paired]
    figure = PeriodFigure(key=key, label=label, n=len(paired))
    figure.a, figure.a_space = _period_reduce(statistic, paired, "a")
    figure.b, figure.b_space = _period_reduce(statistic, paired, "b")
    figure.readings_a = sum(m.a_n for m in paired)
    figure.readings_b = sum(m.b_n for m in paired)
    if figure.a is not None and figure.b is not None:
        figure.change = _r(figure.b - figure.a)
        figure.percent = _r(figure.change / abs(figure.a) * 100.0) if figure.a else None
        figure.direction = (
            "the same" if figure.change == 0 else ("higher" if figure.change > 0 else "lower")
        )
    return figure


def compare_periods(
    statistic: Statistic,
    spaces: Sequence[PeriodSpace],
    periods: Sequence[PeriodWindow],
    *,
    facet: str,
    label: str,
    unit: str = "",
    group_by: str = "",
    group_labels: Optional[Dict[str, str]] = None,
    notes: Iterable[str] = (),
) -> PeriodResult:
    """Both periods' figures over the spaces with readings in BOTH -- like against like.

    A space with readings in one period only is not compared and is named: comparing this week's
    twelve rooms with last week's ten would report a change in which rooms were read, not in
    the rooms. Per group when ``group_by`` is set, always overall.
    """
    labels = dict(group_labels or {})
    result = PeriodResult(
        facet=facet,
        label=label,
        unit=unit,
        statistic=statistic.value,
        group_by=group_by,
        periods=list(periods),
        spaces=sorted(spaces, key=lambda s: (s.label.lower(), s.space_iri)),
        notes=[n for n in notes if n],
    )
    result.overall = _period_figure("all", "all spaces", statistic.value, spaces)
    if group_by:
        by_group: Dict[str, List[PeriodSpace]] = {}
        for s in spaces:
            for key in s.groups:
                by_group.setdefault(key, []).append(s)
        result.groups = [
            _period_figure(key, labels.get(key) or key, statistic.value, members)
            for key, members in sorted(
                by_group.items(), key=lambda kv: group_sort_key(kv[0], labels.get(kv[0], ""))
            )
        ]
    apart = [f"{s.label} ({s.reason})" if s.reason else s.label for s in spaces if not s.paired]
    result.not_compared = _named(apart)
    result.n_not_compared = len(apart)
    return result


# ── one series related to recorded events or to a second series (C5) ─────────────────────
#
# THE RULES, decided here and never by a prompt:
# * A bucket is DURING an event when at least half of it lies inside one, OUTSIDE when none of it
#   does; a bucket that straddles an event's start or end is in NEITHER figure and is counted. For
#   "after", a bucket is AFTER when at least half of it lies within the lag after an event's end and
#   none of it during an event, BASELINE when it is neither during an event nor in any lag; the rest
#   is in neither figure. Fixed rules, so the same readings and events always give the same split.
# * Means are of every READING in the buckets (the store's count and sum), never of bucket means.
# * Spaces are pooled ONLY where they have both sides -- like against like, the C4 rule -- and the
#   per-space differences are reported beside the pooled figure, because a pooled mean can be moved
#   by which spaces hold the most events rather than by anything that happens during them.
# * A correlation needs at least ``MIN_PAIRS`` aligned buckets and both series varying; otherwise it
#   is not computed and the space says why. Pooled correlations are WITHIN-SPACE: each space's own
#   averages are removed first, so a busy room is never "correlated" with a quiet one.
# * An event with no duration (an access denial) has no "during"; it is counted, never stretched.

#: A bucket counts as during (or after) an event when at least this share of it lies inside one.
IN_SHARE = 0.5
#: The fewest aligned buckets a correlation is computed from.
MIN_PAIRS = 3

_IN, _OUT, _NEITHER = "in", "out", "neither"


@dataclass(frozen=True)
class Bucket:
    """One time bucket of one series as the store reduced it: how many readings, their sum."""

    n: int
    total: float

    @property
    def mean(self) -> float:
        """The mean of every reading in the bucket."""
        return self.total / self.n if self.n else 0.0


@dataclass
class RelationInput:
    """One space's inputs to a relation: its series in buckets, and what it is related to."""

    space_iri: str
    label: str
    groups: List[str] = field(default_factory=list)
    #: The series asked about: bucket number (counted from the window's start) -> Bucket.
    series: Dict[int, Bucket] = field(default_factory=dict)
    #: The second series (co-movement) or the yes/no reading (during a state), bucketed alike.
    other: Dict[int, Bucket] = field(default_factory=dict)
    #: The space's recorded events as (start, end) SECONDS from the window's start; an instant has
    #: end == start. Events that straddle the window's edges keep their real bounds.
    events: List[Tuple[float, float]] = field(default_factory=list)
    #: Why the space cannot contribute at all (no sensor, a store that could not be read).
    reason: str = ""


class RelationSpace(BaseModel):
    """One space's side of a relation, with every n it rests on, or why it has no figure."""

    space_iri: str
    label: str
    groups: List[str] = Field(default_factory=list)
    #: during / after: the events in the space inside the window (episodes, for a yes/no state),
    #: those with readings during (after) them, and those whose figure is above the space's
    #: figure outside them.
    events: int = 0
    events_read: int = 0
    events_above: int = 0
    #: Events with no duration: nothing is "during" an instant.
    instants: int = 0
    in_mean: Optional[float] = None
    in_buckets: int = 0
    in_readings: int = 0
    out_mean: Optional[float] = None
    out_buckets: int = 0
    out_readings: int = 0
    #: Buckets in neither figure (straddling an event's edge; for "after", also during an event;
    #: for a state, a bucket where it was on for part of the time).
    neither_buckets: int = 0
    #: The sums behind the means, kept so spaces can be pooled reading by reading.
    in_total: float = 0.0
    out_total: float = 0.0
    difference: Optional[float] = None
    #: co-movement: aligned buckets, Pearson and Spearman on them, and on bucket-to-bucket changes.
    pairs: int = 0
    pearson: Optional[float] = None
    spearman: Optional[float] = None
    changes: int = 0
    change_pearson: Optional[float] = None
    #: Why the space is not in the pooled figure.
    reason: str = ""

    @property
    def compared(self) -> bool:
        """True when the space contributes to the pooled figure."""
        if self.pearson is not None:
            return True
        return self.in_readings > 0 and self.out_readings > 0


class RelationFigure(BaseModel):
    """A relation pooled over a group of spaces (or all of them), every figure with its n."""

    key: str
    label: str
    #: Spaces with both sides (during / after / state) or with a correlation (co-movement).
    spaces: int = 0
    events: int = 0
    events_read: int = 0
    events_above: int = 0
    in_mean: Optional[float] = None
    in_buckets: int = 0
    in_readings: int = 0
    out_mean: Optional[float] = None
    out_buckets: int = 0
    out_readings: int = 0
    neither_buckets: int = 0
    #: in minus out, from the two rounded figures (so the printed numbers add up).
    difference: Optional[float] = None
    #: The difference as a percentage of the outside figure; None when that is zero.
    percent: Optional[float] = None
    spaces_higher: int = 0
    spaces_lower: int = 0
    spaces_same: int = 0
    #: The plain average of the spaces' own differences: no space weighs more for holding more
    #: events or readings.
    mean_space_difference: Optional[float] = None
    #: co-movement
    pairs: int = 0
    pearson: Optional[float] = None
    median_pearson: Optional[float] = None
    spaces_positive: int = 0
    spaces_negative: int = 0
    changes: int = 0
    change_pearson: Optional[float] = None


class RelationResult(BaseModel):
    """The whole result of a RELATE plan (C5)."""

    #: during | after | co_movement
    relation: str
    series: str
    label: str = ""
    unit: str = ""
    #: The second series (co-movement) or the yes/no reading (during a state).
    other: str = ""
    other_label: str = ""
    other_unit: str = ""
    #: The event source (during / after).
    events: str = ""
    events_label: str = ""
    #: True when the "events" are the ON periods of a yes/no reading.
    state: bool = False
    lag_minutes: Optional[float] = None
    lag_default: bool = False
    bucket_minutes: int = 0
    window: Optional[PeriodWindow] = None
    group_by: str = ""
    overall: Optional[RelationFigure] = None
    groups: List[RelationFigure] = Field(default_factory=list)
    spaces: List[RelationSpace] = Field(default_factory=list)
    #: Spaces with no pooled figure, with the reason, named up to MAX_NAMED; how many in all.
    not_compared: List[str] = Field(default_factory=list)
    n_not_compared: int = 0
    #: Events with no duration across the spaces (during: nothing is "during" an instant).
    instants: int = 0
    notes: List[str] = Field(default_factory=list)


def merge_intervals(intervals: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Overlapping or touching intervals merged, in order. An instant stays zero-length."""
    out: List[Tuple[float, float]] = []
    for a, b in sorted((float(a), float(max(a, b))) for a, b in intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _subtract(
    intervals: Sequence[Tuple[float, float]], holes: Sequence[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    """``intervals`` with every part ``holes`` covers removed (both sorted and merged)."""
    out: List[Tuple[float, float]] = []
    for a, b in intervals:
        cur = a
        for s, e in holes:
            if e <= cur or s >= b:
                continue
            if s > cur:
                out.append((cur, min(s, b)))
            cur = max(cur, e)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def _overlap(a0: float, a1: float, merged: Sequence[Tuple[float, float]], starts) -> float:
    """Seconds of [a0, a1) covered by ``merged`` (sorted, disjoint), with their starts given."""
    total = 0.0
    j = bisect.bisect_left(starts, a1) - 1
    while j >= 0:
        s, e = merged[j]
        if e <= a0:
            break
        total += min(a1, e) - max(a0, s)
        j -= 1
    return max(0.0, total)


def _classify(
    index: int,
    size: float,
    events: Sequence[Tuple[float, float]],
    event_starts,
    lag_windows: Optional[Sequence[Tuple[float, float]]],
    lag_starts,
) -> str:
    """in / out / neither for one bucket (see the rules above)."""
    a0 = index * size
    a1 = a0 + size
    during = _overlap(a0, a1, events, event_starts)
    if lag_windows is None:  # during
        if during >= size * IN_SHARE:
            return _IN
        return _OUT if during <= 1e-9 else _NEITHER
    if during > 1e-9:
        return _NEITHER  # during an event: neither after one nor the baseline
    after = _overlap(a0, a1, lag_windows, lag_starts)
    if after >= size * IN_SHARE:
        return _IN
    return _OUT if after <= 1e-9 else _NEITHER


def _zero_spread(values: Sequence[float], mean: float) -> bool:
    """True when a series does not vary (allowing for floating-point dust)."""
    scale = max(1.0, max(abs(v) for v in values))
    return all(abs(v - mean) <= 1e-9 * scale for v in values)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson's r over paired values; None with fewer than MIN_PAIRS or a series that is flat."""
    n = len(xs)
    if n < MIN_PAIRS or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    if _zero_spread(xs, mx) or _zero_spread(ys, my):
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def _ranks(values: Sequence[float]) -> List[float]:
    """1-based ranks, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman's rank correlation (Pearson on average ranks); the same refusals as Pearson."""
    if len(xs) < MIN_PAIRS or len(xs) != len(ys):
        return None
    return pearson(_ranks(xs), _ranks(ys))


def _median(values: Sequence[float]) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _side(buckets: Sequence[Bucket]) -> Tuple[int, int, float]:
    """(buckets with readings, readings, their sum)."""
    held = [b for b in buckets if b.n > 0]
    return len(held), sum(b.n for b in held), sum(b.total for b in held)


def _finish_space(space: RelationSpace, in_side, out_side) -> None:
    """Fill a space's two sides and its difference from (buckets, readings, sum) pairs. In place."""
    space.in_buckets, space.in_readings, space.in_total = in_side
    space.out_buckets, space.out_readings, space.out_total = out_side
    if space.in_readings:
        space.in_mean = _r(space.in_total / space.in_readings)
    if space.out_readings:
        space.out_mean = _r(space.out_total / space.out_readings)
    if space.in_mean is not None and space.out_mean is not None:
        space.difference = _r(space.in_mean - space.out_mean)


def _event_space(
    inp: RelationInput, relation: RelationKind, size: float, lag: float
) -> RelationSpace:
    """One space's level during (or after) its events against its level outside them."""
    space = RelationSpace(space_iri=inp.space_iri, label=inp.label, groups=list(inp.groups))
    space.events = len(inp.events)
    space.instants = sum(1 for s, e in inp.events if e <= s)
    if inp.reason:
        space.reason = inp.reason
        return space
    merged = merge_intervals(inp.events)
    starts = [s for s, _ in merged]
    windows = starts_w = None
    if relation == RelationKind.AFTER:
        windows = _subtract(merge_intervals((e, e + lag) for _s, e in merged), merged)
        starts_w = [s for s, _ in windows]
    classes: Dict[int, str] = {}
    for index, bucket in inp.series.items():
        if bucket.n > 0:
            classes[index] = _classify(index, size, merged, starts, windows, starts_w)
    in_side = _side([inp.series[i] for i, c in classes.items() if c == _IN])
    out_side = _side([inp.series[i] for i, c in classes.items() if c == _OUT])
    space.neither_buckets = sum(1 for c in classes.values() if c == _NEITHER)
    _finish_space(space, in_side, out_side)
    # Event by event: did the series read above the space's own level outside the events?
    out_raw = (space.out_total / space.out_readings) if space.out_readings else None
    for s, e in inp.events:
        if relation == RelationKind.DURING:
            if e <= s:
                continue  # an instant has no "during"
            lo, hi = s, e
        else:
            lo, hi = e, e + lag
        first = int(math.floor(lo / size))
        last = int(math.ceil(hi / size)) - 1
        n, total = 0, 0.0
        for index in range(first, last + 1):
            if classes.get(index) != _IN:
                continue
            a0 = index * size
            if a0 + size <= lo or a0 >= hi:
                continue
            n += inp.series[index].n
            total += inp.series[index].total
        if n:
            space.events_read += 1
            if out_raw is not None and total / n > out_raw:
                space.events_above += 1
    if not inp.series:
        space.reason = "no readings in the window"
    elif not space.in_readings:
        space.reason = (
            "no readings during its events"
            if relation == RelationKind.DURING
            else "no readings after its events"
        )
    elif not space.out_readings:
        space.reason = "no readings outside its events"
    return space


def _state_space(inp: RelationInput) -> RelationSpace:
    """One space's level while a yes/no reading is on against while it is off."""
    space = RelationSpace(space_iri=inp.space_iri, label=inp.label, groups=list(inp.groups))
    if inp.reason:
        space.reason = inp.reason
        return space
    classes: Dict[int, str] = {}
    unread = 0
    for index, bucket in inp.series.items():
        if bucket.n <= 0:
            continue
        state = inp.other.get(index)
        if state is None or state.n <= 0:
            unread += 1
            continue
        share_on = state.mean
        if share_on >= IN_SHARE:
            classes[index] = _IN
        elif share_on <= 1e-9:
            classes[index] = _OUT
        else:
            classes[index] = _NEITHER
    in_side = _side([inp.series[i] for i, c in classes.items() if c == _IN])
    out_side = _side([inp.series[i] for i, c in classes.items() if c == _OUT])
    space.neither_buckets = sum(1 for c in classes.values() if c == _NEITHER) + unread
    _finish_space(space, in_side, out_side)
    # An "event" of a state is an episode: a run of consecutive buckets in which it was on.
    on = sorted(i for i, c in classes.items() if c == _IN)
    runs: List[List[int]] = []
    for index in on:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    space.events = len(runs)
    out_raw = (space.out_total / space.out_readings) if space.out_readings else None
    for run in runs:
        n = sum(inp.series[i].n for i in run)
        total = sum(inp.series[i].total for i in run)
        if n:
            space.events_read += 1
            if out_raw is not None and total / n > out_raw:
                space.events_above += 1
    if not inp.series:
        space.reason = "no readings in the window"
    elif not inp.other:
        space.reason = "no readings of the state in the window"
    elif not space.in_readings:
        space.reason = "the state was never on for half a period"
    elif not space.out_readings:
        space.reason = "the state was never off for a whole period"
    return space


def _series_space(inp: RelationInput) -> Tuple[RelationSpace, List[Tuple[float, float]], List]:
    """One space's co-movement: aligned buckets, the correlations, and its centred pairs."""
    space = RelationSpace(space_iri=inp.space_iri, label=inp.label, groups=list(inp.groups))
    if inp.reason:
        space.reason = inp.reason
        return space, [], []
    aligned = sorted(
        i
        for i, b in inp.series.items()
        if b.n > 0 and inp.other.get(i) is not None and inp.other[i].n > 0
    )
    ys = [inp.series[i].mean for i in aligned]
    xs = [inp.other[i].mean for i in aligned]
    space.pairs = len(aligned)
    r = pearson(xs, ys)
    space.pearson = _r(r) if r is not None else None
    rho = spearman(xs, ys)
    space.spearman = _r(rho) if rho is not None else None
    dx: List[float] = []
    dy: List[float] = []
    position = {i: k for k, i in enumerate(aligned)}
    for i in aligned:
        k = position.get(i + 1)
        if k is not None:
            dx.append(xs[k] - xs[position[i]])
            dy.append(ys[k] - ys[position[i]])
    space.changes = len(dx)
    rc = pearson(dx, dy)
    space.change_pearson = _r(rc) if rc is not None else None
    if not aligned:
        space.reason = "no period with both readings"
    elif space.pairs < MIN_PAIRS:
        space.reason = f"only {space.pairs} period(s) with both readings"
    elif space.pearson is None:
        space.reason = "one of the two readings did not change"
    centred: List[Tuple[float, float]] = []
    if space.pearson is not None:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        centred = [(x - mx, y - my) for x, y in zip(xs, ys)]
    return space, centred, list(zip(dx, dy)) if space.pearson is not None else []


def _level_figure(key: str, label: str, members: Sequence[RelationSpace]) -> RelationFigure:
    """Pool the spaces with both sides, reading by reading, and count their own directions."""
    both = [s for s in members if s.in_readings and s.out_readings]
    figure = RelationFigure(key=key, label=label, spaces=len(both))
    figure.events = sum(s.events for s in both)
    figure.events_read = sum(s.events_read for s in both)
    figure.events_above = sum(s.events_above for s in both)
    figure.neither_buckets = sum(s.neither_buckets for s in both)
    if not both:
        return figure
    figure.in_buckets = sum(s.in_buckets for s in both)
    figure.in_readings = sum(s.in_readings for s in both)
    figure.out_buckets = sum(s.out_buckets for s in both)
    figure.out_readings = sum(s.out_readings for s in both)
    figure.in_mean = _r(sum(s.in_total for s in both) / figure.in_readings)
    figure.out_mean = _r(sum(s.out_total for s in both) / figure.out_readings)
    figure.difference = _r(figure.in_mean - figure.out_mean)
    if figure.out_mean:
        figure.percent = _r(figure.difference / abs(figure.out_mean) * 100.0)
    diffs = [s.difference for s in both if s.difference is not None]
    figure.spaces_higher = sum(1 for d in diffs if d > 0)
    figure.spaces_lower = sum(1 for d in diffs if d < 0)
    figure.spaces_same = sum(1 for d in diffs if d == 0)
    figure.mean_space_difference = _r(sum(diffs) / len(diffs)) if diffs else None
    return figure


def _series_figure(
    key: str,
    label: str,
    members: Sequence[RelationSpace],
    centred: Dict[str, List[Tuple[float, float]]],
    changes: Dict[str, List],
) -> RelationFigure:
    """Pool the spaces with a correlation: within-space r over their centred pairs."""
    held = [s for s in members if s.pearson is not None]
    figure = RelationFigure(key=key, label=label, spaces=len(held))
    if not held:
        return figure
    pairs = [p for s in held for p in centred.get(s.space_iri, [])]
    figure.pairs = len(pairs)
    r = pearson([x for x, _ in pairs], [y for _, y in pairs])
    figure.pearson = _r(r) if r is not None else None
    figure.median_pearson = _r(_median([float(s.pearson) for s in held]))
    figure.spaces_positive = sum(1 for s in held if s.pearson > 0)
    figure.spaces_negative = sum(1 for s in held if s.pearson < 0)
    moves = [p for s in held for p in changes.get(s.space_iri, [])]
    figure.changes = len(moves)
    rc = pearson([x for x, _ in moves], [y for _, y in moves])
    figure.change_pearson = _r(rc) if rc is not None else None
    return figure


def relate(
    relation: RelationKind,
    spaces: Sequence[RelationInput],
    *,
    bucket_seconds: int,
    series: str,
    label: str,
    unit: str = "",
    lag_seconds: float = 0.0,
    state: bool = False,
    other: str = "",
    other_label: str = "",
    other_unit: str = "",
    events: str = "",
    events_label: str = "",
    window: Optional["PeriodWindow"] = None,
    group_by: str = "",
    group_labels: Optional[Dict[str, str]] = None,
    lag_default: bool = False,
    notes: Iterable[str] = (),
) -> RelationResult:
    """Relate one series to events, to a yes/no reading's ON periods, or to a second series.

    Deterministic and offline: ``spaces`` carry each space's bucketed series (and the second
    series or the state) and its events as seconds from the window's start; the result holds every
    space's figures, the pooled figure overall and per group, and the spaces with no figure, named.
    """
    size = float(bucket_seconds)
    labels = dict(group_labels or {})
    per_space: List[RelationSpace] = []
    centred: Dict[str, List[Tuple[float, float]]] = {}
    moves: Dict[str, List] = {}
    for inp in spaces:
        if relation == RelationKind.CO_MOVEMENT:
            space, pairs, change_pairs = _series_space(inp)
            centred[inp.space_iri] = pairs
            moves[inp.space_iri] = change_pairs
        elif state:
            space = _state_space(inp)
        else:
            space = _event_space(inp, relation, size, float(lag_seconds))
        per_space.append(space)

    def figure(key: str, name: str, members: Sequence[RelationSpace]) -> RelationFigure:
        if relation == RelationKind.CO_MOVEMENT:
            return _series_figure(key, name, members, centred, moves)
        return _level_figure(key, name, members)

    result = RelationResult(
        relation=relation.value,
        series=series,
        label=label,
        unit=unit,
        other=other,
        other_label=other_label,
        other_unit=other_unit,
        events=events,
        events_label=events_label,
        state=state,
        lag_minutes=(
            _r(lag_seconds / 60.0)
            if relation == RelationKind.AFTER and lag_seconds is not None
            else None
        ),
        lag_default=lag_default,
        bucket_minutes=int(round(size / 60.0)),
        window=window,
        group_by=group_by,
        spaces=sorted(per_space, key=lambda s: (s.label.lower(), s.space_iri)),
        instants=sum(s.instants for s in per_space),
        notes=[n for n in notes if n],
    )
    result.overall = figure("all", "all spaces", per_space)
    if group_by:
        by_group: Dict[str, List[RelationSpace]] = {}
        for s in per_space:
            for key in s.groups:
                by_group.setdefault(key, []).append(s)
        result.groups = [
            figure(key, labels.get(key) or key, members)
            for key, members in sorted(
                by_group.items(), key=lambda kv: group_sort_key(kv[0], labels.get(kv[0], ""))
            )
        ]
    apart = [
        f"{s.label} ({s.reason})" if s.reason else s.label for s in per_space if not s.compared
    ]
    result.not_compared = _named(apart)
    result.n_not_compared = len(apart)
    return result


# ── evidence for the claim binder ────────────────────────────────────────────────────────


def computed_figures(result: Any) -> Dict[str, float]:
    """{field: number} for ``evidence.computed.record``: every figure an operation produced.

    Field names come from the DATA (group keys, statistic names), never from the answer's prose,
    so the binder can match a figure in the answer to the computation that made it.
    """
    out: Dict[str, float] = {}

    def put(name: str, value: Optional[float]) -> None:
        if value is not None:
            out[name] = float(value)

    if isinstance(result, AggregateResult):
        put("spaces", result.n_spaces)
        put("groups", len(result.groups))
        for g in result.groups:
            stem = f"{g.key} {result.statistic}"
            put(stem, g.value)
            put(f"{g.key} n", g.n)
            put(f"{g.key} mean", g.mean)
            put(f"{g.key} stdev", g.stdev)
            put(f"{g.key} low", g.low)
            put(f"{g.key} high", g.high)
            put(f"{g.key} spread", g.spread)
            put(f"{g.key} total", g.total)
        d = result.dispersion
        if d is not None:
            for name in (
                "groups_n",
                "groups_stdev",
                "groups_low",
                "groups_high",
                "spaces_n",
                "spaces_stdev",
                "spaces_low",
                "spaces_high",
            ):
                put(f"dispersion {name}", getattr(d, name))
    elif isinstance(result, CompareResult):
        from orchestrator.services.deliberation.coverage_audit import _local

        put("comparable", result.n_comparable)
        put("exceeding", result.n_exceeding)
        put("not comparable", len(result.not_comparable))
        for row in result.rows:
            space = _local(row.space_iri)
            put(f"{space} a", row.a)
            put(f"{space} b", row.b)
            put(f"{space} ratio", row.ratio)
            put(f"{space} percent", row.percent)
            put(f"{space} difference", row.difference)
        t = result.total
        if t is not None:
            for name in ("n", "a", "b", "ratio", "percent", "difference", "a_only_n"):
                put(f"total {name}", getattr(t, name))
            put("total a_only_sum", t.a_only_sum)
            put("total b_only_n", t.b_only_n)
            put("total b_only_sum", t.b_only_sum)
    elif isinstance(result, PeriodResult):
        put("not compared", result.n_not_compared)
        for figure in ([result.overall] if result.overall else []) + list(result.groups):
            for name in ("n", "a", "b", "change", "percent", "readings_a", "readings_b"):
                put(f"{figure.key} {name}", getattr(figure, name))
    elif isinstance(result, RelationResult):
        put("not compared", result.n_not_compared)
        put("lag minutes", result.lag_minutes)
        put("bucket minutes", result.bucket_minutes)
        for figure in ([result.overall] if result.overall else []) + list(result.groups):
            for name in _RELATION_FIGURE_FIELDS:
                put(f"{figure.key} {name}", getattr(figure, name))
        from orchestrator.services.deliberation.coverage_audit import _local

        for space in result.spaces:
            stem = _local(space.space_iri)
            for name in _RELATION_SPACE_FIELDS:
                put(f"{stem} {name}", getattr(space, name))
    return out


#: Every figure a relation states, pooled and per space (the claim binder's fields).
_RELATION_FIGURE_FIELDS = (
    "spaces",
    "events",
    "events_read",
    "events_above",
    "in_mean",
    "in_buckets",
    "in_readings",
    "out_mean",
    "out_buckets",
    "out_readings",
    "neither_buckets",
    "difference",
    "percent",
    "spaces_higher",
    "spaces_lower",
    "spaces_same",
    "mean_space_difference",
    "pairs",
    "pearson",
    "median_pearson",
    "spaces_positive",
    "spaces_negative",
    "changes",
    "change_pearson",
)
_RELATION_SPACE_FIELDS = (
    "events",
    "events_read",
    "events_above",
    "instants",
    "in_mean",
    "in_buckets",
    "in_readings",
    "out_mean",
    "out_buckets",
    "out_readings",
    "neither_buckets",
    "difference",
    "pairs",
    "pearson",
    "spearman",
    "changes",
    "change_pearson",
)


__all__ = [
    "AggregateResult",
    "Bucket",
    "CompareFit",
    "CompareResult",
    "ComparisonRow",
    "ComparisonTotal",
    "DECIMALS",
    "Dispersion",
    "GroupResult",
    "IN_SHARE",
    "MIN_PAIRS",
    "PeriodFigure",
    "PeriodResult",
    "PeriodSpace",
    "PeriodWindow",
    "RelationFigure",
    "RelationInput",
    "RelationResult",
    "RelationSpace",
    "SpaceValue",
    "additive",
    "aggregate",
    "compare",
    "compare_fit",
    "compare_periods",
    "computed_figures",
    "facet_unit",
    "fmt",
    "group_sort_key",
    "is_count",
    "merge_intervals",
    "pearson",
    "relate",
    "rounded",
    "spearman",
    "with_unit",
]
