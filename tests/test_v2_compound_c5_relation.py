# -*- coding: utf-8 -*-
"""v2, shape C5 -- a measured series related to recorded events or to a second series.

"Is CO2 higher during timetabled sessions?", "does noise rise in the half hour after access
events?", "when occupancy goes up, does CO2 follow?", "what happens to CO2 while the window is
open?". The answer is CO-OCCURRENCE -- a level during and outside the events, or a correlation of
aligned time buckets -- never a cause, and every figure carries its n (spaces, events, buckets,
readings). A space or an event missing a side is named, never imputed.

Which registers are EVENTS is decided from the graph at run time (``event_sources``): a class whose
records are placed in a space and on the clock. The window and the lag are read from the question
in code; the model names only the reading and what it is set against.

Everything here runs OFFLINE: pure arithmetic, an rdflib graph of an invented building, a stub
LLM, and a fake narrow store that answers the aggregate lane's bucketed GROUP BY from memory.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import rdflib

from orchestrator.services import aggregate_lane as agl
from orchestrator.services import requested_interval as ri
from orchestrator.services import routing_contract as rc
from orchestrator.services.deliberation import capability_schema as cs
from orchestrator.services.deliberation import clarify_policy as cp
from orchestrator.services.deliberation import compiler as C
from orchestrator.services.deliberation import event_sources as evs
from orchestrator.services.deliberation import facet_routing as fr
from orchestrator.services.deliberation import facets
from orchestrator.services.deliberation import operations as ops
from orchestrator.services.deliberation.coverage_audit import (
    CoverageAuditor,
    ModalitySpec,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    V2_DECISIONS,
    Constraint,
    DecisionKind,
    Direction,
    GroupBy,
    RelateSpec,
    RelationKind,
    ThresholdSource,
)
from orchestrator.services.deliberation.dossier import (
    build_dossier,
    numeric_guard,
    render_answer,
    render_dossier_details,
)
from orchestrator.services.deliberation.plan_executor import execute
from shared import config as shared_config

pytestmark = pytest.mark.unit

ONTO = "http://ontosage.org/capabilities#"
NS = "http://example.org/campusE#"
BID = "campusE"
REPO = Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


def _settings():
    import shared.config

    return shared.config.settings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    facets.clear_cache()
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", True, raising=False)
    monkeypatch.setenv("CQIR_COMPILE_CACHE", "false")
    yield
    facets.clear_cache()


# ── 1. the arithmetic, pure ─────────────────────────────────────────────────────────────

B = ops.Bucket
Q = 900  # a quarter-hour bucket, in seconds


def _flat(level_in: float, level_out: float, inside, n: int = 3, buckets: int = 96):
    """Quarter-hour buckets of ``n`` readings: ``level_in`` in the buckets listed, else out."""
    return {i: B(n, n * (level_in if i in inside else level_out)) for i in range(buckets)}


def _inp(name, series, events=(), groups=("F",), other=None, reason=""):
    return ops.RelationInput(
        space_iri=NS + name,
        label=f"Room {name}",
        groups=list(groups),
        series=series,
        other=other or {},
        events=list(events),
        reason=reason,
    )


def _relate(relation, spaces, **kw):
    kw.setdefault("bucket_seconds", Q)
    kw.setdefault("series", "sensor:co2")
    kw.setdefault("label", "co2")
    kw.setdefault("unit", "ppm")
    return ops.relate(relation, spaces, **kw)


def test_during_pools_reading_by_reading_and_every_figure_has_its_n():
    # Room A: an event 09:00-11:00 (buckets 36..43) reads 800, the rest 500.
    # Room B: an event 10:00-12:00 (buckets 40..47) reads 900, the rest 600.
    a = _inp("A", _flat(800, 500, range(36, 44)), [(9 * 3600, 11 * 3600)])
    b = _inp("B", _flat(900, 600, range(40, 48)), [(10 * 3600, 12 * 3600)], groups=("G",))
    res = _relate(RelationKind.DURING, [a, b], group_by="floor", events_label="lecture")
    o = res.overall
    assert (o.spaces, o.events, o.events_read, o.events_above) == (2, 2, 2, 2)
    assert (o.in_mean, o.in_buckets, o.in_readings) == (850.0, 16, 48)
    assert (o.out_mean, o.out_buckets, o.out_readings) == (550.0, 176, 528)
    assert (o.difference, o.percent) == (300.0, 54.55)
    assert (o.spaces_higher, o.spaces_lower, o.spaces_same, o.mean_space_difference) == (
        2,
        0,
        0,
        300.0,
    )
    by = {g.key: g for g in res.groups}
    assert (by["F"].in_mean, by["F"].out_mean, by["F"].spaces) == (800.0, 500.0, 1)
    assert res.not_compared == [] and res.bucket_minutes == 15


def test_a_pooled_mean_is_reported_beside_the_spaces_own_differences():
    """Spaces with more event time weigh more in a pooled mean: the per-space view is shown too."""
    many = _inp("A", _flat(700, 600, range(0, 48)), [(0, 12 * 3600)])  # half the day in events
    few = _inp("B", _flat(450, 400, range(0, 4)), [(0, 3600)])  # one hour
    o = _relate(RelationKind.DURING, [many, few]).overall
    assert (o.spaces_higher, o.mean_space_difference) == (2, 75.0)
    # (144 x 700 + 12 x 450) / 156 and (144 x 600 + 276 x 400) / 420: A's 48 event buckets dominate
    assert (o.in_mean, o.out_mean, o.difference) == (680.77, 468.57, 212.2)


def test_after_reads_the_lag_after_each_event_and_never_the_event_itself():
    # An event 10:00-11:00 (buckets 40..43); 30 minutes after it = buckets 44, 45.
    series = {i: B(3, 3 * (700.0 if i in (44, 45) else 450.0)) for i in range(96)}
    res = _relate(
        RelationKind.AFTER,
        [_inp("A", series, [(10 * 3600, 11 * 3600)])],
        lag_seconds=1800,
        events_label="session",
    )
    o = res.overall
    assert (o.in_mean, o.in_buckets, o.out_mean, o.out_buckets) == (700.0, 2, 450.0, 90)
    assert o.neither_buckets == 4, "the four buckets during the event are in neither figure"
    assert (o.events_read, o.events_above, res.lag_minutes) == (1, 1, 30.0)


def test_a_bucket_straddling_an_events_edge_is_in_neither_figure():
    # An event 09:10-09:50 covers 5 minutes of bucket 36 (09:00-09:15), all of 37 and 38, and
    # 5 minutes of 39: two buckets are during it, two straddle its edges, 92 are outside it.
    space = _inp("A", _flat(800, 500, set()), [(9 * 3600 + 600, 9 * 3600 + 3000)])
    s = _relate(RelationKind.DURING, [space]).spaces[0]
    assert (s.in_buckets, s.neither_buckets, s.out_buckets) == (2, 2, 92)
    # a bucket at least HALF inside an event counts as during it: 09:05-09:55 adds 36 and 39
    wider = _inp("A", _flat(800, 500, set()), [(9 * 3600 + 300, 9 * 3600 + 3300)])
    s = _relate(RelationKind.DURING, [wider]).spaces[0]
    assert (s.in_buckets, s.neither_buckets) == (4, 0)


def test_a_space_missing_a_side_is_named_and_never_imputed():
    no_out = _inp("A", _flat(800, 800, range(96)), [(0, 86400)])
    no_readings = _inp("B", {}, [(0, 3600)])
    unsensed = _inp("C", {}, [(0, 3600)], reason="no co2 sensor")
    fine = _inp("D", _flat(800, 500, range(36, 44)), [(9 * 3600, 11 * 3600)])
    res = _relate(RelationKind.DURING, [no_out, no_readings, unsensed, fine])
    assert res.overall.spaces == 1 and res.overall.in_mean == 800.0
    assert res.n_not_compared == 3
    assert res.not_compared == [
        "Room A (no readings outside its events)",
        "Room B (no readings in the window)",
        "Room C (no co2 sensor)",
    ]


def test_an_instant_has_no_during_and_is_counted():
    space = _inp("A", _flat(800, 500, set()), [(36000, 36000), (40000, 40000)])
    res = _relate(RelationKind.DURING, [space])
    s = res.spaces[0]
    assert (s.events, s.instants, s.in_readings, s.events_read) == (2, 2, 0, 0)
    assert s.reason == "no readings during its events" and res.instants == 2


def test_equal_sides_are_the_same_never_higher():
    space = _inp("A", _flat(500, 500, set()), [(9 * 3600, 10 * 3600)])
    o = _relate(RelationKind.DURING, [space]).overall
    assert (o.difference, o.percent, o.spaces_same, o.spaces_higher) == (0.0, 0.0, 1, 0)
    assert o.events_above == 0, "level with the outside is not above it"


def test_nothing_in_gives_no_figure():
    res = _relate(RelationKind.DURING, [])
    assert res.overall.spaces == 0 and res.overall.in_mean is None and res.not_compared == []
    assert _relate(RelationKind.CO_MOVEMENT, []).overall.pearson is None


def test_a_yes_no_reading_on_against_off():
    # on (1) in buckets 48..51, off (0) elsewhere, half-on in 52 -> neither; 53 unread -> neither
    state = {i: B(3, 3.0 if 48 <= i <= 51 else 0.0) for i in range(96) if i != 53}
    state[52] = B(4, 1.0)
    series = _flat(450, 650, range(48, 52))
    res = _relate(RelationKind.DURING, [_inp("A", series, other=state)], state=True)
    s = res.spaces[0]
    assert (s.in_mean, s.in_buckets, s.out_mean, s.out_buckets) == (450.0, 4, 650.0, 90)
    assert (s.neither_buckets, s.events, s.difference) == (2, 1, -200.0)
    assert res.overall.spaces_lower == 1


def test_co_movement_per_space_and_pooled_within_each_space():
    """Simpson's case: room A is busy and fresh, room B empty and stuffy, but WITHIN each room
    CO2 rises with occupancy. Pooled raw, the rooms' levels would correlate negatively; pooled
    within each room, the co-movement is what it is."""
    hours = range(12)
    occ_a = {h: B(1, 20.0 + (h % 3)) for h in hours}
    co2_a = {h: B(1, 400.0 + 10 * (h % 3)) for h in hours}
    occ_b = {h: B(1, 1.0 + (h % 3)) for h in hours}
    co2_b = {h: B(1, 900.0 + 10 * (h % 3)) for h in hours}
    res = _relate(
        RelationKind.CO_MOVEMENT,
        [_inp("A", co2_a, other=occ_a), _inp("B", co2_b, other=occ_b)],
        bucket_seconds=3600,
    )
    raw = ops.pearson(
        [b.mean for b in list(occ_a.values()) + list(occ_b.values())],
        [b.mean for b in list(co2_a.values()) + list(co2_b.values())],
    )
    assert raw < -0.9, "the rooms' levels alone point the other way"
    o = res.overall
    assert (o.spaces, o.pairs, o.pearson, o.median_pearson, o.spaces_positive) == (
        2,
        24,
        1.0,
        1.0,
        2,
    )
    assert (o.changes, o.change_pearson) == (22, 1.0)
    assert res.spaces[0].spearman == 1.0 and res.bucket_minutes == 60


def test_a_correlation_needs_three_pairs_and_two_changing_series():
    flat = {h: B(1, 5.0) for h in range(10)}
    moving = {h: B(1, float(h)) for h in range(10)}
    two = {h: B(1, float(h)) for h in range(2)}
    res = _relate(
        RelationKind.CO_MOVEMENT,
        [_inp("A", moving, other=flat), _inp("B", two, other=two), _inp("C", moving)],
        bucket_seconds=3600,
    )
    reasons = {s.label: s.reason for s in res.spaces}
    assert reasons == {
        "Room A": "one of the two readings did not change",
        "Room B": "only 2 period(s) with both readings",
        "Room C": "no period with both readings",
    }
    assert res.overall.spaces == 0 and res.n_not_compared == 3


def test_pearson_spearman_and_ties():
    assert ops.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert ops.pearson([1, 2, 3], [3, 2, 1]) == -1.0
    assert ops.pearson([1, 1, 1], [1, 2, 3]) is None
    assert ops.pearson([0.1 + 0.2] * 3, [1, 2, 3]) is None, "floating-point dust is not a spread"
    assert ops.spearman([1, 2, 2, 3], [10, 30, 30, 90]) == 1.0
    assert round(ops.spearman([1, 2, 3, 4], [1, 3, 2, 4]), 4) == 0.8


def test_intervals_merge_and_instants_stay_instants():
    assert ops.merge_intervals([(5, 9), (0, 3), (3, 4), (8, 12), (20, 20)]) == [
        (0.0, 4.0),
        (5.0, 12.0),
        (20.0, 20.0),
    ]


def test_every_relation_figure_is_evidence_for_the_claim_binder():
    a = _inp("A", _flat(800, 500, range(36, 44)), [(9 * 3600, 11 * 3600)])
    figures = ops.computed_figures(_relate(RelationKind.DURING, [a]))
    assert figures["all in_mean"] == 800.0 and figures["all difference"] == 300.0
    assert figures["A in_readings"] == 24.0 and figures["bucket minutes"] == 15.0


# ── 2. what counts as an event: the TBox's interval vocabulary, the data's own shape ────


def _profile(records: int, **preds) -> evs.SourceProfile:
    return evs.SourceProfile("TestThing", records, 2, preds)


def _p(predicate, *, distinct, family, records=4, clock=False, first="", last=""):
    xsd = "http://www.w3.org/2001/XMLSchema#"
    dt = {"datetime": "dateTime", "date": "date", "text": "string", "number": "integer"}[family]
    return evs.PredicateProfile(predicate, records, distinct, (xsd + dt,), first, last, clock=clock)


def test_an_instant_start_places_a_record_on_the_clock():
    roles = evs.time_roles(
        _profile(
            4,
            **{
                evs.START: _p(evs.START, distinct=4, family="datetime"),
                evs.END: _p(evs.END, distinct=4, family="datetime"),
            },
        )
    )
    assert roles == ((evs.ROLE_START, evs.START), (evs.ROLE_END, evs.END))


def test_a_day_with_a_wall_clock_start_does_and_a_document_stamp_never_does():
    preds = {
        evs.START: _p(evs.START, distinct=1, family="date"),  # the register's front-matter date
        evs.DAY: _p(evs.DAY, distinct=1, family="date"),  # every event on one day: still a day
        evs.CLOCK_START: _p(evs.CLOCK_START, distinct=3, family="text", clock=True),
        evs.CLOCK_END: _p(evs.CLOCK_END, distinct=3, family="text", clock=True),
    }
    assert evs.time_roles(_profile(4, **preds)) == (
        (evs.ROLE_DAY, evs.DAY),
        (evs.ROLE_CLOCK_START, evs.CLOCK_START),
        (evs.ROLE_CLOCK_END, evs.CLOCK_END),
    )
    # effectiveFrom as a varying date is the day itself when no effectiveDate is recorded
    varying = {
        evs.START: _p(evs.START, distinct=4, family="date"),
        evs.CLOCK_START: _p(evs.CLOCK_START, distinct=3, family="text", clock=True),
        evs.MINUTES: _p(evs.MINUTES, distinct=2, family="number"),
    }
    assert evs.time_roles(_profile(4, **varying))[0] == (evs.ROLE_DAY, evs.START)
    assert evs.time_roles(_profile(4, **varying))[-1] == (evs.ROLE_MINUTES, evs.MINUTES)
    # the stamp alone, with a clock time, places nothing
    stamped = {
        evs.START: _p(evs.START, distinct=1, family="date"),
        evs.CLOCK_START: _p(evs.CLOCK_START, distinct=3, family="text", clock=True),
    }
    assert evs.time_roles(_profile(4, **stamped)) == ()


@pytest.mark.parametrize(
    "preds",
    [
        {},  # no time at all
        {evs.START: None},  # a date only: day precision, not the clock
        {evs.CLOCK_START: None},  # a clock time with no day
        {evs.START: "notclock"},  # a day with a start that is not a wall-clock time
    ],
)
def test_a_record_that_cannot_be_placed_on_the_clock_is_no_event_source(preds):
    built: Dict[str, evs.PredicateProfile] = {}
    for key, kind in preds.items():
        if key == evs.START:
            built[key] = _p(key, distinct=4, family="date")
            if kind == "notclock":
                built[evs.CLOCK_START] = _p(evs.CLOCK_START, distinct=3, family="text")
        else:
            built[key] = _p(key, distinct=3, family="text", clock=True)
    assert evs.time_roles(_profile(4, **built)) == ()


ROLES_DAY = (
    (evs.ROLE_DAY, evs.DAY),
    (evs.ROLE_CLOCK_START, evs.CLOCK_START),
    (evs.ROLE_CLOCK_END, evs.CLOCK_END),
)
ROLES_INSTANT = ((evs.ROLE_START, evs.START), (evs.ROLE_END, evs.END))
NOW = datetime(2026, 10, 7, 12, 0, 0)


def test_local_wall_clock_is_placed_on_the_stores_utc_clock():
    rows = [
        {
            "r": NS + "s1",
            "space": NS + "L1",
            "rid": "S-1",
            "day": "2026-09-14",
            "cs": "09:00",
            "ce": "11:00",
            "status": "completed",
        },
        # a cancelled session did not happen
        {
            "r": NS + "s2",
            "space": NS + "L1",
            "rid": "S-2",
            "day": "2026-09-14",
            "cs": "13:00",
            "ce": "14:00",
            "status": "Cancelled",
        },
        # no readable start
        {"r": NS + "s3", "space": NS + "L1", "day": "2026-09-14", "cs": "", "ce": "14:00"},
        # an end before the start runs past midnight
        {"r": NS + "s4", "space": NS + "L2", "day": "2026-09-14", "cs": "23:00", "ce": "01:00"},
    ]
    events, counts = evs.assemble_events(rows, ROLES_DAY, "Europe/London", NOW)
    assert (counts.read, counts.cancelled, counts.untimed) == (4, 1, 1)
    first = next(e for e in events if e.rid == "S-1")
    # 14 September is British Summer Time: 09:00 local is 08:00 on the stores' clock
    assert (first.start, first.end) == (datetime(2026, 9, 14, 8), datetime(2026, 9, 14, 10))
    late = next(e for e in events if e.space_iri == NS + "L2")
    assert late.end - late.start == timedelta(hours=2)


def test_instants_open_ended_events_and_explicit_offsets():
    rows = [
        {
            "r": NS + "a",
            "space": NS + "S1",
            "start": "2026-09-14T10:00:00",
            "end": "2026-09-14T10:00:00",
        },
        {"r": NS + "b", "space": NS + "S1", "start": "2026-10-07T09:00:00"},  # still in force
        {
            "r": NS + "c",
            "space": NS + "S1",
            "start": "2026-09-14T10:00:00Z",
            "end": "2026-09-14T11:00:00+00:00",
        },
    ]
    events, counts = evs.assemble_events(rows, ROLES_INSTANT, "Europe/London", NOW)
    by = {e.record.rsplit("#", 1)[-1]: e for e in events}
    assert by["a"].instant and by["a"].start == datetime(2026, 9, 14, 9)
    assert by["b"].open_ended and by["b"].end == NOW and counts.open_ended == 1
    assert by["c"].start == datetime(2026, 9, 14, 10), "an explicit offset converts directly"


# ── 3. a building, its event sources, and a store that buckets in SQL ───────────────────

DAY = "2026-09-14"  # a Monday
FROZEN_UTC = datetime(2026, 10, 7, 12, 0, 0)

_TBOX = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix x: <http://example.org/campusE#> .

brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
o:Record a owl:Class .
x:G a brick:Floor ; rdfs:label "Ground" .
x:U a brick:Floor ; rdfs:label "Upper" .
o:TestLecture rdfs:subClassOf o:Record ; rdfs:label "Lecture slot" ;
    o:layTerms "lecture", "lectures" .
o:TestDoorLog rdfs:subClassOf o:Record ; rdfs:label "Door log entry" ;
    o:layTerms "door log", "door events" .
o:TestRota rdfs:subClassOf o:Record ; rdfs:label "Cleaning rota" ; o:layTerms "cleaning" .
"""

