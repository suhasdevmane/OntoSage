# -*- coding: utf-8 -*-
"""A record moves by ITS OWN cadence, or it does not move.

The defect these tests pin: a register is authored once and read for weeks, so a
twice-daily washroom task sat at `lastCompleted 2026-09-03 / nextDue 2026-09-04` on
2026-09-17. Correct lane, correct register, a reader who concludes the system is broken.

The tempting fix — shift every date by the same delta — is wrong in the other direction:
it would move a five-yearly fixed-wiring inspection that is not due for another three
years, which is inventing an inspection. So the rule under test is per record:

* stale is measured against the record's own frequency / interval, never the calendar;
* an open record keeps the margin it already has instead of growing staler;
* a declared status is never rewritten;
* nothing is ever recorded as done in the future.

Every record here is fabricated in the test. Nothing reads the building's own files, so
these pass in a parked tree with no active building.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from scripts.refresh_record_dates import (
    Cadence,
    Report,
    add_months,
    count_statuses,
    keep_working_day,
    open_state_count,
    parse_frequency,
    refresh_register,
    status_is_held,
    whole_day_shift,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 9, 17, 23, 59, 59)

#: A mapping of the shape the ontology ships, written here so the test does not depend
#: on any particular building or on the real record-document catalogue.
MAPPING = {
    "record_type": "fixture_task",
    "class": "ontosage:FixtureTask",
    "iri_template": "fixture/{code}",
    "label_column": "code",
    "columns": {
        "code": {"predicate": "ontosage:recordId", "datatype": "xsd:string"},
        "frequency": {"predicate": "ontosage:serviceFrequency", "datatype": "xsd:string"},
        "last_done": {"predicate": "ontosage:lastCompleted", "datatype": "xsd:date"},
        "next_due": {"predicate": "ontosage:nextDue", "datatype": "xsd:date"},
        "status": {"predicate": "ontosage:recordStatus", "datatype": "xsd:string"},
    },
}

HEADER = "| code | frequency | last_done | next_due | status |\n|---|---|---|---|---|\n"

FRONT = (
    "---\n"
    "record_type: fixture_task\n"
    'owner: "Fixture Owner"\n'
    'authority: "Fixture Authority"\n'
    'source_system: "Fixture Register"\n'
    "effective_from: 2026-09-01\n"
    'version: "2026.9"\n'
    "simulated: true\n"
    "---\n\n"
    "# Fixture register\n\n"
)

ROWS = [
    # twice-daily washroom service, running normally — 14 days stale
    "| FX-01 | twice daily | 2026-09-03 | 2026-09-04 | Scheduled |",
    # five-yearly fixed-wiring inspection done in 2024 — not stale by its own interval
    "| FX-02 | 5 yearly | 2024-03-12 | 2029-03-11 | Active |",
    # weekly task, declared overdue — stays overdue
    "| FX-03 | weekly | 2026-08-24 | 2026-08-31 | Overdue |",
    # annual test four months overdue — less than one cadence, so it does not move
    "| FX-04 | annual | 2025-05-06 | 2026-05-06 | Overdue |",
    # a one-off laid on for an event — declares no recurrence, so it never recurs
    "| FX-05 | event-driven | 2026-08-27 | 2026-09-04 | Added |",
    # a monthly clean, three days past its month
    "| FX-06 | monthly | 2026-08-14 | 2026-09-14 | Scheduled |",
]


def _write_register(tmp_path: Path) -> Path:
    documents = tmp_path / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    path = documents / "fixture_register.md"
    path.write_text(FRONT + HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")
    return path


def _refreshed_rows(tmp_path: Path, **kwargs) -> dict:
    path = _write_register(tmp_path)
    text = refresh_register(path, {"fixture_task": MAPPING}, AS_OF, Report(), **kwargs)
    assert text is not None, "the fixture register is stale; something should have moved"
    rows = {}
    for line in text.splitlines():
        if not line.startswith("| FX-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows[cells[0]] = dict(zip(["code", "frequency", "last", "next", "status"], cells))
    return rows


# ── the four claims ────────────────────────────────────────────────────────────────


def test_a_twice_daily_task_lands_inside_its_own_interval(tmp_path):
    """A twice-daily service cannot be two weeks since its last visit."""
    row = _refreshed_rows(tmp_path)["FX-01"]
    last = datetime.fromisoformat(row["last"])
    assert (AS_OF - last).days <= 1, f"twice-daily task still {(AS_OF - last).days} days behind"
    assert datetime.fromisoformat(row["next"]) >= AS_OF.replace(hour=0, minute=0, second=0)


def test_a_five_yearly_inspection_is_untouched(tmp_path):
    """Moving an inspection that is not due is inventing one."""
    row = _refreshed_rows(tmp_path)["FX-02"]
    assert row["last"] == "2024-03-12"
    assert row["next"] == "2029-03-11"


def test_an_overdue_record_stays_overdue(tmp_path):
    """Its status is untouched and its due date is still in the past."""
    rows = _refreshed_rows(tmp_path)
    for code in ("FX-03", "FX-04"):
        assert rows[code]["status"] == "Overdue"
        due = datetime.fromisoformat(rows[code]["next"])
        assert due <= AS_OF, f"{code} was rolled out of being overdue"


def test_an_overdue_record_keeps_the_margin_it_had_and_does_not_grow(tmp_path):
    """Weekly: still about a week overdue. Annual: still four months overdue."""
    rows = _refreshed_rows(tmp_path)
    weekly_margin = (AS_OF - datetime.fromisoformat(rows["FX-03"]["next"])).days
    assert 0 <= weekly_margin < 7, f"weekly task is {weekly_margin} days overdue"
    annual = datetime.fromisoformat(rows["FX-04"]["next"])
    assert annual == datetime(2026, 5, 6), "an annual test 4 months overdue must not move"


def test_no_completion_is_recorded_in_the_future(tmp_path):
    for code, row in _refreshed_rows(tmp_path).items():
        last = datetime.fromisoformat(row["last"])
        assert last <= AS_OF, f"{code} claims work completed in the future"


def test_a_declared_status_is_never_rewritten(tmp_path):
    path = _write_register(tmp_path)
    mappings = {"fixture_task": MAPPING}
    before = count_statuses(path, mappings)
    text = refresh_register(path, mappings, AS_OF, Report())
    path.write_text(text, encoding="utf-8", newline="")
    after = count_statuses(path, mappings)
    assert before == after
    assert open_state_count(before) == open_state_count(after) == 3


def test_a_record_declaring_no_recurrence_never_recurs(tmp_path):
    """'event-driven' is a declared cadence of none — not an absent one to infer."""
    row = _refreshed_rows(tmp_path)["FX-05"]
    assert row["last"] == "2026-08-27"
    assert row["next"] == "2026-09-04"


def test_the_declared_interval_between_last_and_next_survives(tmp_path):
    rows = _refreshed_rows(tmp_path)
    for code, original_gap in (("FX-01", 1), ("FX-03", 7), ("FX-06", 31)):
        gap = (
            datetime.fromisoformat(rows[code]["next"]) - datetime.fromisoformat(rows[code]["last"])
        ).days
        assert gap == original_gap, f"{code} gap {gap} != {original_gap}"


def test_freeze_held_leaves_open_records_exactly_where_they_are(tmp_path):
    rows = _refreshed_rows(tmp_path, freeze_held=True)
    assert rows["FX-03"]["last"] == "2026-08-24"
    assert rows["FX-03"]["next"] == "2026-08-31"
    assert rows["FX-01"]["last"] != "2026-09-03", "current records must still roll"


def test_a_second_run_changes_nothing(tmp_path):
    """Re-runnable: the same reference date twice is a no-op the second time."""
    path = _write_register(tmp_path)
    mappings = {"fixture_task": MAPPING}
    first = refresh_register(path, mappings, AS_OF, Report())
    path.write_text(first, encoding="utf-8", newline="")
    assert refresh_register(path, mappings, AS_OF, Report()) is None


def test_only_the_date_cells_are_rewritten(tmp_path):
    """Table shape, padding and every non-date cell survive verbatim."""
    path = _write_register(tmp_path)
    original = path.read_text(encoding="utf-8")
    text = refresh_register(path, {"fixture_task": MAPPING}, AS_OF, Report())
    strip = lambda s: re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", s)  # noqa: E731
    assert strip(text) == strip(original)


# ── the cadence primitives ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,days,months",
    [
        ("twice daily", 0.5, 0),
        ("2-hourly", 1 / 12, 0),
        ("daily, overnight", 1.0, 0),
        ("twice weekly", 3.5, 0),
        ("weekly", 7.0, 0),
        ("6 monthly", 0, 6),
        ("annual", 0, 12),
        ("5 yearly", 0, 60),
        ("90", 90.0, 0),
        ("every 180 days", 180.0, 0),
    ],
)
def test_declared_frequencies_parse(text, days, months):
    cadence = parse_frequency(text)
    assert cadence is not None and cadence.is_periodic
    assert cadence.days == pytest.approx(days) and cadence.months == months


def test_a_declared_non_recurrence_is_not_an_absent_cadence():
    cadence = parse_frequency("event only")
    assert cadence is not None and not cadence.is_periodic
    assert parse_frequency("") is None


def test_a_shift_is_always_a_whole_number_of_days():
    """So a 02:10 night-patrol check stays a 02:10 night-patrol check."""
    anchor = datetime(2026, 9, 4, 2, 10)
    shift = whole_day_shift(anchor, Cadence(days=1 / 12), AS_OF)
    assert shift == int(shift) and (anchor.day + shift) > anchor.day
    assert (anchor.replace(day=4) + __import__("datetime").timedelta(days=shift)).hour == 2


def test_a_weekly_cadence_preserves_the_weekday():
    anchor = datetime(2026, 8, 24)  # a Monday
    shift = whole_day_shift(anchor, Cadence(days=7.0), AS_OF)
    assert shift % 7 == 0


def test_month_cadences_step_by_calendar_months():
    assert add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
    assert add_months(datetime(2026, 8, 14), 6) == datetime(2027, 2, 14)


def test_a_weekday_record_is_not_moved_onto_a_weekend():
    anchor = datetime(2026, 8, 14)  # Friday
    cadence = Cadence(days=7.0)
    shift = keep_working_day(anchor, whole_day_shift(anchor, cadence, AS_OF), cadence)
    assert (anchor + __import__("datetime").timedelta(days=shift)).weekday() < 5


@pytest.mark.parametrize(
    "status,held",
    [
        ("Active", False),
        ("Scheduled", False),
        ("Current", False),
        ("Ready", False),
        ("Overdue", True),
        ("Defective", True),
        ("Outstanding", True),
        ("Unverified", True),
        ("Expired", True),
        ("No evidence", True),
        ("Unevidenced", True),
        ("", True),
        ("something nobody declared", True),
    ],
)
def test_an_unreadable_status_is_treated_as_open(status, held):
    """Rolling a record whose state cannot be read is how an open problem disappears."""
    assert status_is_held(status) is held


def test_the_fixture_mapping_matches_the_shape_the_ontology_ships(tmp_path):
    """Guards the test itself: the fixture must parse as a real record document would."""
    path = _write_register(tmp_path)
    front = yaml.safe_load(path.read_text(encoding="utf-8").split("---")[1])
    for key in ("record_type", "owner", "authority", "source_system", "version", "simulated"):
        assert key in front
