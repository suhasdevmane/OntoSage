# -*- coding: utf-8 -*-
"""2D-06 / BUG-835: a person's word for a field and the column named for it are one word.

"Who owns them?" was compared with the column ``recordOwner`` letter by letter. "owns" and "owner"
share three letters, the census needs five, and the register was declared to have no ownership
field. The words are joined by a table (config/register_vocabulary.yaml) and the census, the
narration guard and the projection all read it, so a synonym is added in one place.

Also pinned here: what the table must NOT do — read the register-wide owner stamp as an answer to
"which records have NO owner", or make the census print an internal field name.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from orchestrator.agents import sparql_agent
from orchestrator.services import register_facts as rf
from orchestrator.services import register_projection as rp
from orchestrator.services import register_vocabulary as rv
from tests.register_fixture_rows import lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)


# ── the words ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "a, b",
    [
        ("owns", "owner"),
        ("owners", "ownership"),
        ("owned", "own"),
        ("points", "point"),
        ("serviced", "services"),
        ("chairs", "chair"),
        ("lines", "line"),
        ("boxes", "box"),
        ("classes", "class"),
    ],
)
def test_two_forms_of_one_word_stem_alike(a, b):
    assert rv.stem(a) == rv.stem(b)


@pytest.mark.parametrize("a, b", [("owner", "order"), ("lift", "left"), ("door", "floor")])
def test_two_different_words_do_not(a, b):
    assert rv.stem(a) != rv.stem(b)


@pytest.mark.parametrize(
    "question, concept",
    [
        ("Who owns the lifts?", "owner"),
        ("Who is responsible for the plant room?", "owner"),
        ("Who has ownership of the chillers?", "owner"),
        ("Who looks after the generators?", "owner"),
        ("When is the next test due?", "due"),
        ("When is it next serviced?", "due"),
        ("What is the deadline for the survey?", "due"),
        ("When was the lift last serviced?", "last_done"),
        ("When was the alarm last tested?", "last_done"),
        ("Where is the first aid room?", "location"),
        ("What is the contact email for estates?", "contact"),
    ],
)
def test_the_table_hears_the_concept_in_the_question(question, concept):
    names = [c.name for c in rv.get_vocabulary().concepts_in(question)]
    assert concept in names, names


@pytest.mark.parametrize(
    "question",
    [
        "Which rooms are suitable for a confidential call?",  # 'call' is not a contact request
        "Is the atrium open at the weekend?",
        "How many seats does the seminar room have?",
    ],
)
def test_a_question_that_asks_for_none_of_them_triggers_none(question):
    assert rv.get_vocabulary().concepts_in(question) == []


@pytest.mark.parametrize(
    "term, column, expected",
    [
        ("owns", "recordOwner", True),
        ("ownership", "recordOwner", True),
        ("owns", "responsibleRole", True),
        ("responsible", "accountableRole", True),
        ("due", "nextTestDue", True),
        ("owns", "accountableFor", False),  # what a group is accountable FOR is not who owns it
        ("owns", "provisionKind", False),
        ("floor", "recordOwner", False),
    ],
)
def test_term_names_column_through_the_table(term, column, expected):
    assert rf._term_matches_column(term, column) is expected


# ── the census ────────────────────────────────────────────────────────────────────────────────────


def _rows(*dicts):
    return list(dicts)


OWNED = _rows(
    {"recordId": "A-1", "label": "Chiller", "recordStatus": "active", "recordOwner": "Estates"},
    {"recordId": "A-2", "label": "Boiler", "recordStatus": "active", "recordOwner": "Estates"},
)


def test_the_census_places_owns_as_a_recorded_field_not_a_stamp():
    columns = sorted({k for r in OWNED for k in r})
    as_field, _as_text, as_stamp, absent = rf._census_terms(OWNED, columns, "Who owns them?", "")
    assert as_field.get("owns") == ["recordOwner"]
    assert "owns" not in as_stamp and "owns" not in absent


@pytest.mark.parametrize(
    "question",
    [
        "Which records have no owner?",
        "Which permission groups are orphaned because no owner can be evidenced?",
        "Which assets are without an owner?",
    ],
)
def test_the_register_wide_stamp_still_cannot_answer_which_records_have_no_owner(question):
    """The record-wide value says who keeps the register; it cannot say which record lacks one
    (BUG-709 row 3), so an absence question keeps the stamp reading."""
    columns = sorted({k for r in OWNED for k in r})
    as_field, _as_text, as_stamp, _absent = rf._census_terms(OWNED, columns, question, "")
    assert "owner" not in as_field
    assert "owner" in as_stamp


def test_the_locked_facts_carry_the_answer_and_never_the_internal_name():
    rows, label = lifted_rows("evacuation_and_peeps.md")
    facts = rf.register_facts(
        rows, "Which refuge points are defective, and who owns them?", TODAY, label
    )
    assert "Building Fire Warden Coordinator" in facts
    assert "EV-003" in facts
    assert "recordOwner" not in facts
    assert "THE ANSWER TO THIS QUESTION, WORKED OUT BY THE SYSTEM" in facts


def test_locked_lines_cover_the_part_they_answer_and_name_the_rest():
    """Wave 4: a word the register cannot place no longer withholds the whole block. The lines
    carry what the rows settle AND say which part of the question they do not reach."""
    rows, label = lifted_rows("evacuation_and_peeps.md")
    lines = rp.facts_lines(rows, "Who owns the refuge points on the moon?", label, TODAY)
    block = "\n".join(lines)
    assert "THIS COVERS PART OF THE QUESTION" in block and "moon" in block
    assert "Building Fire Warden Coordinator" in block


def test_no_locked_lines_for_a_question_about_absence():
    rows, label = lifted_rows("evacuation_and_peeps.md")
    assert rp.facts_lines(rows, "Which provisions have no owner?", label, TODAY) == []


def test_a_long_list_is_handed_over_whole_on_one_line_never_cut():
    rows, label = lifted_rows("workspace_profile_register.md")
    lines = rp.facts_lines(rows, "Is there a quiet room I can use?", label, TODAY)
    joined = "\n".join(lines)
    assert "26 of the 28" in joined
    for ident in ("WS-02", "WS-28"):  # first and last of the 26
        assert ident in joined
    assert "WS-01" not in joined and "WS-19" not in joined  # the two conversational spaces
    assert "noise" in joined and "quietest" not in joined


# ── the owner stamp: the register's value and the record's own ──────────────────────────────────


def test_a_record_with_its_own_owner_shows_that_one_and_the_shared_value_is_set_aside():
    rows = _rows(
        {"recordId": "A", "recordOwner": "Fire Warden, Estates"},
        {"recordId": "B", "recordOwner": "Fire Warden"},
        {"recordId": "C", "recordOwner": "Fire Warden, Security"},
    )
    shared = {"recordOwner": rp._shared_member(rows, "recordOwner")}
    assert shared["recordOwner"] == "Fire Warden"
    assert [rp._cell(r, "recordOwner", shared) for r in rows] == [
        "Estates",
        "Fire Warden",
        "Security",
    ]


def test_nothing_is_split_when_no_value_is_shared_by_every_record():
    rows = _rows(
        {"recordId": "A", "recordOwner": "Estates, Security"},
        {"recordId": "B", "recordOwner": "Catering, Cleaning"},
    )
    assert rp._shared_member(rows, "recordOwner") == ""


def test_a_single_valued_column_is_never_split():
    rows = _rows({"recordId": "A", "recordOwner": "Estates, Facilities and Maintenance"})
    assert rp._shared_member(rows, "recordOwner") == ""


# ── wiring: the register lane uses all of it ─────────────────────────────────────────────────────


def _lane_source() -> str:
    return inspect.getsource(sparql_agent.SPARQLAgent._whole_register)


def test_the_lane_asks_the_rows_before_it_asks_the_model():
    src = _lane_source()
    assert "answer_before_narration" in src
    assert src.index("answer_before_narration") < src.index("self._format_results(")
    assert "_rows_answer or strip_leaked_code_line" in src


def test_a_composed_answer_is_not_given_the_narration_guards():
    """Those guards repair a NARRATION; appending to a projected answer would only restate it."""
    src = _lane_source()
    assert src.count("if not _rows_answer:") == 2


def test_the_lane_hands_over_only_a_whole_register():
    src = _lane_source()
    assert "len(_primary_rows) < record.instances" in src
    assert "bool(second_label)" in src


def test_the_denial_guard_is_the_replacing_one():
    src = _lane_source()
    assert "guard_narration(" in src and "false_absence_corrections(" not in src


def test_a_related_registers_rows_are_read_in_the_same_shape_as_the_first():
    assert inspect.iscoroutinefunction(sparql_agent.SPARQLAgent._register_rows)