#: (room, floor, sensed modalities)
ROOMS = [
    ("L1", "G", ("co2", "occupancy", "window_contact")),
    ("L2", "G", ("co2", "occupancy")),
    ("S1", "U", ("co2", "occupancy", "window_contact")),
    ("S2", "U", ("co2",)),
    ("X1", "U", ()),
]
_CLASS = {
    "co2": "CO2_Level_Sensor",
    "occupancy": "Occupancy_Count_Sensor",
    "window_contact": "Contact_Sensor",
}

_RECORDS = f"""
x:lec1 a o:TestLecture ; o:recordId "LEC-1" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:effectiveDate "{DAY}"^^xsd:date ; o:startsAt "09:00" ; o:endsAt "11:00" ;
    o:locatedInSpace x:L1 ; o:recordStatus "completed" .
x:lec2 a o:TestLecture ; o:recordId "LEC-2" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:effectiveDate "{DAY}"^^xsd:date ; o:startsAt "13:00" ; o:endsAt "14:00" ;
    o:locatedInSpace x:L1 ; o:recordStatus "completed" .
x:lec3 a o:TestLecture ; o:recordId "LEC-3" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:effectiveDate "{DAY}"^^xsd:date ; o:startsAt "10:00" ; o:endsAt "12:00" ;
    o:locatedInSpace x:L2 ; o:recordStatus "completed" .
x:lec4 a o:TestLecture ; o:recordId "LEC-4" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:effectiveDate "{DAY}"^^xsd:date ; o:startsAt "15:00" ; o:endsAt "16:00" ;
    o:locatedInSpace x:L2 ; o:recordStatus "cancelled" .
x:lec5 a o:TestLecture ; o:recordId "LEC-5" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:effectiveDate "{DAY}"^^xsd:date ; o:startsAt "09:00" ; o:endsAt "10:00" ;
    o:locatedInSpace x:X1 ; o:recordStatus "completed" .
x:door1 a o:TestDoorLog ; o:recordId "DL-1" ;
    o:effectiveFrom "{DAY}T10:00:00"^^xsd:dateTime ; o:effectiveTo "{DAY}T10:00:00"^^xsd:dateTime ;
    o:aboutSpace x:S1 .
x:door2 a o:TestDoorLog ; o:recordId "DL-2" ;
    o:effectiveFrom "{DAY}T15:00:00"^^xsd:dateTime ; o:effectiveTo "{DAY}T15:00:00"^^xsd:dateTime ;
    o:aboutSpace x:S1 .
x:door3 a o:TestDoorLog ; o:recordId "DL-3" ;
    o:effectiveFrom "{DAY}T12:00:00"^^xsd:dateTime ; o:effectiveTo "{DAY}T12:00:00"^^xsd:dateTime ;
    o:aboutSpace x:U .
x:rota1 a o:TestRota ; o:recordId "R-1" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:lastCompleted "{DAY}"^^xsd:date ; o:readyBy "08:00" ; o:locatedInSpace x:L1 .
x:rota2 a o:TestRota ; o:recordId "R-2" ; o:effectiveFrom "2026-09-01"^^xsd:date ;
    o:lastCompleted "{DAY}"^^xsd:date ; o:readyBy "08:00" ; o:locatedInSpace x:L2 .
"""


