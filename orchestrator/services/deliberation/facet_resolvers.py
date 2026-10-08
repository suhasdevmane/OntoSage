# -*- coding: utf-8 -*-
"""facet_resolvers.py — read the facet values a compiled plan asks about (v2, P4).

WHAT THIS DOES
--------------
A v2 plan carries ``FacetCriterion``s: "at least 12 seats", "a projector that is ready", "free
for two hours". For every candidate space this module reads the value each criterion is about
and decides met / unmet / unknown, with the record id or property it came from. The executor
then excludes, flags and scores on those checks; the dossier shows them beside the readings.

THE INVARIANTS, each enforced here rather than hoped for
--------------------------------------------------------
* SPARQL IS BUILT IN CODE from the facet's own metadata (class, predicate, join). No model
  writes a query, and no user string is ever interpolated: candidate spaces, classes and
  predicates are IRIs the graph itself returned, and the comparison with the user's value
  happens in Python after the read.
* BATCHED. One query per record class (all its predicates, all candidates in one VALUES
  block), one for the spaces' own properties, one for floors, one capacity read, one booking
  check -- never a query per candidate. Every query carries a LIMIT.
* CAPACITY ONLY THROUGH ITS AUTHORITY ORDER. ``design_occupancy`` settles which figure answers
  (the TTL figure, else the drawing, never an average); a disagreement is UNKNOWN, never picked.
* A RECORD GROUP IS ONE RECORD. "A projector that is ready" is met by a component that is a
  projector AND ready -- never by a room whose projector failed and whose display is ready.
* UNKNOWN IS NOT MET. A value that is not recorded is reported as not recorded; the executor
  ranks such a space below the verified ones and the answer says what could not be checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

from orchestrator.services.deliberation.coverage_audit import SparqlExec, _bindings, _local, _val
from orchestrator.services.deliberation.cqir import (
    SCORING_OPERATORS,
    FacetCriterion,
    FacetOperator,
    Hardness,
)
from orchestrator.services.deliberation.facets import Facet, FacetCatalogue, split_camel
from orchestrator.services.record_entity_links import LINK_PREDICATES, ROUTE_FROM, ROUTE_TO
from shared.utils import describe_exception, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from orchestrator.services.deliberation.candidates import Candidate
    from orchestrator.services.deliberation.capability_schema import BuildingCapabilitySchema

logger = get_logger(__name__)

MET = "met"
UNMET = "unmet"
UNKNOWN = "unknown"

_ONTOSAGE = "http://ontosage.org/capabilities#"
_RECORD_ID = _ONTOSAGE + "recordId"
_BRICK = "https://brickschema.org/schema/Brick#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

#: Rows any one resolver query may return. Reaching it is logged: a check computed over a cut
#: read could call a recorded value "not recorded".
MAX_ROWS = 20000
#: Values one inspection read returns.
VALUE_SET_LIMIT = 50

_CAPACITY_FACET = "ttl:capacity"
_FLOOR_FACET = "spatial:floor"
_FREE_WINDOW_FACET = "event:free_window"

#: An IRI the graph returned, safe to write between angle brackets. Anything else is refused.
_IRI_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+")
_TRUE = frozenset({"true", "1", "yes"})
_FALSE = frozenset({"false", "0", "no"})


@dataclass
class FacetCheck:
    """One criterion, evaluated for one candidate space."""

    space_iri: str
    criterion: FacetCriterion
    #: The criterion's position in the plan: two criteria on one facet stay distinct.
    index: int
    status: str = UNKNOWN  # met | unmet | unknown
    #: The raw values read for the criterion's facet (from the witness record).
    values: List[str] = field(default_factory=list)
    #: What the reader is shown: "seat count: 16", "record status: ready", "not recorded".
    display: str = ""
    #: Where the value came from: record ids ("WorkspaceProfile WS-07") or a property.
    provenance: List[str] = field(default_factory=list)
    hardness: str = Hardness.SOFT.value
    #: The number a ranking criterion scores on, when the facet is numeric.
    number: Optional[float] = None
    #: The facet's reader label.
    label: str = ""


# ── words ────────────────────────────────────────────────────────────────────────────────


def facet_reader_label(facet: Optional[Facet]) -> str:
    """A facet in the reader's words: its label, with the register it comes from."""
    if facet is None:
        return ""
    label = (facet.label or split_camel(_local(facet.predicate or facet.key))).strip()
    if facet.record_class and facet.source_kind in ("record", "spatial"):
        register = split_camel(facet.record_class)
        if register and register not in label.lower():
            return f"{label} ({register})"
    return label


def _excerpt(text: str, limit: int = 80) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _format_value(facet: Facet, raw: str) -> str:
    if facet.value_type in ("number", "integer"):
        try:
            text = f"{float(raw):g}"
        except ValueError:
            return _excerpt(raw)
        return f"{text} {facet.unit}" if facet.unit else text
    if facet.value_type == "boolean":
        low = str(raw).strip().lower()
        return "yes" if low in _TRUE else ("no" if low in _FALSE else _excerpt(raw))
    return _excerpt(raw)


def _display(facet: Facet, values: Sequence[str]) -> str:
    label = facet.label or split_camel(_local(facet.predicate or facet.key))
    if not values:
        return f"{label}: not recorded"
    shown = ", ".join(_format_value(facet, v) for v in sorted(values)[:3])
    more = f" (+{len(values) - 3} more)" if len(values) > 3 else ""
    return f"{label}: {shown}{more}"


