# -*- coding: utf-8 -*-
"""BUG-1445: a narrated value for one record checked against a DIFFERENT record is dropped.

A live answer stated "WS-14 has no natural daylight" / "No daylight (internal)". WS-14's own
``daylightAspect`` cell reads "North-facing"; "Internal, no daylight" belongs to WS-04 and
WS-05. Nothing before this compared a narrated cell against the record it was attributed to —
the register lane hands the model its rows to read, and reads the model's own prose back only
to check for a DENIED field (``guard_narration``'s existing concept-denial path) or a
"nothing matches" contradiction, never a value that is simply attributed to the wrong row.

There is no live LLM in this worktree, so the "model narrated X" step is a literal string
built to the live defect's exact shape (and verified against the register's own rows, not
against anything the code under test produces) — the grounding check itself
(``register_projection.drop_misattributed_cells``) is what is under test, called directly.
"""

from __future__ import annotations

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import lifted_rows

pytestmark = pytest.mark.unit

DOCUMENT = "workspace_profile_register.md"


def _rows():
    rows, _label = lifted_rows(DOCUMENT)
    return rows


def _cell(rows, record_id: str, column: str) -> str:
    row = next(r for r in rows if r.get("recordId", {}).get("value") == record_id)
    return row.get(column, {}).get("value", "")


def test_the_register_rows_confirm_the_live_defects_premise():
    """WS-14 is North-facing; the no-daylight rows are WS-04 and WS-05 -- ground truth, read
    straight from the document, independent of anything guard_narration computes."""
    rows = _rows()
    assert _cell(rows, "WS-14", "daylightAspect") == "North-facing"
    assert _cell(rows, "WS-04", "daylightAspect") == "Internal, no daylight"
    assert _cell(rows, "WS-05", "daylightAspect") == "Internal, no daylight"


def test_a_cell_attributed_to_the_wrong_record_is_dropped():
    """The live shape: a record named once, and a DIFFERENT record's cell stated for it."""
    rows = _rows()
    narration = (
        "**Level 3 computer labs**\n\n"
        "WS-13 is North-facing with an adequate network rating.\n\n"
        "WS-14 has a weak network rating. No daylight (internal).\n\n"
        "WS-04 is an internal lab -- Internal, no daylight -- the only lab with no daylight."
    )
    out = rp.drop_misattributed_cells(narration, rows)
    # WS-14's own, correct fact (weak network) survives -- only the misattributed
    # daylight clause is removed, not the whole chunk naming it.
    assert "WS-14 has a weak network rating." in out
    assert "No daylight (internal)" not in out
    # WS-04's identical words are left alone: they are true of WS-04, not borrowed.
    assert "Internal, no daylight" in out
    assert "WS-13 is North-facing with an adequate network rating." in out


def test_the_grounding_check_catches_the_exact_live_wording():
    """The live answer's own sentence, verbatim, naming WS-14 and WS-04/05's cell."""
    rows = _rows()
    narration = "WS-14: No daylight (internal). Surveyed wireless is weak at the far end."
    out = rp.drop_misattributed_cells(narration, rows)
    assert "No daylight (internal)" not in out
    assert "Surveyed wireless is weak at the far end." in out


def test_a_record_correctly_narrating_its_own_value_is_left_alone():
    rows = _rows()
    narration = "WS-14 is North-facing with a weak network rating; wired sockets are reliable."
    out = rp.drop_misattributed_cells(narration, rows)
    assert out == narration


def test_a_record_narrating_a_value_no_other_record_holds_is_left_alone():
    """A made-up value matches nothing in ANY row, so there is no "wrong row" to point at --
    the check must not invent one."""
    rows = _rows()
    narration = "WS-14 has excellent daylight from a skylight."
    out = rp.drop_misattributed_cells(narration, rows)
    assert out == narration


def test_two_records_named_in_the_same_chunk_is_left_alone():
    """Ambiguous: the check only acts when exactly one record is named in the chunk, by its
    own id -- never by guessing which one a value was "closer to" in the text."""
    rows = _rows()
    narration = "Unlike WS-04, which has no daylight, WS-14 is bright and North-facing."
    out = rp.drop_misattributed_cells(narration, rows)
    assert out == narration


def test_a_single_row_register_has_nothing_to_misattribute():
    out = rp.drop_misattributed_cells("WS-14 has no natural daylight.", [_rows()[0]])
    assert out == "WS-14 has no natural daylight."


def test_empty_narration_or_rows_is_left_alone():
    assert rp.drop_misattributed_cells("", _rows()) == ""
    assert rp.drop_misattributed_cells("WS-14 is North-facing.", []) == "WS-14 is North-facing."


def test_guard_narration_applies_the_grounding_check_end_to_end():
    """The check also runs inside guard_narration, the real call site (sparql_agent)."""
    rows = _rows()
    narration = "WS-14: No daylight (internal)."
    out = rp.guard_narration(narration, rows, "Does WS-14 have daylight?", "Workspace profile")
    assert "No daylight (internal)" not in out