def _uuid(room: str, modality: str) -> str:
    return f"{modality.replace('_', '')}-{room}-0000"


def _building(with_records: bool = True) -> rdflib.Graph:
    lines = [_TBOX]
    for room, floor, sensed in ROOMS:
        lines.append(
            f'x:{room} a brick:Room ; rdfs:label "Room {room}" ; brick:isPartOf x:{floor} .\n'
        )
        for modality in sensed:
            lines.append(
                f"x:{modality}_{room} a brick:{_CLASS[modality]} ; "
                f'rdfs:label "{modality.replace("_", " ")} {room}" ; brick:hasLocation x:{room} ;\n'
                f'  ref:hasExternalReference [ ref:hasTimeseriesId "{_uuid(room, modality)}" ; '
                f"ref:storedAt x:{modality}_data ] .\n"
            )
    if with_records:
        lines.append(_RECORDS)
    g = rdflib.Graph()
    g.parse(data="\n".join(lines), format="turtle")
    return g


def _sparql_json(g: rdflib.Graph):
    async def sparql_exec(query: str) -> Dict[str, Any]:
        res = g.query(query)
        bindings = []
        for row in res:
            binding = {}
            for var in res.vars:
                val = row[var]
                if val is not None:
                    kind = "uri" if isinstance(val, rdflib.URIRef) else "literal"
                    binding[str(var)] = {"type": kind, "value": str(val)}
            bindings.append(binding)
        return {"head": {"vars": [str(v) for v in res.vars]}, "results": {"bindings": bindings}}

    return sparql_exec


