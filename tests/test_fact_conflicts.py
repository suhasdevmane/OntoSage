# -*- coding: utf-8 -*-
"""scripts/fact_conflicts.py finds facts the building states twice, differently.

Each fixture below is a disagreement that was READ in the live building on 2026-09-19 and
resolved by hand, so the extractor is held to the cases that mattered:

* the reception desk open 07:30-18:00 in three registers and 09:00-16:30 in three capability topics;
* the same IT service desk with two telephone numbers;
* a policy sending lone workers to "Level 6" in a building with floors 0-5;
* server rooms on floors 2 and 4 in one file and 2, 4 and 5 in another;
* the waste and lift suppliers named one way in the contract register and another in the ledger.

The last test is the standing check: it runs the scanner over the active building and fails on
any conflict not recorded, with a reason, in ACCEPTED.
"""

from pathlib import Path

import pytest

from scripts import fact_conflicts as fc

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _building(tmp_path, documents=None, ttl=None):
    root = tmp_path / "input"
    (root / "documents").mkdir(parents=True)
    for name, text in (documents or {}).items():
        (root / "documents" / name).write_text(text, encoding="utf-8")
    for name, text in (ttl or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def _found(root):
    return fc.conflicts(fc.scan(root))


def test_the_same_desk_with_two_opening_hours_is_a_conflict(tmp_path):
    root = _building(
        tmp_path,
        documents={"a.md": "| In-person | Main Reception, Room 0.01 | 07:30–18:00 |\n"},
        ttl={
            "b.ttl": 'x:t ontosage:answerText "Reception is open Monday-Friday 09:00-16:30; closed weekends." .\n'
        },
    )
    found = _found(root)
    assert set(found[("reception", "weekday_hours")]) == {"07:30-18:00", "09:00-16:30"}


def test_two_statements_that_agree_are_not_a_conflict(tmp_path):
    root = _building(
        tmp_path,
        ttl={
            "a.ttl": 'x:a ontosage:answerText "Reception is open Mon-Fri 09:00-16:30." .\n',
            "b.ttl": 'x:b ontosage:answerText "reception is staffed Monday–Friday 09.00–16.30 only" .\n',
        },
    )
    assert _found(root) == {}


def test_the_building_and_its_reception_are_read_as_two_subjects_in_one_sentence(tmp_path):
    text = (
        'x:t ontosage:answerText "Card-holders can access Abacws 07:00-22:00 on weekdays and '
        '08:00-18:00 at weekends; reception is staffed Mon-Fri 09:00-16:30 only." .\n'
    )
    facts = {
        (f.subject, f.attribute, f.value) for f in fc.scan(_building(tmp_path, ttl={"a.ttl": text}))
    }
    assert ("building", "weekday_hours", "07:00-22:00") in facts
    assert ("building", "sat_hours", "08:00-18:00") in facts
    assert ("building", "sun_hours", "08:00-18:00") in facts
    assert ("reception", "weekday_hours", "09:00-16:30") in facts
    assert ("building", "weekday_hours", "09:00-16:30") not in facts


def test_a_closed_weekend_is_a_fact_and_a_bare_closed_is_not(tmp_path):
    text = 'x:t ontosage:openingHours "Mon-Fri 07:00-22:00; Sat 09:00-17:00; Sun closed" .\n'
    facts = {(f.attribute, f.value) for f in fc.scan(_building(tmp_path, ttl={"a.ttl": text}))}
    assert ("sun_hours", "closed") in facts and ("sat_hours", "09:00-17:00") in facts
    other = 'x:t ontosage:answerText "The reception status is closed for the evening." .\n'
    assert not [
        f for f in fc.scan(_building(tmp_path / "two", ttl={"b.ttl": other})) if f.value == "closed"
    ]


def test_a_plant_schedule_that_mentions_reception_is_not_the_desks_opening_hours(tmp_path):
    table = (
        "| id | system | zone | setpoint | unoccupied | window |\n|---|---|---|---|---|---|\n"
        "| REG-001 | AHU Floor 0 | Ground floor teaching and reception | 21 degC | frost only | Mon-Fri 07:00-19:00 |\n"
    )
    assert not [
        f
        for f in fc.scan(_building(tmp_path, documents={"hvac.md": table}))
        if f.subject == "reception"
    ]


def test_core_hours_are_a_different_concept_from_card_holder_access_hours(tmp_path):
    root = _building(
        tmp_path,
        documents={"p.md": "Core hours are 07:00–19:00 on weekdays.\n"},
        ttl={
            "a.ttl": 'x:t ontosage:answerText "Standard building hours: Monday–Friday 07:00–22:00." .\n'
        },
    )
    assert _found(root) == {}


def test_a_service_desk_with_two_numbers_is_a_conflict_and_a_directory_row_is_read_by_its_name(
    tmp_path,
):
    table = (
        "| code | name | contact_email | contact_phone |\n|---|---|---|---|\n"
        "| DEP-07 | IT and Network Infrastructure | it@example.ac.uk | 029 2087 0007 |\n"
        "| DEP-04 | Cleaning and Caretaking | c@example.ac.uk | 029 2087 0004 |\n"
    )
    ttl = 'x:t ontosage:answerText "IT support is provided by the IT Service Desk (029 2251 1111)." .\n'
    found = _found(_building(tmp_path, documents={"d.md": table}, ttl={"a.ttl": ttl}))
    assert set(found[("it_service_desk", "phone")]) == {"02920870007", "02922511111"}
    assert ("security", "phone") not in found  # a row that merely mentions Security is not Security


def test_the_nearest_service_names_a_phone_number(tmp_path):
    text = (
        'x:t ontosage:answerText "Estates FM helpdesk (029 2087 6026); out-of-hours emergency '
        '029 2087 5555. Security (24/7): 029 2087 4444." .\n'
    )
    facts = {(f.subject, f.value) for f in fc.scan(_building(tmp_path, ttl={"a.ttl": text}))}
    assert {
        ("estates_helpdesk", "02920876026"),
        ("estates_out_of_hours", "02920875555"),
        ("security", "02920874444"),
    } <= facts


def test_a_floor_the_building_does_not_have_is_a_finding(tmp_path):
    ttl = {
        "floors.ttl": "bldg:Floor0 a brick:Floor .\nbldg:Floor1 a brick:Floor .\nbldg:Floor5 a brick:Floor .\n"
    }
    docs = {"p.md": "Lone working on Level 6 plant areas requires sign-in.\nLevel 3 is fine.\n"}
    found = _found(_building(tmp_path, documents=docs, ttl=ttl))
    assert list(found[("building", "floor_numbers")]) == ["refers to floor 6"]


def test_server_rooms_on_different_floors_in_two_files_are_a_conflict(tmp_path):
    ttl = {
        "one.ttl": 'bldg:Floor2 hbco:spaceFunction "Study floor, server room"^^xsd:string ;\n'
        'bldg:Floor4 hbco:spaceFunction "Labs, server room"^^xsd:string ;\n',
        "two.ttl": 'rdfs:label "Server Room — Floor 2 (Room 2.44)" ; rdfs:label "Room 4.44 — Server Room" ;\n'
        'rdfs:label "Server Room — Floor 5 (Room 5.44)" ;\n',
    }
    found = _found(_building(tmp_path, ttl=ttl))
    assert set(found[("server_rooms", "floors")]) == {"2,4", "2,4,5"}


def test_a_supplier_that_differs_from_the_contract_is_a_conflict_but_a_role_is_not(tmp_path):
    docs = {
        "contracts.md": "| reference | scope | provider |\n|---|---|---|\n"
        "| CON-1 | Waste collection and recycling | Regional Waste Partners |\n"
        "| CON-2 | Cleaning and washroom services | Clearview Facilities |\n",
        "ledger.md": "| line | description | supplier |\n|---|---|---|\n"
        "| CL-1 | Waste and recycling | Cardiff Waste Partners |\n"
        "| CL-2 | Cleaning contract | In-house |\n",
    }
    found = _found(_building(tmp_path, documents=docs))
    assert set(found[("waste", "provider")]) == {
        "Regional Waste Partners",
        "Cardiff Waste Partners",
    }
    assert ("cleaning", "provider") not in found


def test_a_date_cited_beside_a_record_code_must_be_one_the_record_holds(tmp_path):
    docs = {
        "permits.md": "| permit | date | expires |\n|---|---|---|\n| PTW-2026-0417 | 2026-08-30 | 2026-09-02 |\n",
        "note.md": "One set was used under permit PTW-2026-0417 (2026-08-30). Later PTW-2026-0417 on 2026-09-09.\n",
    }
    found = _found(_building(tmp_path, documents=docs))
    values = list(found[("PTW-2026-0417", "cited_date")])
    assert len(values) == 1 and values[0].startswith("2026-09-09")


def test_an_accepted_conflict_is_reported_but_does_not_fail_the_check(tmp_path, capsys):
    docs = {
        "contracts.md": "| reference | scope | provider |\n|---|---|---|\n| CON-1 | Grounds and external areas | Taff Valley Grounds |\n",
        "ledger.md": "| line | description | supplier |\n|---|---|---|\n| CL-1 | Grounds maintenance | Cardiff Grounds Care |\n",
    }
    root = _building(tmp_path, documents=docs)
    assert fc.main(["--input", str(root)]) == 0
    assert "accepted, not resolved: grounds.provider" in capsys.readouterr().out


def test_a_missing_input_folder_is_not_a_pass(tmp_path):
    assert fc.main(["--input", str(tmp_path / "nowhere")]) == 2


def test_the_active_building_states_no_fact_twice_differently():
    """The standing check. Fails on any conflict not recorded, with a reason, in ACCEPTED."""
    root = REPO / "input"
    if not (root / "documents").is_dir():
        pytest.skip("no active building: input/documents is absent (parked tree)")
    open_, _ = fc.split_accepted(_found(root))
    assert not open_, fc.report(open_)


def test_an_amenitys_own_opening_hours_are_not_the_buildings(tmp_path):
    """`ontosage:openingHours` on an Amenity is that amenity's hours (2026-09-20).

    The extractor read the predicate NAME as the subject "building", so a cafe open 08:00-16:30 was
    reported as contradicting a building open 07:00-22:00. The building's own triple must still be
    read as the building's hours; the amenity's must not be."""
    ttl = (
        'bldg:Abacws ontosage:openingHours "Mon-Fri 07:00-22:00" .\n'
        "bldg:Amenity_Cafe_Floor0 a ontosage:Amenity ;\n"
        '    ontosage:openingHours "Monday-Friday 08:00-16:30" ;\n'
        '    ontosage:answerText "There is a cafe on the ground floor." .\n'
    )
    root = _building(tmp_path, ttl={"a.ttl": ttl})
    facts = {(f.subject, f.attribute, f.value) for f in fc.scan(root)}
    assert ("building", "weekday_hours", "07:00-22:00") in facts
    assert ("building", "weekday_hours", "08:00-16:30") not in facts
    assert not _found(root)
