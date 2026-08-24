# -*- coding: utf-8 -*-
"""Meter boundary and allocation method for energy answers (V6-T27, Master Package E).

An energy figure is meaningless without its **boundary** — what the meter actually covers — and,
when the figure is for something smaller than the meter, its **allocation method**. "Floor 2 used
5.46 kWh" is four different claims depending on whether floor 2 has its own meter, whether the
figure is a share of a building total apportioned by area, or whether it is a lighting circuit
that happens to sit on that floor. The number looks identical in all four cases.

Measured before this existed: every energy answer stated a figure and no boundary at all, and
`"How much energy did I use this month?"` was answered `22.06 kWh` by summing six floor meters —
an attribution no meter in the building can support. That refusal lives in the privacy inference
classes; **this module owns the other half**: saying what the figure does cover.

The model is TTL, not code:

* ``ontosage:meterServes``      — the entity the meter measures (a floor, a system, the building)
* ``ontosage:allocationMethod`` — how a figure for a smaller thing is derived from it
* ``ontosage:boundaryNote``     — free prose for anything the two above cannot carry

Adding a building's meter topology is therefore a TTL upload, never a code change, which is the
same contract sensors and plant points already have.

**An undeclared boundary is stated as undeclared.** The alternative — inferring that
`Energy_Meter_Floor2` serves floor 2 from its NAME — is the guess this codebase keeps paying for,
and it is exactly wrong for the case that matters: a meter named for the floor it sits ON while
metering only part of it. Where the graph does not say, the answer says the graph does not say.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_PREFIXES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
    # The namespace this building's own TTLs already declare, verified against them rather than
    # assumed — a second ontosage namespace would put these triples where nothing reads them,
    # which is the present-correct-and-invisible failure from V6-T26.
    "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
)

#: How a figure for a sub-boundary is derived. The KEY is what a building declares in its TTL;
#: the value is the phrase an answer uses. `direct` is the only one that is a measurement — every
#: other method is an estimate, and the wording says so rather than leaving the reader to assume.
ALLOCATION_METHODS: Dict[str, str] = {
    "direct": "measured directly by this meter",
    "sub_metered": "measured by a dedicated sub-meter",
    "apportioned_by_area": "estimated — a share of the parent meter, apportioned by floor area",
    "apportioned_by_occupancy": "estimated — a share of the parent meter, apportioned by occupancy",
    "apportioned_equally": "estimated — the parent meter's total divided equally",
    "modelled": "estimated — modelled rather than metered",
}

#: Methods that produce an ESTIMATE. Kept as data so a new method cannot be added without a
#: deliberate decision about which side of the line it falls on.
ESTIMATED_METHODS = frozenset(ALLOCATION_METHODS) - {"direct", "sub_metered"}


@dataclass
class MeterBoundary:
    """What one meter covers, and how figures below it are derived."""

    meter_iri: str
    serves_iri: str = ""
    serves_label: str = ""
    method: str = ""
    note: str = ""
    uuid: str = ""
    #: How the boundary was established: declared | brick_class | placement | label.
    #: Carried into the answer because a boundary inferred from where a meter SITS deserves
    #: different words from one an operator declared -- presenting the two identically is how a
    #: guess acquires the authority of a fact.
    source: str = ""

    @property
    def meter_name(self) -> str:
        return self.meter_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    @property
    def declared(self) -> bool:
        """True when the graph says what this meter serves. Absence is never inferred away."""
        return bool(self.serves_iri or self.serves_label)

    @property
    def is_estimate(self) -> bool:
        return self.method in ESTIMATED_METHODS

    @property
    def authoritative(self) -> bool:
        """True only when the boundary was DECLARED or follows from the Brick class.

        `placement` and `label` are proposals. Treating them as authoritative would have
        published "the building's water total covers Floor 0" -- the meter is installed there
        and measures the whole site.
        """
        return self.source in ("declared", "brick_class")

    @property
    def covers(self) -> str:
        return self.serves_label or self.serves_iri.rsplit("#", 1)[-1] or ""


def method_phrase(method: str) -> str:
    """Prose for a declared allocation method, or an honest note for an unknown one.

    An unrecognised method is NOT silently treated as direct measurement: a building declaring
    something this version does not understand must not have its estimate presented as a reading.
    """
    key = (method or "").strip().lower()
    if not key:
        return ""
    return ALLOCATION_METHODS.get(
        key, f"declared as '{method}', which this version does not recognise — treat as an estimate"
    )


def statement(boundaries: List[MeterBoundary], subject: str = "") -> str:
    """The boundary sentence that must accompany an energy figure.

    Three cases, deliberately worded differently, because they are three different claims:

    * one declared meter        -> what it covers, and whether the figure is measured or estimated
    * several meters summed     -> the sum's boundary is the UNION, and that is stated as a sum
    * nothing declared          -> say so, and name what would fix it

    Never returns "" for a non-empty input: an energy figure with no boundary line is the state
    this module exists to end.
    """
    if not boundaries:
        return (
            "**Boundary: not declared.** I can't say what this figure covers — the meter behind "
            "it has no `ontosage:meterServes` in the ontology. Declaring the meter's boundary "
            "and allocation method would let every energy answer state it."
        )

    declared = [b for b in boundaries if b.declared]
    if not declared:
        names = ", ".join(sorted({b.meter_name for b in boundaries}))
        return (
            f"**Boundary: not declared.** The figure comes from {names}, but the ontology does "
            f"not say what that meter covers, so I can't tell you whether it is the whole "
            f"{subject or 'space'} or one circuit within it."
        )

    if len(declared) == 1:
        b = declared[0]
        phrase = method_phrase(b.method)
        line = f"**Boundary:** {b.meter_name} — covers {b.covers}"
        if not b.authoritative:
            # A boundary read off where the meter is INSTALLED is not a metering scope, and the
            # sentence has to say so. The same graph that puts the site water meter on floor 0
            # would otherwise have this answer report the whole site's water as floor 0's.
            line += (
                " (inferred from where the meter sits, not a declared metering boundary — "
                "it may cover more or less than that)"
            )
        if phrase:
            line += f"; {phrase}"
        else:
            line += "; allocation method not declared, so treat any sub-figure as an estimate"
        if b.note:
            line += f". {b.note}"
        return line + "."

    covers = ", ".join(sorted({b.covers for b in declared if b.covers}))
    names = ", ".join(sorted({b.meter_name for b in declared}))
    estimated = [b for b in declared if b.is_estimate]
    line = (
        f"**Boundary:** summed across {len(declared)} meters ({names}), covering {covers}. "
        f"The total is the sum of those boundaries — it is not a separate whole-site reading"
    )
    if estimated:
        line += (
            f", and {len(estimated)} of them contribute an estimated share rather than a "
            f"direct measurement"
        )
    return line + "."


def boundary_query(namespace: str) -> str:
    """Every meter's declared boundary in the active building.

    One query for the whole building rather than one per answer: the topology is small (tens of
    meters) and changes only when a TTL is uploaded.
    """
    return (
        _PREFIXES
        + "SELECT DISTINCT ?meter ?serves ?servesLabel ?method ?note ?uuid ?source WHERE {\n"
        # Energy_Sensor as well as Meter: in a retrofitted estate the readable thing is usually
        # the POINT, and the meter individual carries no timeseries reference at all. A boundary
        # only reachable from the Meter would be correct and never found.
        "  { ?meter a ?cls . ?cls rdfs:subClassOf* brick:Meter }\n"
        "  UNION { ?meter a ?ecls . ?ecls rdfs:subClassOf* brick:Energy_Sensor }\n"
        "  OPTIONAL { ?meter ontosage:meterServes ?serves .\n"
        "             OPTIONAL { ?serves rdfs:label ?servesLabel } }\n"
        "  OPTIONAL { ?meter ontosage:allocationMethod ?method }\n"
        "  OPTIONAL { ?meter ontosage:boundarySource ?source }\n"
        "  OPTIONAL { ?meter ontosage:boundaryNote ?note }\n"
        "  OPTIONAL { ?meter ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid }\n"
        f'  FILTER(STRSTARTS(STR(?meter), "{namespace}"))\n'
        "}"
    )


def from_rows(rows: Any) -> Dict[str, MeterBoundary]:
    """{meter local name: MeterBoundary} from either SPARQL result shape.

    Both executor conventions are handled here rather than at the call site — writing this for
    one shape and being handed the other is how a plant lookup turned into a confident false
    "no equipment is declared" (BUG-259).
    """
    from orchestrator.services.evidence.plant_state import rows_of

    out: Dict[str, MeterBoundary] = {}
    for row in rows_of(rows):
        iri = str(row.get("meter") or "")
        if not iri:
            continue
        key = iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        existing = out.get(key)
        b = MeterBoundary(
            meter_iri=iri,
            serves_iri=str(row.get("serves") or ""),
            serves_label=str(row.get("servesLabel") or ""),
            method=str(row.get("method") or ""),
            note=str(row.get("note") or ""),
            uuid=str(row.get("uuid") or ""),
            source=str(row.get("source") or ""),
        )
        # Prefer the row that carries the declaration: reasoning returns a meter once per
        # matched superclass, and an undeclared duplicate must not displace a declared one.
        if existing is None or (not existing.declared and b.declared):
            out[key] = b
    return out


def match(boundaries: Dict[str, MeterBoundary], uuids: List[str], names: List[str]):
    """The boundaries behind a figure, matched by timeseries uuid first, then by meter name.

    UUID is the reliable key — it is what the reading was actually fetched with. Name matching
    is the fallback for answers that cite a meter without carrying its uuid, and it requires an
    EXACT local-name match; substring matching would attach `Energy_Meter_Floor1`'s boundary to
    a figure about `Energy_Meter_Floor10`.
    """
    want_uuids = {u for u in uuids if u}
    hits = [b for b in boundaries.values() if b.uuid and b.uuid in want_uuids]
    if hits:
        return hits
    want_names = {str(n).rsplit("#", 1)[-1].rsplit("/", 1)[-1] for n in names if n}
    return [b for b in boundaries.values() if b.meter_name in want_names]


async def for_building(namespace: str, run_select) -> Dict[str, MeterBoundary]:
    """Load the building's meter topology. Never raises — an energy answer without a boundary
    line is worse than one with, but far better than no answer at all."""
    if not namespace or run_select is None:
        return {}
    try:
        return from_rows(await run_select(boundary_query(namespace) + "\nLIMIT 500"))
    except Exception as exc:
        logger.debug(f"[meter] boundary lookup failed: {exc}")
        return {}


__all__ = [
    "ALLOCATION_METHODS",
    "ESTIMATED_METHODS",
    "MeterBoundary",
    "boundary_query",
    "for_building",
    "from_rows",
    "match",
    "method_phrase",
    "statement",
]
