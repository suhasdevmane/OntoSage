# -*- coding: utf-8 -*-
"""Wave 2 (2D-06), the scripted demo regression: "with A, B and C" is an intersection, and code computes it.

Live, after wave 1: "Where can I work for three hours with power, good Wi-Fi and a low risk of noise?"
answered "The records do not contain any workspace that simultaneously offers power at every seat
(or at some seats), good Wi-Fi (strong or adequate), and a low-noise environment (quiet or silent)
... None of these workspaces combine all three desired attributes", directly ABOVE a table in
which most rows plainly do. Before wave 1 the same question listed the 25 that do.

The narration was left to decide an intersection of three conditions over 28 rows, which is
exactly the operation it is worst at. So the conditions are matched to columns and to the
recorded values that satisfy them (config/register_vocabulary.yaml ``criteria``), the rows are
filtered in code, and the answer is written from the computed set. This walks the REAL workspace
register and checks the count the answer states against the table read a second way.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import ground_truth, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)
DEMO = "Where can I work for three hours with power, good Wi-Fi and a low risk of noise?"
DOC = "workspace_profile_register.md"
LABEL = "Workspace profile"


def _truth(
    power=("at every seat", "at some seats"),
    network=("strong", "adequate"),
    noise=("quiet", "silent"),
):
    return [
        r
        for r in ground_truth(DOC)
        if r["power"] in power and r["network"] in network and r["noise"] in noise
    ]


def _answer(question: str) -> str:
    rows, _label = lifted_rows(DOC)
    return rp.deterministic_answer(rows, question, LABEL, TODAY)


def test_the_demo_question_is_answered_deterministically_with_the_table_count():
    text = _answer(DEMO)
    expected = _truth()
    assert len(expected) == 25
    assert text.splitlines()[0].startswith(f"**{len(expected)} of the 28 records")
    listed = sorted(set(re.findall(r"\bWS-\d+\b", text)))
    assert listed == sorted(r["_id"] for r in expected)


def test_the_answer_states_the_three_conditions_it_computed():
    first = _answer(DEMO).splitlines()[0]
    assert "power access: at every seat or at some seats" in first
    assert "network rating: adequate or strong" in first
    assert "noise profile: quiet or silent" in first


def test_each_row_prints_the_three_values_the_table_holds_for_it():
    text = _answer(DEMO)
    for row in _truth():
        line = next(l for l in text.splitlines() if re.search(rf"\b{row['_id']}\b", l))
        assert f"power access: {row['power']}" in line
        assert f"network rating: {row['network']}" in line
        assert f"noise profile: {row['noise']}" in line


def test_quiet_is_not_narrowed_to_silent_only_and_silent_is_not_dropped():
    """'quiet' stands for quiet OR silent. WS-27 and WS-28 are silent; both must be there, and so
    must the 22 rooms recorded as plain quiet."""
    text = _answer(DEMO)
    ids = set(re.findall(r"\bWS-\d+\b", text))
    assert {"WS-27", "WS-28"} <= ids
    quiet = {r["_id"] for r in _truth() if r["noise"] == "quiet"}
    assert quiet <= ids and len(quiet) == 23


def test_the_conditions_exclude_exactly_the_records_that_fail_one_of_them():
    ids = set(re.findall(r"\bWS-\d+\b", _answer(DEMO)))
    truth = {r["_id"]: r for r in ground_truth(DOC)}
    for ident, row in truth.items():
        meets = (
            row["power"] in ("at every seat", "at some seats")
            and row["network"] in ("strong", "adequate")
            and row["noise"] in ("quiet", "silent")
        )
        assert (ident in ids) == meets, (ident, row["power"], row["network"], row["noise"])
    # the ones a reader would wrongly expect: WS-14 has weak Wi-Fi, WS-01 and WS-19 are not quiet
    assert not {"WS-14", "WS-01", "WS-19"} & ids


def test_the_rows_are_grouped_by_floor_and_the_group_counts_add_up():
    text = _answer(DEMO)
    heads = re.findall(r"^\*\*Floor (\d+)\*\* — (\d+):", text, re.MULTILINE)
    assert heads, text
    total = 0
    for floor, count in heads:
        expected = [r for r in _truth() if r["floor"] == floor]
        assert int(count) == len(expected), (floor, count, len(expected))
        total += int(count)
    assert total == len(_truth())


def test_the_length_of_the_session_is_said_to_be_unfiltered_not_silently_dropped():
    text = _answer(DEMO)
    assert "no session length" in text and "for three hours" in text.lower()


@pytest.mark.parametrize(
    "question, kwargs",
    [
        (
            "Which rooms have good Wi-Fi and are quiet?",
            dict(power=("at every seat", "at some seats", "perimeter only")),
        ),
        (
            "Which spaces have power and a low risk of noise?",
            dict(network=("strong", "adequate", "weak")),
        ),
        ("Which workspaces have power, good Wi-Fi and are quiet?", {}),
    ],
)
def test_any_combination_of_the_conditions_states_the_count_the_table_gives(question, kwargs):
    expected = _truth(**kwargs)
    text = _answer(question)
    assert text.splitlines()[0].startswith(f"**{len(expected)} of the 28 records"), text[:200]
    assert sorted(set(re.findall(r"\bWS-\d+\b", text))) == sorted(r["_id"] for r in expected)


def test_an_empty_intersection_is_said_from_the_computed_set():
    rows, _label = lifted_rows(DOC)
    for row in rows:  # no space has weak Wi-Fi AND is silent: make every quiet room weak-linked
        if row["noiseProfile"]["value"] in ("quiet", "silent"):
            row["networkRating"]["value"] = "weak"
    text = rp.deterministic_answer(rows, DEMO, LABEL, TODAY)
    assert text.startswith("**None of the 28 records in the Workspace profile register match**")
    assert "WS-" not in text.split("\n")[0]


def test_a_condition_the_register_cannot_check_is_not_pretended():
    """Work orders record no Wi-Fi rating: the question is not composed from a column that is
    not there, and 'Wi-Fi' is not silently dropped."""
    rows, label = lifted_rows("maintenance_log.md")
    assert rp.deterministic_answer(rows, "Which work orders have good Wi-Fi?", label, TODAY) == ""


def test_a_question_that_really_is_about_the_reader_is_still_refused():
    for question in (
        "Which spaces are available to me with power and good Wi-Fi?",
        "Can I use a quiet room with good Wi-Fi?",
        "Which of my bookings have power and good Wi-Fi?",
    ):
        assert _answer(question) == "", question


# ── the narration must not be allowed to override a computed answer ─────────────────────────────

LIVE_DENIAL = (
    "The records do not contain any workspace that simultaneously offers power at every seat "
    "(or at some seats), good Wi-Fi (strong or adequate), and a low-noise environment (quiet or "
    "silent).\n\nHere is what the register does record:\n\n| Workspace | Power | Wi-Fi | Noise |\n"
    "|---|---|---|---|\n| WS-02 | at every seat | strong | quiet |\n\n"
    "None of these workspaces combine all three desired attributes in a single record."
)


def test_a_narration_that_says_nothing_matches_is_replaced_by_the_computed_answer():
    rows, _label = lifted_rows(DOC)
    out = rp.guard_narration(LIVE_DENIAL, rows, DEMO, LABEL, TODAY)
    assert "do not contain any workspace" not in out
    assert out.startswith("**25 of the 28 records")


def test_a_narration_that_lists_the_workspaces_is_left_alone():
    rows, _label = lifted_rows(DOC)
    good = "You can work in any of the 25 spaces that have power, strong or adequate Wi-Fi and a quiet or silent noise level: WS-02, WS-03 and the rest."
    assert rp.guard_narration(good, rows, DEMO, LABEL, TODAY) == good


def test_a_denial_about_something_else_is_not_mistaken_for_a_contradiction():
    rows, _label = lifted_rows(DOC)
    narration = (
        "WS-02 has power at every seat, strong Wi-Fi and a quiet noise level.\n\n"
        "The register does not contain any information about carbon emissions."
    )
    out = rp.guard_narration(narration, rows, DEMO, LABEL, TODAY)
    assert out.startswith(narration)
