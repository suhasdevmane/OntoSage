# -*- coding: utf-8 -*-
"""Placeholder alarm / door-access / anomaly records and derived room capacity.

Offline: every case builds its own small building from fixtures, so nothing here needs a graph,
a database or an active building -- the state CI and a fresh clone run in.

The properties pinned are the ones the stakeholder questions are ABOUT: an alarm's lifecycle
ordering, an anomaly's value against its declared band, access events that never name a person,
and a capacity that exists only where the floor plan gives a basis for one.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from scripts import provision_event_and_capacity_data as prov

pytestmark = pytest.mark.unit

NS = "http://example.org/b#"
O = Namespace(prov.ONTOSAGE)  # noqa: E741 - the prefix name used throughout this repo
HBCO = Namespace(prov.HBCO)
BID = "testbldg"
ANCHOR = datetime(2026, 9, 17, 18, 0)
HOURS = prov.parse_opening_hours("Mon-Fri 07:00-21:00; Sat 09:00-17:00; Sun closed")
ROLES = {"Research staff": 4, "External contractor": 3, "Registered visitor": 1, "Cleaning": 2}


def _eq(local, classes, label=None, space="Floor1"):
    return prov.Equipment(
        iri=NS + local,
        label=label or local.replace("_", " "),
        classes=frozenset(classes),
        space_iri=NS + space if space else None,
    )


def _equipment():
    out = [
        _eq("AHU_1", {"Air_Handling_Unit", "AHU", "HVAC_Equipment", "Equipment"}),
        _eq("Boiler_1", {"Boiler", "HVAC_Equipment", "Equipment"}, space="Plant"),
        _eq("Lift_1", {"Elevator", "Equipment"}),
        _eq("Panel_1", {"Fire_Alarm_Control_Panel", "Fire_Safety_Equipment", "Equipment"}),
        _eq("Luminaire_1", {"Luminaire", "Lighting_Equipment", "Equipment"}),  # no family
        _eq("Reader_1", {"Access_Reader", "Access_Control_Equipment", "Equipment"}),
    ]
    out += [_eq(f"Pump_{i}", {"Pump", "Equipment"}, space=None) for i in range(24)]
    return out


def _openings():
    return [
        _eq("Reader_Main", {"Access_Reader", "Access_Control_Equipment"}, space="Room0.01"),
        _eq("Reader_F2", {"Access_Reader", "Access_Control_Equipment"}, space="Floor2"),
        _eq("Turnstile", {"Access_Control_Equipment"}, space=None),
    ]


def _points():
    return [
        prov.BandedPoint(
            NS + "CO2_1", "CO2 room 1", "CarbonDioxide", 400, 1200, 350, 40000, NS + "R1"
        ),
        prov.BandedPoint(NS + "T_1", "Temp room 1", "AirTemperature", 18, 28, -30, 70, NS + "R1"),
        prov.BandedPoint(NS + "RH_1", "RH room 1", "RelativeHumidity", 30, 70, 0, 100, None),
        prov.BandedPoint(NS + "Lvl_1", "Door state", "BinaryState", 0, 1, 0, 1, NS + "R1"),
    ]


def _alarms(anchor=ANCHOR, weeks=10):
    return prov.alarm_events(BID, _equipment(), anchor, weeks, HOURS)


def _access(anchor=ANCHOR, weeks=10):
    return prov.access_events(BID, _openings(), ROLES, anchor, weeks, HOURS)


def _anomalies(anchor=ANCHOR, weeks=10):
    return prov.anomaly_events(BID, _points() * 1, anchor, weeks)


def _parse(text: str) -> Graph:
    g = Graph()
    g.parse(data=text, format="turtle")
    return g


# ── determinism ─────────────────────────────────────────────────────────────────────────────


def test_same_anchor_renders_byte_identical_files():
    first = (
        prov.render_alarm_ttl(_alarms(), NS, ANCHOR)
        + prov.render_access_ttl(_access(), NS, ANCHOR)
        + prov.render_anomaly_ttl(_anomalies(), NS, ANCHOR)
    )
    second = (
        prov.render_alarm_ttl(_alarms(), NS, ANCHOR)
        + prov.render_access_ttl(_access(), NS, ANCHOR)
        + prov.render_anomaly_ttl(_anomalies(), NS, ANCHOR)
    )
    assert first == second


def test_a_later_anchor_keeps_every_earlier_record_id():
    """Re-running tomorrow must update statuses, not mint new identities for old events."""
    later = ANCHOR + timedelta(days=1)
    for build in (_alarms, _access):
        earlier_ids = {e["uuid"] for e in build(ANCHOR, weeks=4)}
        later_ids = {e["uuid"] for e in build(later, weeks=4)}
        # The later window starts a day later, so only events after that start must survive.
        cutoff = later - timedelta(weeks=4)
        kept = {
            e["uuid"]
            for e in build(ANCHOR, weeks=4)
            if e.get("raised_at", e.get("start")) >= cutoff
        }
        assert earlier_ids and kept <= later_ids


def test_different_buildings_get_different_ids():
    a = {e["uuid"] for e in _alarms()}
    b = {e["uuid"] for e in prov.alarm_events("other", _equipment(), ANCHOR, 10, HOURS)}
    assert a and not (a & b)


# ── parsing, uniqueness, provenance ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "render,build,cls",
    [
        (prov.render_alarm_ttl, _alarms, "AlarmEvent"),
        (prov.render_access_ttl, _access, "AccessEvent"),
        (prov.render_anomaly_ttl, _anomalies, "AnomalyEvent"),
    ],
)
def test_every_emitted_record_parses_is_unique_and_declares_itself_simulated(render, build, cls):
    events = build()
    assert events, "fixture produced no events; the assertions below would pass on nothing"
    g = _parse(render(events, NS, ANCHOR))
    subjects = set(g.subjects(RDF.type, O[cls]))
    assert len(subjects) == len(events)
    record_ids = [str(o) for s in subjects for o in g.objects(s, O.recordId)]
    assert len(record_ids) == len(set(record_ids)) == len(events)
    for s in subjects:
        values = list(g.objects(s, O.isSimulated))
        assert values == [Literal(True)], f"{s} does not declare isSimulated true: {values}"
        assert values[0].datatype == XSD.boolean


@pytest.mark.parametrize(
    "render, build, cls",
    [
        (prov.render_alarm_ttl, _alarms, "AlarmEvent"),
        (prov.render_access_ttl, _access, "AccessEvent"),
        (prov.render_anomaly_ttl, _anomalies, "AnomalyEvent"),
    ],
)
def test_generated_records_do_not_borrow_the_maintenance_issue_priority(render, build, cls):
    """Records use their own priority property, not MaintenanceIssue's (BUG-695)."""
    g = _parse(render(build(), NS, ANCHOR))
    assert (None, O.priority, None) not in g


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MODELLING DEBT, NOT A LIVE DEFECT (BUG-695, measured 2026-09-17): effectiveFrom/"
        "effectiveTo are declared with rdfs:domain ConfigurationPeriod and aboutEquipment with "
        "domain Capability, yet all registers use them. The bldg repository's rdfsplus-optimized "
        "ruleset does NOT infer types from rdfs:domain - 1,321 subjects use effectiveFrom without "
        "being ConfigurationPeriod and the class still counts 2,175 with and without inference - "
        "so nothing is mis-typed today. A deployment on a full RDFS ruleset would mis-type every "
        "record. Widen those domains in the OCBV schema; this test then passes and strict xfail "
        "fails, which is the reminder to remove this marker."
    ),
)
@pytest.mark.parametrize(
    "render, build, cls",
    [
        (prov.render_alarm_ttl, _alarms, "AlarmEvent"),
        (prov.render_access_ttl, _access, "AccessEvent"),
        (prov.render_anomaly_ttl, _anomalies, "AnomalyEvent"),
    ],
)
def test_no_emitted_predicate_would_infer_the_record_into_another_class(render, build, cls):
    """Under a FULL RDFS ruleset a domain axiom re-types every subject that uses the predicate.

    Every ontosage: predicate emitted on a record should declare a domain the record's own
    class belongs to (itself or an ancestor) in the committed OCBV schema, so the data stays
    correctly typed whichever ruleset a deployment runs.
    """
    from pathlib import Path

    from rdflib.namespace import RDFS

    schema = Graph()
    schema.parse(
        Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl", format="turtle"
    )

    def ancestors(c, seen=None):
        seen = seen if seen is not None else set()
        if c in seen:
            return seen
        seen.add(c)
        for parent in schema.objects(c, RDFS.subClassOf):
            ancestors(parent, seen)
        return seen

    allowed = ancestors(O[cls])
    g = _parse(render(build(), NS, ANCHOR))
    wrong = {}
    for _s, p, _o in g:
        if not str(p).startswith(str(O)):
            continue
        for domain in schema.objects(p, RDFS.domain):
            if domain not in allowed:
                wrong[str(p).rsplit("#", 1)[-1]] = str(domain).rsplit("#", 1)[-1]
    assert not wrong, f"{cls} carries predicates whose domain would re-type it: {wrong}"
    assert (None, O.priority, None) not in g, "ontosage:priority re-types a record as MaintenanceIssue"