def _in(hour_min: Tuple[int, int], spans) -> bool:
    minutes = hour_min[0] * 60 + hour_min[1]
    return any(a * 60 <= minutes < b * 60 for a, b in spans)


def _readings() -> Dict[str, List[Tuple[datetime, float]]]:
    """Five-minute readings across the day, shaped so every figure can be checked by hand."""
    out: Dict[str, List[Tuple[datetime, float]]] = {}
    day = datetime.strptime(DAY, "%Y-%m-%d")
    lectures = {"L1": [(9, 11), (13, 14)], "L2": [(10, 12)]}
    for room, _floor, sensed in ROOMS:
        for modality in sensed:
            rows = []
            for k in range(288):
                t = day + timedelta(minutes=5 * k)
                hm = (t.hour, t.minute)
                busy = _in(hm, lectures.get(room, []))
                if modality == "co2":
                    if room == "L1":
                        value = 800.0 if busy else 500.0
                    elif room == "L2":
                        value = 900.0 if busy else 600.0
                    elif room == "S1":
                        after = (10, 0) <= hm < (10, 30) or (15, 0) <= hm < (15, 30)
                        value = 700.0 if after else 450.0
                    else:
                        value = 520.0
                elif modality == "occupancy":
                    value = 10.0 if busy else 0.0
                else:  # window contact: open 12:00-13:00 in L1, never in S1
                    value = 1.0 if room == "L1" and t.hour == 12 else 0.0
                rows.append((t, value))
            out[_uuid(room, modality)] = rows
    return out


@dataclass
class _Result:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class _Kind:
    value = "mysql"


