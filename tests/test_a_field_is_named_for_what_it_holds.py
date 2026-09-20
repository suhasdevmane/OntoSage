# -*- coding: utf-8 -*-
"""A register field is read by the WORDS in its name, so a field named for something else is
invisible to the question that asks for it (row 2D-11 follow-up, two mapping defects).

* `service_schedule.yaml` lifted the document's `statutory` column into `ontosage:isOptional`.
  Seven items (SVC-08, 09 and 12..16: the weekly fire alarm test, the lift LOLER examination, the
  chiller F-Gas check, the grease trap and duct clean) therefore read as OPTIONAL, and the word
  "statutory" matched no field, so the register lane could only narrate the note text.
* `work_order.yaml` lifted the document's `hours` column (3.6, 0.8, 2.9) into
  `ontosage:expectedMinutes`. Every work order read as a few minutes long, and the word "hours"
  matched no field.

Both are fixed by giving the field a name that says what it holds. These tests hold the mapping,
the TBox, the lifted triples and the register lane's own reading of the field to that.
"""

import re
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from orchestrator.services.record_documents import lift_document  # noqa: E402

MAPPINGS = REPO / "ontology" / "record_documents"
NS = "http://example.org/building#"


def _doc(name):
    for path in [REPO / "input" / "documents" / name, *sorted(REPO.glob(f"*/documents/{name}"))]:
        if path.is_file():
            return path
    pytest.skip(f"{name} is in no building folder of this checkout")


def _mapping(name):
    return yaml.safe_load((MAPPINGS / f"{name}.yaml").read_text(encoding="utf-8"))


def _records(name):
    """{subject: {predicate local name: value}} from a real lift of the document."""
    result = lift_document(_doc(name), NS, MAPPINGS)
    assert not result.errors, result.errors[:3]
    records = {}
    for subject, predicate, value in result.triples:
        records.setdefault(subject, {})[predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]] = value
    return records


def _schema():
    return (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")


# ── the mappings ───────────────────────────────────────────────────────────────────────────


def test_statutory_is_lifted_as_isStatutory_and_never_as_isOptional():
    spec = _mapping("service_schedule")["columns"]["statutory"]
    assert spec["predicate"] == "ontosage:isStatutory"
    assert spec["datatype"] == "xsd:boolean"
    assert all(
        s["predicate"] != "ontosage:isOptional"
        for s in _mapping("service_schedule")["columns"].values()
    )


def test_hours_are_lifted_as_jobHours_and_never_as_minutes():
    spec = _mapping("work_order")["columns"]["hours"]
    assert spec["predicate"] == "ontosage:jobHours"
    assert spec["datatype"] == "xsd:decimal"
    assert all(
        s["predicate"] != "ontosage:expectedMinutes"
        for s in _mapping("work_order")["columns"].values()
    )


def test_the_tbox_declares_both_fields_with_the_right_type_and_says_what_they_are_not():
    text = _schema()
    end = r"\.\s*(?:\n\s*\n|\Z)"  # a block ends at a blank line, or at the end of the file
    m = re.search(rf"ontosage:isStatutory a owl:DatatypeProperty ;(.*?){end}", text, re.S)
    assert m and "xsd:boolean" in m.group(1) and "OPPOSITE of ontosage:isOptional" in m.group(1)
    m = re.search(rf"ontosage:jobHours a owl:DatatypeProperty ;(.*?){end}", text, re.S)
    assert m and "xsd:decimal" in m.group(1) and "HOURS" in m.group(1)


def test_the_class_says_what_every_entry_of_it_is():
    """Every service schedule entry is a planned one, so the register's own name carries the word
    'planned' and the census does not report it as a property the records failed to record."""
    assert 'rdfs:label "Planned service schedule entry"@en' in _schema()


# ── the lifted data ────────────────────────────────────────────────────────────────────────


def test_exactly_the_documents_statutory_rows_are_statutory_and_none_reads_as_optional():
    records = _records("service_schedules.md")
    statutory = sorted(r["recordId"] for r in records.values() if r.get("isStatutory") is True)
    assert statutory == ["SVC-08", "SVC-09", "SVC-12", "SVC-13", "SVC-14", "SVC-15", "SVC-16"]
    assert all(
        r.get("isStatutory") is False for r in records.values() if r["recordId"] not in statutory
    )
    assert not any("isOptional" in r for r in records.values())


def test_the_statutory_fire_alarm_test_and_the_lift_examination_are_statutory():
    by_id = {r["recordId"]: r for r in _records("service_schedules.md").values()}
    for code in ("SVC-14", "SVC-16"):
        assert by_id[code]["isStatutory"] is True, code
    assert by_id["SVC-01"]["isStatutory"] is False  # a missed clean is an inconvenience


def test_every_work_order_carries_its_hours_as_hours_not_minutes():
    records = _records("maintenance_log.md")
    assert records and not any("expectedMinutes" in r for r in records.values())
    hours = {r["recordId"]: r["jobHours"] for r in records.values() if "jobHours" in r}
    assert len(hours) == len(records)
    assert hours["WO-001"] == pytest.approx(3.6) and hours["WO-002"] == pytest.approx(0.8)
    assert all(
        0 < h < 24 for h in hours.values()
    ), "a job of more than a day would not be a job-hours figure"


# ── how the register lane now reads them ───────────────────────────────────────────────────


def test_the_lane_reads_isStatutory_as_the_field_statutory_and_jobHours_as_job_hours():
    from orchestrator.services import register_facts as rf

    assert rf._plain("isStatutory") == "statutory"
    assert rf._plain("jobHours") == "job hours"
    assert rf._term_matches_column("statutory", "isStatutory")
    assert rf._term_matches_column("hours", "jobHours")
    # what it did before the fix: neither word matched the field it was stored in
    assert not rf._term_matches_column("statutory", "isOptional")
    assert not rf._term_matches_column("hours", "expectedMinutes")


def test_a_question_about_statutory_services_now_finds_a_recorded_field_not_a_note():
    from orchestrator.services import register_facts as rf

    rows = list(_records("service_schedules.md").values())
    columns = sorted({c for r in rows for c in r})
    as_field, as_text, _, absent = rf._census_terms(
        rows, columns, "Which statutory services are overdue?", "Planned service schedule entry"
    )
    assert "statutory" in as_field and as_field["statutory"] == ["isStatutory"]
    assert "statutory" not in as_text and "statutory" not in absent


def test_planned_is_the_registers_own_name_and_not_a_missing_field():
    from orchestrator.services import register_facts as rf

    rows = list(_records("service_schedules.md").values())
    columns = sorted({c for r in rows for c in r})
    as_field, as_text, _, absent = rf._census_terms(
        rows, columns, "Which planned services are overdue?", "Planned service schedule entry"
    )
    assert "planned" not in as_field and "planned" not in as_text and "planned" not in absent


def test_a_question_about_hours_finds_the_work_order_field():
    from orchestrator.services import register_facts as rf

    rows = list(_records("maintenance_log.md").values())
    columns = sorted({c for r in rows for c in r})
    as_field, _, _, absent = rf._census_terms(
        rows, columns, "How many hours did the fault investigation take?", "Work order"
    )
    assert as_field.get("hours") == ["jobHours"] and "hours" not in absent