def test_the_generated_header_is_the_marker_the_provenance_test_reads():
    text = prov.render_alarm_ttl(_alarms(), NS, ANCHOR)
    assert "GENERATED by scripts/" in text[:2000]
    assert "@prefix bldg: <" + NS + ">" in text


def test_no_user_visible_literal_calls_the_data_synthetic():
    rendered = [
        prov.render_alarm_ttl(_alarms(), NS, ANCHOR),
        prov.render_access_ttl(_access(), NS, ANCHOR),
        prov.render_anomaly_ttl(_anomalies(), NS, ANCHOR),
        prov.render_capacity_ttl(*prov.capacity_estimates(_rooms()), NS, ANCHOR),
    ]
    for text in rendered:
        assert prov._visible_word_violations(text) == []


def test_the_visible_word_check_catches_a_violation_and_ignores_comments():
    """Negative control: a checker that never fires proves nothing."""
    assert prov._visible_word_violations('bldg:x rdfs:label "Simulated alarm" .')
    assert not prov._visible_word_violations("# this file is simulated\nbldg:x a bldg:Y .")


# ── alarms ──────────────────────────────────────────────────────────────────────────────────


def test_alarm_lifecycle_never_runs_backwards():
    events = _alarms()
    assert events
    for e in events:
        raised, ack, clear = e["raised_at"], e["acknowledged_at"], e["cleared_at"]
        assert raised <= ANCHOR
        if ack is not None:
            assert raised <= ack <= ANCHOR
        if clear is not None:
            assert ack is not None and raised <= ack <= clear <= ANCHOR


