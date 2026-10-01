# -*- coding: utf-8 -*-
"""A point the ontology declares a STATUS must not be generated as a COUNT (BUG-1150).

``Booking_Status_Room1_25`` is typed ``brick:Occupancy_Status`` -- a ``brick:Status``, not a
``brick:Sensor`` -- and its own ``rdfs:label`` reads "Booking Status - Seminar Room 1.25
(available=0 / booked=1)". Its series nevertheless held values to 189.48 between 2026-08-22
and 2026-09-16. Someone asking how many people were in that room got a number, while the graph
said in the same breath that the point has two states.

THE CHECK IS A SUBCLASS CLOSURE, NOT A NAME
--------------------------------------------
"the point is called ``*_Status``" is the same failure one level down: a building literal
wearing a regex, wrong for the next building's naming, and blind to a status under another
name. The ontology already knows, so the ontology is asked.

AND IT IS ONE-DIRECTIONAL, WHICH WAS MEASURED RATHER THAN ASSUMED
------------------------------------------------------------------
``Status`` implies boolean; ``Sensor`` does NOT imply continuous. ``brick:Contact_Sensor`` is
a ``brick:Sensor`` and reads 0/1, and on the live building **479 points are exactly that**.
The converse rule would have reported 479 false positives on its first run.

The rule lives in ``scripts/audit_status_point_bands.py`` so it can be run against the live
stack; these tests exercise it offline against fixtures, and one live-marked test runs it
against the real graph when a building is active.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "audit_status_point_bands.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_status_point_bands", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("audit_status_point_bands", module)
    spec.loader.exec_module(module)
    return module


audit = _load()


# ── the band rule ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"lo": 0.0, "hi": 1.0, "dec": 0}, True),
        ({"lo": 0, "hi": 1, "dec": 0}, True),
        ({"lo": 0.0, "hi": 30.0, "dec": 0}, False),  # the occupancy COUNT band
        ({"lo": 0.0, "hi": 100.0, "dec": 0}, False),  # the door's band, live today
        ({"lo": 0.0, "hi": 1.0, "dec": 2}, False),  # 0.00..1.00 is not two states
        ({"value_col": "noise_db"}, None),  # declares no band at all
    ],
)
def test_the_band_rule_matches_the_generator_branch(entry, expected):
    """The generator branches on `dec == 0 and (hi - lo) <= 1.0`; so does this."""
    assert audit.band_is_boolean(entry) is expected


def test_a_declared_status_with_a_count_band_is_a_violation():
    """The exact BUG-1150 shape."""
    assert audit.violates(is_status=True, boolean_band=False) is True


def test_a_declared_status_with_a_boolean_band_is_fine():
    assert audit.violates(is_status=True, boolean_band=True) is False


def test_a_status_that_declares_no_band_is_not_failed():
    """245 points on this building declare none. Failing them would say nothing true."""
    assert audit.violates(is_status=True, boolean_band=None) is False


def test_a_boolean_sensor_is_not_a_violation():
    """`brick:Contact_Sensor` IS a Sensor and IS 0/1 — 479 of them on bldg1.

    A rule that also asserted "Sensor implies continuous" would fail all 479 on its first run.
    This is the guard against someone tightening the rule into uselessness.
    """
    assert audit.violates(is_status=False, boolean_band=True) is False


def test_a_continuous_sensor_is_not_a_violation():
    assert audit.violates(is_status=False, boolean_band=False) is False


# ── the roots are a subclass closure, not a name list ──────────────────────────────────


def test_the_rule_names_tbox_roots_and_not_point_names():
    """A design-contract check (#3: no building literals).

    The roots must be Brick TBox classes used as the head of `rdfs:subClassOf*`. If someone
    replaces them with instance-name fragments the audit becomes a denylist that rots.
    """
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "rdfs:subClassOf*" in src, "membership must be a subclass closure"
    assert set(audit.BOOLEAN_ROOTS) == {"Status", "Alarm", "Command"}
    for root in audit.BOOLEAN_ROOTS:
        assert "_" not in root and root[0].isupper(), f"{root!r} is not a Brick TBox class name"


# ── the map reader must not assume a shape ─────────────────────────────────────────────


def test_every_uuid_bearing_entry_is_found_whatever_the_map_shape():
    """The narrow map is uuid -> entry; the plant map nests entries under groups and roles.

    A shape assumption would silently skip a whole store, and a guard that skips a store
    reports "OK" for points it never looked at.
    """
    flat = {"a": {"uuid": "a", "lo": 0, "hi": 1, "dec": 0}}
    nested = {"groups": [{"roles": {"fan_status": {"uuid": "b", "lo": 0, "hi": 1, "dec": 0}}}]}
    found = {e["uuid"] for e in audit._walk(flat)} | {e["uuid"] for e in audit._walk(nested)}
    assert found == {"a", "b"}


def test_the_reader_tolerates_a_map_with_no_uuids_at_all():
    assert list(audit._walk({"table": "events", "rooms": ["Room0.01"]})) == []


# ── the live check ─────────────────────────────────────────────────────────────────────


@pytest.mark.live
def test_no_live_point_declared_a_status_is_generated_as_a_number():
    """Runs the audit against the real graph and the real publish maps.

    Marked `live` and skipped when no building is active, because the committed tree has none
    (Workflow rule 8). That means this assertion does NOT run in CI — the audit script is the
    thing to run by hand, and the offline tests above are what protect the rule itself.
    """
    input_dir = _REPO / "input"
    if not input_dir.is_dir():
        pytest.skip("no active building — run scripts/audit_status_point_bands.py by hand")
    try:
        points = audit.declared_points()
    except Exception as exc:  # pragma: no cover - a stack that is down is not a failure here
        pytest.skip(f"GraphDB not reachable: {exc}")
    bands = audit.publish_map_bands(input_dir)
    bad = [
        (name, label, bands[uuid])
        for uuid, name, label, is_status in points
        if uuid in bands and audit.violates(is_status, audit.band_is_boolean(bands[uuid]))
    ]
    assert not bad, f"{len(bad)} status point(s) generated as numbers: {bad[:5]}"
