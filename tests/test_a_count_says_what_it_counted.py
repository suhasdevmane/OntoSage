# -*- coding: utf-8 -*-
"""Two numbers in one answer must count the same thing, or say that they do not (BUG-441).

WHAT WENT WRONG
---------------
"How many sensors are there in total?" answered, in one block:

    - Sensors declared in the building model: 2,720
    - Sensors that reported data in the last 24 h: 2,763
    - Floors: 8
    - Mapped floor area: 6,129 m2 across 6 floors

Two contradictions on four lines: more sensors reporting than exist, and eight floors in a
six-storey building. Every number was correct.

**The floors.** `brick:Rooftop` and `brick:Parking_Level` are subclasses of `brick:Floor`
in Brick 1.4; the building asserts exactly those specific types, and RDFS inference
correctly derives `a brick:Floor` for both. The external review's remedy was to retype the
data -- which would have made the model LESS accurate to satisfy a count. The count is what
was wrong: it reported a total without saying what the hierarchy swept into it, the same
defect `measurand_kinds.ttl` exists to name for sensors (CAVEAT-286).

**The sensors.** The two figures count different UNITS. Declared counts SUBJECTS typed
`brick:Sensor`; reporting counts timeseries UUIDS, and a sensor may carry more than one
reference -- 2,720 sensors against 2,780 uuids attached to them and 2,841 uuids in the
graph. A stream is not an instrument, and two adjacent lines using the same noun invited
exactly the reading they got.

Nothing here names a building, a floor or a class: the breakdown is read from the graph, so
a building with a mezzanine or a basement gets its own vocabulary in the answer.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import building_metrics as bm  # noqa: E402
from orchestrator.services.building_metrics import (  # noqa: E402
    BuildingMetricsSnapshot,
    render_metrics_block,
)


def _snap(**kw) -> BuildingMetricsSnapshot:
    s = BuildingMetricsSnapshot()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ── the floor count ──────────────────────────────────────────────────────────


def test_a_floor_count_that_swept_in_other_kinds_says_so():
    snap = _snap(floor_count=8, floor_kinds=[("Floor", 6), ("Rooftop", 1), ("Parking_Level", 1)])
    out = render_metrics_block(snap, "Any Building")
    line = next(l for l in out.splitlines() if "Floors" in l)
    assert "8" in line
    assert "6 storeys" in line
    assert "rooftop" in line and "parking level" in line, (
        f"the count does not say what it included: {line!r}"
    )


def test_a_building_of_plain_storeys_gets_a_plain_count():
    """The explanation must not appear where there is nothing to explain."""
    snap = _snap(floor_count=6, floor_kinds=[("Floor", 6)])
    line = next(l for l in render_metrics_block(snap, "Any").splitlines() if "Floors" in l)
    assert line.strip() == "- Floors: **6**"


def test_the_breakdown_uses_the_buildings_own_vocabulary():
    """A building with a mezzanine says mezzanine, with no code change."""
    snap = _snap(floor_count=7, floor_kinds=[("Floor", 6), ("Mezzanine", 1)])
    line = next(l for l in render_metrics_block(snap, "Any").splitlines() if "Floors" in l)
    assert "mezzanine" in line


def test_an_unavailable_breakdown_still_reports_the_count():
    """An unexplained number beats no number; both beat a wrong one."""
    snap = _snap(floor_count=8, floor_kinds=[])
    line = next(l for l in render_metrics_block(snap, "Any").splitlines() if "Floors" in l)
    assert "8" in line


def test_the_breakdown_groups_by_asserted_type_not_by_most_specific():
    """Brick has a CYCLE here, and "most specific" is not defined inside one.

    `brick:Floor rdfs:subClassOf brick:Storey` AND `brick:Storey rdfs:subClassOf
    brick:Floor` are both asserted in Brick 1.4. The first version of this query asked for
    the most specific class via a FILTER NOT EXISTS over subclasses, and returned
    `Rooftop 1, Parking_Level 1` and NO STOREYS -- neither Floor nor Storey is ever most
    specific, so the filter eliminated both, and a six-storey building reported two floors.
    """
    src = inspect.getsource(bm.BuildingMetrics._floor_breakdown)
    assert "GRAPH ?g { ?s a ?t }" in src, (
        "the breakdown no longer reads asserted types; inference will put every subject "
        "under every superclass"
    )
    assert "FILTER NOT EXISTS { ?s a ?sub" not in src, (
        "the most-specific filter is back; Brick's Floor/Storey cycle makes it eliminate "
        "both of them"
    )


# ── the two sensor figures ───────────────────────────────────────────────────


def test_the_reporting_figure_does_not_call_streams_sensors():
    snap = _snap(total_sensors=2720, reporting_sensors=2763, reporting_window_h=24)
    out = render_metrics_block(snap, "Any")
    reporting = next(l for l in out.splitlines() if "2,763" in l)
    assert "stream" in reporting.lower(), (
        f"the reporting line still calls uuids sensors, so a reader compares it with the "
        f"sensor count above and finds more instruments reporting than exist: {reporting!r}"
    )


def test_the_reporting_figure_says_it_is_not_comparable():
    snap = _snap(total_sensors=2720, reporting_sensors=2763, reporting_window_h=24)
    reporting = next(
        l for l in render_metrics_block(snap, "Any").splitlines() if "2,763" in l
    )
    assert "not comparable" in reporting.lower() or "more than one stream" in reporting.lower()


def test_no_building_literal_reached_the_metrics_module():
    src = inspect.getsource(bm).lower()
    for literal in ("abacws", "cardiff", "buildsys", '"bldg1"', "rooftop_"):
        assert literal not in src, f"building literal in building_metrics: {literal}"