def test_alarm_status_agrees_with_its_timestamps():
    by_status = Counter()
    for e in _alarms():
        by_status[e["status"]] += 1
        if e["status"] == "detected":
            assert e["acknowledged_at"] is None and e["cleared_at"] is None
        elif e["status"] == "open":
            assert e["acknowledged_at"] is not None and e["cleared_at"] is None
        else:
            assert e["status"] == "resolved"
            assert e["acknowledged_at"] is not None and e["cleared_at"] is not None
    assert by_status["resolved"] > 0


def test_some_recent_alarms_are_left_unacknowledged():
    """'Which alarms are still unacknowledged?' needs a non-empty answer somewhere."""
    detected = [e for e in _alarms() if e["status"] == "detected"]
    assert detected


def test_alarms_cluster_on_a_few_assets():
    counts = Counter(e["equipment_iri"] for e in _alarms())
    ranked = sorted(counts.values(), reverse=True)
    top = ranked[: max(1, len(ranked) // 5)]
    assert sum(top) > 0.4 * sum(ranked), f"alarms spread evenly: {ranked}"


def test_equipment_without_an_alarm_family_raises_nothing():
    emitted = {e["equipment_iri"] for e in _alarms()}
    assert NS + "Luminaire_1" not in emitted
    assert NS + "Reader_1" not in emitted, "access control belongs to the access-event file"


def test_acknowledgement_is_slower_outside_opening_hours():
    staffed, unstaffed = [], []
    for e in _alarms(weeks=20):
        if e["acknowledged_at"] is None:
            continue
        delay = (e["acknowledged_at"] - e["raised_at"]).total_seconds()
        (staffed if prov._is_open(HOURS, e["raised_at"]) else unstaffed).append(delay)
    assert staffed and unstaffed
    median = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
    assert median(unstaffed) > median(staffed)


# ── access events: role templates, never people ─────────────────────────────────────────────

_ALLOWED_ACCESS_PREDICATES = {
    RDF.type,
    URIRef("http://www.w3.org/2000/01/rdf-schema#label"),
    O.recordId,
    O.accessEventKind,
    O.aboutEquipment,
    O.aboutSpace,
    O.presentedRole,
    O.denialReason,
    O.effectiveFrom,
    O.effectiveTo,
    O.recordStatus,
    O.isSimulated,
}

#: Shapes a personal identifier would take in a literal.
_PERSONAL_RE = re.compile(
    r"@[a-z0-9.-]+\.[a-z]{2,}|\b(?:card|badge|staff|student|employee|person)\s*(?:no|number|id)\b"
    r"|\b(?:mr|mrs|ms|dr)\.?\s+[a-z]+|\b\d{6,}\b",
    re.IGNORECASE,
)


def _access_graph():
    return _parse(prov.render_access_ttl(_access(), NS, ANCHOR))


def test_access_events_carry_only_role_level_predicates():
    g = _access_graph()
    predicates = set(g.predicates())
    assert predicates <= _ALLOWED_ACCESS_PREDICATES, predicates - _ALLOWED_ACCESS_PREDICATES


def test_a_presented_role_is_always_a_declared_role_template():
    g = _access_graph()
    roles = {str(o) for o in g.objects(None, O.presentedRole)}
    assert roles and roles <= set(ROLES)


def test_no_literal_in_access_events_looks_like_a_personal_identifier():
    g = _access_graph()
    for _s, p, o in g:
        if p == O.recordId:
            # The EVENT's own identifier, and nothing else: a fixed prefix and eight hex digits
            # of its uuid5. Pinned exactly, so it cannot drift into a credential-shaped number.
            assert re.fullmatch(r"ACC-[0-9A-F]{8}", str(o)), o
            continue
        if isinstance(o, Literal) and o.datatype != XSD.dateTime:
            assert not _PERSONAL_RE.search(str(o)), f"personal-looking literal: {o!r}"


def test_the_personal_identifier_check_would_fire():
    """Negative control for the check above."""
    for sample in ("Card number 12345678", "j.smith@example.ac.uk", "Dr Jones", "badge id"):
        assert _PERSONAL_RE.search(sample)


def test_a_forced_door_carries_no_role_because_no_credential_was_presented():
    events = _access(weeks=30)
    forced = [e for e in events if e["kind"] == "forced_door"]
    assert forced
    assert all(e["role"] is None for e in forced)
    assert all(e["role"] in ROLES for e in events if e["kind"] != "forced_door")


def test_access_events_are_weighted_to_opening_hours_and_well_ordered():
    events = _access()
    kinds = Counter(e["kind"] for e in events)
    assert kinds["access_denied"] > kinds["held_open"] > kinds["forced_door"] >= 0
    routine = [e for e in events if e["kind"] != "forced_door"]
    in_hours = sum(1 for e in routine if prov._is_open(HOURS, e["start"]))
    assert in_hours > 0.6 * len(routine)
    for e in events:
        assert e["start"] <= e["end"] <= ANCHOR
        if e["kind"] == "access_denied":
            assert e["end"] == e["start"]


def test_no_roles_declared_means_no_role_is_invented():
    events = prov.access_events(BID, _openings(), {}, ANCHOR, 10, HOURS)
    assert events and all(e["role"] is None for e in events)


# ── anomalies ───────────────────────────────────────────────────────────────────────────────


def test_anomaly_values_are_consistent_with_the_points_declared_band():
    events = _anomalies(weeks=30)
    assert events
    for e in events:
        assert e["typical_lo"] <= e["baseline"] <= e["typical_hi"]
        assert e["physical_lo"] <= e["observed"] <= e["physical_hi"]
        inside = e["typical_lo"] <= e["observed"] <= e["typical_hi"]
        if e["detector"] == "stuck":
            assert inside
        else:
            assert not inside, f"out-of-band detector with an in-band value: {e}"
        if e["end"] is not None:
            assert e["start"] <= e["end"] <= ANCHOR


def test_a_point_whose_physical_band_leaves_no_room_raises_no_out_of_band_episode():
    events = [e for e in _anomalies(weeks=52) if e["point_iri"] == NS + "Lvl_1"]
    assert all(e["detector"] == "stuck" for e in events)


def test_anomaly_output_is_opt_in():
    """Held AnomalyEvent graph instances would take anomaly questions from the events store."""
    assert "anomaly" not in prov.output_names(BID, include_anomaly=False)
    assert "anomaly" in prov.output_names(BID, include_anomaly=True)
    assert prov.build_parser().parse_args([]).include_anomaly is False


def test_output_names_are_not_mistaken_for_shared_schema():
    from orchestrator.services.ttl_uploader import _looks_like_schema

    for name in prov.output_names("bldg1", include_anomaly=True).values():
        assert not _looks_like_schema(name), name


# ── room capacity ───────────────────────────────────────────────────────────────────────────


def _room(local, classes, area, has_capacity=False, ambiguous=False):
    return prov.Room(NS + local, frozenset(classes), area, has_capacity, ambiguous)


def _rooms():
    return [
        _room("Office_A", {"Office", "Room"}, 42.0),
        _room("Meet_A", {"Conference_Room", "Room"}, 21.0),
        _room("Lab_A", {"Laboratory", "Room"}, 95.0),
        _room("Office_NoArea", {"Office", "Room"}, None),
        _room("Office_HasCap", {"Office", "Room"}, 40.0, has_capacity=True),
        _room("Store_A", {"Storage_Room", "Room"}, 30.0),
        _room("Generic_A", {"Room"}, 30.0),
        _room("Office_Ambig", {"Office", "Room"}, 30.0, ambiguous=True),
        _room("Office_Tiny", {"Office", "Room"}, 3.0),
    ]


def test_capacity_only_where_an_area_and_a_typed_basis_exist():
    estimates, skipped = prov.capacity_estimates(_rooms())
    got = {e["room_iri"].rsplit("#", 1)[-1]: e["capacity"] for e in estimates}
    assert got == {"Office_A": 4, "Meet_A": 10, "Lab_A": 9}
    assert skipped == Counter(
        {
            "no floor-plan area": 1,
            "already has a capacity": 1,
            "type not laid out for occupants": 1,
            "no density basis for its type": 1,
            "floor plans disagree on its area": 1,
            "too small for one person at the stated density": 1,
        }
    )


def test_every_capacity_states_its_basis_and_marks_no_room_simulated():
    estimates, skipped = prov.capacity_estimates(_rooms())
    g = _parse(prov.render_capacity_ttl(estimates, skipped, NS, ANCHOR))
    rooms = set(g.subjects(HBCO.roomCapacity, None))
    assert len(rooms) == len(estimates)
    for room in rooms:
        (cap,) = list(g.objects(room, HBCO.roomCapacity))
        assert cap.datatype == XSD.integer and int(cap) >= 1
        (basis,) = [str(b) for b in g.objects(room, O.capacityBasis)]
        assert basis.startswith("Estimated, not certified") and "m2" in basis
    assert not list(g.subjects(O.isSimulated, None))


def test_manifest_areas_ignore_other_namespaces_and_flag_disagreement(tmp_path):
    import json

    (tmp_path / "f1.manifest.json").write_text(
        json.dumps(
            {
                "spaces": [
                    {"ontology_iri": NS + "R1", "area_m2": 10.0},
                    {"ontology_iri": NS + "R2", "area_m2": 12.0},
                    {"ontology_iri": "http://elsewhere/x#R3", "area_m2": 9.0},
                    {"ontology_iri": NS + "R4", "area_m2": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "f2.manifest.json").write_text(
        json.dumps({"spaces": [{"ontology_iri": NS + "R2", "area_m2": 30.0}]}), encoding="utf-8"
    )
    areas, ambiguous = prov.manifest_areas([str(p) for p in tmp_path.glob("*.manifest.json")], NS)
    assert areas == {NS + "R1": 10.0}
    assert ambiguous == {NS + "R2"}


# ── references resolve, as the boot validator reads them ────────────────────────────────────


def test_rendered_references_pass_the_dangling_reference_validator(tmp_path):
    from orchestrator.services.input_validators import validate_dangling_references

    declared = {e.iri for e in _equipment() + _openings()} | {
        NS + x for x in ("Floor1", "Floor2", "Plant", "Room0.01", "R1")
    }
    decl = ["@prefix bldg: <" + NS + "> .", "@prefix brick: <" + prov.BRICK + "> .", ""]
    decl += [f"bldg:{iri.rsplit('#', 1)[-1]} a brick:Location ." for iri in sorted(declared)]
    decl += [f"bldg:{p.iri.rsplit('#', 1)[-1]} a brick:Point ." for p in _points()]
    (tmp_path / "decl.ttl").write_text("\n".join(decl) + "\n", encoding="utf-8")
    (tmp_path / "a.ttl").write_text(prov.render_alarm_ttl(_alarms(), NS, ANCHOR), encoding="utf-8")
    (tmp_path / "b.ttl").write_text(prov.render_access_ttl(_access(), NS, ANCHOR), encoding="utf-8")
    (tmp_path / "c.ttl").write_text(
        prov.render_anomaly_ttl(_anomalies(), NS, ANCHOR), encoding="utf-8"
    )
    ok, issues = validate_dangling_references(tmp_path)
    assert ok, issues[:5]

    # Negative control: drop the declarations and the same files must be reported.
    (tmp_path / "decl.ttl").unlink()
    ok, issues = validate_dangling_references(tmp_path)
    assert not ok and issues


def test_opening_hours_parse_and_fall_back():
    assert HOURS[0] == (7.0, 21.0) and HOURS[5] == (9.0, 17.0) and 6 not in HOURS
    assert prov.parse_opening_hours("open when the caretaker is in") == prov.FALLBACK_OPEN
    assert prov.parse_opening_hours(None) == prov.FALLBACK_OPEN


def test_the_iri_renderer_only_prefixes_valid_local_names():
    assert prov._iri(NS + "Room5.01", NS) == "bldg:Room5.01"
    assert prov._iri(NS + "PUMP-CH1", NS) == "bldg:PUMP-CH1"
    assert prov._iri(NS + "Room 5.01", NS) == "<" + NS + "Room 5.01>"
    assert prov._iri(NS + "Room5.", NS) == "<" + NS + "Room5.>"
    assert prov._iri("http://elsewhere/x#A", NS) == "<http://elsewhere/x#A>"