class _BucketStore:
    """Answers the aggregate lane's narrow BUCKET statement from in-memory readings."""

    adapter_type = _Kind()
    table = "narrow_data"

    def __init__(self):
        self.series = _readings()
        self.statements: List[str] = []

    async def execute_query(self, sql: str):
        self.statements.append(sql)
        assert "GROUP BY `uuid`, b" in sql, "a relation is never read row by row"
        uuids = re.findall(r"'([0-9A-Za-z-]{8,64})'", sql.split("IN (", 1)[1].split(")", 1)[0])
        start = re.search(r"`datetime` >= '([^']+)'", sql).group(1)
        end = re.search(r"`datetime` <= '([^']+)'", sql).group(1)
        size = int(re.search(r"/ (\d+)\) AS b", sql).group(1))
        lo = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        hi = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        rows: Dict[Tuple[str, int], List[float]] = {}
        for uuid in uuids:
            for t, v in self.series.get(uuid, []):
                if lo <= t <= hi:
                    b = int((t - lo).total_seconds() // size)
                    rows.setdefault((uuid, b), []).append(v)
        data = [
            {"uuid": u, "b": b, "n": len(vs), "sm": sum(vs)} for (u, b), vs in sorted(rows.items())
        ]
        return _Result(data=data)


MODALITIES = [
    ModalitySpec("co2", ["CO2_Level_Sensor"], sat={"unit": "ppm", "scope": "room"}),
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"], sat={"unit": "persons", "scope": "room"}),
    ModalitySpec(
        "window_contact",
        ["Contact_Sensor"],
        label_contains=["window"],
        sat={"unit": "binary", "scope": "room"},
    ),
]


def _catalogue(g: rdflib.Graph) -> facets.FacetCatalogue:
    facets.clear_cache()
    return _run(
        facets.build_facet_catalogue(
            _sparql_json(g), BID, NS, MODALITIES, modality_config={}, events_store=False
        )
    )


def test_the_catalogue_finds_event_sources_in_the_graph_and_never_by_name():
    cat = _catalogue(_building())
    assert cat.errors == ()
    sources = {f.key: f for f in cat.event_sources()}
    assert set(sources) == {
        "event:TestLecture",
        "event:TestDoorLog",
    }, "the rota records a completion DATE and a ready-by deadline: not a time on the clock"
    lecture = sources["event:TestLecture"]
    assert (lecture.value_type, lecture.source_kind, lecture.entity_type) == (
        "interval",
        "event",
        "space",
    )
    assert lecture.roles == ROLES_DAY, "the constant effectiveFrom stamp is not the day"
    assert (lecture.coverage, lecture.status, lecture.examples) == (3, "suitable", (DAY, DAY))
    assert lecture.label == "lecture slot" and "lectures" in lecture.lay_terms
    door = sources["event:TestDoorLog"]
    assert door.roles == ROLES_INSTANT and door.coverage == 1, "a floor is not a space"
    assert facets.INTERVAL in facets.VALUE_TYPES and C._INTERVAL == facets.INTERVAL


def test_event_sources_leave_criterion_retrieval_exactly_as_it_was():
    """The same catalogue with and without its event sources: every score, every match and the
    unique-word weight identical, so no C1-C3 routing decision can move."""
    with_events = _catalogue(_building())
    without = facets.FacetCatalogue([f for f in with_events if f.value_type != "interval"])
    assert len(with_events) == len(without) + 2
    for question in (
        "Which room has the most lectures and the lowest CO2?",
        "Is CO2 higher during lectures?",
        "noise after the door events",
        "a quiet room with a window open",
    ):
        assert with_events.scores(question) == without.scores(question), question
        assert with_events.term_matches(question) == without.term_matches(question), question
    assert with_events.unique_word_weight == without.unique_word_weight
    hits = [f for _, f in with_events.retrieve("lectures lecture slot door events", k=50)]
    assert hits and all(f.value_type != "interval" for f in hits)


def test_an_event_source_is_matched_by_a_whole_term_of_its_own_words():
    cat = _catalogue(_building())
    assert [f.key for f in cat.match_event_sources("Is CO2 higher during lectures?")] == [
        "event:TestLecture"
    ]
    assert [f.key for f in cat.match_event_sources("noise after the door events")] == [
        "event:TestDoorLog"
    ]
    assert cat.match_event_sources("Does CO2 rise after cleaning?") == [], "not an event source"
    assert cat.match_event_sources("the door was open") == [], "one word of a phrase is not it"


def test_a_building_that_records_no_events_has_no_event_source():
    cat = _catalogue(_building(with_records=False))
    assert cat.event_sources() == [] and cat.errors == ()


# ── 4. the compiler ─────────────────────────────────────────────────────────────────────

MODS = [
    ModalitySpec("co2", ["CO2_Level_Sensor"], sat={"unit": "ppm"}),
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"], sat={"unit": "persons"}),
    ModalitySpec("window_contact", ["Contact_Sensor"], sat={"unit": "binary"}),
]


def _facet(key, label, value_type, *, source="sensor", **kw):
    return facets.Facet(
        key=key,
        entity_type=kw.pop("entity_type", "space"),
        source_kind=source,
        label=label,
        value_type=value_type,
        status=kw.pop("status", "suitable"),
        coverage=kw.pop("coverage", 5),
        **kw,
    )


def _manual(extra=()) -> facets.FacetCatalogue:
    return facets.FacetCatalogue(
        [
            _facet(
                "sensor:co2",
                "co2",
                "number",
                modality="co2",
                unit="ppm",
                lay_terms=("stuffy", "air quality", "carbon dioxide"),
            ),
            _facet(
                "sensor:occupancy",
                "occupancy",
                "number",
                modality="occupancy",
                unit="persons",
                lay_terms=("people", "busy", "crowded"),
            ),
            _facet(
                "sensor:window_contact",
                "window contact",
                "boolean",
                modality="window_contact",
                lay_terms=("window open", "window closed"),
            ),
            _facet(
                "ttl:capacity",
                "room capacity (design occupancy)",
                "integer",
                source="ttl",
                unit="persons",
                lay_terms=("capacity",),
            ),
            _facet(
                "event:TestLecture",
                "lecture slot",
                "interval",
                source="event",
                lay_terms=("lecture", "lectures"),
                record_class="TestLecture",
                coverage=3,
                roles=ROLES_DAY,
                examples=(DAY, DAY),
                resolver="event_sources.events_query",
            ),
            _facet(
                "event:TestDoorLog",
                "door log entry",
                "interval",
                source="event",
                lay_terms=("door log", "door events"),
                record_class="TestDoorLog",
                coverage=1,
                roles=ROLES_INSTANT,
                examples=(DAY, DAY),
                resolver="event_sources.events_query",
            ),
            *extra,
        ]
    )


def _payload(relate, decision="relate", time=None):
    return json.dumps(
        {
            "decision": decision,
            "constraints": [],
            "facet_criteria": [],
            "relate": relate,
            "spatial": [],
            "time": time or {"basis": "now"},
            "unmapped": [],
            "inspect": [],
        }
    )


def _compile(question, *responses, catalogue=None):
    prompts: List[str] = []
    queue = list(responses)

    async def llm(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    out = _run(
        C.compile_query(question, MODS, llm, use_cache=False, catalogue=catalogue or _manual())
    )
    return out, prompts


DURING = "Is CO2 higher during lectures?"


def test_a_relation_to_recorded_events_compiles():
    out, prompts = _compile(
        DURING, _payload({"series": "co2", "relation": "during", "events": "event:TestLecture"})
    )
    assert out.signals == [] and out.is_executable(), out.signals
    assert out.decision == DecisionKind.RELATE and out.operation == "relate"
    spec = out.relate
    assert (spec.series, spec.relation, spec.events, spec.other_series) == (
        "sensor:co2",
        RelationKind.DURING,
        "event:TestLecture",
        None,
    )
    assert spec.lag_minutes is None and spec.window_start is None and spec.window_hours is None
    assert out.operation_facets() == ["sensor:co2", "event:TestLecture"]
    # the prompt lists the event sources in their own section, never among the criteria
    prompt = prompts[0]
    assert "- event:TestLecture | lecture slot | in 3 space(s) |" in prompt
    assert "relate: the question asks how ONE measured modality" in prompt
    assert "| event:TestLecture" not in prompt.split("Recorded events")[0]


def test_the_lag_and_the_window_are_read_from_the_question_never_from_the_model():
    question = "Did CO2 rise within 30 minutes after the door events yesterday?"
    out, _ = _compile(
        question,
        _payload(
            {
                "series": "co2",
                "relation": "after",
                "events": "door events",  # words naming exactly one source
                "lag_minutes": 600,
                "window_start": "1999-01-01 00:00:00",
            }
        ),
    )
    spec = out.relate
    assert out.signals == [] and spec.events == "event:TestDoorLog"
    assert (spec.lag_minutes, spec.lag_source) == (30.0, ThresholdSource.USER)
    expected = ri.calendar_day_bounds(question, ri.building_tz())
    assert (spec.window_start, spec.window_end, spec.window_label) == (
        expected[0],
        expected[1],
        "yesterday",
    )


def test_after_with_no_stated_length_reads_the_declared_default():
    out, _ = _compile(
        "Does CO2 go up after lectures?",
        _payload({"series": "co2", "relation": "after", "events": "event:TestLecture"}),
    )
    assert (out.relate.lag_minutes, out.relate.lag_source) == (
        C.DEFAULT_LAG_MINUTES,
        ThresholdSource.DEFAULT,
    )
    texts = [a.text for a in cp.build_assumptions(out)]
    assert any("'after' read as the 60 minutes after each event ends" in t for t in texts)
    assert "interpreted as current conditions" not in texts


def test_two_readings_and_a_yes_no_state_compile():
    moving, _ = _compile(
        "When occupancy goes up, does CO2 go up too?",
        _payload({"series": "co2", "relation": "co_movement", "other_series": "occupancy"}),
    )
    assert moving.signals == [] and moving.relate.relation == RelationKind.CO_MOVEMENT
    assert moving.relate.other_series == "sensor:occupancy"
    state, _ = _compile(
        "What happens to CO2 while the window is open?",
        _payload({"series": "co2", "other_series": "window_contact"}),  # relation left blank
    )
    assert state.signals == [] and state.relate.relation == RelationKind.DURING
    assert state.relate.other_series == "sensor:window_contact"


@pytest.mark.parametrize(
    "question,relate,needle",
    [
        (
            DURING,
            {"series": "ttl:capacity", "events": "event:TestLecture"},
            "not measured over time",
        ),
        (DURING, {"series": "window_contact", "events": "event:TestLecture"}, "yes/no state"),
        (DURING, {"series": "co2", "relation": "during", "events": "cleaning"}, "it does record"),
        (DURING, {"series": "co2", "relation": "during"}, "say what co2 is set against"),
        (
            DURING,
            {"series": "co2", "relation": "during", "other_series": "occupancy"},
            "measured figure; ask how the two move together",
        ),
        (
            DURING,
            {"series": "co2", "relation": "after", "other_series": "window_contact"},
            "'after' needs recorded events",
        ),
        (DURING, {"series": "co2", "relation": "co_movement"}, "needs the second reading"),
        (DURING, {"series": "co2", "relation": "co_movement", "other_series": "co2"}, "itself"),
        (
            DURING,
            {"series": "co2", "events": "event:TestLecture", "other_series": "occupancy"},
            "one relation at a time",
        ),
        (
            DURING,
            {"series": "co2", "relation": "causes", "events": "event:TestLecture"},
            "not a relation",
        ),
        (
            "Is CO2 higher during lectures this week than last week?",
            {"series": "co2", "relation": "during", "events": "event:TestLecture"},
            "names two periods",
        ),
        (
            "Is CO2 higher in the 48 hours after lectures?",
            {"series": "co2", "relation": "after", "events": "event:TestLecture"},
            "at most 24 hours",
        ),
    ],
)
def test_an_invalid_relation_is_a_signal_never_a_guess(question, relate, needle):
    out, _ = _compile(question, _payload(relate), _payload(relate))
    assert out.relate is None and not out.is_executable()
    assert any(needle in s.note for s in out.signals), out.signals


def test_a_forecast_is_never_a_relation():
    out, _ = _compile(
        "Will CO2 rise during tomorrow's lectures?",
        _payload(
            {"series": "co2", "relation": "during", "events": "event:TestLecture"},
            time={"basis": "forecast", "horizon_hours": 24, "phrase": "tomorrow"},
        ),
    )
    assert any("never forecast" in s.note for s in out.signals)


FROZEN_LOCAL = datetime(2026, 10, 7, 15, 30, 0)  # a Wednesday


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "Is CO2 higher during lectures yesterday?",
            ("2026-10-06 00:00:00", "2026-10-06 23:59:59", None, "yesterday"),
        ),
        (
            "Did noise rise after door events last week?",
            ("2026-09-28 00:00:00", "2026-10-04 23:59:59", None, "last week"),
        ),
        ("Does CO2 follow occupancy over the last 3 days?", (None, None, 72.0, "the last 3 days")),
        ("Is CO2 higher during lectures?", (None, None, None, "")),
    ],
)
def test_the_one_window_a_relation_reads(question, expected):
    start, end, hours, label, why = C._relation_window(question, None, FROZEN_LOCAL)
    assert why == "" and (start, end, hours, label) == expected


