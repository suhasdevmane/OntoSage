# -*- coding: utf-8 -*-
"""A people counter must not report more people than its room declares (BUG-1135).

WHAT WENT WRONG
---------------
The publisher bands every point by the QUANTITY it measures, and this building declares
exactly one band for people: `ontosage:OccupancyCount 0..30`. So all 256 room counters were
banded identically and each was driven to a diurnal peak at the top of that band, whatever
room it was in. Measured 2026-09-30 against the capacities the building itself declares:

    29 of the 41 rooms that carry both a capacity and a counter were over capacity;
    six eight-person rooms peaked at 30 in seven days -- 3.75x;
    and four forty-person rooms could never read above 30, so the same band
    UNDER-reports at the other end.

Nothing was broken in the code. The vocabulary had no place to say that THIS room's ceiling
differs from the measurand's, so nobody could have said it. `hbco:roomCapacity` has been a
triple on 42 spaces since BUG-896; the generator simply was not reading it.

WHAT THESE TESTS PIN
--------------------
1. A counter is capped at its own room's declared capacity -- downward AND upward.
2. A counter whose room declares nothing keeps the measurand band, unchanged.
3. A room too small to generate a COUNT is left alone rather than silently turned into a
   presence flag by the signal generator's binary branch.
4. The new ceiling records its basis, because a ceiling with no basis cannot be told apart
   from a certified fire limit -- and these capacities are declared estimates.
5. The point-to-space relation is bound with a VARIABLE predicate. This building spells it
   three ways and a query naming one loses two thirds of the rooms in silence (lesson #161).
6. Two disagreeing capacities resolve to the LOWER one, as BUG-896 ruled for the same
   reason: exceeding a recorded limit is the dangerous direction.
7. A graph that answers nothing leaves every band as it was and never fails a boot.

Offline: no GraphDB, no MySQL, no model.
"""

from __future__ import annotations

import inspect
import io
import json
from contextlib import contextmanager
from typing import Any, Dict, List

import pytest

from orchestrator.services import publisher_map

pytestmark = pytest.mark.unit


def _fake_urlopen(rows: List[Dict[str, Any]]):
    """Stand in for the SPARQL JSON the ceiling query reads."""
    payload = json.dumps({"results": {"bindings": rows}}).encode("utf-8")

    @contextmanager
    def _open(_req, timeout=None):
        yield io.BytesIO(payload)

    return _open


def _binding(uuid: str, capacity: float) -> Dict[str, Any]:
    return {
        "uuid": {"value": uuid},
        "capacity": {"value": str(capacity)},
    }


def _counter(uuid: str, hi: float = 30.0) -> Dict[str, Any]:
    """A point already carrying the measurand band `_attach_bands` gives it."""
    return {"uuid": uuid, "table": "occupancy_data", "lo": 0.0, "hi": hi, "dec": 0}


@pytest.fixture
def patched(monkeypatch):
    def _apply(points, rows):
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(rows))
        return publisher_map._apply_declared_room_ceilings(points)

    return _apply


# -- property 1: the room's own capacity wins, in both directions --------------


def test_a_small_room_no_longer_reports_thirty(patched):
    points = {"u-small": _counter("u-small")}
    applied = patched(points, [_binding("u-small", 8)])
    assert applied == 1
    assert points["u-small"]["hi"] == 8.0, (
        "an eight-person room was still banded to 30 -- this is the defect, and it peaked "
        "at 3.75x capacity for a week"
    )
    assert points["u-small"]["lo"] == 0.0, "the floor of the band is not this rule's business"


