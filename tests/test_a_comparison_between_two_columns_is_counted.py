"""A comparison the question asks for is counted in code (BUG-624).

"On which floor pairs is the step-free route slower than the stair route?" was answered "15 of
21 records" — true of the rows and false of the question: six of those fifteen are same-floor
routes, which have no stair route to be slower than. The same register answered "nine" the day
before, from the same 21 rows. An arithmetic question settled by whichever way the narration
read it is not settled at all.
"""

import pytest

from orchestrator.services.register_facts import (
    _comparison_lines,
    _endpoint_columns,
    register_facts,
)

pytestmark = pytest.mark.unit

_COLUMNS = [
    "recordId",
    "label",
    "fromFloor",
    "toFloor",
    "walkingMinutes",
    "stepFreeMinutes",
    "recordStatus",
]


def _row(rid, frm, to, walk, step):
    return {
        "recordId": {"value": rid},
        "label": {"value": f"{frm} to {to}"},
        "fromFloor": {"value": frm},
        "toFloor": {"value": to},
        "walkingMinutes": {"value": str(walk)},
        "stepFreeMinutes": {"value": str(step)},
        "recordStatus": {"value": "active"},
    }


# Three genuine floor pairs where step-free is slower, one where it is not, and two same-floor
# routes that also carry a larger step-free figure — the rows that produced the wrong 15.
_ROWS = [
    _row("CIR-001", "Level 0", "Level 1", 2.0, 3.5),
    _row("CIR-002", "Level 1", "Level 2", 2.2, 3.8),
    _row("CIR-003", "Level 2", "Level 3", 2.4, 4.0),
    _row("CIR-004", "Level 3", "Level 4", 3.0, 2.5),
    _row("CIR-005", "Level 0", "Level 0", 2.0, 2.5),
    _row("CIR-006", "Level 1", "Level 1", 1.5, 2.0),
]

_QUESTION = "On which floor pairs is the step-free route slower than the stair route?"


def test_the_same_floor_rows_are_not_counted_as_pairs():
    lines = "\n".join(_comparison_lines(_ROWS, _COLUMNS, _QUESTION))
    assert "on 3 of the 4 records" in lines, lines


def test_the_excluded_rows_are_reported_not_hidden():
    """Six rows vanishing without explanation is how a count becomes unauditable."""
    lines = "\n".join(_comparison_lines(_ROWS, _COLUMNS, _QUESTION))
    assert "2 further records have the same fromFloor and toFloor" in lines
    assert "EXCLUDED" in lines


def test_the_matching_records_are_named():
    lines = "\n".join(_comparison_lines(_ROWS, _COLUMNS, _QUESTION))
    for rid in ("CIR-001", "CIR-002", "CIR-003"):
        assert rid in lines
    assert "CIR-004" not in lines  # step-free is faster here


def test_the_comparative_says_which_way_round():
    faster = "On which floor pairs is the step-free route faster than the stair route?"
    lines = "\n".join(_comparison_lines(_ROWS, _COLUMNS, faster))
    assert "less than" in lines
    assert "on 1 of the 4 records" in lines, lines
    assert "CIR-004" in lines


def test_a_question_with_no_comparative_counts_nothing():
    assert _comparison_lines(_ROWS, _COLUMNS, "Which floor pairs are recorded?") == []


def test_endpoints_are_found_by_their_values_not_their_names():
    """A register that calls them origin/destination has the same pair of endpoints."""
    renamed_columns = [c.replace("fromFloor", "origin").replace("toFloor", "arrivesAt") for c in _COLUMNS]
    renamed = [
        {
            ("origin" if k == "fromFloor" else "arrivesAt" if k == "toFloor" else k): v
            for k, v in row.items()
        }
        for row in _ROWS
    ]
    assert _endpoint_columns(renamed, renamed_columns) == ("arrivesAt", "origin")


def test_nothing_is_counted_when_the_question_names_neither_column():
    """Guessing which two numbers a comparative meant is worse than saying nothing."""
    assert _comparison_lines(_ROWS, _COLUMNS, "Which route is slower than the others?") == []


def test_the_fact_reaches_the_block_the_narration_is_given():
    block = register_facts(_ROWS, _QUESTION)
    assert "stepFreeMinutes is greater than walkingMinutes" in block
    assert "Records held: 6" in block


def _numeric_floor_rows():
    """The register's REAL shape: floors recorded as bare numbers, not as "Level 3".

    The first version of the endpoint finder excluded any column holding numbers, on the
    assumption that a place is spelled with letters. It passed every test above and found
    nothing whatever in the building's only register with endpoints.
    """
    return [
        {
            "recordId": {"value": rid},
            "label": {"value": f"{frm} to {to}"},
            "fromFloor": {"value": frm},
            "toFloor": {"value": to},
            "walkingMinutes": {"value": str(walk)},
            "stepFreeMinutes": {"value": str(step)},
            "recordStatus": {"value": "active"},
            "record": {"value": f"circ/{rid}"},
            "recordVersion": {"value": "2026.9"},
        }
        for rid, frm, to, walk, step in [
            ("CIR-001", "0", "1", 2.0, 3.5),
            ("CIR-002", "1", "2", 2.2, 3.8),
            ("CIR-003", "2", "3", 2.4, 4.0),
            ("CIR-004", "3", "4", 3.0, 2.5),
            ("CIR-005", "0", "0", 2.0, 2.5),
            ("CIR-006", "1", "1", 1.5, 2.0),
        ]
    ]


def test_a_floor_recorded_as_a_number_is_still_a_place():
    rows = _numeric_floor_rows()
    columns = sorted({k for r in rows for k in r})
    assert _endpoint_columns(rows, columns) == ("fromFloor", "toFloor")


def test_the_real_register_shape_is_counted():
    rows = _numeric_floor_rows()
    columns = sorted({k for r in rows for k in r})
    lines = "\n".join(_comparison_lines(rows, columns, _QUESTION))
    assert "on 3 of the 4 records" in lines, lines
    assert "2 further records have the same fromFloor and toFloor" in lines


def test_the_endpoint_columns_are_not_mistaken_for_the_measurements():
    """Four numeric columns, two of which are floors: counting the floors as measurements
    makes the pair ambiguous and the whole fact disappear, silently."""
    rows = _numeric_floor_rows()
    columns = sorted({k for r in rows for k in r})
    assert _comparison_lines(rows, columns, _QUESTION) != []