@pytest.mark.parametrize(
    "question,minutes",
    [
        ("within 30 minutes after each lecture", 30.0),
        ("in the two hours following a door event", 120.0),
        ("CO2 45 mins after the session", 45.0),
        ("in the hour after the lecture", 60.0),
        ("half an hour after lectures", 30.0),
        ("after lectures", None),
        ("over the last 3 days, after lectures", None),
    ],
)
def test_the_stated_length_of_after(question, minutes):
    assert C._stated_lag_minutes(question) == minutes


def test_the_v2_schema_covers_the_relation_parser_and_carries_no_lag_or_date():
    def reads(fn, receiver):
        keys = set()
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == receiver
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                keys.add(node.args[0].value)
        return keys

    props = C._cqir_schema(facets=True)["properties"]
    relate_keys = reads(C._relate_item, "raw")
    assert relate_keys and relate_keys <= set(props["relate"]["properties"])
    assert not {"lag_minutes", "window_start", "window_end", "start", "end", "dates"} & set(
        props["relate"]["properties"]
    )
    assert props["relate"]["properties"]["relation"]["enum"] == sorted(
        r.value for r in RelationKind
    )
    assert "relate" in props["decision"]["enum"]
    assert "relate" not in C._DECISIONS and DecisionKind.RELATE in V2_DECISIONS
    assert "relate" not in json.dumps(C._cqir_schema()), "the v1 schema never sees it"
    assert "relate" not in C._PROMPT and "{event_lines}" not in C._PROMPT


# ── 5. the fingerprint ──────────────────────────────────────────────────────────────────


def test_v1_plans_fingerprint_exactly_as_before():
    """The two values pinned against the unmodified v1 code (test_v2_compound_c1_facets)."""
    from tests.test_v2_compound_c1_facets import (
        V1_FINGERPRINT_FULL,
        V1_FINGERPRINT_MINIMAL,
        _v1_full,
    )

    assert _v1_full().plan_fingerprint() == V1_FINGERPRINT_FULL
    minimal = CQIR(
        decision=DecisionKind.SUPERLATIVE,
        constraints=[Constraint(modality="temperature", direction=Direction.MINIMIZE)],
        raw_query="coolest room",
    )
    assert minimal.plan_fingerprint() == V1_FINGERPRINT_MINIMAL
    assert _v1_full().model_copy(update={"relate": None}).plan_fingerprint() == V1_FINGERPRINT_FULL


def _relate_plan(**kw) -> CQIR:
    spec = dict(series="sensor:co2", relation=RelationKind.DURING, events="event:TestLecture")
    spec.update(kw)
    return CQIR(decision=DecisionKind.RELATE, relate=RelateSpec(**spec), raw_query="q")


def test_a_relation_fingerprint_is_deterministic_and_behavioural():
    base = _relate_plan()
    assert base.plan_fingerprint() == _relate_plan().plan_fingerprint(), "deterministic"
    assert base.operation == "relate" and base.is_executable()
    same = _relate_plan(source_phrase="during lectures", window_label="anything")
    assert same.plan_fingerprint() == base.plan_fingerprint(), "labels are presentation"
    after = _relate_plan(relation=RelationKind.AFTER, lag_minutes=60.0)
    stated = _relate_plan(
        relation=RelationKind.AFTER, lag_minutes=60.0, lag_source=ThresholdSource.USER
    )
    assert after.plan_fingerprint() == stated.plan_fingerprint(), "the same lag computes the same"
    differs = [
        after,
        _relate_plan(relation=RelationKind.AFTER, lag_minutes=30.0),
        _relate_plan(events="event:TestDoorLog"),
        _relate_plan(window_start="2026-10-06 00:00:00", window_end="2026-10-06 23:59:59"),
        _relate_plan(window_hours=72.0),
        _relate_plan(group_by=GroupBy.FLOOR),
        _relate_plan(
            relation=RelationKind.CO_MOVEMENT, events=None, other_series="sensor:occupancy"
        ),
    ]
    prints = [p.plan_fingerprint() for p in differs] + [base.plan_fingerprint()]
    assert len(set(prints)) == len(prints)


