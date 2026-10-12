"""The register lane filters by a named period and storey from the records themselves.

BUG-1522 / BUG-1530 (2026-10-10). "Which departments are based on floor 4?" matched one record
"mentioning floor" and dropped the 4; "incidents logged in September" listed every month;
"how many incidents happened last month" said the register "does not record when incidents
happened" while every row carried effectiveFrom; "contracts that expire next year" read the start
date and the recorded state "expired". Records here are synthetic and name no building.
"""

from datetime import date

import pytest

from orchestrator.services.register_projection import resolve

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 10)


def _depts():
    locs = [
        "Level 0 Estates office",
        "Level 3 office",
        "Level 4 admin office",
        "Level 4 admin office",
        "Levels 3 to 5",
        "Main entrance reception",
    ]
    return [
        {
            "recordId": f"DEP-{i:02d}",
            "label": f"Dept {i}",
            "locationText": t,
            "recordStatus": "active",
        }
        for i, t in enumerate(locs, 1)
    ]


def _incidents():
    rows = [
        ("near miss", "2026-09-03", "2026-09-10"),
        ("injury", "2026-09-20", ""),
        ("near miss", "2026-08-12", "2026-08-26"),
        ("injury", "2026-10-02", ""),
    ]
    return [
        {
            "recordId": f"INC-{i}",
            "label": f"incident {i}",
            "incidentCategory": cat,
            "effectiveFrom": start,
            "completedDate": done,
            "recordStatus": "closed",
        }
        for i, (cat, start, done) in enumerate(rows, 1)
    ]


def _contracts():
    rows = [
        ("Lift", "2023-12-25", "2026-12-24", "active"),
        ("BMS", "2024-12-29", "2027-10-25", "active"),
        ("Grounds", "2023-02-08", "2026-05-03", "expired"),
        ("Chillers", "2026-02-22", "2028-02-22", "active"),
    ]
    return [
        {
            "recordId": f"CON-{i}",
            "label": scope,
            "coveredScope": scope,
            "effectiveFrom": start,
            "effectiveTo": end,
            "recordStatus": status,
        }
        for i, (scope, start, end, status) in enumerate(rows, 1)
    ]


def test_a_floor_named_against_free_text_locations_filters_by_storey():
    res = resolve(_depts(), "Which departments are based on floor 4?", "Department", today=TODAY)
    assert res.other_filters == ["on floor 4"]
    assert res.unresolved == []  # neither "based" nor "floor" is searched as a word


def test_a_register_that_states_storeys_answers_none_for_an_empty_floor():
    rows = [
        {"recordId": "WS-1", "label": "open study", "onFloor": "1", "recordStatus": "active"},
        {"recordId": "WS-2", "label": "lab", "onFloor": "2", "recordStatus": "active"},
    ]
    res = resolve(rows, "Where can I study on the ground floor?", "Workspace profile", today=TODAY)
    assert "on the ground floor" in res.other_filters


def test_a_register_keyed_by_room_id_is_left_alone_for_a_floor():
    rows = [
        {"recordId": "B-1", "label": "b", "location": "Room 5.15 - Seminar", "recordStatus": "ok"},
        {"recordId": "B-2", "label": "b", "location": "Room 2.01 - Lab", "recordStatus": "ok"},
    ]
    res = resolve(rows, "Which bookings are on floor 5?", "Booking", today=TODAY)
    assert not any("floor" in f for f in res.other_filters)


@pytest.mark.parametrize(
    "question, label_part",
    [
        ("What incidents or near misses were logged in September?", "September 2026"),
        ("How many incidents happened last month?", "last month"),
        ("Which incidents happened this month?", "this month"),
    ],
)
def test_a_named_period_filters_on_the_date_the_record_happened(question, label_part):
    res = resolve(_incidents(), question, "Incident record", today=TODAY)
    assert any(f.startswith("effective from:") and label_part in f for f in res.other_filters)


def test_the_register_name_on_one_side_of_or_does_not_narrow_to_the_other():
    res = resolve(
        _incidents(),
        "What incidents or near misses were logged in September?",
        "Incident record",
        today=TODAY,
    )
    assert not any(f.startswith("incident category") for f in res.other_filters)


def test_what_was_done_reads_the_completion_date():
    rows = [
        {
            "recordId": "WO-1",
            "label": "w",
            "raisedDate": "2026-08-28",
            "completedDate": "2026-09-05",
            "recordStatus": "closed",
        },
        {
            "recordId": "WO-2",
            "label": "w",
            "raisedDate": "2026-09-15",
            "completedDate": "",
            "recordStatus": "open",
        },
    ]
    res = resolve(rows, "What maintenance was done last month?", "Work order", today=TODAY)
    assert any(f.startswith("completed date:") for f in res.other_filters)


def test_expiring_next_year_reads_the_end_date_and_not_the_expired_state():
    res = resolve(_contracts(), "Which contracts expire next year?", "Contract", today=TODAY)
    assert any(f.startswith("effective to:") and "next year" in f for f in res.other_filters)
    assert res.status_values == []


def test_expired_this_year_reads_the_end_date_and_keeps_the_state():
    res = resolve(_contracts(), "Which contracts expired this year?", "Contract", today=TODAY)
    assert any(f.startswith("effective to:") for f in res.other_filters)
    assert res.status_values == ["expired"]


def test_started_reads_the_start_date_without_overlap():
    res = resolve(_contracts(), "Which contracts started this year?", "Contract", today=TODAY)
    assert any(f.startswith("effective from:") for f in res.other_filters)