# ── comparisons, in code ─────────────────────────────────────────────────────────────────


def _numbers(values: Sequence[str]) -> List[float]:
    out = []
    for v in values:
        try:
            out.append(float(str(v).strip()))
        except ValueError:
            continue
    return out


def _floor_matches(value: str, wanted: Sequence[str]) -> bool:
    from orchestrator.services.deliberation.capability_schema import _floor_digits

    low = " ".join(str(value).lower().split())
    have = _floor_digits(low.replace(" ", ""))
    for w in wanted:
        w_low = " ".join(str(w).lower().split())
        if w_low == low:
            return True
        digits = _floor_digits(w_low.replace(" ", ""))
        if digits is not None and digits == have:
            return True
    return False


def evaluate(criterion: FacetCriterion, facet: Facet, values: Sequence[str]) -> str:
    """met / unmet / unknown for ONE value list. Unknown when nothing is recorded."""
    values = [v for v in values if str(v).strip()]
    if not values:
        return UNKNOWN
    op = criterion.operator
    if facet.key == _FLOOR_FACET:
        wanted = criterion.value if isinstance(criterion.value, list) else [criterion.value]
        return MET if any(_floor_matches(v, [str(w) for w in wanted]) for v in values) else UNMET
    if facet.value_type in ("number", "integer"):
        numbers = _numbers(values)
        if not numbers:
            return UNKNOWN
        if op in SCORING_OPERATORS:
            return MET  # a ranking criterion only needs a value; the scorer places it
        try:
            target = float(criterion.value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return UNKNOWN
        checks = {
            FacetOperator.BELOW: lambda n: n < target,
            FacetOperator.ABOVE: lambda n: n > target,
            FacetOperator.AT_LEAST: lambda n: n >= target,
            FacetOperator.AT_MOST: lambda n: n <= target,
        }
        test = checks.get(op)
        if test is None:
            return UNKNOWN
        return MET if any(test(n) for n in numbers) else UNMET
    if facet.value_type == "boolean":
        lows = {str(v).strip().lower() for v in values}
        if op == FacetOperator.IS_TRUE:
            return MET if lows & _TRUE else (UNMET if lows & _FALSE else UNKNOWN)
        if op == FacetOperator.IS_FALSE:
            return MET if lows & _FALSE else (UNMET if lows & _TRUE else UNKNOWN)
        return UNKNOWN
    if facet.value_type == "enum":
        wanted = criterion.value if isinstance(criterion.value, list) else [criterion.value]
        wanted_norm = {" ".join(str(w).lower().split()) for w in wanted if w is not None}
        have = {" ".join(str(v).lower().split()) for v in values}
        return MET if have & wanted_norm else UNMET
    if facet.value_type == "text" and op == FacetOperator.CONTAINS:
        needle = " ".join(str(criterion.value or "").lower().split())
        if not needle:
            return UNKNOWN
        return MET if any(needle in " ".join(str(v).lower().split()) for v in values) else UNMET
    return UNKNOWN


def _best_number(criterion: FacetCriterion, numbers: Sequence[float]) -> Optional[float]:
    if not numbers:
        return None
    if criterion.operator == FacetOperator.MINIMIZE:
        return min(numbers)
    if criterion.operator == FacetOperator.NEAR:
        try:
            target = float(criterion.value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return min(numbers, key=lambda n: (abs(n - target), n))
    if criterion.operator in (FacetOperator.AT_MOST, FacetOperator.BELOW):
        return min(numbers)
    return max(numbers)


# ── SPARQL, built in code ────────────────────────────────────────────────────────────────


def _iri(text: str) -> Optional[str]:
    candidate = str(text or "").strip()
    return f"<{candidate}>" if _IRI_RE.fullmatch(candidate) else None


def _values_block(iris: Sequence[str]) -> str:
    return " ".join(i for i in (_iri(x) for x in sorted(set(iris))) if i)


def record_query(
    class_iri: str,
    join_predicate: str,
    predicates: Sequence[str],
    space_iris: Sequence[str],
    limit: int = MAX_ROWS,
) -> str:
    """Every record of one class linked to the candidate spaces, with the asked predicates.

    One query for all candidates and all predicates of the class: ``?r a <class> ;
    <join> ?space``, ``OPTIONAL recordId``, ``OPTIONAL { ?r <p_i> ?v_i }`` per predicate,
    candidates in ONE VALUES block, and a LIMIT.
    """
    cls, join = _iri(class_iri), _iri(join_predicate)
    preds = [_iri(p) for p in predicates]
    if not cls or not join or not all(preds):
        raise ValueError("a facet resolver was handed something that is not an IRI")
    optional = "".join(f"  OPTIONAL {{ ?r {p} ?v{i} }}\n" for i, p in enumerate(preds))
    selected = " ".join(f"?v{i}" for i in range(len(preds)))
    origin = ""
    if join_predicate == LINK_PREDICATES[ROUTE_TO]:
        # A route fact reaching a space is only half a fact without where the route starts.
        # The plan has no origin to choose by, so the origin is READ and SHOWN, never assumed.
        origin = (
            f"  OPTIONAL {{ ?r <{LINK_PREDICATES[ROUTE_FROM]}> ?origin .\n"
            f"             OPTIONAL {{ ?origin <{_RDFS}label> ?originLabel }} }}\n"
        )
        selected += " ?origin ?originLabel"
    return (
        f"SELECT ?space ?r ?rid {selected} WHERE {{\n"
        f"  VALUES ?space {{ {_values_block(space_iris)} }}\n"
        f"  ?r a {cls} ; {join} ?space .\n"
        f"  OPTIONAL {{ ?r <{_RECORD_ID}> ?rid }}\n"
        f"{optional}"
        f"{origin}"
        f"}} LIMIT {int(limit)}"
    )


def space_property_query(
    predicates: Sequence[str], space_iris: Sequence[str], limit: int = MAX_ROWS
) -> str:
    """The candidate spaces' own values for some properties, in one query."""
    preds = [_iri(p) for p in predicates]
    if not all(preds):
        raise ValueError("a facet resolver was handed something that is not an IRI")
    optional = "".join(
        f"  OPTIONAL {{ ?space {p} ?v{i} . FILTER(isLiteral(?v{i})) }}\n"
        for i, p in enumerate(preds)
    )
    selected = " ".join(f"?v{i}" for i in range(len(preds)))
    return (
        f"SELECT ?space {selected} WHERE {{\n"
        f"  VALUES ?space {{ {_values_block(space_iris)} }}\n"
        f"{optional}"
        f"}} LIMIT {int(limit)}"
    )


def floor_query(space_iris: Sequence[str], limit: int = MAX_ROWS) -> str:
    """The floor each candidate space is part of, with the floor's label."""
    return (
        f"SELECT ?space ?floor ?label WHERE {{\n"
        f"  VALUES ?space {{ {_values_block(space_iris)} }}\n"
        f"  ?space <{_BRICK}isPartOf> ?floor .\n"
        f"  ?floor a <{_BRICK}Floor> .\n"
        f"  OPTIONAL {{ ?floor <{_RDFS}label> ?label }}\n"
        f"}} LIMIT {int(limit)}"
    )


def value_set_query(facet: Facet, limit: int = VALUE_SET_LIMIT) -> Optional[str]:
    """The distinct values a facet holds, read-only, for the compiler's inspection step."""
    pred = _iri(facet.predicate or "")
    if not pred:
        return None
    if facet.record_class and facet.source_kind in ("record", "spatial"):
        cls = _iri(_ONTOSAGE + facet.record_class)
        if not cls:
            return None
        pattern = f"?r a {cls} ; {pred} ?v ."
    else:
        pattern = f"?s {pred} ?v ."
    return f"SELECT DISTINCT ?v WHERE {{\n  {pattern}\n  FILTER(isLiteral(?v))\n}} LIMIT {limit}"


async def facet_value_set(
    facet: Facet, sparql_exec: SparqlExec, limit: int = VALUE_SET_LIMIT
) -> List[str]:
    """``describe_facet``: the values a facet actually holds (bounded, deterministic)."""
    query = value_set_query(facet, limit)
    if query is None:
        return list(facet.examples)
    payload = await sparql_exec(query)
    return sorted({_val(b, "v") for b in _bindings(payload) if _val(b, "v")}, key=str.lower)


async def _select(sparql_exec: SparqlExec, query: str, what: str) -> List[Dict[str, Any]]:
    rows = _bindings(await sparql_exec(query))
    if len(rows) >= MAX_ROWS:
        logger.warning(
            f"[facet_resolvers] {what}: the read reached its {MAX_ROWS}-row limit; values beyond "
            "it would show as not recorded"
        )
    return rows


# ── records ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _Record:
    iri: str
    rid: str = ""
    values: Dict[str, Set[str]] = field(default_factory=dict)
    #: For a route record: where the route starts (its label, else its local name).
    origin: str = ""

    @property
    def name(self) -> str:
        return self.rid or _local(self.iri)

    def source(self, register: str) -> str:
        base = f"{register} {self.name}"
        return f"{base}, from {self.origin}" if self.origin else base


@dataclass
class _Item:
    index: int
    criterion: FacetCriterion
    facet: Facet


def _record_status(record: _Record, items: Sequence[_Item]) -> str:
    """Whether ONE record satisfies every criterion in ``items`` (met / unmet / unknown)."""
    statuses = [
        evaluate(i.criterion, i.facet, sorted(record.values.get(i.facet.predicate or "", set())))
        for i in items
    ]
    if any(s == UNMET for s in statuses):
        return UNMET
    if any(s == UNKNOWN for s in statuses):
        return UNKNOWN
    return MET


def _pool_status(records: Sequence[_Record], items: Sequence[_Item]) -> Tuple[str, List[_Record]]:
    """(met / unmet / unknown, the records that meet ``items``) over a pool of records."""
    if not items:
        return MET, list(records)
    meeting = [r for r in records if _record_status(r, items) == MET]
    if meeting:
        return MET, meeting
    if any(_record_status(r, items) == UNKNOWN for r in records):
        return UNKNOWN, []
    return UNMET, []


def _closest(records: Sequence[_Record], items: Sequence[_Item]) -> List[_Record]:
    """The record(s) nearest to meeting ``items``: most criteria met, then by name."""
    if not records:
        return []

    def met_count(r: _Record) -> int:
        return sum(
            1
            for i in items
            if evaluate(i.criterion, i.facet, sorted(r.values.get(i.facet.predicate or "", set())))
            == MET
        )

    ranked = sorted(records, key=lambda r: (-met_count(r), r.name))
    return ranked[:2]


def _evaluate_group(
    space: str, items: Sequence[_Item], records: Sequence[_Record], register: str
) -> List[FacetCheck]:
    """One record group for one space: a space meets the group when ONE record meets it.

    Hard criteria decide whether a qualifying record exists; soft criteria are judged on the
    records that pass the hard ones, all together on one record; ranking criteria (minimize /
    maximize / near) take the best value among the records that pass the rest.
    """
    records = sorted(records, key=lambda r: r.name)
    hard = [
        i
        for i in items
        if i.criterion.hardness == Hardness.HARD and i.criterion.operator not in SCORING_OPERATORS
    ]
    soft = [
        i
        for i in items
        if i.criterion.hardness != Hardness.HARD and i.criterion.operator not in SCORING_OPERATORS
    ]
    scoring = [i for i in items if i.criterion.operator in SCORING_OPERATORS]
    checks: List[FacetCheck] = []

    def check(item: _Item, status: str, witnesses: Sequence[_Record], number=None) -> FacetCheck:
        values: List[str] = []
        for w in witnesses[:1]:
            values = sorted(w.values.get(item.facet.predicate or "", set()))
        return FacetCheck(
            space_iri=space,
            criterion=item.criterion,
            index=item.index,
            status=status,
            values=values,
            display=_display(item.facet, values),
            provenance=[w.source(str(item.facet.record_class)) for w in witnesses[:2]],
            hardness=item.criterion.hardness.value,
            number=number,
            label=facet_reader_label(item.facet),
        )

    if not records:
        for item in items:
            c = check(item, UNKNOWN, [])
            c.display = f"no {register} record for this space"
            checks.append(c)
        return checks

    def per_record(witnesses: Sequence[_Record], group: Sequence[_Item]) -> str:
        """A failed group described RECORD BY RECORD: each closest record with all its values."""
        return "; ".join(
            f"{w.name} — "
            + ", ".join(
                _display(i.facet, sorted(w.values.get(i.facet.predicate or "", set())))
                for i in group
            )
            for w in witnesses[:2]
        )

    hard_status, passing = _pool_status(records, hard)
    soft_pool = passing if hard else records
    soft_status, soft_passing = _pool_status(soft_pool, soft)
    if soft and not soft_pool:
        soft_status = UNKNOWN if hard_status == UNKNOWN else UNMET

    for item in hard:
        witnesses = (
            ([r for r in passing if r in soft_passing] or passing)
            if hard_status == MET
            else _closest(records, hard)
        )
        c = check(item, hard_status, witnesses)
        if hard_status != MET and len(hard) > 1:
            c.display = per_record(witnesses, hard)
        checks.append(c)
    for item in soft:
        witnesses = soft_passing if soft_status == MET else _closest(soft_pool or records, soft)
        c = check(item, soft_status, witnesses)
        if soft_status != MET and len(soft) > 1 and witnesses:
            c.display = per_record(witnesses, soft)
        checks.append(c)
    pool = soft_passing or passing or records
    for item in scoring:
        best: Optional[float] = None
        witness: Optional[_Record] = None
        for record in pool:
            number = _best_number(
                item.criterion,
                _numbers(sorted(record.values.get(item.facet.predicate or "", set()))),
            )
            if number is None:
                continue
            if best is None or _best_number(item.criterion, [best, number]) == number != best:
                best, witness = number, record
        checks.append(
            check(item, MET if best is not None else UNKNOWN, [witness] if witness else [], best)
        )
    return checks


def _records_by_space(
    rows: Sequence[Dict[str, Any]], predicates: Sequence[str]
) -> Dict[str, Dict[str, _Record]]:
    """{space: {record IRI: record}} from the rows of one ``record_query``."""
    by_space: Dict[str, Dict[str, _Record]] = {}
    for row in rows:
        space, rec_iri = _val(row, "space"), _val(row, "r")
        if not space or not rec_iri:
            continue
        record = by_space.setdefault(space, {}).setdefault(rec_iri, _Record(rec_iri))
        rid = _val(row, "rid")
        if rid and (not record.rid or rid < record.rid):
            record.rid = rid
        origin = _val(row, "originLabel") or _local(_val(row, "origin"))
        if origin and (not record.origin or origin < record.origin):
            record.origin = origin
        for idx, predicate in enumerate(predicates):
            value = _val(row, f"v{idx}")
            if value:
                record.values.setdefault(predicate, set()).add(value)
    return by_space


async def _resolve_records(
    items: Sequence[_Item], space_iris: Sequence[str], sparql_exec: SparqlExec
) -> List[FacetCheck]:
    """Every criterion on one record class (one join), for every candidate, in ONE query."""
    first = items[0].facet
    predicates = sorted({i.facet.predicate for i in items if i.facet.predicate})
    query = record_query(
        _ONTOSAGE + str(first.record_class), str(first.join_predicate), predicates, space_iris
    )
    rows = await _select(sparql_exec, query, f"{first.record_class} records")
    by_space = _records_by_space(rows, predicates)

    groups: Dict[str, List[_Item]] = {}
    for item in items:
        groups.setdefault(item.criterion.record_group or f"#{item.index}", []).append(item)
    register = split_camel(str(first.record_class))
    checks: List[FacetCheck] = []
    for space in space_iris:
        records = list(by_space.get(space, {}).values())
        for group_items in groups.values():
            checks.extend(_evaluate_group(space, group_items, records, register))
    return checks


# ── the spaces' own properties, capacity, floors, availability ───────────────────────────


async def _resolve_space_properties(
    items: Sequence[_Item], space_iris: Sequence[str], sparql_exec: SparqlExec
) -> List[FacetCheck]:
    predicates = sorted({i.facet.predicate for i in items if i.facet.predicate})
    rows = await _select(
        sparql_exec, space_property_query(predicates, space_iris), "space properties"
    )
    values: Dict[str, Dict[str, Set[str]]] = {}
    for row in rows:
        space = _val(row, "space")
        for idx, predicate in enumerate(predicates):
            value = _val(row, f"v{idx}")
            if space and value:
                values.setdefault(space, {}).setdefault(predicate, set()).add(value)
    checks = []
    for space in space_iris:
        for item in items:
            found = sorted(values.get(space, {}).get(item.facet.predicate or "", set()))
            status = evaluate(item.criterion, item.facet, found)
            number = None
            if item.criterion.operator in SCORING_OPERATORS:
                number = _best_number(item.criterion, _numbers(found))
            checks.append(
                FacetCheck(
                    space_iri=space,
                    criterion=item.criterion,
                    index=item.index,
                    status=status,
                    values=found,
                    display=_display(item.facet, found),
                    provenance=[f"{_local(item.facet.predicate or '')} (building model)"],
                    hardness=item.criterion.hardness.value,
                    number=number,
                    label=facet_reader_label(item.facet),
                )
            )
    return checks


async def _resolve_capacity(
    items: Sequence[_Item], space_iris: Sequence[str], sparql_exec: SparqlExec
) -> List[FacetCheck]:
    """Capacity through ``design_occupancy`` and its authority order -- never a raw read."""
    from orchestrator.services import design_occupancy

    occupancy = await design_occupancy.declared_design_occupancy(sparql_exec)
    checks = []
    for space in space_iris:
        entry = occupancy.get(space)
        for item in items:
            label = facet_reader_label(item.facet)
            if entry is not None and entry.conflicted:
                figures = ", ".join(str(v) for v in entry.values)
                checks.append(
                    FacetCheck(
                        space_iri=space,
                        criterion=item.criterion,
                        index=item.index,
                        status=UNKNOWN,
                        values=[str(v) for v in entry.values],
                        display=f"{item.facet.label}: the building states disagreeing figures "
                        f"({figures})",
                        provenance=["design occupancy (disagreeing sources)"],
                        hardness=item.criterion.hardness.value,
                        label=label,
                    )
                )
                continue
            value = entry.value if entry is not None else None
            found = [str(value)] if value is not None else []
            source = (
                "architect's drawing"
                if entry is not None and entry.source == design_occupancy.CAPACITY_SOURCE_DRAWING
                else "building model"
            )
            number = float(value) if value is not None else None
            checks.append(
                FacetCheck(
                    space_iri=space,
                    criterion=item.criterion,
                    index=item.index,
                    status=evaluate(item.criterion, item.facet, found),
                    values=found,
                    display=_display(item.facet, found),
                    provenance=[f"design occupancy ({source})"] if found else [],
                    hardness=item.criterion.hardness.value,
                    number=number,
                    label=label,
                )
            )
    return checks


async def _resolve_floors(
    items: Sequence[_Item], space_iris: Sequence[str], sparql_exec: SparqlExec
) -> List[FacetCheck]:
    rows = await _select(sparql_exec, floor_query(space_iris), "floors")
    floors: Dict[str, Set[str]] = {}
    for row in rows:
        space = _val(row, "space")
        name = _val(row, "label") or _local(_val(row, "floor"))
        if space and name:
            floors.setdefault(space, set()).add(name)
    checks = []
    for space in space_iris:
        found = sorted(floors.get(space, set()))
        for item in items:
            checks.append(
                FacetCheck(
                    space_iri=space,
                    criterion=item.criterion,
                    index=item.index,
                    status=evaluate(item.criterion, item.facet, found),
                    values=found,
                    display=_display(item.facet, found),
                    provenance=["floor (building model)"] if found else [],
                    hardness=item.criterion.hardness.value,
                    label=facet_reader_label(item.facet),
                )
            )
    return checks


async def _resolve_availability(
    items: Sequence[_Item],
    space_iris: Sequence[str],
    candidates: Optional[Sequence["Candidate"]],
    schema: Optional["BuildingCapabilitySchema"],
    adapter_getter,
) -> List[FacetCheck]:
    """free_for: the executor's own booking check (``plan_executor._event_availability``)."""
    from orchestrator.services.deliberation.cqir import CQIR, DecisionKind, EventCriterion
    from orchestrator.services.deliberation.plan_executor import _event_availability

    by_iri = {c.space_iri: c for c in (candidates or [])}
    checks: List[FacetCheck] = []
    for item in items:
        hours = float(item.criterion.value or 1.0)  # type: ignore[arg-type]
        results: Dict[str, Any] = {}
        reason = ""
        if schema is None or not by_iri:
            reason = "availability can only be checked against the candidate spaces of a plan"
        else:
            probe = CQIR(
                decision=DecisionKind.SELECT_ONE,
                event_criteria=[EventCriterion(kind="free_window", hours=hours)],
            )
            wanted = [by_iri[i] for i in space_iris if i in by_iri]
            results, notes = await _event_availability(probe, schema, wanted, adapter_getter)
            reason = "; ".join(notes)
        for space in space_iris:
            event = results.get(space)
            if event is None or event.free is None:
                status = UNKNOWN
                display = f"free for {hours:g} h: not checked" + (f" ({reason})" if reason else "")
                provenance: List[str] = []
            else:
                status = MET if event.free else UNMET
                display = (
                    f"free for the next {hours:g} h" if event.free else f"{event.detail}"
                ).strip()
                provenance = ["bookings"]
            checks.append(
                FacetCheck(
                    space_iri=space,
                    criterion=item.criterion,
                    index=item.index,
                    status=status,
                    values=[str(event.free)] if event is not None else [],
                    display=display,
                    provenance=provenance,
                    hardness=item.criterion.hardness.value,
                    label=facet_reader_label(item.facet),
                )
            )
    return checks


def _unknown_for_all(items: Sequence[_Item], space_iris: Sequence[str], why: str):
    return [
        FacetCheck(
            space_iri=space,
            criterion=item.criterion,
            index=item.index,
            status=UNKNOWN,
            display=f"{item.facet.label}: {why}",
            hardness=item.criterion.hardness.value,
            label=facet_reader_label(item.facet),
        )
        for space in space_iris
        for item in items
    ]


def _resolve_space_kinds(
    items: Sequence[_Item],
    space_iris: Sequence[str],
    candidates: Optional[Sequence["Candidate"]],
) -> List[FacetCheck]:
    """A space's kind, read from the candidate itself: its label's descriptor and Brick classes.

    No query: the candidates already carry both. A space the plan holds no candidate for is
    reported as not checked, never guessed (space_kinds.py has why this facet exists).
    """
    from orchestrator.services.deliberation.space_kinds import kind_matches, space_kinds

    by_iri = {c.space_iri: c for c in (candidates or [])}
    checks: List[FacetCheck] = []
    for space in space_iris:
        cand = by_iri.get(space)
        kinds = space_kinds(cand.label, cand.kinds) if cand is not None else ()
        for item in items:
            wanted = item.criterion.value
            wanted = wanted if isinstance(wanted, list) else [wanted]
            wanted = [str(w) for w in wanted if str(w or "").strip()]
            if not kinds or not wanted:
                status = UNKNOWN
            else:
                hit = any(kind_matches(w, kinds) for w in wanted)
                if item.criterion.operator in (FacetOperator.EQUALS, FacetOperator.ONE_OF):
                    status = MET if hit else UNMET
                else:
                    status = UNKNOWN
            checks.append(
                FacetCheck(
                    space_iri=space,
                    criterion=item.criterion,
                    index=item.index,
                    status=status,
                    values=list(kinds),
                    display=", ".join(kinds) if kinds else "kind not recorded",
                    provenance=["label and room type (building model)"] if kinds else [],
                    hardness=item.criterion.hardness.value,
                    label=facet_reader_label(item.facet),
                )
            )
    return checks


async def resolve_facets(
    criteria: Sequence[FacetCriterion],
    catalogue: FacetCatalogue,
    candidate_iris: Sequence[str],
    sparql_exec: SparqlExec,
    *,
    candidates: Optional[Sequence["Candidate"]] = None,
    schema: Optional["BuildingCapabilitySchema"] = None,
    adapter_getter=None,
) -> List[FacetCheck]:
    """Evaluate every facet criterion for every candidate space. Deterministic, batched.

    Returns one ``FacetCheck`` per (criterion, candidate). ``candidates`` and ``schema`` are
    needed only by an availability criterion (the booking check derives each space's booking
    subject from its label); without them availability is reported as not checked.
    """
    space_iris = sorted({str(i) for i in candidate_iris if _iri(str(i))})
    if not criteria or not space_iris:
        return []
    record_batches: Dict[Tuple[str, str], List[_Item]] = {}
    own: List[_Item] = []
    capacity: List[_Item] = []
    floors: List[_Item] = []
    kinds: List[_Item] = []
    availability: List[_Item] = []
    unresolvable: List[Tuple[_Item, str]] = []
    from orchestrator.services.deliberation.space_kinds import SPACE_KIND_FACET

    for index, criterion in enumerate(criteria):
        facet = catalogue.get(criterion.facet)
        if facet is None:
            continue
        item = _Item(index, criterion, facet)
        if facet.key == _CAPACITY_FACET:
            capacity.append(item)
        elif facet.key == _FLOOR_FACET:
            floors.append(item)
        elif facet.key == SPACE_KIND_FACET:
            kinds.append(item)
        elif facet.key == _FREE_WINDOW_FACET and criterion.operator == FacetOperator.FREE_FOR:
            availability.append(item)
        elif facet.source_kind == "sensor":
            unresolvable.append((item, "read through the sensor path, not here"))
        elif facet.record_class and facet.join_predicate and facet.predicate:
            record_batches.setdefault((facet.record_class, facet.join_predicate), []).append(item)
        elif facet.source_kind == "ttl" and facet.predicate and facet.entity_type == "space":
            own.append(item)
        else:
            unresolvable.append((item, "not something a space's records can be checked for"))

    checks: List[FacetCheck] = []
    for (record_class, _join), items in sorted(record_batches.items()):
        try:
            checks += await _resolve_records(items, space_iris, sparql_exec)
        except Exception as exc:
            logger.warning(f"[facet_resolvers] {record_class}: {describe_exception(exc)}")
            checks += _unknown_for_all(items, space_iris, "the records could not be read")
    for name, items, resolver in (
        ("space properties", own, _resolve_space_properties),
        ("capacity", capacity, _resolve_capacity),
        ("floors", floors, _resolve_floors),
    ):
        if not items:
            continue
        try:
            checks += await resolver(items, space_iris, sparql_exec)
        except Exception as exc:
            logger.warning(f"[facet_resolvers] {name}: {describe_exception(exc)}")
            checks += _unknown_for_all(items, space_iris, "could not be read")
    if kinds:
        checks += _resolve_space_kinds(kinds, space_iris, candidates)
    if availability:
        try:
            checks += await _resolve_availability(
                availability, space_iris, candidates, schema, adapter_getter
            )
        except Exception as exc:
            logger.warning(f"[facet_resolvers] availability: {describe_exception(exc)}")
            checks += _unknown_for_all(availability, space_iris, "the bookings could not be read")
    for item, why in unresolvable:
        checks += _unknown_for_all([item], space_iris, why)
    checks.sort(key=lambda c: (c.space_iri, c.index))
    met = sum(1 for c in checks if c.status == MET)
    unknown = sum(1 for c in checks if c.status == UNKNOWN)
    logger.info(
        f"[facet_resolvers] {len(criteria)} criterion(s) x {len(space_iris)} space(s): "
        f"{met} met, {len(checks) - met - unknown} unmet, {unknown} unknown"
    )
    return checks


# ── v2 operations: ONE value per space, for an aggregate (C3) or a comparison (C2) ───────


@dataclass
class FacetValue:
    """A facet's value for ONE space, read for an operation rather than checked against a limit.

    ``reason`` is set when the space has no usable figure: nothing recorded, one record of
    several without it, or records that disagree. An operation never imputes or picks one.
    """

    space_iri: str
    number: Optional[float] = None
    #: A yes/no facet's value.
    flag: Optional[bool] = None
    #: The raw values read, for the evidence table.
    raw: List[str] = field(default_factory=list)
    display: str = ""
    provenance: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def usable(self) -> bool:
        """True when the space has a figure (or, for a text facet, a recorded value)."""
        return not self.reason


def _combine(
    facet: Facet, entries: Sequence[Tuple[str, List[str]]], additive: bool
) -> Tuple[Optional[float], Optional[bool], str, str]:
    """(number, flag, display, reason) for one space from its sources' values.

    ``entries`` holds one (source name, distinct raw values) pair per record -- or a single pair
    for a value the space itself carries. Several records of an amount that ADDS UP are summed
    ("two desk clusters of six seats"); for anything else they must agree, or the space has no
    figure and the disagreement is named.
    """
    label = facet.label or facet.key
    blank = [name for name, values in entries if not values]
    if len(blank) == len(entries):
        return None, None, f"{label}: not recorded", "not recorded"
    if blank:
        return None, None, "", f"{label} not recorded on {blank[0]}"
    doubled = [(name, values) for name, values in entries if len(values) > 1]
    if doubled:
        name, values = doubled[0]
        return None, None, "", f"{name} records {label} twice ({', '.join(values[:3])})"
    raw = [values[0] for _, values in entries]
    if facet.value_type in ("number", "integer"):
        numbers = _numbers(raw)
        if len(numbers) != len(raw):
            return None, None, "", f"{label} is not recorded as a number"
        if additive and len(numbers) > 1:
            total = sum(numbers)
            return total, None, f"{label}: {total:g} over {len(numbers)} records", ""
        if len(set(numbers)) > 1:
            said = ", ".join(f"{name} says {n:g}" for (name, _), n in zip(entries, numbers))
            return None, None, "", f"records disagree: {said}"
        return numbers[0], None, _display(facet, raw[:1]), ""
    if facet.value_type == "boolean":
        lows = {str(v).strip().lower() for v in raw}
        if lows <= _TRUE:
            return None, True, _display(facet, raw[:1]), ""
        if lows <= _FALSE:
            return None, False, _display(facet, raw[:1]), ""
        return None, None, "", f"records disagree on {label}"
    return None, None, _display(facet, sorted(set(raw))), ""


def _record_filter_items(
    facet: Facet, filters: Sequence[FacetCriterion], catalogue: Optional[FacetCatalogue]
) -> List[_Item]:
    """The plan's filters that decide WHICH of a space's records an operation reads.

    Only filters on the same record class through the same join, in the class's default group
    (or none): "bookable seats" sums the seats of bookable workspace records. A criterion in a
    NAMED group is about a different record of the class and narrows the space, not the read.
    """
    if catalogue is None:
        return []
    items: List[_Item] = []
    for index, criterion in enumerate(filters):
        other = catalogue.get(criterion.facet)
        if (
            other is None
            or other.record_class != facet.record_class
            or other.join_predicate != facet.join_predicate
            or criterion.operator in SCORING_OPERATORS
            or criterion.record_group not in (None, "", facet.record_class)
        ):
            continue
        items.append(_Item(index, criterion, other))
    return items


async def _record_values(
    facet: Facet,
    space_iris: Sequence[str],
    sparql_exec: SparqlExec,
    items: Sequence[_Item],
    additive: bool,
) -> Dict[str, FacetValue]:
    predicates = sorted(({facet.predicate or ""} | {i.facet.predicate or "" for i in items}) - {""})
    query = record_query(
        _ONTOSAGE + str(facet.record_class), str(facet.join_predicate), predicates, space_iris
    )
    rows = await _select(sparql_exec, query, f"{facet.record_class} records")
    by_space = _records_by_space(rows, predicates)
    register = split_camel(str(facet.record_class))
    out: Dict[str, FacetValue] = {}
    for space in space_iris:
        records = sorted(by_space.get(space, {}).values(), key=lambda r: r.name)
        if not records:
            out[space] = FacetValue(space, reason=f"no {register} record")
            continue
        qualifying = [r for r in records if not items or _record_status(r, items) == MET]
        if not qualifying:
            out[space] = FacetValue(space, reason=f"no {register} record meets the other criteria")
            continue
        entries = [(r.name, sorted(r.values.get(facet.predicate or "", set()))) for r in qualifying]
        number, flag, display, reason = _combine(facet, entries, additive)
        out[space] = FacetValue(
            space,
            number=number,
            flag=flag,
            raw=sorted({v for _, values in entries for v in values}),
            display=display,
            provenance=[r.source(str(facet.record_class)) for r in qualifying[:3]],
            reason=reason,
        )
    return out


async def _property_values(
    facet: Facet, space_iris: Sequence[str], sparql_exec: SparqlExec
) -> Dict[str, FacetValue]:
    predicate = facet.predicate or ""
    rows = await _select(
        sparql_exec, space_property_query([predicate], space_iris), "space properties"
    )
    found: Dict[str, Set[str]] = {}
    for row in rows:
        space, value = _val(row, "space"), _val(row, "v0")
        if space and value:
            found.setdefault(space, set()).add(value)
    out: Dict[str, FacetValue] = {}
    source = f"{_local(predicate)} (building model)"
    for space in space_iris:
        values = sorted(found.get(space, set()))
        number, flag, display, reason = _combine(facet, [(source, values)], False)
        out[space] = FacetValue(
            space,
            number=number,
            flag=flag,
            raw=values,
            display=display,
            provenance=[source] if values else [],
            reason=reason,
        )
    return out


async def _capacity_values(
    facet: Facet, space_iris: Sequence[str], sparql_exec: SparqlExec
) -> Dict[str, FacetValue]:
    """Capacity through ``design_occupancy``'s authority order; a disagreement is no figure."""
    from orchestrator.services import design_occupancy

    occupancy = await design_occupancy.declared_design_occupancy(sparql_exec)
    out: Dict[str, FacetValue] = {}
    for space in space_iris:
        entry = occupancy.get(space)
        if entry is not None and entry.conflicted:
            figures = ", ".join(str(v) for v in entry.values)
            out[space] = FacetValue(
                space,
                raw=[str(v) for v in entry.values],
                provenance=["design occupancy (disagreeing sources)"],
                reason=f"the building states disagreeing capacities ({figures})",
            )
            continue
        if entry is None or entry.value is None:
            out[space] = FacetValue(space, reason="no design occupancy recorded")
            continue
        source = (
            "architect's drawing"
            if entry.source == design_occupancy.CAPACITY_SOURCE_DRAWING
            else "building model"
        )
        out[space] = FacetValue(
            space,
            number=float(entry.value),
            raw=[str(entry.value)],
            display=_display(facet, [str(entry.value)]),
            provenance=[f"design occupancy ({source})"],
        )
    return out


async def read_facet_values(
    facet: Facet,
    space_iris: Sequence[str],
    sparql_exec: SparqlExec,
    *,
    filters: Sequence[FacetCriterion] = (),
    catalogue: Optional[FacetCatalogue] = None,
    additive: bool = False,
) -> Dict[str, FacetValue]:
    """{space: FacetValue} -- ONE value per space for an aggregate or a comparison.

    Batched like ``resolve_facets``: one query for the facet's record class (every candidate in
    one VALUES block), one for a property of the spaces, one capacity read. Capacity goes through
    its authority order. A sensor facet is not read here -- its value is the executor's windowed
    reading -- and a facet that has no single value per space is reported as such.

    ``filters`` are the plan's criteria; those on the facet's own record class decide which of a
    space's records are read. ``additive`` sums several qualifying records of an amount.
    """
    iris = sorted({str(i) for i in space_iris if _iri(str(i))})
    if not iris:
        return {}
    why = ""
    try:
        if facet.key == _CAPACITY_FACET:
            return await _capacity_values(facet, iris, sparql_exec)
        if (
            facet.source_kind == "record"
            and facet.record_class
            and facet.join_predicate
            and facet.predicate
        ):
            items = _record_filter_items(facet, filters, catalogue)
            return await _record_values(facet, iris, sparql_exec, items, additive)
        if facet.source_kind == "ttl" and facet.predicate and facet.entity_type == "space":
            return await _property_values(facet, iris, sparql_exec)
        why = "has no single value per space to read"
    except Exception as exc:
        logger.warning(f"[facet_resolvers] values of {facet.key}: {describe_exception(exc)}")
        why = "could not be read"
    label = facet.label or facet.key
    return {space: FacetValue(space, reason=f"{label} {why}") for space in iris}


async def read_floor_labels(space_iris: Sequence[str], sparql_exec: SparqlExec) -> Dict[str, str]:
    """{floor local name: the floor's label} for the floors the given spaces are part of.

    The executor groups spaces by the floor local name the coverage audit gives each candidate;
    this is how the answer names that floor the way the building does. Empty when unreadable --
    the local name then stands in.
    """
    iris = sorted({str(i) for i in space_iris if _iri(str(i))})
    if not iris:
        return {}
    try:
        rows = await _select(sparql_exec, floor_query(iris), "floor labels")
    except Exception as exc:
        logger.info(f"[facet_resolvers] floor labels unavailable: {describe_exception(exc)}")
        return {}
    labels: Dict[str, str] = {}
    for row in rows:
        local, label = _local(_val(row, "floor")), _val(row, "label")
        if local and label and (local not in labels or label < labels[local]):
            labels[local] = label
    return labels


__all__ = [
    "FacetCheck",
    "FacetValue",
    "MET",
    "UNKNOWN",
    "UNMET",
    "evaluate",
    "facet_reader_label",
    "facet_value_set",
    "floor_query",
    "read_facet_values",
    "read_floor_labels",
    "record_query",
    "resolve_facets",
    "space_property_query",
    "value_set_query",
]