# ── 6. end to end: compile output -> admission -> execution -> dossier ────────────────────


def _schema(g):
    spaces = _run(CoverageAuditor(_sparql_json(g), MODALITIES).audit(NS))
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


WINDOW = {"window_start": f"{DAY} 00:00:00", "window_end": f"{DAY} 23:59:59", "window_label": DAY}


def _end_to_end(spec: RelateSpec, monkeypatch, raw="q"):
    monkeypatch.setattr(ri, "building_tz", lambda *_a, **_k: None)
    monkeypatch.setattr(ri, "store_now", lambda: FROZEN_UTC)
    g = _building()
    cat = _catalogue(g)
    ir = CQIR(decision=DecisionKind.RELATE, relate=spec, raw_query=raw)
    schema = _schema(g)
    admission = cs.validate(ir, schema, catalogue=cat)
    assert admission.verdict == cs.ADMIT, admission.reason
    store = _BucketStore()
    outcome = _run(
        execute(
            ir,
            admission,
            schema,
            adapter_getter=lambda key: store,
            catalogue=cat,
            sparql_exec=_sparql_json(g),
        )
    )
    dossier = build_dossier(ir, cp.decide(ir, admission), outcome, BID)
    text = render_answer(dossier) + "\n" + render_dossier_details(dossier)
    return outcome, dossier, text, store


def test_co2_during_recorded_lectures_end_to_end(monkeypatch):
    spec = RelateSpec(
        series="sensor:co2", relation=RelationKind.DURING, events="event:TestLecture", **WINDOW
    )
    outcome, dossier, text, store = _end_to_end(spec, monkeypatch, DURING)
    rel = outcome.relation
    o = rel.overall
    # L1: 12 quarter-hours in two lectures at 800, 84 at 500; L2: 8 at 900, 88 at 600
    assert (o.spaces, o.events, o.events_read, o.events_above) == (2, 3, 3, 3)
    assert (o.in_mean, o.in_buckets, o.in_readings) == (840.0, 20, 60)
    assert (o.out_mean, o.out_buckets, o.out_readings) == (551.16, 172, 516)
    assert (o.difference, o.percent, o.mean_space_difference) == (288.84, 52.41, 300.0)
    assert rel.not_compared == ["Room X1 (no co2 sensor)"], "its lecture happened unmeasured"
    assert any("1 cancelled lecture slot record(s) were left out" in n for n in rel.notes)
    assert any("2 other space(s) in scope with a co2 sensor have no" in n for n in rel.notes)
    assert all("GROUP BY `uuid`, b" in s and "/ 900) AS b" in s for s in store.statements)
    assert text.startswith(
        "**Co2 averaged 840 ppm during the 3 lecture slots in 2 spaces and 551.16 ppm "
        "outside them — 288.84 ppm higher (52.41%) during them.**"
    )
    assert "not that one causes the other" in text
    assert "Higher during them in 2 of the 2 spaces; the spaces' own differences average" in text
    assert "3 of the 3 lecture slots with readings had co2 above that space's own figure" in text
    assert "**Window (building time):** 2026-09-14 — Mon 14 Sep 00:00 to Mon 14 Sep 23:59." in text
    assert "| Room L1 | 2 | 800 ppm (12) | 500 ppm (84) | 300 ppm |" in text
    assert "interpreted as current conditions" not in text
    assert numeric_guard(text, dossier) == [], "every number in the answer is in the dossier"


def test_co2_in_the_half_hour_after_door_events_end_to_end(monkeypatch):
    spec = RelateSpec(
        series="sensor:co2",
        relation=RelationKind.AFTER,
        events="event:TestDoorLog",
        lag_minutes=30.0,
        lag_source=ThresholdSource.USER,
        **WINDOW,
    )
    outcome, dossier, text, _ = _end_to_end(spec, monkeypatch)
    o = outcome.relation.overall
    assert (o.spaces, o.events, o.in_mean, o.in_buckets, o.out_mean, o.out_buckets) == (
        1,
        2,
        700.0,
        4,
        450.0,
        92,
    )
    assert (o.difference, o.events_above) == (250.0, 2)
    assert text.startswith(
        "**In the 30 minutes after each of the 2 door log entries in 1 space, co2 averaged "
        "700 ppm, against 450 ppm at other times with no door log entries — 250 ppm higher "
        "(55.56%).**"
    )
    assert "a default" not in text, "the lag was stated"
    assert "of the 1 space" not in text, "one space's own difference is the pooled one"
    assert numeric_guard(text, dossier) == []


def test_co2_moving_with_occupancy_end_to_end(monkeypatch):
    spec = RelateSpec(
        series="sensor:co2",
        relation=RelationKind.CO_MOVEMENT,
        other_series="sensor:occupancy",
        **WINDOW,
    )
    outcome, dossier, text, store = _end_to_end(spec, monkeypatch)
    rel = outcome.relation
    o = rel.overall
    assert (o.spaces, o.pairs, o.pearson, o.change_pearson, o.spaces_positive) == (
        2,
        48,
        1.0,
        1.0,
        2,
    )
    assert rel.n_not_compared == 3
    assert "Room S1 (one of the two readings did not change)" in rel.not_compared
    assert "Room S2 (no occupancy sensor)" in rel.not_compared
    assert all("/ 3600) AS b" in s for s in store.statements), "hourly for a correlation"
    assert "rose and fell together: r = 1 over 48 periods" in text
    assert "not that one causes the other" in text
    assert numeric_guard(text, dossier) == []


def test_co2_while_a_window_reads_open_end_to_end(monkeypatch):
    spec = RelateSpec(
        series="sensor:co2",
        relation=RelationKind.DURING,
        other_series="sensor:window_contact",
        **WINDOW,
    )
    outcome, dossier, text, _ = _end_to_end(spec, monkeypatch)
    rel = outcome.relation
    o = rel.overall
    # L1: open 12:00-13:00 (4 quarter-hours at 500); closed 92 quarter-hours, 12 of them lectures
    assert rel.state and (o.spaces, o.in_mean, o.in_buckets, o.out_buckets) == (1, 500.0, 4, 92)
    assert (o.out_mean, o.difference) == (539.13, -39.13)
    assert "Room S1 (the state was never on for half a period)" in rel.not_compared
    assert "while window contact read on" in text and "39.13 ppm lower (7.26%) while on" in text
    assert numeric_guard(text, dossier) == []


def test_no_event_in_the_window_is_said_plainly(monkeypatch):
    spec = RelateSpec(
        series="sensor:co2",
        relation=RelationKind.DURING,
        events="event:TestLecture",
        window_start="2026-09-20 00:00:00",
        window_end="2026-09-20 23:59:59",
        window_label="that Sunday",
    )
    outcome, dossier, text, store = _end_to_end(spec, monkeypatch)
    assert outcome.relation.overall.spaces == 0 and store.statements == []
    assert "I couldn't work out how co2 relates to lecture slot" in text
    assert "No space had co2 readings both during and outside the lecture slots" in text
    assert numeric_guard(text, dossier) == []