def test_a_room_declaring_MORE_than_the_measurand_band_does_not_raise_it(patched):
    """The obvious rule is `hi = capacity`, and it is wrong in one direction.

    A dry run on 2026-09-30 showed it would raise eleven ceilings, Room2.15 from 30 to 40 —
    and BUG-1137 measures that room at 7.83 m², so 40 people is 0.20 m² each. Lowering an
    estimated capacity under-reports; raising it manufactures a crowd the room cannot hold.
    The cost of this choice is that those eleven stay under-reported, which is stated in the
    module and is the lesser failure.
    """
    points = {"u-big": _counter("u-big")}
    assert patched(points, [_binding("u-big", 50)]) == 0
    assert points["u-big"]["hi"] == 30.0
    assert "hi_basis" not in points["u-big"]


def test_a_capacity_equal_to_the_band_changes_nothing(patched):
    points = {"u-same": _counter("u-same")}
    assert patched(points, [_binding("u-same", 30)]) == 0
    assert points["u-same"]["hi"] == 30.0


# -- property 2: a point the rule cannot reach is left exactly as it was -------


def test_a_counter_whose_room_declares_nothing_keeps_the_measurand_band(patched):
    """This narrows the defect; it does not close it. Most counters have no capacity."""
    points = {"u-known": _counter("u-known"), "u-unknown": _counter("u-unknown")}
    patched(points, [_binding("u-known", 12)])
    assert points["u-unknown"]["hi"] == 30.0
    assert "hi_basis" not in points["u-unknown"]


def test_a_capacity_for_a_point_this_map_does_not_hold_is_ignored(patched):
    points = {"u-known": _counter("u-known")}
    assert patched(points, [_binding("u-elsewhere", 8)]) == 0


# -- property 3: a count must not quietly become a presence flag ---------------


def test_a_room_too_small_to_generate_as_a_count_is_left_alone(patched):
    """`sensor_signal.next_value` treats dec==0 with a span <= 1 as a BINARY point that
    holds and flips. Capping a counter at 1 would stop it being a count at all, and the
    modality would change shape with nothing said."""
    points = {"u-tiny": _counter("u-tiny")}
    assert patched(points, [_binding("u-tiny", 1)]) == 0
    assert points["u-tiny"]["hi"] == 30.0, "a one-person room silently became a presence flag"


def test_the_binary_trap_is_named_where_the_threshold_is_set():
    source = inspect.getsource(publisher_map)
    assert "_MIN_COUNTABLE_SPAN" in source
    assert publisher_map._MIN_COUNTABLE_SPAN >= 2.0


# -- property 4: the new ceiling says where it came from -----------------------


def test_the_new_ceiling_records_its_basis(patched):
    """20 of the 42 declared capacities are themselves implausible (BUG-1137), and every one
    carries `ontosage:capacityBasis` saying it is estimated and not certified. A band that
    inherits that must say so, or it reads as a fire limit."""
    points = {"u": _counter("u")}
    patched(points, [_binding("u", 8)])
    basis = points["u"].get("hi_basis", "")
    assert "roomCapacity" in basis
    assert "not certified" in basis


# -- properties 5 and 6: the query itself ------------------------------------


def test_the_location_relation_is_bound_with_a_variable():
    """`brick:hasLocation` (41), `rec:locatedIn` (41) and `brick:isPartOf` (12) all spell it
    in this one building. Naming any single one of them loses rooms in silence."""
    query = publisher_map._ROOM_CEILING_QUERY
    assert "?sensor ?" in query, "the location predicate must be a variable, not a name"
    for named in ("brick:hasLocation", "rec:locatedIn", "brick:isPartOf"):
        assert named not in query, (
            f"{named} is named in the query; the next spelling of the same relation will be "
            f"dropped without a word"
        )
    assert "hbco:roomCapacity" in query, "reaching a declared capacity is what makes a match"


def test_two_disagreeing_capacities_resolve_to_the_lower_one():
    assert "MIN(?cap)" in publisher_map._ROOM_CEILING_QUERY


def test_the_ceiling_is_the_minimum_of_the_two_sources(patched):
    """Stated as the property rather than as two separate cases, because it is the property
    that makes the rule safe: neither source can make a reading more crowded than it already
    allows."""
    for capacity, band, expected in ((8, 30.0, 8.0), (30, 30.0, 30.0), (50, 30.0, 30.0)):
        points = {"u": _counter("u", hi=band)}
        patched(points, [_binding("u", capacity)])
        assert points["u"]["hi"] == expected == min(float(capacity), band)


