# -*- coding: utf-8 -*-
"""A decline that says what a register records must not name a third of it (BUG-1331).

`out_of_scope_decline` is the one sentence a reader gets when a register is asked something it
holds none of, and it tells them what the register DOES record. Measured 2026-09-30 over all 38
registers under `input/documents` that lift, the sentence named a **median 29%** of the register's
content columns, and **21 of 38 named a third or less** -- `access_permission` 1 of 8,
`event_activity` 1 of 8, `room_bookings` 1 of 5, `accessible_route` 3 of 14.

It was filtered by `Vocabulary.names_what_a_record_is`, which answers a DIFFERENT question --
"do this column's values NAME the record?", used to pick an identifier -- so date, status,
threshold and measurement columns were dropped wholesale, and those are the columns a question
usually asks about.

Live, occupant01, /v1 streaming, 2026-09-30, verbatim:

    "Which boundary-to-door route is currently evidenced for ambulance crews, stretcher teams
     and responders on foot, including step-free constraints?"

    "The accessible route register (16 records) cannot answer this: it records route distance
     metres, route from and route to, and nothing about ambulance, boundary-to-door,
     constraints and crews."

The register holds `isStepFree`, `status`, `surveyedOn`, `surveyedBy`, `doorOperation`,
`liftStatus` and eight more. `isStepFree` is the column the question NAMED -- which is why
"step-free" is absent from the "nothing about" list -- and the sentence still did not name it.
A reader cannot tell that sentence apart from a genuinely thin register, so it is a false
statement about the records: design contract 4.

These tests pin the two properties that make the sentence true rather than merely shorter:
every field named is a field the rows carry, and nothing the register records is silently
omitted -- what the eight-item cap drops is disclosed as a count.
"""

from __future__ import annotations

from datetime import date

import pytest

from orchestrator.services import register_facts as rf
from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import document_names, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 30)

#: The three declines this class of defect was found in, as they were asked live on 2026-09-30.
LIVE_2026_09_30 = [
    (
        "accessible_route_register.md",
        "Which boundary-to-door route is currently evidenced for ambulance crews, stretcher "
        "teams and responders on foot, including step-free constraints?",
        "step free",
    ),
    (
        "asset_engineering_register.md",
        "Which assets should receive survey, maintenance, refurbishment or replacement funding "
        "first when criticality, condition, risk and whole-life cost are combined?",
        "criticality",
    ),
    (
        "room_bookings.md",
        "Which room and time categories show repeated no-shows strongly enough to justify an "
        "owner-led review of release rules?",
        "expected attendees",
    ),
]


@pytest.mark.parametrize("document, question, must_name", LIVE_2026_09_30)
def test_the_decline_names_the_field_the_question_reached(document, question, must_name):
    """A field the question names and the register HOLDS may not be left out of the sentence."""
    rows, label = lifted_rows(document)
    text = rp.out_of_scope_decline(rows, question, label, TODAY)
    assert text, question
    held, _ = text.split(", and nothing about ", 1)
    assert must_name in held, f"{must_name!r} missing from: {held}"


@pytest.mark.parametrize("document, question, _must", LIVE_2026_09_30)
def test_the_field_the_question_reached_is_not_also_called_unrecorded(document, question, _must):
    """The two halves of the sentence are decided by one matcher, so they cannot disagree."""
    rows, label = lifted_rows(document)
    text = rp.out_of_scope_decline(rows, question, label, TODAY)
    held, beyond = text.split(", and nothing about ", 1)
    named = {n.strip() for n in held.split("it records", 1)[1].replace(" and ", ", ").split(",")}
    for word in beyond.rstrip(".").replace(" and ", ", ").split(","):
        assert word.strip() not in named, f"{word!r} is both recorded and 'nothing about'"


@pytest.mark.parametrize("document", document_names())
def test_no_named_field_is_absent_from_the_rows(document):
    """Over-claiming must be impossible: every field named is a column the rows carry."""
    rows, label = lifted_rows(document)
    if not rows:
        pytest.skip(f"{document} lifts no rows")
    content = rf._content_columns(rows, rp._all_columns(rows))
    real = {rp._label(c) for c in content}
    res = rp.resolve(rows, "which of these are unusual, disputed and provisional", label, TODAY)
    named, _extra = rp._what_it_records(rows, res)
    assert named, document
    assert not [n for n in named if n not in real], f"{document}: invented {named} vs {real}"


@pytest.mark.parametrize("document", document_names())
def test_nothing_the_register_records_is_silently_omitted(document):
    """Named + disclosed count == every content column. The cap may shorten, never hide."""
    rows, label = lifted_rows(document)
    if not rows:
        pytest.skip(f"{document} lifts no rows")
    content = rf._content_columns(rows, rp._all_columns(rows))
    expected = len({rp._label(c) for c in content})
    res = rp.resolve(rows, "which of these are unusual, disputed and provisional", label, TODAY)
    named, extra = rp._what_it_records(rows, res)
    assert len(named) + extra == expected, document
    assert len(named) <= 8, f"{document}: {len(named)} fields is not one readable sentence"


@pytest.mark.parametrize("document", document_names())
def test_the_sentence_is_still_one_line(document):
    """A decline is one sentence; the wider field list must not turn it into a listing."""
    rows, label = lifted_rows(document)
    if not rows:
        pytest.skip(f"{document} lifts no rows")
    text = rp.out_of_scope_decline(
        rows, "which of these are unusual, disputed and provisional", label, TODAY
    )
    if not text:
        pytest.skip(f"{document} does not decline this question")
    assert "\n" not in text
    assert "cannot answer this: it records " in text
    assert text.endswith(".")


def test_the_disclosed_remainder_is_worded_for_a_reader():
    """ "plus N more fields" — a count the reader can act on, never a silent truncation."""
    rows, label = lifted_rows("asset_engineering_register.md")
    text = rp.out_of_scope_decline(
        rows,
        "Which assets should receive survey, maintenance, refurbishment or replacement funding "
        "first when criticality, condition, risk and whole-life cost are combined?",
        label,
        TODAY,
    )
    assert "plus 14 more fields" in text, text


def test_no_decline_ever_says_plus_zero_more_fields():
    """A register of eight fields or fewer must carry no remainder clause at all."""
    seen_short = 0
    for document in document_names():
        rows, label = lifted_rows(document)
        if not rows:
            continue
        text = rp.out_of_scope_decline(
            rows, "which of these are unusual, disputed and provisional", label, TODAY
        )
        if not text:
            continue
        assert "plus 0 more" not in text, document
        assert "plus 1 more fields" not in text, document
        content = rf._content_columns(rows, rp._all_columns(rows))
        if len({rp._label(c) for c in content}) <= 8:
            seen_short += 1
            assert "plus " not in text, f"{document}: {text}"
    assert seen_short >= 5, "the short-register branch was never exercised"