def test_no_window_named_reads_a_declared_default_up_to_the_last_event(monkeypatch):
    spec = RelateSpec(series="sensor:co2", relation=RelationKind.DURING, events="event:TestLecture")
    outcome, dossier, text, _ = _end_to_end(spec, monkeypatch)
    rel = outcome.relation
    assert rel.window.label == "the 14 days up to the last lecture slot recorded here"
    assert rel.window.end == f"{DAY} 14:00:00", "it ends where the last event that happened ends"
    assert any("no period was named" in n for n in rel.notes)
    assert rel.overall.spaces == 2 and numeric_guard(text, dossier) == []


def test_the_bucketed_reduction_is_one_group_by_per_store_and_band():
    window = agl.Window("2026-09-14 00:00:00", "2026-09-14 23:59:59", "d")

    class Narrow:
        adapter_type = _Kind()
        table = "co2_data"

    statements = agl.bucket_statements(
        "mysql_narrow", Narrow(), ["co2-L1-0000", "co2-L2-0000"], window, 900, {}
    )
    assert len(statements) == 1 and statements[0].kind == "narrow_bucket"
    sql = statements[0].sql
    assert "FLOOR(TIMESTAMPDIFF(SECOND, '2026-09-14 00:00:00', `datetime`) / 900) AS b" in sql
    assert sql.endswith("GROUP BY `uuid`, b") and "LIMIT" not in sql
    parsed = agl.parse_buckets(statements[0], [{"uuid": "co2-L1-0000", "b": 3, "n": 3, "sm": 1500}])
    assert parsed == [agl.SensorBucket("co2-L1-0000", 3, 3, 1500.0)]
    with pytest.raises(ValueError):
        agl.bucket_statements("mysql_narrow", Narrow(), ["co2-L1-0000"], window, 0)


# ── 7. routing: the C5 signal ───────────────────────────────────────────────────────────

OPS = facets.FacetCatalogue(
    [
        *_manual(),
        _facet(
            "sensor:noise",
            "noise",
            "number",
            modality="noise",
            unit="dB",
            lay_terms=("quiet", "loud", "sound level"),
        ),
        _facet(
            "sensor:temperature",
            "temperature",
            "number",
            modality="temperature",
            unit="degC",
            lay_terms=("warm", "cold"),
        ),
        _facet(
            "sensor:tvoc",
            "tvoc",
            "number",
            modality="tvoc",
            unit="ppb",
            lay_terms=("voc", "voc levels"),
        ),
        _facet(
            "sensor:occupancy_status",
            "occupancy status",
            "boolean",
            modality="occupancy_status",
            lay_terms=("unoccupied", "empty", "vacant", "available", "free space"),
        ),
    ]
)


@pytest.mark.parametrize(
    "query,reason,keys",
    [
        ("Is CO2 higher during lectures?", "events", ("sensor:co2", "event:TestLecture")),
        ("Does noise go up after door events?", "events", ("sensor:noise", "event:TestDoorLog")),
        ("How does occupancy relate to CO2?", "series", ("sensor:co2", "sensor:occupancy")),
        ("When occupancy rises, does CO2 rise too?", "series", ("sensor:co2", "sensor:occupancy")),
        ("Is there a correlation between occupancy and CO2?", "series", None),
        ("CO2 rises while occupancy stays flat", "series", None),
        ("What happens to the temperature while the window is open?", "state", None),
        ("Is the temperature high while the room is unoccupied?", "state", None),
        # a measured reading the clause PREDICATES stands in for a state
        ("Is CO2 higher when it is busy?", "series", ("sensor:co2", "sensor:occupancy")),
    ],
)
def test_a_relation_is_recognised(query, reason, keys):
    sig = fr.operation_signal(query, OPS)
    assert sig is not None and (sig.shape, sig.reason) == ("C5", reason), (query, sig)
    if keys is not None:
        assert set(sig.facet_keys) == set(keys)


@pytest.mark.parametrize(
    "query",
    [
        "What is the CO2 level in room 2.01?",  # a lookup
        "Is CO2 higher during the day than at night?",  # a time of day is not a recorded event
        "What are the CO2 and temperature during the day?",  # two readings, no relation asked
        "Will CO2 rise during tomorrow's lectures?",  # a forecast
        "When is CO2 highest during lectures?",  # asks for a moment
        "Do VOC levels spike after cleaning?",  # cleaning is recorded, but not on the clock
        "Was CO2 higher this week than last week?",  # two periods: C4, v1's compare lane
        "Which lectures are on today?",  # an event lookup, no reading
        # the cue belongs to another clause than the event
        "Lectures run all day; what is the CO2 level during the afternoon?",
        # availability is not a sensed state, and "X-free" is no availability at all
        "Is there a quiet space I can use, and when is it officially available?",
        "Where can I take step-free breaks while keeping a quiet space available?",
        # quantities listed after "while" are not a state, and "when are ..." asks for a moment
        "Which room is best while still meeting reasonable CO2 and temperature needs?",
        "During our class, when are CO2 or temperature most likely to worsen?",
    ],
)
def test_what_is_not_a_relation_is_left_alone(query):
    sig = fr.operation_signal(query, OPS)
    assert sig is None or sig.shape != "C5", (query, sig)


@pytest.mark.parametrize(
    "query,shape,reason",
    [
        ("Which floor has the fewest people?", "C3", "additive"),
        ("Are any rooms over capacity?", "C2", "measured_vs_declared"),
        ("How evenly is the temperature spread across the floors?", "C3", "dispersion"),
    ],
)
def test_c3_and_c2_questions_keep_their_signal(query, shape, reason):
    sig = fr.operation_signal(query, OPS)
    assert sig is not None and (sig.shape, sig.reason) == (shape, reason)


def test_this_week_against_last_week_is_never_a_relation():
    for query in (
        "Was CO2 higher this week than last week?",
        "Was CO2 higher during lectures this week than last week?",
        "Is occupancy higher on weekdays than at weekends, and does CO2 follow it?",
    ):
        assert fr.relation_signal(query, OPS) is None, query


@pytest.fixture
def routing(monkeypatch):
    def _set(mode: str) -> None:
        monkeypatch.setattr(shared_config.settings, "ARBITER_V2_ROUTING", mode)
        monkeypatch.setattr(fr, "active_catalogue", lambda: OPS)

    return _set


def test_a_relation_leaves_the_series_lanes_and_nothing_else_does(routing):
    routing("live")

    def route(query, intent):
        state = {"intent": intent, "concepts": [], "entities": []}
        rc.apply_contract(query, state, stage="concept")
        return state["intent"]

    assert route("Does noise go up after door events?", "anomaly") == "deliberate"
    assert route("When occupancy rises, does CO2 rise too?", "trend") == "deliberate"
    assert route("Is CO2 higher during lectures?", "analytics") == "deliberate"
    # a C3 question in a series lane is not taken, nor a plain trend question
    assert route("Which floor has the fewest people?", "trend") == "trend"
    assert route("Is CO2 trending up this week?", "trend") == "trend"
    assert route("Does noise go up after door events?", "diagnosis") == "diagnosis"


def test_the_relation_modules_name_no_building():
    banned = re.compile(r"abacws|cardiff|bldg[1234]\b|buildsys\.org", re.IGNORECASE)
    for module in (evs, ops, fr):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert not banned.findall(text), module.__name__