def test_only_a_people_counter_is_capped():
    """A presence flag shares the table and must keep its 0..1 band."""
    assert "brick:Occupancy_Count_Sensor" in publisher_map._ROOM_CEILING_QUERY


# -- property 7: a silent graph must not fail a boot ---------------------------


def test_a_graph_that_cannot_answer_leaves_every_band_alone(monkeypatch):
    import urllib.request

    def _boom(_req, timeout=None):
        raise OSError("graphdb is still warming up")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    points = {"u": _counter("u")}
    assert publisher_map._apply_declared_room_ceilings(points) == 0
    assert points["u"]["hi"] == 30.0


def test_the_rebuild_applies_the_ceiling_after_the_measurand_band():
    """Order matters: the ceiling REPLACES the band, so a later `_attach_bands` would undo
    it."""
    source = inspect.getsource(publisher_map._rebuild)
    assert source.index("_attach_bands") < source.index("_apply_declared_room_ceilings")


# -- a band must say when it took effect (CAVEAT-1131) ------------------------
#
# 1,544,386 stored rows sit outside the band their point declares and none was written after
# 2026-09-16. Part of that is a band authored AFTER the readings and applied from that moment
# with no migration, and part is a writer producing values it declares impossible. With no
# valid-from date on the band the two are the same number, and an audit cannot tell a schema
# change from a defect.


def _stamp(points, before):
    return publisher_map._stamp_band_provenance(points, before)


def test_a_band_this_code_writes_carries_the_day_it_took_effect():
    from datetime import datetime, timezone

    points = {"u": _counter("u")}
    assert _stamp(points, {}) == 1
    assert points["u"]["band_from"] == datetime.now(timezone.utc).date().isoformat()


def test_a_band_that_was_already_there_is_dated_UNKNOWN_not_today():
    """Writing today's date onto a band nobody dated would assert something unmeasured. The
    honest record is that it is not known."""
    points = {"u": _counter("u")}
    before = {"u": dict(_counter("u"))}  # banded, never stamped
    assert _stamp(points, before) == 0
    assert points["u"]["band_from"] == publisher_map._BAND_PREDATES_STAMP
    assert not points["u"]["band_from"][:4].isdigit()


def test_an_unchanged_band_keeps_its_date_so_the_map_is_not_rewritten_every_boot():
    points = {"u": _counter("u")}
    before = {"u": dict(_counter("u"), band_from="2026-09-18")}
    assert _stamp(points, before) == 0
    assert points["u"]["band_from"] == "2026-09-18"
    assert points == before, "an unchanged map must compare equal or it is written every boot"


def test_a_band_that_changes_is_redated_even_if_it_had_an_older_date():
    """This is the case the room ceiling creates: a band that narrows today is valid from
    today, and every reading before it was written under the wider one."""
    from datetime import datetime, timezone

    points = {"u": _counter("u", hi=8.0)}
    before = {"u": dict(_counter("u", hi=30.0), band_from="2026-09-18")}
    assert _stamp(points, before) == 1
    assert points["u"]["band_from"] == datetime.now(timezone.utc).date().isoformat()


def test_a_point_with_no_band_is_not_given_a_date():
    points = {"u": {"uuid": "u", "table": "noise_data"}}
    assert _stamp(points, {}) == 0
    assert "band_from" not in points["u"]


def test_the_stamp_has_a_reader():
    """A marker on the bus with no reader is not a disclosure (lesson #157)."""
    from pathlib import Path

    audit = Path("scripts/audit_declared_band_conformance.py").read_text(encoding="utf-8")
    assert "band_from" in audit, "nothing reads the stamp, so it discloses nothing"
    assert "_valid_from" in audit
